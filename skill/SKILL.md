---
name: agent-credit
description: 查询或登记 AI Agent 软件积分、每日签到待办、以及按任务推荐先用哪家。用户提到签到、额度、积分余额、今天用哪个 agent、AutoClaw/WorkBuddy/MiniMax/Trae/LobsterAI 时使用。
---

# Agent Credit

本地台账在 `<REPO>`。所有写账只通过 CLI，不要手改 `data/ledger.json`。

## 调用

在该目录执行（Windows）：

```bat
python <REPO>\credit.py <命令>
```

也可用 `<REPO>\credit.cmd`。

| 用户意图 | 命令 |
|---|---|
| 还剩多少 / 签了没 | `status` |
| 今天该签谁 / 快过期 | `due` |
| 本机装了哪些 / 适配器 | `doctor` |
| 去签到 | `checkin` |
| 签到并打开待签客户端 | `checkin --open` |
| 只处理一家 | `checkin --only autoclaw` |
| 打开待签软件 | `open` 或 `open workbuddy` |
| 这个任务用哪个 | `recommend <用户原话>` |
| 手签完成 | `record <id> claimed` 或 `record <id> claimed 200` |
| 客户端里看到的余额 | `set-balance <id> <数量>` |
| 用掉一笔 | `record <id> used <数量>` |
| Trae 每包余额+过期明细 | `python scripts\trae_credit_detail.py`（`--record` 顺带登记余额） |
| MonkeyCode 积分总量（无逐条过期） | `credits monkeycode_credit` 或 `python -m agent_credit.mc_credits` |
| 签到后对账（真实余额+逐条过期） | `sync`，或 `checkin` 末尾自动跑（配了 credits_command 的账户） |
| 积分余额看板（余额+每条剩余/过期+烧卡顺序） | `board`，或 `python -m agent_credit.board` |

账户 id：`workbuddy` `minimax` `trae` `autoclaw` `lobsterai` `dumate` `todesk` `monkeycode_credit` 等，见 `catalog.yaml`。

## 硬规则

> **动手探测任何客户端之前，先读 `research/SAFETY.md`。**
> 那里有完整的禁止清单、允许路线优先级、探测预算和收手判据。
> 本节的规则 6 是它的摘要，冲突时以 `research/SAFETY.md` 为准。

1. **不要启动** Mavis、Loomy、Coze、小浣熊、千问、Accio、阶跃等登录即领且当日过期的客户端。`open` / `checkin --open` 也不得打开它们。推荐里最多说「你要干这个的话先打开 xxx」。
2. `checkin` 退出码：`0` 全部自动完成；`2` 有待手签；`1` 失败；`4` 已有另一条签到链路在跑
   （`logs\checkin.lock` 被占用，等它结束再试）。把 CLI 原文给用户，待手签列出软件名。
2b. `checkin` 在可见控制台先弹启动闸门：`Y`/`Enter` 立即开始，`N`/`Esc` 跳过今天的 UI 组，
   15 秒无输入自动开始（`--gate-sec` / `--no-gate` 可调）。计划任务按无人值守处理、不弹提示
   也不走旧的空闲闸门。用户按 N 时 `_daily_chain.ps1` 会跳过 Trae 明细同步与 Qoder 用量刷新。
3. AutoClaw 是**每日签到 200**（UI 自动/可手签），不是月度登录。用户说「AutoClaw 签了」→ `record autoclaw claimed 200`。
4. 推荐以 CLI 输出为准，不要即兴改烧法。顺序：已打开的当日清零 > 7 天内到期 > 长期 FIFO > 有上限 > 过期未知（AutoClaw）。轻活不要动 MiniMax/WorkBuddy 囤积分。
5. DuMate / ToDesk 默认不领。`due` / `recommend` 只有余额低于上限阈值才提示。
6. **账号安全优先于积分收益**（完整版见 `research/SAFETY.md`）：
   - **禁止**：解密加密存储的登录态（Trae `storage.json`、AutoClaw `auth.json` 的 safeStorage）、
     内存注入/hook 取 token、开 remote-debugging / CDP 调试口、篡改客户端本地数据伪造额度、
     高频并发压测式请求、绕过验证码、绕过完整性级别/反调试/代码签名、把凭据外传第三方。
   - **禁止写循环重试**。同一端点最多试 2 次，候选端点枚举上限 10 个，
     单次探索不超过 20 个工具调用。超了就停下写清卡点，别扩大探索面。
   - **允许**：只读本机**明文**凭据（WorkBuddy `workbuddy-desktop.info`、MiniMax `auth.json`、
     MonkeyCode `monkeycode-cookies.json`、LobsterAI sqlite 的 `auth_tokens`）直调**官方**接口；
     只读客户端二进制里的 i18n 文案与接口路径字符串；走客户端自身界面的 UI 自动化；
     只读 GET 查询余额/签到状态。
   - 凭据**运行时读取**，不落盘、不进命令行、不进日志、不进输出。
   - **查不到就写 unknown，别硬钻**。本项目一半以上的有效期就是 unknown，照样运转。
     账号被封的代价远高于多领 100 积分。
7. WorkBuddy 客户端会丢弃模拟点击（isTrusted 过滤），`claim_mode=external`（API 直签）是它唯一可靠路线，不要改回 ui。
7b. **`isTrusted` 不能当否决理由**（2026-09-25 主人定调，2026-09-26 复核）：该结论**只对 UIA 的
   `InvokePattern.Invoke()` 成立**；OS 级注入（`SetCursorPos` + `mouse_event`）与 external 直签都不受影响
   （MiniMax 09-23 用 OS 级注入签到成功）。某项 UI 路线失败时，先查坐标 / 入口定位 / 页面加载等待 /
   提权（UIPI），**不要先怪 isTrusted**。
8. AutoClaw 走提权 OCR 路线（scripts/ui_claim_autoclaw.ps1），签到成功后自动关客户端。
   **必须提权跑**：`python scripts\run_claim_only.py`（`--dry-run` 只定位不点签到）。
   AutoClaw 跑在更高完整性级别，未提权时 `mouse_event` 注入会被 UIPI 丢弃——
   表现是「坐标对、窗口也在前台、但点了没反应」，页面纹丝不动。脚本已内置同页检测，
   遇到这种情况返回 `pending` 并提示提权，不要误判成「找不到入口」。
8b. Trae / TraeCode 走 `scripts/ui_claim_trae.ps1`（提权入口 `run_trae_claim.py`，
   支持 `--explore` 只抓布局 / `--dry-run` 只定位）。**前提：客户端必须已经打开**——
   托盘里、**任务栏最小化**的也算：2026-10-29 起脚本会枚举隐藏主窗口并 `SW_RESTORE` 还原
   （Qoder 同样；Qoder 的最小化分支是 2026-10-30 补的 `IsIconic` + `GetWindowPlacement`，
   见 catalog 的 qodercn notes）。
   本环境冷启动这两个客户端必失败（进程起不来，与 MiniMax 的 updater 现象同源），
   脚本找不到窗口就返回 `notfound` 并提示手动打开。菜单文案由服务端下发，
   所以锚点是多候选（中文「签到 / 每日签到」+ 英文「Check in / Checked in」），
   **且必须排除含「已」的状态文案**，否则点到的是状态不是按钮。
9. AutoClaw 的签到入口在「灵感中心」的任务卡片里（i18n 标题「每日签到」），**首页横幅受实验开关 `show_checkin_banner` 控制、生产默认不展示**。OCR 找不到锚点先怀疑「入口没渲染 / 页面没加载完」，不是脚本坏了。不为签到开 CDP（`AUTOCLAW_CDP_PORT`）：那是本机任意进程可连的调试口，且启用必须重启客户端。

## 补齐自动化路线

某家还没打通自动签到时，优先让软件自己交代（用 `research/prompts/UNIVERSAL.md`），
或扫它自己的 `resources/` 找端点字面量——两者都比盲试点击快。
（旧文案里的「容易被 isTrusted 挡」已作废，见硬规则 7b。）
用 `research/` 里的自述调研流程，让那家软件自己交代：

1. **全自动优先**（2026-09-25 主人要求）：新增/修复签到管线时，目标是「一条命令跑完、不需要主人开客户端」。
   凡要求客户端在前台的 UI 路线，都要先验证能否冷启动该客户端——
   本环境**冷启动不了 MiniMax Code（只起来 updater.exe）和 Trae（NO global context）**，
   这两家只能走 external 或另想办法；AutoClaw 可以冷启动。
2. 读 `research/prompts/UNIVERSAL.md`（通用一份，内附本机安装目录速查表），把围栏里的整段粘进该软件的对话框
2. 把它按 `research/ANSWER-SCHEMA.md` 的回答存进 `research/answers/<id>.md`
3. 跑 `python scripts\check_research_answers.py` 确认没混进 token 明文
4. `reliability: 已实测` 才改 `catalog.yaml`，顺手把失效条件写进 `notes`

## 流程

签到：

1. 跑 `due` 或 `checkin`
2. 自动项看 status=ok/failed（ok 已入账）
3. pending 的说明 UI 没点到签到；可用 `checkin --open` 打开已安装客户端，请用户点签到
4. 用户确认后 `record <id> claimed`（数量可省略，用 catalog 每日额度）
5. 用户报了客户端总余额 → `set-balance <id> <数量>`，不要当成签到

Trae 积分明细（余额+过期时间，2026-10-19 跑通并自动化）：

1. **每日自动**：`agent-credit-checkin` 每日任务的 action = `scripts/_daily_chain.ps1`
   （checkin → `trae_credit_sync.ps1` → `credit board`）。sync 聚焦 Agent 窗发 **Ctrl+Shift+N** 开 IDE 窗
   （newIDEWindow 内置快捷键；失败重试 3 轮，锁屏会全失败），扩展 startup/focus dump →
   `--record` 登记 → 关 IDE 窗，全程 ~25s。**只有新鲜 dump 才登记**（2026-10-20 实测：
   旧 dump 会把 claim 后真实余额覆盖成旧值）。手动跑一次：
   `scripts\_task_trae_credit_sync.ps1`；结果看 `logs/trae_credit_sync_result.json`。
2. **SOLO/Agent 窗口不加载用户扩展**（bundle 实锤 `scanUserExtensions` 直接 skip），
   dump 扩展只活在 IDE 窗口。手动入口：SOLO 右上角「IDE」按钮（⚠️ SOLO-lite 无命令面板）。
   扩展只 executeCommand 客户端自己注册的只读 getter —— 不碰凭据、不解密、无注入。
3. **过期时间口径**：结构化通道只给聚合 `expireTime`（最高优包到期日）——Free 单桶即
   「每笔」；实锤 2026-10-31 23:59 月底到期（validity 升 confirmed）。多包账号的每包
   明细只在「设置 → 用量管理」页渲染（`icubeOpenUsageDetails`），需要时走 OCR（未做）。
   `getEntitlementInfo()` 返回 pay status（活动/身份），不含 pack list。
4. `python scripts\trae_credit_detail.py` 解析打印；`--record` 经
   **`credit.py sync --only trae`** 走标准对账通道登记（写账只走 CLI）。
   ⚠️ 别再改回 `set-balance`：那条路写的是**无过期时间**的快照，「快过期先烧」对 Trae 就是瞎的。
   新鲜度闸门在通道内（按 beijingDayKey），不是今天的 dump 直接拒绝登记、不动账本。

对账（WorkBuddy 2026-10-19 / MonkeyCode 2026-10-20 / Trae 2026-10-20）：

1. `checkin` 末尾对配了 `credits_command` / `status_command` 的账户自动跑对账——
   拉服务端真实余额重建账本条目（source=sync），不记签到、不动连签；`credit sync` 可手动跑。
2. WorkBuddy 走 `credits_command`（逐条明细，每条带真实过期时间，`credit due` 临期视图直接受益）；
   `status_command`（一行 JSON 总量）是兜底契约。实测本地账本 3900 → 服务端真相 2717。
3. MonkeyCode 走 `credits_command`（一条总量、expires=null）。GET /users/wallet 的
   `balance` 是毫积分，入账前 ÷1000（10-04 界面 195 vs API 195267）。没有逐条过期，
   validity 维持 unknown。看板会把余额标成服务端真值、过期标成未知。
4. Trae 走 `credits_command`（`python -m agent_credit.trae_credits --json`），
   台账里从此有**真实到期日**（实测 2026-10-31 23:59）。
5. 对账失败只记日志，**不改 checkin 退出码**；`AGENT_CREDIT_SKIP_SYNC=1` 可关。

积分余额看板（2026-10-20 新增）：

1. `credit board` 输出：账户总表（余额/笔数/最近过期/口径）、临期队列（7 天内）、
   烧卡优先级、逐条明细、数据质量说明。落盘 `logs/board/board-日期.md` + `data/board.json`。
2. **口径必须分开标**：「服务端真值」（sync 条目）vs「本地估算」（按 catalog 有效期算的
   daily 条目）vs「过期未知」（AutoClaw 等服务端没下发有效期的）。别把估算说成真相。
3. 烧卡层级与 `recommend` 共用 `agent_credit/priority.py` 一份口径：
   当日清零 > 7 天内到期 > 长期 FIFO > 有上限 > 过期未知（最后动）。两处口径分家会打架。
4. `checkin` 末尾自动刷一次看板；每日链路（`_daily_chain.ps1`）在 Trae 登记后再刷一次，
   因为 Trae 的登记发生在 checkin 之后。

选软件：

1. 跑 `recommend <任务>`
2. 用输出里的「用时再开」和「台账内优先」回答
3. 用户说用了某家多少 → `record <id> used <n>`
