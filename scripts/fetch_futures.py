# -*- coding: utf-8 -*-
"""股指期货当月连续收盘 + 中证1000 现货 → data/futures_kline.json（v2.6.5）。

用途：情绪面「股指期货升贴水」图。基差率 = (期货/现货 − 1) × 100。
当月连续由各月份合约日 K 线拼接（新浪 InnerFuturesNewService.getDailyKLine）：
交易日 t 的当月合约 = t 所在月份的合约；t 晚于当月第三个周五（交割日）则用次月。
新浪合约 K 线历史下界 2018-10（更早返回空），故 IF/IH/IC 序列自 2018-10-22 起、
IM 自 2022-07-22（上市日）起。中证1000 现货走东财 K 线（secid=1.000852），
存于同文件 "SPOT852" 键（000300/000016/000905 现货复用 close_history.json）。

两种模式
--------
1. 默认（日常增量）：每品种只取「库内最后日期所在月 −1」到「当前月」的合约
   （通常 2~3 只），加中证1000 现货增量（已最新则 0 请求）。非致命，异常自吞。
2. ``--seed``（首次/重建）：自 START 逐月拉全部历史合约（IF/IH/IC 各约 100 只，
   共约 5 分钟），仅人工指令执行。

写入规则（与 close_history.json 一致）：只补缺，最近 3 天允许覆盖；
写前 tmp + os.replace 原子替换。
"""
import calendar
import datetime
import json
import os
import sys
import time

BASE = os.path.dirname(os.path.abspath(__file__))
PATH = os.path.join(os.path.dirname(BASE), "data", "futures_kline.json")

PROD = {"IF": "沪深300", "IH": "上证50", "IC": "中证500", "IM": "中证1000"}
START = {"IF": "201810", "IH": "201810", "IC": "201810", "IM": "202207"}
SPOT_SECID = "1.000852"          # 中证1000 现货（东财）
SPOT_BEG = "20220101"            # IM 上市前留足余量
KEEP_DAYS = 3                    # 最近 N 天允许覆盖（当日值可能晚间修正）
SLEEP = 0.25                     # 新浪逐合约拉取间隔（seed 模式约 5 分钟）

KLINE_URL = ("https://stock2.finance.sina.com.cn/futures/api/jsonp.php/var%20t=/"
             "InnerFuturesNewService.getDailyKLine")
SINA_H = {"Referer": "https://finance.sina.com.cn"}
EM_URL = "https://push2his.eastmoney.com/api/qt/stock/kline/get"
EM_H = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                      "Chrome/120.0.0.0 Safari/537.36",
        "Referer": "https://quote.eastmoney.com/"}


# ---------- 当月合约推导 ----------
def third_friday(y, m):
    fridays = [datetime.date(y, m, d)
               for d in range(1, calendar.monthrange(y, m)[1] + 1)
               if datetime.date(y, m, d).weekday() == 4]
    return fridays[2]


def next_ym(ym):
    y, m = int(ym[:4]), int(ym[4:])
    return "%04d%02d" % (y + (m == 12), 1 if m == 12 else m + 1)


def contract_ym(d):
    """交易日 t 的当月合约月份（YYYYMM）：晚于当月第三个周五（交割日）则用次月。"""
    ym = "%04d%02d" % (d.year, d.month)
    if d > third_friday(d.year, d.month):
        ym = next_ym(ym)
    return ym


def listed_contracts(d):
    """当前全部存续合约月份（YYYYMM 列表，当月/次月/当季/下季）。

    中金所挂牌规则：当月、次月及随后两个季月（3/6/9/12）。
    d 晚于当月第三个周五时，当月已经交割、顺延到次月。
    """
    y, m = (d.year, d.month)
    if d > third_friday(y, m):
        y, m = (y + (m == 12), 1 if m == 12 else m + 1)
    out = [(y, m), (y + (m == 12), 1 if m == 12 else m + 1)]
    while len(out) < 4:                       # 补足两个季月
        y2, m2 = out[-1]
        y2, m2 = (y2 + (m2 == 12), 1 if m2 == 12 else m2 + 1)
        if m2 % 3 == 0:
            out.append((y2, m2))
    return ["%04d%02d" % t for t in out[:4]]


def ym_range(a, b):
    """闭区间 [a, b] 的 YYYYMM 序列。"""
    out, cur = [], a
    while cur <= b:
        out.append(cur)
        cur = next_ym(cur)
    return out


# ---------- 存储 ----------
def _load():
    if os.path.exists(PATH):
        try:
            return json.load(open(PATH, encoding="utf-8"))
        except Exception:
            pass
    return {}


def _save(blob):
    tmp = PATH + ".tmp"
    json.dump(blob, open(tmp, "w", encoding="utf-8"), ensure_ascii=False)
    os.replace(tmp, PATH)


def _merge(blob, key, pairs):
    """pairs: [(iso_date, close)] → 只补缺，最近 KEEP_DAYS 天允许覆盖。"""
    dst = blob.setdefault(key, {})
    keep_after = (datetime.date.today()
                  - datetime.timedelta(days=KEEP_DAYS)).isoformat()
    added = 0
    for d, v in pairs:
        if not d or v is None or v != v:
            continue
        if d in dst and d < keep_after:
            continue
        if d not in dst:
            added += 1
        dst[d] = round(float(v), 2)
    blob[key] = {k: dst[k] for k in sorted(dst)}
    return added


# ---------- 取数 ----------
def _fetch_contract(sym):
    """新浪单合约日 K（上市以来全历史）。返回 [(iso, close)]，空合约返回 []。"""
    import requests
    r = requests.get(KLINE_URL, params={"symbol": sym}, headers=SINA_H, timeout=20)
    txt = r.text
    body = txt[txt.find("(") + 1:txt.rfind(")")]
    data = json.loads(body)
    return [(x["d"], float(x["c"])) for x in (data or [])]


def sync_futures(blob, seed=False):
    """拼接当月连续。seed=True 自 START 全量重建，否则增量。"""
    today = datetime.date.today()
    # 次月合约也要拉：交割日次一交易日起当月=次月（否则序列停在交割日）
    cur_ym = next_ym("%04d%02d" % (today.year, today.month))
    listed = listed_contracts(today)          # 当月/次月/当季/下季（CUR 表用）
    for prod in PROD:
        existing = blob.get(prod, {})
        if seed or not existing:
            months = ym_range(START[prod], cur_ym)       # 全量：逐月历史合约
        else:
            # 增量：从「库内最后日期 −40 天」所在月到当前月（覆盖跨交割滚动）
            anchor = (datetime.date.fromisoformat(max(existing))
                      - datetime.timedelta(days=40))
            months = ym_range("%04d%02d" % (anchor.year, anchor.month), cur_ym)
        months = sorted(set(months) | set(listed))       # 存续季月也取，CUR 表用
        added = 0
        bars_cache = {}
        for ym in months:
            sym = prod + ym[2:]
            try:
                bars = _fetch_contract(sym)
            except Exception as e:                        # noqa: BLE001
                print("  !! [futures] %s 取数失败：%s %s"
                      % (sym, type(e).__name__, str(e)[:100]))
                bars = []
            bars_cache[sym] = bars
            # 只收属于「当月」的交易日（拼接规则：t 的当月合约 = contract_ym(t)）
            pairs = [(d, c) for d, c in bars
                     if contract_ym(datetime.date.fromisoformat(d)) == ym]
            added += _merge(blob, prod, pairs)
            time.sleep(SLEEP)
        # CUR：全部存续合约的日收盘（读数表用；与当月连续日期对齐取值）
        cur = blob.setdefault("CUR", {}).setdefault(prod, {})
        for sym in [prod + ym[2:] for ym in listed]:
            pairs = bars_cache.get(sym)
            if pairs is None:                             # 季月不在上面循环里时补拉
                try:
                    pairs = _fetch_contract(sym)
                except Exception as e:                    # noqa: BLE001
                    print("  !! [futures] %s 取数失败：%s %s"
                          % (sym, type(e).__name__, str(e)[:100]))
                    pairs = []
                time.sleep(SLEEP)
            _merge(blob, "CUR." + prod, [(d, c) for d, c in pairs])
        blob["CUR"][prod] = blob.pop("CUR." + prod)
        ks = sorted(blob[prod])
        print("  [futures] %s → %s ~ %s（%d 日，本次新补 %d；存续 %s）"
              % (prod, ks[0] if ks else "-", ks[-1] if ks else "-",
                 len(ks), added, ",".join([prod + ym[2:] for ym in listed])))
    # _meta：各品种最后一个交易日的当月合约代码（gen2 直接引用）
    meta = blob.setdefault("_meta", {})
    meta["updated"] = datetime.datetime.now().isoformat(timespec="seconds")
    contracts = {}
    for prod in PROD:
        ks = sorted(blob.get(prod, {}))
        if ks:
            contracts[prod] = prod + contract_ym(
                datetime.date.fromisoformat(ks[-1]))[2:]
    meta["contract"] = contracts


def sync_spot852(blob):
    """中证1000 现货（东财 K 线）：增量或首次全量。"""
    import requests
    dst = blob.setdefault("SPOT852", {})
    last = max(dst) if dst else ""
    beg = (datetime.date.fromisoformat(last)
           - datetime.timedelta(days=7)).strftime("%Y%m%d") if last else SPOT_BEG
    try:
        r = requests.get(EM_URL, params={
            "secid": SPOT_SECID, "fields1": "f1,f2,f3", "fields2": "f51,f53",
            "klt": "101", "fqt": "0", "beg": beg, "end": "20500101",
        }, headers=EM_H, timeout=40)
        kl = ((r.json() or {}).get("data") or {}).get("klines") or []
    except Exception as e:                                # noqa: BLE001
        print("  !! [futures] 中证1000 现货取数失败（保留原缓存）：%s %s"
              % (type(e).__name__, str(e)[:120]))
        return
    pairs = []
    for line in kl:
        p = line.split(",")
        if len(p) >= 2:
            pairs.append((p[0], p[1]))
    added = _merge(blob, "SPOT852", pairs)
    ks = sorted(blob["SPOT852"])
    print("  [futures] SPOT852（中证1000）+%d → %s ~ %s（%d 日）"
          % (added, ks[0] if ks else "-", ks[-1] if ks else "-", len(ks)))


def main():
    seed = "--seed" in sys.argv
    blob = _load()
    if seed:
        blob = {}                                        # 重建模式：推倒重来
        print("  [futures] seed 模式：逐月拉取历史合约（约 3~5 分钟）...")
    sync_futures(blob, seed=seed)
    sync_spot852(blob)
    _save(blob)
    print("  futures 完成：%s" % PATH)


if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except Exception as e:                               # noqa: BLE001
        print("  !! futures 更新失败（非致命，保留原缓存）：",
              type(e).__name__, str(e)[:160])
    sys.exit(0)
