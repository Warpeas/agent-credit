# -*- coding: utf-8 -*-
"""MonkeyCode 网页端每日签到（2026-11-16 接入）。

机制（实测 2026-11-16）：
  登录 monkeycode-ai.com → 控制台左侧栏有「签到领积分 +100」菜单按钮
  → 点击即签到成功（无弹窗、无验证码，网页 UI 路线没有客户端 API 那道
  captcha），积分立即 +100，侧栏签到菜单项随即消失（天然幂等）。
  实测：Yina 177 → 277。

登录态：data/webprofiles/monkeycode/（2026-11-16 手机验证码登录，
Edge 自己保管 cookie，本脚本不读不导出——research/SAFETY.md 规则 1）。
登录态失效 exit 3 报 NEED_LOGIN；由 checkin 回落到本机已安装的 MonkeyCode
桌面客户端 UIA 路线，不保留人工登录等待，也不阻塞其余账户继续签到。
注意：登录页的微信二维码与短信验证码在自动化 profile 下都可能被长亭
CAP 组件的 Worker timeout 卡住（已加 --disable-features=TrackingPrevention
与 --disable-blink-features=AutomationControlled 规避，登录成功一次后
长期有效，无需每天登录）。

失效条件：
  - 侧栏「签到领积分」文案/结构改版
  - 「订阅重要通知」弹窗出现且 Close 按钮改名
  - 登录态失效模式变化

跑法：python scripts/web_claim_monkeycode.py
退出码：0=完成  2=待人工（页面异常）  3=未登录（转客户端兜底）  其它=失败
"""
from __future__ import annotations

import re
import sys
import time
from datetime import datetime
from pathlib import Path

from playwright.sync_api import sync_playwright

REPO = Path(__file__).resolve().parent.parent
OUT = REPO / "logs" / "webclaim_monkeycode"
PROFILE = REPO / "data" / "webprofiles" / "monkeycode"
URL = "https://monkeycode-ai.com/console/tasks"
DAILY = 100
LAUNCH_ARGS = [
    "--window-size=1440,900",
    "--disable-features=TrackingPrevention",
    "--disable-blink-features=AutomationControlled",
]

OUT.mkdir(parents=True, exist_ok=True)
PROFILE.mkdir(parents=True, exist_ok=True)


def log(msg: str) -> None:
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)


def close_subscribe_popup(page) -> bool:
    """首次进入常有「订阅重要通知」弹窗挡住整页，关掉它。"""
    try:
        body = page.inner_text("body", timeout=5000)
    except Exception:
        return False
    if "订阅重要通知" not in body:
        return False
    for el in page.query_selector_all("button"):
        try:
            if (el.inner_text() or "").strip() == "Close":
                el.click()
                time.sleep(2)
                log("已关闭订阅弹窗")
                return True
        except Exception:
            continue
    return False


def read_points(page) -> int | None:
    """读侧栏账户卡积分数字（'Yina 基础会员 277'）。"""
    try:
        body = page.inner_text("body", timeout=8000)
    except Exception:
        return None
    m = re.search(r"基础会员\s*\n?\s*(\d+)", body)
    return int(m.group(1)) if m else None


def main() -> int:
    today = datetime.now().strftime("%Y-%m-%d")
    with sync_playwright() as p:
        ctx = p.chromium.launch_persistent_context(
            str(PROFILE), channel="msedge", headless=False, args=LAUNCH_ARGS)
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        try:
            page.goto(URL, wait_until="domcontentloaded", timeout=60000)
            time.sleep(10)
            close_subscribe_popup(page)

            # 登录态判据：被踢到 /login = 登录态失效
            if "/login" in page.url:
                log("登录态失效：被重定向到登录页")
                page.screenshot(path=str(OUT / f"nologin_{today}.png"))
                print("NEED_LOGIN: 网页登录态失效", flush=True)
                return 3

            slug = datetime.now().strftime("%H%M%S")
            points_before = read_points(page)
            log(f"登录态有效，当前积分 {points_before}")

            btn = None
            for el in page.query_selector_all("button, a, [role=button]"):
                try:
                    t = (el.inner_text() or "").strip()
                except Exception:
                    continue
                if t.startswith("签到领积分"):
                    btn = el
                    break

            if btn is None:
                # 侧栏签到入口消失 = 今日已签（菜单项签完即隐，天然幂等）
                log("侧栏无「签到领积分」入口——今日已签")
                print("already: 今日已签（签到入口未出现）", flush=True)
                return 0

            try:
                btn.click(timeout=8000)
                log("已点击「签到领积分」")
            except Exception as exc:
                # 首击常已生效，弹窗遮罩挡住后续重试导致 click 超时；
                # 是否签成以积分/入口状态为准
                log(f"点击报超时（可能已生效）: {str(exc)[:100]}")
            time.sleep(6)

            points_after = read_points(page)
            entry_gone = True
            for el in page.query_selector_all("button, a, [role=button]"):
                try:
                    t = (el.inner_text() or "").strip()
                except Exception:
                    continue
                if t.startswith("签到领积分"):
                    entry_gone = False
                    break

            page.screenshot(path=str(OUT / f"claim_{today}_{slug}.png"))
            gained = None
            if points_before is not None and points_after is not None:
                gained = points_after - points_before
            log(f"点击后积分 {points_before} -> {points_after}（差 {gained}），入口消失={entry_gone}")

            if entry_gone and (gained == DAILY or points_after is None):
                print(f"[granted] {DAILY}", flush=True)
                return 0
            if entry_gone and gained is not None and gained > 0:
                print(f"[granted] {gained}", flush=True)
                return 0
            # 入口还在 = 签到没生效；积分异常上涨 = 口径变化，都交人工核对
            print("PENDING: 签到未确认生效（入口仍在或积分异常），人工核对后 "
                  "credit record monkeycode_credit claimed 100", flush=True)
            return 2
        finally:
            time.sleep(3)
            ctx.close()


if __name__ == "__main__":
    sys.exit(main())
