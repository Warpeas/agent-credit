"""第二轮：在 Trae bundle 里按关键词挖积分明细/有效期相关片段（只读）。

用法：python scripts/probe_trae_credit_kw.py [关键词 ...]
默认关键词覆盖明细/过期/余额口径。输出做去重 + 限量。
"""
import io
import re
import sys
from pathlib import Path

OUT_DIR = Path(r"C:\Users\Hunter\AppData\Local\Programs\Trae CN\resources\app\out")
FILES = [
    OUT_DIR / "main.js",
    OUT_DIR / "vs" / "workbench" / "workbench.desktop.main.js",
    OUT_DIR / "vs" / "workbench" / "workbench.desktop.main.solo-lite.js",
]

DEFAULT_KW = [
    "creditDetail", "credit_detail", "creditRecord", "credit_record",
    "creditList", "creditHistory", "creditsDetail",
    "expireTime", "expireAt", "expire_at", "expiredAt", "validUntil", "valid_until",
    "remainingCredits", "creditBalance", "totalCredits", "usedCredits",
    "ide_user_ent_usage", "EntUsage", "entUsage",
    "积分明细", "积分记录", "过期", "到期", "有效期",
]


def main() -> int:
    kws = sys.argv[1:] or DEFAULT_KW
    for f in FILES:
        if not f.exists():
            continue
        s = io.open(f, encoding="utf-8", errors="replace").read()
        print(f"\n===== {f.name} =====")
        for kw in kws:
            idxs = []
            start = 0
            while True:
                i = s.find(kw, start)
                if i < 0:
                    break
                idxs.append(i)
                start = i + 1
                if len(idxs) >= 6:
                    break
            if not idxs:
                continue
            print(f"\n-- KW {kw!r} x{len(idxs)}{'+' if len(idxs)>=6 else ''}")
            for i in idxs[:3]:
                frag = s[max(0, i - 160): i + 200]
                frag = re.sub(r"\s+", " ", frag)
                print("   ...", frag, "...")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
