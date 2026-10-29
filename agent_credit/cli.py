from __future__ import annotations

import argparse
import json
import sys
import time
from typing import Any

from . import checkin as checkin_mod
from . import ledger
from . import lock as lock_mod
from . import trace
from . import mc_credits
from . import wb_credits
from . import board as board_mod
from . import trae_credits
from . import qodercn_credits
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
    # 防撞锁：每日链路用 PowerShell 端 FileShare.None 持有同名的 logs\checkin.lock，
    # 这里抢不到就说明另一条链路正在跑，别再开第二个客户端。链路自己调用时
    # （AGENT_CREDIT_LOCK_HELD=1）直接放行，不再重复抢。
    lock = None
    locked_out = False
    try:
        lock = lock_mod.acquire_for_checkin()
        locked_out = lock is None and not lock_mod.held_by_parent()
    except OSError as exc:
        # 锁自身坏了（权限/路径）不该让当天的签到整轮失败：提示后照常跑。
        print(f"签到锁不可用（{exc}），本次跳过防撞检查", file=sys.stderr)
    if locked_out:
        print("另一个签到正在运行（logs/checkin.lock）；等它结束再试，"
              "或设 AGENT_CREDIT_LOCK_WAIT=秒数 等待", file=sys.stderr)
        return 4
    try:
        return _run_checkin(args)
    finally:
        if lock is not None:
            lock.release()


def _run_checkin(args: argparse.Namespace) -> int:
    trace.init()
    results, _ = checkin_mod.checkin(
        only=args.only,
        gate_sec=args.gate_sec,
        gate_enabled=not args.no_gate,
    )
    pending = failed = ok = skipped = 0
    for r in results:
        if r.status == "skipped":
            # 跳过的在循环里已经实时打过一行，汇总里再打一遍纯属噪音
            skipped += 1
            continue
        trace.note(
            f"{r.name}: {r.detail}" + (f"  +{r.amount}" if r.amount else ""),
            label=f"{r.status} @{trace.elapsed_at(r.at)}s",
        )
        if r.status == "pending":
            pending += 1
        elif r.status == "failed":
            failed += 1
        elif r.status == "ok":
            ok += 1
        else:
            skipped += 1
    if args.open:
        for r in results:
            if r.status != "pending":
                continue
            try:
                exe = launch(r.account_id)
                trace.note(f"已打开 {r.name}: {exe}")
            except FileNotFoundError:
                trace.note(f"未安装或未知路径：{r.name}，请手动打开")
    trace.note(f"汇总：ok {ok} / skipped {skipped} / pending {pending} / failed {failed}")
    trace.note(f"总耗时 {trace.elapsed_at(time.time())}s")
    if pending or failed:
        trace.note(f"明细日志：{trace.init()}")
    if args.hold > 0:
        trace.note(f"停留 {args.hold}s 后关闭窗口（Ctrl+C 可提前退出）")
        time.sleep(args.hold)
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


def cmd_sync(args: argparse.Namespace) -> int:
    trace.init()
    results = checkin_mod.sync(only=args.only)
    if not results:
        print("没有可对账的账户（在 catalog.yaml 配置 credits_command 或 status_command）")
        return 0
    bad = 0
    for r in results:
        if r["ok"]:
            print(f"{r['name']}: {r['before']} → {r['after']}"
                  f"（{r['mode']}，{r['entries']} 条）")
        else:
            bad += 1
            print(f"{r['name']}: 对账失败 — {r['detail']}", file=sys.stderr)
    return 1 if bad else 0


def cmd_credits(args: argparse.Namespace) -> int:
    account = (args.account or "workbuddy").lower()
    try:
        account = find_account(account)["id"]
    except KeyError:
        pass
    if account == "workbuddy":
        if args.line:
            # status_command 约定：一行 JSON。claimed_today 失败不炸主流程（返回 null）。
            result = wb_credits.fetch_credits()
            print(json.dumps({"balance": result["summary"]["total_credits"],
                              "claimed_today": wb_credits.claimed_today()},
                             ensure_ascii=False))
            return 0
        result = wb_credits.fetch_credits()
        if args.json:
            print(json.dumps(result, ensure_ascii=False, indent=1, default=str))
        else:
            print(wb_credits.format_text(result, show_all=args.all))
        return 0
    if account == "trae":
        try:
            parsed = trae_credits.parse_dump(trae_credits.load_dump())
        except trae_credits.CreditQueryError as exc:
            print(f"查询失败：{exc}", file=sys.stderr)
            return 1
        if args.line:
            p = trae_credits.payload(parsed)
            print(json.dumps({"balance": p["total"],
                              "claimed_today": parsed.get("claimed_today")},
                             ensure_ascii=False))
            return 0
        if args.json:
            print(json.dumps(trae_credits.payload(parsed), ensure_ascii=False,
                             indent=1, default=str))
        else:
            print(trae_credits.format_text(parsed))
        return 0
    if account in ("monkeycode_credit", "mc积分"):
        try:
            result = mc_credits.fetch_credits()
        except mc_credits.CreditQueryError as exc:
            print(f"查询失败：{exc}", file=sys.stderr)
            return 1
        if args.line:
            print(json.dumps({"balance": result["balance"],
                              "claimed_today": result["claimed_today"]},
                             ensure_ascii=False))
            return 0
        if args.json:
            print(json.dumps(result, ensure_ascii=False, indent=1, default=str))
        else:
            print(mc_credits.format_text(result))
        return 0
    if account in ("qodercn", "qoder"):
        try:
            record = qodercn_credits.find_usage_record()
        except qodercn_credits.CreditQueryError as exc:
            print(f"查询失败：{exc}", file=sys.stderr)
            return 1
        campaign = qodercn_credits.find_campaign_state()
        if args.line:
            # --line 是给 status_command 用的：非当天的记录一律不报（闸门同 --ledger）
            if not qodercn_credits.is_fresh(record):
                print(f"记录不是今天的（{record.get('recorded_date') or '未知'}），"
                      "拒绝输出：请在 Qoder 打开一次「我的用量」面板", file=sys.stderr)
                return 1
            print(json.dumps({"balance": qodercn_credits.total_remaining(record),
                              "claimed_today": qodercn_credits.claimed_today(campaign)},
                             ensure_ascii=False))
            return 0
        if args.json:
            print(json.dumps(qodercn_credits.ledger_payload(record), ensure_ascii=False,
                             indent=1, default=str))
        else:
            print(qodercn_credits.format_text(record, campaign))
        return 0
    print("积分明细查询目前支持 workbuddy / trae / monkeycode_credit / qodercn"
          "（其余家见 research/answers/ 的登记进度）",
          file=sys.stderr)
    return 1


def cmd_board(args: argparse.Namespace) -> int:
    """积分余额看板：余额 + 每条积分的剩余与过期时间 + 烧卡优先级。"""
    board = board_mod.build(account=args.account)
    if args.json:
        print(json.dumps(board, ensure_ascii=False, indent=1, default=str))
    else:
        print(board_mod.format_text(board))
    if not args.no_write:
        paths = board_mod.write(board, args.out)
        print(f"看板已写入 {paths['markdown']}", file=sys.stderr)
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
    s.add_argument("--hold", type=int, default=0, help="结束后停留 N 秒再关窗口（手动跑时用来看清结果）")
    s.add_argument("--gate-sec", type=int, default=None,
                   help="启动提示的倒计时秒数（默认 15；超时自动开始）")
    s.add_argument("--no-gate", action="store_true",
                   help="不弹启动提示、不等空闲，直接开始（无人值守/排查时用）")
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

    s = sub.add_parser("sync", help="对账：拉服务端真实余额校正台账（不记签到；checkin 末尾也会自动跑）")
    s.add_argument("--only", help="只处理一个账户 id/别名")
    s.set_defaults(func=cmd_sync)

    s = sub.add_parser("credits", help="查询积分明细（余额+过期时间）；支持 workbuddy / trae / monkeycode_credit / qodercn")
    s.add_argument("account", nargs="?", default="workbuddy", help="账户 id，默认 workbuddy")
    s.add_argument("--all", action="store_true", help="包含已用完/已过期的条目")
    s.add_argument("--json", action="store_true", help="输出全量 JSON")
    s.add_argument("--line", action="store_true",
                   help='输出一行 JSON：{"balance": N, "claimed_today": bool}')
    s.set_defaults(func=cmd_credits)

    s = sub.add_parser("board", help="积分余额看板：各家余额 + 每条积分的剩余与过期时间 + 烧卡优先级")
    s.add_argument("--account", help="只看一个账户")
    s.add_argument("--json", action="store_true", help="输出 JSON")
    s.add_argument("--out", default=None, help="Markdown 输出路径（默认 logs/board/board-日期.md）")
    s.add_argument("--no-write", action="store_true", help="只打印，不落盘")
    s.set_defaults(func=cmd_board)

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
