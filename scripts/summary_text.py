# -*- coding: utf-8 -*-
"""总结（Takeaways）里的判断性文字 —— 全部由数据算出来。

背景（2026-11-26）：`gen2.py` 的总结段曾是"数字动态、判断写死"——
PCR「整体偏低」、④「五指数均位于 20/60/250 日均线下方」、⑤「需以三季报盈利兑现为关键验证」
都是固定字符串。2026-11-12 那份报告里，上证50 与 科创50 实际在 20 日线上方（+0.17% / +2.53%），
总结与明细却都写着"均在下方"，且正数被渲染成绿色（A 股惯例绿色为跌）。

本模块只放**纯函数**：不读文件、不联网，便于单测覆盖各种行情状态。
"""
from __future__ import annotations

from typing import Any, Dict, List

__all__ = [
    "pcr_values", "pcr_regime", "low_pcr_sentence",
    "ma_below_counts", "ma_sentence", "combo_sentence",
]


def pcr_values(rows: List[Dict[str, Any]]) -> List[float]:
    """取各指数的 PCR 历史分位（跳过缺失值）。"""
    return [float(r["pcr"]["oi_pct"]) for r in rows
            if r.get("pcr") and r["pcr"].get("oi_pct") is not None]


def pcr_regime(pcts: List[float]) -> str:
    """按中位数给 PCR 整体位置分档，替代写死的"整体偏低"。"""
    vals = sorted(p for p in pcts if p is not None)
    if not vals:
        return "分位样本不足，暂不做整体判断"
    n = len(vals)
    med = vals[n // 2] if n % 2 else (vals[n // 2 - 1] + vals[n // 2]) / 2.0
    if med < 20:
        return "整体处样本区间偏低位置"
    if med > 80:
        return "整体处样本区间偏高位置"
    return "多数处于样本区间中位"


def low_pcr_sentence(pcts: List[float]) -> str:
    """③ 里"最低位"的判断：只有足够多的指数同处低位才说一致性。"""
    n = sum(1 for p in pcts if p is not None and p < 20)
    if n >= 4:
        return ("属情绪层面的<b>一致性偏乐观</b>"
                "（反向指标：极端低位常出现在快速反弹之后，而非恐慌底部）")
    if n:
        return "但仅 %d 只处样本低位，分位有所分化" % n
    return "但分位未普遍处于低位，情绪一致性有限"


def ma_below_counts(rows: List[Dict[str, Any]]) -> tuple:
    """返回 (低于20日线数, 低于60日线数, 低于250日线数)，分母统一用 len(rows)。"""
    keys = ("above_ma20", "above_ma60", "above_ma250")
    return tuple(sum(1 for r in rows if (r.get("tech", {}).get(k) or 0) < 0) for k in keys)


def ma_sentence(rows: List[Dict[str, Any]]) -> str:
    """④ 的均线位置：报数，不做"均位于…"的绝对判断。"""
    n20, n60, n250 = ma_below_counts(rows)
    total = len(rows)
    return ("%d/%d 只在 20 日线下方、%d/%d 只在 60 日线下方、%d/%d 只在 250 日线下方"
            % (n20, total, n60, total, n250, total))


def combo_sentence(up_cnt: int, n20: int, cheap: str, rich: str) -> str:
    """⑤ 组合含义：先报估值两端，再按资金/技术的实际计数给结论。"""
    base = ('估值分位偏低一档（%s）属"估值便宜"；分位偏高一档（%s）已不便宜。'
            % (cheap, rich))
    if up_cnt >= 3 and n20 >= 4:
        tail = '资金端多数回补、技术端普遍偏弱，整体呈"<b>估值与资金先行、技术待确认</b>"的组合。'
    elif up_cnt <= 1 and n20 <= 1:
        tail = '资金端与技术端同步转强，组合更接近"<b>量价共振</b>"。'
    else:
        tail = ('资金与技术信号分化（资金回补 %d/5、%d/5 仍在 20 日线下方），'
                '需按指数分别看待。' % (up_cnt, n20))
    return base + tail
