# -*- coding: utf-8 -*-
"""ivdata —— 指数估值日报的数据源层。

设计目标
--------
1. **可插拔**：每个数据源是一个独立 provider 类，实现统一接口；上层只认接口，
   不认具体来源。换源 / 加源不改业务代码。
2. **多源降级**：每个数据域（行情 / 估值 / 期权 / ETF份额 / 国债）配置一条
   优先级链，前一个源失败自动降级到下一个，全部失败才报错。
3. **只走公开源**：全部数据来自新浪 / 东财 / 交易所与中证官网等公开接口，
   不依赖任何需要 token 的收费数据源。
4. **可追溯**：每次取数记录 provenance（哪个源、什么时间、多少行、是否降级），
   写入 work/provenance.json，报告与排错都能查到数据出处。

目录结构
--------
    ivdata/
        config.py       —— 配置与数据域定义
        contracts.py    —— provider 接口与数据结构
        http.py         —— 带限流/重试/超时的 HTTP 客户端
        store.py        —— 增量缓存（历史库读写、合并去重）
        registry.py     —— provider 注册表与降级链调度
        provenance.py   —— 取数溯源记录
        providers/      —— 各数据源实现
"""
from .config import SETTINGS, DOMAINS          # noqa: F401
from .contracts import QuoteBar, ValuationRow, OptionPcrRow, EtfShareRow, Prov  # noqa: F401
from .registry import Registry                 # noqa: F401
from .store import Store                       # noqa: F401

__all__ = ["SETTINGS", "DOMAINS", "Registry", "Store",
           "QuoteBar", "ValuationRow", "OptionPcrRow", "EtfShareRow", "Prov"]
__version__ = "1.0.0"
