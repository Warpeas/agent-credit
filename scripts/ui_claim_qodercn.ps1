# Qoder CN 每日签到活动 OCR 领取脚本。
# 活动是服务端下发进 webview 的「专属活动权益 / 每天领 100 Credits」弹窗，
# UIA 看不见（主窗口只有 ~13 个 UIA 元素、无领取相关 Name），只能截图 + OCR + OS 级点击。
# 与 ui_claim_trae.ps1 同路：非提权（Qoder 是普通中完整性安装，同完整性即可点击）。
#
# 三条实测踩过的坑，都写进来了：
#   1) DPI：本机 200% 缩放。进程不 SetProcessDpiAwareness(2)，GetWindowRect 给逻辑像素、
#      CopyFromScreen/SetCursorPos 用物理像素，坐标差 2 倍会点到别的窗口。
#   2) 抓图用 PrintWindow(PW_RENDERFULLCONTENT=2) 而非 CopyFromScreen：桌面常有别的窗口
#      （如另一个 agent 会话）叠在 Qoder 上面，CopyFromScreen 会把那层拍进来，PrintWindow
#      只渲染目标窗口自身内容，干净。
#   3) 点击前先抢前台并核对 GetForegroundWindow 确实是本窗口，否则宁可 pending 也不点，
#      免得把点击送进重叠的其它 App。
param(
    [switch]$DryRun,
    [switch]$Explore,
    [string]$OutFile,
    [string]$ProcessName = 'Qoder CN',
    [string]$ExePath = '',
    # 用量仪表图标：底栏左锚定，实测在窗口内 x≈412、距底≈52（物理像素，2664x1612 窗口）
    [int]$GaugeX = 412,
    [int]$GaugeFromBottom = 52,
    # 礼盒图标在「我的用量」小窗里、位于「查看详情」按钮左侧
    [int]$GiftLeftOfDetails = 150,
    [int]$GiftVertOffset = 0
)
$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$root = Split-Path -Parent $PSScriptRoot
$logPath = "$root\logs\ps1_qodercn.log"
$shotPath = "$root\logs\_qoder_shot.png"
function Log($m){ $s=(Get-Date -Format "HH:mm:ss")+" "+$m; try{[System.IO.File]::AppendAllText($logPath,$s+"`n",(New-Object System.Text.UTF8Encoding($false)))}catch{}; Write-Output $s }

trap {
    try {
        $m = "FATAL: " + $_.Exception.Message + " @ " + $_.InvocationInfo.PositionMessage
        Log $m
        if ($OutFile) { [System.IO.File]::WriteAllText($OutFile, (ConvertTo-Json -Compress @{ status='failed'; detail=$m })) }
    } catch {}
    break
}

Add-Type -AssemblyName System.Drawing
Add-Type -AssemblyName System.Runtime.WindowsRuntime
$sig = @"
using System;
using System.Runtime.InteropServices;
public static class Cap {
  [StructLayout(LayoutKind.Sequential)] public struct R { public int L,T,Rr,B; }
  [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr h);
  [DllImport("user32.dll")] public static extern bool ShowWindow(IntPtr h, int c);
  [DllImport("user32.dll")] public static extern bool GetWindowRect(IntPtr h, out R r);
  [DllImport("user32.dll")] public static extern IntPtr GetForegroundWindow();
  [DllImport("user32.dll")] public static extern bool SetCursorPos(int x, int y);
  [DllImport("user32.dll")] public static extern void mouse_event(uint f, uint dx, uint dy, uint d, UIntPtr e);
  [DllImport("user32.dll")] public static extern bool PrintWindow(IntPtr h, IntPtr hdc, uint flags);
  [DllImport("user32.dll")] public static extern uint GetWindowThreadProcessId(IntPtr h, out uint pid);
  [DllImport("shcore.dll")] public static extern int SetProcessDpiAwareness(int a);
}
"@
Add-Type $sig
try { [void][Cap]::SetProcessDpiAwareness(2) } catch {}   # per-monitor v2：全程物理像素

# ---- WinRT OCR 引擎初始化（同 scripts/ocr_image.py 的可用写法）----
$null = [Windows.Media.Ocr.OcrEngine, Windows.Foundation, ContentType = WindowsRuntime]
$null = [Windows.Globalization.Language, Windows.Foundation, ContentType = WindowsRuntime]
$null = [Windows.Graphics.Imaging.SoftwareBitmap, Windows.Foundation, ContentType = WindowsRuntime]
$null = [Windows.Storage.Streams.InMemoryRandomAccessStream, Windows.Foundation, ContentType = WindowsRuntime]
$asTask = ([System.WindowsRuntimeSystemExtensions].GetMethods() | Where-Object {
  $_.Name -eq 'AsTask' -and $_.GetParameters().Count -eq 1 -and
  $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncOperation`1' })[0]
function Await($op, $t){ $m=$asTask.MakeGenericMethod($t); $x=$m.Invoke($null,@($op)); $x.Wait(-1)|Out-Null; return $x.Result }
$engine = [Windows.Media.Ocr.OcrEngine]::TryCreateFromLanguage((New-Object Windows.Globalization.Language "zh-Hans-CN"))
if (-not $engine) { $engine = [Windows.Media.Ocr.OcrEngine]::TryCreateFromUserProfileLanguages() }
if (-not $engine) { Log "no OCR engine"; }

# ---- 目标窗口：进程内 class=Chrome_WidgetWin_1、可见、有标题、面积最大 ----
function Find-TargetWindow {
    $pids = @(Get-Process | Where-Object { $_.ProcessName -like "*$ProcessName*" } | ForEach-Object { $_.Id })
    $best = $null
    foreach ($p in Get-Process) {
        if ($p.MainWindowHandle -eq [IntPtr]::Zero) { continue }
        if ($pids -notcontains $p.Id) { continue }
        $h = $p.MainWindowHandle
        $r = New-Object Cap+R
        [void][Cap]::GetWindowRect($h, [ref]$r)
        $area = ($r.Rr-$r.L)*($r.B-$r.T)
        if ($area -le 0) { continue }
        if (-not $best -or $area -gt $best.Area) { $best = @{ Hwnd=$h; Area=$area; R=$r } }
    }
    return $best
}

$script:WinX=0; $script:WinY=0; $script:WinW=0; $script:WinH=0
function Reset-Rect($hwnd){
    $r = New-Object Cap+R
    [void][Cap]::GetWindowRect($hwnd, [ref]$r)
    $script:WinX=$r.L; $script:WinY=$r.T; $script:WinW=$r.Rr-$r.L; $script:WinH=$r.B-$r.T
}

# PrintWindow 抓目标窗口自身内容 -> 存 PNG -> WinRT OCR -> 返回词级坐标（图像坐标）
function Get-OcrWords($hwnd){
    Reset-Rect $hwnd
    if ($script:WinW -le 0 -or $script:WinH -le 0) { return @() }
    $bmp = New-Object System.Drawing.Bitmap($script:WinW, $script:WinH)
    $g = [System.Drawing.Graphics]::FromImage($bmp)
    $hdc = $g.GetHdc()
    [void][Cap]::PrintWindow($hwnd, $hdc, 2)   # 2 = PW_RENDERFULLCONTENT
    $g.Dispose()
    try { $bmp.Save($shotPath, [System.Drawing.Imaging.ImageFormat]::Png) } catch {}
    $words = @()
    try {
        $ms = New-Object System.IO.MemoryStream
        $bmp.Save($ms, [System.Drawing.Imaging.ImageFormat]::Png)
        $bytes = $ms.ToArray(); $ms.Dispose()
        $stream = New-Object Windows.Storage.Streams.InMemoryRandomAccessStream
        $dw = New-Object Windows.Storage.Streams.DataWriter($stream.GetOutputStreamAt(0))
        $dw.WriteBytes($bytes)
        Await ($dw.StoreAsync()) ([uint32]) | Out-Null
        Await ($dw.FlushAsync()) ([bool]) | Out-Null
        $dec = Await ([Windows.Graphics.Imaging.BitmapDecoder]::CreateAsync($stream)) ([Windows.Graphics.Imaging.BitmapDecoder])
        $sbmp = Await ($dec.GetSoftwareBitmapAsync()) ([Windows.Graphics.Imaging.SoftwareBitmap])
        $res = Await ($engine.RecognizeAsync($sbmp)) ([Windows.Media.Ocr.OcrResult])
        foreach ($ln in $res.Lines) {
            foreach ($wd in $ln.Words) {
                $t = ($wd.Text -replace "\s","")
                if ([string]::IsNullOrWhiteSpace($t)) { continue }
                $br = $wd.BoundingRect
                $words += @{ text=$t; cx=[int]($br.X + $br.Width/2); cy=[int]($br.Y + $br.Height/2); x=[int]$br.X; y=[int]$br.Y }
            }
        }
    } catch { Log ("OCR err: " + $_.Exception.Message) }
    $bmp.Dispose()
    return $words
}

function Join-Text($words){ return (($words | ForEach-Object { $_.text }) -join " ") }
function Find-Word($words, [string]$exact){
    foreach ($w in $words) { if ($w.text -eq $exact) { return $w } }
    return $null
}
function Test-Contains([string]$hay, [string[]]$needles){
    foreach ($n in $needles) { if ($hay -like "*$n*") { return $true } }
    return $false
}

# 抢前台并核对前台确属本窗口；不是则拒绝点击（安全闸门）
function Ensure-Foreground($hwnd){
    [void][Cap]::ShowWindow($hwnd, 9)
    Start-Sleep -Milliseconds 250
    [void][Cap]::SetForegroundWindow($hwnd)
    Start-Sleep -Milliseconds 350
    if ([Cap]::GetForegroundWindow() -ne $hwnd) {
        # AttachThreadInput 技巧再试一次
        [void][Cap]::SetForegroundWindow($hwnd)
        Start-Sleep -Milliseconds 350
    }
    return ([Cap]::GetForegroundWindow() -eq $hwnd)
}

function Click-Img($hwnd, [int]$ix, [int]$iy){
    Reset-Rect $hwnd
    $sx = $script:WinX + $ix
    $sy = $script:WinY + $iy
    [void][Cap]::SetCursorPos($sx, $sy)
    Start-Sleep -Milliseconds 120
    [Cap]::mouse_event(0x0002,0,0,0,[UIntPtr]::Zero)
    [Cap]::mouse_event(0x0004,0,0,0,[UIntPtr]::Zero)
    Log ("click img($ix,$iy) -> screen($sx,$sy)")
}

function Out-Json([string]$status, [string]$detail){
    Log ("RESULT " + $status + ": " + $detail)
    if ($OutFile) {
        try { [System.IO.File]::WriteAllText($OutFile, (ConvertTo-Json -Compress @{ status=$status; detail=$detail }), (New-Object System.Text.UTF8Encoding($false))) } catch {}
    }
    if ($status -eq 'ok' -or $status -eq 'already') { exit 0 }
    exit 2
}

# 领取按钮：webview 里独立成词的「领取」（「领取后」是一个词、不会误命中；「查看详情」「立即查收」也不含独立「领取」）
function Find-ClaimWord($words){ return (Find-Word $words '领取') }
function Get-Granted($text){
    if ($text -match '每天领\D{0,3}(\d+)') { return [int]$matches[1] }
    if ($text -match '\+\s*(\d+)\s*Credit') { return [int]$matches[1] }
    return 0
}

$t = Find-TargetWindow
if (-not $t) { Out-Json "notfound" "未找到 Qoder CN 主窗口（客户端可能没开）" }
$hwnd = $t.Hwnd
Reset-Rect $hwnd
Log ("window hwnd=$hwnd rect=$($script:WinX),$($script:WinY) $($script:WinW)x$($script:WinH)")

$words = Get-OcrWords $hwnd
$text = Join-Text $words

if ($Explore) {
    Log ("--- OCR words (" + $words.Count + ") ---")
    foreach ($w in $words) { Log ("  [" + $w.text + "] @ " + $w.cx + "," + $w.cy) }
    Out-Json "explore" ("OCR 行数=" + $words.Count + "，截图: " + $shotPath)
}

# 幂等：已领过 -> 没有独立「领取」词，但有已领文案
$claim = Find-ClaimWord $words
if (-not $claim) {
    if (Test-Contains $text @('已领取','已到账','今日已领','已签到','明天再来','已领取奖励')) {
        Out-Json "already" "检测到已领取文案，无需重复领取"
    }
}

# 弹窗是否已显示（启动时会自动弹）
$modalOpen = (Test-Contains $text @('专属活动','立即查收','每天领')) -or ($claim -and (Test-Contains $text @('Credits','权益')))

if (-not $modalOpen) {
    # 走「用量仪表 -> 礼盒」把弹窗点开
    if (-not (Ensure-Foreground $hwnd)) { Out-Json "pending" "无法确认 Qoder 处于前台（桌面有重叠窗口），为安全起见不点击；请手动点开签到弹窗或关闭遮挡窗口后重试" }
    Log "弹窗未显示，尝试点用量仪表图标"
    Click-Img $hwnd $GaugeX ($script:WinH - $GaugeFromBottom)
    Start-Sleep -Milliseconds 900
    $words = Get-OcrWords $hwnd; $text = Join-Text $words
    $details = Find-Word $words '查看详情'
    if ($details) {
        # 礼盒在「查看详情」左侧同一行
        $gx = $details.x - $GiftLeftOfDetails
        $gy = $details.cy + $GiftVertOffset
        Log "找到用量小窗，点礼盒图标（相对查看详情左移 $GiftLeftOfDetails）"
        Click-Img $hwnd $gx $gy
        Start-Sleep -Milliseconds 1200
        $words = Get-OcrWords $hwnd; $text = Join-Text $words
        $claim = Find-ClaimWord $words
    } else {
        Log "用量小窗里没找到「查看详情」锚点，礼盒位置无法推算"
    }
}

if (-not $claim) {
    Out-Json "pending" "未定位到「领取」按钮（可能今日无活动、弹窗未开或文案改版）。可手动在 Qoder 里点「用量→礼盒→领取」，再 credit record qodercn claimed 100"
}

Log ("定位到领取按钮 @ img(" + $claim.cx + "," + $claim.cy + ")，额度=" + (Get-Granted $text))

if ($DryRun) { Out-Json "dryrun" ("已定位「领取」@ (" + $claim.cx + "," + $claim.cy + ")，未点击") }

if (-not (Ensure-Foreground $hwnd)) { Out-Json "pending" "点击前无法确认前台，已放弃点击（避免误点重叠窗口）" }
Click-Img $hwnd $claim.cx $claim.cy
Start-Sleep -Milliseconds 2200

# 复核：领取按钮消失 / 出现成功文案 / 出现已领文案
$words2 = Get-OcrWords $hwnd
$text2 = Join-Text $words2
$stillThere = Find-ClaimWord $words2
$granted = Get-Granted $text
if ((Test-Contains $text2 @('已领取','已到账','领取成功','成功','今日已领')) -or (-not $stillThere)) {
    $msg = "领取成功"
    if ($granted -gt 0) { $msg += " [granted] $granted" }
    Out-Json "ok" $msg
}
Out-Json "pending" "点击了「领取」但复核未见成功信号（可能需二次确认或文案改版），请手动确认"
