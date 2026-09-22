from __future__ import annotations

import re
from datetime import date
from typing import Any

from . import ledger
from .catalog import accounts, threshold_ratio

CAP_KEYWORDS: dict[str, tuple[str, ...]] = {
    "coding": ("代码", "重构", "仓库", "编程", "开发", "debug", "bug", "code", "ide", "编译"),
    "docs": ("文档", "写作", "办公", "表格", "excel", "ppt", "幻灯", "演示", "周报"),
    "office": ("办公", "邮件", "总结", "纪要"),
    "search": ("搜索", "研究", "调研", "检索"),
    "multimodal": ("图片", "视频", "多模态", "海报", "绘画", "生成图"),
    "local": ("本地", "隐私", "不上传", "离线"),
    "remote": ("远控", "远程", "控电脑"),
    "ecommerce": ("跨境", "电商", "店铺", "sku"),
}

LIGHT_RE = re.compile(r"日常|聊天|问问|小改|一句话|随手|轻活")


def detect_caps(task: str) -> list[str]:
    text = task.lower()
    hit = [cap for cap, words in CAP_KEYWORDS.items() if any(w.lower() in text for w in words)]
    if "ppt" in text or "幻灯" in task or "演示" in task:
        if "docs" not in hit:
            hit.append("docs")
        if "office" not in hit:
            hit.append("office")
    return hit or ["coding", "office"]


def _burn_tuple(acc: dict[str, Any], data: dict[str, Any], on: date) -> tuple:
    remaining = ledger.remaining(data, acc["id"], on)
    expiry = ledger.soonest_expiry(data, acc["id"], on)
    days_left = (expiry - on).days if expiry else None
    cap = acc.get("cap")
    daily = -(acc.get("daily_amount") or 0)
    if acc.get("grant_type") == "daily_expire":
        return (0, daily, acc["id"])
    if days_left is not None and days_left <= 7:
        return (1, days_left, daily, acc["id"])
    if isinstance(cap, int) and cap > 0:
        return (3, remaining, daily, acc["id"])
    if acc.get("validity_days") is None and acc.get("grant_type") == "accumulating":
        return (4, daily, acc["id"])
    return (2, days_left if days_left is not None else 999, daily, acc["id"])


def recommend(task: str, data: dict[str, Any] | None = None, on: date | None = None) -> dict[str, Any]:
    on = on or ledger.today()
    data = data or ledger.load()
    caps = detect_caps(task)
    light = bool(LIGHT_RE.search(task))
    pool = []
    suggest_open = []
    for acc in accounts():
        acc_caps = set(acc.get("capabilities") or [])
        if acc_caps.isdisjoint(set(caps)):
            continue
        remaining = ledger.remaining(data, acc["id"], on)
        item = {
            "id": acc["id"],
            "name": acc["name"],
            "unit": acc.get("unit"),
            "grant_type": acc.get("grant_type"),
            "remaining": remaining,
            "daily_amount": acc.get("daily_amount") or 0,
            "open_when_needed": bool(acc.get("open_when_needed")),
            "claim_policy": acc.get("claim_policy"),
            "capabilities": list(acc_caps),
            "notes": acc.get("notes") or acc.get("models_note") or "",
        }
        if acc.get("open_when_needed") and acc.get("grant_type") == "daily_expire":
            suggest_open.append(item)
            continue
        usable = remaining > 0
        always_stack = acc.get("claim_policy") == "always"
        if always_stack or usable:
            pool.append(item)

    pool.sort(key=lambda it: _burn_tuple(account_lookup(it["id"]), data, on))
    if light:
        pool = [it for it in pool if it["grant_type"] != "accumulating"] + [
            it for it in pool if it["grant_type"] == "accumulating"
        ]

    suggest_open.sort(key=lambda it: -(it["daily_amount"] or 0))
    primary = pool[0] if pool else (suggest_open[0] if suggest_open else None)
    avoid = [
        it
        for it in pool
        if it["grant_type"] == "accumulating" and light
    ]
    below = []
    ratio = threshold_ratio()
    for acc in accounts():
        if acc.get("claim_policy") != "below_threshold":
            continue
        cap = acc.get("cap") or 0
        rem = ledger.remaining(data, acc["id"], on)
        if isinstance(cap, int) and cap > 0 and rem < cap * ratio:
            below.append({"id": acc["id"], "name": acc["name"], "remaining": rem, "cap": cap})

    return {
        "task": task,
        "capabilities": caps,
        "light": light,
        "primary": primary,
        "pool": pool,
        "suggest_open": suggest_open,
        "avoid_for_light": avoid,
        "claim_if_low": below,
    }


def account_lookup(account_id: str) -> dict[str, Any]:
    for acc in accounts():
        if acc["id"] == account_id:
            return acc
    raise KeyError(account_id)


def format_recommend(result: dict[str, Any]) -> str:
    lines = [
        f"任务：{result['task']}",
        f"能力标签：{', '.join(result['capabilities'])}" + ("（轻活）" if result["light"] else ""),
        "",
    ]
    if result["suggest_open"]:
        lines.append("用时再开（当日清零，不自动启动）：")
        for it in result["suggest_open"][:6]:
            amt = it["daily_amount"]
            unit = "Token" if it["unit"] == "token" else "积分"
            lines.append(f"  - {it['name']}  每日 {amt} {unit}")
        lines.append("")
    if result["primary"]:
        p = result["primary"]
        lines.append(f"台账内优先：{p['name']}  余额 {p['remaining']} {p['unit']}")
    if result["pool"]:
        lines.append("可攒/在账软件顺序（快过期先烧）：")
        for i, it in enumerate(result["pool"][:8], 1):
            lines.append(f"  {i}. {it['name']}  余额 {it['remaining']} {it['unit']}  [{it['grant_type']}]")
    if result["light"] and result["avoid_for_light"]:
        names = "、".join(it["name"] for it in result["avoid_for_light"][:5])
        lines.append(f"轻活尽量别动囤积分：{names}")
    if result["claim_if_low"]:
        lines.append("有上限且余额偏低，可以领：")
        for it in result["claim_if_low"]:
            lines.append(f"  - {it['name']}  {it['remaining']}/{it['cap']}")
    lines.append("规则：当日清零先烧（需你先打开）> 7 天内到期 > 长期 FIFO > 有上限 > 无过期（AutoClaw）。")
    return "\n".join(lines)
