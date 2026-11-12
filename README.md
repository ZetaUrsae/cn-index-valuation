# Index Valuation Daily — A股宽基指数估值与多维跟踪

一个**每个交易日早上自动更新的 A 股宽基指数估值日报**。它不是行情播报，而是回答四个固定问题：
现在贵不贵（估值）、钱在往哪走（资金）、情绪走到哪一步（期权 PCR 与期货基差）、技术位置如何。
服务于长期配置与定投的日常参考——不求消息面时效，只求口径统一、来源可复核。

覆盖五只宽基：**上证50 / 沪深300 / 中证500 / 创业板指 / 科创50**（股指期货另含中证1000）。
产出是一份自包含的 HTML 单文件，可存档、可转发、可离线打开。

**在线查看**

- 正式日报（本地权威线，含历史各期）：<https://index-valuation-daily-10055.app.workbuddy.host/?sharecode=WSS7KSLIGL>
- 观察线快照（云端每日独立跑，最新一期）：<https://zetaursae.github.io/cn-index-valuation/>

产出：`reports/index_val_report_<日期>.html`

> **免责声明**：本项目为个人研究工具。数据全部来自公开接口（新浪财经、东方财富、
> 沪深交易所、中证指数公司），口径与来源在 [docs/DATA.md](docs/DATA.md) 逐项说明；
> 内容不构成投资建议，引用前请自行核对。

---

## 报告内容

单页长报告，自上而下固定顺序（不随数据变化），依次覆盖估值、股债性价比、资金、情绪、技术五个维度：

- **核心指标速览** —— 五指数点位、PE 分位与点位分位（顶部卡片取近 5 年、表内取近 10 年，刻意对照）；
- **一、基本面（估值）** —— 估值总表：PE(TTM)、PB 及**近 10 年分位**、点位分位、隐含 ROE（≈PB/PE）；
  PE/PB Band（3 / 5 / 10 年窗口）；沪深300 ERP（＝1/PE − 10 年期国债收益率）2015 年以来走势，
  含均值、±1σ、历史分位与关键极值标注；
- **二、资金面** —— 对应宽基 ETF 的份额及 5 / 20 / 60 日变化与走势（全部 / 近三年 / 近一年可切）；
- **三、情绪面** —— 期权持仓 PCR（认沽/认购）走势与历史分位；其后是 IH / IF / IC / IM
  四大股指期货的期限结构与当月基差年化升贴水；
- **四、技术面** —— 各指数日 K 线与均线位置；
- **五、四维信号矩阵与机构展望** —— 逐指数逐维度打标汇总，以及近期外资投行公开观点；
- **总结** —— 各指数处于什么位置、哪边更值得关注。

版式与口径约定见 [docs/DATA.md](docs/DATA.md) 第二部分。

---

## 快速开始

```bash
# 依赖：Python 3.13 + requests / pandas / numpy
pip install -r requirements.txt

# 下面两行为作者本机环境，换机器按自己的路径替换
PY=C:/Users/zky12/.workbuddy/binaries/python/envs/default/Scripts/python.exe
cd D:/QClaw/Stock/index_valuation

$PY run_daily.py                        # 日常跑一次（约 25 秒，21 发 HTTP）
$PY run_daily.py --check                # 只判重：RUN / SKIP
$PY run_daily.py --tag test             # 试运行：产物带 _test 后缀，不参与判重
```

日常运行完全自动（定时任务周一至五 06:00），无需人工干预。
完整命令、环境变量、故障排查见 [docs/RUNBOOK.md](docs/RUNBOOK.md)；定时任务每日执行清单见 [docs/DAILY.md](docs/DAILY.md)。

---

## 数据与可靠性

- **只用公开接口**：新浪财经、东方财富、沪深交易所、中证指数公司——无 token、无付费账号，任何人可复现。
- **多源降级**：每个数据域配一条优先级链，主源失败自动切备源，单点故障不会让当天报告开天窗。
- **历史只增不改**：已入库的历史永不重拉重算（2015–2017 段建库时写定后冻结），每日运行只追加增量。
- **留痕可复核**：每次运行记录各数据域的实际来源与耗时（`work/provenance.json`），报告页脚标注数据日期。

实现细节（分层、契约、调度语义）见 [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)。

---

## 文档地图

主文档 5 份 + 变更记录，**每个主题只在一处详述**：

| 想做什么 | 看哪份 |
|----------|--------|
| 了解项目、跑起来 | 本文件 |
| **定时任务每天照着执行**（判重 → 出报告 → 写观点 → 自检 → 推送 GitHub） | [docs/DAILY.md](docs/DAILY.md) |
| 手工运行、环境变量、数据文件清单、排障、改动后验收 | [docs/RUNBOOK.md](docs/RUNBOOK.md) |
| 查某个数字从哪来：数据源接口/单位/口径 + 报告章节映射 | [docs/DATA.md](docs/DATA.md) |
| 改取数层代码、加数据源、理解调度语义 | [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) |
| 查"什么时候为什么改了" | [docs/CHANGELOG.md](docs/CHANGELOG.md) |

写文档的约定：同一内容不要在两份文档里各写一遍（第二处写指针）；主文档只写当前状态，
历史演进进 CHANGELOG；每个"坑"写清**现象 → 原因 → 处理**。

---

## 目录结构

```
index_valuation/
├── run_daily.py            ✅ 日常入口（v2）
├── docs/                   架构 / 数据源 / 数据地图 / 执行手册 / 变更记录
├── ivdata/                 ✅ 取数框架
│   ├── config.py           路径、设置、标的表、域优先级链
│   ├── contracts.py        Provider 基类与数据结构
│   ├── http.py             会话/限流/重试/容错解析
│   ├── registry.py         优先级链调度 + 质量门
│   ├── pipeline.py         业务编排 + 归一化 + 合并 + 原子写
│   ├── provenance.py       溯源
│   ├── store.py            JSON / CSV 读写
│   └── providers/          sina / em / exchange / csi / local
├── scripts/                加工与排版（v1 原样复用）
├── tools/                  辅助工具（站点构建等）
├── data/                   历史库（增量缓存）⚠ 禁删，详见 RUNBOOK 第四节
├── work/                   中间产物（可整体清空）
├── assets/echarts.min.js   图表库本地副本（Actions 报告内联用，避免 CDN）
├── .github/workflows/      Actions 并行观察线（daily.yml）
└── reports/                报告产出（archive/ 为 v1 周报存档）
```

---

## 分支说明

| 分支 | 谁写 | 内容 | 角色 |
|---|---|---|---|
| `main` | 本地定时任务（唯一权威） | 代码 + 完整历史库 + 正式报告 | 日常交付，任何人都以它为准 |
| `actions` | GitHub Actions（每日 force-push） | 云端独立跑一遍的产物（`_gh` 报告、`index.html`） | 并行观察线，供 Pages 发布；**永不合并回 main** |

云端流程：`checkout main`（共享基线）→ `run_daily.py --tag gh` → 推 `actions` →
Pages 自动重建。定义见 [.github/workflows/daily.yml](.github/workflows/daily.yml)。
两条线的 `data/` **各自生长、互不回写**，同日两份报告用于交叉校验数据源稳定性。

---

## 其他约定

- **报告版式与口径约定**（章节顺序、红涨绿跌、日期标注规则）见
  [docs/DATA.md](docs/DATA.md) 第二部分末尾（原 REPORT_DATA_MAP 第五节）；
  改版式请改 `scripts/template2.html`，不要手改报告。
- **定时任务**：WorkBuddy 定时任务 `Index Valuation Daily`（id `f3a34004-…`），
  五步流程见 [docs/DAILY.md](docs/DAILY.md)。
- **非管线脚本**：`recompute_sharpe.py`、`reorder.py`（一次性修正工具）。
- **在线查看**：
  - **正式报告** → WorkBuddy 发布站：<https://index-valuation-daily-10055.app.workbuddy.host/?sharecode=WSS7KSLIGL>
    （`tools/build_site.py` 生成，echarts 本地化；保留每月首个交易日 + 最近 10 期）。
    链接**必须带 `?sharecode=WSS7KSLIGL`**，不带会 403。
  - **观察线** → GitHub Pages：<https://zetaursae.github.io/cn-index-valuation/>
    （源为 `actions` 分支，根地址＝最新一期 `_gh` 报告，历史各期在 `reports/index_val_report_<日期>_gh.html`；
    该分支由 workflow 每次运行 force-push 整体覆盖，本地永不推它）。

---

## 变更记录摘要

- **2026-11-11 v2.7.4**：GitHub Actions 并行观察线上线（云端每日独立跑一遍、产物推 `actions` 分支、Pages 发布）；仓库转公开；脚本路径改 `__file__` 推导（可移植）；Tushare 相关代码与文档全量移除（历史数据保留沿用）
- 2026-11-11 v2.7.3：站点保留策略＝每月首个交易日锚点 + 最近 10 期
- 2026-11-10 v2.7.2：移动端适配（仅 ≤640px 断点，桌面零影响）
- 2026-11-03 v2.7.1：报告发布为在线站点（`tools/build_site.py`，echarts/SDK 本地化）
- 2026-10-28 v2.7.0：机构展望表改「状态 + 观点变化」；2026-10-27 v2.6.7–2.6.8：版式改造（删头部说明、ERP 默认近十年、期货表期限胶囊与年化条、KPI 卡带温度条）
- **2026-10-27 v2.6.6**：修复 10-27 06:00 定时任务失败——期货环节死循环（季月游标不前进）、CUR 数据结构错、`push2his` 被拒；取数加超时收紧与熔断，close_hist/中证1000 现货接新浪兜底
- **2026-10-26 v2.6.5**：情绪面新增「股指期货当月基差」（IH/IF/IC/IM 升贴水走势+读数条，PCR 之后）；新取数脚本 fetch_futures.py（新浪合约拼接当月连续+中证1000 现货）
- **2026-10-26 v2.6.4**：文档体系精简为 6 份（DAILY.md 每日执行清单 / DATA.md 合并 / INDEX 并入本文件）；项目备份至 GitHub 私有仓库，定时任务新增每日推送步骤（单次尝试、失败下次补推）
- 2026-10-23 v2.6.3：核心估值表加「点位分位」列；表下小字展示沪深300/中证500/创业板指近十年+近五年点位中位数；总市值列删除
- 2026-10-21 v2.6.0–2.6.2：ERP 图与读数条可交互（指数×窗口）；PE/PB Band 上线（v2.5.9）；份额/PCR 走势加三档时间窗口；机构观点时效规则（当月或上月+核实日期）
- 2026-10-21 v2.4–2.5：深市 PCR 改单边原值落库（可复核优先）；核心估值表加点位分位探索；提示词分工原则确立（提示词只写意图，细节在文档）
- 2026-10-21 v2.2–2.3：深市份额缺口由深交所区间报表自动回补；只取增量改造（21 发 HTTP/13s）
- 2026-10-20 v2.0–2.1：取数层重构为 `ivdata/` 框架；日报化（周一至五 06:00）
- 2026-10-15 v1.8：加入 ERP 专题；打通 10Y 国债自动来源

完整记录见 [docs/CHANGELOG.md](docs/CHANGELOG.md)（v2.3.2 及更早压缩为归档摘要表，原文在 git 历史）。
