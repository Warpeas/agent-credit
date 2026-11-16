#!/usr/bin/env python3
"""AutoClaw 积分明细页只读采集 v2 —— 「获得」过滤 + 分页采全。

v1 结论：余额数字点击 → /settings/credits 成功；但默认「全部」页签下消耗条目
太多，8 格滚轮到不了「加载更多」，ESC 也关不掉设置页（要用「返回」按钮）。
本版：进页后点「获得」过滤（服务端 flowDirection=earn，条目少一半以上），
大幅滚动 + 反复点「加载更多」，直到「没有更多了」或连续两帧无变化。

只点四类目标：余额数字、「获得」过滤、「加载更多」、「返回」。绝不点
签到/领取/兑换/充值/购买/立即/确认/提交/删除（含「兑换码」「去购买」「刷新」不碰）。
输出：logs/autoclaw_credits/g2_*.png + logs/autoclaw_credits_capture2.json
"""
from __future__ import annotations

import atexit
import ctypes
import ctypes.wintypes as wt
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LOGDIR = ROOT / "logs"
OUTDIR = LOGDIR / "autoclaw_credits"
_EXE_CANDIDATES = (
    str(Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "AutoClaw2" / "AutoClaw2.exe"),
    r"C:\Users\Hunter\AppData\Local\Programs\AutoClaw2\AutoClaw2.exe",
)
EXE = next((p for p in _EXE_CANDIDATES if p and Path(p).exists()), _EXE_CANDIDATES[-1])
PROC = "AutoClaw2.exe"
RESULT = LOGDIR / "autoclaw_credits_capture2.json"

sys.path.insert(0, str(Path(__file__).parent))
from forensics_lobster_windows import (  # noqa: E402
    enum_windows, proc_pids, win_class, win_pid, win_rect, write_png,
)
from ocr_image import ocr_lines  # noqa: E402

user32 = ctypes.WinDLL("user32", use_last_error=True)
gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)
user32.SetProcessDPIAware()
MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004
MOUSEEVENTF_WHEEL = 0x0800
KEYEVENTF_KEYUP = 0x0002
SW_RESTORE = 9
SRCCOPY = 0x00CC0020
HWND_TOPMOST = -1
HWND_NOTOPMOST = -2
SWP_NOMOVE = 0x0002
SWP_NOSIZE = 0x0001
SWP_NOACTIVATE = 0x0010
SWP_NOZORDER = 0x0004

# 本次运行改动过的现场：窗口 rect/最大化/最小化、光标、前台、自己拉起的 PID。
# 所有退出路径（正常返回/异常/KeyboardInterrupt）都走 atexit 还原。
_SCENE: dict = {"hwnd": 0, "place": None, "cursor": None, "fg": 0, "launched_pid": 0}


class _LASTINPUTINFO(ctypes.Structure):
    _fields_ = [("cbSize", wt.UINT), ("dwTime", wt.DWORD)]


def _idle_seconds() -> int:
    """键盘鼠标空闲秒数：收尾时用户已回到电脑前就别再抢前台/挪光标。"""
    li = _LASTINPUTINFO()
    li.cbSize = ctypes.sizeof(_LASTINPUTINFO)
    if not user32.GetLastInputInfo(ctypes.byref(li)):
        return 999999
    tick = ctypes.windll.kernel32.GetTickCount()
    return int(((tick - li.dwTime) & 0xFFFFFFFF) / 1000)


def _cursor_pos() -> tuple[int, int] | None:
    p = wt.POINT()
    if user32.GetCursorPos(ctypes.byref(p)):
        return (int(p.x), int(p.y))
    return None


def _window_place(hwnd: int) -> dict | None:
    r = win_rect(hwnd)
    if not r:
        return None
    return {
        "rect": (int(r.left), int(r.top), int(r.right - r.left), int(r.bottom - r.top)),
        "max": bool(user32.IsZoomed(hwnd)),
        "min": bool(user32.IsIconic(hwnd)),
    }


def _restore_scene() -> None:
    """收尾：窗口尺寸/位置/三态 → 前台 → 光标 → 关掉自己拉起的实例。"""
    try:
        hwnd = _SCENE.get("hwnd") or 0
        place = _SCENE.get("place")
        if hwnd and place:
            left, top, width, height = place["rect"]
            user32.SetWindowPos(hwnd, 0, left, top, width, height,
                                SWP_NOZORDER | SWP_NOACTIVATE)
            if place["max"]:
                user32.ShowWindow(hwnd, 3)      # SW_MAXIMIZE
            elif place["min"]:
                user32.ShowWindow(hwnd, 6)      # SW_MINIMIZE
        # 用户已经回来操作时，抢前台/挪光标比不还原更烦，只还原窗口本身。
        if _idle_seconds() >= 8:
            fg = _SCENE.get("fg") or 0
            if fg and user32.GetForegroundWindow() != fg:
                user32.SetForegroundWindow(fg)
            cur = _SCENE.get("cursor")
            if cur:
                user32.SetCursorPos(int(cur[0]), int(cur[1]))
        log("cleanup: restored window/cursor/foreground")
    except Exception as e:  # noqa: BLE001
        log(f"cleanup scene failed: {e}")
    pid = _SCENE.get("launched_pid") or 0
    if pid:
        try:
            subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"],
                           capture_output=True, timeout=20)
            log(f"cleanup: closed client we launched (pid={pid})")
        except (subprocess.SubprocessError, OSError) as e:
            log(f"cleanup close failed: {e}")


atexit.register(_restore_scene)

FORBIDDEN = ("签到", "领取", "兑换", "充值", "购买", "立即", "确认", "提交", "删除")
NUM_RE = re.compile(r"^[0-9OolI,，.]+$")


def log(m: str) -> None:
    s = time.strftime("%H:%M:%S") + " " + m
    try:
        with open(LOGDIR / "_ac_credits_capture.log", "a", encoding="utf-8") as f:
            f.write(s + "\n")
    except OSError:
        pass
    print(s, flush=True)


def safe(text: str) -> bool:
    return not any(b in text for b in FORBIDDEN)


def find_main(pids: set[int]) -> int:
    best, area = 0, 0
    for h in enum_windows():
        if win_pid(h) not in pids or win_class(h) == "Chrome_WidgetWin_0":
            continue
        r = win_rect(h)
        if not r:
            continue
        a = (r.right - r.left) * (r.bottom - r.top)
        if a >= 200000 and a > area:
            best, area = h, a
    return best


def bring_back(hwnd: int) -> None:
    user32.ShowWindow(hwnd, SW_RESTORE)
    user32.keybd_event(0x12, 0, 0, 0)
    user32.SetForegroundWindow(hwnd)
    user32.keybd_event(0x12, 0, KEYEVENTF_KEYUP, 0)
    user32.SetWindowPos(hwnd, HWND_TOPMOST, 0, 0, 0, 0, SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE)
    time.sleep(0.4)
    user32.SetWindowPos(hwnd, HWND_NOTOPMOST, 0, 0, 0, 0, SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE)
    time.sleep(0.6)


def screen_shot(x: int, y: int, w: int, h: int):
    hdc = user32.GetDC(0)
    mem = gdi32.CreateCompatibleDC(hdc)
    bmp = gdi32.CreateCompatibleBitmap(hdc, w, h)
    gdi32.SelectObject(mem, bmp)
    gdi32.BitBlt(mem, 0, 0, w, h, hdc, x, y, SRCCOPY)

    class BIH(ctypes.Structure):
        _fields_ = [("biSize", wt.DWORD), ("biWidth", wt.LONG), ("biHeight", wt.LONG),
                    ("biPlanes", wt.WORD), ("biBitCount", wt.WORD),
                    ("biCompression", wt.DWORD), ("biSizeImage", wt.DWORD),
                    ("biXPelsPerMeter", wt.LONG), ("biYPelsPerMeter", wt.LONG),
                    ("biClrUsed", wt.DWORD), ("biClrImportant", wt.DWORD)]

    class BI(ctypes.Structure):
        _fields_ = [("bmiHeader", BIH), ("bmiColors", wt.DWORD * 3)]

    bi = BI()
    bi.bmiHeader.biSize = ctypes.sizeof(BIH)
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
    for _ in range(2):
        user32.mouse_event(MOUSEEVENTF_LEFTDOWN, 0, 0, 0, 0)
        time.sleep(0.05)
        user32.mouse_event(MOUSEEVENTF_LEFTUP, 0, 0, 0, 0)
        time.sleep(0.18)
    time.sleep(1.2)


def wheel(x: int, y: int, notches: int) -> None:
    user32.SetCursorPos(int(x), int(y))
    time.sleep(0.15)
    user32.mouse_event(MOUSEEVENTF_WHEEL, 0, 0, int(-120 * notches), 0)
    time.sleep(0.9)


def frame_sig(lines: list[dict]) -> str:
    return "|".join(f"{ln['text']}@{ln['x']},{ln['y']}" for ln in lines)


def main() -> int:
    OUTDIR.mkdir(exist_ok=True)
    pids = set(proc_pids(PROC))
    if not pids:
        log("launching AutoClaw")
        proc = subprocess.Popen([EXE], close_fds=True)
        _SCENE["launched_pid"] = int(proc.pid)
        t0 = time.time()
        while time.time() - t0 < 40:
            time.sleep(2)
            if proc_pids(PROC):
                break
        time.sleep(12)
    pids = set(proc_pids(PROC))
    if not pids:
        log("no process")
        return 1
    hwnd = find_main(pids)
    if not hwnd:
        log("no main window")
        return 1
    # 先记现场再动窗口：位置/尺寸/最大化/最小化、前台、光标。
    _SCENE["hwnd"] = hwnd
    _SCENE["place"] = _window_place(hwnd)
    _SCENE["fg"] = int(user32.GetForegroundWindow())
    _SCENE["cursor"] = _cursor_pos()
    bring_back(hwnd)
    r = win_rect(hwnd)
    X, Y, W, H = r.left, r.top, r.right - r.left, r.bottom - r.top
    log(f"hwnd={hwnd} RECT={X},{Y} {W}x{H}")

    frames = []

    def snap(tag: str) -> list[dict]:
        px, w, h = screen_shot(X, Y, W, H)
        p = OUTDIR / f"{tag}.png"
        write_png(p, px, w, h)
        lines = ocr_lines(p)
        log(f"{tag}: {len(lines)} lines")
        frames.append({"tag": tag, "png": str(p), "lines": lines})
        return lines

    lines = snap("g0_current")
    joined = "".join(ln["text"] for ln in lines)
    on_credits = "积分明细" in joined or "总积分" in joined

    if not on_credits:
        # 可能停在积分页中部（页顶标题在视口外）：先向上滚回页顶再判一次
        for _ in range(3):
            user32.SetCursorPos(int(X + W * 0.55), int(Y + H * 0.5))
            time.sleep(0.15)
            user32.mouse_event(MOUSEEVENTF_WHEEL, 0, 0, int(120 * 15), 0)
            time.sleep(0.9)
        lines = snap("g0b_top")
        joined = "".join(ln["text"] for ln in lines)
        on_credits = "积分明细" in joined or "总积分" in joined

    if not on_credits:
        # 从首页/聊天页进设置：点右上角余额数字（左段，避开「去购买」）
        chip = None
        for ln in lines:
            t = ln["text"].strip()
            if ln["y"] > H * 0.09 or ln["x"] < W * 0.68:
                continue
            if not safe(t) or not NUM_RE.match(t):
                continue
            digits = re.sub(r"[^0-9]", "", t.replace("，", ",").replace("O", "0").replace("o", "0"))
            if digits.isdigit() and int(digits) > 0 and ln["w"] < W * 0.15:
                chip = ln
                break
        if not chip:
            log("balance chip NOT found; abort")
            RESULT.write_text(json.dumps({"status": "no_chip", "frames": frames}, ensure_ascii=False, indent=2),
                              encoding="utf-8")
            return 2
        log(f"balance chip '{chip['text']}' @({chip['x']},{chip['y']})")
        click(X + chip["x"] + chip["w"] * 0.25, Y + chip["y"] + chip["h"] / 2)
        time.sleep(3.0)
        lines = snap("g1_credits")
        joined = "".join(ln["text"] for ln in lines)
        if "积分明细" not in joined and "总积分" not in joined:
            log("not on credits page; abort")
            RESULT.write_text(json.dumps({"status": "no_credits_page", "frames": frames}, ensure_ascii=False, indent=2),
                              encoding="utf-8")
            return 3

    # 1) 点「获得」过滤页签（精确等于「获得」的短行；「获得积分」是条目文案不是页签）
    earn_tab = next((ln for ln in lines
                     if ln["text"].strip() == "获得" and safe(ln["text"])), None)
    if earn_tab:
        log(f"click 获得 filter @({earn_tab['x']},{earn_tab['y']})")
        click(X + earn_tab["x"] + earn_tab["w"] / 2, Y + earn_tab["y"] + earn_tab["h"] / 2)
        time.sleep(2.5)
        lines = snap("g2_earn_filter")
    else:
        log("获得 tab not found; continue with current filter")

    # 2) 滚动 + 「加载更多」直到「没有更多了」/ 连续两帧无变化
    prev_sig = ""
    stable = 0
    no_more = False
    for rnd in range(1, 41):
        wheel(X + W * 0.55, Y + H * 0.60, 12)
        lines = snap(f"g3_r{rnd:02d}")
        joined = "".join(ln["text"] for ln in lines)
        if "没有更多了" in joined:
            no_more = True
            log(f"round {rnd}: 没有更多了 -> done")
            break
        more = next((ln for ln in lines if "加载更多" in ln["text"] and safe(ln["text"])), None)
        if more:
            log(f"round {rnd}: click 加载更多 @({more['x']},{more['y']})")
            click(X + more["x"] + more["w"] / 2, Y + more["y"] + more["h"] / 2)
            time.sleep(2.4)
            stable = 0
            continue
        sig = frame_sig(lines)
        if sig == prev_sig:
            stable += 1
            if stable >= 2:
                log(f"round {rnd}: frame stable twice without 加载更多 -> stop")
                break
        else:
            stable = 0
        prev_sig = sig

    # 3) 「返回」退出设置页
    back = next((ln for ln in lines if ln["text"].strip() == "返回" and safe(ln["text"])), None)
    if back:
        log(f"click 返回 @({back['x']},{back['y']})")
        click(X + back["x"] + back["w"] / 2, Y + back["y"] + back["h"] / 2)
        time.sleep(2.0)
    snap("g9_after_close")

    RESULT.write_text(json.dumps({
        "status": "ok",
        "no_more_seen": no_more,
        "note": "只点余额数字/获得过滤/加载更多/返回；未点任何改变账户状态的按钮",
        "forbidden_words": list(FORBIDDEN),
        "window": {"hwnd": hwnd, "rect": [X, Y, W, H]},
        "captured_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "frames": frames,
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    log(f"wrote {RESULT}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except SystemExit:
        raise
    except BaseException:
        import traceback
        tb = traceback.format_exc()
        try:
            with open(LOGDIR / "_ac_credits_capture.log", "a", encoding="utf-8") as f:
                f.write("EXCEPTION:\n" + tb + "\n")
        except OSError:
            pass
        print(tb, flush=True)
        raise SystemExit(1)
