from __future__ import annotations

import ctypes
import json
import os
import subprocess
import time
from pathlib import Path
from typing import Any

from .apps import find_exe, launch
from .paths import LOG_DIR

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts" / "ui_claim.ps1"
SCRIPT_AUTOCLAW_OCR = ROOT / "scripts" / "ui_claim_autoclaw.ps1"
SCRIPT_MINIMAX_OCR = ROOT / "scripts" / "ui_claim_minimax.ps1"
SCRIPT_LOBSTERAI_OCR = ROOT / "scripts" / "ui_claim_lobsterai.ps1"
SCRIPT_TRAEWORK_OCR = ROOT / "scripts" / "ui_claim_traework.ps1"

DEFAULT_CLICK = ("签到", "立即签到", "立即领取", "打卡")
DEFAULT_ALREADY = ("已签到", "今日已签", "已领取", "已打卡")
DEFAULT_SUCCESS = ("签到成功", "领取成功", "打卡成功", "连续签到")

# process substring, optional SendKeys
RECIPES: dict[str, dict[str, Any]] = {
    "workbuddy": {"process": ["WorkBuddy"], "sendkeys": ""},
    "minimax": {"process": ["MiniMax"], "sendkeys": "/checkin{ENTER}"},
    "traework": {"process": ["TRAE", "Trae"], "sendkeys": ""},
    "autoclaw": {"process": ["AutoClaw"], "sendkeys": ""},
    "lobsterai": {"process": ["LobsterAI", "Lobster"], "sendkeys": ""},
}


def skip_ui() -> bool:
    return os.environ.get("AGENT_CREDIT_SKIP_UI", "").strip() in ("1", "true", "yes")


def _claim_autoclaw() -> tuple[bool, str]:
    """AutoClaw route: screenshot+OCR+click, run ELEVATED.

    Its CEF a11y tree is disabled (no UIA), and simulated clicks are blocked by
    UIPI unless elevated. So we launch an elevated helper via UAC and read the
    JSON result file it writes.
    """
    if not SCRIPT_AUTOCLAW_OCR.is_file():
        return False, f"缺少 {SCRIPT_AUTOCLAW_OCR}"
    if find_exe("autoclaw") is None:
        return False, "未找到客户端，请手动打开后签到"

    LOG_DIR.mkdir(parents=True, exist_ok=True)
    result_path = LOG_DIR / "autoclaw_claim.json"
    if result_path.exists():
        result_path.unlink()

    args = (
        "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File \""
        + str(SCRIPT_AUTOCLAW_OCR) + "\" -OutFile \"" + str(result_path) + "\""
    )
    ret = ctypes.windll.shell32.ShellExecuteW(None, "runas", "powershell", args, None, 0)
    if ret <= 32:
        return False, "UAC 未确认，AutoClaw 自动签到需要提权才能点击（可手动签到后 record 入账）"

    deadline = time.time() + 180
    while time.time() < deadline:
        if result_path.exists():
            try:
                payload = json.loads(result_path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                payload = None
            if isinstance(payload, dict) and payload.get("status"):
                status = str(payload.get("status") or "")
                detail = str(payload.get("detail") or status)
                if status in ("ok", "already"):
                    return True, detail
                return False, detail
        time.sleep(2)
    return False, "提权签到超时（180s），请查看客户端窗口状态"


def _run_elevated_ps1(script: Path, result_path: Path, timeout: int = 240) -> tuple[bool, str]:
    """Run a claim ps1 ELEVATED via UAC and read the JSON result it writes.

    Elevation is mandatory in this environment: a non-elevated launch from the
    automation session cannot start the GUI client at all (no process appears),
    and UIPI blocks non-elevated input into an elevated window. Verified 2026-09-27
    for MiniMax ("今日已签到") and LobsterAI.
    """
    if not script.is_file():
        return False, f"缺少 {script}"

    LOG_DIR.mkdir(parents=True, exist_ok=True)
    if result_path.exists():
        result_path.unlink()

    args = (
        "-NoProfile -ExecutionPolicy Bypass -File \""
        + str(script) + "\" -OutFile \"" + str(result_path) + "\""
    )
    ret = ctypes.windll.shell32.ShellExecuteW(None, "runas", "powershell", args, None, 0)
    if ret <= 32:
        return False, "UAC 未确认：需要提权才能拉起客户端并点击（可手动签到后用 record 入账）"

    deadline = time.time() + timeout
    while time.time() < deadline:
        if result_path.exists():
            try:
                payload = json.loads(result_path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                payload = None
            if isinstance(payload, dict) and payload.get("status"):
                status = str(payload.get("status") or "")
                detail = str(payload.get("detail") or status)
                if status in ("ok", "already"):
                    return True, detail
                return False, detail
        time.sleep(2)
    return False, f"提权签到超时（{timeout}s），请查看客户端窗口状态"


def _claim_minimax() -> tuple[bool, str]:
    """MiniMax Code route: launch elevated, screenshot + OCR + OS-level click.

    The generic UIA route cannot touch it: InvokePattern.Invoke() is script-layer
    dispatch (isTrusted=false) and gets filtered by the frontend. This script uses
    SetCursorPos + mouse_event, which enters the OS input queue (isTrusted=true).

    Must run ELEVATED (see _run_elevated_ps1). The ps1 brings the window forward
    itself and waits for the cold-start render.
    """
    return _run_elevated_ps1(SCRIPT_MINIMAX_OCR, LOG_DIR / "minimax_claim.json")


def _claim_traework() -> tuple[bool, str]:
    """TraeWork route: elevated screenshot+OCR+click.

    Uses its own dedicated ps1 (not the generic recipe) because the button text
    is non-obvious and the menu is a toggle. Needs elevation: a non-elevated
    launch cannot cold-start the client in this environment.
    """
    return _run_elevated_ps1(SCRIPT_TRAEWORK_OCR, LOG_DIR / "traework_claim.json")


def _claim_lobsterai() -> tuple[bool, str]:
    """LobsterAI route: elevate, wait for the AI engine to finish booting, then
    click the top-right daily-points card and the follow-up claim button."""
    return _run_elevated_ps1(SCRIPT_LOBSTERAI_OCR, LOG_DIR / "lobsterai_claim.json")


def claim(account_id: str) -> tuple[bool, str]:
    """Drive the installed desktop client. True only if UI reports claimed/already."""
    if account_id == "autoclaw":
        return _claim_autoclaw()
    if account_id == "minimax":
        return _claim_minimax()
    if account_id == "lobsterai":
        return _claim_lobsterai()
    if account_id == "traework":
        return _claim_traework()
    recipe = RECIPES.get(account_id)
    if recipe is None:
        return False, "无 UI 配方"
    exe = find_exe(account_id)
    if exe is None:
        return False, "未找到客户端，请手动打开后签到"
    if not SCRIPT.is_file():
        return False, f"缺少 {SCRIPT}"

    launched = False
    if not _has_main_window(recipe["process"]):
        launch(account_id)
        launched = True
        time.sleep(2)

    cmd = [
        "powershell",
        "-NoProfile",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        str(SCRIPT),
        "-ProcessMatch",
        "|".join(recipe["process"]),
        "-ClickName",
        "|".join(DEFAULT_CLICK),
        "-AlreadyName",
        "|".join(DEFAULT_ALREADY),
        "-SuccessName",
        "|".join(DEFAULT_SUCCESS),
        "-WaitSeconds",
        "45",
    ]
    sendkeys = (recipe.get("sendkeys") or "").strip()
    if sendkeys:
        cmd.extend(["-SendKeys", sendkeys])

    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=90,
            encoding="utf-8",
            errors="replace",
        )
    except subprocess.TimeoutExpired:
        return False, "UI 签到超时"

    payload = _last_json(proc.stdout)
    if not payload:
        err = (proc.stderr or proc.stdout or "").strip()[:300]
        return False, f"UI 脚本无结果 {err or proc.returncode}"

    status = str(payload.get("status") or "")
    detail = str(payload.get("detail") or status)
    if launched:
        detail = f"已启动客户端；{detail}"
    if status in ("ok", "already"):
        return True, detail
    return False, detail


def _has_main_window(process_names: list[str]) -> bool:
    """True if any matching process currently owns a visible main window.

    Background survivors (e.g. after clicking X on a tray-style app) must NOT
    count as running, or we would never relaunch to get a window back.
    """
    for name in process_names:
        try:
            out = subprocess.check_output(
                [
                    "powershell",
                    "-NoProfile",
                    "-Command",
                    "(Get-Process -Name '" + name + "*' -ErrorAction SilentlyContinue | "
                    "Where-Object { $_.MainWindowHandle -ne 0 } | Measure-Object).Count",
                ],
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=15,
            )
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired, FileNotFoundError, ValueError):
            continue
        try:
            if int((out or "0").strip() or "0") > 0:
                return True
        except ValueError:
            continue
    return False


def _last_json(stdout: str) -> dict[str, Any] | None:
    for line in reversed((stdout or "").splitlines()):
        line = line.strip()
        if line.startswith("{") and line.endswith("}"):
            try:
                data = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(data, dict):
                return data
    return None
