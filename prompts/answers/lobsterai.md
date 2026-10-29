# LobsterAI · Agent 能力自评

| 项 | 值 |
|---|---|
| 模板 | `prompts/agent_self_eval.md` |
| 填写者 | LobsterAI（有道龙虾，当前会话产品自身） |
| 评估日期 | 2026-10-25 |
| 本机版本 | 2026.10.16（`app.asar/package.json`） |
| 本会话模型 | `lobsterai-server/deepseek-flash`；客户端默认 `yd-fast`，UI 显示 DeepSeek-V4.1-Flash |

> 原则：只报本机/本会话能确认的能力；测不到或产品侧未确认的标「未确认」，不按满分估算。
> 依据分三级：**本机实测** > **客户端/官方文件** > **未确认**。

---

产品名：LobsterAI（有道龙虾，桌面端 Agent）
厂商：网易有道
评估日期：2026-10-25

## 额度价值

| 指标 | 自评分(1-5) | 实际情况 | 依据 |
|---|---|---|---|
| 1.1 日额度 | 3 | 每日签到 **100 积分**；无基础/连签分档。新用户另有一次性 300 赠送（台账日历记为 2026-09-29 到期，已过期）；官网「¥0.01 解锁 1000 积分」是付费促销，不算免费日额度。按模板「100-199 = 3」计。 | 2026-10-25 只读 `GET /api/client-activities/daily-check-in-evergreen-prod-20260814/context?configRevision=1` → `state.rewardCredits=100`、`claimedDays=34`、`claimedCredits=3400.0`；`catalog.yaml` lobsterai `daily_amount: 100`；`README.md` 评级表「100/天」 |
| 1.2 有效期 | 5 | 签到积分 **30 天有效、可累积**，不是当日清零。按模板「30+ 天可累积 = 5」计。 | `catalog.yaml` `validity_audit_2026_10_04.lobsterai`：asar i18n `dailyCheckInValidityDays` 为服务端变量，UI 实测 30 天；本地台账 09-28..10-25 每条 `expires_at = granted_at + 30 天` |
| 1.3 连签/额外加成 | 1 | **无连签加成、无月度固定赠送**；`claimedCredits / claimedDays = 3400 / 34 = 100`，逐日线性，没有任何加成日。只有一次性新用户 300 赠送，不构成持续加成。按模板「无加成且额度小 = 1」计。 | 2026-10-25 context 的 `claimedDays/claimedCredits`；`catalog.yaml` lobsterai 条目无 `streak`/`bonus` 字段；`README.md` 评级表「连签/额外：无」 |
| 1.4 可消耗性 | 3 | 100/天能覆盖轻量办公/编码任务，但做长链路 agentic 任务时偏紧；产品没有暴露单任务消耗/余额的只读接口，台账也只记发放、不记扣减，所以「一天到底能花掉多少」无法精确量化。按模板「偶尔够用 = 3」计，实际消耗率标 **未确认**。 | 本会话是长任务会话，但客户端 `cowork_messages` 无 token/credit usage 字段；`catalog.yaml` 备注「无 external 余额端点、本地 sqlite 无积分缓存 → 余额只能 UI OCR」；`README.md` 对账表把 LobsterAI 标为「本地估算」 |

## 能力覆盖

| 指标 | 自评分(1-5) | 实际情况 | 依据 |
|---|---|---|---|
| 2.1 模型代际 | 4 | **内置免费模型只有 DeepSeek-V4.1-Flash**（`lobsterai-server/yd-fast`；本会话 `lobsterai-server/deepseek-flash`）。BYOK 可接 18 家 provider（另含内置 `lobsterai-server` 与自定义），且都是当代款：OpenAI GPT-5.6 Sol/Terra/Luna、GPT-5.5/5.4；Anthropic Claude Opus 4.7/4.6、Sonnet 4.6；Gemini 3.1 Pro/3 Flash；xAI Grok 4.5/4.3；DeepSeek V4 Flash/Pro；Kimi K3/K2.6/K2.5；GLM 5.1/5/4.7；MiniMax M3/M2.7/M2.5；Qwen3.6/3.5 Plus；Doubao-Seed-2.0；另含 Ollama/LM Studio/GitHub Copilot/OpenRouter/自定义。**不给 5**：多厂商旗舰要自备 Key，免费内置只有一家。 | 本机 `%APPDATA%\LobsterAI\lobsterai.sqlite` 的 `app_config`：`model.defaultModel=yd-fast`、`defaultModelProvider=lobsterai-server`；`dist-electron/shared/providers/constants.js` 的 `PROVIDER_DEFINITIONS`；官网 https://lobsterai.youdao.com（2026.10.16） |
| 2.2 编码能力 | 5 | Agentic 编码闭环完整：读仓库 → 改多文件 → 跑脚本/测试 → 迭代修复；支持 Python / PowerShell / JS / Shell 等。本仓库（agent-credit）的台账系统、签到编排、逆向取证与对账脚本都是这套工具链做出来的；本次自评也在本仓库内完成读取、改文件、跑验证。 | 本会话工具链（`read`/`write`/`edit`/`apply_patch`/`exec`/`process`/`sessions_spawn`）；本仓库 `agent_credit/*`、`scripts/*`、`vendor/*` 实际产出；官网「应用开发」页 |
| 2.3 浏览器操控 | 5 | 完整浏览器自动化，**能调试**：打开页面、导航、快照、点击、输入、填表、选择、截图、上传、PDF、多标签、执行 JS、读 console 与 network 请求。底层是 Playwright（客户端配置 `browserWebAccess.profileMode=managed`，`evaluateEnabled=true`）。 | 本会话 `browser` 工具全套（navigate/snapshot/act/screenshot/console/requests/tabs/evaluate/upload/pdf）；`app_config.browserWebAccess`；`browser-automation` 技能 |
| 2.4 电脑操控 | 4 | **没有原生 Computer Use 键鼠工具**；但 `exec` 跑在本机 PowerShell，能操作文件、启动软件、注册计划任务，项目里也用 UIA/OCR/SendInput 脚本完成过客户端签到、窗口管理与真实点击。属于「脚本路线可做大部分桌面操控」，不是开箱即用的原生能力，按模板「大部分桌面操控 = 4」计，但受 UIPI/前台锁/窗口态限制。 | 本会话工具清单无 `computer_*`；`scripts/ui_claim_lobsterai.ps1`、`agent_credit/ui_claim.py`、`scripts/_task_lobsterai.ps1` 的 UIA/OCR/SendInput 实践；官网「可连接文件、终端、浏览器与本地项目」 |
| 2.5 多模态 | 4 | **输入**：可直接看图（`read`/`view_image`），图片附件进入模型上下文。**输出**：可生图（`lobsterai_image_generate`，默认 doubao-seedream-5-0）、生视频（`lobsterai_video_generate`，默认 doubao-seedance-2-0-fast）、TTS。**音频输入未确认**，所以不给 5。 | 本会话 `lobsterai_image_generate`、`lobsterai_video_generate`、`tts`、`view_image`/`read` 工具；Word/Excel/PPT/PDF 技能全套 |
| 2.6 移动端同步 | 未确认 | 官网下载页只列 macOS（Apple/Intel）与 Windows，**未发现 iOS/Android 客户端**；官方主打的「手机远程指挥电脑」是通过微信/企微/钉钉/飞书 IM 发指令，不是移动端 App，也不等于桌面/移动任务同步。本机 `im_config` 为空，未实测 IM 远控。按模板标「未确认」，不推测。 | 官网 https://lobsterai.youdao.com 下载区与「手机远程指挥电脑干活」说明；本机 `lobsterai.sqlite` 的 `im_config` 0 条；`catalog.yaml` lobsterai 无 `mobile` 字段 |

## 领取可靠性

| 指标 | 自评分(1-5) | 实际情况 | 依据 |
|---|---|---|---|
| 3.1 领取方式 | 3 | 当前主路线是 **UI 自动化 + OCR + 真实点击**：runas 拉起 → 等窗口 → OCR 找「每日积分礼」/左下「我的」→ 真实点击 → 校验「今日已领」或额度上涨。可挂每日计划任务全自动跑，但依赖提权、窗口态与前台焦点，属于「UI 自动但偶发失败」。另：external 直签已修复并只读实测通过，但**未切换为主路线**。 | `catalog.yaml` lobsterai `claim_mode: ui`；`scripts/ui_claim_lobsterai.ps1`、`scripts/_task_lobsterai.ps1`；`logs/_lobsterai_log.txt`（2026-10-25 11:09 真实点击后显示「今日已领」/「奖励到账 +100积分」）；`vendor/lobsterai-auto-signin/signin.py status` 只读实测 |
| 3.2 稳定性 | 4 | 服务端 context 显示累计 **claimedDays=34、claimedCredits=3400、claimedToday=true**；本地台账 09-28..10-25 连续 28 天有记录（服务端累计 34 天，说明早期还有 6 天本地未记）。自动跑过程中出现过合成点击假成功、前台遮挡等需重试的情况，且没有独立的 30 天成功率日志，不能报 100%，按模板「≥90% = 4」计。 | 2026-10-25 context；`data/ledger.json` lobsterai entries（09-28..10-25 连续 28 条）；`logs/lobsterai_claim.json`（`{"status":"already","detail":"@今日已领"}`）；`logs/_lobsterai_log.txt` 的 10-24/10-25 失败与修复记录 |
| 3.3 脆弱性 | 2 | 依赖客户端窗口锚点、OCR 文案、React 真实点击与前台焦点；近一个月内多次因「合成点击没进 React」「前台窗口盖住点击位」失效并改脚本；客户端大改版/换文案/改布局都可能要调。按模板「经常因改版失效 = 2」计。external 路线本身对 UI 改版免疫，但参数要跟随客户端版本升级。 | `catalog.yaml` lobsterai notes【2026-10-25 chip 合成消息假成功】、【前台窗口盖住点击位】；`logs/_lobsterai_log.txt` 2026-10-25 00:08/11:08 两次运行；`research/answers/lobsterai.md` 〇节 |

## 实际体验

| 指标 | 自评分(1-5) | 实际情况 | 依据 |
|---|---|---|---|
| 4.1 响应速度 | 未确认 | 无法在产品内部可靠测量「发指令 → 首 token」的端到端延迟；本会话流式输出与工具调用体感流畅，但没有可复现的计时数据，不据此打分。**另：主人 2026-10-27 反馈启动/切换工作空间都要等网关，体感很慢；这是启动链路时延，不是首 token 延迟，单独记录、不混进本项评分。** | 无客观测量数据；客户端 `cowork_messages` 无 latency 字段；`catalog.yaml` lobsterai `owner_note`（2026-10-27） |
| 4.2 指令遵循 | 4 | 能把复杂指令拆成多步并保持目标；涉及产品事实时会区分「本机实测 / 客户端文件 / 未确认」，不把推测写成结论。偶有需要补充约束的情况（例如是否要连带改台账/是否切换签到主路线）。 | 本次按模板逐项打分并附证据；本仓库长期多轮任务（签到编排、逆向取证、对账修正）的交付记录 |
| 4.3 上下文管理 | 4 | OpenClaw 体系有自动上下文压缩与跨会话记忆；DeepSeek V4 系列 provider 表标 1,000,000 token 上下文，长任务多轮迭代稳定。扣 1 分：压缩会把极早期细节摘要化，需要时仍要回读文件；本会话别名 `deepseek-flash` 的实际窗口未在会话内单独暴露。 | `dist-electron/shared/providers/constants.js`：DeepSeek V4 Flash/Pro `contextWindow: 1_000_000`；本会话记忆/压缩机制；长任务中持续回读仓库文件 |
| 4.4 工具生态 | 4 | 扩展体系齐全：**MCP + Skills + Kits + 子 Agent + 定时任务 + IM 通道**；客户端有 `OpenMcp`/`OpenSkills`/`OpenKits`/`OpenScheduledTasks` 快捷键与设置页；本机已装 28 个技能。扣 1 分：本机 `mcp_servers` 0 条、`user_plugins` 0 条，插件市场是否丰富未实测。 | 本机 `lobsterai.sqlite` 的 `mcp_servers`/`user_plugins`/`agents` 表；`%APPDATA%\LobsterAI\SKILLs` 28 个目录；客户端 i18n 的 `OpenMcp`/`OpenSkills`/`OpenKits`；AGENTS 工具清单 |

## 补充说明

- **强项**：开源（GitHub `netease-youdao/lobsterai`，代码可审计）、桌面级本地执行（文件/终端/浏览器/本地项目）；agentic 编码闭环完整；浏览器自动化能读 console/network，可调试；办公文档链路完整（Word/Excel/PPT/PDF）；可生图/生视频/TTS；子 Agent、定时任务、Skills/MCP 扩展齐全；官方支持微信/企微/钉钉/飞书 IM 远控。
- **短板**：免费日额度只有 100，且无连签加成；UI 签到依赖窗口锚点/OCR/真实点击，近一个月多次失效；没有原生 Computer Use 键鼠工具，桌面操控走 PowerShell/UIA/OCR 脚本；没有移动端 App，手机只能通过 IM 远控，不能同步桌面任务；免费内置模型只有 DeepSeek-V4.1-Flash，多厂商旗舰要 BYOK；音频输入未确认；响应延迟无法量化；启动/切换工作空间要等网关，体感慢（2026-10-27 主人反馈）。
- **给横向对比的提示**：2.1 的「多厂商最新旗舰」是 BYOK 可调用，不是免费内置；2.4 是脚本路线而非原生键鼠 SDK，和 Qoder/MiniMax 那种原生 Computer Use 要分开看；3.x 反映的是本项目 UI 自动化的实际可靠性，external 直签已具备条件但尚未切换主路线。
- **本次同时修正了项目里的错误记录**：
  1. `catalog.yaml` 旧结论「服务端当前未下发任何签到活动」是**错的**：根因是 external 探测写死 `clientVersion=1.0.0` + `containerApiVersion=1`；用实际 `2026.10.16` + `desktop_sidebar` 的 `containerApiVersion=2` 后，slot 返回 `available`，活动 `daily-check-in-evergreen-prod-20260814`，context 返回 `rewardCredits=100 / claimedDays=34 / claimedCredits=3400 / claimedToday=true`。
  2. 旧记录「此 UI 没有『今日已领』文字」只适用于 2026-09-28 版本；2026.10.16 版 UI 实测已显示「今日已领」+「奖励到账 +100积分」。
  3. 旧 `models_note` 的「GPT-4o / Claude Sonnet 4.5 / DeepSeek V4 Pro」已过期；按本机 provider 表改为 GPT-5.6 / Claude Opus 4.7 / Sonnet 4.6 / Gemini 3.1 Pro / DeepSeek V4 / Kimi K3 / GLM 5.1 / MiniMax M3 / Qwen3.6 / Doubao 2.0。
  4. `rating.automation` 由 1 改为 3：UI 签到已连续跑通，不再是「占着坑不产粮」；README 综合分由 2.3（C）刷新为 2.9（B）。
  5. `research/answers/lobsterai.md` 已按 2026-10-25 重测结果重写；`vendor/lobsterai-auto-signin/signin.py` 已修为动态读客户端版本、按 placement 选 `containerApiVersion`、用 `activityType` 判定、POST 带 `configRevision` + `idempotencyKey`，`status`/`auto` 只读与幂等路径已实测。
  6. `catalog.yaml` 的 `claim_mode` 仍保留 `ui`，没有擅自切换 external；external 作为候选主线，建议连续观察几天 `status` 后再定。

---

*自评 ≠ 最终评分。本表由 LobsterAI 会话自身填写，供主人结合实测横向对比修正。*
