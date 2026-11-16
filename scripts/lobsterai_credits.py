#!/usr/bin/env python3
"""LobsterAI 积分明细 CLI 启动器（给 catalog 的 status/credits_command 用）。

直接 `python -m agent_credit.lobsterai_credits` 依赖 PYTHONPATH；计划任务里的
嵌入式 Python 可能忽略该环境变量，所以这里显式把仓库根塞进 sys.path。
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agent_credit.lobsterai_credits import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())
