# -*- coding: utf-8 -*-
"""东方财富 —— 指数估值（主源）/ 指数行情 / 10Y 国债收益率。

一、指数估值（本项目的主估值来源）
    GET https://datacenter-web.eastmoney.com/api/data/v1/get

    (a) 成分股表  reportName=RPT_INDEX_COMPONENT
        filter=(INDEX_CODE=000300)          ← 注意是**裸值**，加引号会报 antlr 解析错误
        返回 [{SECURITY_CODE, INDEX_CODE}]，沪深300 恰好 300 条、科创50 50 条。

    (b) 全市场个股估值明细 reportName=RPT_VALUEANALYSIS_DET
        filter=(TRADE_DATE='2026-10-19')    ← 日期是**字符串**，必须单引号
        pageSize 最大实测可到 6000，一次返回全市场约 5500 只个股，1 次请求即可。

    ⚠ `source=WEB` 与 `client=WEB` 两个参数**必须**带，否则返回 9701「服务器繁忙」。

    指数估值 = 成分股市值加权：
        PE_TTM = Σ总市值 / Σ(总市值 / PE_TTM)
        PB     = Σ总市值 / Σ(总市值 / PB_MRQ)
    **必须包含亏损股**（PE<=0 不剔除）——这一点经过实测比对确定：
        同日对五个宽基，上述公式与中证官网口径的平均绝对误差 0.17%，
        最大 0.4%；若剔除亏损股，误差会放大到 15%。

    数据下界：2018-01-02（更早的日期接口返回空）。
    2015-01-05 ~ 2017-12-29 为建库时一次性回填的历史段（已冻结）。

二、指数行情
    GET https://push2.eastmoney.com/api/qt/stock/get?secid=1.000300&fields=f43,...
    仅当日快照，历史走新浪。⚠ 部分网络环境下 push2 不可达，作为 quote 的末位备选。

三、10Y 国债收益率
    GET https://datacenter-web.eastmoney.com/api/data/v1/get
        ?reportName=RPTA_WEB_TREASURYYIELD&columns=ALL&pageSize=500
        &sortColumns=SOLAR_DATE&sortTypes=1
        &filter=(SOLAR_DATE>='2026-01-01')   → EMM00166466 为 10Y 收益率
"""
from __future__ import annotations

import datetime
from collections import OrderedDict
from typing import Any, Dict, List, Optional

from .. import http
from ..config import CODE2EM, CODE2NAME, INDEX_CODES
from ..contracts import Provider, ProviderError

DC = "https://datacenter-web.eastmoney.com/api/data/v1/get"
PUSH = "https://push2.eastmoney.com/api/qt/stock/get"
HDR = {"Referer": "https://data.eastmoney.com/gzfx/"}
QHDR = {"Referer": "https://quote.eastmoney.com/"}

# 东财指数代码（RPT_INDEX_COMPONENT 的 INDEX_CODE）：A 股宽基是 6 位纯数字，
# 与常见指数代码去掉交易所后缀一致，唯独需注意创业板指是 399006。
IDX2EM_CODE = {
    "000300.SH": "000300",
    "000016.SH": "000016",
    "000905.SH": "000905",
    "399006.SZ": "399006",
    "000688.SH": "000688",
}

# 成分股表缓存：指数成分每半年调整一次，缓存 7 天足够，且能省掉每天 5 次请求
_CONS_CACHE: Dict[str, List[str]] = {}
_CONS_FILE = "em_constituents.json"
_CONS_TTL_DAYS = 7


def _constituents(idx_code: str) -> List[str]:
    """取指数成分股代码列表（6 位）。进程内 + 磁盘双层缓存，TTL 7 天。"""
    if idx_code in _CONS_CACHE:
        return _CONS_CACHE[idx_code]

    cached, fresh = _load_cons_cache()
    if fresh and idx_code in cached and cached[idx_code]:
        _CONS_CACHE[idx_code] = cached[idx_code]
        return cached[idx_code]

    rows = _paged("RPT_INDEX_COMPONENT", "ALL",
                  filter_="(INDEX_CODE=%s)" % idx_code, page_size=1000)
    codes = [str(r.get("SECURITY_CODE", "")).strip() for r in rows]
    codes = [c for c in codes if c]
    if not codes:
        # 拉取失败时退回过期缓存，总比直接报错好
        if idx_code in cached and cached[idx_code]:
            _CONS_CACHE[idx_code] = cached[idx_code]
            return cached[idx_code]
        return []

    _CONS_CACHE[idx_code] = codes
    cached[idx_code] = codes
    _save_cons_cache(cached)
    return codes


def _load_cons_cache():
    """返回 (缓存 dict, 是否新鲜)。"""
    import json
    import os
    from ..config import CACHE
    path = os.path.join(CACHE, _CONS_FILE)
    if not os.path.exists(path):
        return {}, False
    try:
        with open(path, encoding="utf-8") as f:
            blob = json.load(f)
        ts = blob.get("_updated_at", "")
        d0 = datetime.datetime.strptime(ts, "%Y%m%d%H%M%S").date()
        age = (datetime.date.today() - d0).days
        return blob.get("data", {}), age <= _CONS_TTL_DAYS
    except Exception:                       # noqa: BLE001
        return {}, False


def _save_cons_cache(data: Dict[str, List[str]]) -> None:
    import json
    import os
    from ..config import CACHE
    path = os.path.join(CACHE, _CONS_FILE)
    tmp = path + ".tmp"
    blob = {"_updated_at": datetime.datetime.now().strftime("%Y%m%d%H%M%S"), "data": data}
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(blob, f, ensure_ascii=False)
        os.replace(tmp, path)
    except Exception:                       # noqa: BLE001
        pass                                # 缓存写失败不影响主流程


class EmValuation(Provider):
    name = "em_valuation"
    domains = ("valuation",)
    desc = "东财全市场个股估值 + 真实成分股加权（口径与指数公司一致，误差 ~0.2%）"

    def fetch_valuation(self, code: str, start: str, end: str) -> List[Dict[str, Any]]:
        idx = IDX2EM_CODE.get(code)
        if not idx:
            raise ProviderError(f"{code} 无东财指数代码映射")

        cons = _constituents(idx)
        if not cons:
            raise ProviderError(f"{idx} 东财成分股为空")

        dates = _trading_dates(start, end)
        if not dates:
            raise ProviderError(f"{start}~{end} 无候选交易日")

        rows: List[Dict[str, Any]] = []
        for d in dates:
            stocks = _all_stocks(_iso(d))
            if not stocks:
                continue                       # 非交易日 / 早于 2018-01-02
            agg = _aggregate_by_constituents(stocks, cons)
            if agg is None:
                continue
            pe, pb, mv, fmv = agg
            # 静态 PE（PE_LAR，按最近年报）单独聚合，对应库内历史 pe 字段。
            # 报告正文只用 pe_ttm，但 raw.json 的 pe 不能留空，否则与历史行不一致。
            pe_static = _aggregate_key(stocks, cons, "PE_LAR")
            rows.append({
                "trade_date": d,
                "pe_ttm": round(pe, 4) if pe else None,
                "pe": round(pe_static, 4) if pe_static else (round(pe, 4) if pe else None),
                "pb": round(pb, 4) if pb else None,
                "turnover_rate": None,
                "turnover_rate_f": None,
                # 东财 TOTAL_MARKET_CAP 单位是「元」，与库内历史口径一致；
                # 的数值恰好等于「元」的数值（即实际存的是亿元，不是文档说的万元）。
                # 实测抽样核对：65,515,940,053,434 元 ↔ 65,515,922,156,051，
                # 比值 1.0000003，因此**不做任何换算**直接落库，否则会差 1 万倍。
                "total_mv": round(mv, 2) if mv else None,
                "float_mv": round(fmv, 2) if fmv else None,
                "source": "em_valuation",
            })
        if not rows:
            raise ProviderError(f"{code} 东财聚合无结果（{start}~{end} 可能早于 2018-01-02）")
        return rows


class EmQuote(Provider):
    name = "em_quote"
    domains = ("quote",)
    desc = "东财指数当日快照（无历史）"

    def fetch_quote(self, code: str, start: str, end: str) -> List[Dict[str, Any]]:
        secid = CODE2EM.get(code)
        if not secid:
            raise ProviderError(f"{code} 无东财 secid")
        if start != end:
            raise ProviderError("东财快照只支持单日")
        j = http.get(PUSH, params={
            "secid": secid, "fltt": "2",
            "fields": "f43,f44,f45,f46,f47,f48,f57,f58,f60,f169,f170",
        }, headers=QHDR, expect="json")
        d = (j or {}).get("data") or {}
        if not d or d.get("f43") in (None, "-"):
            raise ProviderError("东财快照无数据")
        return [{
            "trade_date": end,
            "open": _f(d.get("f46")),
            "high": _f(d.get("f44")),
            "low": _f(d.get("f45")),
            "close": _f(d.get("f43")),
            "pre_close": _f(d.get("f60")),
            "change": _f(d.get("f169")),
            "pct_chg": _f(d.get("f170")),
            "vol": _f(d.get("f47")),
            "amount": _f(d.get("f48")),
        }]


class EmBond10y(Provider):
    name = "em_bond10y"
    domains = ("bond10y",)
    desc = "东财数据中心 中债10年期国债到期收益率（EMM00166466）"

    def fetch_bond10y(self, start: str, end: str) -> List[Dict[str, Any]]:
        rows: List[Dict[str, Any]] = []
        page = 1
        while page <= 40:
            j = http.get(DC, params={
                "reportName": "RPTA_WEB_TREASURYYIELD",
                "columns": "ALL",
                "pageNumber": str(page),
                "pageSize": "500",
                "sortColumns": "SOLAR_DATE",
                "sortTypes": "1",
                "filter": "(SOLAR_DATE>='%s')(SOLAR_DATE<='%s')" % (_iso(start), _iso(end)),
                "source": "WEB", "client": "WEB",
            }, headers={"Referer": "https://data.eastmoney.com/"}, expect="json")
            res = (j or {}).get("result") or {}
            data = res.get("data") or []
            if not data:
                break
            for it in data:
                v = _f(it.get("EMM00166466"))
                d = str(it.get("SOLAR_DATE", ""))[:10].replace("-", "")
                if v is None or not d:
                    continue
                rows.append({"trade_date": d, "y10": round(v, 4)})
            if len(rows) >= (res.get("count") or 0):
                break
            page += 1
        if not rows:
            raise ProviderError("东财国债收益率无数据")
        rows.sort(key=lambda r: r["trade_date"])
        return rows


# ---------------------------------------------------------------- 内部工具

# 同一交易日全市场快照的进程内缓存（见 _all_stocks）
_STOCK_DAY_CACHE: "OrderedDict[str, Dict[str, Dict[str, Any]]]" = OrderedDict()
_STOCK_DAY_CACHE_MAX = 12


def _all_stocks(iso_date: str) -> Dict[str, Dict[str, Any]]:
    """取某一日全市场个股估值明细，返回 {6位代码: row}。

    pageSize 给 6000 时东财一次就返回全部（实测 5575 条 / 1 页），
    但保留分页逻辑以防未来股票数超过单页上限。

    **进程内按日缓存**：五个指数在同一交易日用的是同一份全市场快照，
    不缓存就等于同一天拉 5 次。缓存上限 12 天，避免回测工具跑长区间时吃内存。
    """
    cached = _STOCK_DAY_CACHE.get(iso_date)
    if cached is not None:
        _STOCK_DAY_CACHE.move_to_end(iso_date)
        return cached

    rows = _paged(
        "RPT_VALUEANALYSIS_DET",
        "SECURITY_CODE,TOTAL_MARKET_CAP,NOTLIMITED_MARKETCAP_A,"
        "PE_TTM,PE_LAR,PB_MRQ",
        filter_="(TRADE_DATE='%s')" % iso_date,
        page_size=6000,
    )
    out = {str(r.get("SECURITY_CODE", "")).strip(): r for r in rows if r.get("SECURITY_CODE")}
    if out:                                   # 空结果不缓存，避免瞬时失败被固化
        _STOCK_DAY_CACHE[iso_date] = out
        while len(_STOCK_DAY_CACHE) > _STOCK_DAY_CACHE_MAX:
            _STOCK_DAY_CACHE.popitem(last=False)
    return out


def _paged(report: str, columns: str, filter_: str,
           page_size: int = 5000, max_pages: int = 20) -> List[Dict[str, Any]]:
    """东财 datacenter 通用分页取数。"""
    out: List[Dict[str, Any]] = []
    for page in range(1, max_pages + 1):
        j = http.get(DC, params={
            "reportName": report,
            "columns": columns,
            "pageNumber": str(page),
            "pageSize": str(page_size),
            "source": "WEB",
            "client": "WEB",
            "filter": filter_,
        }, headers=HDR, expect="json", retries=2)
        res = (j or {}).get("result") or {}
        data = res.get("data") or []
        if not data:
            break
        out.extend(data)
        total = res.get("count")
        # count 缺失时以「返回条数 < page_size」判断已到末页
        if total is not None and len(out) >= int(total):
            break
        if total is None and len(data) < page_size:
            break
    return out


def _aggregate_by_constituents(stocks: Dict[str, Dict[str, Any]],
                               cons: List[str]):
    """成分股市值加权得到 (PE, PB, 总市值, 流通市值)。

    与指数公司口径一致的两个关键点（经实测校准）：
      1. 权重用 **总市值**（TOTAL_MARKET_CAP），不是自由流通市值；
      2. PE 计算 **保留亏损股**（PE<=0 参与，贡献负的盈利），不要剔除。
    """
    mv_total = 0.0
    fv_total = 0.0
    inv_pe = 0.0          # Σ(市值 / PE)，亏损股为负值
    inv_pb = 0.0          # Σ(市值 / PB)
    for c in cons:
        s = stocks.get(c)
        if not s:
            continue
        mc = _f(s.get("TOTAL_MARKET_CAP")) or 0.0
        if mc <= 0:
            continue
        mv_total += mc
        fv_total += _f(s.get("NOTLIMITED_MARKETCAP_A")) or 0.0
        pe = _f(s.get("PE_TTM"))
        if pe:                                  # 含负值，仅排除 0/None
            inv_pe += mc / pe
        pb = _f(s.get("PB_MRQ"))
        if pb and pb > 0:                       # PB<=0 无经济意义，排除
            inv_pb += mc / pb

    pe_agg = (mv_total / inv_pe) if abs(inv_pe) > 1e-9 else None
    pb_agg = (mv_total / inv_pb) if inv_pb > 0 else None
    return pe_agg, pb_agg, mv_total, fv_total


def _aggregate_key(stocks: Dict[str, Dict[str, Any]],
                   cons: List[str], key: str) -> Optional[float]:
    """按总市值加权聚合单个估值字段（含亏损，与 index_dailybasic 口径一致）。"""
    inv = 0.0
    mv = 0.0
    for c in cons:
        s = stocks.get(c)
        if not s:
            continue
        m = _f(s.get("TOTAL_MARKET_CAP")) or 0.0
        if m <= 0:
            continue
        v = _f(s.get(key))
        if not v:
            continue
        inv += m / v
        mv += m
    return (mv / inv) if abs(inv) > 1e-9 else None


def _trading_dates(start: str, end: str) -> List[str]:
    """区间内的交易日列表。

    优先用交易所日历（能正确跳过法定节假日），拿不到时退化为「周一~周五」。
    直接用周一~周五会在国庆这类长假期间对同一批日期反复请求接口，
    既慢又容易触发重试。
    """
    try:
        from ..registry import Registry
        cal = Registry.get().fetch("calendar", start, end)
        days = [c["cal_date"] if isinstance(c, dict) else str(c) for c in cal]
        days = sorted({d for d in days if start <= d <= end and str(d).isdigit()})
        if days:
            return days
    except Exception:                       # noqa: BLE001 —— 日历不可用不该阻塞取数
        pass

    d0 = datetime.datetime.strptime(start, "%Y%m%d").date()
    d1 = datetime.datetime.strptime(end, "%Y%m%d").date()
    out = []
    d = d0
    while d <= d1:
        if d.weekday() < 5:
            out.append(d.strftime("%Y%m%d"))
        d += datetime.timedelta(days=1)
    return out


def _iso(ymd: str) -> str:
    return f"{ymd[:4]}-{ymd[4:6]}-{ymd[6:8]}"


def _f(x) -> Optional[float]:
    try:
        return float(x)
    except (TypeError, ValueError):
        return None
