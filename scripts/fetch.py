# -*- coding: utf-8 -*-
"""取数 1/4：指数估值与行情（Tushare index_dailybasic / index_daily）——增量版

本地 raw.json 即历史库：
- 已有缓存时，仅从各序列最后日期往前留 OVERLAP 天的重叠窗口增量补齐，
  与旧历史按 trade_date 合并去重（新值优先，兼顾数据修订），不再全量重拉；
- 缓存缺失或损坏时，自动退回全量模式（估值起点 2015-01-01，行情起点 2019-12-01）。
"""
import sys, os, json
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import cfg
import pandas as pd

pro = cfg.pro_api()
ASOF = cfg.ASOF
BASE = cfg.BASE
OVERLAP = 15  # 增量重叠天数：覆盖长假缺口，并允许新值覆盖近期旧值

CODES = [("000300.SH", "沪深300"), ("000016.SH", "上证50"), ("000905.SH", "中证500"),
         ("399006.SZ", "创业板指"), ("000688.SH", "科创50")]

RAW = BASE + "data/raw.json"
old = {}
if os.path.exists(RAW):
    try:
        old = json.load(open(RAW, encoding="utf-8"))
        if not isinstance(old, dict) or not old:
            old = {}
    except Exception as e:
        print("raw.json 缓存无效，改为全量拉取:", str(e)[:80], flush=True)
        old = {}


def norm(df):
    """规范化返回框：保证 trade_date 列存在且为字符串"""
    if df is None or len(df) == 0:
        return pd.DataFrame(columns=["trade_date"])
    df = df.copy()
    df["trade_date"] = df["trade_date"].astype(str)
    return df.sort_values("trade_date").reset_index(drop=True)


def merge(odf, ndf):
    """旧历史 + 新增量合并；同 trade_date 保留新值"""
    if not len(ndf):
        return odf if len(odf) else ndf
    if len(odf):
        cut = str(ndf["trade_date"].min())
        odf = odf[odf["trade_date"].astype(str) < cut]
    df = pd.concat([odf, ndf], ignore_index=True)
    return df.drop_duplicates(subset="trade_date", keep="last") \
             .sort_values("trade_date").reset_index(drop=True)


out = {}
for c, n in CODES:
    o = old.get(c) or {}
    obasic = pd.DataFrame(o.get("basic") or [])
    odaily = pd.DataFrame(o.get("daily") or [])

    def grab(api_fn, start_default, odf, label):
        if len(odf):
            last = str(odf["trade_date"].max())
            start = cfg.shift(last, days=-OVERLAP)
            mode = "增量"
        else:
            start = start_default
            mode = "全量"
        ndf = norm(api_fn(start_date=start, end_date=ASOF))
        df = merge(odf, ndf)
        print(f"{c} {label}: {mode} {start}~{ASOF} new={len(ndf)} -> total={len(df)}", flush=True)
        return df

    basic = grab(lambda **kw: pro.index_dailybasic(ts_code=c, **kw), "20150101", obasic, "估值")
    daily = grab(lambda **kw: pro.index_daily(ts_code=c, **kw), "20191201", odaily, "行情")

    rng_b = f"{basic['trade_date'].min()}~{basic['trade_date'].max()}" if len(basic) else "-"
    rng_d = f"{daily['trade_date'].min()}~{daily['trade_date'].max()}" if len(daily) else "-"
    print(f"{c} {n}: basic={len(basic)} {rng_b}; daily={len(daily)} {rng_d}", flush=True)
    out[c] = {"name": n, "basic": basic.to_dict("records"), "daily": daily.to_dict("records")}

with open(RAW, "w", encoding="utf-8") as f:
    json.dump(out, f, ensure_ascii=False)
print(f"saved raw.json (ASOF={cfg.ASOF_FMT})")
