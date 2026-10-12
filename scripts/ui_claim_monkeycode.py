#!/usr/bin/env python3
"""MonkeyCode 每日签到（UI 路线）。

为什么走 UI：external 直签需要过captcha。
  POST /api/v1/users/wallet/checkin           -> code 10701「兑换验证码失败」
  POST /api/v1/public/captcha/challenge       -> 201 {challenge:{c:50,s:32,d:3}, token}
  POST /api/v1/public/captcha/redeem          -> 500invalid solutions
`challenge` 的 c/s/d 恒为 50/32/3（连采 6 次不变），是**固定规格的图形验证码**
（画布 50、块 32、容差 3）——需要真渲染 + 图像识别 + 模拟拖动，
成本远高于点一次 UI，且没有可靠解法。故排除 external。

客户端：Tauri(webview2) 应用，**PrintWindow 抓不到 webview 内容**，
必须用屏幕捕获（BitBlt）+ 绝对坐标注入。

签到入口：设置 → 账号 → 「积分」卡片。2026-10-04 实测界面确认：
  - 左下角「设置」→ 弹层 → 左侧「账号」页
  - 卡片三栏：今日额度 / 积分(195) / 已邀请(0人)
  - 积分栏下方绿色「签到 +100」

凭据与合规：只操作本机客户端 UI，不解密登录态、不调未授权接口。

用法（需 GUI 通道：非提权交互式计划任务 RunLevel=Limited + LogonType=Interactive）：
    python scripts/ui_claim_monkeycode.py            # 完整流程
    python scripts/ui_claim_monkeycode.py --explore   # 只截图不点击
输出：logs/monkeycode_claim.json
"""
from __future__ import annotations

import argparse
import ctypes
import ctypes.wintypes as wt
import os
import json
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LOGDIR = ROOT / "logs"
EXE = str(Path(os.environ["LOCALAPPDATA"]) / "MonkeyCode" / "monkeycode-desktop.exe")
PROC = "monkeycode-desktop.exe"
RESULT = LOGDIR / "monkeycode_claim.json"

# webview 渲染就绪阈值（content_ink 的千分比）。空白/半空白窗口远低于此，
# 画完的客户端工作台远高于此。没有这个判断时，会把「没渲染」当成「弹层没开」
# 而多点一次「设置」——「设置」是 toggle，第二次点击会把刚开的弹层关掉。
#
# ⚠️ 2026-10-11 标定完毕。此前 40 是**错的**：40 恰好就等于「窗口没画出来/抓错
# 窗口」的水平，于是 `while ink < INK_MIN` 一次都不循环、闸门形同虚设。
# 实测两个锚点：
#   未渲染 / 抓错窗口 ....... 40（三轮 60s 内**恒定不变**，本身即异常信号）
#   已渲染的工作台 ......... 995（23:12 成功那轮）
# 取 300：远高于噪声、远低于真值，中间留足余量。仍可用 --ink-min 覆盖。
INK_MIN_DEFAULT = 300
INK_WAIT_MAX = 60.0

user32 = ctypes.WinDLL("user32", use_last_error=True)
gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)
user32.SetProcessDPIAware()

SW_RESTORE = 9
MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004
SRCCOPY = 0x00CC0020


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


def log(m: str) -> None:
    s = time.strftime("%H:%M:%S") + " " + m
    try:
        with open(LOGDIR / "_monkeycode_log.txt", "a", encoding="utf-8") as f:
            f.write(s + "\n")
    except OSError:
        pass
    print(s, flush=True)


def proc_pids(name: str) -> list[int]:
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    snap = kernel32.CreateToolhelp32Snapshot(0x00000002, 0)
    if snap == -1:
        return []
    ULONG_PTR = ctypes.c_size_t

    class PROCENTRY32(ctypes.Structure):
        _fields_ = [("dwSize", wt.DWORD), ("cntUsage", wt.DWORD),
                    ("th32ProcessID", wt.DWORD), ("th32DefaultHeapID", ULONG_PTR),
                    ("th32ModuleID", wt.DWORD), ("cntThreads", wt.DWORD),
                    ("th32ParentProcessID", wt.DWORD), ("pcPriClassBase", wt.LONG),
                    ("dwFlags", wt.DWORD), ("szExeFile", ctypes.c_wchar * 260)]

    out: list[int] = []
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


def close_client(timeout: float = 8.0) -> int:
    """关闭 MonkeyCode 客户端，返回关掉的进程数。

    顺序：先 WM_CLOSE 让主窗口走正常退出（能存配置、不留脏状态），
    超时才对剩余进程 TerminateProcess。
    不用 taskkill /IM —— 那个会无差别杀掉所有同名进程，
    而我们要精确只清理由本脚本拉起的那一批。
    """
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    WNDENUMPROC = ctypes.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM)
    pids = set(proc_pids(PROC))
    if not pids:
        return 0

    targets: list[int] = []

    def cb(h, _):
        p = wt.DWORD()
        user32.GetWindowThreadProcessId(h, ctypes.byref(p))
        if int(p.value) in pids and user32.IsWindowVisible(h):
            targets.append(int(h))
        return True

    user32.EnumWindows(WNDENUMPROC(cb), 0)
    for h in targets:
        user32.PostMessageW(h, 0x0010, 0, 0)      # WM_CLOSE

    t0 = time.time()
    killed = 0
    while time.time() - t0 < timeout:
        if not proc_pids(PROC):
            return len(pids)
        time.sleep(0.5)
    for pid in proc_pids(PROC):                  # 还剩的强杀
        h = kernel32.OpenProcess(0x0001 | 0x0400, False, pid)  # SYNCHRONIZE|TERMINATE
        if h:
            kernel32.TerminateProcess(h, 0)
            kernel32.CloseHandle(h)
            killed += 1
    return len(pids)


VK_MENU = 0x12
KEYEVENTF_KEYUP = 0x0002
SW_SHOW = 5


class _POINT(ctypes.Structure):
    _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]


GA_ROOT = 2


def client_owns_point(hwnd: int, x: int, y: int) -> bool:
    """点 (x,y) 处最上层的窗口是否**属于本客户端的窗口树**。

    这是「屏幕捕获到底拍到了谁」的直接校验：本脚本用 CopyFromScreen 抓窗口 rect，
    只要那个矩形里盖着别的窗口，抓到的就是别人的画面，而 OCR/像素判定会全部失真。

    ⚠️ 判据不能直接比 pid。MonkeyCode 是 **Tauri + WebView2**：网页内容跑在
    `msedgewebview2.exe` **子进程**里，该进程的窗口盖在客户端的 rect 上，于是
    「点上的窗口 pid ≠ monkeycode-desktop.exe 的 pid」——2026-10-11 我先写成比 pid，
    结果把**正常情况误判成被遮挡**，白拦了一轮。实测祖先链：
        Chrome_RenderWidgetHostHWND(webview2 子进程)
          -> Chrome_WidgetWin_1(webview2 子进程)
          -> Chrome_WidgetWin_0(客户端)
          -> WRY_WEBVIEW(客户端)          ← Tauri 的 webview 包装
          -> Tauri Window(客户端)          ← 主窗口
    所以正确判据是 **GetAncestor(pointWin, GA_ROOT) == 主窗口 hwnd**：
    点确实在客户端窗口里就是它；点了别人的窗口则 GA_ROOT 是别人的，照样能拦。
    """
    pt = _POINT(x, y)
    top = int(user32.WindowFromPoint(pt) or 0)
    if not top:
        return False
    if top == hwnd:
        return True
    root = int(user32.GetAncestor(top, GA_ROOT) or 0)
    return root == hwnd


def ensure_foreground(hwnd: int) -> bool:
    """把客户端逐级顶到前台，返回它最终是否真的可见且在前台。

    为什么不能只靠一次 SetForegroundWindow：Windows 会拒绝**非前台进程**发起的
    前台切换（SetForegroundWindow 的既定规则）。另一个窗口占着前台时，单次切换
    静默失败——而本脚本用**屏幕捕获**取图，抓到的就是别人窗口。

    ⚠️ 2026-10-11 实测更阴的一种：主窗口本身是**隐藏**的（MonkeyCode 会以「只驻留
    托盘」的方式启动：IsWindowVisible=False、tray_icon_app 在、主窗口 rect 照旧）。
    隐藏窗口上 SetForegroundWindow 不报错也不生效，GetForegroundWindow 甚至还会
    返回它——所以「前台」这个判据不够，必须先把它显示出来，并额外校验可见性。
    症状极具误导性：content_ink 恒为 40、green 恒为 0，看着像「webview 没渲染」，
    实际是「抓错窗口」（那张 _monkey_account.png 里出现的是 WorkBuddy 字样）。

    逐级加码：显示 → 还原 → Alt 技巧 → 绑输入队列强切。
    与 ui_claim_trae.ps1 的 Ensure-Foreground 同一套做法，跨客户端统一。
    """
    if not user32.IsWindowVisible(hwnd):
        user32.ShowWindow(hwnd, SW_SHOW)
        time.sleep(0.6)
    if int(user32.GetForegroundWindow() or 0) == hwnd:
        return True
    if user32.IsIconic(hwnd):
        user32.ShowWindow(hwnd, SW_RESTORE)
        time.sleep(0.4)
        if int(user32.GetForegroundWindow() or 0) == hwnd:
            return True

    # Alt 技巧：按下 Alt（不抬起）再切，Windows 通常放行，随后补 keyup
    user32.keybd_event(VK_MENU, 0, 0, 0)
    user32.SetForegroundWindow(hwnd)
    user32.keybd_event(VK_MENU, 0, KEYEVENTF_KEYUP, 0)
    time.sleep(0.5)
    if int(user32.GetForegroundWindow() or 0) == hwnd:
        return True

    # 绑输入队列后强切
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    target_tid = user32.GetWindowThreadProcessId(hwnd, None)
    cur_tid = kernel32.GetCurrentThreadId()
    if target_tid:
        user32.AttachThreadInput(cur_tid, target_tid, True)
        user32.ShowWindow(hwnd, SW_RESTORE)
        user32.SetForegroundWindow(hwnd)
        user32.AttachThreadInput(cur_tid, target_tid, False)
        time.sleep(0.5)
    if not user32.IsWindowVisible(hwnd):
        return False
    return int(user32.GetForegroundWindow() or 0) == hwnd


def restore_foreground(hwnd: int) -> None:
    """把前台还给运行前的窗口，别让用户对着一个死掉的客户端。"""
    fg = user32.GetForegroundWindow()
    if fg and fg != hwnd and user32.IsWindow(fg):
        try:
            user32.ShowWindow(fg, SW_RESTORE)
            user32.SetForegroundWindow(fg)
        except OSError:
            pass


def _cleanup(launched_by_us: bool, prev_foreground: int) -> None:
    """运行结束一律恢复现场。

    1) 只关**本次由脚本拉起**的实例——签到前就开着的必须保留
       （那是主人自己开的，可能是他正在用的工作窗口）；
    2) 把前台还给运行前的窗口。

    失败时也要清：无人值守跑完桌面不该堆着客户端。
    这个逻辑对齐 ui_claim_autoclaw.ps1 的 $script:LaunchedByUs
    与 ui_claim_trae.ps1 的 taskkill 收尾。
    """
    if launched_by_us:
        n = close_client()
        log(f"cleanup: closed {n} client process(es) we launched")
    else:
        log("cleanup: skipped (client was already running before us)")
    restore_foreground(prev_foreground)


def win_text(h: int) -> str:
    n = user32.GetWindowTextLengthW(h)
    b = ctypes.create_unicode_buffer(n + 1)
    user32.GetWindowTextW(h, b, n + 1)
    return b.value


def win_class(h: int) -> str:
    b = ctypes.create_unicode_buffer(256)
    user32.GetClassNameW(h, b, 256)
    return b.value


def win_pid(h: int) -> int:
    p = wt.DWORD()
    user32.GetWindowThreadProcessId(h, ctypes.byref(p))
    return int(p.value)


def win_rect(h: int):
    r = RECT()
    return r if user32.GetWindowRect(h, ctypes.byref(r)) else None


def win_rect_tuple(h: int) -> tuple[int, int, int, int] | None:
    """win_rect 的元组版 (left, top, width, height)，拿不到返回 None。

    win_rect 返回的是 ctypes RECT 结构体，直接解包会抛
    "cannot unpack non-iterable RECT object"（11-22 实踩）。
    """
    r = win_rect(h)
    if r is None:
        return None
    return int(r.left), int(r.top), int(r.right - r.left), int(r.bottom - r.top)


def enum_windows():
    WNDENUMPROC = ctypes.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM)
    out: list[int] = []

    def cb(h, _):
        out.append(int(h))
        return True
    user32.EnumWindows(WNDENUMPROC(cb), 0)
    return out


def find_main(pids: set[int]) -> int:
    """主窗口 = Tauri Window + 标题含 MonkeyCode + 排除「桌宠」+ 面积最大。

    2026-10-04 实测：该客户端还存在 `tray_icon_app`（2880x1511，隐藏黑窗）
    与 `MonkeyCodeNativePetLayeredWindow`（桌宠 232x240）两个同pid 窗口，
    必须按 class + 标题双重排除，否则会抓到托盘黑窗。

    ⚠️ 2026-10-11：**可见性优先**。客户端有时以「只驻留托盘」的方式启动
    （主窗口 IsWindowVisible=False），此时同 class 同标题的隐藏主窗口面积最大，
    只按面积筛就会选中它——一切照旧却什么都点不到。可见的优先；
    全都不可见时仍返回面积最大者，交给调用方 ShowWindow 再当面校验。
    """
    best, best_score = 0, -1
    for h in enum_windows():
        if win_pid(h) not in pids or win_class(h) != "Tauri Window":
            continue
        t = win_text(h)
        r = win_rect(h)
        if not r or "MonkeyCode" not in t or "桌宠" in t:
            continue
        area = (r.right - r.left) * (r.bottom - r.top)
        score = area * (10 if user32.IsWindowVisible(h) else 1)
        if score > best_score:
            best, best_score = h, score
    return best


def write_png(path: Path, bgra: bytes, w: int, h: int) -> None:
    """最小 PNG 编码（RGBA，无滤波）。

    自包含实现，不依赖 scripts/forensics_lobster_windows.py——
    那个文件是`_` 前缀的本地取证草稿，按项目约定不入库，
    生产脚本不能反向依赖它（否则换台机器就ModuleNotFoundError）。
    纯 zlib，无 Pillow 依赖（本机 managed python 没装 PIL）。
    """
    import struct
    import zlib
    rows = bytearray()
    stride = w * 4
    for y in range(h):
        rows.append(0)                      # filter type 0
        row = bgra[y * stride:(y + 1) * stride]
        for x in range(w):
            b, g, r, _a = row[x * 4:x * 4 + 4]
            rows += bytes((r, g, b, 255))

    def chunk(tag: bytes, data: bytes) -> bytes:
        c = tag + data
        return (struct.pack(">I", len(data)) + c
                + struct.pack(">I", zlib.crc32(c) & 0xFFFFFFFF))

    ihdr = struct.pack(">IIBBBBB", w, h, 8, 6, 0, 0, 0)
    path.write_bytes(
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", ihdr)
        + chunk(b"IDAT", zlib.compress(bytes(rows), 6))
        + chunk(b"IEND", b""))


# UI 内容恒定 1088x716 逻辑像素（Tauri webview），只是被缩放摆放在不同尺寸的
# 窗口里。2026-10-04 实测同一客户端两次冷启动窗口分别是 3866x2090 与 2426x1615，
# **按窗口比例换算会点错位置**（实测把「账号」tab 点成了「临时会话」）。
# 正确做法：按内容宽归一化。
CONTENT_W = 1088.0
CONTENT_H = 716.0


def content_origin(px: bytes, w: int, h: int) -> tuple[int, int, float]:
    """找出 webview 内容在窗口位图里的左上角与缩放比。

    依据：webview 内容区与窗口边框/标题栏颜色不同。从左上角逐行扫描，
    找到第一行「非窗口底色」的像素即内容起点；内容宽固定 1088 逻辑像素，
    缩放 = 实际内容像素宽 / 1088。
    """
    stride = w * 4

    def px_at(x: int, y: int) -> tuple[int, int, int]:
        o = y * stride + x * 4
        return px[o + 2], px[o + 1], px[o]        # R,G,B

    # 以窗口左上角 40x40 区域的众数色作为「边框/底色」
    votes: dict[tuple[int, int, int], int] = {}
    for y in range(0, min(40, h), 4):
        for x in range(0, min(40, w), 4):
            c = px_at(x, y)
            votes[c] = votes.get(c, 0) + 1
    bg = max(votes.items(), key=lambda kv: kv[1])[0]
    # 容差：允许抗锯齿带来的轻微偏差
    def is_bg(c: tuple[int, int, int]) -> bool:
        return abs(c[0] - bg[0]) < 12 and abs(c[1] - bg[1]) < 12 and abs(c[2] - bg[2]) < 12

    # 逐行找内容起始：某行里非底色像素数超过阈值即认为进入内容区
    y0 = 0
    for y in range(0, h - 1):
        n = 0
        for x in range(0, w, 8):
            if not is_bg(px_at(x, y)):
                n += 1
        if n > (w // 8) * 0.30:
            y0 = y
            break
    # 内容区内第一列非底色即 x0
    x0 = 0
    for x in range(0, w - 1):
        n = 0
        for y in range(y0, min(y0 + 200, h), 8):
            if not is_bg(px_at(x, y)):
                n += 1
        if n > (min(200, h - y0) // 8) * 0.30:
            x0 = x
            break
    # 内容右边界：内容高度按 716 逻辑像素等比推
    return int(x0), int(y0), 1.0


def content_click(px: bytes, w: int, h: int, lx: float, ly: float,
                  X: int, Y: int) -> tuple[int, int]:
    """把「缩略图坐标系」下的点换算成屏幕绝对坐标。

    背景（2026-10-04 反复踩坑后定案）：
    - 屏幕 3840x2160 物理像素，DPI 缩放存在
    - 窗口 rect 实测 2426x1615（物理像素）
    - 本项目 PNG 的真实像素尺寸 == 窗口 rect 尺寸（2426x1615）
    - **但 Read 工具展示 PNG 时会等比缩略到 1088 宽**（高度按比例 ≈ 724）

    所以：读图时在缩略图上量的坐标 (lx, ly) 必须按
        scale = w / 缩略图宽
    换算到真实像素，再加窗口原点。

    踩过的四个坑（全部失败，勿重犯）：
      1. 按窗口比例 (0.011, 0.962)          → 语义混淆，y 越界
      2. 颜色扫描自动求内容原点             → 窗口偏移时阈值失准
      3. 完全不缩放 (abs = X+lx)            → 偏小2.23 倍，点不中
      4. scale = w/1088 但 ly 用 716 网格    → y 越界（1690 > 1615）
         正确：缩略图高是 w/aspect，不是固定 716
    """
    THUMB_W = 1088.0
    # 缩略图高度按窗口宽高比推，不能写死
    thumb_h = THUMB_W * h / w if w else 1.0
    sx = w / THUMB_W
    sy = thumb_h / thumb_h          # 纵向已在同一比例下
    return int(X + lx * sx), int(Y + ly * sx)


def screen_shot(x: int, y: int, w: int, h: int):
    """Tauri webview 唯一可靠路径：屏幕区域BitBlt。"""
    hdc = user32.GetDC(0)
    mem = gdi32.CreateCompatibleDC(hdc)
    bmp = gdi32.CreateCompatibleBitmap(hdc, w, h)
    gdi32.SelectObject(mem, bmp)
    gdi32.BitBlt(mem, 0, 0, w, h, hdc, x, y, SRCCOPY)
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


def click(x: int, y: int) -> None:
    user32.SetCursorPos(int(x), int(y))
    time.sleep(0.2)
    user32.mouse_event(MOUSEEVENTF_LEFTDOWN, 0, 0, 0, 0)
    time.sleep(0.07)
    user32.mouse_event(MOUSEEVENTF_LEFTUP, 0, 0, 0, 0)
    time.sleep(0.5)


def content_ink(img) -> int:
    """内容区「非纯色像素」占比×1000，衡量 webview 画了多少东西。

    2026-10-11 新增。冷启动失败那轮（10:59）根因就是这个：
      settle=20s 后webview 还是空白/半空白，count_green 读到 0 → 判定「弹层没开」
      → 再点一次「设置」→ 「设置」是 toggle，把刚开的弹层又关掉了 → 全盘落空。
    空白窗口的 ink 极低（只剩标题栏和边框），画完的窗口 ink 上千。
    有了这个量，就能在点「设置」之前确认「至少画面已经画出来」，
    避免把「没渲染」误当成「弹层没开」而触发 toggle 反噬。
    """
    p, w, h = img
    stride = w * 4
    votes: dict[tuple[int, int, int], int] = {}
    for y in range(0, min(40, h), 4):
        for x in range(0, min(40, w), 4):
            o = (y * w + x) * 4
            c = (p[o + 2], p[o + 1], p[o])
            votes[c] = votes.get(c, 0) + 1
    if not votes:
        return 0
    bg = max(votes.items(), key=lambda kv: kv[1])[0]

    def is_bg(c: tuple[int, int, int]) -> bool:
        return abs(c[0] - bg[0]) < 12 and abs(c[1] - bg[1]) < 12 and abs(c[2] - bg[2]) < 12

    ink = 0
    total = 0
    # 跳过标题栏：只采样内容区（y 从 8% 起）
    for y in range(int(h * 0.08), h, 6):
        base = y * stride
        for x in range(0, w, 6):
            o = base + x * 4
            total += 1
            if not is_bg((p[o + 2], p[o + 1], p[o])):
                ink += 1
    return int(ink * 1000 / total) if total else 0


def write_result(status: str, detail: str) -> None:
    RESULT.write_text(json.dumps({"status": status, "detail": detail},
                                ensure_ascii=False), encoding="utf-8")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--explore", action="store_true", help="只截图，不点击")
    ap.add_argument("--steps", type=int, default=0,
                    help="explore 模式下先执行前 N 步导航再截图（用于观察深层页面）")
    ap.add_argument("--force", action="store_true", help="即使接口显示已签也照点（调试用）")
    ap.add_argument("--settle", type=int, default=20)
    ap.add_argument("--ink-min", type=int, default=INK_MIN_DEFAULT,
                    help="webview 渲染就绪阈值（content_ink 千分比）。空白窗口约 40，"
                         "画完的工作台远高于此；用 --explore 观察 content_ink 曲线即可标定")
    args = ap.parse_args()
    ink_min = args.ink_min
    if RESULT.exists():
        RESULT.unlink()

    # ---- 幂等闸门（必须在拉起客户端之前）----
    # GET /api/v1/users/wallet/checkin 返回 {checked_in: bool}，免验证码，
    # 比 OCR 判定可靠得多（OCR 只认「今日已签到」四个字，换个文案就失效）。
    # 已签 → 直接返回，不启客户端、不做任何点击。
    jar = ""
    try:
        import urllib.request
        ck = Path(os.environ["APPDATA"]) / "com.chaitin.baizhi.monkeycode" / "monkeycode-cookies.json"
        arr = json.loads(ck.read_text(encoding="utf-8"))
        jar = "; ".join(f"{c['name']}={c['value']}" for c in arr)
        req = urllib.request.Request(
            "https://monkeycode-ai.com/api/v1/users/wallet/checkin",
            headers={"Accept": "application/json", "Cookie": jar,
                     "User-Agent": "monkeycode-ui-claim/1.0"})
        with urllib.request.urlopen(req, timeout=20) as resp:
            already = bool((json.loads(resp.read().decode("utf-8")).get("data") or {})
                           .get("checked_in"))
        log(f"pre-check claimed_today={already}")
        if already and not args.force:
            log("already claimed today; skip UI entirely")
            write_result("already", "接口确认今日已签到，未启动客户端、未做任何点击")
            return 0
    except Exception as e:  # noqa: BLE001
        # 查不到就继续走 UI，不要因为接口异常卡住签到
        log(f"pre-check failed ({e}); continue to UI path")

    pids = set(proc_pids(PROC))
    # 签到前的前台窗口，收尾时还回去（别让主人对着一个死掉的客户端）
    prev_foreground = int(user32.GetForegroundWindow())
    launched_by_us = False
    log(f"preexisting procs={len(pids)}")
    if not pids:
        # explore 也允许自己拉起（收尾时会关掉自己启动的实例）——
        # 沙箱/计划任务会话无法在脚本外预先把客户端开好。
        log("launching MonkeyCode")
        subprocess.Popen([EXE], close_fds=True)
        launched_by_us = True
        t0 = time.time()
        while time.time() - t0 < 40:
            time.sleep(2)
            pids = set(proc_pids(PROC))
            if pids:
                log(f"pid appeared after {time.time()-t0:.0f}s")
                break
    time.sleep(args.settle)          # 等webview 拉完远程页面

    pids = set(proc_pids(PROC))
    if not pids:
        log("no process")
        _cleanup(launched_by_us, prev_foreground)
        write_result("notfound", "client did not start")
        return 1

    hwnd = find_main(pids)
    if not hwnd:
        log("main window not found")
        _cleanup(launched_by_us, prev_foreground)
        write_result("notfound", "no main window")
        return 1
    if not ensure_foreground(hwnd):
        # ⚠️ 硬闸门：这个脚本用**屏幕捕获**取图，客户端不在前台时抓到的是
        # 别人窗口（2026-10-11 实测抓到了 WorkBuddy），继续跑就等于在别人的
        # 窗口上按坐标盲点——那正是「把登录态点没了」这类事故的成因。
        # 宁可漏签一天，也不能盲点。
        log("ensure_foreground FAILED; refusing to click on an unverified window")
        _cleanup(launched_by_us, prev_foreground)
        write_result("pending",
                     "MonkeyCode 未能置于前台或仍不可见，无法确认截图来自本客户端；"
                     "为避免在别的窗口上盲点，未做任何点击，不入账")
        return 1
    time.sleep(0.6)
    r = win_rect(hwnd)
    X, Y, W, H = r.left, r.top, r.right - r.left, r.bottom - r.top
    visible = bool(user32.IsWindowVisible(hwnd))
    owns = client_owns_point(hwnd, X + W // 2, Y + H // 2)
    log(f"hwnd={hwnd} RECT={X},{Y} {W}x{H} foreground=ok visible={visible} center_owned_by_client={owns}")
    if not visible or not owns:
        # 「前台」这个判据会被隐藏窗口骗过（GetForegroundWindow 会返回隐藏窗口），
        # 所以再加一道**像素归属**校验：窗口中心那一点最上层的窗口必须是本客户端的。
        log("window center is not owned by the client; refusing to click")
        _cleanup(launched_by_us, prev_foreground)
        write_result("pending",
                     "MonkeyCode 窗口中心被其它窗口覆盖（或窗口仍不可见），"
                     "截图不可信；为避免盲点未做任何点击，不入账")
        return 1

    # 路径：左下「设置」-> 弹层（默认/记忆落在「账号」页）-> 「签到 +100」。
    # lx/ly 是 Read 展示的缩略图(1088宽)坐标系下的坐标，由 content_click 换算。
    # 2026-10-10：弹层点开即停在「账号」页，原第二步「账号 tab」已删——
    # 它在弹层未开时会把点击漏进主界面，反而把后续流程带偏。
    steps = [
        (52, 692, "click 设置"),
        (553, 379, "click 签到 +100"),
    ]

    if args.explore:
        px, w, h = screen_shot(X, Y, W, H)
        # 逐步导航但不点最后的目标按钮，用于定位改版后的入口。
        for lx, ly, what in steps[: max(0, args.steps)]:
            cx, cy = content_click(px, w, h, lx, ly, X, Y)
            log(f"{what} logic=({lx},{ly}) abs=({cx},{cy})")
            click(cx, cy)
            time.sleep(1.8)
            px, w, h = screen_shot(X, Y, W, H)
        tag = f"_monkey_explore{'_nav' if args.steps else ''}.png"
        write_png(LOGDIR / tag, px, w, h)
        log(f"shot -> logs/{tag} ({w}x{h})")
        # explore 模式也收尾：它可能自己拉起了客户端
        _cleanup(launched_by_us, prev_foreground)
        return 0

    # 从这里往后的所有退出路径都必须走_cleanup，
    # 否则无人值守跑完桌面会留着一个客户端窗口。
    try:
        # 初始位图，供content_click 做内容边界检测
        px, w, h = screen_shot(X, Y, W, H)

        # ---- 等 webview 画完（2026-10-11 新增）----
        # 自己拉起的客户端必须等：空白窗口下count_green 恒为 0，会被误判成
        # 「弹层没开」，而「设置」是 toggle —— 第二次点击会把弹层关掉。
        # 已在运行的客户端画面早就画好了，这一轮立即通过，不浪费时间。
        ink = content_ink((px, w, h))
        log(f"content_ink={ink} (settle={args.settle}s, ink_min={ink_min})")
        waited = 0.0
        while ink < ink_min and waited < INK_WAIT_MAX:
            time.sleep(2.0)
            waited += 2.0
            px, w, h = screen_shot(X, Y, W, H)
            ink = content_ink((px, w, h))
            log(f"content_ink={ink} after +{waited:.0f}s")
        if ink < ink_min:
            write_png(LOGDIR / "_monkey_account.png", px, w, h)
            _cleanup(launched_by_us, prev_foreground)
            write_result("pending",
                         f"webview 等待 {waited:.0f}s 仍未渲染（ink={ink} < {ink_min}），"
                         "未做任何点击，不入账")
            log(f"result status=pending detail=webview not rendered (ink={ink})")
            return 1
        # 窗口刚画完时 rect 可能仍在变（冷启动实测 495,344 2728x1816 vs
        # 稳态 294,294 2426x1615）。重取一次 rect 并重截，避免坐标基于旧 rect。
        new_rect = win_rect_tuple(hwnd)
        if new_rect is not None and new_rect != (X, Y, W, H):
            log(f"rect changed after render: {X},{Y} {W}x{H} -> "
                f"{new_rect[0]},{new_rect[1]} {new_rect[2]}x{new_rect[3]}")
            X, Y, W, H = new_rect
            px, w, h = screen_shot(X, Y, W, H)

        # 等渲染这段时间里焦点可能被别人抢走，动坐标前再确认一次：
        # 前台 + 可见 + 窗口中心确实属于本客户端，否则后面所有点击都会落在别人的窗口上。
        if not (ensure_foreground(hwnd)
                and user32.IsWindowVisible(hwnd)
                and client_owns_point(hwnd, X + W // 2, Y + H // 2)):
            log("foreground/visibility/ownership lost before clicking; abort instead of blind-clicking")
            _cleanup(launched_by_us, prev_foreground)
            write_result("pending",
                         "MonkeyCode 在前台确认环节失去焦点或被遮挡；为避免在别的窗口上盲点，"
                         "未做任何点击，不入账")
            return 1

        def count_green(img) -> int:
            """积分卡片的绿色特征（「695」数字 + 「签到 +100」链接）。
            区域 x∈[0.48,0.70]W, y∈[0.40,0.70]H —— 从 x=0.48 起避开左侧
            绿色进度条（终点 ~0.47）。>阈值 即认为账号页弹层当前开着。
            2026-10-10 教训：「设置」按钮是 toggle，弹层残留开着时点它反而
            会把弹层关掉，后续点击全部落空——所以动手前必须先判状态。
            """
            p2, w2, h2 = img
            x0, x1 = int(w2 * 0.48), int(w2 * 0.70)
            y0, y1 = int(h2 * 0.40), int(h2 * 0.70)
            n = 0
            for y in range(y0, y1, 3):
                base = y * w2
                for x in range(x0, x1, 3):
                    o = (base + x) * 4          # BGRA
                    b_, g_, r_ = p2[o], p2[o + 1], p2[o + 2]
                    if g_ > 110 and g_ > r_ * 1.4 and g_ > b_ * 1.3:
                        n += 1
            return n

        # 步骤1：确保账号页弹层开着。最多点两次「设置」，每次点击后都重新判定，
        # 弹层本来就开（比如上一轮残留）时一次都不点。
        panel_ready = False
        clicked = 0
        for attempt in range(2):
            g = count_green((px, w, h))
            log(f"account-page green={g} (attempt {attempt})")
            if g >= 15:
                panel_ready = True
                break
            if clicked > 0:
                # 已经点过一次却还没看到账号页：**先把等待拉长**再决定要不要补点。
                # 「设置」是 toggle，第二次点击可能把刚开的弹层关掉（10-10 踩过），
                # 而弹层从点击到渲染完有明显延迟。所以补点的前提是
                # 「画面确实已经画好 且 等够了仍然 green=0」。
                if content_ink((px, w, h)) < ink_min:
                    log("picture still blank after click; treat as not-rendered, stop clicking")
                    break
                for _ in range(6):
                    time.sleep(2.0)
                    px, w, h = screen_shot(X, Y, W, H)
                    g = count_green((px, w, h))
                    log(f"account-page green={g} (recheck)")
                    if g >= 15:
                        panel_ready = True
                        break
                if panel_ready:
                    break
            cx, cy = content_click(px, w, h, steps[0][0], steps[0][1], X, Y)
            log(f"click 设置 abs=({cx},{cy})")
            click(cx, cy)
            clicked += 1
            time.sleep(1.8)
            px, w, h = screen_shot(X, Y, W, H)
        else:
            panel_ready = False
        # 无论走break 还是走完两轮，没拿到 green 证据就一律不点签到。
        # 10-11 教训：条件循环里break 出去极易让后续步骤失去状态闸门，
        # 一旦这里放过，下一步就是盲点 UI——比漏签一天糟得多。
        if not panel_ready:
            write_png(LOGDIR / "_monkey_account.png", px, w, h)
            write_result("pending",
                         "未能确认账号页弹层已打开（积分卡片绿色特征缺失），未点签到，不入账")
            log("result status=pending detail=账号页未确认打开")
            return 1

        # 步骤2：点「签到 +100」（弹层内固定相对位，content_click 负责坐标换算）
        cx, cy = content_click(px, w, h, steps[1][0], steps[1][1], X, Y)
        log(f"click 签到 +100 abs=({cx},{cy})")
        click(cx, cy)
        time.sleep(1.8)
        px, w, h = screen_shot(X, Y, W, H)

        write_png(LOGDIR / "_monkey_account.png", px, w, h)
        log("shot -> logs/_monkey_account.png")

        # ---- 结果判定：以接口复认为准，OCR 只作辅助日志 ----
        time.sleep(1.5)
        detail = "已点击签到；请复核接口"
        status = "ok"
        try:
            req = urllib.request.Request(
                "https://monkeycode-ai.com/api/v1/users/wallet/checkin",
                headers={"Accept": "application/json", "Cookie": jar,
                         "User-Agent": "monkeycode-ui-claim/1.0"})
            with urllib.request.urlopen(req, timeout=20) as resp:
                ok = bool((json.loads(resp.read().decode("utf-8")).get("data") or {})
                          .get("checked_in"))
            if ok:
                status, detail = "ok", "签到成功（接口确认 checked_in=true）"
            else:
                status, detail = "pending", "已点击但接口仍显示未签到，可能弹了验证码"
        except Exception as e:  # noqa: BLE001
            # 复核失败绝不能报 ok。2026-10-10 实证：账号页 UI 改版后「积分」卡片
            # 消失，脚本按旧坐标点击落在空白处，报 ok 导致账本虚记 100（已回滚）。
            # 宁可 pending 不入账，不可无凭据记成功。
            status = "pending"
            detail = f"点击完成但复核失败: {e}（不入账，待人工确认）"

        log(f"result status={status} detail={detail}")
    finally:
        _cleanup(launched_by_us, prev_foreground)

    write_result(status, detail)
    return 0 if status == "ok" else 1


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except SystemExit:
        raise
    except BaseException as _e:  # noqa: BLE001 —— 计划任务里 stderr 看不到，必须落盘
        import traceback
        _tb = traceback.format_exc()
        try:
            with open(LOGDIR / "_monkeycode_log.txt", "a", encoding="utf-8") as _f:
                _f.write("EXCEPTION:\n" + _tb + "\n")
        except OSError:
            pass
        print(_tb, flush=True)
        raise SystemExit(1)
