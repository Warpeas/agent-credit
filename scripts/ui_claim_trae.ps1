# Trae OCR check-in: find anchors via screenshot+OCR, click the daily check-in button.
# Requires: the client foreground (interactive) or a non-elevated runner.
#
# 2026-10-11: TRAE SOLO CN (Trae) was merged into "Trae CN" and the old
# install dir was emptied (only debug.log left) — so the defaults now point at
# the merged client (Trae CN v3.4.2, main window title "Agent"). Both products
# always shared one credit account, so the ledger keeps a single `trae`
# entry; do NOT add a second one for the merged client.
param(
    [switch]$DryRun,
    [switch]$Explore,
    [string]$OutFile,
    [string]$ProcessName = 'Trae CN',
    [string]$ExePath = '',
    [string]$ShotDir = '',
    [int]$AvatarX = 0,
    [int]$AvatarY = 0,
    # 2026-10-14：客户端由调用方（_task_trae.ps1 计划任务冷启动）在本脚本
    # 之外拉起时，$script:LaunchedByUs 恒为 false，Out-Json 不会关窗——凌晨
    # 那轮签完客户端就一直挂在桌面上。调用方确认是自己冷启动的就传本开关，
    # 结束时与脚本自启动走同一条清理路径。
    [switch]$CloseAfter,
    # 方案甲（2026-10-21 拍板）：签到全程把窗口停到屏外——识别走 PrintWindow
    # （对屏外窗口有效），点击分三级：合成消息 → UIA Invoke → 移回屏内真实点击
    # （光标保存/恢复，暴露面 ~100ms）。传 -Offscreen:$false 退回旧行为。
    [bool]$Offscreen = $true,
    # 前台模式：计划任务参数里传 -Offscreen 0 易踩解析坑，改用无值开关。
    [switch]$Foreground,
    # 前台补签的空闲闸门：用户仍在用电脑就等待，超时仍活跃则放弃本次补签，
    # 绝不为了补 100 积分抢前台/移窗口。仅 -Foreground 时生效。
    [int]$IdleWaitSec = 300,
    [int]$IdleThresholdSec = 60
)
if ($Foreground) { $Offscreen = $false }
$root = Split-Path -Parent $PSScriptRoot
$logPath = "$root\logs\ps1_trae.log"
function Log($m){ $s=(Get-Date -Format "HH:mm:ss")+" "+$m; try{[System.IO.File]::AppendAllText($logPath,$s+"`n",(New-Object System.Text.UTF8Encoding($false)))}catch{}; Write-Output $s }

$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

# Surface terminating errors instead of dying silently (the runner then just
# reports a bare timeout with no clue about the real cause).
trap {
    # 方案甲：FATAL 也不能把窗口留在屏外（A5），尽力恢复后再退出
    try { if ($script:OriginalRect) { Restore-OriginalRect } } catch { }
    # 异常路径也要走完整收尾：只关本次拉起的 PID、把前台还给原窗口。
    # 漏了这两步，FATAL 后桌面上会多留一个客户端并顶掉用户的焦点。
    try {
        if (-not $DryRun -and ($script:LaunchedByUs -or $CloseAfter) -and $script:LaunchedPid -gt 0) {
            taskkill /PID $script:LaunchedPid /T /F 2>$null | Out-Null
        }
    } catch { }
    try { Restore-Foreground } catch { }
    try {
        $m = "FATAL: " + $_.Exception.Message + " @ " + $_.InvocationInfo.PositionMessage
        $p = "$PSScriptRoot\..\logs\trae_claim.json"
        [System.IO.File]::WriteAllText($p, (ConvertTo-Json -Compress @{ status = 'failed'; detail = $m }))
    } catch { }
    break
}

Add-Type -AssemblyName System.Drawing
Add-Type -AssemblyName System.Runtime.WindowsRuntime

Add-Type @"
using System;
using System.Runtime.InteropServices;
public static class Cap32 {
  [DllImport("user32.dll")] public static extern bool SetProcessDPIAware();
  [DllImport("user32.dll")] public static extern bool GetWindowRect(IntPtr hWnd, out RECT rect);
  // 2026-10-08: needed by Reset-WindowRect (clamping an off-screen cold-start rect)
  [DllImport("user32.dll")] public static extern bool SetWindowPos(IntPtr hWnd, IntPtr hWndInsertAfter, int X, int Y, int cx, int cy, uint uFlags);
  [DllImport("user32.dll")] public static extern int GetSystemMetrics(int nIndex);
  [DllImport("user32.dll")] public static extern IntPtr GetForegroundWindow();
  [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr hWnd);
  [DllImport("user32.dll")] public static extern bool SetCursorPos(int X, int Y);
  // 方案甲 BringBack-Click：点击前保存、点击后恢复物理光标（A3 日志断言用）
  [DllImport("user32.dll")] public static extern bool GetCursorPos(out POINT lpPoint);
  [DllImport("user32.dll")] public static extern void mouse_event(uint flags, uint dx, uint dy, uint data, UIntPtr extra);
  [DllImport("user32.dll")] public static extern bool EnumWindows(EnumProc cb, IntPtr lp);
  [DllImport("user32.dll")] public static extern uint GetWindowThreadProcessId(IntPtr hWnd, out uint pid);
  [DllImport("user32.dll")] public static extern bool IsWindowVisible(IntPtr hWnd);
  // 2026-10-11: needed by Find-TargetWindow. Electron 客户端同 pid 下会有
  // Chrome_WidgetWin_0 这类「推广/活动」辅助窗口（实测 Trae 也有，空标题、
  // 渲染前纯黑、尺寸随内容变），只按面积选窗必然翻车（LobsterAI 10-03 踩过）。
  [DllImport("user32.dll", CharSet = CharSet.Unicode)] public static extern int GetClassName(IntPtr hWnd, System.Text.StringBuilder lpClassName, int nMaxCount);
  [DllImport("user32.dll", CharSet = CharSet.Unicode)] public static extern int GetWindowTextW(IntPtr hWnd, System.Text.StringBuilder lpString, int nMaxCount);
  [DllImport("user32.dll")] public static extern bool ShowWindow(IntPtr hWnd, int nCmdShow);
  [DllImport("user32.dll")] public static extern void keybd_event(byte bVk, byte bScan, uint dwFlags, UIntPtr dwExtraInfo);
  [DllImport("user32.dll")] public static extern bool AttachThreadInput(uint idAttach, uint idAttachTo, bool fAttach);
  [DllImport("kernel32.dll")] public static extern uint GetCurrentThreadId();
  [DllImport("user32.dll")] public static extern bool IsIconic(IntPtr hWnd);
  // 2026-10-29：最大化窗口 SetWindowPos 移不动；屏外停放前要先 SW_RESTORE。
  [DllImport("user32.dll")] public static extern bool IsZoomed(IntPtr hWnd);
  [DllImport("user32.dll")] public static extern bool PrintWindow(IntPtr hWnd, IntPtr hdcBlt, uint nFlags);
  [DllImport("user32.dll")] public static extern IntPtr SendMessageTimeout(IntPtr hWnd, uint msg, UIntPtr wParam, IntPtr lParam, uint fuFlags, uint uTimeout, out IntPtr lpdwResult);
  [DllImport("user32.dll")] public static extern bool ScreenToClient(IntPtr hWnd, ref POINT lpPoint);
  [DllImport("user32.dll")] public static extern IntPtr WindowFromPoint(POINT p);
  [DllImport("user32.dll")] public static extern IntPtr ChildWindowFromPointEx(IntPtr hWnd, POINT p, uint flags);
  [DllImport("user32.dll")] public static extern bool GetLastInputInfo(ref LASTINPUTINFO plii);
  [DllImport("kernel32.dll")] public static extern uint GetTickCount();
  public struct RECT { public int Left, Top, Right, Bottom; }
  public struct POINT { public int X, Y; }
  public struct LASTINPUTINFO { public uint cbSize; public uint dwTime; }
  public delegate bool EnumProc(IntPtr hWnd, IntPtr lp);
}
"@

$null = [Windows.Media.Ocr.OcrEngine, Windows.Foundation, ContentType = WindowsRuntime]
$null = [Windows.Globalization.Language, Windows.Foundation, ContentType = WindowsRuntime]
$null = [Windows.Graphics.Imaging.SoftwareBitmap, Windows.Foundation, ContentType = WindowsRuntime]
$null = [Windows.Storage.Streams.InMemoryRandomAccessStream, Windows.Foundation, ContentType = WindowsRuntime]

$asTaskGeneric = ([System.WindowsRuntimeSystemExtensions].GetMethods() | Where-Object {
    $_.Name -eq 'AsTask' -and $_.GetParameters().Count -eq 1 -and
    $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncOperation`1'
})[0]

function Await($WinRtOp, $ResultType) {
    $asTask = $asTaskGeneric.MakeGenericMethod($ResultType)
    $netTask = $asTask.Invoke($null, @($WinRtOp))
    $netTask.Wait(-1) | Out-Null
    return $netTask.Result
}

$script:SavedForeground = [IntPtr]::Zero
# BringBack-Click 专用：移回屏内时临时提到最前 / 点完降回（2026-10-24）。
$script:HWND_TOPMOST = New-Object System.IntPtr(-1)
$script:HWND_NOTOPMOST = New-Object System.IntPtr(-2)
# 方案甲 M1/M4 必须定义在任何调用点之前（本脚本函数是顺序生效的：
# trap/Out-Json/屏外停放都可能在文件中后部函数定义执行前触发）。
function Move-OffscreenNow {
    # M1：整窗停到主屏左界外。SWP_NOSIZE|SWP_NOZORDER|SWP_NOACTIVATE(0x0015)——
    # 绝不激活。坐标用实测宽度动态计算（R7：多显示器/DPI 不写死）。
    if (-not $Offscreen) { return }
    if ($hwnd -eq [IntPtr]::Zero) { return }
    $cr = New-Object Cap32+RECT
    [Cap32]::GetWindowRect($hwnd, [ref]$cr) | Out-Null
    $w = $cr.Right - $cr.Left
    if ($w -le 0) { return }
    [Cap32]::SetWindowPos($hwnd, [IntPtr]::Zero, (-($w + 64)), 0, 0, 0, 0x0015) | Out-Null
}

function Restore-OriginalRect {
    # M4：关闭前把窗口移回启动 rect，防 Electron 持久化屏外位置（R1）。
    if (-not $script:OriginalRect) { return }
    if ($hwnd -eq [IntPtr]::Zero) { return }
    try {
        if ($script:WasZoomed) {
            [Cap32]::ShowWindow($hwnd, 3) | Out-Null   # SW_MAXIMIZE
            Log "restore-rect: maximized (was zoomed)"
            return
        }
        $r = $script:OriginalRect
        # 2026-11-11：位置和尺寸都还原（只回位置会让被钳过/改过的尺寸留下）。
        [Cap32]::SetWindowPos($hwnd, [IntPtr]::Zero, $r.Left, $r.Top,
            ($r.Right - $r.Left), ($r.Bottom - $r.Top), 0x0014) | Out-Null
        $chk = New-Object Cap32+RECT
        [Cap32]::GetWindowRect($hwnd, [ref]$chk) | Out-Null
        # A3 断言：关闭前 rect == 启动 rect
        Log ("restore-rect: now " + $chk.Left + "," + $chk.Top + " " + ($chk.Right-$chk.Left) + "x" + ($chk.Bottom-$chk.Top) + " (expect " + $r.Left + "," + $r.Top + " " + ($r.Right-$r.Left) + "x" + ($r.Bottom-$r.Top) + ")")
        if ($script:WasMinimized) {
            [Cap32]::ShowWindow($hwnd, 6) | Out-Null   # SW_MINIMIZE：原来最小化就还它最小化
            Log "restore-rect: minimized (was iconic)"
        }
    } catch { try { Log ("restore-rect failed: " + $_.Exception.Message) } catch { } }
}
function Save-Foreground {
    if ($script:SavedForeground -eq [IntPtr]::Zero) {
        $f = [Cap32]::GetForegroundWindow()
        if ($f -ne $hwnd) { $script:SavedForeground = $f }
    }
}
function Restore-Foreground {
    try {
        if ($script:SavedForeground -ne [IntPtr]::Zero) {
            # 用户已经切走并在操作时不要再抢回来。
            if ((Get-IdleMs) -lt 8000) { [void](Log "restore-foreground: 用户正在操作，跳过抢回前台"); return }
            [Cap32]::SetForegroundWindow($script:SavedForeground) | Out-Null
        }
    } catch { }
}

function Get-IdleSeconds {
    $li = New-Object Cap32+LASTINPUTINFO
    $li.cbSize = [uint32][System.Runtime.InteropServices.Marshal]::SizeOf($li)
    if (-not [Cap32]::GetLastInputInfo([ref]$li)) { return 999999 }
    $tick = [uint32][Cap32]::GetTickCount()
    return [int]((($tick - $li.dwTime) -band 0xFFFFFFFF) / 1000)
}
function Get-IdleMs {
    $li = New-Object Cap32+LASTINPUTINFO
    $li.cbSize = [uint32][System.Runtime.InteropServices.Marshal]::SizeOf($li)
    if (-not [Cap32]::GetLastInputInfo([ref]$li)) { return 1000000 }
    $tick = [uint32][Cap32]::GetTickCount()
    $ms = [int]((($tick - $li.dwTime) -band 0xFFFFFFFF))
    if ($ms -gt 1000000) { return 1000000 }
    return $ms
}
function Wait-InputQuiet([int]$QuietMs = 320, [int]$MaxWaitMs = 20000) {
    # 点击前闸门：主人正在动鼠标/敲键盘时先等，停手后立刻点、点完立刻还原光标。
    $start = Get-Date
    $deadline = $start.AddMilliseconds($MaxWaitMs)
    $logged = $false
    while ($true) {
        $idle = Get-IdleMs
        if ($idle -ge $QuietMs) {
            if ($logged) { [void](Log ("input-quiet: 已静默 " + $idle + "ms，开始点击（等了 " + [int]((Get-Date) - $start).TotalMilliseconds + "ms）")) }
            return $true
        }
        if (-not $logged) {
            [void](Log ("input-quiet: 用户正在操作（idle=" + $idle + "ms），等键鼠停下再点（上限 " + $MaxWaitMs + "ms）"))
            $logged = $true
        }
        if ((Get-Date) -ge $deadline) {
            [void](Log ("input-quiet: 等待 " + $MaxWaitMs + "ms 仍有键鼠输入，按最小暴露继续"))
            return $false
        }
        Start-Sleep -Milliseconds 25
    }
}
function Test-CursorAt([int]$x, [int]$y) {
    $p = [Cap32+POINT]::new()
    if (-not [Cap32]::GetCursorPos([ref]$p)) { return $false }
    return ($p.X -eq $x -and $p.Y -eq $y)
}

function Wait-ForegroundIdle {
    # 仅前台补签需要闸门；屏外模式不动前台，不在此等待。
    # Log 会 Write-Output，必须 [void] 掉，否则返回值被日志污染成数组，
    # 调用方的 -not 判断失效（2026-10-23 实测：打印了 aborting 却继续跑）。
    if (-not $Foreground) { return $true }
    if ($IdleWaitSec -le 0) { return $true }
    $idle = Get-IdleSeconds
    if ($idle -ge $IdleThresholdSec) { [void](Log ("idle gate: idle=" + $idle + "s, proceed")); return $true }
    [void](Log ("idle gate: user active (idle=" + $idle + "s), wait up to " + $IdleWaitSec + "s"))
    $deadline = (Get-Date).AddSeconds($IdleWaitSec)
    $lastLog = $idle
    while ((Get-Date) -lt $deadline) {
        Start-Sleep -Seconds 5
        $idle = Get-IdleSeconds
        if ($idle -ge $IdleThresholdSec) { [void](Log ("idle gate: idle=" + $idle + "s, proceed")); return $true }
        if (($idle - $lastLog) -ge 120) { [void](Log ("idle gate: still active (idle=" + $idle + "s)")); $lastLog = $idle }
    }
    [void](Log ("idle gate: still active after " + $IdleWaitSec + "s; aborting foreground claim"))
    return $false
}

function Out-Json([string]$status, [string]$detail, [int]$Amount = 0) {
    # 方案甲 M4：任何收尾之前先把窗口移回启动 rect——Electron 会把窗口位置
    # 持久化进自己的 config，留着屏外位置关闭，下次冷启动窗口还在屏外。
    if ($script:OriginalRect) { Restore-OriginalRect }
    # 运行结束一律恢复现场：关掉本次拉起的实例（签到前就开着的保留），并把前台
    # 还给运行前的窗口。失败时也不留窗口——无人值守跑完桌面不该堆着客户端。
    # $CloseAfter：客户端由调用方冷启动（本脚本启动前进程已存在），调用方显式
    # 告知「该关」的场景，见参数注释（2026-10-14 修复）。
    if (-not $DryRun -and ($script:LaunchedByUs -or $CloseAfter)) {
        # 只关本次拉起的进程树：按镜像名 /IM 会把用户中途自己打开的实例一起杀掉。
        if ($script:LaunchedPid -gt 0) {
            taskkill /PID $script:LaunchedPid /T /F 2>$null | Out-Null
            $detail = $detail + "；已关闭本次启动的客户端"
        } else {
            [void](Log "cleanup: launched pid unknown, skip closing to avoid killing user's instance")
        }
    }
    Restore-Foreground
    # $Amount>0 时同时给两个出口：detail 里的 `[granted] N` 标记走
    # checkin.py 的 _parse_granted（框架已认这个约定，external 脚本也这么报），
    # 独立字段给人和 JSON 消费方看。
    if ($Amount -gt 0) {
        $payload = @{ status = $status; detail = $detail; amount = $Amount } | ConvertTo-Json -Compress
    } else {
        $payload = @{ status = $status; detail = $detail } | ConvertTo-Json -Compress
    }
    if ($OutFile) {
        [System.IO.File]::WriteAllText($OutFile, $payload, (New-Object System.Text.UTF8Encoding($false)))
    }
    Write-Output $payload
    if ($status -eq "ok" -or $status -eq "already") { exit 0 }
    exit 2
}

$null = [Cap32]::SetProcessDPIAware()

# exe 路径由 -ProcessName 推导。旧版这里是单引号字面量
# '$env:APPDATA\AppData\Local\Programs\TRAE SOLO CN\TRAE SOLO CN.exe'
# ——单引号里的 $ 不展开，是条恒假路径，一直靠调用方显式传 -ExePath 掩盖。
# 改成派生后，缺 -ExePath 也能走冷启动自愈分支。
if (-not $ExePath) {
    $ExePath = Join-Path $env:LOCALAPPDATA "Programs\$ProcessName\$ProcessName.exe"
}
$exe = $ExePath

# OCR 布局落盘：调锚点全靠它。失败路径也要写，否则永远看不到二跳页面长什么样。
$dumpPath = "$root\logs\ocr_dump_trae.txt"
function Dump-Ocr($lines, $tag) {
    if (-not $lines) { return }
    try {
        $stamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
        # 行级 + 词级都写：黑底白字的按钮（如「签到」）经常整行漏检，只有词级能看出它有没有被认出来
        $lines_txt = ($lines | ForEach-Object {
            $wtxt = ""
            if ($_.words) { $wtxt = " {" + (($_.words | ForEach-Object { $_.text }) -join ",") + "}" }
            "{0} | {1},{2} {3}x{4}{5}" -f $_.text, $_.x, $_.y, $_.w, $_.h, $wtxt
        }) -join "`n"
        [System.IO.File]::AppendAllText($dumpPath, "[$stamp] $tag`n$lines_txt`n---`n", (New-Object System.Text.UTF8Encoding($false)))
    } catch { }
}

# 页面是否真的变了。点入口后如果页面纹丝不动，说明点击没生效——最常见原因是
# 本脚本没提权，而 $ProcessName 跑在更高完整性级别，mouse_event 会被 UIPI 丢掉。
# 不区分这种情况的话，首页的引导文案会被当成签到锚点，静默点错位置。
function Get-SigSet($lines) {
    $s = @{}
    if ($lines) { foreach ($l in $lines) { $s[$l.text] = $true } }
    return $s
}

function Test-SamePage($before, $lines) {
    $b = Get-SigSet $lines
    if (-not $before -or $before.Count -eq 0 -or $b.Count -eq 0) { return $false }
    $inter = 0
    foreach ($k in $before.Keys) { if ($b.ContainsKey($k)) { $inter++ } }
    $union = $before.Count + $b.Count - $inter
    if ($union -le 0) { return $false }
    return (($inter / $union) -gt 0.9)
}

function Get-WinClass([IntPtr]$h) {
    $sb = New-Object System.Text.StringBuilder 256
    [void][Cap32]::GetClassName($h, $sb, 256)
    return $sb.ToString()
}

function Get-WinTitle([IntPtr]$h) {
    $sb = New-Object System.Text.StringBuilder 512
    [void][Cap32]::GetWindowTextW($h, $sb, 512)
    return $sb.ToString()
}

function Find-TargetWindow {
    # 主窗口 = **可见 + class 不是辅助窗口 + 标题非空 + 面积最大**。
    #
    # 2026-10-11：原实现只按「可见 + 宽>500 + 高>400 + 面积最大」筛，**既不看 class
    # 也不看标题**。Electron 客户端的推广/活动窗口是 `Chrome_WidgetWin_0`、标题为空、
    # 首绘前纯黑、尺寸随活动内容变化——一旦它比主窗口大就会被选中，之后所有 OCR 与
    # 点击都在一个黑窗口上（LobsterAI 2026-10-03 的「必然选中黑窗」就是这处；
    # MiniMax 同源）。Trae 合并版同样有这类窗口，故补齐同一条修复。
    # MainWindowHandle 会指向 tiny helper popup，所以仍需枚举。
    $script:BestHwnd = [IntPtr]::Zero
    $script:BestArea = 0
    $script:HiddenCands = New-Object System.Collections.ArrayList
    $script:WinProbe = New-Object System.Collections.ArrayList
    # 2026-11-03：Trae CN 冷启动会同时拉起 Agent(SOLO) 和 Code 两个主窗口，
    # 签到主流程锚点为 Agent 窗口（SOLO Lite）设计。面积相同时「先枚举到」会随机
    # 命中 IDE 窗口。
    # 这里把所有合格主窗口收集下来，由 Select-CodeModeWindow 按 OCR 内容挑选。
    $script:MainCandidates = New-Object System.Collections.ArrayList
    $pidSet = @{}
    Get-Process -Name $ProcessName -ErrorAction SilentlyContinue | ForEach-Object { $pidSet[[uint32]$_.Id] = $true }
    if ($pidSet.Count -eq 0) { return [IntPtr]::Zero }
    $cb = [Cap32+EnumProc]{
        param($h, $lp)
        $owner = [uint32]0
        [Cap32]::GetWindowThreadProcessId($h, [ref]$owner) | Out-Null
        if ($pidSet.ContainsKey($owner)) {
            $r = New-Object Cap32+RECT
            [Cap32]::GetWindowRect($h, [ref]$r) | Out-Null
            $w = $r.Right - $r.Left
            $hh = $r.Bottom - $r.Top
            $vis = [Cap32]::IsWindowVisible($h)
            $iconic = [Cap32]::IsIconic($h)
            $cls = Get-WinClass $h
            $title = Get-WinTitle $h
            $big = ($w -gt 500 -and $hh -gt 400)
            if ($big) {
                [void]$script:WinProbe.Add(("{0} vis={1} cls={2} title='{3}' {4}x{5}" -f `
                    ([int]$h), $vis, $cls, $title, $w, $hh))
            }
            # 三条硬条件，缺一不可。黑窗/推广浮层因此永远不入选。
            if ($vis -and -not $iconic -and $big -and $cls -ne 'Chrome_WidgetWin_0' -and $title -and $title.Trim()) {
                [void]$script:MainCandidates.Add([pscustomobject]@{ H = $h; Area = ($w * $hh) })
                if (($w * $hh) -gt $script:BestArea) {
                    $script:BestHwnd = $h
                    $script:BestArea = $w * $hh
                }
            }
            # 2026-10-29：关到托盘时主窗口是隐藏的（WS_VISIBLE=off），rect/标题
            # 都在。2026-11-29：最小化窗口的 rect 会缩成 -32000,-32000 314x50，
            # 不能再要求 $big；否则托盘/最小化实例会被误等 60s 后报 notfound。
            if ($cls -eq 'Chrome_WidgetWin_1' -and $title -and $title.Trim() -and ((-not $vis) -or $iconic)) {
                [void]$script:HiddenCands.Add([pscustomobject]@{
                    H = $h; Title = $title; Area = ($w * $hh); W = $w; HH = $hh })
            }
        }
        return $true
    }
    [Cap32]::EnumWindows($cb, [IntPtr]::Zero) | Out-Null
    $script:MainCandidates = @($script:MainCandidates | Sort-Object Area -Descending)
    return $script:BestHwnd
}

function Restore-HiddenTraeWindow {
    # 关到托盘后主窗口 WS_VISIBLE=off，旧逻辑只认可见窗口，于是白等 60 秒。
    # 每次只还原一个尚未处理的隐藏窗口；调用方随后重新枚举，把可见候选并入队列。
    if (-not $script:HiddenCands -or $script:HiddenCands.Count -eq 0) { return [IntPtr]::Zero }
    if ($null -eq $script:RestoredHiddenHandles) { $script:RestoredHiddenHandles = @{} }
    if ($null -eq $script:HiddenOriginalState) { $script:HiddenOriginalState = @{} }
    $best = $script:HiddenCands | Sort-Object Area -Descending | Where-Object {
        -not $script:RestoredHiddenHandles.ContainsKey([string]$_.H)
    } | Select-Object -First 1
    if (-not $best) { return [IntPtr]::Zero }
    # ShowWindow(9) 会把最大化窗口变成还原态；按句柄保存，避免多窗口互相污染。
    $script:HiddenOriginalState[[string]$best.H] = [pscustomobject]@{
        WasZoomed = [Cap32]::IsZoomed($best.H)
        WasMinimized = [Cap32]::IsIconic($best.H)
    }
    $script:RestoredHiddenHandles[[string]$best.H] = $true
    [void](Log ("main window hidden (tray?); restoring hwnd=" + $best.H + " title='" + $best.Title + "'"))
    [Cap32]::ShowWindow($best.H, 9) | Out-Null   # SW_RESTORE
    Start-Sleep -Milliseconds 900
    return $best.H
}

# 2026-11-03：多窗口场景（Agent + Code 同时拉起）需要对每个候选窗口做
# 轻量 OCR 来区分模式。Get-QuickOcrText 不依赖全局 $hwnd/$winW，
# 只对传入句柄做一次 PrintWindow + OCR，返回文本行数组（已去空白）。
function Get-QuickOcrText([IntPtr]$h) {
    if ($h -eq [IntPtr]::Zero) { return @() }
    $r = New-Object Cap32+RECT
    [Cap32]::GetWindowRect($h, [ref]$r) | Out-Null
    $w = $r.Right - $r.Left
    $hgt = $r.Bottom - $r.Top
    if ($w -le 0 -or $hgt -le 0) { return @() }
    $bmp = New-Object System.Drawing.Bitmap($w, $hgt)
    $g = [System.Drawing.Graphics]::FromImage($bmp)
    $hdc = $g.GetHdc()
    [Cap32]::PrintWindow($h, $hdc, 2) | Out-Null
    $g.ReleaseHdc($hdc)
    $g.Dispose()
    $ms = New-Object System.IO.MemoryStream
    $bmp.Save($ms, [System.Drawing.Imaging.ImageFormat]::Png)
    $bmp.Dispose()
    $stream = New-Object Windows.Storage.Streams.InMemoryRandomAccessStream
    $writer = New-Object Windows.Storage.Streams.DataWriter($stream.GetOutputStreamAt(0))
    $writer.WriteBytes($ms.ToArray())
    $ms.Dispose()
    Await ($writer.StoreAsync()) ([uint32]) | Out-Null
    Await ($writer.FlushAsync()) ([bool]) | Out-Null
    $decoder = Await ([Windows.Graphics.Imaging.BitmapDecoder]::CreateAsync($stream)) ([Windows.Graphics.Imaging.BitmapDecoder])
    $softBmp = Await ($decoder.GetSoftwareBitmapAsync()) ([Windows.Graphics.Imaging.SoftwareBitmap])
    $engine = [Windows.Media.Ocr.OcrEngine]::TryCreateFromLanguage([Windows.Globalization.Language]::new("zh-Hans-CN"))
    if (-not $engine) { $engine = [Windows.Media.Ocr.OcrEngine]::TryCreateFromUserProfileLanguages() }
    if (-not $engine) { return @() }
    $result = Await ($engine.RecognizeAsync($softBmp)) ([Windows.Media.Ocr.OcrResult])
    $lines = @()
    foreach ($line in $result.Lines) {
        $text = ($line.Text -replace "\s", "")
        if (-not [string]::IsNullOrWhiteSpace($text)) { $lines += $text }
    }
    return $lines
}

function Select-CodeModeWindow {
    # 2026-11-03：Trae CN 冷启动会同时拉起两个主窗口，同尺寸时按面积选窗会随机命中。
    # 当日晚间实测纠正（用户指正 + computer-use 实签验证）：
    #   Agent 窗口（SOLO Lite，OCR 特征「SOLO / 轻松应对 / 和智能体对话」）才是主流程
    #     目标——签到入口在左下角头像菜单/左侧栏签到卡，本脚本的全套锚点都为它设计。
    #   IDE/Code 窗口（文件菜单/资源管理器）：没有左侧栏签到卡和左下账户条，头像在
    #     窗口上栏（IDE 模式贴右上，距右缘约 245px），主流程锚点在这里全找不到。
    # 所以打分【奖励】SOLO 首页特征——与 00:43 初版方向相反（初版误把它当废窗口）。
    if (-not $script:MainCandidates -or $script:MainCandidates.Count -le 1) {
        return $hwnd
    }
    $bestH = [IntPtr]::Zero
    $bestScore = -9999
    foreach ($c in $script:MainCandidates) {
        $texts = Get-QuickOcrText $c.H
        $joined = ($texts -join " ")
        $score = 0
        $hits = @()
        # 权重（2026-11-05 重排）：目标窗口 = **带签到入口/账户条的那个窗口**，
        # SOLO/IDE 模式特征只当平手时的 tiebreak，不许再盖过入口特征。
        # 依据两轮实况：
        #   11-04 01:20 签成：胜出窗口 score=24，靠的是账户条特征（每日领/用户N/免费），
        #     切过去后点 @50,1073 直接命中「每日领（可领 100）」。
        #   11-05 09:11 失败：SOLO 首页窗 score=21 > 账户条窗 10，选中的窗口左下角根本没有
        #     账户条，候选点 @59,1089 点在空白上 → 「未找到签到入口」。旧权重里
        #     SOLO(8)+轻松应对(6)+首页引导(5) 就能压过 用户N(5)+免费(3)，方向是反的。
        if ($joined -match '每日领') { $score += 40; $hits += '每日领' }
        if ($joined -match '用户\s*\d+') { $score += 20; $hits += '用户N' }
        if ($joined -match '免费') { $score += 12; $hits += '免费' }
        # 裸「签到」会被任务标题污染（今天 SOLO 窗里的「检查今日签…」就是白送 +2 的），
        # 只认签到入口的固定搭配。
        if ($joined -match '每日签到|立即签到|签到领|签到得') { $score += 10; $hits += '签到入口' }
        if ($joined -match 'SOLO') { $score += 3; $hits += 'SOLO' }
        if ($joined -match '轻松应对') { $score += 2; $hits += '轻松应对' }
        if ($joined -match '和智能体对话|开始你的第一个任务') { $score += 2; $hits += '首页引导' }
        $preview = if ($joined.Length -gt 80) { $joined.Substring(0, 80) } else { $joined }
        Log ("window-scan hwnd=" + $c.H + " area=" + $c.Area + " score=" + $score +
             " hits=[" + ($hits -join ",") + "] text=" + $preview) | Out-Null
        if ($score -gt $bestScore) { $bestScore = $score; $bestH = $c.H }
    }
    if ($bestH -ne [IntPtr]::Zero) { return $bestH }
    return $hwnd
}

# 前台补签的空闲闸门：在枚举/移动窗口之前，用户活跃就留 pending。
if (-not (Wait-ForegroundIdle)) {
    Out-Json "pending" ("用户正在使用电脑（空闲 < " + $IdleThresholdSec + "s），已取消前台补签；未枚举/移动/点击窗口，等空闲后再试")
}

$script:LaunchedByUs = $false
$script:LaunchedPid = 0
$preexistingApp = @(Get-Process -Name $ProcessName -ErrorAction SilentlyContinue)
$hwnd = Find-TargetWindow
$script:WasMinimized = ($hwnd -ne [IntPtr]::Zero) -and [Cap32]::IsIconic($hwnd)
# 把「同 pid 且够大」的全部候选窗口落盘。选窗出问题时（比如又选中了推广黑窗）
# 这份清单是第一手证据，不用再重新写一遍枚举脚本。
try {
    $pick = if ($hwnd -ne [IntPtr]::Zero) { "PICK hwnd=$hwnd area=$($script:BestArea)" } else { "PICK none" }
    $candInfo = ""
    if ($script:MainCandidates -and $script:MainCandidates.Count -gt 0) {
        $candInfo = "  candidates=" + (($script:MainCandidates | ForEach-Object { "$($_.H)(area=$($_.Area))" }) -join ",") + "`n"
    }
    [System.IO.File]::AppendAllText("$root\logs\_trae_windows.txt",
        ("[{0}] {1} {2}`n" -f (Get-Date -Format "yyyy-MM-dd HH:mm:ss"), $ProcessName, $pick) +
        $candInfo +
        (($script:WinProbe | ForEach-Object { "  $_" }) -join "`n") + "`n")
} catch { }

if ($hwnd -eq [IntPtr]::Zero) {
    # 2026-10-29：先尝试把托盘里的主窗口还原，成功就重新枚举；还原失败再走
    # 原来的「隐藏/托盘 → pending」提示，不误杀主人开着的实例。
    $restored = Restore-HiddenTraeWindow
    if ($restored -ne [IntPtr]::Zero) {
        $hwnd = Find-TargetWindow
        Log ("after hidden-window restore, target hwnd=" + $hwnd)
    }
}
if ($hwnd -eq [IntPtr]::Zero) {
    # 主窗口被隐藏（Trae 关窗 = 最小化到托盘）时不能当「没开」处理：报 notfound
    # 会误导成「客户端有问题」，实际只要主人把窗口打开就能签。
    $hiddenMain = @($script:WinProbe | Where-Object { $_ -match 'vis=False' -and $_ -match 'Chrome_WidgetWin_1' })
    if ($hiddenMain.Count -gt 0) {
        Out-Json "pending" "$ProcessName 在运行但主窗口处于隐藏/托盘状态，找不到可签到的窗口；请打开客户端窗口后重跑（本次未做任何点击）"
    }
    # Self-heal: background survivors can never regain a window, so clear them
    # and start fresh -- but ONLY when the client was not already running for the
    # user. Killing an instance the human had open is never acceptable.
    if ($preexistingApp.Count -eq 0) {
        # 只清「没有主窗口」的后台残留；用户中途自己开的正常实例有窗口，不动它。
        # 按镜像名 /IM 全杀会把那种实例一起带走（2026-11-11 审计）。
        $stale = @(Get-Process -Name $ProcessName -ErrorAction SilentlyContinue | Where-Object { $_.MainWindowHandle -eq 0 })
        foreach ($p in $stale) { taskkill /PID $p.Id /T /F 2>$null | Out-Null }
        if ($stale.Count -gt 0) { Start-Sleep -Seconds 3 }
        if (Test-Path $exe) {
            $proc = Start-Process $exe -PassThru
            $script:LaunchedByUs = $true
            $script:LaunchedPid = [int]$proc.Id
        }
    }
    $dl = (Get-Date).AddSeconds(60)
    while ((Get-Date) -lt $dl) {
        Start-Sleep -Seconds 2
        $hwnd = Find-TargetWindow
        if ($hwnd -ne [IntPtr]::Zero) { break }
    }
    if ($hwnd -eq [IntPtr]::Zero) { Out-Json "notfound" "$ProcessName 启动后 60s 内未出现主窗口（本环境冷启动该客户端会失败，请手动打开后重跑）" }
}

# Foreground helpers: OCR is only trustworthy when $ProcessName is really in front.
# 用户正在操作电脑时会把窗口挤到后台，单靠 SetForegroundWindow 常常切不回来
# （Windows 会拒绝非前台进程的切换请求）。逐级加码：还原 → Alt 技巧 → 绑输入队列强切。
function Ensure-Foreground {
    Save-Foreground
    if ([Cap32]::GetForegroundWindow() -eq $hwnd) { return $true }

    if ([Cap32]::IsIconic($hwnd)) {
        [Cap32]::ShowWindow($hwnd, 9) | Out-Null   # SW_RESTORE
        Start-Sleep -Milliseconds 400
        if ([Cap32]::GetForegroundWindow() -eq $hwnd) { return $true }
    }

    # Alt 技巧：按下 Alt（不起）再切，Windows 通常放行，随后补 keyup
    [Cap32]::keybd_event(0x12, 0, 0, [UIntPtr]::Zero) | Out-Null
    [Cap32]::SetForegroundWindow($hwnd) | Out-Null
    [Cap32]::keybd_event(0x12, 0, 0x0002, [UIntPtr]::Zero) | Out-Null
    Start-Sleep -Milliseconds 500
    if ([Cap32]::GetForegroundWindow() -eq $hwnd) { return $true }

    # 绑输入队列后强切
    $targetTid = [uint32]0
    [Cap32]::GetWindowThreadProcessId($hwnd, [ref]$targetTid) | Out-Null
    $curTid = [Cap32]::GetCurrentThreadId()
    if ($targetTid -ne 0) {
        [Cap32]::AttachThreadInput($curTid, $targetTid, $true) | Out-Null
        [Cap32]::ShowWindow($hwnd, 9) | Out-Null
        [Cap32]::SetForegroundWindow($hwnd) | Out-Null
        [Cap32]::AttachThreadInput($curTid, $targetTid, $false) | Out-Null
        Start-Sleep -Milliseconds 500
    }
    return ([Cap32]::GetForegroundWindow() -eq $hwnd)
}

function Wait-Foreground {
    if ([Cap32]::GetForegroundWindow() -eq $hwnd) { return $true }
    $dl = (Get-Date).AddSeconds(45)
    while ((Get-Date) -lt $dl) {
        if (Ensure-Foreground) { return $true }
        Start-Sleep -Milliseconds 600
    }
    return $false
}

function Get-OcrLinesSafe {
    # 屏外模式下抢前台无收益且打扰用户焦点（方案甲），直接截屏即可。
    if (-not $Offscreen) { try { Ensure-Foreground | Out-Null } catch { } }
    return Get-OcrLines
}

# --- window rect sanity: force it back on-screen -----------------------
# 2026-10-08: Trae had NO equivalent of LobsterAI's Reset-WindowRect, and
# that is why it kept failing. Cold start restores the window to a rect larger
# than the desktop (observed win=3866x2090 on a 3840x2160 screen, click target
# y=2031 — off the bottom). Symptoms looked like "OCR sees the workspace but
# never the check-in entry": the anchor lives in the bottom-left, which is
# exactly the part hanging off-screen. LobsterAI fixed the same class of bug
# on 2026-10-03; this is the port of that fix.
$sw = [Cap32]::GetSystemMetrics(0)
$sh = [Cap32]::GetSystemMetrics(1)
function Reset-WindowRect {
    param([IntPtr]$h)
    $rr = New-Object Cap32+RECT
    [Cap32]::GetWindowRect($h, [ref]$rr) | Out-Null
    $w = $rr.Right - $rr.Left
    $hgt = $rr.Bottom - $rr.Top
    if ($w -le 0 -or $hgt -le 0) { return $false }
    if ($rr.Left -ge 0 -and $rr.Top -ge 0 -and $rr.Right -le $sw -and $rr.Bottom -le $sh) { return $false }
    if ($w -gt $sw) { $w = $sw }
    if ($hgt -gt $sh) { $hgt = $sh }
    $nx = [Math]::Max(0, [Math]::Min($rr.Left, $sw - $w))
    $ny = [Math]::Max(0, [Math]::Min($rr.Top, $sh - $hgt))
    # SWP_NOZORDER(0x0004) | SWP_NOACTIVATE(0x0010)
    [Cap32]::SetWindowPos($h, [IntPtr]::Zero, $nx, $ny, $w, $hgt, 0x0014) | Out-Null
    Start-Sleep -Milliseconds 400
    return $true
}

# 每个候选窗口的 rect 快照、屏外停放和恢复都在 Invoke-TraeWindowClaim 内完成；
# 这里不再提前改动窗口，避免后续候选继承上一个窗口的坐标/最大化状态。

function Test-Blank($bmp) {
    $first = $bmp.GetPixel([int]($winW / 2), [int]($winH / 2))
    for ($i = 1; $i -le 8; $i++) {
        $px = [int]($winW * $i / 9)
        for ($j = 1; $j -le 8; $j++) {
            $py = [int]($winH * $j / 9)
            $c = $bmp.GetPixel($px, $py)
            if ($c.R -ne $first.R -or $c.G -ne $first.G -or $c.B -ne $first.B) { return $false }
        }
    }
    return $true
}

function Get-OcrLines {
    # 方案甲 R2：屏外窗口受 backgroundThrottling 影响，首帧可能 2-8s 才画出
    # 内容（PoC 实测）——PrintWindow 抓到空白帧时重试（2s 间隔，上限 30s），
    # 且绝不走 CopyFromScreen 兜底：屏外坐标的屏幕捕获拍到的是用户屏幕内容。
    $bmp = $null
    # 2026-10-30：上限 15→5（30s→8s）。持续空白帧多等也自愈不了，反而吃光外层预算。
    $maxTry = 1
    if ($Offscreen) { $maxTry = 5 }
    for ($tryN = 1; $tryN -le $maxTry; $tryN++) {
        $bmp = New-Object System.Drawing.Bitmap($winW, $winH)
        $g = [System.Drawing.Graphics]::FromImage($bmp)
        # PrintWindow: works without the window being in the foreground / visible,
        # and also when the window is parked off-screen (同一桌面，DWM 照常合成)。
        $hdc = $g.GetHdc()
        $pw = [Cap32]::PrintWindow($hwnd, $hdc, 2)
        $g.ReleaseHdc($hdc)
        if ($pw -and -not (Test-Blank $bmp)) { $g.Dispose(); break }
        if (-not $Offscreen) {
            # Fall back to screen capture when it yields a blank frame.
            $g.CopyFromScreen($winX, $winY, 0, 0, $bmp.Size)
            $g.Dispose()
            break
        }
        $g.Dispose()
        if ($tryN -lt $maxTry) {
            if ($tryN -eq 1) { [void](Log "step: 屏外捕获空白帧，2s 间隔重试（backgroundThrottling 容忍）") }
            $bmp.Dispose()
            Start-Sleep -Seconds 2
        }
    }
    $ms = New-Object System.IO.MemoryStream
    $bmp.Save($ms, [System.Drawing.Imaging.ImageFormat]::Png)
    # 保留同一帧，供像素级定位（黑底白字按钮 OCR 漏检，只能靠像素找）
    try { $script:ShotBmp = $bmp.Clone() } catch { }
    $bmp.Dispose()
    $stream = New-Object Windows.Storage.Streams.InMemoryRandomAccessStream
    $writer = New-Object Windows.Storage.Streams.DataWriter($stream.GetOutputStreamAt(0))
    $writer.WriteBytes($ms.ToArray())
    $ms.Dispose()
    Await ($writer.StoreAsync()) ([uint32]) | Out-Null
    Await ($writer.FlushAsync()) ([bool]) | Out-Null
    $decoder = Await ([Windows.Graphics.Imaging.BitmapDecoder]::CreateAsync($stream)) ([Windows.Graphics.Imaging.BitmapDecoder])
    $softBmp = Await ($decoder.GetSoftwareBitmapAsync()) ([Windows.Graphics.Imaging.SoftwareBitmap])
    $engine = [Windows.Media.Ocr.OcrEngine]::TryCreateFromLanguage([Windows.Globalization.Language]::new("zh-Hans-CN"))
    if (-not $engine) { $engine = [Windows.Media.Ocr.OcrEngine]::TryCreateFromUserProfileLanguages() }
    if (-not $engine) { return @() }
    $result = Await ($engine.RecognizeAsync($softBmp)) ([Windows.Media.Ocr.OcrResult])
    $lines = @()
    foreach ($line in $result.Lines) {
        $text = ($line.Text -replace "\s", "")
        if ([string]::IsNullOrWhiteSpace($text)) { continue }
        $minX = 999999; $minY = 999999; $maxX = 0; $maxY = 0
        foreach ($wd in $line.Words) {
            $r = $wd.BoundingRect
            if ($r.X -lt $minX) { $minX = [int]$r.X }
            if ($r.Y -lt $minY) { $minY = [int]$r.Y }
            if (($r.X + $r.Width) -gt $maxX) { $maxX = [int]($r.X + $r.Width) }
            if (($r.Y + $r.Height) -gt $maxY) { $maxY = [int]($r.Y + $r.Height) }
        }
        $wds = @()
        foreach ($wd in $line.Words) {
            $wr = $wd.BoundingRect
            $wds += @{ text = ($wd.Text -replace "\s", ""); x = [int]$wr.X; y = [int]$wr.Y; w = [int]$wr.Width; h = [int]$wr.Height }
        }
        $lines += @{ text = $text; x = $minX; y = $minY; w = ($maxX - $minX); h = ($maxY - $minY); words = $wds }
    }
    return $lines
}

function Find-Line($lines, [string]$needle) {
    foreach ($l in $lines) {
        if ($l.text.Contains($needle)) { return $l }
    }
    return $null
}

# 按「词」而不是「行」定位点击目标。OCR 常把相邻元素并成一行
# （实测出现过「灵感与活动每日签到赚积分」整行），取整行中心会点到旁边那个元素上。
function Find-WordHit($lines, [string]$needle) {
    foreach ($l in $lines) {
        if (-not $l.words) { continue }
        if (-not $l.text.Contains($needle)) { continue }
        # 先试单词直接命中
        foreach ($w in $l.words) {
            if ($w.text.Contains($needle)) {
                return @{ text = $w.text; x = $w.x; y = $w.y; w = $w.w; h = $w.h }
            }
        }
        # 再试连续词拼接命中（OCR 把词组拆成多个 word 的情况）
        for ($i = 0; $i -lt $l.words.Count; $i++) {
            $acc = ""
            for ($j = $i; $j -lt [Math]::Min($i + 6, $l.words.Count); $j++) {
                $acc += $l.words[$j].text
                if ($acc.Contains($needle)) {
                    $first = $l.words[$i]
                    $last = $l.words[$j]
                    return @{
                        text = $acc
                        x    = $first.x; y = $first.y
                        w    = ($last.x + $last.w - $first.x); h = $first.h
                    }
                }
            }
        }
    }
    return $null
}

function Find-CheckinAnchor($lines) {
    # Exact match only: the homepage has a "每日签到赚积分" banner that would
    # fool a Contains match and make us skip navigation entirely.
    foreach ($l in $lines) {
        if ($l.text -eq "每日签到") { return $l }
    }
    foreach ($l in $lines) {
        if ($l.text.StartsWith("每日签到") -and $l.text -notmatch "赚|积分|得|领") { return $l }
    }
    return $null
}

# 候选比较：先看离入口行谁更近（药丸垂直居中在入口行上），同样近才比宽度。
# 不能只取「最长区段」——菜单右边界之外是更暗的应用背景，也是一段长对比区段。
function Add-PillCandidate($best, [int]$runStart, [int]$len, [int]$yy, [int]$bg, [int]$rowY) {
    $cand = @{ x = [int]($runStart + ($len / 2)); y = $yy; len = $len; bg = $bg }
    if (-not $best) { return $cand }
    $dCand = [Math]::Abs($yy - $rowY)
    $dBest = [Math]::Abs([int]$best.y - $rowY)
    if ($dCand -lt $dBest) { return $cand }
    if ($dCand -eq $dBest -and $len -gt [int]$best.len) { return $cand }
    return $best
}

# 签到按钮是「签到」两个字，但 OCR 漏检它（旧版黑底白字、新版深灰底白字都漏），
# 所以只能靠像素找。**关键是别用绝对亮度阈值**：
#   旧实现找 R,G,B 都 < 90 的像素。这在浅色主题下等于「找深色药丸」，能用；
#   但 2026-10-11 起客户端菜单是**深色卡片**（底色 ~32），阈值把整片底色都判成
#   按钮，回了一段 356px 的假区段（真按钮只有 ~138px），点击全部落空。
# 正确判据是**与当前行底色的对比**：行底色取该行像素的众数，再找长度 >= 40px
# 且与底色差 >= 6 的连续区段。深色药丸(42) on 深底(32)、浅底上的深药丸，都成立。
function Get-RowBg([System.Drawing.Bitmap]$bmp, [int]$yy, [int]$x0, [int]$x1) {
    $hist = @{}
    for ($x = $x0; $x -lt $x1; $x++) {
        $c = $bmp.GetPixel($x, $yy)
        $b = [int](($c.R + $c.G + $c.B) / 3 / 4) * 4   # 4 级分桶，抗轻微噪点
        if ($hist.ContainsKey($b)) { $hist[$b]++ } else { $hist[$b] = 1 }
    }
    $bestB = -1; $bestN = -1
    foreach ($k in $hist.Keys) { if ($hist[$k] -gt $bestN) { $bestN = $hist[$k]; $bestB = $k } }
    return $bestB
}

function Find-ButtonPill([int]$rowY, [int]$x0, [int]$x1) {
    try {
        if ($x1 -gt $winW) { $x1 = $winW - 1 }
        if ($x0 -lt 0) { $x0 = 0 }
        if ($x1 -le $x0) { return $null }
        $bmp = $script:ShotBmp
        if (-not $bmp) {
            $bmp = New-Object System.Drawing.Bitmap($winW, $winH)
            $g = [System.Drawing.Graphics]::FromImage($bmp)
            $hdc = $g.GetHdc()
            $pw = [Cap32]::PrintWindow($hwnd, $hdc, 2)
            $g.ReleaseHdc($hdc)
            if (-not $pw -or (Test-Blank $bmp)) { $g.CopyFromScreen($winX, $winY, 0, 0, $bmp.Size) }
            $g.Dispose()
        }
        # 多行扫描：药丸可能比说明文字略高或略低，也可能只有 hover 后才渲染
        $best = $null
        $log = New-Object System.Collections.ArrayList
        for ($yy = ($rowY - 30); $yy -le ($rowY + 90); $yy += 4) {
            if ($yy -lt 0 -or $yy -ge $winH) { continue }
            $bg = Get-RowBg $bmp $yy $x0 $x1
            $runStart = -1
            for ($x = $x0; $x -lt $x1; $x++) {
                $c = $bmp.GetPixel($x, $yy)
                $lum = [int](($c.R + $c.G + $c.B) / 3)
                $contrast = ($lum - $bg)
                if ($contrast -lt 0) { $contrast = -$contrast }
                $on = ($contrast -ge 6)
                if ($on -and $runStart -lt 0) { $runStart = $x }
                if (-not $on -and $runStart -ge 0) {
                    $len = $x - $runStart
                    if ($len -ge 40 -and $len -le 260) { $best = Add-PillCandidate $best $runStart $len $yy $bg $rowY }
                    $runStart = -1
                }
            }
            if ($runStart -ge 0) {
                $len = $x1 - $runStart
                if ($len -ge 40 -and $len -le 260) { $best = Add-PillCandidate $best $runStart $len $yy $bg $rowY }
            }
            if ([Math]::Abs($yy - $rowY) -lt 7) {
                $samples = New-Object System.Collections.ArrayList
                for ($sx2 = $x0; $sx2 -lt $x1; $sx2 += 6) {
                    $cc = $bmp.GetPixel($sx2, $yy)
                    [void]$samples.Add("$sx2`:$($cc.R),$($cc.G),$($cc.B)")
                }
                [void]$log.Add("row=$yy bg=$bg " + ($samples -join ' '))
            }
        }
        try {
            $lns = "$(Get-Date -Format HH:mm:ss) x0=$x0 x1=$x1 src=" + $(if ($script:ShotBmp) { 'ocr-frame' } else { 'fresh' }) + " " + ($log -join ' | ') + " best=" + $(if ($best) { "$($best.x),$($best.y) len=$($best.len) bg=$($best.bg)" } else { 'none' }) + "`n"
            [System.IO.File]::AppendAllText("$PSScriptRoot\..\logs\_scan.txt", $lns)
        } catch { }
        if (-not $script:ShotBmp) { $bmp.Dispose() }
        if ($best) { return $best }
    } catch { }
    return $null
}

# 账户菜单里的积分余额（形如「3，527」，千分位是全角逗号）。
# 这是**唯一可靠的「这次点击到底有没有到账」判据**：文本「今日已签」只在领取的
# 那一次菜单会话里出现，重开菜单又会变回「每日领100积分」（2026-10-11 实测），
# 所以「重开菜单→看有没有已签文案」这种方式根本判不出已签。
# 读不到返回 -1，此时退回文本判据（宁可漏记不可虚记）。
function Find-Balance($lines) {
    # 不能锚行首：OCR 经常把账户条整行并成一个文本
    # （实测「．用户712942281“．免费3，527」），余额会跟在用户名后面。
    # 取「第一个含千分位数字的行」里的**最后一个**匹配——账户条上余额在最右。
    # 2026-10-25：余额只在左侧账户菜单里（实测 @455,1038）。不限制 x 时，聊天区
    # 的任意数字（「3655,3644」「877,125」之类）会被读成余额，把到账复核带偏；
    # 10-25 那轮 bal0=877125 就是从对话正文里抓的。
    $xMax = [int]($winW * 0.35)
    foreach ($l in $lines) {
        if (-not $l.text) { continue }
        if ($l.x -ge $xMax) { continue }
        $val = -1
        foreach ($m in [regex]::Matches($l.text, '([0-9]{1,3}(?:[，,][0-9]{3})+)')) {
            $val = [int]($m.Groups[1].Value -replace '[，,]', '')
        }
        if ($val -gt 0) { return $val }
    }
    return -1
}

# ── 2026-10-13 改版修复 ─────────────────────────────────────────────────────
# 2026-10-09 Trae 与 TraeCode 合并为 TRAE，客户端 UI 随之改版：
#   ① 账户条不再显示积分余额（旧「用户71294228173 免费 3,527」-> 新「0用户71294228173免费」），
#      所以 Find-Balance 的千分位正则恒匹配不到、返回 -1，余额判据整体失效
#      （10-12、10-13 连续两天「复核余额 -1 -> -1」就是它）。
#   ② 签到卡片常驻左侧栏底部，不再藏在头像菜单里，且**三态文案互斥**（实测）：
#        未签  ：每日领100积分 / 升级会员，每日多领100积分   按钮 [签到] [升级权益]
#        刚领取：今日签到，已获得100积分。下次可在头像菜单中签到。 按钮 [今日已签(3s)]
#        已签  ：夺会员首月立减¥30 / 升级会员立即获得大额积分…  按钮 [立即升级]
#   ③ 于是「已获得N积分」比余额差更可靠——它直接给出实发额度（服务端随时调额，
#      免费日额度 2026-09-30 就从 150 改成 100，写死 catalog 必然失真）；
#      而入口词「每日领」在已签后整块消失，本身就是干净的幂等闸门。
# 结论：主判据换成 granted，Find-Balance 降级为备用（保留以应对 UI 再次改版）。

# 判据正则集中在这里：scripts/test_trae_states.py 会从源码里把它们抠出来做回归，
# 避免「脚本里改了正则、测试里还是旧的」这种漂移。改动务必同步跑那个测试。
$RE_GRANTED  = '已\s*获\s*得\s*(\d+)\s*积分'
$RE_GRANTED2 = '获\s*得\s*(\d+)\s*积分'
$RE_OFFER    = '每日领\s*(\d+)\s*积分'
$RE_ALREADY  = '升级会员立即获得|立即升级'
$RE_SIGNBTN  = '^签到$'

# 刚领取那一帧卡片上的实发额度：「已获得100积分」。返回 0 表示没读到。
function Find-Granted($lines) {
    foreach ($l in $lines) {
        if (-not $l.text) { continue }
        # 主：卡片文案「已获得100积分」。字符间允许空白——实测 OCR 会把
        # 「头像」拆成「头亻象」，相邻字有抖动，别把间隔写死。
        $m = [regex]::Match($l.text, $RE_GRANTED)
        if (-not $m.Success) {
            # 备：「获得100积分」（OCR 偶尔漏掉「已」）
            $m = [regex]::Match($l.text, $RE_GRANTED2)
        }
        if ($m.Success) {
            $v = 0
            if ([int]::TryParse($m.Groups[1].Value, [ref]$v)) { return $v }
        }
    }
    return 0
}

# 未签卡片上的可领额度：「每日领100积分」。只作交叉校验，不用于入账
# （点了才知道实发多少）。
function Find-OfferAmount($lines) {
    foreach ($l in $lines) {
        if (-not $l.text) { continue }
        $m = [regex]::Match($l.text, $RE_OFFER)
        if ($m.Success) {
            $v = 0
            if ([int]::TryParse($m.Groups[1].Value, [ref]$v)) { return $v }
        }
    }
    return 0
}

# 已签态：签到卡片被会员推广替换，页面上不再有任何签到字样。
function Test-AlreadyCard($lines) {
    foreach ($l in $lines) {
        if (-not $l.text) { continue }
        if ($l.text -match $RE_ALREADY) { return $true }
    }
    return $false
}

# 2026-10-13：按钮不在入口文字的同一行，而在卡片下方（实测入口「每日领100积分」
# @94,1514、按钮「签到」@145,1622，相差 108px）。旧逻辑在入口行右侧做像素扫描
# 找「药丸」，新布局里扫到的是背景深色块（实测 x=664 len=235），于是退化成
# 按 offset 连猜 4 次才碰中。改为按 OCR 短文本在入口行下方定位。
function Find-SignButton($lines, [int]$entryY) {
    $xMax = [int]($winW * 0.35)
    $best = $null
    foreach ($l in $lines) {
        if (-not $l.words) { continue }
        # 按钮是 2 字短文本；左侧栏历史任务名（「配置Trae每日自动签到」）也含
        # 「签到」但是长文本，用它排除。
        if ($l.text.Length -gt 4) { continue }
        if ($l.text -notmatch $RE_SIGNBTN) { continue }
        if ($l.x -ge $xMax) { continue }
        if ($l.y -le $entryY) { continue }
        if (($l.y - $entryY) -gt 260) { continue }
        if (-not $best -or $l.y -lt $best.y) { $best = $l }
    }
    return $best
}

# --- 方案甲：屏外点击的三级机制（M1/M4 的定义在文件头部，调用点更早） --------

function Send-SynthMouse([int]$ax, [int]$ay, [switch]$HoverOnly) {
    # 合成鼠标消息（WM_MOUSEMOVE/WM_LBUTTONDOWN/UP）送到窗口消息队列。
    # 与窗口屏幕位置无关：客户区相对坐标在屏外同样有效（方案甲第一级，
    # 零屏幕暴露）。坐标一律按窗口**当前**位置换算：非屏外模式等同于原逻辑。
    $cr = New-Object Cap32+RECT
    [Cap32]::GetWindowRect($hwnd, [ref]$cr) | Out-Null
    $sx = $cr.Left + $ax
    $sy = $cr.Top + $ay

    # Resolve the deepest child window under the point: with Electron/CEF the
    # top-level window only forwards input, the renderer child is what really
    # handles a click. Sending to the top-level window alone does nothing.
    # Prefer the real top-most window at that point: Electron popup menus may be
    # a separate window rather than a child of the main one, and sending to the
    # main window then does nothing. Verify it belongs to the same process.
    # （屏外时 WindowFromPoint 命中不到任何窗口，target 自然落回主窗口。）
    $sp = [Cap32+POINT]::new()
    $sp.X = $sx
    $sp.Y = $sy
    $top = [Cap32]::WindowFromPoint($sp)
    $target = $hwnd
    if ($top -ne [IntPtr]::Zero) {
        $pidTop = [uint32]0
        [Cap32]::GetWindowThreadProcessId($top, [ref]$pidTop) | Out-Null
        $pidMain = [uint32]0
        [Cap32]::GetWindowThreadProcessId($hwnd, [ref]$pidMain) | Out-Null
        if ($pidTop -eq $pidMain) { $target = $top }
    }
    $cp = [Cap32+POINT]::new()
    $cp.X = $sx
    $cp.Y = $sy
    [Cap32]::ScreenToClient($target, [ref]$cp) | Out-Null
    for ($k = 0; $k -lt 4; $k++) {
        $c = [Cap32]::ChildWindowFromPointEx($target, $cp, 1)
        if ($c -eq [IntPtr]::Zero -or $c -eq $target) { break }
        $target = $c
        $cp.X = $sx
        $cp.Y = $sy
        [Cap32]::ScreenToClient($target, [ref]$cp) | Out-Null
    }

    $lp = [IntPtr]((($cp.Y -band 0xFFFF) * 65536) -bor ($cp.X -band 0xFFFF))
    $res = [IntPtr]::Zero
    # Hover first: Electron only renders the dark "签到" button on hover, so a
    # bare WM_LBUTTONDOWN at its coordinates lands on nothing.
    [Cap32]::SendMessageTimeout($target, 0x0200, [UIntPtr]::Zero, $lp, 0, 1000, [ref]$res) | Out-Null
    $script:LastSynthTarget = $target
    if ($HoverOnly) { return $true }
    Start-Sleep -Milliseconds 200
    $r1 = [Cap32]::SendMessageTimeout($target, 0x0201, [UIntPtr]::new([uint64]1), $lp, 0, 1500, [ref]$res)
    Start-Sleep -Milliseconds 90
    $r2 = [Cap32]::SendMessageTimeout($target, 0x0202, [UIntPtr]::Zero, $lp, 0, 1500, [ref]$res)
    return ($r1 -ne [IntPtr]::Zero -and $r2 -ne [IntPtr]::Zero)
}

function Send-SynthEsc {
    # ESC 的屏外等价物：keybd_event 会落到用户的前台窗口，绝不能发；
    # WM_KEYDOWN/UP 直投客户端消息队列，与位置无关。
    $res = [IntPtr]::Zero
    [Cap32]::SendMessageTimeout($hwnd, 0x0100, [UIntPtr]::new([uint64]0x1B), [IntPtr]::Zero, 0, 1000, [ref]$res) | Out-Null
    Start-Sleep -Milliseconds 60
    [Cap32]::SendMessageTimeout($hwnd, 0x0101, [UIntPtr]::new([uint64]0x1B), [IntPtr]::Zero, 0, 1000, [ref]$res) | Out-Null
}

function Invoke-AtPoint([int]$ax, [int]$ay) {
    # 方案甲 M2（第二级）：UIA InvokePattern。COM 与窗口位置无关，屏外也能
    # Invoke。找 BoundingRectangle 包含目标点且支持 Invoke 的最小元素。
    # 任何异常都视为「找不到」——调用方继续走 BringBack-Click（R5：Invoke
    # 后是否真点中，由原有点击后判据 OCR 复核裁定，这里不做任何重试）。
    try {
        Add-Type -AssemblyName UIAutomationClient -ErrorAction SilentlyContinue
        Add-Type -AssemblyName UIAutomationTypes -ErrorAction SilentlyContinue
        $cr = New-Object Cap32+RECT
        [Cap32]::GetWindowRect($hwnd, [ref]$cr) | Out-Null
        $px = $cr.Left + $ax
        $py = $cr.Top + $ay
        $rootEl = [System.Windows.Automation.AutomationElement]::FromHandle($hwnd)
        if (-not $rootEl) { return $false }
        $walker = [System.Windows.Automation.TreeWalker]::RawViewWalker
        $best = $null
        $bestArea = [double]::MaxValue
        $budget = 2000
        $stack = New-Object System.Collections.Stack
        $stack.Push($rootEl)
        while ($stack.Count -gt 0 -and $budget -gt 0) {
            $el = $stack.Pop()
            $budget--
            if (-not $el) { continue }
            try {
                $rc = $el.Current.BoundingRectangle
                if ($rc.Width -le 0 -or $rc.Height -le 0) { continue }
                if ($px -lt $rc.Left -or $px -ge $rc.Right -or $py -lt $rc.Top -or $py -ge $rc.Bottom) { continue }
                $area = $rc.Width * $rc.Height
                $pat = $null
                if ($area -lt $bestArea -and $el.TryGetCurrentPattern([System.Windows.Automation.InvokePattern]::Pattern, [ref]$pat)) {
                    $best = $el
                    $bestArea = $area
                }
                $kid = $walker.GetFirstChild($el)
                while ($kid -and $budget -gt 0) {
                    $stack.Push($kid)
                    $kid = $walker.GetNextSibling($kid)
                }
            } catch { }
        }
        if (-not $best) { Log ("uia: no invokable element @ " + $ax + "," + $ay); return $false }
        $pat2 = $null
        if (-not $best.TryGetCurrentPattern([System.Windows.Automation.InvokePattern]::Pattern, [ref]$pat2)) { return $false }
        ([System.Windows.Automation.InvokePattern]$pat2).Invoke()
        Log ("uia: invoked '" + $best.Current.Name + "' @ " + $ax + "," + $ay)
        return $true
    } catch {
        Log ("uia: " + $_.Exception.Message)
        return $false
    }
}

function Test-ClickVisible([int]$cx, [int]$cy) {
    # 项目铁律 4 反遮挡（R3）：点击点上最顶层的窗口必须属于客户端进程，
    # 否则真实点击会落到别人的窗口上。
    $sp = [Cap32+POINT]::new()
    $sp.X = $cx
    $sp.Y = $cy
    $top = [Cap32]::WindowFromPoint($sp)
    if ($top -eq [IntPtr]::Zero) { return $false }
    $pidTop = [uint32]0
    [Cap32]::GetWindowThreadProcessId($top, [ref]$pidTop) | Out-Null
    $pidMain = [uint32]0
    [Cap32]::GetWindowThreadProcessId($hwnd, [ref]$pidMain) | Out-Null
    return ($pidTop -eq $pidMain)
}

function BringBack-Click([int]$ax, [int]$ay) {
    # 方案甲 M3（第三级）：窗口移回点击位 → 保存光标 → 真实点击 → 恢复光标
    # → 移回屏外。点击位默认原位，被遮挡则试 (0,0)，再不行放弃（pending 由
    # 后继判据裁定，不重试——SAFETY 第 3 条）。
    $spots = @(@($winX, $winY), @(0, 0))
    $placed = $false
    $cx = 0
    $cy = 0
    # 2026-10-24 修复：原来移回屏内用 0x0015（含 NOZORDER），窗口维持原 z 序——
    # 只要停放时它不是最顶层（用户前台有别的窗口，或像 10-24 实测那样窗口本身就
    # 贴满全屏 3866x2090），点击位顶层永远是别人的窗口，两个落点全被 R3 拦下，
    # 真实点击根本发不出去。改为移回时临时提为 TOPMOST（0x0011=NOSIZE|NOACTIVATE：
    # 不抢焦点，曝光仍 ~100ms），点完立刻降回。反遮挡检查保留——raise 后顶层
    # 必是本进程，过得了 Test-ClickVisible。
    foreach ($s in $spots) {
        [Cap32]::SetWindowPos($hwnd, $script:HWND_TOPMOST, $s[0], $s[1], 0, 0, 0x0011) | Out-Null
        Start-Sleep -Milliseconds 300
        $cx = $s[0] + $ax
        $cy = $s[1] + $ay
        if (Test-ClickVisible $cx $cy) { $placed = $true; break }
        Log ("bringback: spot " + $s[0] + "," + $s[1] + " 被遮挡")
    }
    if (-not $placed) {
        Log "bringback: 两个点击位都被遮挡，跳过真实点击"
        [Cap32]::SetWindowPos($hwnd, $script:HWND_NOTOPMOST, 0, 0, 0, 0, 0x0013) | Out-Null
        Move-OffscreenNow
        return
    }
    # 2026-10-25：窗口不激活时，Chromium/React 会吞掉「第一次」真实点击（只完成
    # 激活），账户条因此点不开——00:57 前台/屏外两种模式都实测过：点击坐标正确、
    # 但菜单没出现。TOPMOST 只解决遮挡，不解决激活；这里在点击前显式抢一次前台，
    # 点完立刻把前台还给主人（Save/Restore-Foreground）。
    # 2026-11-11：先等主人停手、再抢前台；等到超时仍活跃就放弃，避免按键/点击
    # 落到主人当前所在的窗口。
    if (-not (Wait-InputQuiet 320 20000)) {
        [void](Log "bringback: 用户持续操作，放弃本次真实点击")
        [Cap32]::SetWindowPos($hwnd, $script:HWND_NOTOPMOST, 0, 0, 0, 0, 0x0013) | Out-Null
        Move-OffscreenNow
        return
    }
    Save-Foreground
    try { [void](Ensure-Foreground) } catch { }
    Start-Sleep -Milliseconds 150
    $saved = [Cap32+POINT]::new()
    [Cap32]::GetCursorPos([ref]$saved) | Out-Null
    $clicked = $false
    try {
        for ($attempt = 1; $attempt -le 2 -and -not $clicked; $attempt++) {
            if ($attempt -gt 1) {
                if (-not (Wait-InputQuiet 320 20000)) { [void](Log "bringback: 用户持续操作，放弃重试"); break }
            }
            [Cap32]::SetCursorPos($cx, $cy) | Out-Null
            Start-Sleep -Milliseconds 120
            if (-not (Test-CursorAt $cx $cy)) {
                [void](Log ("bringback: 光标被挪走（attempt " + $attempt + "），不盲点"))
                continue
            }
            if ([Cap32]::GetForegroundWindow() -ne $hwnd) {
                [void](Log ("bringback: 前台已被切走（attempt " + $attempt + "），不盲点"))
                break
            }
            [Cap32]::mouse_event(0x0002, 0, 0, 0, [UIntPtr]::Zero)
            [Cap32]::mouse_event(0x0004, 0, 0, 0, [UIntPtr]::Zero)
            $clicked = $true
        }
        [Cap32]::SetCursorPos($saved.X, $saved.Y) | Out-Null
        if ($clicked) {
            [void](Log ("bringback: real click @ " + $cx + "," + $cy + " (cursor saved " + $saved.X + "," + $saved.Y + ")"))
        } else {
            [void](Log ("bringback: 光标两次都被挪走，放弃本次点击 @ " + $cx + "," + $cy))
        }
    } finally {
        # R4：任何异常路径都要恢复光标并重新停到屏外
        [Cap32]::SetCursorPos($saved.X, $saved.Y) | Out-Null
        $now = [Cap32+POINT]::new()
        [Cap32]::GetCursorPos([ref]$now) | Out-Null
        # A3 断言：点击前后 GetCursorPos 一致
        Log ("bringback: cursor restored " + $now.X + "," + $now.Y + " (expect " + $saved.X + "," + $saved.Y + ")")
        # 摘掉 TOPMOST（0x0013=NOSIZE|NOMOVE|NOACTIVATE），避免窗口日后回屏内
        # 时一直钉在最上层打扰用户
        [Cap32]::SetWindowPos($hwnd, $script:HWND_NOTOPMOST, 0, 0, 0, 0, 0x0013) | Out-Null
        # 把前台还给主人原来的窗口，再回屏外（顺序同 Qoder：先还焦点，再置顶条带）
        Restore-Foreground
        Move-OffscreenNow
    }
}

function Click-At([int]$ax, [int]$ay, [switch]$SkipSynth) {
    $cr = New-Object Cap32+RECT
    [Cap32]::GetWindowRect($hwnd, [ref]$cr) | Out-Null
    $sx = $cr.Left + $ax
    $sy = $cr.Top + $ay

    # 1) If we already own the foreground, use REAL input injection. Synthetic
    #    messages opened the account menu but never triggered the dark button;
    #    real input is what the app actually reacts to.
    #    （屏外模式不走这条：窗口永不抢前台，且屏外坐标不能直接真实点击。）
    if (-not $Offscreen -and [Cap32]::GetForegroundWindow() -eq $hwnd) {
        [Cap32]::SetCursorPos($sx, $sy) | Out-Null
        Start-Sleep -Milliseconds 120
        [Cap32]::mouse_event(0x0002, 0, 0, 0, [UIntPtr]::Zero)
        [Cap32]::mouse_event(0x0004, 0, 0, 0, [UIntPtr]::Zero)
        try {
            $ln = "$(Get-Date -Format HH:mm:ss) mode=mouse-fg target=$hwnd ax=$ax ay=$ay win=" + $winW + "x" + $winH + "`n"
            [System.IO.File]::AppendAllText("$PSScriptRoot\..\logs\_clickmode.txt", $ln)
        } catch { }
        return
    }

    # 2) Otherwise deliver the click straight into the window's message queue.
    #    屏外模式下这是第一级（与位置无关，零暴露）；对「签到」黑按钮无效是
    #    已知事实，调用方对那类点击传 -SkipSynth 直接走 UIA → 移回真实点击。
    if (-not $SkipSynth) {
        $msgOk = Send-SynthMouse $ax $ay
        $mode = 'msg-fail'
        if ($msgOk) { $mode = 'msg-ok' }
        try {
            $line = "$(Get-Date -Format HH:mm:ss) mode=$mode target=$($script:LastSynthTarget) ax=$ax ay=$ay win=" + $winW + "x" + $winH + "`n"
            [System.IO.File]::AppendAllText("$PSScriptRoot\..\logs\_clickmode.txt", $line)
        } catch { }
        if ($msgOk) { return }
    }

    if ($Offscreen) {
        # 3) UIA InvokePattern（与位置无关）；4) 移回屏内一次真实点击。
        # 不能直接 if (Invoke-AtPoint ...)：函数里的 Log 走输出流，失败时会返回
        # 「日志字符串 + $false」的非空数组，被当成真 -> 兜底真实点击永远不执行
        # （2026-10-22 实锤：菜单被点关但余额不变，且日志无 bringback 记录）。
        $uiaOut = @(Invoke-AtPoint $ax $ay)
        if ($uiaOut -contains $true) { return }
        BringBack-Click $ax $ay
        return
    }

    [Cap32]::SetCursorPos($sx, $sy) | Out-Null
    Start-Sleep -Milliseconds 120
    [Cap32]::mouse_event(0x0002, 0, 0, 0, [UIntPtr]::Zero)
    [Cap32]::mouse_event(0x0004, 0, 0, 0, [UIntPtr]::Zero)
}

# 广告层必须同时有「明确推广标记」和「明确关闭控件」才成立。单独的关闭按钮
# 可能是编辑器标签/窗口按钮，绝不能盲点；单独出现的会员文案也只是普通业务卡片。
function Find-AdMarker($lines) {
    foreach ($l in $lines) {
        if (-not $l.text) { continue }
        # 只用强广告文案。「升级会员/立即升级」也是已签后的常驻推广卡，
        # 不能仅凭它判断有弹窗，否则会把窗口/侧栏的关闭控件误当广告关闭。
        if ($l.text -match '会员首月立减|限时优惠|促销活动|专属优惠') { return $l }
    }
    return $null
}

function Find-AdPixelClose($marker) {
    # 广告卡的小 x 常被 OCR 整帧漏掉。只在强广告标题所在的左侧卡片内找暗像素
    # 连通团，绝不扫描全窗/猜窗口关闭按钮；点击后仍由新 OCR 验证广告是否消失。
    if (-not $marker -or -not $script:ShotBmp) { return $null }
    $bmp = $script:ShotBmp
    # 标题只占卡片宽度的一小半，x 在标题右侧约 170px；卡片宽度随窗口缩放。
    $x1 = [Math]::Max(0, [int]($marker.x + $marker.w + 20))
    $x2 = [Math]::Min($bmp.Width - 1, [int]($marker.x + [Math]::Max($marker.w + 300, $winW * 0.24)))
    $y1 = [Math]::Max(0, [int]($marker.y - 16))
    $y2 = [Math]::Min($bmp.Height - 1, [int]($marker.y + $marker.h + 24))
    if ($x2 -le $x1 -or $y2 -le $y1) { return $null }

    # 找 4 邻域连通团。小 x 是约 10x10 的独立部件；文字笔画要么太小，要么
    # 宽/高超过 24px。比「取 22px 暗像素最多的方框」更不容易选中标点。
    $remaining = New-Object 'System.Collections.Generic.HashSet[int]'
    for ($y = $y1; $y -le $y2; $y++) {
        for ($x = $x1; $x -le $x2; $x++) {
            $c = $bmp.GetPixel($x, $y)
            if ([Math]::Max($c.R, [Math]::Max($c.G, $c.B)) -lt 190) {
                [void]$remaining.Add(($y * $bmp.Width + $x))
            }
        }
    }
    $best = $null; $bestScore = 0
    while ($remaining.Count -gt 0) {
        $seed = [System.Linq.Enumerable]::First($remaining)
        [void]$remaining.Remove($seed)
        $queue = New-Object 'System.Collections.Generic.Queue[int]'
        $queue.Enqueue($seed)
        $count = 0; $minX = $x2; $maxX = $x1; $minY = $y2; $maxY = $y1
        while ($queue.Count -gt 0) {
            $key = $queue.Dequeue(); $count++
            $px = $key % $bmp.Width; $py = [int]($key / $bmp.Width)
            if ($px -lt $minX) { $minX = $px }; if ($px -gt $maxX) { $maxX = $px }
            if ($py -lt $minY) { $minY = $py }; if ($py -gt $maxY) { $maxY = $py }
            foreach ($nkey in @(($key - 1), ($key + 1), ($key - $bmp.Width), ($key + $bmp.Width))) {
                if ($remaining.Contains($nkey)) { [void]$remaining.Remove($nkey); $queue.Enqueue($nkey) }
            }
        }
        $cw = $maxX - $minX + 1; $ch = $maxY - $minY + 1
        if ($count -lt 6 -or $count -gt 180 -or $cw -lt 5 -or $cw -gt 24 -or $ch -lt 5 -or $ch -gt 24) { continue }
        $cx = $minX + [int]($cw / 2); $cy = $minY + [int]($ch / 2)
        # 关闭键应贴近卡片右上角；同区域有多个候选时取最靠右且最靠上的。
        $score = ($cx * 10) - $cy
        if ($score -gt $bestScore) {
            $bestScore = $score
            $best = @{ x = $cx; y = $cy; w = 1; h = 1; pixels = $count }
        }
    }
    return $best
}

function Find-AdCloseControl($lines, $marker) {
    if (-not $marker) { return $null }
    # 小 x 优先，但必须位于广告卡右上角。历史上全窗最近邻误选过聊天区
    # 1528,782 的关闭图标，连点三次广告仍在。这里用广告标题锚定局部边界。
    $smallX = @()
    $xMin = [int]($marker.x + $marker.w + 20)
    $xMax = [int]($marker.x + [Math]::Max($marker.w + 300, $winW * 0.24))
    $yMin = [int]($marker.y - 16)
    $yMax = [int]($marker.y + $marker.h + 24)
    foreach ($l in $lines) {
        if (-not $l.text) { continue }
        if ($l.words) {
            foreach ($w in $l.words) {
                $cx = $w.x + [int]($w.w / 2); $cy = $w.y + [int]($w.h / 2)
                if ($w.text -match '^[×xX✕✖]$' -and $w.w -le 48 -and $w.h -le 48 -and
                    $cx -ge $xMin -and $cx -le $xMax -and $cy -ge $yMin -and $cy -le $yMax) { $smallX += $w }
            }
        }
        $cx = $l.x + [int]($l.w / 2); $cy = $l.y + [int]($l.h / 2)
        if ($l.text -match '^[×xX✕✖]$' -and $l.w -le 48 -and $l.h -le 48 -and
            $cx -ge $xMin -and $cx -le $xMax -and $cy -ge $yMin -and $cy -le $yMax) { $smallX += $l }
    }
    if ($smallX.Count -gt 0) {
        $mx = $xMax; $my = $yMin
        $closest = $smallX | Sort-Object @{ Expression = {
            [Math]::Sqrt([Math]::Pow(($_.x + [int]($_.w / 2) - $mx), 2) + [Math]::Pow(($_.y + [int]($_.h / 2) - $my), 2))
        } } | Select-Object -First 1
        return @{ Close = $closest; Kind = 'small-x' }
    }
    $pixelClose = Find-AdPixelClose $marker
    if ($pixelClose) { return @{ Close = $pixelClose; Kind = 'small-x-pixel' } }

    # 只认独立短控件，不能把「关闭侧边栏」等泛化文案当广告关闭按钮。
    foreach ($kw in @("关闭", "跳过", "我知道了", "以后再说", "稍后再说")) {
        foreach ($l in $lines) {
            if (-not $l.text) { continue }
            $norm = $l.text -replace '[\s，。！!,.…]', ''
            if ($norm -eq $kw -or $norm -eq ($kw + '广告')) { return @{ Close = $l; Kind = $kw } }
            if ($l.words) {
                foreach ($w in $l.words) {
                    if ($w.text -eq $kw) { return @{ Close = $w; Kind = $kw } }
                }
            }
        }
    }
    return $null
}

function Find-AdLayer($lines) {
    $marker = Find-AdMarker $lines
    if (-not $marker) { return $null }
    $closeInfo = Find-AdCloseControl $lines $marker
    if (-not $closeInfo) { return $null }
    return @{ Marker = $marker; Close = $closeInfo.Close; Kind = $closeInfo.Kind }
}

function Close-AdOverlays {
    # 没有广告时只读一帧并立即返回，不发送无关 ESC/点击。每处理一层都重新 OCR，
    # 绝不复用旧帧连续点多个控件；最多只确认并处理三个明确广告层。
    $adSeen = $false
    for ($layer = 1; $layer -le 3; $layer++) {
        $adLines = @(Get-OcrLines)
        $marker = Find-AdMarker $adLines
        if (-not $marker) {
            # 广告文案消失就是关闭成功；此时 $marker 为 null，绝不能拿全窗其它 x
            # 继续要求「关闭控件也消失」，否则会被无关控件误判为广告仍在。
            return $true
        }
        $info = Find-AdLayer $adLines
        if (-not $info) { return $false }
        $adSeen = $true
        $cl = $info.Close
        [void](Log ("ad-overlay: layer=" + $layer + " marker='" + $info.Marker.text + "' close=" + $info.Kind + " @" + ($cl.x + [int]($cl.w / 2)) + "," + ($cl.y + [int]($cl.h / 2))))
        # 广告卡是 Web 内容，SendMessage 常返回 true 却不触发 DOM 点击；跳过合成
        # 消息，强制 UIA Invoke，失败再移回屏内做一次真实点击。
        [void](Click-At ($cl.x + [int]($cl.w / 2)) ($cl.y + [int]($cl.h / 2)) -SkipSynth)
        Start-Sleep -Milliseconds 800
    }
    $adLines = @(Get-OcrLines)
    $marker = Find-AdMarker $adLines
    if (-not $marker) { return $true }
    return (-not (Find-AdCloseControl $adLines $marker))
}


# ---------------------------------------------------------------------------
# Trae 专属流程
#
# 已知约束（2026-09-26 逆向 + 两家自述）：
#   - 签到入口在**左下角头像菜单**（网页/手机端无入口），菜单文案与开关
#     （checkinMenuEnabled）由服务端下发，本地只有英文 fallback（Check in / Checked in）
#   - 本环境**冷启动不了**这两个客户端（进程起不来），所以默认假设客户端已打开
#   - 鉴权 token 只在 Electron 主进程内存且登录态加密 -> external 不可行，只能走 UI
# ---------------------------------------------------------------------------

# 实测（2026-09-27 头像菜单）：签到入口文案是「每日领150积分」，**不是**「签到」；
# 同一菜单里还有干扰项「升级会员，每日多领50积分」，必须靠「多领/升级/会员」排除掉。
# 截图：OCR 会把菜单项和干扰项搞混，肉眼一看就明白。排查 UI 自动化时截图比文字有用得多。
function Save-Shot($tag) {
    if (-not $ShotDir) { return }
    try {
        if (-not (Test-Path $ShotDir)) { New-Item -ItemType Directory -Path $ShotDir -Force | Out-Null }
        $bmp = New-Object System.Drawing.Bitmap($winW, $winH)
        $g = [System.Drawing.Graphics]::FromImage($bmp)
        if ($Offscreen) {
            # 屏外坐标的 CopyFromScreen 拍到的是用户屏幕内容，必须走 PrintWindow
            $hdc = $g.GetHdc()
            [Cap32]::PrintWindow($hwnd, $hdc, 2) | Out-Null
            $g.ReleaseHdc($hdc)
        } else {
            $g.CopyFromScreen($rect.Left, $rect.Top, 0, 0, $bmp.Size)
        }
        $g.Dispose()
        $bmp.Save((Join-Path $ShotDir ($tag + ".png")), [System.Drawing.Imaging.ImageFormat]::Png)
        $bmp.Dispose()
    } catch { }
}

$clickWords  = @("每日领", "签到", "Check in", "Check-in", "Checkin")
$claimWords  = @("已签到", "已领", "今日已签", "Checked in", "Checked-in")

# 2026-10-15：加 $xMax 区域限制。已签词（「今日已签」等）在左下角卡片/账户菜单，
# 恒在左侧栏；聊天面板里的对话文本（可能正好在讨论「已签」）在全窗口匹配下会
# 造成自指污染误判 already——10-15 凌晨实锤命中了一次。
function Find-AnyLine($lines, [string[]]$needles, [int]$xMax = 0) {
    foreach ($n in $needles) {
        $h = Find-Line $lines $n
        if ($h -and ($xMax -le 0 -or $h.x -lt $xMax)) { return $h }
    }
    return $null
}

# 入口词要排除「已签到」这类状态文案，否则点了个不能点的东西
# 入口匹配必须走 Find-WordHit（单词/连续词拼接）——实测 OCR 会把「每日领150积分」
# 拆成单字（每/日/领/150/积/分），Contains 匹配单字必失败。
# 干扰排除：①「升级会员，每日多领50积分」同样含「每日」；②聊天区里我们自己粘贴的
# prompt 满屏都是「签到」，必须限制在左侧栏（菜单/入口都在 x < 30% 窗口宽）。
function Test-MenuOpen($lines) {
    # 账户菜单展开后才会有这些固定菜单项（首页绝不会出现）
    foreach ($l in $lines) {
        if (-not $l.text) { continue }
        if ($l.text -match "退出登录|管理账户|报告问题") { return $true }
    }
    return $false
}

function Find-EntryWord($lines, [string[]]$needles) {
    $xMax = [int]($winW * 0.3)
    $menuOpen = Test-MenuOpen $lines
    # 2026-10-25：Find-WordHit 每个 needle 只返回**第一条**命中行。聊天区顶部的
    # 对话（「入口已找到每日领…」）在 OCR 顺序里先于左下菜单，x 检查把它 skip 后
    # 就再没机会看到菜单里的「每日领100积分」→ 菜单明明开了仍报「未找到入口」。
    # 先把候选限定在左 30%（菜单/侧栏都在这里），再让 Find-WordHit 找。
    $left = @($lines | Where-Object { $_.x -lt $xMax })
    foreach ($n in $needles) {
        $h = Find-WordHit $left $n
        if (-not $h) { continue }
        if ($h.x -ge $xMax) { continue }
        if ($h.text -match "多领|升级|会员|已") { continue }
        # 侧栏任务列表里的历史任务名（实测「配置Trae每日自动签到」@664,162、
        # 「查询签到入口与积分规则」@101,1100）同样含「签到」且落在 x<30%，
        # 会在首页就被误判成入口 -> 脚本跳过「点头像开菜单」直接点错地方。
        # 「每日领」是菜单独有的强特征，永远优先采信；其余 needle 只有在账户
        # 菜单确实展开时才认。
        if ($n -ne "每日领" -and -not $menuOpen) { continue }
        # 2026-10-25：菜单展开也不够——聊天侧栏的任务标题「检查今日签到情况」
        # 在 x<30% 且含「签到」，被当成入口点了 4 次（@850,167 等），全部落在
        # 对话标题上，余额一分没动。入口只可能是「每日领」行，或**独立短词**
        # 签到 / Check in；长句一律不认。
        if ($n -ne "每日领" -and
            $h.text -notmatch '^\s*(签到|立即签到|Check\s*-?\s*in|Checkin)\s*$') { continue }
        return $h
    }
    return $null
}

function New-TraeClaimResult([string]$Status, [string]$Detail, [int]$Amount = 0) {
    return [pscustomobject]@{ Status = $Status; Detail = $Detail; Amount = $Amount }
}

# 单窗口签到主流程。函数只返回一个结果对象；Out-Json/exit 由最外层候选循环统一收尾。
function Invoke-TraeWindowClaim {
    param([IntPtr]$TargetHandle)
    $hwnd = $TargetHandle
    if ($hwnd -eq [IntPtr]::Zero) {
        return New-TraeClaimResult 'failed' '候选窗口句柄为空'
    }

    # 每个候选独立保存/恢复，不能把上一个窗口的屏外 rect 或最大化状态带过来。
    $script:OriginalRect = $null
    $script:WasZoomed = $false
    $script:WasMinimized = $false
    try {
        $rect = New-Object Cap32+RECT
        if (-not [Cap32]::GetWindowRect($hwnd, [ref]$rect)) {
            return New-TraeClaimResult 'failed' 'GetWindowRect 失败，候选窗口可能已关闭'
        }
        $script:WasZoomed = [Cap32]::IsZoomed($hwnd)
        $script:WasMinimized = [Cap32]::IsIconic($hwnd)
        $hiddenKey = [string]$hwnd
        if ($script:HiddenOriginalState -and $script:HiddenOriginalState.ContainsKey($hiddenKey)) {
            # 隐藏窗口刚被 SW_RESTORE 出来，当前 IsZoomed 已为 false，要沿用还原前状态。
            $script:WasZoomed = $script:WasZoomed -or $script:HiddenOriginalState[$hiddenKey].WasZoomed
            $script:WasMinimized = $script:WasMinimized -or $script:HiddenOriginalState[$hiddenKey].WasMinimized
        }
        # 必须复制一份：后续 GetWindowRect 会原地修改 $rect，不能污染恢复快照。
        $savedRect = New-Object Cap32+RECT
        $savedRect.Left = $rect.Left; $savedRect.Top = $rect.Top
        $savedRect.Right = $rect.Right; $savedRect.Bottom = $rect.Bottom
        $script:OriginalRect = $savedRect

        # 先按窗口尺寸钳 rect，再刷新本候选的坐标/尺寸；屏外停放前若处于最大化需 SW_RESTORE。
        [void](Reset-WindowRect $hwnd)
        [Cap32]::GetWindowRect($hwnd, [ref]$rect) | Out-Null
        $winW = $rect.Right - $rect.Left
        $winH = $rect.Bottom - $rect.Top
        $winX = $rect.Left
        $winY = $rect.Top
        if ($winW -le 0 -or $winH -le 0) {
            return New-TraeClaimResult 'failed' '候选窗口尺寸无效'
        }
        if ($Offscreen -and [Cap32]::IsZoomed($hwnd)) {
            [Cap32]::ShowWindow($hwnd, 9) | Out-Null
            Start-Sleep -Milliseconds 2000
            [Cap32]::GetWindowRect($hwnd, [ref]$rect) | Out-Null
            $winW = $rect.Right - $rect.Left
            $winH = $rect.Bottom - $rect.Top
            $winX = $rect.Left
            $winY = $rect.Top
        }
        try { if (-not $Offscreen) { [void](Ensure-Foreground) } } catch { }
        if ($Offscreen) {
            Move-OffscreenNow
            [void](Log ("step: 窗口已停到屏外（原 rect " + $winX + "," + $winY + " " + $winW + "x" + $winH + "）"))
        }

        [void](Log "step: 窗口已定位，等 8s 让广告浮层冒头后清理")
        # 启动后的广告/弹窗会盖住主界面：等它出现再关，别一上来就清。
        Start-Sleep -Seconds 8
        $adsClosed = Close-AdOverlays
        if (-not $adsClosed) {
            $lines = @(Get-OcrLines)
            Dump-Ocr $lines "trae-ad-unresolved"
            Save-Shot "00-ad-unresolved"
            $detail = '检测到明确广告层，但关闭后广告标记/关闭控件仍未消失；未继续点击签到相关控件'
            if ($Explore) { return New-TraeClaimResult 'explore' $detail }
            return New-TraeClaimResult 'pending' $detail
        }
        Start-Sleep -Seconds 2
        [void](Log "step: OCR 首页")

$lines = Get-OcrLines
Dump-Ocr $lines "trae-home"
Save-Shot "01-home"

# 1) 首页就看得见签到入口？
$entry = Find-EntryWord $lines $clickWords
$claimed = Find-AnyLine $lines $claimWords ([int]($winW * 0.3))

# 1.5) 2026-10-15 纠正：10-13 曾实测「已签态下卡片换成会员推广」，于是把
#      「升级会员立即获得|立即升级」当成已签判据。但 10-15 用户实测：**未签到时**
#      首页同样可能只显示会员推广（签到入口只在头像菜单里，签到成功提示也写明
#      「下次可在头像菜单中签到」）。用会员推广判已签会漏签——这里**不判 already，
#      一律走下方头像菜单确认**：菜单里见「每日领N积分」就签，见「今日已签」才算已签。

# 2) 看不见入口就点左下角头像开菜单
# 2026-10-24：原来这里是 `-and -not $claimed`，只要首页上有「今日已签」就跳过开菜单。
# 实测那张卡片的状态来自客户端内存，客户端跨天没重启时会停在昨天的「已签到」上
# （10-24 00:00 实锤：卡片说已签，服务端余额一分没涨，全天漏签）。
# 所以现在「没看见入口」就一定要开菜单：菜单里的「每日领」才是可点的真入口。
if (-not $entry) {
    # 左下角用户名是稳定锚点（实测「用户71294228173」@109,1732，右边跟「免费」标签）。
    # 直接点用户名文字本身——猜头像图标坐标会时灵时不灵（实测点偏就打不开菜单），
    # 而用户名是一条明确的文本，账户菜单的触发区也覆盖它。
    $userHit = $null
    # 2026-10-13：新版账户条整行被 OCR 并成一条「0用户71294228173免费」，
    # words 是**单字数组**（{0,用,户,71294228173,免,费}），旧的
    # $w.text.StartsWith("用户") 永远匹配不到 -> 候选点一个都生成不出来，
    # 菜单根本打不开。改成按整行文本定位。
    foreach ($l in $lines) {
        if (-not $l.text) { continue }
        if ($l.text -notmatch '用户\s*\d+') { continue }
        if (-not $userHit -or $l.y -gt $userHit.y) {
            $userHit = @{ x = $l.x; y = $l.y; w = $l.w; h = $l.h; text = $l.text }
        }
    }
    if (-not $userHit) {
        # 退而求其次：会员标签「免费」也在同一账户条上
        foreach ($l in $lines) {
            if (-not $l.text) { continue }
            if ($l.text -notmatch '免费') { continue }
            if (-not $userHit -or $l.y -gt $userHit.y) {
                $userHit = @{ x = $l.x; y = $l.y; w = $l.w; h = $l.h; text = $l.text }
            }
        }
    }
    if ($userHit) {
        $ax = $userHit.x - 45
        $ay = $userHit.y + [int]($userHit.h / 2)
    }
    else {
        $ax = [int]($winW * 0.028)
        $ay = [int]($winH - ($winH * 0.028))
    }
    if ($AvatarX -gt 0) { $ax = $AvatarX }
    if ($AvatarY -gt 0) { $ay = $AvatarY }
    # 账户条（左下角）候选点击点。实测很反直觉：
    #   点「免费」标签左侧约 45px → 菜单能打开；点用户名文字中部 → 打不开。
    # 所以两个位置都生成候选点，轮流试，别把赌注压在一个坐标上。
    $accWords = @()
    foreach ($l in $lines) {
        if (-not $l.words) { continue }
        foreach ($w in $l.words) {
            if ($w.text.StartsWith("用户") -or $w.text -eq "免费") { $accWords += $w }
        }
    }
    $candidates = @()
    # 2026-10-25：$userHit 算出的锚点（账户条行 y 中心、左侧头像区）原来**从未
    # 进入候选列表**——下面 $accWords 依赖 StartsWith("用户")，而新版 OCR 的 words
    # 是单字数组 {0,用,户,71294228173,免,费}，永远匹配不到 → 只剩兜底点
    # (2.8%W, 97.2%H)=108,2031，正好落在头像右侧的空白缝里，连点 3 天都开不了菜单。
    # 把锚点作为首选候选，兜底点保留。
    if ($userHit) { $candidates += @{ x = $ax; y = $ay } }
    foreach ($w in $accWords) {
        $cy = $w.y + [int]($w.h / 2)
        # 截图实测：绿色头像图标中心在用户名左侧约 30px，这就是菜单触发区
        $candidates += @{ x = ($w.x - 30); y = $cy }
        $candidates += @{ x = ($w.x - 45); y = $cy }
        $candidates += @{ x = ($w.x + 20); y = $cy }
    }
    $candidates += @{ x = [int]($winW * 0.028); y = [int]($winH * 0.972) }
    $ci = 0
    # 菜单是 toggle：重复点击同一个区域会把刚打开的菜单关掉。
    # 所以每个候选点只点一次，点完连续检测几轮；没检测到就 ESC 收掉再换下一个点。
    [void](Log ("step: 首页无入口，试账户条候选点 " + $candidates.Count + " 个"))
    foreach ($cand in $candidates) {
        [void](Log ("step: 点候选 #" + $ci + " @" + $cand.x + "," + $cand.y))
        # 2026-10-25：账户条这里原来走合成消息，10-25 00:55 实测 msg-ok 但菜单没开，
        # 4s 后就放弃 → 「未找到签到入口」。账户菜单是动作入口，和签到按钮同口径：
        # 直接 UIA → BringBack 真实点击（屏外窗口已 TOPMOST，不会被前台窗口盖住）。
        [void](Click-At $cand.x $cand.y -SkipSynth)
        foreach ($sub in 1..2) {
            Start-Sleep -Seconds 2
            $lines = Get-OcrLines
            Dump-Ocr $lines ("trae-menu-" + $ci + "-" + $sub)
            if ($sub -eq 1) { Save-Shot ("02-menu-" + $ci) }
            $entry = Find-EntryWord $lines $clickWords
            $claimed = Find-AnyLine $lines $claimWords ([int]($winW * 0.3))
            # 只有「入口」或「菜单确实展开了」才算拿到目标。光有状态文案不算——
            # 否则一张跨天残留的「已签到」会让循环立刻收手，连菜单里的入口都没看。
            if ($entry -or (Test-MenuOpen $lines)) { break }
        }
        if ($entry -or (Test-MenuOpen $lines)) { break }
        # ESC 收掉可能的菜单/浮层，再试下一个候选点（屏外：keybd_event 会落到
        # 用户前台窗口，改用合成 ESC 直投客户端队列）
        if ($Offscreen) {
            Send-SynthEsc
        } else {
            [Cap32]::keybd_event(0x1B, 0, 0, [UIntPtr]::Zero) | Out-Null
            [Cap32]::keybd_event(0x1B, 0, 2, [UIntPtr]::Zero) | Out-Null
        }
        Start-Sleep -Milliseconds 600
        $ci++
    }
}

# 2026-11-03 兜底：IDE/Code 窗口没有左下角账户条，头像在窗口上栏右侧（IDE 模式
# 实测：绿色头像 icon 距右缘约 245px、距顶约 20px，1500x900 与 1350x900 两种宽度
# 下偏移一致；当日晚间 computer-use 实签走的就是这条路）。左下流程全军覆没时点这里
# 开同一个头像菜单（菜单内容各窗口一致：每日领100积分 + 签到按钮）。
if (-not $entry -and -not (Test-MenuOpen $lines)) {
    $tx = $winW - 245
    $ty = 20
    [void](Log ("step: 左下账户条未开菜单，兜底点上栏头像 @$tx,$ty（IDE 窗口上栏头像入口）"))
    [void](Click-At $tx $ty -SkipSynth)
    foreach ($sub in 1..2) {
        Start-Sleep -Seconds 2
        $lines = Get-OcrLines
        Dump-Ocr $lines ("trae-topbar-" + $sub)
        if ($sub -eq 1) { Save-Shot "03-topbar" }
        $entry = Find-EntryWord $lines $clickWords
        $claimed = Find-AnyLine $lines $claimWords ([int]($winW * 0.3))
        if ($entry -or (Test-MenuOpen $lines)) { break }
    }
    if (-not $entry -and -not (Test-MenuOpen $lines)) {
        # 没点开就收掉可能的浮层，别把菜单留给下一轮误判
        if ($Offscreen) {
            Send-SynthEsc
        } else {
            [Cap32]::keybd_event(0x1B, 0, 0, [UIntPtr]::Zero) | Out-Null
            [Cap32]::keybd_event(0x1B, 0, 2, [UIntPtr]::Zero) | Out-Null
        }
        Start-Sleep -Milliseconds 600
    }
}

if (-not $entry -and -not $claimed) {
    # 诊断：把可能相关的词全列出来，否则「菜单明明开了却报找不到」无从下手
    $diag = New-Object System.Collections.ArrayList
    foreach ($l in $lines) {
        if (-not $l.words) { continue }
        foreach ($w in $l.words) {
            if ($w.text -match "每日|积分|签到|Check") {
                [void]$diag.Add($w.text + "@" + $w.x + "," + $w.y)
            }
        }
    }
    $peek = ($lines | Select-Object -First 10 | ForEach-Object { $_.text }) -join "/"
    $msg = ("未找到签到入口；相关词: " + ($diag -join " | ") + "；页面: " + $peek)
    if ($Explore) { return New-TraeClaimResult 'explore' $msg }
    return New-TraeClaimResult 'pending' $msg
}

# 探索模式到此为止：菜单词级布局已进 dump 与截图，签到按钮绝不碰
if ($Explore) {
    return New-TraeClaimResult 'explore' ("菜单已抓取，入口候选: " + $entry.text + " @ " + ($entry.x + [int]($entry.w / 2)) + "," + ($entry.y + [int]($entry.h / 2)))
}

if ($claimed -and -not $entry) {
    # 2026-10-24：这里原来是无条件 `if ($claimed) { Out-Json "already" }`，而且优先于
    # 入口点击——只要左侧有「已签到」就直接收工，一个像素都没点。
    # 10-24 00:00 实锤：菜单里同时有「每日领100积分+额外抽奖」和跨天残留的「已签到」，
    # 脚本据此报已签，服务端余额 3,620 纹丝未动（真漏签，且台账被记了假签到）。
    # 新口径：有入口就必须点（点完用 granted/余额复核到账）；没有入口只有文案时
    # 无法复核，一律降级 pending，让台账老实报「待手签」，绝不静默记一笔假的。
    $peek0 = ($lines | Select-Object -First 10 | ForEach-Object { $_.text }) -join "/"
    return New-TraeClaimResult 'pending' ("页面显示「" + $claimed.text + "」但找不到可点的签到入口，无法复核是否到账，按待手签处理；页面: " + $peek0)
}

# 点击前页面上已经有的「已签到」文案（可能就是跨天残留）。点击后它还挂在原处，
# 不能当成本次到账的证据——否则又会回到「点了个状态还报成功」的老路。
$claimedBefore = $null
if ($claimed) { $claimedBefore = [string]$claimed.text }

$bx = $entry.x
$by = $entry.y + [int]($entry.h / 2)
if ($DryRun) {
    return New-TraeClaimResult 'dryrun' ("将点击签到入口: " + $entry.text + " @ " + $bx + "," + $by)
}

# 「每日领150积分」只是说明文字，真正的签到按钮是它右侧的黑色「签到」。
# 按钮相对文字行的偏移随窗口宽度略有变化，按 380 → 300 → 450 → 文字本身 轮换试。
# 按钮相对文字行的偏移：窗口越窄菜单越窄，写死 380 会点到菜单外。
# 用菜单项的右边界推算——黑色「签到」按钮右对齐在菜单内侧约 60px 处。
$offsets = @(380, 300, 450, 0)
$menuRight = 0
$menuXMax = [int]($winW * 0.35)
foreach ($l in $lines) {
    if (-not $l.text) { continue }
    # 2026-10-25：菜单只可能在左侧栏。聊天/文档区里同样会出现「消息」「每日领」
    # 等词，不限制 x 会把 menuRight 拉到窗口右侧，药丸扫描范围随之覆盖聊天区，
    # 扫到的是对话内容而不是「签到」黑钮。
    if ($l.x -ge $menuXMax) { continue }
    if ($l.text -match "退出登录|管理账户|报告问题|升级权益|每日领|消息") {
        $r = $l.x + $l.w
        if ($r -gt $menuRight) { $menuRight = $r }
    }
}
if ($menuRight -gt 0) {
    # PowerShell 5.1 会把 @($d, $d - 60, ...) 里的算术解析成数组运算而报错，
    # 必须先算成独立变量再进数组。
    $d  = [int]([int]$menuRight - 60 - [int]$bx)
    $d1 = $d - 60
    $d2 = $d + 60
    $offsets = @($d, $d1, $d2, 0)
}

# 「签到」按钮 OCR 整行漏检，靠像素扫描在入口行右侧找对比色药丸，
# 命中后以它为主点击点（比按偏移猜可靠得多）。
$x1 = [int]($winW * 0.3)
if ($menuRight -gt 0) { $x1 = [int]($menuRight + 80) }
# ⚠️ 上面这版窗口不够宽：menuRight 是由「文字右边界」推的，而新布局里药丸比任何
# 文字都靠右（实测文字右缘 394，药丸跨 432~570）-> 扫到 474 就把药丸截断了，
# 只会回一段 44px 的假区段。取一个覆盖到菜单右缘之外的宽窗口，
# 再用 Find-ButtonPill 里的 260px 上限把「菜单外更暗的背景」排掉。
if ($menuRight -gt 0) { $x1 = [int]($menuRight + 300) }
if ($x1 -gt ($winW - 1)) { $x1 = $winW - 1 }
# 按钮可能只有 hover 才渲染：先把真实光标移到入口行触发 hover，等它渲染，
# 再刷新一帧去扫描。（屏外：物理光标到不了屏外，改发合成 WM_MOUSEMOVE——
# 合成消息触发 Electron hover 渲染是实证过的，账户菜单就是这么开的。）
if ($Offscreen) {
    Send-SynthMouse ($bx + 60) $by -HoverOnly | Out-Null
} else {
    [Cap32]::SetCursorPos(($winX + [int]$bx + 60), ($winY + $by)) | Out-Null
}
Start-Sleep -Milliseconds 800
$null = Get-OcrLines
# 点击前的余额：菜单重开后「今日已签」文案会消失，余额差才是唯一可靠的到账证据。
# 2026-10-13 起新 UI 账户条不再显示余额，这里恒为 -1，降为备用判据。
$bal0 = Find-Balance $lines
$offer = Find-OfferAmount $lines

# 2026-10-13：优先按 OCR 短文本定位卡片下方的「签到」按钮。命中就只点一次，
# 不再靠像素扫描药丸 + 4 个 offset 轮换去碰运气（新布局里药丸扫描会扫到背景
# 深色块，实测 x=664 len=235，于是每次都要试满 4 个位置）。
$btnLine = Find-SignButton $lines $entry.y
if ($btnLine) {
    $bx = $btnLine.x + [int]($btnLine.w / 2)
    $by = $btnLine.y + [int]($btnLine.h / 2)
    $offsets = @(0)
    [void](Log ("step: 签到按钮按 OCR 定位 @" + $bx + "," + $by))
    try {
        $ln = "$(Get-Date -Format HH:mm:ss) btnOcr x=$bx y=$by text=$($btnLine.text) offer=$offer bal0=$bal0`n"
        [System.IO.File]::AppendAllText("$PSScriptRoot\..\logs\_clickmode.txt", $ln)
    } catch { }
}
else {
    $btn = Find-ButtonPill $by ([int]([int]$bx + 40)) $x1
    if ($btn) {
        $d0 = [int]($btn.x - [int]$bx)
        $dm = $d0 - 40
        $dp = $d0 + 40
        $offsets = @($d0, $dm, $dp, 0)
        $by = $btn.y
        try {
            $ln = "$(Get-Date -Format HH:mm:ss) buttonPill x=$($btn.x) y=$($btn.y) len=$($btn.len) bg=$($btn.bg) entryX=$bx bal0=$bal0 offsets=" + ($offsets -join ',') + "`n"
            [System.IO.File]::AppendAllText("$PSScriptRoot\..\logs\_clickmode.txt", $ln)
        } catch { }
    } else {
        try {
            $ln = "$(Get-Date -Format HH:mm:ss) btnNone entryX=$bx by=$by bal0=$bal0`n"
            [System.IO.File]::AppendAllText("$PSScriptRoot\..\logs\_clickmode.txt", $ln)
        } catch { }
    }
}
[void](Log ("step: 入口已找到 " + $entry.text + "（可领 " + $offer + "），准备点签到按钮"))
for ($i = 0; $i -lt $offsets.Count; $i++) {
    [void](Log ("step: 点击 offset=" + $offsets[$i] + " @" + ($bx + $offsets[$i]) + "," + $by))
    # -SkipSynth：合成消息对「签到」黑按钮无效是实证事实，直接 UIA → 移回真实点击
    [void](Click-At ($bx + $offsets[$i]) $by -SkipSynth)
    foreach ($sub in 1..2) {
        Start-Sleep -Seconds 3
        $lines = Get-OcrLines
        Dump-Ocr $lines ("trae-after-click-" + $i + "-" + $sub)
        if ($sub -eq 1) { Save-Shot ("03-after-" + $i) }

        # ① 主判据（2026-10-13 起）：卡片上的「已获得N积分」直接给出实发额度。
        #    它只在刚领到的那几帧出现，且带额度——比余额差更准，比文案更硬。
        #    **以实测额度为准入账**（服务端随时调额：免费日额度 2026-09-30
        #    就从 150 变成 100），catalog 的 daily_amount 只作预估。
        $g = Find-Granted $lines
        if ($g -gt 0) {
            return New-TraeClaimResult 'ok' ("签到成功（已获得 " + $g + " 积分）[granted] " + $g) $g
        }

        # ② 备用判据：余额差。新 UI 已无余额（bal0 恒 -1），保留以兼容再次改版。
        $bal1 = Find-Balance $lines
        [void](Log ("step: 复核 granted=" + $g + " 余额 " + $bal0 + " -> " + $bal1))
        if ($bal0 -ge 0 -and $bal1 -ge 0 -and $bal1 -gt $bal0) {
            $delta = $bal1 - $bal0
            return New-TraeClaimResult 'ok' ("签到成功（余额 $bal0 -> $bal1）[granted] $delta") $delta
        }

        # ③ 兜底判据：文案。弱——「今日已签」只在刚领的那次菜单会话里出现，
        #    重开菜单就会变回「每日领100积分」，且拿不到额度（入账退回 catalog
        #    的 daily_amount）。仅在上两条都失效时使用。
        $c = Find-AnyLine $lines $claimWords ([int]($winW * 0.3))
        if ($c -and $claimedBefore -and [string]$c.text -eq $claimedBefore) {
            [void](Log ("step: 弱判据被排除（点击前后都是同一句「" + $c.text + "」，不是本次到账证据）"))
            $c = $null
        }
        if ($c) {
            [void](Log ("step: 弱判据命中（未读到「已获得N积分」）: " + $c.text))
            return New-TraeClaimResult 'ok' ("签到成功（点击后新出现: " + $c.text + "）")
        }
    }
}
$peek2 = ($lines | Select-Object -First 10 | ForEach-Object { $_.text }) -join "/"
# 2026-10-13：bal0 在新 UI 里恒为 -1，不能再拿它当「报不报 pending」的前提，
# 否则判据全部落空时脚本会静默走到文件末尾、不写结果文件，调用方只能干等超时。
# 2026-10-24：走到这里 = 入口点过了、granted 没出现、余额没涨。原来这里还会拿
# 「会员推广态」报 already，但同一张卡片在**未签到**时也会显示（见 1.5 节，10-15
# 已实锤漏签）。既然已经点过却复核不到到账，就不该替主人下「已签」的结论：
# 一律报 pending，让他按一下或者手动 record，台账永远只记有证据的那一笔。
if (Test-AlreadyCard $lines) {
    [void](Log "step: 卡片为会员推广态，但本轮到账复核失败，不报 already")
}
# clicked-only 不能判 ok；没有 granted/余额增加/点击后新出现的已签状态，一律 pending。
return New-TraeClaimResult 'pending' ("已点击签到入口但未检测到到账（granted 未出现，余额 $bal0）；页面: " + $peek2)
    } catch {
        return New-TraeClaimResult 'failed' ('窗口处理异常: ' + $_.Exception.Message)
    } finally {
        # 无论 ok/pending/failed/Explore/DryRun，离开当前候选前都先恢复它自己的 rect。
        try { if ($script:OriginalRect) { [void](Restore-OriginalRect) } } catch { }
        $script:OriginalRect = $null
        $script:WasZoomed = $false
        $script:WasMinimized = $false
        if ($script:ShotBmp) { try { $script:ShotBmp.Dispose() } catch { }; $script:ShotBmp = $null }
    }
}

# ── 多窗口外层：OCR 选中者优先，其余按面积；隐藏窗口还原后重新枚举入队 ─────────
if (-not $hwnd -or $hwnd -eq [IntPtr]::Zero) {
    Out-Json "pending" ("找不到 " + $ProcessName + " 窗口，请手动打开客户端后重跑")
}
if ($script:MainCandidates -and $script:MainCandidates.Count -gt 1 -and $script:LaunchedByUs) {
    Start-Sleep -Seconds 3
}
$selectedHwnd = Select-CodeModeWindow
$claimQueue = New-Object System.Collections.ArrayList
$queuedHandles = @{}
$processedHandles = @{}
$candidateIndex = 0
$lastDetail = ''

# 选中的窗口固定排第一；其余候选按面积降序。新还原的隐藏窗口也会走同一入队规则。
$selectedCand = $script:MainCandidates | Where-Object { $_.H -eq $selectedHwnd } | Select-Object -First 1
if ($selectedCand) {
    [void]$claimQueue.Add($selectedCand)
    $queuedHandles[[string]$selectedCand.H] = $true
}
foreach ($cand in @($script:MainCandidates | Sort-Object Area -Descending)) {
    if (-not $cand -or $queuedHandles.ContainsKey([string]$cand.H)) { continue }
    [void]$claimQueue.Add($cand)
    $queuedHandles[[string]$cand.H] = $true
}

while ($true) {
    if ($claimQueue.Count -eq 0) {
        # 可见候选都失败后再逐个还原隐藏窗口；每次还原都重新枚举，纳入新可见结果。
        $restoredHidden = Restore-HiddenTraeWindow
        if ($restoredHidden -eq [IntPtr]::Zero) { break }
        [void](Find-TargetWindow)
        foreach ($cand in @($script:MainCandidates | Sort-Object Area -Descending)) {
            if (-not $cand -or $queuedHandles.ContainsKey([string]$cand.H)) { continue }
            [void]$claimQueue.Add($cand)
            $queuedHandles[[string]$cand.H] = $true
        }
        if ($claimQueue.Count -eq 0) { continue }
    }

    $cand = $claimQueue[0]
    $claimQueue.RemoveAt(0)
    $handleKey = [string]$cand.H
    if ($processedHandles.ContainsKey($handleKey)) { continue }
    $processedHandles[$handleKey] = $true
    $candidateIndex++
    [void](Log ("multi-window: candidate=$candidateIndex handle=$($cand.H) area=$($cand.Area)"))

    # Log 会走 Write-Output；这里用数组收口并校验，绝不把日志误当成 Status/Detail。
    $claimOutput = @(Invoke-TraeWindowClaim $cand.H)
    if ($claimOutput.Count -ne 1 -or $claimOutput[0] -isnot [pscustomobject] -or -not $claimOutput[0].PSObject.Properties['Status']) {
        $result = New-TraeClaimResult 'failed' 'Invoke-TraeWindowClaim 返回值污染或缺失'
    } else {
        $result = $claimOutput[0]
    }
    [void](Log ("multi-window: candidate=$candidateIndex handle=$($cand.H) status=$($result.Status) detail=" + $result.Detail))

    # 终态直接统一收尾；Out-Json 内部 exit，因此成功后不会再处理其他窗口。
    if (@('ok', 'already', 'dryrun', 'explore') -contains $result.Status) {
        Out-Json $result.Status $result.Detail $result.Amount
    }
    if (-not [string]::IsNullOrWhiteSpace($result.Detail)) {
        $lastDetail = "candidate=$candidateIndex handle=$($cand.H) area=$($cand.Area)；" + $result.Detail
    }
    # pending/failed：Invoke 的 finally 已恢复本窗口 rect，这里才继续下一个候选。
}
if ([string]::IsNullOrWhiteSpace($lastDetail)) { $lastDetail = '没有可处理的 Trae 主窗口候选' }
Out-Json "pending" ("所有候选窗口均未确认到账；最后诊断: " + $lastDetail)
