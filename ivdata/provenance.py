# -*- coding: utf-8 -*-
"""ivdata.provenance —— 取数溯源。

每次运行把「哪个数据域用了哪个源、多少行、耗时、是否降级」写进
work/provenance.json，并在控制台打印一张来源表。报告附录可直接引用。
"""
from __future__ import annotations

import datetime
import json
import os
from typing import Dict, List

from .config import WORK

_PATH = os.path.join(WORK, "provenance.json")


class Provenance:
    def __init__(self):
        self.records: List[Dict] = []
        self.started = datetime.datetime.now().isoformat(timespec="seconds")

    def add(self, rec) -> None:
        d = rec.to_dict() if hasattr(rec, "to_dict") else dict(rec)
        d["ts"] = datetime.datetime.now().isoformat(timespec="seconds")
        self.records.append(d)

    def by_domain(self) -> Dict[str, Dict]:
        out = {}
        for r in self.records:
            if r.get("ok"):
                out.setdefault(r["domain"], r)
        return out

    def report(self) -> str:
        """生成控制台摘要表。"""
        ok = self.by_domain()
        lines = ["数据来源（本次运行）："]
        for dom in sorted(ok):
            r = ok[dom]
            fb = ""
            if r.get("fallback_from"):
                fb = "  [降级自: %s]" % " → ".join(r["fallback_from"])
            lines.append("  %-12s %-20s rows=%-6s %.1fs%s"
                         % (dom, r["provider"], r.get("rows", 0),
                            r.get("elapsed", 0.0), fb))
        fails = [r for r in self.records if not r.get("ok")]
        if fails:
            lines.append("  失败尝试（已降级）：")
            for r in fails:
                lines.append("    %-12s %-20s %s" % (r["domain"], r["provider"],
                                                     (r.get("error") or "")[:90]))
        return "\n".join(lines)

    def save(self, path: str = "") -> str:
        path = path or _PATH
        payload = {"started": self.started,
                   "finished": datetime.datetime.now().isoformat(timespec="seconds"),
                   "records": self.records}
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=1)
        os.replace(tmp, path)
        return path
