#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""重算 Sharpe：揭示静态股债平衡的 Sharpe 虚高现象。
原始回测用 rf=0 + 几何收益算 Sharpe，会系统性高估低波动策略。
正确做法：rf=理财收益(2%)，并用算术平均收益(几何+0.5*sigma^2)算超额收益。
"""
import json

with open(r"D:\QClaw\Stock\index_valuation\work\backtest_erp_result.json", encoding="utf-8") as f:
    data = json.load(f)

res = data["price"]["results"]
rf = 0.02  # 银行理财 2%，作为无风险利率

rows = []
for name, m in res.items():
    cagr = m["cagr"]
    vol = m["annvol"]
    # 原始口径：rf=0，几何收益
    sharpe_raw = m["sharpe"]
    # 正确口径：算术超额 / 波动
    arith = cagr + 0.5 * vol * vol
    sharpe_corr = (arith - rf) / vol if vol > 1e-9 else float("nan")
    rows.append((name, cagr, vol, sharpe_raw, sharpe_corr))

# 按类型分组打印
print(f"{'策略':<16}{'年化收益':>10}{'年化波动':>10}{'Sharpe(rf=0)':>16}{'Sharpe(rf=2%)':>16}")
print("-" * 70)
for name, cagr, vol, sr, sc in rows:
    srf = "  NA" if sr != sr else f"{sr:>14.3f}"
    scf = "  NA" if sc != sc else f"{sc:>14.3f}"
    print(f"{name:<16}{cagr*100:>9.2f}%{vol*100:>9.2f}%{srf}{scf}")

print()
print("=== 关键对比（正确口径 rf=2%）===")
static = [(n, c, v, s) for (n, c, v, sr, s) in rows if "平衡" in n]
timing = [(n, c, v, s) for (n, c, v, sr, s) in rows if ("阈值" in n or "z-score" in n or "分位" in n)]
print("静态平衡 Sharpe 区间:",
      f"{min(s for *_, s in static):.3f} ~ {max(s for *_, s in static):.3f}")
print("ERP 择时 Sharpe 区间:",
      f"{min(s for *_, s in timing):.3f} ~ {max(s for *_, s in timing):.3f}")
full = next(s for (n, c, v, sr, s) in rows if n == "满仓沪深300")
print("满仓沪深300 Sharpe:", f"{full:.3f}")
