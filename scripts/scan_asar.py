#!/usr/bin/env python3
"""扫一个 Electron 客户端的 app.asar，找出签到 / 积分相关的字面量。

用途：判断某家能不能走 external 直签（端点 + 鉴权 + host 都要能从这里挖出来）。
接口路径是字符串常量，混淆不掉，二进制直接搜就行。

用法：
    python scripts/scan_asar.py <app.asar 路径> [额外正则...]

输出：每个关键词的命中数与上下文片段；长串（token / APP_KEY 之类）一律 <redacted>。
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

DEFAULT_PATTERNS = [
    r"signin", r"sign_in", r"checkin", r"check-in", r"check_in",
    r"daily-?sign", r"dailySign", r"daily_signin",
    r"claim", r"reward", r"points", r"credit", r"quota", r"wallet",
    r"/api/v\d+/[a-z0-9_\-/]*sign[a-z0-9_\-/]*",
    r"/api/v\d+/[a-z0-9_\-/]*(checkin|reward|points|wallet)[a-z0-9_\-/]*",
]
CN_PATTERNS = [r"签到", r"积分", r"领取", r"已签", r"连续", r"奖励"]

MASK = re.compile(r"[A-Za-z0-9+/=_-]{24,}")
# 接口路径（/api/v1/credits/claim 之类）不是凭据，别把它整条吃掉：
# 先按路径分隔符切碎，只有切完仍 >=24 的单段才 mask。
SPLIT = re.compile(r"[/.:?&=]")


def mask(text: str) -> str:
    def repl(m: re.Match[str]) -> str:
        seg = m.group(0)
        parts = SPLIT.split(seg)
        longest = max(parts, key=len)
        if len(longest) < 24:
            return seg
        return seg.replace(longest, "<redacted>")

    return MASK.sub(repl, text)


def main() -> int:
    args = sys.argv[1:]
    if not args:
        print(__doc__)
        return 1
    target = Path(args[0])
    extra = [a for a in args[1:] if a != "--only"]
    only = "--only" in args
    if not target.exists():
        print(f"not found: {target}")
        return 1

    data = target.read_bytes()
    print(f"file={target} size={len(data)}")

    patterns = (list(extra) if only else DEFAULT_PATTERNS + CN_PATTERNS) + (extra if not only else [])
    if only:
        patterns = list(extra)
    for pat in patterns:
        rx = re.compile(pat.encode())
        hits = list(rx.finditer(data))
        if not hits:
            continue
        print(f"\n[{len(hits)}] {pat}")
        for m in hits[:3]:
            ctx = data[max(0, m.start() - 170):m.start() + 210]
            text = ctx.decode("utf-8", errors="replace")
            text = mask(text)
            print("    ...", text.replace("\n", " ")[:330])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
