#!/usr/bin/env python3
r"""旧链式派单记录拆分回归：qoder 失败记录不得带 codebuddy 的 .codebuddy 路径。

守卫 2026-11-15 的账本记录：旧版一次派单只写一条事件，provider 是最后尝试的
提供者、note 却是整条回退链拼起来的，于是 qoder 的失败记录里出现
`ENOENT: ... \.codebuddy\projects\...`，读起来像 qoder 自己写错了目录。

用法：python scripts/test_ledger_legacy_split.py
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from agent_credit import ledger  # noqa: E402

bad = 0


def check(label: str, got, expect) -> None:
    global bad
    ok = got == expect
    if not ok:
        bad += 1
    print(f"{'ok  ' if ok else 'FAIL'} {label}"
          + ("" if ok else f"\n      got:    {got!r}\n      expect: {expect!r}"))


def legacy_qoder_event() -> dict:
    return {
        "id": "b26a204387c1",
        "at": "2026-11-15T14:09:02",
        "task": "修 qoder 失败记录",
        "attempts": ["codebuddy(fail,2.7s)", "qoder(fail,8.2s)"],
        "provider": "qoder",
        "ok": False,
        "exit_code": 1,
        "note": (
            "exit=0, ENOENT: no such file or directory, open "
            "'C:\\Users\\M4A1g\\.codebuddy\\projects\\x\\y.jsonl'; exit=1"
        ),
        "duration_s": 10.9,
        "usage": {"provider": "qoder", "model": "glm-5", "tokens": 0},
    }


data = {"dispatches": [legacy_qoder_event()]}
repaired = ledger.split_legacy_attempt_chains(data)
check("拆开的旧事件条数", repaired, 1)

events = data["dispatches"]
check("拆成逐次尝试", [e["provider"] for e in events], ["codebuddy", "qoder"])
check("attempt 序号", [e["attempt"] for e in events], [1, 2])
check("ok 按尝试判定", [e["ok"] for e in events], [False, False])
check("耗时来自尝试标签", [e["duration_s"] for e in events], [2.7, 8.2])
check("原 id 留给最终尝试", events[-1]["id"], "b26a204387c1")
check("前序尝试换新 id", events[0]["id"] != "b26a204387c1", True)
check("codebuddy 的路径归 codebuddy",
      ".codebuddy" in events[0]["note"], True)
check("qoder 记录不再带 .codebuddy 路径",
      ".codebuddy" in events[-1]["note"], False)
check("qoder 记录只保留自己的错误", events[-1]["note"], "exit=1")
check("前序尝试补退出码(启动失败=126)", events[0]["exit_code"], 126)
check("usage 只留在最终尝试", [("usage" in e) for e in events], [False, True])

# 分段数与 attempts 数对不上时不猜，原样保留
ambiguous = legacy_qoder_event()
ambiguous["note"] = "exit=1"
data2 = {"dispatches": [ambiguous]}
check("无法无歧义拆分时不动", ledger.split_legacy_attempt_chains(data2), 0)
check("保持原事件", data2["dispatches"], [ambiguous])

# 正常单次尝试记录不受影响
single = {
    "id": "aaaabbbbcccc",
    "provider": "qoder",
    "ok": False,
    "attempts": ["qoder(fail,8.2s)"],
    "note": "exit=1",
}
data3 = {"dispatches": [single]}
check("单尝试记录不动", ledger.split_legacy_attempt_chains(data3), 0)
check("单尝试保持原样", data3["dispatches"], [single])

# providers 过滤：只修指定提供者，其他旧链式记录不动
other = legacy_qoder_event()
other["id"] = "111122223333"
other["provider"] = "ollama"
other["attempts"] = ["ollama(fail,1.0s)", "ollama(fail,8.2s)"]
other["note"] = "exit=1; exit=1"
data4 = {"dispatches": [other, legacy_qoder_event()]}
check("按 provider 过滤后拆开条数", ledger.split_legacy_attempt_chains(data4, {"qoder"}), 1)
check("其他提供者保持原样", data4["dispatches"][0], other)
check("qoder 链被拆开", [e["provider"] for e in data4["dispatches"][1:]], ["codebuddy", "qoder"])

if bad:
    print(f"\n{bad} 项失败")
    raise SystemExit(1)
print("\n全部通过")
