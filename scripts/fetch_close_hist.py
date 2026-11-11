# -*- coding: utf-8 -*-
"""指数收盘价历史 → data/close_history.json（东财日常增量）。

用途：PE/PB Band 图（v2.5.9）需要 2015 年以来的指数收盘价，
用于换算当期 EPS(TTM)=close/PE(TTM)、BPS=close/PB，并把 band 通道画在价格空间。
raw.json 的 daily 只有 2019-12 起的新浪增量，不够 10 年窗口，故单独维护本文件；
2015~2019 的历史段由建库时的一次性回填写定，已冻结、不再重取。

模式（日常增量）：东财 K 线接口 push2his（klt=101 日线、fqt=0），
按「库内最后一天」判断：已最新则 0 请求，否则 1 发/指数。非致命。

写入规则：只新增缺失日期，已有历史一律不覆盖；
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

# 备用源（v2.6.6）：push2his.eastmoney.com 在本机沙箱代理下被直接拒绝
# （0.1s ProxyError，两个子域皆同），2026-10-27 06:00 起 close_hist 全灭。
# 新浪指数日 K 可一次取 5000 根（2006 起，含当日收盘），作等值替代。
SINA_URL = ("https://money.finance.sina.com.cn/quotes_service/api/json_v2.php/"
            "CN_MarketData.getKLineData")
SINA_SYM = {"000016.SH": "sh000016", "000300.SH": "sh000300",
            "000905.SH": "sh000905", "399006.SZ": "sz399006",
            "000688.SH": "sh000688"}
SINA_HDR = {"Referer": "https://finance.sina.com.cn",
            "User-Agent": UA["User-Agent"]}

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



def _fetch_em(s, secid):
    """东财 K 线（主源）：返回 [(iso, close)]。"""
    r = s.get(URL, params={
        "secid": secid, "fields1": "f1,f2,f3", "fields2": "f51,f53",
        "klt": "101", "fqt": "0", "beg": BEG, "end": "20500101",
    }, headers=UA, timeout=10)
    kl = ((r.json() or {}).get("data") or {}).get("klines") or []
    pairs = []
    for line in kl:
        p = line.split(",")
        if len(p) >= 2:
            pairs.append((p[0], p[1]))
    return pairs


def _fetch_sina(s, code):
    """新浪指数日 K（备用源）：datalen=5000 覆盖 2006 起，含当日收盘。

    只保留 HIST_FLOOR 之后（2015-01-05）——本文件的历史起点是 2015，
    多灌 2006~2014 会让报告"数据自 XXXX 起"的标注错乱，也违背只留必要历史的约定。
    """
    r = s.get(SINA_URL, params={"symbol": SINA_SYM[code], "scale": "240",
                               "ma": "no", "datalen": "5000"},
              headers=SINA_HDR, timeout=15)
    data = json.loads(r.text)
    floor = "%s-%s-%s" % (HIST_FLOOR[:4], HIST_FLOOR[4:6], HIST_FLOOR[6:])
    return [(x["day"], x["close"]) for x in data
            if x.get("day") and x.get("close") and x["day"] >= floor]


def incr_em(hist: dict, asof: str) -> int:
    """日常增量：已最新则 0 请求；东财为主源，失败自动降级新浪。

    trust_env 保持默认（跟随沙箱出口代理）：实测置 False 会卡在解析/连接层。
    push2his 一旦失败即视为本次运行不可用（em_dead），不再逐只重试；
    两源都失败连续 2 次则中止本环节（快速失败）。
    """
    import requests
    s = requests.Session()
    fails = 0
    total = 0
    em_dead = False
    for code, secid in SECID.items():
        blob = hist.setdefault(code, {})
        last = max(blob) if blob else ""
        last_yyyymmdd = last.replace("-", "") if last else ""
        if asof and last_yyyymmdd >= asof:
            print("  [close_hist] %s 已最新 (%s)" % (code, last))
            continue
        pairs, src = [], "em"
        if not em_dead:
            try:
                pairs = _fetch_em(s, secid)
            except Exception as e:
                em_dead = True
                print("  !! [close_hist] 东财源不可用，改走新浪：%s %s"
                      % (type(e).__name__, str(e)[:90]))
        if not pairs:
            try:
                pairs = _fetch_sina(s, code)
                src = "sina"
                fails = 0
            except Exception as e:
                fails += 1
                print("  !! [close_hist] %s 两源均失败（连续 %d，保留原缓存）：%s %s"
                      % (code, fails, type(e).__name__, str(e)[:110]))
                if fails >= 2:
                    print("  !! [close_hist] 连续 %d 次失败，中止本环节（非致命）" % fails)
                    return total
                continue
        if not pairs:
            print("  !! [close_hist] %s 接口返回空，保留原缓存" % code)
            continue
        added = _merge(hist, code, pairs)
        total += added
        ks = sorted(hist[code])
        print("  [close_hist] %s(%s) +%d → %s ~ %s（%d 日）"
              % (code, src, added, ks[0], ks[-1], len(ks)))
    return total


def main() -> None:
    asof = (os.environ.get("ASOF") or "")[:8]
    hist = _load()
    n = incr_em(hist, asof)
    if n:
        _save(hist)
    print("  close_hist 完成：本次共新增 %d 条" % n)


if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except Exception as e:                      # noqa: BLE001
        print("  !! close_hist 更新失败（非致命，保留原缓存）：",
              type(e).__name__, str(e)[:160])
    sys.exit(0)
