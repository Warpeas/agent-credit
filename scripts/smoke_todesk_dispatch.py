r"""ToDesk 派单冒烟：临时关掉抢屏保护，强制只走 todesk 这一个 provider。

为什么需要脚本而不是留一份 providers 配置：差别只有 require_idle_s / 超时两三个值，
留文件迟早和主配置漂移；脚本每次现生成，主配置改了也不会不一致。

它会做什么（会打扰人，注意）：
  1. 把焦点抢到 ToDesk AI 主窗口（官方快捷键 Alt+Space）；
  2. 新建会话（Ctrl+Alt+N），把任务粘贴进去回车；
  3. 等客户端把结果写到 data/todesk-taskbox/*.out.md；
  4. **真实消耗积分**（按积分计费，一单几十到几百）。

前提：客户端在跑、主窗口没关到托盘、设置中心已把「新建与修改」放行（否则卡在授权弹窗，最后 124）。

用法（仓库根，用装了依赖的普通 CPython，别用 agent-runtime 那个 safe-path 的）：
    python scripts\smoke_todesk_dispatch.py
    python scripts\smoke_todesk_dispatch.py --task "把这三个 bug 排个优先级" --timeout 300
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

TEMPLATE = """\
providers:
  todesk:
    enabled: true
    priority: 90
    capabilities:
      - text
    exe: "{exe}"
    taskbox: "{taskbox}"
    wake_hotkey: alt+space
    new_session_hotkey: ctrl+alt+n
    answer_timeout_s: {timeout}
    require_idle_s: 0
    poll_interval_s: 1.0
"""


def main() -> int:
    parser = argparse.ArgumentParser(description="ToDesk 派单冒烟（会抢焦点、消耗积分）")
    parser.add_argument("--task", default="回复两个字：OK", help="任务正文")
    parser.add_argument("--capability", default="text", help="能力标签，默认 text")
    parser.add_argument("--timeout", type=int, default=150, help="等结果的秒数，默认 150")
    parser.add_argument(
        "--exe",
        default=r"C:\Program Files\ToDesk AI\ToDeskAI.exe",
        help="客户端路径（换安装目录时改这里）",
    )
    args = parser.parse_args()

    taskbox = REPO / "data" / "todesk-taskbox"
    with tempfile.TemporaryDirectory(prefix="todesk-smoke-") as tmp:
        cfg = Path(tmp) / "providers.yaml"
        cfg.write_text(
            TEMPLATE.format(exe=args.exe, taskbox=taskbox, timeout=args.timeout),
            encoding="utf-8",
        )
        env = dict(os.environ, AGENT_CREDIT_PROVIDERS=str(cfg))
        print(f"[smoke] config={cfg} taskbox={taskbox} timeout={args.timeout}s")
        print("[smoke] 即将抢焦点并粘贴到 ToDesk AI 窗口…")
        proc = subprocess.run(
            [
                sys.executable, "credit.py", "dispatch",
                "--provider", "todesk",
                "--capability", args.capability,
                "--task", args.task,
            ],
            cwd=REPO, env=env,
        )
        return proc.returncode


if __name__ == "__main__":
    raise SystemExit(main())