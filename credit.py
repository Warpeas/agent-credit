#!/usr/bin/env python3
import os
import sys

# 自举：AutoClaw2 自带的 vendored python 是 ._pth 完全隔离模式，
# 连脚本目录都不进 sys.path（2026-11-10 实测），任何解释器都先显式加上。
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from agent_credit.cli import main

if __name__ == "__main__":
    # 计划任务里是一个黑框：中文别被 GBK 控制台吞掉，print 也别憋到进程结束才吐出来
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
        except Exception:
            pass
    raise SystemExit(main())
