# -*- coding: utf-8 -*-
"""ivdata.store —— 增量历史库。

所有域共用一套「读取 → 增量补 → 按日期合并去重 → 落盘」逻辑，
避免旧代码里 fetch.py / fetch3.py / fetch2b.py 各写一份 merge 的重复问题。

文件格式（JSON）：
    {
      "_meta": {"updated": "2026-10-20T21:30:00", "asof": "20261019", "source": "..."},
      "series": {
          "000300.SH": {"trade_date": [...], "close": [...], ...}
      }
    }
内部按列存（columnar）而不是按行存，文件体积可降 40%~60%。

也支持 CSV 形式的大表（pcr_raw，14 万行）：走 store.load_csv / append_csv。
"""
from __future__ import annotations

import csv
import datetime
import json
import os
from typing import Any, Dict, Iterable, List, Optional

from .config import DATA


class Store:
    """单个 JSON 历史库文件的读写封装。"""

    def __init__(self, filename: str, base: str = DATA):
        self.path = os.path.join(base, filename)
        self.data: Dict[str, Any] = {}
        self._load()

    # -------------------------------------------------- 读写
    def _load(self) -> None:
        if not os.path.exists(self.path):
            self.data = {"_meta": {}, "series": {}}
            return
        try:
            with open(self.path, encoding="utf-8") as f:
                d = json.load(f)
            if isinstance(d, dict) and "series" in d:
                self.data = d
            elif isinstance(d, dict) and d and all(isinstance(v, dict) for v in d.values()):
                # 兼容旧格式：{code: {"basic": [...], "daily": [...]}} 由调用方自行迁移
                self.data = {"_meta": {"legacy": True}, "_legacy": d, "series": {}}
            else:
                self.data = {"_meta": {}, "series": {}}
        except Exception:
            self.data = {"_meta": {}, "series": {}}

    def save(self, source: str = "", asof: str = "") -> None:
        self.data.setdefault("_meta", {})
        self.data["_meta"].update({
            "updated": datetime.datetime.now().isoformat(timespec="seconds"),
            "asof": asof,
            "source": source,
        })
        self.data["_meta"].pop("legacy", None)
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(self.data, f, ensure_ascii=False, separators=(",", ":"))
        os.replace(tmp, self.path)          # 原子替换，避免写一半崩溃损坏历史库

    # -------------------------------------------------- 行 <-> 列
    def rows(self, key: str) -> List[Dict[str, Any]]:
        """按行取出某条序列。"""
        col = self.data.get("series", {}).get(key)
        if not col:
            return []
        dates = col.get("trade_date") or []
        if not dates:
            return []
        keys = [k for k in col.keys() if k != "trade_date"]
        return [{**{"trade_date": d}, **{k: col[k][i] for k in keys}}
                for i, d in enumerate(dates)]

    def keys(self) -> List[str]:
        return list(self.data.get("series", {}).keys())

    def put_rows(self, key: str, rows: Iterable[Dict[str, Any]],
                 merge: bool = True, exclude_fields: Optional[set] = None) -> int:
        """写入若干行；merge=True 时与旧数据按 trade_date 合并，新值优先。"""
        new = [r for r in (rows or []) if r.get("trade_date")]
        if exclude_fields:
            new = [{k: v for k, v in r.items() if k not in exclude_fields} for r in new]
        if not new:
            return len(self.rows(key))

        if merge:
            old = self.rows(key)
            if old:
                cut = min(r["trade_date"] for r in new)
                old = [r for r in old if r["trade_date"] < cut]
            allrows = old + new
        else:
            allrows = new

        # 同日期去重，保留最后出现的（新值）
        dedup: Dict[str, Dict[str, Any]] = {}
        for r in allrows:
            d = str(r["trade_date"])
            if d in dedup:
                dedup[d].update({k: v for k, v in r.items() if v is not None})
            else:
                dedup[d] = dict(r)
        ordered = [dedup[d] for d in sorted(dedup)]

        # 列式存储
        fields = []
        for r in ordered:
            for k in r:
                if k not in fields:
                    fields.append(k)
        col: Dict[str, List[Any]] = {f: [] for f in fields}
        for r in ordered:
            for f in fields:
                col[f].append(r.get(f))
        self.data.setdefault("series", {})[key] = col
        return len(ordered)

    def last_date(self, key: str) -> Optional[str]:
        col = self.data.get("series", {}).get(key) or {}
        ds = col.get("trade_date") or []
        return str(ds[-1]) if ds else None

    def first_date(self, key: str) -> Optional[str]:
        col = self.data.get("series", {}).get(key) or {}
        ds = col.get("trade_date") or []
        return str(ds[0]) if ds else None


class CsvStore:
    """大表 CSV 的增量读写（用于 pcr_raw 这类逐日多标的的表）。"""

    def __init__(self, filename: str, base: str = DATA):
        self.path = os.path.join(base, filename)

    def load(self) -> List[Dict[str, str]]:
        if not os.path.exists(self.path):
            return []
        with open(self.path, encoding="utf-8-sig", newline="") as f:
            return list(csv.DictReader(f))

    def last_date(self) -> Optional[str]:
        rows = self.load()
        if not rows:
            return None
        return max(str(r.get("date", "")) for r in rows)

    def upsert(self, new_rows: List[Dict[str, Any]], key_fields=("date", "oc")) -> int:
        """按 (date, oc) 合并写入，新值覆盖旧值。"""
        old = self.load()
        if not old and not new_rows:
            return 0
        merged: Dict[tuple, Dict[str, Any]] = {}
        for r in old:
            merged[tuple(str(r.get(k, "")) for k in key_fields)] = r
        for r in new_rows:
            k = tuple(str(r.get(f, "")) for f in key_fields)
            prev = merged.get(k, {})
            prev.update({kk: vv for kk, vv in r.items() if vv is not None})
            merged[k] = prev

        # 稳定字段顺序：先旧表的表头，再追加新字段
        fields: List[str] = []
        for r in old:
            for k in r:
                if k not in fields:
                    fields.append(k)
        for r in new_rows:
            for k in r:
                if k not in fields:
                    fields.append(k)

        out = [merged[k] for k in sorted(merged)]
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8-sig", newline="") as f:
            w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
            w.writeheader()
            for r in out:
                w.writerow(r)
        os.replace(tmp, self.path)
        return len(out)
