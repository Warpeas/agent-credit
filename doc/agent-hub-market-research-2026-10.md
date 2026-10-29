# 多 Agent 集成管理工具调研（2026-10）

> 调研问题：市面上有没有一个入口，能管理 Qoder、TRAE、WorkBuddy 这类 Agent 软件，知道它们的状态，并在收到指令后做增强、拆解、分派？
>
> 数据口径：GitHub API 快照与公开文档，截至 **2026-10-29**。星数为当日快照；厂商自述能力单独标注，未做逐项实测。
>
> 待核实项：Qoder / TRAE / WorkBuddy 的 CLI 可用范围、套餐限制、是否允许外部程序调用，需以本机版本与官方文档为准。本报告只确认“存在 CLI/文档入口”，未做端到端调用实测。其中 Trae CLI 有资料称仅企业版可用，WorkBuddy CLI 目前主要见社区教程。

---

## 0. 一句话结论

**有相邻品类，但没有完全同款。**

- 最接近“管理一支 Agent 舰队 + 看状态”的是 **Orca**（约 10.9 万星，MIT，桌面 + 移动端 + Computer Use）。
- 最接近“主 Agent 拆解 → 分派 worker → 看板跟踪 → CI 失败回派”的是 **Orchestrator.inc**（约 1.38 万星，Apache-2.0）。
- 最接近“确定性拆解/路由 + 验收 + 可审计”的是 **Bernstein**（约 1.3 千星，beta，50+ CLI adapter）。
- 最接近“一句话 → 自动拆解 → 组队 → DAG 并行”的是 **Agency Orchestrator**（约 2.4 千星，276 个中文角色）。

但它们有一个共同前提：**被管理的 Agent 是 CLI Agent**（Claude Code、Codex、Gemini CLI、Cursor CLI 等）。
**Qoder、TRAE、WorkBuddy 这类以 GUI 为主的桌面 Agent，目前没有任何一款产品原生支持。** 这正是空档。

---

## 1. 先把需求拆成三层

“统一入口”其实是三件事，市面产品通常只强在其中一层：

| 层 | 要解决的问题 | 关键能力 |
|---|---|---|
| **控制面** | 有哪些 Agent、现在什么状态、额度还剩多少 | 注册表、心跳、状态机、生命周期、用量/额度 |
| **编排面** | 这句话到底要做什么、拆给谁、怎么验收 | 指令增强、任务 DAG、能力匹配、成本路由、验收 |
| **执行面** | 怎么真正把任务送进去、把结果拿回来 | CLI / MCP / HTTP API / A2A / GUI 自动化 |

多数“多 Agent 工具”是 **控制面 + 执行面强，编排面弱**；或者反过来。
你的需求三层都要，而且执行面要覆盖 **GUI 桌面软件**，难度最高。

---

## 2. 市场地图

### 2.1 五类玩家

| 类别 | 代表产品 | 管理对象 | 强在哪 | 弱在哪 |
|---|---|---|---|---|
| **编码 Agent 舰队管理器** | Orca、Orchestrator.inc、Conductor、Nimbalyst、Claude Squad、Emdash、Agent of Empires | CLI 编码 Agent | 并行隔离、状态总览、diff 审阅、合并 | 基本只管代码仓库；不覆盖办公 GUI Agent |
| **任务/工作流编排器** | Bernstein、Agency Orchestrator、Claude Code Coordinator、Cursor Projects | 自家运行时或 CLI | 拆解、DAG、角色匹配、验收 | 绑定自家生态；不“管理”外部软件 |
| **企业 Agent 控制平面** | Microsoft Agent 365、agentgateway、UiPath Agent Gateway、Kong AI Gateway、MCP Registry、阿里 MAGIC | 企业内 Agent/MCP | 注册、治理、身份、可观测、合规 | 不做个人任务拆解；重治理轻执行 |
| **个人 Agent 平台** | OpenClaw 2.0、Hermes Agent/Desktop、WorkBuddy、Qoder、TRAE | 自家 Agent | 能操作电脑、有子 Agent/多专家 | 各建各的“统一入口”，互不打通 |
| **观测/用量工具** | AgentsView、Orca 用量追踪、cc-switch | 多 Agent 会话/配置 | 会话检索、成本统计、账号切换 | 只看不管，不执行任务 |

### 2.2 关键产品速览

| 产品 | 形态 | 支持 Agent | 状态跟踪 | 拆解/路由 | 跨 Qoder/TRAE/WorkBuddy |
|---|---|---|---|---|---|
| **Orca** | Win/Mac/Linux 桌面 + iOS/Android + 远程 runtime | 任意 CLI Agent（官方列 20+，含 Claude Code、Codex、Cursor、Kimi、Qwen Code、Hermes 等） | 强：working / waiting / finished、通知、移动端 | 中：Task / Dispatch / Decision Gate；同题多跑，不是语义拆解 | 未原生适配；CLI 可当通用终端接入 |
| **Orchestrator.inc** | Win/Mac/Linux 桌面 + 移动端 | 30+ 编码 Agent | 强：Working / Needs you / In review / Ready to merge | 强：主 Agent 规划 → 每块一个 worker → 失败回派 | 未原生适配 |
| **Bernstein** | CLI/服务，Apache-2.0 | 50+ CLI Agent | 强：事件日志、验收、回放 | 强：plan → roles/signals → 能力路由 → Janitor 验收 | 未原生适配 |
| **Agency Orchestrator** | CLI + Web Studio + 桌面 + Docker | 15 家 LLM（11 家免 key），可把 Claude Code/Gemini/Codex 当 provider | 中：DAG 节点状态 | 强：一句话 → 拆解 → 276 角色匹配 → 并行 | 只能当模型 provider，不管理客户端 |
| **Conductor** | macOS 桌面 | Claude Code、Codex、Cursor | 中强：并行 workspace、状态一览 | 弱：人工按任务指派 | 否 |
| **Nimbalyst（原 Crystal）** | 桌面 + Web | Claude Code、Codex 等 | 中：会话/变更/决策 | 弱到中 | 否 |
| **Claude Squad** | 终端 TUI | Claude Code、Codex、OpenCode、Amp | 中：终端会话 | 弱 | 否 |
| **Vibe Kanban** | 桌面/Web | 10+ 编码 Agent | 强：看板、diff、PR | 弱：人工建卡指派 | 否；**已于 2026-04-10 停止运营**，开源继续 |
| **Microsoft Agent 365** | 企业控制台 | 微软生态 + 第三方 Agent（同步元数据） | 强：注册表、身份、行为、合规 | 弱：不做任务拆解 | 仅治理层；执行靠 Windows 365 for Agents 的 UI 自动化 |
| **OpenClaw 2.0** | 个人 Agent 平台 | 自家 Agent + 子 Agent | 中强：会话、Swarm、移动端 | 中：Swarm 并行子任务 | 能“操作”其他软件，不“管理”其他 Agent |
| **Hermes Agent** | CLI/桌面/消息网关 | 自家 Agent + 子 Agent | 中强：Kanban、会话、内存 | 中强：delegate_task、MOA | 能 computer use，不管理第三方 Agent |

---

## 3. 重点产品拆解

### 3.1 Orca：最像“Agent 舰队控制台”

**事实**
- Stably AI 出品，MIT，仓库 2026-03 创建，约 **108,823 stars**（2026-10-29）。
- 桌面三平台 + iOS/Android + SSH/远程 runtime。
- 核心模型：**一个任务一个 git worktree**，Agent 在隔离目录/分支/终端里跑；同一提示可扇出给 5 个 Agent 对比结果。
- 状态：working / waiting for answer / finished；通知、未读、移动端推送与续聊。
- Orchestration：Message、Task、Dispatch、Decision Gate；支持“Agent 管 Agent”（监控其他 Agent、决定下一步、失败重派、完成触发合并）。
- 额外：Computer Use（操作桌面应用）、内置浏览器/Design Mode、GitHub/Linear、用量与账号切换、Orca CLI（`worktree create` / `snapshot` / `click` / `fill`）。
- 官方适配表里 **没有 Qoder、TRAE、WorkBuddy**；但明确“任何能在终端跑的 CLI Agent 都能跑”。

**判断**
- 这是当前最成熟的“多 Agent 管理 + 状态 + 隔离 + 移动端”成品，且 BYOS（用你自己的订阅），对多订阅用户友好。
- 它的“编排”仍以 **任务/终端** 为单位，不是“把一句模糊需求增强成结构化 DAG 再按能力路由”。同题多跑是它的强项，语义拆解不是。
- 对 Qoder/TRAE/WorkBuddy：如果它们有 CLI，可当通用 CLI Agent 接进去；但 Orca 不认识它们的登录态、额度、审批弹窗，状态语义会退化。

来源：<https://github.com/stablyai/orca>

### 3.2 Orchestrator.inc：最像“拆解 → 分派 → 回派”的成品

**事实**
- Apache-2.0，约 **13,830 stars**；Win/Mac/Linux 桌面 + 移动端；本地优先。
- 你告诉项目主 Agent 要做什么，它 **plan the work**，为每块启动一个 worker，各自独立 worktree/branch。
- 看板泳道：Working / Needs you / In review / Ready to merge；按 Agent、PR、CI、review 自动归位。
- CI 失败、review 评论、合并冲突会 **回派给拥有该分支的 worker**；reviewer agent 可先读 PR。
- 每个任务可选 Agent 与模型；支持 Claude Code、Codex、Cursor、opencode、Aider、Copilot、Grok、Kimi、Pi、Amp、Auggie、Droid 等。

**判断**
- 三条需求里，它最接近“指令拆解 + 分派 + 状态 + 失败回派”的完整闭环。
- 但它是 **代码/PR 中心**：任务单位是分支和 PR，不是“帮我做一份 PPT / 调研 / 发邮件”。
- 没有额度感知路由，也没有 Qoder/TRAE/WorkBuddy 适配。

来源：<https://github.com/OrchestratorInc/agent-orchestrator>

### 3.3 Bernstein：最像“可审计的调度器”

**事实**
- Apache-2.0，约 **1,329 stars**，beta，单人维护。
- 定位：AI Agent 的 **治理层**；policy as code。
- **协调回路里没有 LLM**：用确定性 Python 调度器，plan → roles/signals → 并行 spawn；结果可复现、可回放。
- 50+ CLI adapter（Claude Code、Codex、Gemini CLI 等）；每个 Agent 独立 git worktree。
- “Janitor” 验收：对每个 diff 跑 lint / type check / test，过了才允许合并。
- HMAC 链式事件日志，离线可验证每一步。

**判断**
- 如果你在意“为什么选了这个 Agent、它做了什么、结果凭什么算通过”，Bernstein 的设计最值得抄。
- 但它是 CLI + beta，学习曲线偏工程化；不适合作为普通用户的统一入口。

来源：<https://github.com/sipyourdrink-ltd/bernstein>、<https://bernstein.run>

### 3.4 Agency Orchestrator：最像“指令增强 + 自动组队”

**事实**
- Apache-2.0，约 **2,417 stars**；CLI + Web Studio + 桌面 + Docker。
- 一句话 → AI 拆解任务 → 从 276 个中文角色（+184 英文）中匹配 → 按 DAG 并行 → 输出完整方案。
- 支持验收标准（`acceptance`）、关键步骤人工签字、断点续跑、可分享报告。
- 15 家 LLM provider，11 种免 key 方式；可把本机 Claude Code / Gemini CLI / Codex CLI 当 provider 自动探测。
- 暴露 MCP server，可被其他客户端调用。

**判断**
- 它的“增强 + 拆解 + 角色匹配”是现成参考实现，尤其适合“办公/内容/调研”类任务。
- 但它调度的是 **虚拟角色 + 模型调用**，不是“启动并管理 Qoder/TRAE/WorkBuddy 的会话”。产出偏方案/文档，不负责客户端状态。

来源：<https://github.com/jnmetacode/agency-orchestrator>

### 3.5 其他值得知道的

- **Conductor**：macOS，Claude Code / Codex / Cursor，隔离 workspace，状态一览。生态窄但体验干净。
- **Nimbalyst（原 Crystal）**：Crystal 已改名 Nimbalyst；可视化 workspace + wiki，Claude Code / Codex，偏团队协作与决策记录。
- **Claude Squad**：终端 TUI，管理多个 CLI Agent；轻量，无 GUI。
- **Emdash**：桌面环境，34 个 provider，处理端口/环境。
- **Agent of Empires**：TUI / Web / 移动端管理 Claude Code、OpenCode。
- **Vibe Kanban**：曾经最知名的“看板管 Agent”，2.85 万星；**2026-04-10 停止运营**，代码开源继续。可以读它的设计，但不建议作为长期依赖。
- **AgentsView**：本地优先的多 Agent 会话/成本观测台，适合做“状态与成本”参考。

### 3.6 企业控制平面：Microsoft Agent 365

**事实**
- 2026-05-01 GA；定位 “control plane for AI agents”。
- 能力：组织级 Agent 注册表（含 shadow agents）、生命周期（发布/部署/阻止/删除/审批）、访问控制、行为可观测、Defender/Purview/Entra 安全集成。
- 可把非 Agent 365 管理的外部平台 Agent 与元数据 **同步进注册表**。
- 对没有可靠 API 的桌面/Web 应用，配套 **Windows 365 for Agents** 做 UI 级操作（点击、输入、导航、文件操作），支持人在环。

**判断**
- 它是“管理很多 Agent”的企业级答案，但目标是 **治理与安全**，不是“把一句需求拆给 Qoder/TRAE”。
- 它的“注册表 + 身份 + 可观测 + UI 执行基座”四件套，正好是一个自建 Hub 的参考架构。

来源：<https://learn.microsoft.com/zh-cn/office365/servicedescriptions/microsoft-agent-365/microsoft-agent-365>

### 3.7 协议层：A2A / MCP / agentgateway

- **MCP** 管“Agent 怎么调工具”；**A2A** 管“Agent 之间怎么发现、委派、交换产物”。
- A2A v1.0 于 2026-03 发布，现由 Linux 基金会 AAIF 治理；150+ 组织支持；签名 Agent Card、多协议绑定、多租户。
- **agentgateway** 定位 Agent 数据平面：统一管理 A2A / MCP / LLM 流量，做鉴权、限流、策略、OpenTelemetry。
- **MCP Registry / UiPath Agent Gateway / Kong AI Gateway** 都在做“注册一次，处处可用”。

**判断**
- 如果自建 Hub，对外用 A2A 暴露“我能接任务”，对内用 MCP 管工具；不要发明私有协议。
- 现实是：Qoder/TRAE/WorkBuddy 目前 **不暴露 A2A server**，也不一定暴露可被外部调用的 Agent API。协议层只能作为未来接口，当前仍需 adapter。

### 3.8 厂商原生“协调者”：能力很强，但封闭

- **Claude Code Coordinator**（2026-09-17 beta）：你给目标，Coordinator 界定范围、拆解、派给并行云端线程；每个 worker 是完整 Claude Code 实例，独立分支/仓库副本，共享记忆，完成提 PR。据公开报道，Workflow 并发上限已放宽到 256（厂商口径，未逐项验证）。
- **Cursor Projects**（2026-09-10）：同类“协调者 + 云端 Agent 舰队”。
- **TRAE**（2026-10-09 合并 TraeWork + TraeCode）：一个窗口管理多项目、多 Agent，按任务分配并行推进，实时看进度。
- **Qoder**：Quest 2.0 + 专家团；Computer Use 可后台操作桌面应用、跨应用串联。
- **WorkBuddy**：多 Agent 并行、多模型协同、桌面/小程序/IM 入口，定位“个人 AI 调度中枢”。

**判断**
- 大厂正在把“编排”收进自家入口。第三方中立层的生存空间不在“再造一个更聪明的协调者”，而在 **跨订阅、跨厂商、跨 GUI、额度/成本优化**。

---

## 4. 对照你的三条硬需求

评分 1–5，5 为最接近；主观评估，基于公开资料。

| 产品 | 管理多 Agent | 状态感知 | 指令增强/拆解 | 自动分派 | 原生支持 Qoder/TRAE/WorkBuddy | 综合 |
|---|---:|---:|---:|---:|---:|---:|
| **Orca** | 5 | 5 | 2 | 3 | 1（CLI 可接） | 3.2 |
| **Orchestrator.inc** | 4 | 5 | 4 | 4 | 1 | 3.6 |
| **Bernstein** | 4 | 4 | 4 | 4 | 1 | 3.4 |
| **Agency Orchestrator** | 3 | 3 | 5 | 4 | 1（仅 provider） | 3.2 |
| **Conductor** | 3 | 4 | 1 | 2 | 1 | 2.2 |
| **Vibe Kanban** | 4 | 4 | 1 | 2 | 1 | 2.4（已停运） |
| **Microsoft Agent 365** | 5 | 5 | 1 | 1 | 2（仅元数据） | 2.8 |
| **agent-credit（现有仓库）** | 3 | 4（额度） | 2（关键词） | 2（只推荐） | 5 | 3.2 |

**读法**
- 单看“管 + 看状态”：Orca / Orchestrator.inc / Agent 365 都能打。
- 单看“拆 + 分”：Orchestrator.inc / Bernstein / Agency Orchestrator 都能打。
- 三条同时满足且覆盖 Qoder/TRAE/WorkBuddy：**没有**。
- 你的仓库已经在“注册表 + 额度状态 + 推荐”上占了独特位置，缺的是 **规划器、执行器、运行态**。

---

## 5. 市场空档在哪

1. **跨厂商 GUI Agent 的控制面**
   现有工具假设 Agent 是终端进程；Qoder/TRAE/WorkBuddy 是桌面应用，状态藏在窗口、日志、服务端活动页里。没有标准 API，也没有统一状态模型。

2. **额度/成本感知的 Agent 路由**
   Orca 只追踪 Claude/Codex 用量；多数编排器不关心“这个任务该烧哪家快过期的额度”。对同时持有多家订阅/积分的用户，这是真痛点。

3. **“增强”而不只是“拆解”**
   多数工具把拆解交给主 Agent 或用户；很少显式做“补上下文、补约束、补验收标准、补输出 schema”。而这决定了子任务能不能被验收。

4. **可验收 + 可回滚 + 可交接**
   Bernstein 的 Janitor/审计是方向；多数产品仍停在“跑完给我看 diff”。

5. **本地隐私 + BYOS**
   企业控制平面要上云/上租户；个人用户希望“用我自己的订阅、数据不出本机”。Orca 的 BYOS 是正确方向，但缺中文办公 Agent 适配。

---

## 6. 如果你要做：建议做“薄层”，不要重造

### 6.1 目标架构

```
入口层    CLI / 桌面面板 / IM / MCP client
             │
规划层    Planner：增强 → 结构化任务 DAG → 验收标准
             │
路由层    Router：能力 × 额度 × 成本 × 健康度 × 时延
             │
执行层    Dispatcher：CLI adapter → MCP → A2A → GUI(Computer Use/UIA/OCR)
             │
观测层    Observer：结构化事件 + 进程/窗口/日志探针 + 心跳
             │
验收层    Verifier：确定性检查优先，LLM 复核其次；人工闸门
             │
底座      Registry（Agent Card）/ Run Ledger / Audit / Memory
```

### 6.2 Registry 要描述什么

不要只存“名字 + 余额”，要存 **可调度性**：

| 字段 | 例子 |
|---|---|
| `capabilities` | coding / docs / slides / research / image / local / remote / ecommerce |
| `invoke` | `cli`（命令模板）、`mcp`（server/tool）、`a2a`（endpoint/card）、`ui`（窗口/控件/OCR 锚点） |
| `status_probe` | JSON stream、进程、窗口标题、日志 tail、服务端 usage |
| `quota_source` | 官方 usage API、客户端日志、本地台账 |
| `cost_model` | 按 token / 按积分 / 按次 / 订阅内 |
| `reliability` | 近期成功率、平均时长、失败类型 |
| `constraints` | 需登录、需前台、禁并发、地区限制 |
| `output_schema` | 期望产物格式（diff / 文档 / 表格 / 报告） |

### 6.3 Planner 的输出必须是结构化的

建议直接产出可执行 JSON，而不是一段自然语言计划：

```json
{
  "goal": "给现有项目加一个缓存层并验证",
  "assumptions": ["使用 Redis", "不改公共 API"],
  "subtasks": [
    {
      "id": "t1",
      "title": "分析依赖与调用方",
      "agent_constraints": ["coding", "大上下文"],
      "acceptance": ["列出所有调用点", "给出改动面清单"],
      "depends_on": []
    },
    {
      "id": "t2",
      "title": "实现缓存层",
      "agent_constraints": ["coding", "可写仓库"],
      "acceptance": ["测试通过", "diff 不超过 400 行"],
      "depends_on": ["t1"]
    },
    {
      "id": "t3",
      "title": "独立复核",
      "agent_constraints": ["coding", "不同厂商"],
      "acceptance": ["无 P0/P1 问题", "给出复核报告"],
      "depends_on": ["t2"]
    }
  ],
  "verification": ["单测", "lint", "人工确认公共 API 未变"],
  "approval_points": ["t2 合并前"]
}
```

### 6.4 路由打分（可解释）

```
score = capability_match × quota_available × cost_weight × reliability × latency_weight
```

- 先过硬约束：能不能做、有没有权限、是否禁并发、是否必须前台。
- 再排序：优先烧“快过期/当日清零”的额度（你已有的 `priority.py` 就是这个口径）。
- 输出必须带 **选择理由** 和 **备选**，否则用户不敢信。

### 6.5 状态模型（统一）

`idle → queued → running → waiting_input → waiting_approval → blocked → done / failed / cancelled`

- 首选 **CLI 结构化流**：Qoder `--output-format stream-json`、Trae `exec --json`。
- 次选 **进程/窗口/日志探针**。
- 最后 **GUI 截图 + OCR/UIA**；只做兜底，且必须有人工接管。
- 每个 run 落一份 `run.json`：任务、Agent、开始/结束、事件、产物、验收、成本。

### 6.6 可以直接复用你仓库里的东西

| 现有模块 | 在 Hub 里的角色 |
|---|---|
| `catalog.yaml` | Agent Registry 的雏形；补 `invoke` / `status_probe` / `output_schema` |
| `recommend.py` 的 `detect_caps` | Router 的能力匹配基线；后续换成“规则 + 小模型分类” |
| `priority.py` | 额度优先级唯一口径；直接作为成本路由的 burn order |
| `ledger.py` / `board.py` | 额度账本与看板；扩展为“运行成本 + 余额” |
| `apps.py` / `ui_claim.py` | GUI 兜底 adapter 的起点（窗口锚点、OCR、点击） |
| `trace.py` / `doctor.py` | 运行诊断与可观测性 |
| `cli.py` | 增加 `hub plan` / `hub run` / `hub status` 子命令 |

这说明：**你不需要从零造一个 Orca**。你已经有了“注册表 + 额度 + 推荐 + GUI 自动化”四块，缺的是规划、执行、运行态三块。

### 6.7 MVP 路线

**P0（先证明闭环）**
- `hub plan "任务"`：输出增强后的任务 DAG + 路由理由 + 预估成本，不执行。
- `hub run "任务" --agent qoder`：只接一个 CLI adapter，执行、记录、回放。
- 验收：一个真实任务从指令到产物，全程有 `run.json`。

**P1（多 Agent）**
- 接 Qoder / Trae / WorkBuddy 三个 CLI adapter（没有 CLI 的用 GUI 兜底）。
- 并行 DAG、超时/取消、失败重派、审批收件箱。
- `hub status`：统一状态板 + 额度看板。

**P2（路由与验收）**
- 能力 × 额度 × 成本路由；跨厂商复核（A 做、B 审）。
- 确定性验收（测试/lint/schema/diff 限制）+ 人工闸门。

**P3（协议与入口）**
- Hub 暴露为 MCP server（让别的 Agent 调你）与 A2A server（跨机/跨团队）。
- 移动端/IM 入口、团队共享、审计导出。

### 6.8 不要做什么

- 不要重造 Agent runtime 或模型网关。
- 不要一上来全量 GUI 自动化；CLI 优先，GUI 只做兜底。
- 不要自动合并/自动发布；不可逆动作必须人工确认。
- 不要抓取/代管用户密码；走官方登录态与最小权限。
- 不要把“并行”当默认；并行 = 多份订阅成本，先算账再跑。

---

## 7. 选型建议（Buy vs Build）

### 只想马上用
- **首选 Orca**：跨厂商 CLI Agent、状态、移动端、Computer Use、BYOS，最接近“一个入口看所有 Agent”。
- 需要“任务看板 + PR 闭环”：加 **Orchestrator.inc**。
- 需要“可审计/可复现/验收”：加 **Bernstein**。
- Mac + Claude 系轻量用户：**Conductor** 足够。
- 不建议新项目依赖 **Vibe Kanban**（已停运）。

### 一定要覆盖 Qoder / TRAE / WorkBuddy
- 没有现成货。建议 **自建薄层**，复用 `agent-credit`，把 Orca 作为可选执行/可视化后端。
- 差异化点：跨订阅额度路由、中文办公/编码混合任务、GUI 兜底、本地隐私。
- 先做“规划 + 路由 + 一个 CLI adapter”，不要先做漂亮 UI。

### 企业/团队
- 治理与合规：**Microsoft Agent 365** + **agentgateway** 的思路（注册表、身份、策略、可观测、UI 执行基座）。
- 但员工个人订阅场景不适用；个人版 Hub 更适合本地优先。

---

## 8. 风险与边界

1. **ToS / 封号**：GUI 自动化、代签、多开可能触发风控。仓库 `research/SAFETY.md` 的原则同样适用：只做用户授权动作、控制频率、不碰凭据。
2. **状态不可靠**：GUI 探针会随版本失效；必须有超时、人工接管、失败可见。
3. **成本失控**：并行与重试会烧多份订阅；Router 必须额度感知 + 预算上限。
4. **供应商锁定**：CLI 参数/输出格式会变；adapter 要版本化，配 `doctor` 自检。
5. **Prompt injection**：Agent 产物可能包含恶意指令；跨 Agent 传递前要清洗，执行前要审批。
6. **数据边界**：跨 Agent 共享上下文要最小必要；敏感文件不默认传给所有 Agent。

---

## 9. 结论

- **市场有“多 Agent 管理”，但形态是“编码 CLI 舰队管理”**：Orca 管得最宽，Orchestrator.inc 分得最顺，Bernstein 验得最严。
- **“指令增强 + 拆解 + 按能力/额度分派 + 管理 GUI Agent”这个组合，目前没有成品**。
- 大厂正在把编排收进自家入口（Claude Code Coordinator、Cursor Projects、TRAE 多 Agent、Qoder 专家团），第三方中立层的窗口在 **跨厂商、跨订阅、额度优化、本地隐私**。
- 对你的仓库：这是一次从“积分台账”升级为“Agent Hub”的自然延伸；建议先做 `plan` 与 `run` 两个命令，用真实任务验证，再补状态与验收。

---

## 参考

- Orca：<https://github.com/stablyai/orca> ｜ <https://onorca.dev>
- Orchestrator.inc：<https://github.com/OrchestratorInc/agent-orchestrator> ｜ <https://docs.orchestrator.inc>
- Bernstein：<https://github.com/sipyourdrink-ltd/bernstein> ｜ <https://bernstein.run>
- Agency Orchestrator：<https://github.com/jnmetacode/agency-orchestrator>
- Vibe Kanban（停运公告）：<https://www.vibekanban.com/blog/shutdown> ｜ <https://github.com/BloopAI/vibe-kanban>
- Conductor：<https://conductor.build>
- Nimbalyst：<https://nimbalyst.com>
- Claude Squad：<https://github.com/smtg-ai/claude-squad>
- Microsoft Agent 365：<https://learn.microsoft.com/zh-cn/office365/servicedescriptions/microsoft-agent-365/microsoft-agent-365>
- Windows 365 for Agents：<https://learn.microsoft.com/zh-cn/windows-365/agents/w365a-availability-a365>
- A2A 协议：<https://a2aprotocol.ai/>
- agentgateway / MCP Registry 报道：<https://www.infoq.cn/article/GxD2kl30FpwrMywK5dMj>
- Qoder CLI：<https://www.alibabacloud.com/help/zh/lingma/qodercli-cn/user-guide/using-the-cli>
- Qoder Computer Use：<https://docs.qoder.com/user-guide/chat/computer-use-agent>
- TRAE CLI：<https://docs.trae.cn/cli_command-line-parameters>
- TRAE 多项目/多 Agent：<https://www.trae.cn/>
- WorkBuddy CLI/MCP 教程：<https://blog.csdn.net/weixin_42701915/article/details/166025309>
- OpenClaw 2.0：<https://news.qq.com/rain/a/20260831A0B4SI00>
- Hermes Agent：<https://github.com/NousResearch/hermes-agent>
- AgentsView：<https://m.toutiao.com/article/7651102806912385563/>
- 9 Open-Source Agent Orchestrators：<https://www.augmentcode.com/tools/open-source-agent-orchestrators>
