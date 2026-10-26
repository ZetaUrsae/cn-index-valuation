# -*- coding: utf-8 -*-
"""ivdata.pipeline —— 把各数据域的取数结果，落成旧管线的历史库格式。

设计约束
--------
下游 ``process.py / tech.py / prep.py / proc2.py / gen2.py`` **一行都不改**，
因此本模块的唯一职责是：把新数据源的返回值，转成与旧文件**字段名、单位、
目录结构完全一致**的产物。

产物对照
--------
=============== ========================== ==========================
产物文件         结构                        由哪些域拼装
=============== ========================== ==========================
data/raw.json   {code: {name, basic, daily}}  quote + valuation
data/pcr_raw.csv 逐日×标的的行               option_pcr
data/etf_raw.json {shares, fdaily, main}     etf_share + etf_quote
=============== ========================== ==========================

单位换算（踩过的坑，必须记住）
------------------------------
* 新浪 K 线 ``volume`` 单位是**股**，Tushare ``vol`` 是**手**（1 手 = 100 股），
  写库前除以 100，否则量比会差 100 倍。
* 新浪没有成交额，``amount`` 只能留空 → 用「收盘价 × 成交量」估算，
  仅 ETF 表用到（proc2.py 只取末值展示），不影响任何比值类指标。
* 东财返回的市值单位是**元**，Tushare ``total_mv`` 是**万元**，除以 1e4。
"""
from __future__ import annotations

import datetime
import json
import os
from typing import Any, Dict, List, Optional

from . import http
from .config import (CODE2NAME, DATA, ETF_ALL, ETF_LIST, INDEX_CODES, OPT_ETF,
                     OPT_EXCH, OPT_MAIN, OVERLAP_BY_DOMAIN, OVERLAP_FORCED,
                     SETTINGS, WORK)
from .contracts import ProviderError
from .provenance import Provenance
from .registry import Registry
from .store import CsvStore, Store

# ---------------------------------------------------------------- 工具

def _d(s: str) -> datetime.date:
    return datetime.datetime.strptime(s, "%Y%m%d").date()


def _shift(ymd: str, days: int = 0, months: int = 0, years: int = 0) -> str:
    """日期加减，返回 YYYYMMDD。"""
    d = _d(ymd)
    if years:
        d = d.replace(year=d.year + years)
    if months:
        y, m = d.year, d.month + months
        y += (m - 1) // 12
        m = (m - 1) % 12 + 1
        day = min(d.day, [31, 29 if y % 4 == 0 and (y % 100 != 0 or y % 400 == 0) else 28,
                          31, 30, 31, 30, 31, 31, 30, 31, 30, 31][m - 1])
        d = d.replace(year=y, month=m, day=day)
    if days:
        d = d + datetime.timedelta(days=days)
    return d.strftime("%Y%m%d")


def load_json(path: str) -> Any:
    if not os.path.exists(path):
        return None
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _nan_to_none(o):
    """递归把 NaN / inf 换成 None，保证输出是合法 JSON。"""
    if isinstance(o, float):
        if o != o or o in (float("inf"), float("-inf")):
            return None
        return o
    if isinstance(o, dict):
        return {k: _nan_to_none(v) for k, v in o.items()}
    if isinstance(o, list):
        return [_nan_to_none(v) for v in o]
    return o


# ---------------------------------------------------------------- 主类

class Pipeline:
    """一次运行的完整取数 + 落库流程。

    用法::

        p = Pipeline()
        p.resolve_asof()          # 确定参考交易日
        p.sync_quotes()           # 指数行情
        p.sync_valuations()       # 指数估值
        p.sync_pcr()              # 期权 PCR
        p.sync_etfs()             # ETF 份额 + 行情
        p.finish()                # 写 provenance
    """

    def __init__(self, asof: str = ""):
        self.r = Registry.get()
        self.asof = asof or SETTINGS.asof
        self.today = datetime.date.today().strftime("%Y%m%d")
        self.log: List[str] = []

    # -------------------------------------------------- 生命周期
    def resolve_asof(self) -> str:
        """确定参考交易日：优先 ASOF 环境变量，否则用日历的最后一个交易日。"""
        if self.asof:
            return self.asof
        try:
            cal = self.r.fetch("calendar", _shift(self.today, days=-40), self.today)
            days = [c["cal_date"] if isinstance(c, dict) else c for c in cal]
            days = [d for d in days if d <= self.today]
            if days:
                self.asof = max(days)
        except ProviderError:
            pass
        if not self.asof:
            self.asof = SETTINGS.resolve_asof()
        return self.asof

    def finish(self, name: str = "work/provenance.json") -> str:
        path = os.path.join(os.path.dirname(DATA), name)
        self.r.prov.save(path)
        return path

    def _say(self, msg: str) -> None:
        self.log.append(msg)
        print(msg, flush=True)

    def _ov(self, domain: str) -> int:
        """该域的尾部回看天数（自然日）。

        原则：**只取增量，不重拉历史**。每域都从库内最后一天起算，往前只退
        ``_ov()`` 天（默认 1 天），用于修正当日盘中值 / 未定稿值；再往前的
        日期一律不再请求——2015 起的历史已在库里，直接复用。

        排障时可用 ``IV_OVERLAP=N`` 把全局窗口放大（例如想重算最近一个月）。
        """
        if OVERLAP_FORCED is not None:
            return int(OVERLAP_FORCED)
        return OVERLAP_BY_DOMAIN.get(domain, 1)

    def _stamp(self, domain: str, asof: str) -> None:
        """记录各域的数据截止日。

        ⚠ 绝不能写进 raw.json 顶层：``process.py`` 是
        ``for code, d in raw.items(): name = d["name"]``，
        任何非指数键（如 ``_meta``）都会让日报直接 KeyError 崩掉。
        因此元信息单独落在 work/watermarks.json。
        """
        path = os.path.join(WORK, "watermarks.json")
        blob = load_json(path) or {}
        blob[domain] = {"asof": asof,
                        "updated": datetime.datetime.now().isoformat(timespec="seconds")}
        _write_json(path, blob)

    # -------------------------------------------------- 指数行情
    def sync_quotes(self, store: Optional[Store] = None) -> int:
        """指数日线 → data/raw.json 的 daily 段落。"""
        raw = load_json(os.path.join(DATA, "raw.json")) or {}
        total = 0
        for code in INDEX_CODES:
            old = raw.get(code, {}).get("daily") or []
            last = old[-1]["trade_date"] if old else _shift(self.asof, years=-5)
            start = max(_shift(last, days=-self._ov("quote")), "20191201")
            if start > self.asof:
                self._say(f"  [quote] {code} 已是最新 ({last})")
                continue
            try:
                rows = self.r.fetch("quote", code, start, self.asof)
            except ProviderError as e:
                self._say(f"  [quote] {code} 失败: {str(e)[:120]}")
                continue
            rows = [_norm_quote(r) for r in rows]
            merged = _merge_by_date(old, rows)
            raw.setdefault(code, {})["daily"] = merged
            total += len(rows)
            self._say(f"  [quote] {code} {CODE2NAME.get(code, '')} +{len(rows)} → {len(merged)} 行")
        _write_json(os.path.join(DATA, "raw.json"), raw)
        self._stamp("quote", self.asof)
        return total

    # -------------------------------------------------- 指数估值
    def sync_valuations(self) -> int:
        """指数估值 → data/raw.json 的 basic 段落。

        **写库策略（方案 C）**
        --------------------
        1. Tushare 已有历史（2015 起）视为权威，**不回改**；
        2. 东财只补 ``tushare_last_date`` 之后的增量（每周 Tushare 补一次会前移这条线）；
        3. 若某天东财已写、随后 Tushare 补到同一天，以 Tushare 覆盖（口径统一到官方）。
        """
        raw = load_json(os.path.join(DATA, "raw.json")) or {}
        total = 0
        for code in INDEX_CODES:
            blk = raw.setdefault(code, {})
            blk["name"] = CODE2NAME.get(code, code)
            old = blk.get("basic") or []
            last = old[-1]["trade_date"] if old else "20180102"
            start = max(_shift(last, days=-self._ov("valuation")), "20180102")
            if start > self.asof:
                self._say(f"  [valuation] {code} 已是最新 ({last})")
                continue
            try:
                rows = self.r.fetch("valuation", code, start, self.asof)
            except ProviderError as e:
                self._say(f"  [valuation] {code} 失败: {str(e)[:120]}")
                continue
            rows = [_norm_valuation(r) for r in rows]
            merged = _merge_by_date(old, rows)
            blk["basic"] = merged
            total += len(rows)
            self._say(f"  [valuation] {code} {CODE2NAME.get(code, '')} "
                      f"+{len(rows)} → {len(merged)} 行 (末 {merged[-1]['trade_date']})")
        _write_json(os.path.join(DATA, "raw.json"), raw)
        self._stamp("valuation", self.asof)
        return total

    # -------------------------------------------------- 期权 PCR
    def sync_pcr(self) -> int:
        """期权 PCR → data/pcr_raw.csv（按 date+oc 增量 upsert）。"""
        store = CsvStore("pcr_raw.csv")
        last = store.last_date() or "20220901"
        # 窗口 = 上次库内最后一天的前 1 天 ~ asof。
        # 深交所限的是「短时间总请求数」而非 QPS，逐日一个请求，窗口越大发得越多：
        # 40 天窗口 = 每次运行 26 发（曾把配额吃光、连累 etf_share 被封 IP），
        # 5 天 = 3~4 发。日常运行库里永远只缺 1 天，所以理论上 1 发就够；
        # 保留 1 天重叠是为了「晚间 23 点前跑过一次、当日数据后来才有定稿值」的
        # 情形，次日重取最后一天能自动修正。代价是每天多 1 发，可忽略。
        start = max(_shift(last, days=-1), "20220901")
        if start > self.asof:
            self._say(f"  [pcr] 已是最新 ({last})")
            return 0
        try:
            rows = self.r.fetch("option_pcr", start, self.asof)
        except ProviderError as e:
            self._say(f"  [pcr] 失败: {str(e)[:200]}")
            return 0
        rows = [_norm_pcr(r) for r in rows]
        n = store.upsert(rows, key_fields=("date", "oc"))
        self._say(f"  [pcr] +{len(rows)} → {n} 行 (末 {max(r['date'] for r in rows)})")
        return n

    # -------------------------------------------------- ETF
    def sync_etfs(self) -> int:
        """ETF 份额 + 行情 → data/etf_raw.json。

        只维护 ``ETF_LIST``（报告主表的 5 只）。``ETF_ALL`` 里的 159919/159922/588080
        是期权标的映射的副产品，报告不用它们的份额曲线；把它们写进
        ``etf_raw.json`` 只会让历史库长出一批残缺序列（旧库里本就没有），
        反而在 ``proc2.py`` 按 code 取数时埋坑。需要时用 ``--with-extra-etf`` 显式开启。
        """
        blob = load_json(os.path.join(DATA, "etf_raw.json")) or {}
        shares = blob.get("shares") or {}
        fdaily = blob.get("fdaily") or {}
        main = blob.get("main") or dict(OPT_MAIN)
        total = 0

        for code in ETF_LIST:
            # ---- 份额 ----
            old_s = shares.get(code) or []
            last = old_s[-1]["trade_date"] if old_s else _shift(self.asof, years=-2)
            start = max(_shift(last, days=-self._ov("etf_share")),
                        _shift(self.asof, years=-3))
            if start <= self.asof:
                try:
                    used = ""
                    srows = self.r.fetch("etf_share", code, start, self.asof)
                    used = self.r.decisions.get("etf_share", "")
                    srows = [_norm_share(code, r) for r in srows]
                    prov = self.r.providers.get(used)
                    if getattr(prov, "snapshot_only", False) and _stale_snapshot(old_s, srows):
                        # 快照源没刷新（典型：深交所尚未切到 ASOF 日），换下一个源
                        self._say(f"  [etf_share] {code} 的 {used} 疑似未刷新，换源重取")
                        srows = self.r.fetch("etf_share", code, start, self.asof,
                                             _skip={used})
                        used = self.r.decisions.get("etf_share", used)
                        srows = [_norm_share(code, r) for r in srows]
                    shares[code] = _merge_by_date(old_s, srows)
                    total += len(srows)
                    self._say(f"  [etf_share] {code} +{len(srows)} → {len(shares[code])} 行"
                              f"（{self.r.decisions.get('etf_share', used)}）")
                    # 漏日回补：只有深市需要（沪市给的是完整区间，不会留洞），
                    # 且只在库里确实有缺口时才发请求，正常每日运行时成本为 0。
                    if used != "szse_etf_share_range":
                        gaps = self._fill_share_gaps(code, shares[code], start)
                        if gaps:
                            shares[code] = _merge_by_date(shares[code], gaps)
                            total += len(gaps)
                            self._say(f"  [etf_share] {code} 缺口回补 +{len(gaps)} 日"
                                      f"（szse_etf_share_range）")
                except ProviderError as e:
                    self._say(f"  [etf_share] {code} 失败: {str(e)[:110]}")

            # ---- 行情 ----
            old_q = fdaily.get(code) or []
            last_q = old_q[-1]["trade_date"] if old_q else _shift(self.asof, years=-2)
            start_q = max(_shift(last_q, days=-self._ov("etf_quote")),
                          _shift(self.asof, years=-3))
            if start_q <= self.asof:
                try:
                    qrows = self.r.fetch("etf_quote", code, start_q, self.asof)
                    qrows = [_norm_etf_quote(code, r) for r in qrows]
                    fdaily[code] = _merge_by_date(old_q, qrows)
                    total += len(qrows)
                    self._say(f"  [etf_quote] {code} +{len(qrows)} → {len(fdaily[code])} 行")
                except ProviderError as e:
                    self._say(f"  [etf_quote] {code} 失败: {str(e)[:110]}")

        _write_json(os.path.join(DATA, "etf_raw.json"),
                    {"shares": shares, "fdaily": fdaily, "main": main})
        return total

    def _fill_share_gaps(self, code: str, series: List[Dict[str, Any]],
                         start: str) -> List[Dict[str, Any]]:
        """ETF 份额漏日回补（沪深两市通用）。

        背景：两市的日常源都是「当日快照」——某天没跑成（关机 / 断网 / 被限流），
        那一天就永久缺着，而报告「资金面」的 5/20/60 日变化对缺口敏感。

        - 深市：走深交所「基金规模」区间报表，一次可查 6 个月；
        - 沪市：上交所接口没有区间参数，按 ``STAT_DATE`` 逐日补（缺口通常 1~2 天）。

        只在「库里确实有洞」时才发请求：正常每天跑一次就没有缺口，成本为 0。
        回补只写缺失日期，已有日期一律以库内为准（标签日期一旦写错会污染整条序列）。
        """
        from .providers.exchange import _trading_days

        have = {str(r["trade_date"]) for r in series}
        try:
            days = _trading_days(start, self.asof)
        except Exception:                                  # noqa: BLE001
            return []
        missing = [d for d in days if d not in have]
        if not missing:
            return []

        if not code.endswith(".SZ"):
            # 沪市：逐日按 STAT_DATE 取（每次 2 页，按日缓存可命中）。当天份额
            # 不可能已定稿，一律留给明天；更早的缺口只补最近 10 天，避免长期停机
            # 后一口气发几十个请求。
            todo = [d for d in missing if d < self.today][-10:]
            if not todo:
                return []
            rows: List[Dict[str, Any]] = []
            for d in todo:
                try:
                    rows += self.r.fetch("etf_share", code, d, d,
                                         _skip={"szse_etf_share", "szse_etf_share_range"})
                except ProviderError:
                    continue
            want = set(missing)
            rows = [_norm_share(code, r) for r in rows]
            return [r for r in rows if str(r["trade_date"]) in want]

        # 限流保护：缺口超过 120 天（首次建库 / 长期停机）时只补最近 120 天。
        # 区间报表 20 行/页，120 天 ≈ 9 页已是单次可接受的上限；更早的缺口
        # 交给人工跑 sync_tushare.py，避免把深交所的请求配额一次打光。
        floor = _shift(self.asof, days=-120)
        truncated = [d for d in missing if d < floor]
        if truncated:
            self._say(f"  [etf_share] {code} 缺口 {len(missing)} 日，其中 "
                      f"{len(truncated)} 日早于 {floor}，本次只补最近 120 天"
                      f"（更早的请人工跑 sync_tushare.py）")
            missing = [d for d in missing if d >= floor]
            if not missing:
                return []

        try:
            # 起点回退 10 天：区间报表的标签日比官方日早一个交易日，缺口首日的
            # 标签在窗口之前；多取的行随后会被 want 集合过滤掉。
            rows = self.r.fetch("etf_share", code, _shift(missing[0], days=-10),
                                self.asof,
                                _skip={"exchange_etf_share", "szse_etf_share"})
        except ProviderError as e:
            # 回补失败不影响主流程：当日快照那行照样写进去了，缺口留到下次再补
            self._say(f"  [etf_share] {code} 缺口回补失败（{len(missing)} 日）："
                      f"{str(e)[:110]}")
            return []

        rows = [_norm_share(code, r) for r in rows]
        want = set(missing)
        rows = [r for r in rows if str(r["trade_date"]) in want]
        have2 = {r["trade_date"] for r in rows}
        still = [d for d in missing if d not in have2]
        if still:
            # 剩余缺口多半是最后 1~2 个交易日：份额还没定稿（T 晚间临时值、
            # T+1 早间为准），明天再跑自然会补上。
            self._say(f"  [etf_share] {code} 仍有 {len(still)} 日未补"
                      f"（{still[0]}~{still[-1]}，多为未定稿日）")
        return rows

    # -------------------------------------------------- 10Y 国债
    def sync_bond10y(self) -> int:
        """10Y 国债收益率 → data/yield10y_history.json（尾部增量）。

        ⚠ 文件格式必须是**扁平字典** ``{"YYYY-MM-DD": 收益率, ...}``，
        不能是 ``{"data": [...]}``：``gen2.py`` 里是
        ``_y10all.get(_ds)`` 直接按日期字符串取值，换成列表会让 ERP 序列
        整段变空（报告里的 ERP 折线会消失，正是 2026-10-20 踩过的坑）。
        """
        path = os.path.join(DATA, "yield10y_history.json")
        blob = load_json(path) or {}
        if isinstance(blob, list):                       # 极老的格式：行列表
            blob = {str(r["trade_date"]): r.get("y10") for r in blob if r.get("trade_date")}
        elif isinstance(blob, dict) and "data" in blob:  # 兜底兼容中间态
            blob = {str(r["trade_date"]): r.get("y10")
                    for r in blob["data"] if r.get("trade_date")}
        if not isinstance(blob, dict):
            blob = {}

        last_iso = max(blob) if blob else _shift(self.asof, years=-1)
        # _shift 只认 YYYYMMDD，而 blob 的键是 YYYY-MM-DD
        start = max(_shift(str(last_iso).replace("-", "")[:8], days=-self._ov("bond10y")),
                    _shift(self.asof, days=-400))
        if start > self.asof:
            self._say(f"  [bond10y] 已是最新 ({last_iso})")
            return len(blob)
        try:
            rows = self.r.fetch("bond10y", start, self.asof)
        except ProviderError as e:
            self._say(f"  [bond10y] 失败: {str(e)[:120]}")
            return len(blob)

        added = 0
        for r in rows:
            d = str(r["trade_date"])
            iso = "%s-%s-%s" % (d[:4], d[4:6], d[6:]) if len(d) == 8 and "-" not in d else d
            v = r.get("y10")
            if v is None:
                continue
            if iso not in blob:
                added += 1
            blob[iso] = round(float(v), 4)

        ordered = {k: blob[k] for k in sorted(blob)}
        _write_json(path, ordered)
        self._say(f"  [bond10y] +{added} → {len(ordered)} 条 (末 {max(ordered)})")
        return len(ordered)


# ---------------------------------------------------------------- 归一行

def _norm_quote(r: Dict[str, Any]) -> Dict[str, Any]:
    """统一成 Tushare index_daily 的字段与单位。"""
    close = r.get("close")
    vol = r.get("vol")
    # 新浪给的是「股」，Tushare 给「手」
    if vol is not None:
        vol = round(vol / 100.0, 2)
    amount = r.get("amount")
    if amount is None and close and vol:
        amount = round(close * vol * 100 / 1000.0, 4)   # 千元
    return {
        "trade_date": str(r["trade_date"]),
        "close": close,
        "open": r.get("open"),
        "high": r.get("high"),
        "low": r.get("low"),
        "pre_close": r.get("pre_close"),
        "change": r.get("change"),
        "pct_chg": r.get("pct_chg"),
        "vol": vol,
        "amount": amount,
    }


def _norm_etf_quote(code: str, r: Dict[str, Any]) -> Dict[str, Any]:
    """ETF 行情：字段与 fund_daily 对齐，vol 同样换成「手」。"""
    close = r.get("close")
    vol = r.get("vol")
    if vol is not None:
        vol = round(vol / 100.0, 2)
    amount = r.get("amount")
    if amount is None and close and vol:
        amount = round(close * vol * 100 / 1000.0, 4)   # 千元
    return {
        "ts_code": code,
        "trade_date": str(r["trade_date"]),
        "pre_close": r.get("pre_close"),
        "open": r.get("open"),
        "high": r.get("high"),
        "low": r.get("low"),
        "close": close,
        "change": r.get("change"),
        "pct_chg": r.get("pct_chg"),
        "vol": vol,
        "amount": amount,
    }


def _norm_valuation(r: Dict[str, Any]) -> Dict[str, Any]:
    """估值行补齐 index_dailybasic 的全部字段（缺失的留 None，下游能容忍）。"""
    return {
        "trade_date": str(r["trade_date"]),
        "total_mv": r.get("total_mv"),
        "float_mv": r.get("float_mv"),
        "total_share": r.get("total_share"),
        "float_share": r.get("float_share"),
        "free_share": r.get("free_share"),
        "turnover_rate": r.get("turnover_rate"),
        "turnover_rate_f": r.get("turnover_rate_f"),
        "pe": r.get("pe"),
        "pe_ttm": r.get("pe_ttm"),
        "pb": r.get("pb"),
    }


def _norm_pcr(r: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "date": str(r["date"]),
        "oc": r["oc"],
        "c_oi": _r(r.get("c_oi"), 2),
        "p_oi": _r(r.get("p_oi"), 2),
        "c_vol": _r(r.get("c_vol"), 2),
        "p_vol": _r(r.get("p_vol"), 2),
        "c_amt": r.get("c_amt"),
        "p_amt": r.get("p_amt"),
        "oi_pcr": _r(r.get("oi_pcr"), 6),
        "vol_pcr": _r(r.get("vol_pcr"), 6),
    }


def _norm_share(code: str, r: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "ts_code": code,
        "trade_date": str(r["trade_date"]),
        "fd_share": r.get("fd_share"),
        "fund_type": "ETF",
        "market": code.split(".")[-1],
    }


# ---------------------------------------------------------------- 合并

def _stale_snapshot(old: List[Dict[str, Any]],
                    new: List[Dict[str, Any]]) -> bool:
    """快照型数据源是不是「日期翻篇了、值却没刷新」。

    只对单行结果（深交所基金列表这类只用当日快照的源）生效。判据是
    **新日期前进了一天，但份额与库里最后一日完全相同**。

    为什么敢这么判：五只 ETF 近 900 个交易日里，份额与前一日一字不差的
    只占 0.2%（159915 是 2 天）。所以「没变」几乎必然是交易所还没更新，
    而不是当天真的没申赎。误判的代价只是多重取一次备选源，可以接受。
    """
    if not old or len(new) != 1:
        return False
    o = max(old, key=lambda r: str(r["trade_date"]))
    n = new[0]
    if str(n["trade_date"]) <= str(o["trade_date"]):
        return False
    return float(n["fd_share"]) == float(o["fd_share"])


def _merge_by_date(old: List[Dict[str, Any]],
                   new: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """按 trade_date 合并；新值覆盖旧值中的非空字段，其余保留。"""
    idx: Dict[str, Dict[str, Any]] = {str(r["trade_date"]): dict(r) for r in old}
    for r in new:
        d = str(r["trade_date"])
        if d in idx:
            for k, v in r.items():
                if v is not None:
                    idx[d][k] = v
        else:
            idx[d] = dict(r)
    return [idx[d] for d in sorted(idx)]


def _r(x, nd: int):
    try:
        return round(float(x), nd)
    except (TypeError, ValueError):
        return None


def _write_json(path: str, obj: Any) -> None:
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(_nan_to_none(obj), f, ensure_ascii=False, separators=(",", ":"))
    os.replace(tmp, path)
