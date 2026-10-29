"""只读扫描 Trae CN 客户端 bundle 里的积分相关 API 路径字符串（research/SAFETY.md 允许路线 2：让客户端自己说话）。

用法：python scripts/probe_trae_credit_api.py
输出：命中的唯一字符串列表 + 每条积分相关字符串的上下文片段。
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

PATH_RE = re.compile(r'["\'`][/][A-Za-z0-9_./?&=-]*credit[A-Za-z0-9_./?&=-]*["\'`]', re.I)
API_RE = re.compile(r'["\'`][/]trae[/]api[/][A-Za-z0-9_./?&=-]+["\'`]')
CTX_RE = re.compile(r"credit", re.I)


def main() -> int:
    only_ctx = "--ctx" in sys.argv
    for f in FILES:
        if not f.exists():
            print(f"!! missing {f}")
            continue
        s = io.open(f, encoding="utf-8", errors="replace").read()
        print(f"\n===== {f.name} ({len(s)//1024} KB) =====")
        hits = set(m.group(0).strip("\"'`") for m in PATH_RE.finditer(s))
        hits |= set(m.group(0).strip("\"'`") for m in API_RE.finditer(s))
        for x in sorted(hits):
            print("PATH:", x[:160])
        print(f"-- {len(hits)} unique path strings")
        if only_ctx:
            shown = 0
            for m in CTX_RE.finditer(s):
                frag = s[max(0, m.start() - 90): m.end() + 90]
                if any(k in frag.lower() for k in ("expire", "valid", "detail", "history", "record", "list", "balance", "remain", "total", "used", "ug/")):
                    frag = re.sub(r"\s+", " ", frag)
                    print("CTX:", frag)
                    shown += 1
                    if shown >= 60:
                        print("-- ctx capped at 60")
                        break
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
