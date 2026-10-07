#!/usr/bin/env python3
"""LobsterAI 窗口取证：枚举该进程名下所有顶层窗口，逐个抓图判黑。

为什么需要：2026-10-04 主人观察到「完全黑色、没有标题的窗口」，与 MiniMax 当初
的 Chrome_WidgetWin_0/1 混淆同源。ui_claim_lobsterai.ps1 的 Find-AppWindow
只按面积取最大窗口，Electron 多窗口（真身 + 广告/推广浮层）时可能选中错的那个。

纯 ctypes，不依赖 PowerShell Add-Type（沙箱内 PowerShell 禁止运行时编译）。
窗口枚举用 CreateToolhelp32Snapshot（纯 Win32），不调外部 powershell。

用法（需能拉起 GUI 的通道：提权计划任务 / 交互式登录）：
    python forensics_lobster_windows.py            # 若已在跑就只枚举+抓图
    python forensics_lobster_windows.py --launch   # 先拉起再取证
输出：
    logs/_lobster_windows.json
    logs/_lobster_win_<idx>_<hwnd>.png
"""
from __future__ import annotations

import argparse
import ctypes
import ctypes.wintypes as wt
import os
import json
import struct
import subprocess
import sys
import time
import zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LOGDIR = ROOT / "logs"
EXE = str(Path(os.environ["LOCALAPPDATA"]) / "Programs" / "LobsterAI" / "LobsterAI.exe")
PROC = "LobsterAI.exe"

user32 = ctypes.WinDLL("user32", use_last_error=True)
gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
user32.SetProcessDPIAware()

TH32CS_SNAPPROCESS = 0x00000002


class RECT(ctypes.Structure):
    _fields_ = [("left", wt.LONG), ("top", wt.LONG),
                ("right", wt.LONG), ("bottom", wt.LONG)]


class BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [("biSize", wt.DWORD), ("biWidth", wt.LONG), ("biHeight", wt.LONG),
                ("biPlanes", wt.WORD), ("biBitCount", wt.WORD),
                ("biCompression", wt.DWORD), ("biSizeImage", wt.DWORD),
                ("biXPelsPerMeter", wt.LONG), ("biYPelsPerMeter", wt.LONG),
                ("biClrUsed", wt.DWORD), ("biClrImportant", wt.DWORD)]


class BITMAPINFO(ctypes.Structure):
    _fields_ = [("bmiHeader", BITMAPINFOHEADER), ("bmiColors", wt.DWORD * 3)]


EnumProc = ctypes.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM)


def log(msg: str) -> None:
    print(msg, flush=True)


def proc_pids(name: str) -> list[int]:
    """CreateToolhelp32Snapshot 枚举进程，不依赖 tasklist/powershell。"""
    snap = kernel32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
    if snap == -1:
        return []
    ULONG_PTR = ctypes.c_size_t
    out: list[int] = []
    class PROCENTRY32(ctypes.Structure):
        _fields_ = [("dwSize", wt.DWORD), ("cntUsage", wt.DWORD),
                    ("th32ProcessID", wt.DWORD), ("th32DefaultHeapID", ULONG_PTR),
                    ("th32ModuleID", wt.DWORD), ("cntThreads", wt.DWORD),
                    ("th32ParentProcessID", wt.DWORD), ("pcPriClassBase", wt.LONG),
                    ("dwFlags", wt.DWORD), ("szExeFile", ctypes.c_wchar * 260)]
    pe = PROCENTRY32()
    pe.dwSize = ctypes.sizeof(PROCENTRY32)
    if kernel32.Process32FirstW(snap, ctypes.byref(pe)):
        while True:
            if pe.szExeFile.lower() == name.lower():
                out.append(int(pe.th32ProcessID))
            if not kernel32.Process32NextW(snap, ctypes.byref(pe)):
                break
    kernel32.CloseHandle(snap)
    return out


def win_text(hwnd: int) -> str:
    n = user32.GetWindowTextLengthW(hwnd)
    buf = ctypes.create_unicode_buffer(n + 1)
    user32.GetWindowTextW(hwnd, buf, n + 1)
    return buf.value


def win_class(hwnd: int) -> str:
    buf = ctypes.create_unicode_buffer(256)
    user32.GetClassNameW(hwnd, buf, 256)
    return buf.value


def win_pid(hwnd: int) -> int:
    pid = wt.DWORD()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    return int(pid.value)


def win_rect(hwnd: int):
    r = RECT()
    ok = user32.GetWindowRect(hwnd, ctypes.byref(r))
    if not ok:
        return None
    return r


def enum_windows() -> list[int]:
    out: list[int] = []

    def cb(hwnd, _):
        out.append(int(hwnd))
        return True
    user32.EnumWindows(EnumProc(cb), 0)
    return out


def grab(hwnd: int, w: int, h: int) -> tuple[bytes, int, int] | None:
    """PrintWindow 抓窗口内容，返回 (BGRA 像素, w, h)。"""
    hdc = user32.GetWindowDC(hwnd)
    if not hdc:
        return None
    mem = gdi32.CreateCompatibleDC(hdc)
    bmp = gdi32.CreateCompatibleBitmap(hdc, w, h)
    if not bmp:
        gdi32.DeleteDC(mem)
        user32.ReleaseDC(hwnd, hdc)
        return None
    gdi32.SelectObject(mem, bmp)
    # flag 2 = PW_RENDERFULLCONTENT
    ok = user32.PrintWindow(hwnd, mem, 2)
    bi = BITMAPINFO()
    bi.bmiHeader.biSize = ctypes.sizeof(BITMAPINFOHEADER)
    bi.bmiHeader.biWidth = w
    bi.bmiHeader.biHeight = -h          # 负 = top-down
    bi.bmiHeader.biPlanes = 1
    bi.bmiHeader.biBitCount = 32
    bi.bmiHeader.biCompression = 0
    buf = ctypes.create_string_buffer(w * h * 4)
    got = gdi32.GetDIBits(mem, bmp, 0, h, buf, ctypes.byref(bi), 0)
    gdi32.DeleteObject(bmp)
    gdi32.DeleteDC(mem)
    user32.ReleaseDC(hwnd, hdc)
    if not got:
        return None
    return buf.raw, w, h


def write_png(path: Path, bgra: bytes, w: int, h: int) -> None:
    """最小 PNG 编码（RGBA，无滤波）。"""
    rows = bytearray()
    stride = w * 4
    for y in range(h):
        rows.append(0)                      # filter type 0
        row = bgra[y * stride:(y + 1) * stride]
        for x in range(w):
            b, g, r, a = row[x * 4:x * 4 + 4]
            rows += bytes((r, g, b, 255))

    def chunk(tag: bytes, data: bytes) -> bytes:
        c = tag + data
        return struct.pack(">I", len(data)) + c + struct.pack(">I", zlib.crc32(c) & 0xFFFFFFFF)

    ihdr = struct.pack(">IIBBBBB", w, h, 8, 6, 0, 0, 0)
    png = (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr)
           + chunk(b"IDAT", zlib.compress(bytes(rows), 6)) + chunk(b"IEND", b""))
    path.write_bytes(png)


def analyze(bgra: bytes, w: int, h: int) -> dict:
    """抽样判黑：亮度极差 + 非黑像素占比 + 唯一色数（粗采样）。"""
    stride = w * 4
    samples: list[tuple[int, int, int]] = []
    dark = 0
    total = 0
    for gy in range(1, 10):
        y = h * gy // 10
        base = y * stride
        for gx in range(1, 10):
            x = w * gx // 10
            o = base + x * 4
            b, g, r, a = bgra[o], bgra[o + 1], bgra[o + 2], bgra[o + 3]
            lum = (r * 299 + g * 587 + b * 114) // 1000
            samples.append((r, g, b))
            total += 1
            if lum <= 12:
                dark += 1
    lums = [(r * 299 + g * 587 + b * 114) // 1000 for r, g, b in samples]
    uniq = len(set(samples))
    return {
        "grid_samples": total,
        "dark_ratio": round(dark / total, 3) if total else None,
        "lum_min": min(lums) if lums else None,
        "lum_max": max(lums) if lums else None,
        "uniq_colors": uniq,
        "verdict": "BLACK" if (uniq <= 2 and lums and max(lums) <= 12) else
                   ("NEAR_BLANK" if uniq <= 3 else "CONTENT"),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--launch", action="store_true")
    ap.add_argument("--wait", type=int, default=40)
    args = ap.parse_args()

    before = proc_pids(PROC)
    log(f"[forensics] preexisting {PROC} pids={before}")

    if args.launch and not before:
        log(f"[forensics] launching {EXE}")
        subprocess.Popen([EXE], close_fds=True)
        t0 = time.time()
        while time.time() - t0 < args.wait:
            now = proc_pids(PROC)
            if now:
                log(f"[forensics] pid appeared after {time.time()-t0:.1f}s: {now}")
                break
            time.sleep(2)
        time.sleep(6)   # 等 BrowserWindow 真正建出来

    pids = set(proc_pids(PROC))
    if not pids:
        log("[forensics] no process, abort")
        return 1
    log(f"[forensics] target pids={sorted(pids)}")

    recs = []
    for hwnd in enum_windows():
        pid = win_pid(hwnd)
        if pid not in pids:
            continue
        r = win_rect(hwnd)
        w = (r.right - r.left) if r else 0
        h = (r.bottom - r.top) if r else 0
        rec = {
            "hwnd": hwnd,
            "pid": pid,
            "class": win_class(hwnd),
            "title": win_text(hwnd),
            "rect": [r.left, r.top, w, h] if r else None,
            "visible": bool(user32.IsWindowVisible(hwnd)),
        }
        if w > 200 and h > 200:
            g = grab(hwnd, w, h)
            if g:
                px, gw, gh = g
                rec["grab"] = analyze(px, gw, gh)
                idx = len(recs)
                name = LOGDIR / f"_lobster_win_{idx}_{hwnd}.png"
                try:
                    write_png(name, px, gw, gh)
                    rec["png"] = str(name)
                except Exception as e:  # noqa: BLE001
                    rec["png_error"] = str(e)
        recs.append(rec)

    recs.sort(key=lambda d: -(d["rect"][2] * d["rect"][3]) if d["rect"] else 0)
    out = {"pids": sorted(pids), "windows": recs}
    (LOGDIR / "_lobster_windows.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")

    for i, d in enumerate(recs):
        g = d.get("grab", {})
        print(f"[{i}] hwnd={d['hwnd']} pid={d['pid']} {d['rect']} "
              f"vis={d['visible']} class={d['class']!r} title={d['title']!r} "
              f"-> {g.get('verdict')} uniq={g.get('uniq_colors')} "
              f"dark={g.get('dark_ratio')} lum={g.get('lum_min')}~{g.get('lum_max')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
