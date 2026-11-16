#!/usr/bin/env python3
r"""用量解析的 quota 回归：早退吞值、absent 与 null 的区分。

守卫 2026-11-17 的两处修复：
1. 解析器以前找到第一个含 quota 的字典就 break；长回合里某一轮 quota 只带
   model，会把前面那轮真实的 percent / reset_at 丢掉。现在两项都拿到才停。
2. 整次调用没返回 quota 与返回了但值为空，以前都是两个裸 null，账本看不出
   是没返回还是额度用尽；现在分别标 quota=absent / quota=null（并留 quota_raw）。

用法：python scripts/test_usage_quota_state.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from agent_credit.dispatch.adapters._cli_json import (  # noqa: E402
    format_usage_summary,
    parse_usage_detail,
)

bad = 0


def check(label: str, got, expect) -> None:
    global bad
    ok = got == expect
    if not ok:
        bad += 1
    print(f"{'ok  ' if ok else 'FAIL'} {label}"
          + ("" if ok else f"\n      got:    {got!r}\n      expect: {expect!r}"))


def assistant(quota: dict | None) -> dict:
    raw_usage: dict = {"credit": 0}
    if quota is not None:
        raw_usage["quota"] = quota
    return {
        "type": "message",
        "role": "assistant",
        "providerData": {"model": "hy4-flash-free", "rawUsage": raw_usage},
    }


RESULT = {"type": "result", "usage": {"input_tokens": 100, "output_tokens": 5}, "is_error": False}
PERCENT_ONLY_MODEL = {"model": "hy4-flash"}
FULL_QUOTA = {"model": "hy4-flash", "percent": 41, "reset_at": "1794902205"}
EMPTY_QUOTA = {"model": "hy4-flash", "percent": None, "reset_at": None, "shared_models": ["hy4free"]}


def parse(items: list) -> dict:
    return parse_usage_detail(json.dumps(items, ensure_ascii=False))


# 1) 正常：quota 完整
usage = parse([assistant(FULL_QUOTA), RESULT])
check("short.percent", usage["remaining_percent"], 41)
check("short.reset_at", usage["reset_at"], "2026-11-17T15:56:45+08:00")
check("short.status", usage["status"], "ok")
check("short.no_marker", "quota_state" in usage, False)

# 2) 早退修复：最后一轮 quota 只有 model，上一轮才有值
usage = parse([assistant(FULL_QUOTA), assistant(PERCENT_ONLY_MODEL), RESULT])
check("early_break.percent", usage["remaining_percent"], 41)
check("early_break.reset_at", usage["reset_at"], "2026-11-17T15:56:45+08:00")
check("early_break.status", usage["status"], "ok")

# 3) 整次调用没有 quota
usage = parse([assistant(None), RESULT])
check("absent.state", usage.get("quota_state"), "absent")
check("absent.status", usage["status"], "partial")
check("absent.note", format_usage_summary(usage).endswith("quota=absent"), True)

# 4) 返回了 quota 但两项都空
usage = parse([assistant(EMPTY_QUOTA), RESULT])
check("null.state", usage.get("quota_state"), "null")
check("null.raw", usage.get("quota_raw"), EMPTY_QUOTA)
check("null.percent", usage["remaining_percent"], None)
check("null.note", format_usage_summary(usage).endswith("quota=null"), True)

print("FAILED" if bad else "ALL OK")
sys.exit(1 if bad else 0)
