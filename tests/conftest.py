# -*- coding: utf-8 -*-
"""让测试能直接 import 仓库内模块（ivdata / scripts / tools / run_daily）。"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

for path in (ROOT, os.path.join(ROOT, "scripts"), os.path.join(ROOT, "tools")):
    if path not in sys.path:
        sys.path.insert(0, path)
