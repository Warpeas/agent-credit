"""LobsterAI 积分明细查询与台账对账（2026-11-06 打通）。

数据源：`GET https://lobsterai-server.youdao.com/api/user/credits-earned`
（桌面客户端同一个 Bearer token，只读）。服务端返回**逐条发放记录**：

    {"totalEarned": 4900, "totalRemaining": 2792.46,
     "records": [{"type": "campaign", "name": "每日登录奖励",
                  "credits": 100, "creditsUsed": 0, "creditsRemaining": 100,
                  "status": "active",
                  "earnedAt": "2026-11-06T00:02:27",
                  "expiresAt": "2026-12-06T00:02:28"}, ...]}

这正是旧记录说「拿不到」的东西：每次领取的积分、已用/剩余、过期时间。
token 在 `%APPDATA%\\LobsterAI\\lobsterai.sqlite` 的 kv 表 `auth_tokens` 里，
是客户端自己落的明文；脚本只读、只调官方接口，token 不进命令行/日志/输出。

用法：
    python -m agent_credit.lobsterai_credits            # 人类可读明细
    python -m agent_credit.lobsterai_credits --json     # 原始 JSON
    python -m agent_credit.lobsterai_credits --line     # 一行 JSON（status_command）
    python -m agent_credit.lobsterai_credits --ledger   # 对账载荷（credits_command）

注意：账本是整数粒度，`--ledger` 把每条剩余四舍五入；精确到分的余额看
`--line` / `--json` 的 `totalRemaining`。
"""
from __future__ import annotations

import argparse
import contextlib
import ctypes
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

ACCOUNT = "lobsterai"
HOST = "https://lobsterai-server.youdao.com"
DB = Path(os.environ.get("APPDATA", "")) / "LobsterAI" / "lobsterai.sqlite"
TIMEOUT = 30
CN_TZ = timezone(timedelta(hours=8))

APP_PROCESS = "LobsterAI.exe"
# 「正在用」的判定窗口：会话状态还是 running，或最近 N 分钟仍有消息/会话更新。
# 可用环境变量覆盖，测试里会把它调到极大来模拟「有会话」。
ACTIVE_WINDOW_SEC = int(os.environ.get("AGENT_CREDIT_LOBSTER_ACTIVE_WINDOW", "300"))
# 关客户端再读：显式开关，默认关闭；只在确认无会话时走，且只发 WM_CLOSE，绝不强杀。
CLOSE_FLAG_ENV = "AGENT_CREDIT_LOBSTER_CLOSE_APP"
DEFER_EXIT = 4
ACTIVE_STATUSES = {
    "running", "queued", "starting", "streaming", "working",
    "in_progress", "in-progress", "active", "executing", "busy",
}


def local_today() -> date:
    """服务端的 earnedAt 是北京时间（无时区后缀），别用 UTC 的 date.today() 比。"""
    return datetime.now(CN_TZ).date()


class CreditQueryError(Exception):
    """查询失败；消息固定，不含凭据。"""


class SyncDeferred(CreditQueryError):
    """客户端正在使用中，本轮主动跳过对账（退出码 4，checkin 标 deferred）。"""


def app_running() -> bool:
    """客户端进程是否在跑（只查进程，不碰窗口/会话）。"""
    try:
        out = subprocess.run(
            ["tasklist", "/FI", f"IMAGENAME eq {APP_PROCESS}", "/FO", "CSV", "/NH"],
            capture_output=True, text=True, timeout=10,
            encoding="utf-8", errors="replace").stdout or ""
    except Exception:  # noqa: BLE001
        return False
    return APP_PROCESS.lower() in out.lower()


@contextlib.contextmanager
def _snapshot():
    """把 sqlite + -wal + -shm 复制到临时目录再读，读完删除。

    运行中的客户端会在库上持有锁，`mode=ro` 直连实测报 "disk I/O error"；
    复制副本是只读操作、不打扰客户端，也不要求关程序。WAL 必须一起复制，
    否则副本里看不到最近写入（auth_tokens 可能就在 WAL 里）。
    """
    tmp = Path(tempfile.mkdtemp(prefix="lobsterai-snap-"))
    try:
        dst = tmp / DB.name
        shutil.copy2(DB, dst)
        for suffix in ("-wal", "-shm"):
            src = Path(str(DB) + suffix)
            if src.exists():
                shutil.copy2(src, Path(str(dst) + suffix))
        yield dst
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _latest_ms(con: sqlite3.Connection) -> int:
    stamps = []
    for sql in ("SELECT max(updated_at) FROM cowork_sessions",
                "SELECT max(created_at) FROM cowork_messages"):
        try:
            value = con.execute(sql).fetchone()[0]
        except sqlite3.Error:
            continue
        if isinstance(value, (int, float)):
            stamps.append(int(value))
    return max(stamps) if stamps else 0


def session_active(db_path: Path) -> tuple[bool, str]:
    """副本里判断有没有进行中的会话。

    两个信号取并集：①状态明确在跑（running/streaming/...）；
    ②最近 ACTIVE_WINDOW_SEC 秒内还有会话/消息更新——状态字段有时来不及翻。
    """
    con = sqlite3.connect(str(db_path))
    try:
        con.row_factory = sqlite3.Row
        try:
            rows = con.execute(
                "SELECT title, status FROM cowork_sessions").fetchall()
        except sqlite3.Error:
            rows = []
        for row in rows:
            status = str(row["status"] or "").strip().lower()
            if status in ACTIVE_STATUSES:
                title = str(row["title"] or "").strip()[:24]
                return True, f"会话「{title}」状态 {status}"
        try:
            running = con.execute(
                "SELECT count(*) FROM subagent_runs").fetchone()[0]
        except sqlite3.Error:
            running = 0
        if running:
            try:
                active_runs = con.execute(
                    "SELECT count(*) FROM subagent_runs "
                    "WHERE lower(status) IN (%s)"
                    % ",".join("?" * len(ACTIVE_STATUSES)),
                    tuple(ACTIVE_STATUSES)).fetchone()[0]
            except sqlite3.Error:
                active_runs = 0
            if active_runs:
                return True, f"{active_runs} 个子任务仍在运行"
        stamp = _latest_ms(con)
        if stamp and time.time() * 1000 - stamp < ACTIVE_WINDOW_SEC * 1000:
            mins = max(1, ACTIVE_WINDOW_SEC // 60)
            return True, f"最近 {mins} 分钟仍有会话活动"
    finally:
        con.close()
    return False, "无进行中的会话"


def _read_token(db_path: Path, readonly: bool) -> str:
    uri = ("file:" + str(db_path) + "?mode=ro") if readonly else str(db_path)
    con = sqlite3.connect(uri, uri=readonly)
    try:
        row = con.execute("SELECT value FROM kv WHERE key='auth_tokens'").fetchone()
    finally:
        con.close()
    if not row:
        raise CreditQueryError("kv 里没有 auth_tokens（未登录？）")
    try:
        token = (json.loads(row[0]) or {}).get("accessToken")
    except ValueError:
        raise CreditQueryError("auth_tokens 不是合法 JSON") from None
    if not token:
        raise CreditQueryError("auth_tokens 里没有 accessToken")
    return str(token)


def _close_enabled() -> bool:
    return str(os.environ.get(CLOSE_FLAG_ENV) or "").strip().lower() in (
        "1", "true", "yes", "on")


def _close_gracefully() -> bool:
    """只给主窗口发 WM_CLOSE，等它自己退出；绝不 taskkill/强杀。"""
    try:
        user32 = ctypes.WinDLL("user32", use_last_error=True)
        found = []

        @ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)
        def enum_proc(hwnd, _lparam):
            buf = ctypes.create_unicode_buffer(256)
            user32.GetWindowTextW(hwnd, buf, 256)
            if buf.value.strip() in ("LobsterAI", "LobsterAI.exe") and user32.IsWindowVisible(hwnd):
                found.append(hwnd)
            return True

        user32.EnumWindows(enum_proc, 0)
        if not found:
            return False
        user32.PostMessageW(found[0], 0x10, 0, 0)  # WM_CLOSE
    except Exception:  # noqa: BLE001
        return False
    deadline = time.time() + 20
    while time.time() < deadline:
        if not app_running():
            return True
        time.sleep(1)
    return not app_running()


def _token() -> str:
    if not DB.exists():
        raise CreditQueryError(f"找不到 {DB}")
    # 客户端没开：直接只读，没有锁竞争。
    if not app_running():
        try:
            return _read_token(DB, readonly=True)
        except sqlite3.Error as exc:
            raise CreditQueryError(f"读登录态失败：{exc}") from None

    # 客户端在跑：先做只读快照。快照同时用于「有没有会话」的判断。
    # 边写边复制偶尔会拿到撕裂副本，失败就再拍一次（最多两拍）。
    session_checked = False
    active = None
    reason = ""
    for attempt in (1, 2):
        try:
            with _snapshot() as snap:
                active, why = session_active(snap)
                session_checked = True
                if active:
                    raise SyncDeferred(
                        f"LobsterAI 正在使用中（{why}）；本次跳过对账，等空闲或下次签到时自动补齐")
                try:
                    return _read_token(snap, readonly=False)
                except sqlite3.Error as exc:
                    reason = f"只读快照读登录态失败：{exc}"
        except SyncDeferred:
            raise
        except (sqlite3.Error, OSError) as exc:
            reason = f"做只读快照失败：{exc}"
        if attempt == 1:
            time.sleep(0.4)

    # 回退：显式开关 + 已确认无会话 + 进程仍在跑，才优雅关闭再读一次。
    if _close_enabled() and session_checked and not active and app_running():
        if _close_gracefully():
            try:
                token = _read_token(DB, readonly=True)
                print("[note] 已优雅关闭 LobsterAI 后读取登录态", file=sys.stderr)
                return token
            except sqlite3.Error as exc:
                reason = f"关闭后读取仍失败：{exc}"
        else:
            reason += "；优雅关闭未成功（未强杀）"
    elif app_running() and not _close_enabled():
        reason += "；客户端仍开着，未尝试关闭（AGENT_CREDIT_LOBSTER_CLOSE_APP 默认关闭）"
    if app_running():
        # 客户端在跑但快照读不出：不是业务失败，按「让位」处理，下次自动重试，
        # 避免把一次瞬时 IO 竞争记成对账失败、惊动告警。
        raise SyncDeferred((reason or "读登录态失败") + "；下次签到时自动重试")
    raise CreditQueryError(reason or "读登录态失败，下次自动重试")


def _call(path: str) -> dict[str, Any]:
    req = urllib.request.Request(
        HOST + path,
        headers={
            "Authorization": f"Bearer {_token()}",
            "Accept": "application/json",
            "User-Agent": "agent-credit/1.0",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            body = resp.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        raise CreditQueryError(f"HTTP {exc.code}") from None
    except Exception as exc:  # noqa: BLE001
        raise CreditQueryError(f"请求失败：{exc}") from None
    try:
        payload = json.loads(body)
    except ValueError:
        raise CreditQueryError("响应不是 JSON") from None
    if payload.get("code") not in (0, None):
        raise CreditQueryError(f"服务端返回 code={payload.get('code')}")
    data = payload.get("data")
    if not isinstance(data, dict):
        raise CreditQueryError("响应缺少 data")
    return data


def fetch() -> dict[str, Any]:
    data = _call("/api/user/credits-earned")
    records = data.get("records")
    if not isinstance(records, list):
        raise CreditQueryError("响应缺少 records")
    return data


def _date_part(value: Any) -> str | None:
    if not isinstance(value, str) or len(value) < 10:
        return None
    try:
        return date.fromisoformat(value[:10]).isoformat()
    except ValueError:
        return None


def ledger_payload(data: dict[str, Any]) -> dict[str, Any]:
    """转成 checkin.sync 认的 detail 载荷（逐条 amount/remaining/expires）。"""
    details = []
    for r in data.get("records") or []:
        if not isinstance(r, dict):
            continue
        try:
            amount = float(r.get("credits") or 0)
            remain = float(r.get("creditsRemaining") or 0)
        except (TypeError, ValueError):
            continue
        if amount <= 0:
            continue
        details.append({
            "type": r.get("type") or "unknown",
            "name": r.get("name") or "",
            "amount": amount,
            "remaining": max(0.0, min(amount, remain)),
            "earned_at": r.get("earnedAt") or "",
            "granted_at": _date_part(r.get("earnedAt")),
            "expires_at": _date_part(r.get("expiresAt")),
            "status": r.get("status") or "",
        })
    return {"detail": details}


def line_payload(data: dict[str, Any]) -> dict[str, Any]:
    records = data.get("records") or []
    today = local_today().isoformat()
    claimed_today = any(
        isinstance(r, dict)
        and r.get("type") == "campaign"
        and _date_part(r.get("earnedAt")) == today
        for r in records
    )
    try:
        balance = round(float(data.get("totalRemaining") or 0))
    except (TypeError, ValueError):
        balance = 0
    return {"balance": balance, "claimed_today": claimed_today}


def _fmt(value: Any) -> str:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return str(value)
    return f"{number:g}" if number != int(number) else str(int(number))


def print_human(data: dict[str, Any]) -> None:
    records = [r for r in (data.get("records") or []) if isinstance(r, dict)]
    active = [r for r in records if r.get("status") == "active"]
    print(f"LobsterAI 积分：累计发放 {_fmt(data.get('totalEarned'))}，"
          f"当前可用 {_fmt(data.get('totalRemaining'))}，共 {len(records)} 条发放记录"
          f"（active {len(active)}）")
    print()
    print(f"{'领取时间':<20} {'类型':<8} {'积分':>7} {'剩余':>8} {'过期时间':<20} 状态")
    for r in sorted(records, key=lambda x: str(x.get("earnedAt") or ""), reverse=True):
        print(f"{str(r.get('earnedAt') or '-')[:19]:<20} "
              f"{str(r.get('type') or '-'):<8} "
              f"{_fmt(r.get('credits')):>7} {_fmt(r.get('creditsRemaining')):>8} "
              f"{str(r.get('expiresAt') or '-')[:19]:<20} {r.get('status') or '-'}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="LobsterAI 积分明细（只读）")
    parser.add_argument("--json", action="store_true", help="输出原始 JSON")
    parser.add_argument("--line", action="store_true", help="输出一行 JSON（status_command）")
    parser.add_argument("--ledger", action="store_true", help="输出对账 JSON（credits_command）")
    parser.add_argument("--close-app", action="store_true",
                        help="只读快照失败且确认无会话时才优雅关闭客户端再读（默认关闭）")
    args = parser.parse_args(argv)
    if args.close_app:
        os.environ[CLOSE_FLAG_ENV] = "1"
    try:
        data = fetch()
    except SyncDeferred as exc:
        print(f"[deferred] {exc}", file=sys.stderr)
        return DEFER_EXIT
    except CreditQueryError as exc:
        print(f"[failed] {exc}", file=sys.stderr)
        return 1
    if args.json:
        print(json.dumps(data, ensure_ascii=False, indent=2))
    elif args.line:
        print(json.dumps(line_payload(data), ensure_ascii=False))
    elif args.ledger:
        print(json.dumps(ledger_payload(data), ensure_ascii=False))
    else:
        print_human(data)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
