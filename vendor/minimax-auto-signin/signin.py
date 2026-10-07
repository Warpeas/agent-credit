#!/usr/bin/env python3
"""MiniMax Code 每日签到（external 直签）。

为什么走 external：UI 路线要求客户端在前台且能冷启动，而本环境冷启动 MiniMax 会卡在
updater.exe（主进程起不来），无法做到无人值守。端点由本机 app.asar 逆向得到，见
research/answers/minimax.md。

合规：只读取本机**明文**凭据（.minimax/auth/.../auth.json），只调官方接口，
token 不进命令行、不进日志、不进输出（打印时一律 <redacted>）。

用法：
    python vendor/minimax-auto-signin/signin.py status   # 只读查询，不领取
    python vendor/minimax-auto-signin/signin.py auto     # 查询后按需领取
退出码：0 成功/已签；2 未领取（需人工）；1 失败
"""
from __future__ import annotations

import ctypes
import ctypes.wintypes as wt
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

HOST = "https://agent.minimax.cn"
AUTH_FILE = Path.home() / ".minimax" / "auth" / "prod" / "cn" / "mcode-public" / "auth.json"
# 官方 OAuth2 端点（从 app.asar 逆向：MCODE_OAUTH_CLIENT_ID / resolveMCodeOAuthEndpointConfig）。
# accessToken 实测有效期很短——客户端在跑时 generation 每 ~7 分钟就 +1，
# 所以不跑客户端就必然过期。用 refreshToken 自刷新可拿回 expires_in=3600，
# 无需客户端常驻。
TOKEN_URL = "https://account.minimax.cn/oauth2/token"
CLIENT_ID = "mcode-public"
# ⚠️ 2026-10-03 关闭：刷新会轮换 refresh token，而脚本写回时无法同步更新
# `loginEpoch`（登录纪元），客户端启动时发现 token 与 loginEpoch 不匹配就会
# 退回未登录 —— 主人实测「脚本签完再打开客户端要重新登录」。
# 默认 token 有效就直签、失效就交回 UI/客户端路线，让客户端用自己的正常途径续期。
# 真要开就设环境变量 MINIMAX_ALLOW_TOKEN_REFRESH=1。
ALLOW_TOKEN_REFRESH = os.environ.get(
    "MINIMAX_ALLOW_TOKEN_REFRESH", "").strip().lower() in ("1", "true", "yes")
REFRESH_MARGIN_SEC = 600  # 剩余不足 10 分钟就先刷新

# 客户端续期（warmup）：token 失效时临时拉起 MiniMax，让它用自己的正常途径续期，
# 续完就关掉。脚本**完全不碰 auth.json**，所以不会像自刷新那样冲掉 loginEpoch。
# 设 MINIMAX_NO_WARMUP=1 可关。
APP_EXE = str(Path(os.environ["LOCALAPPDATA"]) / "Programs" / "MiniMax Code" / "MiniMax Code.exe")
APP_PROC = "MiniMax Code.exe"
ALLOW_CLIENT_WARMUP = os.environ.get(
    "MINIMAX_NO_WARMUP", "").strip().lower() not in ("1", "true", "yes")
WARMUP_TIMEOUT_SEC = 180
# 服务端强制校验 timezone_id，缺了会返回 1406010011 invalid timezone_id（HTTP 仍是 200）。
# 只有 IANA 时区名有效（Asia/Shanghai 通过；8 / +8 / 28800 / Shanghai 全部被拒）。
TZ = "Asia/Shanghai"
STATUS_PATH = "/minimax-cloud/api/v1/signin/status?timezone_id=" + TZ
CLAIM_PATH = "/minimax-cloud/api/v1/signin/claim"
TIMEOUT = 30

# 数据模型（本机 app.asar 逆向，见 research/answers/minimax.md）：
#   SigninDayStatus 1=Upcoming 2=Claimable 3=Claimed 4=Disabled
DAY_CLAIMED = 3


def _find_record() -> tuple[dict, str, dict]:
    data = json.loads(AUTH_FILE.read_text(encoding="utf-8"))
    for key, rec in (data.get("records") or {}).items():
        if "oauth" in key and isinstance(rec, dict) and rec.get("accessToken"):
            return data, key, rec
    raise SystemExit("[failed] 凭据里没有 accessToken")


def load_token() -> tuple[str, str, int]:
    if not AUTH_FILE.exists():
        raise SystemExit(f"[failed] 凭据文件不存在: {AUTH_FILE}")
    _, _, rec = _find_record()
    return rec["accessToken"], rec.get("tokenType", "Bearer"), int(rec.get("expiresAtMs") or 0)


def refresh_token(force: bool = False) -> tuple[str, str]:
    """用 refreshToken 换 accessToken，成功后写回 auth.json。

    refresh token 会轮换（服务端原文：'this refresh token can no longer be
    used'），且写回无法同步 loginEpoch，会让客户端退回未登录。故默认禁用，
    见 ALLOW_TOKEN_REFRESH。
    返回 (accessToken, tokenType)；失败返回 (None, None)，调用方回退到旧 token。
    """
    data, key, rec = _find_record()
    if not ALLOW_TOKEN_REFRESH:
        return rec["accessToken"], rec.get("tokenType", "Bearer")
    left = (int(rec.get("expiresAtMs") or 0) - int(time.time() * 1000)) / 1000
    if not force and left > REFRESH_MARGIN_SEC:
        return rec["accessToken"], rec.get("tokenType", "Bearer")

    body = urllib.parse.urlencode({
        "grant_type": "refresh_token",
        "client_id": CLIENT_ID,
        "refresh_token": rec["refreshToken"],
    }).encode()
    req = urllib.request.Request(TOKEN_URL, data=body, method="POST", headers={
        "Content-Type": "application/x-www-form-urlencoded",
        "Accept": "application/json",
    })
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            code, raw = r.status, r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        code, raw = e.code, e.read().decode("utf-8", "replace")
    except Exception as e:  # noqa: BLE001
        print(f"[refresh] 请求失败: {e}")
        return None, None
    if code != 200:
        print(f"[refresh] HTTP {code}: {raw[:200]}")
        return None, None

    j = json.loads(raw)
    at = j.get("access_token")
    if not at:
        print("[refresh] 响应缺少 access_token")
        return None, None
    rec["accessToken"] = at
    if j.get("refresh_token"):
        rec["refreshToken"] = j["refresh_token"]  # 轮换：新值必须留存
    if j.get("token_type"):
        tt = j["token_type"]
        rec["tokenType"] = "Bearer" if tt.lower() == "bearer" else tt
    if j.get("expires_in"):
        rec["expiresAtMs"] = int(time.time() * 1000) + int(j["expires_in"]) * 1000
    rec["generation"] = int(rec.get("generation") or 0) + 1
    tmp = AUTH_FILE.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(str(tmp), str(AUTH_FILE))
    print(f"[refresh] token 已刷新并写回（新有效期 {j.get('expires_in')}s）")
    return at, rec["tokenType"]


def call(path: str, method: str = "GET", body: dict | None = None,
         retried: bool = False) -> tuple[int, str]:
    token, token_type = refresh_token()
    if not token:
        token, token_type, _ = load_token()
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(
        HOST + path,
        data=data,
        method=method,
        headers={
            "Authorization": f"{token_type} {token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": "mcode-auto-signin/1.0",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            return resp.status, resp.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        # 401/403：token 可能已失效。仅在显式允许时才强制刷新重试
        # （默认禁用，见 ALLOW_TOKEN_REFRESH）。
        if e.code in (401, 403) and not retried and ALLOW_TOKEN_REFRESH:
            refresh_token(force=True)
            return call(path, method=method, body=body, retried=True)
        return e.code, e.read().decode("utf-8", "replace")
    except Exception as e:  # noqa: BLE001
        return -1, str(e)


def mask(text: str) -> str:
    out = text
    token, _, _ = (load_token() if AUTH_FILE.exists() else ("", "", 0))
    if token:
        out = out.replace(token, "<redacted>")
    return out[:600]


def cmd_status() -> int:
    if not warm_token():
        print("[pending] token 已失效，且客户端续期未成功")
        return 2
    _, _, exp = load_token()
    if exp:
        left = (exp - int(time.time() * 1000)) / 1000 / 3600
        print(f"[info] token 剩余有效期约 {left:.1f} 小时")
    code, body = call(STATUS_PATH)
    print(f"[status] HTTP {code}")
    print(mask(body))
    return 0 if code == 200 else 1


def _proc_pids(name: str) -> set[int]:
    """纯 Win32 快照枚举，不依赖 tasklist / powershell。"""
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)

    class PROCESSENTRY32W(ctypes.Structure):
        _fields_ = [
            ("dwSize", wt.DWORD), ("cntUsage", wt.DWORD), ("th32ProcessID", wt.DWORD),
            ("th32DefaultHeapID", ctypes.POINTER(ctypes.c_ulong)),
            ("th32ModuleID", wt.DWORD), ("cntThreads", wt.DWORD),
            ("th32ParentProcessID", wt.DWORD), ("pcPriClassBase", ctypes.c_long),
            ("dwFlags", wt.DWORD), ("szExeFile", ctypes.c_wchar * 260),
        ]

    snap = k32.CreateToolhelp32Snapshot(0x00000002, 0)
    if snap == -1:
        return set()
    pe = PROCESSENTRY32W()
    pe.dwSize = ctypes.sizeof(pe)
    out: set[int] = set()
    try:
        if k32.Process32FirstW(snap, ctypes.byref(pe)):
            while True:
                if (pe.szExeFile or "").lower() == name.lower():
                    out.add(pe.th32ProcessID)
                if not k32.Process32NextW(snap, ctypes.byref(pe)):
                    break
    finally:
        k32.CloseHandle(snap)
    return out


def _token_left() -> float:
    _, _, exp = load_token()
    return (exp - int(time.time() * 1000)) / 1000


def warm_token() -> bool:
    """token 快过期时让客户端续期。返回 token 最终是否够用（>60s）。

    - 客户端本来就在跑：只等它自己刷新（不拉起、不关闭）
    - 客户端没跑：临时拉起 → 等续期 → 关掉本次拉起的实例
    """
    left = _token_left()
    if left > REFRESH_MARGIN_SEC:
        return True
    if not ALLOW_CLIENT_WARMUP:
        print(f"[warm] token 剩余 {left:.0f}s（预热已关闭）")
        return left > 60

    preexisting = bool(_proc_pids(APP_PROC))
    print(f"[warm] token 剩余 {left:.0f}s → "
          f"{'客户端已在运行，等它续期' if preexisting else '临时拉起客户端续期'}")

    if not preexisting:
        if not Path(APP_EXE).exists():
            print(f"[warm] 客户端不存在: {APP_EXE}")
            return left > 60
        try:
            subprocess.Popen([APP_EXE], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except Exception as e:  # noqa: BLE001
            print(f"[warm] 拉起失败: {e}")
            return left > 60

    _, _, rec0 = _find_record()
    gen0 = int(rec0.get("generation") or 0)
    exp0 = int(rec0.get("expiresAtMs") or 0)
    deadline = time.time() + WARMUP_TIMEOUT_SEC
    renewed = False
    while time.time() < deadline:
        time.sleep(5)
        _, _, rec = _find_record()
        if (int(rec.get("expiresAtMs") or 0) > exp0
                or int(rec.get("generation") or 0) > gen0):
            print(f"[warm] 客户端已续期 gen {gen0} -> {rec.get('generation')}")
            renewed = True
            break

    if not preexisting:
        subprocess.run(["taskkill", "/F", "/IM", APP_PROC, "/T"], capture_output=True)
        print("[warm] 已关闭本次拉起的客户端")
    elif not renewed:
        print("[warm] 等待超时：客户端未续期")

    left2 = _token_left()
    print(f"[warm] token 剩余 {left2 / 3600:.2f} 小时")
    return left2 > 60


def today_granted() -> int | None:
    """服务端今天这一格实际发放的积分（points + bonus_points），已签才有值。

    catalog 的 daily_amount 是常额（400），活动期服务端会翻倍
    （2026-10 国庆期：day3 = 800+400，day4 = 2000+1000），
    按常额入账会让账本比实际少一大截，所以以服务端为准。
    """
    code, body = call(STATUS_PATH)
    if code != 200:
        return None
    try:
        payload = json.loads(body)
    except Exception:  # noqa: BLE001
        return None
    data = payload.get("data") or payload
    today = next((d for d in (data.get("days") or []) if d.get("is_today")), None)
    if not today or today.get("status") != DAY_CLAIMED:
        return None
    return int(today.get("points") or 0) + int(today.get("bonus_points") or 0)


def cmd_auto() -> int:
    if not warm_token():
        print("[pending] token 已失效，且客户端续期未成功；请手动开一次客户端，或走 UI 路线")
        return 2
    code, body = call(STATUS_PATH)
    print(f"[status] HTTP {code}")
    print(mask(body))
    if code != 200:
        if code in (401, 403):
            print("[pending] token 已失效。为避免冲掉客户端登录态，脚本不自行刷新；"
                  "请让客户端跑一次（它会自己续期），或改走 UI 路线")
        else:
            print("[pending] 查询失败，未领取")
        return 2

    try:
        payload = json.loads(body)
    except Exception:  # noqa: BLE001
        payload = {}
    data = payload.get("data") or payload

    # 已签判定：今天那一格的状态是 Claimed(3)。这是权威来源——
    # 台账可能漏记（人工签到没入账），以服务端为准，不重复领取。
    days = data.get("days") or []
    today = next((d for d in days if d.get("is_today")), None)
    if today and today.get("status") == DAY_CLAIMED:
        print(f"[already] 今日已签到（服务端 day_no={today.get('day_no')} status=Claimed），不重复领取")
        # 已签也报实发额：补账/重跑时让 checkin.py 能按服务端口径入账
        got = int(today.get("points") or 0) + int(today.get("bonus_points") or 0)
        if got:
            print(f"[granted] {got}")
        return 0
    if data.get("claimed_today") is True or data.get("today_claimed") is True:
        print("[already] 今日已签到，不重复领取")
        return 0

    payload_body = {"timezone_id": TZ}
    c2, b2 = call(CLAIM_PATH, method="POST", body=payload_body)
    print(f"[claim] HTTP {c2}")
    print(mask(b2))
    if c2 == 200:
        b2j = {}
        try:
            b2j = json.loads(b2)
        except Exception:  # noqa: BLE001
            pass
        br = b2j.get("base_resp") or {}
        if br and br.get("status_code") not in (0, None):
            print(f"[pending] 领取被拒: {br.get('status_msg')}")
            return 2
        print("[ok] 签到成功")
        # 实发额由服务端说了算：checkin.py 读到 [granted] 就按它入账，
        # 忽略 catalog 的 daily_amount（活动期倍数会对不上）。
        got = today_granted()
        if got:
            print(f"[granted] {got}")
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
