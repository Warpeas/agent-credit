"""MonkeyCode 积分查询（只读，2026-10-20）。

能查：登录用户的积分总量、今日是否已签。
不能查：逐条 grant 剩余与过期时间——GET /api/v1/users/wallet 没有这些字段，
客户端二进制也没有明细端点（records / transactions / detail / points 已于
2026-10-04 实测 404，2026-10-20 复扫 exe 仍只有 wallet 与 wallet/checkin）。

口径：wallet.balance 是毫积分，界面「积分」= balance // 1000。
证据：2026-10-04 账号页「积分 195」vs API 195267；签到 +100 后界面 295 vs
API 295267。把 raw balance 直接写入账本曾把 195 记成 195267，已回滚。

凭据：%APPDATA%\\com.chaitin.baizhi.monkeycode\\monkeycode-cookies.json
明文 cookie（运行时读取，不落盘、不打印、不进日志）。

用法：
    python -m agent_credit.mc_credits              # 人类可读
    python -m agent_credit.mc_credits --json       # 全量 JSON
    python -m agent_credit.mc_credits --line       # 一行 JSON（status_command 约定）
    python -m agent_credit.mc_credits --ledger     # 账本对账载荷（credits_command 约定）
"""
from __future__ import annotations

import argparse
import json
import os
import ssl
import sys
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Any

HOST = "https://monkeycode-ai.com"
WALLET_PATH = "/api/v1/users/wallet"
CHECKIN_PATH = "/api/v1/users/wallet/checkin"
# 界面积分 = raw_balance // SCALE。见模块 docstring。
SCALE = 1000
USER_AGENT = "monkeycode-credits/1.0"


class CreditQueryError(Exception):
    """查询失败（未登录 / 网络 / 服务端业务错误）。消息固定，不含凭据。"""


def cookie_path() -> Path:
    appdata = (os.environ.get("APPDATA") or "").rstrip()
    return Path(appdata) / "com.chaitin.baizhi.monkeycode" / "monkeycode-cookies.json"


def load_cookie_header(path: Path | None = None) -> str:
    """读明文 cookie，拼 Cookie 头。失败抛 CreditQueryError；永不返回值本身给调用方打印。"""
    ck = path or cookie_path()
    if not ck.is_file():
        raise CreditQueryError(
            "未找到 MonkeyCode 登录凭据（%APPDATA%\\com.chaitin.baizhi.monkeycode"
            "\\monkeycode-cookies.json）。请先在客户端登录"
        )
    try:
        arr = json.loads(ck.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise CreditQueryError("凭据文件不可读") from exc
    if not isinstance(arr, list) or not arr:
        raise CreditQueryError("凭据文件为空")
    parts = []
    for item in arr:
        if not isinstance(item, dict):
            continue
        name, value = item.get("name"), item.get("value")
        if isinstance(name, str) and isinstance(value, str) and name and value:
            parts.append(f"{name}={value}")
    if not parts:
        raise CreditQueryError("凭据文件没有可用 cookie")
    return "; ".join(parts)


def _get_json(path: str, cookie_header: str) -> dict[str, Any]:
    req = urllib.request.Request(
        HOST + path,
        headers={
            "Accept": "application/json",
            "Cookie": cookie_header,
            "User-Agent": USER_AGENT,
        },
        method="GET",
    )
    ctx = ssl.create_default_context()
    try:
        with urllib.request.urlopen(req, timeout=20, context=ctx) as resp:
            raw = resp.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        raise CreditQueryError(f"HTTP {exc.code} {path}") from None
    except urllib.error.URLError as exc:
        raise CreditQueryError(f"网络错误 {path}") from exc
    try:
        payload = json.loads(raw)
    except ValueError as exc:
        raise CreditQueryError(f"响应不是 JSON {path}") from exc
    if not isinstance(payload, dict):
        raise CreditQueryError(f"响应不是 JSON 对象 {path}")
    code = payload.get("code")
    if code not in (0, None):
        raise CreditQueryError(f"业务错误 code={code} {path}")
    return payload


def display_credits(raw_balance: Any) -> int:
    """毫积分 → 界面积分。非整数直接拒绝，避免静默失真。"""
    if isinstance(raw_balance, bool) or not isinstance(raw_balance, (int, float)):
        raise CreditQueryError("wallet.balance 不是数字")
    return int(raw_balance) // SCALE


def parse_wallet(payload: dict[str, Any]) -> dict[str, Any]:
    data = payload.get("data")
    if not isinstance(data, dict):
        raise CreditQueryError("wallet 响应缺少 data")
    if "balance" not in data:
        raise CreditQueryError("wallet 响应缺少 balance")
    raw = data["balance"]
    credits = display_credits(raw)
    return {
        "balance": credits,
        "balance_raw": int(raw),
    }


def parse_checkin(payload: dict[str, Any]) -> bool:
    data = payload.get("data")
    if not isinstance(data, dict):
        raise CreditQueryError("checkin 响应缺少 data")
    return bool(data.get("checked_in"))


def fetch_credits(cookie_header: str | None = None) -> dict[str, Any]:
    header = cookie_header if cookie_header is not None else load_cookie_header()
    wallet = parse_wallet(_get_json(WALLET_PATH, header))
    try:
        claimed = parse_checkin(_get_json(CHECKIN_PATH, header))
    except CreditQueryError:
        claimed = None
    return {
        "account": "monkeycode_credit",
        "balance": wallet["balance"],
        "balance_raw": wallet["balance_raw"],
        "scale": SCALE,
        "claimed_today": claimed,
        "grants": None,
        "expires": None,
        "note": "官方接口无逐条 grant/过期时间；balance 已按毫积分÷1000 换成界面积分",
        "queried_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }


def ledger_payload(result: dict[str, Any]) -> dict[str, Any]:
    """账本对账载荷（`--ledger`，供 checkin 的 sync 消费）。

    服务端没有逐条 grant，只能写一条总量、expires=null。
    这样看板会把余额标成「服务端真值」，过期仍是「未知」——两边都不撒谎。
    """
    remain = int(result["balance"])
    grants = []
    if remain > 0:
        grants.append({"remain": remain, "expires": None})
    return {"account": "monkeycode_credit", "total": remain, "grants": grants}


def format_text(result: dict[str, Any]) -> str:
    claimed = result.get("claimed_today")
    if claimed is True:
        claimed_s = "是"
    elif claimed is False:
        claimed_s = "否"
    else:
        claimed_s = "未知"
    lines = [
        f"MonkeyCode 积分（{result.get('queried_at') or '-'}）",
        f"总剩余: {result['balance']} credits"
        f"（raw {result['balance_raw']} ÷ {result['scale']}）",
        f"今日已签: {claimed_s}",
        "过期时间: 无（服务端未下发逐条 grant / expire 字段）",
        "明细: 无。二进制只有 /users/wallet 与 /users/wallet/checkin。",
    ]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="mc_credits",
        description="MonkeyCode 积分查询（只读；无逐条过期）",
    )
    parser.add_argument("--json", action="store_true", help="输出全量 JSON")
    parser.add_argument(
        "--line",
        action="store_true",
        help='输出一行 JSON：{"balance": N, "claimed_today": bool|null}',
    )
    parser.add_argument(
        "--ledger",
        action="store_true",
        help='输出账本对账载荷：{"grants":[{"remain":N,"expires":null}],"total":N}',
    )
    args = parser.parse_args(argv)
    try:
        result = fetch_credits()
        if args.line:
            print(json.dumps(
                {"balance": result["balance"], "claimed_today": result["claimed_today"]},
                ensure_ascii=False,
            ))
        elif args.ledger:
            print(json.dumps(ledger_payload(result), ensure_ascii=False))
        elif args.json:
            print(json.dumps(result, ensure_ascii=False, indent=1, default=str))
        else:
            print(format_text(result))
        return 0
    except CreditQueryError as exc:
        print(f"查询失败：{exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
