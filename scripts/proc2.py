# -*- coding: utf-8 -*-
import json, math, os
BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__))).replace("\\", "/")
import numpy as np
import pandas as pd


def _d(o):
    if isinstance(o, np.integer):
        return int(o)
    if isinstance(o, np.floating):
        return float(o)
    if isinstance(o, np.bool_):
        return bool(o)
    return str(o)


MAIN2NAME = {"OP510050.SH": "上证50", "OP510300.SH": "沪深300", "OP510500.SH": "中证500",
             "OP159915.SZ": "创业板指", "OP588000.SH": "科创50"}
NAME2ETF = {"上证50": ("510050.SH", "华夏上证50ETF", "上交所"),
            "沪深300": ("510300.SH", "华泰柏瑞沪深300ETF", "上交所"),
            "中证500": ("510500.SH", "南方中证500ETF", "上交所"),
            "创业板指": ("159915.SZ", "易方达创业板ETF", "深交所"),
            "科创50": ("588000.SH", "华夏上证科创板50成份ETF", "上交所")}
ORDER = ["上证50", "沪深300", "中证500", "创业板指", "科创50"]
OC2NAME = {v: k for k, v in MAIN2NAME.items()}


def pct(series, v):
    a = np.array([x for x in series if x is not None and np.isfinite(x)], dtype=float)
    if len(a) == 0:
        return None
    return round(float((a < v).sum()) / len(a) * 100, 1)


# ---------------- PCR ----------------
pcr = pd.read_csv(BASE + "data/pcr_raw.csv", dtype={"date": str})

res = {}
for name in ORDER:
    oc = OC2NAME[name]
    g = pcr[pcr["oc"] == oc].sort_values("date")
    oi = g["oi_pcr"].replace([np.inf, -np.inf], np.nan).dropna().tolist()
    vo = g["vol_pcr"].replace([np.inf, -np.inf], np.nan).dropna().tolist()
    cur_oi = float(oi[-1]) if oi else None
    cur_vo = float(vo[-1]) if vo else None
    res[name] = {
        "oc": oc, "n": int(len(g)), "start": str(g["date"].min()), "end": str(g["date"].max()),
        "oi_pcr": round(cur_oi, 3) if cur_oi else None,
        "oi_pcr_pct": pct(oi, cur_oi) if cur_oi else None,
        "oi_pcr_med": round(float(np.median(oi)), 3) if oi else None,
        "oi_pcr_min": round(float(np.min(oi)), 3) if oi else None,
        "oi_pcr_max": round(float(np.max(oi)), 3) if oi else None,
        "oi_pcr_p25": round(float(np.percentile(oi, 25)), 3) if oi else None,
        "oi_pcr_ma20": round(float(np.mean(oi[-20:])), 3) if len(oi) >= 20 else None,
        "vol_pcr": round(cur_vo, 3) if cur_vo else None,
        "vol_pcr_pct": pct(vo, cur_vo) if cur_vo else None,
        "vol_pcr_ma20": round(float(np.mean(vo[-20:])), 3) if len(vo) >= 20 else None,
    }
    tail = g.tail(250)[["date", "oi_pcr", "vol_pcr"]].iloc[::4]
    res[name]["series"] = [
        {"d": str(r["date"]),
         "oi": round(float(r["oi_pcr"]), 3) if np.isfinite(r["oi_pcr"]) else None,
         "vol": round(float(r["vol_pcr"]), 3) if np.isfinite(r["vol_pcr"]) else None}
        for _, r in tail.iterrows()]

json.dump(res, open(BASE + "work/pcr.json", "w", encoding="utf-8"),
          ensure_ascii=False, indent=1, default=_d)
print("=== PCR (认沽/认购) ===")
for n in ORDER:
    v = res[n]
    print(f"{n:<6} OI-PCR={v['oi_pcr']} 分位={v['oi_pcr_pct']}% 中位={v['oi_pcr_med']} 区间[{v['oi_pcr_min']},{v['oi_pcr_max']}] 20日均={v['oi_pcr_ma20']} | VOL-PCR={v['vol_pcr']} 分位={v['vol_pcr_pct']}% 样本{v['n']}日")

# ---------------- ETF shares ----------------
etf = json.load(open(BASE + "data/etf_raw.json", encoding="utf-8"))
sh = etf["shares"]
fd = etf["fdaily"]
shres = {}
for name in ORDER:
    code, fname, exch = NAME2ETF[name]
    rec = sorted(sh[code], key=lambda x: x["trade_date"])
    ds = [r["trade_date"] for r in rec]
    vs = [r["fd_share"] / 10000.0 for r in rec]
    last, lastd = vs[-1], ds[-1]
    # YTD 基准：数据所在年份的上一年最后一个交易日。
    # ⚠ 不要写成 "20260101"——跨年后会永久失效（虽然不报错，但 YTD 会变成全历史涨幅）。
    # 这里用 lastd 而非 ASOF：份额发布可能滞后于行情，按数据自身的年份算才不会错位。
    y0 = [i for i, x in enumerate(ds) if x < lastd[:4] + "0101"]
    y0v = vs[y0[-1]] if y0 else None

    def chg(back):
        i = len(vs) - 1 - back
        if i < 0:
            return None, None
        return round(last - vs[i], 2), round((last / vs[i] - 1) * 100, 2)

    c5, c5p = chg(5)
    c20, c20p = chg(20)
    c60, c60p = chg(60)

    fr = sorted(fd[code], key=lambda x: x["trade_date"])
    price = fr[-1]["close"] if fr else None
    amount = fr[-1]["amount"] if fr else None

    shres[name] = {
        "code": code, "fname": fname, "exch": exch, "date": str(lastd),
        "share": round(last, 2), "price": price, "amount": amount,
        "d5": c5, "d5p": c5p, "d20": c20, "d20p": c20p, "d60": c60, "d60p": c60p,
        "ytd": round(last - y0v, 2) if y0v else None,
        "ytdp": round((last / y0v - 1) * 100, 2) if y0v else None,
        "hi": round(max(vs), 2), "lo": round(min(vs), 2),
        "series": [{"d": ds[i], "v": round(vs[i], 1)}
                   for i in range(0, len(ds), max(1, len(ds) // 70))],
    }
    print(f"{name:<6} {code} {fname} 份额={last:.1f}亿份({lastd}) 5日{c5:+} 20日{c20:+}({c20p}%) 60日{c60:+}({c60p}%) YTD{shres[name]['ytd']:+}({shres[name]['ytdp']}%) 收盘{price}")

json.dump(shres, open(BASE + "work/shares.json", "w", encoding="utf-8"),
          ensure_ascii=False, indent=1, default=_d)
print("saved pcr.json / shares.json")
