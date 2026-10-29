#!/usr/bin/env python3
"""挖 Qoder CN 客户端里的「用量/积分」数据来源：端点路径 + 数据结构字段。

为什么单独写一个：scan_asar.py 每个词只给 3 段上下文，够判断「有没有签到」，
不够把一整套 REST 端点和响应字段挖全。本脚本按「先列清单、再定点看上下文」两步走。

只读：不改写 asar、不执行客户端代码、不联网。长串（token/密钥形状）一律 mask。

用法：
    python scripts/probe_qoder_asar.py [app.asar 路径] [--out logs/_qoder_asar_probe.txt]
"""
from __future__ import annotations

import argparse
import re
import sys
from collections import Counter
from pathlib import Path

DEFAULT_ASAR = Path(
    r"C:\Users\Hunter\AppData\Local\Programs\Qoder CN\resources\app.asar"
)

# 引号里的路径字面量：/algo/api/v1/xxx、/v2/billing/xxx、api/xxx/yyy 都算
PATH_RX = re.compile(rb"""["'`](/[A-Za-z0-9_\-./{}]{4,80}|api/[A-Za-z0-9_\-./{}]{4,80})["'`]""")
# 明显不是端点的噪音：静态资源、文件名、CSS/JS 模块路径
NOISE_SUFFIX = (".js", ".ts", ".tsx", ".css", ".json", ".png", ".svg", ".woff",
                ".wasm", ".map", ".html", ".node", ".md")
NOISE_PARTS = ("node_modules", "/src/", "/out/", "\\", "webpack", "chrome-extension",
               "//", "/icons/", "/assets/")

# 用量/积分面板相关的标识符，用来定位响应结构
SYMBOLS = [
    rb"[Rr]esourcePackage", rb"usageDetail", rb"creditBalance", rb"CreditPackage",
    rb"remainingCredit", rb"expire[A-Za-z_]*", rb"[Ee]xpir", rb"quotaUsage",
    rb"getUsage", rb"fetchUsage", rb"usageSummary", rb"Monthly", rb"refresh",
]

MASK = re.compile(r"[A-Za-z0-9+/=_-]{32,}")


def clean(text: str) -> str:
    return MASK.sub("<masked>", text).replace("\n", " ")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("asar", nargs="?", default=str(DEFAULT_ASAR))
    ap.add_argument("--out", default="logs/_qoder_asar_probe.txt")
    ap.add_argument("--max-paths", type=int, default=120)
    args = ap.parse_args()

    target = Path(args.asar)
    if not target.is_file():
        print(f"not found: {target}", file=sys.stderr)
        return 1
    data = target.read_bytes()
    out: list[str] = [f"file={target} size={len(data)}", ""]

    counts: Counter[str] = Counter()
    for m in PATH_RX.finditer(data):
        p = m.group(1).decode("utf-8", "replace")
        if p.endswith(NOISE_SUFFIX) or any(n in p for n in NOISE_PARTS):
            continue
        if not re.search(r"[A-Za-z]{3}", p):
            continue
        counts[p] += 1
    interesting = [(p, c) for p, c in counts.most_common()
                   if re.search(r"(usage|credit|quota|billing|plan|package|wallet|reward|"
                                r"checkin|sign|member|subscri|balance|entit|activity|benefit)",
                                p, re.I)]
    out.append(f"== 疑似用量/积分端点（{len(interesting)} 条，按命中次数）==")
    for p, c in interesting[:args.max_paths]:
        out.append(f"  {c:>4}  {p}")
    out.append("")
    out.append(f"== 全部路径字面量 top 60（共 {len(counts)} 个去重）==")
    for p, c in counts.most_common(60):
        out.append(f"  {c:>4}  {p}")
    out.append("")

    for sym in SYMBOLS:
        hits = list(re.finditer(sym, data))
        label = sym.decode()
        if not hits:
            out.append(f"== [{label}] 0 命中 ==")
            continue
        out.append(f"== [{label}] {len(hits)} 命中，取 3 段上下文 ==")
        for m in hits[:3]:
            ctx = data[max(0, m.start() - 260):m.start() + 300]
            out.append("  ... " + clean(ctx.decode("utf-8", "replace"))[:560])
        out.append("")

    report = Path(args.out)
    report.parent.mkdir(parents=True, exist_ok=True)
    text = "\n".join(out)
    report.write_text(text, encoding="utf-8")
    print(f"写入 {report}（{len(out)} 行）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
