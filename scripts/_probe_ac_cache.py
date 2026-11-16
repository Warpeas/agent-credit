# -*- coding: utf-8 -*-
"""只读探针：AutoClaw 客户端本地缓存里有没有积分明细（逐条 expiresAt）。
红线（research/SAFETY.md）：只读、不解密、不打印 token/cookie/auth 类字段值。
输出到 stdout（UTF-8），只打印积分相关结构与命中上下文。
"""
import json
import os
import re
import sys

BASES = [
    r"C:\Users\Hunter\AppData\Roaming\autoclaw",
    r"C:\Users\Hunter\AppData\Roaming\AutoClaw-official",
]

KEYWORDS = [
    b"walletItems", b"expiresAt", b"expiryTime", b"expire_at",
    b"creditsDetail", b"points/ledger", b"points/expiring",
    b"credits/ledger", b"wallet", b"pointsBalance", b"credit_ledger",
]

REDACT = re.compile(r"token|secret|cookie|password|authorization|sign|auth", re.I)
CREDIT_HINT = re.compile(r"credit|point|wallet|balance|expire", re.I)


def redact_deep(obj, depth=0, maxdepth=6):
    """打印用：递归 redact 敏感值，积分字段保留。"""
    if depth > maxdepth:
        return "..."
    if isinstance(obj, dict):
        out = {}
        for k, v in obj.items():
            if REDACT.search(str(k)):
                out[str(k)] = "<redacted>"
            else:
                out[str(k)] = redact_deep(v, depth + 1, maxdepth)
        return out
    if isinstance(obj, list):
        return [redact_deep(v, depth + 1, maxdepth) for v in obj[:20]]
    if isinstance(obj, str) and len(obj) > 120:
        return obj[:120] + "...(%d chars)" % len(obj)
    return obj


def probe_json(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            d = json.load(f)
    except Exception as e:
        print("  [json] %s -> parse fail: %s" % (os.path.basename(path), e))
        return
    print("  [json] %s top-level keys: %s" % (os.path.basename(path), list(d.keys()) if isinstance(d, dict) else type(d).__name__))
    # 找积分相关子树
    def walk(o, trail=""):
        if isinstance(o, dict):
            for k, v in o.items():
                t = trail + "." + str(k)
                if CREDIT_HINT.search(str(k)) and not REDACT.search(str(k)):
                    print("    HIT %s = %s" % (t, json.dumps(redact_deep(v), ensure_ascii=False)[:1500]))
                walk(v, t)
        elif isinstance(o, list):
            for i, v in enumerate(o[:50]):
                walk(v, trail + "[%d]" % i)
    walk(d)


def scan_bytes(root):
    """扫客户端自落盘文件里的关键字命中（只读，打印命中上下文）。"""
    hits = 0
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in {"Cache", "Code Cache", "GPUCache", "DawnGraphiteCache", "DawnWebGPUCache", "blob_storage", "Network", "node_modules"}]
        for fn in filenames:
            p = os.path.join(dirpath, fn)
            try:
                if os.path.getsize(p) > 150 * 1024 * 1024:
                    continue
                with open(p, "rb") as f:
                    data = f.read()
            except Exception:
                continue
            for kw in KEYWORDS:
                idx = data.find(kw)
                while idx != -1 and hits < 80:
                    ctx = data[max(0, idx - 60): idx + 400]
                    txt = ctx.decode("utf-8", "replace").replace("\n", " ")
                    # 简单脱敏：不输出疑似长 token
                    txt = re.sub(r"[A-Za-z0-9_\-.]{80,}", "<long-token-like>", txt)
                    print("  [scan] %s :: %s" % (os.path.relpath(p, root), txt))
                    hits += 1
                    idx = data.find(kw, idx + 1)
    if hits == 0:
        print("  [scan] no keyword hits")


for base in BASES:
    print("=" * 70)
    print("BASE:", base)
    if not os.path.isdir(base):
        print("  (missing)")
        continue
    for jf in ("user-cache.json", "token-cache.json", "user-cache.json.backup", "token-cache.json.backup"):
        p = os.path.join(base, jf)
        if os.path.exists(p):
            print("-" * 60)
            print("JSON:", jf)
            probe_json(p)
    for ld in ("logs", "diagnostics", "apmplus"):
        d = os.path.join(base, ld)
        if os.path.isdir(d):
            print("-" * 60)
            print("SCAN DIR:", ld)
            scan_bytes(d)
print("=" * 70)
print("done")
