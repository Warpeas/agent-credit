from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

from . import checkin as checkin_mod
from . import dispatch as dispatch_mod
from . import ledger
from . import lock as lock_mod
from . import trace
from . import mc_credits
from . import wb_credits
from . import board as board_mod
from . import autoclaw_credits
from . import trae_credits
from . import qodercn_credits
from .apps import launch
from .catalog import accounts, find_account
from .doctor import format_report, report
from .recommend import format_recommend, recommend


def cmd_idle(args: argparse.Namespace) -> int:
    """等键鼠空闲：返回 0=已空闲（可续跑）/ 3=超时仍活跃。"""
    from . import interaction

    decision = interaction.wait_for_idle(args.threshold, args.max, label="idle")
    print(json.dumps({"ok": decision.ok, "idle": round(decision.idle, 1),
                      "waited": round(decision.waited, 1)}, ensure_ascii=False))
    return 0 if decision.ok else 3


def _chain_state_line() -> str | None:
    """读计划任务链留下的阶段心跳，区分「等键鼠空闲」和「正在执行」。"""
    path = checkin_mod.REPO_ROOT / "logs" / "chain_state.json"
    try:
        st = json.loads(path.read_text(encoding="utf-8-sig"))
        at = datetime.strptime(st["at"], "%Y-%m-%d %H:%M:%S")
    except (OSError, ValueError, KeyError):
        return None
    if (datetime.now() - at).total_seconds() > 900:
        return None
    label = {
        "checkin": "签到中", "waiting_idle": "等待键鼠空闲",
        "running_ui": "UI 签到执行中", "resume": "续跑 UI 账户",
        "sync": "对账中", "deferred": "已让位", "done": "本轮已结束",
    }.get(st.get("phase"), str(st.get("phase") or "运行中"))
    note = str(st.get("note") or "").strip()
    tail = f"（{note}）" if note else ""
    return f"后台任务：{label}{tail}  [{st.get('at')} pid {st.get('pid')}]"


def cmd_status(_args: argparse.Namespace) -> int:
    data = ledger.load()
    on = ledger.today()
    lines = [f"日期 {on.isoformat()}  台账 {ledger.LEDGER_PATH}"]
    background = _chain_state_line()
    if background:
        lines.append(background)
    lines.append("")
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
    if action == "streak":
        # 按实际到账修正连签：签到动作成功但服务端没发额度时，mark_claimed 仍会 +1，
        # 连签就会虚高。这里只改计数，不动余额/条目（余额以 reconcile 为准）。
        if args.amount is None:
            print("streak 必须带天数", file=sys.stderr)
            return 1
        acc = find_account(args.account)
        data = ledger.load()
        st = ledger.state(data, acc["id"])
        old = st.get("streak_current") or 0
        st["streak_current"] = max(0, int(args.amount))
        ledger.save(data)
        print(f"{acc['name']} 连签 {old} → {st['streak_current']}（按实际到账修正）")
        return 0
    print("action 必须是 used / claimed / streak", file=sys.stderr)
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
        elif r.get("deferred"):
            # 客户端正在使用中：主动让位，不是失败，也不阻塞其他账户。
            print(f"{r['name']}: 对账跳过 — {r['detail']}")
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
    if account == "autoclaw":
        # 数据源 = 只读 UI 采集（scripts/autoclaw_credits_ui_capture2.py）的
        # 当天新鲜 JSON；不是今天的采集一律拒绝登记（防旧值覆盖真余额）。
        try:
            if args.allow_stale:
                data = autoclaw_credits.load_capture(fresh_only=False)
            else:
                data = autoclaw_credits.load_capture(fresh_only=True)
            payload = autoclaw_credits.build_payload(data)
        except SystemExit as exc:
            print(f"查询失败：{exc}", file=sys.stderr)
            return 1
        if args.ledger:
            slim = {k: v for k, v in payload.items() if k != "grants_raw"}
            print(json.dumps(slim, ensure_ascii=False))
            return 0
        if args.line:
            print(json.dumps({"balance": payload["total"],
                              "balance_at_capture": payload["balance_at_capture"],
                              "captured_at": payload["captured_at"]},
                             ensure_ascii=False))
            return 0
        if args.json:
            print(json.dumps(payload, ensure_ascii=False, indent=1, default=str))
        else:
            print(autoclaw_credits.format_text(payload))
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
    if getattr(args, "remaining", False):
        print(ledger.remaining(data, acc["id"]))
        return 0
    payload: dict[str, Any] = {
        "account": acc,
        "state": ledger.state(data, acc["id"]),
        "remaining": ledger.remaining(data, acc["id"]),
        "active": ledger.active_entries(data, acc["id"]),
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2, default=str))
    return 0


def _dispatch_candidates(task: dispatch_mod.Task, forced: str | None):
    return dispatch_mod.candidates(task, forced=forced)


def cmd_dispatch(args: argparse.Namespace) -> int:
    if args.usage:
        try:
            report = ledger.usage_stats(ledger.load(), since=args.since)
        except ValueError as exc:
            print(str(exc), file=sys.stderr)
            return 1
        if args.json:
            print(json.dumps(report, ensure_ascii=False, indent=2))
            return 0
        scope = f" --since {report['since']}" if report["since"] else ""
        print(f"用量聚合{scope}：事件 {report['events']} 条，legacy {report['legacy']} 条"
              f"（无 usage 字段，未回填、不计入合计）")
        if not report["rows"]:
            print("没有可聚合的用量事件")
            return 0
        print(f"{'提供者':<12} {'模型':<14} {'尝试':>4} {'输入token':>10} {'输出token':>10} "
              f"{'消耗额度':>9} {'剩余%':>6} {'重置时间':<26} {'失败':>4}")
        for r in report["rows"]:
            left = "-" if r["remaining_percent"] is None else f"{r['remaining_percent']:g}"
            print(f"{r['provider']:<12} {r['model']:<14} {r['attempts']:>4} "
                  f"{r['input_tokens']:>10} {r['output_tokens']:>10} "
                  f"{r['credits']:>9g} {left:>6} {str(r['reset_at'] or '-'):<26} "
                  f"{r['failed']:>4}")
        return 0

    if args.history:
        data = ledger.load()
        rows = ledger.dispatch_stats(data, limit=args.limit)
        if args.json:
            print(json.dumps(rows, ensure_ascii=False, indent=2))
            return 0
        if not rows:
            print("尚无派单记录")
            return 0
        for r in rows:
            avg = round(r["duration_s"] / r["runs"], 1) if r["runs"] else 0
            print(f"{r['provider']:<12} 次数 {r['runs']:>3}  成功 {r['ok']:>3}  "
                  f"回退 {r['fallback']:>3}  余额未知 {r['balance_unknown']:>3}  "
                  f"总耗时 {r['duration_s']}s  均值 {avg}s")
        return 0

    text = args.task or ""
    if args.task_file:
        text = Path(args.task_file).read_text(encoding="utf-8")
    elif text == "-":
        text = sys.stdin.read()
    if not text.strip() and not args.dry_run:
        print('用法: credit dispatch --capability <能力> --task "<任务文本>"', file=sys.stderr)
        return 1

    task = dispatch_mod.Task(
        text=text.strip(),
        capability=args.capability,
        cwd=Path(args.cwd) if args.cwd else None,
        timeout_s=args.timeout,
    )

    if args.dry_run:
        # 只看「谁会被试、为什么被跳过」，不真的派单、不记账
        providers = _dispatch_candidates(task, args.provider)
        if not providers:
            print(f"没有启用的提供者支持能力 {args.capability}", file=sys.stderr)
            return 1
        for p in providers:
            pre = p.preflight(task)
            state = "可用" if pre.available else f"不可用：{pre.reason}"
            print(f"{p.name:<12} priority={p.priority:<4} {state}")
        return 0

    outcome = dispatch_mod.run(task, forced=args.provider, allow_fallback=not args.no_fallback)

    total_s = round(sum(a.duration_s for a in outcome.attempts), 1)
    digest = hashlib.sha1(task.text.encode("utf-8")).hexdigest()[:12]
    dispatch_id = uuid.uuid4().hex[:12]
    # 每次尝试单独一条事件，各带自己的 usage 与尝试序号；不做重复累加。
    # 读-改-写全程持账本锁：后台实例/另一个 CLI 同时记账时不会互相覆盖。
    with ledger.transaction() as data:
        for index, attempt in enumerate(outcome.attempts, 1):
            ledger.record_dispatch(
                data,
                dispatch_id=dispatch_id,
                attempt=index,
                provider=attempt.provider,
                capability=task.capability,
                ok=attempt.ok,
                duration_s=attempt.duration_s,
                exit_code=attempt.exit_code,
                fallback=bool(outcome.ok and attempt.ok and index > 1),
                attempts=[f"{attempt.provider}({'ok' if attempt.ok else 'fail'},{attempt.duration_s}s)"],
                balance_before=attempt.balance_before,
                balance_unknown=attempt.balance_unknown,
                task_digest=digest,
                note=(attempt.note or "")[:400],
                usage=attempt.usage,
                route=attempt.route,
            )

    if args.json:
        print(json.dumps({
            "ok": outcome.ok,
            "provider": outcome.provider,
            "fallback": outcome.fallback,
            "balance_unknown": outcome.balance_unknown,
            "duration_s": total_s,
            "exit_code": outcome.exit_code,
            "attempts": [a.__dict__ for a in outcome.attempts],
            "text": outcome.text,
        }, ensure_ascii=False, indent=2))
        return 0 if outcome.ok else (outcome.exit_code or 1)

    for a in outcome.attempts:
        mark = "ok  " if a.ok else "fail"
        detail = f" {a.note}" if a.note else ""
        print(f"[{mark}] {a.provider} {a.duration_s}s{detail}", file=sys.stderr)
    if outcome.ok:
        if outcome.fallback:
            print(f"（已回退到 {outcome.provider}）", file=sys.stderr)
        print(outcome.text)
        return 0
    print("派单失败：所有候选提供者都不可用或执行失败", file=sys.stderr)
    return outcome.exit_code or 1


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="credit", description="Agent 积分台账与签到")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("status", help="各家余额与签到状态")
    s.set_defaults(func=cmd_status)

    s = sub.add_parser("idle", help="等键鼠空闲（0=已空闲 / 3=超时仍活跃）")
    s.add_argument("--threshold", type=float, default=60,
                   help="连续无输入多少秒算空闲（默认 60）")
    s.add_argument("--max", type=float, default=300,
                   help="最多等多少秒（默认 300）")
    s.set_defaults(func=cmd_idle)

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

    s = sub.add_parser("record", help="手签入账、登记消耗、修正连签")
    s.add_argument("account")
    s.add_argument("action", choices=["used", "claimed", "streak"],
                   help="claimed=签到入账；used=登记消耗；streak=按实际到账修正连签")
    s.add_argument("amount", nargs="?", type=int, default=None)
    s.add_argument("--source", default="daily")
    s.add_argument("--expires", default=None, help="YYYY-MM-DD，默认按 catalog 有效期")
    s.set_defaults(func=cmd_record)

    s = sub.add_parser("due", help="今天必签 / 快过期 / 月度事项")
    s.set_defaults(func=cmd_due)

    s = sub.add_parser("sync", help="对账：拉服务端真实余额校正台账（不记签到；checkin 末尾也会自动跑）")
    s.add_argument("--only", help="只处理一个账户 id/别名")
    s.set_defaults(func=cmd_sync)

    s = sub.add_parser("credits", help="查询积分明细（余额+过期时间）；支持 workbuddy / trae / monkeycode_credit / qodercn / autoclaw")
    s.add_argument("account", nargs="?", default="workbuddy", help="账户 id，默认 workbuddy")
    s.add_argument("--all", action="store_true", help="包含已用完/已过期的条目")
    s.add_argument("--ledger", action="store_true",
                   help="对账 JSON（credits_command 约定，autoclaw 用）")
    s.add_argument("--allow-stale", action="store_true",
                   help="autoclaw：允许旧采集（仅查看，不登记）")
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
    s.add_argument("--remaining", action="store_true",
                   help="只打印余额数字（给脚本取数用，免去解析带中文的 JSON）")
    s.set_defaults(func=cmd_show)

    s = sub.add_parser("dispatch", help="把任务派给本机其它 agent（单机串行，按 providers.yaml 优先级）")
    s.add_argument("--capability", default="text",
                   help="任务能力标签，匹配 providers.yaml 里的 capabilities（默认 text）")
    s.add_argument("--task", default=None, help='任务文本；传 "-" 从 stdin 读')
    s.add_argument("--task-file", default=None, help="从文件读任务文本")
    s.add_argument("--cwd", default=None, help="给支持工作目录的适配器指定目录")
    s.add_argument("--provider", default=None, help="强制只用一个提供者（不做回退）")
    s.add_argument("--no-fallback", action="store_true", help="首个提供者失败即停")
    s.add_argument("--timeout", type=int, default=600, help="单个提供者超时秒数")
    s.add_argument("--dry-run", action="store_true", help="只做候选与预检，不派单不记账")
    s.add_argument("--history", action="store_true", help="查看 ledger 里的派单聚合统计")
    s.add_argument("--usage", action="store_true",
                   help="按提供者/模型聚合用量（token、消耗额度、剩余百分比、失败条数）")
    s.add_argument("--since", default=None,
                   help="配合 --usage 限制时间范围：7d / 24h / YYYY-MM-DD")
    s.add_argument("--limit", type=int, default=None, help="--history 只看最近 N 条事件")
    s.add_argument("--json", action="store_true", help="输出 JSON")
    s.set_defaults(func=cmd_dispatch)
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
