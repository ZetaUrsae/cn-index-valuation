# -*- coding: utf-8 -*-
"""生成发布用的静态站点目录 site/（v2.7.1：接入云服务）。

产物
----
site/index.html                 门户：左侧日期列表 + 右侧 iframe 显示所选日报
site/reports/*.html             最近 N 期正式报告（含 echarts 本地化改写）
site/assets/echarts.min.js      echarts 本地副本（有则把 CDN 引用改成本地）
site/assets/cloud-sdk.js        云服务 SDK 本地副本（页面用它读云端报告列表）

云服务
------
- 报告清单存在云端表 `reports`（report_date / path / title / views / created_at），
  页面用 SDK 读取并按日期倒序展示；读不到（离线、Origin 不符、配额）时自动回退到
  构建时写死在页面里的快照列表，页面顶部会标明「云端同步 / 离线快照」。
- 配置见 tools/site_cloud.json（endpoint / publishableKey 属公开端配置，非密钥）。
- 新增报告后需要让云端知道：`$PY tools/build_site.py --emit-sql` 打印幂等 INSERT，
  交给 MCP 的 exec_sql 执行即可（本地构建不会自行写库）。

规则
----
- 只收正式文件名 `index_val_report_YYYYMMDD.html`，自动排除 `_test` / `_band` / archive；
- 保留策略（v2.7.3 起）：**每月第一个交易日那期 + 最近 10 期**，并集去重（约 22 期/年上限），
  `--recent N` 调近期数、`--no-monthly` 关闭月初锚点；
- 幂等：每次重建会清空 site/reports 后重新拷贝，不影响原始报告；
- 不发布任何东西，只生成本地目录。
"""
import argparse
import json
import os
import re
import shutil

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REPORTS = os.path.join(BASE, "reports")
SITE = os.path.join(BASE, "site")
CONF = os.path.join(BASE, "tools", "site_cloud.json")
ECHARTS_CDN = "https://cdn.jsdelivr.net/npm/echarts@5/dist/echarts.min.js"
SDK_CDN = "https://cdn.jsdelivr.net/npm/@tencent-ai/workbuddy-cloud-sdk@dev/lib/index.global.js"
PAT = re.compile(r"^index_val_report_(\d{8})\.html$")


def collect(limit=30):
    """全部正式报告（按日期倒序），limit<=0 表示不限。"""
    items = []
    for fn in os.listdir(REPORTS):
        m = PAT.match(fn)
        if not m:
            continue
        d = m.group(1)
        items.append(("%s-%s-%s" % (d[:4], d[4:6], d[6:]), fn))
    items.sort(reverse=True)
    return items if limit <= 0 else items[:limit]


def select_reports(items, recent=10, monthly=True):
    """保留策略（2026-11-11 用户定）：每月第一个交易日那期 + 最近 N 期，并集去重。

    - 「月初锚点」= 按 YYYY-MM 分组后该月最早的一期（不依赖交易日历，
      天然对齐报告的数据日期）；
    - 月初锚点必然与「最近 N 期」重叠，去重即可；
    - 某月整月没跑则自然缺该锚点，不补。
    """
    keep = {}
    for iso, fn in items[:recent]:
        keep[iso] = fn
    if monthly:
        seen = {}
        for iso, fn in sorted(items):          # 升序 → 每月第一条即最早
            seen.setdefault(iso[:7], (iso, fn))
        for iso, fn in seen.values():
            keep[iso] = fn
    return sorted(keep.items(), reverse=True)


def _download(url, dst, min_size):
    """已存在且体积合理则跳过；失败返回 False（调用方保留 CDN 引用）。"""
    if os.path.exists(dst) and os.path.getsize(dst) >= min_size:
        return True
    try:
        import requests
        r = requests.get(url, timeout=30)
        r.raise_for_status()
        if len(r.content) < min_size:
            raise ValueError("体积异常 %d" % len(r.content))
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        open(dst, "wb").write(r.content)
        print("  [site] %s 已本地化 %.0f KB" % (os.path.basename(dst), len(r.content) / 1024))
        return True
    except Exception as e:                                # noqa: BLE001
        print("  !! [site] %s 下载失败（保留 CDN 引用）：%s"
              % (os.path.basename(dst), str(e)[:90]))
        return False


def copy_reports(items, local_echarts):
    dst_dir = os.path.join(SITE, "reports")
    if os.path.isdir(dst_dir):
        shutil.rmtree(dst_dir)
    os.makedirs(dst_dir, exist_ok=True)
    total = 0
    for iso, fn in items:
        txt = open(os.path.join(REPORTS, fn), encoding="utf-8").read()
        if local_echarts:
            txt = txt.replace(ECHARTS_CDN, "../assets/echarts.min.js")
        dst = os.path.join(dst_dir, fn)
        open(dst, "w", encoding="utf-8").write(txt)
        total += os.path.getsize(dst)
    print("  [site] 拷贝 %d 期，共 %.1f MB" % (len(items), total / 1048576))


TPL = """<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>宽基指数 · 多维度分析图</title>
<style>
  :root{--navy:#0f2744;--navy2:#173f74;--gold:#c9a227;--ink:#20334c;--muted:#7b8a9e;
        --line:#e3e9f2;--bg:#eef2f7;--card:#fff;--ok:#0f8a52;--off:#8b98a8;}
  *{box-sizing:border-box;}
  html,body{height:100%;margin:0;}
  body{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI","PingFang SC",
       "Microsoft YaHei",sans-serif;background:var(--bg);color:var(--ink);}
  .app{display:grid;grid-template-columns:236px 1fr;height:100vh;height:100dvh;}
  aside{background:linear-gradient(180deg,#123257,#0d2340);color:#dbe6f5;
        display:flex;flex-direction:column;min-height:0;}
  .brand{padding:20px 18px 14px;border-bottom:1px solid rgba(255,255,255,.09);}
  .brand h1{margin:0;font-size:16px;letter-spacing:.4px;color:#fff;}
  .brand p{margin:6px 0 0;font-size:11.5px;color:#9db3cf;letter-spacing:.3px;}
  .brand .gold{display:inline-block;margin-top:10px;padding:2px 8px;border:1px solid rgba(201,162,39,.55);
        border-radius:3px;font-size:10.5px;color:var(--gold);letter-spacing:1px;}
  .list{flex:1;overflow-y:auto;padding:8px 0;}
  .it{display:flex;align-items:center;justify-content:space-between;gap:8px;
      padding:9px 18px;font-size:13px;color:#c7d7ea;cursor:pointer;
      border-left:3px solid transparent;transition:background .15s,color .15s;}
  .it:hover{background:rgba(255,255,255,.06);color:#fff;}
  .it.on{background:rgba(255,255,255,.10);color:#fff;border-left-color:var(--gold);}
  .it .d{font-variant-numeric:tabular-nums;letter-spacing:.2px;}
  .it .tag{font-size:10px;padding:1px 6px;border-radius:8px;background:rgba(201,162,39,.18);
           color:var(--gold);border:1px solid rgba(201,162,39,.4);}
  .foot{padding:10px 18px 14px;border-top:1px solid rgba(255,255,255,.09);
        font-size:11px;color:#8ea6c3;}
  main{display:flex;flex-direction:column;min-width:0;min-height:0;}
  .bar{display:flex;align-items:center;justify-content:space-between;gap:12px;
       padding:10px 16px;background:var(--card);border-bottom:1px solid var(--line);}
  .bar .t{font-size:13px;color:var(--muted);}
  .bar .t b{color:var(--ink);font-variant-numeric:tabular-nums;}
  .bar .r{display:flex;align-items:center;gap:14px;}
  .badge{display:inline-flex;align-items:center;gap:5px;font-size:11.5px;color:var(--muted);}
  .badge i{width:7px;height:7px;border-radius:50%;background:var(--off);display:inline-block;}
  .badge.on i{background:var(--ok);}
  .bar a{font-size:12.5px;color:var(--navy2);text-decoration:none;white-space:nowrap;}
  .bar a:hover{text-decoration:underline;}
  iframe{flex:1;width:100%;border:0;background:var(--card);}
  @media(max-width:820px){
    .app{grid-template-columns:1fr;grid-template-rows:auto 1fr;}
    .list{display:flex;overflow-x:auto;overflow-y:hidden;padding:6px 8px;}
    .it{border-left:0;border-bottom:3px solid transparent;white-space:nowrap;padding:8px 10px;}
    .it.on{border-left:0;border-bottom-color:var(--gold);}
    .foot{display:none;}
    .brand{padding:12px 14px;display:flex;align-items:baseline;gap:10px;flex-wrap:wrap;}
    .brand .gold{display:none;}
  }
</style>
</head>
<body>
<div class="app">
  <aside>
    <div class="brand">
      <h1>宽基指数 · 多维度分析图</h1>
      <p>日报归档 · 估值 / 资金 / 情绪 / 技术</p>
      <span class="gold">DAILY REPORT</span>
    </div>
    <div class="list" id="list"></div>
    <div class="foot">共 <b id="cnt">0</b> 期 · 最新 <b id="last">—</b></div>
  </aside>
  <main>
    <div class="bar">
      <div class="t">数据日期 <b id="cur">—</b></div>
      <div class="r">
        <span class="badge" id="sync"><i></i><span id="syncTxt">连接中…</span></span>
        <a id="open" href="#" target="_blank" rel="noopener">新窗口打开 ↗</a>
      </div>
    </div>
    <iframe id="frame" src="" title="报告"></iframe>
  </main>
</div>
<script src="assets/cloud-sdk.js"></script>
<script>
var SNAPSHOT = __ITEMS__;
var CLOUD = __CLOUD__;

var list = document.getElementById('list');
var frame = document.getElementById('frame');
var cur = document.getElementById('cur');
var open = document.getElementById('open');
var items = [];
var picked = 0;

function setSync(ok, text) {
  document.getElementById('sync').className = 'badge' + (ok ? ' on' : '');
  document.getElementById('syncTxt').textContent = text;
}

function pick(i) {
  if (!items.length) return;
  picked = i;
  var it = items[i];
  frame.src = it.f;
  cur.textContent = it.d;
  open.href = it.f;
  var nodes = list.querySelectorAll('.it');
  for (var k = 0; k < nodes.length; k++) nodes[k].className = 'it' + (k === i ? ' on' : '');
  if (history.replaceState) history.replaceState(null, '', '#' + it.d);
}

function render() {
  list.innerHTML = '';
  items.forEach(function (it, i) {
    var el = document.createElement('div');
    el.className = 'it';
    el.innerHTML = '<span class="d">' + it.d + '</span>' +
                   (i === 0 ? '<span class="tag">最新</span>' : '');
    el.onclick = function () { pick(i); };
    list.appendChild(el);
  });
  document.getElementById('cnt').textContent = items.length;
  document.getElementById('last').textContent = items.length ? items[0].d : '—';
  var start = 0;
  if (location.hash) {
    var h = location.hash.slice(1);
    for (var j = 0; j < items.length; j++) if (items[j].d === h) { start = j; break; }
  }
  pick(start);
}

async function fromCloud() {
  if (!CLOUD || !window.WorkBuddyCloud) return null;
  var cloud = WorkBuddyCloud.createWorkBuddyCloud({
    endpoint: CLOUD.endpoint,
    oauthRelayBaseUrl: CLOUD.oauthRelayBaseUrl,
    publishableKey: CLOUD.publishableKey
  });
  var res = await cloud.database.from(CLOUD.table || 'reports')
    .select('report_date,path,title')
    .eq('archived', false)
    .order('report_date', { ascending: false })
    .limit(60);
  if (res.error || !res.data || !res.data.length) return null;
  return res.data.map(function (r) {
    return { d: String(r.report_date).slice(0, 10), f: r.path, t: r.title };
  });
}

(async function () {
  try {
    var live = await fromCloud();
    if (live) {
      items = live;
      setSync(true, '云端同步');
    } else {
      items = SNAPSHOT;
      setSync(false, '离线快照');
    }
  } catch (e) {
    items = SNAPSHOT;
    setSync(false, '离线快照');
  }
  render();
})();
</script>
</body>
</html>
"""


def write_index(items, cloud):
    payload = ",\n  ".join(
        '{"d":"%s","f":"reports/%s"}' % (iso, fn) for iso, fn in items)
    html = TPL.replace("__ITEMS__", "[\n  %s\n]" % payload)
    html = html.replace("__CLOUD__", json.dumps(cloud, ensure_ascii=False))
    open(os.path.join(SITE, "index.html"), "w", encoding="utf-8").write(html)
    print("  [site] index.html 已生成（%d 期快照 + 云端读取）" % len(items))


def emit_sql(all_items, selected):
    """打印云端 reports 表的幂等同步语句。

    同时维护 archived：入选站点的 false、未入选的 true —— 这样 DB 保留全量索引
    （以后想回看或重新发布都能查到），首页只展示 archived=false，列表与文件始终一致。
    """
    keep = {iso for iso, _ in selected}
    rows = []
    for iso, fn in all_items:
        rows.append("('%s','reports/%s','宽基指数日报 %s',%s)"
                    % (iso, fn, iso, "false" if iso in keep else "true"))
    print("INSERT INTO reports (report_date, path, title, archived) VALUES\n  "
          + ",\n  ".join(rows) +
          "\nON CONFLICT (report_date) DO UPDATE SET"
          "\n  path = EXCLUDED.path, title = EXCLUDED.title, archived = EXCLUDED.archived;")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--recent", type=int, default=10, help="保留最近多少期（默认 10）")
    ap.add_argument("--no-monthly", action="store_true", help="不保留每月第一个交易日锚点")
    ap.add_argument("--emit-sql", action="store_true",
                    help="只打印云端 reports 表的幂等同步语句，不构建目录")
    args = ap.parse_args()

    everything = collect(0)
    if not everything:
        raise SystemExit("!! reports/ 下没有正式报告（index_val_report_YYYYMMDD.html）")
    items = select_reports(everything, recent=args.recent,
                           monthly=not args.no_monthly)

    if args.emit_sql:
        emit_sql(everything, items)
        return

    os.makedirs(SITE, exist_ok=True)
    ech = _download(ECHARTS_CDN, os.path.join(SITE, "assets", "echarts.min.js"), 500_000)
    _download(SDK_CDN, os.path.join(SITE, "assets", "cloud-sdk.js"), 20_000)
    cloud = {}
    if os.path.exists(CONF):
        cloud = json.load(open(CONF, encoding="utf-8"))
    copy_reports(items, bool(ech))
    write_index(items, cloud)
    print("  site 完成：%s（打开 index.html 预览）" % SITE)


if __name__ == "__main__":
    main()
