# -*- coding: utf-8 -*-
"""ivdata.config —— 全局配置与数据域（domain）定义。

数据域 = 一类同构数据。每个域配一条 **provider 优先级链**。
链路按顺序尝试，第一个成功且通过质量校验的 provider 生效。

调参建议
--------
* 想强制走某个源：把该源名字放到链路第一位，或设环境变量 IV_FORCE=<domain>=<provider>。
* 深市 ETF 份额：日常走「1105 当前规模快照」，漏跑的日子由「基金规模区间报表
  （scsj_fund_jjgm）」自动回补。
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field

# ---------------------------------------------------------------- 路径

from .paths import DATA, WORK, REPORTS  # noqa: E402  （唯一路径定义处）

CACHE = os.path.join(DATA, "cache")          # provider 级原始缓存
for _d in (DATA, WORK, REPORTS, CACHE):
    os.makedirs(_d, exist_ok=True)


# ---------------------------------------------------------------- 运行设置

@dataclass
class Settings:
    """运行期设置，全部可用环境变量覆盖。"""

    # 参考交易日 YYYYMMDD；为空则由日历自动推导
    asof: str = os.environ.get("ASOF", "").strip()

    # 网络
    timeout: float = float(os.environ.get("IV_TIMEOUT", "20"))
    retries: int = int(os.environ.get("IV_RETRIES", "3"))
    backoff: float = float(os.environ.get("IV_BACKOFF", "1.5"))
    qps: float = float(os.environ.get("IV_QPS", "5"))   # 每源每秒请求数上限
    # 逐合约期权明细的数据量很大，默认不做（PCR 改用官方汇总）
    # 需要时设 IV_OPT_CONTRACT_DETAIL=1
    opt_contract_detail: bool = os.environ.get("IV_OPT_CONTRACT_DETAIL", "0") in ("1", "true", "yes")

    # 尾部回看窗口（自然日）。默认 1 天 = 只重取库内最后一天（修正盘中值），
    # 其余全部是新日期；各域可用 OVERLAP_BY_DOMAIN 单独设定。
    overlap_days: int = int(os.environ.get("IV_OVERLAP", "1"))

    # 强制指定某数据域走某个 provider：IV_FORCE="valuation=csi"
    force: dict = field(default_factory=dict)

    def __post_init__(self):
        raw = os.environ.get("IV_FORCE", "").strip()
        if raw:
            for part in raw.split(","):
                if "=" in part:
                    k, v = part.split("=", 1)
                    self.force[k.strip()] = v.strip()

    def forced(self, domain: str) -> str:
        return self.force.get(domain, "")

    def resolve_asof(self, calendar=None) -> str:
        """确定参考交易日。

        优先级：环境变量 ASOF > 传入日历的最后一个交易日 > 今天之前的工作日。
        空值时会被多处引用，因此工具启动时应先调用一次。
        """
        if self.asof:
            return self.asof
        if calendar:
            try:
                days = [r["cal_date"] for r in calendar if r.get("is_open")]
                if days:
                    self.asof = max(days)
                    return self.asof
            except Exception:  # noqa: BLE001
                pass
        import datetime as _dt
        d = _dt.date.today()
        if _dt.datetime.now().hour < 16:      # 当日收盘数据未发布前用上一工作日
            d -= _dt.timedelta(days=1)
        while d.weekday() >= 5:
            d -= _dt.timedelta(days=1)
        self.asof = d.strftime("%Y%m%d")
        return self.asof


SETTINGS = Settings()

# 各数据域的「尾部回看天数」（自然日）。
# 语义：从库内最后一天往前退 N 天开始取 —— 只重取最后 N 天，用于修正当日
# 盘中值 / 未定稿值；**历史一律不重拉**（2015 起的存量直接复用）。
# 0 = 严格增量，只取库内最后一天之后的日期（无修正能力的源才用）。
OVERLAP_BY_DOMAIN = {
    "quote": 1,
    "valuation": 1,
    "etf_share": 1,
    "etf_quote": 1,
    "bond10y": 1,
    "option_pcr": 1,
}
# 显式设 IV_OVERLAP=N 时全局统一为 N（排障用，日常不要动）
OVERLAP_FORCED = os.environ.get("IV_OVERLAP")

# 按 host 覆盖的 QPS。深交所对突发请求很敏感：几秒内连续十几发就会被 WAF
# 直接掐断连接（表现为 RemoteDisconnected，连首页都打不开，几分钟后自愈）。
# 全局限速 5 QPS 对它太快，单独降到 1 QPS。
HOST_QPS = {
    "www.szse.cn": float(os.environ.get("IV_QPS_SZSE", "1")),
}

# ---------------------------------------------------------------- 标的定义

# 报告跟踪的五大宽基。code 带交易所后缀，与库内历史数据对齐。
INDEXES = [
    #  order, code,        name,      sina_symbol, em_secid,  csi_code
    (1, "000300.SH", "沪深300", "sh000300", "1.000300", "000300"),
    (2, "000016.SH", "上证50", "sh000016", "1.000016", "000016"),
    (3, "000905.SH", "中证500", "sh000905", "1.000905", "000905"),
    (4, "399006.SZ", "创业板指", "sz399006", "0.399006", None),      # 深证系列，中证官网无
    (5, "000688.SH", "科创50", "sh000688", "1.000688", "000688"),
]
INDEX_CODES = [x[1] for x in INDEXES]
CODE2NAME = {x[1]: x[2] for x in INDEXES}
CODE2SINA = {x[1]: x[3] for x in INDEXES}
CODE2EM = {x[1]: x[4] for x in INDEXES}
CODE2CSI = {x[1]: x[5] for x in INDEXES}

# 期权标的主映射（与旧版保持一致，报告里的行序依赖它）
OPT_MAIN = {
    "OP510050.SH": "上证50",
    "OP510300.SH": "沪深300",
    "OP510500.SH": "中证500",
    "OP159915.SZ": "创业板指",
    "OP588000.SH": "科创50",
}
# 期权标的 → 交易所、对应 ETF
OPT_EXCH = {
    "OP510050.SH": "SH", "OP510300.SH": "SH", "OP510500.SH": "SH",
    "OP588000.SH": "SH", "OP588080.SH": "SH",
    "OP159915.SZ": "SZ", "OP159919.SZ": "SZ", "OP159922.SZ": "SZ",
}
OPT_ETF = {
    "OP510050.SH": "510050", "OP510300.SH": "510300", "OP510500.SH": "510500",
    "OP588000.SH": "588000", "OP588080.SH": "588080",
    "OP159915.SZ": "159915", "OP159919.SZ": "159919", "OP159922.SZ": "159922",
}

# ETF：报告主表用的 5 只 + 份额曲线需要的深市 ETF
ETF_LIST = ["510300.SH", "510050.SH", "510500.SH", "159915.SZ", "588000.SH"]
ETF_ALL = ETF_LIST + ["159919.SZ", "159922.SZ", "588080.SH"]

# ---------------------------------------------------------------- 数据域与优先级链

# 每个域的值是 provider 名列表，按优先级排列。
# 名字需在 ivdata/providers/__init__.py 的 PROVIDERS 中注册。
DOMAINS = {
    # 指数日行情（OHLCV）：新浪 → 东财
    # ⚠ 中证官网的 index-perf-oneday 只给当日单点，无历史，不放进链里（见 csi.py 说明）
    "quote": ["sina_quote", "em_quote"],

    # 指数估值（PE_TTM / PB）：东财成分股加权（唯一主源）
    # ⚠ csi_valuation 只有静态 PE（字段还叫 peg），无 PB、无创业板指，
    #   口径与报告的 PE_TTM 不一致（科创50 差近一倍），**不可作为主源**。
    "valuation": ["em_valuation"],

    # 期权 PCR（标的级汇总）：上交所/深交所官方日统计
    "option_pcr": ["exchange_pcr"],

    # ETF 份额：沪市走上交所官方（全历史）；深市日常走深交所「当前规模」单日快照，
    # 缺口由深交所「基金规模区间报表」（一次可查 6 个月）自动回补。
    "etf_share": ["exchange_etf_share", "szse_etf_share", "szse_etf_share_range"],

    # ETF 日行情：新浪
    "etf_quote": ["sina_quote"],

    # 10 年期国债收益率：东财增量（唯一写入者）
    "bond10y": ["em_bond10y"],

    # 交易日历：上交所日历 → 本地推导
    "calendar": ["sse_calendar", "local_calendar"],
}

# 每个域的“健康”判据：返回行数下限、必需字段
DOMAIN_SCHEMA = {
    "quote": {"min_rows": 1, "fields": ["trade_date", "close"]},
    "valuation": {"min_rows": 1, "fields": ["trade_date", "pe_ttm", "pb"]},
    "option_pcr": {"min_rows": 1, "fields": ["date", "oc", "oi_pcr"]},
    "etf_share": {"min_rows": 1, "fields": ["trade_date", "fd_share"]},
    "etf_quote": {"min_rows": 1, "fields": ["trade_date", "close"]},
    "bond10y": {"min_rows": 1, "fields": []},
    "calendar": {"min_rows": 1, "fields": []},
}
