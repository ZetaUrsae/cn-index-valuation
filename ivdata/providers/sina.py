# -*- coding: utf-8 -*-
"""新浪财经 —— 指数 / ETF 日线。

接口
----
GET https://money.finance.sina.com.cn/quotes_service/api/json_v2.php/
        CN_MarketData.getKLineData
    ?symbol=sh000300&scale=240&ma=no&datalen=5000

特点
----
* 不需 token，日线可回溯到 2006 年（datalen 最大实测 5000 根）。
* 返回字段：day / open / high / low / close / volume。
* 无成交额（amount），无 pre_close —— 由相邻两日收盘自行推导。
* 实时快照走 hq.sinajs.cn，但历史只能靠 K 线接口，这里只用后者。
"""
from __future__ import annotations

import datetime
from typing import Any, Dict, List

from .. import http
from ..config import CODE2SINA
from ..contracts import Provider, ProviderError

BASE = "https://money.finance.sina.com.cn/quotes_service/api/json_v2.php/CN_MarketData.getKLineData"
REFERER = "https://finance.sina.com.cn/"

# 新浪一次最多给 5000 根日线（约 20 年），够覆盖任何回测窗口
MAX_BARS = 5000


class SinaQuote(Provider):
    name = "sina_quote"
    domains = ("quote", "etf_quote")
    desc = "新浪财经日 K（无需 token，可回溯至 2006 年）"

    def _symbol(self, code: str) -> str:
        # 指数走 CODE2SINA 映射；ETF 直接用 sh/sz + 6 位
        if code in CODE2SINA:
            return CODE2SINA[code]
        num, _, mkt = code.partition(".")
        return ("sh" if mkt.upper() == "SH" else "sz") + num

    def fetch_quote(self, code: str, start: str, end: str) -> List[Dict[str, Any]]:
        return self._fetch(code, start, end)

    def fetch_etf_quote(self, code: str, start: str, end: str) -> List[Dict[str, Any]]:
        return self._fetch(code, start, end)

    def _fetch(self, code: str, start: str, end: str) -> List[Dict[str, Any]]:
        sym = self._symbol(code)
        # datalen 按窗口大小取：新浪没有 start/end 参数，只能「取最近 N 根再本地裁」。
        # 固定给 5000 会让每次增量都白传近 20 年数据；这里按自然日跨度 + 20 缓冲，
        # 下限 60 根（够覆盖节假日，也保证第一行有前收盘可算涨跌幅）。
        span = 0
        try:
            span = (datetime.datetime.strptime(end, "%Y%m%d")
                    - datetime.datetime.strptime(start, "%Y%m%d")).days
        except (TypeError, ValueError):
            span = 0
        bars = min(MAX_BARS, max(60, span + 20))
        raw = http.get(BASE,
                       params={"symbol": sym, "scale": "240", "ma": "no",
                               "datalen": str(bars)},
                       headers={"Referer": REFERER},
                       expect="json")
        if isinstance(raw, str):
            raise ProviderError(f"新浪返回非 JSON: {raw[:80]}")
        if not isinstance(raw, list) or not raw:
            raise ProviderError(f"新浪无数据 symbol={sym}")

        rows: List[Dict[str, Any]] = []
        prev_close = None
        for it in raw:
            d = str(it.get("day", "")).replace("-", "")
            if not d:
                continue
            close = _f(it.get("close"))
            bar = {
                "trade_date": d,
                "open": _f(it.get("open")),
                "high": _f(it.get("high")),
                "low": _f(it.get("low")),
                "close": close,
                "vol": _f(it.get("volume")),
                "amount": None,          # 新浪日 K 不含成交额
            }
            if prev_close:
                bar["pre_close"] = round(prev_close, 4)
                bar["change"] = round(close - prev_close, 4) if close else None
                bar["pct_chg"] = round((close / prev_close - 1) * 100, 4) if prev_close else None
            rows.append(bar)
            if close:
                prev_close = close

        # 只保留请求区间（新浪没有 start/end 参数，只能在本地裁）
        rows = [r for r in rows if start <= r["trade_date"] <= end]
        if not rows:
            raise ProviderError(f"新浪区间 {start}~{end} 无数据")
        return rows


def _f(x) -> float | None:
    try:
        v = float(x)
        return v
    except (TypeError, ValueError):
        return None
