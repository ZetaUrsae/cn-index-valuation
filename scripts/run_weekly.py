# -*- coding: utf-8 -*-
"""一键跑完整个报告管线（按参考交易日自动取数）

用法:
    python run_weekly.py                # 参考日 = 今天之前最近的开市日
    ASOF=20261009 python run_weekly.py  # 指定参考日

顺序: 估值取数 -> 估值计算 -> 技术面 -> 期权PCR(增量) -> ETF份额 -> 期权元信息
      -> PCR/份额指标 -> 技术面扩展 -> 10Y收益率尾部 -> 组装报告

产出: ../reports/index_val_report_<ASOF>.html（只保留日期戳文件，不再生成 _latest 副本）
"""
import os
import sys
import time
import subprocess

SCRIPTS = os.path.dirname(os.path.abspath(__file__))   # scripts/
ROOT = os.path.dirname(SCRIPTS)                        # index_valuation/
PY = sys.executable

sys.path.insert(0, SCRIPTS)
import cfg

STEPS = [
    ("估值取数", "fetch.py"),
    ("估值计算", "process.py"),
    ("技术面指标", "tech.py"),
    ("期权PCR(增量)", "fetch2b.py"),
    ("ETF份额/行情", "fetch3.py"),
    ("期权元信息", "meta.py"),
    ("PCR与份额指标", "proc2.py"),
    ("技术面扩展", "prep.py"),
    ("10Y国债收益率(尾部)", "fetch_yield_tail.py"),
    ("组装报告", "gen2.py"),
]

print("=" * 64)
print("宽基指数估值与多维跟踪 · 日报管线   参考交易日 ASOF =", cfg.ASOF_FMT)
print("=" * 64)

env = dict(os.environ, ASOF=cfg.ASOF)
t0 = time.time()
failed = []
for i, (label, script) in enumerate(STEPS, 1):
    print(f"\n[{i}/{len(STEPS)}] {label} ({script}) ...", flush=True)
    r = subprocess.run([PY, "-u", os.path.join(SCRIPTS, script)], cwd=SCRIPTS, env=env,
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    tail = (r.stdout or "").strip().splitlines()
    for line in tail[-6:]:
        print("    " + line)
    if r.returncode != 0:
        print("    !! 失败 rc=%s" % r.returncode)
        print((r.stderr or "")[-1200:])
        failed.append(script)
        break

if not failed:
    out = os.path.join(cfg.REPORTS, "index_val_report_%s.html" % cfg.ASOF)
    print("\n" + "=" * 64)
    print("完成，用时 %.0fs" % (time.time() - t0))
    print("输出:", out)

sys.exit(1 if failed else 0)
