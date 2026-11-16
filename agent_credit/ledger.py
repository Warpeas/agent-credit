from __future__ import annotations

import json
import os
import re
import time
import uuid
from contextlib import contextmanager
from datetime import date, datetime, timedelta
from typing import Any, Iterator

from .catalog import account_by_id, accounts
from .paths import DATA_DIR, LEDGER_PATH

# 跨进程写锁：前台 CLI（派单）、每日签到链路、后台实例都可能写同一份账本。
# 这把锁覆盖「读-改-写」全过程，而不是只锁写入——否则两个进程各读一份旧数据、
# 各自追加再各自写回，后写的会把先写的那条覆盖掉（丢事件）。
# 锁文件不删，进程崩溃时由操作系统释放句柄，不存在「残留锁要人工清」的问题。
LOCK_PATH = DATA_DIR / "ledger.lock"
LOCK_WAIT_ENV = "AGENT_CREDIT_LEDGER_LOCK_WAIT"
DEFAULT_LOCK_WAIT_S = 10.0


class LedgerLockTimeout(OSError):
    """等锁超时。宁可报错，也不在无锁状态下读写账本。"""


def _lock_wait_s() -> float:
    raw = os.environ.get(LOCK_WAIT_ENV, "").strip()
    if not raw:
        return DEFAULT_LOCK_WAIT_S
    try:
        return max(0.0, float(raw))
    except ValueError:
        return DEFAULT_LOCK_WAIT_S


def _lock(fd: int) -> None:
    if os.name == "nt":
        import msvcrt

        os.lseek(fd, 0, os.SEEK_SET)
        msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
    else:
        import fcntl

        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)


def _unlock(fd: int) -> None:
    try:
        if os.name == "nt":
            import msvcrt

            os.lseek(fd, 0, os.SEEK_SET)
            msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
        else:
            import fcntl

            fcntl.flock(fd, fcntl.LOCK_UN)
    except OSError:
        pass  # 关句柄也会释放锁，这里失败不该让写账本整体失败


@contextmanager
def _locked(wait: float | None = None) -> Iterator[None]:
    """持有账本锁。超时抛 LedgerLockTimeout；持锁进程崩溃由 OS 自动释放。"""
    LOCK_PATH.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(str(LOCK_PATH), os.O_RDWR | os.O_CREAT)
    deadline = time.monotonic() + (_lock_wait_s() if wait is None else max(0.0, wait))
    try:
        while True:
            try:
                _lock(fd)
                break
            except OSError:
                if time.monotonic() >= deadline:
                    raise LedgerLockTimeout(
                        0,
                        f"账本锁被占用超过 {_lock_wait_s() if wait is None else wait}s: {LOCK_PATH}",
                    )
                time.sleep(0.05)
        yield
    finally:
        _unlock(fd)
        os.close(fd)


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


def _read_raw() -> dict[str, Any]:
    data = json.loads(LEDGER_PATH.read_text(encoding="utf-8"))
    known = {acc["id"] for acc in accounts()}
    for acc_id in known:
        data.setdefault("accounts", {}).setdefault(
            acc_id,
            {"streak_current": 0, "last_claim_date": None, "entries": []},
        )
    return data


def _write(data: dict[str, Any]) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    data["updated_at"] = datetime.now().isoformat(timespec="seconds")
    tmp = LEDGER_PATH.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(LEDGER_PATH)


def load() -> dict[str, Any]:
    if not LEDGER_PATH.exists():
        data = empty_ledger()
        _write(data)
        return data
    return _read_raw()


def _merge_missing_dispatches(data: dict[str, Any]) -> None:
    """把盘上已有、而本次内存里没有的派单事件补回来。

    长耗时链路（签到要开客户端、可能跑好几分钟）在开始时 load、结束时 save，
    期间别的进程写的派单事件不在它的内存快照里。这里按事件 id 做并集，
    保证 append-only 的 dispatches 不会因为「后写的覆盖先写的」而丢条。
    只合并 dispatches；accounts 的写入语义复杂，交给持锁的整段事务处理。
    """
    if not LEDGER_PATH.exists():
        return
    try:
        disk = json.loads(LEDGER_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return  # 盘上那份坏了也不能阻止本次写入覆盖它
    known = {e.get("id") for e in data.get("dispatches") or []}
    extra = [e for e in disk.get("dispatches") or [] if e.get("id") not in known]
    if extra:
        data.setdefault("dispatches", []).extend(extra)


def save(data: dict[str, Any]) -> None:
    """单次写入（短临界区）：持锁 + 补回期间新增的派单事件 + 原子替换。

    需要「读-改-写」全程互斥请用 transaction()；save() 只保护写入这一段，
    但它会按 id 合并盘上多出来的 dispatches，避免长链路回写时覆盖别人的事件。
    """
    with _locked():
        _merge_missing_dispatches(data)
        _write(data)


@contextmanager
def transaction(wait: float | None = None) -> Iterator[dict[str, Any]]:
    """读-改-写事务：持锁 → 重新读盘 → 交给调用方修改 → 原子写回。

    锁覆盖全过程，所以并发进程不会各自基于旧快照写回。超时（默认
    AGENT_CREDIT_LEDGER_LOCK_WAIT=10s）抛 LedgerLockTimeout，不带病写入。
    """
    with _locked(wait):
        data = _read_raw() if LEDGER_PATH.exists() else empty_ledger()
        yield data
        _write(data)


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
    dispatch_id: str = "",
    attempt: int = 1,
    usage: dict[str, Any] | None = None,
    route: str = "",
) -> dict[str, Any]:
    """记一条「尝试」事件。一次派单多次尝试时由调用方逐条写，不做重复累加。"""
    event = {
        "id": uuid.uuid4().hex[:12],
        "at": datetime.now().isoformat(timespec="seconds"),
        "dispatch_id": dispatch_id,
        "attempt": int(attempt),
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
        "route": route,
    }
    if usage is not None:
        event["usage"] = usage
    data.setdefault("dispatches", []).append(event)
    return event


def _parse_at(value: object) -> datetime | None:
    try:
        return datetime.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None


def _since_cutoff(value: str | None) -> datetime | None:
    """解析 --since：7d / 24h / YYYY-MM-DD；空值表示不限。"""
    raw = (value or "").strip().lower()
    if not raw:
        return None
    try:
        if raw.endswith("d"):
            return datetime.now() - timedelta(days=int(raw[:-1]))
        if raw.endswith("h"):
            return datetime.now() - timedelta(hours=int(raw[:-1]))
        return datetime.combine(date.fromisoformat(raw), datetime.min.time())
    except ValueError as exc:
        raise ValueError(f"无法解析 --since={value}（支持 7d / 24h / YYYY-MM-DD）") from exc


def usage_stats(data: dict[str, Any], since: str | None = None) -> dict[str, Any]:
    """按提供者 + 模型聚合用量。

    只统计带 `usage` 对象的事件；没有该字段的旧事件计入 legacy，不回填、
    不参与求和。缺项（null）不计入合计，也不会被当成 0。
    """
    cutoff = _since_cutoff(since)
    rows: dict[tuple[str, str], dict[str, Any]] = {}
    matched = legacy = 0
    for event in data.get("dispatches") or []:
        at = _parse_at(event.get("at"))
        if cutoff is not None and (at is None or at < cutoff):
            continue
        matched += 1
        usage = event.get("usage")
        if not isinstance(usage, dict):
            legacy += 1
            continue
        provider = str(event.get("provider") or "-")
        model = str(usage.get("model") or "-")
        item = rows.setdefault((provider, model), {
            "provider": provider,
            "model": model,
            "attempts": 0,
            "ok": 0,
            "partial": 0,
            "failed": 0,
            "input_tokens": 0,
            "output_tokens": 0,
            "credits": 0,
            "remaining_percent": None,
            "reset_at": None,
            "_latest": None,
        })
        item["attempts"] += 1
        status = usage.get("status")
        if status in ("ok", "partial", "failed"):
            item[status] += 1
        for key in ("input_tokens", "output_tokens", "credits"):
            value = usage.get(key)
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                item[key] += value
        if at is not None and (item["_latest"] is None or at >= item["_latest"]):
            if usage.get("remaining_percent") is not None:
                item["remaining_percent"] = usage["remaining_percent"]
            if usage.get("reset_at") is not None:
                item["reset_at"] = usage["reset_at"]
            item["_latest"] = at

    cleaned = []
    for item in rows.values():
        item.pop("_latest", None)
        item["credits"] = round(float(item["credits"]), 4)
        cleaned.append(item)
    cleaned.sort(key=lambda r: (r["provider"], r["model"]))
    return {"since": since or None, "events": matched, "legacy": legacy, "rows": cleaned}


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


# 旧版派单只在结束时写一条事件：provider 是最后尝试的提供者，note 是各次尝试
# 用 "; " 拼起来的。于是 qoder 的失败记录里会带出 codebuddy 的
# `.codebuddy\projects\...` 路径，读起来像 qoder 自己写错了目录。新写入
# （cli.py 的 record_dispatch 调用点）已按尝试逐条记账，下面的函数只修旧数据。
_LEGACY_ATTEMPT_LABEL = re.compile(r"^(?P<provider>[^(]+)\((?P<state>ok|fail),(?P<dur>[\d.]+)s\)$")


def _legacy_exit_code(note: str) -> int:
    """旧记录只存了最后一次尝试的退出码；前序尝试按适配器契约补码。"""
    if note.startswith("预检失败"):
        return 69
    if note.startswith("exit=0"):
        return 126
    return 1


def split_legacy_attempt_event(event: dict[str, Any]) -> list[dict[str, Any]] | None:
    """把一条「整条回退链」事件拆成逐次尝试事件；无法无歧义拆分时返回 None。"""
    labels = list(event.get("attempts") or [])
    parts = (event.get("note") or "").split("; ")
    if len(labels) < 2 or len(parts) != len(labels):
        return None
    parsed = []
    for label in labels:
        match = _LEGACY_ATTEMPT_LABEL.match(label.strip())
        if not match:
            return None
        parsed.append(match)

    out: list[dict[str, Any]] = []
    last = len(labels) - 1
    for index, (match, part) in enumerate(zip(parsed, parts)):
        item = dict(event)
        item.update(
            {
                # 原 id 留给最后一次尝试：外部引用的是“这条派单的最终结果”。
                "id": event.get("id") if index == last else uuid.uuid4().hex[:12],
                "provider": match.group("provider"),
                "ok": match.group("state") == "ok",
                "duration_s": float(match.group("dur")),
                "attempt": index + 1,
                "attempts": [labels[index]],
                "note": part,
            }
        )
        if index != last:
            item["exit_code"] = _legacy_exit_code(part)
            item["fallback"] = False
            item.pop("usage", None)
        out.append(item)
    return out


def split_legacy_attempt_chains(
    data: dict[str, Any], providers: set[str] | None = None
) -> int:
    """原地拆分账本里的旧链式事件，返回被拆开的旧事件条数。

    ``providers`` 限定只处理这些提供者的记录（None 表示全部），用于按需修复
    某些被误读的记录而不动其他历史。
    """
    events = list(data.get("dispatches") or [])
    rebuilt: list[dict[str, Any]] = []
    repaired = 0
    for event in events:
        if providers is not None and event.get("provider") not in providers:
            rebuilt.append(event)
            continue
        parts = split_legacy_attempt_event(event)
        if parts is None:
            rebuilt.append(event)
            continue
        rebuilt.extend(parts)
        repaired += 1
    if repaired:
        data["dispatches"] = rebuilt
    return repaired


def repair_legacy_attempt_chains(providers: set[str] | None = None) -> int:
    """受控修复入口：持锁读盘 → 拆分旧链式事件 → 有改动才原子写回。"""
    with _locked():
        data = _read_raw() if LEDGER_PATH.exists() else empty_ledger()
        repaired = split_legacy_attempt_chains(data, providers)
        if repaired:
            _write(data)
        return repaired

