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
    assert "mavis" in open_ids or "monkeycode_token" in open_ids
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
