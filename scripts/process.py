# -*- coding: utf-8 -*-
"""计算 1/2：估值分位、区间涨跌、隐含ROE（依赖 raw.json）"""
import sys, os, json, math
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import cfg
import numpy as np

BASE = cfg.BASE
ASOF = cfg.ASOF
YEAR = ASOF[:4]
M1 = cfg.shift(ASOF, months=-1)     # 近1月基准
Y1 = cfg.shift(ASOF, years=-1)      # 近1年基准
Y5 = cfg.shift(ASOF, years=-5)      # 近5年窗口下界
Y10 = cfg.shift(ASOF, years=-10)    # 近10年窗口下界

raw = json.load(open(BASE + "data/raw.json", encoding="utf-8"))

# 指数收盘价历史（fetch_close_hist.py 维护）→ 点位分位 / 近10年·近5年点位中位数
Y10_ISO = cfg.fmt(Y10)
Y5_ISO = cfg.fmt(Y5)
CLOSE_HIST = {}
if os.path.exists(BASE + "data/close_history.json"):
    CLOSE_HIST = json.load(open(BASE + "data/close_history.json", encoding="utf-8"))


def pctile(series, val):
    s = np.array([x for x in series if x is not None and not (isinstance(x, float) and math.isnan(x))], dtype=float)
    s = s[s > 0]
    if len(s) == 0 or val is None:
        return None
    return round(float((s < val).sum()) / len(s) * 100, 1)


result = {}
for code, d in raw.items():
    name = d["name"]
    basic = sorted(d["basic"], key=lambda r: r["trade_date"])
    daily = sorted(d["daily"], key=lambda r: r["trade_date"])
    latest = basic[-1]
    close = daily[-1]["close"]

    # 年内涨跌：以 ASOF 所在年份的上一年最后一个交易日收盘为基准
    prev = [r for r in daily if r["trade_date"] < YEAR + "0101"]
    ytd_base = prev[-1]["close"] if prev else None
    ytd = round((close / ytd_base - 1) * 100, 2) if ytd_base else None

    m1 = [r for r in daily if r["trade_date"] >= M1]
    ret1m = round((close / m1[0]["close"] - 1) * 100, 2) if m1 else None
    y1 = [r for r in daily if r["trade_date"] <= Y1]
    ret1y = round((close / y1[-1]["close"] - 1) * 100, 2) if y1 else None

    pe_ttm_series = [r["pe_ttm"] for r in basic]
    pb_series = [r["pb"] for r in basic]
    b5 = [r for r in basic if r["trade_date"] >= Y5]
    b10 = [r for r in basic if r["trade_date"] >= Y10]

    # 点位分位：当日收盘 vs 近10年日频收盘价分布（与 PE/PB 分位同式）。
    # 科创50 的 close_history 自 2020-07 上市起，窗口自然退化为上市以来。
    _hist = CLOSE_HIST.get(code) or {}
    _win = [v for d, v in sorted(_hist.items()) if d >= Y10_ISO and v]
    close_pct = pctile(_win, close)
    close_med = round(float(np.median(_win)), 2) if _win else None
    close_from = min(d for d in _hist if _hist[d]) if _win else None
    _win5 = [v for d, v in sorted(_hist.items()) if d >= Y5_ISO and v]
    close_med5 = round(float(np.median(_win5)), 2) if _win5 else None

    res = {
        "code": code, "name": name, "date": latest["trade_date"], "close": close,
        "pe": latest["pe"], "pe_ttm": latest["pe_ttm"], "pb": latest["pb"],
        "total_mv": latest["total_mv"], "float_mv": latest["float_mv"],
        "turnover": latest["turnover_rate_f"],
        "pe_ttm_pct_all": pctile(pe_ttm_series, latest["pe_ttm"]),
        "pb_pct_all": pctile(pb_series, latest["pb"]),
        "pe_ttm_pct_5y": pctile([r["pe_ttm"] for r in b5], latest["pe_ttm"]),
        "pb_pct_5y": pctile([r["pb"] for r in b5], latest["pb"]),
        "pe_ttm_pct_10y": pctile([r["pe_ttm"] for r in b10], latest["pe_ttm"]),
        "pb_pct_10y": pctile([r["pb"] for r in b10], latest["pb"]),
        "close_pct_10y": close_pct, "close_med_10y": close_med, "close_med_5y": close_med5,
        "close_pct_from": close_from,
        "hist_start": basic[0]["trade_date"], "hist_end": basic[-1]["trade_date"], "hist_n": len(basic),
        "pe_ttm_min": round(min([x for x in pe_ttm_series if x and x > 0]), 2),
        "pe_ttm_max": round(max([x for x in pe_ttm_series if x and x > 0]), 2),
        "pe_ttm_med": round(float(np.median([x for x in pe_ttm_series if x and x > 0])), 2),
        "pb_min": round(min([x for x in pb_series if x and x > 0]), 2),
        "pb_max": round(max([x for x in pb_series if x and x > 0]), 2),
        "pb_med": round(float(np.median([x for x in pb_series if x and x > 0])), 2),
        "ytd": ytd, "ret1m": ret1m, "ret1y": ret1y,
        "implied_roe": round(latest["pb"] / latest["pe_ttm"] * 100, 2) if latest["pe_ttm"] else None,
    }
    result[code] = res
    print(f"{name}: PE_TTM={res['pe_ttm']} 分位10Y={res['pe_ttm_pct_10y']}% PB={res['pb']} "
          f"点位分位={close_pct}% 中位={close_med} YTD={ytd}%", flush=True)

json.dump(result, open(BASE + "work/metrics.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
print("saved metrics.json (ASOF=%s, 近5年>=%s, 近10年>=%s)" % (cfg.ASOF_FMT, Y5, Y10))
