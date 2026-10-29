"""读取三个目标命令的实现片段，确认返回结构（只读）。

用法：python scripts/probe_trae_cmd_impl.py
"""
import io
import re
from pathlib import Path

TARGETS = {
    Path(r"C:\Users\Hunter\AppData\Local\Programs\Trae CN\resources\app\out\vs\workbench\workbench.desktop.main.js"): [
        "icubeGetCreditsUsageInfo",
        "icubeGetEntitlementInfo",
        "icubeGetCheckinCreditsSnapshot",
    ],
    Path(r"C:\Users\Hunter\AppData\Local\Programs\Trae CN\resources\app\out\vs\workbench\workbench.desktop.main.solo-lite.js"): [
        "icubeGetEntitlementInfo",
        "icubeGetCheckinCreditsSnapshot",
        "icubeOpenUsageDetails",
    ],
}


def main() -> int:
    for f, kws in TARGETS.items():
        if not f.exists():
            continue
        s = io.open(f, encoding="utf-8", errors="replace").read()
        print(f"\n===== {f.name} =====")
        for kw in kws:
            start = 0
            shown = 0
            while shown < 2:
                i = s.find(kw, start)
                if i < 0:
                    if shown == 0:
                        print(f"  (miss {kw})")
                    break
                frag = re.sub(r"\s+", " ", s[max(0, i - 260): i + 420])
                print(f"\n>>> {kw} @{i}:")
                print("   ", frag)
                shown += 1
                start = i + 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
