"""跨进程单实例锁：同一时间只让一条签到链路动客户端。

为什么需要它（2026-10-29）：前一条链路 23:58 启动、跨过零点跑到 00:03，计划任务的
IgnoreNew 把 00:00:45 的触发直接丢掉，结果 10-29 一家没签。现在两层防护：

  * 计划任务改 `MultipleInstancesPolicy=Queue`：上一实例没结束时排队，结束后立刻跑
    （见 scripts/register-daily-task.ps1）；
  * 这把锁：`_daily_chain.ps1` 用 `FileShare.None` 持有整条链，手动 `credit checkin`
    在 Python 端用同一把锁；撞上就提示「另一个签到在跑」，而不是两个实例同时开客户端。

实现用 `CreateFileW(share=0)`：进程崩溃/被结束时句柄自动释放，不存在「锁文件残留
要人工删」的问题。锁文件本身不删，留着当诊断点。
"""
from __future__ import annotations

import ctypes
import os
import time
from pathlib import Path

from .paths import LOG_DIR

LOCK_NAME = "checkin.lock"
HOLD_ENV = "AGENT_CREDIT_LOCK_HELD"      # 链路的子进程看到它就不再抢锁
WAIT_ENV = "AGENT_CREDIT_LOCK_WAIT"      # 手动跑时可选：最多等几秒
PATH_ENV = "AGENT_CREDIT_LOCK_PATH"      # 仅测试用：换一把锁，不碰真 logs

_GENERIC_READ = 0x80000000
_GENERIC_WRITE = 0x40000000
_OPEN_ALWAYS = 4
_FILE_ATTRIBUTE_NORMAL = 0x80
_ERROR_ACCESS_DENIED = 5
_ERROR_SHARING_VIOLATION = 32


def _kernel32() -> "ctypes.WinDLL":
    lib = ctypes.WinDLL("kernel32", use_last_error=True)
    lib.CreateFileW.restype = ctypes.c_void_p
    lib.CreateFileW.argtypes = [
        ctypes.c_wchar_p, ctypes.c_uint32, ctypes.c_uint32,
        ctypes.c_void_p, ctypes.c_uint32, ctypes.c_uint32, ctypes.c_void_p,
    ]
    lib.CloseHandle.restype = ctypes.c_int
    lib.CloseHandle.argtypes = [ctypes.c_void_p]
    return lib


_K32 = _kernel32() if os.name == "nt" else None


class CheckinLock:
    """持有中的锁。release() 关句柄即解锁；不删文件。"""

    def __init__(self, path: Path, handle: int) -> None:
        self.path = path
        self._handle = handle

    def release(self) -> None:
        handle, self._handle = self._handle, None
        if not handle:
            return
        if os.name == "nt" and _K32 is not None:
            _K32.CloseHandle(handle)
        else:
            try:
                os.close(handle)
            except OSError:
                pass

    def __enter__(self) -> "CheckinLock":
        return self

    def __exit__(self, *_exc) -> None:
        self.release()

    def __bool__(self) -> bool:
        return self._handle is not None

    def __del__(self) -> None:
        try:
            self.release()
        except Exception:
            pass


def _create_exclusive(path: str) -> int | None:
    if _K32 is None:
        # 非 Windows 只用于跑测试：用原子创建模拟同一时间只允许一个持有者。
        try:
            fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_RDWR)
        except FileExistsError:
            return None
        return fd
    handle = _K32.CreateFileW(
        path,
        _GENERIC_READ | _GENERIC_WRITE,
        0,                      # share=0：别的进程打不开，直到句柄关闭
        None,
        _OPEN_ALWAYS,
        _FILE_ATTRIBUTE_NORMAL,
        None,
    )
    if not handle or handle == ctypes.c_void_p(-1).value:
        return None
    return int(handle)


def default_path() -> Path:
    raw = os.environ.get(PATH_ENV, "").strip()
    return Path(raw) if raw else LOG_DIR / LOCK_NAME


def acquire(path: str | Path | None = None, wait: float = 0.0,
            poll: float = 1.0) -> CheckinLock | None:
    """抢锁；wait 秒内没抢到返回 None。非「被占用」的异常直接抛出。"""
    lock_path = Path(path) if path else default_path()
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    deadline = time.monotonic() + max(0.0, wait)
    while True:
        handle = _create_exclusive(str(lock_path))
        if handle is not None:
            return CheckinLock(lock_path, handle)
        err = ctypes.get_last_error() if os.name == "nt" else 0
        if os.name == "nt" and err not in (_ERROR_SHARING_VIOLATION, _ERROR_ACCESS_DENIED):
            raise OSError(err, f"无法创建签到锁 {lock_path}: {ctypes.FormatError(err)}")
        if time.monotonic() >= deadline:
            return None
        time.sleep(poll)


def held_by_parent() -> bool:
    """当前进程是不是由每日链路拉起的（链路已持有锁）。"""
    return os.environ.get(HOLD_ENV, "").strip().lower() in ("1", "true", "yes", "on")


def wait_seconds() -> float:
    raw = os.environ.get(WAIT_ENV, "").strip()
    try:
        return max(0.0, float(raw)) if raw else 0.0
    except ValueError:
        return 0.0


def acquire_for_checkin() -> CheckinLock | None:
    """CLI 用：链路子进程直接放行；否则按 AGENT_CREDIT_LOCK_WAIT 抢锁。"""
    if held_by_parent():
        return None
    return acquire(wait=wait_seconds())
