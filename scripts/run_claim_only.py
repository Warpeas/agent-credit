"""提权运行 scripts/ui_claim_autoclaw.ps1，并把结果 JSON 读回来。

为什么必须提权：AutoClaw 以较高完整性级别运行，未提权进程通过 mouse_event 注入的
输入会被 UIPI 丢弃（表现是「坐标对、窗口也在前台，但点了没反应」）。
ShellExecuteW + "runas" 会弹一次 UAC，确认后脚本才真正有注入权限。

用法：
    python scripts/run_claim_only.py                 # 真签到
    python scripts/run_claim_only.py --dry-run       # 只定位，不点签到按钮
"""
import argparse
import ctypes
import json
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts" / "ui_claim_autoclaw.ps1"


def main() -> int:
    ap = argparse.ArgumentParser(description="提权运行 AutoClaw 签到脚本（会弹一次 UAC）")
    ap.add_argument("--dry-run", action="store_true", help="传 -DryRun：只定位，不点签到按钮")
    ap.add_argument("--extra", default="", help="原样透传给 ps1 的额外参数")
    args = ap.parse_args()

    result = ROOT / "logs" / "autoclaw_claim.json"
    if result.exists():
        result.unlink()

    ps_args: list[str] = []
    if args.dry_run:
        ps_args.append("-DryRun")
    if args.extra:
        ps_args.append(args.extra)
    ps_args.append(f'-OutFile "{result}"')

    cmd = (
        "-NoProfile -ExecutionPolicy Bypass -File \"" + str(SCRIPT) + "\" "
        + " ".join(ps_args)
    )
    ret = ctypes.windll.shell32.ShellExecuteW(None, "runas", "powershell", cmd, None, 0)
    print("ShellExecuteW ret:", ret)
    if ret <= 32:
        print("UAC declined/failed")
        return 1

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
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
