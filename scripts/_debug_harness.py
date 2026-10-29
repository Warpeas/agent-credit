#!/usr/bin/env python3
"""临时调试：跑 harness 并把原始 stdout/stderr 落盘到 logs/_debug_harness.txt"""
import json
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import test_username_anchor as T  # noqa: E402

harness = T.HARNESS.replace("__REGION__", T.extract_region())
payload = [
    {"name": s["name"], "W": s["W"], "H": s["H"],
     "words": [{"text": t, "cx": cx, "cy": cy} for t, cx, cy in s["words"]]}
    for s in T.SAMPLES
]

with tempfile.TemporaryDirectory() as td:
    hp = Path(td) / "harness.ps1"
    fp = Path(td) / "fixtures.json"
    hp.write_text(harness, encoding="utf-8-sig")
    fp.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8-sig")
    fixtures_head = fp.read_text(encoding="utf-8-sig")[:500]
    r = subprocess.run(
        ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass",
         "-File", str(hp), "-FixturesJson", str(fp)],
        capture_output=True, text=True, encoding="utf-8",
        errors="replace", timeout=120)

report = []
report.append("=== rc: %s" % r.returncode)
report.append("=== fixtures.json (first 500) ===")
report.append(fixtures_head)
report.append("=== stdout ===")
report.append(r.stdout or "(empty)")
report.append("=== stderr ===")
report.append((r.stderr or "(empty)")[:1500])
out = ROOT / "logs" / "_debug_harness.txt"
out.write_text("\n".join(report), encoding="utf-8")
print("written", out)
