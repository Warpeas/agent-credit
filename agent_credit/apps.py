from __future__ import annotations

import os
from pathlib import Path

_KNOWN_CLIENT_DIRS = ("WorkBuddy", "MiniMax Code", "TRAE SOLO CN", "Trae CN", "LobsterAI")


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
    "traework": [
        LOCAL_PROGRAMS / "TRAE SOLO CN" / "TRAE SOLO CN.exe",
        LOCAL_PROGRAMS / "Trae CN" / "Trae CN.exe",
    ],
    "lobsterai": [LOCAL_PROGRAMS / "LobsterAI" / "LobsterAI.exe"],
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
    os.startfile(str(exe))
    return exe
