"""第三轮：挖 ide_user_ent_usage 响应的字段结构（packs / credits / expire）。

用法：python scripts/probe_trae_ent_struct.py
"""
import io
import re
from pathlib import Path

F = Path(r"C:\Users\Hunter\AppData\Local\Programs\Trae CN\resources\app\out\vs\workbench\workbench.desktop.main.solo-lite.js")


def show(s: str, kw: str, before: int, after: int, n: int = 2):
    start = 0
    for k in range(n):
        i = s.find(kw, start)
        if i < 0:
            if k == 0:
                print(f"   (miss {kw!r})")
            return
        frag = s[max(0, i - before): i + after]
        frag = re.sub(r"\s+", " ", frag)
        print(f"\n>>> {kw!r} @{i}:")
        print("   ", frag)
        start = i + 1


def main() -> int:
    s = io.open(F, encoding="utf-8", errors="replace").read()
    print(f"{F.name} {len(s)//1024} KB")
    # pack 映射器：zOn 定义（由上一轮的 zOn(a,l) 调用点找定义）
    show(s, "zOn=", 60, 900)
    show(s, "function zOn", 0, 900)
    # credits usage 更新器
    show(s, "_updateCreditsUsage(t)", 200, 200, 1)
    show(s, "_updateCreditsUsage(e)", 200, 200, 1)
    show(s, "_updateCreditsUsage(", 80, 700, 3)
    # 原始响应字段
    for kw in ("credits_usage", "credit_usage", "bonus_usage", "total_credits", "remain_credits", "credits_limit", "entitlement_briefs", "display_desc", "expire_time"):
        show(s, kw, 120, 220, 2)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
