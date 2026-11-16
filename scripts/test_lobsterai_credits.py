#!/usr/bin/env python3
"""LobsterAI 积分明细 / 台账镜像的离线测试（不联网、不读凭据）。"""
from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from agent_credit import ledger  # noqa: E402
from agent_credit import lobsterai_credits as lc  # noqa: E402

FAILED = 0


def check(name: str, got, expected) -> None:
    global FAILED
    if got == expected:
        print(f"ok   {name}")
    else:
        FAILED += 1
        print(f"FAIL {name}: got={got!r} expected={expected!r}")


FIXTURE = {
    "totalEarned": 400.0,
    "totalRemaining": 150.0,
    "records": [
        {"type": "campaign", "name": "每日登录奖励", "credits": 100.0,
         "creditsUsed": 0.0, "creditsRemaining": 100.0, "status": "active",
         "earnedAt": "2026-11-06T00:02:27", "expiresAt": "2026-12-06T00:02:28"},
        {"type": "campaign", "name": "每日登录奖励", "credits": 100.0,
         "creditsUsed": 50.0, "creditsRemaining": 50.0, "status": "active",
         "earnedAt": "2026-11-05T00:08:39", "expiresAt": "2026-12-05T00:08:39"},
        {"type": "free", "name": "新用户赠送", "credits": 300.0,
         "creditsUsed": 300.0, "creditsRemaining": 0.0, "status": "expired",
         "earnedAt": "2026-09-15T20:11:34", "expiresAt": "2026-09-29T20:11:34"},
    ],
}

payload = lc.ledger_payload(FIXTURE)
check("detail 条数", len(payload["detail"]), 3)
check("日期截到天", payload["detail"][0]["granted_at"], "2026-11-06")
check("保留原始发放额", payload["detail"][1]["amount"], 100.0)
check("保留剩余", payload["detail"][1]["remaining"], 50.0)

old_today = lc.local_today
lc.local_today = lambda: date(2026, 11, 6)
try:
    line = lc.line_payload(FIXTURE)
finally:
    lc.local_today = old_today
check("balance 四舍五入", line["balance"], 150)
check("今日已领", line["claimed_today"], True)

data = ledger.empty_ledger()
before = ledger.remaining(data, "lobsterai", date(2026, 11, 6))
result = ledger.sync_detail(data, "lobsterai", payload["detail"], date(2026, 11, 6))
check("同步前余额", before, 0)
check("同步后余额（0 余额条目不计数）", result["after"], 150)
check("保留全部发放历史", len(data["accounts"]["lobsterai"]["entries"]), 3)
check("活条目数", result["entries"], 2)
check("条目带服务端过期口径",
      data["accounts"]["lobsterai"]["entries"][0]["expiry_basis"], "server")

first_ids = [e["id"] for e in data["accounts"]["lobsterai"]["entries"]]
ledger.sync_detail(data, "lobsterai", payload["detail"], date(2026, 11, 6))
second_ids = [e["id"] for e in data["accounts"]["lobsterai"]["entries"]]
check("重复同步 ID 稳定", first_ids == second_ids, True)

print(f"\nFAIL count = {FAILED}")
raise SystemExit(1 if FAILED else 0)
