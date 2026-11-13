# -*- coding: utf-8 -*-
"""run_daily.py —— 宽基指数估值日报 · v2 管线（主入口）。

取数特点
--------
* 数据源全部为公开接口：新浪 / 东财 / 上交所 / 深交所 / 中证官网；
* 每个数据域配 provider 优先级链，前一个源失败自动降级（见 ivdata/config.py）；
* 每次运行记录溯源（work/provenance.json），报告与排错都能查到数据出处。

用法
----
    # 日常（定时任务调这个）
    python run_daily.py

    # 只判断要不要出新报告（定时任务的第一步；1 发日历请求，不取数）
    python run_daily.py --check

    # 指定参考交易日
    ASOF=20261019 python run_daily.py

    # 试运行：报告名带 _test 标记，定时任务的判重不会因此跳过
    python run_daily.py --tag test          # → index_val_report_20261020_test.html

    # 强制某域走某源（排障用）
    IV_FORCE="valuation=em_valuation" python run_daily.py

    # 只取数不生成报告（调试）
    python run_daily.py --fetch-only
"""
from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.join(ROOT, "scripts")
PY = sys.executable

sys.path.insert(0, ROOT)
sys.path.insert(0, SCRIPTS)

# 取数之后的加工步骤与旧管线完全相同：
# 新管线只负责产出 data/ 下的历史库，加工与排版全部复用，保证报告一字不变。
STEPS = [
    ("估值计算", "process.py"),
    ("技术面指标", "tech.py"),
    ("期权元信息", "meta.py"),
    ("PCR与份额指标", "proc2.py"),
    ("技术面扩展", "prep.py"),
    ("组装报告", "gen2.py"),
]


def _run(script: str, env: dict) -> tuple:
    r = subprocess.run([PY, "-u", os.path.join(SCRIPTS, script)],
                       cwd=SCRIPTS, env=env, capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    return r.returncode, (r.stdout or ""), (r.stderr or "")


def _latest_quote_date() -> str:
    """库内五只指数日线的最新交易日（用于识别"回算旧日期"）。"""
    import json
    raw = json.load(open(os.path.join(ROOT, "data", "raw.json"), encoding="utf-8"))
    dates = []
    for blk in raw.values():
        daily = blk.get("daily") or []
        if daily:
            dates.append(str(daily[-1].get("trade_date")))
    return max(dates) if dates else ""


def _report_state(asof: str, root: str = "") -> tuple:
    """判断参考交易日的报告是否已经「定稿」，返回 (是否需要跑, 原因)。

    判据不是「文件在不在」，而是「文件是不是收盘后生成的」：
    盘中/试运行也会产出同名文件，但里面的份额、PCR 是当日未定稿值，
    次日必须重跑覆盖。收盘时间按 15:00 计（A 股 15:00 收盘，数据当晚定稿）。

    ⚠ 只看**正式文件名**（不带 `_xxx` 试运行标记）。手工试运行的产物另存为
    `index_val_report_<asof>_<tag>.html`，不参与判重，否则一次盘后试跑就会
    让次日的定时任务误判为「已跑过」而跳过。
    """
    root = root or ROOT
    out = os.path.join(root, "reports", "index_val_report_%s.html" % asof)
    extra = _tagged_reports(asof, root)
    tail = ("；另有试运行文件 %s（不计入判重）" % ", ".join(extra)) if extra else ""
    if not os.path.exists(out):
        return True, "缺少 %s 的报告%s" % (asof, tail)
    close = time.mktime(time.strptime(asof + " 15:00", "%Y%m%d %H:%M"))
    mtime = os.path.getmtime(out)
    if mtime < close:
        return True, ("%s 的报告生成于 %s（收盘前），属试运行/盘中产物，需重跑覆盖%s"
                      % (asof, time.strftime("%m-%d %H:%M", time.localtime(mtime)), tail))
    return False, "%s 的报告已于 %s 生成，数据已定稿%s" % (
        asof, time.strftime("%m-%d %H:%M", time.localtime(mtime)), tail)


def _tagged_reports(asof: str, root: str = "") -> list:
    """列出该交易日的试运行报告（文件名带标记）。"""
    import glob
    pat = os.path.join(root or ROOT, "reports", "index_val_report_%s_*.html" % asof)
    return sorted(os.path.basename(p) for p in glob.glob(pat))


def _write_latest_copy(out: str) -> None:
    """把本次报告复制成 reports/latest.html —— 固定入口，本地收藏后不必再改日期戳。

    用**副本**而不是跳转壳：打开就是内容，不会先闪一下跳转页。
    体积与正文相同（约 350 KB），已列入 .gitignore，只存在于本地，
    避免仓库每天多存一份；云端入口由 actions 分支的根 index.html 承担。
    """
    import shutil
    dst = os.path.join(ROOT, "reports", "latest.html")
    tmp = dst + ".tmp"
    shutil.copyfile(out, tmp)
    os.replace(tmp, dst)


REPORT_RE = re.compile(r"^index_val_report_(\d{8})\.html$")


def _archive_old_reports(recent: int = 10, root: str = "") -> list:
    """把超出保留期的报告移入 reports/archive/（保留策略与站点一致：最近 N 期 + 每月首个交易日）。

    - 规则与 `tools/build_site.py::select_reports` 相同，避免两处口径分叉；
    - 只认正式文件名 `index_val_report_YYYYMMDD.html`，`_gh` / `_test` / `_band` 一律不动；
    - 纯本地重命名（git 识别为 rename，历史不丢），几十个文件的量级，耗时毫秒级。
    """
    rep = os.path.join(root or ROOT, "reports")
    items = []
    for fn in os.listdir(rep):
        m = REPORT_RE.match(fn)
        if m:
            items.append((m.group(1), fn))
    if len(items) <= recent:
        return []
    items.sort(reverse=True)
    keep = {fn for _, fn in items[:recent]}
    anchors = {}
    for d, fn in sorted(items):          # 升序 → 每月第一条即该月最早
        anchors.setdefault(d[:6], fn)
    keep |= set(anchors.values())

    arch = os.path.join(rep, "archive")
    moved = []
    for _, fn in items:
        if fn in keep:
            continue
        os.makedirs(arch, exist_ok=True)
        os.replace(os.path.join(rep, fn), os.path.join(arch, fn))
        moved.append(fn)
    return sorted(moved)


def _verify_quotes(asof: str) -> None:
    """校验 asof 当日五只指数的行情确实取到了。

    日历说今天是交易日 ≠ 今天真的有交易：临时休市（台风、哀悼日）不在日历里，
    或交易所数据延迟时，若不检查就会把**旧数据标成 asof 的新日期**。
    这里硬校验：五只指数的 daily 里必须有 trade_date == asof 的行，缺任何一只就停手。
    """
    import json
    from ivdata.config import CODE2NAME, INDEX_CODES
    raw = json.load(open(os.path.join(ROOT, "data", "raw.json"), encoding="utf-8"))
    missing = []
    for code in INDEX_CODES:
        daily = (raw.get(code) or {}).get("daily") or []
        if not any(str(d.get("trade_date")) == asof for d in daily):
            missing.append("%s(%s)" % (CODE2NAME.get(code, code), code))
    if missing:
        raise SystemExit(
            "\n!! asof=%s 当日行情缺失：%s\n"
            "   可能是临时休市（日历未收录）或数据源延迟。为避免把旧数据标成 %s，\n"
            "   本次不生成报告；请人工确认该日是否交易、或改用 --asof 指定上一交易日。"
            % (asof, "、".join(missing), asof))
    print("行情校验：五只指数 %s 当日数据齐全" % asof)


def main() -> int:
    ap = argparse.ArgumentParser(description="宽基指数估值日报 v2 管线")
    ap.add_argument("--fetch-only", action="store_true", help="只取数，不生成报告")
    ap.add_argument("--skip-bond", action="store_true", help="跳过 10Y 国债补齐")
    ap.add_argument("--asof", default="", help="参考交易日 YYYYMMDD")
    ap.add_argument("--check", action="store_true",
                    help="只判断最近交易日是否需要出新报告，输出 RUN/SKIP 后退出")
    ap.add_argument("--tag", default="", metavar="NAME",
                    help="试运行标记：报告存为 index_val_report_<asof>_NAME.html，"
                         "不参与定时任务判重（等同 IV_REPORT_TAG=NAME）")
    args = ap.parse_args()

    if args.tag:
        os.environ["IV_REPORT_TAG"] = args.tag

    if args.asof:
        os.environ["ASOF"] = args.asof

    from ivdata.pipeline import Pipeline
    from ivdata import http

    t0 = time.time()
    p = Pipeline()
    asof = p.resolve_asof()
    # 回填到进程环境：后面 `from cfg import …`（以及子进程）直接用这个 asof，
    # 不再各自推导一次（cfg 推导要发一次日历请求，多进程重复推导纯属浪费且可能不一致）。
    os.environ["ASOF"] = asof

    if args.check:
        need, why = _report_state(asof)
        print("%s %s  %s" % ("RUN" if need else "SKIP", asof, why))
        return 0

    # 回算旧日期会产出"日期混搭"的报告：加工链（tech.py / prep.py）取的是库内最新行，
    # 不按 ASOF 切片，所以 asof 小于库内最新交易日时，估值是旧的、技术面是新的。
    # 取数补数请用 --fetch-only；出报告只允许最新交易日。
    latest = _latest_quote_date()
    if latest and asof < latest and not args.fetch_only:
        raise SystemExit(
            "\n!! --asof %s 早于库内最新交易日 %s：加工链用库内最新数据，"
            "回算会产出日期混搭的报告。\n   只补数据请用 --fetch-only；出报告请用最新交易日。"
            % (asof, latest))

    print("=" * 68)
    print("宽基指数估值与多维跟踪 · 日报 v2 管线")
    print("参考交易日 ASOF = %s" % asof)
    if os.environ.get("IV_REPORT_TAG"):
        print("试运行标记 = %s（报告另存，不影响定时任务判重）" % os.environ["IV_REPORT_TAG"])
    print("=" * 68, flush=True)

    failed: list = []

    # ---------- 1. 取数 ----------
    print("\n[1/4] 指数行情（新浪 → 中证 → 东财）", flush=True)
    try:
        p.sync_quotes()
    except Exception as e:                       # noqa: BLE001
        failed.append("quotes")
        print("  !! 行情取数异常: %s" % e, flush=True)
    _verify_quotes(asof)        # 临时休市/数据延迟时在此停手，防止旧数据标成新日期

    print("\n[2/4] 指数估值（东财成分股加权）", flush=True)
    try:
        p.sync_valuations()
    except Exception as e:                       # noqa: BLE001
        failed.append("valuations")
        print("  !! 估值取数异常: %s" % e, flush=True)

    print("\n[3/4] 期权 PCR（上交所/深交所官方）", flush=True)
    try:
        p.sync_pcr()
    except Exception as e:                       # noqa: BLE001
        failed.append("pcr")
        print("  !! PCR 取数异常: %s" % e, flush=True)

    print("\n[4/4] ETF 份额与行情", flush=True)
    try:
        p.sync_etfs()
    except Exception as e:                       # noqa: BLE001
        failed.append("etfs")
        print("  !! ETF 取数异常: %s" % e, flush=True)

    if not args.skip_bond:
        try:
            p.sync_bond10y()
        except Exception as e:                   # noqa: BLE001
            print("  !! 10Y 国债补齐异常（非致命）: %s" % e, flush=True)

    # 指数收盘价历史（PE/PB Band 用）：东财 K 线增量，非致命（fetch_close_hist.py 自吞异常）
    print("\n[补] 指数收盘价历史（东财 K 线增量，非致命）", flush=True)
    try:
        rc, out, err = _run("fetch_close_hist.py", dict(os.environ, ASOF=asof))
        for line in out.strip().splitlines()[-7:]:
            print("    " + line)
        if rc != 0:
            print("    !! close_hist rc=%s（非致命，继续）" % rc)
    except Exception as e:                       # noqa: BLE001
        print("  !! close_hist 调用失败（非致命）: %s" % e, flush=True)

    # 股指期货当月连续 + 中证1000 现货（情绪面升贴水图用）：非致命
    print("\n[补] 股指期货当月连续（新浪）与中证1000 现货（非致命）", flush=True)
    try:
        rc, out, err = _run("fetch_futures.py", dict(os.environ, ASOF=asof))
        for line in out.strip().splitlines()[-6:]:
            print("    " + line)
        if rc != 0:
            print("    !! futures rc=%s（非致命，继续）" % rc)
    except Exception as e:                       # noqa: BLE001
        print("  !! futures 调用失败（非致命）: %s" % e, flush=True)

    # ---------- 溯源 ----------
    prov_path = p.finish()
    print("\n数据来源溯源：")
    print(p.r.prov.report())
    print("\n溯源明细已写入 %s" % prov_path)
    req = http.request_count()
    print("本次网络请求 %d 次：%s" % (sum(req.values()),
                                  ", ".join("%s=%d" % kv for kv in sorted(req.items()))))

    if args.fetch_only:
        print("\n--fetch-only 指定，跳过报告生成。用时 %.0fs" % (time.time() - t0))
        return 1 if failed else 0

    # ---------- 2. 加工与排版 ----------
    env = dict(os.environ, ASOF=asof)
    for i, (label, script) in enumerate(STEPS, 1):
        print("\n[加工 %d/%d] %s (%s) ..." % (i, len(STEPS), label, script), flush=True)
        rc, out, err = _run(script, env)
        for line in out.strip().splitlines()[-6:]:
            print("    " + line)
        if rc != 0:
            print("    !! 失败 rc=%s" % rc)
            print(err[-1500:])
            failed.append(script)
            break

    print("\n" + "=" * 68)
    if failed:
        print("未完成，失败环节：%s" % ", ".join(failed))
        return 1
    from cfg import REPORT_TAG, report_path
    out = report_path(asof, REPORT_TAG)
    try:
        _write_latest_copy(out)
    except OSError as e:
        # 纯本地便利功能（固定入口副本），失败不能让已产出的报告被判为失败
        print("  [warn] latest.html 副本未更新：%s" % e)
    try:
        moved = _archive_old_reports()
        if moved:
            print("  归档 %d 份超期报告 → reports/archive/" % len(moved))
    except OSError as e:
        print("  [warn] 自动归档未完成：%s" % e)
    print("完成，用时 %.0fs" % (time.time() - t0))
    print("输出: %s" % out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
