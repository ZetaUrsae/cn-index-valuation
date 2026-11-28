# Index Valuation Daily — A股宽基指数估值与多维跟踪

一个**每个交易日早上自动更新的 A 股宽基指数估值日报**。它不是行情播报，而是回答四个固定问题：
现在贵不贵（估值）、钱在往哪走（资金）、情绪走到哪一步（期权 PCR 与期货基差）、技术位置如何。
服务于长期配置与定投的日常参考——不求消息面时效，只求口径统一、来源可复核。

覆盖五只宽基：**上证50 / 沪深300 / 中证500 / 创业板指 / 科创50**（股指期货另含中证1000）。
产出是一份自包含的 HTML 单文件，可存档、可转发、可离线打开。

**在线查看**

| 用途 | 地址与说明 |
|---|---|
| 正式日报（本地权威线，历史各期可选） | <https://index-valuation-daily-10055.app.workbuddy.host/?sharecode=WSS7KSLIGL> —— 链接**必须带 `?sharecode=WSS7KSLIGL`**，否则 403；`tools/build_site.py` 生成，保留最近 10 期 + 每月首个交易日 |
| 观察线快照（云端每日独立跑，最新一期） | <https://zetaursae.github.io/cn-index-valuation/> —— 源为 `actions` 分支，根地址＝最新一期 `_gh` 报告；该分支由 workflow 每次 force-push 整体覆盖，本地永不推它 |

产出：`reports/index_val_report_<日期>.html`

> **免责声明**：本项目为个人研究工具。数据全部来自公开接口（新浪财经、东方财富、
> 沪深交易所、中证指数公司），口径与来源在 [docs/DATA.md](docs/DATA.md) 逐项说明；
> 内容不构成投资建议，引用前请自行核对。

---

## 报告内容

单页长报告，自上而下固定顺序（不随数据变化），依次覆盖估值、股债性价比、资金、情绪、技术五个维度：

- **核心指标速览** —— 五指数点位、PE 分位与点位分位（顶部卡片取近 5 年、表内取近 10 年，刻意对照）；
- **一、基本面（估值）** —— 估值总表：PE(TTM)、PB 及**近 10 年分位**、点位分位、隐含 ROE（≈PB/PE），
  "估值状态"按 PE(TTM) 近 10 年分位判定；PE/PB Band（3 / 5 / 10 年窗口）；沪深300 ERP（＝1/PE − 10 年期国债收益率）2015 年以来走势，
  含均值、±1σ、历史分位与关键极值标注；
- **二、资金面** —— 对应宽基 ETF 的份额及 5 / 20 / 60 日变化与走势（全部 / 近三年 / 近一年可切）；
- **三、情绪面** —— 期权持仓 PCR（认沽/认购）走势与历史分位；其后是 IH / IF / IC / IM
  四大股指期货的期限结构与当月基差年化升贴水；
- **四、技术面** —— 各指数日 K 线与均线位置；
- **五、四维信号矩阵与机构展望** —— 逐指数逐维度打标汇总，以及近期外资投行公开观点；
- **总结** —— 各指数处于什么位置、哪边更值得关注。

版式与口径约定（章节顺序、红涨绿跌、日期标注规则）见 [docs/DATA.md](docs/DATA.md) 第二部分末尾；
改版式请改 `scripts/template2.html`，不要手改报告。

---

## 快速开始

```bash
# 依赖：Python 3.13 + requests / pandas / numpy
pip install -r requirements.txt

# PY 换成你本机的 Python 解释器路径；在项目根目录（本仓库克隆处）执行
PY=python

$PY run_daily.py                        # 日常跑一次（约 10~30 秒，21 发 HTTP）
$PY run_daily.py --check                # 只判重：RUN / SKIP
$PY run_daily.py --tag test             # 试运行：产物带 _test 后缀，不参与判重
```

每次正式运行后会把当期报告复制为 `reports/latest.html`（本地固定入口，已在 `.gitignore` 中，
只是本机便利、不进版本库），收藏这一个文件即可，不必每天改日期戳。

日常运行完全自动（本地定时任务周二至六 06:00，权威线），无需人工干预。
完整命令、环境变量、故障排查见 [docs/RUNBOOK.md](docs/RUNBOOK.md)；定时任务每日执行清单见 [docs/DAILY.md](docs/DAILY.md)。

### 测试与检查

```bash
pip install -r requirements-dev.txt     # pytest / ruff，仅开发用
python -m ruff check .                  # 静态检查（语法 + 未定义名/未用变量）
python -m pytest -q                     # 单元测试，约 1 秒
```

`tests/` 覆盖多类"静默失效"：配置契约（DOMAINS 里的每个源都注册过）、归一化单位换算（股/手、元/万元）、
日期工具（月末夹取、闰年跨年）、报告保留与判重、路径唯一性、动态总结文案与站点构建护栏
（新移动端 CSS 不得污染 PC），现 47 例、零联网零数据依赖。
`.github/workflows/ci.yml` 在每次 push 和 PR 上跑这两步，约 20 秒。

---

## 数据与可靠性

- **只用公开接口**：新浪财经、东方财富、沪深交易所、中证指数公司——无 token、无付费账号，任何人可复现。
- **多源降级**：每个数据域配一条优先级链，主源失败自动切备源，单点故障不会让当天报告开天窗。
- **历史只增不改**：已入库的历史永不重拉重算（2015–2017 段建库时写定后冻结），每日运行只追加增量。
- **留痕可复核**：每次运行记录各数据域的实际来源与耗时（`work/provenance.json`），报告页脚标注数据日期。
- **历史报告只读不改**：已产出的报告是快照，口径、文案、脚注的调整只作用于当期及以后；超出保留期的报告
  （最近 10 期 + 每月首个交易日之外）由每日运行自动移入 `reports/archive/`，失败只告警、不影响交付。

实现细节（分层、契约、调度语义）见 [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)。

---

## 文档地图

主文档 5 份 + 变更记录，**每个主题只在一处详述**：

| 想做什么 | 看哪份 |
|----------|--------|
| 了解项目、跑起来 | 本文件 |
| **定时任务每天照着执行**（判重 → 出报告 → 写观点 → 自检 → 推送 GitHub） | [docs/DAILY.md](docs/DAILY.md)（WorkBuddy 定时任务 `Index Valuation Daily`，id `f3a34004-…`，周二至六 06:00） |
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
├── tests/                  单元测试（pytest，47 例，零联网、零数据依赖）
├── tools/                  辅助工具（站点构建等）
├── data/                   历史库（增量缓存）⚠ 禁删，详见 RUNBOOK 第四节
├── work/                   中间产物（可整体清空）
├── site/                   发布站构建产物（build_site.py 生成，不手改）
├── assets/echarts.min.js   图表库本地副本（Actions 报告内联用，避免 CDN）
├── .github/workflows/      Actions 并行观察线（daily.yml）与 CI（ci.yml）
└── reports/                报告产出（根目录＝最近 10 期 + 每月首个交易日，其余在 archive/）
```

一次性修正工具 `recompute_sharpe.py`、`reorder.py` 为非管线脚本，平时不用。

---

## 分支说明

| 分支 | 谁写 | 内容 | 角色 |
|---|---|---|---|
| `main` | 本地定时任务（唯一权威） | 代码 + 完整历史库 + 正式报告 | 日常交付，任何人都以它为准 |
| `actions` | GitHub Actions（每日 force-push） | 云端独立跑一遍的产物（`_gh` 报告、`index.html`） | 并行观察线，供 Pages 发布；**永不合并回 main** |

云端流程：`checkout main`（共享基线）→ `run_daily.py --tag gh` → 推 `actions` →
Pages 自动重建。定义见 [.github/workflows/daily.yml](.github/workflows/daily.yml)。
两条线的 `data/` **各自生长、互不回写**，同日两份报告用于交叉校验数据源稳定性。

云端定时为 UTC 周一至周五 22:16（＝北京周二至周六 06:16），工作日集合与本地一致；
但免费公共仓库的调度常延迟 4~8 小时，实际触发多在上午至下午，故这条线只作观察、不作准点交付。

---

## 变更记录摘要

- **2026-11-28 v2.9.1**：移动端期货贴水表期限列不再浮动（rowspan + sticky 精确化）；信号矩阵改 2×2 紧凑网格并默认折叠、补开合提示；核心估值表小字补估值状态判定口径
- **2026-11-28 v2.9.0**：数据来源/免责、总结、机构展望、ERP 读数默认折叠（仅移动端）；措辞「偏低估→偏低」；门户「新窗口打开」手机隐藏
- **2026-11-28 v2.8.0**：移动端打磨 + 干净网址日期选择（hash 仅在主动切换时写入）；KPI 一行一个、长文字表卡片化

完整记录见 [docs/CHANGELOG.md](docs/CHANGELOG.md)（v2.3.2 及更早压缩为归档摘要表，原文在 git 历史）。
