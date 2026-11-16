# -*- coding: utf-8 -*-
"""商汤小浣熊网页每日积分签到（2026-11-15 接入）。

机制（面板官方原话 + 明细实测，2026-11-16 确认）：
  每日积分每天 00:00 发放，默认当日 24:00 清零，当天登录后有效期延长至 7 天。
  积分面板无任何「领取」按钮——签到动作 = 当天带着有效登录态打开页面。
  本脚本做的事：用项目持久化 profile 打开主页 → 验证登录态 → 进积分面板
  确认今天 00:00 发放的 +300 条目存在 → [granted] 300 交台账入账。

登录态：data/webprofiles/xiaohuanxiong/（Edge 自己保管 cookie，本脚本不读
不导出——research/SAFETY.md 规则 1）。登录态失效时 exit 2 报 pending，
主人在弹出窗口里人工登录一次即可恢复。

失效条件：
  - account-card-points 按钮类名改版
  - 积分面板明细文案「每日积分发放」改版
  - 发放/有效期规则变更（面板原话与 catalog 注释对照）

跑法：python scripts/web_claim_xiaohuanxiong.py
退出码：0=完成  2=待人工（登录态失效/页面异常）  其它=失败
"""
from __future__ import annotations

import re
import sys
import time
from datetime import datetime
from pathlib import Path

from playwright.sync_api import sync_playwright

REPO = Path(__file__).resolve().parent.parent
OUT = REPO / "logs" / "webclaim_xiaohuanxiong"
PROFILE = REPO / "data" / "webprofiles" / "xiaohuanxiong"
URL = "https://xiaohuanxiong.com/work/home?lang=zh"
DAILY = 300

OUT.mkdir(parents=True, exist_ok=True)
PROFILE.mkdir(parents=True, exist_ok=True)


def log(msg: str) -> None:
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)


def main() -> int:
    today = datetime.now().strftime("%Y-%m-%d")
    with sync_playwright() as p:
        ctx = p.chromium.launch_persistent_context(
            str(PROFILE), channel="msedge", headless=False,
            args=["--window-size=1200,850"])
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        try:
            page.goto(URL, wait_until="domcontentloaded", timeout=60000)
            time.sleep(6)

            # 登录态判据：账户卡积分按钮存在（未登录页没有它）
            if not page.query_selector("button.account-card-points"):
                log("登录态失效：account-card-points 不存在（未登录）")
                page.screenshot(path=str(OUT / f"nologin_{today}.png"))
                print("NEED_LOGIN: 请在弹出窗口登录小浣熊后重跑", flush=True)
                return 2

            log(f"登录态有效，打开积分面板（今日 {today}）")
            page.query_selector("button.account-card-points").click()
            ok_panel = False
            body = ""
            for _ in range(5):
                time.sleep(2)
                try:
                    body = page.inner_text("body", timeout=8000)
                except Exception:
                    body = ""
                if "积分构成" in body:
                    ok_panel = True
                    break
            if not ok_panel:
                log("积分面板未打开（页面可能改版）")
                page.screenshot(path=str(OUT / f"nopanel_{today}.png"))
                print("PANEL_FAIL: 积分面板打不开，人工检查", flush=True)
                return 2

            slug = datetime.now().strftime("%H%M%S")
            page.screenshot(path=str(OUT / f"claim_{today}_{slug}.png"))

            # 官方规则原话在面板里，顺手做一致性核对（失效条件探测）
            m = re.search(r"每日积分每天 00:00 发放[^。\n]*。[^。\n]*。", body)
            if m:
                log(f"规则原话仍在: {m.group(0)[:50]}…")

            # 今天 00:00 的发放条目：形如「每日积分发放\n2026-11-16 00:00 · 有效期至 11-22 24:00\n+300」
            entry = re.search(
                r"每日积分发放\s*\n" + re.escape(today) +
                r"\s+00:00\s*·\s*有效期至\s*(\d{2}-\d{2})\s+24:00\s*\n\+(\d+)",
                body)
            if not entry:
                log(f"未找到今天({today})的发放条目——可能尚未到 00:00 或明细延迟")
                print("NO_ENTRY_TODAY: 今日发放条目未出现（明细更新可能有延迟）", flush=True)
                return 2

            until, amount = entry.group(1), int(entry.group(2))
            log(f"今日发放已入账：+{amount}，有效期至 {until} 24:00（登录延长已生效）")
            print(f"[granted] {amount}", flush=True)
            return 0
        finally:
            time.sleep(3)
            ctx.close()


if __name__ == "__main__":
    sys.exit(main())
