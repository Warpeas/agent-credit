#!/usr/bin/env python3
"""校验 research/answers/ 里的答案：填了没 + 有没有把登录态混进来。

入库前跑一遍。发现疑似 token 明文会以退出码 1 失败，避免把凭据提交进 git。

用法：
    python scripts/check_research_answers.py
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ANSWER_DIR = ROOT / "research" / "answers"

# 疑似凭据明文。宁可误报，不要漏报——误报人工看一眼就能排除。
LEAK_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("JWT", re.compile(r"eyJ[A-Za-z0-9_-]{10,}")),
    ("Bearer", re.compile(r"Bearer\s+[A-Za-z0-9._-]{16,}")),
    ("sk- 前缀密钥", re.compile(r"\bsk-[A-Za-z0-9_-]{16,}")),
    ("Authorization 头", re.compile(r"Authorization\s*[:=]\s*\S{8,}")),
    ("长 base64/hex 串", re.compile(r"\b[A-Za-z0-9+/=_-]{40,}\b")),
    ("口令字段", re.compile(r"(?i)\b(password|passwd|pwd|secret)\s*[:=]\s*\S{4,}")),
    ("cookie 字段", re.compile(r"(?i)\bcookie\s*[:=]\s*\S{8,}")),
]

FILLED_KEYS = ("account_id", "confidence", "checkin", "status", "automation")

# 鉴权方案名：出现在 Authorization 头里不代表泄露，真正要看的是它后面那串
AUTH_SCHEMES = {"Bearer", "Basic", "Cloud-IDE-JWT", "JWT", "Digest", "Token", "OAuth"}
PLACEHOLDER = "YYYY-MM-DD"


def yaml_blocks(text: str) -> list[str]:
    out: list[str] = []
    lines = text.splitlines()
    i = 0
    while i < len(lines):
        if lines[i].strip().startswith("```"):
            i += 1
            buf: list[str] = []
            while i < len(lines) and not lines[i].strip().startswith("```"):
                buf.append(lines[i])
                i += 1
            out.append("\n".join(buf))
        i += 1
    return out


def is_leak(label: str, snippet: str) -> tuple[bool, str]:
    """判断一个命中片段是不是真凭据。返回 (是否泄露, 要展示的片段)。

    宁可误报不要漏报是前提，但纯误报会把「方案名」当凭据，反而让人不看告警。
    这里只排除三类确定不是凭据的东西：占位符、接口路径/域名、鉴权方案名。
    """
    if "<redacted>" in snippet:
        return False, ""

    if label == "Authorization 头":
        # `Authorization: Cloud-IDE-JWT <token>` 里 Cloud-IDE-JWT 是**方案名**不是凭据。
        # 剥掉方案名与包裹符号后，剩下的若为空、是占位符、或短得不像令牌，就不算泄露。
        m2 = re.search(r"Authorization\s*[:=]\s*(.*)$", snippet)
        val = m2.group(1) if m2 else ""
        stripped = re.sub(
            r"^['\"`]?(Bearer|Basic|Cloud-IDE-JWT|JWT|Digest|Token|OAuth)['\"`]?",
            "", val, flags=re.IGNORECASE,
        ).strip(" '\"`,，。;；")
        if not stripped or stripped.startswith(("<", "{")) or len(stripped) < 12:
            return False, ""
        return True, stripped

    if label == "长 base64/hex 串":
        # 接口路径与域名不是凭据。/autoclaw-proxy/proxy/autoclaw-task-complete
        # 这类字面量会被 40+ 长度规则整条命中，先按路径分隔符切碎再判：
        # 只有切完还剩 40+ 的单段才可能是真凭据。
        parts = re.split(r"[/.:?&=]", snippet)
        longest = max(parts, key=len)
        if len(longest) < 40:
            return False, ""
        return True, longest

    return True, snippet


def check_file(path: Path) -> tuple[str, list[str]]:
    text = path.read_text(encoding="utf-8")
    blocks = yaml_blocks(text)
    problems: list[str] = []

    if not blocks:
        return "空", ["没有找到 YAML 代码块"]

    body = max(blocks, key=len)

    if PLACEHOLDER in body or re.search(r"confidence:\s*unknown", body):
        return "待填", []

    missing = [k for k in FILLED_KEYS if not re.search(rf"^{k}:", body, re.M)]
    if missing:
        problems.append("缺少字段: " + ", ".join(missing))

    for label, pat in LEAK_PATTERNS:
        for m in pat.finditer(text):
            leak, shown = is_leak(label, m.group(0))
            if not leak:
                continue
            problems.append(f"疑似{label}明文: {shown[:40]}")

    if problems:
        return "有风险", problems
    return "已填", []


def main() -> int:
    if not ANSWER_DIR.is_dir():
        print(f"没有 {ANSWER_DIR}", file=sys.stderr)
        return 1

    files = sorted(ANSWER_DIR.glob("*.md"))
    if not files:
        print("research/answers/ 是空的")
        return 0

    counts = {"已填": 0, "待填": 0, "空": 0, "有风险": 0}
    risky = 0
    for f in files:
        state, problems = check_file(f)
        counts[state] = counts.get(state, 0) + 1
        print(f"[{state:<5}] {f.name}")
        for p in problems:
            print(f"           {p}")
        if state == "有风险":
            risky += 1

    print("")
    print(" / ".join(f"{k} {v}" for k, v in counts.items() if v))

    if risky:
        print("", file=sys.stderr)
        print(f"{risky} 个文件疑似含凭据明文，修掉前不要 git add", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
