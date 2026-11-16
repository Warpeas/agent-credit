#!/usr/bin/env python3
"""无人值守采集 Trae「用量管理」页 → logs/trae_usage.json。

被 scripts/trae_credit_sync.ps1 在 dump 拉新鲜之后调用：复用
  scripts/ui_trae_usage.ps1  （打开页面 / 展开分组 / 滚动 / PrintWindow 截图）
  scripts/ocr_image.py        （WinRT OCR）
  scripts/trae_usage_parse.py （行配对成 来源/额度/剩余/到期）
只产出一个「当天的」JSON，是否采信由 agent_credit/trae_credits.py 的第二道闸门
（逐包合计 vs dump total）决定；这里只负责把图拍全、把结构化字段落盘。

失败即退出非 0（调用方记录原因、对账自动退回聚合口径），绝不写半成品：
  exit 0 成功   exit 2 数据不足（行数/总额缺失）   exit 3 打不开页面/截图失败

临时截图默认落在 logs/_trae_usage/，无论成功失败都会删除。
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from ocr_image import ocr_lines  # noqa: E402
from trae_usage_parse import merge, norm, parse_frame, parse_page_total  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
SHOT_PS = ROOT / "scripts" / "ui_trae_usage.ps1"
DEFAULT_OUT = ROOT / "logs" / "trae_usage.json"
DEFAULT_SHOTS = ROOT / "logs" / "_trae_usage"


def shot(hwnd: int, scroll: int, png: Path, click: str = "", send_open: bool = False) -> bool:
    """调 ui_trae_usage.ps1 抓一张整窗图。返回是否成功。

    send_open=True 时只对既有窗口发 ctrl+alt+u（不新建窗口），
    用于无人值守时复用 trae_credit_sync 已经拉起的那个 IDE 窗口。
    """
    cmd = ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass",
           "-File", str(SHOT_PS),
           "-SkipOpen", "-Hwnd", str(hwnd),
           "-ScrollDown", str(scroll),
           "-OutPng", str(png), "-NoClose"]
    if send_open:
        cmd.append("-SendOpen")
    if click:
        cmd += ["-Click", click]
    proc = subprocess.run(cmd, capture_output=True, text=True,
                          encoding="utf-8", errors="replace", timeout=180)
    ok = proc.returncode == 0 and png.is_file() and png.stat().st_size > 0
    if not ok:
        tail = " | ".join(l.strip() for l in (proc.stdout + proc.stderr).splitlines() if l.strip())[-400:]
        print(f"WARN: 截图 rc={proc.returncode}: {tail}", file=sys.stderr)
    return ok


def find_header(lines: list[dict], name: str) -> dict | None:
    for ln in lines:
        if norm(ln["text"]).startswith(name):
            return ln
    return None


def is_collapsed(text: str) -> bool:
    return any(c in text for c in "〉>›")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--hwnd", type=int, required=True)
    ap.add_argument("--out", default=str(DEFAULT_OUT))
    ap.add_argument("--shots", default=str(DEFAULT_SHOTS))
    ap.add_argument("--scroll", default="0,9,18,27")
    ap.add_argument("--min-packs", type=int, default=20)
    ap.add_argument("--keep-shots", action="store_true", help="排障用：保留临时截图")
    args = ap.parse_args()

    shots_dir = Path(args.shots)
    shots_dir.mkdir(parents=True, exist_ok=True)
    pngs: list[Path] = []
    try:
        png0 = shots_dir / "s0.png"
        pngs.append(png0)
        # 第一次带 -SendOpen：窗口是 trae_credit_sync 拉起的，页面上还停在别的设置页，
        # 必须让客户端自己把「用量管理」切出来；后面几帧只滚动，不再发键。
        header = None
        for attempt in range(1, 4):
            if not shot(args.hwnd, 0, png0, send_open=True):
                print(f"FAIL: 截图失败（第 {attempt} 次）", file=sys.stderr)
                return 3
            header = find_header(ocr_lines(png0), "每日签到")
            if header:
                break
            print(f"WARN: 第 {attempt} 次没找到「每日签到」（页面可能还在加载），重试",
                  file=sys.stderr)
            time.sleep(2)
        if not header:
            print("FAIL: 页面上找不到「每日签到」分组（用量页没打开？）", file=sys.stderr)
            return 3
        if is_collapsed(header["text"]):
            cx = header["x"] + header["w"] // 2
            cy = header["y"] + header["h"] // 2
            print(f"expand 每日签到 @ {cx},{cy}", file=sys.stderr)
            if not shot(args.hwnd, 0, png0, click=f"{cx},{cy}"):
                print("FAIL: 展开分组后截图失败", file=sys.stderr)
                return 3

        all_rows, groups, page_total = [], {}, None
        for step in [int(s) for s in args.scroll.split(",") if s.strip()]:
            png = png0 if step == 0 else shots_dir / f"s{step}.png"
            if step != 0:
                pngs.append(png)
                if not shot(args.hwnd, step, png):
                    print(f"WARN: 滚动 {step} 截图失败，跳过该帧", file=sys.stderr)
                    continue
            lines = ocr_lines(png)
            rows, gs = parse_frame(lines)
            all_rows.extend(rows)
            for k, v in gs.items():
                cur = groups.setdefault(k, {"name": k, "count": None, "ui_total": None})
                if v["count"] and not cur["count"]:
                    cur["count"] = v["count"]
                if v["ui_total"] and not cur["ui_total"]:
                    cur["ui_total"] = v["ui_total"]
            pt = parse_page_total(lines)
            if pt and not page_total:
                page_total = pt
            print(f"frame {step}: rows={len(rows)}", file=sys.stderr)

        # 2026-11-11 00:15 实跑：设备刚唤醒时首帧只渲染出分组标题（rows=9），
        # 顶部「总可用积分」还没画出来；后面的帧都滚到下面了，于是整轮读不到总额，
        # exit=2 白白退化成聚合。这里补拍顶部帧，等页面渲染完再判失败。
        if page_total is None:
            for attempt in range(1, 4):
                time.sleep(1.5)
                if not shot(args.hwnd, 0, png0):
                    print(f"WARN: 补拍顶部帧失败（第 {attempt} 次）", file=sys.stderr)
                    continue
                lines = ocr_lines(png0)
                pt = parse_page_total(lines)
                print(f"retry-top {attempt}: rows={len(lines)} total={pt}", file=sys.stderr)
                if pt:
                    page_total = pt
                    break

        packs = merge(all_rows)
        for g in groups.values():
            g["parsed_count"] = sum(1 for r in packs if r["source"] == g["name"])
            g["parsed_granted"] = sum(r["granted"] for r in packs if r["source"] == g["name"])
            g["parsed_remaining"] = round(
                sum(r["remaining"] for r in packs if r["source"] == g["name"]), 2)

        if len(packs) < args.min_packs:
            print(f"FAIL: 只解析到 {len(packs)} 笔（< {args.min_packs}），"
                  f"多半是滚动没生效/页面没渲染完", file=sys.stderr)
            return 2
        if page_total is None:
            print("FAIL: 页面上没读到「总可用积分」", file=sys.stderr)
            return 2

        out = {
            "fetched_at": datetime.now().isoformat(timespec="seconds"),
            "hwnd": args.hwnd,
            "page_total": page_total,
            "groups": list(groups.values()),
            "packs": packs,
        }
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.out).write_text(json.dumps(out, ensure_ascii=False, indent=2),
                                  encoding="utf-8")
        summary = (f"OK packs={len(packs)} "
                   f"remaining={sum(p['remaining'] for p in packs):.2f} "
                   f"page_total={page_total:.2f} out={args.out}")
        print(summary)
        return 0
    except subprocess.TimeoutExpired:
        print("FAIL: 截图脚本超时", file=sys.stderr)
        return 3
    finally:
        # 临时截图不留仓库（失败路径同样清）
        if not args.keep_shots:
            for p in pngs:
                try:
                    p.unlink()
                except OSError:
                    pass


if __name__ == "__main__":
    raise SystemExit(main())
