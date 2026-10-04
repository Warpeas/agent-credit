"""诊断：对 MiniMax 的每个顶层窗口做 PrintWindow，判断是否渲染空白。

只读，不点击、不启动、不改任何状态。
"""
import ctypes
import ctypes.wintypes as wt

u = ctypes.WinDLL("user32", use_last_error=True)
g = ctypes.WinDLL("gdi32", use_last_error=True)
k = ctypes.WinDLL("kernel32", use_last_error=True)

EnumWindowsProc = ctypes.WINFUNCTYPE(ctypes.c_bool, wt.HWND, wt.LPARAM)
PW_RENDERFULLCONTENT = 0x00000002
BI_RGB = 0
DIB_RGB_COLORS = 0


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


def title_of(h):
    b = ctypes.create_unicode_buffer(256)
    u.GetWindowTextW(h, b, 256)
    return b.value


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
    """PrintWindow the window and return (ok, distinct_color_count, corner_pixel)."""
    hdc = u.GetWindowDC(h)
    if not hdc:
        return False, 0, None
    mem = g.CreateCompatibleDC(hdc)
    bmp = g.CreateCompatibleBitmap(hdc, w, hgt)
    g.SelectObject(mem, bmp)
    ok = u.PrintWindow(h, mem, PW_RENDERFULLCONTENT)
    bi = BITMAPINFO()
    bi.bmiHeader.biSize = ctypes.sizeof(BITMAPINFOHEADER)
    bi.bmiHeader.biWidth = w
    bi.bmiHeader.biHeight = -hgt  # top-down
    bi.bmiHeader.biPlanes = 1
    bi.bmiHeader.biBitCount = 32
    bi.bmiHeader.biCompression = BI_RGB
    buf = (ctypes.c_char * (w * hgt * 4))()
    got = g.GetDIBits(mem, bmp, 0, hgt, buf, ctypes.byref(bi), DIB_RGB_COLORS)
    colors = set()
    first = None
    if got:
        for i in range(0, min(len(buf), w * hgt * 4), 4 * 97):  # sparse sample
            b_, gg, r_, _a = buf[i], buf[i + 1], buf[i + 2], buf[i + 3]
            colors.add((r_, gg, b_))
            if first is None:
                first = (r_, gg, b_)
    g.DeleteObject(bmp)
    g.DeleteDC(mem)
    u.ReleaseDC(h, hdc)
    return bool(ok), len(colors), first


targets = []
for h in enum_windows():
    r = wt.RECT()
    u.GetWindowRect(h, ctypes.byref(r))
    w, hgt = r.right - r.left, r.bottom - r.top
    if w < 300 or hgt < 200:
        continue
    pid = pid_of(h)
    hproc = k.OpenProcess(0x1000, False, pid)
    name = "?"
    if hproc:
        buf = ctypes.create_unicode_buffer(1024)
        size = ctypes.c_ulong(1024)
        if k.QueryFullProcessImageNameW(hproc, 0, buf, ctypes.byref(size)):
            name = buf.value.split("\\")[-1]
        k.CloseHandle(hproc)
    if "minimax" not in name.lower():
        continue
    targets.append((h, pid, name, w, hgt))

print("=== MiniMax 窗口渲染检测 ===")
for h, pid, name, w, hgt in targets:
    r = wt.RECT()
    u.GetWindowRect(h, ctypes.byref(r))
    vis = bool(u.IsWindowVisible(h))
    ok, ncol, first = grab(h, min(w, 600), min(hgt, 400))
    verdict = "空白/纯色（黑窗口）" if ncol <= 2 else "有内容（真身）"
    print(f"hwnd={h} pid={pid} proc={name}")
    print(f"  rect=({r.left},{r.top}) {w}x{hgt}  visible={vis}  title={title_of(h)!r}")
    print(f"  PrintWindow={ok} 采样唯一色数={ncol} 首像素={first}  -> {verdict}")
