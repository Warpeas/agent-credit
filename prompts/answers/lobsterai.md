# LobsterAI · Agent 能力自评

| 项 | 值 |
|---|---|
| 模板 | `prompts/agent_self_eval.md` |
| 填写者 | LobsterAI（有道龙虾，当前会话产品自身） |
| 评估日期 | 2026-11-06 |
| 本机客户端 | 2026.10.30（安装包 `LobsterAI.exe` ProductVersion；官网下载页同日版本） |
| 本会话模型 | `lobsterai-server/deepseek-flash`；客户端默认 `yd-fast`，UI 显示 DeepSeek-V4.1-Flash |

> 原则：只报本机/本会话能确认的能力；测不到或产品侧未确认的标「未确认」，不按满分估算。
> 依据分三级：**本机实测** > **客户端/官方文件** > **未确认**。

---

产品名：LobsterAI（有道龙虾，桌面端 Agent）
厂商：网易有道
评估日期：2026-11-06

## 额度价值

| 指标 | 自评分(1-5) | 实际情况 | 依据 |
|---|---|---|---|
| 1.1 日额度 | 3 | 每日签到 **100 积分**；无基础/连签分档。新用户另有一次性 300 赠送（台账记为 2026-09-29 到期，已过期）；官网「¥0.01 解锁 1000 积分」是付费促销，不算免费日额度。按模板「100-199 = 3」计。 | 2026-11-06 只读 `GET /api/client-activities/daily-check-in-evergreen-prod-20260814/context?configRevision=1` → `state.rewardCredits=100`、`claimedDays=46`、`claimedCredits=4600`、`claimedToday=true`；`catalog.yaml` lobsterai `daily_amount: 100`；`README.md` 评级表「100/天」 |
| 1.2 有效期 | 5 | 签到积分 **30 天有效、可累积**，不是当日清零。按模板「30+ 天可累积 = 5」计。 | `catalog.yaml` `validity_audit_2026_10_04.lobsterai`；2026-11-06 服务端逐条明细进一步确认：每条 `expiresAt - earnedAt` 正好 30 天（例：2026-11-06T00:02:27 → 2026-12-06T00:02:28）；本地台账 47 条（2026-09-15..2026-11-06）全部按服务端过期日登记 |
| 1.3 连签/额外加成 | 1 | **无连签加成、无月度固定赠送**；`claimedCredits / claimedDays = 4600 / 46 = 100`，逐日线性，没有任何加成日。只有一次性新用户 300 赠送，不构成持续加成。按模板「无加成且额度小 = 1」计。 | 2026-11-06 context 的 `claimedDays/claimedCredits`；`catalog.yaml` lobsterai 条目无 `streak`/`bonus` 字段；`README.md` 评级表「连签/额外：无」 |
| 1.4 可消耗性 | 2 | 服务端逐条明细可算真实消耗：累计发放 4900，已用 **1331.6**（53 天，约 **25.1/天**），另有 **845.7 已过期未用**；当前可用 **2723**。也就是每天 100 的额度大约只用掉四分之一，**大部分会放着过期**。按模板「基本花不掉 = 2」计。 | 只读 `GET /api/user/credits-earned`（2026-11-06 01:03 快照）：`totalEarned=4900`、`totalRemaining=2722.69`；46 条每日 100 + 1 条新用户 300；`creditsUsed` 合计 1331.6，`status=expired` 且 `creditsRemaining>0` 合计 845.74；台账 `data/ledger.json` lobsterai 47 条 |

## 能力覆盖

| 指标 | 自评分(1-5) | 实际情况 | 依据 |
|---|---|---|---|
| 2.1 模型代际 | 4 | **免费内置默认模型只有 DeepSeek-V4.1-Flash**（`lobsterai-server/yd-fast`；本会话 `lobsterai-server/deepseek-flash`）。BYOK 可接 18 家 provider（另含内置 `lobsterai-server` 与自定义），且都是当代款：OpenAI GPT-5.6 Sol/Terra/Luna、GPT-5.5/5.4；Anthropic Claude Opus 4.7/4.6、Sonnet 4.6；Gemini 3.1 Pro/3 Flash/3.1 Flash Lite；xAI Grok 4.5/4.3/Build 0.1；DeepSeek V4 Flash/Pro/Reasoner；Kimi K3/K2.7 Code/K2.6/K2.5；GLM 5.3/5.3 Flash/5.1/5/4.7；MiniMax M3/M2.7/M2.5；Qwen3.8 Max/3.7 Plus/3.8 Flash/3.6/3.5 Plus；Doubao-Seed-2.0 Pro/Lite/Mini；MiMo V2.6 Pro/V2.5；Step 3.5 Flash；另有 Ollama/LM Studio/GitHub Copilot/OpenRouter/自定义。**不给 5**：多厂商旗舰要自备 Key，免费内置只有一家。 | 本机 `%APPDATA%\LobsterAI\lobsterai.sqlite` 的 `app_config`：`model.defaultModel=yd-fast`、`defaultModelProvider=lobsterai-server`；2026.10.30 `dist-electron/shared/providers/constants.js` 的 `PROVIDER_DEFINITIONS`；官网 https://lobsterai.youdao.com（2026-11-06 复核，最新版 2026.10.30） |
| 2.2 编码能力 | 5 | Agentic 编码闭环完整：读仓库 → 改多文件 → 跑脚本/测试 → 迭代修复；支持 Python / PowerShell / JS / Shell 等。本仓库（agent-credit）的台账系统、签到编排、逆向取证与对账脚本都是这套工具链做出来的；本次自评也在本仓库内完成读取、改文件、跑验证。 | 本会话工具链（`read`/`write`/`edit`/`apply_patch`/`exec`/`process`/`sessions_spawn`）；本仓库 `agent_credit/*`、`scripts/*`、`vendor/*` 实际产出；官网「应用开发」页 |
| 2.3 浏览器操控 | 5 | 完整浏览器自动化，**能调试**：打开页面、导航、快照、点击、输入、填表、选择、截图、上传、PDF、多标签、执行 JS、读 console 与 network 请求。底层是 Playwright（客户端配置 `browserWebAccess.profileMode=managed`，`evaluateEnabled=true`）。 | 本会话 `browser` 工具全套（navigate/snapshot/act/screenshot/console/requests/tabs/evaluate/upload/pdf）；`app_config.browserWebAccess`（2026-11-06 只读复核）；`browser-automation` 技能 |
| 2.4 电脑操控 | 4 | **没有原生 Computer Use 键鼠工具**；但 `exec` 跑在本机 PowerShell，能操作文件、启动软件、注册计划任务，项目里也用 UIA/OCR/SendInput 脚本完成过客户端签到、窗口管理与真实点击。属于「脚本路线可做大部分桌面操控」，不是开箱即用的原生能力，按模板「大部分桌面操控 = 4」计，但受 UIPI/前台锁/窗口态限制。 | 本会话工具清单无 `computer_*`；`scripts/ui_claim_lobsterai.ps1`、`agent_credit/ui_claim.py`、`scripts/_task_lobsterai.ps1` 的 UIA/OCR/SendInput 实践；官网「可连接文件、终端、浏览器与本地项目」 |
| 2.5 多模态 | 4 | **输入**：可直接看图（`read`/`view_image`），图片附件进入模型上下文。**输出**：可生图（`lobsterai_image_generate`，默认 doubao-seedream-5-0）、生视频（`lobsterai_video_generate`，默认 doubao-seedance-2-0-fast）、TTS。**音频输入未确认**，所以不给 5。 | 本会话 `lobsterai_image_generate`、`lobsterai_video_generate`、`tts`、`view_image`/`read` 工具；Word/Excel/PPT/PDF 技能全套 |
| 2.6 移动端同步 | 未确认 | 官网下载页只列 macOS（Apple/Intel）与 Windows，**未发现 iOS/Android 客户端**；官方主打的「手机远程指挥电脑」是通过微信/企微/钉钉/飞书 IM 发指令，不是移动端 App，也不等于桌面/移动任务同步。本机 `im_config` 为空，未实测 IM 远控。按模板标「未确认」，不推测。 | 官网 https://lobsterai.youdao.com 下载区与「手机远程指挥电脑干活」说明（2026-11-06 复核）；本机 `lobsterai.sqlite` 的 `im_config` 0 条；`catalog.yaml` lobsterai 无 `mobile` 字段 |

## 领取可靠性

| 指标 | 自评分(1-5) | 实际情况 | 依据 |
|---|---|---|---|
| 3.1 领取方式 | 3 | 当前主路线是 **UI 自动化 + OCR + 真实点击**：runas 拉起 → 等窗口 → OCR 找「每日积分礼」/左下「我的」→ 真实点击 → 校验「今日已领」或额度上涨。可挂每日计划任务全自动跑，但依赖提权、窗口态与前台焦点，属于「UI 自动但偶发失败」。另：external 直签已修复并只读实测通过（2026-11-06），且已打通积分明细接口，但**签到主路线仍未切换**。 | `catalog.yaml` lobsterai `claim_mode: ui`；`scripts/ui_claim_lobsterai.ps1`、`scripts/_task_lobsterai.ps1`；`logs/lobsterai_claim.json`（2026-11-06 00:02 `{"status":"already","detail":"@今日已领"}`）；`vendor/lobsterai-auto-signin/signin.py status`（2026-11-06 只读实测：activity available、claimedToday=true）；`agent_credit/lobsterai_credits.py` |
| 3.2 稳定性 | 4 | 服务端 context 显示累计 **claimedDays=46、claimedCredits=4600、claimedToday=true**；服务端逐条明细共 47 条（46 天每日 100 + 1 条新用户 300 = 4900），本地台账已按这 47 条镜像。按近 30 天（10-08..11-06）算 **29/30 = 96.7%**（10-24 两边都没有记录）。自动跑过程中出现过合成点击假成功、前台遮挡等需重试的情况，且没有独立的全量成功率日志，不能报 100%，按模板「≥90% = 4」计。 | 2026-11-06 context；只读 `GET /api/user/credits-earned` 47 条；`data/ledger.json` lobsterai 47 条；`logs/_lobsterai_log.txt`（2026-11-06 00:02 真实点击后显示「今日已领」/「奖励到账 +100积分」）；`logs/lobsterai_claim.json` |
| 3.3 脆弱性 | 2 | 依赖客户端窗口锚点、OCR 文案、React 真实点击与前台焦点；近一个月内多次因「合成点击没进 React」「前台窗口盖住点击位」失效并改脚本；客户端大改版/换文案/改布局都可能要调。**2026-10-30 版又暴露一类新脆弱点**：`app.asar` 的 `package.json` payload 带 NUL 对齐前缀，旧解析直接 `json.loads` 失败 → `client_version()` 静默退回 `0.0.0` → 服务端返回 `slotState=empty`，external 路线会误报「无活动」；UI 路线不受这条影响。按模板「经常因改版失效 = 2」计。 | `catalog.yaml` lobsterai notes【2026-10-25 chip 合成消息假成功】、【前台窗口盖住点击位】、【2026-11-06 asar payload 前缀】；`vendor/lobsterai-auto-signin/signin.py` 修复前 `status` 返回 empty、修复后返回 available；`logs/_lobsterai_log.txt` 2026-10-25 00:08/11:08 两次运行 |

## 实际体验

| 指标 | 自评分(1-5) | 实际情况 | 依据 |
|---|---|---|---|
| 4.1 响应速度 | 未确认 | 无法在产品内部可靠测量「发指令 → 首 token」的端到端延迟；本会话流式输出与工具调用体感流畅，但没有可复现的计时数据，不据此打分。**另：主人 2026-10-27 反馈启动/切换工作空间都要等网关，体感很慢；这是启动链路时延，不是首 token 延迟，单独记录、不混进本项评分。** | 无客观测量数据；客户端 `cowork_messages` 无 latency 字段；`catalog.yaml` lobsterai `owner_note`（2026-10-27） |
| 4.2 指令遵循 | 4 | 能把复杂指令拆成多步并保持目标；涉及产品事实时会区分「本机实测 / 客户端文件 / 未确认」，不把推测写成结论。偶有需要补充约束的情况（例如是否要连带改台账/是否切换签到主路线）。 | 本次按模板逐项打分并附证据；本仓库长期多轮任务（签到编排、逆向取证、对账修正）的交付记录 |
| 4.3 上下文管理 | 4 | OpenClaw 体系有自动上下文压缩与跨会话记忆；DeepSeek V4 系列 provider 表标 1,000,000 token 上下文，长任务多轮迭代稳定。扣 1 分：压缩会把极早期细节摘要化，需要时仍要回读文件；本会话别名 `deepseek-flash` 的实际窗口未在会话内单独暴露。 | 2026.10.30 `constants.js`：`DEEPSEEK_V4_CONTEXT_WINDOW = 1_000_000`；本会话记忆/压缩机制；长任务中持续回读仓库文件 |
| 4.4 工具生态 | 4 | 扩展体系齐全：**MCP + Skills + Kits + 子 Agent + 定时任务 + IM 通道**；客户端有 `OpenMcp`/`OpenSkills`/`OpenKits`/`OpenScheduledTasks` 快捷键与设置页；本机已装 27 个技能。扣 1 分：本机 `mcp_servers` 0 条、`user_plugins` 0 条，插件市场是否丰富未实测。 | 本机 `lobsterai.sqlite` 的 `mcp_servers`/`user_plugins`/`agents` 表（2026-11-06 只读计数：0/0/1）；`%APPDATA%\LobsterAI\SKILLs` 27 个目录；客户端 i18n 的 `OpenMcp`/`OpenSkills`/`OpenKits`；AGENTS 工具清单 |

## 补充说明

- **强项**：开源（GitHub `netease-youdao/lobsterai`，代码可审计）、桌面级本地执行（文件/终端/浏览器/本地项目）；agentic 编码闭环完整；浏览器自动化能读 console/network，可调试；办公文档链路完整（Word/Excel/PPT/PDF）；可生图/生视频/TTS；子 Agent、定时任务、Skills/MCP 扩展齐全；官方支持微信/企微/钉钉/飞书 IM 远控。
- **短板**：免费日额度只有 100，且无连签加成；UI 签到依赖窗口锚点/OCR/真实点击，近一个月多次失效；没有原生 Computer Use 键鼠工具，桌面操控走 PowerShell/UIA/OCR 脚本；没有移动端 App，手机只能通过 IM 远控，不能同步桌面任务；免费内置模型只有 DeepSeek-V4.1-Flash，多厂商旗舰要 BYOK；音频输入未确认；响应延迟无法量化；启动/切换工作空间要等网关，体感慢（2026-10-27 主人反馈）。
- **给横向对比的提示**：2.1 的「多厂商最新旗舰」是 BYOK 可调用，不是免费内置；2.4 是脚本路线而非原生键鼠 SDK，和 Qoder/MiniMax 那种原生 Computer Use 要分开看；3.x 反映的是本项目 UI 自动化的实际可靠性，external 直签已具备条件但尚未切换主路线。
- **2026-11-06 复核与修正**：
  1. 客户端已从 2026.10.16 升到 **2026.10.30**（exe ProductVersion / 官网下载页一致）；签到活动与 UI 路径未变，2026-11-06 00:02 自动轮返回 `already @今日已领`。
  2. 服务端 context 刷新为 **claimedDays=46 / claimedCredits=4600 / claimedToday=true**；本地台账 39 条，首 2026-09-28、末 2026-11-06，仅缺 10-24；近 30 天 29/30。
  3. **修掉 external 路线的一个静默失效**：2026.10.30 的 `app.asar` 文件 payload 带 NUL 对齐前缀，旧 `client_version()` 直接 `json.loads` 抛异常并吞掉，返回 `0.0.0`；服务端对 `clientVersion=0.0.0` 返回 `slotState=empty`，看起来像「活动下线」。已改为跳过前缀 + `JSONDecoder.raw_decode`，`signin.py status` 恢复 `available`，版本读出 `2026.10.30`。
  4. `models_note` 按 2026.10.30 provider 表刷新：新增 Qwen3.8 Max/3.7 Plus/3.8 Flash、Kimi K2.7 Code、GLM 5.3/5.3 Flash、MiMo V2.6 Pro/V2.5、Grok Build 0.1、Step 3.5 Flash、Gemini 3.1 Flash Lite 等；内置免费默认仍是 `yd-fast`（DeepSeek-V4.1-Flash）。
  5. `catalog.yaml` 的 `claim_mode` 仍保留 `ui`，没有擅自切换 external；external 作为候选主线，建议连续观察几天 `status` 后再定。
  6. 旧结论「服务端当前未下发任何签到活动」仍是错的（2026-10-25 已纠正）；本次进一步确认：2026.10.30 版用 `clientVersion=2026.10.30` + `containerApiVersion=2` 仍返回同一活动 `daily-check-in-evergreen-prod-20260814`。
  7. **积分明细接口打通**：只读 `GET /api/user/credits-earned` 返回 47 条逐次发放（amount / used / remaining / status / earnedAt / expiresAt），首次对账把台账从旧估算 3100 校正为 2775（28 条活条目），01:03 再同步到 2723；看板口径升为「服务端真值」。据此把 1.4 从 3 下调为 **2**：53 天累计发放 4900，实际只用 1331.6（约 25.1/天），另有 845.7 过期未用，日额度大部分花不掉。

---

*自评 ≠ 最终评分。本表由 LobsterAI 会话自身填写，供主人结合实测横向对比修正。*
