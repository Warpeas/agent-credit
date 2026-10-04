"""提权运行 scripts/ui_claim_traework.ps1，并把结果 JSON 读回来。

为什么必须提权：TraeWork 是提权运行的客户端，未提权进程注入的鼠标事件会被 UIPI 丢弃
（表现：坐标对、窗口在前台，但点了没反应）。ShellExecuteW + "runas" 会弹一次 UAC。

前提：**TraeWork 客户端必须已经打开**——本环境冷启动它必失败（进程起不来），
脚本找不到窗口时会返回 pending 并提示手动打开。

用法：
    python scripts/run_traework_claim.py --explore    # 只抓布局，不点击
    python scripts/run_traework_claim.py --dry-run    # 定位但不点签到
    python scripts/run_traework_claim.py              # 真签到
"""
import argparse
import ctypes
import json
import time
from pathlib import Path

ROOT = Path(r"C:\Users\Hunter\Documents\Warpeas\agent-credit")
SCRIPT = ROOT / "scripts" / "ui_claim_traework.ps1"


def main() -> int:
    ap = argparse.ArgumentParser(description="提权运行 TraeWork 签到脚本（会弹一次 UAC）")
    ap.add_argument("--dry-run", action="store_true", help="只定位，不点签到按钮")
    ap.add_argument("--explore", action="store_true", help="只抓 OCR 布局，不做任何点击")
    ap.add_argument("--process-name", default="TRAE SOLO CN", help="客户端进程名（TraeCode 用 'Trae CN'）")
    ap.add_argument("--shots", action="store_true", help="关键步骤截图到 logs\\shots_trae（排查 UI 时很有用）")
    ap.add_argument("--extra", default="", help="原样透传给 ps1 的额外参数")
    args = ap.parse_args()

    result = ROOT / "logs" / "traework_claim.json"
    if result.exists():
        result.unlink()

    ps_args: list[str] = []
    if args.dry_run:
        ps_args.append("-DryRun")
    if args.explore:
        ps_args.append("-Explore")
    ps_args.append(f'-ProcessName "{args.process_name}"')
    if args.extra:
        ps_args.append(args.extra)
    if args.shots:
        ps_args.append('-ShotDir "' + str(ROOT / "logs" / "shots_trae") + '"')
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
