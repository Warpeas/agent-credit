"""签到启动闸门：可见控制台里给主人 15 秒确认窗口。

背景：UI 签到组（Trae / AutoClaw / LobsterAI / Qoder CN / MonkeyCode）以前要么
等主人空闲（最多 5 分钟），要么在无人值守时悄悄开始。有人在用电脑时只能留
pending，没人时又要白等一轮。现在改成启动时问一句：

  * 可见控制台：倒计时 15s。Y/Enter 立即开始，N/Esc 跳过今天的 UI 签到，
    超时自动开始（不再等空闲）。
  * 无可见控制台（计划任务 / 管道 / 重定向）：不提示、不等空闲，直接开始。

闸门只决定 UI 组怎么走，external 签到与对账不受影响。退出码与旧空闲闸门都不变：
`AGENT_CREDIT_GATE=legacy` 可退回「等主人空闲」的老行为，`--no-gate` 可强制直接开始。

每次决策都会落一份 `logs/gate_last.json`：`_daily_chain.ps1` 靠它判断主人按了 N，
从而跳过后续会弹窗的 Trae 明细同步 / Qoder 用量刷新。
"""
from __future__ import annotations

import json
import math
import os
import sys
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Sequence

from . import trace
from .paths import LOG_DIR

DEFAULT_SECONDS = 15
MAX_SECONDS = 300
ENV_SECONDS = "AGENT_CREDIT_GATE_SEC"
ENV_MODE = "AGENT_CREDIT_GATE"          # legacy | idle -> 退回旧空闲闸门
ENV_FORCE_TTY = "AGENT_CREDIT_GATE_FORCE_TTY"  # 仅测试用：强制当作可见控制台
# 计划任务的 action 显式带 -Unattended（_daily_chain.ps1 会把它转成这个变量）。
# 为什么不只靠窗口可见性：任务的控制台窗口在部分上下文里 IsWindowVisible 仍为真，
# 2026-10-29 00:34 那轮就是被误判成「有可见控制台」，白等 15 秒。
ENV_UNATTENDED = "AGENT_CREDIT_GATE_UNATTENDED"
RESULT_PATH_NAME = "gate_last.json"

PROMPT_HINT = "Y/Enter 立即开始，N/Esc 跳过今天的 UI 签到"


@dataclass(frozen=True)
class Decision:
    """一次启动闸门的结论。

    action: start（开始签到） | skip_ui（主人跳过今天的 UI 组） | legacy（退回空闲闸门）
    source: key | timeout | unattended | flag | off
    """

    action: str
    source: str
    seconds: int = 0

    @property
    def start_now(self) -> bool:
        return self.action == "start"

    @property
    def skip_ui(self) -> bool:
        return self.action == "skip_ui"

    def as_dict(self) -> dict[str, object]:
        return {"action": self.action, "source": self.source, "seconds": self.seconds}


def _env_flag(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in ("1", "true", "yes", "on")


def _seconds(value: int | None) -> int:
    if value is None:
        raw = os.environ.get(ENV_SECONDS, "").strip()
        try:
            value = int(raw) if raw else DEFAULT_SECONDS
        except ValueError:
            value = DEFAULT_SECONDS
    return max(1, min(MAX_SECONDS, int(value)))


def _interactive() -> bool:
    """有没有主人能看见、能按键的控制台。

    计划任务以 InteractiveToken 跑 powershell.exe 时也带着控制台句柄，而且窗口
    是否真的可见并不可靠（2026-10-29 00:34 那轮 IsWindowVisible 返回真，白等了
    15 秒）。所以计划任务由 action 显式传 -Unattended，优先级最高。
    """
    if _env_flag(ENV_UNATTENDED):
        return False
    if _env_flag(ENV_FORCE_TTY):
        return True
    try:
        if sys.stdin is None or not sys.stdin.isatty():
            return False
    except Exception:
        return False
    if os.name != "nt":
        return True
    try:
        import ctypes

        hwnd = ctypes.windll.kernel32.GetConsoleWindow()
        if not hwnd:
            return False
        if not ctypes.windll.user32.IsWindowVisible(hwnd):
            return False
        # 最小化的窗口对主人不可见/不可输入，当作无人值守（手动跑也常见）。
        if ctypes.windll.user32.IsIconic(hwnd):
            return False
        return True
    except Exception:
        return False


def _echo(text: str) -> None:
    try:
        print(text, end="", flush=True)
    except Exception:
        pass


def _poll_key() -> str:
    """非阻塞读一个键；没有按键返回空串。方向键等特殊键吞掉后也返回空串。"""
    if os.name != "nt":
        return _poll_key_posix()
    try:
        import msvcrt
    except ImportError:
        return ""
    try:
        if not msvcrt.kbhit():
            return ""
        ch = msvcrt.getwch()
        if ch in ("\x00", "\xe0"):
            if msvcrt.kbhit():
                msvcrt.getwch()
            return ""
        return ch
    except Exception:
        return ""


def _poll_key_posix() -> str:
    try:
        import select

        ready, _, _ = select.select([sys.stdin], [], [], 0)
        if not ready:
            return ""
        return sys.stdin.read(1)
    except Exception:
        return ""


def _classify(key: str) -> str | None:
    """把按键翻成动作；无意义的键返回 None（倒计时继续）。"""
    if not key:
        return None
    if key in ("\r", "\n"):
        return "start"
    low = key.lower()
    if low == "y":
        return "start"
    if low in ("n", "\x1b"):
        return "skip"
    return None


def _countdown(seconds: int) -> str | None:
    """显示倒计时并等按键。返回 start / skip；超时返回 None。"""
    end = time.monotonic() + seconds
    shown: int | None = None
    while True:
        left = max(0, int(math.ceil(end - time.monotonic())))
        if left != shown:
            line = "  还有 %2d 秒…（%s）" % (left, PROMPT_HINT)
            # 定宽覆盖：秒数从两位数掉到一位时，不留上一帧的尾巴字符。
            _echo("\r" + line + " " * max(0, 68 - len(line)))
            shown = left
        action = _classify(_poll_key())
        if action:
            _echo("\n")
            return action
        if left <= 0:
            _echo("\n")
            return None
        time.sleep(0.1)


def _write_result(decision: Decision, ui_names: Sequence[str]) -> None:
    """落一份决策快照。写失败只吞掉：闸门是体验优化，不能反过来搞挂签到。"""
    payload = {
        "date": datetime.now().strftime("%Y-%m-%d"),
        "at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        **decision.as_dict(),
        "ui_accounts": list(ui_names),
    }
    try:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        path: Path = LOG_DIR / RESULT_PATH_NAME
        path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    except Exception:
        pass


def run_gate(
    seconds: int | None = None,
    *,
    enabled: bool = True,
    ui_names: Sequence[str] = (),
) -> Decision:
    """启动闸门主入口。

    enabled=False（`--no-gate`）直接放行；AGENT_CREDIT_GATE=legacy 退回旧空闲闸门。
    """
    secs = _seconds(seconds)
    mode = os.environ.get(ENV_MODE, "").strip().lower()
    names = list(ui_names)

    if mode in ("legacy", "idle"):
        decision = Decision("legacy", "off", secs)
    elif not enabled:
        decision = Decision("start", "flag", secs)
    elif _env_flag(ENV_UNATTENDED) or not _interactive():
        decision = Decision("start", "unattended", secs)
    else:
        trace.note("启动闸门：%d 秒后自动开始｜%s" % (secs, PROMPT_HINT))
        if names:
            trace.note("将操作：" + "、".join(names))
        action = _countdown(secs)
        if action == "start":
            trace.note("启动闸门：已确认，立即开始（不再等空闲）")
            decision = Decision("start", "key", secs)
        elif action == "skip":
            trace.note("启动闸门：主人跳过今天的 UI 签到（其余账户照常）")
            decision = Decision("skip_ui", "key", secs)
        else:
            trace.note("启动闸门：%d 秒内无输入，自动开始（不再等空闲）" % secs)
            decision = Decision("start", "timeout", secs)

    _write_result(decision, names)
    return decision
