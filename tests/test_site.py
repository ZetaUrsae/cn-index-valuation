# -*- coding: utf-8 -*-
"""发布门户与移动端补丁的静态护栏。

不联网、不构建站点，只确认模板里关键结构还在，避免以后改版时
把「PC 下拉 / 移动 chips / 历史报告补丁注入」中的某一环悄悄弄丢。
"""
from ivdata import paths


def _read(rel):
    with open(paths.ROOT + "/" + rel, encoding="utf-8") as f:
        return f.read()


def test_portal_uses_single_dropdown():
    tpl = _read("tools/build_site.py")
    assert 'id="daypick"' in tpl              # 顶部下拉（PC 与手机共用）
    assert 'id="list"' not in tpl             # 移动端 chips 已移除
    assert 'daypick.onchange' in tpl          # 切换联动
    assert 'pick(parseInt(daypick.value, 10), true)' in tpl   # 主动切换才写 hash
    assert 'pick(start, false)' in tpl        # 初始加载不写 hash
    assert '__ITEMS__' in tpl and '__CLOUD__' in tpl   # 数据源占位符未丢


def test_template_has_mobile_patch_markers():
    tpl = _read("scripts/template2.html")
    for marker in ("MOBILE_CSS_BEGIN", "MOBILE_CSS_END",
                   "MOBILE_JS_BEGIN", "MOBILE_JS_END"):
        assert marker in tpl
    assert "position:sticky;left:0;z-index:2" in tpl   # 首列固定
    assert "@media(max-width:380px)" in tpl            # 超窄屏

    # v2.8.0：所有新移动规则都必须在标记块内（PC 零影响）
    css = tpl.split("MOBILE_CSS_BEGIN", 1)[1].split("MOBILE_CSS_END", 1)[0]
    for rule in ("grid-template-columns:1fr", "mob-cards", ".note.folded",
                 "header .idxlist{display:none;}", ".sec-title .en{display:none;}",
                 "#tb-fut td:first-child"):
        assert rule in css, rule

    # 护栏：标记块内的每一条 CSS 规则都必须落在 @media 里，防止 PC 端被误伤。
    import re
    bare = css
    for m in list(re.finditer(r"@media\([^)]*\)\s*\{", css)):
        start = m.end()
        depth = 1
        i = start
        while i < len(css) and depth:
            if css[i] == "{":
                depth += 1
            elif css[i] == "}":
                depth -= 1
            i += 1
        bare = bare[:m.start()] + " " * (i - m.start()) + bare[i:]
    bare = re.sub(r"/\*.*?\*/", "", bare, flags=re.S)
    assert "{" not in bare, "MOBILE_CSS 块内有裸规则（会污染 PC 端）"
    js = tpl.split("MOBILE_JS_BEGIN", 1)[1].split("MOBILE_JS_END", 1)[0]
    assert "MOBILE_CHART" in js and "classList.add('mob-cards')" in js


def test_build_site_injects_mobile_patch_into_copies():
    src = _read("tools/build_site.py")
    assert "def _mobile_blocks" in src
    assert "MOBILE_CSS_BEGIN" in src and "MOBILE_JS_BEGIN" in src
