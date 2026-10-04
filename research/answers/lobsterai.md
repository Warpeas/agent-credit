# LobsterAI · 调研结论（2026-09-26，本机逆向 + 接口实测）

| 项 | 值 |
|---|---|
| 账户 id | `lobsterai` |
| 状态 | **端点已挖出并实测；服务端当前未下发签到活动** |
| 客户端 | Electron，`C:\Users\Hunter\AppData\Local\Programs\LobsterAI\resources\app.asar`（398 MB） |
| 路线 | **external 直签**（`vendor/lobsterai-auto-signin/signin.py`） |

---

## 一、挖出来的东西（全部本机 `app.asar` 逆向 + 实测验证）

| 项 | 值 |
|---|---|
| host | `https://lobsterai-server.youdao.com` |
| 活动槽位 | `GET /api/client-activities/slot?placement=<p>&clientVersion=<v>&containerApiVersion=1&platform=win32` |
| 活动上下文 | `GET /api/client-activities/{activityCode}/context?configRevision=N` |
| **执行动作（签到）** | `POST /api/client-activities/{activityCode}/actions/{actionId}` |
| 签到参数 | `activityCode=daily_check_in`、`actionId=check_in`（`ActivityType.DailyCheckIn` / `DailyCheckInAction.CheckIn`） |
| placement 取值 | `desktop_sidebar`（侧边栏）、`desktop_startup_modal`（启动弹窗） |
| 鉴权 | `Authorization: Bearer <accessToken>` |
| token 位置 | `%APPDATA%\LobsterAI\lobsterai.sqlite` 的 `kv` 表 `auth_tokens`（**明文 JSON**，accessToken 290 字符） |
| 另一条接口 | `POST /api/credits-reset-campaign/free-credits/claim`（需 `campaignCode`，即台账日历里 9-29 到期那 300 赠送） |

i18n 里签到卡片文案（若将来要走 UI 路线可直接当锚点）：
`每日可领 {credits} 积分` / `立即领取` / `领取中…` / `今日已领` / `本期已完成`。

## 二、实测结果：服务端现在没有签到活动

```
GET /api/client-activities/slot?placement=desktop_sidebar&...
→ HTTP 200 {"code":0,"message":"success","data":{"slotState":"empty","activity":null}}
```

两个 placement 都问了，**都是 `slotState=empty`、`activity=null`**。
对应的 `GET /api/client-activities/daily_check_in/context` 返回 `code 51100 活动不存在`
（`ActivityServerErrorCode.NotFound = 51100`，与逆向一致）。

结论：**不是脚本没写对，是 LobsterAI 服务端当前没给这个账号下发签到活动。**
鉴权是通的（否则会 401/403，而不是 code 0）。

## 三、处置

- 已写 `vendor/lobsterai-auto-signin/signin.py`（`status` 只读 / `auto` 有活动才领）
- `catalog.yaml` 已挂 `claim_mode: external` + `command`，**活动一上线就会自动签**，无需再改代码
- 无活动时脚本返回 `[no-activity]` 且退出码 2（判为"待手签"），属正常噪音，不是故障

## 四、待办 / 未决

1. **9-29 到期的 300 赠送**（`credits-reset-campaign`）需要 `campaignCode`，来源还没找到
   ——可能由 `slot` 的活动或 quota/profile 接口下发。等服务端下发活动后一并处理
2. 台账 `daily_amount: 100` 是早期手记值，**服务端没有活动所以无法验证**，保留原值
3. 若活动长期不下发，考虑把 `claim_policy` 从 `always` 调低，避免每天 pending 噪音

```yaml
account_id: lobsterai
software: LobsterAI
version: unknown
researched_at: 2026-09-26
confidence: medium               # 端点/鉴权 high；签到规则无法验证（服务端无活动）

checkin:
  supported: true
  human_path: unknown             # 未走 UI 路线；活动入口为 desktop_sidebar / desktop_startup_modal
  api: "POST https://lobsterai-server.youdao.com/api/client-activities/daily_check_in/actions/check_in"
  cli: null
  daily_amount: unknown           # 台账记 100，服务端无活动无法验证
  streak_cycle: unknown
  validity_days: unknown
  cap: unknown
  idempotent: unknown             # 未实测领取，无法验证

status:
  balance: unknown
  claimed_today: "GET /api/client-activities/slot → data.activity 为 null 表示无活动"
  unit: credit

automation:
  claim_mode: external
  command: "python C:\\Users\\Hunter\\Documents\\Warpeas\\agent-credit\\vendor\\lobsterai-auto-signin\\signin.py auto"
  status_command: unknown
  blockers: "服务端当前未下发签到活动（slotState=empty），无法领取"
  reliability: 已实测（接口可达、鉴权通过、slot 返回 code 0）

evidence:
  - "app.asar → defaultBaseUrl 字面量 https://lobsterai-server.youdao.com"
  - "app.asar → ActivityType = { DailyCheckIn: 'daily_check_in', OneTimeCreditReward: 'one_time_credit_reward' }"
  - "app.asar → DailyCheckInAction = { CheckIn: 'check_in' }"
  - "app.asar → ActivityPlacement = { DesktopSidebar: 'desktop_sidebar', DesktopStartupModal: 'desktop_startup_modal' }"
  - "app.asar → `/api/client-activities/slot?placement=...&clientVersion=...&containerApiVersion=...&platform=...`"
  - "app.asar → `/api/client-activities/${activityCode}/actions/${actionId}`（ActivityAuthMode.Required）"
  - "%APPDATA%\\LobsterAI\\lobsterai.sqlite kv 表 auth_tokens → accessToken len=290（值 <redacted>）"
  - "实测 GET slot → HTTP 200 code 0, slotState=empty, activity=null（两个 placement 都是）"

open_questions:
  - 为何服务端未下发签到活动（地区/账号/活动已下线？）
  - credits-reset-campaign 的 campaignCode 从哪来
  - 每日额度是否仍是 100

catalog_patch:
  lobsterai:
    claim_mode: external
    command: "python C:\\Users\\Hunter\\Documents\\Warpeas\\agent-credit\\vendor\\lobsterai-auto-signin\\signin.py auto"
```
