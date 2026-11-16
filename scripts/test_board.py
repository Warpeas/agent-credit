#!/usr/bin/env python3
"""积分看板 + Trae 明细通道的回归测试。

覆盖四类静默失败：
  1. 口径漂移   —— Trae 载荷的 grants 结构变了，对账写不进账本
  2. 新鲜度闸门 —— 昨天的 dump 被当成今天的登记，把真实余额覆盖成旧值
  3. 看板算错   —— 余额/笔数/最近过期/口径标签与账本对不上
  4. 优先级打架 —— 看板排序与 recommend 不是同一套规则

账本用临时目录，不碰 data/ledger.json；看板落盘也指向临时目录。

用法：python scripts/test_board.py
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
from datetime import date, datetime, timedelta  # noqa: E402
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

tmp = Path(tempfile.mkdtemp(prefix="agent-credit-board-"))
os.environ["AGENT_CREDIT_DATA"] = str(tmp)

from agent_credit import board, checkin, ledger, priority, trae_credits  # noqa: E402
from agent_credit.recommend import recommend  # noqa: E402

ON = date(2026, 10, 20)
bad = 0


def check(label: str, got, expect) -> None:
    global bad
    ok = got == expect
    if not ok:
        bad += 1
    print(f"{'ok  ' if ok else 'FAIL'} {label}"
          + ("" if ok else f"\n      got:    {got!r}\n      expect: {expect!r}"))


def epoch_ms(y: int, m: int, d: int) -> int:
    """本地时间的 epoch 毫秒——别手算，写死常量迟早算错。"""
    return int(datetime(y, m, d, 23, 59, 59).timestamp() * 1000)


def make_dump(day_key: str = "2026-10-20", remaining: float = 3629.2192,
              expire_ms: int | None = None, packs=None) -> dict:
    """造一份形状与客户端扩展导出一致的 dump。"""
    if expire_ms is None:
        expire_ms = epoch_ms(2026, 10, 31)
    results = {
        "creditsUsage": {"ok": True, "data": {
            "limit": 3800, "used": 170.7808, "remaining": remaining,
            "expireTime": expire_ms, "isDollarUsageBilling": False}},
        "checkinSnapshot": {"ok": True, "data": {
            "readiness": "ready", "checkedIn": True, "didCheckedIn": True,
            "credits": 100, "extraCredits": 100,
            "beijingDayKey": day_key}},
    }
    payload = {"fetched_at": "2026-10-19T16:13:18.787Z", "reason": "startup",
               "results": results}
    if packs is not None:
        payload["results"]["entitlement"] = {"ok": True, "data": {
            "user_entitlement_pack_list": packs}}
    return payload


# ---------- trae_credits：聚合口径 ----------
parsed = trae_credits.parse_dump(make_dump())
p = trae_credits.payload(parsed)
check("聚合口径只有一条 grant", len(p["grants"]), 1)
check("聚合口径余额取服务端 remaining", p["total"], 3629)
check("聚合口径带到期日", p["grants"][0]["expires"], "2026-10-31")
check("聚合口径标记 granularity", p["granularity"], "aggregate")

# ---------- trae_credits：逐包口径 ----------
packs = [
    {"entitlement_base_info": {"product_type": "free", "quota": {"credits_limit": 100},
                               "end_time": epoch_ms(2026, 10, 31)},
     "usage": {"credits_amount": 30}, "display_desc": "免费包"},
    {"entitlement_base_info": {"product_type": "paid", "quota": {"credits_limit": 500},
                               "end_time": epoch_ms(2027, 8, 1)},
     "usage": {"credits_amount": 0}, "display_desc": "购买包"},
]
parsed_pk = trae_credits.parse_dump(make_dump(packs=packs))
p_pk = trae_credits.payload(parsed_pk)
check("逐包口径每包一条 grant", len(p_pk["grants"]), 2)
check("逐包剩余 = 额度 - 已用", [g["remain"] for g in p_pk["grants"]], [70, 500])
check("逐包到期日各自独立",
      [g["expires"] for g in p_pk["grants"]], ["2026-10-31", "2027-08-01"])
check("逐包标记 granularity", p_pk["granularity"], "per_pack")

# ---------- 新鲜度闸门 ----------
# is_fresh 默认取真实今天；本测试的其他数据都锚定在 ON(2026-10-20)，
# 必须把 on=ON 一并传进去，否则测试会在当天之后自然失效。
check("当天的 dump 是新鲜的",
      trae_credits.is_fresh(trae_credits.parse_dump(make_dump()), on=ON), True)
check("昨天的 dump 不新鲜",
      trae_credits.is_fresh(trae_credits.parse_dump(make_dump(day_key="2026-10-19")), on=ON), False)
check("没有 day_key 也不新鲜",
      trae_credits.is_fresh(trae_credits.parse_dump({"results": {}})), False)
check("dump 日期取 beijingDayKey",
      trae_credits.dump_date(trae_credits.parse_dump(make_dump(day_key="2026-10-19"))),
      date(2026, 10, 19))

# ---------- 新鲜度闸门第二道：本轮领取之后 dump 必须更晚（2026-11-05） ----------
# 实况：09:30:19 领取成功，09:32:54 对账读的是 09:11 抓的 dump（2950，真值 3050.37），
# 日粒度闸门放行，reconcile 把刚记的 100 当场冲掉。
_parsed_today = trae_credits.parse_dump(make_dump())
_dump_ts = trae_credits.dump_time(_parsed_today).timestamp()
check("没设领取时刻时只按日粒度判",
      trae_credits.is_fresh(_parsed_today, on=ON), True)
os.environ[trae_credits.CLAIM_AFTER_ENV] = str(_dump_ts + 60)   # 领取比 dump 晚 1 分钟
check("当天内但早于本轮领取的 dump 被拒",
      trae_credits.is_fresh(trae_credits.parse_dump(make_dump()), on=ON), False)
check("拒绝原因点名领取时刻",
      "早于本轮领取" in trae_credits.freshness_refusal(
          trae_credits.parse_dump(make_dump()), on=ON), True)
os.environ[trae_credits.CLAIM_AFTER_ENV] = str(_dump_ts - 60)   # dump 是领取之后重抓的
check("领取之后重抓的 dump 放行",
      trae_credits.is_fresh(trae_credits.parse_dump(make_dump()), on=ON), True)
os.environ[trae_credits.CLAIM_AFTER_ENV] = "not-a-number"
check("领取时刻写坏了不拦（宁可不改行为）",
      trae_credits.is_fresh(trae_credits.parse_dump(make_dump()), on=ON), True)
os.environ.pop(trae_credits.CLAIM_AFTER_ENV, None)

# dump 缺失 → 抛错而不是静默返回 0 余额
try:
    trae_credits.load_dump(tmp / "not-there.json")
    check("dump 缺失报错", "no raise", "CreditQueryError")
except trae_credits.CreditQueryError:
    check("dump 缺失报错", "CreditQueryError", "CreditQueryError")

# ---------- 对账：Trae 载荷写进账本 ----------
data = ledger.load()
ledger.grant(data, "trae", 3541, "daily", date(2026, 10, 19))
acc = {"id": "trae", "name": "Trae"}
applied = checkin._apply_sync_payload(acc, trae_credits.payload(parsed), data, ON)
check("Trae 对账走逐条写入", applied["mode"], "grants")
check("Trae 对账后余额", applied["after"], 3629)
entries = ledger.active_entries(data, "trae", ON)
check("Trae 账本条目带真实到期日", entries[0]["expires_at"], "2026-10-31")
check("Trae 账本条目来源是 sync", entries[0]["source"], "sync")
check("Trae 旧条目已置零",
      sum(int(e["remaining"] or 0) for e in ledger.state(data, "trae")["entries"]
          if e["source"] == "daily"), 0)

# ---------- 对账成功要记下新鲜度 ----------
ledger.mark_synced(data, "trae")
check("对账时间被记录", bool(ledger.state(data, "trae").get("last_sync")), True)

# ---------- 看板 ----------
b = board.build(data=data, on=ON)
row = next(r for r in b["accounts"] if r["id"] == "trae")
check("看板余额与账本一致", row["remaining"], 3629)
check("看板笔数", row["grant_count"], 1)
check("看板最近过期", row["soonest_expiry"], "2026-10-31")
check("看板剩余天数", row["days_left"], 11)
check("看板口径=服务端真值", row["quality"], "server")
check("看板过期口径=服务端", row["expiry_basis"], "server")
check("看板带对账时间", bool(row["last_sync"]), True)

# 临期队列只收 0..7 天
check("临期队列不含 11 天后的",
      [g["account_id"] for g in b["near_expiry"] if g["account_id"] == "trae"], [])

# 制造一条 3 天内到期的条目（本地登记 = 估算口径），验证它进临期队列且把账户顶到 T1
soon = (ON + timedelta(days=3)).isoformat()
ledger.grant(data, "minimax", 400, "daily", date(2026, 10, 20), ledger.parse_date(soon))
b2 = board.build(data=data, on=ON)
mm = next(r for r in b2["accounts"] if r["id"] == "minimax")
check("本地估算账户口径=estimate", mm["quality"], "estimate")
check("本地估算账户过期口径=estimate", mm["expiry_basis"], "estimate")
check("临期队列收到 3 天内的条目",
      [g["remaining"] for g in b2["near_expiry"] if g["account_id"] == "minimax"], [400])
check("临期账户升到 T1", mm["tier"], 1)
check("T1 排在 T2 前面",
      b2["burn_order"].index("minimax") < b2["burn_order"].index("trae"), True)

# 看板与 recommend 用同一套层级口径
ledger.save(data)   # recommend 自己从盘上读账本，先落盘
# ⚠️ 必须传 on=ON：recommend 默认用「真实今天」算临期，而本文件的夹具是固定在 ON 的。
# 不传 on 的话，夹具条目（ON+3 天）过了真实今天就会变成「已过期」，
# 断言会随日期一天天烂掉（2026-10-23 起必挂，与被测代码无关）。
rec = recommend("重构这个仓库", on=ON)
check("recommend 也能看到临期积分", any(e["account_id"] == "minimax" for e in rec["expiring"]), True)
check("看板与 recommend 的层级一致",
      priority.tier({"id": "minimax", "grant_type": "accumulating", "validity_days": 30},
                    data, ON), 1)

# Markdown 渲染 + 落盘
md = board.format_markdown(b2)
check("Markdown 含账户表", "## 账户总表" in md, True)
check("Markdown 含逐条明细", "## 逐条明细" in md, True)
check("Markdown 含烧卡优先级", "## 烧卡优先级" in md, True)
paths = board.write(b2, out=tmp / "board.md")
check("看板落盘到指定路径", paths["markdown"].is_file(), True)
check("看板 JSON 落盘", paths["json"].is_file(), True)
check("看板 JSON 可解析", isinstance(json.loads(paths["json"].read_text(encoding="utf-8")), dict), True)

# 单账户视图不能覆盖全量看板产物（否则「看一眼某一家」会冲掉当天的全量看板）
scoped = board.build(data=data, on=ON, account="trae")
check("单账户视图只有该账户", [a["id"] for a in scoped["accounts"]], ["trae"])
scoped_paths = board.write(scoped)
check("单账户视图写自己的 Markdown",
      scoped_paths["markdown"].name, f"board-{ON.isoformat()}-trae.md")
check("单账户视图另存 JSON", scoped_paths["json"].name, "board-trae.json")
full_again = json.loads(paths["json"].read_text(encoding="utf-8"))
check("共享 JSON 仍是全量视图", len(full_again["accounts"]) > 1, True)

# 渲染不能因为缺字段崩掉
empty = board.build(data=ledger.load(), on=ON)
check("空账本也能渲染", isinstance(board.format_text(empty), str), True)

# ---------- checkin 末尾自动刷看板 ----------
# 看板目录指到临时目录，测试不往真 logs/ 里写
board.BOARD_DIR = tmp / "board"
os.environ.pop("AGENT_CREDIT_SKIP_EXTERNAL", None)
os.environ.pop("AGENT_CREDIT_SKIP_SYNC", None)
checkin._refresh_board(data, ON)
refreshed = list((tmp / "board").glob("board-*.md"))
check("checkin 末尾会刷看板", len(refreshed), 1)
check("看板文件名带日期", refreshed[0].name, f"board-{ON.isoformat()}.md")

# 开关打开时不该写（测试环境不产生副产物）
for p in (tmp / "board").glob("board-*.md"):
    p.unlink()
os.environ["AGENT_CREDIT_SKIP_EXTERNAL"] = "1"
checkin._refresh_board(data, ON)
check("跳过对账时不刷看板", len(list((tmp / "board").glob("board-*.md"))), 0)
del os.environ["AGENT_CREDIT_SKIP_EXTERNAL"]

print("")
print("FAIL count =", bad)
raise SystemExit(1 if bad else 0)
