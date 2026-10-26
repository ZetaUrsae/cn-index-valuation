# -*- coding: utf-8 -*-
"""取数 2/4：ETF 期权持仓/成交 聚合为 PCR（增量）

- 合约表缓存到 opt_contracts.json（超过 20 天或缺失时重拉，opt_basic 分页很重）
- PCR 增量：从 pcr_raw.csv 的最后日期往前推 1 个月开始拉，再与旧数据合并
"""
import sys, os, json, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import cfg
import pandas as pd

BASE = cfg.BASE
ASOF = cfg.ASOF
pro = cfg.pro_api()

MAIN = {"OP510050.SH": "上证50", "OP510300.SH": "沪深300", "OP510500.SH": "中证500",
        "OP159915.SZ": "创业板指", "OP588000.SH": "科创50"}

# ---------- 1) 合约表（带缓存） ----------
CACHE = BASE + "data/opt_contracts.json"
need_refresh = True
if os.path.exists(CACHE):
    try:
        c = json.load(open(CACHE, encoding="utf-8"))
        age = (pd.Timestamp(cfg.ASOF_FMT) - pd.Timestamp(c["fetched"])).days
        if age <= 20 and c.get("map"):
            c2u, c2cp, c2d = c["map"], c["cp"], c.get("delist", {})
            need_refresh = False
            print(f"[contracts] cache hit (age={age}d, n={len(c2u)})", flush=True)
    except Exception as e:
        print("[contracts] cache invalid:", str(e)[:80], flush=True)

if need_refresh:
    out = []
    off = 0
    while True:
        df = pro.opt_basic(limit=5000, offset=off)
        if df is None or len(df) == 0:
            break
        out.append(df)
        off += len(df)
        if len(df) < 5000 or off > 400000:
            break
    ob = pd.concat(out, ignore_index=True)
    etf = ob[ob["opt_type"] == "ETF期权"][["ts_code", "opt_code", "call_put", "delist_date"]].copy()
    etf = etf[etf["opt_code"].isin(MAIN.keys())]
    c2u = dict(zip(etf["ts_code"], etf["opt_code"]))
    c2cp = dict(zip(etf["ts_code"], etf["call_put"]))
    c2d = dict(zip(etf["ts_code"], etf["delist_date"].astype(str)))
    json.dump({"fetched": cfg.ASOF_FMT, "map": c2u, "cp": c2cp, "delist": c2d},
              open(CACHE, "w", encoding="utf-8"), ensure_ascii=False)
    print(f"[contracts] refreshed, n={len(c2u)}", flush=True)

# ---------- 2) 增量窗口 ----------
RAW = BASE + "data/pcr_raw.csv"
old = None
start_ym = cfg.shift(ASOF, years=-4)[:6]
if os.path.exists(RAW):
    old = pd.read_csv(RAW, dtype={"date": str})
    if len(old):
        last = str(old["date"].max())
        # 增量：从 last 所在的月份开始（按月接口的最小粒度），不往前多推一个月。
        # 历史已定稿的行一律不重拉，靠脚本末尾的合并逻辑保留旧值。
        start_ym = last[:6]
        print(f"[pcr] incremental from {start_ym} (last={last})", flush=True)


def months(a, b):
    ya, ma = int(a[:4]), int(a[4:6])
    yb, mb = int(b[:4]), int(b[4:6])
    res = []
    while (ya, ma) <= (yb, mb):
        last = [31, 29 if ya % 4 == 0 and (ya % 100 != 0 or ya % 400 == 0) else 28,
                31, 30, 31, 30, 31, 31, 30, 31, 30, 31][ma - 1]
        res.append((f"{ya}{ma:02d}01", f"{ya}{ma:02d}{last:02d}"))
        ma += 1
        if ma > 12:
            ma = 1
            ya += 1
    return res


ms = months(start_ym, ASOF[:6])
print("months to fetch:", len(ms), flush=True)

acc = {}
t0 = time.time()
calls = 0
for s, e in ms:
    for ex in ["SSE", "SZSE"]:
        off = 0
        while True:
            try:
                df = pro.opt_daily(exchange=ex, start_date=s, end_date=e, limit=5000, offset=off)
            except Exception as err:
                print("  ERR", s, ex, off, str(err)[:80], flush=True)
                df = None
            calls += 1
            time.sleep(0.35)
            if df is None or len(df) == 0:
                break
            df = df[df["ts_code"].isin(c2u.keys())]
            if len(df):
                df = df.assign(oc=df["ts_code"].map(c2u), cp=df["ts_code"].map(c2cp))
                g = df.groupby(["trade_date", "oc", "cp"]).agg(
                    oi=("oi", "sum"), vol=("vol", "sum"), amt=("amount", "sum")).reset_index()
                for _, r in g.iterrows():
                    k = (r["trade_date"], r["oc"])
                    d = acc.setdefault(k, {"c_oi": 0.0, "p_oi": 0.0, "c_vol": 0.0,
                                           "p_vol": 0.0, "c_amt": 0.0, "p_amt": 0.0})
                    key = "c" if r["cp"] == "C" else "p"
                    d[key + "_oi"] += r["oi"]
                    d[key + "_vol"] += r["vol"]
                    d[key + "_amt"] += r["amt"]
            off += 5000
            if off > 100000:
                break
    print(f"  {s[:6]} done calls={calls} elapsed={time.time()-t0:.0f}s rows={len(acc)}", flush=True)

rows = [{"date": d, "oc": oc, **v} for (d, oc), v in acc.items()]
new = pd.DataFrame(rows)
if old is not None and len(old):
    old = old[old["date"] < ms[0][0]]
    new = pd.concat([old, new], ignore_index=True)
new = new.drop_duplicates(subset=["date", "oc"], keep="last").sort_values(["oc", "date"])
new["oi_pcr"] = new["p_oi"] / new["c_oi"]
new["vol_pcr"] = new["p_vol"] / new["c_vol"]
new.to_csv(RAW, index=False, encoding="utf-8-sig")
print("PCR rows:", len(new), "range:", new["date"].min(), "~", new["date"].max(), flush=True)
print(new.groupby("oc")["date"].agg(["count", "min", "max"]).to_string(), flush=True)
