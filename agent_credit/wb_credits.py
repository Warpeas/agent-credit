"""WorkBuddy 积分明细查询（只读，2026-10-19 打通）。

查什么：登录用户的剩余积分详情——总量、四大分组（套餐基础/套餐赠送/
购买/平台奖励）、以及**每条积分 grant 的剩余量与过期时间**。

端点（均来自桌面端 app.asar 只读字符串提取，形状对齐客户端自身调用）：
  POST {endpoint}/billing/meter/get-user-resource-summary       总量/分组/逐包周期容量
  POST {endpoint}/billing/meter/get-user-resource-free-packages 免费与活动积分逐条（含过期）
  POST {endpoint}/billing/meter/get-user-resource-paid-packages 购买积分逐条（含过期）
  POST {endpoint}/v2/billing/meter/checkin-activity-status      今日是否已签（--line 用）

两个容易踩的坑（都已实测）：
  1. 资源类端点**不带 /v2 前缀**（签到端点带）。依据：asar 的
     fetchAccountUsage -> getPersonalUsage(endpoint) -> fetchResourceSummary(prefix)，
     prefix 就是 productManager.getEndpoint() 本身。带 /v2 会 404 Route Not Found。
  2. free/paid 端点的 PackageCodes 不能为空数组（HTTP 400 "PackageCodes required"），
     必须按客户端的分组下发（Ys = 付费组；其余 = 免费组）。

凭据：复用 vendor/workbuddy-auto-signin/signin.py 的既有机制——凭据文件里的
明文 token，或由 WorkBuddy 客户端进程自行解密 sym-v1 信封。本模块不实现解密、
不落盘、不打印任何令牌。

用法：
    python -m agent_credit.wb_credits              # 人类可读明细
    python -m agent_credit.wb_credits --all        # 含已用完/已过期条目
    python -m agent_credit.wb_credits --json       # 全量 JSON
    python -m agent_credit.wb_credits --line       # 一行 JSON（status_command 约定）
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
VENDOR_SIGNIN = REPO_ROOT / "vendor" / "workbuddy-auto-signin" / "signin.py"

# 资源类端点无 /v2；签到状态端点有 /v2。见模块 docstring 的坑 1。
SUMMARY_PATH = "/billing/meter/get-user-resource-summary"
FREE_PATH = "/billing/meter/get-user-resource-free-packages"
PAID_PATH = "/billing/meter/get-user-resource-paid-packages"
STATUS_PATH = "/v2/billing/meter/checkin-activity-status"

# asar 枚举 $（TCACA_code_*）与桌面端 queryCreditPackages 的 paid/free 分流：
#   Ys（paid 组，queryBillingResources 实测用于 paid 端点）
PAID_PACKAGE_CODES = [
    "TCACA_code_002_AkiJS3ZHF5", "TCACA_code_005_maRGyrHhw1", "TCACA_code_003_FAnt7lcmRT",
    "TCACA_code_023_4xbGhMrE6q", "TCACA_code_026_BaESVICNoi", "TCACA_code_027_0FCGVA6vSa",
    "TCACA_code_008_cfWoLwvjU4", "TCACA_code_006_DbXS0lrypC", "TCACA_code_035_ArVxJcGDsm",
    "TCACA_code_039_KRcQj7wUat", "TCACA_code_040_mi9rCYg46x",
]
#   免费组 = 枚举其余项。code_008（个人体验版月度配额）经实测放在免费组下发
#   才能取到它的资源记录（CapacityType=4 的 slice 记录）。
FREE_PACKAGE_CODES = [
    "TCACA_code_001_PqouKr6QWV", "TCACA_code_007_nzdH5h4Nl0", "TCACA_code_009_0XmEQc2xOf",
    "TCACA_code_028_NtpWi0jzXs", "TCACA_code_029_6wCGEWquYy", "TCACA_code_030_BjSt89qTvr",
    "TCACA_code_036_lupO5WgNdG", "TCACA_code_037_WxOD3MpI2o", "TCACA_code_038_OhvqZtiPKr",
    "TCACA_code_008_cfWoLwvjU4",
]

# asar 枚举 ds：valid=0 refund=1 expired=2 usedUp=3
STATUS_LABELS = {0: "有效", 1: "已退款", 2: "已过期", 3: "已用完"}
PAGE_SIZE = 200
MAX_PAGES = 10  # 与客户端 fetchAllPages 一致；超出即截断并如实标注

_GROUP_LABELS = {
    "plan_base": "套餐基础积分",
    "plan_bonus": "套餐赠送积分",
    "addon": "购买积分",
    "benefit": "平台奖励积分",
}


class CreditQueryError(Exception):
    """查询失败（未登录 / 网络 / 服务端业务错误）。消息固定，不含凭据。"""


def _load_vendor():
    """加载 vendor 签到模块（复用其凭据与请求机制，不重复实现解密）。"""
    if not VENDOR_SIGNIN.is_file():
        raise CreditQueryError(f"未找到 {VENDOR_SIGNIN}（vendor 子模块缺失？）")
    spec = importlib.util.spec_from_file_location("wb_vendor_signin", VENDOR_SIGNIN)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _session_and_headers() -> tuple[Any, dict[str, str], str]:
    """返回 (vendor 模块, 请求头, endpoint)。失败抛 CreditQueryError。"""
    vendor = _load_vendor()
    auth_file, _looked = vendor.find_auth_file()
    if not auth_file:
        raise CreditQueryError(
            "未找到 WorkBuddy 登录凭据（%LOCALAPPDATA%\\CodeBuddyExtension\\Data\\Public\\auth"
            "\\workbuddy-desktop.info）。请先在客户端登录"
        )
    try:
        session = vendor.resolve_session(vendor.load_session_retry(auth_file))
        headers = vendor.build_headers(session)
    except vendor.AuthError as exc:
        raise CreditQueryError(f"凭据不可用：{exc}") from None
    headers["Accept-Language"] = "zh"
    endpoint = (session.get("auth") or {}).get("endpoint") or vendor.DEFAULT_ENDPOINT
    return vendor, headers, endpoint


def _post(vendor: Any, url: str, headers: dict[str, str], payload: dict[str, Any]) -> dict[str, Any]:
    """POST 并取出 data；网络/5xx 由 vendor 的 retry 兜底（不写循环重试）。"""
    code, body = vendor.post(url, headers, payload, retry=True)
    if code == vendor.CODE_NO_NETWORK:
        raise CreditQueryError(f"网络不通：{body}")
    if not isinstance(body, dict):
        raise CreditQueryError(f"响应不是 JSON：{str(body)[:120]}")
    if code != 200:
        raise CreditQueryError(
            f"HTTP {code} {body.get('error_msg') or body.get('msg') or ''}".strip()
        )
    if body.get("code") not in (0, None):
        raise CreditQueryError(f"服务端返回 code={body.get('code')} msg={body.get('msg')}")
    data = body.get("data")
    if not isinstance(data, dict):
        raise CreditQueryError("响应缺少 data 字段")
    return data


def _num(value: Any) -> float | None:
    """服务端数值常以字符串下发（含空串表示无此字段）。"""
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def fmt_time(value: Any) -> str | None:
    """统一时间格式：epoch 毫秒/秒（int 或数字字符串）或 'YYYY-MM-DD HH:MM:SS' 字符串。"""
    if value is None:
        return None
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        epoch = float(value)
    else:
        text = str(value).strip()
        if not text:
            return None
        if text.isdigit():
            epoch = float(text)
        else:
            return text
    if epoch <= 0:
        return None
    if epoch < 1e11:  # 10 位按秒处理
        epoch *= 1000
    return datetime.fromtimestamp(epoch / 1000).strftime("%Y-%m-%d %H:%M:%S")


def _first_attr(raw: dict[str, Any], key: str) -> str | None:
    for item in raw.get("AccountAttributes") or []:
        if isinstance(item, dict) and item.get("Key") == key:
            text = str(item.get("Value") or "").strip()
            return text or None
    return None


def grant_capacity(raw: dict[str, Any]) -> tuple[float | None, float | None]:
    """取单条 grant 的 (剩余, 总量)。优先级对齐客户端 resolveResourceCapacity：

    1. CapacityType=4（套餐配额/slice）且带 SlicePeriodUsageDetails[0] → 切片字段
    2. CycleCapacity*Precise（周期容量）——套餐配额记录的真余量在这里
       （2026-10-19 实测：code_008 的 CapacityRemainPrecise 是未扣减的包总量 500，
         而 CycleCapacityRemainPrecise=212.99 才与 summary 分组值一致）
    3. 包级 Capacity*Precise（单周期 grant 与 Cycle 值相同，server 分组佐证）
    4. 整数字段兜底
    """
    remain = total = None
    if raw.get("CapacityType") == 4:
        slices = raw.get("SlicePeriodUsageDetails")
        if isinstance(slices, list) and slices and isinstance(slices[0], dict):
            top = slices[0]
            remain = _num(top.get("SlicePeriodCapacityRemainPrecise"))
            total = _num(top.get("SlicePeriodCapacitySizePrecise"))
    if remain is None:
        remain = _num(raw.get("CycleCapacityRemainPrecise"))
    if total is None:
        total = _num(raw.get("CycleCapacitySizePrecise"))
    if remain is None:
        remain = _num(raw.get("CapacityRemainPrecise"))
    if total is None:
        total = _num(raw.get("CapacitySizePrecise"))
    if remain is None:
        remain = _num(raw.get("CycleCapacityRemain"))
        if remain is None:
            remain = _num(raw.get("CapacityRemain"))
    if total is None:
        total = _num(raw.get("CycleCapacitySize"))
        if total is None:
            total = _num(raw.get("CapacitySize"))
    return remain, total


def normalize_grant(raw: dict[str, Any], source: str) -> dict[str, Any]:
    """把服务端的资源记录归一成稳定字段（字段漂移时测试会炸，不会静默失真）。"""
    remain, total = grant_capacity(raw)
    status = raw.get("Status")
    # 过期时间优先级与客户端 toExpiredCreditPackage 一致：
    # DeductionEndTime -> ExpiredTime -> CycleEndTime
    expire_at = None
    for field in ("DeductionEndTime", "ExpiredTime", "CycleEndTime"):
        expire_at = fmt_time(raw.get(field))
        if expire_at:
            break
    return {
        "resource_id": str(raw.get("ResourceId") or ""),
        "package_code": str(raw.get("PackageCode") or ""),
        "package_name": str(raw.get("PackageName") or ""),
        "source": source,
        "status": status,
        "status_label": STATUS_LABELS.get(status, str(status)),
        "remain": remain,
        "total": total,
        "expire_at": expire_at,
        "deduction_end": fmt_time(raw.get("DeductionEndTime")),
        "cycle_start": fmt_time(raw.get("CycleStartTime")),
        "cycle_end": fmt_time(raw.get("CycleEndTime")),
        "created_at": fmt_time(raw.get("CreateTime")),
        "grant_reason": _first_attr(raw, "grantReason"),
        "auto_renew": raw.get("AutoRenewFlag"),
    }


def _page_body(codes: list[str], page: int, extra: dict[str, Any]) -> dict[str, Any]:
    return {
        "PageNumber": page,
        "PageSize": PAGE_SIZE,
        "PackageCodes": codes,
        "Status": [0, 3],
        "IsDisplayTotalInfo": True,
        **extra,
    }


def fetch_packages(vendor: Any, endpoint: str, headers: dict[str, str],
                   path: str, codes: list[str], extra: dict[str, Any]) -> list[dict[str, Any]]:
    """分页拉取（客户端同款 PageSize=200；超过 MAX_PAGES 截断并标注）。"""
    source = "paid" if path == PAID_PATH else "free"
    out: list[dict[str, Any]] = []
    total_count = None
    for page in range(1, MAX_PAGES + 1):
        data = _post(vendor, endpoint + path, headers, _page_body(codes, page, extra))
        accounts = data.get("Accounts") or []
        total_count = data.get("TotalCount", total_count)
        out.extend(normalize_grant(a, source) for a in accounts if isinstance(a, dict))
        if len(accounts) < PAGE_SIZE:
            break
        if total_count is not None and len(out) >= int(total_count):
            break
    if total_count is not None and len(out) < int(total_count):
        # 不静默少算：截断信息随结果带回，由调用方展示
        out.append({"_truncated": True, "_source": source,
                    "_fetched": len(out), "_total": int(total_count)})
    return out


def parse_summary(data: dict[str, Any]) -> dict[str, Any]:
    """解析 get-user-resource-summary。"""
    groups = []
    for g in data.get("CreditGroups") or []:
        if not isinstance(g, dict):
            continue
        kind = str(g.get("Kind") or "")
        groups.append({
            "kind": kind,
            "name": str(g.get("Name") or _GROUP_LABELS.get(kind, kind)),
            "total": _num(g.get("CycleTotalCapacity")),
            "remain": _num(g.get("CycleRemainCapacity")),
            "used": _num(g.get("CycleUsedCapacity")),
            "frozen": _num(g.get("CycleFrozenCapacity")),
            "count": _num(g.get("TotalCount")),
        })
    packages = []
    for p in data.get("Packages") or []:
        if not isinstance(p, dict):
            continue
        packages.append({
            "package_code": str(p.get("PackageCode") or ""),
            "cycle_total": _num(p.get("CycleTotalCapacity")),
            "cycle_remain": _num(p.get("CycleRemainCapacity")),
            "cycle_used": _num(p.get("CycleUsedCapacity")),
            "frozen": _num(p.get("CycleFrozenCapacity")),
            "count": _num(p.get("TotalCount")),
        })
    return {
        "total_credits": _num(data.get("TotalCredits")),
        "is_paid_user": bool(data.get("IsPaidUser")),
        "subscription_package_name": str(data.get("SubscriptionPackageName") or ""),
        "groups": groups,
        "packages": packages,
    }


def today_slice_range() -> dict[str, str]:
    """web 端 buildSlicePeriodRange：当天 00:00:00 - 23:59:59。"""
    today = datetime.now().strftime("%Y-%m-%d")
    return {"SlicePeriodStartTime": f"{today} 00:00:00",
            "SlicePeriodEndTime": f"{today} 23:59:59"}


def fetch_credits() -> dict[str, Any]:
    """主查询：summary + free/paid 逐条明细。只读，不写任何本地状态。"""
    vendor, headers, endpoint = _session_and_headers()
    summary = parse_summary(_post(vendor, endpoint + SUMMARY_PATH, headers, {}))
    raw = fetch_packages(vendor, endpoint, headers, FREE_PATH, FREE_PACKAGE_CODES,
                         today_slice_range())
    raw += fetch_packages(vendor, endpoint, headers, PAID_PATH, PAID_PACKAGE_CODES,
                          {"NeedRenewInfo": True})
    # code_008 同时出现在免费组与付费组 code 列表里（客户端 Ys 如此），
    # 同一资源可能被两个端点各返回一次，按 ResourceId 去重。
    seen: set[str] = set()
    grants: list[dict[str, Any]] = []
    truncated: list[dict[str, Any]] = []
    for g in raw:
        if g.get("_truncated"):
            truncated.append({"source": g.get("_source", "?"),
                              "fetched": g.get("_fetched"),
                              "total": g.get("_total")})
            continue
        rid = g.get("resource_id") or ""
        if rid and rid in seen:
            continue
        if rid:
            seen.add(rid)
        grants.append(g)
    return {"endpoint": endpoint, "summary": summary, "grants": grants,
            "truncated": truncated,
            "queried_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")}


def claimed_today() -> bool | None:
    """今日是否已签（签到状态端点，只读）。失败返回 None 不炸主流程。"""
    try:
        vendor, headers, endpoint = _session_and_headers()
        data = _post(vendor, endpoint + STATUS_PATH, headers, {})
    except CreditQueryError:
        return None
    return bool(data.get("today_checked_in"))


def format_text(result: dict[str, Any], show_all: bool = False) -> str:
    """人类可读输出。默认只列有效条目；--all 带出已用完/已过期。"""
    summary = result["summary"]
    grants = result["grants"]
    valid = [g for g in grants if g.get("status") == 0]
    others = [g for g in grants if g.get("status") != 0]
    valid.sort(key=lambda g: g.get("expire_at") or "9999")
    others.sort(key=lambda g: g.get("expire_at") or "9999")

    lines = [f"WorkBuddy 积分明细（{result['queried_at']}）",
             f"总剩余: {_fmt_num(summary['total_credits'])} credits"
             f"（{summary['subscription_package_name'] or '未知套餐'}）"]
    if summary["groups"]:
        lines.append("分组:")
        for g in summary["groups"]:
            lines.append(f"  {g['name']:<8} 剩余 {_fmt_num(g['remain']):>10} / "
                         f"{_fmt_num(g['total']):<10}（{g['count'] or 0:.0f} 条）")
    remain_sum = sum(g["remain"] or 0 for g in valid)
    lines.append(f"有效积分 {len(valid)} 条，剩余合计 {_fmt_num(remain_sum)}"
                 f"（按过期时间排序）:")
    lines.append(f"  {'过期时间':<19} {'剩余':>8} {'总量':>8}  来源    积分包")
    for g in valid:
        lines.append(f"  {g['expire_at'] or '-':<19} {_fmt_num(g['remain']):>8} "
                     f"{_fmt_num(g['total']):>8}  {g['source']:<6}  {g['package_name']}"
                     f"（{g['grant_reason'] or '无发放原因'}）")
    if show_all and others:
        lines.append(f"已用完/已过期 {len(others)} 条:")
        for g in others:
            lines.append(f"  [{g['status_label']}] {g['expire_at'] or '-'}  "
                         f"剩余 {_fmt_num(g['remain'])} / {_fmt_num(g['total'])}  "
                         f"{g['package_name']}")
    elif others:
        lines.append(f"（另有 {len(others)} 条已用完/已过期，--all 显示）")
    for t in result.get("truncated") or []:
        lines.append(f"⚠️ {t['source']} 端分页截断：取到 {t['fetched']} / {t['total']} 条，"
                     f"剩余合计被低估")
    return "\n".join(lines)


def _fmt_num(value: float | None) -> str:
    if value is None:
        return "-"
    if value == int(value):
        return str(int(value))
    return f"{value:g}"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="wb_credits",
                                     description="WorkBuddy 积分明细查询（只读）")
    parser.add_argument("--all", action="store_true", help="包含已用完/已过期的条目")
    parser.add_argument("--json", action="store_true", help="输出全量 JSON")
    parser.add_argument("--line", action="store_true",
                        help='输出一行 JSON：{"balance": N, "claimed_today": bool}')
    args = parser.parse_args(argv)
    try:
        if args.line:
            result = fetch_credits()
            payload = {"balance": result["summary"]["total_credits"],
                       "claimed_today": claimed_today()}
            print(json.dumps(payload, ensure_ascii=False))
            return 0
        result = fetch_credits()
        if args.json:
            print(json.dumps(result, ensure_ascii=False, indent=1, default=str))
        else:
            print(format_text(result, show_all=args.all))
        return 0
    except CreditQueryError as exc:
        print(f"查询失败：{exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
