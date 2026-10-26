# -*- coding: utf-8 -*-
"""本地数据源 —— 本地历史推导。

不依赖网络，作为交易日历域的最后兜底。
10Y 国债已由 `em_bond10y` 单一写入（`data/yield10y_history.json`），
原 `manual_bond10y` 旁路已删除，避免同一指标两个写入者。
"""
from __future__ import annotations

import datetime
from typing import Any, Dict, List

from ..contracts import Provider, ProviderError


class LocalCalendar(Provider):
    """用中证/交易所都不可用时，退化为「工作日即交易日」（不含节假日）。"""

    name = "local_calendar"
    domains = ("calendar",)
    desc = "本地推导交易日（工作日，忽略法定节假日）"

    def fetch_calendar(self, start: str, end: str) -> List[str]:
        d0 = datetime.datetime.strptime(start, "%Y%m%d").date()
        d1 = datetime.datetime.strptime(end, "%Y%m%d").date()
        out, d = [], d0
        while d <= d1:
            if d.weekday() < 5:
                out.append(d.strftime("%Y%m%d"))
            d += datetime.timedelta(days=1)
        if not out:
            raise ProviderError("区间内无工作日")
        return out
