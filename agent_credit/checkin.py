from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass
from datetime import date
from typing import Any

from . import ledger
from .catalog import accounts, find_account, threshold_ratio
from .ui_claim import claim as ui_claim, skip_ui


@dataclass
class CheckinResult:
    account_id: str
    name: str
    status: str  # ok | skipped | pending | failed
    detail: str
    amount: int = 0


def _should_claim(acc: dict[str, Any], data: dict[str, Any], on: date) -> tuple[bool, str]:
    policy = acc.get("claim_policy")
    if policy in ("never_auto", "monthly") or acc.get("claim_mode") == "never":
        return False, "不自动领取"
    if ledger.claimed_on(data, acc["id"], on):
        return False, "今日已签"
    if policy == "below_threshold":
        cap = acc.get("cap") or 0
        if not isinstance(cap, int) or cap <= 0:
            return False, "上限未测出，跳过"
        rem = ledger.remaining(data, acc["id"], on)
        if rem >= cap * threshold_ratio():
            return False, f"余额 {rem} 高于阈值，跳过"
    if policy in ("always", "below_threshold"):
        return True, "应签"
    return False, f"未知策略 {policy}"


def _run_external(acc: dict[str, Any]) -> tuple[bool, str]:
    command = (acc.get("command") or "").strip()
    if not command:
        return False, "未配置 command，改按手签处理"
    if os.environ.get("AGENT_CREDIT_SKIP_EXTERNAL", "").strip().lower() in ("1", "true", "yes"):
        return False, "外部命令已跳过（AGENT_CREDIT_SKIP_EXTERNAL）"
    try:
        proc = subprocess.run(
            command,
            shell=True,
            capture_output=True,
            text=True,
            timeout=60,
            encoding="utf-8",
            errors="replace",
        )
    except subprocess.TimeoutExpired:
        return False, "外部命令超时"
    if proc.returncode != 0:
        return False, f"外部命令失败 exit={proc.returncode}"
    return True, "外部命令成功"


def checkin(
    only: str | None = None,
    data: dict[str, Any] | None = None,
    on: date | None = None,
) -> tuple[list[CheckinResult], dict[str, Any]]:
    on = on or ledger.today()
    data = data or ledger.load()
    targets = [find_account(only)] if only else accounts()
    results: list[CheckinResult] = []

    for acc in targets:
        should, reason = _should_claim(acc, data, on)
        if not should:
            results.append(CheckinResult(acc["id"], acc["name"], "skipped", reason))
            continue

        mode = acc.get("claim_mode") or "manual"
        command = (acc.get("command") or "").strip()
        if command or mode == "external":
            ok, detail = _run_external(acc)
            if ok:
                results.append(_grant_success(acc, data, on, detail))
                continue
            if "未配置 command" not in detail and "外部命令已跳过" not in detail:
                results.append(CheckinResult(acc["id"], acc["name"], "failed", detail))
                continue
            if mode != "ui":
                mode = "manual"

        if mode == "ui":
            if skip_ui():
                results.append(
                    CheckinResult(acc["id"], acc["name"], "pending", "已跳过 UI 签到（AGENT_CREDIT_SKIP_UI）")
                )
                continue
            ok, detail = ui_claim(acc["id"])
            if ok:
                results.append(_grant_success(acc, data, on, detail))
                continue
            hint = (
                f"{detail}。请在 {acc['name']} 里手动签到 {acc.get('daily_amount') or 0}，"
                f"然后执行: credit record {acc['id']} claimed {acc.get('daily_amount') or 0}"
            )
            status = "failed" if "超时" in detail else "pending"
            results.append(CheckinResult(acc["id"], acc["name"], status, hint))
            continue

        if mode == "manual":
            hint = f"请打开 {acc['name']} 手动签到 {acc.get('daily_amount') or 0}，然后执行: credit record {acc['id']} claimed {acc.get('daily_amount') or 0}"
            results.append(CheckinResult(acc["id"], acc["name"], "pending", hint))
            continue

        results.append(CheckinResult(acc["id"], acc["name"], "skipped", f"claim_mode={mode}"))

    ledger.save(data)
    return results, data


def _grant_success(acc: dict[str, Any], data: dict[str, Any], on: date, detail: str) -> CheckinResult:
    streak = ledger.mark_claimed(data, acc["id"], on)
    daily, bonus = _grant_amounts(acc, streak)
    if daily:
        ledger.grant(data, acc["id"], daily, "daily", on)
    if bonus:
        ledger.grant(data, acc["id"], bonus, "streak", on)
    return CheckinResult(
        acc["id"], acc["name"], "ok", f"{detail}；连签 {streak}", daily + bonus
    )


def _grant_amounts(acc: dict[str, Any], streak: int) -> tuple[int, int]:
    daily = int(acc.get("daily_amount") or 0)
    info = acc.get("streak") or {}
    bonus_on = info.get("bonus_on") or []
    if streak not in bonus_on:
        return daily, 0
    bonus_amount = int(info.get("bonus_amount") or 0)
    mode = info.get("mode") or "extra"
    if mode == "set_daily":
        return bonus_amount, 0
    return daily, bonus_amount


def record_claimed(
    key: str,
    amount: int,
    source: str = "daily",
    expires: str | None = None,
    data: dict[str, Any] | None = None,
    on: date | None = None,
) -> dict[str, Any]:
    on = on or ledger.today()
    data = data or ledger.load()
    acc = find_account(key)
    if amount <= 0:
        amount = int(acc.get("daily_amount") or 0)
    if amount <= 0:
        raise ValueError("amount required")
    already = ledger.claimed_on(data, acc["id"], on)
    streak = ledger.mark_claimed(data, acc["id"], on)
    expires_on = ledger.parse_date(expires) if expires else None
    bonus_entry = None
    if source == "daily" and not already and not expires:
        daily, bonus = _grant_amounts(acc, streak)
        if amount == int(acc.get("daily_amount") or 0):
            amount = daily
        entry = ledger.grant(data, acc["id"], amount, source, on, expires_on)
        if bonus:
            bonus_entry = ledger.grant(data, acc["id"], bonus, "streak", on)
    else:
        entry = ledger.grant(data, acc["id"], amount, source, on, expires_on)
    ledger.save(data)
    return {
        "account": acc,
        "streak": streak,
        "already_today": already,
        "entry": entry,
        "bonus_entry": bonus_entry,
        "remaining": ledger.remaining(data, acc["id"], on),
    }


def set_balance(
    key: str,
    amount: int,
    expires: str | None = None,
    data: dict[str, Any] | None = None,
    on: date | None = None,
) -> dict[str, Any]:
    """Replace current remaining with a UI snapshot. Does not mark check-in."""
    on = on or ledger.today()
    data = data or ledger.load()
    acc = find_account(key)
    if amount < 0:
        raise ValueError("amount must be >= 0")
    for entry in ledger.state(data, acc["id"])["entries"]:
        entry["remaining"] = 0
    entry = None
    if amount > 0:
        expires_on = ledger.parse_date(expires) if expires else None
        entry = ledger.grant(data, acc["id"], amount, "snapshot", on, expires_on)
    ledger.save(data)
    return {
        "account": acc,
        "entry": entry,
        "remaining": ledger.remaining(data, acc["id"], on),
    }


def record_used(key: str, amount: int, data: dict[str, Any] | None = None) -> dict[str, Any]:
    data = data or ledger.load()
    acc = find_account(key)
    used = ledger.consume(data, acc["id"], amount)
    ledger.save(data)
    return {
        "account": acc,
        "used": used,
        "requested": amount,
        "remaining": ledger.remaining(data, acc["id"]),
    }


def due(data: dict[str, Any] | None = None, on: date | None = None) -> dict[str, Any]:
    on = on or ledger.today()
    data = data or ledger.load()
    must_claim = []
    pending_manual = []
    for acc in accounts():
        should, reason = _should_claim(acc, data, on)
        if not should:
            continue
        item = {"id": acc["id"], "name": acc["name"], "reason": reason, "mode": acc.get("claim_mode")}
        mode = acc.get("claim_mode")
        has_cmd = bool((acc.get("command") or "").strip())
        if mode == "ui" or (mode == "external" and has_cmd):
            must_claim.append(item)
        else:
            pending_manual.append(item)

    from .catalog import calendar_items

    cal = []
    for item in calendar_items():
        raw = str(item.get("date") or "")
        if raw == "monthly-01":
            if on.day == 1:
                cal.append(item)
            continue
        d = ledger.parse_date(raw)
        if d and 0 <= (d - on).days <= 14:
            cal.append({**item, "days_left": (d - on).days})

    return {
        "must_claim": must_claim,
        "pending_manual": pending_manual,
        "expiring": ledger.expiring_within(data, 7, on),
        "calendar": cal,
    }
