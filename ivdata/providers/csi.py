# -*- coding: utf-8 -*-
"""中证指数官网 —— 指数 PE + 行情。

接口（从前端 app.js 里逆向出来的）
----------------------------------
1) 官方 PE_TTM 全历史
   GET https://www.csindex.com.cn/csindex-home/perf/indexCsiDsPe?indexCode=000300
   → [{"tradeDate":"20110628","indexName":"沪深300","peg":14.32}, ...]
   实测：沪深300 / 上证50 / 中证500 自 2011-06-28 起，科创50 自 2020-07-06 起。
   创业板指（399006）不在中证官网覆盖范围（深证系列，由巨潮发布）。

2) 指数行情
   GET https://www.csindex.com.cn/csindex-home/perf/index-perf-oneday?indexCode=000300
   只给当日快照，历史日线请用新浪源。

说明
----
* 该接口的 `peg` 字段实为 **PE_TTM**（Rolling PE），不是 PEG。已用沪深300
  与中证官网口径一致（同一交易日差异 < 2%，属口径微差）。
* 中证官网**不提供 PB**。PB 由 em_valuation 用成分股/全市场聚合补足，
  见 EmValuation；本 provider 只负责 PE，返回时 pb 留空，由上层合并。
"""
from __future__ import annotations

from typing import Any, Dict, List

from .. import http
from ..config import CODE2CSI
from ..contracts import Provider, ProviderError

BASE = "https://www.csindex.com.cn/csindex-home"
REFERER = "https://www.csindex.com.cn/"


class CsiValuation(Provider):
    name = "csi_valuation"
    domains = ("valuation",)
    desc = "中证指数官网 PE_TTM 全历史（权威口径，无 PB）"

    def fetch_valuation(self, code: str, start: str, end: str) -> List[Dict[str, Any]]:
        csi = CODE2CSI.get(code)
        if not csi:
            raise ProviderError(f"{code} 不在中证官网覆盖范围（无 csi_code 映射）")

        j = http.get(f"{BASE}/perf/indexCsiDsPe",
                     params={"indexCode": csi},
                     headers={"Referer": REFERER},
                     expect="json")
        if not isinstance(j, dict):
            raise ProviderError("中证 PE 接口返回格式异常")
        if str(j.get("code")) != "200":
            raise ProviderError(f"中证 PE 接口错误: {j.get('msg')}")

        data = j.get("data") or []
        if not data:
            raise ProviderError(f"中证 PE 无数据 indexCode={csi}")

        rows: List[Dict[str, Any]] = []
        for it in data:
            d = str(it.get("tradeDate", ""))
            if not d or not (start <= d <= end):
                continue
            pe = _f(it.get("peg"))
            if pe is None:
                continue
            rows.append({
                "trade_date": d,
                "pe_ttm": round(pe, 4),
                "pe": round(pe, 4),      # 中证只发布 TTM，动态 PE 用同值占位
                "pb": None,              # 由 em_valuation 合并补足
                "turnover_rate": None,
                "turnover_rate_f": None,
                "total_mv": None,
                "float_mv": None,
            })
        if not rows:
            raise ProviderError(f"中证 PE 区间 {start}~{end} 无数据")
        return rows


class CsiQuote(Provider):
    """中证官网当日快照（仅作 quote 的备用，历史仍走新浪）。"""

    name = "csi_quote"
    domains = ("quote",)
    desc = "中证指数官网当日行情快照（无历史）"

    def fetch_quote(self, code: str, start: str, end: str) -> List[Dict[str, Any]]:
        csi = CODE2CSI.get(code)
        if not csi:
            raise ProviderError(f"{code} 无 csi_code")
        if start != end:
            raise ProviderError("中证快照接口只支持单日，历史行情请用新浪源")
        j = http.get(f"{BASE}/perf/index-perf-oneday",
                     params={"indexCode": csi},
                     headers={"Referer": REFERER},
                     expect="json")
        h = ((j or {}).get("data") or {}).get("intraDayHeader") or {}
        if not h:
            raise ProviderError("中证快照无数据")
        cur = _f(h.get("current"))
        pre = _f(h.get("closePre"))
        if cur is None:
            raise ProviderError("中证快照缺 current")
        return [{
            "trade_date": str(h.get("tradeDate", "")).replace("-", ""),
            "open": _f(h.get("openToday")),
            "high": _f(h.get("high")),
            "low": _f(h.get("low")),
            "close": cur,
            "pre_close": pre,
            "change": _f(h.get("change")),
            "pct_chg": _f(h.get("changePct")),
            "vol": _f(h.get("tradingVol")),
            "amount": _f(h.get("tradingAmt")),
        }]


def _f(x) -> float | None:
    try:
        return float(x)
    except (TypeError, ValueError):
        return None
