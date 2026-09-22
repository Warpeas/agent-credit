from __future__ import annotations

import json
import uuid
from datetime import date, datetime, timedelta
from typing import Any

from .catalog import account_by_id, accounts
from .paths import DATA_DIR, LEDGER_PATH


def today() -> date:
    return date.today()


def parse_date(value: str | None) -> date | None:
    if not value:
        return None
    return date.fromisoformat(value[:10])


def fmt(d: date | None) -> str | None:
    return d.isoformat() if d else None


def empty_ledger() -> dict[str, Any]:
    return {
        "version": 1,
        "updated_at": None,
        "accounts": {
            acc["id"]: {
                "streak_current": 0,
                "last_claim_date": None,
                "entries": [],
            }
            for acc in accounts()
        },
    }


def load() -> dict[str, Any]:
    if not LEDGER_PATH.exists():
        data = empty_ledger()
        save(data)
        return data
    data = json.loads(LEDGER_PATH.read_text(encoding="utf-8"))
    known = {acc["id"] for acc in accounts()}
    for acc_id in known:
        data.setdefault("accounts", {}).setdefault(
            acc_id,
            {"streak_current": 0, "last_claim_date": None, "entries": []},
        )
    return data


def save(data: dict[str, Any]) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    data["updated_at"] = datetime.now().isoformat(timespec="seconds")
    tmp = LEDGER_PATH.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(LEDGER_PATH)


def state(data: dict[str, Any], account_id: str) -> dict[str, Any]:
    return data["accounts"][account_id]


def remaining(data: dict[str, Any], account_id: str, on: date | None = None) -> int:
    on = on or today()
    total = 0
    for entry in state(data, account_id)["entries"]:
        exp = parse_date(entry.get("expires_at"))
        if exp is not None and exp < on:
            continue
        total += int(entry.get("remaining") or 0)
    return total


def active_entries(data: dict[str, Any], account_id: str, on: date | None = None) -> list[dict[str, Any]]:
    on = on or today()
    items = []
    for entry in state(data, account_id)["entries"]:
        if int(entry.get("remaining") or 0) <= 0:
            continue
        exp = parse_date(entry.get("expires_at"))
        if exp is not None and exp < on:
            continue
        items.append(entry)
    items.sort(key=lambda e: (e.get("expires_at") or "9999-12-31", e.get("granted_at") or ""))
    return items


def soonest_expiry(data: dict[str, Any], account_id: str, on: date | None = None) -> date | None:
    dates = []
    for entry in active_entries(data, account_id, on):
        exp = parse_date(entry.get("expires_at"))
        if exp:
            dates.append(exp)
    return min(dates) if dates else None


def claimed_on(data: dict[str, Any], account_id: str, on: date | None = None) -> bool:
    on = on or today()
    last = parse_date(state(data, account_id).get("last_claim_date"))
    return last == on


def grant(
    data: dict[str, Any],
    account_id: str,
    amount: int,
    source: str,
    granted_on: date | None = None,
    expires_on: date | None = None,
) -> dict[str, Any]:
    granted_on = granted_on or today()
    acc = account_by_id(account_id)
    if expires_on is None:
        days = acc.get("validity_days")
        if days == 0:
            expires_on = granted_on
        elif isinstance(days, int) and days > 0:
            expires_on = granted_on + timedelta(days=days)
        elif acc.get("expires_on"):
            expires_on = parse_date(acc["expires_on"])
    entry = {
        "id": f"{account_id}-{granted_on.isoformat()}-{source}-{uuid.uuid4().hex[:6]}",
        "amount": int(amount),
        "remaining": int(amount),
        "granted_at": granted_on.isoformat(),
        "expires_at": fmt(expires_on),
        "source": source,
    }
    st = state(data, account_id)
    st["entries"].append(entry)
    return entry


def consume(data: dict[str, Any], account_id: str, amount: int, on: date | None = None) -> int:
    on = on or today()
    left = int(amount)
    if left <= 0:
        raise ValueError("amount must be positive")
    for entry in active_entries(data, account_id, on):
        take = min(left, int(entry["remaining"]))
        entry["remaining"] -= take
        left -= take
        if left == 0:
            break
    used = amount - left
    if used == 0:
        raise ValueError(f"{account_id} has no remaining balance")
    return used


def mark_claimed(data: dict[str, Any], account_id: str, on: date | None = None) -> int:
    on = on or today()
    st = state(data, account_id)
    last = parse_date(st.get("last_claim_date"))
    if last == on:
        return st.get("streak_current") or 0
    if last == on - timedelta(days=1):
        st["streak_current"] = int(st.get("streak_current") or 0) + 1
    else:
        st["streak_current"] = 1
    st["last_claim_date"] = on.isoformat()
    return st["streak_current"]


def expiring_within(data: dict[str, Any], days: int, on: date | None = None) -> list[dict[str, Any]]:
    on = on or today()
    horizon = on + timedelta(days=days)
    out = []
    for acc in accounts():
        for entry in active_entries(data, acc["id"], on):
            exp = parse_date(entry.get("expires_at"))
            if exp is None:
                continue
            if on <= exp <= horizon:
                out.append({"account_id": acc["id"], "name": acc["name"], **entry, "days_left": (exp - on).days})
    out.sort(key=lambda x: x.get("expires_at") or "")
    return out
