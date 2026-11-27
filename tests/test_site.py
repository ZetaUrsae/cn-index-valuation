# -*- coding: utf-8 -*-
"""发布门户与移动端补丁的静态护栏。

不联网、不构建站点，只确认模板里关键结构还在，避免以后改版时
把「PC 下拉 / 移动 chips / 历史报告补丁注入」中的某一环悄悄弄丢。
"""
from ivdata import paths


def _read(rel):
    with open(paths.ROOT + "/" + rel, encoding="utf-8") as f:
        return f.read()


def test_portal_has_pc_dropdown_and_mobile_chips():
    tpl = _read("tools/build_site.py")
    assert 'id="daypick"' in tpl              # PC 下拉
    assert 'id="list"' in tpl                 # 移动 chips
    assert 'daypick.onchange' in tpl          # 切换联动
    assert '__ITEMS__' in tpl and '__CLOUD__' in tpl   # 数据源占位符未丢


def test_template_has_mobile_patch_markers():
    tpl = _read("scripts/template2.html")
    for marker in ("MOBILE_CSS_BEGIN", "MOBILE_CSS_END",
                   "MOBILE_JS_BEGIN", "MOBILE_JS_END"):
        assert marker in tpl
    assert "position:sticky;left:0;z-index:2" in tpl   # 首列固定
    assert "@media(max-width:380px)" in tpl            # 超窄屏


def test_build_site_injects_mobile_patch_into_copies():
    src = _read("tools/build_site.py")
    assert "def _mobile_blocks" in src
    assert "MOBILE_CSS_BEGIN" in src and "MOBILE_JS_BEGIN" in src
