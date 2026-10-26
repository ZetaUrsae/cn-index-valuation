# 文档索引

## 分工原则

**每个主题只在一个文档里详述，其余文档只留一句话加指针。**
写新文档前先查下表，避免内容重复。

| 主题 | 唯一权威位置 |
|------|--------------|
| 项目介绍、快速命令、目录结构、文档地图 | [../README.md](../README.md) |
| 分层设计、Provider 契约、调度语义、方案 C、扩展点 | [ARCHITECTURE.md](ARCHITECTURE.md) |
| 数据域优先级链、各源接口/单位/口径/精度 | [DATA_SOURCES.md](DATA_SOURCES.md) |
| 操作命令、环境变量、数据文件清单、故障排查、验收清单、v1 备用 | [RUNBOOK.md](RUNBOOK.md) |
| **定时任务每日执行清单**（提示词的展开版；提示词本身在 WorkBuddy 任务 `f3a34004`） | [RUNBOOK.md](RUNBOOK.md) 第七节 |
| 报告章节→数据来源映射、报告版式与口径约定 | [REPORT_DATA_MAP.md](REPORT_DATA_MAP.md) |
| 逐版本变更 | [CHANGELOG.md](CHANGELOG.md) |

## 什么时候看哪份

| 文档 | 读者 | 什么时候看 |
|------|------|-----------|
| [../README.md](../README.md) | 所有人 | 第一次接触项目 |
| [REPORT_DATA_MAP.md](REPORT_DATA_MAP.md) | 所有人 | 想知道报告某一章/某个数字从哪来；改版式前看约定 |
| [DATA_SOURCES.md](DATA_SOURCES.md) | 核对数据的人 | 怀疑某个数字不对、查接口/单位/口径 |
| [ARCHITECTURE.md](ARCHITECTURE.md) | 改代码的人 | 要动取数层、加数据源、理解调度语义 |
| [RUNBOOK.md](RUNBOOK.md) | 值守的人 | 报告没出来、图表空白、PCR 不更新 |
| [CHANGELOG.md](CHANGELOG.md) | 所有人 | 想知道"什么时候为什么改了这个" |

## 历史审计（`audits/`）

这些是**一次性诊断报告**，保留作决策依据与踩坑记录。
其中的「待修复」条目在 v2.0 已完成或已被架构取代，**不要当作当前状态**。

| 文件 | 内容 |
|------|------|
| `audits/20261020_healthcheck_round1.md` | 第一轮体检：定时任务配置、工程架构、代码稳健性、提示词合理性 |
| `audits/20261020_healthcheck_round2.md` | 第二轮独立复核（只读诊断，未改代码） |
| `audits/20261020_option_source_validation.md` | 沪深交易所期权持仓量官方接口可行性验证 |

> 第二轮体检提出的三条待修复项，处置情况：
>
> 1. `fetch2b.py` 期权合约缓存 TTL 被回退为 20 天 → **已被取代**：
>    v2 的 PCR 走交易所官方汇总，不再依赖逐合约缓存；`fetch2b.py` 仅在
>    `sync_tushare.py --with-pcr`（人工指令）时使用。
> 2. `proc2.py` ETF 份额 YTD 基准硬编码 `"20260101"` → **已修（2026-10-20）**：
>    改为 `x < lastd[:4] + "0101"`，即按数据自身年份取上一年末。
>    用 `lastd` 而非 `ASOF`，因为份额发布可能滞后于行情，按数据年份算才不会错位。
> 3. 定时任务 prompt 里 views/syn 的写入顺序不合理 → **已修（2026-10-20）**：
>    流程由四步改为五步，机构观点移到管线之后（读 `work/metrics.json` /
>    `pcr.json` / `shares.json` 据实写，再只重跑 `gen2.py`）；
>    入口同时由 `scripts/run_weekly.py` 换成 `run_daily.py`，并保留失败回退。

---

## 写文档的约定

- 文件名全大写英文（`RUNBOOK.md`），日期用 `YYYYMMDD`；
- 主文档只写**当前状态**，历史演进写进 `CHANGELOG.md`；
- **同一内容不要在两份文档里各写一遍**——第二处写指针（"见 XXX 第 N 节"）；
- 每个"坑"必须写清**现象 → 原因 → 处理**三件事，只写原因后来人没法用；
- 涉及数字的地方标出**取数日期**，否则半年后无法复现。
