#!/usr/bin/env python3
"""Qoder CN 用户名锚点判据回归测试（离线，不点真客户端）。

背景
----
2026-10-20 定时签到轮翻车：情况二（用户名 -> 权益中心 -> 活动弹窗）的锚点旧按
「cy 最靠下的词」取底栏单词，而底栏一行里 warpeas 与工作区名 agent-c.. 的 cy
只差 ~4px——首帧渲染动画 / OCR 抖动时会选中工作区名，点它开不了账户菜单，
当天直接 pending（且旧逻辑两轮点击复用同一锚点、不重解析）。UI 判据失效是
**静默**的：不报错，只是签不到，所以这里把判据从 ps1 源码里抠出来跑真实 OCR
词框样本，防止以后改了判据而样本没跟上。

判据只存在于 scripts/ui_claim_qodercn.ps1 的 ANCHOR-REGION 块，这里不复制副本。

样本坐标来自两处实测：
  - 还原态（2198x1142）：logs/_qoder_shot.png（2026-10-20 失败当日截图）经
    scripts/ocr_image.py 离线复跑的词框；
  - 最大化态（3866x2090）：logs/ps1_qodercn.log 08:58 的 OCR dump。
保留 OCR 的识别错误（「agent-c..」「口本地Pm．"_」），因为判据必须容忍这种抖动。

用法：
    python scripts/test_username_anchor.py
"""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PS1 = ROOT / "scripts" / "ui_claim_qodercn.ps1"

REGION_BEGIN = "# >>> ANCHOR-REGION"
REGION_END = "# <<< ANCHOR-REGION"

# 样本词框：(text, cx, cy)。cx/cy 为词框中心（ps1 OcrWords 的同名口径）。
# 期望：candidates 为按 cx 升序的候选文本（| 分隔），best 为最终锚点文本。
SAMPLES = [
    {
        "name": "还原态-稳定帧",
        "W": 2198, "H": 1142,
        "words": [
            ("W", 61, 1084),            # 头像单字，Length<2 排除
            ("warpeas", 161, 1089),     # 用户名：底栏行内最左
            ("0", 465, 1082),           # 齿轮图标，纯数字排除
            ("agent-c..", 653, 1085),   # 工作区名（cy 仅低 4px，旧判据会翻）
            ("口本地Pm．\"_", 888, 1080),  # cx > W*0.30=659 排除
            ("51％", 1100, 1085),       # cx > 659 排除
        ],
        "candidates": "warpeas|agent-c..",
        "best": "warpeas",
    },
    {
        "name": "还原态-cy抖动翻转",
        "W": 2198, "H": 1142,
        "words": [
            ("W", 61, 1084),
            ("warpeas", 161, 1083),     # cy 被抖到工作区名之下——旧判据翻车点
            ("0", 465, 1082),
            ("agent-c..", 653, 1085),
            ("51％", 1100, 1085),
        ],
        "candidates": "warpeas|agent-c..",
        "best": "warpeas",
    },
    {
        "name": "还原态-首帧漏检warpeas",
        "W": 2198, "H": 1142,
        "words": [
            ("W", 61, 1084),
            ("0", 465, 1082),
            ("agent-c..", 653, 1085),   # 漏检用户名的降级路径：不崩，继续点
            ("51％", 1100, 1085),
        ],
        "candidates": "agent-c..",
        "best": "agent-c..",
    },
    {
        "name": "最大化态",
        "W": 3866, "H": 2090,
        "words": [
            ("W", 51, 2031),
            ("warpeas", 109, 2036),
            ("0", 345, 2031),
            ("0", 456, 2031),
            ("agent-credit", 608, 2031),
            ("本地", 678, 2036),        # 行内第 3 个，被 cap=2 截断（点了有副作用）
            ("maln", 1521, 2031),       # cx > W*0.30=1159 排除
            ("100％", 1788, 2036),      # 排除
            ("自动化", 94, 1877),       # cy < maxCy-12=2024，左侧栏排除
            ("扩展", 94, 1938),         # 同上
        ],
        "candidates": "warpeas|agent-credit",
        "best": "warpeas",
    },
    {
        "name": "空词表",
        "W": 2198, "H": 1142,
        "words": [],
        "candidates": "",
        "best": "",
    },
]

# harness：把抠出的判据块拼进来，喂 fixture JSON，回传每个样本的候选与最佳锚点。
# ⚠️ ps1 必须存成 UTF-8 with BOM（项目踩过：无 BOM 时 PS 5.1 按 GBK 解析，中文全乱）。
HARNESS = """param([string]$FixturesJson)
$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$OutputEncoding = [System.Text.Encoding]::UTF8
__REGION__
$fixtures = Get-Content -LiteralPath $FixturesJson -Raw -Encoding UTF8 | ConvertFrom-Json
$out = @()
foreach ($f in $fixtures) {
    $t = @{ H = [int]$f.H; W = [int]$f.W }
    $words = @()
    foreach ($w in $f.words) {
        $words += @{ text = [string]$w.text; sx = [int]$w.cx; sy = [int]$w.cy; cx = [int]$w.cx; cy = [int]$w.cy }
    }
    $cands = @(Find-UsernameCandidates $words $t)
    $best = Find-Username $null $t $words
    $out += @{
        name = [string]$f.name
        candidates = (($cands | ForEach-Object { [string]$_.text }) -join "|")
        best = $(if ($best) { [string]$best.uname } else { "" })
    }
}
# ⚠️ `,$out | ConvertTo-Json` 在 PS 5.1 下会多包一层 {"value":...,"Count":n}
# （实测），直接 `$out | ConvertTo-Json`：管道展开 5 个元素 -> 标准 JSON 数组；
# 单元素时会退化成单个对象，Python 侧已做 dict->[dict] 兜底。
$out | ConvertTo-Json -Compress -Depth 4
"""


def extract_region() -> str:
    src = PS1.read_text(encoding="utf-8-sig")
    i = src.find(REGION_BEGIN)
    j = src.find(REGION_END)
    if i < 0 or j < 0 or j < i:
        sys.exit(f"FAIL: {PS1.name} 里找不到 ANCHOR-REGION 标记 —— 判据被挪走/改名了？测试与脚本漂移了。")
    region = src[i:j]
    for fn in ("function Find-UsernameCandidates", "function Find-Username("):
        if fn not in region:
            sys.exit(f"FAIL: ANCHOR-REGION 里没有 {fn} —— 函数被改名？测试与脚本漂移了。")
    return region


def run_fixtures(samples: list[dict]) -> list[dict]:
    harness = HARNESS.replace("__REGION__", extract_region())
    payload = [
        {"name": s["name"], "W": s["W"], "H": s["H"],
         "words": [{"text": t, "cx": cx, "cy": cy} for t, cx, cy in s["words"]]}
        for s in samples
    ]
    with tempfile.TemporaryDirectory() as td:
        hp = Path(td) / "harness.ps1"
        fp = Path(td) / "fixtures.json"
        hp.write_text(harness, encoding="utf-8-sig")
        fp.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8-sig")
        try:
            r = subprocess.run(
                ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass",
                 "-File", str(hp), "-FixturesJson", str(fp)],
                capture_output=True, text=True, encoding="utf-8",
                errors="replace", timeout=120)
        except subprocess.TimeoutExpired:
            sys.exit("FAIL: harness 超时（120s）")
    out = (r.stdout or "").strip()
    if not out:
        sys.exit(f"FAIL: harness 无输出。stderr={(r.stderr or '')[:300]}")
    try:
        data = json.loads(out)
    except json.JSONDecodeError:
        sys.exit(f"FAIL: harness 输出不是 JSON: {out[:300]}")
    return data if isinstance(data, list) else [data]


def main() -> int:
    print(f"判据来源 {PS1.relative_to(ROOT)}#ANCHOR-REGION\n")
    got = run_fixtures(SAMPLES)
    failed = 0
    print(f"{'样本':<24} {'候选':<28} {'最佳':<14} 结果")
    for s, g in zip(SAMPLES, got):
        cand = g.get("candidates", "")
        best = g.get("best", "")
        ok = (cand == s["candidates"]) and (best == s["best"])
        failed += 0 if ok else 1
        flag = "ok" if ok else f"FAIL 期望 candidates={s['candidates']!r} best={s['best']!r}"
        print(f"{s['name']:<24} {cand or '(无)':<28} {best or '(无)':<14} {flag}")
    print()
    print("FAIL count =", failed)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
