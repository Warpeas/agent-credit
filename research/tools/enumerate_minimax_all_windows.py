"""全量窗口取证：不限类名/尺寸，枚举 MiniMax 进程所有顶层窗口 + 真身的子窗口树。

目的：找出用户看到的"全黑画面窗口"到底是谁。
  Chrome_WidgetWin_0 可见性恒为 0，故用户看到的黑屏必然另有其物：
  可能是真身渲染前的黑帧、广告子窗口、或另一个可见窗口。
"""
import ctypes
import ctypes.wintypes as wt
from pathlib import Path

u = ctypes.WinDLL("user32", use_last_error=True)
g = ctypes.WinDLL("gdi32", use_last_error=True)
dwmapi = ctypes.WinDLL("dwmapi", use_last_error=True)
k32 = ctypes.WinDLL("kernel32", use_last_error=True)

EnumWindowsProc = ctypes.WINFUNCTYPE(ctypes.c_bool, wt.HWND, wt.LPARAM)
GWL_STYLE = -16
GWL_EXSTYLE = -20
GW_OWNER = 4
DWMWA_CLOAKED = 14
WS_VISIBLE = 0x10000000
WS_EX_TOOLWINDOW = 0x00000080
WS_EX_LAYERED = 0x00080000
WS_EX_TRANSPARENT = 0x00000020
WS_EX_NOREDIRECTIONBITMAP = 0x00200000
WS_POPUP = 0x80000000
WS_CHILD = 0x40000000

BASE = Path(r"C:\Users\Hunter\Documents\Warpeas\agent-credit")


class PROCESSENTRY32W(ctypes.Structure):
    _fields_ = [
        ("dwSize", wt.DWORD), ("cntUsage", wt.DWORD), ("th32ProcessID", wt.DWORD),
        ("th32DefaultHeapID", ctypes.POINTER(ctypes.c_ulong)),
        ("th32ModuleID", wt.DWORD), ("cntThreads", wt.DWORD),
        ("th32ParentProcessID", wt.DWORD), ("pcPriClassBase", ctypes.c_long),
        ("dwFlags", wt.DWORD), ("szExeFile", ctypes.c_wchar * 260),
    ]


def mm_pids():
    snap = k32.CreateToolhelp32Snapshot(0x00000002, 0)
    if snap == -1:
        return set()
    pe = PROCESSENTRY32W()
    pe.dwSize = ctypes.sizeof(pe)
    out = set()
    try:
        if k32.Process32FirstW(snap, ctypes.byref(pe)):
            while True:
                if "minimax" in (pe.szExeFile or "").lower():
                    out.add(pe.th32ProcessID)
                if not k32.Process32NextW(snap, ctypes.byref(pe)):
                    break
    finally:
        k32.CloseHandle(snap)
    return out


def enum_top():
    out = []

    def cb(h, l):
        out.append(h)
        return True

    u.EnumWindows(EnumWindowsProc(cb), 0)
    return out


def enum_children(parent):
    out = []

    def cb(h, l):
        out.append(h)
        return True

    u.EnumChildWindows(parent, EnumWindowsProc(cb), 0)
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
    return {0: "no", 1: "user", 2: "shell", 3: "inh"}.get(v.value, str(v.value))


class BMIH(ctypes.Structure):
    _fields_ = [
        ("biSize", wt.DWORD), ("biWidth", wt.LONG), ("biHeight", wt.LONG),
        ("biPlanes", wt.WORD), ("biBitCount", wt.WORD), ("biCompression", wt.DWORD),
        ("biSizeImage", wt.DWORD), ("biXPelsPerMeter", wt.LONG), ("biYPelsPerMeter", wt.LONG),
        ("biClrUsed", wt.DWORD), ("biClrImportant", wt.DWORD),
    ]


class BMI(ctypes.Structure):
    _fields_ = [("bmiHeader", BMIH), ("bmiColors", wt.DWORD * 3)]


def grab(h, w, hgt):
    hdc = u.GetWindowDC(h)
    if not hdc:
        return False, 0, None
    mem = g.CreateCompatibleDC(hdc)
    bmp = g.CreateCompatibleBitmap(hdc, w, hgt)
    g.SelectObject(mem, bmp)
    ok = u.PrintWindow(h, mem, 2)
    bi = BMI()
    bi.bmiHeader.biSize = ctypes.sizeof(BMIH)
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


def px(v):
    if not v:
        return None
    return tuple(int.from_bytes(x, "little") if isinstance(x, bytes) else int(x) & 0xFF for x in v)


def ex_flags(ex):
    f = []
    if ex & WS_EX_TOOLWINDOW:
        f.append("TOOLWINDOW")
    if ex & WS_EX_LAYERED:
        f.append("LAYERED")
    if ex & WS_EX_TRANSPARENT:
        f.append("TRANSPARENT")
    if ex & WS_EX_NOREDIRECTIONBITMAP:
        f.append("NOREDIR")
    return "|".join(f) or "-"


L = []
pids = mm_pids()
L.append(f"MiniMax pids ({len(pids)}): {sorted(pids)}")
L.append("")
L.append("=== A. 全部顶层窗口（不限类名 / 不限尺寸）===")
tops = []
for h in enum_top():
    if pid_of(h) in pids:
        tops.append(h)
for h in sorted(tops):
    x, y, w, hh = rect_of(h)
    st = u.GetWindowLongW(h, GWL_STYLE)
    ex = u.GetWindowLongW(h, GWL_EXSTYLE)
    ok, ncol, first = grab(h, min(max(w, 1), 400), min(max(hh, 1), 300)) if (w > 2 and hh > 2) else (False, 0, None)
    L.append(f"hwnd={h:<9} pid={pid_of(h):<6} class={cls_of(h)!r:<26} title={title_of(h)!r}")
    L.append(f"    rect={rect_of(h)} Vis={int(bool(u.IsWindowVisible(h)))} WSV={int(bool(st & WS_VISIBLE))} "
             f"POPUP={int(bool(st & WS_POPUP))} CHILD={int(bool(st & WS_CHILD))}")
    L.append(f"    EX={ex_flags(ex)} cloak={cloaked_of(h)} owner={u.GetWindow(h, GW_OWNER)}")
    L.append(f"    PW={int(ok)} colors={ncol} first={px(first)}")
L.append("")

L.append("=== B. 真身(有标题的可见窗口)的子窗口树 ===")
main = None
for h in tops:
    if u.IsWindowVisible(h) and title_of(h):
        main = h
        break
if main:
    L.append(f"main hwnd={main} title={title_of(main)!r}")
    kids = enum_children(main)
    L.append(f"子窗口数={len(kids)}")
    for h in kids:
        x, y, w, hh = rect_of(h)
        st = u.GetWindowLongW(h, GWL_STYLE)
        ex = u.GetWindowLongW(h, GWL_EXSTYLE)
        ok, ncol, first = grab(h, min(max(w, 1), 300), min(max(hh, 1), 200)) if (w > 2 and hh > 2) else (False, 0, None)
        L.append(f"  hwnd={h:<9} class={cls_of(h)!r:<28} rect={(x, y, w, hh)} "
                 f"Vis={int(bool(u.IsWindowVisible(h)))} WSV={int(bool(st & WS_VISIBLE))} EX={ex_flags(ex)}")
        L.append(f"      PW={int(ok)} colors={ncol} first={px(first)}")
else:
    L.append("未找到有标题的可见窗口")

L.append("")
L.append("=== C. 全屏覆盖检测：任何 MiniMax 窗口是否覆盖整屏 ===")
sw = u.GetSystemMetrics(0)
sh = u.GetSystemMetrics(1)
L.append(f"SM_CXSCREEN={sw} SM_CYSCREEN={sh}  (非 DPI-aware 值)")
for h in tops:
    x, y, w, hh = rect_of(h)
    if w >= sw * 0.9 and hh >= sh * 0.9:
        L.append(f"  !! 近全屏: hwnd={h} class={cls_of(h)!r} rect={(x, y, w, hh)} Vis={int(bool(u.IsWindowVisible(h)))}")

out = BASE / "logs" / "_mm_allwins.txt"
out.write_text("\n".join(L), encoding="utf-8")
print("written", out)
