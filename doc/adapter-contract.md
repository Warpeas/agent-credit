# 派单适配器接入契约

> 面向"要被调用的那个 agent"（也面向给它们写适配器的人）。
> 目标：在**不改调度器代码**的前提下接入一个新提供者。

## 1. 一句话模型

`credit.py dispatch` 把一段任务文本交给本机某个 agent 执行，单机串行，
按 `providers.yaml` 的优先级依次尝试，失败自动回退到下一个。

```
Task ──► preflight() ──► [余额规则] ──► dispatch() ──► Result
              │                                        │
              └── available=False：跳过，记一条 fail 事件 ┘
```

调度器只认识三样东西：适配器类、能力标签、配置表。它不知道 Ollama、Qoder、
LobsterAI 之间的任何差别。

## 2. 目录与注册

```
agent_credit/dispatch/
├── base.py          # 契约：Task / Preflight / Result / Provider（不要改）
├── registry.py      # 自动发现 + 读 providers.yaml + 按 (priority, name) 排序
├── scheduler.py     # 串行执行、余额规则、失败回退（不要改）
└── adapters/
    ├── _cli_json.py    # 共用解析（正文 / 用量），下划线开头，不注册
    ├── ollama.py       # 本地 Ollama（unbounded）
    ├── qoder.py        # Qoder CN CLI（qoderclicn）
    ├── lobsterai.py    # LobsterAI 本地网关（lobster.cmd）
    ├── codebuddy.py    # 腾讯 CodeBuddy Code CLI（codebuddy / cbc）
    ├── dumate.py       # DuMate 本地 opencode 运行时
    ├── loomy.py        # Loomy 任务箱通道（office / search 独占标签）
    └── <你的名字>.py   # 新增文件即自动注册
```

自动发现规则（`registry.discover()`）：

- 扫描 `adapters/` 下所有不以 `_` 开头的模块；
- 模块里**定义**（`obj.__module__ == 模块名`，import 进来再导出的不算）的
  `Provider` 子类，且类属性 `name` 非空；
- 每个类实例化一次，配置来自 `providers.yaml` 中同名的那一段。

因此接入新提供者 = **新增一个文件 + 在 providers.yaml 加一段同名配置**，
`registry.py`、`scheduler.py`、`cli.py` 都不需要动。

## 3. 接口契约

### 3.1 类属性（能力声明）

| 属性 | 类型 | 必填 | 含义 |
|---|---|---|---|
| `name` | `str` | 是 | 唯一标识，必须与 `providers.yaml` 里的键一致 |
| `capabilities` | `set[str]` | 是 | 能接的任务类型，见 §4 |
| `supports_balance` | `bool` | 否 | 是否**真能**查到剩余额度；默认 `False` |
| `unbounded` | `bool` | 否 | 是否完全不消耗额度（如本地模型），默认 `False` |

`supports_balance = False` **不等于**该提供者被排除：调度器只会打上
`balance_unknown`，照常派单，失败时回退。这就是"余额查不到"的正确降级方式。

### 3.2 方法

```python
from ..base import Preflight, Provider, Result, Task


class MyAgentProvider(Provider):
    name = "myagent"
    capabilities = {"code", "review"}
    supports_balance = False   # 真能查余额时才改成 True

    def preflight(self, task: Task) -> Preflight:
        """派单前自检：可执行文件在不在、登录态、本地服务是否在跑。

        能判定的"不可用"都要在这里说清楚，并写进 reason——
        这条 reason 会原样进 ledger 的 attempts 和 stderr，是排障第一现场。
        """
        return Preflight(available=True, balance_note="可选的补充说明")

    def read_balance(self) -> tuple[int | None, str]:
        """返回 (剩余额度, 说明)。查不到就返回 (None, 原因)，不要猜、不要伪造。"""
        return None, "未接入余额查询"

    def dispatch(self, task: Task) -> Result:
        """真正执行。必须返回 Result，不要抛异常（异常会被捕获但信息会丢）。"""
        return Result(ok=True, exit_code=0, text="模型输出", duration_s=0.0, note="可选备注")
```

### 3.3 数据结构

`Task`（只读使用，请勿修改）：

| 字段 | 类型 | 说明 |
|---|---|---|
| `text` | `str` | 任务正文（prompt） |
| `capability` | `str` | 任务能力标签，用于筛选提供者 |
| `cwd` | `Path \| None` | 需要读写仓库时的工作目录 |
| `timeout_s` | `int` | 建议超时，`subprocess.run(timeout=task.timeout_s)` |
| `meta` | `dict` | 预留扩展位 |

`Preflight`：`available: bool`、`reason: str`、`balance: int | None`、`balance_note: str`。

`Result`：`ok: bool`（唯一判据）、`exit_code: int`、`text: str`（正文，会原样打印到 stdout）、
`duration_s: float`（自己计时，不要留 0）、`note: str`（进 ledger，写清模型/耗时/异常，
拿得到用量时附带一行人读摘要，见 §7.2）、`balance_after: int | None`、
`raw_tail: str`（失败时留最后 300~400 字符原始输出）、
`usage: dict | None`（结构化用量，见 §7.2；拿不到也必须返回 `status=failed` 的字典，
不要留 `None` 或空字典）。

## 4. 能力标签约定

用 `--capability` 选任务类型，标签必须与配置里的 `capabilities` 有交集才会被选中。
现有标签：

| 标签 | 含义 |
|---|---|
| `any` | 声明"什么都能接"（慎用，会让它排到所有候选里） |
| `text` | 通用文本生成/改写 |
| `code` | 读写代码 |
| `code-gen` | 只生成代码片段，不改文件 |
| `review` | 代码审查 |
| `test-gen` | 生成测试 |
| `commit` | 写提交信息 |
| `explain` | 解释代码/报错 |
| `office` | 办公文档批处理（Word/Excel/PPT/PDF 等）；目前仅 loomy 声明 |
| `search` | 资料检索与汇总；目前仅 loomy 声明 |

新增标签时，在本文档补一行即可；调度器不做任何白名单校验。

## 5. 配置（`providers.yaml`）

```yaml
providers:
  myagent:
    enabled: true          # false = 完全跳过，用于临时停用
    priority: 40           # 越小越先试；同值时按 name 排序
    capabilities:          # 覆盖类里的默认能力声明
      - code
      - review
    # 以下为适配器自己的参数：Provider.__init__ 已把它们放进 self.config
    binary: myagent-cli
    timeout_hint: 300
```

规则：

- `enabled` / `priority` / `capabilities` / `supports_balance` 由基类统一处理；
- 其余键是适配器的自由配置，**不要在代码里写死路径、模型名、端口**，一律从
  `self.config.get(...)` 取，并给一个合理默认值；
- 用 `AGENT_CREDIT_PROVIDERS=<path>` 可临时指向另一份配置做实验，不必改仓库文件。

## 6. 返回码约定（写进 `Result.exit_code`）

| 码 | 含义 |
|---|---|
| `0` | 成功（且 `ok=True`） |
| `1` | 适配器判定失败（跑完了但没有正文 / 协议不符），可继续回退 |
| `3` | 疑似额度/限流（适配器已知该 CLI 的此类返回时使用，便于事后统计） |
| `124` | 超时 |
| `126` | 进程启动失败（含登录态被拒，如 dumate 对 401/403 归到这里） |
| `127` | 可执行文件找不到 |
| `64` | 没有可用候选（调度器产出，适配器不会返回） |
| `69` | 预检不可用（调度器产出）；ollama 在派单期间本地服务不可达时也用这个码 |
| `75` | 余额不足被跳过（调度器产出） |
| `-1` | 适配器抛异常，调度器兜底记 `Result(ok=False, exit_code=-1)` |

上表之外，适配器也会透传被调 CLI / HTTP 的原始返回码（codebuddy 在退出码非 0 时透传，
退出码 0 但判定失败时归一到 `126`/`1`，判定依据见 §10.3；ollama 透传 HTTP 状态码，
如 404/500）；统计时按上表理解语义，原始码看 `note` / `raw_tail`。

反过来，被调 CLI 的码与上表同名不同义时要归一到契约码，原始码留 `note`：
lobster.cmd 的 `3`（环境缺失）记 `126`、`64`（参数错误）记 `1`、`2`（路由被拒）记 `1`。

失败时请把原始输出的尾部放进 `raw_tail`，`stderr` 往往是唯一能定位问题的线索。

## 7. ledger：派单事件与用量

### 7.1 事件粒度与字段

**一次尝试一条事件**。一次派单回退到多个提供者时，每次尝试各写一条，共用同一个
`dispatch_id`，`attempt` 从 1 递增；不做重复累加。示例：

```json
{
  "id": "b6aa6a9742f0",
  "at": "2026-11-15T19:02:17",
  "dispatch_id": "28859cb49b61",  // 同一次派单的所有尝试共用
  "attempt": 1,                   // 本次派单内的尝试序号，1 基
  "provider": "codebuddy",
  "capability": "code",
  "ok": true,
  "duration_s": 8.0,              // 本次尝试耗时（不是整条链累计）
  "exit_code": 0,
  "fallback": false,              // true = 成功的那次不是第一优先的提供者
  "attempts": ["codebuddy(ok,8.0s)"], // 本次尝试的单条摘要
  "balance_before": null,
  "balance_unknown": true,
  "task_digest": "bdbddd6634bb",  // sha1(任务文本)[:12]，用于去重/关联
  "note": "taskbox f5ba737bdaec, worker 6.0s; exit=0; usage=ok, model=hy4-free, ...",
  "route": "direct",              // direct / queue / direct->queue，见 7.1.1
  "usage": { "...见 7.2..." }
}
```

`note` 只留人读摘要（允许截断到 400 字符），机器可读的数字一律以 `usage` 为准。

#### 7.1.1 `route`：这一单实际走的通道

| 值 | 含义 |
|---|---|
| `direct` | 直连执行（成功或失败都算）；codebuddy 会注入 `CODEBUDDY_CONFIG_DIR` |
| `queue` | 配置为只走队列，或直连不可用且自动选择了队列 |
| `direct->queue` | 直连不可用/失败后，本单回落到队列；`note` 开头保留直连失败原因 |
| `taskbox` | 走本机任务箱 + worker（loomy）；`note` 里带任务箱 id 与 worker 耗时 |

`route` 是账本里判断"这一单到底走哪条路"的第一字段，不要只看 `duration_s`。

### 7.2 `usage` 对象

```json
{
  "status": "ok",
  "model": "hy4-free",
  "input_tokens": 25345,
  "output_tokens": 35,
  "credits": 0,
  "remaining_percent": 40,
  "reset_at": "2026-11-16T09:46:08+08:00",
  "error": "仅 status=failed 时出现"
}
```

| 字段 | 类型 | 口径 |
|---|---|---|
| `status` | `"ok" \| "partial" \| "failed"` | 见下方状态语义 |
| `model` | `str \| None` | 实际执行模型；取 CLI 的 `providerData.model`，没有则退回 `quota.model` |
| `input_tokens` | `int \| None` | 输入 token；codebuddy 优先取 result 项的 `usage.input_tokens` |
| `output_tokens` | `int \| None` | 输出 token；同上 |
| `credits` | `number \| None` | 本事件消耗额度；codebuddy 取各次模型调用 `rawUsage.credit` 之和 |
| `remaining_percent` | `number \| None` | 最近一次剩余百分比；codebuddy 取 `rawUsage.quota.percent` |
| `reset_at` | `str \| None` | 最近一次重置时间；epoch 秒转换为本地 ISO 8601，非数字原样保留 |
| `error` | `str` | 仅 `failed` 出现，写清没拿到用量的原因 |

状态语义（**不允许留空或吞掉**）：

- `ok`：五个数值字段全部拿到（值为 0 也算拿到）；
- `partial`：至少拿到一项，但有缺项；缺项一律 `null`，**不补 0、不估算**；
- `failed`：没有可识别的 usage/rawUsage，或 stdout 不是 JSON。必须带 `error` 说明原因。
  没执行到 CLI 的尝试（预检失败、余额不足、队列投递失败、超时）也记 `failed`，
  `error` 以「未执行：」「超时」开头。

适配器未实现用量采集时，调度器会兜底写
`{"status":"failed", ..., "error":"适配器未回传 usage（<provider> 未实现用量采集或未执行）"}`。
`note` 里可以带一行 `usage=...` 摘要，但不要把人读摘要当数据源。

codebuddy 的实测口径（2026-11-15，2.184.0）：`--output-format json` 输出消息数组，
最后一项 `type=result` 的 `usage` 有 input/output token；assistant 消息的
`providerData.rawUsage` 才有 `credit`、`quota.percent`、`quota.reset_at`；
`total_cost_usd` 恒为 0，不是消耗额度。解析在 `adapters/_cli_json.parse_usage_detail`。

**hy4free 的用量特征（2026-11-15 实测）**：每次调用约 2.4 万输入 token
（简单文本 25345；带读写工具的任务 76033），大头是 codebuddy 自己注入的
记忆/系统说明，不是任务文本；`credit` 恒为 0。判断余量只能看
`quota.percent`：当前 41，`reset_at` 在次日早上（本次 2026-11-16T09:46:08+08:00）。
不要把 `input_tokens` 当任务规模，也不要拿 `credit` 判断是否还有额度。

### 7.3 聚合查询

```powershell
python credit.py dispatch --usage                 # 全部事件
python credit.py dispatch --usage --since 7d      # 最近 7 天
python credit.py dispatch --usage --since 24h
python credit.py dispatch --usage --since 2026-11-01
python credit.py dispatch --usage --since 7d --json
```

按 `provider + model` 分组，输出：

- 输入/输出 token 合计；
- 消耗额度合计（`credits`）；
- 最近一次非空的剩余百分比与重置时间（按事件 `at` 取最新）；
- 解析失败条数（`usage.status == "failed"`）；
- `legacy` 条数：`--since` 范围内**没有 `usage` 字段**的旧事件。legacy 不回填、
  不参与求和，只在汇总行报数。

`--usage` 只读账本，不触发派单，也不要求 `--capability/--task`。

`credit.py dispatch --history` 仍按提供者聚合事件数/成功/回退/余额未知/累计耗时；
事件粒度改为「每次尝试一条」后，这里的次数即尝试次数。

**适配器不需要自己记账**：只要如实填 `ok`、`duration_s`、`usage`（`note` 给人看），
账本由派单进程在锁内统一写入。

## 8. 自检清单（提交前逐条跑）

```powershell
# 1) 试运行：只看候选和预检，不派单、不记账
python credit.py dispatch --dry-run --capability code

# 2) 单独验证一个提供者（强制只用它，不触发回退）；ollama 本地免费，先用它跑通链路
python credit.py dispatch --provider ollama --capability commit --task "Reply with OK"

# 3) 验证在链路里的位置与回退行为（commit 链第一优先是 ollama）
python credit.py dispatch --capability commit --task "Reply with OK"

# 4) 确认事件已入账
python credit.py dispatch --history --limit 5
```

接入自己的提供者时，把上面的 `ollama` 换成你的 `name`、把 `commit` 换成它声明的标签。

单独调适配器的等价方式：

```python
from agent_credit.dispatch.registry import build
from agent_credit.dispatch.base import Task

p = next(x for x in build() if x.name == "ollama")   # 换成你的 name
t = Task(text="Reply with OK", capability="commit")   # 换成它声明的标签
print(p.preflight(t))          # 期望 available=True，reason 能说清不可用原因
r = p.dispatch(t)
print(r.ok, r.exit_code, r.duration_s, r.note, r.text[:200])
```

验收标准：

- [ ] `--dry-run` 里能看到你的提供者，且 `priority` 与配置一致；
- [ ] 强制模式下能独立跑通并返回非空 `text`；
- [ ] 运行结束后 `data/ledger.json` 多了一条 `dispatches` 记录，`duration_s > 0`；
- [ ] 能拿到用量时，那条事件的 `note` 里带 token / 轮次（拿不到就允许为空）；
- [ ] 把二进制/端口故意改错后，`preflight` 返回 `available=False` 且 `reason` 可读，
      链路能回退到下一个提供者而不是崩掉；
- [ ] 未实现余额查询时，`supports_balance = False`，且**没有**因此让该提供者被排除。

## 9. 硬约束

1. **不碰别人的凭据与配置目录**：只走官方 CLI/网关自身的非交互入口；不读取、
   不复制、不修改其它 agent 的账号凭据或配置文件。
2. **不绕过鉴权**：登录态缺失时就在 `preflight` 里如实报告"未登录 + 怎么登录"，
   不要伪造 token、不要复用别人的会话。
3. **不猜余额**：查不到就 `(None, 原因)`，让调度器降级；不要用"上次看到的值"冒充。
4. **不吞错误**：`Result.ok` 只在真有正文时为 `True`；异常写进 `note` / `raw_tail`。
5. **不改调度器**：需要新行为就先改本文档和 `base.py` 的契约，再让所有适配器跟上；
   禁止在 `scheduler.py` 里写 `if provider.name == "xxx"` 这种分支。

## 10. 已知坑（2026-11-15 实测，接新适配器前先读）

### 10.1 npm 的 `.cmd` shim 会把参数里的换行当命令分隔符

Windows 上 npm 全局安装的 CLI 是 `xxx.cmd` shim。带换行的参数交给 shim 后，
cmd.exe 会把换行当成命令分隔，多行 prompt 只有第一行被送进去，后面的内容被当作
另一条命令。现象是模型只看到第一段任务，反问"接下来做什么"，而退出码仍是 0——
只看返回码会当成成功。

对策：`codebuddy.py` 在拼命令行之前把 prompt 折成单行
（`" ".join(task.text.splitlines())`）。如果换行本身有语义（代码块、清单），
不要这么折，改用文件或 stdin 传全文。

### 10.2 headless 派单必须 `--permission-mode bypassPermissions`

codebuddy 在 `--permission-mode acceptEdits` 下只自动批准读改文件；Bash、pytest 这类
要人工授权的动作没人点，它只回一句"需要授权 / 接下来做什么"就正常退出。
调度器按"有正文 + 退出码 0"判定，于是这句话会被当成成功：`Result.ok=True`，
ledger 里也是一条成功事件，实际活没干。

所以 headless 必须用 `--permission-mode bypassPermissions`：`providers.yaml` 的
codebuddy 段已这样配，`codebuddy.py` 的缺省值也是它。其它 CLI（例如 qoder 现有配置
仍是 `accept_edits`）还没做同样验证，接入前自己确认，不要假定行为一致。

### 10.3 codebuddy 的快速失败：exit 0 不代表成功

codebuddy 启动时要写 `~/.codebuddy/projects/<cwd-slug>/*.jsonl` 和 `traces/`。
沙箱或 ACL 不允许写时，它 **2~3 秒就退出，退出码仍是 0**，错误可能落在 stderr，
也可能写进 JSON 的 `is_error` / `errors`（实测：`ENOENT ...projects...jsonl`、
`EPERM mkdir ...projects...`）。只看返回码会把它当成功，回退链停在这一步空转。

`codebuddy.py` 的判定顺序（命中任一即 `ok=False`，不重试，调度器立刻试下一个候选）：

1. 退出码非 0；
2. JSON `is_error=true` 或 `subtype=error*`；
3. 退出码 0，但 stderr 或解析出的错误命中 `enoent` / `eperm` / `eacces` /
   `authentication required` / `please use /login` → 失败，正文清空；
4. 退出码 0 但没有正文。

1/2/3 的 `exit_code` 归一到 `126`（启动失败），4 归一到 `1`；原始退出码写进
`note`。正文里出现 ENOENT/EPERM 不算失败——那是任务本身在讨论报错，
所以只扫 stderr 和解析出的错误，不扫正文。

**直连优先（`transport: auto`，2026-11-15 起默认）**：适配器给子进程注入
`CODEBUDDY_CONFIG_DIR`（默认 `<repo>/data/codebuddy-home`，可用 `config_dir` 覆盖），
把 CLI 的 traces/projects/sessions/logs/plugins 全部移出 `%USERPROFILE%\.codebuddy`。
官方文档在安装包内：`dist/web-ui/docs/cn/cli/env-vars.md`（`CODEBUDDY_CONFIG_DIR`
自定义配置与数据目录）与 `installation.md`（默认目录、目录结构）。可执行文件先用
`shutil.which` 解析成完整路径，不裸写 `codebuddy`（Python 子进程里裸名会
`WinError 2`）。

**settings 是否需要显式补**：实测空 `CODEBUDDY_CONFIG_DIR` +
`--permission-mode bypassPermissions` 下，纯文本、读文件、写文件三类任务都成功，
`permission_denials` 为空；`~/.codebuddy/settings.json` 里只有 `enabledPlugins` /
`trustedDirectories`，都不是派单必需项。因此默认不复制、不加载用户 settings，
避免把 MCP/skills/hooks 一起带进来。确实依赖 settings 的机器可在 providers.yaml 配
`settings: <文件或 JSON 串>`，适配器会原样追加 `--settings`。直连不加载用户级
skills/MCP/memory；需要它们的任务应走队列（用户会话里仍读 `~/.codebuddy`）。

**沙箱冷却**：错误路径落在当前用户家目录、且命中 EPERM/EACCES/ENOENT 时，写
`data/codebuddy_health.json` 记 `blocked_until`（默认 300 秒）和当时的 `config_dir`。
冷却只对同一 `config_dir` 生效——换成新的可写目录后旧冷却自动作废，不会出现
"直连已经能用了还被冷却挡住"。直连成功即清除冷却。

**自动回落队列**：`transport: auto` 下，直连返回 `126`（启动/写盘失败）或 `127`
（找不到可执行文件）时，自动把同一任务投队列；`124` 超时不回落（进程可能仍在
执行，重投会重复干活）。回落时账本 `route=direct->queue`，`note` 开头保留
"直连失败(exit=126)，已回落队列: ..."；队列也失败则保留队列结果与两边的失败原因。
冷却期内同样直接走队列，`route=direct->queue`。配置为 `transport: queue` 时
`route=queue`，队列路径仍读用户家目录配置（用户会话内可用）。

**登录态不在 `CODEBUDDY_CONFIG_DIR` 里**：凭据在
`%LOCALAPPDATA%\CodeBuddyExtension\Data\Public\auth\Tencent-Cloud.coding-copilot.info`
（桌面版与 CLI 共用），与配置目录无关，所以换目录后直连仍然带登录态，不需要迁移或重登。
该目录下的 `.lock` 写入仍会被沙箱拒（日志里 `EPERM ... auth\...workbuddy.lock`），
CLI 按 `kind=transient` 重试后继续，不影响结果——这是目前唯一残留的写盘拒绝，属非致命。

**一次直连的实际耗时（2026-11-15，固定目录第二次起）**：整单墙钟约 `9.2s`，
其中 CLI 自报 `duration_ms` 仅 `3.1~3.6s`（模型往返），其余是启动与收尾：

| 阶段 | 耗时 | 说明 |
|---|---|---|
| 远程产品配置拉取 | ~3.5s | 与鉴权刷新并行，是 pre-model 阶段的主要等待 |
| shell snapshot | ~1.3s | 起 `git-bash` 导环境 |
| 插件市场加载 | ~0.65s | 从本地目录读，**不联网重拉** |
| git 仓库扫描 | ~0.6s | 生成 git 上下文 |
| 收尾等待 | ~0.5s | `PrintBackgroundWait` |

所以"重拉插件市场约十秒"不是常规成本：固定目录避免的是**每次新建临时目录都当首次
安装**，常规单次仍是 ~9s，其中 3~4s 是 codebuddy 自己的远程配置/鉴权刷新，适配器
这层能优化的空间只有几十毫秒（解析、探针写入），不值得再动。

**队列通道**：任务投到 `data/codebuddy-taskbox/pending`，由计划任务在当前用户会话
拉起 `scripts/codebuddy-worker.py` 执行，结果从 `results` 取回；`preflight` 用
`schtasks /Query` 确认任务已注册，未注册则 `available=False`。退出码沿用上表口径
（预检 69、拉起失败 126、超时 124）。完整协议、清理规则与任务注册权限见
`doc/ledger-lock-and-scheduled-dispatch.md`。

---

## 11. 派单主题：持久化指令的落点（2026-11-16）

### 11.1 先澄清一件事

"持久化"不等于"不占上下文"。任何指令最终都要被模型读进 prompt，token 一分不少；
真正的收益是**只维护一份、改一处全生效、人不用每次在 `--task` 里手写同样的约束**。
所以判断标准不是"省 token"，而是"谁写、写在哪、换仓库/换机器会不会串味"。

### 11.2 各 provider 的持久化能力（实测出处）

| provider | 项目级指令 | 全局/用户级指令 | 会话续接 | 独立系统提示 | 换仓库 / 换机器 / 多实例 |
|---|---|---|---|---|---|
| codebuddy | `./CODEBUDDY.md`、`./.codebuddy/CODEBUDDY.md`、`.codebuddy/rules/*.md`；向上递归到文件系统根 | `~/.codebuddy/CODEBUDDY.md` + `~/.codebuddy/rules/*.md`；本仓库用 `CODEBUDDY_CONFIG_DIR=data/codebuddy-home` 隔离 | `-c` / `--resume` / `--session-id` | `--system-prompt`、`--system-prompt-file`、`--append-system-prompt` | 项目级随仓库走；用户级在 config dir，跨仓库共享、不跨机器（换机器即空） |
| qoder | `AGENTS.md`（项目记忆目录）；bundle 里 `getProjectMemoryDir()` | 全局 config dir 下的 `AGENTS.md` | `-c` / `-r` / `--session-id` | `--system-prompt`、`--append-system-prompt` | 用户级会污染用户自己的交互会话，**未找到可靠的 config-dir 隔离开关**（bundle 里 `${QODER_CONFIG_DIR}` 只用于技能/钩子路径模板） |
| dumate | 项目 `AGENTS.md`（opencode 运行时按 `x-opencode-directory` 读） | `XDG_CONFIG_HOME` 指向 DuMate 真实配置根，写全局会污染 DuMate 本体 | 运行时内部有 session，适配器每次新建 | 未找到稳定入口（HTTP 提交 message 无 system 字段） | 多账号各有一份 config（适配器按 mtime 取最新一份） |
| loomy | 项目 `AGENTS.md`（payload `cwd`） | `opencode/skills/**`（我们的 `loomy-taskbox-worker` 就是持久机制）；`.runtime-instructions/loomy-runtime-guidance.md` 由 Loomy 模板同步，**手改会被覆盖** | Loomy 自己的会话 | 未找到稳定入口 | 实例 hash 目录（`C:/Users/Public/Loomy/<hash>/`）随版本可能变，安装脚本用 glob |
| ollama | 无 | 无（Modelfile 的 `SYSTEM` 绑定模型，全任务共享，会串味，不推荐） | 无 | `/api/generate` 的 `system` 字段（每次请求） | 无持久态 |
| lobsterai | 无 | 无 | `--session-key lobster:<Caller>`（服务端会话，常驻会累积历史） | 无（只有 `-Prompt`） | caller 相同即共用会话，跨任务串味 |

### 11.3 本仓库的实现（最小一步）

- 唯一来源：`instructions/dispatch-theme.md`（约 640 字符）。改它 = 改所有后续派单。
- 注入方式一律用各家**原生**参数，不发明中间层：
  - codebuddy：`--append-system-prompt`，直连与队列两条路都带（队列走 `payload.append_system_prompt`，由 `scripts/codebuddy-worker.py` 追加同一参数）；
  - qoder：`--append-system-prompt`（无隔离配置目录，只能每次带）；
  - ollama：`/api/generate` 的 `system` 字段。
- codebuddy / qoder 的可执行文件是 npm shim，参数里的换行会被截断（见 10.1），
  所以这两家把主题折叠成单行（`theme_oneliner()`）；ollama 走 JSON，保留多行。
- 关闭 / 覆盖：`providers.yaml` 里给某个 provider 写 `theme: <路径>` 覆盖，
  `theme: off` 关闭；临时验证用环境变量 `AGENT_CREDIT_THEME=<路径>`（优先级最高）。
- 文件缺失或不可读时返回空串，**不报错、不影响派单**；要退回"每次手写"就 `theme: off`。

### 11.4 风险与处理

| 风险 | 表现 | 处理 |
|---|---|---|
| 串味（一份主题对所有仓库生效） | 在 A 仓库的习惯被带进 B 仓库 | 主题只写跨仓库通用的约束；仓库特有规则放该仓库的 `CODEBUDDY.md` / `AGENTS.md` |
| 向上递归抓到别的仓库的 `CODEBUDDY.md` | 子目录会话继承了上级（甚至工作区外）的指令 | codebuddy 可设 `CODEBUDDY_DISABLE_PARENT_MEMORY=1` 或 `memory.parentDiscovery=false`（官方 memory 文档） |
| 版本漂移 | 主题改了，旧单行为不变、新单立刻变 | 无需缓存失效；账本里按时间能对齐版本。需要可追溯时在主题首行写版本号 |
| 顺手改了 Loomy/ DuMate 的模板文件 | 升级后被覆盖，行为忽变 | 只写自己仓库的文件与正式技能目录，`.runtime-instructions/` 不碰 |
| 主题过长 | 单行参数有长度上限（cmd ~8k） | 控制在 1~2KB；超了拆成仓库级 `AGENTS.md` / `CODEBUDDY.md` |

### 11.5 验证记录（2026-11-16 实测）

用 `data/theme-verify.md`（要求回复以 `THEME-OK:` 开头）经 `AGENT_CREDIT_THEME` 注入：

```text
codebuddy 直连：THEME-OK: PING    28.1s  route=direct
codebuddy 队列：THEME-OK: PINGQ   57.1s（worker 54.2s）route=queue
ollama       ：THEME-OK: PINGO   21.0s  qwen3:8b-q4_K_M, 11.7 tok/s
默认主题长度 636 字符；theme: off 时为 0
```

qoder 只核对了 `--append-system-prompt` 在 `--help` 中存在（未跑真实单，避免无谓消耗额度）。
