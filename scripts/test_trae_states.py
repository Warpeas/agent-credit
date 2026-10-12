"""Trae 签到卡片三态判据回归测试。

背景
----
2026-10-09 Trae 与 TraeCode 合并为 TRAE，客户端 UI 改版后**账户条不再显示积分
余额**，「读余额看点击前后差额」这条主判据连续两天静默失效——不报错，只是悄悄退回
「今日已签」文案兜底，于是入账额度再也跟不上服务端调额（免费日额度 2026-09-30 就
从 150 改成了 100）。失效持续两天才被发现，就是因为没有任何东西在守着它。

所以这里把判据正则**从 ps1 源码里抠出来**跑一遍真实样本，防止以后改了正则而样本
没跟上。正则只存在于 scripts/ui_claim_trae.ps1，这里不复制副本。

样本来自 2026-10-13 的实测 OCR dump（logs/ocr_dump_trae.txt），保留 OCR 的识别
错误（「头亻象」「氵去」），因为判据必须容忍这种抖动。

用法：
    python scripts/test_trae_states.py
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PS1 = ROOT / "scripts" / "ui_claim_trae.ps1"

# ps1 里集中定义的判据正则（改了那边的名字，这里会直接报错而不是悄悄放过）
PATTERN_VARS = ("RE_GRANTED", "RE_GRANTED2", "RE_OFFER", "RE_ALREADY", "RE_SIGNBTN")

# 卡片三态。lines 是 OCR 文本行；granted/offer/already 是 ps1 三个函数的期望返回值。
SAMPLES = {
    "刚领取": {
        "lines": [
            "．今日签到，",
            "已获得100积分。下次可在头亻象菜单中签到。",
            "今日已签(3s)",
        ],
        "granted": 100,
        "offer": 0,
        "already": False,
    },
    "未签": {
        "lines": [
            "每日领100积分",
            "升级会员，每日多领100积分",
            "签到",
            "升级权益",
            "0用户71294228173免费",
        ],
        "granted": 0,
        "offer": 100,
        "already": False,
    },
    "已签稳定": {
        "lines": [
            "夺会员首月立减¥30",
            "升级会员立即获得大额积分，专享模型优惠，",
            "高峰期优先响应。",
            "立即升级",
        ],
        "granted": 0,
        "offer": 0,
        "already": True,
    },
}

# Find-SignButton 用同一份未签 dump 的坐标：(text, x, y, w, h)
# entry 是入口行「每日领100积分」@94,1514；干扰项包含左侧栏历史任务名与「升级权益」。
SIGNBTN_ENTRY_Y = 1514
SIGNBTN_WIN_W = 2880
SIGNBTN_LINES = [
    ("配置Trae每日自动签到", 40, 863, 274, 28),
    ("查询签到入口与积分规则", 40, 999, 307, 28),
    ("每日领100积分", 94, 1514, 179, 26),
    ("升级会员，每日多领100积分", 50, 1562, 310, 24),
    ("签到", 145, 1622, 51, 25),
    ("升级权益", 377, 1622, 104, 26),
    ("0用户71294228173免费", 44, 1720, 336, 48),
]
SIGNBTN_EXPECT = "签到"


def load_patterns() -> dict[str, str]:
    src = PS1.read_text(encoding="utf-8-sig")
    out: dict[str, str] = {}
    for name in PATTERN_VARS:
        m = re.search(r"^\$" + name + r"\s*=\s*'(.*)'\s*$", src, re.M)
        if not m:
            sys.exit(f"FAIL: {PS1.name} 里找不到 ${name} —— 正则已改名？测试与脚本漂移了。")
        out[name] = m.group(1)
    return out


def find_granted(lines: list[str], p: dict[str, str]) -> int:
    for t in lines:
        m = re.search(p["RE_GRANTED"], t) or re.search(p["RE_GRANTED2"], t)
        if m:
            return int(m.group(1))
    return 0


def find_offer(lines: list[str], p: dict[str, str]) -> int:
    for t in lines:
        m = re.search(p["RE_OFFER"], t)
        if m:
            return int(m.group(1))
    return 0


def test_already(lines: list[str], p: dict[str, str]) -> bool:
    return any(re.search(p["RE_ALREADY"], t) for t in lines)


def find_sign_button(lines: list[tuple], entry_y: int, win_w: int, p: dict[str, str]):
    """镜像 ps1 的 Find-SignButton：入口行下方、左侧栏内、长度 ≤4 的短文本按钮。"""
    x_max = int(win_w * 0.35)
    best = None
    for text, x, y, w, h in lines:
        if len(text) > 4:
            continue
        if not re.search(p["RE_SIGNBTN"], text):
            continue
        if x >= x_max or y <= entry_y or (y - entry_y) > 260:
            continue
        if best is None or y < best[2]:
            best = (text, x, y, w, h)
    return best


def main() -> int:
    p = load_patterns()
    print(f"正则来源 {PS1.relative_to(ROOT)}")
    for k in PATTERN_VARS:
        print(f"  ${k:<12} = {p[k]!r}")
    print()

    failed = 0
    print(f"{'样本':<10} {'granted':>8} {'offer':>7} {'already':>8}   结果")
    for name, s in SAMPLES.items():
        lines = s["lines"]
        got = (find_granted(lines, p), find_offer(lines, p), test_already(lines, p))
        want = (s["granted"], s["offer"], s["already"])
        ok = got == want
        failed += 0 if ok else 1
        flag = "ok" if ok else f"FAIL 期望 {want}"
        print(f"{name:<10} {got[0]:>8} {got[1]:>7} {str(got[2]):>8}   {flag}")

    btn = find_sign_button(SIGNBTN_LINES, SIGNBTN_ENTRY_Y, SIGNBTN_WIN_W, p)
    got_btn = btn[0] if btn else None
    ok = got_btn == SIGNBTN_EXPECT
    failed += 0 if ok else 1
    print()
    print(f"按钮定位: 命中={got_btn!r} 期望={SIGNBTN_EXPECT!r}  {'ok' if ok else 'FAIL'}")

    print()
    print("FAIL count =", failed)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
