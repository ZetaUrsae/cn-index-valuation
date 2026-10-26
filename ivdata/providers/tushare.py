# -*- coding: utf-8 -*-
"""Tushare Pro —— **备用数据源**。

默认不参与取数：Registry 只有在显式允许（IV_ALLOW_TUSHARE=1，仅人工指令场景）且
优先级链上所有官方/公开源都失败时才会走到这里。

设计原则
--------
* 只在 `available()` 为真（装了 tushare 且有 token）时才进入调度。
* 每个方法都保留与旧脚本完全一致的接口语义，随时可以原地替换回去。
* 逐合约汇总 PCR（TusharePcr）保留旧有实现，但默认不在链首——
  因为它需要先缓存 opt_basic 合约表（13,124 行 / ~7.5 MB），
  且缓存过期会静默漏算。官方汇总接口没有这个问题。
"""
from __future__ import annotations

import json
import os
from typing import Any, Dict, List, Optional

from ..config import DATA, INDEX_CODES, OPT_ETF, OPT_MAIN
from ..contracts import Provider, ProviderError, ProviderUnavailable

SKILL = r"C:/Users/zky12/.workbuddy/skills/tushare-data/scripts"
_CONTRACTS = os.path.join(DATA, "opt_contracts.json")


def _pro():
    """惰性构造 pro_api，避免没装 tushare 时 import 就炸。"""
    import sys
    if SKILL not in sys.path:
        sys.path.insert(0, SKILL)
    try:
        from get_token import get_token
        import tushare as ts
    except Exception as e:                       # noqa: BLE001
        raise ProviderUnavailable(f"tushare 环境不可用: {e}")
    return ts.pro_api(get_token())


class _TushareBase(Provider):
    _cached_pro = None

    def available(self) -> bool:
        try:
            if _TushareBase._cached_pro is None:
                _TushareBase._cached_pro = _pro()
            return True
        except ProviderUnavailable:
            return False
        except Exception:
            return False

    def pro(self):
        if _TushareBase._cached_pro is None:
            _TushareBase._cached_pro = _pro()
        return _TushareBase._cached_pro


class TushareQuote(_TushareBase):
    name = "tushare_quote"
    domains = ("quote",)
    desc = "Tushare index_daily（备用）"

    def fetch_quote(self, code: str, start: str, end: str) -> List[Dict[str, Any]]:
        df = self.pro().index_daily(ts_code=code, start_date=start, end_date=end)
        if df is None or len(df) == 0:
            raise ProviderError(f"Tushare 无行情 {code}")
        df = df.sort_values("trade_date")
        out = []
        for r in df.to_dict("records"):
            r["trade_date"] = str(r["trade_date"])
            out.append(r)
        return out


class TushareValuation(_TushareBase):
    name = "tushare_valuation"
    domains = ("valuation",)
    desc = "Tushare index_dailybasic（备用，含完整 PE/PB）"

    def fetch_valuation(self, code: str, start: str, end: str) -> List[Dict[str, Any]]:
        df = self.pro().index_dailybasic(ts_code=code, start_date=start, end_date=end)
        if df is None or len(df) == 0:
            raise ProviderError(f"Tushare 无估值 {code}")
        df = df.sort_values("trade_date")
        out = []
        for r in df.to_dict("records"):
            r["trade_date"] = str(r["trade_date"])
            out.append(r)
        return out


class TushareEtfQuote(_TushareBase):
    name = "tushare_etf_quote"
    domains = ("etf_quote",)
    desc = "Tushare fund_daily（备用）"

    def fetch_etf_quote(self, code: str, start: str, end: str) -> List[Dict[str, Any]]:
        df = self.pro().fund_daily(ts_code=code, start_date=start, end_date=end)
        if df is None or len(df) == 0:
            raise ProviderError(f"Tushare 无 ETF 行情 {code}")
        df = df.sort_values("trade_date")
        out = []
        for r in df.to_dict("records"):
            r["trade_date"] = str(r["trade_date"])
            out.append(r)
        return out


class TushareEtfShare(_TushareBase):
    name = "tushare_etf_share"
    domains = ("etf_share",)
    desc = "Tushare fund_share（备用）"

    def fetch_etf_share(self, code: str, start: str, end: str) -> List[Dict[str, Any]]:
        df = self.pro().fund_share(ts_code=code, start_date=start, end_date=end)
        if df is None or len(df) == 0:
            raise ProviderError(f"Tushare 无 ETF 份额 {code}")
        df = df.sort_values("trade_date")
        out = []
        for r in df.to_dict("records"):
            r["trade_date"] = str(r["trade_date"])
            out.append({"trade_date": r["trade_date"],
                        "fd_share": r.get("fd_share")})
        return out


class TusharePcr(_TushareBase):
    """逐合约汇总 PCR —— 旧管线 fetch2b.py 的逻辑，保留为兜底。"""

    name = "tushare_pcr"
    domains = ("option_pcr",)
    desc = "Tushare opt_basic + opt_daily 逐合约汇总（备用，需合约缓存）"

    def fetch_option_pcr(self, start: str, end: str,
                         targets: Optional[List[str]] = None) -> List[Dict[str, Any]]:
        c2u, c2d = self._contracts()
        live = {k: v for k, v in c2u.items() if str(c2d.get(k, "")) >= start}
        if not live:
            raise ProviderError("Tushare 合约缓存为空或已过期")

        by_oc: Dict[str, Dict] = {}
        for ts_code, opt_code in live.items():
            by_oc.setdefault(opt_code, []).append(ts_code)

        rows: List[Dict[str, Any]] = []
        for oc, codes in by_oc.items():
            if oc not in OPT_MAIN and oc not in OPT_ETF:
                continue
            ex = "SSE" if oc.endswith(".SH") else "SZSE"
            acc: Dict[str, Dict] = {}
            for i in range(0, len(codes), 200):
                chunk = codes[i:i + 200]
                try:
                    df = self.pro().opt_daily(ts_code=",".join(chunk),
                                              start_date=start, end_date=end)
                except Exception:
                    continue
                if df is None or len(df) == 0:
                    continue
                for r in df.to_dict("records"):
                    d = str(r["trade_date"])
                    cp = "C" if str(r.get("call_put", "")).upper().startswith("C") else "P"
                    a = acc.setdefault(d, {"c_oi": 0.0, "p_oi": 0.0, "c_vol": 0.0,
                                           "p_vol": 0.0, "c_amt": 0.0, "p_amt": 0.0})
                    oi = float(r.get("oi") or 0)
                    vol = float(r.get("vol") or 0)
                    amt = float(r.get("amount") or 0)
                    if cp == "C":
                        a["c_oi"] += oi; a["c_vol"] += vol; a["c_amt"] += amt
                    else:
                        a["p_oi"] += oi; a["p_vol"] += vol; a["p_amt"] += amt
            for d, a in acc.items():
                rows.append({
                    "date": d, "oc": oc,
                    "c_oi": a["c_oi"], "p_oi": a["p_oi"],
                    "c_vol": a["c_vol"], "p_vol": a["p_vol"],
                    "c_amt": round(a["c_amt"], 4), "p_amt": round(a["p_amt"], 4),
                    "oi_pcr": round(a["p_oi"] / a["c_oi"], 6) if a["c_oi"] else None,
                    "vol_pcr": round(a["p_vol"] / a["c_vol"], 6) if a["c_vol"] else None,
                })
        if not rows:
            raise ProviderError("Tushare PCR 汇总无结果")
        rows.sort(key=lambda r: (r["date"], r["oc"]))
        return rows

    @staticmethod
    def _contracts():
        if not os.path.exists(_CONTRACTS):
            raise ProviderError("缺少 opt_contracts.json 合约缓存")
        c = json.load(open(_CONTRACTS, encoding="utf-8"))
        if not c.get("map") or not c.get("delist"):
            raise ProviderError("合约缓存结构不完整")
        return c["map"], c["delist"]
