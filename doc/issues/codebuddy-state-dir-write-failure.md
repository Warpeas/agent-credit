# codebuddy CLI 启动写入失败（EPERM / ENOENT）识别说明

> 读者：一个完全没有本仓库上下文的执行 agent（也可以是 codebuddy 自己）。
> 目标：先判断失败发生在"状态目录/归属"还是"调用方的文件系统限制"，然后**如实报告**。
> **本机已判定为后者**：用户在普通终端跑 §0 的六条探针全部 OK，目录、归属、ACL 都正常，**没有任何目录需要修**。
> 一句话：headless 启动时写 `%USERPROFILE%\.codebuddy\projects` 或 `traces` 被拒，CLI 以**退出码 0** 结束、stdout 为空，任务实际没有执行。
> 允许的动作只有"识别并明确报告"；**不要修权限、不要建目录、不要绕沙箱**（见 §6）。

---

## 0. 先做判断（30 秒，确认有没有目录要修）

在 **PowerShell 普通终端**（就是你平时手动敲命令的那个窗口，不是任何 agent 的托管 shell）里逐条试写。**这一步只写临时文件并立即删除**，不创建业务数据：

```powershell
$targets = @(
  "C:\Users\M4A1g\Documents\Warpeas\_probe.txt",
  "$env:TEMP\_probe.txt",
  "$env:USERPROFILE\_probe.txt",
  "$env:USERPROFILE\.codebuddy\_probe.txt",
  "$env:USERPROFILE\.codebuddy\projects\_probe.txt",
  "$env:USERPROFILE\.codebuddy\traces\_probe.txt"
)
foreach ($p in $targets) {
  try { Set-Content $p "x" -ErrorAction Stop; "OK   $p"; Remove-Item $p -Force }
  catch { "FAIL $p :: $($_.Exception.Message)" }
}
```

按下表对号入座，不要跳步：

| 结果 | 含义 | 下一步 |
|---|---|---|
| 全部 `OK`（**本机实测就是这种**） | 目录、归属、写入全部正常，**没有目录要修**。若某个 agent 仍报 EPERM/ENOENT，问题在**调用它的那个进程所处环境** | **停止**。不要改任何权限、不要建目录，按 §9 报告"卡在调用方沙箱" |
| 工作区/`%TEMP%` 为 `OK`，但 `%USERPROFILE%` 根和 `.codebuddy` 下全部 `FAIL` | 同上，这是**进程级文件系统限制**（沙箱），不是目录 ACL | **停止**。按 §9 报告，不要修目录 |
| `%USERPROFILE%` 根 `OK`，只有 `.codebuddy` 下 `FAIL` | 理论上才可能是目录层问题 | 也**不要**自己动手修；按 §9 报告这组结果，交由目录的所有者决定 |

2026-11-15 在本机的两次对照：

- 从本仓库的 agent 托管 shell 里跑：第三条路径以后全部 `FAIL`（见 §4.3 左表）。
- 用户在自己的普通 PowerShell 窗口里跑：**六条全部 `OK`**（见 §4.3 右表）。

两者用的是同一台机器、同一个用户、同一批目录。结论因此是确定的：**目录与 ACL 正常，拒绝来自调用方进程所处的沙箱**。所以本机**没有目录要修**。

---

## 1. 现象

- `codebuddy -p ... --output-format json` 启动后立即结束，**退出码 0**，**stdout 为空**，错误只出现在 stderr。
- 上层派单按"退出码 + 是否有正文"判定失败并回退；用户看到的是"任务没执行，换别家跑了"。
- 同一个工作目录的 `projects\<cwd-slug>` 目录下，历史 `.jsonl` 会话文件是存在的，说明这个目录**平时是可写的**，问题不是"目录从来没建过"。
- qoder CLI 也出现同类现象（`~/.qoder\projects` 创建被拒），可作交叉参考。

---

## 2. 报错原文（实测，逐条注明出现在哪一步）

### 2.1 默认启动：会话持久化阶段

命令：`codebuddy -p "Reply with OK" --output-format json --permission-mode bypassPermissions`
结果：`exit=0`，`stdout` 长度 0。

```text
node.exe : EPERM: operation not permitted, open 'C:\Users\M4A1g\.codebuddy\projects\c-Users-M4A1g-Documents-Warpeas-agent-credit\01a1dec6-0f58-7328-9bcc-4c9318067eb9.jsonl'
所在位置 C:\Users\M4A1g\AppData\Roaming\npm\codebuddy.ps1:24 字符: 5
+     & "node$exe"  "$basedir/node_modules/@tencent-ai/codebuddy-code/b ...
+     ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
    + CategoryInfo          : NotSpecified: (EPERM: operatio...18067eb9.jsonl':String) [], RemoteException
    + FullyQualifiedErrorId : NativeCommandError
```

- 出现步骤：CLI 已启动 node，正在写本次会话的 JSONL 记录，**还没进入模型调用**。
- 文件名是每次运行的 UUID，目录是当前工作目录对应的 slug。

### 2.2 加 `--no-session-persistence`：traces 阶段

命令：`codebuddy -p "Reply with OK" --output-format json --permission-mode bypassPermissions --no-session-persistence`
结果：`exit=0`，`stdout` 长度 0。

```text
node.exe : EPERM: operation not permitted, mkdir 'C:\Users\M4A1g\.codebuddy\traces\7248'
所在位置 C:\Users\M4A1g\AppData\Roaming\npm\codebuddy.ps1:24 字符: 5
...
    + FullyQualifiedErrorId : NativeCommandError
```

- 出现步骤：跳过了会话 JSONL，改为创建 `traces\<pid>`，仍然被拒。
- `7248` 是当次进程 PID，每次运行都不同。

### 2.3 工作目录的 slug 目录不存在时：会话持久化阶段

命令同上（默认启动），但工作目录是临时副本 `...\Warpeas\.ac-copy-dispatch`。
结果：`exit=0`，无正文。

```text
ENOENT: no such file or directory, open 'C:\Users\M4A1g\.codebuddy\projects\c-Users-M4A1g-Documents-Warpeas-.ac-copy-dispatch\01a1dde1-66f3-7402-b6bb-6d23bcde7aa5.jsonl'
```

- 出现步骤：CLI 没有为这个新工作目录创建 `projects\<slug>`，直接打开文件失败。
- 注意：这是 `ENOENT`（父目录不存在），和 2.1 的 `EPERM`（有目录但写不了）是两种不同状态，别混为一谈。

### 2.4 qoder 参考

```text
EPERM: operation not permitted, mkdir 'C:\Users\M4A1g\.qoder\projects\C--Users-M4A1g-Documents-Warpeas--ac-copy-dispatch'
```

- 出现步骤：qoder 启动时创建 per-cwd 状态目录。
- 说明两家 CLI 采用同一种"按工作目录建状态目录"的模式，所以问题形态相似；本次识别范围仍以 codebuddy 为主。

### 2.5 改权限模式的对照

命令：`codebuddy -p "Reply with OK" --output-format json --permission-mode acceptEdits`
结果：`exit=0`，`stdout` 长度 0，报错与 2.1 **完全相同**（同样是 projects 下的 JSONL 打开失败）。

> 说明：本次实际见到的只有 `EPERM` 和 `ENOENT`，没有见到 `EACCES`。下文自检里的 `EACCES` 只是同类错误的检查项，不代表本机出现过。

---

## 3. 复现步骤（可直接照抄）

环境：Windows 11 家庭版 中文版 10.0.26300，用户 `imini\m4a1g`，PowerShell 5.1。

```powershell
cd C:\Users\M4A1g\Documents\Warpeas\agent-credit

# 3.1 默认（会话持久化开启）
codebuddy -p "Reply with OK" --output-format json --permission-mode bypassPermissions

# 3.2 跳过会话持久化
codebuddy -p "Reply with OK" --output-format json --permission-mode bypassPermissions --no-session-persistence

# 3.3 只读权限模式（对照）
codebuddy -p "Reply with OK" --output-format json --permission-mode acceptEdits
```

| 用例 | 预期 | 实际（2026-11-15 实测） |
|---|---|---|
| 3.1 | 退出码 0，stdout 是含正文的 JSON | 退出码 0，stdout 为空，stderr `EPERM open ...projects...jsonl` |
| 3.2 | 退出码 0，stdout 是含正文的 JSON | 退出码 0，stdout 为空，stderr `EPERM mkdir ...traces\<pid>` |
| 3.3 | 退出码 0，stdout 是含正文的 JSON | 退出码 0，stdout 为空，stderr 与 3.1 相同 |

注意：`-p` 的 prompt 是单行短句，失败发生在模型调用之前，因此与 prompt 内容、模型选择无关。

---

## 4. 环境事实（2026-11-15 实测，不是推测）

### 4.1 系统与入口

- OS：`Microsoft Windows 11 家庭版 中文版`，版本 `10.0.26300`
- 当前用户：`imini\m4a1g`，家目录 `C:\Users\M4A1g`
- PATH 中的入口是 npm 生成的 shim：
  - `C:\Users\M4A1g\AppData\Roaming\npm\codebuddy.cmd`
  - `C:\Users\M4A1g\AppData\Roaming\npm\codebuddy.ps1`
  - 两者最终都调用 `node_modules/@tencent-ai/codebuddy-code`，所以报错前缀是 `node.exe`
- `codebuddy --version` 正常输出 `2.184.0`，说明二进制/入口本身没坏，失败发生在启动后的状态写入阶段。

### 4.2 目录归属与 ACL

| 目录 | 存在 | Owner | ACL（当前用户） |
|---|---|---|---|
| `C:\Users\M4A1g\.codebuddy` | 是 | `IMINI\M4A1g` | `IMINI\M4A1g:(I)(OI)(CI)(F)` |
| `...\.codebuddy\projects` | 是 | `IMINI\M4A1g` | `IMINI\M4A1g:(I)(OI)(CI)(F)` |
| `...\.codebuddy\traces` | 是 | `IMINI\M4A1g` | `IMINI\M4A1g:(I)(OI)(CI)(F)` |
| `...\projects\c-Users-M4A1g-Documents-Warpeas-agent-credit` | 是 | `IMINI\M4A1g` | `IMINI\M4A1g:(I)(OI)(CI)(F)` |

补充事实：

- 三个目录的 ACE 都是**继承来的 FullControl**（`(I)`），没有 Deny ACE。
- 当前进程完整性级别是 **Medium**（`Mandatory Label\Medium Mandatory Level`）。
- `.codebuddy` 是普通目录，不是 junction/符号链接（`LinkType` 为空，`Target` 为空）。
- 目录里的历史 `.jsonl` 文件属性是 `Archive`，不是只读。

### 4.3 写入探针结果（关键，两组对照）

**A. 从 agent 托管 shell 里跑（派单进程所在环境）**

| 路径 | 结果 |
|---|---|
| `C:\Users\M4A1g\Documents\Warpeas\_probe.txt` | OK |
| `%TEMP%\_probe.txt` | OK |
| `C:\Users\M4A1g\_probe.txt`（家目录根） | 拒绝 |
| `...\.codebuddy\_probe.txt` | 拒绝 |
| `...\.codebuddy\projects\_probe.txt` | 拒绝 |
| `...\.codebuddy\traces\_probe.txt` | 拒绝 |

**B. 用户在自己打开的普通 PowerShell 窗口里跑（同一台机器、同一用户、同一批路径）**

```text
OK   C:\Users\M4A1g\Documents\Warpeas\_probe.txt
OK   C:\Users\M4A1g\AppData\Local\Temp\_probe.txt
OK   C:\Users\M4A1g\_probe.txt
OK   C:\Users\M4A1g\.codebuddy\_probe.txt
OK   C:\Users\M4A1g\.codebuddy\projects\_probe.txt
OK   C:\Users\M4A1g\.codebuddy\traces\_probe.txt
```

六条全部 OK。

结论：

1. **不是 ACL、不是归属、不是只读、不是 junction、不是完整性标签**——这些都查过且正常，用户普通终端也能写。
2. 拒绝是**进程级**的：同一个用户、同一批目录，A 环境写工作区和 `%TEMP%` 可以、写家目录根和 `.codebuddy` 全部不行；B 环境全部可以。
3. 因此真正挡住 codebuddy 的是**调用它的那个进程所处的文件系统限制/沙箱**，而不是目标目录本身。
4. **没有目录要修。** 不要为了"做点什么"去改 ACL、建目录或提权——这些改动不会让 A 环境变好，只会污染一个本来就正常的目录。

> 由此定下的处置口径：识别 + 明确报告，不做任何权限变更（见 §6）；适配器侧遇到这类拒绝直接标记失败并冷却跳过，让调度器立刻换下一个候选。

---

## 5. 已尝试过的两种绕过方式，以及为什么没解决

### 5.1 关闭会话持久化（`--no-session-persistence`）

- 做法：`codebuddy ... --no-session-persistence`
- 结果：确实跳过了 `projects\<slug>\<uuid>.jsonl`，但立刻卡在下一步 `EPERM mkdir ...traces\<pid>`；仍然是退出码 0、stdout 为空。
- 为什么没解决：这个参数只去掉"会话记录"这一处写入，`traces` 仍然要按进程建目录。只要目标根目录不可写，换一个写入点还是会失败。
- 额外代价：即使能跑通，也会丢掉会话历史，不适合作为长期方案。

### 5.2 改权限模式（`acceptEdits` / `bypassPermissions`）

- 做法：分别用 `--permission-mode acceptEdits` 和 `--permission-mode bypassPermissions` 启动。
- 结果：两者都在 **projects 写入阶段**失败，报错完全相同（见 2.5）。
- 为什么没解决：权限模式管的是"模型调用工具时要不要人工批准"，发生在启动和状态写入**之后**；它不会给进程额外的文件系统权限。
- 补充：`bypassPermissions` 仍然是 headless 干活的必需项（否则会只回一句"需要授权"、退出码 0），但它解决的是另一个症状，**不是这个写入问题**。

---

## 6. 处理边界：只允许识别和报告

### 6.1 允许做的（只有这两件）

1. **识别**：按 §0 跑探针，按 §1–§4 判断失败发生在哪一层；把原始报错和探针输出原样留下。
2. **明确报告**：按 §9 的口径写清"卡在调用方沙箱，目录无需修复"，并附证据。

到此为止。本机（2026-11-15）已经确认目录、归属、ACL 全部正常，**没有任何目录需要创建或修复**。

### 6.2 明确禁止（做了就算越界，直接判失败）

- **创建、删除、重建 `.codebuddy` 及其 `projects`/`traces` 目录**（包括"只补一级"）。
- 提权 / "以管理员身份运行" / `takeown` / `icacls` 授权 / `Set-Acl` / 改所有者 / 改 ACL 继承规则。
- 关闭或绕过沙箱、Defender、受控文件夹访问、任何安全策略；不要为了绕开限制去换执行账户或启动方式。
- 修改 codebuddy 的配置、登录态、凭据；删除或清空已有会话数据。
- 顺带修改 `.qoder` 或其它 agent 的目录（qoder 只作为参考，不在本次范围）。
- 为了让验收通过而关掉回退、伪造正文、或把失败记成成功。

### 6.3 为什么不能"顺手修一下"

- 六条探针在普通终端全过，说明目标目录对当前用户本来就可写；再去改 ACL/建目录，不会改变调用方沙箱的判定。
- 改 ACL、提权、绕沙箱都会扩大权限面，且很难回滚；为一个已被证伪的假设付这个代价不划算。
- 真正的解法不在权限里，而在"由哪个进程去执行"（见 §9 的最后一段）。

---

## 7. 验收标准

必须在**非沙箱进程**里跑（用户自己的普通 PowerShell 窗口、计划任务、或独立守护进程），且是**真实派单（非 dry-run）**。在 agent 托管 shell 里跑必然失败，那里的结果不构成验收证据。

### 7.1 直接调用

```powershell
cd C:\Users\M4A1g\Documents\Warpeas\agent-credit
codebuddy -p "Reply with OK" --output-format json --permission-mode bypassPermissions
```

通过条件：

- 退出码 `0`；
- stdout **非空**，是合法 JSON，且能取到正文（例如 `OK`）；
- stderr 不含 `EPERM` / `ENOENT` / `EACCES`。

### 7.2 真实派单

```powershell
cd C:\Users\M4A1g\Documents\Warpeas\agent-credit
python credit.py dispatch --provider codebuddy --capability code --task "Reply with OK" --timeout 120
```

通过条件（四条全部满足）：

1. 命令退出码 `0`；
2. 输出里有**有效正文**（不是"需要授权"、不是反问、不是空）；
3. 最新一条派单记录（`data/ledger.json` 的 `dispatches` 数组最后一项）满足：`provider = codebuddy`、`ok = true`、`exit_code = 0`、`fallback = false`；
4. 输出里**没有**"已回退 / fallback"字样。

失败时的典型表现（判失败，不要美化）：

- 记录里 `ok = false`、`exit_code = 126`、`fallback = true`；
- 或者命令退出码 0 但正文为空；
- 或者 stderr 仍然出现 `EPERM` / `ENOENT` / `EACCES`。

若在**沙箱环境**里跑 §7.2，正确表现是：codebuddy 那条 `exit_code = 126`，`note` 以"调用环境受限，需在非沙箱环境执行"开头，调度器立刻回退到下一个候选；随后 5 分钟内再派单，codebuddy 会被预检直接跳过（0 秒，`exit_code = 69`），不会每次都起一个注定失败的进程空转。这不算"修好了"，而是如实暴露了执行环境的限制。

---

## 8. 自检命令清单与"什么算失败"

按顺序跑，任一步失败就停在该步，不要继续往下"试"。

```powershell
# 1) 入口是否正常（不应该写状态目录）
codebuddy --version
# 期望：2.184.0；失败：非 0 退出或无输出

# 2) 写入探针（见 §0 的脚本）
# 期望：§0 表格里对应你这一层的全部 OK

# 3) 直接 headless 调用（见 §7.1）
# 期望：exit 0 + 非空正文 + stderr 无 EPERM/ENOENT/EACCES

# 4) 真实派单（见 §7.2）
# 期望：exit 0 + 有效正文 + 账本 ok=true / exit_code=0 / fallback=false

# 5) 看账本最后一条
$j = Get-Content "C:\Users\M4A1g\Documents\Warpeas\agent-credit\data\ledger.json" -Raw | ConvertFrom-Json
$j.dispatches | Select-Object -Last 1 at,provider,ok,exit_code,fallback,note | Format-List
```

判定口径：

| 现象 | 判定 |
|---|---|
| 退出码非 0 | 失败 |
| 退出码 0 但 stdout 为空 / 取不到正文 | 失败 |
| stderr 出现 `EPERM` / `ENOENT` / `EACCES` | 失败 |
| 正文是"需要授权 / 接下来做什么"这类反问 | 失败 |
| 派单 `ok=false` 或 `exit_code=126` 或 `fallback=true` | 失败 |
| 只有"我说修好了"但没有第 4/5 步的输出 | 不算完成 |

---

## 9. 交付时请报告

1. **卡在哪一层**：目录/归属问题，还是调用方文件系统沙箱，还是其它；给出 §0 探针的**完整实际输出**，并注明是在哪个环境里跑的（托管 shell / 普通终端）。
2. **做了什么**：只允许两件事——识别、报告。明确写"未修改任何目录、ACL、权限、配置"。如果做了其中任何一项，直接判越界失败。
3. **本机的标准答案**（2026-11-15 已确认）：

   > 卡在调用方沙箱。普通终端六条探针全部 OK，目录、归属、ACL 正常，**目录无需修复**。
   > 派单进程（及其子进程）写家目录被拒，属于调用环境限制，需在非沙箱环境下执行。

4. **验收证据**（只有在非沙箱进程里跑过才需要附）：§7.1 和 §7.2 的完整命令与输出，包括账本最后一条的 `provider / ok / exit_code / fallback`。
5. **如果你在非沙箱环境里跑**：报告 §7 是否通过。通过就说明"目录本来正常，之前的失败确实来自调用方环境"；不通过再附原始报错，**不要**回头去改权限。

不要用"已尝试/应该可以"代替证据，也不要把"我改好了"当成结论——本机不存在需要修的目录。

