from __future__ import annotations
import os
import subprocess
from pathlib import Path

_KNOWN_CLIENT_DIRS = ("WorkBuddy", "MiniMax Code", "TRAE SOLO CN", "Trae CN", "LobsterAI", "Qoder CN")


def _looks_real(programs_dir: Path) -> bool:
    """A Programs dir is 'real' if it contains one of the known client folders."""
    return any((programs_dir / d).is_dir() for d in _KNOWN_CLIENT_DIRS)


def _detect_local_programs() -> Path:
    """Find the real per-user Programs dir.

    Environment variables (LOCALAPPDATA/USERPROFILE) may point into an agent
    sandbox, so verify candidates contain known clients, then fall back to
    enumerating C:\\Users\\*. AGENT_CREDIT_LOCALAPPDATA wins if set explicitly.
    """
    candidates: list[Path] = []
    explicit = os.environ.get("AGENT_CREDIT_LOCALAPPDATA")
    if explicit:
        candidates.append(Path(explicit) / "Programs")
    for var in ("USERPROFILE", "HOME"):
        base = os.environ.get(var)
        if base:
            candidates.append(Path(base) / "AppData" / "Local" / "Programs")
    la = os.environ.get("LOCALAPPDATA")
    if la:
        candidates.append(Path(la) / "Programs")
    for c in candidates:
        if c.is_dir() and _looks_real(c):
            return c
    users_dir = Path(os.environ.get("SystemDrive", "C:") + "\\") / "Users"
    for user_dir in sorted(users_dir.glob("*")):
        c = user_dir / "AppData" / "Local" / "Programs"
        if c.is_dir() and _looks_real(c):
            return c
    for c in candidates:
        if c.is_dir():
            return c
    return candidates[-1] if candidates else Path.home() / "AppData" / "Local" / "Programs"


LOCAL_PROGRAMS = _detect_local_programs()

# First existing path wins. Daily-expire apps are listed for doctor only.
LAUNCH_CANDIDATES: dict[str, list[Path]] = {
    "workbuddy": [LOCAL_PROGRAMS / "WorkBuddy" / "WorkBuddy.exe"],
    "minimax": [LOCAL_PROGRAMS / "MiniMax Code" / "MiniMax Code.exe"],
    "trae": [
        # 2026-10-11: TRAE SOLO CN 已并入 Trae CN，旧目录只剩 debug.log。
        # 活的那个排前面，「first existing wins」才不会白 stat 一条死路径。
        LOCAL_PROGRAMS / "Trae CN" / "Trae CN.exe",
        LOCAL_PROGRAMS / "TRAE SOLO CN" / "TRAE SOLO CN.exe",
    ],
    "lobsterai": [LOCAL_PROGRAMS / "LobsterAI" / "LobsterAI.exe"],
    # Qoder CN：exe 名带空格，进程名与目录名同为 "Qoder CN"。
    # 2026-11-17：Qoder 经 Launcher 自动更新（11/16 00:15，Launcher.exe 时间戳
    # 实锤）后主程序数据库升到 schema 85，旧版 Programs\Qoder CN\Qoder CN.exe
    # （0.1.3/schema64）从此打不开库——FutureDatabaseVersionError 错误页（
    # 20261117-091507/20261118-101019/20261118-191203 三份证据截图）。开始菜单
    # 快捷方式指向 Launcher（AppData\Local\Qoder CN\ 下，不在 Programs 里）。
    # Launcher 路径排前 first-wins，旧版留作兜底。
    "qodercn": [
        Path(LOCAL_PROGRAMS).parent / "Qoder CN" / "Qoder CN Launcher" / "Qoder CN Launcher.exe",
        LOCAL_PROGRAMS / "Qoder CN" / "Qoder CN.exe",
    ],
    "dumate": [LOCAL_PROGRAMS / "DuMate" / "DuMate.exe"],
    "joycode": [LOCAL_PROGRAMS / "JoyCode" / "JoyCode.exe"],
    "kimi": [LOCAL_PROGRAMS / "Kimi" / "Kimi.exe"],
    "accio": [LOCAL_PROGRAMS / "Accio" / "Accio.exe"],
    "coze": [LOCAL_PROGRAMS / "Coze" / "Coze.exe"],
    "qwenwork": [
        LOCAL_PROGRAMS / "QwenWorkCN" / "Launcher.exe",
        LOCAL_PROGRAMS / "QwenWorkCN" / "QwenWorkCN.exe",
    ],
    "autoclaw": [
        Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "AutoClaw" / "AutoClaw.exe",
        LOCAL_PROGRAMS / "AutoClaw" / "AutoClaw.exe",
        LOCAL_PROGRAMS / "智谱AutoClaw" / "AutoClaw.exe",
    ],
    "todesk": [
        Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "ToDesk AI" / "ToDeskAI.exe",
        LOCAL_PROGRAMS / "ToDesk" / "ToDesk.exe",
        Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "ToDesk" / "ToDesk.exe",
    ],
    "qclaw": [
        # Installed under a versioned folder, e.g. QClaw\v0.2.37.630\QClaw.exe
        Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "QClaw" / "*" / "QClaw.exe",
    ],
    "xiaohuanxiong": [
        Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "raccoon-ai" / "商汤小浣熊.exe",
    ],
    # MonkeyCode 是 per-user Tauri 安装，不在 Programs 目录；2026-11-29 复核
    # 注册表 InstallLocation 与 exe 均确认存在，别再误报「本机未装」。
    "monkeycode_credit": [
        Path(LOCAL_PROGRAMS).parent / "MonkeyCode" / "monkeycode-desktop.exe",
    ],
}


def find_exe(account_id: str) -> Path | None:
    for path in LAUNCH_CANDIDATES.get(account_id) or []:
        if any(ch in path.parts for ch in ("*", "?")):
            anchor = Path(path.drive + path.root)
            matches = sorted(anchor.glob(str(path.relative_to(anchor))))
            if matches:
                return matches[-1]  # pick the highest version
            continue
        if path.is_file():
            return path
    return None


def launch(account_id: str) -> Path:
    exe = find_exe(account_id)
    if exe is None:
        raise FileNotFoundError(f"未找到 {account_id} 的客户端，请手动打开或在 apps.py 补路径")
    if account_id == "qodercn":
        # 2026-11-17：计划任务（HighestAvailable）拉起的客户端继承 High 完整性
        # 令牌，Qoder 在 High 下数据库初始化失败（「本地数据库无法打开」错误页，
        # 11/17-11/18 四轮全复现，20261118-101019 等证据截图在案）；主人 Medium
        # 手动开一直正常。explorer 代理启动可把完整性降到 Medium（explorer 自身
        # Medium，派生子进程继承），等效于开始菜单启动。仅限 qodercn——其他客户
        # 端（LobsterAI/Trae/AutoClaw）在 High 下实测正常。
        subprocess.Popen(["explorer.exe", str(exe)])
    else:
        os.startfile(str(exe))
    return exe
