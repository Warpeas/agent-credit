#!/usr/bin/env python3
import sys

from agent_credit.cli import main

if __name__ == "__main__":
    # 计划任务里是一个黑框：中文别被 GBK 控制台吞掉，print 也别憋到进程结束才吐出来
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
        except Exception:
            pass
    raise SystemExit(main())
