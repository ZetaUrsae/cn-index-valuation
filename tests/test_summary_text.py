# -*- coding: utf-8 -*-
"""总结段（Takeaways）的判断文字必须由数据算出来。

同时守住两条回归线：模板/生成脚本里不再出现会过期的时间锚点，
也不再写死"均在均线下方"这类与明细可能矛盾的绝对断言。
"""
import os

from ivdata import paths
from summary_text import (combo_sentence, low_pcr_sentence, ma_below_counts,
                          ma_sentence, pcr_regime, pcr_values)


def _rows(pcts, above20, above60=None, above250=None):
    """造测试行；后两条均线默认跟随 above20，方便只关心其中一条的用例。"""
    return [{"pcr": {"oi_pct": p},
             "tech": {"above_ma20": a,
                      "above_ma60": b if above60 is not None else a,
                      "above_ma250": c if above250 is not None else a}}
            for p, a, b, c in zip(
                pcts, above20,
                above60 if above60 is not None else above20,
                above250 if above250 is not None else above20)]


# ---------------------------------------------------------------- PCR

def test_pcr_values_skips_missing():
    rows = [{"pcr": {"oi_pct": 12.3}}, {"pcr": {"oi_pct": None}}, {"pcr": {}}]
    assert pcr_values(rows) == [12.3]


def test_pcr_regime_boundaries():
    assert pcr_regime([10, 15, 19.9]) == "整体处样本区间偏低位置"
    assert pcr_regime([20, 50, 80]) == "多数处于样本区间中位"
    assert pcr_regime([80.1, 90]) == "整体处样本区间偏高位置"
    assert pcr_regime([15, 25]) == "多数处于样本区间中位"   # 偶数个取中位数
    assert "样本不足" in pcr_regime([])


def test_low_pcr_sentence_depends_on_count():
    assert "一致性偏乐观" in low_pcr_sentence([5, 8, 11, 15])
    assert "但仅 2 只" in low_pcr_sentence([5, 8, 40, 60])
    assert "未普遍" in low_pcr_sentence([30, 40, 60])


# ---------------------------------------------------------------- 均线

def test_ma_counts_are_data_driven():
    rows = _rows([1] * 5, [2.53, 0.17, -0.82, -2.41, -9.0])
    assert ma_below_counts(rows)[0] == 3
    assert "3/5 只在 20 日线下方" in ma_sentence(rows)


def test_ma_sentence_never_claims_all_below_when_some_are_above():
    rows = _rows([1] * 5, [2.53, 0.17, -0.82, -2.41, -9.0])
    sentence = ma_sentence(rows)
    assert "五指数当前均位于" not in sentence
    assert "3/5" in sentence


def test_ma_counts_all_below():
    assert ma_below_counts(_rows([1] * 5, [-1] * 5)) == (5, 5, 5)


# ---------------------------------------------------------------- 组合含义

def test_combo_sentence_three_regimes():
    strong = combo_sentence(4, 5, "创业板指", "上证50")
    weak = combo_sentence(0, 0, "创业板指", "上证50")
    mixed = combo_sentence(2, 3, "创业板指", "上证50")
    assert "估值与资金先行" in strong
    assert "量价共振" in weak
    assert "信号分化" in mixed and "资金回补 2/5" in mixed


def test_combo_sentence_has_no_time_anchor():
    assert "三季报" not in combo_sentence(2, 3, "A", "B")


# ---------------------------------------------------------------- 回归护栏

def test_active_sources_have_no_stale_wording():
    src = {}
    for rel in ("scripts/gen2.py", "scripts/template2.html"):
        src[rel] = io_read(os.path.join(paths.ROOT, rel))
    for name, text in src.items():
        assert "三季报" not in text, name
        assert "位于20/60/250日均线下方" not in text, name
        assert "五指数当前均位于" not in text, name
    # 技术面表格的涨跌样式必须按数值算，不能写死 down
    assert '<td class="down">\'+fmt(t.above_ma20' not in src["scripts/template2.html"]


def io_read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()
