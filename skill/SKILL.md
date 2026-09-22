---
name: agent-credit
description: 查询或登记 AI Agent 软件积分、每日签到待办、以及按任务推荐先用哪家。用户提到签到、额度、积分余额、今天用哪个 agent、AutoClaw/WorkBuddy/MiniMax/TraeWork/LobsterAI 时使用。
---

# Agent Credit

本地台账在 `C:\Users\Hunter\Documents\Warpeas\agent-credit`。所有写账只通过 CLI，不要手改 `data/ledger.json`。

## 调用

在该目录执行（Windows）：

```bat
python C:\Users\Hunter\Documents\Warpeas\agent-credit\credit.py <命令>
```

也可用 `C:\Users\Hunter\Documents\Warpeas\agent-credit\credit.cmd`。

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

1. **不要启动** Mavis、MonkeyCode Token、Loomy、Coze、小浣熊、千问、Accio、阶跃等登录即领且当日过期的客户端。`open` / `checkin --open` 也不得打开它们。推荐里最多说「你要干这个的话先打开 xxx」。
2. `checkin` 退出码：`0` 全部自动完成；`2` 有待手签；`1` 失败。把 CLI 原文给用户，待手签列出软件名。
3. AutoClaw 是**每日手动签到 200**，不是月度登录。用户说「AutoClaw 签了」→ `record autoclaw claimed 200`。
4. 推荐以 CLI 输出为准，不要即兴改烧法。顺序：已打开的当日清零 > 7 天内到期 > 长期 FIFO > 有上限 > 无过期（AutoClaw）。轻活不要动 MiniMax/WorkBuddy 囤积分。
5. DuMate / ToDesk 默认不领。`due` / `recommend` 只有余额低于上限阈值才提示。
6. 不要打印、复制 token，不外传任何登录态给第三方，不解密加密存储的登录态（如 TraeWork 的 storage.json）。允许的例外：读取本机**明文**凭据（如 WorkBuddy 的 workbuddy-desktop.info）直调**官方**接口的 external 脚本（vendor/ 内），其输出与命令行不得包含 token。
7. WorkBuddy 客户端会丢弃模拟点击（isTrusted 过滤），`claim_mode=external`（API 直签）是它唯一可靠路线，不要改回 ui。
8. AutoClaw 走提权 OCR 路线（scripts/ui_claim_autoclaw.ps1），签到成功后自动关客户端；手动跑会弹 1 次 UAC。

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
