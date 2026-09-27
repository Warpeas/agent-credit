"""Run a .ps1 ELEVATED via UAC (ShellExecuteW "runas") and wait a bit.

Usage: python scripts/_elevate_run.py scripts/register-daily-task.ps1
"""
import ctypes
import sys
from pathlib import Path

ps1 = Path(sys.argv[1]).resolve()
if not ps1.is_file():
    print("missing:", ps1)
    raise SystemExit(1)

extra = " ".join(sys.argv[2:])
cmd = '-NoProfile -ExecutionPolicy Bypass -File "' + str(ps1) + '"'
if extra:
    cmd += " " + extra
ret = ctypes.windll.shell32.ShellExecuteW(None, "runas", "powershell", cmd, None, 0)
print("ShellExecuteW ret:", ret)
raise SystemExit(0 if ret > 32 else 1)
