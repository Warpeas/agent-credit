from __future__ import annotations

import ctypes
import json
import os
import subprocess
import time
from pathlib import Path
from typing import Any

from . import trace
from .apps import find_exe, launch
from .paths import LOG_DIR

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts" / "ui_claim.ps1"
SCRIPT_AUTOCLAW_OCR = ROOT / "scripts" / "ui_claim_autoclaw.ps1"
SCRIPT_MINIMAX_OCR = ROOT / "scripts" / "ui_claim_minimax.ps1"
SCRIPT_LOBSTERAI_OCR = ROOT / "scripts" / "ui_claim_lobsterai.ps1"
SCRIPT_TRAE_OCR = ROOT / "scripts" / "ui_claim_trae.ps1"
SCRIPT_QODERCN_OCR = ROOT / "scripts" / "ui_claim_qodercn.ps1"
TASK_TRAE_LAUNCHER = ROOT / "scripts" / "_task_trae.ps1"
# 2026-10-11：TRAE SOLO CN（Trae）已合并进 Trae CN，旧安装目录只剩 debug.log。
# 两个产品向来共用同一个积分账户，所以台账继续只用 `trae` 一条，不新增账户。
TRAE_PROCESS = "Trae CN"
# Qoder CN 的进程名/主窗口标题都是 "Qoder CN"（exe 名带空格）。
QODERCN_PROCESS = "Qoder CN"

PS = ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass"]

DEFAULT_CLICK = ("签到", "立即签到", "立即领取", "打卡")
DEFAULT_ALREADY = ("已签到", "今日已签", "已领取", "已打卡")
DEFAULT_SUCCESS = ("签到成功", "领取成功", "打卡成功", "连续签到")

# process substring, optional SendKeys
RECIPES: dict[str, dict[str, Any]] = {
    "workbuddy": {"process": ["WorkBuddy"], "sendkeys": ""},
    "minimax": {"process": ["MiniMax"], "sendkeys": "/checkin{ENTER}"},
    "trae": {"process": ["TRAE", "Trae"], "sendkeys": ""},
    "autoclaw": {"process": ["AutoClaw"], "sendkeys": ""},
    "lobsterai": {"process": ["LobsterAI", "Lobster"], "sendkeys": ""},
}


def skip_ui() -> bool:
    return os.environ.get("AGENT_CREDIT_SKIP_UI", "").strip() in ("1", "true", "yes")


# 提权跑的 ps1 由 UAC 另起一个窗口，它的 stdout 我们拿不到，只能读它自己写的日志。
# 文件名与各脚本里的 $logPath 对应（见各 ps1 顶部的 Log 函数）。
_PS1_LOG_NAME = {
    "ui_claim_lobsterai": "_lobsterai_log.txt",
}


def _ps1_log(script: Path) -> Path:
    name = script.stem
    return LOG_DIR / _PS1_LOG_NAME.get(name, "ps1_%s.log" % name.replace("ui_claim_", "", 1))


def _read_payload(result_path: Path) -> dict[str, Any] | None:
    """结果文件可能正被写入（读到半个 JSON 是常态）——解析失败就当还没好。"""
    if not result_path.exists():
        return None
    try:
        payload = json.loads(result_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
    if isinstance(payload, dict) and payload.get("status"):
        return payload
    return None


def _wait_elevated(script: Path, result_path: Path, timeout: int) -> tuple[bool, str]:
    """UAC 提权后的等待：tail 日志 + 心跳，别让黑框干等没反馈。"""
    tailer = trace.LogTailer(_ps1_log(script), label=script.stem)
    got, payload = trace.wait_for(
        lambda: _read_payload(result_path), timeout=timeout, label=script.stem, tailer=tailer,
    )
    if not got:
        return False, f"提权签到超时（{timeout}s），请查看客户端窗口状态"
    status = str(payload.get("status") or "")
    detail = str(payload.get("detail") or status)
    return status in ("ok", "already"), detail


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
    trace.note("请求 UAC 提权运行 AutoClaw 签到脚本（超时 180s）")
    ret = ctypes.windll.shell32.ShellExecuteW(None, "runas", "powershell", args, None, 0)
    if ret <= 32:
        return False, "UAC 未确认，AutoClaw 自动签到需要提权才能点击（可手动签到后 record 入账）"
    trace.note("提权窗口已拉起，等待结果文件…")
    return _wait_elevated(SCRIPT_AUTOCLAW_OCR, result_path, 180)


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
    trace.note(f"请求 UAC 提权运行 {script.name}（超时 {timeout}s）")
    ret = ctypes.windll.shell32.ShellExecuteW(None, "runas", "powershell", args, None, 0)
    if ret <= 32:
        return False, "UAC 未确认：需要提权才能拉起客户端并点击（可手动签到后用 record 入账）"
    trace.note("提权窗口已拉起，等待结果文件…")
    return _wait_elevated(script, result_path, timeout)


def _claim_minimax() -> tuple[bool, str]:
    """MiniMax Code route: launch elevated, screenshot + OCR + OS-level click.

    The generic UIA route cannot touch it: InvokePattern.Invoke() is script-layer
    dispatch (isTrusted=false) and gets filtered by the frontend. This script uses
    SetCursorPos + mouse_event, which enters the OS input queue (isTrusted=true).

    Must run ELEVATED (see _run_elevated_ps1). The ps1 brings the window forward
    itself and waits for the cold-start render.
    """
    return _run_elevated_ps1(SCRIPT_MINIMAX_OCR, LOG_DIR / "minimax_claim.json")


def _read_result(result_path: Path) -> tuple[bool, str]:
    """Interpret the JSON the ps1 helpers write."""
    if not result_path.exists():
        return False, "签到脚本未产出结果文件"
    try:
        payload = json.loads(result_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return False, "签到结果文件无法解析"
    if not isinstance(payload, dict):
        return False, "签到结果格式异常"
    status = str(payload.get("status") or "")
    detail = str(payload.get("detail") or status)
    return status in ("ok", "already"), detail


def _run_ps1(script: Path, result_path: Path, timeout: int = 240,
             process_name: str = "", exe_path: str = "",
             extra_args: list[str] | None = None) -> tuple[bool, str]:
    """Run a claim ps1 at the CURRENT integrity level and read its JSON result.

    `process_name` is forwarded as -ProcessName; without it the script falls back
    to its own default, which is how a renamed client silently breaks the route.
    `extra_args` are appended verbatim (e.g. Trae's -CloseAfter).
    """
    if not script.is_file():
        return False, f"缺少 {script}"

    LOG_DIR.mkdir(parents=True, exist_ok=True)
    if result_path.exists():
        result_path.unlink()

    cmd = PS + ["-WindowStyle", "Hidden", "-File", str(script), "-OutFile", str(result_path)]
    if process_name:
        cmd += ["-ProcessName", process_name]
    if exe_path:
        cmd += ["-ExePath", exe_path]
    if extra_args:
        cmd += extra_args
    rc, _ = trace.stream(cmd, label=script.stem, timeout=timeout, cwd=str(ROOT))
    if rc is None:
        return False, f"签到脚本超时（{timeout}s）"
    if rc:
        # pending/notfound 也会用非 0 退出，最终以结果文件为准，这里只作提示
        trace.note(f"{script.name} 退出码 {rc}（以结果文件为准）", label=script.stem)
    return _read_result(result_path)


def _launch_via_limited_task(launcher: Path, timeout: int = 150,
                             process_name: str = "", exe_path: str = "") -> tuple[bool, str]:
    """Cold-start a GUI client through a RunLevel=Limited scheduled task.

    Every direct launch path fails here: os.startfile, ShellExecute and
    subprocess.Popen all report success while producing zero processes, because
    the caller runs inside Task Scheduler / an automation sandbox rather than the
    interactive desktop. A Limited + Interactive scheduled task does land in the
    real desktop session, and Limited means no UAC prompt.

    The launcher must NOT unregister the task afterwards — its lifetime is the
    client's lifetime. Verified 2026-10-08 and 2026-10-09.
    """
    if not launcher.is_file():
        return False, f"缺少 {launcher}"
    cmd = PS + ["-File", str(launcher), "-WaitReady"]
    if process_name:
        cmd += ["-ProcessName", process_name]
    if exe_path:
        cmd += ["-ExePath", exe_path]
    trace.note(f"冷启动客户端（计划任务方式，上限 {timeout}s）", label=launcher.stem)
    rc, out = trace.stream(cmd, label=launcher.stem, timeout=timeout, cwd=str(ROOT))
    out = out.strip()
    if rc is None:
        return False, f"拉起客户端超时（{timeout}s）"
    if rc != 0:
        return False, f"拉起客户端失败 rc={rc}: {out[:200]}"
    if "EXE MISSING" in out:
        return False, out[:200]
    return True, out[-200:]


def _claim_trae() -> tuple[bool, str]:
    """Trae route: cold-start via scheduled task, then click at medium integrity.

    Deliberately NOT elevated. The previous implementation used
    ShellExecute("runas"), but elevation does not help spawn a visible window —
    it still reported "no main window within 60s" every time the client was not
    already open, which is what broke the 2026-10-08 and 2026-10-09 check-ins.

    Both halves are medium integrity here, so UIPI does not block the synthetic
    clicks (it only gates LOW -> HIGH). Same reasoning as the other helpers, just
    without the UAC detour. Fixed 2026-10-09.

    2026-10-11: TRAE SOLO CN was merged into Trae CN, so both steps are now told
    the new process name explicitly instead of relying on their own defaults.
    """
    if not SCRIPT_TRAE_OCR.is_file():
        return False, f"缺少 {SCRIPT_TRAE_OCR}"

    # exe 由 Python 侧探好再显式传给 ps1：ps1 自己在计划任务上下文里推导会拿到
    # 空值（10-12 00:01 那轮就是这样 —— 客户端没拉起，白等 90s 后报 pending）。
    exe = find_exe("trae")
    exe_path = str(exe) if exe else ""
    ok, note = _launch_via_limited_task(TASK_TRAE_LAUNCHER,
                                        process_name=TRAE_PROCESS, exe_path=exe_path)
    if not ok:
        return False, note
    # 2026-10-14：客户端由计划任务在 ps1 之外冷启动时，ps1 自己的
    # $LaunchedByUs 检测会把它当成「用户预先开着」而拒绝关窗（凌晨签完窗口
    # 一直挂桌面的根因）。launcher 仅在 preexisting procs=0 时真正启动，
    # 此时显式传 -CloseAfter，让 ps1 结束时统一清理。
    cold_started = "preexisting procs=0" in note and "started " in note
    # 2026-10-29：启动闸门已经拿到主人授权（Y/超时）或明确无人值守，Python 侧
    # 不再等空闲；不传 -IdleWaitSec 0 的话 ps1 自己的 5 分钟空闲闸门会再等一遍，
    # 用户一直活跃时还会直接返回 pending，闸门等于白问。
    # 也不再传 -CloseAfter：领取成功后要先在同一个客户端里拉明细（见下），
    # 拉完再由 Python 关掉本次冷启动的实例。
    extra = ["-IdleWaitSec", "0"]
    ok, detail = _run_ps1(SCRIPT_TRAE_OCR, LOG_DIR / "trae_claim.json",
                          timeout=300, process_name=TRAE_PROCESS, exe_path=exe_path,
                          extra_args=extra)
    # 2026-10-29：合并「签到 + 积分明细」。以前每日链路签完要再开一次 IDE 窗
    # （Ctrl+Shift+N）才能拿到逐条过期，多一轮开关窗口、多一次前台争抢。
    # 现在领取成功后趁同一个客户端还在，直接把 IDE 窗开出来、等 dump、登记、关窗。
    # 失败只记一笔，不改领取结果；链路的 sync 兜底会再试。
    if ok:
        sync_ok, sync_detail = _sync_trae_credits()
        detail += ("；积分明细已拉取（随本次对账登记）" if sync_ok
                   else f"；积分明细未拉取（{sync_detail}）")
    if cold_started:
        try:
            subprocess.run(["taskkill", "/IM", TRAE_PROCESS + ".exe", "/F"],
                           capture_output=True, timeout=20)
            detail += "；已关闭本次启动的客户端"
        except (subprocess.SubprocessError, OSError):
            pass
    if not ok:
        return False, f"{detail}（启动日志: {note}）"
    return True, detail


def _sync_trae_credits() -> tuple[bool, str]:
    """在 Trae 已打开的前提下把积分明细拉新鲜（不写账），返回 (ok, 说明)。

    登记交给 checkin 末尾的 sync：那边用的是同一份内存账本，最后统一落盘；
    这里若另起 `credit.py sync`，写进去的条目会被随后的整体保存覆盖。
    """
    script = ROOT / "scripts" / "trae_credit_sync.ps1"
    if not script.is_file():
        return False, f"缺少 {script}"
    rc, out = trace.stream(PS + ["-File", str(script), "-NoRecord"],
                           label="trae_credit_sync", timeout=240)
    if rc is None:
        return False, "同步脚本超时（240s）"
    try:
        payload = json.loads(out.strip().splitlines()[-1])
    except (ValueError, IndexError):
        return False, "同步脚本没有返回结果"
    return bool(payload.get("ok")), str(payload.get("error") or payload.get("steps"))


class _LastInputInfo(ctypes.Structure):
    _fields_ = [("cbSize", ctypes.c_uint), ("dwTime", ctypes.c_uint)]


def _user_idle_seconds() -> float:
    """Seconds since the last keyboard/mouse input on this desktop."""
    info = _LastInputInfo()
    info.cbSize = ctypes.sizeof(_LastInputInfo)
    if not ctypes.windll.user32.GetLastInputInfo(ctypes.byref(info)):
        return 1e9
    tick = ctypes.windll.kernel32.GetTickCount() & 0xFFFFFFFF
    return ((tick - info.dwTime) & 0xFFFFFFFF) / 1000.0


def _wait_for_user_idle(timeout: int, threshold: int, label: str) -> bool:
    """Wait until the user has been idle for `threshold` seconds, at most `timeout`.

    2026-10-22: Qoder's off-screen check-in briefly brings the window back for a
    real SendInput click (the campaign webview ignores synthetic mouse messages).
    Moving it while the owner is actively using the machine is exactly the
    interference this gate exists to avoid. Timeout proceeds anyway -- a missed
    sign-in is worse than a short flash -- but the ps1 then uses minimal exposure.
    """
    idle = _user_idle_seconds()
    if idle >= threshold:
        return True
    trace.note(f"{label} 空闲闸门：用户活跃（空闲 {idle:.0f}s），最多等 {timeout}s")
    deadline = time.time() + timeout
    while time.time() < deadline:
        time.sleep(10)
        idle = _user_idle_seconds()
        if idle >= threshold:
            trace.note(f"{label} 空闲闸门：已空闲 {idle:.0f}s，继续")
            return True
    trace.note(f"{label} 空闲闸门：等待超时（{timeout}s），按最小暴露模式继续")
    return False


QODER_IDLE_WAIT_SEC = 300
QODER_IDLE_THRESHOLD_SEC = 60


def _claim_qodercn() -> tuple[bool, str]:
    """Qoder CN route: raise the client window, then click 「领取」 in the daily
    campaign webview (每日领 100 Credits).

    The claim lives in a server-delivered webview that UIA cannot see (main window
    exposes only ~13 UIA elements, none claim-related), so this is OCR + OS-level
    click -- same route shape as Trae. Deliberately NOT elevated: Qoder CN is a
    normal medium-integrity install, and the ps1 runs at the same integrity, so
    UIPI does not gate the synthetic clicks. No plaintext token lives under
    ~/.qoder-cn/.auth, so external direct-sign is off the table per SAFETY.md.
    """
    if not SCRIPT_QODERCN_OCR.is_file():
        return False, f"缺少 {SCRIPT_QODERCN_OCR}"

    exe = find_exe("qodercn")
    exe_path = str(exe) if exe else ""
    if exe is None:
        return False, "未找到 Qoder CN 客户端，请手动打开后签到"
    # 2026-10-22：先等用户空闲，再拉起/搬动 Qoder。窗口没开时这一步避免冷启动
    # 的窗口打断主人；已经在用时避免把窗口搬到屏外。ps1 侧还有一层兜底，
    # 但这里先等可以覆盖「冷启动」这一段，ps1 调用时传 -IdleWaitSec 0。
    # 2026-10-23：checkin 的 UI 共享闸门只等一次；它通过后这里不再重复等。
    if os.environ.get("AGENT_CREDIT_SHARED_IDLE_DONE", "").strip().lower() in ("1", "true", "yes"):
        trace.note("Qoder CN 空闲闸门：由 UI 共享闸门完成，跳过")
    else:
        _wait_for_user_idle(QODER_IDLE_WAIT_SEC, QODER_IDLE_THRESHOLD_SEC, "Qoder CN")
    # 客户端没在跑就先拉起（os.startfile 尽力而为；计划任务上下文里若起不来，
    # ps1 会以 notfound 退出，checkin 退化为 pending，不会误记账）。
    had_window = _has_main_window([QODERCN_PROCESS])
    launched_by_us = False
    if not had_window:
        try:
            launch("qodercn")
        except FileNotFoundError:
            return False, "未找到 Qoder CN 客户端，请手动打开后签到"
        launched_by_us = True
        # 2026-10-30：这里原来等 90s，ps1 里再等 90s，最坏 180s 白等（10-30 00:03
        # 那轮就是这么耗掉的）。Python 侧只等进程/窗口「起来」——30s 足够冷启动冒头，
        # 真正的等待交给 ps1 一次做完；心跳日志避免黑框看起来卡死。
        deadline = time.time() + 30
        next_beat = deadline - 10
        while time.time() < deadline:
            if _has_main_window([QODERCN_PROCESS]):
                trace.note("Qoder CN 主窗口已出现（Python 侧）")
                break
            if time.time() >= next_beat:
                trace.note("Qoder CN 等待主窗口 … 最多 30s")
                next_beat = time.time() + 10
            time.sleep(3)
    else:
        trace.note("Qoder CN 主窗口已在，跳过冷启动等待")

    # 2026-10-22 方案甲：窗口停屏外 + PrintWindow + BringBack 点击，链路比旧版长；
    # 空闲等待已在上面做过，ps1 不再等（-IdleWaitSec 0），超时放宽到 300s。
    # 2026-10-30：窗口已在时把 ps1 的等待降到 20s；本次冷启动才给满 90s。
    ok, detail = _run_ps1(SCRIPT_QODERCN_OCR, LOG_DIR / "qodercn_claim.json",
                          timeout=300, process_name=QODERCN_PROCESS, exe_path=exe_path,
                          extra_args=["-IdleWaitSec", "0",
                                      "-WindowWaitSec", "20" if had_window else "60"])
    # 2026-10-29：领取成功后趁窗口还开着，立刻点开一次「我的用量」，让客户端把当天
    # 用量写进自己的日志。以前这一步由每日链路单独再开一次 Qoder 来做（实测多花
    # 2–4 分钟：冷启动 + 120s 空闲闸门）。失败只记一笔，不改领取结果；链路兜底会再点。
    if ok:
        usage_ok, usage_detail = _run_ps1(
            SCRIPT_QODERCN_OCR, LOG_DIR / "qodercn_usage.json",
            timeout=150, process_name=QODERCN_PROCESS, exe_path=exe_path,
            extra_args=["-Usage", "-IdleWaitSec", "0", "-WindowWaitSec", "20"])
        detail += "；已点开「我的用量」" if usage_ok else f"；用量面板未打开（{usage_detail}）"
    # 本次冷启动的实例签成功就关掉（与 Trae/LobsterAI/MonkeyCode 一致）；
    # pending/failed 时保留窗口，方便主人接手手动点启动弹窗。
    if ok and launched_by_us:
        try:
            subprocess.run(["taskkill", "/IM", QODERCN_PROCESS + ".exe", "/F"],
                           capture_output=True, timeout=20)
            detail += "；已关闭本次启动的客户端"
        except (subprocess.SubprocessError, OSError):
            pass
    return ok, detail


def _claim_lobsterai() -> tuple[bool, str]:
    """LobsterAI route: elevate, wait for the AI engine to finish booting, then
    click the top-right daily-points card and the follow-up claim button."""
    return _run_elevated_ps1(SCRIPT_LOBSTERAI_OCR, LOG_DIR / "lobsterai_claim.json")


UI_ROUTE_IDS = ("autoclaw", "minimax", "lobsterai", "trae", "qodercn")


def has_ui_route(account_id: str) -> bool:
    """该账户是否有**可用的** UI 路径。

    checkin() 用它决定「外部命令失败后要不要回落到 UI」。没有这个判断时，
    一个声明了 `claim_mode: ui` 但其实没有 UI 配方的账户会白回落到一条死路，
    最终报出「无 UI 配方」，把外部命令**真实的**失败原因盖掉。
    2026-10-11 MonkeyCode 上午那轮就是这么被掩盖的——排查时白绕了一圈。
    """
    return account_id in UI_ROUTE_IDS or account_id in RECIPES


def claim(account_id: str) -> tuple[bool, str]:
    """Drive the installed desktop client. True only if UI reports claimed/already."""
    if account_id == "autoclaw":
        return _claim_autoclaw()
    if account_id == "minimax":
        return _claim_minimax()
    if account_id == "lobsterai":
        return _claim_lobsterai()
    if account_id == "trae":
        return _claim_trae()
    if account_id == "qodercn":
        return _claim_qodercn()
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

    rc, out = trace.stream(cmd, label="ui_claim", timeout=90)
    if rc is None:
        return False, "UI 签到超时"

    payload = _last_json(out)
    if not payload:
        err = out.strip()[-300:]
        return False, f"UI 脚本无结果 {err or rc}"

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
