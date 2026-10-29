"""回归测试：`bonus_points` 不得与 `points` 重复计账（2026-10-24 修复）。

离线跑：把 signin.call 打桩喂真实服务端返回过的 days[]，断言上报的实发额。

为什么需要这个测试：
2026-09-30 ~ 2026-10-07 与 10-24，服务端下发了 bonus_points > 0 的日子，
而脚本按 `points + bonus_points` 上报实发额，导致台账多记 5024 积分。
客户端自带的类型定义已经写明 bonus 是「已包含在 points 里」的额外额度：

    /** Extra credits already included in points; absent on older responses. */

跑法：python vendor/minimax-auto-signin/test_bonus_points.py
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("mm_signin", HERE / "signin.py")
signin = importlib.util.module_from_spec(spec)
spec.loader.exec_module(signin)


def panel(days: list[dict]) -> str:
    return json.dumps(
        {"data": {"scene": 2, "days": days}, "base_resp": {"status_code": 0, "status_msg": "ok"}},
        ensure_ascii=False,
    )


def day(n: int, points: int, bonus: int = 0, today: bool = False) -> dict:
    return {
        "day_no": n,
        "points": points,
        "bonus_points": bonus,
        "status": signin.DAY_CLAIMED,
        "is_today": today,
    }


CASES = [
    # (说明, days, 期望实发额)
    ("官方基线 平时 400", [day(1, 400, today=True)], 400),
    ("官方基线 第4天加码 1000", [day(4, 1000, today=True)], 1000),
    ("国庆期 day1 = 800（含 bonus 400）", [day(1, 800, 400, today=True)], 800),
    ("国庆期 day4 = 2000（含 bonus 1000）", [day(4, 2000, 1000, today=True)], 2000),
    ("10-24 活动期 day4 = 2024（含 bonus 1024）", [day(4, 2024, 1024, today=True)], 2024),
]


def main() -> int:
    failures = 0
    for name, days, expected in CASES:
        signin.call = lambda _path, _body=panel(days): (200, _body)
        got = signin.today_granted()
        ok = got == expected
        print(f"[{'ok' if ok else 'FAIL'}] {name}: got={got} expected={expected}")
        if not ok:
            failures += 1

    # 反向断言：points - bonus_points 必须落在官方基线 {400, 1000} 内
    for _, days, _ in CASES:
        d = days[0]
        base = d["points"] - d["bonus_points"]
        ok = base in (400, 1000)
        print(f"[{'ok' if ok else 'FAIL'}] 基线自洽 points-bonus={base} ∈ {{400, 1000}}")
        if not ok:
            failures += 1

    print("全部通过" if not failures else f"{failures} 项失败")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
