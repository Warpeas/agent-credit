#!/usr/bin/env python3
"""MonkeyCode 签到 UI 探路：按坐标点击并OCR，找出「设置 → 账号 → 签到」的真实位置。

为什么用屏幕捕获而不是 PrintWindow：Tauri(webview2) 窗口 PrintWindow 只能拿到
窗口边框，webview 内容是合成层。上面的取证图能出内容是因为 fallback 到了
CopyFromScreen。这里直接固定用屏幕捕获 + 精确定位。

坐标策略：先用 GetWindowRect 拿到窗口在屏幕上的绝对位置，再按**比例**换算点击点，
不写死绝对像素（窗口位置每次冷启动都不同，10-04 实测 -13,-13 3866x2090 跨屏）。

用法（需 GUI 通道）：
    python monkeycode_probe_ui.py            # 只截图 + OCR，不点击
    python monkeycode_probe_ui.py --click 0.02,0.96   # 点相对坐标（0~1）
"""
from __future__ import annotations

import argparse
import ctypes
import ctypes.wintypes as wt
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from forensics_lobster_windows import (  # noqa: E402
    LOGDIR, analyze, enum_windows, grab, proc_pids, win_class, win_pid,
    win_rect, win_text, write_png,
)

user32 = ctypes.WinDLL("user32", use_last_error=True)
user32.SetProcessDPIAware()
PROC = "monkeycode-desktop.exe"

SW_RESTORE = 9
MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004


def find_main() -> int:
    """主窗口 = 标题含 MonkeyCode 且面积最大的 Tauri Window。"""
    pids = set(proc_pids(PROC))
    best, area = 0, 0
    for h in enum_windows():
        if win_pid(h) not in pids:
            continue
        if win_class(h) != "Tauri Window":
            continue
        t = win_text(h)
        r = win_rect(h)
        if not r or "MonkeyCode" not in t or "桌宠" in t:
            continue
        a = (r.right - r.left) * (r.bottom - r.top)
        if a > area:
            best, area = h, a
    return best


def screen_shot(x: int, y: int, w: int, h: int):
    """屏幕区域捕获（Tauri webview 唯一可靠路径）。"""
    gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)
    hdc = user32.GetDC(0)
    mem = gdi32.CreateCompatibleDC(hdc)
    bmp = gdi32.CreateCompatibleBitmap(hdc, w, h)
    gdi32.SelectObject(mem, bmp)
    gdi32.BitBlt(mem, 0, 0, w, h, hdc, x, y, 0x00CC0020)  # SRCCOPY

    class BITMAPINFOHEADER(ctypes.Structure):
        _fields_ = [("biSize", wt.DWORD), ("biWidth", wt.LONG), ("biHeight", wt.LONG),
                    ("biPlanes", wt.WORD), ("biBitCount", wt.WORD),
                    ("biCompression", wt.DWORD), ("biSizeImage", wt.DWORD),
                    ("biXPelsPerMeter", wt.LONG), ("biYPelsPerMeter", wt.LONG),
                    ("biClrUsed", wt.DWORD), ("biClrImportant", wt.DWORD)]

    class BITMAPINFO(ctypes.Structure):
        _fields_ = [("bmiHeader", BITMAPINFOHEADER), ("bmiColors", wt.DWORD * 3)]

    bi = BITMAPINFO()
    bi.bmiHeader.biSize = ctypes.sizeof(BITMAPINFOHEADER)
    bi.bmiHeader.biWidth = w
    bi.bmiHeader.biHeight = -h
    bi.bmiHeader.biPlanes = 1
    bi.bmiHeader.biBitCount = 32
    buf = ctypes.create_string_buffer(w * h * 4)
    gdi32.GetDIBits(mem, bmp, 0, h, buf, ctypes.byref(bi), 0)
    gdi32.DeleteObject(bmp)
    gdi32.DeleteDC(mem)
    user32.ReleaseDC(0, hdc)
    return buf.raw, w, h


def click_abs(x: int, y: int) -> None:
    user32.SetCursorPos(int(x), int(y))
    time.sleep(0.15)
    user32.mouse_event(MOUSEEVENTF_LEFTDOWN, 0, 0, 0, 0)
    time.sleep(0.06)
    user32.mouse_event(MOUSEEVENTF_LEFTUP, 0, 0, 0, 0)
    time.sleep(0.4)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--click", default="", help="相对坐标 x,y（0~1），可多次")
    ap.add_argument("--tag", default="probe")
    args = ap.parse_args()

    hwnd = find_main()
    if not hwnd:
        print("[probe] main window not found")
        return 1
    user32.ShowWindow(hwnd, SW_RESTORE)
    user32.SetForegroundWindow(hwnd)
    time.sleep(1.0)
    r = win_rect(hwnd)
    X, Y, W, H = r.left, r.top, r.right - r.left, r.bottom - r.top
    print(f"[probe] hwnd={hwnd} rect={X},{Y} {W}x{H}", flush=True)

    steps = [s for s in args.click.split(";") if s.strip()]
    for i, s in enumerate(steps + [""]):
        if s:
            fx, fy = (float(v) for v in s.split(","))
            cx = int(X + W * fx)
            cy = int(Y + H * fy)
            print(f"[probe] click rel=({fx},{fy}) -> abs=({cx},{cy})", flush=True)
            click_abs(cx, cy)
            time.sleep(1.6)
        px, w, h = screen_shot(X, Y, W, H)
        name = LOGDIR / f"_monkey_{args.tag}{i}.png"
        write_png(name, px, w, h)
        a = analyze(px, w, h)
        print(f"[probe] shot {name.name} {w}x{h} {a}", flush=True)

    print(f"[probe] done. screenshots in {LOGDIR}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
