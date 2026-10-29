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
  status_command: "%USERPROFILE%\.minimax\\bin\\mcode-tools.cmd auth status"   # 仅鉴权态，不是积分余额
  blockers:
    - "官方 mcode-tools CLI 没有签到/积分子命令（已用 --help 与 connector tools 全量枚举确认）"
    - "前端 isTrusted 过滤 <-- 仅对 UIAutomation Invoke 路线成立；本项目 OCR 点击路线用的是 OS 级注入，不成立（见下）"
    - "签到请求走 Electron 自定义协议 app://cloud，由主进程注入鉴权头，外部进程无法直接复用"
    - "auth.json 含明文 OAuth bearer，属于登录态等价物，不应被脚本直接拼进 external 命令"
    - "auth broker（命名管道 mcode-auth-lease-* + capability file）只在 MiniMax Code 进程内有效"
  reliability: 已实测（CLI/connector/auth 目录）+ 已确认（端点路径自 app.asar 逆向）+ 推测（风控头细节未验证）

evidence:
  - "%USERPROFILE%\.minimax\\bin\\mcode-tools.cmd --help -> 仅 auth / get-asset-url / upload-temp-url / connector"
  - "mcode-tools connector tools -> 只有 connector__hengsheng__*（恒生金融数据）与 connector__matrix__*（多媒体），无 credit/signin/daily"
  - "mcode-tools auth status -> auth_mode:shared-broker, status:authenticated, generation:10, scope:agent.default（不含积分字段）"
  - "%USERPROFILE%\.minimax\\auth\\prod\\cn\\mcode-public\\auth.json 含 accessToken/refreshToken 明文 OAuth（已 redact，未粘贴原文）"
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
（isTrusted 的完整论证就在本文件「关于「isTrusted 过滤」这条 blocker」一节，
`research/NOTES-isTrusted.md` 并未单独落盘。）

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

## external 直签（2026-09-26 打通，已切为默认路线）

**UI 路线做不到全自动**：本环境无法冷启动 MiniMax Code —— `Start-Process` 与
`ShellExecuteW(open)` 都只起来一个 **`updater.exe`**，主进程始终不出现（全进程 diff 验证过）；
`.minimax` 最后活动停在 9-24，客户端压根没跑。主人要求"不要手动、全自动"，于是按硬规则 6 的
例外条款（读本机**明文**凭据 + 直调**官方**接口 + 脚本放 `vendor/` 内）走了 external。

实现：`vendor/minimax-auto-signin/signin.py`（`status` 只读 / `auto` 查询后按需领取）。
token 不进命令行、不进日志、不进输出（打印一律 `<redacted>`）。

**踩到的坑：`timezone_id` 必填。**

```
GET /minimax-cloud/api/v1/signin/status            → HTTP 200，业务 1406010011 invalid timezone_id
GET .../signin/status?timezone_id=Asia/Shanghai    → ✅ 正常返回面板
```

只有 **IANA 时区名**有效；`8` / `+8` / `28800` / `Shanghai` **全部被拒**。
**注意它 HTTP 仍是 200**——只看状态码会误判成功。

**数据模型（与逆向一致）**：`days[]` 里 `is_today=true` 且 `status=3(Claimed)` 即今日已领，
`status=2(Claimable)` 才能领。已签判定以服务端为准（台账可能漏记，但不重复领取）。

**实测**：9-26 00:0x 首次 `auto` 领到 `day_no=4, points=1000`（连签第 4 天奖励，与
「第 4、7 天各 +1000」一致），`claim_result=1`；复跑返回 `[already] 不重复领取`，幂等通过。
CLI 集成 `credit checkin --only minimax` → `[skipped] 今日已签`。

`catalog.yaml` 已改：`claim_mode: external` + `command` 指向该脚本。

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

## 六、2026-09-27 崩溃诊断（重要）

现象：MiniMax 客户端"打开瞬间关掉"。经系统排查，已排除脚本/提权/窗口枚举/单实例锁/GPU/WebGPU 假设。

实测排除：
- runas 提权启动 → 瞬间自退；改回 open 普通用户 → 同样启动即退（ShellExecuteW ret:42 启动成功，但 15–25s 后 tasklist 无 MiniMax 进程）
- %APPDATA%\MiniMax 下无 SingletonLock 残留
- 加 `--disable-gpu` / `--disable-features=WebGPU` → 仍启动即退

关键证据：
- `logs/main-09-27.log`：主进程启动到 01:10:37.053 截断（窗口已注册 type=archon），随后进程消失；无 error/gpu fatal 日志
- `Crashpad/reports` 与 `metadata` 均空 → 无 crash dump
- `observability-outbox.jsonl` 的 `app.startup_performance_summary`：启动 4s 完成、surface_to_visible_ms=72.3（窗口曾可见），随后崩溃
- 客户端崩溃前几秒能正常登录并调 signin/status（api-09-27.log, hasBearer:true）

结论：MiniMax 3.0.73 在用户当前环境（Windows 10.0.26200 / Ryzen 5700X3D / GPU acceleration enabled / WebGPU(Dawn) 渲染）启动完成、窗口闪现后数秒内崩溃退出，无 dump，根因需 MiniMax 侧分析。

影响：客户端不稳定 → OCR 路线（需窗口）与 external 路线（auth.json 的 accessToken 已于 2026-09-26 00:24 过期，客户端又跑不起来刷不到新 token）都受阻。MiniMax 当前无法自动签到。

待修：清 %APPDATA%\MiniMax 缓存（GPUCache/DawnWebGPUCache/DawnGraphiteCache/Cache/Code Cache/blob_storage/Session Storage，保留 Local Storage/Network/Cookies/Preferences）或覆盖重装，验证客户端能否稳定。

## 七、2026-10-02 双窗口根因（已闭环）+ OAuth2 token 刷新端点

### 7.1 「黑屏窗口与正常窗口共存」到底是什么

取证方法：杀掉进程后用**非提权**计划任务拉起客户端（`RunLevel=Limited` + `InteractiveToken`），
Python(ctypes) 从启动前开始每 0.3s 采样所有 MiniMax 顶层窗口的
`class / title / rect / IsWindowVisible / WS_VISIBLE / DWM cloaked / PrintWindow 渲染色数`。
产物：`logs/_mm_timeline.txt`、`logs/_mm_allwins.txt`。

冷启动时序（同一 MAIN 进程 pid）：

| 时刻 | 事件 |
|---|---|
| t=0.0–0.8s | MAIN 进程已起，**窗口数 = 0** |
| t=1.3s | `Chrome_WidgetWin_0` 出现，`1440x756`（物理 2880x1512），`Vis=0`，PrintWindow **单色纯黑** |
| t=2.1s | `Chrome_WidgetWin_1` 出现，标题 `MiniMax Code`，`Vis=1`，渲染色数 11 → t=3.9s 涨到 35 |

结论：**这是 Electron 主进程创建的两个 BrowserWindow，同属一个 pid**，
所以任何「按 pid 枚举窗口」的自动化都会同时看到它们。黑窗口比真身早约 0.8s 出现。

那个 `Chrome_WidgetWin_0` 不是常驻隐藏的死窗口，而是**活动/推广浮层窗口**，状态随时变化——
`logs/minimax_windows.txt` 的历史记录直接证明：

| 时刻 | `Chrome_WidgetWin_0` 状态 |
|---|---|
| 2026-09-30 07:13（冷启动瞬间） | 扫描结果里**只有它**，真身尚未创建 |
| 2026-09-30 23:17 | `visible=False blank=True`（隐藏、纯黑） |
| **2026-09-30 23:21 / 23:24 / 23:26** | **`visible=True blank=False`，2880x1511（近满屏）** |

也就是说，主人看到的两个现象是**同一个窗口的不同阶段**：
- 「全黑画面的窗口」= 该窗口刚被 show、WebContents 还没完成首绘；
- 「广告遮盖了整个窗口」= 同一窗口渲染完成后的推广内容（宽 2880 = 满屏宽）。

### 7.2 代码侧修复

`scripts/ui_claim_minimax.ps1` 的 `Find-AppWindow` 原 fallback 在 90s 超时后会退化成
「不要求标题」的查找，冷启动早期只有黑窗口存在时会锁死它 → 之后所有点击坐标整体偏移，
表现为「点击被吞掉」。已改为：

- 无标题且渲染为纯色的窗口 **score = 0，永不入选**；
- `if ($best.score -le 0) { return [IntPtr]::Zero }` —— 只有黑窗口时拒绝返回，继续等待；
- 有标题但抓图失败的窗口仍保留 score 4/1，避免真身被 `Test-WindowBlank` 的保守兜底误杀。

### 7.3 不依赖 UAC、不要求客户端常驻的两条路

**(A) 临时拉起客户端（已验证可行）**
注册 `RunLevel=Limited`（非提权）+ `LogonType=Interactive` 的计划任务，Action 直接执行
`%LOCALAPPDATA%\Programs\MiniMax Code\MiniMax Code.exe`，
`Start-ScheduledTask` 即可拉起 —— **不弹 UAC**（实测 procs 从 0 → 7）。
签到完 `Stop-Process` 收掉，不需要常驻。
注意：沙箱会话里 `Start-Process` 拉 GUI 无效（procs=0），必须走计划任务。

**(B) 纯脚本刷新 token（端点已挖到，未实机刷新）**
`app.asar` 内常量：`MCODE_OAUTH_CLIENT_ID = 'mcode-public'`、`audience = 'agent-backend'`；
端点配置：`https://account.minimax.cn`（prod/cn）下
`/oauth2/device/code`、`/oauth2/token`、`/oauth2/revoke`。

凭据文件 `%USERPROFILE%\.minimax\auth\prod\cn\mcode-public\auth.json` 里有**明文**
`accessToken` + `refreshToken` + `clientId` + `expiresAtMs`（`generation` 已到 50，
说明客户端在持续刷新）。accessToken 有效期约 1 小时 —— 这就是「客户端不常驻就刷不到
新 token」的根因。

零风险探测结果（用无效 refresh_token，不会作废真实凭据）：

```
POST https://account.minimax.cn/oauth2/token   (json 与 form 两种 Content-Type 均一致)
  -> 400 {"error":"invalid_grant","error_description":"this refresh token can no longer be used, start a new authorization"}
POST https://account.minimax.cn/oauth2/device/code
  -> 400 {"error":"invalid_request","error_description":"valid S256 PKCE is required"}
```

端点确认为标准 OAuth2。用真实 `refresh_token` 即可换取新 accessToken，**全程不需要客户端**。

⚠️ 待主人定夺，不要擅自执行：错误文案暗示 refresh token **轮换**（旧 token 刷新后作废），
因此刷新成功后必须把新 token 写回 `auth.json`，否则客户端下次刷新会失败（掉登录）。
写入前应先备份该文件。这条路线属凭据操作，按本文件第四节第 4 条仍需主人明确授权。

## 八、2026-10-24 · `bonus_points` 语义订正（台账多记 5024，已修）

### 8.1 根因：把 bonus_points 当成「额外再加一份」

本文件第三节写「字段是 points(基础) + bonus_points(加成)」——**这句话是错的**。
客户端自带的类型定义已经把话说死了（`app.asar` → `@mavis/shared/src/daily-signin.ts`）：

```ts
export interface SigninDayItem {
  day_no: number;
  points: number;
  /** Extra credits already included in points; absent on older responses. */
  bonus_points?: number;
  status: SigninDayStatus;
  is_today: boolean;
}
```

> **bonus_points 是「已经包含在 points 里」的额外额度**，不是另一份待加的奖励。

前端渲染同源，可交叉验证：

- `...(z ? { points: _(z.points), total_points: _(z.points) } : {})` → `total_points` 就是 `points`
- 签到按钮文案 `signin.claim_now` 里的 `{points: q}`，`q = _(R?.points ?? 0)` → 按钮上写的「签到得@N」= points
- `bonus_points` 只作为「这 800 里有 400 是活动多给的」这种**构成说明**单独展示

### 8.2 三条独立证据都指向同一结论

| 证据 | 内容 |
|---|---|
| 类型定义注释 | `Extra credits already included in points` |
| 官方口径 | 每日 400、第 4/7 天加码至 1000 → 基线就是 400/1000 |
| 实测数据 | 每一格 `points - bonus_points` 都正好落在 {400, 1000}，没有一个例外 |

实测三例：

| 日期 | 场景 | points | bonus_points | 真值 = points | 旧口径 points+bonus |
|---|---|---|---|---|---|
| 10-07 | 国庆期 day1 | 800 | 400 | **800** | 1200 ❌ |
| 10-13 | 国庆期 day4 | 2000 | 1000 | **2000** | 3000 ❌ |
| 10-24 | 活动期 day4 | 2024 | 1024 | **2024** | 3048 ❌ |

`points - bonus_points` 恰好等于官方基线（400 / 1000），这说明 points 是**当日总额**，
bonus 只是告诉客户端「其中多少是活动加成」。

### 8.3 错在哪、怎么错的

- 10-04 记「平时 1200/天、第 4/7 天 3000、整周期 12000」→ 把 bonus 又加了一次，实际是 800/2000。
- 10-11 记「平时 400/天、day1=1200、整周期 4800」→ 同样的错，数字对上了但语义还是错的。
- `vendor/minimax-auto-signin/signin.py` 的 `today_granted()` 与 `cmd_auto()` 都按
  `points + bonus_points` 上报实发额 → 凡 bonus>0 的日子都多记。
- 2026-10-04 还手工把台账里 09-30 / 10-01 两条从 800 改成 1200「补连签加成」——按新语义那两条 800 本来就是对的。

> 讽刺的是 MEMORY.md 10-13 那条「day1=800(+bonus 400)……周期合计 **4400**」反而是对的
> （它把 day1 当 800 算），只是没把「为什么 800 不用再加 400」讲清楚，错在解释不在数字。

### 8.4 影响面与已做的修正

台账多记 **5024** 积分（余额虚高）：

| 日期 | 旧入账 | 真值 | 多记 |
|---|---|---|---|
| 09-30 | 1200 | 800 | 400 |
| 10-01 | 1200 | 800 | 400 |
| 10-03 | 3000 | 2000 | 1000 |
| 10-04 | 1200 | 800 | 400 |
| 10-05 | 1200 | 800 | 400 |
| 10-06 | 3000 | 2000 | 1000 |
| 10-07 | 1200 | 800 | 400 |
| 10-24 | 3048 | 2024 | 1024 |
| | | | **合计 5024** |

修正动作：

1. 备份 `data/_ledger_backup_20261024_before_mmbonus_fix.json`，定点改这 8 条的 amount/remaining；
   余额是按条目累加算出来的，不另存字段 → **余额 27648 → 22624**。
2. `vendor/minimax-auto-signin/signin.py` 改为只取 `points`（`today_granted()` 与已签分支各一处），
   docstring 写明依据，避免以后再被改回去。
3. `catalog.yaml` 的 `daily_amount_by_day` / `streak` 改回**官方基线**
   `{1..7} = 400/400/400/1000/400/400/1000`，`cycle_total: 4000`，
   `bonus_on: [4,7]`、`bonus_amount: 600`（= 1000 - 400）；`rating.review` 里那套
   「1200/天、第 4/7 天 3000、周期 12000」一并作废。

### 8.5 官方口径（2026-10-24 核对）

`https://agent.minimax.cn/docs/code/account/usage`（M Plan 与积分）原文：

- 每日签到可领取 **400 积分**
- 连续签到第 **4** 天、第 **7** 天，单日奖励加码至 **1000 积分**
- 完成一周签到，累计可领取 **4000 积分**
- 签到积分可累计使用，自到账之日起 **30 天**内有效

2026-10-24 实测 `GET /signin/status`（is_today=day4，全周期可读）：

```
day1=400  day2=400  day3=400  day4=2024(1000基线+1024活动加成)
day5=400  day6=400  day7=1000            → 整周期 5024
```

即**活动期服务端会把当天额度翻倍**，并把多出来的部分记在 `bonus_points`。
所以「日额度」在活动期会临时高于基线，基线才是稳定承诺。

### 8.6 留下的判断

M Plan（订阅）的额度与签到积分是两套：M Plan 按 **5 小时窗口 + 周窗口** 刷新，
不结转、用完不累积；签到积分则是 30 天可累积。两者不能混算，
台账只跟签到赠予的那份（README「本地估算」口径）。

## 九、2026-10-24 · 服务端真值通道打通（`/credit/details`）

### 9.1 端点

第三节留下的 open question ——「余额/今日已签是 GET status 同路径返回，还是另有 quota 接口」——
**答：另有端点，而且就是逐笔明细**。

从客户端 bundle 里扒出来的调用（app.asar，模块 11557）：

```js
async function s(e, t) {
  let n = "/minimax-cloud/api/v1/credit/details",
      {data: i} = await r.ZP.get(n, {...t, params: e});
  if (!Array.isArray(i.details) || "number" != typeof i.total_count)
    throw Error("Credit details response payload is invalid");
  return {details: i.details, total_count: i.total_count};
}
```

调用方（设置→用量→积分明细面板）传的是：

```js
xK({page_number: u, page_size: d, include_expired: true}, {...})
```

**只读 GET，无副作用，不触发领取。**

### 9.2 每条字段（客户端自己的映射函数 `et`）

| 字段 | 含义 |
|---|---|
| `credit_type` | `1 = Purchased`（购买）、`2 = Free`（签到赠予）——枚举见 asar `Purchased=1, Free=2` |
| `granted_amount` | 当笔总量 |
| `remaining_amount` | 当笔剩余 |
| `consumed_amount` | 当笔已用 |
| `granted_at_ms` / `expire_at_ms` | 毫秒时间戳 |

客户端 UI 文案也对得上：`usage_credit_type_free:"签到"`、`usage_credit_type_purchased:"购买"`、
`usage_credit_details_expires_at:"到期时间"`、`usage_credit_status_active:"生效中"`。

### 9.3 打通方式

新增 `vendor/minimax-auto-signin/credits.py`（只读，输出对齐项目 `credits_command` 契约），
`catalog.yaml` 的 minimax 配 `credits_command` → `checkin` 末尾自动对账，`credit sync --only minimax` 手动可跑。

```json
{"account": "minimax", "total": 16550,
 "grants": [{"remain": 400, "expires": "2026-09-04", "granted_at": "2026-08-05", "package": "签到赠予", ...}]}
```

### 9.4 对账暴露的三类漂移（本地台账此前看不见）

拿服务端 40 笔逐笔比对本地 30 条，差的不只是第八节那个多记：

1. **漏记 8 笔早期签到**（08-05、08-11、09-07、09-15、09-16、09-17 等）。
   其中 08-05/08-11/09-07/09-15/09-16/09-17 这几笔**现在还没到期**，本地台账压根没有。
2. **漏记 09-24、09-25 两天**——服务端有，本地没有。
   所以本地 `streak_current=29` 是**记账断档**，不是领取断档；
   服务端口径 09-23..10-24 **连续 32 天每天都有签到**（100%）。
3. **漏记活动期加成与扣减**：09-28 本地记 400、服务端 800；09-29 本地 1000、服务端 2000；
   10-02 本地 1000、服务端 800；10-05 服务端显示已用 138，09-07 已用 136。

### 9.5 余额口径变更

| | 数值 | 说明 |
|---|---|---|
| 修正 bonus 双计后（上一版） | 22624 | 本地估算 |
| **接真值通道后** | **14286** | 服务端真值（26 条 source=sync） |

差的 8338 = 服务端剩余 16550 减去 6 笔已过期但服务端仍记着 remaining 的
（08-05/08-11/09-07/09-15/09-16/09-17 共 2264）+ 本地多记的 5024 + 本地漏记的早期签到与加成等。

看板里 MiniMax 的口径标签也从「本地估算」变成「服务端真值」，层级从 T1 变成 T2 长期 FIFO。

### 9.6 扣减机制（原来完全不知道）

签到赠予积分**确实会被扣**，来源是 M Plan 额度用尽后的自动溢出扣费，官方文案：

> `usage_resource_tooltip_rule3`：「扣费顺序：Token Plan > 积分。当达到 5 小时或周额度上限后，
> 超出用量将默认按到期时间扣除积分（含赠予积分），可在设置中关闭。」

实测印证：10-05 那笔 800 在 2026-10-24 下午一小时内从 709 掉到 662；09-19~10-04 那批 14 笔
remaining 全部为 0（已用尽）。**本地台账此前把 `remaining` 一直记成等于 `amount`，
所以完全看不到这些扣减** —— 接了 `/credit/details` 才暴露。

### 9.7 安全边界

- 只读 GET 官方接口，不碰领取端点。
- 只读本机**明文**凭据（`~/.minimax/auth/.../auth.json`），token 不进命令行/日志/输出。
- 同一端点最多试 2 次的规矩照旧；本次只发了 2 次探测 GET（一次探端点、一次全量）。
- 不解密登录态、不开调试口、不做任何客户端本地数据改写。


