# -*- coding: utf-8 -*-
"""指数收盘价历史 → data/close_history.json（Tushare 一次性回填 + 东财日常增量）。

用途：PE/PB Band 图（v2.5.9）需要 2015 年以来的指数收盘价，
用于换算当期 EPS(TTM)=close/PE(TTM)、BPS=close/PB，并把 band 通道画在价格空间。
raw.json 的 daily 只有 2019-12 起的新浪增量，不够 10 年窗口，故单独维护本文件。

两种模式
--------
1. 默认（日常增量）：东财 K 线接口 push2his（klt=101 日线、fqt=0）。
   按「库内最后一天」判断：已最新则 0 请求，否则 1 发/指数。非致命。
2. ``--seed-tushare``（一次性历史回填，用户 2026-10-21 批准仅此一次）：
   Tushare index_daily 从 20150105 起补齐全部缺失日。
   沿用 sync_tushare.py 惯例：自设 IV_ALLOW_TUSHARE=1，人工指令工具。

写入规则（两种模式一致）：只新增缺失日期，已有历史一律不覆盖；
最近 3 天允许覆盖（当晚修正）。写前 tmp + os.replace 原子替换。
"""
import datetime
import json
import os
import sys

BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE)
PATH = os.path.join(os.path.dirname(BASE), "data", "close_history.json")

# secid 规则：沪市 1.，深市 0.
SECID = {"000016.SH": "1.000016", "000300.SH": "1.000300",
         "000905.SH": "1.000905", "399006.SZ": "0.399006",
         "000688.SH": "1.000688"}
BEG = "20150101"   # 与估值历史起点对齐（科创50 接口自然从基日 1000 起）
HIST_FLOOR = "20150105"

URL = "https://push2his.eastmoney.com/api/qt/stock/kline/get"
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                    "Chrome/120.0.0.0 Safari/537.36",
      "Referer": "https://quote.eastmoney.com/"}

KEEP_DAYS = 3   # 最近 N 天允许覆盖（当日值可能晚间修正）


def _load() -> dict:
    if os.path.exists(PATH):
        try:
            return json.load(open(PATH, encoding="utf-8"))
        except Exception:
            pass
    return {}


def _save(hist: dict) -> None:
    tmp = PATH + ".tmp"
    json.dump(hist, open(tmp, "w", encoding="utf-8"), ensure_ascii=False)
    os.replace(tmp, PATH)


def _merge(hist: dict, code: str, pairs) -> int:
    """pairs: [(iso_date, close), ...] → 只补缺，已定稿历史不覆盖。返回新增条数。"""
    blob = hist.setdefault(code, {})
    keep_after = (datetime.date.today() - datetime.timedelta(days=KEEP_DAYS)).isoformat()
    added = 0
    for d, v in pairs:
        if not d or v is None:
            continue
        if d in blob and d < keep_after:
            continue
        if d not in blob:
            added += 1
        blob[d] = round(float(v), 2)
    hist[code] = {k: blob[k] for k in sorted(blob)}
    return added


def seed_tushare(hist: dict, asof: str) -> int:
    """一次性历史回填：Tushare index_daily（人工批准，仅此一次）。"""
    import cfg
    pro = cfg.pro_api()
    total = 0
    for code in SECID:
        df = pro.index_daily(ts_code=code, start_date=HIST_FLOOR, end_date=asof,
                             fields="trade_date,close")
        pairs = []
        for _, r in df.iterrows():
            d = str(r["trade_date"])
            pairs.append(("%s-%s-%s" % (d[:4], d[4:6], d[6:]), r["close"]))
        added = _merge(hist, code, pairs)
        total += added
        ks = sorted(hist[code])
        print("  [seed-tushare] %s +%d → %s ~ %s（%d 日）"
              % (code, added, ks[0], ks[-1], len(ks)))
    return total


def incr_em(hist: dict, asof: str) -> int:
    """日常增量：东财 K 线，已最新则 0 请求。"""
    import requests
    total = 0
    for code, secid in SECID.items():
        blob = hist.setdefault(code, {})
        last = max(blob) if blob else ""
        last_yyyymmdd = last.replace("-", "") if last else ""
        if asof and last_yyyymmdd >= asof:
            print("  [close_hist] %s 已最新 (%s)" % (code, last))
            continue
        try:
            r = requests.get(URL, params={
                "secid": secid, "fields1": "f1,f2,f3", "fields2": "f51,f53",
                "klt": "101", "fqt": "0", "beg": BEG, "end": "20500101",
            }, headers=UA, timeout=40)
            kl = ((r.json() or {}).get("data") or {}).get("klines") or []
        except Exception as e:
            print("  !! [close_hist] %s 取数失败（保留原缓存）：%s %s"
                  % (code, type(e).__name__, str(e)[:120]))
            continue
        if not kl:
            print("  !! [close_hist] %s 接口返回空，保留原缓存" % code)
            continue
        pairs = []
        for line in kl:
            p = line.split(",")
            if len(p) >= 2:
                pairs.append((p[0], p[1]))
        added = _merge(hist, code, pairs)
        total += added
        ks = sorted(hist[code])
        print("  [close_hist] %s +%d → %s ~ %s（%d 日）"
              % (code, added, ks[0], ks[-1], len(ks)))
    return total


def main() -> None:
    seed = "--seed-tushare" in sys.argv
    if seed:
        os.environ.setdefault("IV_ALLOW_TUSHARE", "1")   # 沿用 sync_tushare 惯例
    asof = (os.environ.get("ASOF") or "")[:8]
    hist = _load()
    if seed:
        if not asof:
            raise SystemExit("!! --seed-tushare 需要指定 ASOF=YYYYMMDD（回填截至日）")
        n = seed_tushare(hist, asof)
    else:
        n = incr_em(hist, asof)
    if n:
        _save(hist)
    print("  close_hist 完成：本次共新增 %d 条%s" % (n, "（Tushare 一次性回填）" if seed else ""))


if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except Exception as e:                      # noqa: BLE001
        print("  !! close_hist 更新失败（非致命，保留原缓存）：",
              type(e).__name__, str(e)[:160])
    sys.exit(0)
