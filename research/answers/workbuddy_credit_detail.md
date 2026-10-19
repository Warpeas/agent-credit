# WorkBuddy 积分明细 · 探索答案

| 项 | 值 |
|---|---|
| 账户 id | `workbuddy`（明细查询挂在同账户下，不新开账户） |
| 状态 | **已打通**（2026-10-19，只读查询） |
| 置信度 | high（端点来自客户端二进制只读提取 + 同日实测 200） |

把结论原样存底。`evidence` 段无 token / cookie / 密码明文（已过
`scripts/check_research_answers.py`）。复跑方式见文末。

```yaml
account_id: workbuddy
software: WorkBuddy 积分明细查询
version: "桌面端 app.asar 构建于 2026-10-15（文件时间戳）"
researched_at: 2026-10-19
confidence: high

checkin:
  supported: true
  api: "POST /v2/billing/meter/checkin-activity-status + POST /v2/billing/meter/daily-checkin（vendor/workbuddy-auto-signin，未变）"
  daily_amount: 100
  validity_days: 30
  idempotent: true

status:
  balance: "POST /billing/meter/get-user-resource-summary —— TotalCredits + CreditGroups（套餐基础/套餐赠送/购买/平台奖励 四组，各带周期容量）+ Packages（逐 PackageCode 周期容量）"
  per_grant_detail: "POST /billing/meter/get-user-resource-free-packages 与 /get-user-resource-paid-packages —— 每条积分 grant 一条资源记录：CapacityRemainPrecise（剩余）、CapacitySizePrecise（总量）、DeductionEndTime（过期，epoch ms）、CycleEndTime（周期结束）、Status（0 有效/1 退款/2 过期/3 用完）、AccountAttributes.grantReason（发放原因）。⚠️ 余量优先级对齐客户端 resolveResourceCapacity：CapacityType=4 套餐配额的真余量在 CycleCapacityRemainPrecise，包级 CapacityRemainPrecise 是未扣减的包总量（实测 008 记录：包级 500 vs Cycle 212.99，后者才等于 summary 分组值）"
  claimed_today: "POST /v2/billing/meter/checkin-activity-status → data.today_checked_in"
  unit: credit

validity:
  days: 30
  confidence: confirmed
  evidence: "逐条 grant 的 DeductionEndTime - CreateTime = 30 天（2026-10-19 实测 44 条有效样本；例：CreateTime 1789837781000 → DeductionEndTime 1792429779000，差 2591999 秒 ≈ 30 天）。catalog validity_audit 同月从 measured 升级为 confirmed"

automation:
  claim_mode: external
  command: "（不变，见 catalog）"
  credits_command: "credit credits workbuddy [--all|--json|--line]；等价 python -m agent_credit.wb_credits"
  status_command: "set PYTHONPATH={REPO}&& python -m agent_credit.wb_credits --line（输出 {\"balance\": N, \"claimed_today\": bool}，catalog 预留字段语义）"
  blockers: "无。凭据复用签到路线：明文 token 或由 WorkBuddy 客户端进程自行解密 sym-v1 信封（vendor 脚本机制，本模块不实现解密）"
  reliability: 已实测

evidence:
  - "app.asar 只读字符串（未执行未改写）：fetchAccountUsage → getPersonalUsage(endpoint) → fetchResourceSummary(prefix)，证明资源类端点前缀就是 endpoint 本身、不带 /v2"
  - "app.asar：queryCreditPackages 的 paid/free 分流与 Ys 付费组 11 个 PackageCode；Status 枚举 ds（valid=0/refund=1/expired=2/usedUp=3）；toExpiredCreditPackage 的过期优先级 DeductionEndTime→ExpiredTime→CycleEndTime"
  - "app.asar：buildSlicePeriodRange（当天 00:00:00-23:59:59）与 IsDisplayTotalInfo/NeedRenewInfo 参数形状"
  - "2026-10-19 实测：summary 200，TotalCredits=2716.99，CreditGroups 四组（平台奖励 5041/剩 2504，套餐基础 500/剩 212.99）"
  - "2026-10-19 实测：free-packages 200，70 条资源（44 条 Status=0 剩余合计 2504；26 条 Status=3 已用完）；paid-packages 200，0 条（本账号无购买记录）"
  - "2026-10-19 实测：free-packages 带 code_008 时返回 CapacityType=4 的套餐配额记录（CycleStartTime 2026-10-01，CycleEndTime 2026-10-31 23:59:59）"
  - "2026-10-19 实测：该 008 记录的原始字段——CapacityRemainPrecise=500（未扣减包总量）而 CycleCapacityRemainPrecise=212.9900019（真余量，等于 summary 的 plan_base 分组值）；响应中无 SlicePeriodUsageDetails 字段，客户端 slice 分支实际走的是 Cycle 回落。对账等式：44 条活动积分剩 2504 + 套餐配额 212.99 = 2716.99 = TotalCredits"

open_questions:
  - "paid-packages 对本账号恒 0，购买积分的逐条形态（是否多周期/自动续费字段）未验证"
  - "expiredCreditPackages 形态端点（Status [2,3] + PackageEndTimeRange + OrderBy endTime desc）已从二进制提取但未调用——当前 --all 的已用完/已过期条目已由 free/paid 端点的 Status=[0,3] 覆盖，无需再调"
  - "【已解决】CapacityType=4 套餐配额的余量字段：不在 SlicePeriodUsageDetails（响应里没有该字段），在 CycleCapacityRemainPrecise。曾据包级 CapacityRemainPrecise 把 500 当成余量，被对账等式（有效剩余合计 == TotalCredits）抓住，已修并固化回归用例"

catalog_patch:
  workbuddy:
    validity_days: 30
    status_command: "set PYTHONPATH={REPO}&& python -m agent_credit.wb_credits --line"
    notes: "（已追加积分明细查询段，含端点、坑、失效条件）"
```

## 端点契约（复跑照这个抄）

全部只读。凭据 = 签到同款（`workbuddy-desktop.info`，运行时读取，不落盘不打印）；
请求头在签到 Bearer 基础上加 `Accept-Language: zh`。

| 端点 | body | 说明 |
|---|---|---|
| `POST {endpoint}/billing/meter/get-user-resource-summary` | `{}` | 总量 + 四分组 + 逐包周期容量 |
| `POST {endpoint}/billing/meter/get-user-resource-free-packages` | `{PageNumber:1, PageSize:200, PackageCodes:[10 个免费组 code], Status:[0,3], SlicePeriodStartTime:"YYYY-MM-DD 00:00:00", SlicePeriodEndTime:"YYYY-MM-DD 23:59:59"}` | 逐条 grant；带 code_008 才返回套餐配额记录 |
| `POST {endpoint}/billing/meter/get-user-resource-paid-packages` | `{PageNumber:1, PageSize:200, PackageCodes:[Ys 11 个付费组 code], Status:[0,3], IsDisplayTotalInfo:true, NeedRenewInfo:true}` | 购买积分逐条 |
| `POST {endpoint}/v2/billing/meter/checkin-activity-status` | `{}` | 今日是否已签（`today_checked_in`） |

PackageCode 清单（asar 枚举 `$`，24 字符短码，非凭据）：

- 付费组 `Ys`（paid 端点用）：002 / 005 / 003 / 023 / 026 / 027 / 008 / 006 / 035 / 039 / 040
- 免费组（free 端点用）：001 / 007 / 009 / 028 / 029 / 030 / 036 / 037 / 038 / 008

## 已排除的路线（别再重走）

| 路线 | 结果 |
|---|---|
| 资源端点带 `/v2` 前缀（`/v2/billing/meter/get-user-resource-*`） | HTTP 404 `{"error_msg":"404 Route Not Found"}`。签到端点带 `/v2`，资源端点不带——两者前缀规则不同，别想当然 |
| `PackageCodes: []` 空数组 | HTTP 400 `10001:GetUserResourceFreePackages PackageCodes required`。必须按客户端分组下发 |
| 自己实现 sym-v1 信封解密 | 不做。vendor 脚本已让客户端进程自行解密（SAFETY 允许路线「让客户端自己说话」），本模块直接复用，不引入新的凭据处理面 |
| `get-enterprise-user-usage` | 企业账户专用，个人账号不适用 |

## 失效条件

- 端点路径改名 / 前缀规则变化 → `credit credits workbuddy` 报 HTTP 404，先来这份文档核对路径
- PackageCode 枚举变更（新增发放类型）→ free 组漏 code 会少算；症状是 summary 分组剩余 > 明细剩余合计，用 `--json` 对账
- sym-v1 信封格式升级 → vendor 签到脚本先炸（AUTH_ERROR），明细查询同一凭据链路会一起炸，不是本模块的问题
- `Accept-Language` 缺失时服务端可能返回英文包名，不影响数值

## 复跑

```bat
credit credits workbuddy
credit credits workbuddy --all
credit credits workbuddy --json
python -m agent_credit.wb_credits --line
```

回归测试：`python scripts/test_wb_credits.py`（解析器 + body 形状 + 时间格式，
字段漂移会直接报错，不会静默失真）。
