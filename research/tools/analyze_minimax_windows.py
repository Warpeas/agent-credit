"""MiniMax 窗口取证：黑窗口到底是什么。

只读。枚举属于 MiniMax 进程的每个顶层窗口，报告：
  pid / 子进程类型(--type=) / 窗口类名 / 样式 / 是否 DWM cloaked / owner /
  rect / PrintWindow 渲染采样 / 标题
"""
import ctypes
import ctypes.wintypes as wt
import subprocess

u = ctypes.WinDLL("user32", use_last_error=True)
g = ctypes.WinDLL("gdi32", use_last_error=True)
k = ctypes.WinDLL("kernel32", use_last_error=True)
dwmapi = ctypes.WinDLL("dwmapi", use_last_error=True)

EnumWindowsProc = ctypes.WINFUNCTYPE(ctypes.c_bool, wt.HWND, wt.LPARAM)
GWL_STYLE = -16
GWL_EXSTYLE = -20
GW_OWNER = 4
DWMWA_CLOAKED = 14
WS_VISIBLE = 0x10000000
WS_EX_TOOLWINDOW = 0x00000080
WS_EX_LAYERED = 0x00080000
WS_EX_TRANSPARENT = 0x00000020


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


def style_of(h):
    return u.GetWindowLongW(h, GWL_STYLE), u.GetWindowLongW(h, GWL_EXSTYLE)


def cloaked_of(h):
    v = ctypes.c_int()
    hr = dwmapi.DwmGetWindowAttribute(h, DWMWA_CLOAKED, ctypes.byref(v), ctypes.sizeof(v))
    if hr != 0:
        return "n/a"
    return {0: "not-cloaked", 1: "cloaked-user", 2: "cloaked-shell", 3: "cloaked-inherited"}.get(v.value, str(v.value))


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


def cmdline(pid):
    return cmd_map.get(pid, "?")


# MiniMax 进程 pid 集合 + 命令行（由 PowerShell 导出，wmic 在 Win11 已被移除）
import json
import re as _re
from pathlib import Path

mm_pids = set()
cmd_map = {}
_procs = Path(r"C:\Users\Hunter\Documents\Warpeas\agent-credit\logs\_mm_procs.json")
if _procs.exists():
    _body = "\n".join(_procs.read_text(encoding="utf-8-sig").strip().splitlines()[:-1])
    try:
        arr = json.loads(_body)
        if isinstance(arr, dict):
            arr = [arr]
        for p in arr:
            pid = int(p.get("ProcessId"))
            cmd = p.get("CommandLine") or ""
            mm_pids.add(pid)
            m = _re.search(r"--type=([\w\-]+)", cmd)
            cmd_map[pid] = m.group(1) if m else "MAIN"
    except Exception as e:
        print("proc parse error:", e)

print("MiniMax pids:", sorted(mm_pids))
print()

rows = []
for h in enum_windows():
    pid = pid_of(h)
    if pid not in mm_pids:
        continue
    x, y, w, hh = rect_of(h)
    if w < 200 or hh < 150:
        continue
    st, ex = style_of(h)
    ok, ncol, first = grab(h, min(w, 600), min(hh, 400))
    rows.append(dict(hwnd=h, pid=pid, cls=cls_of(h), title=title_of(h),
                     rect=(x, y, w, hh), vis=bool(u.IsWindowVisible(h)),
                     style_ws_visible=bool(st & WS_VISIBLE),
                     ex_toolwindow=bool(ex & WS_EX_TOOLWINDOW),
                     cloaked=cloaked_of(h), owner=u.GetWindow(h, GW_OWNER),
                     pw=ok, colors=ncol, first=first, cmd=cmdline(pid)))

print("=== MiniMax 顶层窗口（>200x150）===")
for r in rows:
    print(f"hwnd={r['hwnd']} pid={r['pid']}")
    print(f"  class={r['cls']!r} title={r['title']!r}")
    print(f"  rect={r['rect']} IsWindowVisible={r['vis']} WS_VISIBLE={r['style_ws_visible']} "
          f"EX_TOOLWINDOW={r['ex_toolwindow']} cloaked={r['cloaked']} owner={r['owner']}")
    print(f"  PrintWindow={r['pw']} 采样色数={r['colors']} 首像素={r['first']}")
    c = r["cmd"]
    tail = c[-90:] if len(c) > 90 else c
    print(f"  进程命令行尾部: ...{tail}")
    print()
