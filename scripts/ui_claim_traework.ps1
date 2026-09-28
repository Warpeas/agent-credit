# $ProcessName OCR check-in: find anchors via screenshot+OCR, click the daily check-in button.
# Requires: $ProcessName foreground (interactive) or elevated runner (scheduled task).
param(
    [switch]$DryRun,
    [switch]$Explore,
    [string]$OutFile,
    [string]$ProcessName = 'TRAE SOLO CN',
    [string]$ExePath = 'C:\Users\Hunter\AppData\Local\Programs\TRAE SOLO CN\TRAE SOLO CN.exe',
    [string]$ShotDir = '',
    [int]$AvatarX = 0,
    [int]$AvatarY = 0
)
$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

# Surface terminating errors instead of dying silently (the runner then just
# reports a bare timeout with no clue about the real cause).
trap {
    try {
        $m = "FATAL: " + $_.Exception.Message + " @ " + $_.InvocationInfo.PositionMessage
        $p = "$PSScriptRoot\..\logs\traework_claim.json"
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
            [Cap32]::SetForegroundWindow($script:SavedForeground) | Out-Null
        }
    } catch { }
}

function Out-Json([string]$status, [string]$detail) {
    # 运行结束一律恢复现场：关掉本次拉起的实例（签到前就开着的保留），并把前台
    # 还给运行前的窗口。失败时也不留窗口——无人值守跑完桌面不该堆着客户端。
    if (-not $DryRun -and $script:LaunchedByUs) {
        taskkill /IM "TRAE SOLO CN.exe" /F 2>$null | Out-Null
        $detail = $detail + "；已关闭本次启动的客户端"
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

$exe = 'C:\Users\Hunter\AppData\Local\Programs\TRAE SOLO CN\TRAE SOLO CN.exe'

# OCR 布局落盘：调锚点全靠它。失败路径也要写，否则永远看不到二跳页面长什么样。
$dumpPath = "C:\Users\Hunter\Documents\Warpeas\agent-credit\logs\ocr_dump_traework.txt"
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

function Find-TargetWindow {
    # Largest visible top-level window of any $ProcessName process. MainWindowHandle
    # can point at tiny helper popups (update banners etc.), so enumerate.
    $script:BestHwnd = [IntPtr]::Zero
    $script:BestArea = 0
    $pidSet = @{}
    Get-Process -Name $ProcessName -ErrorAction SilentlyContinue | ForEach-Object { $pidSet[[uint32]$_.Id] = $true }
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

$script:LaunchedByUs = $false
$preexistingApp = @(Get-Process -Name $ProcessName -ErrorAction SilentlyContinue)
$hwnd = Find-TargetWindow
if ($hwnd -eq [IntPtr]::Zero) {
    # Self-heal: background survivors can never regain a window, so clear them
    # and start fresh -- but ONLY when the client was not already running for the
    # user. Killing an instance the human had open is never acceptable.
    if ($preexistingApp.Count -eq 0) {
        if (Get-Process -Name $ProcessName -ErrorAction SilentlyContinue) {
            taskkill /IM "TRAE SOLO CN.exe" /F 2>$null | Out-Null
            Start-Sleep -Seconds 3
        }
        if (Test-Path $exe) { Start-Process $exe; $script:LaunchedByUs = $true }
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
    # Foreground is best-effort now: PrintWindow captures the window even when
    # something else is on top, so a refused foreground switch must not abort.
    try { Ensure-Foreground | Out-Null } catch { }
    return Get-OcrLines
}

$rect = New-Object Cap32+RECT
[Cap32]::GetWindowRect($hwnd, [ref]$rect) | Out-Null
$winW = $rect.Right - $rect.Left
$winH = $rect.Bottom - $rect.Top
$winX = $rect.Left
$winY = $rect.Top

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
    $bmp = New-Object System.Drawing.Bitmap($winW, $winH)
    $g = [System.Drawing.Graphics]::FromImage($bmp)
    # PrintWindow: works without the window being in the foreground / visible.
    # Fall back to screen capture when it yields a blank frame.
    $hdc = $g.GetHdc()
    $pw = [Cap32]::PrintWindow($hwnd, $hdc, 2)
    $g.ReleaseHdc($hdc)
    if (-not $pw -or (Test-Blank $bmp)) {
        $g.CopyFromScreen($winX, $winY, 0, 0, $bmp.Size)
    }
    $g.Dispose()
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

# The real claim button is dark-on-dark ("签到" in white on a black pill), which
# OCR misses entirely - so its position cannot be read from text. Scan the row
# to the right of the entry label for a dark horizontal run instead.
function Find-DarkButton([int]$rowY, [int]$x0, [int]$x1) {
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
        # 多行扫描：按钮可能比说明文字略高或略低；只有 hover 之后它才渲染出来
        $best = $null
        $log = New-Object System.Collections.ArrayList
        for ($yy = ($rowY - 30); $yy -le ($rowY + 90); $yy += 6) {
            if ($yy -lt 0 -or $yy -ge $winH) { continue }
            $runStart = -1
            for ($x = $x0; $x -lt $x1; $x++) {
                $c = $bmp.GetPixel($x, $yy)
                $dark = ($c.R -lt 90 -and $c.G -lt 90 -and $c.B -lt 90)
                if ($dark -and $runStart -lt 0) { $runStart = $x }
                if (-not $dark -and $runStart -ge 0) {
                    $len = $x - $runStart
                    if ($len -ge 30 -and (-not $best -or $len -gt $best.len)) { $best = @{ x = [int]($runStart + ($len / 2)); y = $yy; len = $len } }
                    $runStart = -1
                }
            }
            if ($runStart -ge 0) {
                $len = $x1 - $runStart
                if ($len -ge 30 -and (-not $best -or $len -gt $best.len)) { $best = @{ x = [int]($runStart + ($len / 2)); y = $yy; len = $len } }
            }
            if ([Math]::Abs($yy - $rowY) -lt 7) {
                $samples = New-Object System.Collections.ArrayList
                for ($sx2 = $x0; $sx2 -lt $x1; $sx2 += 6) {
                    $cc = $bmp.GetPixel($sx2, $yy)
                    [void]$samples.Add("$sx2`:$($cc.R),$($cc.G),$($cc.B)")
                }
                [void]$log.Add("row=$yy " + ($samples -join ' '))
            }
        }
        try {
            $lns = "$(Get-Date -Format HH:mm:ss) x0=$x0 x1=$x1 src=" + $(if ($script:ShotBmp) { 'ocr-frame' } else { 'fresh' }) + " " + ($log -join ' | ') + " best=" + $(if ($best) { "$($best.x),$($best.y) len=$($best.len)" } else { 'none' }) + "`n"
            [System.IO.File]::AppendAllText("$PSScriptRoot\..\logs\_scan.txt", $lns)
        } catch { }
        if (-not $script:ShotBmp) { $bmp.Dispose() }
        if ($best) { return $best }
    } catch { }
    return $null
}

function Click-At([int]$ax, [int]$ay) {
    $sx = $winX + $ax
    $sy = $winY + $ay

    # 1) If we already own the foreground, use REAL input injection. Synthetic
    #    messages opened the account menu but never triggered the dark button;
    #    real input is what the app actually reacts to.
    if ([Cap32]::GetForegroundWindow() -eq $hwnd) {
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

    # Resolve the deepest child window under the point: with Electron/CEF the
    # top-level window only forwards input, the renderer child is what really
    # handles a click. Sending to the top-level window alone does nothing.
    # Prefer the real top-most window at that point: Electron popup menus may be
    # a separate window rather than a child of the main one, and sending to the
    # main window then does nothing. Verify it belongs to the same process.
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
    Start-Sleep -Milliseconds 200
    $r1 = [Cap32]::SendMessageTimeout($target, 0x0201, [UIntPtr]::new([uint64]1), $lp, 0, 1500, [ref]$res)
    Start-Sleep -Milliseconds 90
    $r2 = [Cap32]::SendMessageTimeout($target, 0x0202, [UIntPtr]::Zero, $lp, 0, 1500, [ref]$res)
    $mode = 'msg-fail'
    if ($r1 -ne [IntPtr]::Zero -and $r2 -ne [IntPtr]::Zero) { $mode = 'msg-ok' }
    try {
        $line = "$(Get-Date -Format HH:mm:ss) mode=$mode target=$target ax=$ax ay=$ay win=" + $winW + "x" + $winH + "`n"
        [System.IO.File]::AppendAllText("$PSScriptRoot\..\logs\_clickmode.txt", $line)
    } catch { }
    if ($mode -eq 'msg-ok') { return }

    [Cap32]::SetCursorPos($sx, $sy) | Out-Null
    Start-Sleep -Milliseconds 120
    [Cap32]::mouse_event(0x0002, 0, 0, 0, [UIntPtr]::Zero)
    [Cap32]::mouse_event(0x0004, 0, 0, 0, [UIntPtr]::Zero)
}

# Dismiss possible ad/popup overlays: ESC, then click visible close labels.
function Close-AdOverlays {
    try {
        Add-Type -AssemblyName System.Windows.Forms
        [System.Windows.Forms.SendKeys]::SendWait("{ESC}")
        Start-Sleep -Milliseconds 800
    } catch { }
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
        $g.CopyFromScreen($rect.Left, $rect.Top, 0, 0, $bmp.Size)
        $g.Dispose()
        $bmp.Save((Join-Path $ShotDir ($tag + ".png")), [System.Drawing.Imaging.ImageFormat]::Png)
        $bmp.Dispose()
    } catch { }
}

$clickWords  = @("每日领", "签到", "Check in", "Check-in", "Checkin")
$claimWords  = @("已签到", "已领", "今日已签", "Checked in", "Checked-in")

function Find-AnyLine($lines, [string[]]$needles) {
    foreach ($n in $needles) {
        $h = Find-Line $lines $n
        if ($h) { return $h }
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
    foreach ($n in $needles) {
        $h = Find-WordHit $lines $n
        if (-not $h) { continue }
        if ($h.x -ge $xMax) { continue }
        if ($h.text -match "多领|升级|会员|已") { continue }
        # 侧栏任务列表里的历史任务名（实测「配置Trae每日自动签到」@664,162、
        # 「查询签到入口与积分规则」@101,1100）同样含「签到」且落在 x<30%，
        # 会在首页就被误判成入口 -> 脚本跳过「点头像开菜单」直接点错地方。
        # 「每日领」是菜单独有的强特征，永远优先采信；其余 needle 只有在账户
        # 菜单确实展开时才认。
        if ($n -ne "每日领" -and -not $menuOpen) { continue }
        return $h
    }
    return $null
}

# 窗口查找与冷启动尝试在骨架（head）里已经做过一次：找不到会直接 notfound 退出。
# 这里只做兜底，避免重复启动客户端。
if (-not $hwnd -or $hwnd -eq [IntPtr]::Zero) {
    Out-Json "pending" ("找不到 " + $ProcessName + " 窗口，请手动打开客户端后重跑")
}

$rect = New-Object Cap32+RECT
[Cap32]::GetWindowRect($hwnd, [ref]$rect) | Out-Null
$winW = $rect.Right - $rect.Left
$winH = $rect.Bottom - $rect.Top
try { Ensure-Foreground | Out-Null } catch { }

# 启动后的广告/弹窗会盖住主界面：等它出现再关，别一上来就清
Start-Sleep -Seconds 8
Close-AdOverlays
Start-Sleep -Seconds 2

$lines = Get-OcrLines
Dump-Ocr $lines "trae-home"
Save-Shot "01-home"

# 1) 首页就看得见签到入口？
$entry = Find-EntryWord $lines $clickWords
$claimed = Find-AnyLine $lines $claimWords

# 2) 看不见就点左下角头像开菜单
if (-not $entry -and -not $claimed) {
    # 左下角用户名是稳定锚点（实测「用户71294228173」@109,1732，右边跟「免费」标签）。
    # 直接点用户名文字本身——猜头像图标坐标会时灵时不灵（实测点偏就打不开菜单），
    # 而用户名是一条明确的文本，账户菜单的触发区也覆盖它。
    $userHit = $null
    foreach ($l in $lines) {
        if (-not $l.words) { continue }
        foreach ($w in $l.words) {
            if ($w.text.StartsWith("用户") -and (-not $userHit -or $w.y -gt $userHit.y)) {
                $userHit = $w
            }
        }
    }
    if (-not $userHit) {
        # 退而求其次：会员标签「免费」也在同一账户条上
        foreach ($l in $lines) {
            if (-not $l.words) { continue }
            foreach ($w in $l.words) {
                if ($w.text -eq "免费" -and (-not $userHit -or $w.y -gt $userHit.y)) {
                    $userHit = $w
                }
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
    foreach ($cand in $candidates) {
        Click-At $cand.x $cand.y
        foreach ($sub in 1..2) {
            Start-Sleep -Seconds 2
            $lines = Get-OcrLines
            Dump-Ocr $lines ("trae-menu-" + $ci + "-" + $sub)
            if ($sub -eq 1) { Save-Shot ("02-menu-" + $ci) }
            $entry = Find-EntryWord $lines $clickWords
            $claimed = Find-AnyLine $lines $claimWords
            if ($entry -or $claimed) { break }
        }
        if ($entry -or $claimed) { break }
        # ESC 收掉可能的菜单/浮层，再试下一个候选点
        [Cap32]::keybd_event(0x1B, 0, 0, [UIntPtr]::Zero) | Out-Null
        [Cap32]::keybd_event(0x1B, 0, 2, [UIntPtr]::Zero) | Out-Null
        Start-Sleep -Milliseconds 600
        $ci++
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
    if ($Explore) { Out-Json "explore" $msg }
    Out-Json "pending" $msg
}

# 探索模式到此为止：菜单词级布局已进 dump 与截图，签到按钮绝不碰
if ($Explore) {
    Out-Json "explore" ("菜单已抓取，入口候选: " + $entry.text + " @ " + ($entry.x + [int]($entry.w / 2)) + "," + ($entry.y + [int]($entry.h / 2)))
}

if ($claimed) {
    Out-Json "already" ("今日已签到（" + $claimed.text + "），无需重复点击")
}

$bx = $entry.x
$by = $entry.y + [int]($entry.h / 2)
if ($DryRun) {
    Out-Json "dryrun" ("将点击签到入口: " + $entry.text + " @ " + $bx + "," + $by)
}

# 「每日领150积分」只是说明文字，真正的签到按钮是它右侧的黑色「签到」。
# 按钮相对文字行的偏移随窗口宽度略有变化，按 380 → 300 → 450 → 文字本身 轮换试。
# 按钮相对文字行的偏移：窗口越窄菜单越窄，写死 380 会点到菜单外。
# 用菜单项的右边界推算——黑色「签到」按钮右对齐在菜单内侧约 60px 处。
$offsets = @(380, 300, 450, 0)
$menuRight = 0
foreach ($l in $lines) {
    if (-not $l.text) { continue }
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

# 黑底白字的「签到」按钮 OCR 整行漏检，靠像素扫描在入口行右侧找深色块，
# 命中后以它为主点击点（比按偏移猜可靠得多）。
$x1 = [int]($winW * 0.3)
if ($menuRight -gt 0) { $x1 = [int]($menuRight + 80) }
# 黑色「签到」按钮是 hover 才渲染的元素：实测没有 hover 时入口行右侧
# x=263~431 全是 250,250,250 纯白，OCR 与像素扫描都看不到它。
# 先把真实光标移到入口行触发 hover，等它渲染，再刷新一帧去扫描。
[Cap32]::SetCursorPos(($winX + [int]$bx + 60), ($winY + $by)) | Out-Null
Start-Sleep -Milliseconds 800
$null = Get-OcrLines
$btn = Find-DarkButton $by ([int]([int]$bx + 40)) $x1
if ($btn) {
    $d0 = [int]($btn.x - [int]$bx)
    $dm = $d0 - 40
    $dp = $d0 + 40
    $offsets = @($d0, $dm, $dp, 0)
    $by = $btn.y
    try {
        $ln = "$(Get-Date -Format HH:mm:ss) darkBtn x=$($btn.x) y=$($btn.y) len=$($btn.len) entryX=$bx offsets=" + ($offsets -join ',') + "`n"
        [System.IO.File]::AppendAllText("$PSScriptRoot\..\logs\_clickmode.txt", $ln)
    } catch { }
}
for ($i = 0; $i -lt $offsets.Count; $i++) {
    Click-At ($bx + $offsets[$i]) $by
    foreach ($sub in 1..2) {
        Start-Sleep -Seconds 3
        $lines = Get-OcrLines
        Dump-Ocr $lines ("trae-after-click-" + $i + "-" + $sub)
        if ($sub -eq 1) { Save-Shot ("03-after-" + $i) }
        $c = Find-AnyLine $lines $claimWords
        if ($c) {
            Out-Json "ok" ("签到成功（点击后显示: " + $c.text + "）")
        }
    }
}
$peek2 = ($lines | Select-Object -First 10 | ForEach-Object { $_.text }) -join "/"
Out-Json "pending" ("点击各候选位置后均未出现已签状态，页面: " + $peek2)
