# 方案甲：屏外窗口后台签到 — 实现交接文档

> **拍板记录**：2026-10-21 00:1x，主人拍板「甲方案」，委托其他 agent 会话实现。
> **PoC 依据**：2026-10-20 23:06-23:46 影子桌面 PoC（见「参考资料」），结论已写入
> `.workbuddy/memory/2026-10-20.md` 与 `MEMORY.md`「影子桌面」节。
> **本文档面向实现者**：不依赖任何对话上下文，按本文 + 参考资料可独立开工。

---

## 1. 背景与目标

签到链路里 UI 路线的客户端（Trae / MiniMax / LobsterAI / AutoClaw / QoderCN）目前
冷启动后**整个窗口挂在主人屏幕上**直到关闭（10-60 秒），且坐标点击会瞬移物理光标。
主人诉求：**不抢屏幕**。

已实证的技术边界（PoC，详见第 2 节）：

- 抓图 + OCR + 状态判据 → **可完全后台化**；
- 点击 → **不可完全后台化**（OS 级输入注入到不了不可见桌面），只能把暴露面压到
  「一次 ~100ms 的光标跳动」。

方案甲 = 用**屏外窗口**（同一桌面，窗口整体移出屏幕边界）实现「识别全后台」，
把点击暴露面压到最小。不引入新桌面、不改签到语义、不改判据。

## 2. PoC 已验证结论（实现者可直接采信）

| 命题 | 结论 | 证据 |
|---|---|---|
| Electron 客户端在无 shell 的影子桌面正常渲染 | ✅ | Trae 冷启动于 CreateDesktop 桌面，PrintWindow 抓到 359-587 色、std 22-35 的完整 UI |
| WinRT OCR 对影子桌面截图有效 | ✅ | 抓到 60 个词（Trae 菜单/侧栏/账户栏） |
| 影子桌面线程 SendInput 注入 | ❌ `inserted=0`，系统直接拒绝 | 输入走「输入桌面」不跟调用线程桌面；光标探针证明默认桌面光标全程未动（3659,5 → 3659,5） |
| 跨桌面 PostMessage/SendMessage | ✅ WM_CLOSE / WM_GETTEXT 实测可达 | 但 Chromium 自绘 UI 对合成鼠标消息无感，点不动签到按钮 |
| 影子桌面上 BitBlt(GetDC(NULL)) | ❌ 恒失败（全黑） | 只有 PrintWindow 系可用 |
| Win+Tab 虚拟桌面 | ❌ 排除 | 无公开 API；非当前桌面不合成、截图黑；切换抢焦点 |
| 冷启动首帧渲染延迟 | ⚠️ 窗口出现后 2-8s 才真正画出内容（首帧 uniq=3） | 捕获必须重试到 `uniq>5 -and std>3` |

**推论（方案甲的依据）**：屏外窗口比影子桌面更弱一档——窗口仍在默认桌面、
`IsWindowVisible=true`，DWM 正常合成，PrintWindow 必然可用（现有脚本本就依赖
「PrintWindow 对被遮挡/非前台窗口有效」，见 `ui_claim_trae.ps1` 注释）。
唯一需要每客户端实测的是渲染节流（见风险 R2）。

## 3. 方案甲架构

### 3.1 时序

```
计划任务冷启动客户端（现有链路，不变）
  → Find-*Window 找到主窗口（现有逻辑，不变）
  → Reset-WindowRect（现有机制：把冷启动的异常 rect 拨回屏内，不变）
  → 【新】Move-Offscreen：整窗移出左边界，SWP_NOZORDER|SWP_NOACTIVATE
  → 【新】跳过 Ensure-Foreground / Wait-Foreground（屏外抢前台无收益，且打扰用户焦点）
  → 判据阶段：PrintWindow 截图 + OCR + 状态机（现有逻辑，坐标全部不变）
  → 需要点击时：
      → 【新】先试 UIA InvokePattern（窗口屏外也能 Invoke，COM 与位置无关）
            成功 → 直接进入点击后判据复核
      → 【新】兜底 Bring-Back-And-Click：
            1. 窗口移回「点击位」（默认原位；被遮挡则试 (0,0)，再不行 → pending）
            2. GetCursorPos 保存光标
            3. SetCursorPos + mouse_event 点击（现有 Click-At 主体，坐标不变）
            4. SetCursorPos 恢复光标
            5. 窗口移回屏外
  → 点击后判据复核（现有逻辑，不变）
  → 【新】关闭前 Restore-OriginalRect：把窗口移回启动时的 rect
  → WM_CLOSE / 现有收尾（不变）
```

### 3.2 三个新机制的具体规格

**M1 Move-Offscreen（启动后立即执行）**

- 坐标：`x = -(窗口宽 + 64)`，`y = 0`（整窗在主屏左界外；不要用 -32000 之类极端值，
  Electron 对极端坐标有 clamp 历史）。窗口宽高用 `GetWindowRect` 实测。
- API：`SetWindowPos(hWnd, [IntPtr]::Zero 之后... )`——现有脚本的 P/Invoke 块多数已声明
  `SetWindowPos`（`ui_claim_trae.ps1` 的 `Reset-WindowRect` 就在用）；没声明的补声明。
- Flags：`SWP_NOZORDER(0x0004) | SWP_NOACTIVATE(0x0010) | SWP_NOSIZE 视情况`——
  **绝不激活窗口**。
- 原 rect 存脚本变量（`$script:OriginalRect`），关闭前恢复用。

**M2 UIA Invoke 优先（点击前）**

- 参考现成实现：`scripts/ui_claim.ps1` 的 `Invoke-Element`（InvokePattern 优先、
  GetClickablePoint 兜底——注意兜底那段在屏外场景不可用，只取 InvokePattern 分支）；
  `scripts/ui_claim_monkeycode.py` 的 `uia_click` / `uia_claim_flow` 也可参考。
- 成功判据：Invoke 不抛异常即视为已点，**随后必须过原有点击后判据**（OCR 复核），
  不过 → `pending` 入账失败，**不重试**（SAFETY 第 3 条：不写循环重试）。
- 预期：Trae/MiniMax 的签到卡片是自绘 UI，UIA 大概率找不到 → 自动走 M3，属正常路径。

**M3 Bring-Back-And-Click（坐标点击兜底）**

- 点击位选择：默认**原位**（启动时 rect）；移回后用项目铁律 4 反遮挡校验
  （`WindowFromPoint(窗口中心)` 顶层祖先 == 主窗口），不过则试 `(0,0)`，再不过 → pending。
- 光标保存/恢复：`GetCursorPos` → 点击 → `SetCursorPos` 恢复。必须包在 try/finally 里，
  任何异常路径都要恢复光标（恢复失败要打日志）。
- 点击坐标算法不变：窗口原点 + OCR 词框相对坐标（现有 `Click-At` 的主体逻辑照抄）。
- 点完立即移回屏外（M1 的逆操作），再做点击后判据。

**M4 Restore-OriginalRect（关闭前）**

- 在 `Restore-Scene` / `Close-LaunchedApp` / WM_CLOSE **之前**执行。
- 原因（甲方案最大的隐藏坑）：Electron 客户端会把窗口位置持久化进自己的 config，
  留着屏外位置关闭 → 下次冷启动窗口还在屏外 → 判据坐标全错，且用户永远看不到窗口。
- 同时保留现有 `Reset-WindowRect` 的启动时检查——它现在多一层职责：把上次残留的
  屏外位置拨回屏内（双保险）。

## 4. 改动点地图（按文件，精确到函数）

### 批次 1：`scripts/ui_claim_trae.ps1`

| 函数（行号） | 改动 |
|---|---|
| `Find-TargetWindow` (199) | 返回后调用 M1 Move-Offscreen，保存 `$script:OriginalRect` |
| `Ensure-Foreground` (288) / `Wait-Foreground` (319) / `Get-OcrLinesSafe` (329) | 屏外模式下**跳过**（保留函数，加 `-Offscreen` 开关或直接摘调用点；`Wait-Foreground` 的 45s 等待逻辑在屏外模式必须跳过，否则白等） |
| `Click-At` (685) | 入口处先试 M2 UIA Invoke；失败走 M3：移回 → 保存光标 → 原点击逻辑 → 恢复光标 → 移屏外 |
| `Close-AdOverlays` (761) 与收尾 | 关闭前插入 M4 Restore-OriginalRect |
| `Save-Shot` (793) | 不用改（PrintWindow 对屏外窗口有效） |

### 批次 2：同模式复制

| 文件 | 窗口查找 | 点击 | 备注 |
|---|---|---|---|
| `ui_claim_minimax.ps1` | `Find-AppWindow` (210) | `Click-At` (471) | ⚠️ `Find-AppWindow` 刚修过哈希表数组排序坑（2026-10-20），**别碰那块**；`Wait-Foreground` (319) 屏外跳过 |
| `ui_claim_lobsterai.ps1` | `Find-AppWindow` (104) / `Find-ByTitle` (141) | `Click-At` (259) | 已有 `Reset-WindowRect` (188) / `Save-Foreground` / `Restore-Scene` (102)，M4 挂 `Restore-Scene` |
| `ui_claim_autoclaw.ps1` | `Find-AutoClawWindow` (142) | `Click-At` (368) | `Wait-Foreground` (227) 屏外跳过 |

### 批次 3（默认不做）：`scripts/ui_claim_qodercn.ps1`

`Capture-Win` (116) 是 **CopyFromScreen 屏幕捕获**，且「权益中心」菜单弹窗是**独立层**
（PrintWindow 主窗口会漏掉弹窗）。屏外后屏幕捕获拿到的是屏幕外坐标（全黑/其他内容）。
要做先论证：弹窗是否跟随主窗口位置。默认结论：**维持现状**。

### 不做：`scripts/ui_claim_monkeycode.py`

`screen_shot` (489) 是 BitBlt 屏幕捕获（Tauri/WebView2，PrintWindow 抓不到 webview 内容），
窗口必须真在屏幕上。但它已有 `uia_click` / `uia_claim_flow` (565/585)——若 UIA 路线
足够成熟，窗口可屏外。**列为后续调研项，不在本期范围**，别顺手改。

## 5. 明确不做清单（含原因，防止实现者走弯路）

1. **影子桌面做点击**：SendInput 在影子桌面线程 `inserted=0`（系统拒绝），输入只走
   「输入桌面」。已实测，别再试。
2. **Win+Tab 虚拟桌面**：无公开 API、非当前桌面不合成、切换抢焦点。
3. **改签到判据/语义/账本**：本方案只改窗口位置与点击路径，判据正则、幂等闸门、
   `[granted] N` 上报逻辑一律不动。
4. **CDP / remote-debugging**：SAFETY.md 红线，禁止。
5. **给点击加循环重试**：SAFETY.md 第 3 条，一次不过就 pending。

## 6. 风险登记与缓解

| # | 风险 | 缓解 |
|---|---|---|
| R1 | 客户端把屏外位置持久化，下次启动仍在屏外 | M4 关闭前恢复 rect + 启动时 `Reset-WindowRect` 双保险；验收项 A3 断言 rect 恢复 |
| R2 | Electron 窗口不可见时 backgroundThrottling 降频，渲染延迟/暂停 | 捕获加重试循环（PoC 模式：间隔 2s 直到 `uniq>5 -and std>3`，上限 30s）；每客户端首轮实测一次并在 catalog notes 记录 |
| R3 | 窗口移回点击位时被其他窗口遮挡，点击落空 | 项目铁律 4 反遮挡校验（`WindowFromPoint(中心)` 顶层祖先 == 主窗口）；不过 → 试 (0,0) → 再不过 → pending |
| R4 | 光标恢复失败（异常路径） | try/finally 强制恢复 + 日志断言；A3 验收 |
| R5 | UIA Invoke 点错按钮（自绘 UI 的 UIA 名不准） | Invoke 后必须过原有点击后判据；不过 → pending，不重试 |
| R6 | 移窗瞬间用户看到窗口一闪 | 移动是同步 API（毫秒级）；点击位默认原位（用户本来就看到客户端在那个位置启动，一闪的感知增量极小）；验收 A3 人工确认 |
| R7 | 多显示器/DPI 环境下屏外坐标语义变化 | 屏外判据用 `GetWindowRect` 实测宽度动态计算，不写死；DPI 只认 `SetProcessDPIAware` 运行时查询（项目铁律 2） |

## 7. 落地批次与 commit 粒度

- **批次 1**：`ui_claim_trae.ps1`（回归最全：`scripts/test_trae_states.py` 三态样本）。
- **批次 2**：`ui_claim_minimax.ps1` → `ui_claim_lobsterai.ps1` → `ui_claim_autoclaw.ps1`，
  一个客户端一个 commit。
- **批次 3**：`ui_claim_qodercn.ps1` 先写论证（弹窗跟随性），结论默认「不做」。
- 每批次：改完 → 跑回归 → 请主人实弹一轮（见 N1）→ commit。
- `scripts/_poc_desktop.ps1` / `_task_poc_desktop.ps1` / `_poc_probe.ps1` 是 PoC 草稿
  （`_` 前缀，按项目约定**不进 commit**）；PoC 里可复用的 P/Invoke（MoveWindow/
  PrintWindow/光标保存）可提炼进生产脚本。

## 8. 验收项

**机器可验**：
- A1 判据回归全绿：`python scripts/test_trae_states.py`、`python scripts/test_username_anchor.py`
  （后者证明没碰坏 qodercn 判据）；判据正则若改，样本必须同步（回归会报错，设计如此）。
- A2 端到端状态一致：实弹 `credit checkin --only <client>` 的 ok/already/pending 分布
  与改造前同状态（对比 `logs/checkin_*.log` 历史）。
- A3 日志断言（新增）：点击前后 `GetCursorPos` 一致；关闭前 rect == 启动 rect。

**人工/实弹**：
- A4 无闪现：主人观察或录屏一整轮，确认没有客户端窗口长时间挂屏（允许点击瞬间
  毫秒级移窗）；光标点击后回位。
- A5 异常路径：运行中杀掉脚本，确认客户端不留屏外（至少下次启动能被拨回屏内）。
- A6 账本不受影响：debug 轮不动 `data/ledger.json`（现有约定）。

## 9. 实现注意事项（硬提醒）

- **N1 沙箱里跑不了 GUI**：agent 会话内 `Start-Process` / `os.startfile` 拉 GUI 进程数为 0
  （2026-10-20 实测两次，白等 90s）。实弹验证必须请主人在交互桌面跑，或挂
  `scripts/_task_*.ps1` 非提权计划任务。别在会话里空跑。
- **N2 PowerShell 5.1 坑索引**（全部实测过，详见 `MEMORY.md`）：
  ps1 必须 UTF-8 with BOM；`$null` 字符串参数会被马谢成空串（Win32 收 NULL 的一律
  `IntPtr.Zero`）；`Marshal.SizeOf` 传实例不传类型字面量；参数签名别用 `[uint]/[ushort]`
  （任务上下文报 Unable to find type）；`$child` 与 `$Child` 大小写碰撞；
  函数返回 1 元素数组会退化成标量（调用侧 `@()` 包裹）。
- **N3 不动判据样本**：`test_trae_states.py` 从 ps1 源码抠正则跑样本，改正则忘改样本
  会直接报错——这是保护机制不是障碍。
- **N4 提交前**：`python scripts/test_leak_check.py`；确认没有 import `_` 草稿；
  每次会话变更独立 commit。
- **N5 SAFETY 合规**：仍是 OS 级点击客户端自身界面；点击次数不增加（只是位置变了）；
  不开 CDP、不解密、不写循环重试。方案甲不触碰任何红线，`research/SAFETY.md` 不用改。

## 10. 参考资料

- PoC 全套：`scripts/_poc_desktop.ps1`（parent/child 一体，含 MoveWindow/PrintWindow/
  光标探针现成代码）、`scripts/_task_poc_desktop.ps1`、`scripts/_poc_probe.ps1`、
  `logs/poc_desktop.log`（全程日志）、`logs/poc_client_printwindow.png`（实证截图）。
- 结论沉淀：`.workbuddy/memory/2026-10-20.md`（PoC 结论节）、
  `.workbuddy/memory/MEMORY.md`（「影子桌面」节 + 「PowerShell 脚本 bug 类型」）。
- 安全边界：`research/SAFETY.md`。
- 现有生产实现：`scripts/ui_claim_{trae,minimax,lobsterai,autoclaw,qodercn}.ps1`、
  `scripts/ui_claim_monkeycode.py`、`scripts/ui_claim.ps1`（UIA Invoke 参考）。
