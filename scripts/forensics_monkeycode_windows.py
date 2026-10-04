#!/usr/bin/env python3
"""MonkeyCode 窗口取证：拉起客户端，枚举窗口并逐个抓图落 PNG。

用途：定位「设置 → 账号 → 签到」的真实像素坐标，为 UI 点击脚本提供锚点。
原生 exe（非 Electron），窗口类与 Electron 不同，枚举逻辑保持通用。

用法（需 GUI 通道：非提权交互式计划任务）：
    python forensics_monkeycode_windows.py --launch
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from forensics_lobster_windows import (  # noqa: E402
    LOGDIR, analyze, enum_windows, grab, proc_pids, win_class, win_pid,
    win_rect, win_text, write_png,
)

EXE = r"C:\Users\Hunter\AppData\Local\MonkeyCode\monkeycode-desktop.exe"
PROC = "monkeycode-desktop.exe"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--launch", action="store_true")
    ap.add_argument("--wait", type=int, default=40)
    ap.add_argument("--settle", type=int, default=18)
    args = ap.parse_args()

    before = proc_pids(PROC)
    print(f"[forensics] preexisting {PROC} pids={before}", flush=True)
    if args.launch and not before:
        print(f"[forensics] launching {EXE}", flush=True)
        subprocess.Popen([EXE], close_fds=True)
        t0 = time.time()
        while time.time() - t0 < args.wait:
            now = proc_pids(PROC)
            if now:
                print(f"[forensics] pid after {time.time()-t0:.1f}s: {now}", flush=True)
                break
            time.sleep(2)
    time.sleep(args.settle)   # 等 webview 拉完远程页面

    pids = set(proc_pids(PROC))
    if not pids:
        print("[forensics] no process, abort")
        return 1
    print(f"[forensics] target pids={sorted(pids)}", flush=True)

    recs = []
    for hwnd in enum_windows():
        pid = win_pid(hwnd)
        if pid not in pids:
            continue
        r = win_rect(hwnd)
        w = (r.right - r.left) if r else 0
        h = (r.bottom - r.top) if r else 0
        rec = {"hwnd": hwnd, "pid": pid, "class": win_class(hwnd),
               "title": win_text(hwnd),
               "rect": [r.left, r.top, w, h] if r else None,
               "visible": bool(__import__("ctypes").WinDLL("user32").IsWindowVisible(hwnd))}
        if w > 200 and h > 200:
            g = grab(hwnd, w, h)
            if g:
                px, gw, gh = g
                rec["grab"] = analyze(px, gw, gh)
                name = LOGDIR / f"_monkey_win_{len(recs)}_{hwnd}.png"
                try:
                    write_png(name, px, gw, gh)
                    rec["png"] = str(name)
                except Exception as e:  # noqa: BLE001
                    rec["png_error"] = str(e)
        recs.append(rec)

    recs.sort(key=lambda d: -(d["rect"][2] * d["rect"][3]) if d["rect"] else 0)
    out = {"pids": sorted(pids), "windows": recs}
    (LOGDIR / "_monkey_windows.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    for i, d in enumerate(recs):
        g = d.get("grab", {})
        print(f"[{i}] hwnd={d['hwnd']} {d['rect']} vis={d['visible']} "
              f"class={d['class']!r} title={d['title']!r} -> {g.get('verdict')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
