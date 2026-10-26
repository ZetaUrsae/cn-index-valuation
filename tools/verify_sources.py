# -*- coding: utf-8 -*-
"""verify_sources.py —— 数据源交叉校验工具。

用途
----
新管线以公开源（新浪/东财/交易所）为主、Tushare 为周度校准。这个脚本把
**同一份数据用多个源各取一遍**，给出偏差表，用来回答两个问题：

1. 主源今天是不是正常的？（有没有悄悄返回错数据）
2. 与 Tushare 的偏差还在可接受范围内吗？

它**不写任何生产文件**，只打印报表；每周 sync_tushare.py 之后跑一次即可。

用法
----
    # 校验最近一个交易日
    python tools/verify_sources.py

    # 指定日期
    python tools/verify_sources.py --asof 20261019

    # 只看估值
    python tools/verify_sources.py --only valuation

    # 导出 CSV（放到 work/ 便于留档）
    python tools/verify_sources.py --csv
"""
from __future__ import annotations

import argparse
import csv
import datetime
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from ivdata.config import INDEX_CODES, CODE2NAME, DATA, WORK   # noqa: E402
from ivdata.pipeline import load_json                          # noqa: E402

TOL = {               # 各域可接受的最大相对偏差（%）
    "valuation": 3.0,
    "quote": 0.2,
    "option_pcr": 10.0,
    "etf_share": 1.0,
}

# 中证官网口径是**静态 PE**，对成分类蓝筹（沪深300/上证50）与 TTM 接近，
# 对高成长（中证500/科创50）天然偏离很大。只有落在「同类可比」名单里才判阈值。
CSI_COMPARABLE = {"000300.SH", "000016.SH"}
JUMP_TOL = 15.0       # 单日估值跳变阈值（%）：指数 PE/PB 一天不可能变这么多


def _pct(a, b):
    if not a or not b:
        return None
    try:
        return (float(a) / float(b) - 1) * 100
    except (ZeroDivisionError, TypeError, ValueError):
        return None


def _fmt(v, nd=3):
    return "—" if v is None else f"{v:.{nd}f}"


def check_valuation(asof: str) -> list:
    """东财聚合 vs 中证官方（静态 PE）vs 本地历史稳定性。

    ⚠ 参照值说明：新管线日常不调用 Tushare，所以 raw.json 里当日的值
    本身就是东财写的，拿它做参照会恒等于 0（无意义的自比）。
    真正有意义的两条校验是：

    1. **中证官网** —— 独立第三方，但它是**静态 PE**（不是 TTM），
       所以对沪深300/上证50 应当在 ±3% 内，对中证500/科创50 天然偏离
       10%~45%（成长股盈利波动大）。这里只用它抓「数量级错乱」，
       不当作精度基准。
    2. **历史跳变** —— 当日值与前一日相比，PE/PB 变动超过 15%
       基本可以判定取数出错（指数单日估值不可能这样跳）。
    """
    from ivdata.providers.em import EmValuation
    from ivdata.providers.csi import CsiValuation

    raw = load_json(os.path.join(DATA, "raw.json")) or {}
    rows = []
    em = EmValuation()
    csi = CsiValuation()

    for code in INDEX_CODES:
        hist = sorted(((raw.get(code) or {}).get("basic") or []),
                      key=lambda r: r["trade_date"])
        prev = None
        for r in hist:
            if r["trade_date"] < asof:
                prev = r
        ref = next((r for r in hist if r["trade_date"] == asof), None)

        em_row, csi_row = None, None
        try:
            em_row = em.fetch_valuation(code, asof, asof)[-1]
        except Exception as e:                   # noqa: BLE001
            print(f"  [东财] {code} 失败: {str(e)[:80]}")
        try:
            csi_row = csi.fetch_valuation(code, asof, asof)[-1]
        except Exception:                        # noqa: BLE001
            csi_row = None                       # 创业板指本来就无中证口径

        for field in ("pe_ttm", "pb"):
            rows.append({
                "domain": "valuation",
                "code": code,
                "name": CODE2NAME.get(code, code),
                "field": field,
                "ref_tushare": prev.get(field) if prev else None,   # 实际是「前一日」
                "primary_em": em_row.get(field) if em_row else None,
                "cross_csi": csi_row.get(field) if csi_row else None,
                "stored": ref.get(field) if ref else None,
                "label_ref": "前一日",
            })
    return rows


def check_quote(asof: str) -> list:
    """新浪 vs 东财：两个独立源当日报价，当日直接对拍。

    行情是「收盘价」这种唯一事实，两源应当逐位相同（容差 0.2% 已经很宽）。
    本地 raw.json 当日的值就是主源写的，不能作参照（自比恒 0）。

    ⚠ 东财行情接口是**实时快照**，只支持 asof == 今天。若校验历史日期，
    东财会返回今天的数据，与新浪的历史值不可比，此时跳过东财对照。
    """
    from ivdata.providers.sina import SinaQuote
    from ivdata.providers.em import EmQuote

    today = datetime.date.today().strftime("%Y%m%d")
    use_em = (asof == today)

    sina = SinaQuote()
    em = EmQuote() if use_em else None
    rows = []
    for code in INDEX_CODES:
        try:
            s = sina.fetch_quote(code, asof, asof)[-1]
        except Exception as e:                   # noqa: BLE001
            print(f"  [新浪] {code} 失败: {str(e)[:80]}")
            continue
        e_ = None
        if em:
            try:
                e_ = em.fetch_quote(code, asof, asof)[-1]
            except Exception:                    # noqa: BLE001
                e_ = None
        rows.append({
            "domain": "quote", "code": code, "name": CODE2NAME.get(code, code),
            "field": "close",
            "ref_tushare": e_.get("close") if e_ else None,   # 东财作对照
            "primary_em": s.get("close"),                     # 新浪为主源
            "cross_csi": None,
            "label_ref": "东财",
        })
    return rows


def check_pcr(asof: str) -> list:
    """交易所官方 vs Tushare 历史同日值。

    日常运行不写 Tushare，所以这里比较的是「交易所今日值」与
    「pcr_raw.csv 里由 sync_tushare.py 周度写入的 Tushare 同日值」。
    若该日没有 Tushare 记录（正常情况），则只做「前一日跳变」校验。
    """
    from ivdata.providers.exchange import ExchangePcr
    from ivdata.store import CsvStore

    store = CsvStore("pcr_raw.csv")
    old = {(r["date"], r["oc"]): r for r in store.load()}
    try:
        fresh = ExchangePcr().fetch_option_pcr(asof, asof)
    except Exception as e:                       # noqa: BLE001
        print(f"  [交易所] PCR 失败: {str(e)[:100]}")
        return []

    # 每个合约的上一交易日值，作为跳变基准
    prev_by_oc = {}
    for (d, oc), r in old.items():
        if d < asof:
            if oc not in prev_by_oc or d > prev_by_oc[oc][0]:
                prev_by_oc[oc] = (d, float(r["oi_pcr"]) if r.get("oi_pcr") else None)

    rows = []
    for r in fresh:
        k = (r["date"], r["oc"])
        ref = old.get(k)                       # 同日的 Tushare 记录（周度同步才有）
        base = (float(ref["oi_pcr"]) if ref and ref.get("oi_pcr")
                else (prev_by_oc.get(r["oc"]) or (None, None))[1])
        rows.append({
            "domain": "option_pcr", "code": r["oc"], "name": r["oc"],
            "field": "oi_pcr",
            "ref_tushare": base,
            "primary_em": r.get("oi_pcr"),
            "cross_csi": None,
            "label_ref": "Tushare" if ref else "前一日",
        })
    return rows


def report(rows: list, asof: str, to_csv: bool = False) -> int:
    """打印偏差表，返回「判定异常」的条数。"""
    if not rows:
        print("没有可比对的数据。")
        return 0

    print()
    print("=" * 104)
    print(f"数据源交叉校验  参考日 {asof}")
    print("=" * 104)
    print(f"{'域':<10}{'标的':<11}{'字段':<8}{'对照源':>10}{'主源':>10}{'偏差%':>9}"
          f"{'中证':>10}{'vs中证%':>9}  判定")
    print("-" * 104)

    bad = 0
    for r in rows:
        jump = _pct(r["primary_em"], r["ref_tushare"])
        d_csi = _pct(r["cross_csi"], r["primary_em"])
        flags = []
        tol = TOL.get(r["domain"], 3.0)

        # 1) 与对照源的偏差：同一事实两源应当一致，超容差即需人工看
        #    估值例外——平日对照值是「前一日」，那是跳变校验（见 2）。
        if r["domain"] == "valuation":
            pass
        elif jump is not None and abs(jump) > tol:
            flags.append(f"vs{r.get('label_ref', '对照')}超阈")

        # 2) 单日跳变：指数估值不可能一天变动 15% 以上，超了就是取数出错
        if jump is not None and abs(jump) > JUMP_TOL:
            flags.append("日变动异常")

        # 3) 中证交叉：仅对「静态 PE ≈ TTM」的宽基做阈值判定。
        #    中证只给静态 PE，所以 PB 行、以及成长类指数不判。
        if (r["field"] == "pe_ttm" and r["code"] in CSI_COMPARABLE
                and d_csi is not None and abs(d_csi) > TOL["valuation"]):
            flags.append("vs中证超阈")

        if flags:
            bad += 1
        print(f"{r['domain']:<10}{r['code']:<11}{r['field']:<8}"
              f"{_fmt(r['ref_tushare'], 4):>10}{_fmt(r['primary_em'], 4):>10}"
              f"{_fmt(jump, 2):>9}{_fmt(r['cross_csi'], 4):>10}{_fmt(d_csi, 2):>9}"
              f"  {'OK' if not flags else ' / '.join(flags)}")

    print("-" * 104)
    print(f"容差：估值跳变 ±{JUMP_TOL}%；行情/份额 ±{TOL['quote']}%；PCR ±{TOL['option_pcr']}%")
    print(f"中证交叉仅对 {sorted(CSI_COMPARABLE)} 的 PE 判 ±{TOL['valuation']}%"
          f"（中证为静态 PE，成长类指数不可比）")
    print(f"异常 {bad} 条 / 共 {len(rows)} 条")

    if to_csv:
        path = os.path.join(WORK, f"verify_{asof}.csv")
        with open(path, "w", encoding="utf-8-sig", newline="") as f:
            names = ["domain", "code", "name", "field", "ref_source",
                     "ref_value", "primary_value", "diff_pct", "diff_csi_pct"]
            w = csv.DictWriter(f, fieldnames=names)
            w.writeheader()
            for r in rows:
                w.writerow({
                    "domain": r["domain"], "code": r["code"], "name": r["name"],
                    "field": r["field"],
                    "ref_source": r.get("label_ref", "前一日"),
                    "ref_value": r["ref_tushare"], "primary_value": r["primary_em"],
                    "diff_pct": _round(_pct(r["primary_em"], r["ref_tushare"])),
                    "diff_csi_pct": _round(_pct(r["cross_csi"], r["primary_em"])),
                })
        print(f"明细已导出：{path}")

    return bad


def _round(v, nd=3):
    return "" if v is None else round(v, nd)


def main() -> int:
    ap = argparse.ArgumentParser(description="数据源交叉校验")
    ap.add_argument("--asof", default="")
    ap.add_argument("--only", default="", help="valuation / quote / option_pcr")
    ap.add_argument("--csv", action="store_true", help="导出明细到 work/")
    args = ap.parse_args()

    asof = args.asof
    if not asof:
        from ivdata.config import SETTINGS
        asof = SETTINGS.resolve_asof()

    want = args.only.strip()
    rows = []
    if want in ("", "valuation"):
        print(f"[1/3] 估值：东财聚合 vs 前一日（中证静态PE 作交叉）...")
        rows += check_valuation(asof)
    if want in ("", "quote"):
        print(f"[2/3] 行情：新浪 vs 东财...")
        rows += check_quote(asof)
    if want in ("", "option_pcr"):
        print(f"[3/3] 期权 PCR：交易所官方 vs Tushare/前一日...")
        rows += check_pcr(asof)

    bad = report(rows, asof, args.csv)
    return 0 if bad == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
