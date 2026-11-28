#!/usr/bin/env python3
from __future__ import annotations

import os
import tempfile
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

tmp = Path(tempfile.mkdtemp(prefix="agent-credit-"))
os.environ["AGENT_CREDIT_DATA"] = str(tmp)
os.environ["AGENT_CREDIT_SKIP_UI"] = "1"
os.environ["AGENT_CREDIT_SKIP_EXTERNAL"] = "1"

from agent_credit.catalog import accounts, find_account, load_catalog  # noqa: E402
from agent_credit import ledger, checkin  # noqa: E402
from agent_credit.recommend import recommend  # noqa: E402

# 自测使用临时账本，也不能把真实计划任务心跳写成 running_ui；否则 status
# 会在测试结束后 15 分钟内误报「后台 UI 签到执行中」（2026-11-29 实测）。
checkin._chain_state = lambda *_args, **_kwargs: None


def main() -> None:
    cat = load_catalog()
    ids = [a["id"] for a in accounts()]
    assert "autoclaw" in ids, ids
    ac = find_account("智谱")
    assert ac["daily_amount"] == 200
    assert ac["validity_days"] is None
    assert ac["claim_mode"] == "ui"
    mavis = find_account("mavis")
    assert mavis["claim_policy"] == "never_auto"

    # MiniMax 按天整档额度：必须逐日等于**官方基线**（400/400/400/1000/400/400/1000），
    # 整周期 = cycle_total = 4000。回归防护——服务端调额或有人把表改成两段式时立刻炸。
    # 2026-10-24 订正：bonus_points 已包含在 points 里（客户端类型定义原文
    # "Extra credits already included in points"），所以 day1 不是 800+400=1200。
    # 活动期服务端会临时翻倍（10-24 实测 day4=2024），那是服务端实发，不进基线表。
    mm = find_account("minimax")
    mm_streak = mm.get("streak") or {}
    per_day = [checkin._grant_amounts(mm, s)[0] + checkin._grant_amounts(mm, s)[1]
               for s in range(1, 8)]
    assert per_day == [400, 400, 400, 1000, 400, 400, 1000], per_day
    assert sum(per_day) == mm_streak["cycle_total"] == 4000
    # vendor 脚本不得再把 bonus_points 加到 points 上（2026-10-24 修的 bug，台账多记 5024）。
    mm_src = (ROOT / "vendor" / "minimax-auto-signin" / "signin.py").read_text(encoding="utf-8")
    bad = [ln.strip() for ln in mm_src.splitlines()
           if "bonus_points" in ln and "+" in ln and "int(" in ln]
    assert not bad, f"signin.py 又把 bonus_points 加了一遍：{bad}"
    # 没配整档表的账户仍走「daily + bonus」两段式，不能被这次改动带偏。
    assert checkin._grant_amounts({"daily_amount": 100,
                                   "streak": {"bonus_on": [3], "bonus_amount": 50}}, 3) == (100, 50)
    assert checkin._grant_amounts({"daily_amount": 100,
                                   "streak": {"bonus_on": [3], "bonus_amount": 50}}, 1) == (100, 0)

    # 实发额上报：UI 脚本也会在 detail 里带 `[granted] N`（Trae 用菜单余额差
    # 算实际到账），checkin 必须认，否则又退回按 catalog 常额入账。
    assert checkin._parse_granted("签到成功（余额 3427 -> 3527）[granted] 100") == 100
    assert checkin._parse_granted("签到成功（余额 3427 -> 3527）") is None
    assert checkin._parse_granted("") is None

    # 有 UI 配方的账户才允许「外部失败 → 回落 UI」；没有配方的账户必须如实
    # 上报外部失败，避免「无 UI 配方」盖掉真实原因。MonkeyCode 客户端已安装，
    # 2026-11-29 起网页未登录必须回落到它的专用 UIA 脚本。
    from agent_credit import ui_claim as _uic
    assert _uic.has_ui_route("trae") is True
    assert _uic.has_ui_route("autoclaw") is True
    assert _uic.has_ui_route("lobsterai") is True
    assert _uic.has_ui_route("monkeycode_credit") is True
    assert _uic.has_ui_route("workbuddy") is True   # 在 RECIPES 里

    data = ledger.load()
    r1 = checkin.record_claimed("autoclaw", 200, data=data)
    assert r1["entry"]["amount"] == 200
    assert r1["entry"]["expires_at"] is None
    data = ledger.load()
    checkin.record_claimed("workbuddy", 100, data=data)
    data = ledger.load()
    used = checkin.record_used("workbuddy", 40)
    assert used["used"] == 40
    assert used["remaining"] == 60

    rec = recommend("重构这个仓库")
    assert "coding" in rec["capabilities"]
    open_ids = [x["id"] for x in rec["suggest_open"]]
    assert "mavis" in open_ids
    pool_ids = [x["id"] for x in rec["pool"]]
    assert "autoclaw" in pool_ids or "workbuddy" in pool_ids
    assert rec["primary"]["id"] != "catpaw"
    assert "catpaw" not in pool_ids

    results, _ = checkin.checkin()
    statuses = {r.account_id: r.status for r in results}
    assert statuses.get("mavis") == "skipped"
    assert statuses.get("autoclaw") in ("skipped", "pending")  # already claimed today
    pending = [r for r in results if r.status == "pending"]
    assert any(r.account_id == "lobsterai" for r in pending), pending

    cal = cat.get("calendar") or []
    assert any(x.get("id") == "lobster_gift" for x in cal)

    data = ledger.load()
    snap = checkin.set_balance("minimax", 3200, data=data)
    assert snap["remaining"] == 3200
    data = ledger.load()
    snap = checkin.set_balance("minimax", 100, data=data)
    assert snap["remaining"] == 100

    from agent_credit.doctor import report

    rows = {row["id"]: row for row in report()}
    assert "workbuddy" in rows
    print("selftest ok", tmp)


if __name__ == "__main__":
    main()
