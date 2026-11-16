#!/usr/bin/env python3
"""扫描窗口某一纵向区间内的「暗色区段」，用来定位黑底按钮/深色卡片。

排障工具，不是生产脚本：Find-DarkButton 在 Trae 新布局上误检了一段 356px 的
"暗色"（真按钮只有 38~44px），需要看清那一行到底有什么，才能改判定条件。

用法：
    python scripts/forensics_row_scan.py <png> <y0> <y1> [--x0 0] [--x1 900] [--step 6]
"""
from __future__ import annotations

import argparse
import struct
import zlib
from pathlib import Path


def load_png(path: Path):
    b = path.read_bytes()
    assert b[:8] == b"\x89PNG\r\n\x1a\n", "not a png"
    w, h = struct.unpack(">II", b[16:24])
    bd, ct = b[24], b[25]
    assert bd == 8, f"bitdepth {bd}"
    ch = {0: 1, 2: 3, 4: 2, 6: 4}[ct]
    i, idat = 8, b""
    while i < len(b):
        ln = struct.unpack(">I", b[i:i + 4])[0]
        t = b[i + 4:i + 8]
        if t == b"IDAT":
            idat += b[i + 8:i + 8 + ln]
        i += 12 + ln
        if t == b"IEND":
            break
    raw = zlib.decompress(idat)
    stride = w * ch
    prev = bytearray(stride)
    rows = []
    pos = 0
    for _y in range(h):
        ft = raw[pos]
        pos += 1
        line = bytearray(raw[pos:pos + stride])
        pos += stride
        if ft == 1:
            for x in range(ch, stride):
                line[x] = (line[x] + line[x - ch]) & 0xFF
        elif ft == 2:
            for x in range(stride):
                line[x] = (line[x] + prev[x]) & 0xFF
        elif ft == 3:
            for x in range(stride):
                a = line[x - ch] if x >= ch else 0
                line[x] = (line[x] + ((a + prev[x]) >> 1)) & 0xFF
        elif ft == 4:
            for x in range(stride):
                a = line[x - ch] if x >= ch else 0
                bb = prev[x]
                c = prev[x - ch] if x >= ch else 0
                p = a + bb - c
                pa, pb, pc = abs(p - a), abs(p - bb), abs(p - c)
                pr = a if (pa <= pb and pa <= pc) else (bb if pb <= pc else c)
                line[x] = (line[x] + pr) & 0xFF
        prev = line
        rows.append(bytes(line))
    return w, h, ch, rows


def is_dark(px: tuple[int, int, int]) -> bool:
    return px[0] < 90 and px[1] < 90 and px[2] < 90


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("png")
    ap.add_argument("y0", type=int)
    ap.add_argument("y1", type=int)
    ap.add_argument("--x0", type=int, default=0)
    ap.add_argument("--x1", type=int, default=900)
    ap.add_argument("--step", type=int, default=6)
    a = ap.parse_args()
    w, h, ch, rows = load_png(Path(a.png))
    print(f"png {w}x{h} ch={ch}")
    for y in range(max(0, a.y0), min(h, a.y1), a.step):
        row = rows[y]
        runs = []
        start = -1
        for x in range(a.x0, min(a.x1, w)):
            o = x * ch
            d = is_dark((row[o], row[o + 1], row[o + 2]))
            if d and start < 0:
                start = x
            elif not d and start >= 0:
                if x - start >= 8:
                    runs.append((start, x - start))
                start = -1
        if start >= 0 and min(a.x1, w) - start >= 8:
            runs.append((start, min(a.x1, w) - start))
        # 取该行最亮/最暗色作参照
        sample = [tuple(row[x * ch:x * ch + 3]) for x in range(a.x0, min(a.x1, w), 40)]
        print(f"y={y:4d} runs={runs} sample={sample[:6]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
