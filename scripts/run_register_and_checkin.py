import ctypes
import json
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
result = ROOT / "logs" / "autoclaw_claim.json"
if result.exists():
    result.unlink()

args = (
    "-NoProfile -ExecutionPolicy Bypass -File \""
    + str(ROOT / "scripts" / "register_and_checkin.ps1") + "\""
)
ret = ctypes.windll.shell32.ShellExecuteW(None, "runas", "powershell", args, None, 0)
print("ShellExecuteW ret:", ret)
if ret <= 32:
    print("UAC declined/failed")
    raise SystemExit(1)

deadline = time.time() + 180
payload = None
while time.time() < deadline:
    if result.exists():
        try:
            payload = json.loads(result.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            payload = None
        if isinstance(payload, dict) and payload.get("status"):
            break
    time.sleep(2)

print("claim result:", json.dumps(payload, ensure_ascii=False) if payload else "TIMEOUT")
