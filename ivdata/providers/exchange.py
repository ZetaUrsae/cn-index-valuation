# -*- coding: utf-8 -*-
"""交易所官方公开接口 —— 期权 PCR / ETF 份额 / 交易日历。

三个接口全部来自沪深交易所官网页面的真实后端。之前一直找不到，是因为
目录名 / sqlId 猜错了（`ysp*` 系列是错的，深交所实际是 `option_jycchztj`）。

--------------------------------------------------------------------------
1) 上交所 · 期权每日统计（标的级，含双边持仓量）
   GET https://query.sse.com.cn/commonQuery.do
   ?sqlId=COMMON_SSE_ZQPZ_YSP_QQ_SJTJ_MRTJ_CX
   &isPagination=true&tradeDate=20261019
   &pageHelp.pageSize=10&pageHelp.pageNo=1
   &pageHelp.beginPage=1&pageHelp.cacheSize=1&pageHelp.endPage=1

   ⚠ tradeDate 必须是 YYYYMMDD；传 2026-10-19 会静默返回 0 行。
   返回每标的一行：
     SECURITY_CODE      标的代码 510050
     CALL_VOLUME        认购成交量
     PUT_VOLUME         认沽成交量
     LEAVES_CALL_QTY    未平仓认购（双边加总，与 Tushare 逐位一致）
     LEAVES_PUT_QTY     未平仓认沽
     CP_RATE            认沽/认购(%)
   月度统计把 sqlId 换成 COMMON_SSE_ZQPZ_YSP_QQ_SJTJ_YDTJ_CX，tradeDate 传 YYYYMM。

--------------------------------------------------------------------------
2) 深交所 · 交易持仓汇总统计
   GET https://www.szse.cn/api/report/ShowReport/data
   ?SHOWTYPE=JSON&CATALOGID=option_jycchztj&TABKEY=tab1
   &PAGENO=1&PAGESIZE=50&txtSearchDate=2026-10-19

   ⚠ 日期是 YYYY-MM-DD。不传则返回全部历史（4558 行 / 228 页 / 跨 195 个交易日）。
   ⚠ PAGESIZE 上限 500，超过被静默截断。
   返回字段：
     bdzqdm  标的代码+名称  创业板ETF易方达(159915)
     kzjysl  认购交易数量   ← 与 Tushare c_vol **逐位相等**
     kdjysl  认沽交易数量   ← 与 Tushare p_vol **逐位相等**
     kzccsl  认购持仓数量   ← 单边口径（对冲后），比 Tushare 低 7%~8%
     kdccsl  认沽持仓数量   ← 单边口径（对冲后），比 Tushare 低 12%~16%
   页脚原文：「认购（认沽）未平仓量按对冲后的权利仓（或义务仓）单边计算。」

   **口径处理（v2.5.0 起）**：深市持仓量**直接采用页面单边原值，不做任何换算**。
   这样报告里创业板指的持仓量 / PCR 与深交所官网逐位对得上，可人工复核。
   代价：与 2026-09-08 及更早的 Tushare 双边口径历史存在约 5%~8% 的台阶
   （PCR 分位的可比性见 docs/DATA_SOURCES.md「深市期权未平仓量」）。
   （v2.4.x 曾用固定系数乘回双边，属于自定口径、无官方依据，已废弃。）

--------------------------------------------------------------------------
3) 上交所 · ETF 份额
   GET https://query.sse.com.cn/commonQuery.do
   ?sqlId=COMMON_SSE_ZQPZ_ETFZL_XXPL_ETFGM_SEARCH_L
   &isPagination=true&pageHelp.pageSize=500&pageHelp.pageNo=1

   字段：STAT_DATE / SEC_CODE / SEC_NAME / TOT_VOL（万份）
   单位与 Tushare fund_share.fd_share/10000 一致。
   深市 ETF（159915）本接口覆盖不到，走深交所基金规模（见 4）。

--------------------------------------------------------------------------
4) 深交所 · 基金规模区间报表（深市 ETF 份额的历史回补）
   GET https://www.szse.cn/api/report/ShowReport/data
   ?SHOWTYPE=JSON&CATALOGID=scsj_fund_jjgm&jjlb=ETF
   &txtDm=159915&txtStart=2026-04-21&txtEnd=2026-10-21&PAGENO=1

   单次最多 6 个月、每页 20 行；current_size 为万份。
   ⚠ size_date 标的是「官方份额日的前一交易日」，需按交易日历 +1 个交易日换算；
   末尾 1~2 行为未定稿的临时值。详见 SzseEtfShareRange 的类注释。
"""
from __future__ import annotations

import datetime
import os
import re
from collections import OrderedDict
from functools import lru_cache
from typing import Any, Dict, List, Optional

from .. import http
from ..config import OPT_ETF, OPT_EXCH, OPT_MAIN
from ..contracts import Provider, ProviderError, ProviderNotApplicable

SSE_Q = "https://query.sse.com.cn/commonQuery.do"
SSE_HDR = {"Referer": "https://www.sse.com.cn/"}
SZSE_Q = "https://www.szse.cn/api/report/ShowReport/data"
SZSE_HDR = {"Referer": "https://www.szse.cn/"}

class ExchangePcr(Provider):
    name = "exchange_pcr"
    domains = ("option_pcr",)
    desc = "沪深交易所官方期权日统计（沪市双边、深市单边，均按官网原值落库）"

    # 已知与 Tushare 存在口径差异的日子：到期日（每月第四个周三）交易所披露的是
    # 「交割后」持仓量，Tushare 取的是「收盘」持仓量，前者会明显偏小。
    # 实测 2026-09-23：510050 交易所 461,524 vs Tushare 799,982（0.577 倍），
    # 而成交量、成交额完全一致 —— 说明不是取数缺失，是口径不同。
    # 这类日子不做修正（无法反推交割前后差异），只在此登记供排查时参考。
    KNOWN_OI_DIVERGENCE = ("20260923",)

    def fetch_option_pcr(self, start: str, end: str,
                         targets: Optional[List[str]] = None) -> List[Dict[str, Any]]:
        rows: List[Dict[str, Any]] = []
        days = _trading_days(start, end)

        sh_rows = self._sse(days)
        rows.extend(sh_rows)

        sz_rows = self._szse(days)
        rows.extend(sz_rows)

        if not rows:
            raise ProviderError(f"交易所期权统计 {start}~{end} 无数据")
        rows.sort(key=lambda r: (r["date"], r["oc"]))
        return rows

    # ------------------------------------------------ 上交所
    def _sse(self, days: List[str]) -> List[Dict[str, Any]]:
        out: List[Dict[str, Any]] = []
        empty_streak = 0
        for d in days:
            data = self._sse_day(d)
            if not data:
                empty_streak += 1
                # 连续 3 天没数据说明已经越过上市起点，停止回溯
                if empty_streak >= 3:
                    break
                continue
            empty_streak = 0
            for it in data:
                code = str(it.get("SECURITY_CODE", "")).strip()
                oc = "OP%s.SH" % code
                if oc not in OPT_MAIN and oc not in OPT_ETF:
                    continue           # 只保留报告跟踪的标的
                c_oi = _n(it.get("LEAVES_CALL_QTY"))
                p_oi = _n(it.get("LEAVES_PUT_QTY"))
                c_vol = _n(it.get("CALL_VOLUME"))
                p_vol = _n(it.get("PUT_VOLUME"))
                out.append({
                    "date": d, "oc": oc,
                    "c_oi": c_oi, "p_oi": p_oi,
                    "c_vol": c_vol, "p_vol": p_vol,
                    "c_amt": None, "p_amt": None,
                    "oi_pcr": round(p_oi / c_oi, 6) if c_oi else None,
                    "vol_pcr": round(p_vol / c_vol, 6) if c_vol else None,
                })
        return out

    @staticmethod
    def _sse_day(day: str) -> List[Dict[str, Any]]:
        """取上交所某日全部期权标的统计。

        ⚠ 必须翻页。接口默认 pageSize=20，而跟踪的期权标的共 8 个、
        实际返回常超 20 行（含当月/次月/季月等多档），只取第 1 页会丢行。
        2026-09-23 曾因只取首页导致 4 个标的持仓量只剩 58%~68%
        （成交量却完全正确），PCR 单日偏差最高 21%。
        """
        out: List[Dict[str, Any]] = []
        page = 1
        while page <= 10:
            try:
                j = http.get(SSE_Q, params={
                    "sqlId": "COMMON_SSE_ZQPZ_YSP_QQ_SJTJ_MRTJ_CX",
                    "isPagination": "true",
                    "tradeDate": day,
                    "pageHelp.pageSize": "100",
                    "pageHelp.pageNo": str(page),
                    "pageHelp.beginPage": str(page),
                    "pageHelp.cacheSize": "1",
                    "pageHelp.endPage": str(page),
                }, headers=SSE_HDR, expect="json", retries=1)
            except Exception:
                break
            ph = (j or {}).get("pageHelp") or {}
            data = ph.get("data") or []
            if not data:
                break
            out.extend(data)
            if page >= int(ph.get("pageCount") or 1):
                break
            page += 1
        return out

    # ------------------------------------------------ 深交所
    def _szse(self, days: List[str]) -> List[Dict[str, Any]]:
        out: List[Dict[str, Any]] = []
        empty_streak = 0
        req_fail = 0
        for d in days:
            data = self._szse_day(d)
            if data is None:            # None = 请求本身失败（区别于「当天无数据」）
                req_fail += 1
                continue
            if not data:
                empty_streak += 1
                if empty_streak >= 3:
                    break
                continue
            empty_streak = 0
            for it in data:
                code = _szse_code(it.get("bdzqdm", ""))
                if not code:
                    continue
                oc = "OP%s.SZ" % code
                if oc not in OPT_MAIN and oc not in OPT_ETF:
                    continue
                c_vol = _n(it.get("kzjysl"))
                p_vol = _n(it.get("kdjysl"))
                # 持仓量直接用页面披露的单边（对冲后）原值，不做换算
                c_oi = _n(it.get("kzccsl"))
                p_oi = _n(it.get("kdccsl"))
                out.append({
                    "date": d, "oc": oc,
                    "c_oi": c_oi, "p_oi": p_oi,
                    "c_vol": c_vol, "p_vol": p_vol,
                    "c_amt": None, "p_amt": None,
                    "oi_pcr": round(p_oi / c_oi, 6) if c_oi else None,
                    "vol_pcr": round(p_vol / c_vol, 6) if c_vol else None,
                })
        if req_fail:
            # 不能静默吞掉：深交所被限流时这里会全数失败，但上交所那半边仍正常，
            # 整个域依旧算「成功」，报告里只会表现为创业板指 PCR 停在旧日期。
            print(f"  [exchange] 深交所期权统计 {req_fail}/{len(days)} 天请求失败"
                  f"（多半是 IP 被限流，见 docs/RUNBOOK.md 5.6）", flush=True)
        return out

    @staticmethod
    def _szse_day(day: str) -> Optional[List[Dict[str, Any]]]:
        """返回 None 表示请求失败（区别于返回空列表的「当天没有数据」）。"""
        try:
            j = http.get(SZSE_Q, params={
                "SHOWTYPE": "JSON",
                "CATALOGID": "option_jycchztj",
                "TABKEY": "tab1",
                "PAGENO": "1",
                "PAGESIZE": "50",
                "txtSearchDate": _iso(day),
            }, headers=SZSE_HDR, expect="json", retries=1)
        except Exception:
            return None
        if isinstance(j, list) and j:
            return j[0].get("data") or []
        return []


# 上交所 ETF 份额「按日全市场名单」的进程内缓存（见 ExchangeEtfShare._day_snapshot）
_SSE_SHARE_CACHE: "OrderedDict[str, Dict[str, Dict[str, Any]]]" = OrderedDict()

# 交易日历全序列的进程内缓存（见 SseCalendar）
_CAL_CACHE: List[str] = []


class ExchangeEtfShare(Provider):
    name = "exchange_etf_share"
    domains = ("etf_share",)
    desc = "上交所官网 ETF 份额（TOT_VOL，万份）"

    # 注意：不加 snapshot_only。沪市在 etf_share 链上没有备选源，
    # 一旦被 _stale_snapshot 判为「未刷新」就会换源换到深市接口（必然 ProviderError）。
    # 本 provider 已用 STAT_DATE=end 精确定位当日，不需要这层启发式判断。

    def fetch_etf_share(self, code: str, start: str, end: str) -> List[Dict[str, Any]]:
        num, _, mkt = code.partition(".")
        if mkt.upper() != "SH":
            raise ProviderNotApplicable(f"{code} 不是沪市 ETF，上交所接口不覆盖")

        # 该接口**没有区间参数**，一次只返回某一日的全市场名单（约 900+ 行 / 2 页）。
        # 先按 STAT_DATE=end 精确取「end 那一日」；取不到再退回「最新一日」。
        # 用 STAT_DATE 而不是无脑取最新，是为了补跑历史日期（--asof）时不拿错日子。
        snap = self._day_snapshot(end) or self._day_snapshot("")
        row = snap.get(num)
        rows = [row] if row else []
        rows = [r for r in rows if start <= r["trade_date"] <= end]
        if not rows:
            raise ProviderError(f"{code} 上交所 ETF 份额区间 {start}~{end} 无数据")
        return rows

    def _day_snapshot(self, stat_date: str) -> Dict[str, Dict[str, Any]]:
        """取某一日全市场 ETF 份额，返回 {6位代码: row}；stat_date 为空取最新一日。

        进程内按日缓存：四只沪市 ETF 共用同一份名单，不缓存就要把同一张表
        拉 4 遍（每遍 2 页）。
        """
        key = stat_date or "_latest_"
        hit = _SSE_SHARE_CACHE.get(key)
        if hit is not None:
            _SSE_SHARE_CACHE.move_to_end(key)
            return hit

        params = {
            "sqlId": "COMMON_SSE_ZQPZ_ETFZL_XXPL_ETFGM_SEARCH_L",
            "isPagination": "true",
            "pageHelp.pageSize": "500",
            "pageHelp.cacheSize": "1",
        }
        if key != "_latest_" and len(stat_date) == 8:
            params["STAT_DATE"] = "%s-%s-%s" % (stat_date[:4], stat_date[4:6], stat_date[6:8])

        out: Dict[str, Dict[str, Any]] = {}
        page = 1
        while page <= 20:
            params.update({"pageHelp.pageNo": str(page), "pageHelp.beginPage": str(page),
                           "pageHelp.endPage": str(page)})
            j = http.get(SSE_Q, params=params, headers=SSE_HDR, expect="json")
            ph = (j or {}).get("pageHelp") or {}
            data = ph.get("data") or []
            if not data:
                break
            for it in data:
                c = str(it.get("SEC_CODE", "")).strip()
                d = str(it.get("STAT_DATE", "")).replace("-", "")
                v = _n(it.get("TOT_VOL"))
                if c and d and v is not None and v > 0:
                    out[c] = {"trade_date": d, "fd_share": round(v, 4)}
            if len(data) < 500:
                break
            page += 1

        if out:
            _SSE_SHARE_CACHE[key] = out
            while len(_SSE_SHARE_CACHE) > 8:
                _SSE_SHARE_CACHE.popitem(last=False)
        return out


class SzseEtfShare(Provider):
    """深交所基金列表的「当前规模」（万份）—— 深市 ETF 份额的唯一非 Tushare 源。

    接口
    ----
    GET https://www.szse.cn/api/report/ShowReport/data
        ?SHOWTYPE=JSON&CATALOGID=1105&TABKEY=tab1&txtkey1=159915

    ``txtkey1`` 是页面上的「代码或简称」筛选框，实测可把 1075 行缩到 1 行，
    一次请求即可，不必像早期实现那样翻 54~60 页（翻页还容易在中途被限频）。

    字段 ``dqgm`` = 当前规模（万份），与 Tushare ``fund_share.fd_share/1e4``
    **逐位一致**（2026-10-20 实测 2,673,645.49 vs 2,673,645.4936，仅差深交所
    只保留 2 位小数造成的舍入）。

    ⚠ 三个必须知道的坑
    ------------------
    1. **只有当日快照，没有历史区间参数。** 本 provider 每次只能贡献 1 行，
       日常靠每日运行「往后追」；漏跑的日子由 ``SzseEtfShareRange``（区间报表，
       见下）自动回补，不再依赖 Tushare。
    2. **日期归属错位一天。** ``metadata.subname`` 是快照日（如 2026-10-20），
       而列头括号里印的却是 2026-10-19。实测 dqgm 的值属于 subname 那天。
       稳妥做法是取 ``min(subname, end)``：早间运行时 subname 可能已翻到
       下一交易日，但值仍是 end 日的确认值，钳到 end 才正确。
    3. **晚间值是临时值。** 页面提示「T 日晚间更新的 T 日规模仅供参考，
       以 T+1 日早间更新的 T 日规模为准」。定时任务 06:00 跑，天然拿到确认值。
    """

    name = "szse_etf_share"
    domains = ("etf_share",)
    desc = "深交所基金列表当前规模快照（dqgm，万份，单日）"

    #: 只给「当日值」、没有历史区间参数的数据源。管线据此启用「滞后判定」
    #: （见 Pipeline.sync_etfs 的 _stale_snapshot）。上交所那条给的是完整区间，
    #: 缺数据时表现为「没有这一天」而不是「拿到旧值」，不需要这个判据。
    snapshot_only = True

    def __init__(self) -> None:
        # 上一次请求的原始返回 + 快照日；由 _filtered/_paged 写入，供主流程读取
        self._last_blk: Optional[Dict[str, Any]] = None
        self._last_snap: str = ""

    def fetch_etf_share(self, code: str, start: str, end: str) -> List[Dict[str, Any]]:
        num, _, mkt = code.partition(".")
        if mkt.upper() != "SZ":
            raise ProviderNotApplicable(f"{code} 不是深市 ETF，深交所接口不覆盖")

        # 精确筛选（1 次请求）→ 失效则翻页兜底
        if not self._filtered(num):
            self._paged(num)

        blk, snap_date = self._last_blk or {}, self._last_snap
        data = blk.get("data") or []
        got: List[Dict[str, Any]] = []
        for it in data:
            m = re.search(r"code=(\d{6})", str(it.get("sys_key", "")))
            if not m or m.group(1) != num:
                continue
            v = _n(it.get("dqgm"))
            if v is None or v <= 0:
                continue
            d = min(snap_date, end) if snap_date else end
            if d < start:
                continue
            got.append({"trade_date": d, "fd_share": round(v, 4)})

        if not got:
            raise ProviderError(f"{code} 深交所份额快照（{snap_date or '未知'}）"
                                f"未覆盖请求窗口 {start}~{end}")
        got.sort(key=lambda r: r["trade_date"])
        return got

    # ------------------------------------------------ 内部
    def _ask(self, params: Dict[str, str]) -> Any:
        """深交所对系统代理时通时不通，两条通道都试一遍。"""
        try:
            return http.get(SZSE_Q, params=params, headers=SZSE_HDR,
                            expect="json", retries=1)
        except Exception:                                  # noqa: BLE001
            return http.get(SZSE_Q, params=params, headers=SZSE_HDR,
                            expect="json", retries=1, direct=True)

    def _take(self, r: Any) -> Dict[str, Any]:
        blk = (r or [{}])[0] if isinstance(r, list) else (r or {})
        meta = blk.get("metadata") or {}
        snap = _ymd(meta.get("subname"))
        self._last_blk, self._last_snap = blk, snap
        return blk

    def _filtered(self, num: str) -> bool:
        try:
            self._take(self._ask({
                "SHOWTYPE": "JSON", "CATALOGID": "1105",
                "PAGENO": "1", "TABKEY": "tab1", "txtkey1": num,
            }))
        except Exception:                                  # noqa: BLE001
            return False
        return bool((self._last_blk or {}).get("data"))

    def _paged(self, num: str) -> bool:
        """精确筛选失效时的退路：翻页扫全表，找到即停。"""
        for page in range(1, 80):
            try:
                blk = self._take(self._ask({
                    "SHOWTYPE": "JSON", "CATALOGID": "1105",
                    "PAGENO": str(page), "TABKEY": "tab1",
                }))
            except Exception:                              # noqa: BLE001
                return False
            data = blk.get("data") or []
            if not data:
                return False
            if any(f"code={num}" in str(it.get("sys_key", "")) for it in data):
                # 保留整页，由调用方按 code 过滤
                return True
            if page >= int((blk.get("metadata") or {}).get("pagecount") or 0):
                return False
        return False


class SzseEtfShareRange(Provider):
    """深交所「基金规模」区间报表 —— 深市 ETF 份额的历史回补源。

    接口
    ----
    GET https://www.szse.cn/api/report/ShowReport/data
        ?SHOWTYPE=JSON&CATALOGID=scsj_fund_jjgm&jjlb=ETF
        &txtDm=159915&txtStart=2026-04-21&txtEnd=2026-10-21&PAGENO=1

    页面 ``market/fund/volume/etf/index.html``（市场数据 → 基金规模）的查询条件
    在接口元数据里写死了 ``dateRange('all','${txtEnd}','6m')``：**单次最多 6 个月**，
    本 provider 自动切块。每页 20 行，字段 ``size_date`` / ``fund_code`` /
    ``current_size``（万份，含千分位），值与 Tushare ``fund_share.fd_share`` 同源同值。

    ⚠ 标签日错位一个交易日（2026-10 实测 155/155 行命中）
    -----------------------------------------------------
    ``size_date`` 标的是「官方份额日的前一个交易日」：

        row[label] == 官方[交易日历中 label 的下一个交易日]

    4-10 月 118 行 + 2-4 月 37 行，除末尾未定稿的 1~2 行外全部吻合。因此换算
    必须走交易日历取「下一个交易日」，不能简单 +1 天（周五的下一个是下周一）。

    由此得到两条处理规则：
    1. **映射**：label → next_trading_day(label) 才是官方份额日；
    2. **丢掉未定稿**：官方日 > 今天-1 的行丢弃（T 晚间临时值、T+1 早间才定稿，
       与 1105 快照同一族的规则）。丢掉的这几天正好由每日快照覆盖。

    单次 6 个月 ≈ 7 页 = 7 个请求，只在管线检测到缺口时才会被调用。
    """

    name = "szse_etf_share_range"
    domains = ("etf_share",)
    desc = "深交所基金规模区间报表（标签日=官方日前一交易日，可回补历史缺口）"

    #: 官方上限 6 个月，留 10 天余量
    MAX_SPAN_DAYS = 170
    #: 6 个月最多 ~130 个交易日 = 7 页；上限放宽到 20 页防意外截断
    MAX_PAGES = 20

    def fetch_etf_share(self, code: str, start: str, end: str) -> List[Dict[str, Any]]:
        num, _, mkt = code.partition(".")
        if mkt.upper() != "SZ":
            raise ProviderNotApplicable(f"{code} 不是深市 ETF，深交所区间报表不覆盖")

        # 1) 按 ≤170 天切块抓取，先收下全部 label -> 值
        labels: Dict[str, float] = {}
        for cs, ce in _chunks(start, end, self.MAX_SPAN_DAYS):
            for d, v in self._query(num, cs, ce):
                labels[d] = v
        if not labels:
            raise ProviderError(f"{code} 深交所区间报表 {start}~{end} 无数据")

        # 2) label → 官方份额日：取交易日历里的下一个交易日
        cal_end = _shift_date(max(labels), 20)
        cal = _trading_days(min(labels), cal_end)
        nxt = {d: cal[i + 1] for i, d in enumerate(cal[:-1])}

        today = datetime.date.today().strftime("%Y%m%d")
        cutoff = _shift_date(today, -1)          # 官方日 > 昨天 的还没定稿
        rows: List[Dict[str, Any]] = []
        for d, v in sorted(labels.items()):
            official = nxt.get(d)
            if not official or not (start <= official <= end):
                continue
            if official > cutoff or v <= 0:
                continue
            rows.append({"trade_date": official, "fd_share": round(v, 4)})

        if not rows:
            raise ProviderError(f"{code} 深交所区间报表 {start}~{end} 映射后无可用行")
        rows.sort(key=lambda r: r["trade_date"])
        return rows

    # ------------------------------------------------ 内部
    def _query(self, num: str, start: str, end: str) -> List[tuple]:
        """单个时间块内翻页，返回 [(label, 万份)]。"""
        out: List[tuple] = []
        page = 1
        while page <= self.MAX_PAGES:
            try:
                r = http.get(SZSE_Q, params={
                    "SHOWTYPE": "JSON", "CATALOGID": "scsj_fund_jjgm",
                    "jjlb": "ETF", "txtDm": num,
                    "txtStart": _iso(start), "txtEnd": _iso(end),
                    "PAGENO": str(page),
                }, headers=SZSE_HDR, expect="json", retries=1)
            except Exception:                              # noqa: BLE001
                # 深交所对系统代理时通时不通，直连再试一次
                try:
                    r = http.get(SZSE_Q, params={
                        "SHOWTYPE": "JSON", "CATALOGID": "scsj_fund_jjgm",
                        "jjlb": "ETF", "txtDm": num,
                        "txtStart": _iso(start), "txtEnd": _iso(end),
                        "PAGENO": str(page),
                    }, headers=SZSE_HDR, expect="json", retries=1, direct=True)
                except Exception:                          # noqa: BLE001
                    break
            blk = (r or [{}])[0] if isinstance(r, list) else (r or {})
            meta = blk.get("metadata") or {}
            data = blk.get("data") or []
            if not data:
                break
            for it in data:
                if str(it.get("fund_code", "")).strip() != num:
                    continue
                d = _ymd(it.get("size_date"))
                v = _n(it.get("current_size"))
                if d and v > 0:
                    out.append((d, v))
            if page >= int(meta.get("pagecount") or 1):
                break
            page += 1
        return out


class SseCalendar(Provider):
    """交易日历：用中证指数官网的上证指数历史日期（一次返回全序列）。

    日历是历史事实，一次运行内不会变，因此做了进程内缓存：不缓存的话
    ``resolve_asof`` + 各域缺口检测会把同一张表拉 6 次。
    """

    name = "sse_calendar"
    domains = ("calendar",)
    desc = "交易日历（以上交所指数历史日期为准）"

    def fetch_calendar(self, start: str, end: str) -> List[str]:
        global _CAL_CACHE
        if not _CAL_CACHE:
            j = http.get("https://www.csindex.com.cn/csindex-home/perf/index-perf-tradeDate",
                         params={"indexCode": "000300"},
                         headers={"Referer": "https://www.csindex.com.cn/"},
                         expect="json")
            data = (j or {}).get("data") or []
            _CAL_CACHE = sorted({str(x) for x in data})
        if not _CAL_CACHE:
            raise ProviderError("中证交易日历无数据")
        days = [d for d in _CAL_CACHE if start <= d <= end]
        if not days:
            raise ProviderError(f"交易日历 {start}~{end} 无数据")
        return days


# ---------------------------------------------------------------- 工具

def _szse_code(s: str) -> str:
    """'创业板ETF易方达(159915)' -> '159915'"""
    s = str(s or "")
    if "(" in s and s.endswith(")"):
        return s[s.rindex("(") + 1:-1]
    return ""


def _n(x) -> float:
    """解析带千分位的数字字符串 '1,178,601' -> 1178601.0"""
    if x is None:
        return 0.0
    s = str(x).replace(",", "").strip()
    if not s or s in ("-", "--"):
        return 0.0
    try:
        return float(s)
    except ValueError:
        return 0.0


def _iso(ymd: str) -> str:
    return f"{ymd[:4]}-{ymd[4:6]}-{ymd[6:8]}"


def _ymd(x) -> str:
    """'2026-10-20 ' -> '20261020'；不像日期的返回空串（宁可空，不要猜）。"""
    d = re.sub(r"\D", "", str(x or ""))[:8]
    return d if len(d) == 8 else ""


def _shift_date(ymd: str, days: int) -> str:
    """YYYYMMDD 平移 N 个自然日。"""
    d = datetime.datetime.strptime(ymd, "%Y%m%d").date()
    return (d + datetime.timedelta(days=days)).strftime("%Y%m%d")


def _chunks(start: str, end: str, span: int) -> List[tuple]:
    """把 [start,end] 切成若干 ≤span 自然日的块（深交所区间报表单次上限 6 个月）。"""
    out: List[tuple] = []
    cs = start
    while cs <= end:
        ce = min(_shift_date(cs, span), end)
        out.append((cs, ce))
        cs = _shift_date(ce, 1)
    return out


@lru_cache(maxsize=32)
def _trading_days(start: str, end: str) -> List[str]:
    """区间内的交易日列表（升序）。

    优先用交易所日历。**不要**退回「周一~周五」作为唯一依据：
    ``_sse / _szse`` 里有「连续 3 天无数据即认为越过上市起点、停止回溯」的优化，
    如果日历把国庆长假当成交易日，长假结束后的前 3 个真实交易日还没被问到
    就会提前 break，导致整段漏数据（曾因此丢掉 10-08 ~ 10-19 的 PCR）。
    """
    try:
        from ..registry import Registry
        cal = Registry.get().fetch("calendar", start, end)
        days = sorted({(c["cal_date"] if isinstance(c, dict) else str(c))
                       for c in cal})
        days = [d for d in days if start <= d <= end and str(d).isdigit()]
        if days:
            return days
    except Exception:                       # noqa: BLE001
        pass

    d0 = datetime.datetime.strptime(start, "%Y%m%d").date()
    d1 = datetime.datetime.strptime(end, "%Y%m%d").date()
    out, d = [], d0
    while d <= d1:
        if d.weekday() < 5:
            out.append(d.strftime("%Y%m%d"))
        d += datetime.timedelta(days=1)
    return out
