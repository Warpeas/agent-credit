# TraeWork / TraeCode · 调研结论（2026-09-26）

| 项 | 值 |
|---|---|
| 账户 id | `traework`（**不新增 `traecode`，两者共享积分账户**） |
| 状态 | **已填** · 可靠性：未实测（端点 high；自签方案未跑） |
| 来源 | TraeWork 与 TraeCode 各自自述（`research/prompts/UNIVERSAL.md`）+ 本机逆向复核 |
| 结论 | 端点明确、规则明确；**自动化两条路都不划算或做不到** → 维持 manual |

---

## 零、先说结论（我的判读）

1. **两个产品是同一套签到**：`TRAE SOLO CN`（TraeWork）与 `Trae CN`（TraeCode）
   的 `out\main.js` 大小只差 3 字节，共用 `api.trae.cn` 的同一组接口。
   **主人已确认两者共享积分账户 → 每天只需签一次。**
2. **external 不可行**：鉴权头是 `Authorization: Cloud-IDE-JWT <token>`，
   token 只存在于 Electron 主进程内存（源自 `storage.json` 那份**加密**登录态的运行时解密值）。
   按硬规则 6，不解密 → 拿不到凭据。
3. **UI / 自签也都不划算**：
   - 我这侧：两个客户端**都冷启动失败**，且登录态加密
   - 它那侧：有内置定时任务（左栏「自动化」），但定时唤起的是 agent，
     agent 跑在隔离 V8（无 fetch），只能靠"电脑控制"去点界面，
     **且每次运行自己会消耗积分**——净收益可能为负
4. **规则已确认**：150/天（免费）、200/天（会员）、有效期 31 天、
   **无连签奖励**（官方「月最高 6,200」= 200×31 纯线性）、每月登录赠 500（当月有效）

---

## 一、本机逆向（2026-09-26，我做的）

| 项 | 事实 |
|---|---|
| 两个安装目录 | `…\TRAE SOLO CN`（TraeWork）、`…\Trae CN`（TraeCode），均为 VS Code 系，明文 `resources\app\` |
| 共用端点 | `POST https://api.trae.cn/trae/api/v2/ug/checkin_credits/status` \| `/claim`（host 从 `%APPDATA%\Trae CN\logs\*\main.log` 的 `ttnet fetch request` 行得到） |
| 裸连实测 | HTTP 200，业务 `code 1001 未认证`，返回字段 `checked_in` / `enable` |
| 登录态 | `%APPDATA%\<产品>\User\globalStorage\storage.json` 键 `iCubeAuthInfo://icube-dc:<deviceId>`（776 字符，**非 JSON = 加密**）→ 不碰 |
| 冷启动 | 两个都失败：`ShellExecuteW(open)` 返回 42，45 秒后无任何新进程 |

---

## 二、TraeWork 自述（原话摘录 + YAML）

探索日志要点：版本 0.1.69（build 2.3.87413）；签到代码在 `@byted-icube/ai-modules-chat`、
`desktop-modules`、`solo-lite`、`webcomponents`；核心方法 `claimCheckin()` → `getCheckinPort().claim()`；
有 `scheduleCheckinDayRefresh()` 但**只刷新状态不会自动签到**；agent 运行在隔离 V8（**无 fetch、
无网络**），不能直接调 API；CLI 是标准 VS Code CLI 无签到子命令。

```yaml
account_id: traework
software: TraeWork (TRAE SOLO CN)
version: 0.1.69 (build 2.3.87413)
researched_at: 2026-09-26
confidence: high

checkin:
  supported: true
  human_path: "左下角头像 → 签到按钮（每日签到: {credits} credits）"
  api: "POST https://api.trae.cn/trae/api/v2/ug/checkin_credits/claim"
  cli: null
  daily_amount: 150          # 免费用户；会员 200（extra_credits +50）
  streak_cycle: null         # 未发现连签阶梯奖励；会员每月多得 1550 是固定每日 +50 而非连签
  validity_days: 31
  cap: null
  idempotent: true

status:
  balance: "界面：头像菜单 → 查看积分；API：GET /v1/billing/credit_balance_summary"
  claimed_today: "界面：头像菜单签到按钮显示「已签到」；store.checkinCredits.checkedIn"
  unit: credit

automation:
  claim_mode: manual
  command: null
  status_command: null
  blockers: "AI Agent 运行在隔离 V8 上下文，无 fetch/无内部 service 句柄；登录态加密存储"
  reliability: 未实测
```

它的原话结论：

> **不能直接调用 API 签到**，但可以做定时 + 间接方案。Schedule 工具可配
> `cron: "0 9 * * *"` 做每日提醒；computer-use 模拟点击待实测。

---

## 三、TraeCode 自述（质量更高，原话摘录 + YAML）

它挖到了我这边没拿到的关键细节：

- 鉴权头 `mixAuthorization: 'Cloud-IDE-JWT'`，另带 `x-device-id` / `x-app-version`
- claim 只注册了一个内部命令 `workbench.action.icubeClaimCheckinCredits`，
  走 sandbox IPC 频道 `vscode:sandbox::main-invoke-claimCheckinCredits`，**外部进程无法触达**
- CLI 子命令仅 `chat / tunnel / user / login`，**无 `--command`**，无 deep-link
- status 响应只消费 `enable / checked_in / did_checked_in / credits / extra_credits / beijingDayKey`
  ——**没有 streak 字段**
- 有内置定时任务：左栏顶部「自动化」，支持每天/周/月，运行环境必须选**本地**
- Hooks 只有 6 个会话事件，**无定时事件**

```yaml
account_id: traework
software: TraeWork (TRAE SOLO CN)
version: 1.107.1
researched_at: 2026-09-26
confidence: high

checkin:
  supported: true
  human_path: "左下角头像 → 菜单「签到」按钮（云端开关 checkinMenuEnabled 控制）"
  api: "POST https://api.trae.cn/trae/api/v2/ug/checkin_credits/claim ；body={req_source:1}；鉴权 Authorization: Cloud-IDE-JWT <运行时内存 token，来源 storage.json 加密登录态，未解密>"
  cli: null
  daily_amount: 150                  # 免费；会员 200/天
  streak_cycle: null                 # 无连签周期/加成
  validity_days: 31
  cap: "免费 150/天（31 天月最高 4,650）；会员 200/天（月最高 6,200）"
  idempotent: true                   # 推测（代码守卫，未实点）

automation:
  claim_mode: manual
  command: null
  status_command: null
  blockers: "token 只在 Electron 主进程内存；无 CLI --command、无 deep-link、无本地 HTTP；Shell/MCP 无法触达 IPC；登录态加密按硬规则不解密"
  reliability: 未实测

# 以下 status 段它没给，是按本项目 schema 补的（非原话）
status:
  balance: "头像菜单 / 账户管理界面；status 接口字段 credits / extra_credits"
  claimed_today: "status 接口 checked_in（按北京自然日 beijingDayKey 判定）"
  unit: credit
```

它的原话结论：

> 定时器**我有**（左栏顶部「自动化」= 内置定时任务，支持每天定点、本地环境无人值守跑 Prompt），
> 但定时唤起的那个我**仍然够不到签到接口**。唯一能闭环的配法是
> 「定时任务（本地）+ 电脑控制去点头像菜单的签到」，UI 自动化未实测，
> **且每次自签本身会消耗少量积分**。

（YAML 里 status 段它没给，我按项目 schema 补在代码块内并标注了「非原话」。）

---

## 五、OCR 路线打通（2026-09-27 00:57 实测成功）

`scripts/ui_claim_traework.ps1` + `scripts/run_traework_claim.py`（提权，`--shots` 截图诊断）。

**打通过程中的四个真问题与修法**（全靠截图肉眼看，OCR 文字看不出）：

1. **提权才能冷启动**：未提权 `ShellExecuteW(open)` 起不来（之前结论"冷启动必失败"是错的），
   走 `runas` 提权启动成功 → 推翻了"必须主人手动打开"的前提
2. **签到按钮文案是「每日领150积分」不是「签到」**：且 OCR 会把它**拆成单字**
   （每/日/领/150/积/分），Contains 匹配必失败 → 必须用 `Find-WordHit` 的连续词拼接
3. **菜单是 toggle**：多个候选点轮流点击会互相打架（点开又被下一个候选点关掉）
   → 每个候选点只点一次，点完连续检测，没检测到就 ESC 收场换下一个
4. **「每日领150积分」是说明文字，签到按钮是它右侧的黑底白字「签到」**（OCR 漏检黑底白字）
   → 点击位置按文字行 +380px 偏移轮换（380→300→450→文字本身）

**实测**：`ok` —— 「签到成功（点击后显示: 本账号今日已签到，明日再来）」。
入账 `record traework claimed 150` → 余额 300，连签 1，上次 2026-09-27。客户端照例被关闭。

**遗留**：偏移 380 是按本次窗口（约 2560 宽）量的，窗口尺寸大变时可能要重调——
好在脚本有 `--shots` 截图与词级 dump，排查成本已很低。

---

## 六、最终处置

- **不新增 `traecode` 账户**：主人确认共享积分账户，新增会导致重复计数
- `catalog.yaml`：`claim_mode: manual`（诚实反映"需主人开客户端 + 确认 UAC"）；
  `validity_days: 31`；`daily_amount: 150`（官方确认）；**无连签奖励**；
  每月登录赠 500（`extra_monthly: 500` 已有）
- **不启用它内置的「定时任务 + 电脑控制」自签**：日收益 150，定时 agent 每次运行
  自身消耗积分（数量未知），净收益可能为负
- 现行流程：跑 `python scripts\run_traework_claim.py`（弹 UAC 确认）→
  脚本自动开菜单、点签到、验证、入账前先确认状态 → 手动 `record traework claimed 150`
  （或由我代跑并入账）
