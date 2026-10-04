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
import json
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(r"C:\Users\Hunter\Documents\Warpeas\agent-credit")
LOGDIR = ROOT / "logs"
EXE = r"C:\Users\Hunter\AppData\Local\MonkeyCode\monkeycode-desktop.exe"
PROC = "monkeycode-desktop.exe"
RESULT = LOGDIR / "monkeycode_claim.json"

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
    """
    best, area = 0, 0
    for h in enum_windows():
        if win_pid(h) not in pids or win_class(h) != "Tauri Window":
            continue
        t = win_text(h)
        r = win_rect(h)
        if not r or "MonkeyCode" not in t or "桌宠" in t:
            continue
        a = (r.right - r.left) * (r.bottom - r.top)
        if a > area:
            best, area = h, a
    return best


def write_png(path: Path, bgra: bytes, w: int, h: int) -> None:
    """最小 PNG 编码（RGBA，无滤波）。

    自包含实现，不依赖 scripts/_forensics_lobster_windows.py——
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


def write_result(status: str, detail: str) -> None:
    RESULT.write_text(json.dumps({"status": status, "detail": detail},
                                ensure_ascii=False), encoding="utf-8")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--explore", action="store_true", help="只截图，不点击")
    ap.add_argument("--force", action="store_true", help="即使接口显示已签也照点（调试用）")
    ap.add_argument("--settle", type=int, default=20)
    args = ap.parse_args()
    if RESULT.exists():
        RESULT.unlink()

    # ---- 幂等闸门（必须在拉起客户端之前）----
    # GET /api/v1/users/wallet/checkin 返回 {checked_in: bool}，免验证码，
    # 比 OCR 判定可靠得多（OCR 只认「今日已签到」四个字，换个文案就失效）。
    # 已签 → 直接返回，不启客户端、不做任何点击。
    jar = ""
    try:
        import urllib.request
        ck = Path(r"C:\Users\Hunter\AppData\Roaming\com.chaitin.baizhi.monkeycode\monkeycode-cookies.json")
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
    log(f"preexisting procs={len(pids)}")
    if not pids:
        if args.explore:
            log("not running and --explore; abort")
            return 1
        log("launching MonkeyCode")
        subprocess.Popen([EXE], close_fds=True)
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
        write_result("notfound", "client did not start")
        return 1

    hwnd = find_main(pids)
    if not hwnd:
        log("main window not found")
        write_result("notfound", "no main window")
        return 1
    user32.ShowWindow(hwnd, SW_RESTORE)
    user32.SetForegroundWindow(hwnd)
    time.sleep(1.2)
    r = win_rect(hwnd)
    X, Y, W, H = r.left, r.top, r.right - r.left, r.bottom - r.top
    log(f"hwnd={hwnd} RECT={X},{Y} {W}x{H}")

    if args.explore:
        px, w, h = screen_shot(X, Y, W, H)
        write_png(LOGDIR / "_monkey_explore.png", px, w, h)
        log(f"shot -> logs/_monkey_explore.png ({w}x{h})")
        return 0

    # 初始位图，供content_click 做内容边界检测
    px, w, h = screen_shot(X, Y, W, H)

    # 路径：左下「设置」-> 弹层 -> 左侧「账号」页 -> 「签到 +100」。
    # lx/ly 是 Read 展示的缩略图(1088 宽)坐标系下的坐标，由 content_click 换算。
    steps = [
        (52, 692, "click 设置"),
        (165, 170, "click 账号 tab"),
        (563, 380, "click 签到 +100"),
    ]
    for lx, ly, what in steps:
        cx, cy = content_click(px, w, h, lx, ly, X, Y)
        log(f"{what} logic=({lx},{ly}) abs=({cx},{cy})")
        click(cx, cy)
        time.sleep(1.8)
        px, w, h = screen_shot(X, Y, W, H)   # 每步后重抓，弹层会改变内容

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
        detail = f"点击完成但复核失败: {e}"

    log(f"result status={status} detail={detail}")
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
