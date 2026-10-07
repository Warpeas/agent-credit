#!/usr/bin/env python3
"""AutoClaw 积分明细页只读取证（**只点导航入口，不点任何改变状态的按钮**）。

背景（2026-10-04）：`catalog.yaml` 曾把 autoclaw 的积分有效期记为 unknown，
理由是「客户端无文案、points/expiring 端点需解密登录态」。
但从客户端明文 dist 里挖到了确切结构，说明这个信息**本来就展示给人看**：

  - i18n `creditsDetail.ledger.expiresAt = "{{date}}到期"`
  - 页面路由 `/settings/credits`（设置 → 积分明细）
  - 流水结构 `{id, description, occurredAt, expiresAt, amount, type}`
  - `expiresAt` 是 **Unix 秒级时间戳**（渲染时 `new Date(e * 1e3)`）
  - **积分分四类**，各自的有效期规则可能不同：
      `daily`(每日) / `monthly`(包月) / `longTerm`(长期) / `campaign`(活动)
    服务端若下发 `walletItems[]` 则以其为准（key + displayName + balanceView）

读 UI 属于 `research/SAFETY.md` 的允许路线（走客户端自身界面）。
**该页面存在兑换码输入框（settings.points.redeemTitle），本脚本永不触碰。**

用法（需 GUI 通道：非提权交互式计划任务 RunLevel=Limited + LogonType=Interactive）：
    python scripts/probe_autoclaw_credits.py
输出：logs/_ac_*.png、logs/autoclaw_credits_probe.json
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
EXE = str(Path(os.environ["LOCALAPPDATA"]) / "Programs" / "AutoClaw2" / "AutoClaw2.exe")
PROC = "AutoClaw2.exe"
RESULT = LOGDIR / "autoclaw_credits_probe.json"

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
SW_RESTORE = 9
SRCCOPY = 0x00CC0020

# 绝不触碰的词——这些是会改变账户状态的按钮
FORBIDDEN = ("签到", "领取", "兑换", "充值", "购买", "立即", "确认", "提交", "删除")


def log(m: str) -> None:
    s = time.strftime("%H:%M:%S") + " " + m
    try:
        with open(LOGDIR / "_ac_probe.log", "a", encoding="utf-8") as f:
            f.write(s + "\n")
    except OSError:
        pass
    print(s, flush=True)


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
    user32.mouse_event(MOUSEEVENTF_LEFTDOWN, 0, 0, 0, 0)
    time.sleep(0.07)
    user32.mouse_event(MOUSEEVENTF_LEFTUP, 0, 0, 0, 0)
    time.sleep(0.6)


def safe(text: str) -> bool:
    return not any(b in text for b in FORBIDDEN)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--settle", type=int, default=34)
    args = ap.parse_args()
    if RESULT.exists():
        RESULT.unlink()

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
    time.sleep(args.settle)

    pids = set(proc_pids(PROC))
    if not pids:
        log("no process")
        return 1
    hwnd = find_main(pids)
    if not hwnd:
        log("no main window")
        return 1
    user32.ShowWindow(hwnd, SW_RESTORE)
    user32.SetForegroundWindow(hwnd)
    time.sleep(1.2)
    r = win_rect(hwnd)
    X, Y, W, H = r.left, r.top, r.right - r.left, r.bottom - r.top
    log(f"hwnd={hwnd} RECT={X},{Y} {W}x{H}")

    trace = []

    def snap(tag: str) -> list[dict]:
        px, w, h = screen_shot(X, Y, W, H)
        p = LOGDIR / f"_ac_{tag}.png"
        write_png(p, px, w, h)
        lines = ocr_lines(p)
        log(f"{tag}: png {w}x{h}, {len(lines)} lines")
        for ln in lines[:45]:
            log(f"   {ln['text']}  @({ln['x']},{ln['y']}) {ln['w']}x{ln['h']}")
        trace.append({"tag": tag, "png": str(p), "lines": lines})
        return lines

    lines = snap("00_home")

    # 路径（从客户端明文 dist 挖出的真实结构，2026-10-04）：
    #   /settings/credits 是设置页的一个 leaf tab，
    #   渲染成 <div data-zwork-surface="settings/credits">，
    #   导航项带 data-settings-tab="credits"，
    #   i18n label = creditsDetail.title = 「积分」。
    #   → 所以路径是「打开设置面板 → 点左侧「积分」」，不是首页右上角的余额。
    #   ⚠️ 右上角那个「1,200」是余额展示，旁边是「去购买」，点了会进支付页 —— 不碰。
    steps = [
        (("设置", "偏好设置", "Settings"), "01_settings"),
        (("积分",), "02_credits"),
    ]
    for words, tag in steps:
        target = next((ln for ln in lines
                       if any(w in ln["text"] for w in words)
                       and safe(ln["text"]) and ln["w"] < 300), None)
        if not target:
            log(f"no hit for {words}; visible: "
                + "/".join(ln["text"][:12] for ln in lines[:20]))
            continue
        log(f"click {words} -> {target['text']} @({target['x']+target['w']//2},"
            f"{target['y']+target['h']//2})")
        click(X + target["x"] + target["w"] // 2, Y + target["y"] + target["h"] // 2)
        time.sleep(3.2)
        lines = snap(tag)

    # 明细页可能需要再点「积分明细」页签
    tab = next((ln for ln in lines
                if ("明细" in ln["text"] or "总积分" in ln["text"])
                and safe(ln["text"]) and ln["w"] < 300), None)
    if tab:
        log(f"click detail tab {tab['text']}")
        click(X + tab["x"] + tab["w"] // 2, Y + tab["y"] + tab["h"] // 2)
        time.sleep(3.5)
        lines = snap("03_detail")

    RESULT.write_text(json.dumps({
        "status": "ok",
        "note": "只点导航入口；未点击任何签到/领取/兑换/充值按钮",
        "forbidden_words": list(FORBIDDEN),
        "window": {"hwnd": hwnd, "rect": [X, Y, W, H]},
        "trace": trace,
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
            with open(LOGDIR / "_ac_probe.log", "a", encoding="utf-8") as f:
                f.write("EXCEPTION:\n" + tb + "\n")
        except OSError:
            pass
        print(tb, flush=True)
        raise SystemExit(1)
