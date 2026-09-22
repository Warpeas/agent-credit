# AutoClaw OCR check-in: find anchors via screenshot+OCR, click the daily check-in button.
# Requires: AutoClaw foreground (interactive) or elevated runner (scheduled task).
param(
    [switch]$DryRun,
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
    # Claimed (ok/already): kill the client so it does not linger in the background.
    # pending/failed: keep the window open for manual follow-up.
    if ($status -eq "ok" -or $status -eq "already") {
        if (-not $DryRun) {
            taskkill /IM AutoClaw.exe /F 2>$null | Out-Null
            $detail = $detail + "；已关闭客户端"
        }
    }
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

$hwnd = Find-AutoClawWindow
if ($hwnd -eq [IntPtr]::Zero) {
    # Self-heal: background survivors can never regain a window, so clear them
    # and start fresh (silent when already elevated).
    if (Get-Process AutoClaw -ErrorAction SilentlyContinue) {
        taskkill /IM AutoClaw.exe /F 2>$null | Out-Null
        Start-Sleep -Seconds 3
    }
    if (Test-Path $exe) { Start-Process $exe }
    $dl = (Get-Date).AddSeconds(60)
    while ((Get-Date) -lt $dl) {
        Start-Sleep -Seconds 2
        $hwnd = Find-AutoClawWindow
        if ($hwnd -ne [IntPtr]::Zero) { break }
    }
    if ($hwnd -eq [IntPtr]::Zero) { Out-Json "notfound" "AutoClaw 启动后 60s 内未出现主窗口" }
}

# Foreground helpers: OCR is only trustworthy when AutoClaw is really in front.
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

function Click-At([int]$ax, [int]$ay) {
    $sx = $winX + $ax
    $sy = $winY + $ay
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

# Round 1: dismiss ad overlays first, then see what page we are on.
Close-AdOverlays
$lines = Get-OcrLinesSafe
if ($null -eq $lines) { Out-Json "pending" "AutoClaw 未在前台（请点击其窗口后重试）" }
$anchor = Find-CheckinAnchor $lines
if (-not $anchor) {
    # Homepage has no check-in content; navigate via the bottom-left entry first.
    $entry = Find-Line $lines "灵感与活动"
    if (-not $entry) { $entry = Find-Line $lines "我的积分" }
    if (-not $entry) {
        Close-AdOverlays
        $lines = Get-OcrLinesSafe
        if ($null -eq $lines) { Out-Json "pending" "AutoClaw 不在前台，无法确认页面" }
        $entry = Find-Line $lines "灵感与活动"
        if (-not $entry) { $entry = Find-Line $lines "我的积分" }
    }
    if (-not $entry) {
        Out-Json "pending" ("未找到入口（灵感与活动/我的积分），页面文字: " + (($lines | Select-Object -First 6 | ForEach-Object { $_.text }) -join "/"))
    }
    if ($DryRun) {
        Out-Json "dryrun" ("将点击入口: " + $entry.text + " @ " + ($entry.x + [int]($entry.w / 2)) + "," + ($entry.y + [int]($entry.h / 2)))
    }
    Click-At ($entry.x + [int]($entry.w / 2)) ($entry.y + [int]($entry.h / 2))
    Start-Sleep -Seconds 6
    Close-AdOverlays
    $lines = Get-OcrLinesSafe
    if ($null -eq $lines) { Out-Json "pending" "点击后 AutoClaw 不在前台，无法确认页面" }
    $anchor = Find-Line $lines "每日签到"
    if (-not $anchor) {
        $peek = ($lines | Select-Object -First 10 | ForEach-Object { $_.text }) -join "/"
        Out-Json "pending" ("点击入口后仍未找到「每日签到」，当前页面: " + $peek)
    }
}

# On the activity page. Dump full OCR layout for offline tuning before clicking.
$dumpPath = "C:\Users\Hunter\Documents\Warpeas\agent-credit\logs\autoclaw_ocr_dump.txt"
try {
    $stamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    $lines_txt = ($lines | ForEach-Object { "{0} | {1},{2} {3}x{4}" -f $_.text, $_.x, $_.y, $_.w, $_.h }) -join "`n"
    [System.IO.File]::AppendAllText($dumpPath, "[$stamp]`n$lines_txt`n---`n", (New-Object System.Text.UTF8Encoding($false)))
} catch { }

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

Click-At $btnX $btnY

# Multi-frame verification: the success toast may be brief, and a button that
# disappears after the click is itself proof of success.
$okHit = $null
$alreadyHit = $null
$btnGone = $false
foreach ($wait in @(1500, 2500, 3500)) {
    Start-Sleep -Milliseconds $wait
    $after = Get-OcrLinesSafe
    if ($null -eq $after) { continue }
    $anchor2 = Find-CheckinAnchor $after
    if (-not $anchor2) { continue }
    $btnStill = $false
    foreach ($l in $after) {
        if ($l.text -eq "签到" -and [Math]::Abs($l.y - ($anchor2.y + 95)) -lt 60 -and $l.x -lt ($anchor2.x + 400)) { $btnStill = $true; break }
    }
    if (-not $btnStill) { $btnGone = $true }
    foreach ($l in $after) {
        if (($l.text.Contains("签到成功") -or $l.text.Contains("领取成功")) -and [Math]::Abs($l.y - ($anchor2.y + 95)) -lt 200) { $okHit = $l; break }
    }
    if ($okHit) { break }
    foreach ($l in $after) {
        if ($l.text.Contains("已完成") -and [Math]::Abs($l.y - ($anchor2.y + 95)) -lt 60 -and $l.x -lt ($anchor2.x + 400)) { $alreadyHit = $l; break }
    }
    if ($alreadyHit) { break }
}
if ($okHit) { Out-Json "ok" ("签到成功: " + $okHit.text) }
if ($alreadyHit) { Out-Json "already" ("点击后显示: " + $alreadyHit.text) }
if ($btnGone) { Out-Json "ok" "签到按钮已消失，判定签到成功" }
Out-Json "pending" "已点击签到位置，未检测到成功提示"
