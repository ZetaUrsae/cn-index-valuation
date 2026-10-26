# -*- coding: utf-8 -*-
"""重排 template2.html 的章节顺序：基本面 -> 资金面 -> 情绪面 -> 技术面 -> 总结；标的对照移至附录。"""
p = "D:/QClaw/Stock/index_valuation/scripts/template2.html"
s = open(p, encoding="utf-8").read()

M0  = "\n  <!-- 结论先行 -->"
M1  = "\n  <!-- ① 标的对照 -->"
M2  = "\n  <!-- ② 核心估值表 -->"
M3  = "\n  <!-- 估值横向对比 -->"
M4  = "\n  <!-- ③ 四维跟踪 -->"
M5  = "\n  <!-- 3.1 情绪面 -->"
M6  = "\n  <!-- 3.2 资金面 -->"
M7  = "\n  <!-- 3.3 技术面 -->"
M8  = "\n  <!-- 3.4 基本面 -->"
M9  = "\n  <!-- ④ 四维信号矩阵 -->"
M10 = "\n  <!-- 综合结论 -->"
M11 = "\n  <footer>"

marks = [M0, M1, M2, M3, M4, M5, M6, M7, M8, M9, M10, M11]
idx = []
for m in marks:
    assert m in s, "missing marker: " + m
    idx.append(s.index(m))

head = s[:idx[0]]
B_sum    = s[idx[0]:idx[1]]
B_inst   = s[idx[1]:idx[2]]
B_val    = s[idx[2]:idx[3]]
B_cross  = s[idx[3]:idx[4]]
B_hdr4   = s[idx[4]:idx[5]]
B_sent   = s[idx[5]:idx[6]]
B_fund   = s[idx[6]:idx[7]]
B_tech   = s[idx[7]:idx[8]]
B_fundmt = s[idx[8]:idx[9]]
B_matrix = s[idx[9]:idx[10]]
B_concl  = s[idx[10]:idx[11]]
tail     = s[idx[11]:]


def body_from(block, anchor):
    """取 block 中从 anchor 开始的内容（丢弃标题行）"""
    return block[block.index(anchor):]


# ---------- 1) 顶部：结论卡片 -> 核心指标速览 ----------
new_sum = ("\n  <!-- 核心指标速览 -->\n"
           "  <div class=\"card\" style=\"padding:16px 20px;\">\n"
           "    <div class=\"kpi\" id=\"kpi\"></div>\n"
           "  </div>\n")

# ---------- 2) 一、基本面：估值分析 ----------
val_body = body_from(B_val, '<div class="card"><div class="tblwrap">')
new_val = ("\n  <!-- 一、基本面 -->\n"
           "  <div class=\"sec-title\">一、基本面：估值分析 <span class=\"en\">Fundamentals · Valuation</span></div>\n"
           "  <div class=\"sub-title\"><span class=\"badge\">估值概览</span>核心估值表 <span class=\"hint\">"
           "PE(TTM) / PB(LF) / 历史分位 / 股息率 / 股债性价比</span></div>\n"
           "  " + val_body)

# ---------- 3) 估值横向对比（作为基本面子块） ----------
cross_body = body_from(B_cross, '<div class="grid2">')
new_cross = ("\n  <!-- 估值横向对比 -->\n"
             "  <div class=\"sub-title\"><span class=\"badge\">横向对比</span>PE / PB / 股息率 / 估值走势 "
             "<span class=\"hint\">四图速览</span></div>\n"
             "  " + cross_body)

# ---------- 4) 机构展望（仍属基本面） ----------
new_fundmt = (B_fundmt
              .replace("  <!-- 3.4 基本面 -->", "  <!-- 机构展望 -->")
              .replace('<span class="badge">基本面</span>估值分位与机构展望',
                       '<span class="badge">机构展望</span>估值分位与机构观点'))

# ---------- 5) 二、资金面 ----------
new_fund = (B_fund
            .replace("  <!-- 3.2 资金面 -->", "  <!-- 二、资金面 -->")
            .replace('<div class="sub-title"><span class="badge">资金面</span>ETF 基金份额变化'
                     '<span class="hint">份额增加＝净申购（资金流入）</span></div>',
                     '<div class="sec-title">二、资金面：ETF 基金份额变化 '
                     '<span class="en">Fund Flows</span>'
                     '<span class="hint">份额增加＝净申购（资金流入）</span></div>'))

# ---------- 6) 三、情绪面 ----------
new_sent = (B_sent
            .replace("  <!-- 3.1 情绪面 -->", "  <!-- 三、情绪面 -->")
            .replace('<div class="sub-title"><span class="badge">情绪面</span>持仓 PCR（认沽 / 认购持仓比）'
                     '<span class="hint">数值越低＝看跌保护需求越弱、情绪越偏乐观</span></div>',
                     '<div class="sec-title">三、情绪面：持仓 PCR（认沽 / 认购持仓比） '
                     '<span class="en">Sentiment · PCR</span>'
                     '<span class="hint">数值越低＝看跌保护需求越弱、情绪越偏乐观</span></div>'))

# ---------- 7) 四、技术面 ----------
new_tech = (B_tech
            .replace("  <!-- 3.3 技术面 -->", "  <!-- 四、技术面 -->")
            .replace('<div class="sub-title"><span class="badge">技术面</span>K线形态与均线位置'
                     '<span class="hint">近 60 个交易日</span></div>',
                     '<div class="sec-title">四、技术面：K线形态与均线位置 '
                     '<span class="en">Technicals</span>'
                     '<span class="hint">近 60 个交易日</span></div>'))

# ---------- 8) 五、四维信号矩阵（列顺序同步调整） ----------
new_matrix = (B_matrix
              .replace("  <!-- ④ 四维信号矩阵 -->", "  <!-- 五、四维信号矩阵 -->")
              .replace('<div class="sec-title">④ 四维信号矩阵', '<div class="sec-title">五、四维信号矩阵')
              .replace('<th class="l">指数</th><th>情绪面（PCR）</th><th>资金面（份额）</th>'
                       '<th>技术面（K线）</th><th>基本面（估值）</th><th class="l">综合解读</th>',
                       '<th class="l">指数</th><th>基本面（估值）</th><th>资金面（份额）</th>'
                       '<th>情绪面（PCR）</th><th>技术面（K线）</th><th class="l">综合解读</th>'))

# ---------- 9) 总结 ----------
new_concl = """  <!-- 总结 -->
  <div class="sec-title">总结 <span class="en">Takeaways</span></div>
  <div class="card" style="padding:20px 24px;">
    <div class="lead" style="margin-bottom:14px;">
      <p><span class="hl">整体判断：</span>五大宽基呈"<b>大盘价值便宜、中盘偏贵、成长内部分化</b>"。估值看，<b>上证50 / 沪深300</b> 处历史中枢且 PB 分位偏低、股息率最高；<b>中证500</b> 已抬至偏高区间；<b>创业板指</b> PE 分位回落至 22%，<b>科创50</b> 仍在 70%+ 高分位。</p>
      <p><span class="hl">资金与情绪：</span>ETF 份额<b>近 60 个交易日普遍回流</b>，科创50ETF +95.7%、创业板ETF +86.1% 领先；期权 <b>持仓 PCR 全线走低</b>，中证500、创业板指处<b>近四年历史极低位（分位 0.6% / 1.7%）</b>，看跌保护需求极弱。</p>
      <p class="note" style="margin-top:2px;">涨幅按 A 股惯例<b>红涨绿跌</b>；各维信号标签按"绿＝有利 / 红＝不利"的估值温度惯例着色（详见各表图例）。</p>
    </div>
    <p style="margin:0 0 9px;"><b>① 基本面（估值）：</b>PE 分位由低到高为 <span id="rank"></span>。上证50 / 沪深300 估值处历史中枢、PB 分位偏低、股息率最高（3.17% / 2.70%）；中证500 的 PE、PB 分位均约 70%，已不便宜；创业板指 PE 分位回落至 22%、隐含 ROE 最高（14.1%）；科创50 为唯一 PE、PB、股息率三口径同时偏贵的指数。</p>
    <p style="margin:0 0 9px;"><b>② 资金面：</b>近 60 个交易日五只 ETF <b>份额全部回升</b>，科创50ETF（+95.7%）、创业板ETF（+86.1%）弹性最大，与市场"科创 / 创业板 ETF 获大额净流入"的描述相互印证；但拉长到年内，除科创50ETF（+19.1%）外其余四只份额<b>均为大幅净赎回</b>（上证50ETF −87.1%、沪深300ETF −72.0%），显示年内资金整体撤离宽基、近两个月才转为回补。</p>
    <p style="margin:0 0 9px;"><b>③ 情绪面：</b>五大指数期权持仓 PCR <b>全部低于样本中位数</b>，其中中证500（0.6% 分位）、创业板指（1.7% 分位）处于近四年<b>历史极低位</b>——认沽持仓相对认购大幅萎缩，说明市场对下行保护的需求已显著退潮，属情绪层面的<b>一致性偏乐观</b>信号（需注意其反向指标属性：极端低位往往出现在快速反弹之后，而非恐慌底部）。</p>
    <p style="margin:0 0 9px;"><b>④ 技术面：</b>五指数均跌破 20/60/250 日均线并呈空头排列，距 250 日高点回撤 12%–37%，创业板指、科创50 回撤最深（−34.4% / −37.5%），与三季度成长板块创纪录的单季跌幅一致。</p>
    <p style="margin:0;"><b>⑤ 四维组合的含义：</b>估值便宜（上证50 / 沪深300）+ 情绪偏乐观 + 份额回补，但技术面仍在破位——属"<b>估值与资金先行、技术待确认</b>"的组合；创业板指估值分位最低但 PCR 处历史极低位、份额年内仍净赎回，弹性最大同时波动也最大；科创50 是唯一"估值偏贵 + 情绪不低 + 份额大增"的组合，需以三季报盈利兑现为关键验证。</p>
  </div>
"""

# ---------- 10) 附录：标的对照 ----------
new_inst = (B_inst
            .replace("  <!-- ① 标的对照 -->", "  <!-- 附录：标的对照 -->")
            .replace('<div class="sec-title">① 标的对照：主要 ETF 与场内期权 <span class="en">Instruments</span></div>',
                     '<div class="sec-title">附录：标的对照（主要 ETF 与场内期权） '
                     '<span class="en">Appendix · Instruments</span></div>'))

# ---------- 组装 ----------
new = (head + new_sum + new_val + new_cross + new_fundmt
       + new_fund + new_sent + new_tech + new_matrix + new_concl + new_inst + tail)

# ---------- JS / CSS 微调 ----------
# KPI 改为 PE 分位（与基本面打头一致）
new = new.replace(
    "    el.innerHTML='<div class=\"kl\">'+r.name+' · PCR分位</div>'+\n"
    "      '<div class=\"kv\">'+fmt(r.pcr.oi_pct,1)+'%<small style=\"color:'+DIMC[r.pcr.sigc]+'\">'+r.pcr.sig+'</small></div>';",
    "    el.innerHTML='<div class=\"kl\">'+r.name+' · PE分位</div>'+\n"
    "      '<div class=\"kv\">'+fmt(r.pe_pct,1)+'%<small style=\"color:'+DIMC[r.stc]+'\">'+r.st+'</small></div>';")

# 矩阵行：列顺序 基本面/资金面/情绪面/技术面
new = new.replace(
    "      cell(r.pcr.sig,r.pcr.sigc)+cell(r.fund.sig,r.fund.sigc)+cell(r.tsig.sig,r.tsig.sigc)+cell(r.st,r.stc)+",
    "      cell(r.st,r.stc)+cell(r.fund.sig,r.fund.sigc)+cell(r.pcr.sig,r.pcr.sigc)+cell(r.tsig.sig,r.tsig.sigc)+")

# 矩阵图例说明同步顺序
new = new.replace(
    "'<span style=\"margin-left:8px;\">（情绪面：按 PCR 历史分位映射色阶，低位＝看跌保护需求弱、一致性偏乐观，属反向观察；资金面：份额增加记有利；技术面／基本面：位置越高／分位越低记有利）</span>';",
    "'<span style=\"margin-left:8px;\">（基本面：估值分位越低记有利；资金面：份额增加记有利；情绪面：按 PCR 历史分位映射色阶，低位＝看跌保护需求弱、一致性偏乐观，属反向观察；技术面：位置越高记有利）</span>';")

# sec-title 内的 hint 样式
new = new.replace(
    "  .sec-title .en{font-size:11px;color:var(--faint);font-weight:500;letter-spacing:1px;text-transform:uppercase;}",
    "  .sec-title .en{font-size:11px;color:var(--faint);font-weight:500;letter-spacing:1px;text-transform:uppercase;}\n"
    "  .sec-title .hint{font-size:11.5px;color:var(--faint);font-weight:500;letter-spacing:0;text-transform:none;}")

open(p, "w", encoding="utf-8").write(new)
print("reordered OK; length:", len(s), "->", len(new))
