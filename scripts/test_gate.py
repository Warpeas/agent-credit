#!/usr/bin/env python3
"""启动闸门回归：按键分类 + 三种入口（可见控制台 / 无人值守 / --no-gate / legacy）。

重点守两件事：
  1. 无人值守（计划任务隐藏窗口）绝不能卡在倒计时——必须直接放行；
  2. 主人按 N 时必须落到 skip_ui，并写进 logs/gate_last.json 给每日链路读。

不碰真控制台：`_interactive` / `_countdown` 都是注入点，测试直接替换。

用法：python scripts/test_gate.py
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from agent_credit import gate  # noqa: E402

tmp = Path(tempfile.mkdtemp(prefix="agent-credit-gate-"))
gate.LOG_DIR = tmp
# trace.note 默认写 logs/checkin_<today>.log；测试别往真日志里掺假记录。
gate.trace._LOG_PATH = tmp / "gate-test.log"

bad = 0


def check(label: str, got, expect) -> None:
    global bad
    ok = got == expect
    if not ok:
        bad += 1
    print(f"{'ok  ' if ok else 'FAIL'} {label}"
          + ("" if ok else f"\n      got:    {got!r}\n      expect: {expect!r}"))


def result_file() -> dict:
    return json.loads((tmp / gate.RESULT_PATH_NAME).read_text(encoding="utf-8"))


# ---------- 按键分类 ----------
check("Enter 立即开始", gate._classify("\r"), "start")
check("y 立即开始", gate._classify("y"), "start")
check("大写 Y 立即开始", gate._classify("Y"), "start")
check("n 跳过 UI", gate._classify("n"), "skip")
check("Esc 跳过 UI", gate._classify("\x1b"), "skip")
check("其它键忽略", gate._classify("x"), None)
check("空键忽略", gate._classify(""), None)

# ---------- 秒数：默认 15，边界收敛 ----------
check("默认 15s", gate._seconds(None), gate.DEFAULT_SECONDS)
check("0s 收到 1s", gate._seconds(0), 1)
check("超大值收到上限", gate._seconds(99999), gate.MAX_SECONDS)

# ---------- 无人值守：不提示、直接开始 ----------
gate._interactive = lambda: False
d = gate.run_gate(ui_names=["Trae"])
check("无人值守直接开始", (d.action, d.source), ("start", "unattended"))
check("无人值守落盘", (result_file()["action"], result_file()["source"]),
      ("start", "unattended"))

# ---------- 可见控制台：Y / N / 超时 ----------
gate._interactive = lambda: True

gate._countdown = lambda seconds: "start"
d = gate.run_gate(ui_names=["Trae"])
check("Y 立即开始", (d.action, d.source), ("start", "key"))

gate._countdown = lambda seconds: "skip"
d = gate.run_gate(ui_names=["Trae"])
check("N 跳过 UI", (d.action, d.source), ("skip_ui", "key"))
check("N 落盘（每日链路靠它）", (result_file()["action"], result_file()["ui_accounts"]),
      ("skip_ui", ["Trae"]))

gate._countdown = lambda seconds: None
d = gate.run_gate(ui_names=["Trae"])
check("超时自动开始", (d.action, d.source), ("start", "timeout"))

# ---------- --no-gate：直接开始 ----------
gate._countdown = lambda seconds: "skip"  # 不应该被调用
d = gate.run_gate(enabled=False, ui_names=["Trae"])
check("--no-gate 直接开始", (d.action, d.source), ("start", "flag"))

# ---------- legacy：退回旧空闲闸门 ----------
gate.os.environ[gate.ENV_MODE] = "legacy"
d = gate.run_gate(ui_names=["Trae"])
check("legacy 不接管", d.action, "legacy")
gate.os.environ.pop(gate.ENV_MODE, None)

# ---------- 计划任务的无人值守标记优先级最高 ----------
os.environ[gate.ENV_UNATTENDED] = "1"
d = gate.run_gate(ui_names=["Trae"])
check("计划任务 -Unattended 直接放行", (d.action, d.source), ("start", "unattended"))
os.environ.pop(gate.ENV_UNATTENDED, None)

# ---------- AGENT_CREDIT_GATE_SEC 生效 ----------
gate.os.environ[gate.ENV_SECONDS] = "8"
check("env 倒计时秒数", gate._seconds(None), 8)
gate.os.environ.pop(gate.ENV_SECONDS, None)

# ---------- checkin 接线：闸门结论必须压过旧的空闲等待 ----------
# 账本走临时路径，外部命令/对账全关，UI 点击替换成桩，绝不碰真客户端与真账本。
# 注意 LEDGER_PATH 在 import 时已绑定，必须改模块属性而不是只设环境变量。
os.environ["AGENT_CREDIT_SKIP_SYNC"] = "1"
os.environ["AGENT_CREDIT_SKIP_EXTERNAL"] = "1"

from agent_credit import checkin  # noqa: E402

checkin.trace._LOG_PATH = tmp / "checkin-test.log"
checkin.ledger.DATA_DIR = tmp / "data"
checkin.ledger.LEDGER_PATH = tmp / "data" / "ledger.json"


def _no_idle(*_args, **_kwargs):
    raise AssertionError("启动闸门已给结论，不该再等主人空闲")


def _no_ui(*_args, **_kwargs):
    raise AssertionError("按 N 之后不该再走 UI 路线（含 MiniMax 的 UI 兜底）")


checkin._wait_for_user_idle = _no_idle
checkin.ui_claim = _no_ui
checkin.run_gate = lambda *a, **k: gate.Decision("skip_ui", "key", 15)

results, _ = checkin.checkin()
ui_results = [r for r in results if r.account_id in checkin.UI_IDLE_ACCOUNTS]
check("N：UI 组全部 pending", {r.status for r in ui_results}, {"pending"})
check("N：原因写明跳过", all("主人按 N" in r.detail for r in ui_results), True)
minimax = next(r for r in results if r.account_id == "minimax")
check("N：MiniMax UI 兜底也拦住", minimax.status, "pending")
check("N：last_gate 保留", checkin.last_gate.action, "skip_ui")

checkin.run_gate = lambda *a, **k: gate.Decision("start", "key", 15)
checkin.ui_claim = lambda account_id: (True, f"{account_id} 模拟 [granted] 100")
results, _ = checkin.checkin()
ui_results = [r for r in results if r.account_id in checkin.UI_IDLE_ACCOUNTS]
# monkeycode_credit 在 b9dfcd9 后 claim_mode=external，测试环境 SKIP_EXTERNAL
# 会把它挡成 pending。它留在 UI 组是产品语义正确的——playwright 真开 Edge
# 窗口，照样要等主人空闲——所以断言按 claim_mode 分流：ui 成员必须 ok，
# 非 ui 成员允许 skipped/pending 但不许 failed。
mode_of = {a["id"]: (a.get("claim_mode") or "manual") for a in checkin.accounts()}
check("Y：UI 组 ui 成员不再等空闲、直接签",
      {r.status for r in ui_results if mode_of[r.account_id] == "ui"}, {"ok"})
check("Y：UI 组非 ui 成员不许 failed",
      {r.status for r in ui_results if mode_of[r.account_id] != "ui"}
      <= {"skipped", "pending"}, True)

print()
print("全部通过" if not bad else f"{bad} 个失败")
sys.exit(1 if bad else 0)
