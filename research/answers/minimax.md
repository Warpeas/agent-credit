# MiniMax Code · 自述答案

| 项 | 值 |
|---|---|
| 账户 id | `minimax` |
| 状态 | 已填 · confidence: medium（端点部分已由本机逆向升级为 high） |
| 来源 | MiniMax Code 客户端自述，2026-09-23 |
| 安全检查 | 已跑 `check_research_answers.py` 通过，无 token 明文 |

```yaml
account_id: minimax
software: MiniMax Code
version: unknown
researched_at: 2026-09-23
confidence: medium

checkin:
  supported: true
  human_path: 主页左下角"每日签到"卡片（OCR 已定位）
  api: "GET  {host}/minimax-cloud/api/v1/signin/status ; POST {host}/minimax-cloud/api/v1/signin/claim ; host(cn/prod)=https://agent.minimax.cn"  # 已确认，见「端点逆向」
  cli: unknown                # 官方 mcode-tools.cmd 没有 checkin/claim/reward 子命令
  daily_amount: 400
  streak_cycle: "7 天一轮；第 4、7 天各 +1000"
  validity_days: 30
  cap: null
  idempotent: unknown         # 没有任何可重复触发的入口，无法实测

status:
  balance: "本机无明文余额缓存。mcode-tools auth status 只返回鉴权态，不含积分；余额只能前端 UI/OCR 读"
  claimed_today: "本机无明文状态缓存。同上，只能 UI/OCR 读"
  unit: credit

automation:
  claim_mode: ui             # 2026-09-23 实测通过后由 manual 升级；自述原值 never 不采纳
  command: ""
  status_command: "C:\\Users\\Hunter\\.minimax\\bin\\mcode-tools.cmd auth status"   # 仅鉴权态，不是积分余额
  blockers:
    - "官方 mcode-tools CLI 没有签到/积分子命令（已用 --help 与 connector tools 全量枚举确认）"
    - "前端 isTrusted 过滤 <-- 仅对 UIAutomation Invoke 路线成立；本项目 OCR 点击路线用的是 OS 级注入，不成立（见下）"
    - "签到请求走 Electron 自定义协议 app://cloud，由主进程注入鉴权头，外部进程无法直接复用"
    - "auth.json 含明文 OAuth bearer，属于登录态等价物，不应被脚本直接拼进 external 命令"
    - "auth broker（命名管道 mcode-auth-lease-* + capability file）只在 MiniMax Code 进程内有效"
  reliability: 已实测（CLI/connector/auth 目录）+ 已确认（端点路径自 app.asar 逆向）+ 推测（风控头细节未验证）

evidence:
  - "C:\\Users\\Hunter\\.minimax\\bin\\mcode-tools.cmd --help -> 仅 auth / get-asset-url / upload-temp-url / connector"
  - "mcode-tools connector tools -> 只有 connector__hengsheng__*（恒生金融数据）与 connector__matrix__*（多媒体），无 credit/signin/daily"
  - "mcode-tools auth status -> auth_mode:shared-broker, status:authenticated, generation:10, scope:agent.default（不含积分字段）"
  - "C:\\Users\\Hunter\\.minimax\\auth\\prod\\cn\\mcode-public\\auth.json 含 accessToken/refreshToken 明文 OAuth（已 redact，未粘贴原文）"
  - "MiniMax Code 安装路径 ...\\MiniMax Code\\MiniMax Code.exe；CLI 实体为 resources\\resources\\mcode-tools\\cli.mjs"
  - "config.yaml 暴露 baseURL https://agent.minimax.cn/mavis/api/v1/llm/v1，是 LLM 网关而非签到端点"
  - "app.asar 前端 bundle 直出（2026-09-23 本机逆向）：getSigninPanel -> GET /minimax-cloud/api/v1/signin/status；claimSignin -> POST /minimax-cloud/api/v1/signin/claim"
  - "同 bundle 内的同族路径（SKILL_HUB_BASE / DESKTOP_ERROR_API_HOST）显示 cn/prod host = https://agent.minimax.cn"
  - "@mavis/shared/src/daily-signin.ts 给出完整数据模型：SigninDayStatus 1=Upcoming 2=Claimable 3=Claimed 4=Disabled；SigninClaimResult 1=Claimed 2=AlreadyClaimed；day_no 1..7"
  - "鉴权约定（bundle 注释原文）：Bearer 放 Authorization 头，不进查询串；真实用户 ID 放 user_id 查询参数；只允许 HTTPS"
  - "请求经 app://cloud 协议由主进程代理，非 /minimax-cloud/api 前缀一律拒绝 —— 外部直连需自备 token"

open_questions:
  - "风控头：除 Bearer 外是否还有设备指纹 / ts+nonce 签名（未验证，需抓包或读拦截器实现）"
  - "token 获取：本机 Local Storage(leveldb) 是否明文可取；即使可取，复用登录态的风险与封号边界需主人定夺"
  - "余额/今日已签是 GET status 同路径返回，还是另有 quota 接口"
  - "MiniMax 是否会在 mcode-tools 加 signin/reward 子命令"

catalog_patch:
  minimax:
    # 无 patch：evidence 不足以改为 external，保持 manual
```

## 处置

**`catalog.yaml` 已改：`claim_mode: manual` → `ui`**（2026-09-23 实测通过后）。
`agent_credit/ui_claim.py` 新增 `_claim_minimax()`，走验证过的 OCR+OS 注入脚本，
不再走那条会被过滤的通用 UIA 路线。

自述里建议的 `claim_mode: never` 不采纳 —— `never` 会把 MiniMax 从 `due` / `checkin`
里彻底摘掉，而它仍是每日必签中额度最大的一家（400/天）。

## 关于「isTrusted 过滤」这条 blocker

**不成立，至少对本项目用的 OCR 点击路线不成立。**

- `scripts/ui_claim.ps1`（通用路线）走 **UI Automation 的 `InvokePattern.Invoke()`**，
  是脚本层派发，`isTrusted` 为 false，会被前端过滤 —— **这条成立**。
- `scripts/ui_claim_minimax.ps1` / `ui_claim_autoclaw.ps1` 走 **`SetCursorPos` + `mouse_event`**，
  属于操作系统级输入注入，进系统输入队列，前端拿到的是真实输入事件，`isTrusted` 为 true。
  **这两条不受 isTrusted 影响，用它解释失败是错的。**

MiniMax 那次失败的真正原因更可能是脚本自身缺陷：点错了目标、校验窗口没盖住按钮区域。
详见 `research/NOTES-isTrusted.md`。

## 端点逆向（2026-09-23 本机完成）

MiniMax Code 的 `resources/app.asar`（527 MB，Electron 归档）里，签到是**一等公民模块**，不是隐藏功能。

归档格式：`u32@0=4`，`u32@12=json_len`，JSON 头从 offset 16 开始，body 起始 = `(16+json_len)` 上对齐到 4 字节。

关键命中（前端 bundle，已压缩混淆但路径是字面量，未加密）：

```
async getSigninPanel() { let {data:e} = await <axios>.get ("/minimax-cloud/api/v1/signin/status", cfg); ... }
async claimSignin()    { let {data:e} = await <axios>.post("/minimax-cloud/api/v1/signin/claim", {}, cfg); ... }
```

- Host：同 bundle 内 `SKILL_HUB_BASE` / `DESKTOP_ERROR_API_HOST` 的 cn/prod 值均为 `https://agent.minimax.cn`
- 鉴权约定（bundle 内设计注释原文）：`Authorization: Bearer` **放请求头**，绝不进查询串；
  真实用户 ID 放 `user_id` 查询参数；只允许 HTTPS。
- 传输层：渲染进程把请求交给 `app://cloud` 自定义协议，主进程校验
  `pathname === '/minimax-cloud/api' || startsWith('/minimax-cloud/api/')` 后才注入鉴权并转发 ——
  **这是外部 CLI 不能直接调的根本原因**：头是主进程加的，不是渲染进程带的。
- 数据模型 `@mavis/shared/src/daily-signin.ts`：
  `SigninDayStatus{ Upcoming=1, Claimable=2, Claimed=3, Disabled=4 }`、
  `SigninClaimResult{ Claimed=1, AlreadyClaimed=2 }`、
  `SigninDayItem{ day_no, points, status, is_today }`、`day_no ∈ 1..7`。
  与自述的「7 天一轮，第 4/7 天各 +1000」一致。

**为什么 MiniMax 客户端自己答 "unknown / never"**：它没读自己的 `app.asar`。
把它带的项目目录里根本没有 `app.asar`，而它也没想到去安装目录翻自己的 bundle。
这说明「让各家 Agent 自述」这条路对 Electron 应用价值有限 —— 它们不认识自己的打包产物。

## 实测（2026-09-23 01:57，已跑通）

修完脚本后实跑，结果：

```
{"detail":"签到成功: 今日已签到","status":"ok"}
```

**OS 级模拟点击对 MiniMax Code 有效**，「isTrusted 过滤」这条 blocker 正式作废。

定位的关键常量（两次不同窗口尺寸下实测一致）：

| 元素 | 相对「每日签到」标题的偏移 |
|---|---|
| 「今天」格子 | (+29, +120) |
| 7 天格子区 | y +120 ~ +280 |
| **签到按钮** | **(+207, +373)**，尺寸 185×26 |

踩到的坑：按钮文本 OCR 会飘（`签到得@400` → `雷签到得@羽0`），而卡片里的说明文字
「连续签到得更多积分」也含「签到得」且在按钮上方，正则会先命中它。
修法：排除 `连续签到`，命中项取**最靠下**的，再加一层几何回退（锚点 +207/+373）。

另一条实测观察：**签到成功后卡片会从侧边栏移除**。所以「找不到签到卡」通常意味着
今天已签，不是布局坏了。脚本仍保守返回 `pending` —— 谎报成功会静默漏掉一整天。

已入账：`credit record minimax claimed 400` → 剩余 400，连签 1 天。

## 下一步

1. **[已完成]** 修 `ui_claim_minimax.ps1`：点击目标从「今天」标签改为真正的按钮「签到得@400」（y≈1882）；
   已签检测窗口与成功校验窗口的基准从标题锚点（y≈1509）改为实际按钮位置，范围 ±300。
   旧代码的校验窗口是「锚点 ±200」= y 1309~1709，按钮在 1882，**根本没被覆盖**。
2. **[已完成]** 端点逆向：从 `app.asar` 直接拿到 `/minimax-cloud/api/v1/signin/{status,claim}`。
   这一步证实 MiniMax 客户端的自述（"api: unknown / 需抓 network"）是**调研不足**，不是做不到。
3. **[已完成]** `catalog.yaml` 中 minimax 的 `claim_mode` 由 `manual` 改为 `ui`；
   `agent_credit/ui_claim.py` 新增 `_claim_minimax()` 分支，走验证过的 OCR 脚本，
   不再走会被过滤的通用 UIA 路线。
4. 待定夺：`external` 路线需复用登录态 token（读本机 Local Storage）。属凭据复用，有封号与泄露风险，
   **需要主人明确授权才做**。
5. 稳定性观察：OCR 点击依赖窗口在前台、依赖 OCR 识别率。建议先连跑 3 天，
   出现 ≥1 次 pending 就退回 `manual` + 人工兜底。
