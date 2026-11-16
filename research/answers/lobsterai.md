# LobsterAI · 调研结论（2026-09-26 初版；2026-10-25 修正；2026-11-06 复核）

| 项 | 值 |
|---|---|
| 账户 id | `lobsterai` |
| 状态 | **活动已确认可用（2026-10-25 修正旧探测参数后；2026-11-06 在 2026.10.30 客户端复核仍可用）；external 直签具备条件，当前主路线仍为 UI** |
| 客户端 | Electron，`%LOCALAPPDATA%\Programs\LobsterAI\resources\app.asar`（约 704 MB，v2026.10.30） |
| 路线 | UI/OCR 主路线（`catalog.yaml claim_mode: ui`）；external 备用（`vendor/lobsterai-auto-signin/signin.py`） |

---

## 〇、2026-10-25 修正（先看这段）

旧结论「服务端当前未下发签到活动」是**错的**，根因是 external 探测写死了过期的请求参数：

- 旧：`clientVersion=1.0.0`、`containerApiVersion=1`
- 实际（v2026.10.16）：`clientVersion=2026.10.16`；`desktop_sidebar` 用 `containerApiVersion=2`，`desktop_startup_modal` 用 `3`

用实际参数只读重测：

```
GET /api/client-activities/slot?placement=desktop_sidebar&clientVersion=2026.10.16&containerApiVersion=2&platform=win32
→ 200 {"code":0,"data":{"slotState":"available","activity":{"activityCode":"daily-check-in-evergreen-prod-20260814","configRevision":1,"activityType":"daily_check_in",...}}}

GET /api/client-activities/daily-check-in-evergreen-prod-20260814/context?configRevision=1
→ 200 {"code":0,"data":{"lifecycleState":"active","state":{"rewardCredits":100,"claimedDays":34,"claimedCredits":3400.0,"claimedToday":true,...}}}
```

结论：

1. 活动一直在，**不是服务端没下发**；旧脚本的参数过期才返回 `slotState=empty` / `51100 活动不存在`。
2. 每日 100 积分、30 天有效、可累积；`claimedDays=34` / `claimedCredits=3400` 与服务端口径一致。
3. UI 2026.10.16 已显示「今日已领」和「奖励到账 +100积分」；旧记录「此 UI 没有今日已领文字」只适用于 2026-09-28 版本，已过期。
4. `vendor/lobsterai-auto-signin/signin.py` 已修：动态读客户端版本、按 placement 选 CAV、用 `activityType` 判定、POST 带 `configRevision` + `idempotencyKey`。`status` / `auto` 只读与幂等路径已实测（`claimedToday=true` 时 `auto` 直接返回，不发 POST）。
5. `catalog.yaml` 主路线仍保留 `claim_mode: ui`，没有擅自切换 external；external 已可作为下一阶段的候选主线。

---

## 〇bis、2026-11-06 复核（客户端 2026.10.30）

1. 客户端已从 2026.10.16 升到 **2026.10.30**（安装包 `LobsterAI.exe` ProductVersion；官网下载页一致）。活动仍是 `daily-check-in-evergreen-prod-20260814`，`desktop_sidebar` + `containerApiVersion=2`。
2. 只读 context 刷新：`claimedDays=46`、`claimedCredits=4600`、`claimedToday=true`、`rewardCredits=100`；本地台账 39 条（2026-09-28..2026-11-06，仅缺 10-24），近 30 天 29/30=96.7%。
3. **修掉一类静默失效**：2026.10.30 的 `app.asar` 文件 payload 带 NUL 对齐前缀，旧 `client_version()` 直接 `json.loads` 抛异常并被 `except` 吞掉，返回 `0.0.0`；服务端对 `clientVersion=0.0.0` 返回 `slotState=empty`，看起来像活动下线。现改为 `lstrip(b"\x00")` + `JSONDecoder.raw_decode`，`signin.py status` 恢复 `available`，版本读出 `2026.10.30`。
4. 2026-11-06 00:02 自动 UI 轮返回 `already @今日已领`，UI 路径未受版本升级影响。
5. 失效条件补充：asar 打包格式/前缀再变、`package.json` 读取路径变更；external 路线应在客户端升级后先跑一次 `status` 再判定「无活动」。

---

## 〇ter、2026-11-06 积分明细接口（补上旧记录说「拿不到」的逐条数据）

`GET /api/user/credits-earned`（同一 Bearer token，只读）返回：

```json
{"totalEarned":4900,"totalRemaining":2792.46,
 "records":[{"type":"campaign","name":"每日登录奖励",
  "credits":100,"creditsUsed":0,"creditsRemaining":100,
  "status":"active","earnedAt":"2026-11-06T00:02:27",
  "expiresAt":"2026-12-06T00:02:28"}]}
```

- 47 条：46 天每日 100（4600）+ 新用户 300 = 4900；`status` 分 active / expired / exhausted。
- `totalRemaining` 只算 active（实测 2792.46），过期未用 845.74 不计入；随会话消耗实时下降。
- 过期日就是服务端真值，不再需要「领取日 + 30 天」推导；1.2 的有效期由 measured 升为 confirmed。
- 已新增 `agent_credit/lobsterai_credits.py`（人类表 / `--json` / `--line` / `--ledger`）和 `scripts/lobsterai_credits.py`；catalog 配 `status_command` / `credits_command`。
- 对账：`ledger.sync_detail` 按服务端 47 条整体镜像（保留 amount / remaining / status / 原始过期日；source=sync、expiry_basis=server），首次 3100 → 2775（28 条活条目）。

---

## 一、挖出来的东西（本机 app.asar 逆向 + 实测验证）

| 项 | 值 |
|---|---|
| host | `https://lobsterai-server.youdao.com` |
| 活动槽位 | `GET /api/client-activities/slot?placement=<p>&clientVersion=<app version>&containerApiVersion=2\|3&platform=win32` |
| 活动上下文 | `GET /api/client-activities/{activityCode}/context?configRevision=N` |
| **执行动作（签到）** | `POST /api/client-activities/{activityCode}/actions/{actionId}` |
| 签到参数 | `activityCode=daily-check-in-evergreen-prod-20260814`、`activityType=daily_check_in`、`actionId=check_in` |
| placement 取值 | `desktop_sidebar`（containerApiVersion=2）、`desktop_startup_modal`（containerApiVersion=3） |
| 鉴权 | `Authorization: Bearer <accessToken>` |
| token 位置 | `%APPDATA%\LobsterAI\lobsterai.sqlite` 的 `kv` 表 `auth_tokens`（**明文 JSON**） |
| 另一条接口 | `POST /api/credits-reset-campaign/free-credits/claim`（需 `campaignCode`，即台账日历里 9-29 到期那 300 赠送） |

活动 `daily-check-in-evergreen-prod-20260814` 的关键字段（2026-10-25 只读 context）：

```
rewardCredits = 100
claimedDays = 34
claimedCredits = 3400.0
claimedToday = true
timezone = Asia/Shanghai
```

i18n 里签到卡片文案（UI 路线可直接当锚点）：
`每日可领 {credits} 积分` / `立即领取` / `领取中…` / `今日已领` / `本期已完成`。

## 二、实测结果：活动可用，旧参数导致误判

```
GET /api/client-activities/slot?placement=desktop_sidebar&clientVersion=2026.10.16&containerApiVersion=2&platform=win32
→ HTTP 200 {"code":0,"message":"success","data":{"slotState":"available","activity":{
    "activityCode":"daily-check-in-evergreen-prod-20260814",
    "configRevision":1,
    "activityType":"daily_check_in",
    "placement":"desktop_sidebar",
    "templateKey":"native_daily_check_in_v1",
    "startAt":"2026-08-13T16:00:00Z",
    "endAt":"2126-07-20T16:00:00Z",
    "timezone":"Asia/Shanghai",
    "loginRequired":true,
    "periodLabel":"常驻活动",
    "cardTitle":"每日积分礼"
}}}
```

`desktop_startup_modal` 用 `containerApiVersion=3` 时当前仍返回 `slotState=empty`，属正常——每日签到活动绑定在 `desktop_sidebar`；启动弹窗位另有 `NativeStartupCreditV1` 容器，当前没有活动。

旧脚本用 `clientVersion=1.0.0` + `containerApiVersion=1`，两个 placement 都返回 `empty`，于是被误判成「服务端没活动」。**根因是请求参数过期，不是服务端没下发。**

## 三、处置

- `catalog.yaml` 主路线：`claim_mode: ui`，入口=`主窗口右上角「每日积分礼」/ 左下「我的」→「立即领取」`；2026-10-16 版 UI 已能直接看到「今日已领」和「奖励到账 +100积分」。
- `vendor/lobsterai-auto-signin/signin.py`：已按实际客户端修复，`status` 只读可读到活动与 `claimedToday/rewardCredits/claimedDays/claimedCredits`；`auto` 在 `claimedToday=true` 时幂等返回，不发 POST。
- external 已具备切换条件，但**未擅自切换**主路线；是否把 `claim_mode` 改成 `external`，建议先连续观察几天 `status` 后再定。
- 无活动时脚本返回 `[no-activity]` 且退出码 2（判为“待手签”），属正常噪音，不是故障。

## 四、待办 / 未决

1. **9-29 到期的 300 赠送**（`credits-reset-campaign`）需要 `campaignCode`，来源还没找到
   ——可能由 slot 的活动或 quota/profile 接口下发。等服务端下发活动后一并处理。
2. `daily_amount: 100` 已由 context `rewardCredits=100` 与 `claimedCredits=4600 / claimedDays=46` 双向验证，不再是“早期手记值”。
3. 有效期 30 天仍来自 asar i18n `dailyCheckInValidityDays` + UI OCR；当前 context 不返回有效期字段。
4. 本地台账 09-28..11-06 共 39 条（仅缺 10-24），服务端 `claimedDays=46`，说明早期至少漏记 7 天；下次对账时补。
5. 若决定切换 external，先跑 `signin.py status` 确认 `claimedToday` 闸门，再改 `claim_mode: external` + `command`。

```yaml
account_id: lobsterai
software: LobsterAI
version: "2026.10.30"
researched_at: 2026-11-06
confidence: high                  # 端点/鉴权/活动/日额度均已实测；有效期 30 天为 UI+i18n

checkin:
  supported: true
  human_path: "右上角「每日积分礼」→「立即领取」；或左下「我的」→ 用户面板「立即领取」"
  api: "GET /api/client-activities/slot?placement=desktop_sidebar&clientVersion=2026.10.30&containerApiVersion=2&platform=win32; POST /api/client-activities/daily-check-in-evergreen-prod-20260814/actions/check_in"
  cli: "python vendor/lobsterai-auto-signin/signin.py status|auto"
  daily_amount: 100
  streak_cycle: null               # 无连签加成；claimedCredits/claimedDays = 100/天
  validity_days: 30
  cap: null
  idempotent: true                 # claimedToday 闸门；已签时 auto 不发 POST

status:
  balance: "GET /api/user/credits-earned → data.totalRemaining（逐条 records[]，active 合计）"
  claimed_today: "GET /api/client-activities/{activityCode}/context?configRevision=N → data.state.claimedToday"
  unit: credit

automation:
  claim_mode: ui                   # 主路线；external 已修复，候选切换
  command: "python %USERPROFILE%\\Documents\\Warpeas\\agent-credit\\vendor\\lobsterai-auto-signin\\signin.py auto"
  status_command: "python %USERPROFILE%\\Documents\\Warpeas\\agent-credit\\vendor\\lobsterai-auto-signin\\signin.py status"
  blockers: "UI 路线依赖窗口锚点/OCR/真实点击；external 需客户端版本与 containerApiVersion 跟随升级"
  reliability: "已实测：context claimedDays=46 / claimedCredits=4600（2026-11-06）；credits-earned 47 条（4900 发放 / 2775 可用 / 28 条 active）；本地台账已按逐条明细镜像，看板标服务端真值"

evidence:
  - "app.asar → defaultBaseUrl 字面量 https://lobsterai-server.youdao.com"
  - "app.asar → ActivityType.DailyCheckIn = 'daily_check_in'；DailyCheckInAction.CheckIn = 'check_in'"
  - "app.asar → ActivityContainerApiVersion = { NativeDailyCheckInV1: 2, NativeStartupCreditV1: 3 }"
  - "app.asar → ActivityPlacement = { DesktopSidebar: 'desktop_sidebar', DesktopStartupModal: 'desktop_startup_modal' }"
  - "实测 GET slot（clientVersion=2026.10.16, containerApiVersion=2）→ 200 slotState=available, activityCode=daily-check-in-evergreen-prod-20260814"
  - "实测 GET context（configRevision=1）→ rewardCredits=100, claimedDays=34, claimedCredits=3400.0, claimedToday=true（2026-10-25）"
  - "实测 GET context（2026.10.30 客户端）→ claimedDays=46, claimedCredits=4600.0, claimedToday=true（2026-11-06）"
  - "2026.10.30 app.asar payload 带 NUL 前缀；旧 client_version() 解析失败→0.0.0→slotState=empty；已修复并实测读出 2026.10.30"
  - "实测 GET /api/user/credits-earned → totalEarned=4900, totalRemaining=2792.46, records=47（46 每日 + 1 新用户 300），每条含 credits/creditsUsed/creditsRemaining/status/earnedAt/expiresAt"
  - "UI 2026.10.16 实测（logs/_lobsterai_log.txt 2026-10-25 11:09）→「今日已领」+「奖励到账 +100积分」"
  - "旧脚本 clientVersion=1.0.0 + containerApiVersion=1 → slotState=empty（已确认是参数过期，不是活动下线）"

open_questions:
  - credits-reset-campaign 的 campaignCode 从哪来
  - 是否把主路线从 UI 切到 external（需连续几天 status 观察）
  - 本地台账漏记的 6 天早期签到如何补

catalog_patch:
  lobsterai:
    daily_amount: 100
    validity_days: 30
    # claim_mode: external   # 候选；切换前先连续观察 status
    # command: "python {REPO}\\vendor\\lobsterai-auto-signin\\signin.py auto"
    status_command: "python {REPO}\\scripts\\lobsterai_credits.py --line"
    credits_command: "python {REPO}\\scripts\\lobsterai_credits.py --ledger"
```
