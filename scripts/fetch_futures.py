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
TIMEOUT = 8                      # 单请求超时：正常 <1s，8s 已远超；原 20s×25 请求=8 分钟
BREAK_AFTER = 3                  # 连续 N 个请求失败即熔断（网络整体异常时别再耗满超时）

KLINE_URL = ("https://stock2.finance.sina.com.cn/futures/api/jsonp.php/var%20t=/"
             "InnerFuturesNewService.getDailyKLine")
SINA_H = {"Referer": "https://finance.sina.com.cn"}
EM_URL = "https://push2his.eastmoney.com/api/qt/stock/kline/get"
# 备用现货源（push2his 在本机沙箱代理下被直接拒绝，2026-10-27 起加降级）
SINA_SPOT_URL = ("https://money.finance.sina.com.cn/quotes_service/api/json_v2.php/"
                 "CN_MarketData.getKLineData")
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

    中金所挂牌规则：当月、次月 + 随后两个季月（3/6/9/12）。
    d 晚于当月第三个周五时，当月已经交割、顺延到次月。

    注意：季月游标必须独立逐月推进——曾用 `out[-1]` 当游标，遇 12 月后
    下一个月是次年 1 月（非季月）不 append，游标不前进 → 死循环，
    2026-10-27 06:00 定时任务的"挂起 12 分钟"即此。
    """
    y, m = d.year, d.month
    if d > third_friday(y, m):
        y, m = (y + (m == 12), 1 if m == 12 else m + 1)
    out = [(y, m), (y + (m == 12), 1 if m == 12 else m + 1)]   # 当月、次月
    cy, cm = out[-1]                                           # 独立游标
    guard = 0
    while len(out) < 4 and guard < 36:
        guard += 1
        cy, cm = (cy + (cm == 12), 1 if cm == 12 else cm + 1)
        if cm % 3 == 0:
            out.append((cy, cm))
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
_SESS = None


def _sess():
    """普通 Session（跟随 env 代理 = 沙箱出口代理）。

    **不要置 trust_env=False**：本机 HTTP(S)_PROXY 是沙箱注入的出口代理（端口每会话可能
    变，2026-10-26=7864、10-27=12164），「直连」与「走代理」是同一出口路径；实测置 False
    后请求会卡在解析/连接层（超时参数管不到 DNS），2 分钟零输出。
    可靠性靠 TIMEOUT + BREAK_AFTER 熔断，而不是绕代理。
    """
    global _SESS
    if _SESS is None:
        import requests
        _SESS = requests.Session()
    return _SESS


_FAILS = [0]                # 连续失败计数（跨品种累计，进程内）


def _fetch_contract(sym):
    """新浪单合约日 K（上市以来全历史）。返回 [(iso, close)]，空合约返回 []。

    连续 BREAK_AFTER 次失败后抛 _Breaker，调用方中止本环节并保留原缓存。
    """
    r = _sess().get(KLINE_URL, params={"symbol": sym}, headers=SINA_H, timeout=TIMEOUT)
    txt = r.text
    body = txt[txt.find("(") + 1:txt.rfind(")")]
    data = json.loads(body)
    _FAILS[0] = 0
    return [(x["d"], float(x["c"])) for x in (data or [])]


class _Breaker(Exception):
    """网络整体异常：已连续多次失败，中止本环节（非致命，保留缓存）。"""


def _try(sym):
    """带熔断的取数：失败累计到 BREAK_AFTER 即中止，避免逐请求耗满超时。"""
    try:
        return _fetch_contract(sym)
    except Exception as e:                                # noqa: BLE001
        _FAILS[0] += 1
        print("  !! [futures] %s 取数失败（连续 %d）：%s %s"
              % (sym, _FAILS[0], type(e).__name__, str(e)[:100]))
        if _FAILS[0] >= BREAK_AFTER:
            raise _Breaker("连续 %d 个请求失败，本环节中止" % _FAILS[0])
        return []


def sync_futures(blob, seed=False):
    """拼接当月连续。seed=True 自 START 全量重建，否则增量。"""
    today = datetime.date.today()
    # 次月合约也要拉：交割日次一交易日起当月=次月（否则序列停在交割日）
    cur_ym = next_ym("%04d%02d" % (today.year, today.month))
    listed = listed_contracts(today)          # 当月/次月/当季/下季（CUR 表用）
    curs = blob.setdefault("CUR", {})         # CUR[prod][sym] = {date: close}
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
            bars = _try(sym)
            bars_cache[sym] = bars
            # 只收属于「当月」的交易日（拼接规则：t 的当月合约 = contract_ym(t)）
            pairs = [(d, c) for d, c in bars
                     if contract_ym(datetime.date.fromisoformat(d)) == ym]
            added += _merge(blob, prod, pairs)
            time.sleep(SLEEP)
        # CUR：全部存续合约的日收盘（读数表用）——按合约分开存：
        #   CUR[prod][sym] = {iso_date: close}
        # 曾误用 _merge 把各合约混成一个 {date: close} 扁平字典，
        # 导致 gen2 取 _fser.get(_fd) 时 _fser 是 float（AttributeError）。
        cur = {}
        for ym in listed:
            sym = prod + ym[2:]
            pairs = bars_cache.get(sym)
            if pairs is None:                             # 季月不在上面循环里时补拉
                pairs = _try(sym)
                time.sleep(SLEEP)
            d = {}
            for dd, c in pairs:
                if dd and c is not None and c == c:
                    d[dd] = round(float(c), 2)
            cur[sym] = {k: d[k] for k in sorted(d)}
        curs[prod] = cur
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
    """中证1000 现货：东财 K 线为主，失败降级新浪（push2his 在本机沙箱代理下被拒）。"""
    dst = blob.setdefault("SPOT852", {})
    last = max(dst) if dst else ""
    beg = (datetime.date.fromisoformat(last)
           - datetime.timedelta(days=7)).strftime("%Y%m%d") if last else SPOT_BEG
    pairs, src = [], "em"
    try:
        r = _sess().get(EM_URL, params={
            "secid": SPOT_SECID, "fields1": "f1,f2,f3", "fields2": "f51,f53",
            "klt": "101", "fqt": "0", "beg": beg, "end": "20500101",
        }, headers=EM_H, timeout=TIMEOUT)
        kl = ((r.json() or {}).get("data") or {}).get("klines") or []
        for line in kl:
            p = line.split(",")
            if len(p) >= 2:
                pairs.append((p[0], p[1]))
    except Exception as e:                                # noqa: BLE001
        print("  .. [futures] 东财现货源不可用，改走新浪：%s %s"
              % (type(e).__name__, str(e)[:80]))
    if not pairs:
        try:
            r = _sess().get(SINA_SPOT_URL, params={
                "symbol": "sh000852", "scale": "240", "ma": "no", "datalen": "5000",
            }, headers=SINA_H, timeout=TIMEOUT)
            data = json.loads(r.text)
            floor = "%s-%s-%s" % (SPOT_BEG[:4], SPOT_BEG[4:6], SPOT_BEG[6:])
            pairs = [(x["day"], x["close"]) for x in data
                     if x.get("day") and x.get("close") and x["day"] >= floor]
            src = "sina"
        except Exception as e:                            # noqa: BLE001
            print("  !! [futures] 中证1000 现货两源均失败（保留原缓存）：%s %s"
                  % (type(e).__name__, str(e)[:110]))
            return
    added = _merge(blob, "SPOT852", pairs)
    ks = sorted(blob["SPOT852"])
    print("  [futures] SPOT852（中证1000,%s）+%d → %s ~ %s（%d 日）"
          % (src, added, ks[0] if ks else "-", ks[-1] if ks else "-", len(ks)))


def main():
    seed = "--seed" in sys.argv
    blob = _load()
    if seed:
        blob = {}                                        # 重建模式：推倒重来
        print("  [futures] seed 模式：逐月拉取历史合约（约 3~5 分钟）...")
    try:
        sync_futures(blob, seed=seed)
        sync_spot852(blob)
    except _Breaker as e:
        print("  !! futures 熔断：%s（保留原缓存，稍后运行自动补齐）" % e)
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
