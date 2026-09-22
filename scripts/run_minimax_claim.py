import ctypes
import json
import time
from pathlib import Path

ROOT = Path(r"C:\Users\Hunter\Documents\Warpeas\agent-credit")
result = ROOT / "logs" / "minimax_claim.json"
if result.exists():
    result.unlink()

script = ROOT / "scripts" / "ui_claim_minimax.ps1"
cmd = '-NoProfile -ExecutionPolicy Bypass -File "' + str(script) + '" -OutFile "' + str(result) + '"'
ret = ctypes.windll.shell32.ShellExecuteW(None, "open", "powershell", cmd, None, 0)
print("ShellExecuteW ret:", ret)
if ret <= 32:
    print("launch failed")
    raise SystemExit(1)

deadline = time.time() + 150
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
