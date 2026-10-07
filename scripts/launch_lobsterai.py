"""Phase 1 only: launch LobsterAI DETACHED (de-elevated via the running shell).

Run elevated ONCE (one UAC). The app then runs non-elevated as a child of
explorer, survives this script's exit, and every later recognize/claim/verify
run can be NON-elevated (no UAC). This fixes the observed problem where an app
launched by an elevated script died together with that script's process tree.

    python scripts/launch_lobsterai.py
"""
import os
import ctypes
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = str(ROOT / "scripts" / "launch_detached.ps1")
EXE = str(Path(os.environ["LOCALAPPDATA"]) / "Programs" / "LobsterAI" / "LobsterAI.exe")

cmd = '-NoProfile -ExecutionPolicy Bypass -File "' + SCRIPT + '" -Exe "' + EXE + '"'
ret = ctypes.windll.shell32.ShellExecuteW(None, "runas", "powershell", cmd, None, 0)
print("ShellExecuteW ret:", ret)
raise SystemExit(0 if ret > 32 else 1)
