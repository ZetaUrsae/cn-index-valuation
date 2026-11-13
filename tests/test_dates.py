# -*- coding: utf-8 -*-
"""日期工具：月末夹取、闰年、跨年。

`_shift` 被增量取数、区间补缺、月锚归档等多处依赖，一旦错一天，
表现是"某天数据莫名缺失"或"重复取数"，很难从结果反推。
"""
from ivdata.pipeline import _d, _shift


def test_parse():
    assert _d("20261112").isoformat() == "2026-11-12"


def test_shift_days_cross_month():
    assert _shift("20261031", days=1) == "20261101"
    assert _shift("20260101", days=-1) == "20251231"


def test_shift_month_clamps_day():
    """8/31 加一个月应落在 9/30，而不是抛异常或溢出到 10/1。"""
    assert _shift("20260831", months=1) == "20260930"


def test_shift_leap_year():
    assert _shift("20240229", years=1) == "20250228"
    assert _shift("20240229", years=4) == "20280229"


def test_shift_months_cross_year():
    assert _shift("20261215", months=1) == "20270115"
    assert _shift("20260110", months=-2) == "20251110"


def test_shift_zero_is_identity():
    assert _shift("20261112") == "20261112"
