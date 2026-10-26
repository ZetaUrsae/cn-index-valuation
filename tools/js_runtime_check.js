#!/usr/bin/env node
/**
 * js_runtime_check.js —— 报告内联 JS 运行时校验（v2.6.2 起，交付前必跑）。
 *
 * 背景：`node --check`/`new Function` 只能查语法，查不出「gen2 删了某个 DATA 字段、
 * 模板还在读」这类运行时错误（2026-10-21 v2.6.2 实测：fund.series 被删后资金面表
 * 整段崩掉、全部图表不渲染）。本工具用 DOM/echarts 桩把报告里的内联脚本真实跑一遍。
 *
 * 用法：node tools/js_runtime_check.js reports/index_val_report_YYYYMMDD[_TAG].html
 * 退出码：0 = 全部脚本块运行通过；1 = 有运行时错误。
 */
'use strict';
const fs = require('fs');

const file = process.argv[2];
if (!file) { console.error('usage: node js_runtime_check.js <report.html>'); process.exit(1); }
const html = fs.readFileSync(file, 'utf8');

const dm = html.match(/const DATA = ([\s\S]*?);\r?\n/);
if (!dm) { console.error('FAIL: 找不到 const DATA 赋值'); process.exit(1); }
const dataLit = dm[1];

const re = /<script>([\s\S]*?)<\/script>/g;
let m; const blocks = [];
while ((m = re.exec(html))) blocks.push(m[1]);

const el = () => ({
  innerHTML: '', textContent: '', style: {}, value: '',
  appendChild() {}, addEventListener() {},
  querySelectorAll() { return []; },
});
global.document = {
  getElementById: () => el(),
  createElement: () => el(),
  addEventListener() {},
  body: { appendChild() {} },
};
global.window = global;
global.addEventListener = () => {};
global.echarts = {
  init: () => ({ setOption() {}, resize() {}, on() {} }),
  graphic: { LinearGradient: function () {} },
};

let ok = true;
for (let i = 0; i < blocks.length; i++) {
  let src = blocks[i];
  if (src.includes('const DATA =')) {
    src = src.replace(/const DATA = [\s\S]*?;\r?\n/, 'const DATA = ' + dataLit + ';\n');
  }
  try {
    new Function(src)();
    console.log('block ' + (i + 1) + ' RUN OK');
  } catch (e) {
    ok = false;
    console.log('block ' + (i + 1) + ' RUNTIME FAIL: ' + e.message);
    console.log('  ' + String(e.stack || '').split('\n')[1]);
  }
}
console.log(ok ? 'ALL RUNTIME OK' : 'STILL FAILING');
process.exit(ok ? 0 : 1);
