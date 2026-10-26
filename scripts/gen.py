# -*- coding: utf-8 -*-
import json, math
from collections import OrderedDict

raw = json.load(open("D:/QClaw/Stock/index_valuation/data/raw.json", encoding="utf-8"))
met = json.load(open("D:/QClaw/Stock/index_valuation/work/metrics.json", encoding="utf-8"))

order = ["000016.SH","000300.SH","000905.SH","399006.SZ","000688.SH"]

# 股息率 (中证指数公司口径, 2026-10-13) + 10Y国债
DIV = {"000016.SH":3.1687,"000300.SH":2.7006,"000905.SH":1.4518,"399006.SZ":1.0751,"000688.SH":0.2709}
BOND10Y = 1.6654

rows = []
for c in order:
    m = met[c]
    ep = 100.0/m["pe_ttm"]                    # 盈利收益率 %
    rp = ep - BOND10Y                          # 股债性价比/风险溢价
    rows.append({
        "code": c, "name": m["name"],
        "close": m["close"],
        "pe_ttm": m["pe_ttm"], "pe": m["pe"], "pb": m["pb"],
        "pe_pct": m["pe_ttm_pct_10y"], "pb_pct": m["pb_pct_10y"],
        "pe_pct_5y": m["pe_ttm_pct_5y"], "pb_pct_5y": m["pb_pct_5y"],
        "div": DIV[c],
        "mv": m["total_mv"]/1e12,
        "roe": m["implied_roe"],
        "ytd": m["ytd"], "m1": m["ret1m"], "y1": m["ret1y"],
        "ep": ep, "rp": rp,
        "pe_med": m["pe_ttm_med"], "pb_med": m["pb_med"],
        "pe_min": m["pe_ttm_min"], "pe_max": m["pe_ttm_max"],
        "hist_from": m["hist_start"][:4],
        "bleed": "亏损" if False else "",
    })

def status(p):
    if p is None: return ("—", "na")
    if p < 20: return ("低估", "s1")
    if p < 40: return ("偏低估", "s2")
    if p < 60: return ("适中", "s3")
    if p < 80: return ("偏高", "s4")
    return ("高估", "s5")

for r in rows:
    r["st"], r["stc"] = status(r["pe_pct"])

# 月度 PE(TTM) 序列（近37个月末）
def month_end_series(code, months=37):
    d = sorted(raw[code]["basic"], key=lambda x: x["trade_date"])
    buckets = OrderedDict()
    for x in d:
        buckets[x["trade_date"][:6]] = x
    keys = list(buckets.keys())[-months:]
    labels = [k[:4]+"-"+k[4:] for k in keys]
    vals = [round(buckets[k]["pe_ttm"],2) if buckets[k]["pe_ttm"] and buckets[k]["pe_ttm"]>0 else None for k in keys]
    return labels, vals

labels, _ = month_end_series("000300.SH")
series_map = {}
for c in order:
    _, v = month_end_series(c)
    series_map[met[c]["name"]] = v

# 历史极值区间(PE_TTM) 用于条形背景范围: 0 .. max(pe_ttm_max)
pe_axis_max = max(r["pe_max"] for r in rows)

DATA = {
  "asof": "2026-10-14",
  "divAsof": "2026-10-13",
  "bond10y": BOND10Y,
  "rows": rows,
  "months": labels,
  "peSeries": series_map,
  "peAxisMax": round(pe_axis_max,1),
}

html = open("D:/QClaw/Stock/index_valuation/scripts/template.html", encoding="utf-8").read()
html = html.replace("/*__DATA__*/", "const DATA = " + json.dumps(DATA, ensure_ascii=False) + ";")
open("D:/QClaw/Stock/index_valuation/宽基指数估值表-20261014.html","w",encoding="utf-8").write(html)
print("generated, rows:", len(rows), "months:", len(labels))
print(json.dumps(DATA["rows"], ensure_ascii=False, indent=1)[:2200])
