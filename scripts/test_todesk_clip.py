r"""ToDesk 适配器里那套无依赖剪贴板实现的回归测试。

被测的是 agent_credit/dispatch/adapters/todesk.py 的 clipboard_set / clipboard_get：
纯 ctypes 直调 user32 / kernel32，最容易在改动时静默坏掉的地方是 restype——
64 位句柄不声明 restype 就会被截成 32 位 int，GlobalLock 返回野指针，
表现为 `OSError: access violation reading 0xFFFFFFFF...`（2026-11-16 踩过一次）。

用法（仓库根）：
    python scripts\test_todesk_clip.py
成功：打印"回读=OK"并以 0 退出；失败：非 0 退出，且原剪贴板内容会被还原。
只读写剪贴板，不碰窗口、不发按键。
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agent_credit.dispatch.adapters.todesk import (  # noqa: E402
    _idle_seconds,
    clipboard_get,
    clipboard_set,
)

MARKER = "KURO-CLIP-TEST-黑猫"


def main() -> int:
    original = clipboard_get()
    print(f"idle={_idle_seconds():.1f}s 原剪贴板长度={len(original)}")
    try:
        clipboard_set(MARKER)
        got = clipboard_get()
        if got != MARKER:
            print(f"回读=MISMATCH: {got!r}")
            return 1
        print("回读=OK")
        return 0
    finally:
        if original:
            clipboard_set(original)
            print(f"已还原，长度={len(clipboard_get())}")


if __name__ == "__main__":
    raise SystemExit(main())