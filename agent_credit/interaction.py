"""统一交互调度：空闲检测、让位、前台保还。

为什么单独一层：签到里 5 家必须操作 GUI，各家脚本各自等空闲/抢前台，
既有重复等待，也没有「用户回来就停手」的统一语义。这里只做三件事：

  * user_idle_seconds()   —— GetLastInputInfo，键鼠最近一次输入距今秒数
  * wait_for_idle(...)    —— 等到连续 N 秒无输入，最多等 M 秒
  * ForegroundGuard       —— 开跑前记住前台窗口与光标，收尾时安全还回去

安全边界：恢复前台只在「用户仍空闲且前台已被自动化窗口占着」时做；
用户正在操作时绝不抢焦点，最多把光标位置还原。
"""
from __future__ import annotations

import ctypes
import ctypes.wintypes as wt
import os
import time
from dataclasses import dataclass

user32 = ctypes.WinDLL("user32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

# 默认值：连续 60s 无输入才算空闲；进入 UI 组最多等 5 分钟；
# 用户中途回来先等 90s，仍活跃就把剩余 UI 账户让位。
IDLE_THRESHOLD_SEC = 60
IDLE_WAIT_SEC = 300
YIELD_WAIT_SEC = 90
# 恢复前台的最小空闲时间：短于此值说明主人正在用，绝不抢。
# 用 8s 而不是 2s：主人切去别的窗口读东西时键鼠也会停，2s 太容易误抢。
RESTORE_MIN_IDLE_SEC = 8.0


class _LASTINPUTINFO(ctypes.Structure):
    _fields_ = [("cbSize", ctypes.c_uint), ("dwTime", ctypes.c_uint)]


class _POINT(ctypes.Structure):
    _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]


def _env_sec(name: str, default: int) -> float:
    raw = (os.environ.get(name) or "").strip()
    try:
        return float(raw) if raw else float(default)
    except ValueError:
        return float(default)


def user_idle_seconds() -> float:
    """键鼠最近一次输入距今的秒数；取不到时返回一个很大的值。"""
    info = _LASTINPUTINFO()
    info.cbSize = ctypes.sizeof(_LASTINPUTINFO)
    if not user32.GetLastInputInfo(ctypes.byref(info)):
        return 1e9
    tick = kernel32.GetTickCount() & 0xFFFFFFFF
    return ((tick - info.dwTime) & 0xFFFFFFFF) / 1000.0


def user_is_quiet(threshold: float = 5.0) -> bool:
    return user_idle_seconds() >= threshold


@dataclass
class IdleDecision:
    ok: bool
    waited: float
    idle: float
    aborted: bool = False


def wait_for_idle(
    threshold: float = IDLE_THRESHOLD_SEC,
    max_wait: float = IDLE_WAIT_SEC,
    *,
    poll: float = 2.0,
    should_abort=None,
    label: str = "UI",
) -> IdleDecision:
    """等到连续 `threshold` 秒无输入；最多等 `max_wait` 秒。

    should_abort() 返回 True 时提前结束（用于上层收到停止信号）。
    超时不报错——调用方决定是让位还是按最小暴露模式继续。
    """
    t0 = time.monotonic()
    idle = user_idle_seconds()
    if threshold <= 0 or idle >= threshold:
        return IdleDecision(True, 0.0, idle)
    while True:
        waited = time.monotonic() - t0
        if waited >= max_wait:
            return IdleDecision(False, waited, user_idle_seconds())
        if should_abort and should_abort():
            return IdleDecision(False, waited, user_idle_seconds(), aborted=True)
        time.sleep(min(poll, max(0.2, max_wait - waited)))
        idle = user_idle_seconds()
        if idle >= threshold:
            return IdleDecision(True, time.monotonic() - t0, idle)


def ui_idle_settings() -> tuple[float, float, float]:
    """(threshold, max_wait, yield_wait)；都可以用环境变量覆盖，方便临时调。"""
    return (
        _env_sec("AGENT_CREDIT_UI_IDLE_THRESHOLD", IDLE_THRESHOLD_SEC),
        _env_sec("AGENT_CREDIT_UI_IDLE_WAIT", IDLE_WAIT_SEC),
        _env_sec("AGENT_CREDIT_UI_YIELD_WAIT", YIELD_WAIT_SEC),
    )


class ForegroundGuard:
    """记住开跑前的前台窗口与光标，收尾时还回去。

    只做「安全恢复」：如果主人已经切走并在操作（空闲 < RESTORE_MIN_IDLE_SEC），
    不碰前台，也不移动光标——那才是真正的打断。
    """

    def __init__(self) -> None:
        self.hwnd = 0
        self.cursor = (0, 0)
        self._captured = False

    def capture(self) -> None:
        try:
            self.hwnd = int(user32.GetForegroundWindow() or 0)
            pt = _POINT()
            if user32.GetCursorPos(ctypes.byref(pt)):
                self.cursor = (pt.x, pt.y)
            self._captured = True
        except Exception:
            self._captured = False

    def restore(self) -> str:
        """返回一句可写日志的结果说明。"""
        if not self._captured or not self.hwnd:
            return "no-foreground"
        if user_idle_seconds() < RESTORE_MIN_IDLE_SEC:
            return "user-active-skip"
        try:
            if not user32.IsWindow(self.hwnd):
                return "target-gone"
            current = int(user32.GetForegroundWindow() or 0)
            if current != self.hwnd:
                # Alt 轻敲一下解 Windows 的前台锁（与各 ps1 里同一手法）
                user32.keybd_event(0x12, 0, 0, ctypes.c_ulong(0))
                user32.keybd_event(0x12, 0, 2, ctypes.c_ulong(0))
                time.sleep(0.04)
                user32.SetForegroundWindow(self.hwnd)
            user32.SetCursorPos(int(self.cursor[0]), int(self.cursor[1]))
            return "restored" if int(user32.GetForegroundWindow() or 0) == self.hwnd else "restore-failed"
        except Exception as exc:  # 恢复失败只影响体验，不能影响签到结果
            return f"restore-error:{exc}"
