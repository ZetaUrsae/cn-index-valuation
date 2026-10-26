# 架构说明（ARCHITECTURE）

## 一、设计目标

1. **日常基本不依赖 Tushare**：Tushare 的积分、限频、可用性都不受自己控制，
   而这份日报每天都要出。七个数据域全部有非 Tushare 的主源，Tushare 只在
   深市 ETF 份额主源被限流时兜一次底（旧管线是 ~15 次 / 1 万+ 行）。
2. **单源挂掉不能停报**：每个数据域至少两个源，自动降级。
3. **产出零变化**：报告的版式与内容不允许改。所以 v2 只替换"取数"这一层，
   `process / tech / meta / proc2 / prep / gen2` 六个加工脚本一字未动。
4. **可溯源**：每次运行要知道"这个数字是哪个源给的"。

---

## 二、方案 C：历史权威性与日常新鲜度分工

```
2015-01-05 ─────────────── 2017-12-29 │ 2018-01-02 ──────────── 今天
   Tushare 权威历史（不可替代）        │   东财可覆盖（日常增量）
   ← 已写定，永不重拉 →              │   ← 每日自动取数 →
```

- 东财估值数据下界是 **2018-01-02**，而报告分位数依赖 2015 起的完整序列；
- 东财回补历史时用的是**当前成分股**，早年偏差 2%~7%（实测详见 DATA_SOURCES 第二节「已知偏差」）；
- 所以：**Tushare 管历史权威性，东财管日常新鲜度。**

历史段一旦写定就冻结，日常与周末都不再需要 Tushare：

- 估值/行情：东财当日口径已与 Tushare 收敛到 0%（2026 年全年逐日对比）；
- 深市 ETF 份额：日常走深交所当日快照，漏日由深交所「基金规模」区间报表回补；
- `sync_tushare.py` 降级为**人工指令工具**（参数 `HIST_FLOOR` / `TAIL_DAYS` 见 DATA_SOURCES 第三节），
  只有明确要求时才跑；默认连兜底都不触发（`IV_ALLOW_TUSHARE` 未设 = 全程禁用）。

---

## 三、分层

```
┌─────────────────────────────────────────────────────────────┐
│ 入口层                                                       │
│   run_daily.py      日常（v2，公开源）                       │
│   sync_tushare.py   人工指令：权威校准/补数（默认不跑）      │
│   scripts/run_weekly.py  旧管线（v1，全 Tushare，备用）      │
│   tools/verify_sources.py  交叉校验（只读，不写生产文件）    │
└──────────────────────┬──────────────────────────────────────┘
                       │
┌──────────────────────▼──────────────────────────────────────┐
│ 编排层  ivdata/pipeline.py                                   │
│   Pipeline.sync_quotes / sync_valuations / sync_pcr          │
│            sync_etfs / sync_bond10y / finish                 │
│   _norm_* 归一化  |  _merge_by_date 合并  |  _write_json 原子写│
└──────────────────────┬──────────────────────────────────────┘
                       │
┌──────────────────────▼──────────────────────────────────────┐
│ 调度层  ivdata/registry.py                                   │
│   按 DOMAINS 优先级链依次尝试；DOMAIN_SCHEMA 质量校验；       │
│   失败自动降级；记录 Provenance                              │
└──────────────────────┬──────────────────────────────────────┘
                       │
┌──────────────────────▼──────────────────────────────────────┐
│ 数据源层  ivdata/providers/                                  │
│   sina.py      指数/ETF 行情                                 │
│   em.py        估值聚合 / 行情快照 / 10Y 国债                │
│   exchange.py  沪深交易所 PCR / ETF份额 / 交易日历            │
│   csi.py       中证官网（仅交叉校验）                        │
│   local.py     手工输入 / 本地日历兜底                       │
│   tushare.py   全 Tushare 实现（默认禁用，仅人工指令）       │
└──────────────────────┬──────────────────────────────────────┘
                       │
┌──────────────────────▼──────────────────────────────────────┐
│ 加工层  scripts/（v1 原样复用，零改动）                      │
│   process.py → tech.py → meta.py → proc2.py → prep.py → gen2.py │
└──────────────────────┬──────────────────────────────────────┘
                       │
                    reports/index_val_report_<ASOF>.html
```

加工层六个脚本取数后依次执行（`run_daily.py` 自动调度），每个报告章节的数据来源
与它们的对应关系见 [REPORT_DATA_MAP.md](REPORT_DATA_MAP.md)：

| # | 脚本 | 作用 | 产出 |
|---|------|------|------|
| 1 | process.py | 估值分位 / 区间涨跌 / 隐含 ROE | work/metrics.json |
| 2 | tech.py | 均线 / 回撤等技术面 | work/tech.json |
| 3 | meta.py | ETF / 期权元信息（三级兜底，不强依赖 Tushare） | work/opts.json |
| 4 | proc2.py | PCR 与份额指标加工 | work/pcr.json, work/shares.json |
| 5 | prep.py | 技术面扩展指标（60 日 K 线，零外部请求） | work/tech.json（增补） |
| 6 | gen2.py | 组装数据并注入模板 | work/data2.json, reports/*.html |

取数阶段（`ivdata/pipeline.py`）负责：指数行情、指数估值、期权 PCR、
ETF 份额与行情、10Y 国债尾部补齐。

---

## 四、关键设计：Provider 契约

所有 provider 继承 `ivdata.contracts.Provider`，实现 `fetch_<domain>` 方法。

```python
class Provider(abc.ABC):
    name: str                     # 全局唯一，DOMAINS 里引用的就是这个名字
    domains: set                  # 支持的数据域

    def available(self) -> bool:  # 依赖是否就绪（token/库/文件）
        return True
```

**返回值统一为 dict 列表**，字段名严格对齐旧管线
（`raw.json` / `pcr_raw.csv` / `etf_raw.json` 的字段）。
这是"下游脚本零改动"的关键——`process.py` 拿到的还是它认识的那个 dict。

字段契约在 `contracts.py` 用 dataclass 定义（`QuoteBar` / `ValuationRow` /
`OptionPcrRow` / `EtfShareRow`），但**传递时是 dict，不是 dataclass 实例**，
因为旧脚本直接做 `r["trade_date"]` 下标访问。

### 可选标记：`snapshot_only`

有些源只提供"当日一个值"，没有历史区间参数（目前只有深交所基金列表）。
这类源必须标 `snapshot_only = True`，否则会静默出问题：

- 它可能"日期翻篇了、值还没刷新"，管线需要据此启用滞后判定并换源重取；
- 漏跑的日子它自己补不回来，需要 `_fill_share_gaps` 用区间源兜（见第五节）。

上交所那条虽然也是"一次只给一日名单"，但它的 `STAT_DATE` 能直接回查任意历史日期，
相当于可自愈，所以不标这个标记（而且沪市在链上没有备选源，
被误判为"未刷新"就会换到深市接口并必然失败）。

### 调度语义

`Registry.fetch(domain, *args, _skip=(), **kwargs)` 的行为：

```
for name in DOMAINS[domain]:
    name in _skip             → 跳过（调用方指定本次不要用这个源）
    ├─ provider 未注册       → 记错误，下一个
    ├─ provider 不支持该域    → 记错误，下一个
    ├─ 是 tushare* 且已禁用   → 记错误，下一个
    ├─ available() == False  → 记错误，下一个
    ├─ fetch_*() 抛 ProviderUnavailable → 不算失败，下一个
    ├─ fetch_*() 抛其他异常   → 记失败，下一个
    ├─ DOMAIN_SCHEMA 校验不过 → 记失败，下一个
    └─ 通过 → 返回，记录 Provenance，结束
全部失败 → raise ProviderError（带上每个源的错误摘要）
```

`_skip` 是给「主源给了可疑结果，换下一个源重取」用的，**不会**传给 provider。
目前只有一处使用：`Pipeline.sync_etfs` 发现深交所快照"日期翻篇了、值却没变"
时，把 `szse_etf_share` 排除后重新取一次（判定逻辑见 `_stale_snapshot`）。

`DOMAIN_SCHEMA` 是轻量质量门，防止"接口返回 200 但内容是空表"：

```python
"valuation": {"min_rows": 1, "fields": ["trade_date", "pe_ttm", "pb"]},
```

### 强制与禁用

- `IV_FORCE="valuation=tushare_valuation"` → 把该源提到链首
- `IV_ALLOW_TUSHARE=1` → 才允许 `tushare*` 进入降级链（默认禁用，仅 `sync_tushare.py` 自设）

---

## 五、增量与合并

### `_merge_by_date(old, new)`

按 `trade_date`（或 `date`）合并两份列表：

```
索引 old 的每一行 → 建 dict
new 的每一行覆盖进去（新值优先，可覆盖修订值）
按日期升序输出
```

"新值优先"是有意的：交易所偶尔会修订近期数据，旧值保护会导致修订永远进不来。
代价是**窗口内的日期会被覆盖**，所以窗口必须小（默认 1 天）；历史靠窗口本身挡住。

### 回看窗口：只取增量，不重拉历史

**原则**：库里已有的历史一律不再请求。每个域都从本地最后一行的日期往前退 N 天
开始取，N 由 `OVERLAP_BY_DOMAIN` 按域配置，默认 **1 天**——只重取最后一天，
用于修正盘中值 / 未定稿值，其余全是新日期。2015 起的存量数据（含 Tushare
写定的历史段）直接复用，永不重拉。

| 域 | 窗口 | 说明 |
|----|------|------|
| 行情 / 估值 | 1 天 | 只重取最后一天；`IV_OVERLAP=N` 可全局放大（仅排障用） |
| ETF 份额 / 行情 | 1 天 | 同上；真正的缺口由 `_fill_share_gaps` 另行扫描补齐 |
| PCR | 1 天 | 交易所按日查，窗口越大越发请求，深交所有限流前车之鉴 |
| 10Y 国债 | 1 天 | 东财按日查 |

### 进程内缓存：同一份数据不拉第二遍

| 缓存 | 位置 | 省掉的重复 |
|------|------|-----------|
| 全市场个股估值快照（按日） | `em._STOCK_DAY_CACHE` | 5 个指数共用同一天 = 5 倍 |
| 上交所 ETF 份额全市场名单（按日） | `exchange._SSE_SHARE_CACHE` | 4 只沪市 ETF = 4 倍 |
| 交易日历全序列 | `exchange._CAL_CACHE` | 一次运行内 6 次 → 1 次 |
| 交易日列表 | `exchange._trading_days`（lru_cache） | 各域缺口检测的重复调用 |

实测一次日常运行的 HTTP 请求数：**21 发**（旧窗口 15 天时 35 发，其中东财 11 → 3）。
样本：`asof=20261020`，行情 10 发（5 指数 + 5 ETF）、上交所 4 发、深交所 3 发、
东财 3 发（估值 2 天 + 10Y）、中证 1 发（日历）。

### 原子写

`_write_json` 先写临时文件，再 `os.replace` 覆盖。
避免"写到一半被 kill"造成 JSON 损坏。

---

## 六、运行元信息的存放（重要约束）

**不能**把 `{"_meta": ..., "000300.SH": ...}` 混在一起写进 `raw.json`：

```python
# process.py 第 N 行
for code, d in raw.items():
    name = d["name"]        # ← "_meta" 是 str，会 KeyError
```

所以运行元信息分两处：

- `work/watermarks.json` —— 各域最后成功取数的日期，用于增量起点与健康判断
- `work/provenance.json` —— 本次运行每个域的 provider、耗时、行数、降级链

`yield10y_history.json` 同理必须是**扁平字典**（`gen2.py` 用 `.get(date_key)`）。

---

## 七、Provenance（溯源）

每次运行结束打印：

```
数据来源溯源：
domain        provider            rows    elapsed  fallback
valuation     em_valuation        5       12.4s    -
quote         sina_quote          25      1.2s     -
option_pcr    exchange_pcr        8       6.1s     -
etf_share     exchange_etf_share  10      3.3s     -
bond10y       em_bond10y          1       0.8s     -

本次网络请求 89 次：sse=18, eastmoney=31, sina=25, szse=3, chinabond=12
```

`fallback_from` 非空说明该域降级过，值得看一眼。
`Registry.used_tushare()` 返回本次是否动用了 Tushare（默认关掉后应恒为 False）。

---

## 八、错误处理约定

| 异常 | 含义 | 调度器行为 |
|------|------|-----------|
| `ProviderUnavailable` | 依赖缺失（无 token、无库） | 不算失败，换下一个源 |
| 其他 `Exception` | 该源这次取数失败 | 记录失败，换下一个源 |
| `ProviderError`（全链失败） | 所有源都挂 | 抛给 Pipeline，由入口决定是否继续 |

`Pipeline` 层面：估值/行情/PCR/ETF 四个域中任一失败，`run_daily.py`
会把它记入 `failed` 列表但仍继续跑完其余步骤，最后以非 0 退出码结束。
**只有加工阶段失败才会 `break`**（因为后续步骤依赖前一步的产物）。

10Y 国债（`sync_bond10y`）是**非致命**步骤，异常只打印不中断——
`gen2.py` 会退回序列里最近一日的 10Y，ERP 读数仍可用（`manual_inputs.bond10y` 旁路已废弃）。

---

## 九、为什么 csi 不在主链

`CsiValuation` 看起来是最权威的源（中证指数公司官方），但有三个硬伤：

1. `/perf/indexCsiDsPe` 返回的字段名叫 `peg`，**实际是静态 PE**，不是 TTM；
2. 没有 PB；
3. 不覆盖创业板指（`csi_code = None`）。

把它当主源会让科创50 的 PE 差近一倍。所以它只出现在
`tools/verify_sources.py` 里做数量级 sanity check，
且只对沪深300/上证50 判阈值。

`CsiQuote`（`index-perf-oneday`）只给当日单点、无历史，同样不能进链。

---

## 十、目录职责

目录树与各目录职责见 [../README.md](../README.md)「目录结构」；
`data/` 与 `work/` 下每个文件的写入者与可否删除见 [RUNBOOK.md](RUNBOOK.md) 第四节。

---

## 十一、扩展点

想加一个新数据源，只需三步，**不用碰 Pipeline 和加工脚本**：

```python
# 1. ivdata/providers/mysrc.py
class MyValuation(Provider):
    name = "mysrc_valuation"
    domains = {"valuation"}
    def fetch_valuation(self, code, start, end):
        return [{"trade_date": ..., "pe_ttm": ..., "pb": ...}]

# 2. ivdata/providers/__init__.py
PROVIDERS = [..., MyValuation]

# 3. ivdata/config.py
DOMAINS["valuation"] = ["em_valuation", "mysrc_valuation", "tushare_valuation"]
```

放在第二位而不是第一位——先跑一周用 `verify_sources.py` 对比，
确认偏差在容差内再考虑提权。
