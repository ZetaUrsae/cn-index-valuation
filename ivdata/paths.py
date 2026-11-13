# -*- coding: utf-8 -*-
"""ivdata.paths —— 项目内所有路径的**唯一定义处**。

动因（2026-11-13）：此前 `BASE` 在 5 个脚本里各写一份，出现过两类事故——
一处写死本机绝对路径 `D:/QClaw/...`（云端运行直接 FileNotFoundError），
一处推导时漏了尾部斜杠（`BASE + "data/raw.json"` 拼成 `…index_valuedata/raw.json`），
两者都是本地跑得好好的、换机器才暴露。现在只在这里推导一次。

约定
----
* ``ROOT``  —— 项目根，正斜杠，**无**尾部斜杠（拼接请用 ``p()`` 或 ``BASE``）
* ``BASE``  —— 同 ROOT 但**带**尾部斜杠，兼容既有 ``BASE + "data/x.json"`` 写法
* ``DATA / WORK / REPORTS / SCRIPTS / ASSETS`` —— 常用子目录（无尾部斜杠）

⚠ 只覆盖「相对项目根」的路径。脚本自身所在目录（如 `scripts/` 下的取数脚本
读同目录的缓存文件）不属于本模块语义，那类场景用 ``SCRIPTS`` 或直接 __file__。
"""
from __future__ import annotations

import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__))).replace("\\", "/")
BASE = ROOT + "/"

DATA = ROOT + "/data"
WORK = ROOT + "/work"
REPORTS = ROOT + "/reports"
SCRIPTS = ROOT + "/scripts"
ASSETS = ROOT + "/assets"


def p(*parts: str) -> str:
    """拼路径：`p("data", "raw.json")` → `<root>/data/raw.json`。"""
    return "/".join([ROOT] + [str(x).strip("/") for x in parts if x])
