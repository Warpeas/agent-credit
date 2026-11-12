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
UIA_SCRIPT = ROOT / "scripts" / "uia_monkeycode.ps1"
UIA_RESULT = LOGDIR / "_monkeycode_uia.json"

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
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
user32.SetProcessDPIAware()

SW_RESTORE = 9
SW_MAXIMIZE = 3
MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004
SRCCOPY = 0x00CC0020
# 方案甲：窗口停到主屏左界外，只留一条窄边给 DWM/WebView2 保持渲染。
SWP_NOSIZE = 0x0001
SWP_NOMOVE = 0x0002
SWP_NOZORDER = 0x0004
SWP_NOACTIVATE = 0x0010
HWND_TOPMOST = -1
HWND_NOTOPMOST = -2
OFFSCREEN_STRIP = 48
IDLE_THRESHOLD_SEC = 60
# 脚本内部默认不等待：checkin.py 会在 60s 命令超时之外先等空闲；
# 手动跑可显式 --idle-wait 300。内部闸门只做“活跃就 pending”的最后一道保险。
IDLE_WAIT_SEC = 0
# 2026-10-25：--no-idle-gate 同时关闭**点击前**的空闲复查。实测 MonkeyCode
# 客户端一启动就会自己注入一次输入事件（Popen 后 GetLastInputInfo 立即归零），
# 于是「启动后等 20s 再点」时 idle 必然 <60，per-click 闸门 100% 拒绝点击。
# 10-24/10-25 连续两天「UIA 找到设置按钮但点击被遮挡或用户活跃」就是这么来的，
# 共享闸门通过也没用。启动前的空闲已由 checkin 统一确认，这里不再二次判断。
SKIP_CLICK_IDLE = False
# 记录签到前窗口的原始 rect / hwnd，任何退出路径都要还原。
CURRENT_HWND = None
ORIG_RECT = None
# 屏外停放时的「正常态」rect（最大化窗口会先还原再停放）：
# 2026-10-25 实测最大化窗口被移回屏内并 SetForegroundWindow 时，Windows/Electron
# 会把它还原成 normal rect（3866x2090 -> 2426x1615 @294,294），UIA 探针按最大化
# 布局给出的坐标立刻失效（按钮 y=2038 -> 实际点 y=2332，屏幕外）。停放前先
# SW_RESTORE，用正常态 rect 做后续换算；收尾时再按需恢复最大化。
PARK_RECT = None
WAS_MAXIMIZED = False
# 本次由脚本拉起的 PID 集合：收尾只关这些，用户自己开的实例一律不动。
LAUNCHED_PIDS: set[int] = set()


class RECT(ctypes.Structure):
    _fields_ = [("left", wt.LONG), ("top", wt.LONG),
                ("right", wt.LONG), ("bottom", wt.LONG)]


class WPOINT(ctypes.Structure):
    _fields_ = [("x", wt.LONG), ("y", wt.LONG)]


class WINDOWPLACEMENT(ctypes.Structure):
    """GetWindowPlacement 用：rcNormalPosition 是 Electron/Tauri 自己也认的「正常态」rect。"""
    _fields_ = [("length", wt.UINT), ("flags", wt.UINT), ("showCmd", wt.UINT),
                ("ptMinPosition", WPOINT), ("ptMaxPosition", WPOINT),
                ("rcNormalPosition", RECT)]


class BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [("biSize", wt.DWORD), ("biWidth", wt.LONG), ("biHeight", wt.LONG),
                ("biPlanes", wt.WORD), ("biBitCount", wt.WORD),
                ("biCompression", wt.DWORD), ("biSizeImage", wt.DWORD),
                ("biXPelsPerMeter", wt.LONG), ("biYPelsPerMeter", wt.LONG),
                ("biClrUsed", wt.DWORD), ("biClrImportant", wt.DWORD)]


class BITMAPINFO(ctypes.Structure):
    _fields_ = [("bmiHeader", BITMAPINFOHEADER), ("bmiColors", wt.DWORD * 3)]


class LASTINPUTINFO(ctypes.Structure):
    _fields_ = [("cbSize", wt.UINT), ("dwTime", wt.DWORD)]


user32.SetWindowPos.argtypes = [wt.HWND, wt.HWND, ctypes.c_int, ctypes.c_int,
                                ctypes.c_int, ctypes.c_int, wt.UINT]
user32.SetWindowPos.restype = wt.BOOL
user32.GetLastInputInfo.argtypes = [ctypes.POINTER(LASTINPUTINFO)]
user32.GetLastInputInfo.restype = wt.BOOL
kernel32.GetTickCount.restype = wt.DWORD
user32.GetWindowPlacement.argtypes = [wt.HWND, ctypes.POINTER(WINDOWPLACEMENT)]
user32.GetWindowPlacement.restype = wt.BOOL
user32.SetWindowPlacement.argtypes = [wt.HWND, ctypes.POINTER(WINDOWPLACEMENT)]
user32.SetWindowPlacement.restype = wt.BOOL
user32.IsZoomed.argtypes = [wt.HWND]
user32.IsIconic.argtypes = [wt.HWND]
SW_SHOWNORMAL = 1


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


def close_client(timeout: float = 8.0, only: set[int] | None = None) -> int:
    """关闭 MonkeyCode 客户端，返回关掉的进程数。

    顺序：先 WM_CLOSE 让主窗口走正常退出（能存配置、不留脏状态），
    超时才对剩余进程 TerminateProcess。
    `only` 给出时只处理这些 PID（本次脚本拉起的实例），
    否则会把用户中途自己打开的同名客户端一起关掉。
    """
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    WNDENUMPROC = ctypes.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM)
    pids = set(proc_pids(PROC))
    if only is not None:
        pids &= only
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
        if not (set(proc_pids(PROC)) & pids):
            return len(pids)
        time.sleep(0.5)
    for pid in (set(proc_pids(PROC)) & pids):     # 还剩的强杀
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

    # 绑输入队列后强切。除了目标线程，还要临时绑上**当前前台窗口**的线程：
    # Windows 的前台锁是按输入队列判定的，只绑目标线程往往仍被拒
    # （2026-10-18 远程会话实测：目标可见但被终端盖住，单绑目标线程失败）。
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    target_tid = user32.GetWindowThreadProcessId(hwnd, None)
    cur_tid = kernel32.GetCurrentThreadId()
    fg = int(user32.GetForegroundWindow() or 0)
    fg_tid = user32.GetWindowThreadProcessId(fg, None) if fg else 0
    attached_fg = False
    if fg_tid and fg_tid != cur_tid:
        attached_fg = bool(user32.AttachThreadInput(cur_tid, fg_tid, True))
    if target_tid:
        user32.AttachThreadInput(cur_tid, target_tid, True)
        user32.BringWindowToTop(hwnd)
        user32.ShowWindow(hwnd, SW_RESTORE)
        user32.SetForegroundWindow(hwnd)
        user32.AttachThreadInput(cur_tid, target_tid, False)
        time.sleep(0.5)
    if attached_fg:
        user32.AttachThreadInput(cur_tid, fg_tid, False)
    if not user32.IsWindowVisible(hwnd):
        return False
    return int(user32.GetForegroundWindow() or 0) == hwnd


def restore_foreground(prev_foreground: int) -> None:
    """把前台还给运行前的窗口，别让用户对着一个死掉的客户端。"""
    # 用户已经切走并在操作时不要再抢回来（二次打断比不还原更烦）。
    if user_idle_seconds() < 8:
        log("restore-foreground: 用户正在操作，跳过抢回前台")
        return
    fg = int(prev_foreground or user32.GetForegroundWindow() or 0)
    if fg and fg != CURRENT_HWND and user32.IsWindow(fg):
        try:
            user32.ShowWindow(fg, SW_RESTORE)
            user32.SetForegroundWindow(fg)
        except OSError:
            pass


def user_idle_seconds() -> int:
    li = LASTINPUTINFO()
    li.cbSize = ctypes.sizeof(LASTINPUTINFO)
    if not user32.GetLastInputInfo(ctypes.byref(li)):
        return 999999
    tick = int(kernel32.GetTickCount()) & 0xFFFFFFFF
    return int(((tick - int(li.dwTime)) & 0xFFFFFFFF) / 1000)


def user_idle_ms() -> int:
    li = LASTINPUTINFO()
    li.cbSize = ctypes.sizeof(LASTINPUTINFO)
    if not user32.GetLastInputInfo(ctypes.byref(li)):
        return 1000000
    tick = int(kernel32.GetTickCount()) & 0xFFFFFFFF
    return min(((tick - int(li.dwTime)) & 0xFFFFFFFF), 1000000)


def wait_input_quiet(quiet_ms: int = 320, max_wait_ms: int = 20000) -> bool:
    """点击前等主人停手。

    屏外识别可以全程不碰光标，但真实点击那一下必须占用鼠标。他正在拖动/连点时
    先等；停手后立刻点、点完立刻还原（见 real_click_at）。超时仍继续——漏签的
    代价比短暂借用光标大，但会留一行日志。
    """
    t0 = time.time()
    deadline = t0 + max_wait_ms / 1000.0
    logged = False
    while True:
        idle = user_idle_ms()
        if idle >= quiet_ms:
            if logged:
                log(f"input-quiet: 已静默 {idle}ms，开始点击（等了 {int((time.time() - t0) * 1000)}ms）")
            return True
        if not logged:
            log(f"input-quiet: 用户正在操作（idle={idle}ms），等键鼠停下再点（上限 {max_wait_ms}ms）")
            logged = True
        if time.time() >= deadline:
            log(f"input-quiet: 等待 {max_wait_ms}ms 仍有键鼠输入，按最小暴露继续")
            return False
        time.sleep(0.025)


def cursor_at(x: int, y: int) -> bool:
    p = _POINT()
    if not user32.GetCursorPos(ctypes.byref(p)):
        return False
    return p.x == int(x) and p.y == int(y)


def real_click_at(x: int, y: int) -> bool:
    """静默闸门 → 移动光标 → 核对仍在目标点 → 按下抬起 → 立刻还原光标。

    hover 的 120ms 里主人把鼠标挪走时，直接按下去会点到他当前所在的位置
    （可能点进别的窗口），所以按下前必须再核对一次；两次都不中就放弃。
    """
    if not wait_input_quiet():
        log("click: 用户持续操作，放弃本次真实点击")
        return False
    saved = _POINT()
    user32.GetCursorPos(ctypes.byref(saved))
    try:
        for attempt in (1, 2):
            if attempt == 2:
                if not wait_input_quiet():
                    log("click: 用户持续操作，放弃重试")
                    return False
            user32.SetCursorPos(int(x), int(y))
            time.sleep(0.12)
            if not cursor_at(x, y):
                log(f"click: 光标被挪走（attempt {attempt}），不盲点")
                continue
            # 等待期间点击位可能被新窗口盖住：按下去之前再核一次归属。
            if CURRENT_HWND and not client_owns_point(CURRENT_HWND, x, y):
                log(f"click: 点击位已被别的窗口占据（attempt {attempt}），放弃")
                return False
            user32.mouse_event(MOUSEEVENTF_LEFTDOWN, 0, 0, 0, 0)
            user32.mouse_event(MOUSEEVENTF_LEFTUP, 0, 0, 0, 0)
            return True
        return False
    finally:
        # 无论成功、放弃还是异常，光标立刻回原位（不再等外层 sleep）。
        try:
            user32.SetCursorPos(saved.x, saved.y)
        except OSError:
            pass


def wait_for_user_idle(timeout: int, threshold: int) -> bool:
    """等用户空闲 threshold 秒；超时仍活跃返回 False，调用方留 pending。"""
    idle = user_idle_seconds()
    if idle >= threshold:
        log(f"idle gate: idle={idle}s, proceed")
        return True
    log(f"idle gate: user active (idle={idle}s), wait up to {timeout}s")
    deadline = time.time() + timeout
    last_log = idle
    while time.time() < deadline:
        time.sleep(5)
        idle = user_idle_seconds()
        if idle >= threshold:
            log(f"idle gate: idle={idle}s, proceed")
            return True
        if idle - last_log >= 120:
            log(f"idle gate: still active (idle={idle}s)")
            last_log = idle
    log(f"idle gate: still active after {timeout}s; abort")
    return False


def _rect_close(r, w: int, h: int, tol: int = 4) -> bool:
    if not r:
        return False
    return abs((r.right - r.left) - w) <= tol and abs((r.bottom - r.top) - h) <= tol


def _restore_placement(hwnd: int, rect: RECT) -> bool:
    """把目标 rect 写进 WINDOWPLACEMENT.rcNormalPosition 再 SetWindowPlacement。"""
    wp = WINDOWPLACEMENT()
    wp.length = ctypes.sizeof(WINDOWPLACEMENT)
    if not user32.GetWindowPlacement(wt.HWND(hwnd), ctypes.byref(wp)):
        return False
    wp.showCmd = SW_SHOWNORMAL
    wp.rcNormalPosition = rect
    return bool(user32.SetWindowPlacement(wt.HWND(hwnd), ctypes.byref(wp)))


def restore_rect(hwnd: int, rect: RECT) -> None:
    """还原窗口位置 + 尺寸，并读回校验。

    2026-11-13（与 Qoder 同款坑）：SetWindowPos 在 Electron/Tauri 窗口上可能只挪位置、
    宽高被丢掉，窗口留下一条细缝；下一轮又把细缝当成 ORIG_RECT，永远修不回来。
    这里四步递进、每步校验，最后兜底夹进屏幕给一个能用的尺寸。
    """
    w = rect.right - rect.left
    h = rect.bottom - rect.top
    if w <= 0 or h <= 0:
        return
    hp = wt.HWND(hwnd)
    if user32.IsZoomed(hp) or user32.IsIconic(hp):
        user32.ShowWindow(hp, SW_RESTORE)
        time.sleep(0.4)
    user32.SetWindowPos(hp, None, rect.left, rect.top, w, h,
                        SWP_NOZORDER | SWP_NOACTIVATE)
    time.sleep(0.3)
    cur = win_rect(hwnd)
    if _rect_close(cur, w, h):
        log(f"restore-rect: now {cur.left},{cur.top} {cur.right-cur.left}x{cur.bottom-cur.top}")
        return
    got = "?" if not cur else f"{cur.right-cur.left}x{cur.bottom-cur.top}"
    log(f"restore-rect: 首试没到位 ({got})，改用 SetWindowPlacement")
    _restore_placement(hwnd, rect)
    time.sleep(0.35)
    cur = win_rect(hwnd)
    if _rect_close(cur, w, h):
        log(f"restore-rect: placement ok {cur.left},{cur.top} {cur.right-cur.left}x{cur.bottom-cur.top}")
        return
    log("restore-rect: 仍不到位，改「先定尺寸再挪位」")
    user32.SetWindowPos(hp, None, 0, 0, w, h, SWP_NOZORDER | SWP_NOACTIVATE)
    time.sleep(0.25)
    user32.SetWindowPos(hp, None, rect.left, rect.top, 0, 0,
                        SWP_NOSIZE | SWP_NOZORDER | SWP_NOACTIVATE)
    time.sleep(0.25)
    cur = win_rect(hwnd)
    if _rect_close(cur, w, h):
        log(f"restore-rect: two-step ok {cur.left},{cur.top} {cur.right-cur.left}x{cur.bottom-cur.top}")
        return
    sw, sh = user32.GetSystemMetrics(0), user32.GetSystemMetrics(1)
    w2 = max(900, min(w, sw - 160))
    h2 = max(600, min(h, sh - 160))
    x2 = max(8, min(rect.left, sw - w2 - 8))
    y2 = max(8, min(rect.top, sh - h2 - 8))
    log(f"restore-rect: 兜底夹进屏幕 {x2},{y2} {w2}x{h2}")
    user32.SetWindowPos(hp, None, x2, y2, w2, h2, SWP_NOZORDER | SWP_NOACTIVATE)
    time.sleep(0.3)
    cur = win_rect(hwnd)
    log(f"restore-rect: now {cur.left},{cur.top} {cur.right-cur.left}x{cur.bottom-cur.top} "
        f"(expect {rect.left},{rect.top} {w}x{h})")


def sane_rect(hwnd: int, r):
    """把「细缝 rect」修成 placement 里记着的正常 rect。

    2026-11-13：上一轮异常退出可能把窗口留在 12px 宽的细缝上。直接把它当
    ORIG_RECT/PARK_RECT，就等于忠实还原一条缝，永远修不回来。
    """
    if not r:
        return r
    w, h = r.right - r.left, r.bottom - r.top
    if w >= 600 and h >= 400:
        return r
    wp = WINDOWPLACEMENT()
    wp.length = ctypes.sizeof(WINDOWPLACEMENT)
    if user32.GetWindowPlacement(wt.HWND(hwnd), ctypes.byref(wp)):
        n = wp.rcNormalPosition
        if (n.right - n.left) >= 600 and (n.bottom - n.top) >= 400:
            log(f"orig-rect: 细缝 {w}x{h}，改用 placement 正常态 "
                f"{n.right-n.left}x{n.bottom-n.top}")
            return n
    return r


def park_offscreen(hwnd: int, record: bool = False) -> None:
    """把窗口停到主屏左界外，只留 OFFSCREEN_STRIP 像素窄边。

    窄边留给 DWM/WebView2 继续合成；UIA 探针用 -AllowOffscreen 忽略
    IsOffscreen，因此窗口屏外也能定位控件。
    """
    global PARK_RECT, WAS_MAXIMIZED
    # 先还原最大化：最大化窗口移到屏外后，SetForegroundWindow 会触发
    # Windows/Electron 还原成 normal rect，坐标与 UIA 探针不一致（见 PARK_RECT 注释）。
    if not WAS_MAXIMIZED and user32.IsZoomed(hwnd):
        WAS_MAXIMIZED = True
        user32.ShowWindow(hwnd, SW_RESTORE)
        time.sleep(0.4)
    r = win_rect(hwnd)
    if not r:
        return
    # 只有第一次（窗口还在屏内）记录正常态 rect；后续重复 park 时窗口已在屏外，
    # 记下来会把 PARK_RECT 写成屏外坐标，bringback 又被钳回屏幕边缘。
    if record:
        PARK_RECT = sane_rect(hwnd, r)
    w, h = r.right - r.left, r.bottom - r.top
    if w <= 0 or h <= 0:
        return
    user32.SetWindowPos(wt.HWND(hwnd), None, OFFSCREEN_STRIP - w, 0, 0, 0,
                        SWP_NOSIZE | SWP_NOZORDER | SWP_NOACTIVATE)
    time.sleep(0.3)


def bringback_click(hwnd: int, screen_x: int, screen_y: int, what: str) -> bool:
    """屏外模式下只把窗口移回屏内点击一下，随后立刻停回屏外。

    点击目标坐标来自屏外 UIA 探针（屏幕坐标）；先用当前窗口原点换算成
    客户区相对坐标，再把窗口移回原 rect 后点同一相对位置。
    """
    cur = win_rect(hwnd)
    if not cur:
        return False
    client_x = screen_x - cur.left
    client_y = screen_y - cur.top
    log(f"bringback: target screen=({screen_x},{screen_y}) parked rect="
        f"{cur.left},{cur.top} {cur.right - cur.left}x{cur.bottom - cur.top}")
    target = PARK_RECT or ORIG_RECT or cur
    sw, sh = user32.GetSystemMetrics(0), user32.GetSystemMetrics(1)
    w, h = target.right - target.left, target.bottom - target.top
    # 2026-10-25：按「窗口左上角」钳制不够——MonkeyCode 冷启动后窗口高 2192px，
    # 比 2160px 的屏幕还高，设置/签到按钮在 client y≈2038，窗口一放回原位
    # 点击点就落到 y=2185（屏幕外），client_owns_point 必然失败。改为按**点击点**
    # 钳制到工作区（排除任务栏），允许标题栏暂时移出屏幕上缘；只暴露一次点击的时间。
    work = RECT()
    if not user32.SystemParametersInfoW(0x0030, 0, ctypes.byref(work), 0):
        work = RECT(0, 0, sw, sh)
    min_tx = work.left - client_x
    max_tx = max(min_tx, work.right - 1 - client_x)
    min_ty = work.top - client_y
    max_ty = max(min_ty, work.bottom - 1 - client_y)
    tx = max(min_tx, min(target.left, max_tx))
    ty = max(min_ty, min(target.top, max_ty))
    prev_fg = int(user32.GetForegroundWindow() or 0)
    saved = _POINT()
    user32.GetCursorPos(ctypes.byref(saved))
    try:
        log(f"bringback: {what} client=({client_x},{client_y}) -> visible {tx},{ty}")
        user32.SetWindowPos(wt.HWND(hwnd), None, tx, ty, 0, 0,
                            SWP_NOSIZE | SWP_NOZORDER | SWP_NOACTIVATE)
        user32.ShowWindow(hwnd, SW_SHOW)
        # 2026-10-25：前台锁/置顶窗口会让「移回屏内」仍被盖住（实测 rect 已正确
        # 但 WindowFromPoint 命中别人）。和 Trae/AutoClaw 同口径：点击前临时提为
        # TOPMOST（SWP_NOACTIVATE，不抢焦点），点完立刻降回。
        user32.SetWindowPos(wt.HWND(hwnd), wt.HWND(HWND_TOPMOST), tx, ty, 0, 0,
                            SWP_NOSIZE | SWP_NOACTIVATE)
        time.sleep(0.3)
        # 2026-10-25：这里不再调 ensure_foreground —— 它为了绕前台锁会按 Alt 再切，
        # 在本机实测会把 Windows 壳层的「Shell_SystemDim」遮罩拉起来，反遮挡检查
        # 于是看到顶层是 explorer 的 dim 窗（不是客户端），永远放弃点击。
        # TOPMOST 已经足够让窗口出现在最上层并接收真实点击（点击本身会激活它），
        # 收尾 restore_foreground 会把前台还回去。
        if not user32.IsWindowVisible(hwnd):
            log("bringback: window not visible after raise; skip")
            return False
        r = win_rect(hwnd)
        log(f"bringback: rect now {r.left},{r.top} {r.right - r.left}x{r.bottom - r.top} (want {tx},{ty})")
        sx, sy = r.left + client_x, r.top + client_y
        if not client_owns_point(hwnd, sx, sy):
            pt = _POINT(sx, sy)
            top = int(user32.WindowFromPoint(pt) or 0)
            root = int(user32.GetAncestor(top, GA_ROOT) or 0) if top else 0
            log(f"bringback: click point ({sx},{sy}) covered by another window; skip "
                f"(top={top} class={win_class(top) if top else ''} pid={win_pid(top) if top else 0} "
                f"root={root} fg={int(user32.GetForegroundWindow() or 0)} hwnd={hwnd})")
            return False
        if real_click_at(sx, sy):
            log(f"bringback: real click {what} @ {sx},{sy}")
        else:
            log(f"bringback: 光标两次被挪走，放弃点击 {what}")
            return False
        time.sleep(0.4)
        return True
    finally:
        try:
            user32.SetCursorPos(saved.x, saved.y)
        except OSError:
            pass
        # 摘掉 TOPMOST，避免窗口日后回屏内时一直钉在最上层
        try:
            user32.SetWindowPos(wt.HWND(hwnd), wt.HWND(HWND_NOTOPMOST), 0, 0, 0, 0,
                                SWP_NOSIZE | SWP_NOMOVE | SWP_NOACTIVATE)
        except OSError:
            pass
        park_offscreen(hwnd)
        restore_foreground(prev_fg)


def _cleanup(launched_by_us: bool, prev_foreground: int) -> None:
    """运行结束一律恢复现场。

    1) 只关**本次由脚本拉起**的实例——签到前就开着的必须保留
       （那是主人自己开的，可能是他正在用的工作窗口）；
    2) 把前台还给运行前的窗口。

    失败时也要清：无人值守跑完桌面不该堆着客户端。
    这个逻辑对齐 ui_claim_autoclaw.ps1 的 $script:LaunchedByUs
    与 ui_claim_trae.ps1 的 taskkill 收尾。
    """
    # 2026-11-13：不管是不是我们拉起的，关窗前都要先还原 rect / 最大化态——
    # Tauri/Electron 会把窗口位置写进自己的状态文件，带着屏外条带关掉，下次冷启动
    # 就在屏外开窗（「防 Electron 持久化屏外位置」就是这条）。
    if CURRENT_HWND and ORIG_RECT:
        try:
            restore_rect(CURRENT_HWND, ORIG_RECT)
            # 停放前若窗口是最大化，收尾恢复最大化状态，别把主人的窗口留成还原态
            if WAS_MAXIMIZED:
                user32.ShowWindow(CURRENT_HWND, SW_MAXIMIZE)
                time.sleep(0.2)
            log("cleanup: restored original window rect"
                + (" (maximized)" if WAS_MAXIMIZED else ""))
        except OSError as exc:
            log(f"cleanup: restore window rect failed: {exc}")
    if launched_by_us:
        n = close_client(only=LAUNCHED_PIDS)
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
    # 2026-10-30：走统一的「等主人停手 → 点 → 立刻还原光标」路径。
    if not real_click_at(x, y):
        log(f"click: 光标两次被挪走，放弃点击 @ {x},{y}")
    time.sleep(0.5)


def ensure_visible(hwnd: int) -> None:
    """把窗口显示/还原出来，但**不要求它在前台**。

    UIA 定位 + OS 点击不需要前台：只需要窗口可见，且点击点没有被别的窗口盖住
    （由 client_owns_point 单独校验）。远程桌面/后台会话里
    SetForegroundWindow 经常被前台锁拒绝，以前整条 UI 路径就卡死在那里；
    现在（2026-10-18）改由 UIA 主路承担，前台不再是非要不可的条件。
    """
    if not user32.IsWindowVisible(hwnd):
        user32.ShowWindow(hwnd, SW_SHOW)
        time.sleep(0.5)
    if user32.IsIconic(hwnd):
        user32.ShowWindow(hwnd, SW_RESTORE)
        time.sleep(0.4)


def uia_probe(hwnd: int, timeout: float = 40.0, allow_offscreen: bool = False) -> dict | None:
    """跑 PowerShell UIA 探针，返回它写的状态 JSON；失败返回 None。

    探针只读可访问树，不点击。按控件名（设置/账号/签到/微信扫码登录）
    定位，因此与分辨率、DPI 缩放、窗口比例都无关。
    """
    if not UIA_SCRIPT.is_file():
        return None
    try:
        if UIA_RESULT.exists():
            UIA_RESULT.unlink()
    except OSError:
        pass
    cmd = [
        "powershell", "-NoProfile", "-ExecutionPolicy", "Bypass",
        "-WindowStyle", "Hidden", "-File", str(UIA_SCRIPT),
        "-Hwnd", str(int(hwnd)), "-OutFile", str(UIA_RESULT),
    ]
    if allow_offscreen:
        cmd.append("-AllowOffscreen")
    try:
        subprocess.run(cmd, capture_output=True, timeout=timeout)
    except (subprocess.SubprocessError, OSError) as e:  # noqa: BLE001
        log(f"uia probe failed: {e}")
        return None
    try:
        payload = json.loads(UIA_RESULT.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def uia_click(hwnd: int, target: dict, what: str, offscreen: bool = False) -> bool:
    """按 UIA 给出的屏幕坐标点击，并先确认该点确实属于本客户端。

    屏外模式下坐标是屏外屏幕坐标，不能直接点：短暂 bringback 到原 rect
    点一下再停回屏外；点击前再查一次用户空闲，活跃就放弃本次点击。

    非屏外模式仍用 OS 级 mouse_event 而不是 InvokePattern：WebView2 前端可能把
    isTrusted=false 的脚本层调用过滤掉（MiniMax 已实证）。UIA 只负责
    「控件在哪」，点击仍走真实输入队列。
    """
    try:
        x, y = int(target["x"]), int(target["y"])
    except (KeyError, TypeError, ValueError):
        log(f"uia: {what} target missing coordinates")
        return False
    if offscreen:
        if not SKIP_CLICK_IDLE and user_idle_seconds() < IDLE_THRESHOLD_SEC:
            log(f"uia: {what}: user became active; skip bringback click")
            return False
        return bringback_click(hwnd, x, y, what)
    if not client_owns_point(hwnd, x, y):
        log(f"uia: {what} at ({x},{y}) is covered by another window; refuse to click")
        return False
    log(f"uia: click {what} at ({x},{y})")
    click(x, y)
    return True


def uia_claim_flow(hwnd: int, offscreen: bool = False) -> tuple[str, str] | None:
    """UIA 主路：打开设置 → 账号页 → 签到。

    返回 (status, detail)，status ∈ already | claimed | clicked |
    login_required | pending；None 表示 UIA 不可用，调用方回落到像素路径。

    登录页识别是这里的硬闸门：只要出现「用微信扫一扫登录 / 微信扫码 /
    扫码登录」，立刻返回 login_required，绝不在登录页上点任何坐标。

    offscreen=True 时窗口先停到屏外条带；UIA 探针用 -AllowOffscreen，
    只有真正点击时才短暂 bringback 到原 rect。
    """
    if os.environ.get("AGENT_CREDIT_MONKEY_NO_UIA", "").strip().lower() in ("1", "true", "yes"):
        log("uia: disabled by AGENT_CREDIT_MONKEY_NO_UIA")
        return None

    ensure_visible(hwnd)
    if offscreen:
        park_offscreen(hwnd)
        log("uia: offscreen mode; window parked, probe allows offscreen elements")
    else:
        # 前台不是硬条件（点击前还有 ownership 校验），但能拿到就拿：
        # 远程会话里窗口常被终端盖住，拿到前台才点得到。
        if not ensure_foreground(hwnd):
            log("uia: foreground not acquired; clicks will still be ownership-checked")
    tried_connect = False
    account_clicks = 0
    for _ in range(8):
        probe = uia_probe(hwnd, allow_offscreen=offscreen)
        if not probe:
            log("uia: probe unavailable; falling back to pixel path")
            return None
        state = probe.get("state")
        log(f"uia: state={state} count={probe.get('count')}")

        if state == "account":
            if probe.get("already"):
                name = probe.get("claim_name") or "今日已签到"
                return "already", f"UIA 确认今日已签到（{name}）"
            if not uia_click(hwnd, probe.get("claim") or {}, "签到", offscreen=offscreen):
                return "pending", "UIA 找到签到按钮但点击被遮挡或用户活跃，未入账"
            time.sleep(1.5)
            after = uia_probe(hwnd, allow_offscreen=offscreen)
            if after and after.get("state") == "account" and after.get("already"):
                return "claimed", "UIA 点击后在界面确认「今日已签到」"
            return "clicked", "UIA 已点击签到，界面尚未确认"

        if state == "login":
            marker = probe.get("login_marker") or "微信扫码登录"
            log(f"uia: login marker detected: {marker}")
            return "login_required", f"检测到登录页（{marker}），登录态已失效，请扫码登录"

        if state == "closed":
            if not uia_click(hwnd, probe.get("settings") or {}, "设置", offscreen=offscreen):
                return "pending", "UIA 找到设置按钮但点击被遮挡或用户活跃，未入账"
            time.sleep(1.5)
            continue

        if state == "other":
            # 2026-10-26：会话过期后账号页没有「签到」，只有一个绿色「连接」按钮。
            # 主人实测点一下就能恢复登录（客户端随之回写 cookies.json），
            # 所以这里是明确的恢复动作，不是重试噪声；每轮只点一次。
            connect = probe.get("connect")
            if connect and not tried_connect:
                tried_connect = True
                log("uia: session looks disconnected; clicking 连接")
                if not uia_click(hwnd, connect, "连接", offscreen=offscreen):
                    return "pending", "UIA 找到「连接」按钮但点击被遮挡或用户活跃，未入账"
                time.sleep(3.0)
                continue
            if account_clicks < 2:
                account_clicks += 1
                if not uia_click(hwnd, probe.get("account_nav") or {}, "账号", offscreen=offscreen):
                    return "pending", "UIA 未能打开账号页（导航按钮被遮挡或用户活跃）"
                time.sleep(1.2)
                continue
            return "pending", ("账号页没有签到入口：已尝试「连接」与「账号」仍未出现签到按钮；"
                               "多半是登录态失效。请在客户端点绿色「连接」完成授权后重跑")

        return None
    return "pending", "UIA 在等待时间内未进入账号页（面板可能停在未连接/其它页）"


def looks_like_login_page(img) -> bool:
    """像素兜底用的登录页识别：找一块大的高密度深色方块（二维码）。

    为什么不能只看绿色：登录页有绿色竖分隔条和绿色状态点，旧 green 判据
    会把它算成 200（账号页约 120），于是误以为账号页已开。
    这里按粗网格统计深色占比，取最大连通块；二维码约 6x6 个格子，
    普通标题文字/黑色按钮达不到这个规模。
    """
    p, w, h = img
    x0, x1 = int(w * 0.40), int(w * 0.85)
    y0, y1 = int(h * 0.25), int(h * 0.75)
    cell = max(12, int(min(w, h) / 45))
    cols = max(1, (x1 - x0) // cell)
    rows = max(1, (y1 - y0) // cell)
    if cols < 4 or rows < 4:
        return False
    step = max(1, cell // 5)

    light = 0
    total = 0
    grid = [[False] * cols for _ in range(rows)]
    for gy in range(rows):
        for gx in range(cols):
            dark = 0
            n = 0
            for y in range(y0 + gy * cell, min(y0 + (gy + 1) * cell, y1), step):
                base = y * w
                for x in range(x0 + gx * cell, min(x0 + (gx + 1) * cell, x1), step):
                    o = (base + x) * 4
                    b_, g_, r_ = p[o], p[o + 1], p[o + 2]
                    n += 1
                    if r_ < 90 and g_ < 90 and b_ < 90:
                        dark += 1
                    if r_ > 200 and g_ > 200 and b_ > 200:
                        light += 1
                    total += 1
            grid[gy][gx] = n > 0 and dark >= n * 0.35

    # 深色主题/全黑画面不是「登录页」，别误报
    if total == 0 or light < total * 0.30:
        return False

    best = 0
    best_w = best_h = 0
    seen = [[False] * cols for _ in range(rows)]
    for gy in range(rows):
        for gx in range(cols):
            if not grid[gy][gx] or seen[gy][gx]:
                continue
            stack = [(gy, gx)]
            seen[gy][gx] = True
            n = 0
            min_y = max_y = gy
            min_x = max_x = gx
            while stack:
                cy, cx = stack.pop()
                n += 1
                min_y, max_y = min(min_y, cy), max(max_y, cy)
                min_x, max_x = min(min_x, cx), max(max_x, cx)
                for dy, dx in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                    ny, nx = cy + dy, cx + dx
                    if 0 <= ny < rows and 0 <= nx < cols and grid[ny][nx] and not seen[ny][nx]:
                        seen[ny][nx] = True
                        stack.append((ny, nx))
            if n > best:
                best = n
                best_w, best_h = max_x - min_x + 1, max_y - min_y + 1
    log(f"login-page check: dark-block cells={best} box={best_w}x{best_h}")
    # 二维码是「又大又方」的深色块；整行文字是 1 格高，不满足。
    return best >= 10 and best_w >= 4 and best_h >= 4


def api_checked_in(jar: str) -> bool:
    """GET /wallet/checkin，返回服务端是否已签到。异常由调用方处理。"""
    import urllib.request
    req = urllib.request.Request(
        "https://monkeycode-ai.com/api/v1/users/wallet/checkin",
        headers={"Accept": "application/json", "Cookie": jar,
                 "User-Agent": "monkeycode-ui-claim/1.0"})
    with urllib.request.urlopen(req, timeout=20) as resp:
        return bool((json.loads(resp.read().decode("utf-8")).get("data") or {})
                    .get("checked_in"))


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
    global IDLE_THRESHOLD_SEC, SKIP_CLICK_IDLE, CURRENT_HWND, ORIG_RECT
    ap = argparse.ArgumentParser()
    ap.add_argument("--explore", action="store_true", help="只截图，不点击")
    ap.add_argument("--steps", type=int, default=0,
                    help="explore 模式下先执行前 N 步导航再截图（用于观察深层页面）")
    ap.add_argument("--force", action="store_true", help="即使接口显示已签也照点（调试用）")
    ap.add_argument("--settle", type=int, default=20)
    ap.add_argument("--ink-min", type=int, default=INK_MIN_DEFAULT,
                    help="webview 渲染就绪阈值（content_ink 千分比）。空白窗口约 40，"
                         "画完的工作台远高于此；用 --explore 观察 content_ink 曲线即可标定")
    ap.add_argument("--no-offscreen", action="store_true",
                    help="不把窗口停到屏外（旧行为，会显示窗口）")
    ap.add_argument("--no-idle-gate", action="store_true",
                    help="跳过用户空闲闸门（仅调试用）")
    ap.add_argument("--idle-wait", type=int, default=IDLE_WAIT_SEC,
                    help="等待用户空闲的上限秒数")
    ap.add_argument("--idle-threshold", type=int, default=IDLE_THRESHOLD_SEC,
                    help="判定空闲所需的秒数")
    args = ap.parse_args()
    ink_min = args.ink_min
    IDLE_THRESHOLD_SEC = args.idle_threshold
    SKIP_CLICK_IDLE = bool(args.no_idle_gate)
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

    offscreen = not args.explore and not args.no_offscreen
    if not args.explore and not args.no_idle_gate:
        if not wait_for_user_idle(args.idle_wait, args.idle_threshold):
            log("user active; aborting before launching any client")
            write_result("pending",
                         "用户正在使用电脑（空闲未达阈值）；MonkeyCode 未启动/未点击，不入账")
            return 2

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
                LAUNCHED_PIDS.update(pids)
                log(f"pid appeared after {time.time()-t0:.0f}s")
                break
    early_hwnd = find_main(pids)
    if early_hwnd and offscreen:
        CURRENT_HWND = early_hwnd
        ORIG_RECT = sane_rect(early_hwnd, win_rect(early_hwnd))
        ensure_visible(early_hwnd)
        park_offscreen(early_hwnd, record=True)
        log("offscreen: parked before settle")

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
    if offscreen:
        if CURRENT_HWND != hwnd:
            if CURRENT_HWND and ORIG_RECT:
                try:
                    restore_rect(CURRENT_HWND, ORIG_RECT)
                except OSError:
                    pass
            CURRENT_HWND = hwnd
            ORIG_RECT = sane_rect(hwnd, win_rect(hwnd))
        ensure_visible(hwnd)
        park_offscreen(hwnd, record=(PARK_RECT is None))

    # ---- UIA 主路（2026-10-18）----
    # 按控件名定位，不再依赖窗口比例/DPI；也不要求窗口在前台。
    # 登录页在这里就是硬闸门：识别到扫码登录页立刻退出，绝不在上面点击。
    # 只有探针不可用（PowerShell/UIA 异常、脚本缺失）才回落到下面的像素路径。
    if not args.explore:
        uia_outcome = uia_claim_flow(hwnd, offscreen=offscreen)
        if uia_outcome is not None:
            uia_status, uia_detail = uia_outcome
            if uia_status in ("already", "claimed", "clicked"):
                # 界面证据只进 detail；是否入账仍以接口为准（项目硬规则）。
                try:
                    api_ok = api_checked_in(jar)
                except Exception as e:  # noqa: BLE001
                    api_ok = False
                    uia_detail += f"；接口复核失败: {e}"
                if api_ok:
                    status = "already" if uia_status == "already" else "ok"
                    detail = f"{uia_detail}；接口确认 checked_in=true"
                else:
                    status = "pending"
                    detail = f"{uia_detail}；接口未确认，不入账"
            else:
                status, detail = "pending", uia_detail
            _cleanup(launched_by_us, prev_foreground)
            write_result(status, detail)
            log(f"result status={status} detail={detail}")
            return 0 if status in ("ok", "already") else 2
        if offscreen:
            log("uia unavailable; offscreen mode refuses visible pixel fallback")
            _cleanup(launched_by_us, prev_foreground)
            write_result("pending",
                         "UIA 不可用；屏外模式不回退到可见像素路径（可用 --no-offscreen 强制旧路径）")
            return 2

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
        return 2
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
        return 2

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
            return 2
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
            return 2

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
            return 2

        # 登录页闸门（像素兜底）：登录页也带绿色分隔条/绿点，green 判据会误判成
        # 账号页。这里再找二维码的大块深色连通区；命中就绝不点签到。
        if looks_like_login_page((px, w, h)):
            write_png(LOGDIR / "_monkey_account.png", px, w, h)
            write_result("pending",
                         "检测到二维码登录页（登录态已失效），未点击签到，不入账")
            log("result status=pending detail=login page detected")
            return 2

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
    return 0 if status in ("ok", "already") else (2 if status == "pending" else 1)


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
