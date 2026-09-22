# MiniMax Code daily check-in via screenshot+OCR+click. ASCII code only.
# The check-in card ("每日签到 / 今天 @400") sits on the home sidebar, no navigation needed.
param(
    [string]$OutFile = ""
)
$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

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
  public struct RECT { public int Left, Top, Right, Bottom; }
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

function Out-Json([string]$status, [string]$detail) {
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
}

function Wait-Foreground {
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
    if (-not (Wait-Foreground)) { return $null }
    return Get-OcrLines
}

$rect = New-Object Cap32+RECT
[Cap32]::GetWindowRect($hwnd, [ref]$rect) | Out-Null
$winW = $rect.Right - $rect.Left
$winH = $rect.Bottom - $rect.Top
$winX = $rect.Left
$winY = $rect.Top

function Get-OcrLines {
    $bmp = New-Object System.Drawing.Bitmap($winW, $winH)
    $g = [System.Drawing.Graphics]::FromImage($bmp)
    $g.CopyFromScreen($winX, $winY, 0, 0, $bmp.Size)
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
    [Cap32]::SetCursorPos($sx, $sy) | Out-Null
    Start-Sleep -Milliseconds 120
    [Cap32]::mouse_event(0x0002, 0, 0, 0, [UIntPtr]::Zero)
    [Cap32]::mouse_event(0x0004, 0, 0, 0, [UIntPtr]::Zero)
}

$lines = Get-OcrLinesSafe
if ($null -eq $lines) { Out-Json "pending" "MiniMax Code 未在前台（请点击其窗口后重试）" }

# Anchor: the "每日签到" card on the home sidebar.
$anchor = Find-Line $lines "每日签到"
if (-not $anchor) {
    $peek = ($lines | Select-Object -First 8 | ForEach-Object { $_.text }) -join "/"
    Out-Json "pending" ("未找到「每日签到」卡片，当前页面: " + $peek)
}

# Already-checked markers on/near the card.
foreach ($l in $lines) {
    if (($l.text.Contains("已签") -or $l.text.Contains("已领")) -and [Math]::Abs($l.y - $anchor.y) -lt 120 -and $l.x -lt ($anchor.x + 500)) {
        Out-Json "already" ("今日已签（" + $l.text + "）")
    }
}

# Button: the "今天" cell of the check-in strip (text like 今天@400).
$btn = Find-Line $lines "今天"
if (-not $btn) {
    Out-Json "pending" ("找到签到卡但未见「今天」按钮，锚点 @ " + $anchor.x + "," + $anchor.y)
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
        if (($l.text.Contains("成功") -or $l.text.Contains("已领") -or $l.text.Contains("已签")) -and [Math]::Abs($l.y - $a2.y) -lt 200 -and $l.x -lt ($a2.x + 600)) {
            if ($l.text -notmatch "连续签到得") { $okHit = $l; break }
        }
    }
    if ($okHit) { break }
    foreach ($l in $after) {
        if ($l.text.Contains("已签") -and [Math]::Abs($l.y - $a2.y) -lt 120 -and $l.x -lt ($a2.x + 500)) {
            $alreadyHit = $l; break
        }
    }
    if ($alreadyHit) { break }
}
if ($okHit) { Out-Json "ok" ("签到成功: " + $okHit.text) }
if ($alreadyHit) { Out-Json "already" ("点击后显示: " + $alreadyHit.text) }
Out-Json "pending" "已点击「今天」签到格，未检测到成功提示"
