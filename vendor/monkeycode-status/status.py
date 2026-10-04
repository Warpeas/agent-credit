#!/usr/bin/env python3
"""MonkeyCode 积分状态（只读）。

为什么只读：签到接口 POST /api/v1/users/wallet/checkin 需要验证码
（返回 10701「兑换验证码失败」，客户端内建 captcha challenge/redeem + ha_token），
external 直签走不通；但**查询**接口不需要验证码，余额与今日是否已签都能拿到。

凭据：%APPDATA%/com.chaitin.baizhi.monkeycode/monkeycode-cookies.json
      cookie monkeycode_ai_session（明文，domain monkeycode-ai.com）
token 不进命令行、不进日志、不进输出（打印一律 <redacted>）。

用法：
    python vendor/monkeycode-status/status.py           # 人类可读
    python vendor/monkeycode-status/status.py --json    # 一行 JSON
退出码：0 查询成功；1 失败
"""
from __future__ import annotations

import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

HOST = "https://monkeycode-ai.com"
COOKIE_FILE = Path(r"C:\Users\Hunter\AppData\Roaming\com.chaitin.baizhi.monkeycode\monkeycode-cookies.json")
TIMEOUT = 25


def cookie_header() -> tuple[str, str]:
    if not COOKIE_FILE.exists():
        raise SystemExit(f"[failed] 凭据文件不存在: {COOKIE_FILE}")
    arr = json.loads(COOKIE_FILE.read_text(encoding="utf-8"))
    val = ""
    for c in arr:
        if c.get("name") == "monkeycode_ai_session":
            val = c.get("value") or ""
    if not val:
        raise SystemExit("[failed] 凭据里没有 monkeycode_ai_session（客户端可能已登出）")
    return f"monkeycode_ai_session={val}", val


def call(path: str) -> tuple[int, str]:
    jar, _ = cookie_header()
    req = urllib.request.Request(HOST + path, method="GET", headers={
        "Accept": "application/json",
        "User-Agent": "monkeycode-status/1.0",
        "Cookie": jar,
    })
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            return r.status, r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")
    except Exception as e:  # noqa: BLE001
        return -1, str(e)


def main() -> int:
    _, secret = cookie_header()

    code, body = call("/api/v1/users/wallet")
    wallet = {}
    if code == 200:
        try:
            wallet = (json.loads(body).get("data") or {})
        except Exception:  # noqa: BLE001
            wallet = {}

    code2, body2 = call("/api/v1/users/wallet/checkin")
    checked_in = None
    if code2 == 200:
        try:
            checked_in = (json.loads(body2).get("data") or {}).get("checked_in")
        except Exception:  # noqa: BLE001
            checked_in = None

    out = {
        "balance": int(wallet.get("balance") or 0),
        "claimed_today": bool(checked_in) if checked_in is not None else None,
        "daily_token_balance": int(wallet.get("daily_token_balance") or 0),
        "daily_token_limit": int(wallet.get("daily_token_limit") or 0),
        "wallet_http": code,
        "checkin_http": code2,
    }

    if "--json" in sys.argv:
        print(json.dumps(out, ensure_ascii=False))
    else:
        print(f"[wallet]  HTTP {code}")
        print(f"  账号剩余积分 : {out['balance']}")
        print(f"  今日 token   : {out['daily_token_balance']} / {out['daily_token_limit']}")
        print(f"[checkin] HTTP {code2}")
        print(f"  今日是否已签 : {out['claimed_today']}")

    return 0 if code == 200 else 1


if __name__ == "__main__":
    raise SystemExit(main())
