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


def mark_synced(data: dict[str, Any], account_id: str,
                at: datetime | None = None) -> str:
    """记一次成功对账的时刻（看板用它显示新鲜度）。

    只在对账成功后调用。放在账本里而不是日志里，是因为「这个数字是什么时候
    从服务端拉到的」决定了它有多可信——昨天同步的余额和今天的不是一个量级。
    """
    stamp = (at or datetime.now()).strftime("%Y-%m-%d %H:%M:%S")
    state(data, account_id)["last_sync"] = stamp
    return stamp


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


def sync_grants(
    data: dict[str, Any],
    account_id: str,
    grants: list[dict[str, Any]],
    on: date | None = None,
) -> dict[str, Any]:
    """用服务端逐条明细替换账本条目（对账语义：不记签到、不动连签状态）。

    grants: [{"remain": number, "expires": "YYYY-MM-DD"|None,
              "granted_at": "YYYY-MM-DD"|None}, ...]——只写 remain > 0 的条目。
    旧条目 remaining 全部置零，按服务端剩余重建（source="sync"）。
    账本是整数粒度，小数四舍五入；逐条舍入与总值的少量偏差已知会存在，
    精确值以 `credit credits workbuddy` 为准。

    返回 {"before", "after", "entries"} 供调用方展示。
    """
    on = on or today()
    st = state(data, account_id)
    before = remaining(data, account_id, on)
    for entry in st["entries"]:
        entry["remaining"] = 0
    written = 0
    for g in grants:
        if not isinstance(g, dict):
            continue
        remain = g.get("remain")
        if not isinstance(remain, (int, float)) or isinstance(remain, bool) or remain <= 0:
            continue
        value = int(remain + 0.5)
        granted_on = parse_date(g.get("granted_at")) or on
        expires = g.get("expires")
        expires = expires[:10] if isinstance(expires, str) and expires else None
        if expires is not None:
            try:
                parse_date(expires)
            except ValueError:
                expires = None  # 服务端给了怪日期：不写过期，好过写错
        st["entries"].append({
            "id": f"{account_id}-{granted_on.isoformat()}-sync-{uuid.uuid4().hex[:6]}",
            "amount": value,
            "remaining": value,
            "granted_at": granted_on.isoformat(),
            "expires_at": expires,
            "source": "sync",
        })
        written += 1
    return {"before": before, "after": remaining(data, account_id, on), "entries": written}


def reconcile_total(
    data: dict[str, Any],
    account_id: str,
    total: int,
    on: date | None = None,
) -> dict[str, Any]:
    """服务端只给**总量**（没有逐条明细）时用它校正台账，保留每条的过期时间。

    为什么需要第三种登记语义：`sync_grants` 是「按服务端逐条重建」，而
    `set_balance` 式的单条快照会把逐日领取攒出来的一堆批次压成一条无过期条目——
    临期队列与烧卡优先级当场失明（2026-10-20 在 qodercn 上真踩过：
    8 条 ×100（各 30 天有效期）被对账成 1 条 800、expires=null）。
    服务端既然只下发一个桶总数，就该拿它去**校正总量**，而不是替换结构。

    规则（扣减顺序与 consume 一致 = 先到期先烧）：
      总量 < 台账有效合计 → 逐条扣到相等（扣到 0 的条目留在账本里留痕）
      总量 > 台账有效合计 → 补一条：发放日=今天，有效期按 catalog 的 validity_days
      相等            → 一条不动，只由调用方记 last_sync
    """
    on = on or today()
    before = remaining(data, account_id, on)
    target = int(total)
    if target < 0:
        raise ValueError("total must be >= 0")
    if target < before:
        left = before - target
        for entry in active_entries(data, account_id, on):
            take = min(left, int(entry["remaining"]))
            entry["remaining"] -= take
            left -= take
            if left == 0:
                break
    elif target > before:
        grant(data, account_id, target - before, "sync", on)
    # 存活条目统一标成「总量经服务端校正」；过期日是我们按领取日推出来的，
    # 所以另外带上 expiry_basis=derived，让看板能把两种口径分开写（否则
    # 单一 source 字段会把「余额真值」和「过期也是真值」混成一谈）
    for entry in active_entries(data, account_id, on):
        entry["source"] = "sync"
        entry["expiry_basis"] = "derived"
    return {"before": before, "after": remaining(data, account_id, on),
            "entries": len(active_entries(data, account_id, on))}


def record_dispatch(
    data: dict[str, Any],
    *,
    provider: str,
    capability: str,
    ok: bool,
    duration_s: float,
    exit_code: int,
    fallback: bool,
    attempts: list[str],
    balance_before: int | None = None,
    balance_unknown: bool = False,
    task_digest: str = "",
    note: str = "",
) -> dict[str, Any]:
    """记一条派单事件。这是回答「到底省了多少」的唯一数据源。"""
    event = {
        "id": uuid.uuid4().hex[:12],
        "at": datetime.now().isoformat(timespec="seconds"),
        "provider": provider,
        "capability": capability,
        "ok": bool(ok),
        "duration_s": round(float(duration_s), 1),
        "exit_code": int(exit_code),
        "fallback": bool(fallback),
        "attempts": list(attempts),
        "balance_before": balance_before,
        "balance_unknown": bool(balance_unknown),
        "task_digest": task_digest,
        "note": note,
    }
    data.setdefault("dispatches", []).append(event)
    return event


def dispatch_stats(data: dict[str, Any], limit: int | None = None) -> list[dict[str, Any]]:
    """按提供者聚合派单事件：次数、成功数、回退数、总耗时。"""
    events = list(data.get("dispatches") or [])
    if limit:
        events = events[-limit:]
    stats: dict[str, dict[str, Any]] = {}
    for e in events:
        item = stats.setdefault(
            e.get("provider") or "-",
            {"provider": e.get("provider") or "-", "runs": 0, "ok": 0, "fallback": 0,
             "balance_unknown": 0, "duration_s": 0.0},
        )
        item["runs"] += 1
        item["ok"] += 1 if e.get("ok") else 0
        item["fallback"] += 1 if e.get("fallback") else 0
        item["balance_unknown"] += 1 if e.get("balance_unknown") else 0
        item["duration_s"] = round(item["duration_s"] + float(e.get("duration_s") or 0), 1)
    return sorted(stats.values(), key=lambda s: -s["runs"])
