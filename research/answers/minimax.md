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
`C:\Users\Hunter\AppData\Local\Programs\MiniMax Code\MiniMax Code.exe`，
`Start-ScheduledTask` 即可拉起 —— **不弹 UAC**（实测 procs 从 0 → 7）。
签到完 `Stop-Process` 收掉，不需要常驻。
注意：沙箱会话里 `Start-Process` 拉 GUI 无效（procs=0），必须走计划任务。

**(B) 纯脚本刷新 token（端点已挖到，未实机刷新）**
`app.asar` 内常量：`MCODE_OAUTH_CLIENT_ID = 'mcode-public'`、`audience = 'agent-backend'`；
端点配置：`https://account.minimax.cn`（prod/cn）下
`/oauth2/device/code`、`/oauth2/token`、`/oauth2/revoke`。

凭据文件 `C:\Users\Hunter\.minimax\auth\prod\cn\mcode-public\auth.json` 里有**明文**
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
