# Index Valuation Daily — A股宽基指数估值与多维跟踪

每个交易日早上自动生成五只宽基指数（沪深300 / 上证50 / 中证500 / 创业板指 / 科创50）的
「估值 + 资金面 + 情绪面 + 技术面」多维跟踪日报（HTML）。

产出：`reports/index_val_report_<日期>.html`。

---

## 快速开始

```bash
# Python 固定用这个 venv（pandas / requests 装在其中）
PY=C:/Users/zky12/.workbuddy/binaries/python/envs/default/Scripts/python.exe
cd D:/QClaw/Stock/index_valuation

$PY run_daily.py                        # 日常跑一次（约 25 秒）
$PY run_daily.py --check                # 只判重：RUN / SKIP
$PY run_daily.py --tag test             # 试运行：产物带 _test 后缀，不影响定时任务判重
```

日常运行完全自动（定时任务周一至五 06:00），无需人工干预。
完整命令、环境变量、故障排查见 [docs/RUNBOOK.md](docs/RUNBOOK.md)；定时任务每日执行清单见 [docs/DAILY.md](docs/DAILY.md)。

---

## 核心设计（四条）

1. **只走公开源**：七个数据域全部用公开接口（新浪 / 东财 / 沪深交易所官方 / 中证官网），
   每个域有优先级链，单源挂掉自动降级不停报，不依赖任何需要 token 的收费数据源。
2. **历史冻结 + 缺口自愈**：东财估值下界 2018-01-02，2015–2017 为建库时一次性
   写定的历史段，**永久冻结、不再重拉**；沪深两市的 ETF 份额漏日都由交易所官方接口按日回查
   自动回补（深市一次可查 6 个月，沪市按 `STAT_DATE` 逐日）。
3. **只取增量**：每个域都从库内最后一天起算、只往前退 1 天（修正盘中值），
   历史一律不再请求；同一交易日的数据在进程内缓存，五个指数 / 四只 ETF 共用一份。
   实测一次运行 **21 发 HTTP**、约 13 秒。
4. **产出零变化**：v2 只替换取数层，加工与排版脚本原样复用，报告版式严格不变；
   每次运行的取数来源记录在 `work/provenance.json`。

机制细节：[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)（分层/契约/调度/方案 C）。

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
历史演进进 CHANGELOG；每个"坑"写清**现象 → 原因 → 处理**。历史审计报告在 `docs/audits/`
（一次性诊断，勿当现状）。

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

## 其他约定

- **报告版式与口径约定**（章节顺序、红涨绿跌、日期标注规则）见
  [docs/DATA.md](docs/DATA.md) 第二部分末尾（原 REPORT_DATA_MAP 第五节）；
  改版式请改 `scripts/template2.html`，不要手改报告。
- **定时任务**：WorkBuddy 定时任务 `Index Valuation Daily`（id `f3a34004-…`），
  五步流程见 [docs/DAILY.md](docs/DAILY.md)。
- **非管线脚本**：`recompute_sharpe.py`、`reorder.py`（一次性修正工具）。
- **在线查看**：
  - 正式报告 → WorkBuddy 发布站（`tools/build_site.py` 生成，echarts 本地化）；
  - GitHub Actions 观察线 → `actions` 分支，已开 Pages：
    <https://zetaursae.github.io/cn-index-valuation/>（根地址＝最新一期观察报告，
    历史各期在 `reports/index_val_report_<日期>_gh.html`）。该分支由 workflow
    每次运行 force-push 整体覆盖，本地永不推它。

---

## 变更记录摘要

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
