#!/usr/bin/env python3
"""catalog.yaml 提交前校验。

为什么需要（2026-10-04 踩了两次）：
1. 本项目自带 `agent_credit/yaml_lite.py`（零依赖轻量解析器），
   **不支持 `>-` 折叠标量**，写了会直接抛 `bad indent`，
   而 pyyaml 能正常解析 —— 只用 pyyaml 验会漏掉这个。
2. 双引号标量里写裸 `"`（比如 notes 里引别人的原话）会让 pyyaml 报
   `expected <block end>`，轻量解析器则可能静默截断。
   2026-10-04 上午的 commit 就带着这个错，直到下午跑 status 才暴露。

所以两个解析器都要过，且额外检查标量里的裸引号。
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CATALOG = ROOT / "catalog.yaml"

# 与 yaml_lite 同能力的字段：这些字段会被 checkin/status 消费
CRITICAL = ("id", "name", "claim_policy", "claim_mode", "command", "daily_amount",
            "validity_days", "cap", "aliases", "notes", "rating", "review")


def check_lite() -> list[str]:
    sys.path.insert(0, str(ROOT))
    try:
        from agent_credit import yaml_lite
    except ImportError as e:
        return [f"[lite] cannot import yaml_lite: {e}"]
    errs = []
    try:
        # yaml_lite 的入口是 load_yaml（不是 pyyaml 的 safe_load）
        data = yaml_lite.load_yaml(CATALOG.read_text(encoding="utf-8"))
    except Exception as e:  # noqa: BLE001
        return [f"[lite] parse failed: {e}"]
    if not isinstance(data, dict):
        return ["[lite] top level is not a mapping"]
    for key in ("accounts", "calendar", "validity_audit_2026_10_04"):
        if key not in data:
            errs.append(f"[lite] missing top-level key: {key}")
    accounts = data.get("accounts") or []
    if not isinstance(accounts, list) or not accounts:
        errs.append("[lite] accounts is empty or not a list")
    else:
        for a in accounts:
            if not isinstance(a, dict) or "id" not in a:
                errs.append(f"[lite] account without id: {a!r:.60}")
    return errs


def check_pyyaml() -> list[str]:
    try:
        import yaml
    except ImportError:
        return ["[pyyaml] not installed, skip"]
    try:
        data = yaml.safe_load(CATALOG.read_text(encoding="utf-8"))
    except Exception as e:  # noqa: BLE001
        return [f"[pyyaml] parse failed: {e}"]
    if not isinstance(data, dict):
        return ["[pyyaml] top level is not a mapping"]
    return []


def check_raw_quotes() -> list[str]:
    """扫双引号标量里的裸引号（pyyaml 会报错，轻量解析器可能静默截断）。"""
    errs = []
    pat = re.compile(r'^(\s*)(' + "|".join(CRITICAL) + r'):\s+"(.*)"\s*$')
    for i, line in enumerate(CATALOG.read_text(encoding="utf-8").split("\n"), 1):
        m = pat.match(line)
        if not m:
            continue
        body = m.group(3).replace('\\"', "")
        if '"' in body:
            errs.append(f"[raw] line {i}: unescaped quote in {m.group(2)}")
    return errs


def check_folded() -> list[str]:
    """折叠标量轻量解析器不支持，提前报错并给替代写法。"""
    errs = []
    for i, line in enumerate(CATALOG.read_text(encoding="utf-8").split("\n"), 1):
        if re.match(r"^\s+\w+:\s*[|>][-+]?\s*$", line):
            errs.append(f"[folded] line {i}: yaml_lite does NOT support >- or |; "
                        f"write it as a single-line double-quoted scalar")
    return errs


def main() -> int:
    errs = check_folded() + check_raw_quotes() + check_lite() + check_pyyaml()
    if errs:
        print("FAIL:")
        for e in errs:
            print("  " + e)
        return 1
    print("OK: catalog.yaml passes folded-scalar, raw-quote, yaml_lite and pyyaml checks")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
