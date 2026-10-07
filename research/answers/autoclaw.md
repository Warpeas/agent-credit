# AutoClaw 智谱 · 探索答案

| 项 | 值 |
|---|---|
| 账户 id | `autoclaw` |
| 状态 | **已填** · 可靠性：**未实测**（端点/host/鉴权 high；额度与周期仍 unknown） |
| 来源 | AutoClaw 客户端自述 + 本机复核，2026-09-24 |
| 版本 | 1.19.0（`resources/app.asar` 内 `package.json`，`name=autoclaw`） |
| 安全检查 | 已跑 `check_research_answers.py`；`APP_KEY` 在入库前已 `<redacted>` |

---

## 一、原始回答（AutoClaw 自述，保留原话）

```yaml
account_id: autoclaw
software: AutoClaw（智谱）
version: 1.19.0
researched_at: 2026-09-24
confidence: medium               # 端点/鉴权 high；额度/周期服务端下发无法确认

checkin:
  supported: true
  human_path: 首页右上角「每日签到」横幅（class `daily-signin-banner`）→ 直接点击即签到；或 侧边栏底部「灵感中心」入口（带 daily-signin 红点）→「每日签到」卡片 → 领取
  api: "POST https://autoglm-acceleration-api.zhipuai.cn/autoclaw-proxy/proxy/autoclaw-task-complete  body={task_id:'daily_signin'}；查询 GET https://autoglm-acceleration-api.zhipuai.cn/autoclaw-proxy/proxy/autoclaw-task-list?lang=zh-CN"
  cli: null                       # 无官方签到 CLI
  daily_amount: unknown           # 服务端 reward_points 下发；台账记的 200/天 我无法从代码证实
  streak_cycle: unknown           # 服务端下发（task 列表/元数据）
  validity_days: unknown          # 存在 /agent-assetmgr/api/v1/points/expiring → 积分会过期，天数服务端定
  cap: null
  idempotent: true                # 服务端返回 already_completed；重复触发安全

status:
  balance: "GET https://autoglm-acceleration-api.zhipuai.cn/agent-assetmgr/api/v2/wallets?biz_app_id=autoclaw（旧接口 /agent-assetmgr/api/v1/wallet-instances）；界面：右上角积分/会员入口 → 积分明细"
  claimed_today: "GET .../autoclaw-proxy/proxy/autoclaw-task-list?lang=zh-CN → 取 task_id=='daily_signin' 且 status=='completed'"
  unit: credit

automation:
  claim_mode: ui                  # external 仅靠 CDP 调 app 内 IPC 可行；直接 HTTPS 复用需解密 token（否决）
  command: unknown                # 未实测；CDP 路径见下方说明，未跑
  status_command: unknown         # 未实测
  blockers: "① 默认无 remote-debugging（需 AUTOCLAW_CDP_PORT 重启）；② token 在 auth.json 为 safeStorage 加密（enc:，按约束不解密）；③ 无公开签到 CLI；④ 手工 HTTPS 需自算 X-Auth-Sign=md5(APP_ID&ts&APP_KEY) 且需 Bearer token"
  reliability: 未实测             # command/status_command 为 推测

evidence:
  - "C:\\Program Files\\AutoClaw\\resources\\app.asar → package.json: {name:autoclaw, version:1.19.0}"
  - "out/main/index.js → const completeClientTask=(p)=>post('/autoclaw-proxy/proxy/autoclaw-task-complete',{...p}) ; getTaskList → GET `/autoclaw-proxy/proxy/autoclaw-task-list${qs}`"
  - "out/main/index.js → IPC.AUTH_COMPLETE_CLIENT_TASK: 校验 params.task_id 后调 completeClientTask({task_id})"
  - "out/renderer → const DAILY_SIGNIN_TASK_ID='daily_signin'; completeDailySignin → electronAPI.auth.completeClientTask({task_id:'daily_signin'})"
  - "out/main/index.js → getZaiProxyBaseUrl/getApiRequestHost: prod=autoglm-acceleration-api.zhipuai.cn / pre=autoglm-pre-api.zhipuai.cn / dev=autoglm-inner-3.zhipuai.cn"
  - "out/main/index.js → authHeaders: X-Auth-Sign=md5(`${APP_ID}&${ts}&${APP_KEY}`)，APP_ID=100003，APP_KEY=<redacted>；commonHeaders 追加 authorization=Bearer <token>（从 getAuthState().token / 缓存读，值 <redacted>）"
  - "out/main/index.js → /agent-assetmgr/api/v2/wallets?biz_app_id=autoclaw ; /agent-assetmgr/api/v1/points/expiring?biz_app_id=autoclaw"
  - "%USERPROFILE%\AppData\\Roaming\\autoclaw\\auth.json → token/refreshToken 前缀 'enc:'（safeStorage 加密），token-cache.json 同；无明文"
  - "out/main/index.js → remote-debugging-port 仅由 process.env.AUTOCLAW_CDP_PORT||AUTOCLAW_E2E_CDP_PORT 触发；当前 AutoClaw.exe 命令行未含该开关"
  - "out/renderer → daily-signin 横幅用普通 React onClick（无 isTrusted 校验）"

open_questions:
  - daily_amount / 连签周期 / 积分有效期 / 领取上限 均为服务端下发，代码中无硬编码，需登录取 task-list 或 wallets 实测
  - 是否有频控（重复调用 task-complete 的限流）未实测；幂等由 already_completed 推断
  - 打开 CDP 后外部调用 app 内 IPC 是否被附加风控未验证（client-sign V4 目前默认关，且只作用于模型请求）

catalog_patch:
  autoclaw:
    claim_mode: ui
```

自述的两条结论（原话摘录）：

- 外部自动化**能走通的一条**：设 `AUTOCLAW_CDP_PORT=9222` 重启 AutoClaw 后，用 CDP `Runtime.evaluate`
  直接调 app 自己的 IPC `window.electronAPI.auth.completeClientTask({task_id:"daily_signin"})`
  （不模拟点击、不解密 token）；不开 CDP 则只能模拟点击。
- 它（AutoClaw 内的 agent）**跨进程调不到该 IPC**，但**能建 cron**；要真正每天自签需走上面 CDP 通道。

---

## 二、本机复核（2026-09-24，逐条扫 `app.asar`）

复核方式：一次性脚本对 309,819,360 字节的 `app.asar` 做字节级正则命中，输出上下文中的
长串（APP_KEY / token）一律 mask。脚本为临时产物，未入库。

| 自述项 | 复核 | 说明 |
|---|---|---|
| Electron + `app.asar` 309 MB | ✅ | 309,819,360 字节；另有 `app.asar.unpacked` |
| version 1.19.0 / name=autoclaw | ✅ | `"name":"autoclaw","version":"1.19.0"` 全量唯一命中。注：该 asar 头部布局被 runtime patch 改过，简易 offset 解析失败（u32@12 不是 4），改用全量字面量扫描确认 |
| 端点 `.../autoclaw-task-complete`、`.../autoclaw-task-list` | ✅ | 各 1 处命中；另有 `/agentdr/v1/assistant/inspiration-task-complete` |
| host `autoglm-acceleration-api.zhipuai.cn` | ✅ | 7 处；prod / pre / dev 三套常量齐全 |
| 鉴权 `X-Auth-Appid`/`X-Auth-TimeStamp`/`X-Auth-Sign` + `authorization: Bearer` | ✅ | 8 处命中；APP_KEY 未入库 |
| `DAILY_SIGNIN_TASK_ID = "daily_signin"` | ✅ | 6 处；renderer 侧 `completeDailySignin` → `electronAPI.auth.completeClientTask` |
| `daily-signin-banner` | ✅ | 21 处，含 `className: "daily-signin-banner"` 与本地存储键 `dailySigninBanner.seenDate.v1` |
| token 为 `enc:` 前缀（safeStorage） | ✅ | `%APPDATA%\autoclaw\auth.json` 与 `token-cache.json`：`token` len=560、`refreshToken` len=556，均 `enc:` 前缀，无明文 |
| CDP 需 `AUTOCLAW_CDP_PORT` | ✅ | 命中；仅当显式设该变量（或 dev 构建）才 `appendSwitch("remote-debugging-port", …)` |
| 签到横幅无 isTrusted 校验 | ✅ | `role:"button"` + 普通 `onClick` / `onKeyDown`，无事件可信度校验 |
| 无官方签到 CLI | ✅（未证伪） | `resources` 下有 `gateway/openclaw`、`node`、`python`，未见签到子命令 |
| 额度 / 连签 / 有效期 = unknown | ✅ 一致 | 代码确无硬编码，`reward_points` 由服务端下发 |

**复核挖到、但自述没说清的三条**：

1. **首页横幅点击 ≠ 直接签到。** 代码是 `setInspirationView(true, "daily-signin-banner")`
   —— 横幅只是打开「灵感中心」视图并定位到签到卡片，真正的签到仍在任务卡片里
   （`completeDailySignin()` → `completeClientTask({task_id:'daily_signin'})`）。
2. **横幅本身可能根本不显示。** 命中实验开关常量 `show_checkin_banner`，`defaultValue: "off"`
   （注释原文：生产默认 / 对照组 / 取数失败兜底），非 release 构建才桌面端强制 true。
   这解释了 OCR 为什么长期找不到精确「每日签到」锚点——**不是脚本点错，是入口可能压根没渲染**。
3. **绝对 URL 属推断。** 代码里是 `post("/autoclaw-proxy/proxy/autoclaw-task-complete")`，
   base 来自 `getZaiProxyBaseUrl()`（url 以 `/` 开头时 axios 会丢弃 baseURL 的 path）。
   自述给出的绝对地址拼法合理，但未发过请求验证。

i18n 侧还捞到任务卡片的确定文案，可直接给 OCR 当锚点：
标题 `每日签到`、副标题 `赚 {{points}} 分/天`、已完成 `已完成`、已签到 `已签到…`。

---

## 三、对现有 OCR 路线的诊断

`scripts/ui_claim_autoclaw.ps1` 找不到精确「每日签到」就转点「灵感与活动」，再等 6 秒找锚点，
长期返回 pending。`logs/autoclaw_ocr_dump.txt` 的首页 dump 里只有「每日签到赚积分」（x=342,y=1562），
没有精确「每日签到」——与「横幅开关 off、入口在灵感中心」一致。

所以 **失败点不是 `isTrusted`**（横幅是普通 React 事件，OS 级点击本就绕得过），
而是**入口定位 + 页面加载等待**。修法方向（未实施）：

- 锚点改用 i18n 已知文案：`每日签到` / `赚 X 分/天` / `已完成`
- 进入「灵感与活动」后延长等待、多次采样 OCR，别只等一轮 6 秒
- 保留 `logs/autoclaw_ocr_dump.txt` 作为离线调参依据

---

---

## 三·补、2026-09-24 01:30 实测（DryRun）

主人授权后跑了两轮 DryRun，结论：

1. **几何没问题**。屏幕 3840×2160、DPI 192（200%），AutoClaw 主窗口
   `rect=520,132 → 3320,1932`（2800×1800），完全在屏幕内；点击换算后落在 (681,1704)，有效。
2. **但点击不生效**。探针点了「灵感与活动」@窗口内 (161,1572)：窗口集合不变、
   OCR 页面也一字未变（还是聊天页）。
3. **根因是 UIPI**。当前会话 `self_is_admin=False`，而对 5 个 AutoClaw 进程
   `OpenProcess(PROCESS_QUERY_INFORMATION)` **全部失败**——非提权进程连查询都做不到，
   更不可能注入输入。项目原本就靠 `run_claim_only.py`（`ShellExecuteW` + `runas`）提权，
   与这次观测一致。
4. **提权这一步我这边做不了**：`ShellExecuteW runas` 返回 5（拒绝访问，沙箱弹不出 UAC），
   `Start-Process -Verb RunAs` 被安全策略拦。**需要主人在自己屏幕上确认一次 UAC**。

### 实测顺带挖出的脚本 bug

点入口后脚本用 `Find-Line $lines "每日签到"`（Contains）做二跳匹配，于是把首页那条
「每日签到赚积分」（x=342,y=1562）当成了签到锚点，输出
`找到「每日签到」@ 342,1562，将点击按钮 @ 442,1657`——而首页第一轮本来是刻意排除它的。
结果就是**假阳性锚点 + 静默点错位置**。已修：

- 二跳改用 `Find-CheckinAnchor`（严格匹配，与首页一致）
- 新增 `Test-SamePage`：点入口前后比对 OCR 文本集合（Jaccard > 0.9 即判定页面未变化），
  命中就 `pending` 并明确提示「点击未生效，请提权跑」——不再伪装成「找不到入口」
- `Dump-Ocr` 提前并覆盖失败路径，pending 时也会落盘完整布局供离线调参
- `scripts/run_claim_only.py` 增加 `--dry-run` 与 `--extra` 参数透传

### 提权实测（2026-09-24 07:38，主人跑）——定位成功

主人以 `run_claim_only.py --dry-run` 提权跑（`ShellExecuteW ret: 42`，UAC 通过）：

```
{"detail": "找到「每日签到」@ 676,814，将点击按钮 @ 724,920", "status": "dryrun"}
```

**提权后点击生效、导航成功、锚点定位正确**，UIPI 假设正式坐实。主人截图（灵感与活动页）核对：

- 「每日签到」@ (676,814) = 赚积分任务第一张卡的标题，换算截图比例 ≈ (682,836)，吻合
- 按钮 @ (724,920) = 卡片里**黑色「签到」按钮**，换算 ≈ (739,929)，吻合。
  按钮匹配逻辑（`立即领取/去签到/立即签到/领取/签到`，≤6 字、排除含"每日/已"）命中的
  就是按钮文字本身；`已是最新版本`（升级卡）被"已"排除，`去邀请` 不在关键词表，均无误命中
- 卡片结构：标题「每日签到」/ 副标题「签到得@20 积分」/ 黑色「签到」按钮

**台账疑点（截图新证据，待签到后校准）**：

1. 副标题显示「签到得 @20 积分」——**主人已确认真实日额度是 200/天**，
   副标题的「@20」属显示/OCR 误差，台账 `daily_amount: 200` 不动
2. 右上角「我的积分 **1,352**」→ `set-balance autoclaw 1352` 可校准台账
3. 「152 积分将于 3 天内到期」→ 与 `points/expiring` 端点吻合，积分确实会过期

### 真跑结果（2026-09-24 23:57）——链路打通，今日已签

主人问「这命令不能由你来调起来吗」→ 可以，**但要走沙箱外通道**（沙箱内 `ShellExecuteW runas`
返回 5，UAC 弹不出来）。沙箱外跑 `python scripts/run_claim_only.py`：`ret: 42`，UAC 由主人在屏幕确认：

```
{"detail": "今日已签到（．已完成已签到1天），无需重复点击；已关闭客户端", "status": "already"}
```

- 主人当天已手签过：卡片 OCR 显示「已完成 / 已签到1天」→ 已签态命中，幂等保护生效，未重复点击
- **已签态的 OCR 锚点确认可用**：`已完成`、`已签到N天` 就是卡片上的状态文案
- 副作用：成功/已签分支会 `taskkill AutoClaw.exe`，客户端被关闭（脚本既有设计）
- 已入账：`record autoclaw claimed 200` → 剩余 600，连签 1 天，上次 2026-09-24

**结论：AutoClaw 自动签到链路已打通**（提权 → 导航 → 定位按钮 → 幂等判定 → 入账）。
下一步是放进每日计划任务（`scripts/register-task.ps1`）观察稳定性，连跑 3 天无 pending 再固化。

### 对照实验（2026-09-25 00:03）：不提权到底行不行

主人问「不提权不能跑吗」——之前的失败测试都在**沙箱内**跑，沙箱本身可能就挡住跨进程输入，
所以补了一次对照：**沙箱外 + 不提权**跑 DryRun。

```
{"detail":"点击「0灵感与活动每日签到赚积分」后页面无变化：点击未生效。未提权时输入会被 UIPI 丢弃",
 "status":"pending"}
```

→ **沙箱外不提权依然点不动**，沙箱不是元凶。三组对照：

| 条件 | 结果 |
|---|---|
| 沙箱内 · 不提权 | 页面无变化（点不动） |
| 沙箱外 · 不提权 | 页面无变化（点不动） ← 本次新数据 |
| 沙箱外 · 提权 | 成功导航并定位按钮 ✅ |

**结论：必须提权。** 好在这对自动化几乎零成本——计划任务勾「以最高权限运行」即可，
静默提权不会弹 UAC。

补充：本次想读 AutoClaw 进程完整性级别做铁证时，进程已退出（`Get-Process AutoClaw` 空），
没取到 `TokenElevation`。证据强度是「三组行为对照」而非「直接读到 IL 值」，够用但不算铁证；
哪天 AutoClaw 改成非提权启动，可以不提权再试一次。

### 顺带修的真 bug：OCR 合并行导致入口点偏

本次 OCR 把「灵感与活动」和「每日签到赚积分」**并成一行**，脚本取整行中心点到
(287,1573)——偏到了旁边那个「每日签到赚积分」元素上（正确入口是 161,1572）。
这类偏移会伪装成「点击未生效」，干扰 UIPI 判断。

已修：`Get-OcrLines` 现在保留每行 `words`，新增 `Find-WordHit` 按**词**定位
（单词直接命中 → 连续词拼接命中），入口「灵感与活动」与回退「我的积分」都走词级，
找不到才回退整行。语法校验 `errors=0`，待下次实跑验证。

### 第二次真跑（2026-09-25 00:11）——**真正签到成功**

```
{"detail": "点击后显示: ．已完成已签到2天；已关闭客户端", "status": "already"}
```

判读关键在「点击后」三个字（连签从 1 天 → **2 天**）：

- 9-24 那次是 `今日已签到（…已签到1天），无需重复点击` = **点击前**就已签，走了幂等分支
- 9-25 这次是 `点击后显示` = **这次点击才完成签到**

即：**AutoClaw 端到端自动签到首次真正成功**。入账 `record autoclaw claimed 200`
→ 余额 800，连签 2，上次 2026-09-25。客户端照例被 taskkill 关闭。

**顺手修的判定埋雷**：脚本把「点击后才变成已完成」也归为 `already`。现在手动入账没事，
但将来若接自动入账（`ok` 才入账）会静默漏掉一整天。已改：点击后的 `alreadyHit` 判 `ok`，
并注释清楚「点击前已签」由上面 `doneLine` 分支提前返回 `already`，两者不能混。

### 广告遮罩（2026-09-26 主人观察 → 修复）

主人实测观察：**第一次启动时有广告遮住主界面，点击后没跳转；第二次没有广告，点击「灵感」
才跳过去；且签到卡片加载花了一段时间。**

这与「云端内容渲染慢」是**两个独立因素**。脚本原缺陷是：一上来就 `Close-AdOverlays`，
**广告还没出现就清，清完广告才冒出来，等于白清**。

修了三处（语法校验 `errors=0`）：

1. **预热**：拉前台后先等 8 秒让广告出现 → `Close-AdOverlays` → 再等 2 秒 → OCR
2. **入口查找多重试**：找不到「灵感与活动 / 我的积分」时循环 3 轮（每轮等 5 秒 + 关广告 + 重扫），
   不再试一次就放弃
3. **签到卡片多轮等待**（昨晚已加）：6 轮 × 5 秒，卡片是云端下发的，冷启动后十几秒才渲染

重跑验证：`今日已签到（．已完成已签到3天），无需重复点击` —— 成功导航到签到页并正确判已签。

**沉淀**：这类客户端「看不见目标」有三类不同原因，必须分开处理——
① 广告遮罩（等它出现再关）② 云端内容渲染慢（轮询等）③ 未提权 / UIPI（点击完全无效）。
按 SKILL 硬规则 7b，先查这三样，别先怪 `isTrusted`。

### 第三次跑（2026-09-25 00:18，同日第二次）——幂等正确 + 前台修复

主人在跑的过程中把 AutoClaw 切到后台，脚本报：

```
{"detail": "AutoClaw 未在前台（请点击其窗口后重试）", "status": "pending"}
```

根因：**旧的前台逻辑只有一句 `SetForegroundWindow`**，用户在操作电脑时 Windows 会拒绝
非前台进程的切换请求，45 秒轮询全部失败。对无人值守场景这是硬伤——主人只要在用电脑就会漏签。

已把 `Wait-Foreground` 做成逐级加码（`Ensure-Foreground`）：

1. 最小化则 `ShowWindow(SW_RESTORE)`
2. **Alt 技巧**：`keybd_event(Alt 按下)` → `SetForegroundWindow` → `keyup`（Windows 通常放行）
3. **绑输入队列强切**：`AttachThreadInput(当前线程, 目标窗口线程)` → 切 → 解绑
4. 仍失败才继续轮询到 45 秒超时

修完重跑（主人刚操作完电脑的同一场景）：

```
{"detail": "今日已签到（．已完成已签到2天），无需重复点击；已关闭客户端", "status": "already"}
```

**幂等正确**：进入页面识别到「已完成 / 已签到2天」，点击前即判定已签，**没有重复点击**，
连签维持 2 天。台账不再入账（当天已记 200）。

三次连跑观察（可靠性初判）：

| 时间 | 结果 | 含义 |
|---|---|---|
| 9-24 23:57 | `今日已签到…无需重复点击` | 主人当天已手签，幂等分支 |
| 9-25 00:11 | `点击后显示…已签到2天` | 本次点击签到成功 |
| 9-25 00:18 | `今日已签到…无需重复点击` | 同日重跑，幂等，未重复签到 |

→ 幂等与重复跑都是安全的，可以挂计划任务。

### 待办

在**管理员 PowerShell** 里跑（或普通终端跑、屏幕确认 UAC）：

```bat
python <REPO>\scripts\run_claim_only.py --dry-run
```

预期两种结果：

- `pending` + 「页面无变化」→ 提权也没解决，得换思路（CDP 或放弃自动）
- `dryrun` + 真实锚点坐标 → 拿坐标回填锚点，再跑一次真签到并入账

---

## 四、处置

- **`catalog.yaml` 的 `claim_mode` 保持 `ui`，`command` 不填**——`reliability: 未实测`，
  按 `research/README.md` 的规矩不得改运行时字段。
- 已把端点来源、入口线索、横幅开关、失效条件写进 `catalog.yaml` 的 `autoclaw.notes`（纯注释，不改行为）。
- `skill/SKILL.md` 已加一条：不为签到常开 CDP；OCR 找不到锚点先怀疑入口没渲染。

## 五、下一步（均未执行，需主人定夺）

1. **DryRun 定位**：在你不用 AutoClaw 时跑
   `powershell -ExecutionPolicy Bypass -File scripts\ui_claim_autoclaw.ps1 -DryRun -OutFile logs\autoclaw_claim.json`。
   注意它会把 AutoClaw 拉到前台并按 ESC 关弹窗，**会打断当前对话**，所以不能现在跑。
2. **不建议为签到常开 CDP**：`remote-debugging-port` 是本机任意进程可连的调试口，
   且启用必须重启客户端。只在 OCR 彻底走不通时再评估。
3. **它的 cron 自签没有优势**：AutoClaw 内的 agent 跨进程调不到 IPC，cron 最终还是要落到
   CDP 或 UI 点击上，反而多一层依赖。
