# AutoClaw 积分明细（逐条到期日）调研与路线登记

```yaml
account_id: autoclaw
software: AutoClaw 桌面端积分明细（逐条到期日）
version: "AutoClaw2（2026-11-10 本机运行中版本）"
researched_at: 2026-11-10
confidence: high
status: 已实测
automation: "已接入每日链（_daily_chain.ps1 采集→sync --only autoclaw）；签到自动化不变（ui）"

checkin:
  supported: true
  api: "UI 路线（灵感中心任务卡，scripts/ui_claim_autoclaw.ps1，未变）"
  daily_amount: 200
  validity_days: 7
  validity_note: "每日签到实测=发放后 7 天整过期（11-10 00:02 → 11-17 00:02:40）；活动/加油站类另有当天/月底口径，逐条各异"

credit_detail:
  supported: true
  route: "UI 只读采集：右上角余额数字按钮（header/credits，onClick 跳 /settings/credits）→ 「获得」过滤 → 滚动+加载更多 → OCR"
  scripts:
    capture: scripts/autoclaw_credits_ui_capture2.py
    parse: agent_credit/autoclaw_credits.py
  cli: "python credit.py credits autoclaw [--ledger|--line|--json|--allow-stale]"
  freshness_gate: "只解析当天采集（logs/autoclaw_credits_capture2.json 的 captured_at 日期必须=今天）"
  per_entry_remaining: "服务端不给逐条剩余 → FIFO 反推（consumed=Σ发放−余额，最早到期先清零），payload 标 fifo_assumed=true"
  granularity: per_pack

excluded:
  - "external 直调：X-Auth-Sign=md5(APP_ID&ts&APP_KEY) 需自算签名（SAFETY.md 第 4 节）"
  - "token-cache.json 明文 token 解锁不了签名要求；auth.json 仍是 safeStorage"
  - "技能中继 /skill-service/invoke：credits 无 capability（404 not_found 实测）"
  - "运行时 in-process SDK getCreditsLedgers：只在运行时进程内 IPC，子进程不可达"
  - "客户端本地缓存/日志：无积分流水落盘（2026-11-10 扫描 0 命中）"
```

日期：2026-11-10 · 结论可信度：**confirmed**（UI 实测 + 客户端 dist 字符串佐证）

## 结论

1. **每条发放流水的到期时间，客户端 UI 明细页直接展示**（「{{date}} 到期」，精确到秒）。
   早先「逐条到期日服务端不下发」的结论只对外部 API 成立；UI 属于
   `research/SAFETY.md` 允许路线 3（客户端自身界面）。
2. **每日签到 200 = 发放后 7 天整过期**：2026-11-10 00:02 发放 → 2026-11-17 00:02:40
   到期（多笔样本一致：11-09 21:56 → 11-16 21:56:25，11-07 00:34 → 11-14 00:34:31）。
   活动/加油站/月度类另有「当天 23:59:59 / 月底 / 自然日」口径，按条各自展示。
3. 服务端流水**没有逐条剩余**（renderer 条目 schema 只有
   `{id, description, occurredAt, expiresAt?, amount}`）；台账的逐条 remain 用
   **FIFO 反推**：consumed = Σ发放 − 当前余额，从最早到期整笔清零到余数笔。
   口径在载荷里标 `fifo_assumed: true`、`granularity: per_pack`。

## 数据通路（实锤，2026-11-10 本机 AutoClaw2 dist 复核）

- UI 路由：设置页 leaf tab `settings/credits`（surface
  `data-zwork-surface="settings/credits"`，i18n `creditsDetail.title`=「积分」，
  明细区标题 `creditsDetail.ledger.title`=「积分明细」，过滤 全部/消耗/获得，
  分页按钮 `creditsDetail.ledger.loadMore`=「加载更多」/`noMore`=「没有更多了」）。
- **入口**：主界面右上角余额数字本身是个按钮（surface `header/credits`，
  `onClick: () => { _$e(); t(uve) }`，`uve = "/settings/credits"`，title=`credits.detail`）；
  它旁边的「去购买」是另一个按钮（`onClick: () => a({type:"buy"})`，title=`credits.buy`）。
  点击余额数字左段（x + 25%w）即可安全进入明细页，不会误触购买。
- 底层协议（main.cjs，仅供理解，不外调）：zwork 桥命令
  `readCreditsLedgers(query)` → `requestEnvelopeData(p6i, {asset_type:"point",
  wallet_type:"all", page_size, cursor, flow_direction}, …)`；服务端原始条目
  `mutation_type === "credit" && n > 0` 才带 `expiresAt`（数学上 floor(n) 秒级时间戳）。
- **fetchPoints 只出聚合余额**（totalPoints/dailyPoints/monthlyPoints/… +
  walletItems[]），不带流水；流水必须走 `credits.ledgers.read`（UI 明细页用它）。

## 已探明并排除的路线（勿重走）

| 路线 | 结论 | 证据 |
|---|---|---|
| external 直调任务/积分 API | 仍排除：`X-Auth-Sign=md5(APP_ID&ts&APP_KEY)` 需自算签名 | SAFETY.md 第 4 节明文列名 AutoClaw |
| `autoclaw\token-cache.json` 明文 token | 不能解锁上面的排除：签名不随 token 走 | 2026-11-10 读文件核实（只有 token/refreshToken/updatedAt） |
| 技能中继 `/skill-service/invoke`（ZWORK_SKILL_SERVICE_URL） | 无 credits capability：`profile=zwork_client, operation=credits.ledgers.read` → HTTP 404 `not_found` | 2026-11-10 本机实测 |
| 运行时 in-process SDK（`getCreditsLedgers`，zwork-bootstrap-preload.cjs） | 只活在运行时进程内（IPC `zwork:auth:session`），子进程/脚本无法触达 | dist 静态分析 |
| 客户端本地缓存/日志（user-cache.json、logs/、Local Storage 等） | 无积分流水落盘 | 2026-11-10 全目录扫描 0 命中 |

## 采集实现（只读）

`scripts/autoclaw_credits_ui_capture2.py`：
前台化 AutoClaw2 → （如不在明细页）点余额数字 → 点「获得」过滤 → 循环
滚动 + 点「加载更多」直到「没有更多了」→ 点「返回」退出。
FORBIDDEN 词闸门（签到/领取/兑换/充值/购买/立即/确认/提交/删除）全程保留，
「兑换码」「去购买」「刷新」永不触碰。产出 `logs/autoclaw_credits_capture2.json`
+ `logs/autoclaw_credits/*.png`。

解析与对账：`agent_credit/autoclaw_credits.py`（OCR 行 → 条目 → FIFO），
CLI 入口 `python credit.py credits autoclaw [--ledger|--line|--json|--allow-stale]`。
**新鲜度闸门**：只解析当天采集（隔天拒绝登记，防旧值覆盖真余额）——
2026-10-20 Trae 旧 dump 覆盖真余额的教训同源。

## 已接入

- `catalog.yaml` autoclaw `credits_command: python "{REPO}\credit.py" credits autoclaw --ledger`
- 每日链 `_daily_chain.ps1`：checkin（领完即杀客户端）→ 冷启动采集 → `sync --only autoclaw`
- checkin 末尾的自动对账对 autoclaw 会先报一次「失败」（采集还没发生）——预期，不改退出码

## 失效条件

- 设置页/明细页改版、surface 改名（`settings/credits` / `header/credits`）；
- 余额数字按钮移除或与「去购买」合并；
- 「获得 / 加载更多 / 没有更多了」文案变更（服务端下发 i18n）；
- OCR 日期格式变化（现口径 `2026/11/10 00:02 · 2026/11/17 00:02:40 到期`，
  注意 OCR 会把首个斜杠/冒号变全角：`2026／11/0900：01`）；
- 客户端版本升级更换 renderer 结构（当前 AutoClaw2，2026-11-10）。
