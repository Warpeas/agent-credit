"""从 catalog.yaml 生成「评级总表 + 各家简评」，写入 README.md 的标记区间。

用法：
    python scripts/gen_rating_table.py            # 打印结果
    python scripts/gen_rating_table.py --write    # 写入 README.md

评分口径：综合分 = 0.4*value + 0.3*capability + 0.3*automation（各项 1-5）
档位：>=4.5 S | >=3.5 A | >=2.5 B | >=1.5 C | 其余 D

改评级请改 catalog.yaml 里的 rating 块（owner_note 填真实使用体验），
然后重跑本脚本刷新 README，不要手改 README 里的表格。
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from agent_credit.catalog import accounts  # noqa: E402

README = ROOT / "README.md"
BEGIN = "<!-- BEGIN RATING -->"
END = "<!-- END RATING -->"

GRANT_LABEL = {
    "accumulating": "每日签到·可累积",
    "daily_expire": "登录即领·当日清零",
    "monthly": "月度",
    "one_shot": "一次性",
}
MODE_LABEL = {
    "external": "external 直签",
    "ui": "UI/OCR 提权",
    "manual": "手签",
    "never": "不自动",
}


def tier(score: float) -> str:
    if score >= 4.5:
        return "S"
    if score >= 3.5:
        return "A"
    if score >= 2.5:
        return "B"
    if score >= 1.5:
        return "C"
    return "D"


def amount_text(acc: dict) -> str:
    unit = acc.get("unit") or ""
    daily = acc.get("daily_amount") or 0
    if acc.get("grant_type") == "daily_expire":
        if unit == "token":
            return f"{daily/1_000_000:.0f}M token/天"
        return f"{daily}/天"
    if acc.get("grant_type") == "monthly":
        return f"{acc.get('monthly_amount')}/月" if acc.get("monthly_amount") else "周期制"
    if acc.get("grant_type") == "one_shot":
        return "一次性"
    return f"{daily}/天" if daily else "-"


def grant_text(acc: dict) -> str:
    gt = acc.get("grant_type")
    if gt == "daily_expire" and acc.get("validity_days") is None:
        return "网页登录·有效期待确认"
    return GRANT_LABEL.get(gt, str(gt))


def mode_text(acc: dict) -> str:
    # checkin.py 的实际判定：有 command 就走 external，否则按 claim_mode
    if acc.get("claim_mode") == "never":
        return "不自动"
    if acc.get("command"):
        return "external 直签"
    return MODE_LABEL.get(acc.get("claim_mode"), str(acc.get("claim_mode")))


def validity_text(acc: dict) -> str:
    gt = acc.get("grant_type")
    if gt == "daily_expire":
        # 规则有更新但天数未确认时，validity_days 置 null，显示待确认而不是硬说当日清零
        if acc.get("validity_days") is None:
            return "待确认"
        return "当日清零"
    if acc.get("expires_on"):
        return f"至 {acc['expires_on']}"
    if gt == "one_shot":
        return f"{acc.get('validity_days')} 天" if acc.get("validity_days") else "未定"
    days = acc.get("validity_days")
    if days is None:
        return "服务端下发"
    return f"{days} 天"


def streak_text(acc: dict) -> str:
    st = acc.get("streak")
    if not st:
        return "无"
    days = "/".join(str(d) for d in (st.get("bonus_on") or []))
    return f"{st.get('cycle_days')} 天周期，第 {days} 天 +{st.get('bonus_amount')}"


def rows() -> list[dict]:
    out = []
    for acc in accounts():
        r = acc.get("rating") or {}
        v = int(r.get("value") or 0)
        c = int(r.get("capability") or 0)
        a = int(r.get("automation") or 0)
        score = round(0.4 * v + 0.3 * c + 0.3 * a, 2)
        out.append(
            {
                "id": acc["id"],
                "name": acc.get("name") or acc["id"],
                "vendor": acc.get("vendor") or "-",
                "tier": tier(score),
                "score": score,
                "v": v,
                "c": c,
                "a": a,
                "amount": amount_text(acc),
                "validity": validity_text(acc),
                "streak": streak_text(acc),
                "grant": grant_text(acc),
                "mode": mode_text(acc),
                "review": (r.get("review") or "").strip(),
                "best_for": (r.get("best_for") or "").strip(),
                "owner_note": (r.get("owner_note") or "").strip(),
                "models": acc.get("models_note") or "-",
                "mobile": acc.get("mobile"),
                "mobile_note": (acc.get("mobile_note") or "").strip(),
            }
        )
    out.sort(key=lambda x: (-x["score"], x["name"]))
    return out


def build_markdown() -> str:
    data = rows()
    L: list[str] = []
    L.append("## 评级总表")
    L.append("")
    L.append(
        "> 由 `scripts/gen_rating_table.py` 从 `catalog.yaml` 生成。"
        "改评级请改 `catalog.yaml` 的 `rating` 块（`owner_note` 填真实使用体验），再跑 `python scripts/gen_rating_table.py --write` 刷新本表。"
    )
    L.append("")
    L.append("| 档 | Agent | 厂商 | 免费额度 | 有效期 | 连签/额外 | 发放方式 | 领取路线 | 评分 V/C/A | 综合 |")
    L.append("|---|---|---|---|---|---|---|---|---|---|")
    for r in data:
        L.append(
            f"| **{r['tier']}** | {r['name']} | {r['vendor']} | {r['amount']} | {r['validity']} "
            f"| {r['streak']} | {r['grant']} | {r['mode']} | {r['v']}/{r['c']}/{r['a']} | {r['score']} |"
        )
    L.append("")
    L.append("评分口径：**综合 = 0.4×额度价值 + 0.3×能力覆盖 + 0.3×领取可靠性**（各 1-5）。")
    L.append("档位：≥4.5 S｜≥3.5 A｜≥2.5 B｜≥1.5 C｜其余 D。")
    L.append("")
    L.append("## 各家简评")
    L.append("")
    L.append("> 以下为**基于台账事实的分析初稿**，主人可按实际体验在 `catalog.yaml` 的 `owner_note` 里覆写。")
    L.append("")
    for r in data:
        L.append(f"### {r['tier']} · {r['name']}（{r['vendor']}）— {r['score']} 分")
        L.append("")
        L.append(f"- 额度：{r['amount']}，{r['validity']}，连签/额外：{r['streak']}")
        L.append(f"- 模型：{r['models']}")
        if r["mobile"] is False:
            suffix = f"（{r['mobile_note']}）" if r["mobile_note"] else ""
            L.append(f"- 移动端：无手机客户端，离开电脑用不了{suffix}")
        elif r["mobile"] is True:
            suffix = f"—— {r['mobile_note']}" if r["mobile_note"] else ""
            L.append(f"- 移动端：有{suffix}")
        L.append(f"- 简评：{r['review']}")
        L.append(f"- 适合：{r['best_for']}")
        L.append(f"- 主人体验：{r['owner_note'] if r['owner_note'] else '_待补充_'}")
        L.append("")
    return "\n".join(L).rstrip() + "\n"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--write", action="store_true", help="写入 README.md 的标记区间")
    args = ap.parse_args()
    md = build_markdown()
    if not args.write:
        print(md)
        return 0
    text = README.read_text(encoding="utf-8")
    if BEGIN not in text or END not in text:
        print(f"README.md 缺少标记 {BEGIN} / {END}", file=sys.stderr)
        return 1
    head, rest = text.split(BEGIN, 1)
    _, tail = rest.split(END, 1)
    README.write_text(head + BEGIN + "\n\n" + md + "\n" + END + tail, encoding="utf-8")
    print(f"已刷新 {README}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
