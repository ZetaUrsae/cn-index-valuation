# -*- coding: utf-8 -*-
"""把项目根加入 sys.path —— 让 `scripts/` 下的脚本能 `import ivdata`。

为什么需要：这些脚本既可能被 `run_daily.py` 以子进程方式调用
（`python scripts/tech.py`），也可能手工 `cd scripts && python tech.py`。
两种情况下 sys.path[0] 都是 scripts 目录，项目根不在其中。

用法（每个脚本首行）：

    import _bootstrap  # noqa: F401  —— 必须先于 `from ivdata... import` 执行
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)
