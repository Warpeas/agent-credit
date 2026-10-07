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
$root = Split-Path -Parent $PSScriptRoot
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
  [DllImport("user32.dll", CharSet = CharSet.Unicode)] public static extern int GetWindowText(IntPtr hWnd, System.Text.StringBuilder s, int n);
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
    # 运行结束一律恢复现场：关掉本次由脚本拉起的实例（签到前就开着的保留），
    # 再把前台还给运行前的窗口。失败时也不留窗口——无人值守跑完桌面不该堆着
    # 客户端，诊断信息已落日志（minimax_shot.png / ocr dump）与台账。
    Stop-LaunchedApp
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

$exe = '$env:APPDATA\AppData\Local\Programs\MiniMax Code\MiniMax Code.exe'
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

function Test-WindowBlank($h, $w, $hh) {
    # A window can hold a perfectly good rect and still render nothing -- MiniMax
    # opens an extra all-black window next to the real one (reported by the user
    # 2026-09-30). PrintWindow a thumbnail and see whether it is one flat colour.
    try {
        $bw = [Math]::Min($w, 480)
        $bh = [Math]::Min($hh, 320)
        $b = New-Object System.Drawing.Bitmap($bw, $bh)
        $g = [System.Drawing.Graphics]::FromImage($b)
        $hdc = $g.GetHdc()
        $pw = [Cap32]::PrintWindow($h, $hdc, 2)
        $g.ReleaseHdc($hdc)
        $g.Dispose()
        if (-not $pw) { $b.Dispose(); return $true }
        $c0 = $b.GetPixel(4, 4)
        $flat = $true
        for ($i = 1; $i -le 6; $i++) {
            for ($j = 1; $j -le 6; $j++) {
                $c = $b.GetPixel([int]($bw * $i / 7), [int]($bh * $j / 7))
                if ([Math]::Abs($c.R - $c0.R) -gt 6 -or
                    [Math]::Abs($c.G - $c0.G) -gt 6 -or
                    [Math]::Abs($c.B - $c0.B) -gt 6) { $flat = $false; break }
            }
            if (-not $flat) { break }
        }
        $b.Dispose()
        return $flat
    } catch { return $true }
}

function Find-AppWindow {
    param([switch]$RequireNamed)

    $pidSet = @{}
    Get-Process 'MiniMax Code' -ErrorAction SilentlyContinue | ForEach-Object { $pidSet[[uint32]$_.Id] = $true }
    if ($pidSet.Count -eq 0) { return [IntPtr]::Zero }
    $script:Cands = @()
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
            # main window entirely and report a bogus "not found".
            if ($w -gt 500 -and $hh -gt 400) {
                $sb = New-Object System.Text.StringBuilder 256
                [Cap32]::GetWindowText($h, $sb, 256) | Out-Null
                $script:Cands += @{ h = $h; w = $w; hh = $hh; x = $r.Left; y = $r.Top;
                                    vis = [Cap32]::IsWindowVisible($h); title = $sb.ToString() }
            }
        }
        return $true
    }
    [Cap32]::EnumWindows($cb, [IntPtr]::Zero) | Out-Null

    # Every coordinate we click is derived from the chosen window's rect, so a
    # blank decoy window silently shifts the whole run. Log the candidates.
    try {
        $out = "=== $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') window scan ===`n"
        foreach ($c in $script:Cands) {
            $blank = Test-WindowBlank $c.h $c.w $c.hh
            $out += ("hwnd={0} rect={1},{2} {3}x{4} visible={5} blank={6} title={7}`n" -f `
                     $c.h, $c.x, $c.y, $c.w, $c.hh, $c.vis, $blank, $c.title)
        }
        [System.IO.File]::AppendAllText(
            "$root\logs\minimax_windows.txt",
            $out, (New-Object System.Text.UTF8Encoding($false)))
    } catch { }

    # MiniMax keeps TWO top-level BrowserWindows on the SAME pid (MAIN process).
    # Cold-start timeline measured 2026-10-02, sampling every 0.3s from launch:
    #   t=0.0-0.8s  MAIN process up, zero windows
    #   t=1.3s      Chrome_WidgetWin_0 appears: 1440x756, invisible, PrintWindow
    #               returns one flat black colour   <-- decoy, exists FIRST
    #   t=2.1s      Chrome_WidgetWin_1 appears: titled "MiniMax Code", visible,
    #               renders (colour count 11 -> 35 by t=3.9s)   <-- the real one
    # The decoy is the app's promo/overlay window: on 2026-09-30 23:21-23:26 it
    # logged visible=True AND blank=False at 2880x1511 (near full-screen), which
    # is exactly the "all-black window" and "ad covering everything" the user saw.
    # Locking onto it shifts every click coordinate, which reads as "the click
    # got swallowed".
    #
    # Rank: named+visible > named > visible+renders > renders > named-but-blank.
    # An UNNAMED window that renders flat black scores 0 and is never selectable,
    # so the decoy can never win even when it is the only window present.
    $rank = @()
    foreach ($c in $script:Cands) {
        $blank = Test-WindowBlank $c.h $c.w $c.hh
        $named = $c.title -match "(?i)minimax"
        $score = 0
        if ($named -and $c.vis) { $score = 5 }
        elseif ($named) { $score = 4 }
        elseif ($c.vis -and -not $blank) { $score = 3 }
        elseif (-not $blank) { $score = 2 }
        elseif ($named) { $score = 1 }
        $rank += @{ h = $c.h; score = $score; area = ($c.w * $c.hh) }
    }
    $best = $rank | Sort-Object @{ e = 'score'; desc = $true }, @{ e = 'area'; desc = $true } |
            Select-Object -First 1
    if (-not $best) { return [IntPtr]::Zero }
    # Only the decoy around (unnamed + flat black) -> refuse, keep waiting.
    if ($best.score -le 0) { return [IntPtr]::Zero }
    # Callers waiting for a launch must demand a titled window (score>=4).
    if ($RequireNamed -and $best.score -lt 4) { return [IntPtr]::Zero }
    return $best.h
}

$hwnd = Find-AppWindow
if ($hwnd -eq [IntPtr]::Zero) {
    if (Test-Path $exe) { Start-Process $exe }
    $dl = (Get-Date).AddSeconds(90)
    while ((Get-Date) -lt $dl) {
        Start-Sleep -Seconds 2
        # Require a TITLED window while waiting: the black decoy shows up first
        # and would otherwise be accepted as "the window has appeared".
        $hwnd = Find-AppWindow -RequireNamed
        if ($hwnd -ne [IntPtr]::Zero) { break }
    }
    if ($hwnd -eq [IntPtr]::Zero) {
        # Relax the titled-window rule as a last resort. Safe since 2026-10-02:
        # Find-AppWindow now scores the unnamed all-black decoy 0 and refuses it,
        # so this can no longer latch onto the decoy and click at bogus coords.
        $hwnd = Find-AppWindow
    }
    if ($hwnd -eq [IntPtr]::Zero) { Out-Json "notfound" "MiniMax Code 启动后 90s 内未出现主窗口" }
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
    $shot.Save("$root\logs\minimax_shot.png", [System.Drawing.Imaging.ImageFormat]::Png)
    $shot.Dispose()
} catch { }

function Ocr-Bitmap($bmp) {
    $ms = New-Object System.IO.MemoryStream
    $bmp.Save($ms, [System.Drawing.Imaging.ImageFormat]::Png)
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
    return ,$lines
}

function Get-OcrLines {
    $bmp = New-Object System.Drawing.Bitmap($winW, $winH)
    $g = [System.Drawing.Graphics]::FromImage($bmp)
    # PrintWindow captures the window itself (works while occluded / not in
    # front). Fall back to screen capture on a blank frame, and - critically -
    # on a frame that OCR finds almost nothing in: Electron windows sometimes
    # hand PrintWindow a stale/unrendered surface, which used to make the brand
    # check fail and abort the whole claim.
    $hdc = $g.GetHdc()
    $pw = [Cap32]::PrintWindow($hwnd, $hdc, 2)
    $g.ReleaseHdc($hdc)
    if (-not $pw -or (Test-Blank $bmp)) {
        $g.CopyFromScreen($winX, $winY, 0, 0, $bmp.Size)
    }
    $g.Dispose()
    $lines1 = Ocr-Bitmap $bmp
    if ($lines1.Count -ge 3) {
        try { $script:ShotBmp = $bmp.Clone() } catch { }
        $bmp.Dispose()
        return ,$lines1
    }

    $bmp2 = New-Object System.Drawing.Bitmap($winW, $winH)
    $g2 = [System.Drawing.Graphics]::FromImage($bmp2)
    $g2.CopyFromScreen($winX, $winY, 0, 0, $bmp2.Size)
    $g2.Dispose()
    $lines2 = Ocr-Bitmap $bmp2
    if ($lines2.Count -gt $lines1.Count) {
        try { $script:ShotBmp = $bmp2.Clone() } catch { }
        $bmp.Dispose()
        $bmp2.Dispose()
        return ,$lines2
    }
    $bmp2.Dispose()
    try { $script:ShotBmp = $bmp.Clone() } catch { }
    $bmp.Dispose()
    return ,$lines1
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
$confirmTries = 0
while (-not $confirmed -and $confirmTries -lt 4) {
    $confirmTries++
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
    if ($confirmed) { break }
    # Cold start often lands on a white/black unrendered frame (confirmed
    # 2026-09-30: fresh launch -> blank bitmap -> zero OCR lines -> instant
    # pending). Wait for the renderer to catch up, then re-shoot.
    Start-Sleep -Seconds 6
    $lines = Get-OcrLinesSafe
    if ($null -eq $lines) { break }
}
if (-not $confirmed) {
    $top = ($lines | Where-Object { $_.y -lt 120 } | Select-Object -First 5 | ForEach-Object { $_.text }) -join "/"
    Out-Json "pending" ("截图未确认是 MiniMax 窗口（顶部无标题，可能被遮挡），已放弃点击。顶部: " + $top)
}

# --- Ad interstitial handling (2026-09-30) ---
# The client pops a full-window promo ("模型上新/双重福利，限时开启", active
# 2026-09-28..10-07). Its copy contains BOTH "每日签到" and "领取", which hijacked
# the anchor+button search and clicked into the ad text (614,658 = ad body).
# Detect the ad, try ESC to dismiss, re-shoot; if it survives, fail safe
# (pending, no click) instead of poking a stranger's pixels.
function Test-AdPresent($ls) {
    foreach ($l in $ls) {
        if ($l.text -match "双重福利|福利一|福利二|立即体验|国庆|首发上线") { return $true }
    }
    return $false
}

# Diagnostic only: when ESC cannot dismiss the ad we need to know WHERE its close
# affordance lives. Dump the OCR geometry, the UIA element tree and a dark-pixel
# scan of the ad's top band so the next iteration can click with evidence instead
# of guessing.
function Write-AdProbe($ls) {
    $out = "=== $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') ad probe ===`n"
    $out += "window: ${winW}x${winH} at ${winX},${winY} hwnd=$hwnd`n"
    $out += "--- OCR ---`n"
    foreach ($l in $ls) { $out += ("{0} | {1},{2} {3}x{4}`n" -f $l.text, $l.x, $l.y, $l.w, $l.h) }
    try {
        Add-Type -AssemblyName UIAutomationClient
        Add-Type -AssemblyName UIAutomationTypes
        $ae = [System.Windows.Automation.AutomationElement]::FromHandle($hwnd)
        $all = $ae.FindAll([System.Windows.Automation.TreeScope]::Descendants,
                           [System.Windows.Automation.Condition]::TrueCondition)
        $out += "--- UIA count: " + $all.Count + " ---`n"
        $n = 0
        foreach ($e in $all) {
            if ($n++ -gt 400) { break }
            try {
                $nm = $e.Current.Name
                $ct = $e.Current.ControlType.ProgrammaticName
                if (-not $nm -and $ct -notmatch 'Button|Hyperlink|Image') { continue }
                $r = $e.Current.BoundingRectangle
                $out += ("{0} | {1} | {2},{3} {4}x{5}`n" -f $ct, $nm,
                         [int]$r.X, [int]$r.Y, [int]$r.Width, [int]$r.Height)
            } catch { }
        }
    } catch { $out += "UIA failed: " + $_.Exception.Message + "`n" }
    # Dark-pixel scan: the promo's close glyph is usually a small dark mark near
    # the top-right of the ad panel. Report dark pixel clusters in the top band.
    try {
        if ($script:ShotBmp) {
            $bmp = $script:ShotBmp
            $out += "--- dark clusters (top band y<260) ---`n"
            $sw = $bmp.Width
            $sh = [Math]::Min($bmp.Height, 260)
            $grid = @{}
            for ($y = 0; $y -lt $sh; $y += 4) {
                for ($x = 0; $x -lt $sw; $x += 4) {
                    $c = $bmp.GetPixel($x, $y)
                    if ($c.R -lt 90 -and $c.G -lt 90 -and $c.B -lt 90) {
                        $key = "{0},{1}" -f ([int]($x / 40)), ([int]($y / 40))
                        if (-not $grid.ContainsKey($key)) { $grid[$key] = 0 }
                        $grid[$key] = $grid[$key] + 1
                    }
                }
            }
            foreach ($k in ($grid.GetEnumerator() | Sort-Object -Property Value -Descending | Select-Object -First 12)) {
                $out += ("cell {0} dark={1}`n" -f $k.Key, $k.Value)
            }
        }
    } catch { $out += "pixel scan failed: " + $_.Exception.Message + "`n" }
    [System.IO.File]::AppendAllText(
        "$root\logs\minimax_ad_probe.txt",
        $out, (New-Object System.Text.UTF8Encoding($false)))
}


# Anchor: the "每日签到" card, which lives in the far-LEFT sidebar.
# A plain text search happily matches the same phrase inside a chat transcript
# (this project's own conversations contain it), which sent us clicking into the
# chat column. Take the leftmost hit and reject anything in the right-hand column.
#
# 2026-09-30: the promo panel ("双重福利，限时开启", 9/28-10/07) is NORMAL CONTENT,
# not a modal -- it sits in the right-hand content column (x>=649) and its copy
# contains both "每日签到" and "领取". It does NOT cover the sidebar card
# (verified: card at x=54/1306, button at x=273/1605). So: never try to dismiss
# it (ESC cannot, and refusing to run blocks a perfectly good claim) -- instead
# confine the search to the left sidebar, which is <600px wide at any window size.
function Find-Anchor($ls) {
    $best = $null
    foreach ($l in $ls) {
        # Length cap: the ad copy "…登录MiniMaxCode并完成每日签到，即" is a long
        # sentence that happens to CONTAIN the phrase; the real card label is 4 chars.
        if ($l.text.Contains("每日签到") -and $l.text.Length -le 12 -and $l.x -lt 600) {
            if ($null -eq $best -or $l.x -lt $best.x) { $best = $l }
        }
    }
    return $best
}

$anchor = Find-Anchor $lines

# The promo is usually harmless furniture in the right-hand column -- but it also
# ships as a translucent modal: OCR still reads the sidebar through it, yet every
# click is swallowed by the overlay (verified 2026-09-30: three post-click frames
# identical, button text never changed). ESC does not dismiss it, so aim at the
# close glyph near the top-right of the ad panel, then verify the panel is gone
# before trusting any further click.
function Dismiss-AdModal($ls) {
    $minX = 999999; $minY = 999999; $maxX = 0; $maxY = 0
    foreach ($l in $ls) {
        if ($l.text -match "双重福利|福利一|福利二|首发上线|立即体验|国庆") {
            if ($l.x -lt $minX) { $minX = $l.x }
            if ($l.y -lt $minY) { $minY = $l.y }
            if (($l.x + $l.w) -gt $maxX) { $maxX = $l.x + $l.w }
            if (($l.y + $l.h) -gt $maxY) { $maxY = $l.y + $l.h }
        }
    }
    if ($maxX -eq 0) { return $false }
    $cands = @(
        @{ x = $maxX + 28; y = $minY - 8 },
        @{ x = $maxX + 28; y = $minY + 16 },
        @{ x = $maxX - 12; y = $minY - 28 },
        @{ x = $maxX + 56; y = $minY + 24 },
        @{ x = $maxX - 44; y = $minY - 18 }
    )
    foreach ($c in $cands) {
        if ($c.x -ge ($winW - 40) -or $c.y -lt 40) { continue }
        Click-At ([int]$c.x) ([int]$c.y)
        Start-Sleep -Milliseconds 1300
        $after = Get-OcrLinesSafe
        if ($null -eq $after) { continue }
        if (-not (Test-AdPresent $after)) { $script:lines = $after; return $true }
    }
    return $false
}

if ((Test-AdPresent $lines)) {
    $null = Dismiss-AdModal $lines
    $anchor = Find-Anchor $lines
}
if (-not $anchor -and (Test-AdPresent $lines)) {
    # Sometimes the same promo DOES come up as a full-window interstitial that
    # hides the sidebar entirely (seen 00:03 on the same day). ESC is the only
    # safe dismissal we have; if the sidebar comes back we carry on, otherwise
    # we stop instead of clicking blind.
    for ($k = 0; $k -lt 2 -and -not $anchor; $k++) {
        [Cap32]::keybd_event(0x1B, 0, 0, [UIntPtr]::Zero)
        Start-Sleep -Milliseconds 80
        [Cap32]::keybd_event(0x1B, 0, 2, [UIntPtr]::Zero)   # KEYEVENTF_KEYUP
        Start-Sleep -Milliseconds 1500
        $after = Get-OcrLinesSafe
        if ($null -eq $after) { break }
        $lines = $after
        $anchor = Find-Anchor $lines
    }
}
if (-not $anchor) {
    # OCR can simply miss one frame -- re-shoot before concluding anything.
    for ($k = 0; $k -lt 2 -and -not $anchor; $k++) {
        Start-Sleep -Seconds 3
        $again = Get-OcrLinesSafe
        if ($null -eq $again) { break }
        $lines = $again
        $anchor = Find-Anchor $lines
    }
}
if (-not $anchor) {
    # A rendered sidebar with NO check-in card means the card has collapsed --
    # that only happens after today's claim went through (verified 2026-09-30
    # 23:21: sidebar read fine, card gone, account already claimed). Reporting
    # that as "pending" made a perfectly good day look like a failure.
    $sidebar = $false
    foreach ($l in $lines) {
        if ($l.x -lt 600 -and $l.text -match "新建|插件|定时|网站|远程|本地|项目") { $sidebar = $true; break }
    }
    if ($sidebar) {
        Out-Json "already" "签到卡已收起（侧栏正常渲染），判定今日已签"
    }
    Write-AdProbe $lines
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
    # Length cap: ad body "可领取双倍免费积分，新老用户均可参与…" (25+ chars) used
    # to match "领取"; the real button is "签到得@400"-shaped, well under 16.
    if ($l.text.Length -gt 16) { continue }
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
$dumpPath = "$root\logs\minimax_ocr_dump.txt"
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
    # Post-click frames were never recorded, so a "no success toast" result was
    # undebuggable: we could not tell a missed click from a missed marker.
    try {
        $atxt = ($after | ForEach-Object { "{0} | {1},{2} {3}x{4}" -f $_.text, $_.x, $_.y, $_.w, $_.h }) -join "`n"
        [System.IO.File]::AppendAllText(
            "$root\logs\minimax_after_dump.txt",
            "[wait=$wait btnY=$btnY]`n$atxt`n---`n", (New-Object System.Text.UTF8Encoding($false)))
    } catch { }
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
