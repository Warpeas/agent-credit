#!/usr/bin/env python3
"""wb_credits 回归测试：解析器 + body 形状 + 分页 + 去重 + CLI 接线。

为什么需要：这套查询的判据全是**字段名与端点形状**，服务端一改字段名，
症状是静默失真（remain 变 None、少算总量），不报错。所以形状断言必须钉死。
样本字段来自 2026-10-19 实测响应（值已脱敏替换，无真实账号数据）。

用法：python scripts/test_wb_credits.py
"""
from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from agent_credit import wb_credits as wb  # noqa: E402


class FakeVendor:
    CODE_NO_NETWORK = -1


def ms(dt: datetime) -> int:
    return int(dt.timestamp() * 1000)


bad = 0


def check(label: str, got, expect) -> None:
    global bad
    ok = got == expect
    if not ok:
        bad += 1
    print(f"{'ok  ' if ok else 'FAIL'} {label}"
          + ("" if ok else f"\n      got:    {got!r}\n      expect: {expect!r}"))


# ---------- fmt_time ----------
check("fmt_time epoch ms", wb.fmt_time(ms(datetime(2026, 9, 20, 1, 9, 41))),
      "2026-09-20 01:09:41")
check("fmt_time epoch ms 字符串", wb.fmt_time(str(ms(datetime(2026, 10, 27, 12, 0, 0)))),
      "2026-10-27 12:00:00")
check("fmt_time 10 位秒级", wb.fmt_time(int(datetime(2026, 10, 1, 0, 0, 0).timestamp())),
      "2026-10-01 00:00:00")
check("fmt_time 日期字符串原样", wb.fmt_time("2026-10-20 01:09:39"), "2026-10-20 01:09:39")
check("fmt_time None", wb.fmt_time(None), None)
check("fmt_time 空串", wb.fmt_time(""), None)
check("fmt_time 零值", wb.fmt_time(0), None)

# ---------- grant_capacity ----------
check("capacity Precise 优先",
      wb.grant_capacity({"CapacityRemainPrecise": "100", "CapacitySizePrecise": "100"}),
      (100.0, 100.0))
check("capacity Cycle 优先于包级（CapacityType=4 套餐配额）",
      wb.grant_capacity({
          "CapacityType": 4,
          "CapacityRemainPrecise": "500", "CapacitySizePrecise": "500",
          "CycleCapacityRemainPrecise": "212.9900019",
          "CycleCapacitySizePrecise": "500",
      }),
      (212.9900019, 500.0))
check("capacity slice 详情最优先（CapacityType=4 且两者都在时）",
      wb.grant_capacity({
          "CapacityType": 4,
          "CycleCapacityRemainPrecise": "300", "CycleCapacitySizePrecise": "500",
          "SlicePeriodUsageDetails": [
              {"SlicePeriodCapacityRemainPrecise": "212.99",
               "SlicePeriodCapacitySizePrecise": "500"}],
      }),
      (212.99, 500.0))
check("capacity 非 slice 类型不看 SlicePeriodUsageDetails",
      wb.grant_capacity({
          "CapacityType": 1,
          "CapacityRemainPrecise": "100", "CapacitySizePrecise": "100",
          "SlicePeriodUsageDetails": [
              {"SlicePeriodCapacityRemainPrecise": "1",
               "SlicePeriodCapacitySizePrecise": "2"}],
      }),
      (100.0, 100.0))
check("capacity Cycle 回落",
      wb.grant_capacity({"CycleCapacityRemainPrecise": "7",
                         "CycleCapacitySizePrecise": "100"}),
      (7.0, 100.0))
check("capacity 整数字段回落",
      wb.grant_capacity({"CapacityRemain": 9, "CapacitySize": 100}),
      (9.0, 100.0))
check("capacity 全空", wb.grant_capacity({}), (None, None))

# 2026-10-19 实测原始记录（code_008 个人体验版，CapacityType=4）固化回归：
# 包级 CapacityRemainPrecise=500 是未扣减的包总量，真余量在 Cycle 字段。
# 账号类字段（Uin/DealName/AccountId）已替换为测试值，容量字段原样保留。
RAW_008 = {
    "AccountId": 0, "Uin": "test-uin", "AppId": 0, "DealName": "test-deal",
    "CapacityType": 4, "CapacityUnit": "credits",
    "CreateTime": 1781620351000,
    "CycleStartTime": "2026-10-01 00:00:00", "CycleEndTime": "2026-10-31 23:59:59",
    "DeductionStartTime": 1781620350000, "DeductionEndTime": 2042029949000,
    "PackageCode": "TCACA_code_008_cfWoLwvjU4", "PackageName": "CodeBuddy个人体验版",
    "CapacityRemain": 500, "CapacityUsed": 0, "CapacitySize": 500,
    "CycleCapacityRemain": 212, "CycleCapacitySize": 500, "CycleCapacityUsed": 287,
    "ResourceId": "codebuddy-test0009", "Status": 0,
    "CapacitySizePrecise": "500", "CapacityRemainPrecise": "500",
    "CapacityUsedPrecise": "0",
    "CycleCapacitySizePrecise": "500", "CycleCapacityRemainPrecise": "212.9900019",
    "CycleCapacityUsedPrecise": "287.0099981",
}
g008 = wb.normalize_grant(RAW_008, "free")
check("实测 008 记录：余量取 Cycle 字段", (g008["remain"], g008["total"]),
      (212.9900019, 500.0))
check("实测 008 记录：周期结束", g008["cycle_end"], "2026-10-31 23:59:59")
check("实测 008 记录：过期取 DeductionEndTime", g008["deduction_end"],
      "2034-09-16 22:32:29")

# ---------- normalize_grant ----------
BASE_RAW = {
    "ResourceId": "codebuddy-test0001",
    "PackageCode": "TCACA_code_007_nzdH5h4Nl0",
    "PackageName": "CodeBuddy个人版国内运营裂变包",
    "Status": 0,
    "CapacityRemainPrecise": "100",
    "CapacitySizePrecise": "100",
    "DeductionEndTime": ms(datetime(2026, 10, 27, 12, 0, 0)),
    "ExpiredTime": "",
    "CycleStartTime": "2026-09-20 01:09:40",
    "CycleEndTime": "2026-10-20 01:09:39",
    "CreateTime": ms(datetime(2026, 9, 20, 1, 9, 41)),
    "AccountAttributes": [
        {"Key": "payerType", "Value": "0", "Type": 5},
        {"Key": "grantReason", "Value": "官方活动发放", "Type": 0},
    ],
}
g = wb.normalize_grant(BASE_RAW, "free")
check("grant 过期取 DeductionEndTime", g["expire_at"], "2026-10-27 12:00:00")
check("grant deduction_end", g["deduction_end"], "2026-10-27 12:00:00")
check("grant cycle_end 原样", g["cycle_end"], "2026-10-20 01:09:39")
check("grant 发放原因", g["grant_reason"], "官方活动发放")
check("grant 状态标签", g["status_label"], "有效")
check("grant 剩余/总量", (g["remain"], g["total"]), (100.0, 100.0))
check("grant 来源", g["source"], "free")

r2 = dict(BASE_RAW, DeductionEndTime=None, ExpiredTime="2026-10-06 18:10:02")
check("过期优先级 ExpiredTime 次选",
      wb.normalize_grant(r2, "free")["expire_at"], "2026-10-06 18:10:02")
r3 = dict(BASE_RAW, DeductionEndTime=None, ExpiredTime="")
check("过期优先级 CycleEndTime 兜底",
      wb.normalize_grant(r3, "free")["expire_at"], "2026-10-20 01:09:39")
check("状态标签 usedUp",
      wb.normalize_grant(dict(BASE_RAW, Status=3), "free")["status_label"], "已用完")
check("状态标签 expired",
      wb.normalize_grant(dict(BASE_RAW, Status=2), "free")["status_label"], "已过期")

# ---------- parse_summary ----------
s = wb.parse_summary({
    "TotalCredits": "2716.9900019",
    "IsPaidUser": False,
    "SubscriptionPackageName": "体验版",
    "Packages": [
        {"PackageCode": "TCACA_code_007_nzdH5h4Nl0", "CycleTotalCapacity": "5041",
         "CycleRemainCapacity": "2504", "CycleUsedCapacity": "2537",
         "CycleFrozenCapacity": "0", "TotalCount": 70},
    ],
    "CreditGroups": [
        {"Kind": "plan_base", "Name": "套餐基础积分", "CycleTotalCapacity": "500",
         "CycleRemainCapacity": "212.9900019", "CycleUsedCapacity": "287.0099981",
         "CycleFrozenCapacity": "0", "TotalCount": 1},
        {"Kind": "benefit", "Name": "平台奖励积分", "CycleTotalCapacity": "5041",
         "CycleRemainCapacity": "2504", "CycleUsedCapacity": "2537",
         "CycleFrozenCapacity": "0", "TotalCount": 70},
    ],
})
check("summary 总量", s["total_credits"], 2716.9900019)
check("summary 分组数", len(s["groups"]), 2)
check("summary 分组名中文化", s["groups"][0]["name"], "套餐基础积分")
check("summary 分组剩余", s["groups"][0]["remain"], 212.9900019)
check("summary 逐包", s["packages"][0]["cycle_remain"], 2504.0)
check("summary 付费标记", s["is_paid_user"], False)

# ---------- _page_body（客户端形状钉死） ----------
free_body = wb._page_body(wb.FREE_PACKAGE_CODES, 1,
                          {"SlicePeriodStartTime": "2026-10-19 00:00:00",
                           "SlicePeriodEndTime": "2026-10-19 23:59:59"})
check("free body 形状", free_body, {
    "PageNumber": 1, "PageSize": 200, "PackageCodes": wb.FREE_PACKAGE_CODES,
    "Status": [0, 3], "IsDisplayTotalInfo": True,
    "SlicePeriodStartTime": "2026-10-19 00:00:00",
    "SlicePeriodEndTime": "2026-10-19 23:59:59"})
paid_body = wb._page_body(wb.PAID_PACKAGE_CODES, 2, {"NeedRenewInfo": True})
check("paid body 形状", paid_body, {
    "PageNumber": 2, "PageSize": 200, "PackageCodes": wb.PAID_PACKAGE_CODES,
    "Status": [0, 3], "IsDisplayTotalInfo": True, "NeedRenewInfo": True})
check("PageSize 与客户端一致", wb.PAGE_SIZE, 200)
check("Status 枚举顺序（valid+usedUp）", free_body["Status"], [0, 3])

# ---------- code 列表 ----------
check("付费组 = asar Ys 11 项", len(wb.PAID_PACKAGE_CODES), 11)
check("付费组无重复", len(set(wb.PAID_PACKAGE_CODES)), 11)
check("免费组含 008（套餐配额记录）",
      "TCACA_code_008_cfWoLwvjU4" in wb.FREE_PACKAGE_CODES, True)
check("免费组无重复", len(set(wb.FREE_PACKAGE_CODES)), len(wb.FREE_PACKAGE_CODES))

# ---------- fetch_packages 分页 / 截断 ----------
def _grant(i: int, status: int = 0) -> dict:
    return {"ResourceId": f"codebuddy-test{i:04d}", "PackageCode": "TCACA_code_007",
            "PackageName": "测试包", "Status": status,
            "CapacityRemainPrecise": "10", "CapacitySizePrecise": "100",
            "DeductionEndTime": ms(datetime(2026, 10, 27, 12, 0, 0))}


calls: list[tuple[str, dict]] = []


def fake_post_paged(vendor, url, headers, payload):
    """替身层的 _post：直接返回 data 字典（真实 _post 的返回形态）。"""
    calls.append((url, payload))
    page = payload["PageNumber"]
    if url.endswith(wb.FREE_PATH):
        if page == 1:
            return {"Accounts": [_grant(i) for i in range(200)], "TotalCount": 250}
        return {"Accounts": [_grant(i) for i in range(200, 250)], "TotalCount": 250}
    raise wb.CreditQueryError("404 Route Not Found")


wb._post = fake_post_paged
grants = wb.fetch_packages(FakeVendor(), "https://ep", {}, wb.FREE_PATH,
                           wb.FREE_PACKAGE_CODES, {})
check("分页取满 250 条", len(grants), 250)
check("无截断标记", any(x.get("_truncated") for x in grants), False)
check("第二页确实发出", [p["PageNumber"] for _, p in calls], [1, 2])


def fake_post_over(vendor, url, headers, payload):
    return {"Accounts": [_grant(i) for i in range(200)], "TotalCount": 2500}


wb._post = fake_post_over
grants = wb.fetch_packages(FakeVendor(), "https://ep", {}, wb.FREE_PATH,
                           wb.FREE_PACKAGE_CODES, {})
check("超过 MAX_PAGES 截断", len(grants), wb.MAX_PAGES * wb.PAGE_SIZE + 1)
check("截断标记带回", grants[-1].get("_truncated"), True)
check("截断总数标注", grants[-1].get("_total"), 2500)

# ---------- fetch_credits 去重（code_008 双列表） ----------
dup_a = _grant(1)
dup_b = _grant(2)


def fake_post_routes(vendor, url, headers, payload):
    if url.endswith(wb.SUMMARY_PATH):
        return {"TotalCredits": "100", "CreditGroups": [], "Packages": []}
    if url.endswith(wb.FREE_PATH):
        return {"Accounts": [dup_a], "TotalCount": 1}
    if url.endswith(wb.PAID_PATH):
        return {"Accounts": [dup_a, dup_b], "TotalCount": 2}
    raise wb.CreditQueryError("404 Route Not Found")


wb._post = fake_post_routes
wb._session_and_headers = lambda: (FakeVendor(), {"Accept-Language": "zh"}, "https://ep")
result = wb.fetch_credits()
check("去重后 2 条", len(result["grants"]), 2)
check("去重按 ResourceId",
      sorted(x["resource_id"] for x in result["grants"]),
      sorted({dup_a["ResourceId"], dup_b["ResourceId"]}))

# ---------- format_text ----------
text_result = {
    "queried_at": "2026-10-19 22:30:00",
    "summary": {"total_credits": 2716.99, "is_paid_user": False,
                "subscription_package_name": "体验版",
                "groups": [{"kind": "benefit", "name": "平台奖励积分", "total": 5041.0,
                            "remain": 2504.0, "used": 2537.0, "frozen": 0.0,
                            "count": 70.0}],
                "packages": []},
    "grants": [
        dict(_g := wb.normalize_grant(_grant(1), "free"),
             expire_at="2026-10-25 08:00:00"),
        wb.normalize_grant(_grant(2), "free"),  # expire 2026-10-27
        wb.normalize_grant(_grant(3, status=3), "free"),
    ],
    "truncated": [],
}
text = wb.format_text(text_result, show_all=False)
check("默认按过期排序", text.index("2026-10-25") < text.index("2026-10-27"), True)
check("默认隐藏已用完条目", "[已用完]" in text, False)
check("默认提示另有条目", "另有 1 条" in text, True)
check("总量展示", "2716.99" in text, True)
text_all = wb.format_text(text_result, show_all=True)
check("--all 展示已用完", "[已用完]" in text_all, True)
trunc_result = dict(text_result, truncated=[{"source": "free", "fetched": 2000,
                                             "total": 2500}])
check("截断告警", "分页截断" in wb.format_text(trunc_result), True)

# ---------- 对账不变量：有效 grant 剩余合计 == summary 总量 ----------
# 2026-10-19 实测：2504（44 条活动积分）+ 212.99（套餐配额）= 2716.99 = TotalCredits。
# 容量优先级一旦搞错（如把 008 的包总量 500 当余量），这个等式立刻破——固化为回归。
inv_grants = [
    wb.normalize_grant(dict(_grant(1), CapacityRemainPrecise="100",
                            CycleCapacityRemainPrecise="100",
                            CycleCapacitySizePrecise="100"), "free"),
    wb.normalize_grant(RAW_008, "free"),
]
inv_summary = wb.parse_summary({"TotalCredits": "312.9900019",
                                "CreditGroups": [], "Packages": []})
check("对账不变量：有效剩余合计 == summary 总量",
      round(sum(g["remain"] or 0 for g in inv_grants), 6),
      round(inv_summary["total_credits"], 6))

# ---------- CLI 接线 ----------
from agent_credit.cli import build_parser  # noqa: E402

args = build_parser().parse_args(["credits"])
check("credits 默认账户", args.account, "workbuddy")
check("credits 标志位齐全",
      [f for f in ("all", "json", "line")
       if hasattr(build_parser().parse_args(
           ["credits", "workbuddy", "--all", "--json", "--line"]), f)],
      ["all", "json", "line"])
check("credits 指定账户",
      build_parser().parse_args(["credits", "minimax"]).account, "minimax")

print("")
print("FAIL count =", bad)
raise SystemExit(1 if bad else 0)
