# -*- coding: utf-8 -*-
"""取数 4/4：ETF 与期权元信息。

数据来源优先级
--------------
1. ``data/opt_contracts.json`` —— 期权合约表缓存（本脚本 TTL 管理）
2. ``data/etf_meta.json``      —— ETF 名称/管理人/费率缓存（落盘）
3. 内置兜底表                   —— 上面两者都缺时用，保证日报不会因元信息中断
"""
import sys, os, json
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import cfg

BASE = cfg.BASE
ASOF = cfg.ASOF
CACHE = BASE + "data/opt_contracts.json"
ETF_META = BASE + "data/etf_meta.json"

ETF_CODES = ["510300.SH", "510050.SH", "510500.SH", "159915.SZ", "588000.SH"]

# 兜底：基金公司/费率变了需要手工更新，但名称与成立日基本不变
ETF_FALLBACK = {
    "510300.SH": {"name": "华泰柏瑞沪深300ETF", "management": "华泰柏瑞基金",
                  "found_date": "20120504", "list_date": "20120528", "m_fee": "0.50", "c_fee": "0.10"},
    "510050.SH": {"name": "华夏上证50ETF", "management": "华夏基金",
                  "found_date": "20041230", "list_date": "20050223", "m_fee": "0.50", "c_fee": "0.10"},
    "510500.SH": {"name": "南方中证500ETF", "management": "南方基金",
                  "found_date": "20130206", "list_date": "20130315", "m_fee": "0.50", "c_fee": "0.10"},
    "159915.SZ": {"name": "易方达创业板ETF", "management": "易方达基金",
                  "found_date": "20110920", "list_date": "20111209", "m_fee": "0.50", "c_fee": "0.10"},
    "588000.SH": {"name": "华夏上证科创板50ETF", "management": "华夏基金",
                  "found_date": "20200928", "list_date": "20201116", "m_fee": "0.50", "c_fee": "0.10"},
}


def load_contracts():
    """返回 (c2u, c2d)；缓存缺失时期权合约计数记为 0（缓存由建库脚本一次性生成）。"""
    if os.path.exists(CACHE):
        c = json.load(open(CACHE, encoding="utf-8"))
        if c.get("map") and c.get("delist"):
            return c["map"], c["delist"]
    print("[meta] 无合约缓存 → 期权合约计数记为 0", flush=True)
    return {}, {}


def load_etf_meta():
    """ETF 名称/管理人/费率：缓存 → 内置兜底。"""
    if os.path.exists(ETF_META):
        try:
            c = json.load(open(ETF_META, encoding="utf-8"))
            if all(k in c for k in ETF_CODES):
                return c
        except Exception:                        # noqa: BLE001
            pass

    return dict(ETF_FALLBACK)


c2u, c2d = load_contracts()
live_cnt, all_cnt = {}, {}
for ts, oc in c2u.items():
    all_cnt[oc] = all_cnt.get(oc, 0) + 1
    if str(c2d.get(ts, "")) > ASOF:
        live_cnt[oc] = live_cnt.get(oc, 0) + 1
print("live ETF option contracts:", live_cnt, flush=True)

etf_meta = load_etf_meta()
print("[meta] ETF 元信息 %d 条" % len(etf_meta), flush=True)

OPTS = {
    "OP510050.SH": {"exch": "上交所", "etf": "510050.SH", "name": "上证50ETF期权", "start": "2015-02-09"},
    "OP510300.SH": {"exch": "上交所", "etf": "510300.SH", "name": "沪深300ETF期权", "start": "2019-12-23"},
    "OP159919.SZ": {"exch": "深交所", "etf": "159919.SZ", "name": "沪深300ETF期权(深)", "start": "2019-12-23"},
    "OP510500.SH": {"exch": "上交所", "etf": "510500.SH", "name": "中证500ETF期权", "start": "2022-09-19"},
    "OP159922.SZ": {"exch": "深交所", "etf": "159922.SZ", "name": "中证500ETF期权(深)", "start": "2022-09-19"},
    "OP159915.SZ": {"exch": "深交所", "etf": "159915.SZ", "name": "创业板ETF期权", "start": "2022-09-19"},
    "OP588000.SH": {"exch": "上交所", "etf": "588000.SH", "name": "科创50ETF期权", "start": "2023-06-05"},
    "OP588080.SH": {"exch": "上交所", "etf": "588080.SH", "name": "科创板50ETF期权", "start": "2023-06-05"},
}
for k, v in OPTS.items():
    v["live"] = int(live_cnt.get(k, 0))
    v["all"] = int(all_cnt.get(k, 0))
    mm = etf_meta.get(v["etf"], {})
    v["etf_name"] = mm.get("name", "")
    v["etf_mgr"] = mm.get("management", "")
    mf, cf = mm.get("m_fee", ""), mm.get("c_fee", "")
    v["etf_fee"] = (f"{mf}+{cf}" if mf or cf else "")

json.dump(OPTS, open(BASE + "work/opts.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
print("saved opts.json (ASOF=%s)" % cfg.ASOF_FMT)
