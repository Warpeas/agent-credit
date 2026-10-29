"""Qoder CN 积分查询（只读，2026-10-20 打通）。

查什么：登录用户的**服务端真值余额**，按桶给——套餐内 Credits（userQuota）、
资源包 Add-on Credits（addOnQuota）、共享资源包（orgResourcePackage）、
个人专属资源包（dedicatedResourcePackage），每桶 total/used/remaining，
外加 plan 的 expiresAt。

数据源 = 客户端自己写的明文日志：

    %APPDATA%\\com.qodercn.app.stable\\logs\\<session>\\main.log
        [Auth] [AccountUsage] 用量响应摘要 {"qoderUsage":{...}}

那就是 `GET https://openapi.qoder.com.cn/sash/api/v2/me/usage` 的响应摘要。
读客户端自己的输出属 research/SAFETY.md 路线 2「让客户端自己说话」：
不解密、不联网、不碰凭据、不抓包。

为什么不走 external 直连（别再试一遍）：token 在
`%APPDATA%\\com.qodercn.app.stable\\auth.v1.dat`，头三字节 `v10` =
Chromium safeStorage（DPAPI）密文。SAFETY 第 1 节把「解密加密存储的登录态」
列为绝对禁止（与 Trae 的 iCubeAuthInfo、AutoClaw 的 enc: 同类）→ 排除。

拿不到什么：**逐条 grant 和每条积分的过期时间**。me/usage 的响应只有上面四个桶，
没有任何批次数组；本账号实测 expiresAt=253402214400000（年 9999 哨兵=无到期）。
所以看板把 Qoder 标成「服务端真值余额 + 过期未知」，与 MonkeyCode 同档，
不拿本地 30 天估算冒充服务端有效期。

新鲜度闸门：**只有当天的记录才允许登记**（与 Trae 同款）。用量请求只在
「我的用量」面板打开时发出（13 个历史会话仅 2 个有记录），当天没记录就说明
面板没开过——旧值登记会把签到后的真实余额覆盖成旧值，所以直接拒绝。

用法：
    python -m agent_credit.qodercn_credits              # 人类可读明细
    python -m agent_credit.qodercn_credits --json       # 全量 JSON（含出处）
    python -m agent_credit.qodercn_credits --line       # 一行 JSON（status_command）
    python -m agent_credit.qodercn_credits --ledger     # 对账载荷（credits_command）
    python -m agent_credit.qodercn_credits --allow-stale # 旧记录也允许打印（仅查看）
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import date, datetime
from pathlib import Path
from typing import Any

ACCOUNT = "qodercn"
APP_DATA_DIRNAME = "com.qodercn.app.stable"
USAGE_MARK = "[AccountUsage] 用量响应摘要"
CAMPAIGN_MARK = "[Campaign]"
LOG_LIMIT_MB = 8  # 单文件超读上限：只为防极端大的 main.log 拖死对账

# 桶 → 客户端展示名（i18n 实测：planCredits/resourcePackage/
# sharedResourcePackage/dedicatedResourcePackage）
BUCKET_LABELS = {
    "userQuota": "套餐内 Credits",
    "addOnQuota": "资源包（Add-on Credits）",
    "orgResourcePackage": "共享资源包",
    "dedicatedResourcePackage": "个人专属资源包",
}
# 年 9999 一类哨兵：客户端拿去「永不过期」展示，登记成日期只会污染临期队列
SENTINEL_YEAR = 9000


class CreditQueryError(Exception):
    """查询失败（没日志 / 没记录 / 解析不了）。消息固定，不含凭据。"""


def _log_roots() -> list[Path]:
    """候选 userData 根。APPDATA 可能指向沙箱，所以要像 apps.py 一样兜底枚举。"""
    candidates: list[Path] = []
    appdata = os.environ.get("APPDATA")
    if appdata:
        candidates.append(Path(appdata))
    for var in ("USERPROFILE", "HOME"):
        base = os.environ.get(var)
        if base:
            candidates.append(Path(base) / "AppData" / "Roaming")
    users = Path(os.environ.get("SystemDrive", "C:") + "\\") / "Users"
    if users.is_dir():
        candidates.extend(sorted(users.glob("*/AppData/Roaming")))
    seen: set[Path] = set()
    out: list[Path] = []
    for cand in candidates:
        root = cand / APP_DATA_DIRNAME
        if root.is_dir() and root not in seen:
            seen.add(root)
            out.append(root)
    return out


def usage_log_files() -> list[Path]:
    """所有 main.log，按修改时间从新到旧。"""
    files: list[Path] = []
    for root in _log_roots():
        files.extend((root / "logs").glob("*/main.log"))
    return sorted((f for f in files if f.is_file()),
                  key=lambda f: f.stat().st_mtime, reverse=True)


def _read_tail(path: Path) -> list[str]:
    try:
        if path.stat().st_size > LOG_LIMIT_MB * 1024 * 1024:
            with path.open("rb") as fh:
                fh.seek(-LOG_LIMIT_MB * 1024 * 1024, os.SEEK_END)
                fh.readline()  # 丢掉半行
                raw = fh.read()
        else:
            raw = path.read_bytes()
    except OSError as exc:
        raise CreditQueryError(f"读日志失败：{exc}") from None
    return raw.decode("utf-8", errors="replace").splitlines()


def _json_at(text: str, start: int) -> dict[str, Any] | None:
    """从 start 处的前导 { 起解一个 JSON 对象（行尾还有别的东西也不影响）。"""
    idx = text.find("{", start)
    if idx < 0:
        return None
    try:
        obj, _ = json.JSONDecoder().raw_decode(text[idx:])
    except ValueError:
        return None
    return obj if isinstance(obj, dict) else None


def _line_ts(line: str) -> datetime | None:
    """`[2026-10-16T00:45:37.959Z]` -> 本地 datetime。解不出就 None，不猜。"""
    m = re.match(r"\[(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}[^]]*)\]", line)
    if not m:
        return None
    try:
        return datetime.fromisoformat(m.group(1).replace("Z", "+00:00")).astimezone()
    except ValueError:
        return None


def normalize_bucket(key: str, raw: Any) -> dict[str, Any] | None:
    """把一桶归一成 {key,name,total,used,remaining}。非对象（"missing"）返回 None。"""
    if not isinstance(raw, dict):
        return None

    def num(value: Any) -> int | None:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return None
        return int(round(value))

    return {
        "key": key,
        "name": BUCKET_LABELS.get(key, key),
        "total": num(raw.get("total")),
        "used": num(raw.get("used")),
        "remaining": num(raw.get("remaining")),
        "percentage": num(raw.get("percentage")),
        "unit": str(raw.get("unit") or ""),
    }


def epoch_ms_to_date(value: Any) -> str | None:
    """epoch 毫秒 -> 'YYYY-MM-DD'。哨兵年（>=9000）与非法值一律 None。"""
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value <= 0:
        return None
    try:
        dt = datetime.fromtimestamp(value / 1000)
    except (OSError, OverflowError, ValueError):
        return None
    if dt.year >= SENTINEL_YEAR:
        return None
    return dt.date().isoformat()


def normalize_usage(usage: dict[str, Any], when: datetime | None,
                    origin: str) -> dict[str, Any]:
    buckets: list[dict[str, Any]] = []
    for key in BUCKET_LABELS:
        bucket = normalize_bucket(key, usage.get(key))
        if bucket:
            buckets.append(bucket)
    expires = epoch_ms_to_date(usage.get("expiresAt"))
    return {
        "recorded_at": when.strftime("%Y-%m-%d %H:%M:%S") if when else None,
        "recorded_date": when.date().isoformat() if when else None,
        "origin": origin,
        "user_type": str(usage.get("userType") or ""),
        "usage_type": str(usage.get("usageType") or ""),
        "plan_expires": expires,
        "total_usage_percentage": usage.get("totalUsagePercentage"),
        "is_quota_exceeded": bool(usage.get("isQuotaExceeded")),
        "buckets": buckets,
        "raw_extra": {k: v for k, v in usage.items()
                      if k in ("orgResourcePackage", "dedicatedResourcePackageCount")},
    }


def find_usage_record() -> dict[str, Any]:
    """取最新一条用量记录（新会话优先，会话内从行尾往前找）。"""
    files = usage_log_files()
    if not files:
        raise CreditQueryError(
            f"找不到 Qoder CN 的日志（%APPDATA%\\{APP_DATA_DIRNAME}\\logs\\*/main.log）")
    scanned = 0
    for path in files:
        scanned += 1
        for line in reversed(_read_tail(path)):
            pos = line.find(USAGE_MARK)
            if pos < 0:
                continue
            payload = _json_at(line, pos + len(USAGE_MARK))
            usage = payload.get("qoderUsage") if payload else None
            if not isinstance(usage, dict):
                continue
            record = normalize_usage(usage, _line_ts(line), path.parent.name)
            record["scanned_files"] = scanned
            return record
    raise CreditQueryError(
        f"翻过 {scanned} 个会话的 main.log，没有一条「用量响应摘要」——"
        "用量请求只在打开「我的用量」面板时发出：点开一次再来")


def find_campaign_state() -> dict[str, Any] | None:
    """服务端签到态（[Campaign] claimable）。没有则 None，不影响主流程。

    「活动状态响应解析完成」是本次真的问了服务端；「活动状态使用缓存」是本地缓存，
    可能滞后一个缓存 TTL（实测 expiresInMs 约 3~5 分钟）。两者都记 source，
    让调用方自己决定信多少。
    """
    for path in usage_log_files()[:3]:
        try:
            lines = _read_tail(path)
        except CreditQueryError:
            continue
        fresh = None
        cached = None
        for line in reversed(lines):
            pos = line.find(CAMPAIGN_MARK)
            if pos < 0:
                continue
            tail = line[pos:]
            if "claimable" not in tail:
                continue
            payload = _json_at(tail, len(CAMPAIGN_MARK))
            if not isinstance(payload, dict) or "claimable" not in payload:
                continue
            item = {
                "claimable": bool(payload.get("claimable")),
                "show_campaign": bool(payload.get("showCampaign")),
                "source": "server" if "响应解析完成" in tail else "cache",
                "recorded_at": (_line_ts(line) or datetime.now().astimezone())
                               .strftime("%Y-%m-%d %H:%M:%S"),
            }
            if item["source"] == "server" and fresh is None:
                fresh = item
            if cached is None:
                cached = item
        if fresh or cached:
            return fresh or cached
    return None


def claimed_today(campaign: dict[str, Any] | None) -> bool | None:
    """把签到态翻译成「今天是否已领」。

    showCampaign=false 说明服务端根本没下发活动 → 未知（不是「已领」）。
    claimable=false 且活动可见 → 今天领过了（或不符合条件，两者不可分辨）。
    """
    if not campaign or not campaign.get("show_campaign"):
        return None
    return not campaign.get("claimable")


def total_remaining(record: dict[str, Any]) -> int:
    return sum(b["remaining"] or 0 for b in record["buckets"])


def ledger_payload(record: dict[str, Any]) -> dict[str, Any]:
    """`--ledger`：服务端只给桶总数，所以走 **reconcile** 契约而不是 grants。

    为什么不用 grants（sync_grants）也不用 balance（快照）：两种都会把台账里
    「逐日领取的 N 条 ×100、各带 30 天有效期」的结构替换掉——grants 会写成
    一条没有过期时间的聚合条目，快照同样。那样一来临期队列与烧卡优先级对 Qoder
    就完全失明（2026-10-20 实踩过一次）。reconcile 的语义是「拿服务端总数
    校正台账总量」：多了就按先到期先烧扣掉，少了补一条，每条自己的过期时间留着。
    """
    return {
        "account": ACCOUNT,
        "total": total_remaining(record),
        "reconcile": "fifo",
        "granularity": "bucket",
        "plan_expires": record.get("plan_expires"),
        "recorded_at": record.get("recorded_at"),
        "buckets": [{"name": b["name"], "remaining": b["remaining"],
                     "total": b["total"], "used": b["used"]} for b in record["buckets"]],
    }


def is_fresh(record: dict[str, Any], on: date | None = None) -> bool:
    """当天的记录才算新鲜。旧记录登记会把签到后的余额覆盖成旧值。"""
    on = on or date.today()
    raw = record.get("recorded_date")
    if not raw:
        return False
    try:
        return date.fromisoformat(raw) == on
    except ValueError:
        return False


def format_text(record: dict[str, Any], campaign: dict[str, Any] | None) -> str:
    total = total_remaining(record)
    lines = [f"Qoder CN 积分（记录于 {record.get('recorded_at') or '未知时间'}，"
             f"来源会话 {record.get('origin') or '-'}）",
             f"总剩余: {total} credits（桶合计）",
             f"套餐类型: {record.get('user_type') or '-'}，"
             f"计量: {record.get('usage_type') or '-'}，"
             f"已超额: {'是' if record['is_quota_exceeded'] else '否'}"]
    if record.get("plan_expires"):
        lines.append(f"套餐到期: {record['plan_expires']}")
    lines.append("分桶:")
    for bucket in record["buckets"]:
        lines.append(f"  {bucket['name']:<18} 剩余 {_fmt(bucket['remaining']):>7} / "
                     f"总量 {_fmt(bucket['total']):>7}（已用 {_fmt(bucket['used'])}）")
    for key, value in (record.get("raw_extra") or {}).items():
        lines.append(f"  {BUCKET_LABELS.get(key, key):<18} 服务端值 {value!r}（非逐条明细）")
    state = claimed_today(campaign)
    if campaign:
        tail = ("缓存态，可能有几分钟滞后" if campaign["source"] == "cache" else "服务端态")
        lines.append(f"今日签到: {'已领' if state else '还能领' if state is not None else '未知'}"
                     f"（{tail}：claimable={str(campaign['claimable']).lower()}，"
                     f"showCampaign={str(campaign['show_campaign']).lower()}）")
    else:
        lines.append("今日签到: 未知（日志里没有 [Campaign] 活动状态行）")
    lines.append("逐条积分的剩余/过期: 拿不到——me/usage 只下发上面这些桶。")
    return "\n".join(lines)


def _fmt(value: Any) -> str:
    return "-" if value is None else str(value)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="qodercn_credits",
                                     description="Qoder CN 积分查询（只读）")
    parser.add_argument("--json", action="store_true", help="输出全量 JSON")
    parser.add_argument("--line", action="store_true",
                        help='一行 JSON：{"balance": N, "claimed_today": bool|null}')
    parser.add_argument("--ledger", action="store_true", help="账本对账载荷（sync 消费）")
    parser.add_argument("--allow-stale", action="store_true",
                        help="允许非当天的记录参与登记/输出（默认拒绝，防旧值覆盖）")
    args = parser.parse_args(argv)

    try:
        record = find_usage_record()
    except CreditQueryError as exc:
        print(f"查询失败：{exc}", file=sys.stderr)
        return 1
    campaign = find_campaign_state()

    if (args.ledger or args.line) and not args.allow_stale and not is_fresh(record):
        print(f"记录不是今天的（{record.get('recorded_date') or '未知'}，"
              f"来自 {record.get('origin') or '-'}），拒绝登记：旧值会把签到后的"
              "真实余额覆盖成旧值。要刷新请在 Qoder 打开一次「我的用量」面板",
              file=sys.stderr)
        return 1

    if args.line:
        print(json.dumps({"balance": total_remaining(record),
                          "claimed_today": claimed_today(campaign)}, ensure_ascii=False))
    elif args.ledger:
        print(json.dumps(ledger_payload(record), ensure_ascii=True))
    elif args.json:
        print(json.dumps({"usage": record, "campaign": campaign},
                         ensure_ascii=False, indent=1, default=str))
    else:
        print(format_text(record, campaign))
    return 0


if __name__ == "__main__":
    from .console import use_utf8

    use_utf8()
    raise SystemExit(main())
