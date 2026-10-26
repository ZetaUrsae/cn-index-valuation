# -*- coding: utf-8 -*-
"""sync_tushare.py —— 每周一次的 Tushare 权威口径同步（方案 C）。

为什么需要这个脚本
------------------
本项目日常取数已全部改为新浪 / 东财 / 交易所官方接口，Tushare 调用量降到原来的
约 1/20。但有两个场景仍必须用 Tushare：

1. **历史段补齐**：东财全市场估值明细最早只到 2018-01-02，而报告的分位数
   依赖 2015 年起的完整序列，2015-01-05 ~ 2017-12-29 只能由 Tushare 提供。
2. **口径校准**：东财是「用今日成分股回溯历史」，遇到成分股调整的年份，
   与当年真实成分会有 2%~3% 偏差。每周用 Tushare 覆盖最近一段，
   保证报告最新读数与官方口径一致。

运行频率：每周一次（建议周六）。日常日报**不调用 Tushare**。

用法
----
    # 增量：只补 raw.json / pcr_raw.csv / etf_raw.json 的尾部
    python sync_tushare.py

    # 指定参考日
    ASOF=20261019 python sync_tushare.py

    # 补齐 2015 起的全部缺口（首次运行或历史库损坏后）
    python sync_tushare.py --full

退出码
------
0  成功（含「无缺口可补」）
1  Tushare 不可用（未装 tushare / 无 token / 积分不足）——非致命，主流程继续
2  至少一个域同步失败
"""
from __future__ import annotations

import argparse
import os
import sys
import traceback

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# 本脚本是「人工指令」入口：只有它才允许 Tushare 进入降级链。
# 必须在 import ivdata.config 之前设置（SETTINGS 在类定义时就读取环境变量）。
os.environ["IV_ALLOW_TUSHARE"] = "1"

from ivdata.config import DATA, SETTINGS                       # noqa: E402
from ivdata.store import CsvStore                             # noqa: E402

# Tushare 历史库的下界：2015-01-05 是报告的统计起点，不能变
HIST_FLOOR = "20150105"
# 增量窗口：每次补最近 N 天（覆盖法定长假 + 接口偶发缺日）
TAIL_DAYS = 45


def _pro():
    """惰性导入 Tushare，失败时给出可操作的提示而不是 traceback。"""
    try:
        from scripts.cfg import pro_api          # noqa: F401
    except Exception:                            # noqa: BLE001
        sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "scripts"))
    try:
        import cfg
        return cfg.pro_api()
    except Exception as e:                       # noqa: BLE001
        print("[tushare] 不可用: %s" % e, flush=True)
        return None


def _shift(ymd: str, days: int) -> str:
    import datetime
    d = datetime.datetime.strptime(ymd, "%Y%m%d").date()
    return (d + datetime.timedelta(days=days)).strftime("%Y%m%d")


def sync_valuation(pro, asof: str, full: bool = False) -> int:
    """指数估值（index_dailybasic）→ data/raw.json basic 段落。"""
    from ivdata.pipeline import load_json, _merge_by_date, _write_json
    from ivdata.config import INDEX_CODES, CODE2NAME

    raw = load_json(os.path.join(DATA, "raw.json")) or {}
    total = 0
    for code in INDEX_CODES:
        blk = raw.setdefault(code, {})
        blk["name"] = CODE2NAME.get(code, code)
        old = blk.get("basic") or []
        if full or not old:
            start = HIST_FLOOR
        else:
            start = max(_shift(old[-1]["trade_date"], -10), HIST_FLOOR)
        if start > asof:
            print(f"  [ts-valuation] {code} 已最新 ({old[-1]['trade_date']})", flush=True)
            continue
        try:
            df = pro.index_dailybasic(ts_code=code, start_date=start, end_date=asof,
                                      fields=("ts_code,trade_date,total_mv,float_mv,"
                                              "total_share,float_share,free_share,"
                                              "turnover_rate,turnover_rate_f,pe,pe_ttm,pb"))
        except Exception as e:                   # noqa: BLE001
            print(f"  [ts-valuation] {code} 失败: {e}", flush=True)
            continue
        if df is None or df.empty:
            print(f"  [ts-valuation] {code} 无数据 ({start}~{asof})", flush=True)
            continue
        rows = [{k: (None if v != v else v) for k, v in rec.items()}
                for rec in df.to_dict("records")]
        merged = _merge_by_date(old, rows)
        blk["basic"] = merged
        total += len(rows)
        print(f"  [ts-valuation] {code} +{len(rows)} → {len(merged)} 行 "
              f"(末 {merged[-1]['trade_date']})", flush=True)

    # ⚠ 不要把元信息写进 raw.json 顶层：process.py 会把它当作指数遍历而 KeyError
    _write_json(os.path.join(DATA, "raw.json"), raw)
    return total


def sync_quote(pro, asof: str, full: bool = False) -> int:
    """指数日线（index_daily）→ data/raw.json daily 段落。"""
    from ivdata.pipeline import load_json, _merge_by_date, _write_json
    from ivdata.config import INDEX_CODES

    raw = load_json(os.path.join(DATA, "raw.json")) or {}
    total = 0
    for code in INDEX_CODES:
        blk = raw.setdefault(code, {})
        old = blk.get("daily") or []
        start = "20191201" if (full or not old) else _shift(old[-1]["trade_date"], -10)
        if start > asof:
            continue
        try:
            df = pro.index_daily(ts_code=code, start_date=start, end_date=asof)
        except Exception as e:                   # noqa: BLE001
            print(f"  [ts-quote] {code} 失败: {e}", flush=True)
            continue
        if df is None or df.empty:
            continue
        rows = [{k: (None if v != v else v) for k, v in rec.items()}
                for rec in df.to_dict("records")]
        blk["daily"] = _merge_by_date(old, rows)
        total += len(rows)
        print(f"  [ts-quote] {code} +{len(rows)} → {len(blk['daily'])} 行", flush=True)
    _write_json(os.path.join(DATA, "raw.json"), raw)
    return total


def sync_etf(pro, asof: str) -> int:
    """ETF 份额 + 行情（fund_share / fund_daily）→ data/etf_raw.json。"""
    from ivdata.pipeline import load_json, _merge_by_date, _write_json
    from ivdata.config import ETF_ALL, OPT_MAIN

    blob = load_json(os.path.join(DATA, "etf_raw.json")) or {}
    shares = blob.get("shares") or {}
    fdaily = blob.get("fdaily") or {}
    main = blob.get("main") or dict(OPT_MAIN)
    total = 0
    for code in ETF_ALL:
        old_s = shares.get(code) or []
        start = _shift(old_s[-1]["trade_date"], -10) if old_s else _shift(asof, -400)
        try:
            df = pro.fund_share(ts_code=code, start_date=start, end_date=asof)
            if df is not None and not df.empty:
                rows = df.to_dict("records")
                shares[code] = _merge_by_date(old_s, rows)
                total += len(rows)
                print(f"  [ts-share] {code} +{len(rows)}", flush=True)
        except Exception as e:                   # noqa: BLE001
            print(f"  [ts-share] {code} 失败: {e}", flush=True)

        old_q = fdaily.get(code) or []
        start_q = _shift(old_q[-1]["trade_date"], -10) if old_q else _shift(asof, -400)
        try:
            df = pro.fund_daily(ts_code=code, start_date=start_q, end_date=asof)
            if df is not None and not df.empty:
                rows = df.to_dict("records")
                fdaily[code] = _merge_by_date(old_q, rows)
                total += len(rows)
                print(f"  [ts-etfq] {code} +{len(rows)}", flush=True)
        except Exception as e:                   # noqa: BLE001
            print(f"  [ts-etfq] {code} 失败: {e}", flush=True)

    _write_json(os.path.join(DATA, "etf_raw.json"),
                {"shares": shares, "fdaily": fdaily, "main": main})
    return total


def sync_pcr(pro, asof: str) -> int:
    """期权 PCR（opt_daily 逐合约汇总）→ data/pcr_raw.csv。

    仅在交易所官方接口出问题、或需要交叉校验时才跑。
    逐合约明细在 10 万行量级，调用次数较多，故单独设开关。
    """
    try:
        import fetch2b
    except Exception as e:                       # noqa: BLE001
        print(f"  [ts-pcr] 无法加载 fetch2b.py: {e}", flush=True)
        return 0
    try:
        fetch2b.main()
        return 1
    except Exception as e:                       # noqa: BLE001
        print(f"  [ts-pcr] 失败: {e}", flush=True)
        return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="Tushare 每周权威口径同步")
    ap.add_argument("--full", action="store_true", help="补齐 2015 起的全部历史缺口")
    ap.add_argument("--with-pcr", action="store_true", help="同时用 Tushare 重算期权 PCR")
    ap.add_argument("--asof", default=os.environ.get("ASOF", "").strip())
    args = ap.parse_args()

    from ivdata.config import SETTINGS
    asof = args.asof or SETTINGS.resolve_asof()
    print(f"[tushare-sync] 参考日 {asof}  full={args.full}  with_pcr={args.with_pcr}",
          flush=True)

    pro = _pro()
    if pro is None:
        return 1

    ok = True
    for name, fn in (("valuation", lambda: sync_valuation(pro, asof, args.full)),
                     ("quote", lambda: sync_quote(pro, asof, args.full)),
                     ("etf", lambda: sync_etf(pro, asof))):
        try:
            n = fn()
            print(f"[tushare-sync] {name} 完成，新增 {n} 行", flush=True)
        except Exception as e:                   # noqa: BLE001
            ok = False
            print(f"[tushare-sync] {name} 异常: {e}", flush=True)
            traceback.print_exc()

    if args.with_pcr:
        sync_pcr(pro, asof)

    return 0 if ok else 2


if __name__ == "__main__":
    sys.exit(main())
