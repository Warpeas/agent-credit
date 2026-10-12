# agent-credit 项目长期约定

## 探索安全（最高优先级）

- **动任何客户端前先读 `research/SAFETY.md`**（单一来源；`skill/SKILL.md`、`catalog.yaml`
  notes、README 都引用它，改规则只改那一处）。
- 禁止：解密登录态 / 内存注入取 token / CDP / 绕完整性级别 / 篡改本地数据 /
  高频压测 / 绕验证码 / 写循环重试。
- 允许：只读本机明文凭据调官方接口、只读二进制 i18n、走客户端自身 UI 自动化、
  只读 GET 查余额与签到状态、问 Agent 自己。
- 预算：同端点 ≤2 次、候选端点 ≤10、单次探索 ≤20 工具调用；**查不到写 unknown，别硬钻**。

## 环境限制（踩过的坑）

- **沙箱/会话里直接拉 GUI 恒失败**：`Start-Process` / `Popen` / `os.startfile` /
  `ShellExecute` 都返回成功但**进程数为 0**。唯一可行：非提权计划任务
  （`RunLevel=Limited` + `LogonType=Interactive`）。
- ⚠️ 拉客户端的任务**跑完不要 Unregister**（任务生命周期 == 应用生命周期，会连杀客户端）。
- `-UserId` 必须从 `[WindowsIdentity]::GetCurrent().Name` 推导，别硬编码。
- `schtasks.exe` 被拦 → 用 `Start/Stop/Unregister-ScheduledTask`（`Remove-ScheduledTask` 不存在）。
- PowerShell 工具：不许 `Add-Type`（Win32 用 Python `ctypes`）；结果不回显 → **写文件再 Read**；
  避免 `%VAR%` 写法。Bash 里调 `powershell` 被拒。
- `wmic` 已移除 → `Get-CimInstance Win32_Process`；屏幕 3840x2160 有 DPI 缩放。
- 计划任务里 Python 崩了看不到 stderr → 脚本自己 try/except 把 traceback 落盘。
- 拉起 GUI 标准写法见 `scripts/_task_*.ps1`（`_task_trae.ps1 -ProcessName X [-WaitReady]`、
  `_task_lobsterai.ps1 -Mode claim|verify`、`_task_trae_claim.ps1`）。
- ⚠️ **`Unregister-ScheduledTask` 在沙箱里「拒绝访问」** → 同名任务残留，下次
  `Register-ScheduledTask` 报「文件已存在」。但 `Start-ScheduledTask` 仍能启动那个旧任务，
  所以生产路径**碰巧还能跑**，代价是每次日志里一条报错 + 旧任务的 action 不会更新
  （exe 路径若变，残留任务会启动错误的路径）。排查时别被这条报错误导成“客户端没拉起”。
- **同完整性原理**：客户端是 Limited 任务拉起的（中完整性），驱动脚本同完整性跑即可，
  **不需要 UAC**（UIPI 只拦 LOW→HIGH）。旧「必须提权」结论已推翻。

## PowerShell 脚本 bug 类型

1. **单引号里 `$` 不展开**（`$x='$root\logs\a.png'` 是字面量）→ 一律 `Join-Path`。
2. **函数定义必须在启动流程之前**（顺序执行）。
3. 补 P/Invoke 前核对 `Add-Type` 块是否已声明该 Win32 API。
4. ⚠️ **ps1 必须存成 UTF-8 with BOM**。无 BOM 时 PS 5.1 按 GBK 解析，中文全变乱码
   （10-13 抽脚本片段时踩到：`_probe_trae.ps1` 直接语法报错，且乱码会跟着
   `WriteAllText` 写进结果 JSON）。**抽取/重写 ps1 后必须复查文件头三字节**。
5. **`if () {} else {}` 不能直接接管道**（PS 7 才支持），要先攒数组再统一 `Out-File`，
   否则整条命令解析失败、静默 exit 1。
6. **`Get-Content` 读无 BOM 的 UTF-8 会按 GBK 解析** → 读出来像乱码，但文件本身是好的。
   排查编码问题一律用 Python 读原始字节确认，别信 PowerShell 管道里的“乱码”。
   （`Write-Host` 也不进 pipeline，`2>&1 | Out-File` 抓不到它。）

## UI 自动化铁律（跨客户端）

1. **别用绝对亮度阈值找元素**（深浅主题随时切）→ 相对当前行底色（像素众数分桶）+ 长度区间；
   扫描窗口别用「文字右边界 + 常量」推（新控件常比文字更靠右，会把元素切断）。
2. **DPI 只认运行时查询**（`SetProcessDPIAware`），别读注册表（登录时写入，会话内改不更新）。
3. **选窗三条硬条件：可见 + class ≠ `Chrome_WidgetWin_0` + 标题非空**，面积只作同级比较。
   Electron 客户端都会另建推广/活动窗（空标题、首绘前纯黑、尺寸随内容变）。
4. **反遮挡终判据**：`WindowFromPoint(窗口中心)` 顶层祖先（`GetAncestor GA_ROOT`）== 主窗口；
   **不能比 pid**（WebView2 内容在 `msedgewebview2.exe` 子进程）。主窗口可能隐藏/托盘，
   此时 `GetForegroundWindow()` 仍会返回它 → 「前台」不足以验证。
5. **`claim_mode: ui` ≠ 有 UI 配方** → 回落 UI 前先过 `ui_claim.has_ui_route()`。
6. **坐标换算**：Read 展示 PNG 等比缩到 1088 宽，`scale = 真实像素宽/1088`，
   `abs = 窗口原点 + 缩略图坐标*scale`（见 `scripts/ui_claim_monkeycode.py:content_click`）。
7. OCR 会被活动广告文案劫持 → 锚点/按钮限定左侧栏 `x<600` 且限文本长度（锚点 ≤12、按钮 ≤16）。

## 客户端事实

### MiniMax Code

- Electron，`%LOCALAPPDATA%\Programs\MiniMax Code\MiniMax Code.exe`；双窗口
  `Chrome_WidgetWin_1`（真身）/ `_0`（推广浮层，冷启动早 ~0.8s、纯黑）。
- **额度（10-13 API panel 硬证据，推翻此前所有 OCR 推测）**：day1=800(+bonus 400)、
  day2=400、day3=400、**day4=1000**、day5=400、day6=400、**day7=1000**，周期合计 **4400**。
  以 `/signin/status` 的 `panel.days` 为准（10-04 记的 12000、catalog 的 3000 均作废）。
- 有效期 30 天 = confirmed（**付费积分 1 年**，别混用）。
- external：`vendor/minimax-auto-signin/signin.py`，端点
  `/signin/{status,claim}`，**必带 `timezone_id=Asia/Shanghai`**；
  token `~/.minimax/auth/prod/cn/mcode-public/auth.json` 明文，客户端一停就废。
- ⚠️ **不要开 OAuth2 自刷新**：轮 token 时无法同步 `loginEpoch` → 客户端退回未登录。
  通用教训：动第三方凭据前先找会话级标识（loginEpoch / session / device id）。

### MonkeyCode（长亭百川）

- Tauri(webview2)，`%LOCALAPPDATA%\MonkeyCode\monkeycode-desktop.exe`；同 pid 另有
  `tray_icon_app` 与桌宠窗 → find_main 双重排除。
- `GET /users/wallet` 的 `balance` == 签到积分；`/wallet/checkin` 的 `checked_in` 是
  **幂等闸门，必须在拉起客户端之前**查（已签直接返回；点完再复核，以接口为准不信 OCR，
  复核不过 → pending 不入账）。
- **external 直签永久不可行**（10701 + 固定规格图形验证码）→ 走 UI：
  左下「设置」→ 账号页 → 积分卡片下方绿色「签到 +100」；**UI 路径无验证码**。
  ⚠️「设置」是 toggle，弹层残留时点它会关掉 → 先检测账号页绿色特征。
- 有效期 unknown（两侧确认无明细入口）；cookie 只在**重连/重登**时回写，
  掉登录 = 账号页积分卡片消失 + external 全线 401。
- 恢复现场：`launched_by_us` + try/finally + 收尾 WM_CLOSE（超时才 Terminate，
  **别 `taskkill /IM`**）。

### LobsterAI

- Electron，双窗口同 MiniMax 构型。
- **积分四类、各自有效期独立**（daily/monthly/longTerm/campaign）→ `validity_days` 为 null
  是**无法单值表达**，不是 unknown。查法：设置 → 积分明细（`/settings/credits`）。
- 积分礼**不走 `daily_check_in` 槽位**（slot 永久 empty）→ 判是否已领要看 UI
  「积分额度」数值 + 有无「立即领取」按钮；入口：左下「我的」面板 / 右上角「每日积分礼」chip。
- 无 external 余额端点、本地 sqlite 无积分缓存 → 余额只能 UI OCR。
- ⚠️ 用户栏选择器不能只按空间挑：面板展开时左下同时有「退出登录」和「我的」
  → 用 `Find-UserBar` + `Test-PanelOpen`（10-08 曾点掉登录态，需人工重登）。

### Trae（2026-10-09 官宣：Trae + TraeCode 合并为 TRAE，统一叫 Trae）

- 活的：`%LOCALAPPDATA%\Programs\Trae CN\Trae CN.exe` v3.4.2，主窗口标题 `Agent`；
  同 pid 另有 **128×200** 小窗 → 筛选要「可见 + class + 标题非空 + 面积最大」四条齐。
  两产品共用一个积分账户 → 台账只留 `trae` 一条；**account id 不改**（改了要迁
  ledger 历史，收益不抵风险），catalog 显示名已改 `Trae`。
- **日额度 100**（09-30 起实测，原 150）。**额度一律以实测为准**：脚本用 detail 里的
  `[granted] N` 上报，`checkin.py` 接 `_parse_granted`。
- **签到卡片常驻左侧栏底部，三态互斥**（10-13 实测，当前判据基础）：
  未签「每日领100积分」+「升级会员，每日多领100积分」/ 按钮 [签到][升级权益]；
  刚领「今日签到，已获得100积分。下次可在头像菜单中签到。」/ [今日已签(3s)]；
  已签（稳定）卡片整块换成会员推广「夺会员首月立减¥30 / 升级会员立即获得大额积分…」/
  [立即升级]，**页面再无任何签到字样**。
- **判据优先级（10-13 改）**：① 正则抓「已获得N积分」取实发额度（主，比余额差直接，
  服务端调额能自动跟上）→ ② 余额差（备用）→ ③ 文案（兜底，拿不到额度退回 daily_amount）。
  幂等闸门 = 入口词「每日领」消失 + 会员推广态出现。
- ⚠️ **账户条已无积分余额**（旧「用户71294228173 免费 3,527」→ 新「0用户71294228173免费」，
  整行被 OCR 并成一条、**words 是单字数组**）→ 「读账户条余额看差额」这条老路线作废
  （Find-Balance 恒 -1），按 word 匹配「用户」的锚点也失效，要按整行文本定位。
- 链路：`_task_trae.ps1` 非提权任务拉起 + `_run_ps1` 同完整性点击。
  ⚠️ 缺 `Reset-WindowRect` 会让冷启动窗口比桌面还大、签到锚点挂到屏幕外。
- ⏳ 待办：09-30 疑似漏记「月赠 500」（仅单日差额证据），下次月赠到账时用同分钟余额差复核。

## 进度可观测性（10-11 立）

- 计划任务 = 一个黑框 → `agent_credit/trace.py` 统一负责：
  `note()` 带耗时戳、`stream()` 实时转发子进程输出、`LogTailer` 读提权 ps1 的日志、
  `wait_for()` 心跳。落盘 `logs/checkin_YYYY-MM-DD.log`（窗口关了也能回看）。
- ps1 侧：`ui_claim_{minimax,autoclaw,trae}.ps1` 顶部有 `Log()`（写
  `logs/ps1_<name>.log` + `Write-Output`），主流程关键点调用；文件名与
  `ui_claim.py:_ps1_log` 对应（LobsterAI 是 `_lobsterai_log.txt`）。
- `credit.py` 入口 reconfigure UTF-8 + 行缓冲；`register-daily-task.ps1` 命令带 `-u`。
- 手动跑想看清结果：`credit checkin --hold N`（结束后停留 N 秒）。

## 工程约定

- **入库标准**：项目资产（换机器还要用）→ 入库；一次性改写脚本 → 用完即删；
  运行期产物（账本/日志/截图）→ `.gitignore`。`.workbuddy/memory/*.md` 入库。
- 提交前：凭据扫描（`scripts/test_leak_check.py`）、检查生产脚本没 import `_` 草稿、
  审计残留杂项；每次会话变更独立 commit。
- **UI 判据必须有回归测试**：判据失效是**静默**的（不报错，只退回弱判据、额度失真）。
  `scripts/ui_claim_trae.ps1` 的判据正则集中在顶部（`$RE_*`），
  `scripts/test_trae_states.py` 从源码抠正则跑三态样本——改了正则忘了改样本会直接报错。
  新写 UI 判据照这个模式来。
- 调试**不动账本** `data/ledger.json`；改前备份。
- ⚠️「已发布/已推送」结论必须复核（`git branch -a` / API），别凭记忆（10-07 记错过）。
- 沙箱推 GitHub：`github.com` 的 CONNECT 被代理拦，`api.github.com` 直连；
  **不再维护推送脚本，主人自己 push**。
