import ctypes
import json
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
result = ROOT / "logs" / "minimax_claim.json"
if result.exists():
    result.unlink()

script = ROOT / "scripts" / "ui_claim_minimax.ps1"
cmd = '-NoProfile -ExecutionPolicy Bypass -File "' + str(script) + '" -OutFile "' + str(result) + '"'
# 必须提权（"runas"）：本环境非提权的 GUI 启动从自动化会话根本起不来（进程不出现），
# 只有提权（UAC）启动才会落到交互桌面并存活——与 TraeWork/AutoClaw 同一套路。
# 此前「runas 会瞬间自退」是沙箱内的假象，沙箱外 runas 完全正常（实测进程稳定存活）。
ret = ctypes.windll.shell32.ShellExecuteW(None, "runas", "powershell", cmd, None, 0)
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
