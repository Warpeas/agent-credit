# AutoClaw 智谱 · Agent 能力自评

| 项 | 值 |
|---|---|
| 模板 | `prompts/agent_self_eval.md` |
| 填写者 | AutoClaw（智谱桌面 Agent，当前会话产品自身） |
| 评估日期 | 2026-10-25 |
| 本机版本 | 1.20.0（`C:\Program Files\AutoClaw\resources\app.asar` 内 `package.json`；asar 310,216,022 字节） |
| 本会话模型 | `zai/zai_auto`（Auto 路由）；图像模型 `zai/zai_auto-fast` |
| 上下文 | 1,048,576 tokens；max output 393,216（Auto） |

> 原则：只报本机/本会话能确认的能力；测不到或产品侧未确认的标「未确认」，不按满分估算。
> 依据分三级：**本机实测** > **客户端/官方文件** > **未确认**。
> 2026-09-24 的旧记录基于 1.19.0；本次按 1.20.0 重新核对，旧结论仍有效的保留，失效的单独标注。

---

产品名：AutoClaw（桌面 AI Cowork 平台，Electron + OpenClaw Gateway）
厂商：智谱 AI（ZhipuAI）
评估日期：2026-10-25

## 额度价值

| 指标 | 自评分(1-5) | 实际情况 | 依据 |
|---|---|---|---|
| 1.1 日额度 | 4 | 每日签到 **200 credit**（基础日额度；活动期另有一次性大额赠送，不计入这里），无基础/连签分档。按模板「200-499 = 4」计；不到 5（500+/天）。 | `catalog.yaml` autoclaw `daily_amount: 200`；`data/ledger.json` 33 笔签到全部 200；`logs/checkin_2026-10-25.log` 12:40 `+200`；主人 2026-09-24 已确认卡片副标题「签到得@20 积分」是显示/OCR 误差。 |
| 1.2 有效期 | 3 | **不是单一有效期，也不是「无过期」**：客户端积分分 `daily` / `monthly` / `longTerm` / `campaign` 四类，各类独立计算；存在「长期积分」，但 UI 也会滚动提示最近一批「N 积分将于 3 天内到期」。按模板无法用单值表达：不按 5（不能证明 30 天可累积）、不按 2（不是当日清零），保守给 3。台账 `expires_at=null` 是「服务端不下发逐条到期日」，不是「永不过期」。 | `catalog.yaml` `validity_audit_2026_10_04.autoclaw`（客户端明文 dist `/settings/credits`、i18n `creditsDetail.ledger.expiresAt`、四类 `walletItems`）；`README.md`「积分有效期」节；`research/answers/autoclaw.md` 2026-09-24 实测「152 积分将于 3 天内到期」。 |
| 1.3 连签加成 | 2 | 无连签加成、无月度固定赠送；33 笔签到全部 200，没有加成日。另有**不定期大额积分赠送活动**（非固定周期，不能算稳定连签加成）。200/天属中等偏大，按模板「无加成但额度大 = 2」计。 | `data/ledger.json` autoclaw `amounts = [200]`；`catalog.yaml` 无 `streak` 字段，`extra_note` 只记录不定期大额活动，不构成稳定加成；`README.md` 评级表「连签/额外：无（另有不定期大额积分活动）」。 |
| 1.4 可消耗性 | 3 | 台账只记发放、不记扣减，实际消耗率**未确认**；200/天 + GLM-5.3 属「高消耗」档，重任务容易不够、轻任务够用；余额累积到 6,600（本地估算），说明并非每天用满。**资源紧张时任务会直接停止执行，额度够也不一定跑得完。**按「偶尔够用 = 3」计。 | `%APPDATA%\autoclaw\settings.json` 模型 `creditConsumptionLevel`：Auto 低 / Auto-Fast 中 / GLM-5.3 高 / GLM-5.3-Flash 低；`data/ledger.json` 33 笔、`remaining_sum=6,600`；`logs/board/board-2026-10-25.md` 标「本地估算」。 |

## 能力覆盖

| 指标 | 自评分(1-5) | 实际情况 | 依据 |
|---|---|---|---|
| 2.1 模型代际 | 4 | 本机 1.20.0 模型目录**不是「只有 GLM」**：Auto（`zai_auto`，路由，`metadata.auto_model_name=deepseek-v4-pro`，1M 上下文 / 393k 输出，低消耗）、Auto-Fast（`zai_auto-fast`，1M / 131k，支持图片，中消耗）、GLM-5.3（`zaicoding_glm-5.3`，1M / 307k，高消耗）、GLM-5.3-Flash（`zai_glm-5.3-flash`，1M / 131k，支持图片，低消耗），另支持自定义 API（本机已加 Ollama qwen3:14b，200k 上下文）。给 4：有 DeepSeek-V4-Pro 路由 + GLM-5.3 这一代，但不是 5（内置目录只有 4 个，且 Auto 实际落点由服务端决定）。 | `%APPDATA%\autoclaw\settings.json` → `models.catalog`；`C:\Users\Hunter\.openclaw-autoclaw\openclaw.json` → `models.providers.zai.models`；`app.asar` 内 `package.json` version 1.20.0。旧记录「桌面端只有 GLM」与更早的「Pony-Alpha-2/DeepSeek/Kimi/MiniMax 多模型池」都不准确。 |
| 2.2 编码能力 | 5 | Agentic 编码闭环完整：读仓库 → 改多文件 → 跑脚本/测试 → 迭代修复；支持 Python / PowerShell / JS / Shell 等。本仓库的 AutoClaw 签到脚本与 2026-09-24 自述调研由本产品会话维护，2026-10-25 双击修复记录在 catalog notes；本次自评也在仓库内完成读改跑。子 Agent、cron、文件/终端工具齐全。 | 本会话工具链（`read`/`write`/`edit`/`apply_patch`/`exec`/`process`/`sessions_spawn`/`cron`）；`scripts/ui_claim_autoclaw.ps1`、`scripts/run_claim_only.py`、`research/answers/autoclaw.md`；`catalog.yaml` autoclaw notes 的 10-25 双击修复记录。 |
| 2.3 浏览器操控 | 4 | 产品侧有完整浏览器自动化：`autoglm-browser-agent`（`browser_subagent`）、`browser-automation` 技能、`autoclaw-visible-browser` 插件、本地 `docs/cli/browser.md`；能打开、点击、填表、截图、读页面。**本会话未实测**：`openclaw.json` 的 `tools.deny` 明确 deny 了 `browser`，且当前 MCP 无健康服务。按「能打开/点击/填表 = 4」计，不报 5。 | `openclaw.json` `tools.deny: ["browser","image"]`；`plugins.entries.autoclaw-visible-browser.enabled=true`；可用技能 `autoglm-browser-agent` / `browser-automation`；`resources/gateway/openclaw/docs/cli/browser.md`；工作区 `AGENTS.md` 的浏览器指引。 |
| 2.4 电脑操控 | 4 | 没有原生 `computer_*` 键鼠工具；但 `exec` 跑在本机 PowerShell（host=ASUS，`tools.exec.security=full`），能操作文件、启动软件、注册计划任务，并用 UIA/OCR/SendInput 做窗口管理与真实点击。本仓库 AutoClaw 签到就是提权 OCR + 真实点击跑通的。受 UIPI/前台锁/窗口态限制，给 4 不是 5。 | 本会话 `exec` 的 host/shell；`openclaw.json` `tools.exec.security=full`；`scripts/ui_claim_autoclaw.ps1`、`scripts/run_claim_only.py`；`research/answers/autoclaw.md` 的 UIPI/提权实测；`catalog.yaml` notes 的 BringBack/TOPMOST 修复。 |
| 2.5 多模态 | 4 | 输入：图片（Auto-Fast / GLM-5.3-Flash 的 `input` 含 `image`；`imageModel=zai_auto-fast`；也可走 `autoglm-image-recognition`），音频（`autoglm-asr-translate` 可转录）。输出：图片（`autoglm-generate-image-seedream`、`autoglm-image-edit`、`autoglm-search-image`、`autoglm-remove-bg`）、语音（`tts`）。视频生成**未确认**，故不给 5。 | `settings.json` 模型 `input` 数组；本会话可用技能清单；`tts` 工具；无视频生成技能。 |
| 2.6 移动端同步 | 3 | 有移动端；但移动端与桌面端项目**不同步**，是独立的云端 claw 环境。按「有移动端但不同步 = 3」。移动端模型是否与桌面一致**未确认**——旧记录说「同为 GLM」，但桌面端已确认 Auto 路由指向 DeepSeek-V4-Pro，不能沿用旧说法。 | `catalog.yaml` autoclaw `mobile: true` / `mobile_note`；`README.md` MiniMax 对比段；`settings.json` `cloudDevices`（remote sandbox，不等于移动端同步）。 |

## 领取可靠性

| 指标 | 自评分(1-5) | 实际情况 | 依据 |
|---|---|---|---|
| 3.1 领取方式 | 3 | UI 自动化 + OCR + 提权真实点击；每日计划任务 `agent-credit-checkin` 00:05 跑；不是 external 直签（token 在 `%APPDATA%\autoclaw\auth.json` 为 safeStorage `enc:`，按 `research/SAFETY.md` 不解密）。能全自动，但依赖窗口/焦点/提权，偶发失败，按「UI 自动但偶发失败 = 3」计。 | `catalog.yaml` `claim_mode: ui`；`scripts/ui_claim_autoclaw.ps1`、`scripts/run_claim_only.py`；`logs/checkin_2026-10-25.log`；`research/answers/autoclaw.md`。 |
| 3.2 稳定性 | 4 | 本地台账 33 笔（09-18..10-25）；09-24 自动化上线后 **31/32 天**有记录，只缺 10-07 一天，约 97%。最近 10-23/24/25 均成功；10-25 11:08 首击失败，12:40 双击补击成功（17→18 天）。没有独立 30 天成功率日志，不报 100%，按「≥90% = 4」计。 | `data/ledger.json` autoclaw entries（gap 10-06 → 10-08 仅 1 天）；`logs/checkin_2026-10-23.log`、`...10-24.log`、`...10-25.log` 的 `<ok>` 行。 |
| 3.3 脆弱性 | 3 | 依赖客户端 UI 锚点/OCR/React 真实点击/提权/前台焦点；改版或布局变化需调整。近期不是版本改版，而是 CEF 首击只聚焦、前台窗口遮挡等运行时问题，已用「短间隔双击 + 多轮 + HWND_TOPMOST」修复；按「偶需调整 = 3」计。不是 API 直签，不给 5/4。 | `catalog.yaml` notes【2026-10-25 双击签到】【2026-10-25 真实点击被前台窗口挡住】；`logs/checkin_2026-10-25.log` 的 11:08/12:40 两轮；`skill/SKILL.md` 硬规则 8/9。 |

## 实际体验

| 指标 | 自评分(1-5) | 实际情况 | 依据 |
|---|---|---|---|
| 4.1 响应速度 | 未确认 | 没有在产品内部可靠测量「发指令 → 首 token」的端到端延迟；资源紧张时任务会**停止执行/中断**，这不是单纯延迟变慢；本会话工具调用与流式输出体感正常，但没有可复现计时，不据此打分。 | 无客观测量数据；`settings.json` 的 `timeout=7200` 是超时上限，不是延迟。 |
| 4.2 指令遵循 | 4 | 能把复杂指令拆成多步并保持目标；本次按模板逐项核对、区分「本机实测/客户端文件/未确认」，并发现旧记录中的版本、模型、有效期错误；偶有需要补充约束。 | 本次填写与仓库核对过程；本仓库长期多轮任务（签到编排、OCR 取证、对账修复）的交付记录。 |
| 4.3 上下文管理 | 4 | 模型上下文 1,048,576 tokens（Auto/GLM-5.3 等），max output 393,216/307,200；OpenClaw 有自动压缩（reserve 40k）与跨会话记忆文件；长对话稳定。扣 1 分：压缩会把极早期细节摘要化，需要时仍要回读文件。 | `settings.json` 各模型 `contextWindow`/`maxTokens`；`openclaw.json` `compaction.reserveTokens=40000`；本会话长上下文与回读仓库文件的做法。 |
| 4.4 工具生态 | 4 | 扩展体系齐全：40+ 技能（docx/xlsx/pptx/pdf/browser/design/legal/finance 等）、MCP 配置（飞书/天眼查/企查查/北大法宝/元典等，部分启用）、插件（office-bridge/web-search/visible-browser/safety-guard 等）、子 Agent、cron、canvas、nodes、IM 通道。扣 1 分：本机 MCP 当前无健康服务，插件市场/上架机制未确认；按「MCP 或自有插件体系 = 4」计。 | 本会话可用技能清单；`openclaw.json` `mcp.servers`、`plugins.entries`；工作区 `AGENTS.md`「No MCP tools are currently healthy」；`skill_workshop` 工具。 |

## 补充说明

- **强项**：本地执行能力完整（文件/终端/计划任务/UIA/OCR）；agentic 编码闭环；1M 上下文；40+ 技能 + MCP + 插件 + 子 Agent + cron；UI 签到链路已实测跑通（09-24 起 31/32 天有记录）；10-25 双击修复后首击失效可自动补击。
- **短板**：内置模型目录只有 4 个（Auto/Auto-Fast/GLM-5.3/GLM-5.3-Flash），不是多厂商大池；移动端不同步桌面项目；签到依赖 UI 锚点/提权/前台焦点，偶发失败；积分有效期分类且逐条到期日服务端不下发，台账只能按「过期未知」处理；本会话 MCP 无健康服务、浏览器工具被 deny；响应速度无法量化。
- **实测体验（2026-10-25，主人反馈）**：
  - 经常容易资源紧张，任务会**停止执行**（不是变慢，是中断）。
  - 时不时有**送大额积分**的活动；活动期余额会突然增加，但周期不固定，不能当作稳定的日额度或连签加成。
- **给横向对比的提示**：
  1. **不要再说「AutoClaw 只有 GLM」**：1.20.0 的 Auto/Auto-Fast 的 `metadata.auto_model_name=deepseek-v4-pro`，另有 GLM-5.3/5.3-Flash；Auto 是路由，实际落点由服务端决定，但「只有 GLM」不成立。
  2. **1.2 不要用单值**：`daily`/`monthly`/`longTerm`/`campaign` 四类独立，UI 的「N 天内到期」是滚动提示，不能反推固定天数；台账 `expires_at=null` 是未知，不是永不过期。
  3. **3.x 是「本项目自动化视角」**：AutoClaw 没有 external 直签，UI 链路能全自动但比 API 直签脆；不要拿它和 MiniMax/WorkBuddy 的 external 5 分直接比。
  4. **2.3/2.4 是「产品具备、本会话未实测/脚本路线」**：浏览器工具在本会话被 deny，桌面操控走 PowerShell/UIA/OCR，不是原生 Computer Use SDK。
- **本次修正的项目记录**：
  - `catalog.yaml` / `README.md`：AutoClaw 版本 `1.19.0` → `1.20.0`（asar `package.json`；310,216,022 字节）。
  - `catalog.yaml` 顶部 / `README.md` L215：「无明确过期」→「有效期分类（daily/monthly/longTerm/campaign），不是『永不过期』；台账按过期未知处理」。
  - `catalog.yaml` / `README.md`：模型说明从「只有 GLM」改为 1.20.0 实际模型目录；`rating.capability` 3 → 4，README 评级 3.1 → 3.4。
  - `catalog.yaml` `capabilities`：`[coding, local]` → `[coding, office, docs, search, multimodal, local]`；新增 `validity_note: "分类（4 类）"`，`scripts/gen_rating_table.py` 已支持该字段并重生成 README 评级表；另加 `extra_note: "另有不定期大额积分活动"`，评级表「连签/额外」列会显示该备注。
  - `priority.py` / `board.py` / `recommend.py` / `SKILL.md` / `README.md`：T4 标签「无过期」→「过期未知」，避免把「服务端没下发到期日」误写成「永不过期」。
  - `research/answers/autoclaw.md`：顶部版本更新为 1.20.0，并追加「2026-10-25 复核」节（保留 2026-09-24 的 1.19.0 原始记录）。
  - `skill/SKILL.md`：「AutoClaw 是每日手动签到 200」→「每日签到 200（UI 自动/可手签）」。

---

*自评 ≠ 最终评分。本表由 AutoClaw 会话自身填写，供主人结合实测横向对比修正。*
