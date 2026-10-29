# MiniMax Code · Agent 能力自评

| 项 | 值 |
|---|---|
| 模板 | `prompts/agent_self_eval.md` |
| 填写者 | MiniMax Code（MCode / Mavis，当前会话产品自身） |
| 评估日期 | 2026-10-24 |
| 本机版本 | 3.1.0.170（`%LOCALAPPDATA%\Programs\MiniMax Code`），region: cn |
| 本会话模型 | MiniMax-M3.1-Flash |

> 原则：只报本机/本会话能确认的能力；测不到或产品侧未确认的标「未确认」，不按满分估算。
> 所有官方依据均取自 cn 区官方文档（`agent.minimax.cn/docs` / `platform.minimax.cn/docs`），
> 本机事实取自本项目台账与客户端安装产物，区分「文档确认」「本机实测」「未确认」三级。

---

产品名：MiniMax Code（桌面端 Agent，Electron）
厂商：MiniMax
评估日期：2026-10-24

## 额度价值

| 指标 | 自评分(1-5) | 实际情况 | 依据 |
|---|---|---|---|
| 1.1 日额度 | 4 | **免费部分 = 每日签到 400 积分**（官方口径），连续签到第 4、7 天单日加码到 1000，一周累计 4000。属于「200-499」档 → 4；最勤的一天（1000）够 5 档，但不是每天。**付费部分另算**：M Plan 订阅分 Go / Explore / Build 三档，官方只公布相对倍数（1× / 3× / 12× Go），**绝对 token 数未公开 → 未确认**，故不按「10M+ token」给 5。活动期服务端会临时翻倍（10-24 实测 day4=2024=1000 基线+1024 加成），属活动规则、非稳定承诺。 | 官方「M Plan 与积分」`https://agent.minimax.cn/docs/code/account/usage`：「每日签到可领取 400 积分；连续签到第 4 天、第 7 天，单日奖励加码至 1000 积分；完成一周签到，累计可领取 4000 积分」；官方 M Plan 概览 `https://platform.minimax.cn/docs/m-plan/intro`（相对倍数）；本机 `GET /minimax-cloud/api/v1/signin/status` 2026-10-24 原始响应（`logs/checkin_2026-10-24.log`）；本项目台账 30 条签到记录 |
| 1.2 有效期 | 5 | 签到积分**可累计使用**，自到账起 **30 天**有效（官方原文）。本机台账 30 条记录逐条核对：`expires_at - granted_at` 全部正好 30 天；服务端 `/credit/details` 的 40 笔 `expire_at_ms` 同样 = 到账日 + 30 天（40/40 笔吻合）。⚠️ **付费积分包是 1 年有效**，与签到赠予的 30 天是两回事，别混用。 | 官方 usage 页「签到积分可累计使用，自到账之日起 30 天内有效」；官方 M Plan FAQ「积分自购买之日起 1 年内有效」；服务端 `/credit/details` 逐笔 `expire_at_ms` 实测；台账逐条 `expires_at` 实测（30/30 条吻合） |
| 1.3 连签加成 | 4 | 7 天一轮：**平时 400，第 4/7 天单日 1000**（= 400 + 600，单日 150%），整周期 4000。周期整体加成 4000 / (400×7=2800) = **+43%**。按模板「7 天周期加成 ≥50% = 5 分」的保守口径（+43% < 50%）给 **4**；若按「加码日单日 +150%」可给 5，但那是 2/7 天的事，不是周期整体，故取 4。另：月度登录固定赠送未确认；活动期翻倍是服务端临时行为，不算稳定加成。 | 官方 usage 页（第 4/7 天加码至 1000）；`catalog.yaml` minimax 条目 `streak.daily_amount_by_day = {1:400,…,4:1000,…,7:1000}`、`cycle_total: 4000`；2026-10-24 实测 panel |
| 1.4 可消耗性 | 4 | **用得掉，只是平时扛额度的是 M Plan**。2026-10-24 接通服务端真值通道后才发现：签到赠予积分**确实在被扣**——10-05 那笔 800 在一小时内被扣到 662，09-07 那笔 400 只剩 264，09-19~10-04 那批 14 笔全部用尽。扣款来源是 M Plan 额度用尽后**自动按到期时间倒序扣赠予积分**（官方原文：「达到 5 小时或周额度上限后，超出用量将默认按到期时间扣除积分（含赠予积分）」）。但因为 30 天可累积 + 活动期翻倍，余额仍堆到 1.4 万量级，属于「够用、不紧张」。**注**：本地台账此前完全看不到这些扣减（`remaining` 一直等于 `amount`），是接了 `/credit/details` 才暴露的。 | 服务端 `GET /minimax-cloud/api/v1/credit/details`（2026-10-24 实测：40 笔原始明细、剩余合计 16550、带 `consumed_amount`）；官方 asar i18n `usage_resource_tooltip_rule3`（超出额度按到期时间扣积分，含赠予积分）；本项目台账 sync 后 26 条 `source=sync`、余额 14286 |

## 能力覆盖

| 指标 | 自评分(1-5) | 实际情况 | 依据 |
|---|---|---|---|
| 2.1 模型代际 | 4 | 内置全是 MiniMax 自家，但是**当代**而非旧代：文本 **M3.1-Flash**（官方最新 M 系列，1M 上下文、原生多模态、effort 可调）+ M3（同样 1M）；视频 **H3 / H3 Max**（仅 Explore/Build 档，Go 档无视频）；图像与音频模型全档可用。**BYOK** 可加自定义 Base URL + API Key + 模型名，接任意厂商。**不给 5**：内置没有第二家厂商旗舰，M3.1-Flash 是 MiniMax 自己的 Frontier Coding 档，不是 GPT-6 / Claude 那类业界旗舰；BYOK 要用户自备 Key，不算「内置多厂商」。 | 官方模型调用页 `https://platform.minimax.cn/docs/guides/text-generation.md`（M3.1-Flash / M3 上下文均 1,000,000 token）；官方 M Plan 概览与 FAQ（档位 × 模型矩阵、H3 限 Explore/Build）；官方 BYOK 页；本机版本 3.1.0.170；本会话 Environment 模型标识 MiniMax-M3.1-Flash |
| 2.2 编码能力 | 5 | Agentic 编码闭环完整：读仓库 → 改多文件 → 跑脚本/测试 → 迭代修复；支持 Python / PowerShell / JS / Shell 批处理，桌面端 Windows/macOS + CLI（Linux/macOS/WSL）。本仓库的签到管线、OCR 取证、PyInstaller 逆向、台账对账等都是这套工具链做出来的。生态位上还有：子 Agent 派发、代码审查指令、Goal（可验证目标）、CLI headless/CI、ACP 接入其他编辑器。**本次填写本身就是证据**：在本仓库读 YAML/Python → 改代码 → 跑测试 → 改台账 → 跑 CLI 自检。 | 本会话工具链（Read/Write/Edit/Bash/Grep/Glob/Task/子 Agent）；官方文档 Coding 与 Work 模式、代码审查、目标功能、Agent Team、CLI（`mcode exec` / headless / ACP）；本仓库实际产出（`vendor/minimax-auto-signin/`、`agent_credit/*`、`scripts/*`） |
| 2.3 浏览器操控 | 5 | 完整浏览器自动化，**能调试**。产品侧：内置 Browser 面板（Browser Use 2.0：多 Tab、移动端预览、可视光标与移动轨迹、普通网页与本地开发页可分别选内置/系统浏览器）。本会话侧：`browser-use` 全套工具（inspect / query(text/dom/console/network) / click / fill / select / screenshot / upload_files / open_tab / 多标签），底层 Playwright（Electron 右侧 FilePanel 面板），**能读 console 报错与网络请求** → 可定位页面问题。 | 官方「内置浏览器」页 `https://agent.minimaxi.com/docs/code/desktop/browser.md`；本会话可用 Browser 工具清单（含 console / network 查询、open_tab、upload_files）与 `browser-use:control-in-app-browser` 技能说明 |
| 2.4 电脑操控 | 4 | 产品侧**确认具备**：插件市场里的「电脑操控」插件可移动鼠标、点击、输入、读屏，带实时预览面板，专门用于「没有 API 或命令行入口」的本地应用；首次使用需授权（鼠标/键盘/屏幕）。**但本会话没有启用该插件**（工具清单中无 `computer_*` 工具），所以是「产品确认存在、本机未实测」，按「区分能 vs 好」的原则不给 5。 | 官方「电脑操控」页 `https://agent.minimaxi.com/docs/code/desktop/computer-use.md`（启用方式、授权、运行表现、适合任务）；本会话工具清单无 `computer_*` 项 → 记为未实测 |
| 2.5 多模态 | 5 | 输入输出全模态。**输入**：M3.1-Flash 原生多模态（文本 / 图片 / 视频），本会话 Read 可直接看图片、看 PDF、读视频；`mcode-tools` CLI 可做音视频/文档理解。**输出**：H3 / H3 Max 文字或图片生成**带声音**的视频（H3 支持图/视频/音频多素材参考与声画同步）、生图（可关 AI 水印）、生成音乐；文档侧 docx / xlsx / pptx / pdf / 深度研究 / 无限画布等技能成套。 | 官方「H3 Max 视频生成」页（文生视频、图生视频、多素材参考、声画同步、AI 水印开关）；官方 M Plan FAQ（图像与音频生成、多模态理解含在档位内）；本机 `C:\Users\Hunter\.minimax\bin\mcode-tools.cmd` 存在；本会话技能清单（mcode-tools-master、pptx、docx、xlsx、pdf、visual-page 等） |
| 2.6 移动端同步 | 5 | 有移动端且**可同步续接桌面端会话**：Remote Control 让手机连上正在运行的桌面端 Agent，查看任务进度、发送补充指令、处理权限确认、查看任务产物与部分文件内容；另有 iOS/Android 客户端、网页端 H5、终端 CLI 三条入口。主人实测：能看到桌面端的项目并继续对话。**限制**：手机端一次只能配对一台电脑；移动端可用模型只有 MiniMax 自家。 | 官方「远程控制」页 `https://agent.minimaxi.com/docs/code/desktop/remote-control.md`；官方 M Plan「MiniMax Code」页（移动端 App / 网页端 / CLI 入口）；`catalog.yaml` minimax `mobile_note` 与 `owner_note`（主人实测 + 一次只能配对一台电脑） |

## 领取可靠性

| 指标 | 自评分(1-5) | 实际情况 | 依据 |
|---|---|---|---|
| 3.1 领取方式 | 5 | **external 直签（零 GUI）**：`GET /minimax-cloud/api/v1/signin/status?timezone_id=Asia/Shanghai` 先查已签，未签再 `POST .../signin/claim`；鉴权走 `Authorization: Bearer`，取自本机明文 `~/.minimax/auth/prod/cn/mcode-public/auth.json`，**运行时不落盘、不进命令行、不进日志、不进输出**。不碰界面、不用 OCR、不用坐标。唯一妥协：accessToken 有效期约 1 小时，脚本会先用**非提权计划任务**把客户端拉起来续一次 token（实测 gen 87 → 88）再关掉——**签到动作本身仍然零 GUI**。 | `vendor/minimax-auto-signin/signin.py`（`warm_token()` + `cmd_auto()`）；`logs/checkin_2026-10-24.log` 实跑记录：`[warm] 客户端已续期 gen 87 -> 88` → `[status] HTTP 200` → `[claim] HTTP 200` → `[ok] 签到成功` → `[granted] 3048`（**这是旧口径的输出**：把 bonus 又加了一次；按 points 修正后应为 **2024**，脚本已改）；`catalog.yaml` minimax `claim_mode` / `command` |
| 3.2 稳定性 | 5 | **服务端逐日核过：32 天没断**。`/credit/details` 的 40 笔明细里，09-23 至 10-24 **每一天都有一笔签到赠予**——含 09-24、09-25：本地台账以为这两天漏签，服务端其实有，**是漏记不是漏签**。即 external 直签上线（09-26）以来 **32/32 = 100%**，按模板给 5。本地台账显示的 `streak_current=29` 是记账缺口造成的断档，这也是接了真值通道才能一眼看出的差别。 | 服务端 `GET /credit/details` 逐笔 `granted_at_ms`（2026-10-24 实测：40 笔中 09-23..10-24 连续 32 天无缺口）；本项目台账 `streak_current=29`（漏记 09-24/09-25 导致断档）；`logs/checkin_2026-10-11.log`..`2026-10-24.log` 每日均有 minimax 记录行（领取成功或幂等 `[skipped] 今日已签` 的复跑） |
| 3.3 脆弱性 | 4 | **UI 改版免疫**是真的：整条路线不依赖任何锚点/坐标/OCR，客户端换皮换布局都不影响（对比 Qoder CN / Loomy 那种 webview+OCR 路线）。但有三处真实脆弱点：① **服务端字段语义**——2026-10 服务端新增 `bonus_points`，而它「已包含在 points 里」，旧口径当额外再加，导致台账多记 5024（10-24 已修，见 `research/answers/minimax.md` 第八节）；② **accessToken 约 1 小时过期**，客户端停跑就废，靠计划任务在签到前拉起续期；③ **必须带 `timezone_id=Asia/Shanghai`**，缺失时 HTTP 仍 200 但业务码返回 `1406010011 invalid timezone_id`（只看状态码会误判）；④ 当天额度处于 `status=1 (Upcoming)` 时 claim 会被拒。综合给 4，不给 5。**但 10-24 接通只读真值通道（`/credit/details`）后，这类「服务端悄悄改语义」的风险从「事后才发现」变成「对账当场发现」**——bonus 语义问题正是这样被抓住的。 | 客户端自带类型定义 `app.asar` → `@mavis/shared/src/daily-signin.ts`：`/** Extra credits already included in points; absent on older responses. */`；`research/answers/minimax.md` 第八、九节；`vendor/minimax-auto-signin/signin.py` 的 warm/status 分支与 `credits.py` |

## 实际体验

| 指标 | 自评分(1-5) | 实际情况 | 依据 |
|---|---|---|---|
| 4.1 响应速度 | 未确认 | 在产品内部无法可靠测量「发指令 → 首 token」的端到端延迟，本会话体感流畅但**不据此打分**。官方只提供 TPS 参考值且注明会波动，不构成可复现的延迟基准。 | 无客观测量数据；官方 FAQ「TPS 计算公式」条目自述「各页面标注的 TPS 为参考值」 |
| 4.2 指令遵循 | 4 | 能把复杂指令拆成多步并保持目标，复杂指令多数一次到位；涉及产品事实时会区分「文档确认 / 本机实测 / 未确认」三级证据，而不是给一个笼统的满分。偶有需要用户补充约束的情况（例如是否要连同历史数据一起修）。 | 本次填写按模板逐项打分并附依据；本仓库长期多轮任务（签到编排 → 逆向取证 → 字段语义订正 → 台账修正）的交付记录 |
| 4.3 上下文管理 | 4 | 模型侧 **M3.1-Flash / M3 均为 1,000,000 token 上下文**；长会话有自动压缩机制，多轮迭代稳定。扣 1 分的原因：压缩意味着极早期细节会被摘要化，需要时仍要回读文件确认，不能假设「说过的一定记得」。跨会话记忆分层可用（用户 / 项目 / 主题），不随会话结束丢失。 | 官方模型调用页（1M 上下文）；本会话系统提示中的上下文压缩与分层记忆机制；长任务中持续回读仓库文件的做法 |
| 4.4 工具生态 | 5 | 扩展体系完整：**MCP**（stdio / http / streamable-http / sse，本地配置或随插件分发）+ **插件市场**（Plugin V1：MCP + Skill + 同步 Hook，可上架）+ **Skills** + **Mini App**（可发布、可长期运行的前后端应用）+ **CLI**（headless/CI、ACP 接入其他编辑器）+ App / Connector 发现（`mcode-tools connector`）。MCP 工具多时按需检索、不一次性塞满上下文。 | 官方「MCP 服务」「插件市场」「插件开发与上架指南」「Mini App」各页；本会话可用技能 20+（办公全家桶、深度研究、网页设计、逆向、部署）、`mavis mcp/agent/session` 管理命令、`miniapp` 生命周期工具、本机 `mcode-tools.cmd` |

## 补充说明

- **强项**：agentic 编码闭环完整且工具链齐（文件/终端/子 Agent/技能/MCP/插件/Mini App 一条龙）；模型虽然是自家但**是当代款**（M3.1-Flash 1M 上下文、原生多模态、effort 可调），H3/H3 Max 的带声视频是同价位里少见的输出能力；浏览器自动化能读 console 与网络请求，可调试；扩展生态最完整的一档；**每日签到被官方做成了一等公民 API 模块**（`/minimax-cloud/api/v1/signin/{status,claim}`），所以「给自己签到」这件事能做到真正的 external 直签、零 GUI、零 OCR。
- **短板**：内置模型只有 MiniMax 自家，跨厂商覆盖要靠 BYOK 自备 Key；**电脑操控是插件形态**，本会话未启用、未实测，不能当已验证能力上报；活动期额度会临时翻倍、服务端字段语义曾悄悄变更（`bonus_points`），规则稳定性不如写死在文档里的产品；M Plan 订阅额度**不结转**，高强度用完就是等 5 小时/周窗口刷新；音频输入与视频生成的实际可用性受 M Plan 档位约束（Go 档无视频）。
- **给横向对比的提示**：
  1. **本产品的「额度」有两套，别混算**：免费签到积分（400/天、30 天可累积、可攒）vs M Plan 订阅（5 小时 + 周窗口、不结转）。本次自评的 1.1–1.4 只针对**免费签到**那套；若评测口径含付费订阅，需要分列。M Plan 官方只公布相对倍数（1× / 3× / 12× Go），**绝对 token 量未公开**，任何「10M+/天」的说法都需要另行取证。
  2. **3.x 是本项目视角的「可自动化领取」**——MiniMax 给自家签到开了官方 API，属于特例；别的产品未必有这种条件，别把「别人做不到」当成「我更强」。
  3. **2.4 / 2.5 / 2.1 的结论依赖本机配置**（插件是否启用、M Plan 档位、模型是否 BYOK），换机器可能降级，横向对比请以「本机实测」为准。
  4. **本次自评同时修正了本项目对 MiniMax 的错误记录**：
     - `bonus_points` 被当成额外额度重复计账，导致台账多记 5024 —— 已修（`vendor/minimax-auto-signin/signin.py` 改为只取 `points`，并加回归测试 `test_bonus_points.py`）。
     - `catalog.yaml` / README 里「1200/天、第 4/7 天 3000、周期 12000」已按官方口径与客户端类型定义订正为「平时 400、第 4/7 天 1000、周期 4000」。
     - **2026-10-24 接通了服务端真值通道**：`GET /minimax-cloud/api/v1/credit/details`（逐笔剩余 + 到期时间 + 已用额），已配 `credits_command`，MiniMax 在看板上从「本地估算」升为「服务端真值」。对账暴露出本地台账三类额外漂移并一并修掉：**漏记 8 笔早期签到**（08-05..09-17）、**漏记 09-24/09-25 两天实际已签**（本地 streak 因此虚低）、**漏记活动期加成与扣减**（10-05 已用 138、09-07 已用 136）。余额 22624（本地估算）→ **14286**（服务端真值）。
     - 详见 `research/answers/minimax.md` 第八、九节。

---

*自评 ≠ 最终评分。本表由 MiniMax Code 会话自身填写，供主人结合实测横向对比修正。*
