# MiniMax Code daily check-in via screenshot+OCR+click. ASCII code only.
# The check-in card ("每日签到 / 今天 @400") sits on the home sidebar, no navigation needed.
# On success: restores the previously focused window, and closes the client if
# this script was the one that started it (-NoClose to opt out).
param(
    [string]$OutFile = "",
    # 默认会在签到成功后关闭「本次由脚本拉起」的客户端；签到前已运行的不动。
    # -NoClose 用于探索期：保留窗口以便反复调试，不必每次重拉（重拉会弹 UAC）。
    [switch]$NoClose
)
$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

# Surface terminating errors instead of dying silently.
trap {
    try {
        $m = "FATAL: " + $_.Exception.Message + " @ " + $_.InvocationInfo.PositionMessage
        $p = "$PSScriptRoot\..\logs\minimax_claim.json"
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
  [DllImport("user32.dll")] public static extern void mouse_event(uint flags, uint dx, uint dy, uint data, UIntPtr extra);
  [DllImport("user32.dll")] public static extern bool EnumWindows(EnumProc cb, IntPtr lp);
  [DllImport("user32.dll")] public static extern uint GetWindowThreadProcessId(IntPtr hWnd, out uint pid);
  [DllImport("user32.dll")] public static extern bool IsWindowVisible(IntPtr hWnd);
  [DllImport("kernel32.dll")] public static extern uint GetCurrentThreadId();
  [DllImport("user32.dll")] public static extern bool AttachThreadInput(uint idAttach, uint idAttachTo, bool fAttach);
  [DllImport("user32.dll")] public static extern bool ShowWindow(IntPtr hWnd, int nCmdShow);
  [DllImport("user32.dll")] public static extern void keybd_event(byte bVk, byte bScan, uint dwFlags, UIntPtr dwExtraInfo);
  [DllImport("user32.dll")] public static extern bool PrintWindow(IntPtr hWnd, IntPtr hdcBlt, uint nFlags);
  [DllImport("user32.dll")] public static extern IntPtr SendMessageTimeout(IntPtr hWnd, uint msg, UIntPtr wParam, IntPtr lParam, uint fuFlags, uint uTimeout, out IntPtr lpdwResult);
  [DllImport("user32.dll")] public static extern bool ScreenToClient(IntPtr hWnd, ref POINT lpPoint);
  [DllImport("user32.dll")] public static extern IntPtr WindowFromPoint(POINT p);
  [DllImport("user32.dll")] public static extern IntPtr ChildWindowFromPointEx(IntPtr hWnd, POINT p, uint flags);
  public struct RECT { public int Left, Top, Right, Bottom; }
  public struct POINT { public int X, Y; }
  public delegate bool EnumProc(IntPtr hWnd, IntPtr lp);
}
"@

Add-Type @"
using System;
using System.Runtime.InteropServices;
[ComImport, Guid("A5CD92FF-29BE-454C-8D04-D82879FB3F1B"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
public interface IVirtualDesktopManager {
  int IsWindowOnCurrentVirtualDesktop(IntPtr hWnd, out bool onCurrent);
}
[ComImport, Guid("AA509086-5CA9-4C25-8F95-589D3C07B48A")]
public class CVirtualDesktopManager { }
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

$script:SavedHwnd = [IntPtr]::Zero
$script:CloseAllowed = $false

function Save-Foreground {
    # Remember what the user was actually using, so we can hand focus back.
    # If MiniMax is already in front there is nothing to restore.
    if ($script:SavedHwnd -ne [IntPtr]::Zero) { return }
    $cur = [Cap32]::GetForegroundWindow()
    if ($cur -ne [IntPtr]::Zero -and $cur -ne $hwnd) { $script:SavedHwnd = $cur }
}

function Restore-Foreground {
    if ($script:SavedHwnd -eq [IntPtr]::Zero) { return }
    $h = $script:SavedHwnd
    # Windows ignores SetForegroundWindow from a process that does not own the
    # foreground. Attach to the current foreground thread first, which is the
    # sanctioned way to borrow it, then retry a couple of times.
    $myThread = [Cap32]::GetCurrentThreadId()
    $ok = $false
    for ($i = 0; $i -lt 3; $i++) {
        # SW_RESTORE first: a window on another virtual desktop is DWM-cloaked and
        # refuses to take focus until it is shown again.
        [void][Cap32]::ShowWindow($h, 9)
        Start-Sleep -Milliseconds 150
        # Tap Alt: Windows hands the foreground to whoever owns it, and a process
        # that does not will have SetForegroundWindow silently ignored otherwise.
        [Cap32]::keybd_event(0x12, 0, 0, [UIntPtr]::Zero)
        [Cap32]::keybd_event(0x12, 0, 2, [UIntPtr]::Zero)
        $scratch = [uint32]0
        $fgThread = [Cap32]::GetWindowThreadProcessId([Cap32]::GetForegroundWindow(), [ref]$scratch)
        [void][Cap32]::AttachThreadInput($myThread, $fgThread, $true)
        $ok = [Cap32]::SetForegroundWindow($h)
        [void][Cap32]::AttachThreadInput($myThread, $fgThread, $false)
        if ($ok) { break }
        Start-Sleep -Milliseconds 300
    }
    $script:SavedHwnd = [IntPtr]::Zero
}

function Stop-LaunchedApp {
    # Only ever close what *we* started. If any MiniMax process was already
    # alive when the script began, we touch nothing.
    # Default is NO-CLOSE: closing after every run forces a fresh elevated
    # launch next time, which means another UAC prompt for the human.
    if ($NoClose) { return }
    if (-not $script:CloseAllowed) { return }

    Start-Sleep -Seconds 3
    $procs = @(Get-Process -Name $AppProcess -ErrorAction SilentlyContinue)
    if ($procs.Count -eq 0) { return }

    foreach ($p in $procs) {
        try { $p.CloseMainWindow() | Out-Null } catch { }
    }
    Start-Sleep -Seconds 8
    foreach ($p in @(Get-Process -Name $AppProcess -ErrorAction SilentlyContinue)) {
        try { Stop-Process -Id $p.Id -Force -ErrorAction SilentlyContinue } catch { }
    }
}

function Out-Json([string]$status, [string]$detail) {
    # On success give the window back, then close the client if we launched it.
    # On failure keep it open -- the human needs to look at it.
    if ($status -eq "ok" -or $status -eq "already") { Stop-LaunchedApp }
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

$exe = 'C:\Users\Hunter\AppData\Local\Programs\MiniMax Code\MiniMax Code.exe'
$AppProcess = 'MiniMax Code'

# KNOWN GAP (2026-09-23): the cold-start path below is UNVERIFIED. Launching the
# client from an automated context produced no process and no log entry at all
# (Roaming\MiniMax\logs stayed at its previous mtime), while the same context can
# launch notepad fine. So either the app or the host blocks it. If cold start
# never works, Stop-LaunchedApp can never fire -- it only closes what we started.

# Snapshot before we touch anything. If the client was ALREADY running we must
# never close it -- the user may be mid-session. Only a client we start ourselves
# is ours to shut down.
$preexisting = @(Get-Process -Name $AppProcess -ErrorAction SilentlyContinue | ForEach-Object { $_.Id })
$script:CloseAllowed = ($preexisting.Count -eq 0)

function Find-AppWindow {
    $script:BestHwnd = [IntPtr]::Zero
    $script:BestArea = 0
    $pidSet = @{}
    Get-Process 'MiniMax Code' -ErrorAction SilentlyContinue | ForEach-Object { $pidSet[[uint32]$_.Id] = $true }
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
            # Do NOT require IsWindowVisible here. An Electron window parked on
            # another virtual desktop (or DWM-cloaked) reports visible=false
            # while still holding a real rect -- filtering on it made us miss the
            # main window entirely and report a bogus "not found". Size is the
            # reliable discriminator: only the real window is 1400x900-ish.
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

$hwnd = Find-AppWindow
if ($hwnd -eq [IntPtr]::Zero) {
    if (Test-Path $exe) { Start-Process $exe }
    $dl = (Get-Date).AddSeconds(60)
    while ((Get-Date) -lt $dl) {
        Start-Sleep -Seconds 2
        $hwnd = Find-AppWindow
        if ($hwnd -ne [IntPtr]::Zero) { break }
    }
    if ($hwnd -eq [IntPtr]::Zero) { Out-Json "notfound" "MiniMax Code 启动后 60s 内未出现主窗口" }
    # 冷启动后给渲染多留时间，避免抓到白屏
    Start-Sleep -Seconds 12
}

function Wait-Foreground {
    Save-Foreground
    # A window parked in the tray keeps a perfectly good rect but is NOT visible,
    # so CopyFromScreen photographs whatever sits underneath it. (Confirmed 2026-09-23:
    # IsWindowVisible=false, yet IVirtualDesktopManager says it IS on the current
    # desktop -- so this is a hidden window, not a desktop issue.) Force it back
    # on screen before trusting any screenshot or click.
    [void][Cap32]::ShowWindow($hwnd, 9)
    Start-Sleep -Milliseconds 300
    if ([Cap32]::GetForegroundWindow() -eq $hwnd) { return $true }
    [Cap32]::SetForegroundWindow($hwnd) | Out-Null
    Start-Sleep -Milliseconds 800
    if ([Cap32]::GetForegroundWindow() -eq $hwnd) { return $true }
    $dl = (Get-Date).AddSeconds(45)
    while ((Get-Date) -lt $dl) {
        Start-Sleep -Milliseconds 600
        if ([Cap32]::GetForegroundWindow() -eq $hwnd) { return $true }
    }
    return $false
}

function Get-OcrLinesSafe {
    # Foreground is best-effort now: PrintWindow captures the window even when it
    # is occluded or not in front, so a refused foreground switch must not abort
    # the run (it used to return $null -> "未在前台" -> pending).
    try { Wait-Foreground | Out-Null } catch { }
    return Get-OcrLines
}

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

# A window parked on another virtual desktop still reports a valid rect and even
# accepts SetForegroundWindow, but CopyFromScreen then captures whatever the
# CURRENT desktop shows -- we OCR a stranger's window and click into it. Refuse.
try {
    $vdm = New-Object CVirtualDesktopManager
    $onCurrent = $false
    $hr = $vdm.IsWindowOnCurrentVirtualDesktop($hwnd, [ref]$onCurrent)
    if ($hr -eq 0 -and -not $onCurrent) {
        Out-Json "pending" "MiniMax Code 在另一个虚拟桌面，无法安全截图点击（请切到它所在的桌面）"
    }
} catch { }

$rect = New-Object Cap32+RECT
[Cap32]::GetWindowRect($hwnd, [ref]$rect) | Out-Null
$winW = $rect.Right - $rect.Left
$winH = $rect.Bottom - $rect.Top
$winX = $rect.Left
$winY = $rect.Top

# 诊断用：保存一次主窗口截图，便于肉眼定位签到按钮（不影响点击逻辑）
try {
    $shot = New-Object System.Drawing.Bitmap($winW, $winH)
    $sg = [System.Drawing.Graphics]::FromImage($shot)
    $hdc2 = $sg.GetHdc()
    $pw2 = [Cap32]::PrintWindow($hwnd, $hdc2, 2)
    $sg.ReleaseHdc($hdc2)
    if (-not $pw2 -or (Test-Blank $shot)) { $sg.CopyFromScreen($winX, $winY, 0,0, $shot.Size) }
    $sg.Dispose()
    $shot.Save("C:\Users\Hunter\Documents\Warpeas\agent-credit\logs\minimax_shot.png", [System.Drawing.Imaging.ImageFormat]::Png)
    $shot.Dispose()
} catch { }

function Get-OcrLines {
    $bmp = New-Object System.Drawing.Bitmap($winW, $winH)
    $g = [System.Drawing.Graphics]::FromImage($bmp)
    # PrintWindow: captures the window itself, so it works while occluded, not in
    # the foreground, or on a locked session. Fall back to screen capture when it
    # yields a blank frame (some GPU-composited apps return black/white).
    $hdc = $g.GetHdc()
    $pw = [Cap32]::PrintWindow($hwnd, $hdc, 2)
    $g.ReleaseHdc($hdc)
    if (-not $pw -or (Test-Blank $bmp)) {
        $g.CopyFromScreen($winX, $winY, 0, 0, $bmp.Size)
    }
    $g.Dispose()
    try { $script:ShotBmp = $bmp.Clone() } catch { }
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
        $lines += @{ text = $text; x = $minX; y = $minY; w = ($maxX - $minX); h = ($maxY - $minY) }
    }
    return $lines
}

function Find-Line($lines, [string]$needle) {
    foreach ($l in $lines) {
        if ($l.text.Contains($needle)) { return $l }
    }
    return $null
}

function Click-At([int]$ax, [int]$ay) {
    $sx = $winX + $ax
    $sy = $winY + $ay

    # 1) Already in front -> real input injection (most reliable).
    if ([Cap32]::GetForegroundWindow() -eq $hwnd) {
        [Cap32]::SetCursorPos($sx, $sy) | Out-Null
        Start-Sleep -Milliseconds 120
        [Cap32]::mouse_event(0x0002, 0, 0, 0, [UIntPtr]::Zero)
        [Cap32]::mouse_event(0x0004, 0, 0, 0, [UIntPtr]::Zero)
        return
    }

    # 2) Otherwise deliver the click into the window's own message queue, which
    #    needs no foreground at all. Prefer the real top-most window at the point
    #    (Electron/CEF popups may be separate windows), verifying the process.
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
    Start-Sleep -Milliseconds 150
    $r1 = [Cap32]::SendMessageTimeout($target, 0x0201, [UIntPtr]::new([uint64]1), $lp, 0, 1500, [ref]$res)
    Start-Sleep -Milliseconds 90
    $r2 = [Cap32]::SendMessageTimeout($target, 0x0202, [UIntPtr]::Zero, $lp, 0, 1500, [ref]$res)
    if ($r1 -ne [IntPtr]::Zero -and $r2 -ne [IntPtr]::Zero) { return }

    # 3) Last resort: real cursor input anyway.
    [Cap32]::SetCursorPos($sx, $sy) | Out-Null
    Start-Sleep -Milliseconds 120
    [Cap32]::mouse_event(0x0002, 0, 0, 0, [UIntPtr]::Zero)
    [Cap32]::mouse_event(0x0004, 0, 0, 0, [UIntPtr]::Zero)
}

$lines = Get-OcrLinesSafe
if ($null -eq $lines) { Out-Json "pending" "MiniMax Code 未在前台（请点击其窗口后重试）" }

# Sanity gate: confirm we actually photographed MiniMax. A top-most window parked
# over it (or another desktop) still yields a plausible-looking OCR dump -- and we
# would then click straight into that stranger's window. Its title bar sits at the
# very top, so require the brand string up there before touching the mouse.
$confirmed = $false
foreach ($l in $lines) {
    if ($l.y -lt 120 -and $l.text -match "(?i)min[i1l]max|code") { $confirmed = $true; break }
}
# 容错：只要捕捉到 MiniMax 主页特有的「每日签到」卡片即确认窗口正确
# （OCR 偶发把标题栏误识为 MinlMaxC0de，品牌串匹配会漏，改用语义特征词）
if (-not $confirmed) {
    foreach ($l in $lines) {
        if ($l.text -match "每日签到") { $confirmed = $true; break }
    }
}
if (-not $confirmed) {
    $top = ($lines | Where-Object { $_.y -lt 120 } | Select-Object -First 5 | ForEach-Object { $_.text }) -join "/"
    Out-Json "pending" ("截图未确认是 MiniMax 窗口（顶部无标题，可能被遮挡），已放弃点击。顶部: " + $top)
}

# Anchor: the "每日签到" card, which lives in the far-LEFT sidebar.
# A plain text search happily matches the same phrase inside a chat transcript
# (this project's own conversations contain it), which sent us clicking into the
# chat column. Take the leftmost hit and reject anything in the right-hand column.
$anchor = $null
foreach ($l in $lines) {
    if ($l.text.Contains("每日签到")) {
        if ($null -eq $anchor -or $l.x -lt $anchor.x) { $anchor = $l }
    }
}
if ($anchor -and $anchor.x -gt [int]($winW * 0.4)) { $anchor = $null }
if (-not $anchor) {
    $peek = ($lines | Select-Object -First 8 | ForEach-Object { $_.text }) -join "/"
    Out-Json "pending" ("未找到「每日签到」卡片（今日已签后卡片会收起），当前页面: " + $peek)
}

# Already-checked markers on/near the card.
# NOTE: the action button ("签到得@400") sits ~370px BELOW the "每日签到" title,
# so the window must extend far down from the anchor, not +/-120.
foreach ($l in $lines) {
    if (($l.text.Contains("已签") -or $l.text.Contains("已领")) -and
        $l.y -ge ($anchor.y - 60) -and $l.y -le ($anchor.y + 700) -and $l.x -lt ($anchor.x + 500)) {
        Out-Json "already" ("今日已签（" + $l.text + "）")
    }
}

# Button: prefer the real action button ("签到得@400"), fall back to the "今天" cell.
# Clicking the "今天" label was the historical bug -- it is not clickable.
$btn = $null
foreach ($l in $lines) {
    if ($l.y -le $anchor.y) { continue }
    if ($l.y -gt ($anchor.y + 700)) { continue }
    if ($l.x -gt ($anchor.x + 400)) { continue }
    if ($l.text -match "连续签到") { continue }
    if ($l.text -match "签到得|领取|领积分|签到领") {
        if ($null -eq $btn -or $l.y -gt $btn.y) { $btn = $l }
    }
}
if (-not $btn) {
    # Once today's claim goes through the card collapses: the title stays but the
    # day grid and the button are gone. Clicking anything here is pointless, so
    # read that shape as "already claimed" instead of firing a blind click.
    $hasGrid = $false
    foreach ($l in $lines) {
        if ($l.y -le $anchor.y) { continue }
        if ($l.y -gt ($anchor.y + 700)) { continue }
        if ($l.x -gt ($anchor.x + 500)) { continue }
        if ($l.text -match "天|@|签到得|领取") { $hasGrid = $true; break }
    }
    if (-not $hasGrid) {
        Out-Json "already" "签到卡只剩标题（日期格与按钮均已收起），判定今日已签"
    }
    # Geometric fallback: the action button sits at a FIXED offset from the
    # "每日签到" title -- measured (+207, +373) across two different window sizes.
    $btn = @{ text = "(fallback-offset)"; x = ($anchor.x + 114); y = ($anchor.y + 360); w = 185; h = 26 }
}
$btnX = $btn.x + [int]($btn.w / 2)
$btnY = $btn.y + [int]($btn.h / 2)

if ($OutFile -eq "__DUMP__") { }

# Dump for offline tuning
$dumpPath = "C:\Users\Hunter\Documents\Warpeas\agent-credit\logs\minimax_ocr_dump.txt"
try {
    $stamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    $lines_txt = ($lines | ForEach-Object { "{0} | {1},{2} {3}x{4}" -f $_.text, $_.x, $_.y, $_.w, $_.h }) -join "`n"
    [System.IO.File]::AppendAllText($dumpPath, "[$stamp]`n$lines_txt`n---`n", (New-Object System.Text.UTF8Encoding($false)))
} catch { }

Click-At $btnX $btnY

# Multi-frame verification: button text change / success toast / already marker.
$okHit = $null
$alreadyHit = $null
foreach ($wait in @(1500, 2500, 3500)) {
    Start-Sleep -Milliseconds $wait
    $after = Get-OcrLinesSafe
    if ($null -eq $after) { continue }
    $a2 = Find-Line $after "每日签到"
    if (-not $a2) { continue }
    foreach ($l in $after) {
        if (($l.text.Contains("成功") -or $l.text.Contains("已领") -or $l.text.Contains("已签")) -and
            [Math]::Abs($l.y - $btnY) -lt 300 -and $l.x -lt ($a2.x + 600)) {
            if ($l.text -notmatch "连续签到得") { $okHit = $l; break }
        }
    }
    if ($okHit) { break }
    foreach ($l in $after) {
        if ($l.text.Contains("已签") -and [Math]::Abs($l.y - $btnY) -lt 300 -and $l.x -lt ($a2.x + 500)) {
            $alreadyHit = $l; break
        }
    }
    if ($alreadyHit) { break }
}
if ($okHit) { Out-Json "ok" ("签到成功: " + $okHit.text) }
if ($alreadyHit) { Out-Json "already" ("点击后显示: " + $alreadyHit.text) }
Out-Json "pending" ("已点击签到按钮「" + $btn.text + "」@ " + $btnX + "," + $btnY + "，未检测到成功提示")
