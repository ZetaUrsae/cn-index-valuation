# -*- coding: utf-8 -*-
"""技术面扩展：给 tech.json 补 60 日 K 线（供报告技术面迷你图用）。

历史上曾计划给三个次级期权标的（159919/159922/588080）
填 etf_name/etf_mgr，但 gen2.py 从不读这两个字段——报告里的次级 ETF 名称
来自 gen2.py 的 OPTALT_NAME 硬编码字典。v2.0 起删除该调用，本脚本零外部请求。
"""
import json

import _bootstrap  # noqa: F401  （把项目根加入 sys.path）
from ivdata.paths import BASE  # noqa: E402

# extend tech with 60-day candles
raw = json.load(open(BASE + "data/raw.json", encoding="utf-8"))
tech = json.load(open(BASE + "work/tech.json", encoding="utf-8"))
order = ["000300.SH", "000016.SH", "000905.SH", "399006.SZ", "000688.SH"]
for c in order:
    d = sorted(raw[c]["daily"], key=lambda r: r["trade_date"])[-60:]
    tech[c]["candles60"] = [[round(x["open"], 2), round(x["close"], 2),
                             round(x["low"], 2), round(x["high"], 2)] for x in d]
    tech[c]["dates60"] = [x["trade_date"][4:] for x in d]
    tech[c]["vol60"] = [round((x.get("vol") or 0) / 1e4, 1) for x in d]
json.dump(tech, open(BASE + "work/tech.json", "w", encoding="utf-8"),
          ensure_ascii=False, indent=1)
print("tech extended; sample dates:", tech["000300.SH"]["dates60"][-3:],
      "candles:", tech["000300.SH"]["candles60"][-2:])
