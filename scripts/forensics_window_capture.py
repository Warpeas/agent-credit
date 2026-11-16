#!/usr/bin/env python3
"""按进程名抓取主窗口位图，零干扰（PrintWindow，不进前台、不点击）。

为什么独立成一个工具：现有 ui_claim_*.ps1 都是「抓图 + 点击 + 判定」耦合在一起，
一旦只想看一眼当前布局就必须跑整条流程（会抢前台、会点菜单）。
排障时经常只需要「现在窗口长什么样」，这个工具只做这一件事。

窗口筛选（踩过的坑一并写死在这里）：
  Electron/Tauri 客户端同一个 pid 下常有多个 Chrome_WidgetWin_* 窗口：
    - Chrome_WidgetWin_1 主窗口（有标题、面积大）
    - Chrome_WidgetWin_0 推广浮层（无标题、冷启动时比主窗口先出现、可能近满屏纯黑）
    - 另有 64x100 之类的小残窗（同 class、有标题）——只按「可见 + 有标题」筛会选错
  所以：可见 + class==Chrome_WidgetWin_1 + 标题非空 + 面积最大。

用法：
    python scripts/forensics_window_capture.py <ProcessName> <out.png> [--title-like Agent]
输出一行 JSON：{"hwnd":..,"rect":[x,y,w,h],"png":"..","title":".."}
"""
from __future__ import annotations

import argparse
import ctypes
import ctypes.wintypes as wt
import json
import sys
from pathlib import Path

user32 = ctypes.WinDLL("user32", use_last_error=True)
gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)
user32.SetProcessDpiAwareness = getattr(user32, "SetProcessDPIAware", None)
try:
    ctypes.windll.shcore.SetProcessDpiAwareness(2)  # per-monitor v2
except Exception:
    user32.SetProcessDPIAware()


class RECT(ctypes.Structure):
    _fields_ = [("left", ctypes.c_long), ("top", ctypes.c_long),
                ("right", ctypes.c_long), ("bottom", ctypes.c_long)]


class BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [("biSize", wt.DWORD), ("biWidth", ctypes.c_long),
                ("biHeight", ctypes.c_long), ("biPlanes", wt.WORD),
                ("biBitCount", wt.WORD), ("biCompression", wt.DWORD),
                ("biSizeImage", wt.DWORD), ("biXPelsPerMeter", ctypes.c_long),
                ("biYPelsPerMeter", ctypes.c_long), ("biClrUsed", wt.DWORD),
                ("biClrImportant", wt.DWORD)]


def pids_of(name: str) -> set[int]:
    import subprocess
    r = subprocess.run(["tasklist", "/FI", f"IMAGENAME eq {name}", "/FO", "CSV", "/NH"],
                       capture_output=True, text=True, errors="replace")
    out = set()
    for line in r.stdout.splitlines():
        parts = [p.strip('"') for p in line.split('","')]
        if len(parts) >= 2 and parts[0].lower() == name.lower():
            try:
                out.add(int(parts[1]))
            except ValueError:
                pass
    return out


def enum_candidates(pids: set[int], title_like: str = ""):
    WNDENUMPROC = ctypes.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM)
    found = []

    def cb(h, _):
        pid = wt.DWORD()
        user32.GetWindowThreadProcessId(h, ctypes.byref(pid))
        if pid.value not in pids:
            return True
        if not user32.IsWindowVisible(h):
            return True
        cls = ctypes.create_unicode_buffer(256)
        user32.GetClassNameW(h, cls, 256)
        if cls.value != "Chrome_WidgetWin_1":
            return True
        n = user32.GetWindowTextLengthW(h)
        buf = ctypes.create_unicode_buffer(n + 1)
        user32.GetWindowTextW(h, buf, n + 1)
        title = buf.value
        if not title.strip():
            return True
        if title_like and title_like.lower() not in title.lower():
            return True
        r = RECT()
        user32.GetWindowRect(h, ctypes.byref(r))
        w, hh = r.right - r.left, r.bottom - r.top
        found.append((w * hh, h, title, r.left, r.top, w, hh, cls.value))
        return True

    user32.EnumWindows(WNDENUMPROC(cb), 0)
    found.sort(reverse=True)
    return found


def capture(hwnd: int, x: int, y: int, w: int, h: int, out: Path) -> None:
    hdc = user32.GetDC(0)
    memdc = gdi32.CreateCompatibleDC(hdc)
    bmp = gdi32.CreateCompatibleBitmap(hdc, w, h)
    gdi32.SelectObject(memdc, bmp)
    # PrintWindow(.., 2) == PW_RENDERFULLCONTENT，Electron/CEF 必须带这个 flag，
    # 否则拿到全黑帧。
    ok = user32.PrintWindow(hwnd, memdc, 2)
    if not ok:
        gdi32.BitBlt(memdc, 0, 0, w, h, hdc, x, y, 0x00CC0020)
    bi = BITMAPINFOHEADER()
    bi.biSize = ctypes.sizeof(BITMAPINFOHEADER)
    bi.biWidth = w
    bi.biHeight = -h  # 负数 = top-down
    bi.biPlanes = 1
    bi.biBitCount = 32
    bi.biCompression = 0
    buf = ctypes.create_string_buffer(w * h * 4)
    gdi32.GetDIBits(memdc, bmp, 0, h, buf, ctypes.byref(bi), 0)
    gdi32.DeleteObject(bmp)
    gdi32.DeleteDC(memdc)
    user32.ReleaseDC(0, hdc)

    # 手写 PNG（本机没有 Pillow，png 编码器只此一份）
    import struct
    import zlib
    rows = []
    mv = memoryview(buf)
    for yy in range(h):
        o = yy * w * 4
        row = bytearray(mv[o:o + w * 4])
        for xx in range(w):
            b, g, r, _a = row[xx * 4], row[xx * 4 + 1], row[xx * 4 + 2], row[xx * 4 + 3]
            row[xx * 4], row[xx * 4 + 1], row[xx * 4 + 2], row[xx * 4 + 3] = r, g, b, 255
        rows.append(b"\x00" + bytes(row))
    raw = b"".join(rows)

    def chunk(t: bytes, d: bytes) -> bytes:
        return (struct.pack(">I", len(d)) + t + d
                + struct.pack(">I", zlib.crc32(t + d) & 0xFFFFFFFF))

    png = (b"\x89PNG\r\n\x1a\n"
           + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 6, 0, 0, 0))
           + chunk(b"IDAT", zlib.compress(raw, 6))
           + chunk(b"IEND", b""))
    out.write_bytes(png)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("process_name")
    ap.add_argument("out")
    ap.add_argument("--title-like", default="")
    args = ap.parse_args()

    pids = pids_of(args.process_name)
    if not pids:
        print(json.dumps({"error": "no process", "pids": []}, ensure_ascii=False))
        return 1
    cands = enum_candidates(pids, args.title_like)
    if not cands:
        print(json.dumps({"error": "no window", "pids": sorted(pids)}, ensure_ascii=False))
        return 1
    cands_out = [{"title": c[2], "rect": [c[3], c[4], c[5], c[6]], "area": c[0]}
                 for c in cands]
    _area, hwnd, title, x, y, w, h, _cls = cands[0]
    out = Path(args.out)
    capture(hwnd, x, y, w, h, out)
    print(json.dumps({"hwnd": hwnd, "title": title, "rect": [x, y, w, h],
                      "png": str(out), "candidates": cands_out},
                     ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
