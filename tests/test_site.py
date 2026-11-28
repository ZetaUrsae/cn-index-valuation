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
    assert '#open{display:none;}' in tpl      # v2.9.0 手机端隐藏「新窗口打开」
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
                 "#tb-fut td.fut-name", "#t-fut td:first-child:not(.fut-name)",
                 "#t-matrix.mob-cards tr{display:grid",
                 "details.mob-fold>summary::after"):
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

    # v2.9.0：移动端折叠块 / 信号矩阵隐列 / 表头底色 / 字号，全部落在正确作用域
    for rule in ("#t-matrix th:nth-child(6),#t-matrix td:nth-child(6){display:none !important;}",
                 "#sum-card p:not(.note){font-size:12px;line-height:1.68;}",
                 "background:linear-gradient(180deg,#16345f,#12294b);}"):
        assert rule in css, rule
    assert "d.open = false;" in js               # 移动端默认收起 .mob-fold
    # 折叠结构：foot 两端折叠（无 open）；四处 mob-fold 带 open（PC 展开）
    assert '<details class="foot-fold">' in tpl
    assert tpl.count('<details class="mob-fold" open>') == 4
    # 矩阵卡片短标签（去掉表头括号注释）
    assert "s.replace(/（[^）]*）/g, '')" in js
    # v2.9.3：图例色点删除，分档文字并入 note（纯文字、只出现一次）
    assert 'id="lg-val"' not in tpl
    assert "document.getElementById('lg-val')" not in tpl
    assert "估值状态</b>按 <b>PE(TTM) 近10年分位</b>判定：" in tpl
    _vnote = tpl.split('· <b>估值状态</b>', 1)[1].split('</div>', 1)[0]
    for level in ("低估(&lt;20%)", "偏低(20–40%)", "适中(40–60%)", "偏高(60–80%)", "高估(&gt;80%)"):
        assert _vnote.count(level) == 1, level
    assert "分档见下方图例" not in tpl
    # 估值走势小字：来源移到 footer 折叠区，图下不再重复
    assert "估值带收盘价</b>：2015~2019 为一次性回填的历史序列" in tpl
    assert "收盘价来源：2015~2019" not in tpl
    # 情绪面 hint 精简、机构展望 hint 移除（非一手来源已在 footer）
    assert "情绪越偏乐观</span>" in tpl and "看跌保护需求越弱" not in tpl
    assert "外资投行观点（按机构）</summary>" in tpl
    # 总结改用 sec-title 作 summary，sum-hint 已移除
    assert '<summary class="sec-title">总结' in tpl
    assert "sum-hint" not in tpl
    # 措辞：偏低估已改偏低（模板图例 + gen2 状态函数）
    assert "偏低估" not in tpl
    gen2 = _read("scripts/gen2.py")
    assert 'return ("偏低", "s2")' in gen2
    # 章节标题：资金面去「变化」、情绪面去括号
    assert "二、资金面：ETF 基金份额 <span" in tpl
    assert "三、情绪面：持仓 PCR <span" in tpl


def test_build_site_injects_mobile_patch_into_copies():
    src = _read("tools/build_site.py")
    assert "def _mobile_blocks" in src
    assert "MOBILE_CSS_BEGIN" in src and "MOBILE_JS_BEGIN" in src
