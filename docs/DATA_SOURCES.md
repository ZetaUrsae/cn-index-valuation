# 数据源说明（DATA SOURCES）

本文件记录每个数据域**用哪些源、为什么这么排、精度如何验证**。
新管线（v2）的原则：**日常完全不用 Tushare**，能用公开源的一律用公开源。
Tushare 只在人工指令（`sync_tushare.py`，或显式设 `IV_ALLOW_TUSHARE=1`）时才参与，
其余情况下连兜底都不会触发；它已写定的 2015 起历史永久留存、不再重拉。

---

## 一、总览

| 数据域 | 优先级链 | 日常实际使用 | 历史起点 | Tushare 是否参与 |
|--------|----------|--------------|----------|------------------|
| `quote` 指数日行情 | `sina_quote` → `em_quote` → `tushare_quote` | 新浪 | 2019-12（本地）/ 2010+（源） | 否 |
| `valuation` 指数估值 | `em_valuation` → `tushare_valuation` | 东财成分股聚合 | **2018-01-02** | 否 |
| `option_pcr` 期权 PCR | `exchange_pcr` → `tushare_pcr` | 上交所/深交所官方 | 2022-10-10（科创50 2023-06-05） | 否 |
| `etf_share` ETF 份额 | `exchange_etf_share`(沪) / `szse_etf_share`(深快照) → `szse_etf_share_range`(深区间) → `tushare_etf_share` | 上交所官方 + 深交所快照/区间 | 2023-01（本地） | 否 |
| `etf_quote` ETF 行情 | `sina_quote` → `tushare_etf_quote` | 新浪 | — | 否 |
| `bond10y` 10Y 国债 | `em_bond10y`（唯一源；`manual_bond10y` 已于 v2.4.0 删除） | 东财（中债数据） | 2002-01-04 | 否 |
| `close_hist` 指数收盘价（Band 图专用） | `fetch_close_hist.py`：东财 K 线 `push2his`（日常增量）；2015~2019 为 Tushare `index_daily` **一次性回填（2026-10-21，仅此一次）** | 东财 K 线 | 2015-01-05（科创50 自基日） | 已回填段是；此后否 |
| `calendar` 交易日历 | `sse_calendar` → `local_calendar` | 上交所 | — | 否 |

> `csi_valuation` / `csi_quote`（中证指数官网）**不在任何主链里**，
> 仅作为 `tools/verify_sources.py` 的交叉校验参考。原因见第二节第 5 条。

---

## 二、各源详解

### 1. 东方财富 —— 估值（核心）

**接口**：`https://datacenter-web.eastmoney.com/api/data/v1/get`

整个估值链路分两步：

1. **取成分股**：报表 `RPT_INDEX_COMPONENT`
   ```
   reportName=RPT_INDEX_COMPONENT&filter=(INDEX_CODE=000300)&pageSize=500
   ```
   - ⚠ `filter` 里**必须用裸值**（`(INDEX_CODE=000300)`）。加引号会触发 antlr
     `InputMismatchException`，因为该列是数值型。
   - 实测返回真实成分：沪深300 恰好 300 只、科创50 恰好 50 只、创业板指 100 只。
   - 缓存 7 天（`data/em_constituents.json`）。成分调整是半年级别的，7 天足够。

2. **取全市场估值**：报表 `RPT_VALUEANALYSIS_DET`
   ```
   reportName=RPT_VALUEANALYSIS_DET&source=WEB&client=WEB
   &filter=(TRADE_DATE='2026-10-19')&pageSize=6000
   ```
   - ⚠ `source=WEB&client=WEB` **必填**，缺了会被拒。
   - `pageSize=6000` 一次拿回全部 5575 只股票，**单次请求**搞定全市场。
   - 日期过滤要用**单引号**（`TRADE_DATE='2026-10-19'`，连字符格式）。

**聚合口径（关键，误差 0.17%）**

```
PE = Σmv / Σ(mv / PE_i)      PB = Σmv / Σ(mv / PB_i)
权重 = TOTAL_MARKET_CAP（总市值），不是流通市值
亏损股（PE ≤ 0）必须计入，不能剔除
```

这个口径与中证指数公司的计算方式一致。踩过的坑：

| 尝试 | 沪深300 PE 误差 |
|------|-----------------|
| 流通市值加权、剔除亏损 | ≈ 5% |
| 总市值加权、剔除亏损 | ≈ 15% |
| **总市值加权、含亏损** | **0.17%** ✅ |

**字段对照**

| 报告字段 | 东财字段 | 说明 |
|----------|----------|------|
| `pe_ttm` | `PE_TTM` | 动态市盈率 |
| `pb` | `PB_MRQ` | 市净率（最近报告期） |
| `pe`（静态） | `PE_LAR` | 最近年报 PE，聚合后与 Tushare 的 `pe` 逐位吻合（192.2792 vs 192.2791） |
| `total_mv` | `TOTAL_MARKET_CAP` | **单位是元**，但数值与 Tushare `index_dailybasic.total_mv` 完全相等，**不要任何换算** |
| `float_mv` | `NOTLIMITED_MARKETCAP_A` | 自由流通市值 |
| `turnover_rate_f` | 需另算 | 由成交量与自由流通股本推导 |

> 单位坑：曾错误地除以 1e4（以为元→万元），导致 `total_mv` 差 10000 倍
> （6551594005 vs 65515922156051）。**东财的元数值直接就是 Tushare 存的值**，
> 因为 Tushare 文档写的"万元"实际口径如此。

**历史下界**：`2018-01-02`。2017-12-01 及更早返回"返回数据为空"。

**已知偏差**：东财回补历史时用的是**当前成分股**，所以越往前偏离越大：

| 日期 | 沪深300 PE / PB 偏差 |
|------|----------------------|
| 2019-01-02 | +0.11% / −2.27% |
| 2021-01-04 | +6.95% / −0.73% |
| 2023-01-03 | −2.74% / −4.96% |

这正是历史段必须由 Tushare 一次性写定的理由（东财不能用当前成分股回补早年），
写定后冻结、不再重拉；日常增量交给东财。

### 2. 新浪财经 —— 指数/ETF 行情

`https://money.finance.sina.com.cn/quotes_service/api/json_v2.php/CN_MarketData.getKLineData`

- 单次最多 1023 根 K 线，需分页。
- ⚠ `volume` 单位是**股**，Tushare `vol` 是**手**（1 手 = 100 股）→ **除以 100**。
- 无 `amount` 字段，按 `close × vol(手) × 100 / 1000` 估算（千元）。
- 返回体可能是 JSONP，`ivdata.http._loads` 已做 BOM/JSONP 容错。

### 3. 上海证券交易所

**期权日统计**
`http://query.sse.com.cn/commonQuery.do?sqlId=COMMON_SSE_ZQPZ_YSP_QQ_SJTJ_MRTJ_CX&tradeDate=YYYYMMDD`

- 按 `tradeDate` 逐日查；每交易日 5 行（认购/认沽 × 持仓/成交）。
- 需要 `Referer: http://www.sse.com.cn/`。
- 已实现 `pageHelp.pageSize=100` 分页循环，实测只有 5 行，但保留以防改版。
- ⚠ **到期日（周三）差异**：交易所报的是**结算后**持仓量，Tushare 报**收盘**持仓量。
  2026-09-23 实测 `oi_pcr` 差到 0.577×（成交量、成交额完全一致）。
  这是会计口径差异，不是取数 bug，已在 `exchange.py` 记录为
  `KNOWN_OI_DIVERGENCE = ("20260923",)`。

**ETF 份额**

```
GET https://query.sse.com.cn/commonQuery.do
    ?sqlId=COMMON_SSE_ZQPZ_ETFZL_XXPL_ETFGM_SEARCH_L
    &isPagination=true&pageHelp.pageSize=500&pageHelp.pageNo=1
    [&STAT_DATE=2026-10-20]        ← 可选；不传则返回「最新一日」
```

- 一次返回**某一日全市场 ETF 名单**（约 920 只 / 2 页），字段 `SEC_CODE` + `TOT_VOL`（万份，
  与 Tushare `fund_share.fd_share` 同值）；
- **没有区间参数**。`STAT_DATE` 是唯一的时间入口：传某个历史日期可回查当日的份额，
  实测 `STAT_DATE=2026-09-15` 返回 907 行、值与我们库里逐位一致；
- 因此 provider 按 `STAT_DATE=end` 精确定位当日，取不到再退回「最新一日」——
  这样补跑历史日期（`--asof`）也不会拿错日子；
- **按日缓存**：四只沪市 ETF 共用同一份名单，不缓存就要把同一张表拉 4 遍（每遍 2 页）。
- 漏日同样能自愈：`Pipeline._fill_share_gaps` 检测到缺口后按日逐个回查（缺口通常 1~2 天），
  只补缺失日期，当天（未定稿）一律留给明天。

**交易日历**
中证指数官网 `index-perf-tradeDate`，一次返回全序列（很小），provider 内做了进程内缓存，
一次运行只拉 1 次。

### 4. 深圳证券交易所 —— 深市 ETF 份额

`GET https://www.szse.cn/api/report/ShowReport/data`
`?SHOWTYPE=JSON&CATALOGID=1105&TABKEY=tab1&PAGENO=1&txtkey1=159915`

`CATALOGID=1105` 是「基金列表」，约 1075 只基金 / 54 页。页面上的「代码或简称」
筛选框就是 `txtkey1`，实测能把结果缩到 1 行，**一次请求即可**，
不必再像早期实现那样翻 54 页（翻页正是触发限流的主因）。

字段 `dqgm` = 当前规模（万份），与 Tushare `fund_share.fd_share / 1e4` **逐位一致**：
2026-10-20 实测深交所 2,673,645.49 vs Tushare 2,673,645.4936，只差深交所保留 2 位小数。

四个必须记住的性质：

1. **快照只有当日一个值，没有历史区间参数。** 每次只贡献 1 行，靠每日运行往后追；
   漏跑的日子由下面的「区间报表」（`scsj_fund_jjgm`）自动回补，**不需要 Tushare**。
2. **日期归属容易错位一天。** `metadata.subname` 是快照日（形如 `2026-10-20`），
   而列头括号里印的日期却是前一天。实测 `dqgm` 的值属于 `subname` 那天，
   所以取 `min(subname, end)`：早间运行时 subname 可能已翻到下一交易日，
   但值仍是 end 日的确认值，钳到 end 才正确。
3. **晚间值是临时值。** 页面原文：「该字段 T 日晚间更新的 T 日规模仅供参考，
   以 T+1 日早间更新的 T 日规模为准」。定时任务 06:00 跑，天然拿到确认值。
4. **限流是按主机、按「短时间总请求数」的，不是 QPS 限流。** 同一 IP 短时间内
   连发十几请求就会被 WAF 掐断，表现为 `RemoteDisconnected`：TCP 能连、TLS 能握手，
   但 HTTP 请求直接被丢弃，**连首页都打不开**，实测封禁可达 1 小时以上。
   因此要两手抓：`ivdata/config.py` 把 `www.szse.cn` 的 QPS 压到 1（`HOST_QPS`），
   更重要的是**少发请求**——`Pipeline.sync_pcr` 的回溯窗口已收到
   「库里最后一天的前 1 天 ~ asof」：日常只缺 1 天新数据，所以通常只发 1~2 发
   （曾因 40 天窗口每次运行发 26 发，把配额吃光）。
   另外 `Pipeline.sync_etfs` 有「疑似未刷新就换源重取」的判定。

**为什么不拿周度 Tushare 顶替**：份额是日报「资金面」的 5/20/60 日变化基准，
周内不动就会让曲线出现台阶，所以仍然每日从深交所取。

**深市份额的缺口回补（区间报表）**

`CATALOGID=scsj_fund_jjgm`（页面上是「基金规模」查询页，可选时间窗口）：

```
GET https://www.szse.cn/api/report/ShowReport/data
    ?SHOWTYPE=JSON&CATALOGID=scsj_fund_jjgm&jjlb=ETF
    &txtDm=159915&txtStart=2026-04-21&txtEnd=2026-10-21&PAGENO=1
```

- 页面查询条件在接口元数据里写死 `dateRange('all','${txtEnd}','6m')`：**单次最多 6 个月**，
  每页 20 行，字段 `size_date` / `current_size`（万份，含千分位），
  与 Tushare `fund_share.fd_share` 同源同值；
- **标签日错位一个交易日**：`size_date` 标的是「官方份额日的前一个交易日」，即
  `row[label] == 官方[交易日历中 label 的下一个交易日]`。两个独立窗口实测
  155/155 行全部命中（2026 年 4-10 月 118 行、2-4 月 37 行），只有末尾未定稿的
  1~2 行例外。换算必须走交易日历取「下一个交易日」，不能简单 +1 天；
- **末尾 1~2 行未定稿**（T 晚间临时值、T+1 早间为准），provider 直接丢弃
  「官方日 > 今天-1」的行——这几天正好由每日快照覆盖；
- 成本：管线**只在检测到缺口时**才调用，45 天缺口 ≈ 2 页 = 2 个请求，
  正常每天跑一次则一次都不发；缺口超过 120 天（首次建库 / 长期停机）时只补最近
  120 天，更早的走人工 `sync_tushare.py`，避免一次翻几十页把配额打光。

> 管道分工：`SzseEtfShare` 负责当日快照，`SzseEtfShareRange` 负责历史缺口，
> 回补只写缺失日期、已有日期一律以库内为准（标签错位一旦写反会污染整条序列）。

### 5. 中证指数官网（仅交叉校验）

`https://www.csindex.com.cn/csindex-home/perf/indexCsiDsPe`

三个致命问题，导致**不可作为主源**：

1. 返回字段名叫 `peg`，实际是**静态 PE**（不是 PEG，也不是 TTM）；
2. 没有 PB；
3. 不覆盖创业板指。

因此只用于「数量级 sanity check」：沪深300/上证50 的静态 PE 与 TTM PE 接近，
可以用 ±3% 判；中证500/科创50 天然偏离 20%~45%（成长股盈利波动大），不判。

### 6. Tushare Pro（默认完全禁用，仅人工指令）

`index_dailybasic` / `daily` / `opt_daily` / `fund_share`。

- **默认不参与任何取数，包括兜底**：`Registry.fetch` 会跳过所有 `tushare*`
  provider（`SETTINGS.allow_tushare=False`）。只有显式设 `IV_ALLOW_TUSHARE=1`
  才会进入降级链，`sync_tushare.py` 在导入配置前自行打开。
- `sync_tushare.py` 是人工指令入口：2015 起的权威历史校准、以及需要时的一次性补数。
  它写定的历史（`raw.json` / `etf_raw.json`）**永久留存，不再重拉**。
- 日常七个域（行情、估值、PCR、沪市份额、深市份额、ETF 行情、10Y、日历）
  全部不碰 Tushare；深市份额的缺口也能用深交所区间报表补上。

实测一次日常运行的 provider 分布（2026-10-21 09:1x，深交所正常时）：

```
calendar   sse_calendar
quote      sina_quote
valuation  em_valuation
option_pcr exchange_pcr
etf_share  exchange_etf_share(沪) + szse_etf_share(深)   ← 零 Tushare
etf_quote  sina_quote
bond10y    em_bond10y
```

深交所被限流时，深市那行当日份额取不到 → 记为缺口，下次运行由
`szse_etf_share_range` 补（若同时被限流，缺口留到配额恢复后自动补齐）。
Tushare 不会自动介入，除非人工设了 `IV_ALLOW_TUSHARE=1`。

**限频注意事项（历史坑）**

- `opt_basic` 总量 >23 万行，必须分页到 offset≈400000 才完整，
  否则历史合约缺失、PCR 只剩近 1 年。已缓存到 `data/opt_contracts.json`。
- `opt_daily` 限 200 次/分钟，必须用 `exchange + start_date/end_date` 区间查询
  **按月切片**，不能按 `trade_date` 逐日拉。

---

## 三、Tushare 的定位（人工指令工具，非周期任务）

设计动机与历史分段图见 [ARCHITECTURE.md](ARCHITECTURE.md) 第二节。

**它不再是「每周任务」**：2015–2017 段早已写定、永不变化；日常增量公开源已覆盖；
深市份额的缺口也有深交所区间报表回补。所以只在人工判断需要时才跑：

```bash
$PY sync_tushare.py          # 人工触发（例如怀疑历史库有洞、或想做一次权威校准）
```

`sync_tushare.py` 参数：

- `HIST_FLOOR = "20150105"`：历史下界；
- `TAIL_DAYS = 45`：尾部窗口，覆盖近 6 周（足够消化假期与临时停机）；
- `--full`：从 `HIST_FLOOR` 全量重拉（慎用，耗积分）；
- `--with-pcr`：连带同步期权 PCR（默认跳过，因为交易所源已足够好）；
- `--asof YYYYMMDD`：校准到指定日期。

---

## 四、精度验证记录

### 估值复现（2026-10-19）

| 指数 | PE 偏差 | PB 偏差 |
|------|---------|---------|
| 沪深300 | −0.24% | −0.47% |
| 上证50 | −0.26% | −0.57% |
| 中证500 | +0.35% | −0.04% |
| 创业板指 | +0.02% | **+2.55%** |
| 科创50 | +0.00% | **+2.81%** |

`total_mv` 吻合到 0.00003%。深市两个指数的 PB 偏差 2.5%~2.8%，
怀疑与深市自由流通市值口径差异有关，尚在观察。

### 深市期权未平仓量：直接用页面单边原值（v2.5.0 起）

深交所「交易持仓汇总统计」页面（`CATALOGID=option_jycchztj`）披露的未平仓量，页脚注明为
**对冲后单边**（`kzccsl` / `kdccsl`）；而上交所日统计（`LEAVES_CALL_QTY` / `LEAVES_PUT_QTY`）
与 Tushare `opt_daily` 均为**双边加总**口径。两市定义不同，数值不可直接互比。

**现行做法（2026-10-21 起）**：深市持仓量**直接落库页面原值，不做任何换算**，
报告里创业板指的持仓量、PCR 与深交所官网页面逐位对得上，便于人工复核。

- 交易日 2026-09-09 起的深市行已按此还原（72 行，3 个深市标的），
  校验：159915 `2026-10-20` → 1,444,503 / 643,044，PCR 0.4452，与页面「认沽认购未平仓比率 44.52%」一致。
- 2026-09-08 及更早：Tushare `opt_daily` 双边原值（历史不改）。
- **已知断点**：2026-09-08 → 09-09 之间深市持仓量约有 −5%~−8% 的台阶，
  创业板指 PCR 历史分位**跨越该断点**，仅作相对参照。报告页脚与情绪面注释已注明。

**已废弃做法（v2.4.x，勿恢复）**：曾把深市单边乘以固定系数 `(1.0868, 1.1566)` 换算回双边。
问题是该比值本身漂移，实测：

| 日期 | 页面单边 认购/认沽 | 当时库内（换算值） | 实测比值 c / p |
|---|---|---|---|
| 2024-09-20 | 878,610 / 498,223 | 909,608 / 532,534 | 1.0353 / 1.0689 |
| 2025-09-22 | 817,656 / 1,133,523 | 920,816 / 1,260,125 | 1.1262 / 1.1117 |

即真实比值在 1.03~1.13 间漂移，固定常数带来 ±4% 持仓量误差、PCR 2~4pp 误差；
且该做法使 2026-09-09~10-20 的行既非 Tushare 原值、也非官方页面值（第三种口径），
故整体撤回。成交量（`kzjysl`/`kdjysl`）两市定义一致，与页面逐位相同，从未受影响。

### 期权 PCR（2022-10 至 2026-10，4720 个共同行）

平均偏差 **0.03%**，唯一离群点是到期日 2026-09-23（口径差异，见上文）。

### 报告一致性

新旧报告对比：206660 vs 206688 字节（+28），均 645 行；
`<table>`=8、`<tr>`=9、`<td>`=59、`<th>`=72、`<div>`=80、`class="down"`=6 全部相同；
`DATA` 顶层键完全一致；ERP 序列均 2863 点。
差异仅限预期内的指标漂移（ERP ±0.3%、PCR、深市 PB）。

---

## 四之二、探测过但未采用的源（备查）

### 中证「指数估值看板」—— 唯一带股息率（`dp`）的官方 JSON

```
GET https://www.csindex.com.cn/csindex-home/data-service/indexValuation
```

返回 `{"data":{"tradeDate":"20261020","indexValuations":[{...}]}}`，每条含
`pe`（静态 PE）/ `peg`（滚动 PE）/ `pb` / **`dp`（股息率 %）** / 去年底同口径值。

- **覆盖只有 8 只**：上证指数、上证180、上证50、沪深300、上证380、红利指数、中证红利、中证500；
  **没有创业板指、没有科创50**；
- **只有当日快照**：接受 `?tradeDate=` / `?indexCode=` 也不改变返回（仍是当天 8 只）；
- 与报告口径对照（2026-10-20）：上证50 `dp` 3.21%、沪深300 2.80%、中证500 1.51%。

结论：**不接入**。五只标的里两只无来源，做不成一列；2026-10-21（v2.4.0）已把股息率从报告移除。
其余探测过的端点（`perf/indexCsiDsPe` 只给 PE、`indexInfo/index-details-data` 500、
`exportExcel/downloadindex-perf` 需 POST、国证 `index/indexList` / `selectIndexByCode` 无股息率字段）
均不可用。

---

## 五、如何做交叉校验

```bash
# 全量校验（估值 + 行情 + PCR）
python tools/verify_sources.py --asof 20261019

# 只看估值
python tools/verify_sources.py --only valuation

# 导出明细 CSV 到 work/
python tools/verify_sources.py --csv
```

判读规则：

| 域 | 对照源 | 容差 | 含义 |
|----|--------|------|------|
| `valuation` | 前一日值 | ±15% | 单日跳变，超了基本是取数出错 |
| `valuation` | 中证静态 PE | ±3%（仅沪深300/上证50） | 数量级 sanity check |
| `quote` | 东财（仅当日） | ±0.2% | 两个独立源应当逐位相同 |
| `option_pcr` | Tushare 同日 / 前一日 | ±10% | 允许到期日口径差异 |

> ⚠ 校验时**不要拿 raw.json 当日的值做参照**——那本来就是主源写的，
> 会得到一个恒为 0.00% 的无意义自比。这是本工具最初版本的 bug。

---

## 六、新增数据源的检查清单

想接入新源，按这个顺序做，别跳步：

1. 手工 curl 一次目标接口，确认返回结构、单位、日期格式；
2. 在 `ivdata/providers/` 下新建类，继承 `Provider`，实现对应 `fetch_*`；
3. 在 `ivdata/providers/__init__.py` 的 `PROVIDERS` 里注册；
4. 加入 `ivdata/config.py` 的 `DOMAINS` 链——**先放第二位**，别直接取代主源；
5. 用 `tools/verify_sources.py` 对比一周，确认偏差在容差内；
6. 确认 `DOMAIN_SCHEMA` 的 `min_rows` / `fields` 能拦住残缺返回；
7. 把单位、限频、口径坑写进本文件。
