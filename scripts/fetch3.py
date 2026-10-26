# -*- coding: utf-8 -*-
"""取数 3/4：ETF 份额与行情（Tushare fund_share / fund_daily）——增量版

本地 etf_raw.json 即历史库：
- 已有缓存时，仅从各序列最后日期往前留 OVERLAP 天的重叠窗口增量补齐，
  与旧历史按 trade_date 合并去重（新值优先），不再全量重拉；
- 缓存缺失或损坏时，自动退回全量模式（份额起点 2023-01-01，行情起点 2023-12-01）。
"""
import sys, os, json
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import cfg
import pandas as pd

pro = cfg.pro_api()
ASOF = cfg.ASOF
BASE = cfg.BASE
OVERLAP = 15

ETFS = ["510300.SH", "510050.SH", "510500.SH", "159915.SZ", "588000.SH"]
MAIN = {"OP510050.SH": "上证50", "OP510300.SH": "沪深300", "OP510500.SH": "中证500",
        "OP159915.SZ": "创业板指", "OP588000.SH": "科创50"}

RAWF = BASE + "data/etf_raw.json"
old = {}
if os.path.exists(RAWF):
    try:
        old = json.load(open(RAWF, encoding="utf-8"))
        if not isinstance(old, dict) or "shares" not in old:
            old = {}
    except Exception as e:
        print("etf_raw.json 缓存无效，改为全量拉取:", str(e)[:80], flush=True)
        old = {}


def norm(df):
    if df is None or len(df) == 0:
        return pd.DataFrame(columns=["trade_date"])
    df = df.copy()
    df["trade_date"] = df["trade_date"].astype(str)
    return df.sort_values("trade_date").reset_index(drop=True)


def merge(odf, ndf):
    if not len(ndf):
        return odf if len(odf) else ndf
    if len(odf):
        cut = str(ndf["trade_date"].min())
        odf = odf[odf["trade_date"].astype(str) < cut]
    df = pd.concat([odf, ndf], ignore_index=True)
    return df.drop_duplicates(subset="trade_date", keep="last") \
             .sort_values("trade_date").reset_index(drop=True)


def inc_fetch(api_fn, start_default, old_records, code, label):
    odf = pd.DataFrame(old_records or [])
    if len(odf):
        last = str(odf["trade_date"].max())
        start = cfg.shift(last, days=-OVERLAP)
        mode = "增量"
    else:
        start = start_default
        mode = "全量"
    ndf = norm(api_fn(ts_code=code, start_date=start, end_date=ASOF))
    df = merge(odf, ndf)
    print(f"{code} {label}: {mode} {start}~{ASOF} new={len(ndf)} -> total={len(df)}", flush=True)
    return df


shares, fdaily = {}, {}
for code in ETFS:
    df = inc_fetch(lambda ts_code, start_date, end_date: pro.fund_share(
        ts_code=ts_code, start_date=start_date, end_date=end_date),
        "20230101", old.get("shares", {}).get(code), code, "份额")
    shares[code] = df.to_dict("records")
for code in ETFS:
    df = inc_fetch(lambda ts_code, start_date, end_date: pro.fund_daily(
        ts_code=ts_code, start_date=start_date, end_date=end_date),
        "20231201", old.get("fdaily", {}).get(code), code, "行情")
    fdaily[code] = df.to_dict("records")

json.dump({"shares": shares, "fdaily": fdaily, "main": MAIN},
          open(RAWF, "w", encoding="utf-8"), ensure_ascii=False)
print("saved etf_raw.json (ASOF=%s)" % cfg.ASOF_FMT)
