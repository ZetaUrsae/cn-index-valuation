# -*- coding: utf-8 -*-
"""ivdata.contracts —— provider 接口与统一数据结构。

所有 provider 都返回 **dict 列表**，字段名与旧管线（raw.json / pcr_raw.csv /
etf_raw.json）完全一致，这样下游 process/tech/proc2/gen2 不需要任何改动。
"""
from __future__ import annotations

import abc
from dataclasses import dataclass, asdict
from typing import Any, Dict, List, Optional


# ---------------------------------------------------------------- 数据结构

@dataclass
class QuoteBar:
    """指数 / ETF 日线（OHLCV + 成交额），字段与库内历史数据对齐。"""
    trade_date: str          # YYYYMMDD
    close: float
    open: Optional[float] = None
    high: Optional[float] = None
    low: Optional[float] = None
    pre_close: Optional[float] = None
    change: Optional[float] = None
    pct_chg: Optional[float] = None
    vol: Optional[float] = None       # 手 / 股，按源不同，仅作量比使用
    amount: Optional[float] = None    # 千元

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class ValuationRow:
    """指数估值（PE/PB/市值/换手等），字段与库内历史数据对齐。"""
    trade_date: str
    pe: Optional[float] = None
    pe_ttm: Optional[float] = None
    pb: Optional[float] = None
    turnover_rate: Optional[float] = None
    turnover_rate_f: Optional[float] = None
    total_mv: Optional[float] = None      # 万元
    float_mv: Optional[float] = None
    total_share: Optional[float] = None
    float_share: Optional[float] = None
    free_share: Optional[float] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class OptionPcrRow:
    """标的级 PCR，对齐 pcr_raw.csv 字段。"""
    date: str                 # YYYYMMDD
    oc: str                   # OP510300.SH
    c_oi: float = 0.0
    p_oi: float = 0.0
    c_vol: float = 0.0
    p_vol: float = 0.0
    c_amt: Optional[float] = None
    p_amt: Optional[float] = None
    oi_pcr: Optional[float] = None
    vol_pcr: Optional[float] = None

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        if d["oi_pcr"] is None and d["c_oi"]:
            d["oi_pcr"] = round(d["p_oi"] / d["c_oi"], 6)
        if d["vol_pcr"] is None and d["c_vol"]:
            d["vol_pcr"] = round(d["p_vol"] / d["c_vol"], 6)
        return d


@dataclass
class EtfShareRow:
    """ETF 份额（单位：万份）。"""
    trade_date: str
    fd_share: float

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class Prov:
    """一次取数的溯源记录。"""
    domain: str
    provider: str
    ok: bool
    rows: int = 0
    elapsed: float = 0.0
    fallback_from: List[str] = None
    error: str = ""
    asof: str = ""
    note: str = ""

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["fallback_from"] = self.fallback_from or []
        return d


# ---------------------------------------------------------------- 异常

class ProviderError(Exception):
    """provider 取数失败（可降级到下一个源）。"""


class ProviderUnavailable(ProviderError):
    """provider 依赖缺失（如缺少本地缓存/配置）——直接跳过，不重试。"""


class ProviderNotApplicable(ProviderUnavailable):
    """该源不覆盖这个标的（如沪市接口拿到深市代码）——正常跳过，不算失败。

    继承 ``ProviderUnavailable`` 是为了复用 Registry 的「跳过不记错」分支：
    否则 ``etf_share`` 链上每只深市 ETF 每天都会在溯源里留一条假失败。
    """


class QualityCheckFailed(ProviderError):
    """取数成功但数据不满足质量要求。"""


# ---------------------------------------------------------------- 接口

class Provider(abc.ABC):
    """所有数据源的基类。

    子类至少实现 ``name`` 与对应域的取数方法。方法失败请抛 ProviderError。
    """

    #: 注册名，需与 config.DOMAINS 中的字符串一致
    name: str = ""
    #: 支持的数据域
    domains: tuple = ()
    #: 人类可读说明
    desc: str = ""

    # ---- 各域取数接口（子类按需覆写）--------------------------------
    def fetch_quote(self, code: str, start: str, end: str) -> List[Dict[str, Any]]:
        raise ProviderUnavailable(f"{self.name} 不支持 quote")

    def fetch_valuation(self, code: str, start: str, end: str) -> List[Dict[str, Any]]:
        raise ProviderUnavailable(f"{self.name} 不支持 valuation")

    def fetch_option_pcr(self, start: str, end: str,
                         targets: Optional[List[str]] = None) -> List[Dict[str, Any]]:
        raise ProviderUnavailable(f"{self.name} 不支持 option_pcr")

    def fetch_etf_share(self, code: str, start: str, end: str) -> List[Dict[str, Any]]:
        raise ProviderUnavailable(f"{self.name} 不支持 etf_share")

    def fetch_bond10y(self, start: str, end: str) -> List[Dict[str, Any]]:
        raise ProviderUnavailable(f"{self.name} 不支持 bond10y")

    def fetch_calendar(self, start: str, end: str) -> List[str]:
        raise ProviderUnavailable(f"{self.name} 不支持 calendar")

    # ---- 工具 -----------------------------------------------------
    def available(self) -> bool:
        """依赖是否就绪。返回 False 时 registry 直接跳过、不计为失败。"""
        return True

    def __repr__(self) -> str:
        return f"<{type(self).__name__} {self.name}>"
