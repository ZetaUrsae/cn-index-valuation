# 执行手册（RUNBOOK）

面向"人工要能操作、出问题要能查"的场景。所有命令都在
`D:/QClaw/Stock/index_valuation/` 下执行，Python 用固定路径：

```
C:/Users/zky12/.workbuddy/binaries/python/envs/default/Scripts/python.exe
```

下文简写为 `$PY`。

> **定时任务的每日执行清单已独立为 [DAILY.md](DAILY.md)**（定时任务唯一自动加载的文档，
> 2026-10-26 起与提示词配套）。本手册供**人工查阅**：手工运行、环境变量、数据文件清单、
> 排障、改动后验收。

---

## 一、例行操作

### 1.1 每日（自动）

定时任务 **Index Valuation Daily**（周一至周五 06:00）调用 `run_daily.py`，
取上一交易日收盘数据，产出 `reports/index_val_report_<日期>.html`。

无需人工干预。若需确认：

```bash
ls -lt reports/*.html | head -3
```

### 1.2 人工指令（Tushare 校准 / 补数，默认不跑）

为什么不再周期性跑，见 [DATA.md](DATA.md) 第一部分第三节（一句话：2015–2017 段
已写定冻结，日常增量公开源全覆盖，深市份额缺口由深交所区间报表回补）。需要人工校准时：

```bash
$PY sync_tushare.py
```

输出示例：

```
[tushare-sync] 参考日 20261019  full=False  with_pcr=False
  [ts-valuation] 000300.SH +11 → 2862 行 (末 20261019)
  ...
[tushare-sync] valuation 完成，新增 55 行
[tushare-sync] quote 完成，新增 55 行
[tushare-sync] etf 完成，新增 40 行
```

退出码：`0` 成功 / `1` Tushare 不可用（不致命）/ `2` 部分域失败。

**close_history.json 的一次性回填已完成（2026-10-21），不要再跑**：

```bash
# 仅历史存档——2026-10-21 已执行，重复执行没有意义（缺的早已补齐）
cd scripts && ASOF=20261020 $PY fetch_close_hist.py --seed-tushare
```

### 1.3 每周（交叉校验，只读）

随时可跑，校验「当日值 vs 库内 Tushare 同日值 / 中证官网」：

```bash
$PY tools/verify_sources.py --csv
```

看最后一行 `异常 N 条 / 共 M 条`。`N > 0` 时按第五节排查。

---

## 二、手工运行

```bash
$PY run_daily.py                        # 正常跑一次（约 10~15 秒，21~25 发请求）
$PY run_daily.py --check                # 只判重：RUN / SKIP（定时任务第 1 步）
$PY run_daily.py --tag test             # 试运行：产物带 _test 后缀，不参与判重（见 DAILY.md 二）
$PY run_daily.py --fetch-only --asof 20261016   # 只补某天的数据（不出报告）
$PY run_daily.py --fetch-only           # 只取数不出报告（调试数据源，不触碰 reports/）
$PY run_daily.py --skip-bond            # 跳过 10Y 补齐（东财 10Y 慢/挂时用，ERP 末点会滞后）
```

补数口径（v2.3 起只取增量）：各域从库内最后一天起算、只回看 1 天；
要重算最近 N 天用 `IV_OVERLAP=N`（仅排障，见第三节）。

**两条限制**（v2.5.8 起代码强制/提醒）：

- **出报告只能是库内最新交易日**。`--asof` 早于库内最新日会被直接拒绝——
  加工链的 `tech.py`/`prep.py` 取的是库内最新一行、不按 ASOF 切片，
  回算会产出"估值是旧的、技术面是新的"混搭报告。只补数据请加 `--fetch-only`。
- **盘后手工跑当天要显式 `--asof`，且别早于 17:00**。上交所日历在 T 日盘后
  仍不含当日（实测 15:41 查询，末条是 T-1），所以 `--check` 会把 asof 定在昨天；
  而份额、期权 PCR 要到晚间才发布——15:41 实跑时行情已是当日收盘、份额与 PCR 仍停在前一日。
  正常出当日报告就交给次日 06:00 的定时任务。

---

## 三、环境变量

| 变量 | 默认 | 说明 |
|------|------|------|
| `ASOF` | 自动推导 | 参考交易日 `YYYYMMDD` |
| `IV_ALLOW_TUSHARE` | `0` | 设 `1` 才允许 Tushare 进入降级链；默认全程禁用，仅 `sync_tushare.py` 自行开启 |
| `IV_FORCE` | 空 | `域=provider`，强制某域走某源，如 `valuation=em_valuation` |
| `IV_TIMEOUT` | `20` | 单请求超时（秒） |
| `IV_RETRIES` | `3` | 重试次数 |
| `IV_BACKOFF` | `1.5` | 重试退避基数（秒） |
| `IV_QPS` | `5` | 每源每秒请求上限 |
| `IV_OVERLAP` | 不设（按域 1 天） | 全局覆盖各域回看窗口，仅排障用（例如 `IV_OVERLAP=30` 重算最近一个月）；不设则各域只重取最后 1 天 |
| `IV_OPT_CONTRACT_DETAIL` | `0` | 设 `1` 才逐合约取期权明细（数据量大） |
| `IV_REPORT_TAG` | 空 | 试运行标记，报告名加 `_后缀`，不参与判重（等同 `--tag`，见 DAILY.md 二） |

示例：

```bash
# 排障：临时允许 Tushare 进入降级链（人工指定；平时不要设）
IV_ALLOW_TUSHARE=1 $PY run_daily.py --fetch-only

# 强制某域走某源
IV_FORCE="valuation=em_valuation" $PY run_daily.py --fetch-only
```

---

## 四、产物与中间文件

> 本表是数据文件的**唯一权威清单**（含写入者）。报告各章节与这些文件的对应关系
> 见 [DATA.md](DATA.md) 第二部分。

| 路径 | 写入者 | 内容 | 可否删除 |
|------|--------|------|----------|
| `data/raw.json` | run_daily 各 sync_* | 五指数估值 + 行情历史（2015 起 / 行情 2019-12 起） | ❌ **禁止** |
| `data/etf_raw.json` | run_daily sync_etfs | ETF 份额与行情（2023 起） | ❌ **禁止** |
| `data/pcr_raw.csv` | run_daily sync_pcr | 期权 PCR 日度聚合（2022-10 起） | ❌ **禁止** |
| `data/yield10y_history.json` | run_daily 第 5 步 / fetch_yield_tail.py | 10Y 国债日频（2002 起，扁平字典） | ❌ **禁止** |
| `data/close_history.json` | fetch_close_hist.py（run_daily 第 6 步，非致命） | 五指数日收盘价 2015 起（2015~2019 为 Tushare 2026-10-21 一次性回填，其后东财 K 线增量），PE/PB Band 与点位分位/点位中位数（v2.6.3）专用 | ❌ **禁止** |
| `data/opt_contracts.json` | meta.py | 期权合约表缓存（TTL 4 天） | ⚠ 可删，会重新拉（慢） |
| `data/em_constituents.json` | em_valuation | 东财成分股缓存（TTL 7 天） | ⚠ 可删，会重拉 |
| `data/etf_meta.json` | meta.py | ETF 名称/管理人/费率缓存 | ⚠ 可删，有内置兜底 |
| `data/manual_inputs.json` | 每日流程（模型撰写） | 研究文本：外资投行观点 `views`（按机构一行一条）+ `syn`（沪深300、创业板指各一句） | ❌ **禁止**，且必须合法 JSON |
| `data/cache/` | 各 provider | provider 级原始响应缓存 | ✅ 可删 |
| `work/metrics.json` | process.py | 估值分位 + 点位分位/点位中位数 + 区间涨跌 + 隐含 ROE | ✅ 可整体清空，每次重写 |
| `work/tech.json` | tech.py, prep.py | 技术面指标 + 60 日 K 线 | 同上 |
| `work/pcr.json` / `work/shares.json` | proc2.py | PCR / 份额加工结果 | 同上 |
| `work/opts.json` | meta.py | ETF / 期权元信息 | 同上 |
| `work/data2.json` | gen2.py | 报告 DATA 的落盘副本（调试用） | 同上 |
| `work/provenance.json` | run_daily | 本次取数溯源（域→provider→行数→降级） | ✅ 可删，每次重写 |
| `work/watermarks.json` | run_daily | 各域最后成功取数日期 | ✅ 可删，会重建 |
| `reports/*.html` | gen2.py | 报告产出 | ⚠ 归档用，别乱删 |

### 两个 JSON 的格式红线（踩过坑）

1. **`raw.json` 顶层只能是 `{code: {...}}`**。
   `process.py` 里是 `for code, d in raw.items(): name = d["name"]`，
   任何 `_meta`、`version` 之类的键都会 `KeyError: 'name'`。
   运行元信息写到 `work/watermarks.json`。

2. **`yield10y_history.json` 必须是扁平字典** `{"2026-10-19": 1.65, ...}`。
   `gen2.py` 用 `_y10all.get(_ds)` 查找。写成 `{"data": [...]}` 会让
   ERP 专题整段空白（报告从 ~25 万掉到 ~20 万字节）。

3. **`close_history.json` 是 `{ts_code: {"YYYY-MM-DD": close}}` 的两层字典**。
   写入者只有 `fetch_close_hist.py`（东财增量）；2015~2019 段由 Tushare
   `index_daily` 一次性回填（2026-10-21，用户批准仅此一次，**不要再跑
   `--seed-tushare`**）。已有历史不覆盖、只补缺，最近 3 天允许覆盖。
   v2.6.3 起 `process.py` 也**只读**本文件（算点位分位与近10年点位中位数）。

---

## 五、故障排查

### 5.1 报告变小了 / ERP 图表消失

**症状**：报告 HTML 从 ~25 万掉到 ~20 万字节，ERP 折线图空。

**原因**：`yield10y_history.json` 格式被写错。

**处理**：

```bash
$PY -c "
import json
d=json.load(open('data/yield10y_history.json',encoding='utf-8'))
print(type(d).__name__, len(d))
print(list(d.items())[:3])
"
```

应当是 `dict` 且键形如 `'2026-10-19'`。若输出 `dict 2` 且键是 `data`/`meta`，
说明格式错了，从备份恢复或重跑 `sync_bond10y`。

### 5.2 `KeyError: 'name'`（process.py 报错）

**原因**：`raw.json` 顶层被写入了元信息键。

**处理**：

```bash
$PY -c "
import json
raw=json.load(open('data/raw.json',encoding='utf-8'))
print(list(raw.keys()))
"
```

只应出现 `000300.SH 000016.SH 000905.SH 399006.SZ 000688.SH`。
多出来的键手工删掉即可。

### 5.3 估值某个指数缺失 / PE 为 null

**排查顺序**：

```bash
# ① 东财成分股是否拿到
$PY -c "
import json
d=json.load(open('data/em_constituents.json',encoding='utf-8'))
for k,v in d.items(): print(k, len(v.get('codes',v) if isinstance(v,dict) else v))
"

# ② 强制东财单跑一天
$PY -c "
import sys; sys.path.insert(0,'.')
from ivdata.providers.em import EmValuation
print(EmValuation().fetch_valuation('000300.SH','20261019','20261019'))
"
```

常见原因：
- 东财 `RPT_VALUEANALYSIS_DET` 当日尚未发布（约 18:00 后才有）→ 换上一交易日；
- 成分股缓存过期且刷新失败 → 删 `em_constituents.json` 重跑；
- 收到 `antlr InputMismatchException` → `filter=(INDEX_CODE=000300)` 被加了引号。

### 5.4 PCR 最新日期停在某个旧日期

**原因**：交易日历用了 Mon–Fri 近似，遇到长假会触发"连续 3 天空值就停"的提前退出。

**确认**：`ivdata/providers/exchange.py` 的 `_trading_days` 应优先调
`Registry.get().fetch("calendar", ...)`，而不是 `range(start, end)` + weekday 判断。

**处理**：

```bash
$PY -c "
import sys; sys.path.insert(0,'.')
from ivdata.providers.exchange import SseCalendar
c=SseCalendar().fetch_calendar('20260901','20261031')
print([r['cal_date'] for r in c if r['is_open']][-8:])
"
```

### 5.5 PCR 与 Tushare 差很多（某一天）

**先看是不是到期日**。到期日（每月第四个周三）交易所报的是**结算后**持仓量，
Tushare 报**收盘**持仓量，2026-09-23 实测差 0.577×，成交量与成交额完全一致。
这是口径差异，不是 bug，已在 `exchange.py` 记为 `KNOWN_OI_DIVERGENCE`。

非到期日偏差 >10% 才算异常，按 5.3 的方式单跑一天对比。

### 5.6 深市 ETF 份额取不到

深市（159915）份额主源是深交所 `CATALOGID=1105` 的「当前规模」快照。
它**只有当日值、没有历史**，且做了按主机的突发限流。先分清是哪种情况：

**a) 日志里是 `深交所份额快照（未知）未覆盖请求窗口`，且耗时约 10 秒**
说明深交所把本机 IP 掐了（WAF）。症状：连 `https://www.szse.cn/` 都打不开，
`RemoteDisconnected`；TCP 能连、TLS 也能握手，但 HTTP 请求被直接掐掉。
**不要立刻重试**，越试封得越久（2026-10-20 实测：连续测试十几发后封了 1 小时以上）。
等它自愈。此时当日那一行份额会缺失（不自动回落 Tushare），先记为缺口；
下次运行由深交所「基金规模」区间报表（`szse_etf_share_range`，一次可查 6 个月）
自动补齐。若区间报表同时被限流，缺口留到配额恢复后自动补，报告仍可出。

顺带一提，深交所的限流**不是 QPS 限流**，是"短时间总请求数"限流，所以把 QPS
压到 1 并不够——真正的减法是少发请求，这也是 `sync_pcr` 把回溯窗口收到
「库里最后一天前 1 天 ~ asof」的原因：日常只缺 1 天新数据，深市通常只发 1~2 发。

**b) 抓到的值与上一交易日完全相同，日志出现「疑似未刷新，换源重取」**
说明深交所还没把 `dqgm` 刷到 ASOF 日。这是设计内的兜底：五只 ETF 近 900 个
交易日里份额与前一日一字不差的只有 0.2%，所以「没变」基本等于「没更新」。

**c) 报告里创业板指份额停在旧日期**
多半是当天 `run_daily.py` 在深交所被封期间跑的。下次运行会自动检测缺口，
用区间报表补上（日志里出现「缺口回补 +N 日」）；也可手动重跑一次。

> 深市其他 ETF（159919 / 159922）与 588080 不进日常取数（`ETF_ALL` 里的备用项，
> 需 `--with-extra-etf` 才取）；附录删除后报告已不再引用它们的份额，
> 只有期权 PCR 仍按主 ETF 标的映射取数。

### 5.7 10Y 国债补齐失败

`sync_bond10y` 是**非致命**步骤，失败只告警。此时：

- `gen2.py` 取 10Y 的顺序是「`asof` 当日 → 序列里最近一日 → `manual_inputs.bond10y`（已废弃，通常没有）」，
  所以 ERP 读数仍可用，只是末点可能停在前一交易日；
- ERP 历史线会滞后。等东财接口恢复后重跑 `--fetch-only` 即可。

确认来源：

```bash
$PY -c "
import json
d=json.load(open('data/yield10y_history.json',encoding='utf-8'))
ks=sorted(d); print('末5:', [(k,d[k]) for k in ks[-5:]])
"
```

### 5.8 网络请求被拒（权限弹窗）

某些域（`push2.eastmoney.com`、`api.waditu.com`）在本机需要授权。
若被拒且提示"不要再重试"，**跳过该域**，靠其他 provider 降级完成，
不要构造等价替代请求。

---

## 六、验收清单（改动后必须过）

每次改动取数逻辑或 provider 后，按这个清单验证：

```bash
# 1. 正常跑一次（全程零 Tushare，Tushare 默认禁用）
$PY run_daily.py

# 1b. 确认报告指纹与改动前一致（版式不许变）
md5sum reports/index_val_report_<ASOF>.html

# 1c. 看本次实际用了哪些源、有没有降级
$PY -c "
import json
p=json.load(open('work/provenance.json',encoding='utf-8'))
used={}
for r in p['records']:
    if r['ok']: used.setdefault(r['domain'],set()).add(r['provider'])
for d,s in sorted(used.items()): print('%-12s %s'%(d, ', '.join(sorted(s))))
print('Tushare 记录:', [ (r['domain'],r['ok']) for r in p['records'] if 'tushare' in r['provider'] ])
"

# 2. 结构一致性（与上一版报告对比）
$PY -c "
import os
for p in ['reports/index_val_report_20261016.html','reports/index_val_report_20261019.html']:
    h=open(p,encoding='utf-8').read()
    # ⚠ 必须用**前缀**计数（'<td'），才能同时抓到 '<td>' 和 '<td class=...>'
    print('%-42s %7d line=%d ' % (os.path.basename(p), len(h), h.count(chr(10))),
          ' '.join('%s=%d' % (t, h.count('<'+t)) for t in
                   ['table','tr','td','th','div','script']))
"

# 3. 内联 JS 语法
$PY -c "
import re
h=open('reports/index_val_report_<日期>.html',encoding='utf-8').read()
b=re.findall(r'<script(?![^>]*src=)[^>]*>(.*?)</script>', h, re.S)
open('work/_inline_check.js','w',encoding='utf-8').write('\n;\n'.join(b))
"
node --check work/_inline_check.js

# 4. 交叉校验
$PY tools/verify_sources.py --asof <日期>
```

要求：
- 报告字节数变化 <1%；
- `table=8 tr=9 td=59 th=72 div=80 script=2` 全部不变，行数 645 不变；
- `const DATA` 顶层 19 个键完全一致；
- ERP `series` 点数逐日 +1（例如 20261019 为 2863、20261020 为 2864）。

> ⚠ **计数口径必须用前缀**（`h.count('<td')`），不能写 `h.count('<td>')`。
> 模板里大量标签带属性（`<td class="up">`、`<div class="card">`），
> 裸标签计数会漏掉它们——`<div>` 裸计数恒为 0、`<div ` 只有 80 但 `<div` 也是 80，
> `<td>` 裸计数 25 而 `<td` 是 59。用错口径会得出「版式变了」的假警报。
>
> 本机**无头浏览器截图不可用**，所以版式验证只能靠上面这种静态计数 +
> `node --check` 校验内联 JS，不能靠截图肉眼比对。

---

## 七、旧管线（备用）

`scripts/run_weekly.py` 是 v1 入口（全 Tushare，10 步）。
**仅在人工指令下使用**——定时任务不会自动切到它（见 DAILY.md 四），因为它会把 Tushare 数值
写进 `data/raw.json` 历史库。

```bash
cd scripts
ASOF=20261019 $PY run_weekly.py
```

两套入口对比：

| | `run_daily.py`（v2，日常） | `scripts/run_weekly.py`（v1，备用） |
|---|---|---|
| 取数来源 | 新浪 / 东财 / 交易所官方 | Tushare |
| Tushare 调用 | 0 次（深市份额缺口由区间报表回补） | ~15 次/天，1 万+ 行 |
| 降级能力 | 每域有优先级链，自动降级 | 无，任一接口挂就断 |
| 溯源 | `work/provenance.json` | 无 |
| 产出 | **完全一致** | **完全一致** |

两者加工步骤完全相同，可交替使用，数据文件格式一致。
