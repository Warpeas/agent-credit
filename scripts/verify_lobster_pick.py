#!/usr/bin/env python3
"""验证修好的窗口选择逻辑：复刻 ui_claim_lobsterai.ps1 的 Find-AppWindow 判据。

与取证脚本的区别：不抓图，只跑筛选判据并报告选了谁。
用来在改完 PS 之后、用真进程验证「不再选黑窗」。
"""
from __future__ import annotations

import ctypes
import ctypes.wintypes as wt
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from forensics_lobster_windows import (  # noqa: E402
    LOGDIR, PROC, enum_windows, grab, analyze, proc_pids, win_class, win_pid,
    win_rect, win_text,
)

user32 = ctypes.WinDLL("user32", use_last_error=True)


def pick(pids: set[int]) -> dict:
    """严格复刻修好后的 PS 判据：可见 + 非空标题 + 非 Chrome_WidgetWin_0，再取面积最大。"""
    best, best_area, rejected = None, 0, []
    for hwnd in enum_windows():
        pid = win_pid(hwnd)
        if pid not in pids:
            continue
        r = win_rect(hwnd)
        if not r:
            continue
        w, h = r.right - r.left, r.bottom - r.top
        if w <= 500 or h <= 400:
            continue
        cls, title = win_class(hwnd), win_text(hwnd)
        why = None
        if not user32.IsWindowVisible(hwnd):
            why = "not visible"
        elif not title.strip():
            why = "empty title"
        elif cls == "Chrome_WidgetWin_0":
            why = "aux window class"
        if why:
            rejected.append({"hwnd": hwnd, "class": cls, "title": title,
                             "rect": [r.left, r.top, w, h], "rejected_because": why,
                             "area": w * h})
            continue
        if w * h > best_area:
            best, best_area = hwnd, w * h
    return {"picked": best, "area": best_area, "rejected": rejected}


def main() -> int:
    pids = set(proc_pids(PROC))
    if not pids:
        print("[verify] LobsterAI not running — start it first")
        return 1
    res = pick(pids)
    print(f"[verify] pids={sorted(pids)}")
    print(f"[verify] picked hwnd={res['picked']} area={res['area']}")
    for r in res["rejected"]:
        print(f"[verify]  rejected hwnd={r['hwnd']} {r['rect']} "
              f"class={r['class']!r} area={r['area']} <- {r['rejected_because']}")

    if res["picked"]:
        r = win_rect(res["picked"])
        g = grab(res["picked"], r.right - r.left, r.bottom - r.top)
        if g:
            px, w, h = g
            a = analyze(px, w, h)
            print(f"[verify] picked window content: {a}")
            if a["verdict"] == "BLACK":
                print("[verify] FAIL — still grabbed a black window")
                return 2
            print("[verify] PASS — picked window has real content")
    out = LOGDIR / "_lobster_pick_verify.json"
    out.write_text(json.dumps(res, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[verify] wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
