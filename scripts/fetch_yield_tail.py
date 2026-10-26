# -*- coding: utf-8 -*-
"""增量更新 10年期国债收益率历史（yield10y_history.json）的尾部。

数据源：东方财富数据中心 RPTA_WEB_TREASURYYIELD（数据源自中国债券信息网/中债）。
只拉取最近约 400 个交易日补齐缺口，与本地已有序列合并后回写。
本步<b>非致命</b>：任何异常都只告警并以 exit 0 退出，避免阻塞整条周度管线。
"""
import json
import os
import sys
import datetime

BASE = os.path.dirname(os.path.abspath(__file__))
PATH = os.path.join(os.path.dirname(BASE), "data", "yield10y_history.json")
TOKEN = "894050c76af8597a853f5b408b759f5d"


def main():
    try:
        import requests
    except Exception as e:
        print("  !! 跳过 10Y 更新（无 requests 模块）：", e)
        return

    # 载入已有序列
    hist = {}
    if os.path.exists(PATH):
        try:
            hist = json.load(open(PATH, encoding="utf-8"))
        except Exception:
            hist = {}

    try:
        UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                            "Chrome/120.0.0.0 Safari/537.36",
              "Referer": "https://data.eastmoney.com/cjsj/zmgzsyl.html"}
        # 增量：只按「库里最后一天到现在」的跨度取，不再固定拉 400 条。
        # 接口不支持按区间过滤，只能取最近 N 条再本地筛，所以 N 必须算准。
        last = max(hist) if hist else ""
        try:
            need = (datetime.date.today()
                    - datetime.date.fromisoformat(last)).days + 10 if last else 90
        except ValueError:
            need = 90
        page_size = str(min(max(need, 30), 400))
        r = requests.get(
            "https://datacenter-web.eastmoney.com/api/data/v1/get",
            params={"reportName": "RPTA_WEB_TREASURYYIELD", "columns": "ALL",
                    "sortColumns": "SOLAR_DATE", "sortTypes": "-1",
                    "token": TOKEN, "pageNumber": "1", "pageSize": page_size},
            headers=UA, timeout=40)
        js = r.json()
        rows = (js.get("result") or {}).get("data") or []
        if not rows:
            print("  !! 10Y 接口返回空，保留原缓存")
            return
        # 只写缺失日；最近 3 天允许覆盖（当日值可能晚间补发或修正）。
        # 已有历史一律不动——这样即使误设大窗口，也不会改写已定稿的历史序列。
        keep_after = (datetime.date.today() - datetime.timedelta(days=3)).isoformat()
        added = skipped = 0
        for x in rows:
            d = (x.get("SOLAR_DATE") or "")[:10]
            v = x.get("EMM00166466")
            if not (d and v is not None):
                continue
            if d in hist and d < keep_after:
                skipped += 1
                continue
            if d not in hist:
                added += 1
            hist[d] = round(float(v), 4)
        json.dump(hist, open(PATH, "w", encoding="utf-8"), ensure_ascii=False)
        ks = sorted(hist)
        print("  10Y 尾部更新完成：新增 %d 条、沿用已有 %d 条，序列 %s ~ %s（共 %d 个交易日）"
              % (added, skipped, ks[0], ks[-1], len(hist)))
    except Exception as e:
        print("  !! 10Y 更新失败（保留原缓存）：", type(e).__name__, str(e)[:160])


if __name__ == "__main__":
    main()
    sys.exit(0)
