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
    ├── ollama.py
    ├── qoder.py
    ├── lobsterai.py
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
`duration_s: float`（自己计时，不要留 0）、`note: str`（进 ledger，写清模型/耗时/异常）、
`balance_after: int | None`、`raw_tail: str`（失败时留最后 300~400 字符原始输出）。

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
| `3` | 疑似额度/限流（适配器已知该 CLI 的此类返回时使用，便于事后统计） |
| `124` | 超时 |
| `126` | 进程启动失败 |
| `127` | 可执行文件找不到 |
| `64` | 没有可用候选（调度器产出，适配器不会返回） |
| `69` | 预检不可用（调度器产出） |
| `75` | 余额不足被跳过（调度器产出） |

失败时请把原始输出的尾部放进 `raw_tail`，`stderr` 往往是唯一能定位问题的线索。

## 7. ledger：派单事件

每条派单（成功或失败）都会写进 `data/ledger.json` 的 `dispatches[]`：

```json
{
  "id": "f7c98b95a4d5",
  "at": "2026-11-15T10:03:23",
  "provider": "ollama",          // 最终执行者；全失败时是最后一个尝试者
  "capability": "commit",
  "ok": true,
  "duration_s": 33.3,            // 整条链累计耗时
  "exit_code": 0,
  "fallback": false,             // true = 不是第一优先的提供者出的活
  "attempts": ["qoder(fail,0.0s)", "ollama(ok,33.3s)"],
  "balance_before": null,
  "balance_unknown": false,
  "task_digest": "da4f40c69a66", // sha1(任务文本)[:12]，用于去重/关联
  "note": "qwen3:8b-q4_K_M, 9.5 tok/s, 70 tok"
}
```

`credit.py dispatch --history` 按提供者聚合次数/成功/回退/余额未知/累计耗时。
这是回答"到底省了多少额度"的唯一数据源：**适配器不需要自己记账**，
只要如实填 `ok`、`duration_s`、`note` 即可。

## 8. 自检清单（提交前逐条跑）

```powershell
# 1) 试运行：只看候选和预检，不派单、不记账
python credit.py dispatch --dry-run --capability code

# 2) 单独验证你的提供者（强制只用它，不触发回退）
python credit.py dispatch --provider myagent --capability code --task "Reply with OK"

# 3) 验证在链路里的位置与回退行为
python credit.py dispatch --capability code --task "Reply with OK"

# 4) 确认事件已入账
python credit.py dispatch --history --limit 5
```

单独调适配器的等价方式：

```python
from agent_credit.dispatch.registry import build
from agent_credit.dispatch.base import Task

p = next(x for x in build() if x.name == "myagent")
t = Task(text="Reply with OK", capability="code")
print(p.preflight(t))          # 期望 available=True，reason 能说清不可用原因
r = p.dispatch(t)
print(r.ok, r.exit_code, r.duration_s, r.note, r.text[:200])
```

验收标准：

- [ ] `--dry-run` 里能看到你的提供者，且 `priority` 与配置一致；
- [ ] 强制模式下能独立跑通并返回非空 `text`；
- [ ] 运行结束后 `data/ledger.json` 多了一条 `dispatches` 记录，`duration_s > 0`；
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
