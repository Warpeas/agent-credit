from __future__ import annotations

import argparse
import json
import sys
from typing import Any

from . import checkin as checkin_mod
from . import ledger
from .apps import launch
from .catalog import accounts, find_account
from .doctor import format_report, report
from .recommend import format_recommend, recommend


def cmd_status(_args: argparse.Namespace) -> int:
    data = ledger.load()
    on = ledger.today()
    lines = [f"日期 {on.isoformat()}  台账 {ledger.LEDGER_PATH}", ""]
    for acc in accounts():
        st = ledger.state(data, acc["id"])
        rem = ledger.remaining(data, acc["id"], on)
        last = st.get("last_claim_date") or "-"
        streak = st.get("streak_current") or 0
        claimed = "已签" if ledger.claimed_on(data, acc["id"], on) else "未签"
        policy = acc.get("claim_policy")
        mode = acc.get("claim_mode")
        extra = ""
        if acc.get("grant_type") == "daily_expire":
            extra = "  [用时再开]"
            claimed = "-"
        lines.append(
            f"{acc['id']:<18} {acc['name']:<16} 余额 {rem:>10} {acc.get('unit')}  "
            f"{claimed} 连签{streak} 上次{last}  {policy}/{mode}{extra}"
        )
    print("\n".join(lines))
    return 0


def cmd_checkin(args: argparse.Namespace) -> int:
    results, _ = checkin_mod.checkin(only=args.only)
    pending = failed = 0
    for r in results:
        print(f"[{r.status}] {r.name}: {r.detail}" + (f"  +{r.amount}" if r.amount else ""))
        if r.status == "pending":
            pending += 1
        elif r.status == "failed":
            failed += 1
    if args.open:
        for r in results:
            if r.status != "pending":
                continue
            try:
                exe = launch(r.account_id)
                print(f"  已打开 {r.name}: {exe}")
            except FileNotFoundError:
                print(f"  未安装或未知路径：{r.name}，请手动打开")
    if failed:
        return 1
    if pending:
        return 2
    return 0


def cmd_recommend(args: argparse.Namespace) -> int:
    task = " ".join(args.task).strip()
    if not task:
        print("用法: credit recommend <任务描述>", file=sys.stderr)
        return 1
    print(format_recommend(recommend(task)))
    return 0


def cmd_record(args: argparse.Namespace) -> int:
    action = args.action
    if action == "used":
        if args.amount is None:
            print("used 必须带数量", file=sys.stderr)
            return 1
        result = checkin_mod.record_used(args.account, args.amount)
        print(
            f"已从 {result['account']['name']} 扣除 {result['used']} "
            f"(请求 {result['requested']})，剩余 {result['remaining']}"
        )
        return 0
    if action == "claimed":
        result = checkin_mod.record_claimed(
            args.account,
            args.amount if args.amount is not None else 0,
            source=args.source,
            expires=args.expires,
        )
        acc = result["account"]
        extra = "（今日已记过一次签到，仍入账）" if result["already_today"] else ""
        print(f"{acc['name']} 入账 {result['entry']['amount']} {acc.get('unit')} 来源 {result['entry']['source']}{extra}")
        if result["bonus_entry"]:
            print(f"连签奖励 +{result['bonus_entry']['amount']}")
        print(f"连签 {result['streak']} 天，剩余 {result['remaining']}")
        return 0
    print("action 必须是 used 或 claimed", file=sys.stderr)
    return 1


def cmd_due(_args: argparse.Namespace) -> int:
    info = checkin_mod.due()
    print("今日应自动签：")
    if not info["must_claim"]:
        print("  （无）")
    for it in info["must_claim"]:
        print(f"  - {it['name']} ({it['mode']})")
    print("待手签：")
    if not info["pending_manual"]:
        print("  （无）")
    for it in info["pending_manual"]:
        print(f"  - {it['name']}")
    print("7 天内到期批次：")
    if not info["expiring"]:
        print("  （无）")
    for it in info["expiring"]:
        print(f"  - {it['name']}  剩余 {it['remaining']}  {it['expires_at']} 还有 {it['days_left']} 天")
    print("日历：")
    if not info["calendar"]:
        print("  （近 14 天无）")
    for it in info["calendar"]:
        extra = f" 还有 {it['days_left']} 天" if "days_left" in it else ""
        print(f"  - {it.get('date')} {it.get('note')}{extra}")
    return 0


def cmd_doctor(_args: argparse.Namespace) -> int:
    print(format_report(report()))
    return 0


def cmd_open(args: argparse.Namespace) -> int:
    ids = [args.account] if args.account else [r["id"] for r in checkin_mod.due()["pending_manual"]]
    if not ids:
        print("没有待打开的手签软件")
        return 0
    code = 0
    for key in ids:
        acc = find_account(key)
        if acc.get("claim_policy") == "never_auto" and acc.get("grant_type") == "daily_expire":
            print(f"跳过当日清零：{acc['name']}（用时再开，不自动启动）")
            continue
        try:
            exe = launch(acc["id"])
            print(f"已打开 {acc['name']}: {exe}")
        except FileNotFoundError as exc:
            print(str(exc), file=sys.stderr)
            code = 1
    return code


def cmd_set_balance(args: argparse.Namespace) -> int:
    result = checkin_mod.set_balance(args.account, args.amount, expires=args.expires)
    print(f"{result['account']['name']} 快照余额 {result['remaining']} {result['account'].get('unit')}")
    return 0


def cmd_show(args: argparse.Namespace) -> int:
    acc = find_account(args.account)
    data = ledger.load()
    payload: dict[str, Any] = {
        "account": acc,
        "state": ledger.state(data, acc["id"]),
        "remaining": ledger.remaining(data, acc["id"]),
        "active": ledger.active_entries(data, acc["id"]),
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2, default=str))
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="credit", description="Agent 积分台账与签到")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("status", help="各家余额与签到状态")
    s.set_defaults(func=cmd_status)

    s = sub.add_parser("checkin", help="按策略签到（ui=本机客户端；失败则提示手签）")
    s.add_argument("--only", help="只处理一个账户 id/别名")
    s.add_argument("--open", action="store_true", help="打开待手签且已安装的客户端（不含当日清零）")
    s.set_defaults(func=cmd_checkin)

    s = sub.add_parser("recommend", help="根据任务推荐用哪家")
    s.add_argument("task", nargs="+")
    s.set_defaults(func=cmd_recommend)

    s = sub.add_parser("record", help="手签入账或登记消耗")
    s.add_argument("account")
    s.add_argument("action", choices=["used", "claimed"])
    s.add_argument("amount", nargs="?", type=int, default=None)
    s.add_argument("--source", default="daily")
    s.add_argument("--expires", default=None, help="YYYY-MM-DD，默认按 catalog 有效期")
    s.set_defaults(func=cmd_record)

    s = sub.add_parser("due", help="今天必签 / 快过期 / 月度事项")
    s.set_defaults(func=cmd_due)

    s = sub.add_parser("doctor", help="探测本机安装与适配器")
    s.set_defaults(func=cmd_doctor)

    s = sub.add_parser("open", help="打开待手签客户端；可指定账户")
    s.add_argument("account", nargs="?", default=None)
    s.set_defaults(func=cmd_open)

    s = sub.add_parser("set-balance", help="按客户端看到的余额写入快照（不记签到）")
    s.add_argument("account")
    s.add_argument("amount", type=int)
    s.add_argument("--expires", default=None)
    s.set_defaults(func=cmd_set_balance)

    s = sub.add_parser("show", help="某个账户的 JSON 详情")
    s.add_argument("account")
    s.set_defaults(func=cmd_show)
    return p


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return int(args.func(args))
    except KeyError as exc:
        print(f"找不到账户: {exc}", file=sys.stderr)
        return 1
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 1
