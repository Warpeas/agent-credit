"""积分余额看板：把台账里各家的余额、每条积分的剩余与过期时间汇成一张表。

看板回答三个问题：

  1. 一共剩多少、分别剩多少、这些数字是**服务端真值**还是**本地估算**
  2. 哪些积分快过期、还剩几天（该先烧谁）
  3. 烧卡优先级怎么排——与 recommend 共用 priority.py 的同一套规则，
     避免「看板说先烧 A、推荐却说先烧 B」

只读台账，不写账本。落盘产物：

    logs/board/board-YYYY-MM-DD.md   人看
    data/board.json                    机器读

数据来源只有账本（data/ledger.json）——账本里的每条积分都带 remaining 与
expires_at。服务端逐条明细的账户（WorkBuddy、MiniMax、Qoder CN）过期日是真的；
MonkeyCode 只有服务端总量、过期未知；AutoClaw 有效期分类且服务端不下发逐条
到期日，台账按「过期未知」处理；LobsterAI 按签到规则估算。看板上分别标成
「服务端真值」「本地估算」「过期未知」，不混为一谈。
"""
from __future__ import annotations

import argparse
import json
import sys
import unicodedata
from datetime import date, datetime
from pathlib import Path
from typing import Any

from . import ledger
from . import priority
from .catalog import accounts, find_account
from .console import use_utf8
from .paths import DATA_DIR, LOG_DIR

BOARD_DIR = LOG_DIR / "board"
BOARD_JSON = DATA_DIR / "board.json"

SOURCE_LABELS = {
    "sync": "服务端对账",
    "daily": "每日签到",
    "streak": "连签奖励",
    "snapshot": "本地快照",
}

QUALITY_LABELS = {
    "server": "服务端真值",
    "estimate": "本地估算",
    "mixed": "真值+估算",
}

EXPIRY_BASIS_LABELS = {
    "server": "服务端",
    "estimate": "估算",
    # 余额经服务端对账校正，但过期日是「领取日 + catalog 有效期」推出来的
    # （服务端只下发桶总数的那类账户，如 Qoder CN）
    "derived": "按领取日推导",
    "mixed": "服务端+估算",
    "unknown": "未知",
}


def _w(text: Any) -> int:
    """显示宽度：CJK 全角算 2 列，否则表格会歪。"""
    return sum(2 if unicodedata.east_asian_width(c) in ("W", "F") else 1
               for c in str(text))


def _pad(text: Any, width: int) -> str:
    return str(text) + " " * max(0, width - _w(text))


def _fmt_int(value: Any) -> str:
    try:
        return f"{int(value):,}"
    except (TypeError, ValueError):
        return str(value)


def _grant_rows(data: dict[str, Any], acc: dict[str, Any],
                on: date) -> list[dict[str, Any]]:
    """账户的每条有效积分：剩余 + 过期日 + 口径。"""
    rows = []
    for entry in ledger.active_entries(data, acc["id"], on):
        expires = entry.get("expires_at")
        source = entry.get("source")
        rows.append({
            "remaining": int(entry.get("remaining") or 0),
            "expires_at": expires,
            "days_left": priority.days_left(expires, on),
            "granted_at": entry.get("granted_at"),
            "source": source,
            "source_label": SOURCE_LABELS.get(source, source or "-"),
            # 过期日是服务端给的（sync）还是按 catalog 有效期算的（daily/streak）。
            # 条目自带 expiry_basis 时以它为准：对账校正过总量的账户（reconcile）
            # 余额是真值、过期日却是推导值，两个口径不能用同一个 source 分辨。
            "expiry_basis": entry.get("expiry_basis") or (
                ("server" if source == "sync" else "estimate") if expires else "unknown"),
        })
    return rows


def _classify(grants: list[dict[str, Any]], key: str) -> str:
    values = {g[key] for g in grants}
    if not values:
        return "unknown"
    if values == {"server"}:
        return "server"
    if values == {"estimate"}:
        return "estimate"
    if values == {"unknown"}:
        return "unknown"
    return "mixed"


def build(data: dict[str, Any] | None = None, on: date | None = None,
          account: str | None = None) -> dict[str, Any]:
    """看板数据。account 只看一家（给 --account 用）。"""
    on = on or ledger.today()
    data = data if data is not None else ledger.load()

    acc_list = accounts()
    if account:
        acc = find_account(account)
        acc_list = [acc]

    rows: list[dict[str, Any]] = []
    for acc in acc_list:
        grants = _grant_rows(data, acc, on)
        remaining = ledger.remaining(data, acc["id"], on)
        expires_list = [g["expires_at"] for g in grants if g["expires_at"]]
        soonest = min(expires_list) if expires_list else None
        st = ledger.state(data, acc["id"])
        rows.append({
            "id": acc["id"],
            "name": acc["name"],
            "unit": acc.get("unit"),
            "remaining": remaining,
            "grant_count": len(grants),
            "grants": grants,
            "soonest_expiry": soonest,
            "days_left": priority.days_left(soonest, on),
            "quality": _quality(grants),
            "expiry_basis": _classify(grants, "expiry_basis"),
            "last_sync": st.get("last_sync"),
            "tier": priority.tier(acc, data, on),
            "tier_label": priority.tier_label(priority.tier(acc, data, on)),
            "grant_type": acc.get("grant_type"),
            "cap": acc.get("cap"),
            "daily_amount": acc.get("daily_amount") or 0,
        })

    funded = [r for r in rows if r["remaining"] > 0]
    burn_order = sorted(
        funded,
        key=lambda r: priority.account_sort_key(find_account(r["id"]), data, on),
    )

    near = [dict(g, account_id=r["id"], account_name=r["name"])
            for r in rows for g in r["grants"]
            if g["days_left"] is not None and 0 <= g["days_left"] <= priority.EXPIRY_WINDOW_DAYS]
    near.sort(key=lambda g: (g["days_left"], -g["remaining"]))

    return {
        "date": on.isoformat(),
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        # 视图范围：None=全量看板；单账户时只出该账户的视图
        "scope": account,
        "total_remaining": sum(r["remaining"] for r in rows),
        "funded_count": len(funded),
        "account_count": len(rows),
        "accounts": rows,
        "near_expiry": near,
        "burn_order": [r["id"] for r in burn_order],
        "expiry_unknown": [
            {"id": r["id"], "name": r["name"], "remaining": r["remaining"],
             "grants": r["grant_count"]}
            for r in funded if not r["soonest_expiry"]
        ],
    }


def _quality(grants: list[dict[str, Any]]) -> str:
    """余额口径：全是服务端对账条目 = 真值；全是本地登记 = 估算；混合 = 混合。

    逐包明细的账户（Trae 走「用量管理」OCR 入账）来源不是 "sync"，但余额与
    到期日都逐笔来自服务端页面，故 expiry_basis 全为 server 时同样算真值。
    """
    sources = {g["source"] for g in grants}
    if not sources:
        return "unknown"
    bases = {g["expiry_basis"] for g in grants}
    if sources == {"sync"} or bases == {"server"}:
        return "server"
    if "sync" in sources or "server" in bases:
        return "mixed"
    return "estimate"


def format_text(board: dict[str, Any]) -> str:
    """终端可读看板。"""
    lines: list[str] = []
    lines.append(f"积分余额看板 · {board['date']} · 生成于 {board['generated_at']}")
    lines.append(f"合计剩余 {_fmt_int(board['total_remaining'])} ｜ 有余额 {board['funded_count']} 家"
                 f" ｜ {priority.EXPIRY_WINDOW_DAYS} 天内到期 {len(board['near_expiry'])} 笔")
    lines.append("")

    funded = [r for r in board["accounts"] if r["remaining"] > 0]
    lines.append("【账户总表】")
    if not funded:
        lines.append("  （台账里没有有余额的账户）")
    else:
        lines.append("  " + _pad("账户", 18) + _pad("余额", 10) + _pad("笔数", 6)
                     + _pad("最近过期", 13) + _pad("剩余天", 7) + _pad("口径", 12) + "层级")
        for r in funded:
            lines.append("  " + _pad(r["name"], 18) + _pad(_fmt_int(r["remaining"]), 10)
                         + _pad(r["grant_count"], 6) + _pad(r["soonest_expiry"] or "-", 13)
                         + _pad(r["days_left"] if r["days_left"] is not None else "-", 7)
                         + _pad(QUALITY_LABELS.get(r["quality"], r["quality"]), 12)
                         + r["tier_label"])
            if r["last_sync"]:
                lines.append("  " + " " * 18 + f"↳ 最近对账 {r['last_sync']}")
    lines.append("")

    lines.append(f"【临期队列 · {priority.EXPIRY_WINDOW_DAYS} 天内】先烧这些")
    if not board["near_expiry"]:
        lines.append("  （无）")
    else:
        lines.append("  " + _pad("剩余", 9) + _pad("到期", 13) + _pad("剩", 5) + "账户")
        for g in board["near_expiry"]:
            lines.append("  " + _pad(_fmt_int(g["remaining"]), 9) + _pad(g["expires_at"], 13)
                         + _pad(g["days_left"], 5) + g["account_name"])
    lines.append("")

    lines.append("【烧卡优先级】")
    # 按 burn_order 取行，不能按 accounts 的 catalog 顺序——否则层级排序白算了
    by_id = {r["id"]: r for r in board["accounts"]}
    order = [by_id[i] for i in board["burn_order"] if i in by_id]
    for i, r in enumerate(order, 1):
        lines.append(f"  {i}. {_pad(r['name'], 18)}{_pad(_fmt_int(r['remaining']), 9)}"
                     f"{_pad(r['tier_label'], 18)}最近到期 {r['soonest_expiry'] or '未知'}")
    lines.append("  规则：当日清零 > 7 天内到期 > 长期 FIFO > 有上限待补 > 过期未知（最后动）")
    lines.append("")

    for r in funded:
        if not r["grants"]:
            continue
        lines.append(f"【逐条明细 · {r['name']}】{QUALITY_LABELS.get(r['quality'], '')}")
        lines.append("  " + _pad("到期", 13) + _pad("剩余", 9) + _pad("剩余天", 7)
                     + _pad("来源", 12) + "过期口径")
        for g in r["grants"]:
            lines.append("  " + _pad(g["expires_at"] or "-", 13) + _pad(_fmt_int(g["remaining"]), 9)
                         + _pad(g["days_left"] if g["days_left"] is not None else "-", 7)
                         + _pad(g["source_label"], 12)
                         + EXPIRY_BASIS_LABELS.get(g["expiry_basis"], g["expiry_basis"]))
        lines.append("")

    lines.append("【数据质量】")
    server = [r["name"] for r in funded if r["quality"] == "server"]
    est = [r["name"] for r in funded if r["quality"] == "estimate"]
    mixed = [r["name"] for r in funded if r["quality"] == "mixed"]
    if server:
        lines.append(f"  服务端真值：{'、'.join(server)}")
    if mixed:
        lines.append(f"  真值+估算：{'、'.join(mixed)}")
    if est:
        lines.append(f"  本地估算：{'、'.join(est)}")
    for u in board["expiry_unknown"]:
        lines.append(f"  ⚠️ 过期未知：{u['name']}（{u['grants']} 笔 / {_fmt_int(u['remaining'])}）"
                     "——台账没有有效期，排序按「最后动」处理")
    return "\n".join(lines)


def format_markdown(board: dict[str, Any]) -> str:
    """落盘的 Markdown 看板。"""
    lines: list[str] = []
    lines.append(f"# 积分余额看板 · {board['date']}")
    lines.append("")
    lines.append(f"生成于 {board['generated_at']} ｜ 合计剩余 **{_fmt_int(board['total_remaining'])}**"
                 f" ｜ 有余额 **{board['funded_count']}** 家"
                 f" ｜ {priority.EXPIRY_WINDOW_DAYS} 天内到期 **{len(board['near_expiry'])}** 笔")
    lines.append("")
    lines.append("## 账户总表")
    lines.append("")
    lines.append("| 账户 | 余额 | 笔数 | 最近过期 | 剩余天 | 口径 | 层级 | 最近对账 |")
    lines.append("|---|---:|---:|---|---:|---|---|---|")
    for r in board["accounts"]:
        if r["remaining"] <= 0:
            continue
        lines.append(f"| {r['name']} | {_fmt_int(r['remaining'])} | {r['grant_count']} | "
                     f"{r['soonest_expiry'] or '-'} | "
                     f"{r['days_left'] if r['days_left'] is not None else '-'} | "
                     f"{QUALITY_LABELS.get(r['quality'], r['quality'])} | {r['tier_label']} | "
                     f"{r['last_sync'] or '-'} |")
    lines.append("")
    lines.append(f"## 临期队列（{priority.EXPIRY_WINDOW_DAYS} 天内，先烧这些）")
    lines.append("")
    if not board["near_expiry"]:
        lines.append("无")
    else:
        lines.append("| 剩余 | 到期 | 剩 | 账户 |")
        lines.append("|---:|---|---:|---|")
        for g in board["near_expiry"]:
            lines.append(f"| {_fmt_int(g['remaining'])} | {g['expires_at']} | "
                         f"{g['days_left']} | {g['account_name']} |")
    lines.append("")
    lines.append("## 烧卡优先级")
    lines.append("")
    by_id = {r["id"]: r for r in board["accounts"]}
    for i, rid in enumerate(board["burn_order"], 1):
        r = by_id.get(rid)
        if r is None:
            continue
        lines.append(f"{i}. **{r['name']}** — {_fmt_int(r['remaining'])} ｜ {r['tier_label']}"
                     f" ｜ 最近到期 {r['soonest_expiry'] or '未知'}")
    lines.append("")
    for rule in priority.TIER_RULES:
        lines.append(f"- {rule}")
    lines.append("")
    lines.append("## 逐条明细")
    lines.append("")
    for r in board["accounts"]:
        if r["remaining"] <= 0 or not r["grants"]:
            continue
        lines.append(f"### {r['name']}（{QUALITY_LABELS.get(r['quality'], r['quality'])}）")
        lines.append("")
        lines.append("| 到期 | 剩余 | 剩余天 | 来源 | 过期口径 |")
        lines.append("|---|---:|---:|---|---|")
        for g in r["grants"]:
            lines.append(f"| {g['expires_at'] or '-'} | {_fmt_int(g['remaining'])} | "
                         f"{g['days_left'] if g['days_left'] is not None else '-'} | "
                         f"{g['source_label']} | "
                         f"{EXPIRY_BASIS_LABELS.get(g['expiry_basis'], g['expiry_basis'])} |")
        lines.append("")
    lines.append("## 数据质量")
    lines.append("")
    for r in board["accounts"]:
        if r["remaining"] <= 0:
            continue
        lines.append(f"- **{r['name']}**：余额口径 {QUALITY_LABELS.get(r['quality'], r['quality'])}"
                     f"｜过期口径 {EXPIRY_BASIS_LABELS.get(r['expiry_basis'], r['expiry_basis'])}")
    for u in board["expiry_unknown"]:
        lines.append(f"- ⚠️ **{u['name']}** 过期未知（{u['grants']} 笔 / {_fmt_int(u['remaining'])}），"
                     "排序按「最后动」处理")
    return "\n".join(lines) + "\n"


def write(board: dict[str, Any], out: str | Path | None = None) -> dict[str, Path]:
    """落盘：Markdown（人看）+ JSON（机器读）。返回写到的路径。

    **单账户视图不覆盖全量看板**：`--account xxx` 的产物写自己的文件名，
    共享的 data/board.json 也不动。否则「看一眼某一家」会把当天的全量看板
    冲成单账户视图——看板是每天要对着看的东西，不能被随手一条命令改掉。
    """
    on = board.get("date") or date.today().isoformat()
    scope = board.get("scope")
    if out:
        md_path = Path(out)
    else:
        BOARD_DIR.mkdir(parents=True, exist_ok=True)
        suffix = f"-{scope}" if scope else ""
        md_path = BOARD_DIR / f"board-{on}{suffix}.md"
    md_path.parent.mkdir(parents=True, exist_ok=True)
    md_path.write_text(format_markdown(board), encoding="utf-8")
    result = {"markdown": md_path}
    if scope:
        # 单账户视图另存一份 JSON，不碰共享的 data/board.json
        scoped_json = DATA_DIR / f"board-{scope}.json"
        scoped_json.write_text(json.dumps(board, ensure_ascii=False, indent=2, default=str),
                               encoding="utf-8")
        result["json"] = scoped_json
    else:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        BOARD_JSON.write_text(json.dumps(board, ensure_ascii=False, indent=2, default=str),
                              encoding="utf-8")
        result["json"] = BOARD_JSON
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="board", description="积分余额看板")
    parser.add_argument("--account", help="只看一个账户")
    parser.add_argument("--json", action="store_true", help="输出 JSON")
    parser.add_argument("--out", default=None, help="Markdown 输出路径")
    parser.add_argument("--no-write", action="store_true", help="不落盘")
    args = parser.parse_args(argv)
    board = build(account=args.account)
    if args.json:
        print(json.dumps(board, ensure_ascii=False, indent=1, default=str))
    else:
        print(format_text(board))
    if not args.no_write:
        paths = write(board, args.out)
        print(f"看板已写入 {paths['markdown']}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    use_utf8()
    sys.exit(main())
