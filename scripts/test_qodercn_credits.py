#!/usr/bin/env python3
"""qodercn_credits 回归：日志解析 + 新鲜度闸门 + 对账契约。

为什么需要：这个模块从客户端自己落的 main.log 里抓用量响应，字段一漂移就会
**静默少一桶或多算一桶**；而它的危险动作是「把签到后的真实余额覆盖成旧值」
（Trae 2026-10-20 踩过 stale dump）。所以解析形状与闸门两头都要钉住。

夹具用的是 2026-10-16 08:45:37 那条真实日志（含年 9999 的 expiresAt 哨兵）。

用法：python scripts/test_qodercn_credits.py
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from agent_credit import qodercn_credits as qc  # noqa: E402
from agent_credit.console import use_utf8  # noqa: E402

use_utf8()

bad = 0


def check(label: str, got, expect) -> None:
    global bad
    ok = got == expect
    if not ok:
        bad += 1
    print(f"{'ok  ' if ok else 'FAIL'} {label}"
          + ("" if ok else f"\n      got:    {got!r}\n      expect: {expect!r}"))


# ---------- 真实夹具（2026-10-16T00:45:37.959Z = 本地 08:45:37）----------
REAL_LINE = (
    "[2026-10-16T00:45:37.959Z] [INFO] [main] [Auth] [AccountUsage] 用量响应摘要 "
    '{"operation":"account.getQuotaUsage","requestId":"670255af-95da","method":"GET",'
    '"path":"/sash/api/v2/me/usage","host":"openapi.qoder.com.cn","status":200,'
    '"durationMs":89,"displayMode":"qoder","hasQoderUsage":true,"hasEnterpriseUsage":false,'
    '"qoderUsage":{"userType":"invalid","usageType":"credits","expiresAt":253402214400000,'
    '"totalUsagePercentage":0,"isQuotaExceeded":false,"isPlanQuotaProrated":false,'
    '"userQuota":{"total":0,"used":0,"remaining":0,"percentage":0,"cap":"missing",'
    '"available":"missing","unit":"credits"},'
    '"addOnQuota":{"total":300,"used":0,"remaining":300,"percentage":0,"cap":"missing",'
    '"available":"missing","unit":"credits"},'
    '"orgResourcePackage":"missing","dedicatedResourcePackageCount":"missing"},'
    '"enterpriseUsage":"missing"}'
)


def make_log(tmp: Path, session: str, lines: list[str]) -> Path:
    d = tmp / "logs" / session
    d.mkdir(parents=True, exist_ok=True)
    path = d / "main.log"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def with_roots(tmp: Path):
    """把日志根指向临时目录（find_usage_record 只经这两个函数摸文件系统）。"""
    qc._log_roots = lambda: [tmp]


tmp = Path(tempfile.mkdtemp())
with_roots(tmp)

# ---------- 解析 ----------
make_log(tmp, "20261016-003747.141-32792-aaaa", ["[x] 无关行", REAL_LINE])
rec = qc.find_usage_record()
check("抓到桶数量（个人号只有 user/addOn 两桶是对象）", [b["key"] for b in rec["buckets"]],
      ["userQuota", "addOnQuota"])
check("addOnQuota 剩余 300", rec["buckets"][1]["remaining"], 300)
check("总量=桶合计", qc.total_remaining(rec), 300)
check("记录本地时间", rec["recorded_at"], "2026-10-16 08:45:37")
check("记录日期", rec["recorded_date"], "2026-10-16")
check("missing 桶不进 buckets", "orgResourcePackage" in [b["key"] for b in rec["buckets"]], False)
check("missing 值仍留档", rec["raw_extra"].get("orgResourcePackage"), "missing")

# ---------- 年 9999 哨兵绝不能登记成日期 ----------
check("expiresAt 哨兵 -> None", rec["plan_expires"], None)
check("哨兵毫秒确实是大数（防误改成 int 比较）", 253402214400000 > 1e14, True)
check("epoch_ms 正常值", qc.epoch_ms_to_date(1764460800000),
      datetime.fromtimestamp(1764460800).date().isoformat())
check("epoch_ms 拒收 bool", qc.epoch_ms_to_date(True), None)
check("epoch_ms 拒收 0", qc.epoch_ms_to_date(0), None)

# ---------- 对账载荷：服务端只有桶总数 -> 走 reconcile，不写 grants ----------
lp = qc.ledger_payload(rec)
check("ledger account", lp["account"], "qodercn")
check("ledger total", lp["total"], 300)
check("走 reconcile 契约", lp["reconcile"], "fifo")
check("绝不带 grants（带了你就会把逐日批次压成一条无过期条目）", "grants" in lp, False)
check("分桶拆解随载荷带出（供日志追溯）",
      [b["name"] for b in lp["buckets"]], ["套餐内 Credits", "资源包（Add-on Credits）"])
check("资源包桶数值", lp["buckets"][1]["remaining"], 300)
check("载荷中文走 ASCII 转义（cmd 的 GBK 控制台不拆坏）",
      "\\u8d44\\u6e90\\u5305" in json.dumps(lp, ensure_ascii=True), True)

# ---------- 有套餐内余额时：总量=两桶之和 ----------
PLAN_LINE = REAL_LINE.replace('"userQuota":{"total":0,"used":0,"remaining":0',
                              '"userQuota":{"total":1000,"used":400,"remaining":600') \
                      .replace('"expiresAt":253402214400000', '"expiresAt":1764460800000')
make_log(tmp, "20261016-003747.141-32792-aaaa", [PLAN_LINE])
rec2 = qc.find_usage_record()
check("两桶都计入总量", qc.total_remaining(rec2), 900)
check("plan 到期日照带出（供人看，不参与登记）",
      qc.ledger_payload(rec2)["plan_expires"], qc.epoch_ms_to_date(1764460800000))

# ---------- 新鲜度闸门（stale 会把签到后的余额覆盖成旧值）----------
check("昨天记录判为不新鲜", qc.is_fresh(rec2, datetime(2026, 10, 17).date()), False)
check("同日记录判为新鲜", qc.is_fresh(rec2, datetime(2026, 10, 16).date()), True)
check("无时间戳判为不新鲜", qc.is_fresh({"recorded_date": None}), False)

# 行首时间戳按日志约定是 UTC（带 Z），夹具也必须用 UTC 现刻，否则 +8 会翻到次日
today_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")
make_log(tmp, "20261016-003747.141-32792-aaaa",
         [REAL_LINE.replace("2026-10-16T00:45:37.959Z", today_iso)])
check("当天记录闸门放行", qc.is_fresh(qc.find_usage_record()), True)

# ---------- 坏行/缺行的降级 ----------
make_log(tmp, "20261016-003747.141-32792-aaaa",
         ["[2026-10-16T00:45:37.959Z] [Auth] [AccountUsage] 用量响应摘要 {\"qoderUsage\":{",
          "[2026-10-16T00:45:37.959Z] [Auth] [AccountUsage] 用量查询开始 无 JSON"])
try:
    qc.find_usage_record()
    check("截断/缺 qoderUsage 的行会被跳过 -> 报错", "no raise", "CreditQueryError")
except qc.CreditQueryError:
    check("截断/缺 qoderUsage 的行会被跳过 -> 报错", "CreditQueryError", "CreditQueryError")

make_log(tmp, "20261016-003747.141-32792-aaaa", [REAL_LINE])
nested = tmp / "logs" / "20261020-000000.000-1-bbbb"
nested.mkdir(parents=True, exist_ok=True)
(nested / "main.log").write_text(
    "[2026-10-20T00:00:01.000Z] [Auth] [AccountUsage] 用量响应摘要 "
    '{"qoderUsage":{"userType":"pro","userQuota":{"total":10,"used":0,"remaining":10},'
    '"addOnQuota":{"total":5,"used":0,"remaining":5}}}', encoding="utf-8")
newest = qc.find_usage_record()
check("新会话优先于旧会话", newest["user_type"], "pro")
check("会话出处", "20261020-000000.000-1-bbbb" in newest["origin"], True)

# ---------- 轮转日志：记录被挤进 main.1.log 也要读得到（2026-10-31 实踩）----------
rot = tmp / "logs" / "20261031-000000.000-9-cccc"
rot.mkdir(parents=True, exist_ok=True)
(rot / "main.log").write_text("[2026-10-31T00:01:00.000Z] [Auth] 普通日志\n",
                              encoding="utf-8")
rotated = rot / "main.1.log"
rotated.write_text(
    "[2026-10-31T00:07:06.000Z] [Auth] [AccountUsage] 用量响应摘要 "
    '{"qoderUsage":{"userType":"rotated","userQuota":{"total":0,"used":0,"remaining":0},'
    '"addOnQuota":{"total":1600,"used":307,"remaining":1293}}}', encoding="utf-8")
now = datetime.now().timestamp()
os.utime(rot / "main.log", (now - 120, now - 120))
os.utime(rotated, (now + 5, now + 5))
rot_rec = qc.find_usage_record()
check("轮转文件里的记录也能读到", qc.total_remaining(rot_rec), 1293)
check("轮转记录带出会话出处", rot_rec["origin"], "20261031-000000.000-9-cccc")

# ---------- 签到态（[Campaign] claimable）----------
check("无活动下发 -> 未知", qc.claimed_today({"show_campaign": False, "claimable": False}), None)
check("活动可见且 claimable=false -> 已领",
      qc.claimed_today({"show_campaign": True, "claimable": False}), True)
check("活动可见且 claimable=true -> 未领",
      qc.claimed_today({"show_campaign": True, "claimable": True}), False)
check("没有 Campaign 行 -> 未知", qc.claimed_today(None), None)

camp_line = ('[2026-10-20T00:00:02.000Z] [INFO] [main] [Campaign] 活动状态响应解析完成 '
             '{"normalizationResult":"accepted","durationMs":75,"showCampaign":true,'
             '"claimable":false}')
cache_line = ('[2026-10-20T00:00:03.000Z] [INFO] [main] [Campaign] 活动状态使用缓存 '
              '{"expiresInMs":196255,"showCampaign":true,"claimable":true}')
make_log(tmp, "20261020-000000.000-1-bbbb", [camp_line, cache_line])
camp = qc.find_campaign_state()
check("优先取服务端态而非缓存态", (camp["source"], camp["claimable"]), ("server", False))

# ---------- 人类可读输出如实声明局限 ----------
text = qc.format_text(rec, None)
check("输出含总剩余", "总剩余: 300" in text, True)
check("输出声明逐条拿不到", "逐条" in text and "拿不到" in text, True)
check("输出不含凭据字样", all(k not in text.lower() for k in
                          ("token", "cookie", "authorization")), True)

print("")
print("FAIL count =", bad)
raise SystemExit(1 if bad else 0)
