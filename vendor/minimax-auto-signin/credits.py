#!/usr/bin/env python3
"""MiniMax Code 积分明细（只读）——服务端真值通道。

端点（客户端自带 bundle 逆向，app.asar → @mavis/shared）：
    GET /minimax-cloud/api/v1/credit/details
        ?page_number=1&page_size=100&include_expired=true
    → { details: [...], total_count: N }

每条 details 字段：
    credit_type     1=Purchased（购买） 2=Free（签到赠予）
    granted_amount  当笔总量
    remaining_amount 当笔剩余
    consumed_amount 当笔已用
    granted_at_ms / expire_at_ms  毫秒时间戳

输出（对齐项目 credits_command 契约，一行 JSON）：
    {"account": "minimax", "total": N,
     "grants": [{"remain": N, "expires": "YYYY-MM-DD",
                 "granted_at": "YYYY-MM-DD", "package": "签到赠予"}]}

合规：只读 GET 官方接口；只读本机明文凭据；token 不进命令行/日志/输出。
用法：
    python vendor/minimax-auto-signin/credits.py          # 打印一行 JSON
    python vendor/minimax-auto-signin/credits.py --pretty  # 给人看的明细
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

HERE = Path(__file__).resolve().parent
_spec = importlib.util.spec_from_file_location("mm_signin", HERE / "signin.py")
try:
    signin = importlib.util.module_from_spec(_spec)
    _spec.loader.exec_module(signin)
except Exception as _e:  # noqa: BLE001
    raise SystemExit(f"[failed] 无法加载 signin.py: {_e}")

CN = timezone(timedelta(hours=8))
DETAILS_PATH = "/minimax-cloud/api/v1/credit/details"
TYPE_NAME = {1: "购买积分", 2: "签到赠予"}


def _date(ms) -> str | None:
    try:
        return datetime.fromtimestamp(int(ms) / 1000, CN).strftime("%Y-%m-%d")
    except Exception:
        return None


def _num(v) -> int:
    try:
        return int(float(v or 0) + 0.5)
    except Exception:
        return 0


def fetch(page_size: int = 100) -> list[dict]:
    """翻页拉全量明细（include_expired=true，历史也在内）。"""
    out: list[dict] = []
    page = 1
    total_count = None
    while True:
        path = (f"{DETAILS_PATH}?page_number={page}&page_size={page_size}"
                "&include_expired=true")
        code, body = signin.call(path)
        if code != 200:
            raise SystemExit(f"[failed] HTTP {code}: {signin.mask(body)[:200]}")
        try:
            j = json.loads(body)
        except Exception:
            raise SystemExit(f"[failed] 响应不是 JSON: {signin.mask(body)[:200]}")
        data = j.get("data") if isinstance(j.get("data"), dict) else j
        details = data.get("details")
        if not isinstance(details, list):
            raise SystemExit(f"[failed] 响应缺少 details 数组: {signin.mask(body)[:200]}")
        total_count = data.get("total_count")
        out.extend(details)
        if len(details) < page_size:
            break
        page += 1
        if total_count is not None and len(out) >= int(total_count):
            break
        if page > 50:            # 兜底：最多 50 页，防止服务端异常导致死循环
            break
    return out


def to_payload(details: list[dict]) -> dict:
    grants = []
    total = 0
    for d in details:
        remain = _num(d.get("remaining_amount"))
        if remain <= 0:
            continue        # 已用尽/已过期的不写（sync_grants 也只写 remain>0）
        grants.append({
            "remain": remain,
            "expires": _date(d.get("expire_at_ms")),
            "granted_at": _date(d.get("granted_at_ms")),
            "package": TYPE_NAME.get(d.get("credit_type"), "积分"),
            "granted": _num(d.get("granted_amount")),
            "consumed": _num(d.get("consumed_amount")),
        })
        total += remain
    grants.sort(key=lambda g: (g["granted_at"] or "", g["expires"] or ""))
    return {"account": "minimax", "total": total, "grants": grants}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pretty", action="store_true", help="打印人类可读明细")
    args = ap.parse_args()

    code, body = signin.call(f"{DETAILS_PATH}?page_number=1&page_size=1&include_expired=true")
    if code in (401, 403):
        # token 过期：按项目既有做法让客户端续一次期（可用 MINIMAX_NO_WARMUP=1 关）。
        # 预热超时压到 45s：checkin 的对账命令超时是 60s，别让预热把整条链路拖爆。
        signin.WARMUP_TIMEOUT_SEC = min(int(signin.WARMUP_TIMEOUT_SEC), 45)
        if signin.warm_token():
            details = fetch()
        else:
            raise SystemExit("[pending] token 失效且客户端续期失败，请先开一次客户端")
    else:
        details = fetch()

    payload = to_payload(details)
    if args.pretty:
        print(f"服务端剩余合计 {payload['total']}，有效 {len(payload['grants'])} 笔"
              f"（原始 {len(details)} 笔）")
        for g in payload["grants"]:
            print(f"  {g['granted_at']}  {g['package']:<8} 剩余 {g['remain']:>6}"
                  f" / 总量 {g['granted']:>6}  到期 {g['expires']}")
        return 0
    print(json.dumps(payload, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
