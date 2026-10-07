#!/usr/bin/env python3
"""LobsterAI（网易有道龙虾）每日签到（external 直签）。

端点与鉴权全部由本机 app.asar 逆向得到（见 research/answers/lobsterai.md）：
  host   https://lobsterai-server.youdao.com
  槽位   GET  /api/client-activities/slot?placement=...&clientVersion=...&containerApiVersion=1&platform=win32
  上下文 GET  /api/client-activities/{activityCode}/context?configRevision=N
  领取   POST /api/client-activities/{activityCode}/actions/check_in
  鉴权   Authorization: Bearer <accessToken>
  token  本机明文，%APPDATA%\\LobsterAI\\lobsterai.sqlite 的 kv 表 auth_tokens

合规（硬规则 6 例外条款）：只读本机明文凭据、只调官方接口、token 不进命令行/日志/输出。

用法：
    python vendor/lobsterai-auto-signin/signin.py status   # 只读查询
    python vendor/lobsterai-auto-signin/signin.py auto     # 有活动就领
退出码：0 成功或已领；2 无可领活动（服务端未下发）；1 失败
"""
from __future__ import annotations

import os
import json
import sqlite3
import sys
import urllib.error
import urllib.request
from pathlib import Path

DB = Path(os.environ["APPDATA"]) / "LobsterAI" / "lobsterai.sqlite"
HOST = "https://lobsterai-server.youdao.com"
PLACEMENTS = ["desktop_sidebar", "desktop_startup_modal"]
CLIENT_VERSION = "1.0.0"   # 实测服务端不校验（0.0.0 也返回 code 0）
CONTAINER_API_VERSION = 1
PLATFORM = "win32"
DAILY_CHECK_IN_CODE = "daily_check_in"
CHECK_IN_ACTION = "check_in"
TIMEOUT = 30

_token_cache: str | None = None


def token() -> str:
    global _token_cache
    if _token_cache:
        return _token_cache
    if not DB.exists():
        raise SystemExit(f"[failed] 找不到 {DB}")
    con = sqlite3.connect("file:" + str(DB) + "?mode=ro", uri=True)
    try:
        row = con.execute("SELECT value FROM kv WHERE key='auth_tokens'").fetchone()
    finally:
        con.close()
    if not row:
        raise SystemExit("[failed] kv 里没有 auth_tokens（未登录？）")
    data = json.loads(row[0])
    tok = data.get("accessToken")
    if not tok:
        raise SystemExit("[failed] auth_tokens 里没有 accessToken")
    _token_cache = tok
    return tok


def call(path: str, method: str = "GET", body: dict | None = None) -> tuple[int, str]:
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(
        HOST + path,
        data=data,
        method=method,
        headers={
            "Authorization": f"Bearer {token()}",
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": "lobsterai-auto-signin/1.0",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            return r.status, r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")
    except Exception as e:  # noqa: BLE001
        return -1, str(e)


def mask(text: str) -> str:
    try:
        t = token()
    except SystemExit:
        t = ""
    if t:
        text = text.replace(t, "<redacted>")
    return text[:800]


def slot_query(placement: str) -> str:
    return (
        f"/api/client-activities/slot?placement={placement}"
        f"&clientVersion={CLIENT_VERSION}"
        f"&containerApiVersion={CONTAINER_API_VERSION}&platform={PLATFORM}"
    )


def find_activity() -> dict | None:
    """两个位置都问一下，返回第一个非空的 activity。"""
    for placement in PLACEMENTS:
        code, body = call(slot_query(placement))
        if code != 200:
            continue
        try:
            payload = json.loads(body)
        except Exception:  # noqa: BLE001
            continue
        data = payload.get("data") or {}
        act = data.get("activity")
        if act:
            act["_placement"] = placement
            return act
    return None


def cmd_status() -> int:
    act = find_activity()
    if not act:
        # 打印一次原始返回，便于确认到底是 empty 还是接口坏了
        code, body = call(slot_query(PLACEMENTS[0]))
        print(f"[status] HTTP {code}")
        print(mask(body))
        print("[no-activity] 服务端当前未下发签到活动（slotState=empty），无需领取")
        return 2
    print(f"[status] 活动: {act.get('activityCode')} rev={act.get('configRevision')} "
          f"state={act.get('lifecycleState')} placement={act.get('_placement')}")
    return 0


def cmd_auto() -> int:
    act = find_activity()
    if not act:
        code, body = call(slot_query(PLACEMENTS[0]))
        print(f"[status] HTTP {code}")
        print(mask(body))
        print("[no-activity] 服务端当前未下发签到活动，未领取")
        return 2

    act_code = act.get("activityCode")
    rev = act.get("configRevision")
    print(f"[activity] {act_code} rev={rev}")

    if act_code != DAILY_CHECK_IN_CODE:
        print(f"[skip] 当前活动不是每日签到（{act_code}），未领取")
        return 2

    # 上下文：拿 actions 与已领状态
    if rev:
        c, b = call(f"/api/client-activities/{act_code}/context?configRevision={rev}")
        print(f"[context] HTTP {c}")
        print(mask(b))
        try:
            ctx = (json.loads(b).get("data") or {})
        except Exception:  # noqa: BLE001
            ctx = {}
        if ctx.get("claimedToday") is True or ctx.get("state", {}).get("claimedToday") is True:
            print("[already] 今日已签到，不重复领取")
            return 0

    c2, b2 = call(
        f"/api/client-activities/{act_code}/actions/{CHECK_IN_ACTION}",
        method="POST",
        body={},
    )
    print(f"[claim] HTTP {c2}")
    print(mask(b2))
    if c2 == 200:
        try:
            code = json.loads(b2).get("code")
        except Exception:  # noqa: BLE001
            code = None
        if code in (0, None):
            print("[ok] 签到成功")
            return 0
    print("[pending] 领取未成功，需人工确认")
    return 2


def main() -> int:
    mode = sys.argv[1] if len(sys.argv) > 1 else "status"
    if mode == "status":
        return cmd_status()
    if mode == "auto":
        return cmd_auto()
    print(__doc__)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
