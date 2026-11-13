# -*- coding: utf-8 -*-
"""归一化：单位换算与字段补齐。

这几条是"数字对不上"最容易出问题的地方（股/手、元/万元、权重聚合），
而且都能用构造数据验证，不需要联网。
"""
from ivdata.pipeline import _norm_etf_quote, _norm_pcr, _norm_quote, _norm_valuation


def test_quote_volume_shares_to_lots():
    row = _norm_quote({"trade_date": "20261112", "close": 10.0, "vol": 1_234_500})
    assert row["vol"] == 12345.0
    assert row["trade_date"] == "20261112"


def test_quote_amount_derived_from_lots():
    """amount 缺失时由 close × vol(手) × 100 股 / 1000 折算成千元。"""
    row = _norm_quote({"trade_date": "20261112", "close": 10.0, "vol": 100_000})
    assert row["vol"] == 1000.0
    assert row["amount"] == round(10.0 * 1000 * 100 / 1000.0, 4)


def test_quote_amount_kept_when_provided():
    row = _norm_quote({"trade_date": "20261112", "close": 10.0,
                       "vol": 100_000, "amount": 999.5})
    assert row["amount"] == 999.5


def test_etf_quote_keeps_code_and_unit():
    row = _norm_etf_quote("510300.SH", {"trade_date": "20261112",
                                        "close": 4.0, "vol": 1000})
    assert row["ts_code"] == "510300.SH"
    assert row["vol"] == 10.0


def test_valuation_fills_missing_fields():
    row = _norm_valuation({"trade_date": "20261112", "pe_ttm": 13.82, "pb": 1.4})
    assert row["pe_ttm"] == 13.82
    assert row["pb"] == 1.4
    assert row["total_mv"] is None          # 缺失字段补 None，下游能容忍


def test_pcr_rounding():
    row = _norm_pcr({"date": "20261112", "oc": "OP510300.SH",
                     "c_oi": 1234.5678, "p_oi": 2345.6789,
                     "oi_pcr": 1.23456789, "vol_pcr": "bad"})
    assert row["c_oi"] == 1234.57
    assert row["oi_pcr"] == 1.234568
    assert row["vol_pcr"] is None           # 脏值不炸，落 None
