# Loomy · Agent 能力自评

| 项 | 值 |
|---|---|
| 模板 | `prompts/agent_self_eval.md` |
| 填写者 | Loomy（当前会话产品自身） |
| 评估日期 | 2026-10-24 |

> 原则：只报本机/本会话能确认的能力；测不到或产品侧未确认的标「未确认」，不按满分估算。

---

产品名：Loomy（桌面客户端 AI Agent）
厂商：科大讯飞
评估日期：2026-10-24

## 额度价值

| 指标 | 自评分(1-5) | 实际情况 | 依据 |
|---|---|---|---|
| 1.1 日额度 | 5 | 每日登录即发 5000 积分（credit），无基础/连签分档，另有永久 6500 托底。按模板口径（5=500+/天）为最高档。 | `catalog.yaml` L474 `daily_amount: 5000`、L482 notes（另有永久 6500）；`README.md` 评级总表讯飞 Loomy 行「5000/天」 |
| 1.2 有效期 | 3 | 每日额度当日清零（`grant_type: daily_expire`），但有永久 6500 托底。按口径「3=当日清零但有永久托底」。 | `catalog.yaml` L473 `grant_type: daily_expire`、L475 `validity_days: 0`、L482 notes |
| 1.3 连签加成 | 2 | 无连签加成、无月度固定赠送（台账无 streak/extra 记录）。但 5000/天额度大，按口径「2=无加成但额度大」。 | `catalog.yaml` L468-L492 Loomy 条目无 streak/加成字段；`README.md` 评级表「连签/额外」列为「无」 |
| 1.4 可消耗性 | 3 | 活跃日用（办公文档批处理、项目开发、数据分析）能持续消耗；但产品被台账定为「用时再开」（`claim_policy: never_auto`、`open_when_needed: true`），不常开的日子 5000 全部白白清零，实际消耗率低。且手机端不同步任务，离开电脑消耗不掉。 | `catalog.yaml` L477/L481（never_auto / open_when_needed）；L484 `mobile_note`（手机端似乎不能同步任务，主人 2026-10-23）；`README.md` 一期范围「不做：定时启动 … Loomy 等当日清零客户端」 |

## 能力覆盖

| 指标 | 自评分(1-5) | 实际情况 | 依据 |
|---|---|---|---|
| 2.1 模型代际 | 4 | 产品侧多模型可切：DeepSeek / MiniMax / 豆包 / 千问 + 讯飞星火 X2.5/X2.6（API Key），端侧星火 X2.5-4B。**注：当前会话模型标识为 auto（自动路由），底层具体型号/代际会话内不可自证，落点由服务端决定，故不按满分计。** | `catalog.yaml` L485 `models_note`（2026-10-22 官网+媒体）；本会话环境信息「powered by imodel/auto」 |
| 2.2 编码能力 | 5 | Agentic 编码闭环完整：读仓库→改多文件→跑脚本→迭代修复。本仓库（agent-credit）的台账系统与 19+ 签到/取证脚本、hitomi 逆向项目的 PyInstaller 字节码手术与 SQLite 瘦身等中型工程均由 Loomy 历史会话独立完成。支持 Python/PowerShell/JS/批处理等多语言与终端链路。 | 本会话工具链（Read/Write/Edit/Bash/Grep/Glob）；本仓库 `credit.py`、`scripts/*.py`、`agent_credit/yaml_lite.py` 等实际产出 |
| 2.3 浏览器操控 | 5 | 具备完整浏览器自动化：打开页面、点击、填表、截图、执行 JS、读取控制台与网络请求、多标签管理，可调试网页。底层为 Playwright（sidebar 用户可见 / managed 后台两种模式）。 | 本会话可用 playwright-browser MCP 全套工具（navigate/click/fill_form/snapshot/screenshot/evaluate/console_messages/network_requests/tabs/wait 等） |
| 2.4 电脑操控 | 3 | 无原生键鼠/窗口管理 MCP，仅 bash（PowerShell）+ 文件工具：文件操作、启动软件、系统脚本、计划任务注册强；键鼠模拟需自写 PowerShell 脚本（SendInput/OCR 路线），且受 UIPI 权限、CEF 内核 UIA 不可达、isTrusted 过滤等系统限制（需提权）。 | 本会话工具清单（无 Computer Use 原生工具）；本仓库 `scripts/elevate_run.py`、`scripts/ocr_image.py`、`scripts/capture_ocr.ps1` 及环境约束记录（AutoClaw 需管理员权限、CEF UIA 不通） |
| 2.5 多模态 | 4 | 输入端可看图（图片附件直接查看 + 识图/OCR 兜底工具）；输出端可文生图、参考图改图、生成音乐。**音频输入、视频生成未确认，故按「图+文多模态输入 + 生图输出」记 4 分。** | 本会话 loomy_image（generate/analyze）、yinshu-music 工具可用 |
| 2.6 移动端同步 | 3 | 有手机客户端，但似乎不能同步任务（主人 2026-10-23 实测）。按口径「3=有移动端但不同步」。另有 IM 远控通道（飞书/企微/微信/钉钉/QQ 可远程派任务、收发文件），部分弥补但非官方同步。 | `catalog.yaml` L483-L484 `mobile: true` / `mobile_note`；本会话 remote-file-sender 远程通道工具 |

## 领取可靠性

| 指标 | 自评分(1-5) | 实际情况 | 依据 |
|---|---|---|---|
| 3.1 领取方式 | 2 | 无「签到」动作——登录即发当日额度，零 GUI 交互；但领取依赖启动客户端，且当日清零策略决定台账 `claim_policy: never_auto`（不自动启动，用时再开）。实际从不自动领取，按口径「2=需手动触发」。 | `catalog.yaml` L477 `claim_policy: never_auto`、L473 `grant_type: daily_expire`；`README.md` 一期范围「不做：定时启动 Loomy」 |
| 3.2 稳定性 | 未确认 | 过去 30 天从未自动领取（never_auto），无成功率数据可报。机制上「启动即到账」无 UI 失败面，理论上启动成功率即到账成功率，但该路径从未被自动化验证，不吹。 | `catalog.yaml` L477-L478（never_auto / claim_mode: never）；`README.md` L217 |
| 3.3 脆弱性 | 4 | 领取机制无 UI 锚点依赖（登录即发，无签到浮窗/按钮可被改版破坏），改版免疫度高；仅依赖登录态有效与客户端可启动，大改版（登录流程变更）才会影响。 | `catalog.yaml` L473/L478（登录即领、无 UI 签到模式）；对比 `README.md` 中 Qoder/Trae 等签到 UI/OCR 路线均依赖锚点 |

## 实际体验

| 指标 | 自评分(1-5) | 实际情况 | 依据 |
|---|---|---|---|
| 4.1 响应速度 | 未确认 | 无法在产品内部可靠测量端到端首 token 延迟；本会话工具调用与输出体感流畅，但不据此打分。 | 无客观测量数据 |
| 4.2 指令遵循 | 4 | 能拆解多步任务并保持目标；复杂指令多数一次到位，涉及产品事实时会区分「已确认/未确认」。偶有需要补充约束的情况。 | 本会话按模板逐项填写、区分证据等级；本仓库长期多轮任务（签到编排、逆向取证、对账修复）交付记录 |
| 4.3 上下文管理 | 4 | 有跨会话长期记忆机制（按需检索，不随会话结束丢失），会话内多轮迭代稳定；单会话上下文窗口大小未确认，超长会话极早期细节可能需回读文件确认。 | 本会话记忆系统可用并已应用（hitomi 项目、agent-credit 环境约束等）；长任务中持续回读仓库文件的习惯 |
| 4.4 工具生态 | 5 | MCP + Skills 双扩展体系齐全：支持挂载/管理第三方 MCP（含浏览器、邮箱、飞书/企微/钉钉 CLI 等）+ 内置 50+ 技能（Word/Excel/PPT/PDF 办公全家桶、深度研究、网页设计、专利写作、图文卡片、逆向工程等）+ IM 远控通道（飞书/企微/微信/QQ/钉钉收发消息与文件）。 | 本会话 loomy_config（mcp_add/mcp_toggle）工具可用；本会话技能清单（lark-* / wecom-unified / dws / office 全套等） |

## 补充说明

- **强项**：办公文档链路完整（Word/Excel/PPT/PDF 技能全覆盖）；IM 远控+远程文件收发（飞书/企微/微信/钉钉/QQ 多通道）；MCP/Skills 双生态可扩展；bash+脚本路线下的桌面取证/逆向能力（PyInstaller 改码、SQLite 取证等均已实际跑通）；Playwright 浏览器自动化可调试。
- **短板**：无原生 Computer Use 工具，键鼠操控走脚本路线且受系统权限/isTrusted 限制，与有原生键鼠 SDK 的产品不可直接等同；当日清零 + 手机端不同步任务 → 额度实际消耗率低，离开电脑就浪费；当前会话模型标识为 auto，具体型号会话内不可自证；音频输入/视频生成未确认。
- **给横向对比的提示**：2.4 的桌面操控是「bash+脚本」路线而非原生键鼠工具，评估时建议与 Qoder 等有原生 Computer Use SDK 的产品区分对待；3.x 三项反映的是「本项目视角下的可自动化性」——Loomy 机制上登录即领、改版免疫，但当日清零决定它被策略性排除在自动领取之外，这是产品机制与项目策略的叠加结果，而非机制脆弱。

---
*自评 ≠ 最终评分。本表由 Loomy 会话自身填写，供主人结合实测横向对比修正。*
