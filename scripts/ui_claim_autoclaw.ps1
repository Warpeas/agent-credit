# AutoClaw OCR check-in: find anchors via screenshot+OCR, click the daily check-in button.
# Requires: AutoClaw foreground (interactive) or elevated runner (scheduled task).
param(
    [switch]$DryRun,
    [string]$OutFile = ""
)
$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

# A terminating error used to kill the script without writing any result file,
# which made the runner wait 180s and report a bare timeout. Always surface it.
trap {
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
            [Cap32]::SetForegroundWindow($script:SavedForeground) | Out-Null
        }
    } catch { }
}

function Out-Json([string]$status, [string]$detail) {
    # 运行结束一律恢复现场：
    #   1) 关掉本次由脚本拉起的实例（签到前就开着的必须保留）；
    #   2) 把前台还给运行前的窗口。
    # 失败时也不留窗口：无人值守跑完桌面不该堆着客户端，诊断信息已落日志+台账。
    if (-not $DryRun -and $script:LaunchedByUs) {
        taskkill /IM AutoClaw.exe /F 2>$null | Out-Null
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

$exe = 'C:\Program Files\AutoClaw\AutoClaw.exe'

# OCR 布局落盘：调锚点全靠它。失败路径也要写，否则永远看不到二跳页面长什么样。
$dumpPath = "C:\Users\Hunter\Documents\Warpeas\agent-credit\logs\autoclaw_ocr_dump.txt"
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

$script:LaunchedByUs = $false
$preexistingApp = @(Get-Process AutoClaw -ErrorAction SilentlyContinue)
$hwnd = Find-AutoClawWindow
if ($hwnd -eq [IntPtr]::Zero) {
    # Self-heal: background survivors can never regain a window, so clear them
    # and start fresh -- but ONLY when the client was not already running for the
    # user. Killing an instance the human had open is never acceptable.
    if ($preexistingApp.Count -eq 0) {
        if (Get-Process AutoClaw -ErrorAction SilentlyContinue) {
            taskkill /IM AutoClaw.exe /F 2>$null | Out-Null
            Start-Sleep -Seconds 3
        }
        if (Test-Path $exe) { Start-Process $exe; $script:LaunchedByUs = $true }
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
    $bmp = New-Object System.Drawing.Bitmap($winW, $winH)
    $g = [System.Drawing.Graphics]::FromImage($bmp)
    # PrintWindow first: it captures the window even when it is occluded, not
    # in the foreground, or the session is locked. Fall back to screen capture
    # when PrintWindow yields a blank frame.
    $hdc = $g.GetHdc()
    $pw = [Cap32]::PrintWindow($hwnd, $hdc, 2)
    $g.ReleaseHdc($hdc)
    if (-not $pw -or (Test-Blank $bmp)) {
        $g.CopyFromScreen($winX, $winY, 0, 0, $bmp.Size)
    }
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

function Click-At([int]$ax, [int]$ay) {
    $sx = $winX + $ax
    $sy = $winY + $ay

    # Preferred: hand the click straight to the window's message queue. It does
    # NOT need the window to be in the foreground (Windows refuses the switch
    # while the user is working, which is what broke every run before), and it
    # is unaffected by other windows covering it.
    $pt = [Cap32+POINT]::new()
    $pt.X = $sx
    $pt.Y = $sy
    [Cap32]::ScreenToClient($hwnd, [ref]$pt) | Out-Null
    $lp = [IntPtr]((($pt.Y -band 0xFFFF) * 65536) -bor ($pt.X -band 0xFFFF))
    $res = [IntPtr]::Zero
    $r1 = [Cap32]::SendMessageTimeout($hwnd, 0x0201, [UIntPtr]::new([uint64]1), $lp, 0, 1500, [ref]$res)
    Start-Sleep -Milliseconds 90
    $r2 = [Cap32]::SendMessageTimeout($hwnd, 0x0202, [UIntPtr]::Zero, $lp, 0, 1500, [ref]$res)
    if ($r1 -ne [IntPtr]::Zero -and $r2 -ne [IntPtr]::Zero) { return }

    # Fallback: real cursor input injection, only correct when foregrounded.
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

# Round 1: 先看页面。启动后的广告遮罩会盖住主界面（主人实测：有广告那次点了没跳转，
# 没广告那次才跳过去）。所以先给广告时间冒出来，关掉它，再看页面——
# 一上来就清广告，清完广告才出现，等于白清。
Start-Sleep -Seconds 8
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
    $beforeSig = Get-SigSet $lines
    Click-At ($entry.x + [int]($entry.w / 2)) ($entry.y + [int]($entry.h / 2))

    # 灵感中心的卡片是云端下发的，冷启动后常常要十几秒才渲染出来。
    # 只等一轮 6 秒会在「页面已切换、卡片还没到」时误判成找不到入口。
    $anchor = $null
    $samePageChecked = $false
    foreach ($round in 1..6) {
        Start-Sleep -Seconds 5
        Close-AdOverlays
        $lines = Get-OcrLinesSafe
        if ($null -eq $lines) { continue }
        if (-not $samePageChecked) {
            $samePageChecked = $true
            if (Test-SamePage $beforeSig $lines) {
                Dump-Ocr $lines "pending-点入口后页面无变化"
                Out-Json "pending" ("点击「" + $entry.text + "」后页面无变化：点击未生效。未提权时输入会被 UIPI 丢弃，请用 scripts\run_claim_only.py（ShellExecuteW runas）提权跑")
            }
        }
        # 严格匹配：不能用 Contains，首页「每日签到赚积分」这类引导文案会假阳性命中
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
# 能走到这里说明卡片是「本次点击之后」才变成已完成的——那就是本次签到成功，
# 必须判 ok。「点击前就已签」在上面 doneLine 分支提前返回了 already，
# 两者不能混：判成 already 的话，将来接自动入账（ok 才入账）会静默漏掉一天。
if ($alreadyHit) { Out-Json "ok" ("签到成功（点击后显示: " + $alreadyHit.text + "）") }
if ($btnGone) { Out-Json "ok" "签到按钮已消失，判定签到成功" }
Out-Json "pending" "已点击签到位置，未检测到成功提示"
