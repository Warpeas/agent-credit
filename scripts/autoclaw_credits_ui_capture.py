#!/usr/bin/env python3
"""AutoClaw 积分明细页只读采集（2026-11-10）。

导航路径（2026-11-10 从客户端明文 dist 复核）：右上角余额数字是一个按钮
（surface header/credits，title=credits.detail，onClick 跳转 /settings/credits），
「去购买」是另一个按钮（onClick=buy）——本脚本只点余额数字本身，
且保留 probe_autoclaw_credits.py 的 FORBIDDEN 词闸门。

页面结构（zh i18n 实测）：「积分明细」标题 + 过滤页签 全部/消耗/获得 +
逐条流水（description / 时间 / 金额 / 「{{date}} 到期」）+ 「加载更多」
（creditsDetail.ledger.loadMore）直到「没有更多了」。

只点两类目标：余额数字、加载更多。绝不点 签到/领取/兑换/充值/购买/立即/确认/提交/删除。
输出：logs/autoclaw_credits/frame_*.png + logs/autoclaw_credits_capture.json
"""
from __future__ import annotations

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
    # 本执行环境 LOCALAPPDATA 可能为空（见记忆），字面路径兜底
    r"C:\Users\Hunter\AppData\Local\Programs\AutoClaw2\AutoClaw2.exe",
)
EXE = next((p for p in _EXE_CANDIDATES if p and Path(p).exists()), _EXE_CANDIDATES[-1])
PROC = "AutoClaw2.exe"
RESULT = LOGDIR / "autoclaw_credits_capture.json"

sys.path.insert(0, str(Path(__file__).parent))
from forensics_lobster_windows import (  # noqa: E402
    analyze, enum_windows, proc_pids, win_class, win_pid, win_rect, write_png,
)
from ocr_image import ocr_lines  # noqa: E402

user32 = ctypes.WinDLL("user32", use_last_error=True)
gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)
user32.SetProcessDPIAware()
MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004
MOUSEEVENTF_WHEEL = 0x0800
KEYEVENTF_KEYUP = 0x0002
VK_ESCAPE = 0x1B
SW_RESTORE = 9
SRCCOPY = 0x00CC0020
HWND_TOPMOST = -1
HWND_NOTOPMOST = -2
SWP_NOMOVE = 0x0002
SWP_NOSIZE = 0x0001
SWP_NOACTIVATE = 0x0010

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
    # ALT 击键绕前台锁（项目 BringBack 惯用法），TOPMOST 短暂曝光防遮挡
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
    # 双击保险（2026-10-25 catalog 教训：CEF/React 首击可能只完成焦点切换）
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
    time.sleep(0.8)


def press_esc(times: int = 3) -> None:
    for _ in range(times):
        user32.keybd_event(VK_ESCAPE, 0, 0, 0)
        time.sleep(0.08)
        user32.keybd_event(VK_ESCAPE, 0, KEYEVENTF_KEYUP, 0)
        time.sleep(0.5)


def main() -> int:
    OUTDIR.mkdir(exist_ok=True)
    pids = set(proc_pids(PROC))
    log(f"preexisting procs={len(pids)}")
    if not pids:
        log("launching AutoClaw")
        subprocess.Popen([EXE], close_fds=True)
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

    lines = snap("00_home")
    for ln in lines[:40]:
        log(f"   {ln['text']}  @({ln['x']},{ln['y']}) {ln['w']}x{ln['h']}")

    # 1) 找右上角余额数字（header/credits 按钮）：y<9%H、x>68%W、纯数字
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
        log("balance chip NOT found; abort (no blind clicks)")
        RESULT.write_text(json.dumps({"status": "no_chip", "frames": frames}, ensure_ascii=False, indent=2),
                          encoding="utf-8")
        return 2
    log(f"balance chip '{chip['text']}' @({chip['x']},{chip['y']})")
    # 点数字左段（x+25%w），远离右侧相邻的「去购买」
    click(X + chip["x"] + chip["w"] * 0.25, Y + chip["y"] + chip["h"] / 2)
    time.sleep(3.0)

    lines = snap("01_credits")
    texts = [ln["text"] for ln in lines]
    on_page = any("积分明细" in t or ("积分" in t and "到期" in "".join(texts)) or "全部" in texts for t in texts)
    log(f"credits page detected: {on_page}")
    if not on_page:
        log("not on credits page; abort")
        press_esc()
        RESULT.write_text(json.dumps({"status": "no_credits_page", "frames": frames}, ensure_ascii=False, indent=2),
                          encoding="utf-8")
        return 3

    # 2) 循环：滚到列表底部 → 点「加载更多」→ 再 OCR，直到「没有更多了」
    prev_clickable = True
    no_more_seen = False
    for rnd in range(1, 21):
        wheel(X + W * 0.5, Y + H * 0.62, 8)
        lines = snap(f"02_r{rnd:02d}")
        joined = "".join(ln["text"] for ln in lines)
        if "没有更多了" in joined:
            no_more_seen = True
            log(f"round {rnd}: 没有更多了 -> done")
            break
        more = next((ln for ln in lines if "加载更多" in ln["text"] and safe(ln["text"])), None)
        if more:
            log(f"round {rnd}: click 加载更多 @({more['x']},{more['y']})")
            click(X + more["x"] + more["w"] / 2, Y + more["y"] + more["h"] / 2)
            time.sleep(2.2)
            prev_clickable = True
        else:
            if not prev_clickable:
                log(f"round {rnd}: no 加载更多 twice -> stop")
                break
            prev_clickable = False
            log(f"round {rnd}: 加载更多 not visible")

    # 3) ESC 关设置页，恢复原状
    press_esc(3)
    time.sleep(1.0)
    snap("99_after_close")

    RESULT.write_text(json.dumps({
        "status": "ok",
        "no_more_seen": no_more_seen,
        "note": "只点余额数字与加载更多；未点任何签到/领取/兑换/充值按钮",
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
