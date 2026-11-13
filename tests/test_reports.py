# -*- coding: utf-8 -*-
"""报告保留策略与判重。

这两处是"看不见的规则"：保留策略决定哪些报告留在根目录、哪些进 archive；
判重决定定时任务当天跑不跑。写错不会报错，只会悄悄多跑/漏跑。
"""
import os
import time

import pytest

import run_daily
from tools.build_site import select_reports


def _items(dates, suffix=""):
    return [("%s-%s-%s" % (d[:4], d[4:6], d[6:]), "index_val_report_%s%s.html" % (d, suffix))
            for d in dates]


# ---------------------------------------------------------------- 保留策略

def test_keep_recent_and_monthly_anchor():
    dates = ["20261016", "20261019", "20261020", "20261021", "20261022",
             "20261023", "20261026", "20261027", "20261028", "20261029",
             "20261030", "20261102", "20261103"]
    kept = [fn for _, fn in select_reports(_items(dates), recent=3, monthly=True)]
    assert "index_val_report_20261016.html" in kept      # 10 月锚点，虽远超最近 3 期
    assert "index_val_report_20261102.html" in kept      # 11 月锚点
    assert "index_val_report_20261103.html" in kept      # 最新一期
    assert len(kept) == 3 + 1                            # 最近 3 期 ∪ {10 月锚}，11 月锚已在内


def test_recent_only_when_monthly_off():
    dates = ["20261016", "20261102", "20261103", "20261104"]
    kept = [fn for _, fn in select_reports(_items(dates), recent=2, monthly=False)]
    assert kept == ["index_val_report_20261104.html", "index_val_report_20261103.html"]


def test_selection_is_descending():
    dates = ["20261016", "20261102", "20261103"]
    kept = [iso for iso, _ in select_reports(_items(dates), recent=2, monthly=True)]
    assert kept == sorted(kept, reverse=True)


def test_empty_input():
    assert select_reports([]) == []


# ---------------------------------------------------------------- 自动归档

def _touch_reports(tmp_path, names):
    rep = tmp_path / "reports"
    rep.mkdir(exist_ok=True)
    for n in names:
        (rep / n).write_text("x", encoding="utf-8")
    return rep


def test_archive_moves_expired_only(tmp_path):
    # 10-16 是 10 月锚点（必须保留），10-20 既非锚点又不进最近 2 期 → 应归档
    dates = ["20261016", "20261020", "20261102", "20261103", "20261104"]
    rep = _touch_reports(tmp_path, [n for _, n in _items(dates)])

    moved = run_daily._archive_old_reports(recent=2, root=str(tmp_path))

    assert moved == ["index_val_report_20261020.html"]
    assert (tmp_path / "reports" / "archive" / moved[0]).exists()
    assert not (rep / moved[0]).exists()
    assert (rep / "index_val_report_20261016.html").exists()      # 月锚点保留
    assert (rep / "index_val_report_20261104.html").exists()


def test_archive_ignores_tagged_files(tmp_path):
    rep = _touch_reports(tmp_path, [
        "index_val_report_20261104.html",
        "index_val_report_20261001_test.html",
        "index_val_report_20261001_gh.html",
    ])
    run_daily._archive_old_reports(recent=1, root=str(tmp_path))
    assert (rep / "index_val_report_20261001_test.html").exists()
    assert (rep / "index_val_report_20261001_gh.html").exists()


def test_archive_noop_when_under_limit(tmp_path):
    _touch_reports(tmp_path, ["index_val_report_20261103.html",
                              "index_val_report_20261104.html"])
    assert run_daily._archive_old_reports(recent=5, root=str(tmp_path)) == []


# ---------------------------------------------------------------- 判重

def _set_mtime(path, ymd, hhmm):
    t = time.mktime(time.strptime("%s %s" % (ymd, hhmm), "%Y%m%d %H:%M"))
    os.utime(path, (t, t))


def test_missing_report_needs_run(tmp_path):
    (tmp_path / "reports").mkdir()
    need, why = run_daily._report_state("20261112", root=str(tmp_path))
    assert need is True
    assert "缺少" in why


def test_intraday_report_needs_rerun(tmp_path):
    rep = _touch_reports(tmp_path, ["index_val_report_20261112.html"])
    _set_mtime(rep / "index_val_report_20261112.html", "20261112", "10:30")
    need, why = run_daily._report_state("20261112", root=str(tmp_path))
    assert need is True
    assert "收盘前" in why


def test_final_report_skips(tmp_path):
    rep = _touch_reports(tmp_path, ["index_val_report_20261112.html"])
    _set_mtime(rep / "index_val_report_20261112.html", "20261112", "16:05")
    need, why = run_daily._report_state("20261112", root=str(tmp_path))
    assert need is False
    assert "已定稿" in why


def test_tagged_report_does_not_count(tmp_path):
    """试运行文件存在也不算"已定稿"，否则次日会误跳过。"""
    rep = _touch_reports(tmp_path, ["index_val_report_20261112_test.html"])
    need, _ = run_daily._report_state("20261112", root=str(tmp_path))
    assert need is True
    assert (rep / "index_val_report_20261112_test.html").exists()


@pytest.mark.parametrize("asof", ["20261001"])
def test_reason_mentions_asof(tmp_path, asof):
    (tmp_path / "reports").mkdir()
    _, why = run_daily._report_state(asof, root=str(tmp_path))
    assert asof in why
