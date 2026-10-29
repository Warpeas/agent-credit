# agent-credit

本地 Agent 积分台账 + 签到编排。当日清零、登录即领的软件**不自动启动**，用的时候再开。

<!-- BEGIN RATING -->

## 评级总表

> 由 `scripts/gen_rating_table.py` 从 `catalog.yaml` 生成。改评级请改 `catalog.yaml` 的 `rating` 块（`owner_note` 填真实使用体验），再跑 `python scripts/gen_rating_table.py --write` 刷新本表。

| 档 | Agent | 厂商 | 免费额度 | 有效期 | 连签/额外 | 发放方式 | 领取路线 | 评分 V/C/A | 综合 |
|---|---|---|---|---|---|---|---|---|---|
| **S** | MiniMax Code | MiniMax | 400/天 | 30 天 | 7 天周期，第 4/7 天 +600 | 每日签到·可累积 | external 直签 | 5/4/5 | 4.7 |
| **S** | WorkBuddy | 腾讯 | 100/天 | 30 天 | 7 天周期，第 7 天 +1000 | 每日签到·可累积 | external 直签 | 4/5/5 | 4.6 |
| **B** | AutoClaw 智谱 | 智谱 AI | 200/天 | 分类（4 类） | 无（另有不定期大额积分活动） | 每日签到·可累积 | UI/OCR 提权 | 4/4/2 | 3.4 |
| **B** | Qoder CN | 阿里巴巴 | 100/天 | 30 天 | 无 | 每日签到·可累积 | UI/OCR 提权 | 3/5/2 | 3.3 |
| **B** | Trae | 字节跳动 | 100/天 | 31 天 | 无 | 每日签到·可累积 | UI/OCR 提权 | 3/4/3 | 3.3 |
| **B** | ZCode 智谱 | 智谱 AI | 周期制 | 服务端下发 | 无 | 月度 | 不自动 | 3/5/1 | 3.0 |
| **B** | LobsterAI | 网易有道 | 100/天 | 30 天 | 无 | 每日签到·可累积 | UI/OCR 提权 | 2/4/3 | 2.9 |
| **B** | DuMate 百度搭子 | 百度 | 500/天 | 30 天 | 无 | 每日签到·可累积 | 手签 | 4/3/1 | 2.8 |
| **B** | JoyCode 京东 | 京东云 | 一次性 | 至 2026-10-16 | 无 | 一次性 | 不自动 | 4/3/1 | 2.8 |
| **B** | Kimi Work | 月之暗面 | 周期制 | 服务端下发 | 无 | 月度 | 不自动 | 3/4/1 | 2.7 |
| **B** | 讯飞 Loomy | 科大讯飞 | 5000/天 | 当日清零 | 无 | 登录即领·当日清零 | 不自动 | 3/4/1 | 2.7 |
| **B** | Mavis 腾讯 | 腾讯 | 10M token/天 | 当日清零 | 无 | 登录即领·当日清零 | 不自动 | 4/2/1 | 2.5 |
| **C** | CatPaw 美团 | 美团 | 一次性 | 365 天 | 无 | 一次性 | 不自动 | 2/4/1 | 2.3 |
| **C** | 扣子 Coze | 字节跳动 | 1500/天 | 当日清零 | 无 | 登录即领·当日清零 | 不自动 | 2/4/1 | 2.3 |
| **C** | ToDesk AI | ToDesk | 500/天 | 当日清零 | 无 | 每日签到·当日清零 | 手签 | 2/3/1 | 2.0 |
| **C** | MonkeyCode 积分 | 长亭百川 | 100/天 | 服务端下发 | 无 | 每日签到·可累积 | external 直签 | 1/3/1 | 1.6 |
| **C** | 千问办公 | 阿里巴巴 | 100/天 | 当日清零 | 无 | 登录即领·当日清零 | 不自动 | 1/3/1 | 1.6 |
| **C** | 商汤小浣熊 | 商汤科技 | 300/天 | 待确认 | 无 | 网页登录·有效期待确认 | 不自动 | 1/3/1 | 1.6 |
| **C** | 阶跃 AI | 阶跃星辰 | 20/天 | 当日清零 | 无 | 登录即领·当日清零 | 不自动 | 1/3/1 | 1.6 |
| **D** | Accio Work | 阿里国际 | 200/天 | 当日清零 | 无 | 登录即领·当日清零 | 不自动 | 1/2/1 | 1.3 |

评分口径：**综合 = 0.4×额度价值 + 0.3×能力覆盖 + 0.3×领取可靠性**（各 1-5）。
档位：≥4.5 S｜≥3.5 A｜≥2.5 B｜≥1.5 C｜其余 D。

## 各家简评

> 以下为**基于台账事实的分析初稿**，主人可按实际体验在 `catalog.yaml` 的 `owner_note` 里覆写。

### S · MiniMax Code（MiniMax）— 4.7 分

- 额度：400/天，30 天，连签/额外：7 天周期，第 4/7 天 +600
- 模型：文本 MiniMax-M3.1-Flash（官方 M Plan 文本模型，Preview 版已下线）+ M2.7；视频 H3 / H3 Max（仅 Explore/Build 档可用，Go 档不可用）；图像与音频模型全档可用；支持 BYOK 自定义供应商【官方 M Plan 概览 2026-10-24：https://platform.minimax.cn/docs/m-plan/intro】【2026-10-22 官网：Code 2.0 起扩为通用桌面 Agent（办公自动化/定时任务/电脑操控/视频生成）】
- 移动端：有—— 能看到桌面端的项目并继续对话（比 AutoClaw 移动端强）；模型同样只有 MiniMax 自家
- 简评：可累积额度里的天花板：**平时 400/天，第 4/7 天单日加码到 1000，7 天周期 4000**（2026-10-24 按官方口径 https://agent.minimax.cn/docs/code/account/usage 核对，赠予积分 30 天有效、可累积；活动期服务端会翻倍，10-24 实测 day4=2024）。external 直签无GUI 无 UAC，不受客户端活动推广干扰，是当前唯一完全无感的路线。唯一软肋是 accessToken 有效期极短（客户端停跑就废），需靠计划任务在签到前先拉客户端续期。模型限于 MiniMax 自家但已换代到 M3.1-Flash/M2.7 + H3/H3 Max 视频，多模态是加分项。
- 适合：高频重度使用、多模态任务；移动端可续桌面端的对话
- 主人体验：有移动端，能看到桌面端的项目并继续对话（这点比 AutoClaw 强，后者移动端是另一套环境、项目不同步）。模型两端都只有 MiniMax 自家（M3/M2.7/H3）。**手机端一次只能配对一台电脑**，换设备需要重新配对。

### S · WorkBuddy（腾讯）— 4.6 分

- 额度：100/天，30 天，连签/额外：7 天周期，第 7 天 +1000
- 模型：混元 Hy3/Hy4 + MiniMax-M3、GLM-5.2/5.1/5V-Turbo、Kimi-K3/K2.7-Code、DeepSeek-V4-Pro/Flash【2026-10-22 官方文档：已全面换代到 V4/K3/GLM-5 这一代】
- 简评：额度不算最高但最省心：external 直签零交互，30 天有效期够攒，7 天连签再加 1000。2026-10 官方文档确认已换代到混元 Hy4 + Kimi-K3/GLM-5.2/DeepSeek-V4/MiniMax-M3 这一代，多模型池是台账里最全的一档，办公文档链路完整。
- 适合：日常编码主力 + 腾讯文档/办公场景
- 主人体验：不能调用内置浏览器去调试网页——没有 Playwright，浏览器操控能力缺失。

### B · AutoClaw 智谱（智谱 AI）— 3.4 分

- 额度：200/天，分类（4 类），连签/额外：无（另有不定期大额积分活动）
- 模型：【2026-10-25 本机 1.20.0 settings.json 实测】Auto（zai_auto，metadata.auto_model_name=deepseek-v4-pro，1M context/393k output，低消耗）+ Auto-Fast（zai_auto-fast，1M/131k，支持图片，中消耗）+ GLM-5.3（zaicoding_glm-5.3，1M/307k，高消耗）+ GLM-5.3-Flash（zai_glm-5.3-flash，1M/131k，支持图片，低消耗）+ 自定义 API（本机 Ollama qwen3:14b）。不是『只有 GLM』，也不是旧记录的多厂商大池；官方 2026-10-22 页面另列 GLM-5-Turbo/GLM-5V-Turbo，未在本机目录出现。
- 移动端：有—— 与桌面端项目不同步，是独立的云端 claw 环境；移动端模型未实测。桌面端 1.20.0 已确认 Auto 路由 metadata 指向 DeepSeek-V4-Pro + GLM-5.3/5.3-Flash，不能再说『同为 GLM』
- 简评：200/天，有效期分类（daily/monthly/longTerm/campaign，非统一天数），本地执行能力全，有思考过程。模型不是只有 GLM：1.20.0 的 Auto/Auto-Fast metadata 指向 DeepSeek-V4-Pro，另有 GLM-5.3/5.3-Flash，且支持自定义 API；但内置目录只有 4 个，场景覆盖仍不如多厂商大池。签到藏在灵感中心任务卡里靠 OCR 定位，首页横幅还受服务端开关控制，随时可能定位不到；实测经常容易资源紧张，任务会停止执行；时不时有送大额积分的活动（非固定周期，不能当稳定日额度）。有效期逐条到期日服务端不下发，台账按『过期未知』处理。
- 适合：需要本地执行 + Auto/GLM 多模型路由的场景；资源紧张时会停止执行，别当稳定主力
- 主人体验：有思考过程（早先记的『不输出思考情况』是误记，已更正）。但经常容易资源紧张，任务会停止执行；时不时有送大额积分的活动（非固定周期，不能当稳定日额度），实际用起来不太好用。**桌面端 1.20.0 模型目录不是只有 GLM**：settings.json 的 models.catalog = Auto/Auto-Fast（metadata.auto_model_name=deepseek-v4-pro）+ GLM-5.3 + GLM-5.3-Flash + 自定义 API（本机 Ollama qwen3:14b）。旧记录『只有 GLM』与更早的『Pony-Alpha-2/DeepSeek/Kimi/MiniMax 多模型池』都不准确。移动端与桌面端项目不同步，是独立的云端 claw 环境；移动端模型未实测。

### B · Qoder CN（阿里巴巴）— 3.3 分

- 额度：100/天，30 天，连签/额外：无
- 模型：分级池 Auto/Ultimate/Performance/Efficient：Qwen3.8-Max、Kimi-K3/K2.7-Code、GLM-5.3/5.2、DeepSeek-V4-Pro/Flash、MiniMax-M3；可接百炼/智谱/Kimi/MiniMax 等自定义【2026-10-22 官方文档】
- 简评：100/天、领取后 30 天有效、每日 10:00 (UTC+8) 刷新，可累积。Qoder 本身是能打的 agentic IDE，2026-10 官方文档模型池已换代到 Qwen3.8-Max + Kimi-K3/GLM-5.3/DeepSeek-V4/MiniMax-M3 这一代并带分级路由，是台账里与 WorkBuddy 并列最全的一档。签到藏在服务端下发的活动 webview 里，UIA 看不见只能靠 OCR 点击；脚本全程锚点定位不写死坐标（应对本机 200% 缩放与窗口态变化）。但点击需在真实交互桌面里才落地（agent 子进程受 Windows foreground-lock 限制点不进去），要挂到每日计划任务或用户终端跑；启动自动弹窗那条判据最稳。
- 适合：作为编码主力顺手领；签到走启动弹窗最稳
- 主人体验：有操纵电脑的能力（Computer Use），目前有 Qwen Flash 和 DeepSeek Flash 免费用，每天刷新限额。

### B · Trae（字节跳动）— 3.3 分

- 额度：100/天，31 天，连签/额外：无
- 模型：国内版 14 款：Doubao-Seed-2.0-Code、MiniMax-M2.7/M2.5、GLM-5.1/5V-Turbo/5、DeepSeek-V4-Pro/Flash、Kimi-K2.6/K2.5、Qwen3.6/3.5-Plus；国际版 19 款另含 GPT-6 系、Gemini-3.1、Kimi-K3【2026-10-22 官方文档】，CUE / MCP
- 简评：额度中等（100/天，2026-10-11 实测修正）但 31 天有效期 + 每月登录赠 500。国内版 14 款模型（DeepSeek-V4/GLM-5.1/Kimi-K2.6/Qwen3.6，比国际版慢半代，国际版已上 GPT-6 系/Kimi-K3）与 MCP 支持是优势。领取靠 UI + OCR 点击，窗口改版即失效，是五家里最脆的一环。2026-10-11 客户端从 TRAE SOLO CN 合并为 Trae CN（主窗口标题 'Agent'），脚本已同步适配。与 TraeCode 共用同一积分账户，别重复计数。
- 适合：需要多模型切换、MCP 工具链的编码任务
- 主人体验：_待补充_

### B · ZCode 智谱（智谱 AI）— 3.0 分

- 额度：周期制，服务端下发，连签/额外：无
- 模型：GLM-5.3（1M 上下文）/ GLM-5.3-Flash / GLM-5-turbo；ZCode 为 GLM-5.3 官方 Harness，绑定 BigModel/Z.ai 账号直用套餐【zcode.z.ai/cn/docs，2026-10-30】；本机版本 3.16.3.8992
- 简评：订阅制订额，无每日签到、不进自动盘（同 Kimi Work 的订阅型分组）；额度机制是 5 小时段 + 周双窗口、不结转，量级不小但不可攒。能力是台账天花板级：GLM-5.3 官方 Harness，agentic 编码全流程 + computer-use 原生桌面操控 + browser-use 浏览器自动化 + MCP/插件/技能生态 + 子智能体/定时/闲时任务，本仓库日常维护即由 ZCode 会话完成。短板：内置仅 GLM 系、无生图/生视频输出、无独立官方移动客户端（Remote/Bot 远控）。
- 适合：日常编码主力与长任务自动化；非高峰跑省额度
- 主人体验：_待补充_

### B · LobsterAI（网易有道）— 2.9 分

- 额度：100/天，30 天，连签/额外：无
- 模型：BYOK 多提供商（2026.10.16 客户端 provider 表）：内置免费 DeepSeek-V4.1-Flash（lobsterai-server/yd-fast，本会话 model=lobsterai-server/deepseek-flash）；BYOK 可接 OpenAI GPT-5.6 Sol/Terra/Luna、GPT-5.5/5.4，Anthropic Claude Opus 4.7/4.6、Sonnet 4.6，Gemini 3.1 Pro/3 Flash，xAI Grok 4.5/4.3，DeepSeek V4 Flash/Pro，Kimi K3/K2.6/K2.5，GLM 5.1/5/4.7，MiniMax M3/M2.7/M2.5，Qwen3.6/3.5 Plus，Doubao-Seed-2.0，另含 Ollama/LM Studio/GitHub Copilot/OpenRouter/自定义【2026-10-25 本机 app_config + dist-electron/shared/providers/constants.js；官网 2026.10.16】
- 简评：100/天、30 天可累积、无连签加成，额度本身不大；但每日「每日积分礼」UI 路线已连续实测入账（09-28..10-25 共 28 天，服务端 context claimedDays=34 / claimedCredits=3400），不再是「占着坑不产粮」。模型侧 2026.10.16 客户端已换到 DeepSeek V4 Flash/Pro、Kimi K3、GLM 5.1、MiniMax M3、Qwen3.6、Doubao 2.0，BYOK 还能接 GPT-5.6 / Claude Opus 4.7 / Gemini 3.1 Pro；浏览器自动化可调试，办公文档链路完整。短板：UI 签到依赖窗口锚点/OCR，近一个月多次因合成点击与前台遮挡失效；无原生 Computer Use；无手机客户端（仅 IM 远控）。
- 适合：日常办公/编码副手；每日顺手领，UI 自动签到已跑通
- 主人体验：2026-10-27 主人反馈：总是要等网关启动；不知道为什么不能「不设工作空间」直接用；切换工作空间时也要重启/启动网关，体感很慢。

### B · DuMate 百度搭子（百度）— 2.8 分

- 额度：500/天，30 天，连签/额外：无
- 模型：未公开型号（Turbo/Ultra 双模式，多模型混合架构 + 自研 Harness 引擎）【2026-10-22 公开渠道查不到具体清单】
- 简评：500/天是全场第二高，但领取上限（cap）始终没测出来，一期不敢自动领。百度系执行式智能体（型号未公开，Turbo/Ultra 双模式 + 行业套件），适合资料型任务。只要把 cap 摸清就能进自动盘。
- 适合：搜索资料、文档处理；待摸清上限后启用
- 主人体验：_待补充_

### B · JoyCode 京东（京东云）— 2.8 分

- 额度：一次性，至 2026-10-16，连签/额外：无
- 模型：JoyAI-Code / Kimi-K2（6 月起 K2.6）/ DeepSeek-V3.1 / Doubao-Seed-1.6（5 月起 Seed-2.0 多模态）+ Auto 路由；可自定义接入 OpenAI/Anthropic/Gemini 等【2026-10-22 官方文档】
- 简评：一次性 10000 积分，量很大但 10-16 到期，属于有死期的存量。京东云系编码平台（JoyAI-Code/Kimi-K2.6/DeepSeek-V3.1/Doubao-Seed + Auto 路由）。当前策略是永不自动、用时再开。
- 适合：到期前集中消耗，别放着烂掉
- 主人体验：_待补充_

### B · Kimi Work（月之暗面）— 2.7 分

- 额度：周期制，服务端下发，连签/额外：无
- 模型：Kimi K3（2.8T MoE、1M 上下文、原生视觉，单模型无选择器）【2026-10-22 官网复核：旧记仍然准确】
- 简评：周期制额度（下次重置 10-14），Kimi K3（2.8T MoE）+ 100 万上下文是长文档场景的独门优势，2026-10 官网复核 K3 仍是当前驱动模型。不自动领，按周期重置。
- 适合：超长文档阅读、办公写作
- 主人体验：_待补充_

### B · 讯飞 Loomy（科大讯飞）— 2.7 分

- 额度：5000/天，当日清零，连签/额外：无
- 模型：DeepSeek / MiniMax / 豆包 / 千问可切换 + 讯飞星火 X2.5/X2.6（API Key）；端侧星火 X2.5-4B【2026-10-22 官网+媒体：已扩为通用桌面 Agent，接入飞书/企微/钉钉】
- 移动端：有—— 有手机客户端，但似乎不能同步任务
- 简评：5000/天当日清零，另有永久 6500 托底。讯飞系已从办公/搜索/文档扩为通用桌面 Agent（文件整理/数据分析/网页操作/IM 远控，模型可切 DeepSeek/MiniMax/豆包/千问 + 星火 X2.5）。清零额度里算厚道的，但同样要当天开。没有手机客户端，意味着离开电脑就消耗不掉，进一步压低了它的实际价值。
- 适合：办公文档批处理，且必须在电脑前当天做掉
- 主人体验：有手机客户端，但似乎不能同步任务。

### B · Mavis 腾讯（腾讯）— 2.5 分

- 额度：10M token/天，当日清零，连签/额外：无
- 模型：Hy4 + DeepSeek-V4-Flash 双模型按任务难度自动切换 + 端侧本地模型（本地模式文件 0 上传），支持自定义接入【2026-10-22 官网】
- 简评：额度是全场最猛的 10M token/天，能力标签也写得最全（coding/office/local/remote）。但纸面参数与实测体感差距最大：模型侧为 Hy4 + DeepSeek-V4-Flash 双模型自动切换（无 K3/GLM-5 等新模型），且当日清零决定它进不了自动签到。2026-09 起定位 24 小时 AI 管家（电脑/文件/软件/浏览器 4 个子 Agent + 手机远控 PC + 端侧本地模型），是腾讯应用宝团队出品（官方名 Marvis 马维斯），电脑管理方向的差异化值得观察。
- 适合：电脑管理/系统运维方向值得一试；不适合项目编码与 vibe coding
- 主人体验：10M token 看着多，实际不好用。「省心组合」模型更新慢、能力弱、响应也慢（当前是 hy4preview + deepseek v4pro）。不知道是上下文管理还是提示词的问题：做项目推进很慢，输入抓不到重点，输出倒是全面细致但没重点。没有工作空间设计，不适合 vibe coding。多 agent 的设计也没看出明显优势。唯一可能的价值点在于是腾讯电脑管家团队出品，电脑管理方面或许有点用。【2026-10-22 公开渠道更正：实为应用宝团队出品，官方名 Marvis 马维斯；模型现为 Hy4 + DeepSeek-V4-Flash】

### C · CatPaw 美团（美团）— 2.3 分

- 额度：一次性，365 天，连签/额外：无
- 模型：自研 LongCat 2.0（1.6T 总参、1M 原生上下文，2026-07 开源）+ 多模型混合可配【2026-10-22 官方博客：已升级为全场景 Agent 平台】
- 简评：新用户 1000 一次性，365 天有效期。2026-07 起升级为搭载自研 LongCat 2.0（1M 上下文）的全场景 Agent 平台（工作台 + Managed Agents），不再只是编码 IDE。没有每日签到，领完就没有后续产出。
- 适合：一次性消耗完即可
- 主人体验：_待补充_

### C · 扣子 Coze（字节跳动）— 2.3 分

- 额度：1500/天，当日清零，连签/额外：无
- 模型：DeepSeek-V4-Pro / GLM-5.3 / Doubao-Seed-2.1-pro / Kimi K3 + Seedream 5.0/Seedance 2.5 多模态；扣子编程另有 MiniMax M2.5/GLM-5/Seed-2.0-Code【2026-10-22 官方文档：已扩为多模型货架 + AI 编程】
- 简评：1500/天当日清零。字节系多模型货架（DeepSeek-V4-Pro/GLM-5.3/豆包 2.1/Kimi K3）+ Seedream/Seedance 多模态生成 + 扣子编程，模型新鲜度是清零档里最高的。清零机制决定它只能当临时补充。
- 适合：多模态/搜索类临时任务
- 主人体验：_待补充_

### C · ToDesk AI（ToDesk）— 2.0 分

- 额度：500/天，当日清零，连签/额外：无【2026-11-16 主人确认改版，原 100/天·30 天·7 天连签+600 作废】
- 模型：GLM-5V-Turbo / Qwen3.5-Plus / Kimi-K2.5 / 豆包 / DeepSeek / MiniMax / Step 约 7 款可切换 + 自定义 API【2026-10-22 官网+社区实测，具体型号以客户端为准】
- 简评：500/天但当天过期、不可累积。2026 已升级为独立桌面 Agent（V3.0）：7 款三方模型可切（GLM-5V-Turbo/Kimi-K2.5 等）+ 键鼠执行 + 定时任务，不再只是远控附加，但和编码主力场景重叠度仍低。
- 适合：远程协助场景，顺手领
- 主人体验：_待补充_

### C · MonkeyCode 积分（长亭百川）— 1.6 分

- 额度：100/天，服务端下发，连签/额外：无
- 模型：模型无关（BYOK），可使用 GPT / Claude / DeepSeek / GLM / Kimi / Qwen / 豆包及本地模型【2026-10-22 官网】
- 简评：目前只有每日签到 +100 积分，不再发放其他额度或 Token。签到 UI 自动化已打通并实测入账；积分总量可自动对账，但没有逐条有效期信息。
- 适合：长亭百川系编码客户端的每日积分，脚本自动领取
- 主人体验：签到入口在账号页积分卡片下方；签到 +100 积分。

### C · 千问办公（阿里巴巴）— 1.6 分

- 额度：100/天，当日清零，连签/额外：无
- 模型：官方未公开具体型号，旗舰 Qwen3.8-Max 驱动（2.4T MoE、1M 上下文）【2026-10-22 官方文档：2026-08 新上线的一站式办公智能体】
- 简评：100/天当日过期。阿里系一站式办公智能体（Qwen3.8-Max 驱动，2026-08 上线，覆盖文档/PPT/网页/视频剪辑/浏览器自动化），但额度太小，属于聊胜于无。
- 适合：几乎不值得专门启动
- 主人体验：_待补充_

### C · 商汤小浣熊（商汤科技）— 1.6 分

- 额度：300/天，待确认，连签/额外：无
- 模型：日日新 SenseNova U1 / U1.5（原生统一多模态）【2026-10-22 官网：办公/代码小浣熊已合并为统一品牌】
- 移动端：无手机客户端，离开电脑用不了
- 简评：300/天，商汤系办公文档向（已接入 SenseNova U1，9 月起办公/代码小浣熊合并为统一品牌并出行业版），额度在这个量级很难支撑一次像样的任务。2026-10-02 更新：改为网页登录即领、有效期多天（待确认）——若确为多天有效，它比同类当日清零产品更值得定期去领。无手机客户端。
- 适合：低频办公辅助；网页端顺手领
- 主人体验：每日积分是网页登录即领，不是客户端；有效期若干天（天数待确认）。没有手机客户端。

### C · 阶跃 AI（阶跃星辰）— 1.6 分

- 额度：20/天，当日清零，连签/额外：无
- 模型：Step 3.5 Flash / Step 3.7 Flash / Step 5 Preview（Agentic 旗舰，权重已开放）【2026-10-22 官方平台】
- 简评：20/天当日过期。阶跃星辰已上 Step 5 Preview（Agentic 旗舰）与 Step 3.7 Flash 多模态推理，模型本身不弱，但全场最低额度，基本可以忽略。
- 适合：基本忽略
- 主人体验：_待补充_

### D · Accio Work（阿里国际）— 1.3 分

- 额度：200/天，当日清零，连签/额外：无
- 模型：Gemini / GPT-4o / Claude / Qwen 经自家网关路由，可按 Agent 分配【2026-10-22 官网 FAQ】
- 简评：200/天当日清零，阿里国际电商向（Gemini/GPT-4o/Claude/Qwen 网关路由，型号偏旧）。场景窄 + 额度小，优先级垫底。
- 适合：跨境电商相关任务才考虑
- 主人体验：_待补充_

<!-- END RATING -->

## 一期范围

- 每日必签（无上限可攒）：WorkBuddy / MiniMax / Trae / AutoClaw / LobsterAI / **MonkeyCode 积分**
- 自动签到：优先 external 直签（WorkBuddy，全自动无 GUI）；其余走本机客户端 UI
- 幂等：所有签到脚本都先用只读接口确认「今天是否已签」，已签直接返回，**不启客户端、不做点击**
  （MonkeyCode 用 `GET /api/v1/users/wallet/checkin`；LobsterAI 用 chip 上的「今日已领」文案）
- 可选：在 `catalog.yaml` 填 `command` 覆盖为外部脚本
- 对账：签到后自动拉服务端真实余额校正台账（catalog 填 `credits_command` 逐条明细 / `status_command` 总量快照；`credit sync` 可手动跑，`AGENT_CREDIT_SKIP_SYNC=1` 可关）。WorkBuddy 已打通逐条过期；MonkeyCode 已打通总量快照（无逐条过期，validity 仍 unknown）；随后刷新积分看板（`credit board`）
- AutoClaw：每日 200；有效期分类（daily/monthly/longTerm/campaign），不是『永不过期』，台账按过期未知处理；UI 失败后 `record autoclaw claimed 200`
- DuMate / ToDesk：上限未测出前不自动领
- 不做：定时启动 Mavis / Loomy 等当日清零客户端

## 仓库约定

**探索任何客户端之前先读 `research/SAFETY.md`。** 这些账号承载真实付费订阅，
被判定为自动化攻击会直接封号、囤的积分归零——代价远高于多领 100 积分。
核心是：只读明文凭据 + 只调官方接口 + 只走客户端自己的界面；
不解密登录态、不开调试口、不篡改客户端、不写重试风暴、不绕验证码；
**查不到就写 unknown，别硬钻**。

**不按文件名前缀、也不按「谁生成的」决定是否入库**，判断标准是开发规范：

| 判断 | 处置 | 例子 |
|---|---|---|
| 是项目资产（换机器还要用、需要被审阅） | **入库** | `scripts/forensics_*.py`、`research/tools/`、`.workbuddy/memory/*.md` |
| 一次性改写脚本（使命完成） | **用完即删**，不留占位 | 改注册表的临时 patch 脚本 |
| 运行期产物（状态而非代码） | **.gitignore 排除** | `data/ledger.json`、`logs/` |

曾用 `_` 前缀标记「本地草稿不提交」，已废除——那个约定会让有用的取证脚本被
永久排除在版本控制外，下次排查同类问题只能重写。取证与探路脚本恰恰是最该
入库的：它们记录了「怎么发现的」，比结论更值钱。

`.workbuddy/memory/` 下的技术判断与踩坑记录同样入库，理由一样：
「为什么当初判断 external 走不通」「为什么窗口要按可见性+标题过滤」这类
推理过程，等价于 `research/answers/`。只有 `automations/`（agent 运行时任务
记忆，UUID 命名）属运行期产物，被忽略。

## 命令

在本目录：

```bat
credit.cmd status
credit.cmd due
credit.cmd doctor
credit.cmd checkin
credit.cmd checkin --open
credit.cmd open workbuddy
credit.cmd recommend 重构这个仓库
credit.cmd record autoclaw claimed
credit.cmd set-balance minimax 3200
credit.cmd record workbuddy used 50
credit.cmd board
credit.cmd sync
credit.cmd credits workbuddy
```

或：`python credit.py status`

改完评级后重刷上面的表格：

```bat
python scripts\gen_rating_table.py --write
```

改完 `catalog.yaml` 提交前**必须**跑一遍校验：

```bat
python scripts\test_catalog_yaml.py
```

它检查四件事，因为本项目有两个 YAML 解析器、要求不一样：
`catalog.yaml` 由自带的 `agent_credit/yaml_lite.py` 解析（零依赖），
但编辑时你可能顺手用了 pyyaml 才支持的写法——

- **`>-` / `|` 折叠标量**：`yaml_lite` 不支持，会直接抛 `bad indent`，而 pyyaml 能过
- **双引号标量里的裸 `"`**：pyyaml 报 `expected <block end>`，`yaml_lite` 可能静默截断
- `yaml_lite` 解析结果里 accounts / calendar / validity_audit 是否齐全
- pyyaml 能否解析（两个解析器都过才算安全）

## 积分余额看板

`credit board` 把台账里各家的余额、**每条积分的剩余与过期时间**、以及烧卡优先级汇成一张表：

```bat
credit.cmd board              :: 终端可读看板（同时落盘）
credit.cmd board --account trae
credit.cmd board --json
```

产出两份：

- `logs/board/board-YYYY-MM-DD.md` —— 人看（账户总表 / 临期队列 / 烧卡优先级 / 逐条明细 / 数据质量）
- `data/board.json` —— 机器读

看板把三种口径分开标，不混为一谈：

| 口径 | 含义 | 谁 |
|---|---|---|
| **服务端真值** | 余额与过期日都来自服务端逐条明细（source=sync） | WorkBuddy、Trae、**MiniMax** |
| 本地估算 | 余额按每日签到累加，过期日按 catalog 有效期算 | LobsterAI |
| 真值总量 + 推导过期 | 服务端只给桶总量，用它校正台账总数；每条到期日来自「领取日 + 有效期」 | Qoder CN（reconcile 契约） |
| 过期未知 | 服务端没下发有效期，排序按「最后动」处理 | AutoClaw、MonkeyCode 积分 |

已经打通服务端通道的账户（`catalog.yaml` 里配了 `credits_command`）：

| 账户 | 能查到 | 通道 |
|---|---|---|
| WorkBuddy | **逐条**剩余 + 每条过期时间（47 条量级） | 只读调官方 billing/meter 端点 |
| MiniMax Code | **逐条**剩余 + 每条过期时间（40 笔量级，含已过期与已用尽） | 只读 GET `/minimax-cloud/api/v1/credit/details`（2026-10-24 打通） |
| Trae | 总余额 + 到期日（聚合口径，逐包需 UI OCR） | 客户端扩展导出 dump |
| MonkeyCode 积分 | 总余额（**无**逐条过期） | 只读 GET /users/wallet（毫积分 ÷1000） |
| Qoder CN | 总余额 + 分桶（套餐内/资源包）+ 今日签到态；服务端**不下发**逐条批次，台账用 reconcile 保住每条的推导到期日 | 读客户端自己落的 `me/usage` 日志摘要 |

**每日签到后自动同步**：`checkin` 末尾会跑对账（拉服务端真实余额）并刷一次看板，
看板已包含 Trae/Qoder 当轮登记的数据。每日链路 `scripts/_daily_chain.ps1` 只在
「补拉真的又跑过」（`logs/checkin_last.json` 判定本轮不是 pending/failed、且明细
仍不新鲜）时才再刷一次，避免同一份数据刷两遍。

⚠️ Qoder CN 的用量只在**打开「我的用量」面板**那一刻才向服务端取（不像 WorkBuddy 那样
随命令即取），所以它同样有 Trae 那种「新鲜度闸门」：台账里没有当天记录时，对账如实报
失败、不拿旧值覆盖签到后的余额。每日链路里已接好触发步——
`scripts/ui_claim_qodercn.ps1 -Usage` 在签到后点开一次小窗（2026-10-20 实测：点击
screen(400,2023) 开窗，同一秒 main.log 落下新的「用量响应摘要」），随后
`credit.py sync --only qodercn` 由闸门裁定有没有取到新数。

烧卡层级（当日清零 > 7 天内到期 > 长期 FIFO > 有上限 > 过期未知）与 `recommend`
共用 `agent_credit/priority.py` 一份口径：看板说先烧 A、推荐说先烧 B 那种分裂，
是这类项目最容易出的内耗。

## 积分有效期

2026-10-04 逐家实测，结论与证据存在 `catalog.yaml` 的 `validity_audit_2026_10_04`。
可信度分三档，别把「unknown」当成「永久有效」：

| 账户 | 天数 | 可信度 | 依据 |
|---|---|---|---|
| MiniMax Code | **30** | confirmed | asar i18n 官方文案 + 服务端 `expire_at_ms` 算出正好 30 天 |
| WorkBuddy | 30 | measured | 本地记账规则；服务端 status 无有效期字段 |
| LobsterAI | 30 | measured | i18n `dailyCheckInValidityDays` 的 `days` 是服务端变量；UI 实测 30 天 |
| Trae | 31 | measured | 官方规则页 + 双方 Agent 自述（FIFO 自然日）；API 无字段 |
| AutoClaw | **分类，无统一值** | measured | 积分分daily/monthly/longTerm/campaign 四类，各类独立算；明细页在设置→积分 |
| MonkeyCode 积分 | ? | **unknown** | 2026-10-20 复扫：wallet 无 expire/grants，exe 仍只有 wallet/checkin；总量可对账（毫积分÷1000），逐条过期仍无从查证 |
| Qoder CN | 30 | **measured（仅官方文案）** | 活动弹窗写「领取后 30 天有效」；但 2026-10-20 实测服务端 `me/usage` 只下发桶、不下发逐条过期，`expiresAt` 是本套餐的年 9999 哨兵 → 台账里每条的到期日按「领取日+30」推导（看板标「按领取日推导」），总量以服务端为准 |

三个容易踩的坑：

- **MiniMax 赠予积分 30 天，付费积分 1 年**——同一段 i18n 里写明，别混用。
- **AutoClaw 的有效期是分类的**，问「多少天」本身不成立。而且它有「长期积分」这一类，
  说明并非全部统一过期。查法是设置 → 积分明细页，每条流水带 `{{date}} 到期`。
- **AutoClaw 的「N 天内到期」是滚动提示**，永远显示最近一批的剩余天数
  （实测见过「152 积分 3 天内到期」和「542 积分 3 天内到期」），
  不能反推出固定有效期。

> 方法论：判断有效期时**别只探接口**。客户端的积分明细页往往本来就展示这个信息，
> 读 UI 属于 `research/SAFETY.md` 的允许路线，不需要解密任何东西。
> AutoClaw 就是靠读明文 dist + UI 才把「unknown」翻成「measured」的。

## 排查工具

客户端出问题时先取证再改代码，工具都在仓库里：

```bat
:: 枚举某客户端全部顶层窗口 + 逐个抓图判黑（定位「全黑窗口」这类问题）
python scripts\forensics_lobster_windows.py --launch
python scripts\forensics_monkeycode_windows.py --launch

:: 验证窗口选择判据是否还会选错
python scripts\verify_lobster_pick.py

:: 界面探路：按坐标点击 + 截图，定位签到按钮
python scripts\monkeycode_probe_ui.py --tag s0
```

窗口坐标换算的坑（三套坐标系混用）见 `scripts/ui_claim_monkeycode.py:content_click`
的注释：截图 PNG 真实像素 == 窗口 rect，但 Read 展示时会缩略到 1088 宽，
`scale = w / 1088` 再加窗口原点才是对的。

## 计划任务（可选）

```powershell
powershell -ExecutionPolicy Bypass -File scripts\register-task.ps1
```

## 托盘/隐藏窗口

UI 签到要的是客户端的**主窗口**，光有进程（关到托盘）不算。2026-10-29 起：

- Qoder CN / Trae：可见窗口找不到时，枚举同进程的隐藏 `Chrome_WidgetWin_1` 主窗口，
  `ShowWindow(SW_RESTORE)` 还原后重新定位（最大化状态会在收尾时恢复）。
- LobsterAI / AutoClaw：同样先枚举隐藏的「有标题、非黑窗」大窗口并还原；
  LobsterAI 还原失败才走「再拉起一个实例」，AutoClaw 还原失败就用原来的 60 秒等待。
- MiniMax / MonkeyCode：本来就接受隐藏主窗口并自己 `ShowWindow`，无需改动。
- WorkBuddy 走 API 直签，不涉及窗口。

还原会把窗口从托盘拉出来，跑完不会自动再塞回去。2026-10-29 实测：Qoder 主窗口
`WS_VISIBLE=off` 时能在 1 秒内还原（以前要白等 90 秒后报 notfound）。

## 启动闸门（签到前确认）

`credit checkin` 在**可见控制台**里会先问一句再动手：

- 15 秒倒计时（`--gate-sec N` 或 `AGENT_CREDIT_GATE_SEC` 可改）
- `Y` / `Enter`：立即开始，不再等空闲
- `N` / `Esc`：跳过今天的 UI 组（Trae / AutoClaw / LobsterAI / Qoder CN / MonkeyCode），
  外部直签和对账照常；`_daily_chain.ps1` 读到 `logs\gate_last.json` 后跳过后续会弹窗的
  Trae 明细同步与 Qoder 用量刷新
- 超时无输入：自动开始

计划任务按无人值守处理，不弹提示也不等空闲：`_daily_chain.ps1 -Unattended` 显式传入时
直接放行；没带开关的旧任务/手动触发则看父进程是不是 Task Scheduler（`svchost.exe`），
是也直接放行。不再靠「控制台窗口是否可见」判断——任务里的可见性不可靠，2026-10-29
00:34 那轮就因此白等了 15 秒。手动跑脚本或 `credit checkin` 仍会弹提示。
`AGENT_CREDIT_GATE=legacy` 可退回旧行为，`--no-gate` 强制直接开始。
每次决策落在 `logs\gate_last.json`（含 action / source / date）。

## 防撞锁（同一时间只跑一条链路）

- 计划任务 `agent-credit-checkin` 的 `MultipleInstancesPolicy` 已从 `IgnoreNew` 改为
  `Queue`：上一条链路跑过头（例如 23:58 启动、跨零点才结束）时，00:00 的触发会排队，
  而不是被直接丢弃。
- `_daily_chain.ps1` 整条链持有 `logs\checkin.lock`（`FileShare.None`，进程结束自动释放），
  最多等 20 分钟；手动 `credit checkin` 在 Python 端抢同一把锁，撞上直接退出码 `4` 并提示，
  不会两个实例同时开客户端。
- 2026-10-29 的漏签就是 `IgnoreNew` + 跨零点链路造成的，现在两层都补上了。

## 运行进度与日志

每日计划任务跑的是一个控制台窗口，而 UI 签到（拉起客户端 → 等窗口 → OCR → 点击 → 复核）
动辄几十秒到几分钟。现在每一步都会实时打印，并同步落盘：

```bat
credit checkin            :: 逐账户打印「开始 / 结果」，子脚本的输出实时转发
credit checkin --hold 30  :: 跑完停留 30 秒再关窗口（手动排查时用）
```

- 控制台每行带耗时与来源：`[+12s 00:05:31] <3/19 trae> Trae 开始（应签，mode=ui）`
- 同一份输出写入 `logs\checkin_YYYY-MM-DD.log`，窗口关掉也能回看
- 提权跑的 ps1（MiniMax / AutoClaw / LobsterAI）的 stdout 拿不到，改由脚本自己写
  `logs\ps1_<name>.log`，父进程 tail 出来
- 输出统一 UTF-8（子进程吐 GBK 也能正确解码），中文不会再变问号

## Agent 技能

技能文件：`skill/SKILL.md`。已安装到用户技能目录后，对话里说「今天签到」「这个任务用哪个」即可。
