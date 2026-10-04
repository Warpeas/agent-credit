"""check_research_answers 的凭据判定自检：真凭据必须 ALERT，方案名/路径/占位符必须 skip。"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from check_research_answers import is_leak, LEAK_PATTERNS  # noqa: E402

CASES = [
    # (文本, 期望是否泄露)
    ("Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9", True),
    ("Authorization: Bearer abcdef1234567890abcdef1234567890", True),
    ("Authorization: Cloud-IDE-JWT <token>", False),
    ("Authorization: 'Cloud-IDE-JWT'", False),
    ("Authorization: Cloud-IDE-JWT", False),
    ("Authorization: Bearer <redacted>", False),
    ("/api/client-activities/daily_check_in/actions/check_in", False),
    ("https://api.trae.cn/trae/api/v2/ug/checkin_credits/claim", False),
    ("eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9eyJhbGciOiJIUzI1NiJ9", True),  # JWT 规则直接命中
]


def judge(text: str) -> bool:
    for label, pat in LEAK_PATTERNS:
        for m in pat.finditer(text):
            leak, _ = is_leak(label, m.group(0))
            if leak:
                return True
    return False


bad = 0
for text, expect in CASES:
    got = judge(text)
    ok = got == expect
    if not ok:
        bad += 1
    print(f"{'ok  ' if ok else 'FAIL'} expect={'ALERT' if expect else 'skip ':<5} got={'ALERT' if got else 'skip ':<5} {text[:58]}")

print("")
print("FAIL count =", bad)
raise SystemExit(1 if bad else 0)
