# 账本跨进程写锁与 codebuddy 队列派单

> 适用版本：2026-11-15 起。本文覆盖两件事：
> 1. `data/ledger.json` 的跨进程写锁（谁在写、锁住什么、超时与崩溃怎么办）；
> 2. `codebuddy` 的队列通道（任务怎么投递、worker 怎么被拉起、结果与退出码怎么回传、计划任务要什么权限）。
> 相关：`doc/adapter-contract.md`（适配器契约）、`doc/issues/codebuddy-state-dir-write-failure.md`（为什么沙箱内不能直连）。

---

## 1. 账本写锁

### 1.1 为什么需要

`ledger.save()` 原先只有「写临时文件 + 原子替换」：能保证单个文件不半写，但挡不住**丢更新**——
进程 A 读到 `dispatches` 有 10 条，进程 B 此刻追加了 1 条并写回；A 拿着旧快照再写回，B 那条就没了。
会同时写账本的角色至少有三个：前台 `credit dispatch`、每日签到链路、以后可能出现的后台实例。

### 1.2 锁的实现与范围

| 项 | 约定 |
|---|---|
| 锁文件 | `data/ledger.lock`（内容无意义，只作锁载体；随 `AGENT_CREDIT_DATA` 迁移） |
| 原语 | Windows `msvcrt.locking(LK_NBLCK)` / POSIX `fcntl.flock(LOCK_EX)`；非阻塞轮询 50ms |
| 覆盖范围 | `ledger.transaction()`：**持锁 → 重新读盘 → 调用方修改 → 原子写回**，全程互斥 |
| 单写路径 | `ledger.save()` 也持同一把锁，只覆盖「合并 + 写入」这一段，供不方便包事务的调用方使用 |
| 超时 | 默认 **10 秒**，可用 `AGENT_CREDIT_LEDGER_LOCK_WAIT=<秒>` 调整；超时抛 `LedgerLockTimeout`（`OSError` 子类），**不会**在无锁状态下强行写入 |
| 崩溃恢复 | 进程死亡后操作系统立即释放句柄；`ledger.lock` 文件保留但不阻塞后续进程，**不需要人工删锁** |
| 半写保护 | 写入仍是 `ledger.json.tmp` → `os.replace()`，读方要么看到旧文件、要么看到新文件 |
| 合并规则 | `save()` 在锁内按事件 `id` 把盘上多出的 `dispatches` 补回内存快照，再写回。只并 `dispatches`（append-only），不动 `accounts` |

### 1.3 使用方式

```python
# 需要读-改-写全程互斥时（派单记账走这条）
with ledger.transaction() as data:
    ledger.record_dispatch(data, ...)

# 只做一次整体写入时（签到链路的收尾）
ledger.save(data)
```

签到链路单次运行可能持续数分钟（要拉起客户端），不可能全程持锁；它在收尾 `save()` 时靠
1.2 的合并规则补回期间新增的派单事件，所以不会覆盖前台派单。

### 1.4 已验证（2026-11-15 实测）

- **并发不丢写**：4 个进程各用 `transaction()` 追加 60 条，共 240 条 → 盘上 `count=240 unique=240`，无 `.tmp` 残留。
- **等锁超时**：另一进程持锁 4s，`transaction(wait=1.0)` 在 1s 时报 `LedgerLockTimeout`；释放后 `transaction(wait=5)` 立即获得。
- **崩溃恢复**：持锁进程 `os._exit(9)`，下一个进程 `transaction(wait=5)` 立刻拿到锁（OS 已释放），无需清理文件。
- **旧快照回写不丢事件**：进程 A `load()` 后停 2.5s 再 `save()`，期间进程 B 追加 5 条 → 最终仍为 5 条（合并生效）。

---

## 2. codebuddy 队列通道

### 2.1 为什么走队列

派单进程如果运行在受限沙箱里，子进程 codebuddy 写 `%USERPROFILE%\.codebuddy` 会被拒（EPERM），
2~3 秒即退出。目录与 ACL 经用户普通终端六条探针确认正常，见
`doc/issues/codebuddy-state-dir-write-failure.md`。
队列把「投递」和「执行」拆开：前台只写仓库内的文件（沙箱可写），执行交给计划任务拉起、
运行在**当前用户交互会话**里的 worker（非沙箱）。

### 2.2 目录结构

```text
data/codebuddy-taskbox/
  pending/<id>.json    适配器投递，等待认领
  running/<id>.json    worker 已认领，执行中（原子 rename 认领）
  results/<id>.json    worker 写回结果，适配器读走后删除
```

`<id>` = `sha1(任务文本 + uuid4)[:12]`。目录位置可用 `queue_dir` 覆盖，
整棵树随 `AGENT_CREDIT_DATA` 迁移。worker 另可用 `AGENT_CREDIT_CODEBUDDY_BOX` 覆盖。

### 2.3 投递格式（pending）

```json
{
  "id": "5dfebcd5a19c",
  "at": "2026-11-15T18:54:54",
  "capability": "code",
  "text": "Reply with exactly: OK",
  "cwd": "C:\\Users\\M4A1g\\Documents\\Warpeas\\agent-credit",
  "timeout_s": 180,
  "binary": "codebuddy",
  "permission_mode": "bypassPermissions"
}
```

`text` 由 worker 折成单行再传 `-p`（npm shim 会把换行当命令分隔符）。写文件用 `.tmp` + `os.replace`。

### 2.4 结果格式（results）

```json
{
  "id": "5dfebcd5a19c",
  "ok": true,
  "exit_code": 0,
  "text": "OK",
  "note": "exit=0",
  "raw_tail": "",
  "elapsed_s": 6.0,
  "finished_at": "2026-11-15T18:55:01",
  "worker_pid": 2372,
  "usage": {
    "status": "ok",
    "model": "hy4-free",
    "input_tokens": 25345,
    "output_tokens": 35,
    "credits": 0,
    "remaining_percent": 40,
    "reset_at": "2026-11-16T09:46:08+08:00"
  }
}
```

- `ok` 只在「退出码 0 + 有正文 + 无错误」时为 `true`；适配器还会再次校验 `text` 非空。
- `exit_code` 由 worker 归一，写入结果文件——计划任务本身拿不到子进程退出码，**以结果文件为唯一可信回执**。
- `usage` 由 worker 用 `parse_usage_detail` 从 codebuddy 原始 stdout 解析后回传；
  worker 执行失败/超时也要回传 `status=failed` 的字典（字段全 `null` + `error`），
  适配器原样写进账本。字段与状态语义见 `doc/adapter-contract.md` §7.2。
- worker **不写账本**：账本由发起派单的前台进程在 `ledger.transaction()` 里写，避免两个写者（锁能兜底，但没必要）。

### 2.5 退出码与超时

| 场景 | 结果 | 含义 |
|---|---|---|
| 计划任务未注册 / `schtasks /Query` 失败 | 预检不通过，`exit_code=69` | 调度器 0 秒跳过该候选，不会空转 |
| `schtasks /Run` 失败 | `126`，pending 撤单 | 任务没投递成功，明确报「拉不起来」 |
| worker 子进程超时 | `124` | worker 记录超时并写回结果 |
| 子进程启动期写入被拒（EPERM/ENOENT/EACCES） | `126` | worker 的运行环境仍受限，需换环境 |
| 退出码 0 但无正文 | `1` | 与直连口径一致 |
| 适配器等结果超过 `timeout_s` | `124`，按状态收尾 | 见下 |

适配器超时收尾规则：任务还在 `pending` → 删除（撤单）；已在 `running` → 保留（worker 会跑完并写结果，
结果文件若无人读取，由 worker 在 24 小时后清理）；两者都不在 → 报「状态不明」。

### 2.6 触发与串行

- 适配器写 pending 后执行 `schtasks /Run /TN agent-credit-codebuddy`。
- 等待期间每 `retrigger_s`（默认 10s）补触发一次：上一个实例还在跑时 `IgnoreNew` 会忽略启动请求，
  补触发保证排队中的任务在前一个结束后被立刻拉起。
- 轮询间隔 `poll_interval_s`（默认 2s），总等待不超过 `timeout_s`。
- 计划任务设置 `MultipleInstancesPolicy=IgnoreNew`，**一次一单**；worker 每次只认领最老的一单，没有待办立刻退出。
- 认领用 `os.replace(pending → running)`，天然防重复执行。

### 2.7 清理规则

| 对象 | 规则 |
|---|---|
| `pending` | 适配器超时且未被认领 → 当场撤单删除 |
| `running` | 保留（执行中）；超过 24h 的孤儿由 worker 启动时清理 |
| `results` | 适配器读到即删；超过 24h 的孤儿由 worker 清理 |
| `logs/codebuddy-worker.log` | 只追加，每次认领/完成各一行；不自动轮转（体积很小） |

---

## 3. 计划任务：注册、权限、验证

### 3.1 注册

```powershell
cd C:\Users\M4A1g\Documents\Warpeas\agent-credit
powershell -ExecutionPolicy Bypass -File .\scripts\register-codebuddy-task.ps1
```

脚本用 XML 注册（`Register-ScheduledTask -Xml`），关键设置：

| 设置 | 值 | 原因 |
|---|---|---|
| `LogonType` | `InteractiveToken` | 必须跑在当前用户的交互会话里；Session 0 下家目录/凭据/代理都可能不同 |
| `RunLevel` | `LeastPrivilege` | worker 只需要用户自己的权限；不申请提权，也就不弹 UAC |
| `MultipleInstancesPolicy` | `IgnoreNew` | 串行，一次一单 |
| `ExecutionTimeLimit` | `PT30M` | 兜底，防止 worker 卡死占住任务 |
| Triggers | 空 | 纯按需，只由 `schtasks /Run` 触发 |

### 3.2 权限说明

本机（Windows 11，用户 `imini\m4a1g`）**未提权、未弹 UAC** 注册成功，任务状态 `Ready`，
`Logon Mode: Interactive only`，`Run As User: M4A1g`。

如果换一台机器被拒绝（某些组策略会限制普通用户注册任务），处理方式：

1. 用**管理员身份**打开 PowerShell（开始菜单右键 →「终端(管理员)」→ 确认 UAC）；
2. 在其中执行同一条命令：

   ```powershell
   powershell -ExecutionPolicy Bypass -File C:\Users\M4A1g\Documents\Warpeas\agent-credit\scripts\register-codebuddy-task.ps1
   ```

这是唯一可能需要交互的地方。脚本**不会**自行提权，也不会修改安全策略。

### 3.3 验证与注销

```powershell
schtasks /Query /TN agent-credit-codebuddy /FO LIST /V   # Logon Mode / Run As User / Last Result
Get-Content .\logs\codebuddy-worker.log -Tail 5          # 每次认领与完成各一行
powershell -ExecutionPolicy Bypass -File .\scripts\register-codebuddy-task.ps1 -Remove   # 注销
```

`Last Result` 只是旁证（任务启动成功即为 0，与 codebuddy 成败无关）；**codebuddy 的成败只看结果文件**，
也就是账本里的 `exit_code` 与 `ok`。

已知限制：用户注销后任务不会运行（InteractiveToken 的固有约束）；锁屏不影响。

---

## 4. 验收记录（2026-11-15 实测）

第一步（锁）：

```text
4 进程 × 60 条 → count=240 unique=240, tmp_left=False
持锁 4s 时 transaction(wait=1.0) → TIMEOUT 1.00s
释放后 transaction(wait=5) → ACQUIRED 0.00s
持锁进程 os._exit(9) 后 transaction(wait=5) → ACQUIRED 0.01s
stale load(2.5s) + 并发追加 5 条 → 最终 5 条（未丢）
```

第二步（真实派单，非 dry-run）：

```text
> python credit.py dispatch --capability code --task "Reply with exactly: OK" --timeout 180
[ok  ] codebuddy 8.0s taskbox 5dfebcd5a19c, worker 6.0s; exit=0
OK

at         : 2026-11-15T18:55:02
provider   : codebuddy
ok         : True
duration_s : 8.0
exit_code  : 0
fallback   : False
attempts   : {codebuddy(ok,8.0s)}
note       : taskbox 5dfebcd5a19c, worker 6.0s; exit=0
```

worker 日志：

```text
2026-11-15 18:54:55 [pid 2372] 执行 5dfebcd5a19c capability=code timeout=180
2026-11-15 18:55:01 [pid 2372] 完成 5dfebcd5a19c: ok=True exit=0 dur=6.0s
```

任务状态：`Ready`，`Logon Mode: Interactive only`，`Last Result: 0`。

### 4.1 用量结构化回传（2026-11-15 实测）

真实队列派单后，账本事件里的 `usage` 原样如下（非构造样例）：

```json
{
  "id": "b6aa6a9742f0",
  "at": "2026-11-15T19:02:17",
  "dispatch_id": "28859cb49b61",
  "attempt": 1,
  "provider": "codebuddy",
  "ok": true,
  "exit_code": 0,
  "fallback": false,
  "route": "queue",
  "usage": {
    "status": "ok",
    "model": "hy4-free",
    "input_tokens": 25345,
    "output_tokens": 35,
    "credits": 0,
    "remaining_percent": 40,
    "reset_at": "2026-11-16T09:46:08+08:00"
  }
}
```

聚合：

```text
> python credit.py dispatch --usage --since 1d
用量聚合 --since 1d：事件 30 条，legacy 27 条（无 usage 字段，未回填、不计入合计）
提供者        模型            尝试   输入token  输出token  消耗额度  剩余%  重置时间                     失败
codebuddy    hy4-free          1     25345        35          0     40  2026-11-16T09:46:08+08:00     0
loomy        -                 1         0         0          0      -  -                             1
ollama       -                 1         0         0          0      -  -                             1
```

同一次派单回退到两个提供者时，ledger 里是两条事件、共用 `dispatch_id`，
`attempt` 分别为 1/2（loomy 预检失败 → ollama 成功），不会合并累加。

口径说明：`credits` 取 codebuddy `rawUsage.credit`（实际扣费额度，本次模型
`hy4-free` 为 0）；`rawUsage.original_credit`（1.44）是折扣前名义值，
不是实际消耗，未计入。`total_cost_usd` 恒为 0，同样不是额度。

## 5. loomy 任务箱的唤醒源（2026-11-15）

### 5.1 为什么需要额外的唤醒源

Loomy 官方定时任务只有 `daily / weekly / 一次性`（`userData/schedule-tasks.json` 里
`frequency` 只有这几种，UI 表单同样没有分钟级选项），而适配器派单最多等
`--timeout`（默认 600s）。日级兜底与分钟级等待对不上，所以由我们自己补一个触发器。

### 5.2 实现

- `scripts/loomy-wake.py`：读 Loomy 自己生成的
  `C:/Users/Public/Loomy/<实例 hash>/userData/schedule-dispatch-bridge.env`
  （`LOOMY_SCHEDULE_DISPATCH_URL` + `TOKEN`，token **只用于请求头，不写日志、不入仓库**），
  POST `{"taskId": "<已有兜底任务 id>", "source": "manual-run"}`。
- Windows 计划任务 `agent-credit-loomy-wake`：每 5 分钟、当前用户交互令牌、
  真实 `python.exe`（不要用 WindowsApps 的 python 别名）。
- Loomy 侧零改动，`data/codebuddy-taskbox` 与 `data/loomy-taskbox` 保持两个独立箱。

### 5.3 关键坑：`source` 必须是 `manual-run`

`schedule-task-service._resolveScheduleSlotKey()` 只在 `source === 'manual-run'`
（或 `ignoreEnabled === true`）时返回 `null`；其它来源会按
`computeLastDueRunAt()` 把「当天 09:30」当成排程点去领槽。结果是**当天第一次
唤醒成功，之后全部返回 200 但根本不执行**（`schedule-slot-already-claimed`，
HTTP 层看不出来）。2026-11-15 实测：23:18 成功，23:23 与 23:26 的 POST 都是 200，
但任务没跑、心跳没动。

用 `manual-run` 的代价：不参与排程领槽，理论上可能与 09:30 的官方任务撞车；
Loomy 自身 `runningTaskIds` 单飞 + 脚本 120s 冷却把并发挡住，且撞车时最多多跑
一轮空箱。

### 5.4 失败分类、重试与诊断

| 情况 | 状态 | 行为 |
|---|---|---|
| POST 2xx + `queued` | `ok` | 正常；空箱也会跑一轮 worker 并刷新心跳 |
| 距上次成功 < 120s | `skip` | 不 POST，日志写 `skip cooldown Ns` |
| 已有唤醒进程在跑 | `skip` | 锁文件 `data/loomy-wake.lock`，超过 600s 视为陈旧 |
| 连接失败/超时 | `launched` | 8s × 3 次（退避 0/2/5s）→ 回落 `Loomy.exe --scheduled-dispatch <taskId>` |
| 回落也失败 | `failed` | 日志带原因，任务计划器 Last Result=1 |
| HTTP 4xx（token 失效/id 不存在） | `failed` | 不重试，重试无意义 |
| 桥 env 缺失/不完整 | `failed` | 日志写 `bridge_env_missing / incomplete` |

日志：`logs/loomy-wake.log`，一行一条（ok/skip/launched/failed 可区分），超过
512KB 轮转 `.log.1`。状态：`data/loomy-wake-state.json`（`status`、`detail`、
`last_ok_at`、`next_at`），适配器 preflight 读它显示「下次消费约 HH:MM:SS」，
用来区分「真不可用」和「还没到点」。

### 5.5 阈值配套

`providers.yaml` 的 loomy 段：`wake_interval_s: 300`、`heartbeat_max_age_s: 900`
（= 3 倍唤醒间隔）。不要再出现「日级调度配 30 分钟阈值」的组合。

### 5.6 实测

- 空箱：23:33:01 唤醒 → 23:33:27 worker 心跳刷新（`ran=6`），无报错。
- 真单：23:29:32 唤醒 → 23:30:08 入账，`[ok] loomy 90.0s`，产出 `WAKE2`。
- 计划任务：`Last Result=0`，`Next Run Time` 每 5 分钟推进。
