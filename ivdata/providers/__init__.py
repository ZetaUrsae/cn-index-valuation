# -*- coding: utf-8 -*-
"""ivdata.providers —— 各数据源实现。

注册顺序无关；真正决定用哪个源的是 config.DOMAINS 里的优先级链。
"""
from .sina import SinaQuote
from .csi import CsiQuote, CsiValuation
from .em import EmQuote, EmValuation, EmBond10y
from .exchange import (ExchangePcr, ExchangeEtfShare, SzseEtfShare,
                       SzseEtfShareRange, SseCalendar)
from .local import LocalCalendar

PROVIDERS = [
    # 公开源（优先，零 token 依赖）
    SinaQuote,
    EmQuote,
    EmValuation,
    EmBond10y,
    ExchangePcr,
    ExchangeEtfShare,
    SzseEtfShare,
    SzseEtfShareRange,
    SseCalendar,
    LocalCalendar,
    # 仅作交叉校验参考，不参与主链 ——
    # 中证官网只提供静态 PE（无 PB、无创业板指），口径与 PE_TTM 不一致，
    # 放进链里会「成功」地写坏数据，因此只注册供 tools/verify_sources.py 调用。
    CsiValuation,
    CsiQuote,
]

__all__ = ["PROVIDERS"]
