# -*- coding: utf-8 -*-
"""2026 年内逐日对比：东财聚合 / 中证官网 vs 本地 raw.json 的 Tushare 存值。

只读，不写任何 data/ 文件。用途：评估「停用每周 Tushare 校准」后，
东财口径与 Tushare 口径在今年一年内的系统性偏差有多大。
"""
import sys, os, json, csv, statistics as st

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from ivdata.config import INDEXES
from ivdata.providers import em, csi

REF_CUT = "20261010"          # 该日之前（含）的 raw.json 行都由 Tushare 写入
OUT_CSV = os.path.join("work", "compare_vs_tushare_2026.csv")


def pct(a, b):
    """a 相对 b 的偏差 %；任一为空返回 None。"""
    if a is None or b is None or b == 0:
        return None
    return (a - b) / abs(b) * 100.0


def stat_block(pairs):
    """pairs: [(ref, em)] -> (n, mean|dev|, median, p95, worst)。"""
    devs = [abs(pct(e, r)) for r, e in pairs if e is not None and r]
    if not devs:
        return None
    devs.sort()
    n = len(devs)
    return {
        "n": n,
        "mean": sum(devs) / n,
        "median": devs[n // 2],
        "p95": devs[min(n - 1, int(n * 0.95))],
        "max": devs[-1],
    }


def main():
    raw = json.load(open("data/raw.json", encoding="utf-8"))
    codes = [t[1] for t in sorted(INDEXES)]          # (order, code, name, ...)

    # ---- 参考值：raw.json 2026 年 Tushare 段 ----
    ref = {}   # (code, date, field) -> value
    dates_all = set()
    for code in codes:
        for r in raw[code]["basic"]:
            d = r["trade_date"]
            if d >= "20260101" and d <= REF_CUT:
                dates_all.add(d)
                for f in ("pe_ttm", "pe", "pb", "total_mv"):
                    if r.get(f) is not None:
                        ref[(code, d, f)] = r[f]
    dates = sorted(dates_all)
    print(f"参考段：2026-01-01 ~ {REF_CUT}，共 {len(dates)} 个交易日（Tushare 存值）")

    # ---- 东财逐日聚合（每个交易日只发 1 次全市场请求，5 个指数共用）----
    cons = {}
    for code in codes:
        idx = em.IDX2EM_CODE.get(code)
        cons[code] = em._constituents(idx) if idx else []
    print("东财成分股数量：", {c[:6]: len(v) for c, v in cons.items()})

    em_rows = []          # (code, date, field, ref, em)
    for i, d in enumerate(dates):
        iso = f"{d[:4]}-{d[4:6]}-{d[6:]}"
        try:
            stocks = em._all_stocks(iso)
        except Exception as e:                      # noqa: BLE001
            print(f"  [em] {d} 失败: {str(e)[:80]}")
            continue
        for code in codes:
            if not cons[code]:
                continue
            pe, pb, mv, _ = em._aggregate_by_constituents(stocks, cons[code])
            pe_lar = em._aggregate_key(stocks, cons[code], "PE_LAR")
            got = {"pe_ttm": pe, "pb": pb, "total_mv": mv, "pe": pe_lar}
            for f, v in got.items():
                r = ref.get((code, d, f))
                if r is not None:
                    em_rows.append((code, d, f, r, v))
        if (i + 1) % 40 == 0:
            print(f"  ... 东财 {i+1}/{len(dates)} 日")

    # ---- 中证官网（独立官方源，只有 PE 一类字段）----
    csi_rows = []
    for code in codes:
        csi_code = getattr(csi, "CODE2CSI", {}).get(code)
        if not csi_code:
            continue
        try:
            rows = csi.CsiValuation().fetch_valuation(code, "20260101", REF_CUT)
        except Exception as e:                      # noqa: BLE001
            print(f"  [csi] {code} 失败: {str(e)[:80]}")
            continue
        m = {r["trade_date"]: r["pe_ttm"] for r in rows}
        for d in dates:
            for f in ("pe_ttm", "pe"):   # 同时对两个字段比，判 peg 到底是 TTM 还是静态
                r = ref.get((code, d, f))
                if r is not None and d in m:
                    csi_rows.append((code, d, f, r, m[d]))

    # ---- 汇总 ----
    print()
    print("=" * 96)
    print(f"{'来源':<6} {'指数':<11} {'字段':<9} {'天数':>5} {'平均|偏差|':>10} {'中位':>8} "
          f"{'P95':>8} {'最大':>8}")
    print("-" * 96)
    all_out = []
    for src, rows in (("东财", em_rows), ("中证", csi_rows)):
        for code in codes:
            for f in ("pe_ttm", "pe", "pb", "total_mv"):
                pairs = [(r, e) for c, d, ff, r, e in rows if c == code and ff == f]
                s = stat_block(pairs)
                if not s:
                    continue
                # 带符号平均（看系统性方向）
                signed = [pct(e, r) for cc, d, ff, r, e in rows
                          if cc == code and ff == f and e is not None]
                smean = sum(signed) / len(signed) if signed else 0
                print(f"{src:<6} {code:<11} {f:<9} {s['n']:>5} {s['mean']:>9.3f}% "
                      f"{s['median']:>7.3f}% {s['p95']:>7.3f}% {s['max']:>7.3f}%"
                      f"   带符号均值 {smean:+.3f}%")
                all_out.append((src, code, f, s, smean))

    # ---- CSV ----
    with open(OUT_CSV, "w", newline="", encoding="utf-8-sig") as fh:
        w = csv.writer(fh)
        w.writerow(["source", "code", "field", "date", "ref_tushare", "alt_value", "dev_pct"])
        for c, d, f, r, e in em_rows:
            p = pct(e, r)
            if p is not None:
                w.writerow(["em", c, f, d, r, e, round(p, 4)])
        for c, d, f, r, e in csi_rows:
            p = pct(e, r)
            if p is not None:
                w.writerow(["csi", c, f, d, r, e, round(p, 4)])
    print(f"\n明细已写 {OUT_CSV}（东财 {len(em_rows)} 行 + 中证 {len(csi_rows)} 行）")

    # ---- 分位数影响：用东财偏差重塑当前分位 ----
    print()
    print("若以东财口径为当前值、Tushare 历史为分位基线，全年平均偏差对应的分位移动：")
    for src, code, f, s, smean in all_out:
        if src != "em" or f not in ("pe_ttm", "pb"):
            continue
        h = sorted(x[f] for x in raw[code]["basic"] if x.get(f) is not None)
        cur = raw[code]["basic"][-1][f]
        p0 = 100 * sum(1 for x in h if x <= cur) / len(h)
        p1 = 100 * sum(1 for x in h if x <= cur * (1 + smean / 100)) / len(h)
        print(f"  {code:<11} {f:<7} 平均偏差 {smean:+.3f}% → 分位 {p0:.1f}% → {p1:.1f}%"
              f"（移 {abs(p1-p0):.1f}pp）")


if __name__ == "__main__":
    main()
