"""枚举 Trae bundle 里注册的全部 icube.* 命令与 credits 相关事件名（只读）。

用法：python scripts/probe_trae_commands.py
"""
import io
import re
from pathlib import Path

FILES = [
    Path(r"C:\Users\Hunter\AppData\Local\Programs\Trae CN\resources\app\out\vs\workbench\workbench.desktop.main.solo-lite.js"),
    Path(r"C:\Users\Hunter\AppData\Local\Programs\Trae CN\resources\app\out\vs\workbench\workbench.desktop.main.js"),
]


def main() -> int:
    for f in FILES:
        if not f.exists():
            continue
        s = io.open(f, encoding="utf-8", errors="replace").read()
        print(f"\n===== {f.name} =====")
        cmds = set(re.findall(r'registerCommand\("([a-zA-Z0-9._-]+)"', s))
        for c in sorted(cmds):
            if "icube" in c or "credit" in c.lower() or "usage" in c.lower() or "commercial" in c.lower():
                print("CMD:", c)
        evs = set(re.findall(r'dispatchEvent\(new\s+\w+\("([a-zA-Z0-9._:-]+)"', s))
        evs |= set(re.findall(r'new\s+CustomEvent\("([a-zA-Z0-9._:-]+)"', s))
        for e in sorted(evs):
            if "credit" in e.lower() or "usage" in e.lower() or "icube" in e.lower():
                print("EVT:", e)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
