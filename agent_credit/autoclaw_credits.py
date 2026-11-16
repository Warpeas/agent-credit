#!/usr/bin/env python3
"""AutoClaw 积分明细解析（UI 采集 → 台账对账载荷）。

数据来源：scripts/autoclaw_credits_ui_capture2.py 的只读 UI 采集
（积分设置页 → 「获得」过滤 → 滚动 + 加载更多 → OCR 落盘
logs/autoclaw_credits_capture2.json）。属于 research/SAFETY.md 允许路线 3
（客户端自身界面），不碰任何改变状态的按钮。

口径（2026-11-10 实测）：
  * 每条发放流水 UI 自带到期时间（「{{date}} 到期」，精确到秒）；
    每日签到 200 = 发放后 7 天整过期（11-10 00:02 → 11-17 00:02:40）。
  * UI/接口都不给逐条剩余 → 用 FIFO 反推：consumed = Σ发放 - 当前余额，
    从最早到期开始整笔清零、到余数笔部分消耗（与项目烧卡顺序一致：
    全部 7 天内到期时，最早到期 = 最早发放）。
  * 台账 amount 记为估算的 remaining（source=sync），原始发放额保留在
    payload 的 grants_raw 里备查。

用法：
  python -m agent_credit.autoclaw_credits              # 人类可读
  python -m agent_credit.autoclaw_credits --json       # 全量 JSON
  python -m agent_credit.autoclaw_credits --line       # 一行 JSON（status_command 约定）
  python -m agent_credit.autoclaw_credits --ledger     # 对账载荷（credits_command）
  python -m agent_credit.autoclaw_credits --capture    # 无新鲜采集时先跑 UI 采集（手动用）
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from datetime import date, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LOGDIR = ROOT / "logs"
CAPTURE = LOGDIR / "autoclaw_credits_capture2.json"
CAPTURE_SCRIPT = ROOT / "scripts" / "autoclaw_credits_ui_capture2.py"
ACCOUNT = "autoclaw"

RE_EXPIRY = re.compile(r"(\d{4}/\d{2}/\d{2})\s*(\d{1,2}[:：]\d{2}(?:[:：]\d{2})?)?\s*到\s*期")
RE_DATETIME = re.compile(r"(\d{4}/\d{2}/\d{2})\s*(\d{1,2}[:：]\d{2}(?:[:：]\d{2})?)?")
RE_AMOUNT = re.compile(r"^[+＋]?([0-9OolI１２３４５６７８９０,，]{1,9})$")
UI_WORDS = {"全部", "消耗", "获得", "积分明细", "积分", "返回", "通用", "记忆", "关于",
            "总积分", "奖励积分", "加载更多", "没有更多了", "刷新", "兑换码",
            # 左侧导航/标题栏噪声：会被误当成条目描述（2026-11-10 实测）
            "模型与API", "模型与 API", "Agent管理", "Agent 管理", "远程控制",
            "工具与连接", "Office插件", "Office 插件", "归档", "数据与隐私",
            "意见反馈", "AutoClaw"}

FULLWIDTH = str.maketrans("０１２３４５６７８９：，＋／", "0123456789:,+/")


def norm(s: str) -> str:
    return s.translate(FULLWIDTH).replace("O", "0").replace("o", "0").replace("l", "1").replace("I", "1")


def _to_int(digits: str) -> int | None:
    d = re.sub(r"[^0-9]", "", norm(digits))
    return int(d) if d else None


def _expiry_iso(text: str) -> str | None:
    m = RE_EXPIRY.search(norm(text))
    if not m:
        return None
    day = m.group(1).replace("/", "-")
    hhmmss = m.group(2) or "00:00"
    parts = hhmmss.split(":")
    while len(parts) < 3:
        parts.append("00")
    try:
        dt = datetime.strptime(f"{day} {'{:02d}:{:02d}:{:02d}'.format(int(parts[0]), int(parts[1]), int(parts[2]))}",
                               "%Y-%m-%d %H:%M:%S")
    except ValueError:
        return None
    return dt.strftime("%Y-%m-%d %H:%M:%S")


def _occurred_iso(text: str) -> str | None:
    t = norm(text)
    if RE_EXPIRY.search(t):
        return None
    m = RE_DATETIME.search(t)
    if not m:
        return None
    day = m.group(1).replace("/", "-")
    hm = (m.group(2) or "00:00").split(":")
    try:
        dt = datetime.strptime(f"{day} {int(hm[0]):02d}:{int(hm[1]):02d}", "%Y-%m-%d %H:%M")
    except ValueError:
        return None
    return dt.strftime("%Y-%m-%d %H:%M")


def load_capture(fresh_only: bool = True) -> dict:
    if not CAPTURE.exists():
        raise SystemExit(f"capture not found: {CAPTURE}（先跑 scripts/autoclaw_credits_ui_capture2.py）")
    data = json.loads(CAPTURE.read_text(encoding="utf-8"))
    if data.get("status") != "ok":
        raise SystemExit(f"capture status={data.get('status')!r}, not usable")
    if fresh_only:
        day_key = datetime.strptime(data["captured_at"][:10], "%Y-%m-%d").date()
        if day_key != date.today():
            raise SystemExit(f"capture is stale ({day_key}), 当天采集才允许登记（防旧值覆盖真余额）")
    return data


def ensure_fresh_capture(run_capture: bool) -> dict:
    try:
        return load_capture(fresh_only=True)
    except SystemExit:
        if not run_capture:
            raise
    env = dict(__import__("os").environ)
    env.setdefault("LOCALAPPDATA", r"C:\Users\Hunter\AppData\Local")
    env["PYTHONIOENCODING"] = "utf-8"
    rc = subprocess.call([sys.executable, str(CAPTURE_SCRIPT)], env=env,
                         cwd=str(ROOT), shell=False)
    if rc != 0:
        raise SystemExit(f"capture script failed rc={rc}")
    return load_capture(fresh_only=True)


def parse_balance(frames: list[dict]) -> int | None:
    for fr in frames:
        lines = fr["lines"]
        anchor = next((ln for ln in lines if ln["text"].strip() == "总积分"), None)
        if not anchor:
            continue
        cands = [ln for ln in lines
                 if anchor["y"] + 30 < ln["y"] < anchor["y"] + 170
                 and ln["x"] < anchor["x"] + 400
                 and RE_AMOUNT.match(ln["text"].strip())]
        if cands:
            cands.sort(key=lambda ln: ln["y"])
            v = _to_int(RE_AMOUNT.match(cands[0]["text"].strip()).group(1))
            if v is not None:
                return v
    return None


def parse_entries(frames: list[dict]) -> tuple[list[dict], list[str]]:
    entries: dict[tuple, dict] = {}
    warnings: list[str] = []
    for fr in frames:
        lines = sorted(fr["lines"], key=lambda ln: (ln["y"], ln["x"]))
        for e in lines:
            exp_iso = _expiry_iso(e["text"])
            if not exp_iso:
                continue
            ex, ey = e["x"], e["y"]
            # occurred：同一行左侧的日期时间
            occ = None
            best_dx = None
            for o in lines:
                if o is e or o["x"] >= ex:
                    continue
                if abs(o["y"] - ey) > 26:
                    continue
                occ_iso = _occurred_iso(o["text"])
                if not occ_iso:
                    continue
                dx = ex - o["x"]
                if best_dx is None or dx < best_dx:
                    best_dx, occ = dx, occ_iso
            if occ is None:
                warnings.append(f"{fr['tag']}: no occurred for expiry {exp_iso}")
                continue
            # amount：右上的 +N（视觉上比 meta 行高 ~20px）
            amt = None
            best_dy = None
            for a in lines:
                if a is e or a["x"] < ex + 400:
                    continue
                if not (-50 < a["y"] - ey < 30):
                    continue
                m = RE_AMOUNT.match(a["text"].strip())
                if not m:
                    continue
                v = _to_int(m.group(1))
                if v is None:
                    continue
                dy = abs(a["y"] - ey)
                if best_dy is None or dy < best_dy:
                    best_dy, amt = dy, v
            if amt is None:
                warnings.append(f"{fr['tag']}: no amount for expiry {exp_iso}")
                continue
            # description：meta 行上方最近的非日期行
            desc = ""
            best_dy = None
            for dline in lines:
                if dline is e or dline["y"] >= ey - 6:
                    continue
                if ey - dline["y"] > 80:
                    continue
                t = dline["text"].strip()
                if not t or t in UI_WORDS or RE_DATETIME.search(t) or RE_AMOUNT.match(t):
                    continue
                dy = ey - dline["y"]
                if best_dy is None or dy < best_dy:
                    best_dy, desc = dy, t
            key = (occ, exp_iso, amt)
            cand = {"occurred_at": occ, "expires_at": exp_iso,
                    "amount": amt, "description": desc, "frames": [fr["tag"]]}
            if key not in entries:
                entries[key] = cand
            else:
                old = entries[key]
                old["frames"].append(fr["tag"])
                if len(desc) > len(old["description"]) and desc not in UI_WORDS:
                    old["description"] = desc
    out = sorted(entries.values(), key=lambda x: x["occurred_at"], reverse=True)
    return out, warnings


def fifo_remaining(entries: list[dict], balance: int) -> list[dict]:
    """entries 按 occurred 倒序（新→旧）；从旧到新清零直到 consumed 用完。"""
    asc = sorted(entries, key=lambda x: x["occurred_at"])
    total = sum(e["amount"] for e in asc)
    consumed = max(0, total - balance)
    leftovers: dict[int, int] = {}
    for idx, e in enumerate(asc):
        take = min(e["amount"], consumed)
        leftovers[id(e)] = e["amount"] - take
        consumed -= take
    return leftovers


def build_payload(data: dict, balance_override: int | None = None) -> dict:
    frames = data.get("frames", [])
    entries, warnings = parse_entries(frames)
    balance = balance_override if balance_override is not None else parse_balance(frames)
    if balance is None:
        raise SystemExit("balance (总积分) not found in capture")
    leftovers = fifo_remaining(entries, balance)
    today = date.today()
    grants = []
    for e in sorted(entries, key=lambda x: x["occurred_at"]):
        rem = leftovers[id(e)]
        expired = bool(e["expires_at"] and e["expires_at"][:10] < today.isoformat())
        if expired:
            rem = 0
        grants.append({
            "remain": int(rem),
            "expires": e["expires_at"][:10] if e["expires_at"] else None,
            "granted_at": e["occurred_at"][:10],
            "description": e["description"],
            "expires_full": e["expires_at"],
            "amount": e["amount"],
        })
    active_total = sum(g["remain"] for g in grants)
    return {
        "account": ACCOUNT,
        "total": int(active_total),
        "grants": grants,
        "granularity": "per_pack",
        "source": "ui_ocr",
        "fifo_assumed": True,
        "balance_at_capture": int(balance),
        "captured_at": data.get("captured_at"),
        "queried_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "entries_seen": len(entries),
        "warnings": warnings,
        "grants_raw": [
            {"occurred_at": e["occurred_at"], "expires_at": e["expires_at"],
             "amount": e["amount"], "description": e["description"]}
            for e in sorted(entries, key=lambda x: x["occurred_at"])
        ],
    }


def format_text(payload: dict) -> str:
    lines = [f"AutoClaw 积分明细（UI 采集 {payload['captured_at']}，口径=逐条 FIFO 估算）",
             f"总剩余: {payload['total']}（采集时余额 {payload['balance_at_capture']}）",
             f"{'发放':<17}{'到期':<21}{'发放额':>6}{'剩余':>6}  说明"]
    for x in payload["grants_raw"]:
        rem = next((it["remain"] for it in payload["grants"]
                    if it.get("expires_full") == x["expires_at"]), "?")
        mark = "已过期" if (x["expires_at"] or "")[:10] < payload["queried_at"][:10] else ""
        lines.append(f"{x['occurred_at']:<17}{x['expires_at'] or '-':<21}{x['amount']:>6}{rem:>6}  {x['description']} {mark}")
    if payload["warnings"]:
        lines.append("warnings:")
        lines.extend("  " + w for w in payload["warnings"][:10])
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="AutoClaw 积分明细（UI 采集解析，只读）")
    ap.add_argument("--json", action="store_true", help="全量 JSON")
    ap.add_argument("--line", action="store_true", help="一行 JSON（status_command 约定）")
    ap.add_argument("--ledger", action="store_true", help="对账 JSON（credits_command）")
    ap.add_argument("--capture", action="store_true",
                    help="无当天新鲜采集时先跑 UI 采集脚本（需 GUI，手动用）")
    ap.add_argument("--allow-stale", action="store_true", help="允许旧采集（仅查看，不登记）")
    ap.add_argument("--balance", type=int, default=None, help="覆盖余额（调试用）")
    args = ap.parse_args(argv)

    if args.allow_stale:
        data = load_capture(fresh_only=False)
    else:
        data = ensure_fresh_capture(args.capture)
    payload = build_payload(data, balance_override=args.balance)

    if args.ledger:
        slim = {k: v for k, v in payload.items() if k not in {"grants_raw"}}
        print(json.dumps(slim, ensure_ascii=False))
        return 0
    if args.line:
        print(json.dumps({"account": ACCOUNT, "balance": payload["total"],
                          "balance_exact": payload["total"],
                          "balance_at_capture": payload["balance_at_capture"],
                          "captured_at": payload["captured_at"]}, ensure_ascii=False))
        return 0
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0

    g = [x for x in payload["grants"] if x["remain"] > 0] or payload["grants"][-8:]
    print(format_text(payload))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
