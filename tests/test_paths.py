# -*- coding: utf-8 -*-
"""路径定义：全项目只在这里推导一次。

防的是本文档开头提到的两类事故——写死本机绝对路径、推导时漏尾部斜杠。
两条断言都很便宜，但能把"换台机器才炸"变成"本地就红"。
"""
import os

from ivdata import paths


def test_root_is_project_root():
    assert os.path.basename(paths.ROOT) == "index_valuation"
    assert os.path.isdir(paths.ROOT)
    assert os.path.isdir(os.path.join(paths.ROOT, "ivdata"))


def test_base_has_trailing_slash_and_joins_correctly():
    assert paths.BASE == paths.ROOT + "/"
    # 历史写法 BASE + "data/raw.json" 必须能拼出存在的路径
    assert os.path.isfile(paths.BASE + "data/raw.json")
    assert os.path.isfile(paths.BASE + "scripts/template2.html")


def test_named_dirs_exist():
    for d in (paths.DATA, paths.WORK, paths.REPORTS, paths.SCRIPTS, paths.ASSETS):
        assert os.path.isdir(d), d


def test_no_windows_separator():
    """统一正斜杠：混用会让 REGEX/日志/跨平台拼接出问题。"""
    assert "\\" not in paths.ROOT


def test_p_helper_ignores_stray_slashes():
    assert paths.p("data", "/raw.json") == paths.ROOT + "/data/raw.json"
    assert paths.p("data", "") == paths.ROOT + "/data"
