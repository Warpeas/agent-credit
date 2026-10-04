"""MiniMax 冷启动时序取证：黑窗口 vs 真身 的出现/可见性/渲染 演化。

每轮采样所有属于 MiniMax 进程的可见性相关顶层窗口（不限尺寸，但过滤 <50px），
记录：t / hwnd / class / title / rect / IsWindowVisible / WS_VISIBLE / cloaked /
      PrintWindow 色数 / 首像素
用于回答：黑窗口是否在冷启动早期 visible=True 且渲染纯黑，之后被隐藏。
"""
import ctypes
import ctypes.wintypes as wt
import json
import re
import subprocess
import sys
import time
from pathlib import Path

u = ctypes.WinDLL("user32", use_last_error=True)
g = ctypes.WinDLL("gdi32", use_last_error=True)
dwmapi = ctypes.WinDLL("dwmapi", use_last_error=True)

EnumWindowsProc = ctypes.WINFUNCTYPE(ctypes.c_bool, wt.HWND, wt.LPARAM)
GWL_STYLE = -16
GWL_EXSTYLE = -20
GW_OWNER = 4
DWMWA_CLOAKED = 14
WS_VISIBLE = 0x10000000
WS_EX_TOOLWINDOW = 0x00000080
WS_MINIMIZE = 0x20000000

BASE = Path(r"C:\Users\Hunter\Documents\Warpeas\agent-credit")


def enum_windows():
    out = []

    def cb(h, l):
        out.append(h)
        return True

    u.EnumWindows(EnumWindowsProc(cb), 0)
    return out


def pid_of(h):
    p = ctypes.c_ulong()
    u.GetWindowThreadProcessId(h, ctypes.byref(p))
    return p.value


def cls_of(h):
    b = ctypes.create_unicode_buffer(256)
    u.GetClassNameW(h, b, 256)
    return b.value


def title_of(h):
    n = u.GetWindowTextLengthW(h)
    b = ctypes.create_unicode_buffer(n + 1)
    u.GetWindowTextW(h, b, n + 1)
    return b.value


def rect_of(h):
    r = wt.RECT()
    u.GetWindowRect(h, ctypes.byref(r))
    return (r.left, r.top, r.right - r.left, r.bottom - r.top)


def cloaked_of(h):
    v = ctypes.c_int()
    hr = dwmapi.DwmGetWindowAttribute(h, DWMWA_CLOAKED, ctypes.byref(v), ctypes.sizeof(v))
    if hr != 0:
        return "n/a"
    return {0: "no", 1: "user", 2: "shell", 3: "inherited"}.get(v.value, str(v.value))


class BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [
        ("biSize", wt.DWORD), ("biWidth", wt.LONG), ("biHeight", wt.LONG),
        ("biPlanes", wt.WORD), ("biBitCount", wt.WORD), ("biCompression", wt.DWORD),
        ("biSizeImage", wt.DWORD), ("biXPelsPerMeter", wt.LONG), ("biYPelsPerMeter", wt.LONG),
        ("biClrUsed", wt.DWORD), ("biClrImportant", wt.DWORD),
    ]


class BITMAPINFO(ctypes.Structure):
    _fields_ = [("bmiHeader", BITMAPINFOHEADER), ("bmiColors", wt.DWORD * 3)]


def grab(h, w, hgt):
    """PrintWindow 采样；返回 (ok, 色数, 首像素)。"""
    hdc = u.GetWindowDC(h)
    if not hdc:
        return False, 0, None
    mem = g.CreateCompatibleDC(hdc)
    bmp = g.CreateCompatibleBitmap(hdc, w, hgt)
    g.SelectObject(mem, bmp)
    ok = u.PrintWindow(h, mem, 2)
    bi = BITMAPINFO()
    bi.bmiHeader.biSize = ctypes.sizeof(BITMAPINFOHEADER)
    bi.bmiHeader.biWidth = w
    bi.bmiHeader.biHeight = -hgt
    bi.bmiHeader.biPlanes = 1
    bi.bmiHeader.biBitCount = 32
    buf = (ctypes.c_char * (w * hgt * 4))()
    got = g.GetDIBits(mem, bmp, 0, hgt, buf, ctypes.byref(bi), 0)
    colors = set()
    first = None
    if got:
        for i in range(0, len(buf), 4 * 97):
            b_, gg, r_, _a = buf[i], buf[i + 1], buf[i + 2], buf[i + 3]
            colors.add((r_, gg, b_))
            if first is None:
                first = (r_, gg, b_)
    g.DeleteObject(bmp)
    g.DeleteDC(mem)
    u.ReleaseDC(h, hdc)
    return bool(ok), len(colors), first


_tl = ctypes.WinDLL("kernel32", use_last_error=True)


class PROCESSENTRY32W(ctypes.Structure):
    _fields_ = [
        ("dwSize", wt.DWORD), ("cntUsage", wt.DWORD), ("th32ProcessID", wt.DWORD),
        ("th32DefaultHeapID", ctypes.POINTER(ctypes.c_ulong)),
        ("th32ModuleID", wt.DWORD), ("cntThreads", wt.DWORD),
        ("th32ParentProcessID", wt.DWORD), ("pcPriClassBase", ctypes.c_long),
        ("dwFlags", wt.DWORD), ("szExeFile", ctypes.c_wchar * 260),
    ]


def mm_pids():
    """纯 Win32 快照枚举，避免依赖外部 powershell 调用。"""
    snap = _tl.CreateToolhelp32Snapshot(0x00000002, 0)  # TH32CS_SNAPPROCESS
    if snap == -1:
        return set()
    pe = PROCESSENTRY32W()
    pe.dwSize = ctypes.sizeof(pe)
    out = set()
    try:
        if _tl.Process32FirstW(snap, ctypes.byref(pe)):
            while True:
                nm = pe.szExeFile or ""
                if "minimax" in nm.lower():
                    out.add(pe.th32ProcessID)
                if not _tl.Process32NextW(snap, ctypes.byref(pe)):
                    break
    finally:
        _tl.CloseHandle(snap)
    return out


INTERESTING = ("Chrome_WidgetWin",)

# --- 埋伏阶段：等 MiniMax 进程出现，避免错过启动瞬间 ---
wait_deadline = time.time() + 240
while time.time() < wait_deadline:
    if mm_pids():
        break
    time.sleep(0.15)

t0 = time.time()
lines = []
lines.append(f"launch detected: {time.strftime('%H:%M:%S')}")
lines.append("fields: t | hwnd | class | title | rect(x,y,w,h) | IsVis | WS_VIS | MIN | cloaked | PW_ok | colors | first")
lines.append("")

seen_first = {}
round_i = 0
deadline = t0 + 150
next_at = 0.0

while time.time() < deadline:
    el = time.time() - t0
    if el < next_at:
        time.sleep(0.2)
        continue
    round_i += 1
    pids = mm_pids()
    rows = []
    for h in enum_windows():
        pid = pid_of(h)
        if pid not in pids:
            continue
        c = cls_of(h)
        if not any(c.startswith(p) for p in INTERESTING):
            continue
        x, y, w, hh = rect_of(h)
        if w < 50 or hh < 50:
            continue
        st = u.GetWindowLongW(h, GWL_STYLE)
        ok, ncol, first = grab(h, min(w, 400), min(hh, 300))
        rows.append((h, pid, c, title_of(h), (x, y, w, hh),
                     bool(u.IsWindowVisible(h)), bool(st & WS_VISIBLE),
                     bool(st & WS_MINIMIZE), cloaked_of(h), ok, ncol, first))
    rows.sort(key=lambda r: r[1])
    tag = f"[t={el:6.1f}s] pids={len(pids)} wins={len(rows)}"
    lines.append(tag)
    for r in rows:
        h, pid, c, ti, rect, vis, wsv, mini, cl, ok, ncol, first = r
        lines.append(
            f"   hwnd={h:<9} pid={pid:<6} {c:<20} title={ti!r:<22} "
            f"rect={str(rect):<26} Vis={int(vis)} WSV={int(wsv)} MIN={int(mini)} "
            f"cloak={cl:<9} PW={int(ok)} colors={ncol:<4} first={first}"
        )
        key = (c, h)
        if key not in seen_first:
            seen_first[key] = f"{el:.1f}s"
    # 前 25s 每 0.3s（抓启动瞬间），25-50s 每 1s，之后每 3s
    next_at = el + (0.3 if el < 25 else (1.0 if el < 50 else 3.0))
    # 早停：稳定窗口已渲染且已持续 30s
    if rows and el > 45:
        rendered = [r for r in rows if r[10] > 8]
        if len(rendered) >= 1 and el > 75:
            break

lines.append("")
lines.append("=== 每个窗口首次出现的时刻 ===")
for (c, h), t in sorted(seen_first.items(), key=lambda kv: kv[1]):
    lines.append(f"  {t:>8}  hwnd={h}  {c}")

out = BASE / "logs" / "_mm_timeline.txt"
out.write_text("\n".join(lines), encoding="utf-8")
print(f"written: {out}  rounds={round_i}")
