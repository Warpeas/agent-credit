"""Windows 控制台的中文输出：强制 UTF-8。

背景：Windows 控制台默认走 GBK，脚本里带中文的 print 会显示成乱码，
重定向到文件或管道时更明显（本项目日志全是中文，乱码等于信息全丢）。
`credit.py` 与 `trace.init()` 早就各自处理过，但直接 `python -m agent_credit.xxx`
会绕过它们——所以每个可独立运行的模块在 `__main__` 里都调一次本函数。

只影响输出编码，不改数据、不改文件。
"""
from __future__ import annotations

import sys


def use_utf8() -> None:
    """把 stdout/stderr 切到 UTF-8（老 Python 没有 reconfigure 就静默跳过）。"""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
        except Exception:
            pass
