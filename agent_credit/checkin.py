from __future__ import annotations

import os
import re
import subprocess
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

from . import ledger
from .catalog import accounts, find_account, threshold_ratio
from .ui_claim import claim as ui_claim, has_ui_route, skip_ui

# Repo root, so catalog.yaml never has to hardcode a checkout path.
REPO_ROOT = Path(__file__).resolve().parent.parent


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


def _run_external(acc: dict[str, Any]) -> tuple[bool, str, str]:
    """返回 (ok, detail, stdout)。stdout 交给 _parse_granted 提取实发额。"""
    command = (acc.get("command") or "").strip()
    if not command:
        return False, "未配置 command，改按手签处理", ""
    # {REPO} = 本仓库根目录。让 catalog.yaml 不必写死检出路径，
    # 换机器/ 换目录都能直接用。%USERPROFILE% 等由 cmd 自行展开。
    command = command.replace("{REPO}", str(REPO_ROOT))
    if os.environ.get("AGENT_CREDIT_SKIP_EXTERNAL", "").strip().lower() in ("1", "true", "yes"):
        return False, "外部命令已跳过（AGENT_CREDIT_SKIP_EXTERNAL）", ""
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
        return False, "外部命令超时", ""
    if proc.returncode != 0:
        # 把脚本最后一行输出带出来，否则只看得到退出码，没法判断是没活动还是真失败
        tail = (proc.stdout or "").strip().splitlines()
        last = tail[-1][:200] if tail else ((proc.stderr or "").strip().splitlines() or [""])[-1][:200]
        detail = f"外部命令失败 exit={proc.returncode}"
        if last:
            detail += f" | {last}"
        return False, detail, (proc.stdout or "")
    return True, "外部命令成功", (proc.stdout or "")


def _parse_granted(out: str) -> int | None:
    """外部脚本可用 `[granted] N` 上报服务端实发额。

    catalog 的 daily_amount 是常额，活动期服务端会翻倍（MiniMax 国庆期
    day4 实发 3000 vs 常额 400），按常额入账会让账本比实际少一大截。
    脚本上报多少就记多少。
    """
    m = re.search(r"\[granted\]\s*(\d+)", out or "")
    if not m:
        return None
    v = int(m.group(1))
    return v or None


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
            ok, detail, out = _run_external(acc)
            if ok:
                results.append(_grant_success(acc, data, on, detail,
                                              override=_parse_granted(out)))
                continue
            if "未配置 command" in detail or "外部命令已跳过" in detail:
                if mode != "ui":
                    mode = "manual"
            elif mode == "ui" and not has_ui_route(acc["id"]):
                # 声明了 ui 却**根本没有 UI 配方**，此时回落到 UI 路由只是走一条
                # 死路，还会报出「无 UI 配方」把外部命令的真实失败原因盖掉
                # （2026-10-11 MonkeyCode 上午的失败就是这样被掩盖的，白查一轮）。
                # 直接如实上报外部命令的失败。
                status = "pending" if "exit=2" in detail else "failed"
                results.append(
                    CheckinResult(acc["id"], acc["name"], status,
                                  f"外部命令失败，且该账户没有 UI 路径可回落：{detail}")
                )
                continue
            elif mode == "ui":
                # External route failed (expired token / endpoint change) and a UI
                # route exists. Fall through to it instead of declaring failure --
                # the UI route is the designated fallback and may still succeed.
                pass
            else:
                # 退出码约定与 CLI 全局一致：0 完成 / 2 待手签 / 其它失败。
                # 服务端未下发签到活动这类「今天确实没签到」的情况退出 2，
                # 它是 pending 不是故障——误报成 failed 会掩盖真正的问题。
                if "exit=2" in detail:
                    results.append(
                        CheckinResult(acc["id"], acc["name"], "pending", f"（待手签）{detail}")
                    )
                    continue
                results.append(CheckinResult(acc["id"], acc["name"], "failed", detail))
                continue

        if mode == "ui":
            if skip_ui():
                results.append(
                    CheckinResult(acc["id"], acc["name"], "pending", "已跳过 UI 签到（AGENT_CREDIT_SKIP_UI）")
                )
                continue
            ok, detail = ui_claim(acc["id"])
            if ok:
                # UI 脚本也可以用 detail 里的 `[granted] N` 上报实发额
                # （TraeWork 靠菜单余额差算出来）。catalog 的 daily_amount 是预估，
                # 服务端活动期随时会调：Trae 的免费日额度 2026-09-30 就从 150 变 100，
                # 按常额入账会连续多记。上报多少就记多少。
                results.append(_grant_success(acc, data, on, detail,
                                              override=_parse_granted(detail)))
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


def _grant_success(acc: dict[str, Any], data: dict[str, Any], on: date, detail: str,
                   override: int | None = None) -> CheckinResult:
    streak = ledger.mark_claimed(data, acc["id"], on)
    if override:
        # 服务端实发额（外部脚本 [granted] 上报）：一条 daily 记到底，
        # 不再叠加 catalog 的 streak bonus，否则会重复计。
        daily, bonus = override, 0
        detail = f"{detail}（实发 {override}）"
    else:
        daily, bonus = _grant_amounts(acc, streak)
    if daily:
        ledger.grant(data, acc["id"], daily, "daily", on)
    if bonus:
        ledger.grant(data, acc["id"], bonus, "streak", on)
    return CheckinResult(
        acc["id"], acc["name"], "ok", f"{detail}；连签 {streak}", daily + bonus
    )


def _lookup_day_table(table: Any, streak: int) -> int | None:
    """按天整档表查值。yaml_lite 会把 key 读成字符串、pyyaml 读成 int，两边都试。"""
    if not isinstance(table, dict):
        return None
    for key in (streak, str(streak)):
        if key in table:
            return int(table[key])
    return None


def _grant_amounts(acc: dict[str, Any], streak: int) -> tuple[int, int]:
    daily = int(acc.get("daily_amount") or 0)
    info = acc.get("streak") or {}
    # 有按天整档表就直接用它，不再走「daily + bonus」两段式。
    # 起因：MiniMax 的 day1 基础额度是 800、其他天是 400，单个 daily_amount
    # 表达不了这种「同周期内基础额度自己会变」的情况，硬套会少算/多算 400。
    total = _lookup_day_table(info.get("daily_amount_by_day"), streak)
    if total is not None:
        return total, 0
    bonus_on = info.get("bonus_on") or []
    if streak not in bonus_on:
        return daily, 0
    mode = info.get("mode") or "extra"
    # 按天分档的加成（MiniMax：day1=400、day4/7=600），没有就退回单一 bonus_amount。
    bonus_amount = _lookup_day_table(info.get("bonus_amount_by_day"), streak)
    if bonus_amount is None:
        bonus_amount = int(info.get("bonus_amount") or 0)
    if mode == "set_daily":
        return daily + bonus_amount, 0
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
