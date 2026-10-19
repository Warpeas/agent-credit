#!/usr/bin/env python3
"""credit sync 对账回归：ledger.sync_grants + _apply_sync_payload + sync 开关。

覆盖三类静默失败：字段漂移（payload 契约变了不报错）、
对账写错条目（过期日期/余量优先级）、开关失效（测试里真联网）。
账本用临时目录，不碰 data/ledger.json。

用法：python scripts/test_credit_sync.py
"""
from __future__ import annotations

import os
import sys
import tempfile
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

tmp = Path(tempfile.mkdtemp(prefix="agent-credit-sync-"))
os.environ["AGENT_CREDIT_DATA"] = str(tmp)

from agent_credit import checkin, ledger  # noqa: E402

ON = date(2026, 10, 19)
bad = 0


def check(label: str, got, expect) -> None:
    global bad
    ok = got == expect
    if not ok:
        bad += 1
    print(f"{'ok  ' if ok else 'FAIL'} {label}"
          + ("" if ok else f"\n      got:    {got!r}\n      expect: {expect!r}"))


def fresh(account_id: str = "workbuddy") -> dict:
    data = ledger.load()
    # 清掉该账户既有条目，保证用例之间互不污染
    ledger.state(data, account_id)["entries"] = []
    return data


# ---------- ledger.sync_grants ----------
data = fresh()
ledger.grant(data, "workbuddy", 500, "daily", date(2026, 10, 1))
check("对账前余额", ledger.remaining(data, "workbuddy", ON), 500)

r = ledger.sync_grants(data, "workbuddy", [
    {"remain": 100, "expires": "2026-11-01", "granted_at": "2026-10-02"},
    {"remain": 212.99, "expires": None},
], on=ON)
check("对账 before", r["before"], 500)
check("对账 after（小数四舍五入）", r["after"], 313)
check("对账条目数", r["entries"], 2)
check("旧条目已置零",
      sum(int(e["remaining"] or 0) for e in ledger.state(data, "workbuddy")["entries"]
          if e["source"] == "daily"), 0)
entries = ledger.active_entries(data, "workbuddy", ON)
check("重建条目 source=sync", {e["source"] for e in entries}, {"sync"})
check("重建条目带过期时间",
      sorted((e["expires_at"] or "") for e in entries), ["", "2026-11-01"])

# 过期日期已过的条目：照写但不计入余额（服务端说有效、日期却过去了，
# 以下次对账自愈；写入而非静默丢弃）
data = fresh()
r = ledger.sync_grants(data, "workbuddy", [{"remain": 50, "expires": "2026-10-01"}], on=ON)
check("过去日期的条目不计入余额", r["after"], 0)
check("过去日期的条目仍落账", r["entries"], 1)

# 怪日期消毒：不写错过期，好过写不上
data = fresh()
r = ledger.sync_grants(data, "workbuddy", [{"remain": 50, "expires": "not-a-date"}], on=ON)
check("怪日期置空后计入余额", r["after"], 50)

# 脏数据过滤：0 / 负数 / 非数字 / 布尔
data = fresh()
r = ledger.sync_grants(data, "workbuddy", [
    {"remain": 0}, {"remain": -5}, {"remain": "x"}, {"remain": True}, {"remain": None},
    {"remain": 30},
], on=ON)
check("脏数据只收有效值", (r["entries"], r["after"]), (1, 30))

# ---------- _parse_sync_output ----------
check("纯 JSON 输出", checkin._parse_sync_output('{"balance": 100}'), {"balance": 100})
check("前置告警+末行 JSON",
      checkin._parse_sync_output("warning: x\n{\"balance\": 100}"), {"balance": 100})
try:
    checkin._parse_sync_output("not json at all")
    check("非 JSON 报错", "no raise", "ValueError")
except ValueError:
    check("非 JSON 报错", "ValueError", "ValueError")

# ---------- _apply_sync_payload ----------
acc = {"id": "workbuddy", "name": "WorkBuddy"}

data = fresh()
r = checkin._apply_sync_payload(acc, {"grants": [{"remain": 100, "expires": "2026-11-01"}],
                                      "total": 100}, data, ON)
check("grants 契约走逐条写入", (r["mode"], r["entries"], r["after"]), ("grants", 1, 100))

data = fresh()
ledger.grant(data, "workbuddy", 999, "daily", date(2026, 10, 1))
r = checkin._apply_sync_payload(acc, {"balance": 2716.99, "claimed_today": True}, data, ON)
check("balance 契约走总量快照", (r["mode"], r["entries"]), ("snapshot", 1))
check("快照小数四舍五入", r["after"], 2717)
check("快照替换旧余额", ledger.remaining(data, "workbuddy", ON), 2717)

for bad_payload in ({}, [1, 2], {"grunds": []}, {"balance": "x"}, {"balance": None}):
    try:
        checkin._apply_sync_payload(acc, bad_payload, fresh(), ON)
        check(f"坏载荷 {bad_payload!r:.30} 报错", "no raise", "ValueError")
    except ValueError:
        check(f"坏载荷 {bad_payload!r:.30} 报错", "ValueError", "ValueError")

# ---------- sync() 开关与无能力账户 ----------
os.environ["AGENT_CREDIT_SKIP_SYNC"] = "1"
data = fresh()
check("SKIP_SYNC 时不跑对账", checkin.sync(only="workbuddy", data=data, on=ON), [])
del os.environ["AGENT_CREDIT_SKIP_SYNC"]

os.environ["AGENT_CREDIT_SKIP_EXTERNAL"] = "1"
data = fresh()
check("SKIP_EXTERNAL 连带跳过", checkin.sync(only="workbuddy", data=data, on=ON), [])
del os.environ["AGENT_CREDIT_SKIP_EXTERNAL"]

data = fresh()
check("无对账命令的账户返回空", checkin.sync(only="minimax", data=data, on=ON), [])
check("无对账命令时不动账本", ledger.remaining(data, "workbuddy", ON), 0)

# ---------- sync() 端到端（monkeypatch trace.stream，不真联网） ----------
import json  # noqa: E402

_orig_stream = checkin.trace.stream
_commands: list[str] = []


def fake_stream_ok(command, shell=False, label=None, timeout=None):
    _commands.append(command)
    return 0, json.dumps({"grants": [{"remain": 100, "expires": "2026-11-01"}],
                          "total": 100})


checkin.trace.stream = fake_stream_ok
results = checkin.sync(only="workbuddy", on=ON)  # data=None → 自己加载、自己保存
check("独立 sync 跑通", (len(results), results[0]["ok"]), (1, True))
check("独立 sync 已落盘", ledger.remaining(ledger.load(), "workbuddy", ON), 100)
check("{REPO} 已替换", all("{REPO}" not in c for c in _commands), True)


def fake_stream_fail(command, shell=False, label=None, timeout=None):
    return 1, "boom\nlast line detail"


checkin.trace.stream = fake_stream_fail
results = checkin.sync(only="workbuddy", on=ON)
check("命令失败不计账", results[0]["ok"], False)
check("失败详情带末行", "last line detail" in results[0]["detail"], True)


def fake_stream_timeout(command, shell=False, label=None, timeout=None):
    return None, ""


checkin.trace.stream = fake_stream_timeout
results = checkin.sync(only="workbuddy", on=ON)
check("超时如实上报", results[0]["detail"], "对账命令超时")
checkin.trace.stream = _orig_stream

print("")
print("FAIL count =", bad)
raise SystemExit(1 if bad else 0)
