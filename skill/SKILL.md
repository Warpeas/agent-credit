---
name: agent-credit
description: 查询或登记 AI Agent 软件积分、每日签到待办、以及按任务推荐先用哪家。用户提到签到、额度、积分余额、今天用哪个 agent、AutoClaw/WorkBuddy/MiniMax/TraeWork/LobsterAI 时使用。
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

账户 id：`workbuddy` `minimax` `traework` `autoclaw` `lobsterai` `dumate` `todesk` `monkeycode_credit` 等，见 `catalog.yaml`。

## 硬规则

> **动手探测任何客户端之前，先读 `research/SAFETY.md`。**
> 那里有完整的禁止清单、允许路线优先级、探测预算和收手判据。
> 本节的规则 6 是它的摘要，冲突时以 `research/SAFETY.md` 为准。

1. **不要启动** Mavis、MonkeyCode Token、Loomy、Coze、小浣熊、千问、Accio、阶跃等登录即领且当日过期的客户端。`open` / `checkin --open` 也不得打开它们。推荐里最多说「你要干这个的话先打开 xxx」。
2. `checkin` 退出码：`0` 全部自动完成；`2` 有待手签；`1` 失败。把 CLI 原文给用户，待手签列出软件名。
3. AutoClaw 是**每日手动签到 200**，不是月度登录。用户说「AutoClaw 签了」→ `record autoclaw claimed 200`。
4. 推荐以 CLI 输出为准，不要即兴改烧法。顺序：已打开的当日清零 > 7 天内到期 > 长期 FIFO > 有上限 > 无过期（AutoClaw）。轻活不要动 MiniMax/WorkBuddy 囤积分。
5. DuMate / ToDesk 默认不领。`due` / `recommend` 只有余额低于上限阈值才提示。
6. **账号安全优先于积分收益**（完整版见 `research/SAFETY.md`）：
   - **禁止**：解密加密存储的登录态（TraeWork `storage.json`、AutoClaw `auth.json` 的 safeStorage）、
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
8b. TraeWork / TraeCode 走 `scripts/ui_claim_traework.ps1`（提权入口 `run_traework_claim.py`，
   支持 `--explore` 只抓布局 / `--dry-run` 只定位）。**前提：客户端必须已经打开**——
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
   本环境**冷启动不了 MiniMax Code（只起来 updater.exe）和 TraeWork（NO global context）**，
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

选软件：

1. 跑 `recommend <任务>`
2. 用输出里的「用时再开」和「台账内优先」回答
3. 用户说用了某家多少 → `record <id> used <n>`
