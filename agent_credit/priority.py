"""烧卡优先级的唯一口径。

`recommend`（这个任务用哪家）和 `board`（积分余额看板）必须用同一套排序规则，
否则会出现「看板说先烧 A、推荐却说先烧 B」，主人按哪个都不对。

规则来自技能的硬规则 4：
    当日清零 > 7 天内到期 > 长期 FIFO > 有上限 > 过期未知（AutoClaw）

层级编号越小越先烧：

    T0 当日清零   —— 登录即领、当天过期，不用就白瞎
    T1 7天内到期  —— 再不用就过期，最该先烧
    T2 长期 FIFO  —— 有效期还长，但按发放时间排队用
    T3 有上限待补  —— 有额度上限且快满了，先把上限用掉
    T4 过期未知   —— 有效期未知（AutoClaw），当作最后动

注意 T2/T4 的顺序：AutoClaw 的有效期分类且服务端不下发逐条到期日、台账未知，
它排在有明确到期日的长期积分之后——「不确定的先别动」。
"""
from __future__ import annotations

from datetime import date
from typing import Any

from . import ledger

EXPIRY_WINDOW_DAYS = 7

TIER_LABELS: dict[int, str] = {
    0: "T0 当日清零",
    1: f"T1 {EXPIRY_WINDOW_DAYS}天内到期",
    2: "T2 长期 FIFO",
    3: "T3 有上限待补",
    4: "T4 过期未知",
}

TIER_RULES: list[str] = [
    "T0 当日清零：登录即领、当天过期（用时再开的那几家）",
    f"T1 {EXPIRY_WINDOW_DAYS}天内到期：再不用就过期，最该先烧",
    "T2 长期 FIFO：有效期还长，按发放时间排队用",
    "T3 有上限待补：有额度上限且快满了，先把上限用掉",
    "T4 过期未知：有效期未知（AutoClaw），当作最后动",
]


def days_left(expires_at: str | None, on: date | None = None) -> int | None:
    """距过期还有几天。日期缺失/非法一律 None（不当成 0 天，那会误判成最紧急）。"""
    on = on or ledger.today()
    if not expires_at:
        return None
    try:
        exp = ledger.parse_date(str(expires_at)[:10])
    except ValueError:
        return None
    if exp is None:
        return None
    return (exp - on).days


def tier(acc: dict[str, Any], data: dict[str, Any], on: date | None = None) -> int:
    """账户的烧卡层级（0 最先烧）。"""
    on = on or ledger.today()
    expiry = ledger.soonest_expiry(data, acc["id"], on)
    left = (expiry - on).days if expiry else None
    if acc.get("grant_type") == "daily_expire":
        return 0
    if left is not None and left <= EXPIRY_WINDOW_DAYS:
        return 1
    cap = acc.get("cap")
    if isinstance(cap, int) and cap > 0:
        return 3
    if acc.get("validity_days") is None and acc.get("grant_type") == "accumulating":
        return 4
    return 2


def tier_label(level: int) -> str:
    return TIER_LABELS.get(level, f"T{level}")


def account_sort_key(acc: dict[str, Any], data: dict[str, Any],
                     on: date | None = None) -> tuple:
    """账户级排序键：层级优先，层内按到期日 → 余额 → 每日额度 → id。

    历史上这个键写在 recommend._burn_tuple 里，看板需要同一份，
    于是搬到这里由两边共用（口径分家是这类项目最常见的内耗来源）。
    """
    on = on or ledger.today()
    level = tier(acc, data, on)
    remaining = ledger.remaining(data, acc["id"], on)
    expiry = ledger.soonest_expiry(data, acc["id"], on)
    left = (expiry - on).days if expiry else None
    cap = acc.get("cap")
    daily = -(acc.get("daily_amount") or 0)
    if level == 0:
        return (0, daily, acc["id"])
    if level == 1:
        return (1, left, daily, acc["id"])
    if level == 3:
        return (3, remaining, daily, acc["id"])
    if level == 4:
        return (4, daily, acc["id"])
    return (2, left if left is not None else 999, daily, acc["id"])
