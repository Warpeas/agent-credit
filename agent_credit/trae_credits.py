"""Trae 积分明细查询（只读，2026-10-20 接入通用对账契约）。

查什么：登录用户的剩余积分详情——总余额、**过期时间**，以及（dump 里存在时）
每个权益包的逐包余额与到期日。

数据源：客户端自带扩展 trae-credit-dump 导出的 logs/trae_credit_detail.json。
扩展只 executeCommand 客户端自己注册的 getter（icubeGetEntitlementInfo /
creditsUsage / checkinSnapshot），不碰凭据、不解密、无注入——
属 research/SAFETY.md 第 2 节「让客户端自己说话」的允许路线。

口径（别把它当成逐条真相）：

  * 结构化通道只给**聚合** creditsUsage：limit / used / remaining / expireTime。
    expireTime 是客户端展示的「最高优包到期日」；免费单桶账号下它即每笔的到期日。
  * 逐包清单 user_entitlement_pack_list 只在「设置 → 用量管理」页渲染
    （icubeOpenUsageDetails），结构化通道里没有。dump 里若存在就按包逐条登记
    （granularity=per_pack），不存在就按聚合口径登记（granularity=aggregate）
    并在载荷里标明，免得下游把聚合值当逐包真相用。

新鲜度闸门：**只有当天的 dump 才允许登记**。2026-10-20 实测过用昨天的旧 dump
登记，会把当天签到后的真实余额覆盖成旧值。判定看 beijingDayKey；
不是今天的 dump 直接退出非 0（对账记失败、不动账本）。

用法：
    python -m agent_credit.trae_credits            # 人类可读
    python -m agent_credit.trae_credits --json     # 账本对账载荷（sync 消费）
    python -m agent_credit.trae_credits --force    # 允许非当天的 dump（只看不登记）
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import date, datetime
from pathlib import Path
from typing import Any

from .console import use_utf8
from .paths import LOG_DIR

DUMP_PATH = LOG_DIR / "trae_credit_detail.json"
ACCOUNT = "trae"


class CreditQueryError(Exception):
    """查询失败（dump 缺失 / 解析失败）。消息固定，不含凭据。"""


def ts_to_str(value: Any) -> str | None:
    """epoch 毫秒/秒 -> 'YYYY-MM-DD HH:MM:SS'。拿不准就返回 None，不猜。"""
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value <= 0:
        return None
    ts = value / 1000 if value > 1e12 else value
    try:
        return datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S")
    except (OSError, OverflowError, ValueError):
        return None


def find_pack_list(node: Any) -> tuple[list[Any] | None, str | None]:
    """递归找 user_entitlement_pack_list，返回 (packs, origin_path) 或 (None, None)。"""
    if isinstance(node, dict):
        for k, v in node.items():
            if k == "user_entitlement_pack_list" and isinstance(v, list):
                return v, k
        for k, v in node.items():
            found, path = find_pack_list(v)
            if found is not None:
                return found, f"{k}.{path}"
    elif isinstance(node, list):
        for i, v in enumerate(node):
            found, path = find_pack_list(v)
            if found is not None:
                return found, f"[{i}].{path}"
    return None, None


def pack_row(pack: dict[str, Any]) -> dict[str, Any]:
    """逐包行：剩余 / 额度 / 已用 / 到期日（字段名以 dump 实测为准）。"""
    base = pack.get("entitlement_base_info") or {}
    quota = base.get("quota") or {}
    usage = pack.get("usage") or {}
    limit = quota.get("credits_limit")
    used = usage.get("credits_amount") or 0
    expire = pack.get("expire_time") or base.get("end_time") or pack.get("yearly_expire_time")
    remaining: int | None
    if limit == -1:
        remaining = None          # 不限量：登记不出有限额度，跳过
    elif isinstance(limit, (int, float)) and not isinstance(limit, bool):
        remaining = max(int(limit - used), 0)
    else:
        remaining = None
    return {
        "product_type": base.get("product_type"),
        "desc": pack.get("display_desc") or base.get("display_desc") or "",
        "status": pack.get("status"),
        "limit": limit,
        "used": used,
        "remaining": remaining,
        "expire": ts_to_str(expire),
    }


def load_dump(path: Path | None = None) -> dict[str, Any]:
    """读客户端导出的 dump。缺失/坏文件抛 CreditQueryError（不猜、不硬钻）。"""
    path = path or DUMP_PATH
    if not path.is_file():
        raise CreditQueryError(
            f"没有 {path.name}——先跑 scripts/trae_credit_sync.ps1 让客户端导出积分明细")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise CreditQueryError(f"dump 解析失败：{exc}") from None
    if not isinstance(payload, dict):
        raise CreditQueryError("dump 不是 JSON 对象")
    return payload


def parse_dump(payload: dict[str, Any]) -> dict[str, Any]:
    """把 dump 归一成：总余额 / 到期日 / 逐包 / 签到快照 / dump 时间。"""
    results = payload.get("results") or {}
    usage = (results.get("creditsUsage") or {}).get("data") or {}
    snap = (results.get("checkinSnapshot") or {}).get("data") or {}
    packs, origin = find_pack_list(payload)
    total = usage.get("remaining")
    if isinstance(total, bool) or not isinstance(total, (int, float)):
        total = None
    return {
        "total": total,
        "limit": usage.get("limit"),
        "used": usage.get("used"),
        "expire_at": ts_to_str(usage.get("expireTime")),
        "packs": packs or [],
        "packs_origin": origin,
        "day_key": str(snap.get("beijingDayKey") or ""),
        "claimed_today": bool(snap.get("checkedIn")),
        "claim_credits": snap.get("credits"),
        "claim_extra": snap.get("extraCredits"),
        "fetched_at": str(payload.get("fetched_at") or ""),
    }


def dump_date(parsed: dict[str, Any]) -> date | None:
    """dump 归属的本地日期：优先 beijingDayKey，其次 fetched_at（UTC→本地）。"""
    key = parsed.get("day_key") or ""
    if len(key) >= 10:
        try:
            return date.fromisoformat(key[:10])
        except ValueError:
            pass
    fetched = parsed.get("fetched_at") or ""
    if fetched:
        try:
            dt = datetime.fromisoformat(fetched.replace("Z", "+00:00"))
            return dt.astimezone().date()
        except ValueError:
            pass
    return None


def is_fresh(parsed: dict[str, Any], on: date | None = None) -> bool:
    """当天的 dump 才算新鲜。昨天的旧 dump 会把今天的真实余额覆盖成旧值。"""
    on = on or date.today()
    return dump_date(parsed) == on


def build_grants(parsed: dict[str, Any]) -> list[dict[str, Any]]:
    """账本对账用的逐条载荷：{"remain", "expires", "granted_at"}。"""
    grants: list[dict[str, Any]] = []
    for pack in parsed.get("packs") or []:
        if not isinstance(pack, dict):
            continue
        row = pack_row(pack)
        remain = row.get("remaining")
        if not isinstance(remain, int) or remain <= 0:
            continue
        grants.append({
            "remain": remain,
            "expires": (row.get("expire") or "")[:10] or None,
            "granted_at": None,
            "package": row.get("desc") or "",
        })
    if grants:
        return grants
    # 聚合口径：客户端展示的到期日即整笔的到期日（免费单桶账号成立）
    total = parsed.get("total")
    if isinstance(total, bool) or not isinstance(total, (int, float)) or total <= 0:
        return []
    return [{
        "remain": int(round(total)),
        "expires": (parsed.get("expire_at") or "")[:10] or None,
        "granted_at": None,
        "package": "聚合额度（到期日取客户端展示的最高优包到期日）",
    }]


def payload(parsed: dict[str, Any]) -> dict[str, Any]:
    """标准对账载荷：与 wb_credits --ledger 同契约（grants + total）。

    ensure_ascii 的选择在打印处做（这里只出结构），载荷用 ASCII 转义，
    免得 cmd.exe 的 GBK 控制台把中文 JSON 拆坏。
    """
    grants = build_grants(parsed)
    total = parsed.get("total")
    if isinstance(total, bool) or not isinstance(total, (int, float)):
        total = sum(g["remain"] for g in grants)
    return {
        "account": ACCOUNT,
        "total": int(round(total)),
        "grants": grants,
        "granularity": "per_pack" if parsed.get("packs") else "aggregate",
        "queried_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }


def _fmt_num(value: Any) -> str:
    if value is None:
        return "-"
    if isinstance(value, float) and value == int(value):
        return str(int(value))
    return f"{value:g}" if isinstance(value, (int, float)) else str(value)


def format_text(parsed: dict[str, Any]) -> str:
    """人类可读输出。"""
    p = payload(parsed)
    lines = [f"Trae 积分明细（dump {parsed.get('fetched_at') or '?'}）",
             f"总剩余: {_fmt_num(p['total'])} credits"]
    if parsed.get("expire_at"):
        lines.append(f"到期: {parsed['expire_at']}")
    if p["granularity"] == "per_pack":
        lines.append("口径: 逐包（user_entitlement_pack_list）")
    else:
        lines.append("口径: 聚合（客户端展示的最高优包到期日；逐包需「设置→用量管理」OCR）")
    if parsed.get("day_key"):
        state = "已签" if parsed.get("claimed_today") else "未签"
        lines.append(f"今日签到({parsed['day_key']}): {state} "
                     f"credits={parsed.get('claim_credits')} extra={parsed.get('claim_extra')}")
    lines.append(f"登记条目: {len(p['grants'])} 条")
    for g in p["grants"]:
        lines.append(f"  {g['expires'] or '-':<12} 剩余 {g['remain']:>8}  {g['package']}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="trae_credits",
                                     description="Trae 积分明细查询（只读）")
    parser.add_argument("--json", action="store_true", help="输出账本对账载荷")
    parser.add_argument("--force", action="store_true",
                        help="允许非当天的 dump（只看不登记）")
    args = parser.parse_args(argv)
    try:
        parsed = parse_dump(load_dump())
    except CreditQueryError as exc:
        print(f"查询失败：{exc}", file=sys.stderr)
        return 1
    if not is_fresh(parsed) and not args.force:
        print(f"dump 不是今天的（{parsed.get('day_key') or parsed.get('fetched_at') or '未知'}），"
              "拒绝登记：旧 dump 会把签到后的真实余额覆盖成旧值", file=sys.stderr)
        return 1
    if args.json:
        print(json.dumps(payload(parsed), ensure_ascii=True))
    else:
        print(format_text(parsed))
    return 0


if __name__ == "__main__":
    use_utf8()
    sys.exit(main())
