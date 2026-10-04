"""提权运行 scripts/ui_claim_lobsterai.ps1（会弹一次 UAC）。
为什么必须 runas：本自动化会话非提权拉不起 GUI 客户端，与 MiniMax/AutoClaw/TraeWork 同套路。
用法：
    python scripts/run_lobsterai_claim.py --explore   # 只抓布局，不点击
    python scripts/run_lobsterai_claim.py             # 真签到
"""
import argparse
import ctypes
import json
import time
from pathlib import Path

ROOT = Path(r"C:\Users\Hunter\Documents\Warpeas\agent-credit")
SCRIPT = ROOT / "scripts" / "ui_claim_lobsterai.ps1"


def main() -> int:
    ap = argparse.ArgumentParser(description="提权运行 LobsterAI 签到脚本（会弹一次 UAC）")
    ap.add_argument("--explore", action="store_true", help="只抓 OCR 布局，不做任何点击")
    ap.add_argument("--verify", action="store_true", help="点左下角用户栏，读当天签到状态（不改任何东西）")
    ap.add_argument("--elevate", action="store_true",
                    help="提权运行（默认不提权：app 应已由 launch_lobsterai.py 以普通权限常驻）")
    ap.add_argument("--out", default="", help="结果 JSON 输出路径（实签用）")
    args = ap.parse_args()

    result = ROOT / "logs" / "lobsterai_claim.json"
    if result.exists():
        result.unlink()

    ps_args = []
    if args.explore:
        ps_args.append("-Explore")
    if args.verify:
        ps_args.append("-Verify")
    if not args.elevate:
        # 非提权跑时绝不能尝试拉起 app（必然失败），直接快速 notfound
        ps_args.append("-NoLaunch")
    if args.out:
        ps_args.append(f'-OutFile "{args.out}"')
    else:
        ps_args.append(f'-OutFile "{result}"')
    cmd = (
        "-NoProfile -ExecutionPolicy Bypass -File \"" + str(SCRIPT) + "\" "
        + " ".join(ps_args)
    )
    verb = "runas" if args.elevate else "open"
    ret = ctypes.windll.shell32.ShellExecuteW(None, verb, "powershell", cmd, None, 0)
    print("ShellExecuteW ret:", ret)
    if ret <= 32:
        print("UAC declined/failed" if args.elevate else "launch failed")
        return 1

    deadline = time.time() + 300
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
