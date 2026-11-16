# AutoClaw OCR check-in: find anchors via screenshot+OCR, click the daily check-in button.
# Requires: AutoClaw foreground (interactive) or elevated runner (scheduled task).
param(
    [switch]$DryRun,
    [string]$OutFile = "",
    # 方案甲（2026-10-21 拍板）：签到全程把窗口停到屏外——识别走 PrintWindow
    # （对屏外窗口有效），点击分三级：合成消息 → UIA Invoke → 移回屏内真实点击
    # （光标保存/恢复，暴露面 ~100ms）。传 -Offscreen:$false 退回旧行为。
    [bool]$Offscreen = $true
)
$root = Split-Path -Parent $PSScriptRoot
$logPath = "$root\logs\ps1_autoclaw.log"
function Log($m){ $s=(Get-Date -Format "HH:mm:ss")+" "+$m; try{[System.IO.File]::AppendAllText($logPath,$s+"`n",(New-Object System.Text.UTF8Encoding($false)))}catch{}; Write-Output $s }
function Wait-InputQuiet([int]$QuietMs = 320, [int]$MaxWaitMs = 20000) {
    # 点击前闸门：主人正在动鼠标/敲键盘时先等，停手后立刻点、点完立刻还原光标。
    # 内部 Log 一律 [void]：Log 走输出流，混进来会把返回值变成数组。
    $start = Get-Date
    $deadline = $start.AddMilliseconds($MaxWaitMs)
    $logged = $false
    while ($true) {
        $idle = [Cap32]::IdleMs()
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

$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

# A terminating error used to kill the script without writing any result file,
# which made the runner wait 180s and report a bare timeout. Always surface it.
trap {
    # 方案甲：FATAL 也不能把窗口留在屏外（A5），尽力恢复后再退出
    try { if ($script:OriginalRect) { Restore-OriginalRect } } catch { }
    # 异常路径也要走完整收尾：只关本次拉起的 PID、把前台还给原窗口。
    # 漏了这两步，FATAL 后桌面上会多留一个客户端并顶掉用户的焦点。
    try {
        if (-not $DryRun -and $script:LaunchedByUs -and $script:LaunchedPid -gt 0) {
            taskkill /PID $script:LaunchedPid /T /F 2>$null | Out-Null
        }
    } catch { }
    try { Restore-Foreground } catch { }
    try {
        $m = "FATAL: " + $_.Exception.Message + " @ " + $_.InvocationInfo.PositionMessage
        $p = "$PSScriptRoot\..\logs\autoclaw_claim.json"
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
  [DllImport("user32.dll")] public static extern IntPtr GetForegroundWindow();
  [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr hWnd);
  [DllImport("user32.dll")] public static extern bool SetCursorPos(int X, int Y);
  // 方案甲 BringBack-Click：点击前保存、点击后恢复物理光标（A3 日志断言用）
  [DllImport("user32.dll")] public static extern bool GetCursorPos(out POINT lpPoint);
  // 方案甲 M1/M3/M4：屏外停放 / 移回点击位 / 恢复启动 rect
  [DllImport("user32.dll")] public static extern bool SetWindowPos(IntPtr hWnd, IntPtr hWndInsertAfter, int X, int Y, int cx, int cy, uint uFlags);
  [DllImport("user32.dll")] public static extern void mouse_event(uint flags, uint dx, uint dy, uint data, UIntPtr extra);
  [DllImport("user32.dll")] public static extern bool EnumWindows(EnumProc cb, IntPtr lp);
  [DllImport("user32.dll")] public static extern uint GetWindowThreadProcessId(IntPtr hWnd, out uint pid);
  [DllImport("user32.dll")] public static extern bool IsWindowVisible(IntPtr hWnd);
  // 2026-10-29：关到托盘时主窗口隐藏，需要按标题/类名把它找回来。
  [DllImport("user32.dll", CharSet=CharSet.Unicode)] public static extern int GetWindowTextW(IntPtr hWnd, System.Text.StringBuilder s, int n);
  [DllImport("user32.dll", CharSet=CharSet.Unicode)] public static extern int GetClassName(IntPtr hWnd, System.Text.StringBuilder s, int n);
  [DllImport("user32.dll")] public static extern bool ShowWindow(IntPtr hWnd, int nCmdShow);
  [DllImport("user32.dll")] public static extern void keybd_event(byte bVk, byte bScan, uint dwFlags, UIntPtr dwExtraInfo);
  [DllImport("user32.dll")] public static extern bool AttachThreadInput(uint idAttach, uint idAttachTo, bool fAttach);
  [DllImport("kernel32.dll")] public static extern uint GetCurrentThreadId();
  [DllImport("user32.dll")] public static extern bool IsIconic(IntPtr hWnd);
  [DllImport("user32.dll")] public static extern bool PrintWindow(IntPtr hWnd, IntPtr hdcBlt, uint nFlags);
  [DllImport("user32.dll")] public static extern IntPtr SendMessageTimeout(IntPtr hWnd, uint msg, UIntPtr wParam, IntPtr lParam, uint fuFlags, uint uTimeout, out IntPtr lpdwResult);
  [DllImport("user32.dll")] public static extern bool ScreenToClient(IntPtr hWnd, ref POINT lpPoint);
  [DllImport("user32.dll")] public static extern IntPtr WindowFromPoint(POINT p);
  [DllImport("user32.dll")] public static extern IntPtr ChildWindowFromPointEx(IntPtr hWnd, POINT p, uint flags);
  // 2026-10-30：点击前的「静默闸门」用 GetLastInputInfo 判断主人是否在操作。
  [StructLayout(LayoutKind.Sequential)] public struct LASTINPUTINFO { public uint cbSize; public uint dwTime; }
  [DllImport("user32.dll")] public static extern bool GetLastInputInfo(ref LASTINPUTINFO plii);
  [DllImport("kernel32.dll")] public static extern uint GetTickCount();
  public static int IdleMs() {
    LASTINPUTINFO li = new LASTINPUTINFO();
    li.cbSize = (uint)Marshal.SizeOf(typeof(LASTINPUTINFO));
    if (!GetLastInputInfo(ref li)) { return 1000000; }
    uint idle = unchecked(GetTickCount() - li.dwTime);
    return idle > 1000000u ? 1000000 : (int)idle;
  }
  public struct RECT { public int Left, Top, Right, Bottom; }
  public struct POINT { public int X, Y; }
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
        $r = $script:OriginalRect
        # 位置和尺寸都还原；只回位置会让被改过尺寸的窗口永久变形。
        [Cap32]::SetWindowPos($hwnd, [IntPtr]::Zero, $r.Left, $r.Top,
            ($r.Right - $r.Left), ($r.Bottom - $r.Top), 0x0014) | Out-Null
        $chk = New-Object Cap32+RECT
        [Cap32]::GetWindowRect($hwnd, [ref]$chk) | Out-Null
        # A3 断言：关闭前 rect == 启动 rect
        Log ("restore-rect: now " + $chk.Left + "," + $chk.Top + " " + ($chk.Right-$chk.Left) + "x" + ($chk.Bottom-$chk.Top) + " (expect " + $r.Left + "," + $r.Top + " " + ($r.Right-$r.Left) + "x" + ($r.Bottom-$r.Top) + ")")
        if ($script:WasMinimized) {
            [void][Cap32]::ShowWindow($hwnd, 6)   # SW_MINIMIZE：原来最小化就还它最小化
            Log "restore-rect: minimized (was iconic)"
        }
    } catch { try { Log ("restore-rect failed: " + $_.Exception.Message) } catch { } }
}

function Test-RectOnAnyScreen($r) {
    # R1 双保险用的屏内判定：rect 与任一显示器的 bounds 相交即视为屏内
    # （多显示器左屏是负坐标，不能用 Right<0 这种朴素判断——R7）。
    try {
        Add-Type -AssemblyName System.Windows.Forms -ErrorAction SilentlyContinue
        foreach ($s in [System.Windows.Forms.Screen]::AllScreens) {
            $b = $s.Bounds
            if ($r.Right -gt $b.Left -and $r.Left -lt $b.Right -and
                $r.Bottom -gt $b.Top -and $r.Top -lt $b.Bottom) { return $true }
        }
    } catch { return $true }  # 查询失败就当在屏内，别乱动窗口
    return $false
}

# 现场保存/还原：脚本会把客户端提到前面抢操作，结束后必须把前台还给原来
# 那个窗口，否则跑一次就把主人的桌面布局顶掉了。
$script:SavedForeground = [IntPtr]::Zero
function Save-Foreground {
    if ($script:SavedForeground -eq [IntPtr]::Zero) {
        $f = [Cap32]::GetForegroundWindow()
        if ($f -ne $hwnd) { $script:SavedForeground = $f }
    }
}
function Restore-Foreground {
    try {
        if ($script:SavedForeground -ne [IntPtr]::Zero) {
            # 用户已经切走并在操作时不要再抢回来（二次打断比不还原更烦）。
            if ([Cap32]::IdleMs() -lt 8000) {
                [void](Log "restore-foreground: 用户正在操作，跳过抢回前台")
                return
            }
            [Cap32]::SetForegroundWindow($script:SavedForeground) | Out-Null
        }
    } catch { }
}

function Out-Json([string]$status, [string]$detail) {
    # 方案甲 M4：任何收尾之前先把窗口移回启动 rect——Electron 会把窗口位置
    # 持久化进自己的 config，留着屏外位置关闭，下次冷启动窗口还在屏外。
    if ($script:OriginalRect) { Restore-OriginalRect }
    # 运行结束一律恢复现场：
    #   1) 关掉本次由脚本拉起的实例（签到前就开着的必须保留）；
    #   2) 把前台还给运行前的窗口。
    # 失败时也不留窗口：无人值守跑完桌面不该堆着客户端，诊断信息已落日志+台账。
    if (-not $DryRun -and $script:LaunchedByUs) {
        # 只关本次拉起的进程树：按镜像名 /IM 会把用户中途自己打开的实例一起杀掉。
        if ($script:LaunchedPid -gt 0) {
            taskkill /PID $script:LaunchedPid /T /F 2>$null | Out-Null
            $detail = $detail + "；已关闭本次启动的客户端"
        } else {
            Log "cleanup: launched pid unknown, skip closing to avoid killing user's instance"
        }
    }
    Restore-Foreground
    $payload = @{ status = $status; detail = $detail } | ConvertTo-Json -Compress
    if ($OutFile) {
        [System.IO.File]::WriteAllText($OutFile, $payload, (New-Object System.Text.UTF8Encoding($false)))
    }
    Write-Output $payload
    if ($status -eq "ok" -or $status -eq "already") { exit 0 }
    exit 2
}

$null = [Cap32]::SetProcessDPIAware()

$exe = 'C:\Program Files\AutoClaw\AutoClaw.exe'

# OCR 布局落盘：调锚点全靠它。失败路径也要写，否则永远看不到二跳页面长什么样。
$dumpPath = "$root\logs\autoclaw_ocr_dump.txt"
function Dump-Ocr($lines, $tag) {
    if (-not $lines) { return }
    try {
        $stamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
        $lines_txt = ($lines | ForEach-Object { "{0} | {1},{2} {3}x{4}" -f $_.text, $_.x, $_.y, $_.w, $_.h }) -join "`n"
        [System.IO.File]::AppendAllText($dumpPath, "[$stamp] $tag`n$lines_txt`n---`n", (New-Object System.Text.UTF8Encoding($false)))
    } catch { }
}

# 页面是否真的变了。点入口后如果页面纹丝不动，说明点击没生效——最常见原因是
# 本脚本没提权，而 AutoClaw 跑在更高完整性级别，mouse_event 会被 UIPI 丢掉。
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

function Find-AutoClawWindow {
    # Largest visible top-level window of any AutoClaw process. MainWindowHandle
    # can point at tiny helper popups (update banners etc.), so enumerate.
    $script:BestHwnd = [IntPtr]::Zero
    $script:BestArea = 0
    $pidSet = @{}
    Get-Process AutoClaw -ErrorAction SilentlyContinue | ForEach-Object { $pidSet[[uint32]$_.Id] = $true }
    if ($pidSet.Count -eq 0) { return [IntPtr]::Zero }
    $cb = [Cap32+EnumProc]{
        param($h, $lp)
        $owner = [uint32]0
        [Cap32]::GetWindowThreadProcessId($h, [ref]$owner) | Out-Null
        if ($pidSet.ContainsKey($owner) -and [Cap32]::IsWindowVisible($h)) {
            $r = New-Object Cap32+RECT
            [Cap32]::GetWindowRect($h, [ref]$r) | Out-Null
            $w = $r.Right - $r.Left
            $hh = $r.Bottom - $r.Top
            if ($w -gt 500 -and $hh -gt 400 -and ($w * $hh) -gt $script:BestArea) {
                $script:BestHwnd = $h
                $script:BestArea = $w * $hh
            }
        }
        return $true
    }
    [Cap32]::EnumWindows($cb, [IntPtr]::Zero) | Out-Null
    return $script:BestHwnd
}

function Restore-HiddenAutoClawWindow {
    # 2026-10-29：关到托盘时主窗口 WS_VISIBLE=off，Find-AutoClawWindow 只认可见
    # 窗口，旧逻辑会白等 60 秒。枚举同进程的隐藏窗口，按「大 + 有标题 + 非黑窗」
    # 选主窗口，SW_RESTORE 还原。
    $script:HidHwnd = [IntPtr]::Zero
    $script:HidArea = 0
    $pidSet = @{}
    Get-Process AutoClaw -ErrorAction SilentlyContinue | ForEach-Object { $pidSet[[uint32]$_.Id] = $true }
    if ($pidSet.Count -eq 0) { return [IntPtr]::Zero }
    $cb = [Cap32+EnumProc]{
        param($h, $lp)
        $owner = [uint32]0
        [Cap32]::GetWindowThreadProcessId($h, [ref]$owner) | Out-Null
        if ($pidSet.ContainsKey($owner)) {
            if ([Cap32]::IsWindowVisible($h)) { return $true }
            $r = New-Object Cap32+RECT
            [Cap32]::GetWindowRect($h, [ref]$r) | Out-Null
            $w = $r.Right - $r.Left
            $hh = $r.Bottom - $r.Top
            if ($w -le 500 -or $hh -le 400) { return $true }
            $sb = New-Object System.Text.StringBuilder 256
            [void][Cap32]::GetWindowTextW($h, $sb, 256)
            if ([string]::IsNullOrWhiteSpace($sb.ToString())) { return $true }
            $cn = New-Object System.Text.StringBuilder 256
            [void][Cap32]::GetClassName($h, $cn, 256)
            if ($cn.ToString() -eq 'Chrome_WidgetWin_0') { return $true }
            if (($w * $hh) -gt $script:HidArea) {
                $script:HidArea = $w * $hh
                $script:HidHwnd = $h
            }
        }
        return $true
    }
    [Cap32]::EnumWindows($cb, [IntPtr]::Zero) | Out-Null
    if ($script:HidHwnd -eq [IntPtr]::Zero) { return [IntPtr]::Zero }
    Log ("main window hidden (tray?); restoring hwnd=" + $script:HidHwnd)
    [void][Cap32]::ShowWindow($script:HidHwnd, 9)   # SW_RESTORE
    Start-Sleep -Milliseconds 900
    return $script:HidHwnd
}

$script:LaunchedByUs = $false
$script:LaunchedPid = 0
$script:WasMinimized = $false
$preexistingApp = @(Get-Process AutoClaw -ErrorAction SilentlyContinue)
$hwnd = Find-AutoClawWindow
if ($hwnd -ne [IntPtr]::Zero) {
    # 主人可能把窗口最小化在任务栏：记下来，收尾时原样放回去。
    $script:WasMinimized = [Cap32]::IsIconic($hwnd)
}
if ($hwnd -eq [IntPtr]::Zero) {
    # 2026-10-29：先试托盘还原；还原成功就直接用，不必再等 60 秒。
    $restored = Restore-HiddenAutoClawWindow
    if ($restored -ne [IntPtr]::Zero) {
        Log ("after hidden-window restore, hwnd=" + $restored)
        $hwnd = Find-AutoClawWindow
        if ($hwnd -eq [IntPtr]::Zero) { $hwnd = $restored }
    }
}
if ($hwnd -eq [IntPtr]::Zero) {
    # Self-heal: background survivors can never regain a window, so clear them
    # and start fresh -- but ONLY when the client was not already running for the
    # user. Killing an instance the human had open is never acceptable.
    if ($preexistingApp.Count -eq 0) {
        # 只清「没有主窗口」的后台残留；用户中途自己开的正常实例有窗口，不动它。
        # 按镜像名 /IM 全杀会把那种实例一起带走（2026-11-11 审计）。
        $stale = @(Get-Process AutoClaw -ErrorAction SilentlyContinue | Where-Object { $_.MainWindowHandle -eq 0 })
        foreach ($p in $stale) { taskkill /PID $p.Id /T /F 2>$null | Out-Null }
        if ($stale.Count -gt 0) { Start-Sleep -Seconds 3 }
        if (Test-Path $exe) {
            $proc = Start-Process $exe -PassThru
            $script:LaunchedByUs = $true
            $script:LaunchedPid = [int]$proc.Id
            Log ("launched pid=" + $script:LaunchedPid)
        }
    }
    $dl = (Get-Date).AddSeconds(60)
    while ((Get-Date) -lt $dl) {
        Start-Sleep -Seconds 2
        $hwnd = Find-AutoClawWindow
        if ($hwnd -ne [IntPtr]::Zero) { break }
    }
    if ($hwnd -eq [IntPtr]::Zero) { Out-Json "notfound" "AutoClaw 启动后 60s 内未出现主窗口" }
}

# Foreground helpers: OCR is only trustworthy when AutoClaw is really in front.
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
    # Foreground is now best-effort only: PrintWindow captures the window even
    # when another window is on top, so a failed foreground switch must not
    # abort the whole check-in any more.
    # 屏外模式下抢前台无收益且打扰用户焦点（方案甲），直接截屏即可。
    if (-not $Offscreen) { try { Ensure-Foreground | Out-Null } catch { } }
    return Get-OcrLines
}

$rect = New-Object Cap32+RECT
[Cap32]::GetWindowRect($hwnd, [ref]$rect) | Out-Null
$winW = $rect.Right - $rect.Left
$winH = $rect.Bottom - $rect.Top
$winX = $rect.Left
$winY = $rect.Top

# --- 方案甲 M1：窗口整窗停到主屏左界外，识别全后台化 -------------------------
# 窗口仍在默认桌面（DWM 正常合成，PrintWindow 可用），只是不可见、绝不激活。
# 原 rect 存入 $script:OriginalRect，Out-Json 收尾前恢复（M4）；
# $winX/$winY 保持原位语义，供移回点击用。
$script:OriginalRect = $null
if ($Offscreen) {
    # R1 双保险：上次异常退出可能把屏外位置持久化——启动时先拨回屏内再存原 rect
    if (-not (Test-RectOnAnyScreen $rect)) {
        [Cap32]::SetWindowPos($hwnd, [IntPtr]::Zero, 100, 100, 0, 0, 0x0015) | Out-Null
        Start-Sleep -Milliseconds 300
        $rect = New-Object Cap32+RECT
        [Cap32]::GetWindowRect($hwnd, [ref]$rect) | Out-Null
        $winW = $rect.Right - $rect.Left
        $winH = $rect.Bottom - $rect.Top
        $winX = $rect.Left
        $winY = $rect.Top
        Log ("step: 检测到残留屏外位置，已拨回屏内 " + $winX + "," + $winY)
    }
    $script:OriginalRect = $rect
    Move-OffscreenNow
    Log ("step: 窗口已停到屏外（原 rect " + $winX + "," + $winY + " " + $winW + "x" + $winH + "）")
}

function Test-Blank($bmp) {
    # Sample a grid: if every sample is the same colour the capture is unusable
    # (PrintWindow returns a black/white frame for some GPU-composited apps).
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
    # 2026-10-30：上限 15→5（30s→8s）。持续空白帧多等也自愈不了，反而吃光外层预算。
    $maxTry = 1
    if ($Offscreen) { $maxTry = 5 }
    $bmp = $null
    for ($tryN = 1; $tryN -le $maxTry; $tryN++) {
        $bmp = New-Object System.Drawing.Bitmap($winW, $winH)
        $g = [System.Drawing.Graphics]::FromImage($bmp)
        # PrintWindow first: it captures the window even when it is occluded, not
        # in the foreground, or the session is locked.
        $hdc = $g.GetHdc()
        $pw = [Cap32]::PrintWindow($hwnd, $hdc, 2)
        $g.ReleaseHdc($hdc)
        if ($pw -and -not (Test-Blank $bmp)) { $g.Dispose(); break }
        if (-not $Offscreen) {
            $g.CopyFromScreen($winX, $winY, 0, 0, $bmp.Size)
            $g.Dispose()
            break
        }
        $g.Dispose()
        if ($tryN -lt $maxTry) {
            if ($tryN -eq 1) { Log "step: 屏外捕获空白帧，2s 间隔重试（backgroundThrottling 容忍）" | Out-Null }
            $bmp.Dispose()
            Start-Sleep -Seconds 2
        }
    }
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
        if ($l.text -and $l.text.Contains($needle)) { return $l }
    }
    return $null
}

# 按「词」而不是「行」定位点击目标。OCR 常把相邻元素并成一行
# （实测出现过「灵感与活动每日签到赚积分」整行），取整行中心会点到旁边那个元素上。
function Find-WordHit($lines, [string]$needle) {
    foreach ($l in $lines) {
        if (-not $l.words) { continue }
        if (-not $l.text -or -not $l.text.Contains($needle)) { continue }
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
        if ($l.text -and $l.text.StartsWith("每日签到") -and $l.text -notmatch "赚|积分|得|领") { return $l }
    }
    return $null
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

    # Prefer the real top-most window at the point (Electron/CEF popups may be
    # separate windows), verifying the process.（屏外时 WindowFromPoint 命中
    # 不到任何窗口，target 自然落回主窗口。）
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
    # hover first: some buttons only render on hover
    [Cap32]::SendMessageTimeout($target, 0x0200, [UIntPtr]::Zero, $lp, 0, 1000, [ref]$res) | Out-Null
    $script:LastSynthTarget = $target
    if ($HoverOnly) { return $true }
    Start-Sleep -Milliseconds 150
    $r1 = [Cap32]::SendMessageTimeout($target, 0x0201, [UIntPtr]::new([uint64]1), $lp, 0, 1500, [ref]$res)
    Start-Sleep -Milliseconds 90
    $r2 = [Cap32]::SendMessageTimeout($target, 0x0202, [UIntPtr]::Zero, $lp, 0, 1500, [ref]$res)
    return ($r1 -ne [IntPtr]::Zero -and $r2 -ne [IntPtr]::Zero)
}

function Send-SynthEsc {
    # ESC 的屏外等价物：keybd_event/SendKeys 会落到用户的前台窗口，绝不能发；
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

function BringBack-Click([int]$ax, [int]$ay, [int]$Clicks = 1, [int]$IntervalMs = 180) {
    # 方案甲 M3（第三级）：窗口移回点击位 → 保存光标 → 真实点击 → 恢复光标
    # → 移回屏外。点击位默认原位，被遮挡则试 (0,0)，再不行放弃（pending 由
    # 后继判据裁定，不重试——SAFETY 第 3 条）。
    $spots = @(@($winX, $winY), @(0, 0))
    $placed = $false
    $cx = 0
    $cy = 0
    # 2026-10-25：移回屏内时临时提为 TOPMOST（0x0011=NOSIZE|NOACTIVATE，不抢焦点），
    # 否则主人前台窗口会盖住点击位，R3 把两个落点都判成「被遮挡」→ 真实点击根本没发出去
    # （10-25 00:08 本机实测）。点完立刻降回。
    foreach ($s in $spots) {
        [Cap32]::SetWindowPos($hwnd, [IntPtr](-1), $s[0], $s[1], 0, 0, 0x0011) | Out-Null
        Start-Sleep -Milliseconds 300
        $cx = $s[0] + $ax
        $cy = $s[1] + $ay
        if (Test-ClickVisible $cx $cy) { $placed = $true; break }
        Log ("bringback: spot " + $s[0] + "," + $s[1] + " 被遮挡")
    }
    if (-not $placed) {
        Log "bringback: 两个点击位都被遮挡，跳过真实点击"
        [Cap32]::SetWindowPos($hwnd, [IntPtr](-2), 0, 0, 0, 0, 0x0013) | Out-Null
        Move-OffscreenNow
        return
    }
    $saved = [Cap32+POINT]::new()
    [Cap32]::GetCursorPos([ref]$saved) | Out-Null
    # 2026-11-11：先等主人停手，再抢前台。旧顺序是「抢前台 → 等 20s → 超时照点」，
    # 用户正好回来时按键会落进客户端、点击也可能打到别的窗口。
    if (-not (Wait-InputQuiet 320 20000)) {
        [void](Log "bringback: 用户持续操作，放弃本次真实点击")
        [Cap32]::SetWindowPos($hwnd, [IntPtr](-2), 0, 0, 0, 0, 0x0013) | Out-Null
        Move-OffscreenNow
        return
    }
    # 2026-10-25：与 Trae/LobsterAI 同一坑——窗口未激活时 CEF/React 可能吞掉第一次
    # 真实点击（只完成激活）。点击前显式抢前台，点完 Restore-Foreground 归还。
    Save-Foreground
    $fgOk = $false
    try { $fgOk = [bool](Ensure-Foreground) } catch { }
    $chk = New-Object Cap32+RECT
    [Cap32]::GetWindowRect($hwnd, [ref]$chk) | Out-Null
    Log ("bringback: ensure-foreground=" + $fgOk + " rect=" + $chk.Left + "," + $chk.Top + " click=" + $cx + "," + $cy)
    Start-Sleep -Milliseconds 150
    try {
        # 2026-10-25：首击常被 CEF/React 的焦点切换吞掉。调用方可要求短间隔连点
        # （AutoClaw 签到按钮用 2 连击、180ms），全部点完再统一恢复光标/前台/屏外。
        for ($ci = 1; $ci -le [Math]::Max(1, $Clicks); $ci++) {
            [Cap32]::SetCursorPos($cx, $cy) | Out-Null
            Start-Sleep -Milliseconds 120
            if (-not (Test-CursorAt $cx $cy)) {
                [void](Log ("bringback: 光标被挪走（click " + $ci + "），不盲点"))
                break
            }
            # 注入前最后一道复核：前台已不是目标窗口就放弃，别打到别人窗口。
            if ([Cap32]::GetForegroundWindow() -ne $hwnd) {
                [void](Log ("bringback: 前台已被切走（click " + $ci + "），不盲点"))
                break
            }
            [Cap32]::mouse_event(0x0002, 0, 0, 0, [UIntPtr]::Zero)
            [Cap32]::mouse_event(0x0004, 0, 0, 0, [UIntPtr]::Zero)
            [void](Log ("bringback: real click " + $ci + "/" + [Math]::Max(1, $Clicks) + " @ " + $cx + "," + $cy + " (cursor saved " + $saved.X + "," + $saved.Y + ")"))
            [void][Cap32]::SetCursorPos($saved.X, $saved.Y)
            if ($ci -lt $Clicks) { Start-Sleep -Milliseconds $IntervalMs }
        }
    } finally {
        # R4：任何异常路径都要恢复光标并重新停到屏外
        [Cap32]::SetCursorPos($saved.X, $saved.Y) | Out-Null
        $now = [Cap32+POINT]::new()
        [Cap32]::GetCursorPos([ref]$now) | Out-Null
        # A3 断言：点击前后 GetCursorPos 一致
        Log ("bringback: cursor restored " + $now.X + "," + $now.Y + " (expect " + $saved.X + "," + $saved.Y + ")")
        # 摘掉 TOPMOST，否则窗口回屏内后会一直钉在最上层
        [Cap32]::SetWindowPos($hwnd, [IntPtr](-2), 0, 0, 0, 0, 0x0013) | Out-Null
        Restore-Foreground
        Move-OffscreenNow
    }
}

function Click-At([int]$ax, [int]$ay, [switch]$SkipSynth, [switch]$SkipUia, [int]$Clicks = 1, [int]$IntervalMs = 180) {
    $cr = New-Object Cap32+RECT
    [Cap32]::GetWindowRect($hwnd, [ref]$cr) | Out-Null
    $sx = $cr.Left + $ax
    $sy = $cr.Top + $ay

    # 1) Already in front -> real input injection (most reliable).
    #    （屏外模式不走这条：窗口永不抢前台，且屏外坐标不能直接真实点击。）
    if (-not $Offscreen -and [Cap32]::GetForegroundWindow() -eq $hwnd) {
        [Cap32]::SetCursorPos($sx, $sy) | Out-Null
        Start-Sleep -Milliseconds 120
        for ($ci = 1; $ci -le [Math]::Max(1, $Clicks); $ci++) {
            [Cap32]::mouse_event(0x0002, 0, 0, 0, [UIntPtr]::Zero)
            [Cap32]::mouse_event(0x0004, 0, 0, 0, [UIntPtr]::Zero)
            if ($ci -lt $Clicks) { Start-Sleep -Milliseconds $IntervalMs }
        }
        return
    }

    # 2) 合成消息投递（屏外模式下这是第一级：与位置无关，零暴露）；
    #    对真正的动作按钮无效是已知事实，调用方对那类点击传 -SkipSynth/-SkipUia
    #    直接走移回真实点击。
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
        #    -SkipUia：AutoClaw 的 CEF a11y 树被禁用（见 ui_claim.py 注释），
        #    调用方可跳过这一级直接走 BringBack-Click。
        if (-not $SkipUia) {
            # Log 走输出流：失败时返回「日志+$false」非空数组会被判真（2026-10-22 实锤）
            $uiaOut = @(Invoke-AtPoint $ax $ay)
            if ($uiaOut -contains $true) { return }
        }
        BringBack-Click $ax $ay $Clicks $IntervalMs
        return
    }

    # 3) Fallback: real cursor input anyway（非屏外旧行为）.
    [Cap32]::SetCursorPos($sx, $sy) | Out-Null
    Start-Sleep -Milliseconds 120
    [Cap32]::mouse_event(0x0002, 0, 0, 0, [UIntPtr]::Zero)
    [Cap32]::mouse_event(0x0004, 0, 0, 0, [UIntPtr]::Zero)
}

# Dismiss possible ad/popup overlays: ESC, then click visible close labels.
function Close-AdOverlays {
    # 屏外模式下 SendKeys 的 ESC 会落到用户的前台窗口（方案甲：绝不打扰），
    # 改用合成 ESC 直投客户端消息队列。
    if ($Offscreen) {
        try { Send-SynthEsc; Start-Sleep -Milliseconds 800 } catch { }
    } else {
        try {
            Add-Type -AssemblyName System.Windows.Forms
            [System.Windows.Forms.SendKeys]::SendWait("{ESC}")
            Start-Sleep -Milliseconds 800
        } catch { }
    }
    try {
        $adLines = Get-OcrLines
        foreach ($kw in @("关闭", "跳过", "我知道了", "以后再说", "稍后再说")) {
            $cl = Find-Line $adLines $kw
            if ($cl) {
                Click-At ($cl.x + [int]($cl.w / 2)) ($cl.y + [int]($cl.h / 2))
                Start-Sleep -Milliseconds 800
            }
        }
    } catch { }
}

# Round 1: 先看页面。启动后的广告遮罩会盖住主界面（主人实测：有广告那次点了没跳转，
# 没广告那次才跳过去）。所以先给广告时间冒出来，关掉它，再看页面——
# 一上来就清广告，清完广告才出现，等于白清。
Start-Sleep -Seconds 8
Log "step: 已等 8s，清广告后 OCR 首页"
Close-AdOverlays
Start-Sleep -Seconds 2
$lines = Get-OcrLinesSafe
if ($null -eq $lines) { Out-Json "pending" "AutoClaw 未在前台（请点击其窗口后重试）" }
$anchor = Find-CheckinAnchor $lines
if (-not $anchor) {
    # Homepage has no check-in content; navigate via the bottom-left entry first.
    # 按词定位：避免整行中心点偏到相邻元素（如「灵感与活动每日签到赚积分」合并行）
    # 入口找不到大概率是广告还盖着（或页面没加载完），多试几轮而不是一次就放弃。
    $entry = $null
    foreach ($try in 1..3) {
        $entry = Find-WordHit $lines "灵感与活动"
        if (-not $entry) { $entry = Find-Line $lines "灵感与活动" }
        if (-not $entry) { $entry = Find-WordHit $lines "我的积分" }
        if (-not $entry) { $entry = Find-Line $lines "我的积分" }
        if ($entry) { break }
        Start-Sleep -Seconds 5
        Close-AdOverlays
        $lines = Get-OcrLinesSafe
        if ($null -eq $lines) { Out-Json "pending" "AutoClaw 不在前台，无法确认页面" }
    }
    if (-not $entry) {
        Out-Json "pending" ("未找到入口（灵感与活动/我的积分），已重试 3 轮；页面文字: " + (($lines | Select-Object -First 6 | ForEach-Object { $_.text }) -join "/"))
    }
    if ($DryRun) {
        # DryRun 也要点开入口：签到卡片在灵感中心里，不点开只能看到首页，
        # 拿不到真正的锚点布局。这只是切换视图，不领积分；
        # 真正的签到按钮由后面的 DryRun 分支拦住。
        Write-Output ("[dryrun] 点开入口: " + $entry.text + " @ " + ($entry.x + [int]($entry.w / 2)) + "," + ($entry.y + [int]($entry.h / 2)))
    }
    Log ("step: 点开入口 " + $entry.text)
    $beforeSig = Get-SigSet $lines
    Click-At ($entry.x + [int]($entry.w / 2)) ($entry.y + [int]($entry.h / 2))

    # 灵感中心的卡片是云端下发的，冷启动后常常要十几秒才渲染出来。
    # 只等一轮 6 秒会在「页面已切换、卡片还没到」时误判成找不到入口。
    $anchor = $null
    $samePageChecked = $false
    $entryRetried = $false
    foreach ($round in 1..6) {
        Start-Sleep -Seconds 5
        Close-AdOverlays
        $lines = Get-OcrLinesSafe
        if ($null -eq $lines) { continue }
        if (-not $samePageChecked) {
            $samePageChecked = $true
            if (Test-SamePage $beforeSig $lines) {
                if (-not $entryRetried) {
                    # 合成消息对导航不生效（2026-10-22 v2.1.0 实测），移回窗口真实点一次。
                    # 不走 UIA：CEF a11y 被禁用，Invoke 必失败。
                    $entryRetried = $true
                    Log "step: 入口点击未生效，改真实点击重试一次"
                    Click-At ($entry.x + [int]($entry.w / 2)) ($entry.y + [int]($entry.h / 2)) -SkipSynth -SkipUia
                    $samePageChecked = $false
                    continue
                }
                Dump-Ocr $lines "pending-点入口后页面无变化"
                Out-Json "pending" ("点击「" + $entry.text + "」后页面无变化：点击未生效。未提权时输入会被 UIPI 丢弃，请用 scripts\run_claim_only.py（ShellExecuteW runas）提权跑")
            }
        }
        # 严格匹配：不能用 Contains，首页「每日签到赚积分」这类引导文案会假阳性命中
        Log ("step: 等签到卡渲染 round=" + $round)
        $anchor = Find-CheckinAnchor $lines
        if ($anchor) { break }
        Dump-Ocr $lines ("inspiration-loading-round" + $round)
    }
    if (-not $anchor) {
        $peek = ($lines | Select-Object -First 10 | ForEach-Object { $_.text }) -join "/"
        Out-Json "pending" ("点击入口后 30s 内仍未渲染出「每日签到」，当前页面: " + $peek)
    }
}

# On the activity page. Dump full OCR layout for offline tuning before clicking.
Dump-Ocr $lines "activity-page"

# Prefer a real button label found by OCR over a blind offset.
$btnX = $anchor.x + 100
$btnY = $anchor.y + 95
$btnByLabel = $null
foreach ($kw in @("立即领取", "去签到", "立即签到", "领取", "签到")) {
    foreach ($l in $lines) {
        if ($l.text.Contains($kw) -and $l.text.Length -le 6 -and $l.text -notmatch "每日|已") {
            $btnByLabel = $l
            break
        }
    }
    if ($btnByLabel) { break }
}
if ($btnByLabel) {
    $btnX = $btnByLabel.x + [int]($btnByLabel.w / 2)
    $btnY = $btnByLabel.y + [int]($btnByLabel.h / 2)
}
$doneLine = $null
foreach ($l in $lines) {
    # x must stay within the same task card: the "邀请好友" card on the right
    # has a "已完成0次" line at the same height (OCR misread of 已邀请0次).
    if ($l.text.Contains("已完成") -and [Math]::Abs($l.y - ($anchor.y + 95)) -lt 60 -and $l.x -lt ($anchor.x + 400)) { $doneLine = $l; break }
}

if ($doneLine) {
    Out-Json "already" ("今日已签到（" + $doneLine.text + "），无需重复点击")
}

if ($DryRun) {
    Out-Json "dryrun" ("找到「每日签到」@ " + $anchor.x + "," + $anchor.y + "，将点击按钮 @ " + $btnX + "," + $btnY)
}

$preStreak = 0
foreach ($l in $lines) {
    $m = [regex]::Match($l.text, '已签到\s*(\d+)\s*天')
    if ($m.Success) { $preStreak = [int]$m.Groups[1].Value; break }
}
Log ("step: 点击前连签=" + $preStreak)

# 2026-10-25：首击经常只完成 CEF/React 的焦点切换，onClick 不触发。改成
# 「短间隔双击」：一轮里连点 2 下（180ms 间隔），没签上再换下一轮，最多 3 轮
# （共 6 次点击）。已领取后按钮会禁用，重复点击是幂等的；每轮之间用 OCR 复核，
# 一旦出现成功标记/已完成/连签+1/按钮连续两帧消失就立即收手。
$okHit = $null
$alreadyHit = $null
$btnGone = $false
$maxRounds = 3
$clicksPerRound = 2
$clickIntervalMs = 180
for ($round = 1; $round -le $maxRounds; $round++) {
    Log ("step: 第 " + $round + "/" + $maxRounds + " 轮双击签到按钮（" + $clicksPerRound + " 击，间隔 " + $clickIntervalMs + "ms）")
    Click-At $btnX $btnY -SkipSynth -SkipUia -Clicks $clicksPerRound -IntervalMs $clickIntervalMs
    $btnGoneFrames = 0
    foreach ($wait in @(1200, 1800)) {
        Start-Sleep -Milliseconds $wait
        $after = Get-OcrLinesSafe
        if ($null -eq $after) { continue }
        $anchor2 = Find-CheckinAnchor $after
        if (-not $anchor2) { continue }
        $btnStill = $false
        foreach ($l in $after) {
            if ($l.text -eq "签到" -and [Math]::Abs($l.y - ($anchor2.y + 95)) -lt 60 -and $l.x -lt ($anchor2.x + 400)) { $btnStill = $true; break }
        }
        # 单帧漏读很常见；按钮连续两帧都不在，才算「消失」
        if ($btnStill) { $btnGoneFrames = 0 } else { $btnGoneFrames++ }
        if ($btnGoneFrames -ge 2) { $btnGone = $true; break }
        foreach ($l in $after) {
            if (($l.text.Contains("签到成功") -or $l.text.Contains("领取成功")) -and [Math]::Abs($l.y - ($anchor2.y + 95)) -lt 200) { $okHit = $l; break }
        }
        if ($okHit) { break }
        foreach ($l in $after) {
            if ($l.text.Contains("已完成") -and [Math]::Abs($l.y - ($anchor2.y + 95)) -lt 60 -and $l.x -lt ($anchor2.x + 400)) { $alreadyHit = $l; break }
        }
        if ($alreadyHit) { break }
        # 卡片上的连签天数也是硬证据：10-24 点击前 16 天、点击后 17 天。
        foreach ($l in $after) {
            $m2 = [regex]::Match($l.text, '已签到\s*(\d+)\s*天')
            if ($m2.Success -and [int]$m2.Groups[1].Value -gt $preStreak) {
                $alreadyHit = @{ text = ("已签到{0}天（点击前 {1} 天）" -f $m2.Groups[1].Value, $preStreak) }
                break
            }
        }
        if ($alreadyHit) { break }
    }
    if ($okHit -or $alreadyHit -or $btnGone) { break }
    Start-Sleep -Milliseconds 500
}
Log "step: 复核点击结果"
if ($okHit) { Out-Json "ok" ("签到成功: " + $okHit.text) }
# 能走到这里说明卡片是「本次点击之后」才变成已完成的——那就是本次签到成功，
# 必须判 ok。「点击前就已签」在上面 doneLine 分支提前返回了 already，
# 两者不能混：判成 already 的话，将来接自动入账（ok 才入账）会静默漏掉一天。
if ($alreadyHit) { Out-Json "ok" ("签到成功（点击后显示: " + $alreadyHit.text + "）") }
if ($btnGone) { Out-Json "ok" "签到按钮已消失，判定签到成功" }
Out-Json "pending" "已点击签到位置，未检测到成功提示"
