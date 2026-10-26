# -*- coding: utf-8 -*-
"""组装全部数据 -> DATA -> 注入 template2.html"""
import json, sys, os

BASE = "D:/QClaw/Stock/index_valuation/"
sys.path.insert(0, BASE)
import cfg
MAN = cfg.load_manual()

raw = json.load(open(BASE + "data/raw.json", encoding="utf-8"))
met = json.load(open(BASE + "work/metrics.json", encoding="utf-8"))
tech = json.load(open(BASE + "work/tech.json", encoding="utf-8"))
pcr = json.load(open(BASE + "work/pcr.json", encoding="utf-8"))
shares = json.load(open(BASE + "work/shares.json", encoding="utf-8"))
opts = json.load(open(BASE + "work/opts.json", encoding="utf-8"))
etfraw = json.load(open(BASE + "data/etf_raw.json", encoding="utf-8"))

ORDER = ["上证50", "沪深300", "中证500", "创业板指", "科创50"]
CODE = {"上证50": "000016.SH", "沪深300": "000300.SH", "中证500": "000905.SH",
        "创业板指": "399006.SZ", "科创50": "000688.SH"}

# 10Y 国债：以管线自动写入的日频序列为唯一来源。
# 早期用过 manual_inputs.bond10y 覆盖 ERP 末点，结果是「末点用旧值、前一点用新值」，
# 曲线末端出现断点（2026-10-21 发现：序列 10-20=1.6354，人工值仍是 1.6497/10-19）。
# 现在只在序列缺当日数据时，才退回人工值/最近一日。
try:
    _Y10 = json.load(open(BASE + "data/yield10y_history.json", encoding="utf-8"))
except Exception:
    _Y10 = {}
_ASOF_ISO = cfg.fmt(cfg.ASOF)
BOND10Y = float(MAN.get("bond10y", 0) or 0)
BONDDATE = MAN.get("bond10y_date") or ""
_hist = sorted(k for k in _Y10 if k <= _ASOF_ISO)
if _hist:
    _k = _ASOF_ISO if _ASOF_ISO in _Y10 else _hist[-1]
    BOND10Y, BONDDATE = float(_Y10[_k]), _k
ETFMAIN = {"上证50": "510050.SH", "沪深300": "510300.SH", "中证500": "510500.SH",
           "创业板指": "159915.SZ", "科创50": "588000.SH"}
OPTMAIN = {"上证50": "OP510050.SH", "沪深300": "OP510300.SH", "中证500": "OP510500.SH",
           "创业板指": "OP159915.SZ", "科创50": "OP588000.SH"}


def status(p):
    if p is None:
        return ("—", "na")
    if p < 20:
        return ("低估", "s1")
    if p < 40:
        return ("偏低估", "s2")
    if p < 60:
        return ("适中", "s3")
    if p < 80:
        return ("偏高", "s4")
    return ("高估", "s5")


# close 历史：fetch_close_hist.py 维护（2015 起 Tushare 一次性回填 + 东财增量），
# 供 PE/PB Band 换算当期 EPS(TTM)=close/PE、BPS=close/PB 并画价格通道
CLOSE_HIST = json.load(open(BASE + "data/close_history.json", encoding="utf-8"))


def band_data():
    """周采样（每 ISO 周取最后一个交易日）的 close/PE/PB 序列。

    只保留 close、pe、pb 三者都有效的日子；10 年窗口约 521 点/指数，
    控制报告体积。科创50 的估值自 2020-07 起，序列自然从此开始。
    """
    import datetime
    out = {}
    for name in ORDER:
        code = CODE[name]
        cl = CLOSE_HIST.get(code) or {}
        pts = {}
        for x in sorted(raw[code]["basic"], key=lambda x: x["trade_date"]):
            _d = x["trade_date"]
            iso = "%s-%s-%s" % (_d[:4], _d[4:6], _d[6:])
            pe, pb = x.get("pe_ttm"), x.get("pb")
            c = cl.get(iso)
            if not c or not pe or pe <= 0 or not pb or pb <= 0:
                continue
            _y, _w, _ = datetime.date.fromisoformat(iso).isocalendar()
            pts["%04d-W%02d" % (_y, _w)] = (iso, c, pe, pb)
        seq = [pts[k] for k in sorted(pts)]
        out[name] = {
            "dates": [s[0] for s in seq],
            "close": [round(s[1], 2) for s in seq],
            "pe": [round(s[2], 3) for s in seq],
            "pb": [round(s[3], 3) for s in seq],
        }
    return out


def signal_fund(r):
    """资金面信号：以近60日份额变化率为主"""
    v = r["d60p"]
    if v is None:
        return ("—", "na")
    if v >= 20:
        return ("大幅回流", "s1")
    if v >= 5:
        return ("净申购", "s2")
    if v > -5:
        return ("小幅净赎回", "s3")
    if v > -20:
        return ("净赎回", "s4")
    return ("大幅净赎回", "s5")


def signal_pcr(p):
    if p is None:
        return ("—", "na")
    if p < 10:
        return ("历史极低位", "s1")
    if p < 25:
        return ("历史低位", "s2")
    if p < 50:
        return ("中低位", "s3")
    if p < 75:
        return ("中高位", "s4")
    return ("历史高位", "s5")


def signal_tech(t):
    """技术面信号：按相对 MA20 的位置分层"""
    a20, r20 = t["above_ma20"], t["ret20"]
    if a20 is None or r20 is None:
        return ("—", "na")
    if a20 >= 0 and r20 > 0:
        return ("修复走强", "s1")
    if a20 >= -3:
        return ("相对抗跌", "s2")
    if a20 >= -6:
        return ("弱势整理", "s3")
    if a20 >= -10:
        return ("破位下行", "s4")
    return ("深度超跌", "s5")


rows = []
for name in ORDER:
    code = CODE[name]
    m = met[code]
    t = tech[code]
    f = shares[name]
    p = pcr[name]
    etfcode = ETFMAIN[name]
    o = opts[OPTMAIN[name]]
    ep = 100.0 / m["pe_ttm"]
    rp = ep - BOND10Y
    st, stc = status(m["pe_ttm_pct_10y"])
    fst, fstc = signal_fund(f)
    pst, pstc = signal_pcr(p["oi_pcr_pct"])
    tst, tstc = signal_tech(t)
    scale = round(f["share"] * f["price"], 1) if f["price"] else None   # 亿份 × 元/份 = 亿元
    rows.append({
        "name": name, "code": code, "date": m["date"],
        "close": m["close"], "pe_ttm": m["pe_ttm"], "pe": m["pe"], "pb": m["pb"],
        "pe_pct": m["pe_ttm_pct_10y"], "pb_pct": m["pb_pct_10y"],
        "close_pct": m.get("close_pct_10y"),
        "close_med": m.get("close_med_10y"), "close_med5": m.get("close_med_5y"),
        "hist_from": m["hist_start"][:4],
        "mv": m["total_mv"] / 1e12, "roe": m["implied_roe"],
        "ytd": m["ytd"], "m1": m["ret1m"], "y1": m["ret1y"],
        "ep": ep, "rp": rp, "pe_med": m["pe_ttm_med"], "pe_min": m["pe_ttm_min"], "pe_max": m["pe_ttm_max"],
        "pb_med": m["pb_med"], "st": st, "stc": stc,
        "etf": {"code": etfcode, "name": f["fname"], "mgr": o["etf_mgr"],
                "price": f["price"], "share": f["share"], "scale": scale},
        "pcr": {"oi": p["oi_pcr"], "oi_pct": p["oi_pcr_pct"], "oi_med": p["oi_pcr_med"],
                "oi_min": p["oi_pcr_min"], "oi_max": p["oi_pcr_max"], "oi_ma20": p["oi_pcr_ma20"],
                "p25": p["oi_pcr_p25"], "vol": p["vol_pcr"], "vol_pct": p["vol_pcr_pct"],
                "n": p["n"], "start": p["start"], "sig": pst, "sigc": pstc,
                "series": p["series"]},
        "fund": {"d5": f["d5"], "d5p": f["d5p"], "d20": f["d20"], "d20p": f["d20p"],
                 "d60": f["d60"], "d60p": f["d60p"], "ytd": f["ytd"], "ytdp": f["ytdp"],
                 "hi": f["hi"], "lo": f["lo"], "sig": fst, "sigc": fstc},
        "tech": t,
        "tsig": {"sig": tst, "sigc": tstc},
    })

# ---------- PCR / 份额走势全历史序列（v2.6.2：窗口 全部/近三年/近一年，默认近一年） ----------
# 每 2 个交易日抽 1 点、锚定最新日（近一年窗口仍有约 125 点，比旧版 63 点更密）；
# 窗口切片由前端按点数完成（近一年=125 点、近三年=375 点、全部=全部）。
# 对齐基准 = 沪深300 标的日期，缺日为 null（科创50 期权自 2023-06 起，前端 connectNulls）。
# 日期以 6 位整数存（YYMMDD，如 261021），控制报告体积。
def _tail2(seq):
    """每 2 个交易日抽 1 点，锚定最新日。"""
    return list(seq[::-1][::2])[::-1]


import pandas as pd
pcrdf = pd.read_csv(BASE + "data/pcr_raw.csv")
OC2N = {"OP510050.SH": "上证50", "OP510300.SH": "沪深300", "OP510500.SH": "中证500",
        "OP159915.SZ": "创业板指", "OP588000.SH": "科创50"}

pcr_days = _tail2(sorted(pcrdf[pcrdf["oc"] == "OP510300.SH"]["date"].astype(str).tolist()))
pcr_maps = {nm: dict(zip(pcrdf[pcrdf["oc"] == oc]["date"].astype(str),
                         pcrdf[pcrdf["oc"] == oc]["oi_pcr"]))
            for oc, nm in OC2N.items()}
pcrAll = {
    "dates": [int(d[2:]) for d in pcr_days],
    "series": {nm: [round(float(m[d]), 3) if d in m and m[d] == m[d] else None
                    for d in pcr_days]
               for nm, m in pcr_maps.items()},
}

share_days = _tail2(sorted(r["trade_date"] for r in etfraw["shares"]["510300.SH"]))
shareAll = {"dates": [int(d[2:]) for d in share_days], "series": {}}
for nm in ORDER:
    mp = {r["trade_date"]: r["fd_share"] / 10000.0 for r in etfraw["shares"][ETFMAIN[nm]]}
    shareAll["series"][nm] = [round(mp[d], 1) if d in mp else None for d in share_days]


# ---------- 动态生成「总结」（随数据变化，避免硬编码过期） ----------
def _p1(v):
    return "—" if v is None else ("%+.1f%%" % v)


def _lb(r):
    return "%sETF(%s)" % (r["name"], r["etf"]["code"])


_by = lambda key: sorted(rows, key=lambda r: (key(r) if key(r) is not None else 9e9))
_byrev = lambda key: sorted(rows, key=lambda r: (key(r) if key(r) is not None else -9e9), reverse=True)

by_pe = _by(lambda r: r["pe_pct"])
by_pb = _by(lambda r: r["pb_pct"])
by_roe = _byrev(lambda r: r["roe"])
by_d60 = _byrev(lambda r: r["fund"]["d60p"])
by_ytd = _byrev(lambda r: r["fund"]["ytdp"])
by_pcr = _by(lambda r: r["pcr"]["oi_pct"])
by_dd = _by(lambda r: r["tech"]["dd_from_250high"])

rank = " &lt; ".join("<b>%s</b>（%.1f%%）" % (r["name"], r["pe_pct"]) for r in by_pe if r["pe_pct"] is not None)
cheap = "、".join(r["name"] for r in by_pe[:2])
rich = "、".join(r["name"] for r in by_pe[-2:])
d60_txt = "、".join("%s（%s）" % (_lb(r), _p1(r["fund"]["d60p"])) for r in by_d60[:2])
ytd_txt = "、".join("%s（%s）" % (_lb(r), _p1(r["fund"]["ytdp"])) for r in by_ytd)
pcr_txt = "、".join("%s（%.1f%% 分位）" % (r["name"], r["pcr"]["oi_pct"])
                    for r in by_pcr if r["pcr"]["oi_pct"] is not None)
dd_txt = "、".join("%s（%s）" % (r["name"], _p1(r["tech"]["dd_from_250high"])) for r in by_dd)
up_cnt = sum(1 for r in rows if (r["fund"]["d60p"] or 0) > 0)
pos_ytd = [r for r in rows if (r["fund"]["ytdp"] or 0) > 0]
neg_ytd = [r for r in rows if (r["fund"]["ytdp"] or 0) <= 0]
ytd_desc = ("仅 %s 年初至今为正（%s），其余均净赎回（%s 赎回最多，%s）"
            % (_lb(pos_ytd[0]), _p1(pos_ytd[0]["fund"]["ytdp"]),
               _lb(neg_ytd[-1]), _p1(neg_ytd[-1]["fund"]["ytdp"]))) if pos_ytd and neg_ytd \
    else "年初至今份额整体净赎回"

summary_html = (
    '<div class="lead" style="margin-bottom:14px;">'
    '<p><span class="hl">整体判断：</span>五大宽基估值分化明显——PE 分位由低到高为 %s。'
    'PB 分位最低的是 <b>%s</b>（%.1f%%），'
    '隐含 ROE 最高的是 <b>%s</b>（%.1f%%）。</p>'
    '<p><span class="hl">资金与情绪：</span>近 60 个交易日 %d/5 只 ETF 份额回升，%s 领先；'
    '期权持仓 PCR 整体处样本区间偏低位置，分位最低为 <b>%s</b>（%.1f%%）。</p>'
    '<p class="note" style="margin-top:2px;">涨幅按 A 股惯例<b>红涨绿跌</b>；'
    '各维信号标签按"绿＝有利 / 红＝不利"的估值温度惯例着色（详见各表图例）。</p></div>'
    '<p style="margin:0 0 9px;"><b>① 基本面（估值）：</b>PE 分位由低到高为 %s。'
    'PB 分位最低 <b>%s</b>（%.1f%%）；'
    '隐含 ROE 最高 <b>%s</b>（%.1f%%）；估值分位最高的是 <b>%s</b>（%.1f%%），压力最大。</p>'
    '<p style="margin:0 0 9px;"><b>② 资金面：</b>近 60 个交易日份额变化：%s；'
    '年初至今：%s。</p>'
    '<p style="margin:0 0 9px;"><b>③ 情绪面：</b>持仓 PCR 及历史分位：%s。'
    '其中 <b>%s</b> 与 <b>%s</b> 处样本区间最低位，认沽持仓相对认购显著萎缩，'
    '属情绪层面的<b>一致性偏乐观</b>（反向指标：极端低位常出现在快速反弹之后，而非恐慌底部）。</p>'
    '<p style="margin:0 0 9px;"><b>④ 技术面：</b>距 250 日高点回撤：%s；'
    '回撤最深为 <b>%s</b>（%s）。五指数当前均位于 20/60/250 日均线下方。</p>'
    '<p style="margin:0;"><b>⑤ 组合含义：</b>估值分位偏低一档（%s）属"估值便宜"；'
    '分位偏高一档（%s）已不便宜。结合资金回补而技术仍在均线下方，'
    '整体呈"<b>估值与资金先行、技术待确认</b>"的组合，需以三季报盈利兑现为关键验证。</p>'
) % (
    rank,
    by_pb[0]["name"], by_pb[0]["pb_pct"],
    by_roe[0]["name"], by_roe[0]["roe"],
    up_cnt, d60_txt,
    by_pcr[0]["name"], by_pcr[0]["pcr"]["oi_pct"],
    rank,
    by_pb[0]["name"], by_pb[0]["pb_pct"],
    by_roe[0]["name"], by_roe[0]["roe"], by_pe[-1]["name"], by_pe[-1]["pe_pct"],
    d60_txt, ytd_txt,
    pcr_txt, by_pcr[0]["name"], by_pcr[1]["name"],
    dd_txt, by_dd[0]["name"], _p1(by_dd[0]["tech"]["dd_from_250high"]),
    cheap, rich,
)

_pmin = pcrdf["date"].astype(str).min()
_smin = pcrdf[pcrdf["oc"] == "OP588000.SH"]["date"].astype(str).min()

# ---------- ERP 历史序列 ----------
# v2.6.1 起图与读数条全部由 erp_weekly()（周采样，五指数）驱动、统计在前端算，
# 原「沪深300 日频 DATA.erp」统计块已删除（前端不再消费）。

def erp_weekly():
    """五指数 ERP 周采样序列（v2.6.0 交互式 ERP 图，v2.6.1 起读数条也用它）。

    ERP = 100/PE(TTM) − 10Y，日频点按 ISO 周取最后一个交易日；
    10Y 缺失或 PE 无效的日子跳过。科创50 自 2020-07 起。
    """
    import datetime
    out = {}
    for name in ORDER:
        code = CODE[name]
        pts = {}
        for x in sorted(raw[code]["basic"], key=lambda x: x["trade_date"]):
            _d = x["trade_date"]
            iso = "%s-%s-%s" % (_d[:4], _d[4:6], _d[6:])
            if iso < "2015-01-05":
                continue
            _y = _Y10.get(iso)
            _pe = x.get("pe_ttm")
            if _y is None or not _pe or _pe <= 0:
                continue
            _yy, _w, _ = datetime.date.fromisoformat(iso).isocalendar()
            pts["%04d-W%02d" % (_yy, _w)] = (iso, 100.0 / _pe - _y)
        seq = [pts[k] for k in sorted(pts)]
        # 末点保底：若周采样最后一天早于 asof（如 y10 缺当日），用 met 当日值补上
        if seq and seq[-1][0] < _ASOF_ISO:
            seq.append((_ASOF_ISO, 100.0 / met[code]["pe_ttm"] - BOND10Y))
        out[name] = {
            "dates": [s[0] for s in seq],
            "erp": [round(s[1], 4) for s in seq],
        }
    return out


def _views():
    """机构观点：按机构组织的一行一条（org / date / scope / view）。

    兼容旧格式 {指数: [观点, "机构（日期）"]}，只在文件被写回旧结构时兜底，
    正常路径下 manual_inputs.json 的 views 就是 list。
    """
    v = MAN.get("views", [])
    if isinstance(v, dict):
        out = []
        for scope, val in v.items():
            seq = list(val) if isinstance(val, (list, tuple)) else [str(val)]
            txt = seq[0] if seq else ""
            src = seq[1] if len(seq) > 1 else ""
            out.append({"org": src or "—", "date": "", "scope": scope, "view": txt})
        return out
    return [e for e in v if isinstance(e, dict) and (e.get("org") or e.get("view"))]


DATA = {
    "asof": cfg.ASOF_FMT,
    "pcrAsof": cfg.ASOF_FMT,
    "bond10y": BOND10Y, "bondDate": BONDDATE, "rows": rows,
    "band": band_data(),
    "pcrAll": pcrAll, "shareAll": shareAll,
    "pcrStart": cfg.fmt(_pmin), "sciPcrStart": cfg.fmt(_smin),
    "views": _views(), "syn": MAN.get("syn", {}),
    "summary": summary_html,
    "erpS": erp_weekly(),
}
json.dump(DATA, open(BASE + "work/data2.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)

OUT = cfg.report_path(cfg.ASOF, cfg.REPORT_TAG)   # 试运行时带 IV_REPORT_TAG 标记
html = open(os.path.dirname(os.path.abspath(__file__)) + "/template2.html", encoding="utf-8").read()
html = html.replace("/*__DATA__*/", "const DATA = " + json.dumps(DATA, ensure_ascii=False) + ";")
open(OUT, "w", encoding="utf-8").write(html)
print("generated OK ->", os.path.basename(OUT))
for r in rows:
    print(f"{r['name']:<6} ETF={r['etf']['code']} {r['etf']['share']}亿份 {r['etf']['scale']}亿元 | "
          f"PCR={r['pcr']['oi']}({r['pcr']['oi_pct']}%) {r['pcr']['sig']} | "
          f"资金60日{r['fund']['d60p']}% {r['fund']['sig']} | 技术 {r['tsig']['sig']}")
