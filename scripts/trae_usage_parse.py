#!/usr/bin/env python3
"""把 Trae「设置 → 用量管理」页的截图 OCR 成结构化积分包列表。

为什么需要：每条积分包的额度/剩余/到期日没有对外 getter（扩展能拿到的
icubeGetCreditsUsageInfo 只有聚合值），只在这一页渲染，所以只能截图后读。

输入：ui_trae_usage.ps1 产出的 PNG（可多张，覆盖不同滚动位置）。
OCR：复用 scripts/ocr_image.py（WinRT OCR，返回行级文本 + 坐标）。
输出：stdout 打印表格；--json 落结构化结果。

页面版式（2026-11-10 实测，单位 px，行高 100）：
    每日签到v        共28笔              2,700.20/2,800   <- 组头 + 笔数 + 组合计
      签到奖励         即将到期                              <- 行标题 / 到期说明
      2026/11/11 10:57 到期              0.20/100          <- 到期行 + 可用/获得
所以行的配对规则是：到期行 y 与数量行 y 相差约 17px；组合计则贴在组头 y+24。
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from ocr_image import ocr_lines  # noqa: E402

GROUP_NAMES = ("每日签到", "每月登录赠送", "邀请奖励", "活动奖励", "其他奖励")

EXP_RE = re.compile(r"^(\d{4})/(\d{1,2})/(\d+):(\d{2})到期$")
AMT_RE = re.compile(r"^([\d,]+(?:\.\d+)?)/([\d,]+(?:\.\d+)?)$")
CNT_RE = re.compile(r"^共(\d+)笔$")


def norm(s: str) -> str:
    """全角标点/空格归一：OCR 会把 / ． ， ： 混着输出。"""
    return (
        s.replace("／", "/")
        .replace("．", ".")
        .replace("，", ",")
        .replace("：", ":")
        .replace(" ", "")
        .replace("\u00a0", "")
    )


def num(s: str) -> float:
    return float(s.replace(",", ""))


def parse_expiry(text: str, prev: datetime | None):
    """'2026/11/1110:57到期' → datetime。日期与小时粘在一起，需按合法性拆。"""
    m = EXP_RE.match(text)
    if not m:
        return None
    year, month, chunk, minute = int(m.group(1)), int(m.group(2)), m.group(3), int(m.group(4))
    cands = []
    # 常见是 2 位日 + 2 位小时（如 1110）；小时 <10 时可能是 3 位（如 091）。
    for cut in (2, 1):
        if len(chunk) <= cut:
            continue
        day, hour = int(chunk[:cut]), int(chunk[cut:])
        if 1 <= day <= 31 and 0 <= hour <= 23:
            cands.append((day, hour))
    if not cands:
        return None
    picks = []
    for day, hour in cands:
        try:
            picks.append(datetime(year, month, day, hour, minute))
        except ValueError:
            continue
    if not picks:
        return None
    if prev:
        for p in picks:
            if p > prev:
                return p
    return picks[0]


def parse_frame(lines: list[dict]):
    rows, groups = [], {}
    # 1) 先定位组头（同一帧可能有多个组）
    headers = []
    for ln in lines:
        t = norm(ln["text"])
        for g in GROUP_NAMES:
            if t.startswith(g):
                headers.append({"name": g, "y": ln["y"], "x": ln["x"]})
                groups.setdefault(g, {"name": g, "count": None, "ui_total": None})
                break
    headers.sort(key=lambda h: h["y"])

    def header_above(y):
        best = None
        for h in headers:
            if h["y"] < y and (best is None or h["y"] > best["y"]):
                best = h
        return best

    def group_of(y):
        """行归属：优先「上方最近的组头」；组头滚出屏幕时，按展示顺序取
        「下方最近组头」的前一组（页面里 每日签到 在 每月登录赠送 之前）。"""
        h = header_above(y)
        if h:
            return h["name"]
        below = None
        for h2 in headers:
            if h2["y"] > y and (below is None or h2["y"] < below["y"]):
                below = h2
        if below:
            idx = GROUP_NAMES.index(below["name"])
            return GROUP_NAMES[idx - 1] if idx > 0 else "未知"
        # 整帧没有组头：只可能是滚进了第一个组（后面的组只有一两笔，且滚到那里时
        # 前面的组头早已离开屏幕）；按展示顺序仍归第一组。
        return GROUP_NAMES[0]

    # 2) 组笔数 / 组合计
    for ln in lines:
        t = norm(ln["text"])
        m = CNT_RE.match(t)
        if m:
            h = header_above(ln["y"])
            if h and abs(ln["y"] - h["y"]) < 120:
                groups[h["name"]]["count"] = int(m.group(1))
            continue
        am = AMT_RE.match(t)
        if am:
            h = header_above(ln["y"])
            if h and abs(ln["y"] - (h["y"] + 24)) <= 30:
                groups[h["name"]]["ui_total"] = {
                    "remaining": num(am.group(1)),
                    "granted": num(am.group(2)),
                }

    # 3) 行配对：到期行 ↔ 右侧数量行
    expiries = []
    for ln in lines:
        t = norm(ln["text"])
        if "到期" not in t:
            continue
        expiries.append({"line": ln, "text": t})
    expiries.sort(key=lambda e: e["line"]["y"])

    prev = None
    for e in expiries:
        ln = e["line"]
        dt = parse_expiry(e["text"], prev)
        if not dt:
            continue
        best = None
        for ln2 in lines:
            if ln2["x"] < 2400:
                continue
            am = AMT_RE.match(norm(ln2["text"]))
            if not am:
                continue
            dy = abs(ln2["y"] - (ln["y"] - 17))
            if dy <= 20 and (best is None or dy < best[0]):
                best = (dy, am)
        if not best:
            continue          # 行被截断（帧边界），交给别的帧补
        rows.append(
            {
                "source": group_of(ln["y"]),
                "granted": num(best[1].group(2)),
                "remaining": num(best[1].group(1)),
                "expires_at": dt.strftime("%Y-%m-%d %H:%M"),
            }
        )
        prev = dt
    return rows, groups


def parse_page_total(lines: list[dict]):
    """抓「总可用积分」下面那行数字（3,200·20 这类 OCR 噪声要清洗）。"""
    for i, ln in enumerate(lines):
        if norm(ln["text"]).startswith("总可用积分"):
            for ln2 in lines[i + 1: i + 4]:
                # OCR 把小数点读成 ·（如 3,200·20），按千分位/小数点清洗
                t2 = re.sub(r"[^\d.]", lambda m: "." if m.group(0) == "·" else "", norm(ln2["text"]))
                t2 = t2.strip(".")
                if re.match(r"^\d+(\.\d+)?$", t2):
                    return float(t2)
    return None


def merge(all_rows):
    # 到期时间是每笔的唯一键（同一帧里滚出来的重复行靠它合并）。
    # 已知来源优先于「未知」——滚动帧里组头滚出屏幕时，集团归属要靠别的帧补。
    seen = {}
    for r in all_rows:
        key = r["expires_at"]
        cur = seen.get(key)
        if cur is None:
            seen[key] = dict(r)
            continue
        if cur["source"] == "未知" and r["source"] != "未知":
            cur["source"] = r["source"]
        if r["remaining"] < cur["remaining"]:
            cur["remaining"] = r["remaining"]
    # 按页面展示顺序（组）再按到期时间排，方便和页面对照
    order = {g: i for i, g in enumerate(GROUP_NAMES)}
    return sorted(seen.values(), key=lambda r: (order.get(r["source"], 99), r["expires_at"]))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("pngs", nargs="+")
    ap.add_argument("--json", default="")
    args = ap.parse_args()

    all_rows, groups, page_total = [], {}, None
    for p in args.pngs:
        path = Path(p)
        if not path.exists():
            print(f"[skip] not found: {path}", file=sys.stderr)
            continue
        lines = ocr_lines(path)
        if not lines:
            print(f"[skip] no OCR text: {path}", file=sys.stderr)
            continue
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
        print(f"[ocr] {path.name}: rows={len(rows)}", file=sys.stderr)

    packs = merge(all_rows)
    for g in groups.values():
        g["parsed_count"] = sum(1 for r in packs if r["source"] == g["name"])
        g["parsed_granted"] = sum(r["granted"] for r in packs if r["source"] == g["name"])
        g["parsed_remaining"] = round(sum(r["remaining"] for r in packs if r["source"] == g["name"]), 2)

    print(f"{'来源':<12}{'额度':>8}{'剩余':>10}  到期")
    print("-" * 48)
    for r in packs:
        print(f"{r['source']:<12}{r['granted']:>8.0f}{r['remaining']:>10.2f}  {r['expires_at']}")
    print("-" * 48)
    print(f"共 {len(packs)} 笔，合计额度 {sum(r['granted'] for r in packs):.0f}，"
          f"剩余 {sum(r['remaining'] for r in packs):.2f}")
    for g in groups.values():
        ui = g["ui_total"]
        ui_s = f"，页面组头 {ui['remaining']:.2f}/{ui['granted']:.0f}" if ui else ""
        print(f"  [{g['name']}] 页面笔数 {g['count']}，解析 {g['parsed_count']} 笔"
              f"（额度 {g['parsed_granted']:.0f}，剩余 {g['parsed_remaining']:.2f}{ui_s}）")
    if page_total:
        print(f"  页面总可用积分 {page_total:.2f}")

    if args.json:
        out = {
            "fetched_at": datetime.now().isoformat(timespec="seconds"),
            "page_total": page_total,
            "groups": list(groups.values()),
            "packs": packs,
        }
        Path(args.json).write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"JSON: {args.json}")
    return 0 if packs else 2


if __name__ == "__main__":
    raise SystemExit(main())
