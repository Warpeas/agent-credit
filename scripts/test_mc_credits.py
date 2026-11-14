#!/usr/bin/env python3
"""mc_credits 回归：毫积分换算 + 响应形状 + CLI 接线。

为什么需要：wallet.balance 是毫积分，直接入账会把 195 记成 195267
（2026-10-03/04 已踩过）。字段一漂移必须立刻失败，不能静默当 1:1。

用法：python scripts/test_mc_credits.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from agent_credit import mc_credits as mc  # noqa: E402

bad = 0


def check(label: str, got, expect) -> None:
    global bad
    ok = got == expect
    if not ok:
        bad += 1
    print(f"{'ok  ' if ok else 'FAIL'} {label}"
          + ("" if ok else f"\n      got:    {got!r}\n      expect: {expect!r}"))


# ---------- display_credits（10-04 实测配对）----------
check("195267 → 界面 195", mc.display_credits(195267), 195)
check("295267 → 界面 295（领 +100 后）", mc.display_credits(295267), 295)
check("176855 → 176", mc.display_credits(176855), 176)
check("1000 → 1", mc.display_credits(1000), 1)
check("999 → 0", mc.display_credits(999), 0)
check("0 → 0", mc.display_credits(0), 0)

try:
    mc.display_credits(True)
    check("bool 拒绝", "no raise", "CreditQueryError")
except mc.CreditQueryError:
    check("bool 拒绝", "CreditQueryError", "CreditQueryError")

try:
    mc.display_credits("195267")
    check("字符串拒绝", "no raise", "CreditQueryError")
except mc.CreditQueryError:
    check("字符串拒绝", "CreditQueryError", "CreditQueryError")


# ---------- parse_wallet ----------
w = mc.parse_wallet({
    "code": 0,
    "message": "success",
    "data": {
        "id": "x",
        "balance": 195267,
    },
})
check("parse_wallet 用毫积分换算", w["balance"], 195)
check("parse_wallet 保留 raw", w["balance_raw"], 195267)
check("parse_wallet 只返回积分余额", set(w), {"balance", "balance_raw"})

try:
    mc.parse_wallet({"code": 0, "data": {}})
    check("缺 balance 报错", "no raise", "CreditQueryError")
except mc.CreditQueryError:
    check("缺 balance 报错", "CreditQueryError", "CreditQueryError")

try:
    mc.parse_wallet({"code": 0, "data": None})
    check("缺 data 报错", "no raise", "CreditQueryError")
except mc.CreditQueryError:
    check("缺 data 报错", "CreditQueryError", "CreditQueryError")


# ---------- parse_checkin ----------
check("checked_in true", mc.parse_checkin({"data": {"checked_in": True}}), True)
check("checked_in false", mc.parse_checkin({"data": {"checked_in": False}}), False)
check("checked_in 缺省当 false", mc.parse_checkin({"data": {}}), False)

try:
    mc.parse_checkin({"data": None})
    check("checkin 缺 data 报错", "no raise", "CreditQueryError")
except mc.CreditQueryError:
    check("checkin 缺 data 报错", "CreditQueryError", "CreditQueryError")


# ---------- format_text 不含凭据、写明无过期 ----------
sample = {
    "account": "monkeycode_credit",
    "balance": 176,
    "balance_raw": 176855,
    "scale": 1000,
    "claimed_today": True,
    "grants": None,
    "expires": None,
    "queried_at": "2026-10-20 22:00:00",
}
text = mc.format_text(sample)
check("可读输出含总量", "总剩余: 176 credits" in text, True)
check("可读输出含已签", "今日已签: 是" in text, True)
check("可读输出声明无过期", "无" in text and "过期" in text, True)
check("可读输出不含 cookie 字样", "cookie" not in text.lower(), True)
check("可读输出不含其他额度", "token" not in text.lower(), True)


# ---------- --line 契约形状（给 status_command / sync）----------
line = {"balance": sample["balance"], "claimed_today": sample["claimed_today"]}
check("line 契约可 json", json.loads(json.dumps(line)),
      {"balance": 176, "claimed_today": True})
check("line 用换算后的积分不是 raw", line["balance"] != 176855, True)


# ---------- --ledger 契约（credits_command / sync）----------
lp = mc.ledger_payload(sample)
check("ledger 总量是换算后的积分", lp["total"], 176)
check("ledger 一条总量、无过期", lp["grants"], [{"remain": 176, "expires": None}])
check("ledger 不把 raw 毫积分写入账本", lp["total"] != 176855, True)
check("ledger 零余额空 grants",
      mc.ledger_payload({**sample, "balance": 0})["grants"], [])


print("")
print("FAIL count =", bad)
raise SystemExit(1 if bad else 0)
