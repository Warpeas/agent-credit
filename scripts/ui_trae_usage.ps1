# 打开 Trae「设置 → 用量管理」页，滚到指定位置，PrintWindow 抓整窗 PNG。
#
# 为什么这么走：每笔积分包的额度/剩余/到期日没有对外 getter，只在这一页渲染
# （2026-11-10 调研：icubeGetCreditsUsageInfo 只给聚合值）。本脚本只做两件事：
#   1. 让客户端自己打开那一页（扩展命令 agentCredit.openUsagePage）
#   2. PrintWindow 抓图（与 ui_claim_trae.ps1 同一手法：不要求窗口在最前、
#      被遮挡也能拿到内容，避免抢焦点失败时抓到别的 App）
# 不做任何点击、不碰凭据。
#
# 用法：
#   powershell -ExecutionPolicy Bypass -File scripts\ui_trae_usage.ps1 -OutPng logs\_a.png -ScrollDown 0
#   powershell -ExecutionPolicy Bypass -File scripts\ui_trae_usage.ps1 -SkipOpen -Hwnd 2756018 -ScrollDown 9
#
# 前提：扩展 agent-credit.trae-credit-dump 已安装且贡献了 ctrl+alt+u。
param(
    [string]$OutPng = "",
    [int]$ScrollDown = 0,        # 先滚到顶，再向下滚动这么多格（1 格≈100px）
    [switch]$SkipOpen,           # 页面已开着时只滚动+抓图
    [switch]$SendOpen,           # 配合 -SkipOpen：不新建窗口，只对目标窗口发 ctrl+alt+u
    [switch]$NoClose,
    [string]$Hwnd = "",
    [string]$Click = "",         # 窗口相对坐标 "x,y"，用于点开默认折叠的分组（如 每日签到）
    [int]$WaitSec = 8,
    [string]$ProcessName = "Trae CN"
)

$root = Split-Path -Parent $PSScriptRoot
$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

Add-Type -AssemblyName System.Drawing
Add-Type -AssemblyName System.Windows.Forms

Add-Type @"
using System;
using System.Runtime.InteropServices;
using System.Text;
public static class U32 {
  [DllImport("user32.dll")] public static extern bool SetProcessDPIAware();
  [DllImport("user32.dll")] public static extern bool EnumWindows(EnumProc cb, IntPtr p);
  [DllImport("user32.dll")] public static extern bool IsWindowVisible(IntPtr h);
  [DllImport("user32.dll")] public static extern bool IsIconic(IntPtr h);
  [DllImport("user32.dll")] public static extern int GetWindowTextW(IntPtr h, StringBuilder s, int n);
  [DllImport("user32.dll")] public static extern uint GetWindowThreadProcessId(IntPtr h, out uint pid);
  [DllImport("user32.dll")] public static extern bool GetWindowRect(IntPtr h, out RECT r);
  [DllImport("user32.dll")] public static extern IntPtr GetForegroundWindow();
  [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr h);
  [DllImport("user32.dll")] public static extern bool ShowWindow(IntPtr h, int c);
  [DllImport("user32.dll")] public static extern void keybd_event(byte vk, byte scan, uint flags, UIntPtr extra);
  [DllImport("user32.dll")] public static extern IntPtr SendMessage(IntPtr h, uint msg, IntPtr w, IntPtr l);
  [DllImport("user32.dll")] public static extern bool PrintWindow(IntPtr h, IntPtr hdc, uint flags);
  [DllImport("user32.dll")] public static extern bool SetCursorPos(int x, int y);
  [DllImport("user32.dll")] public static extern void mouse_event(uint flags, uint dx, uint dy, uint data, UIntPtr extra);
  public delegate bool EnumProc(IntPtr h, IntPtr p);
  public struct RECT { public int Left, Top, Right, Bottom; }
}
"@

[U32]::SetProcessDPIAware() | Out-Null

function Get-TraeWindows {
    $script:traePids = @(Get-Process -Name $ProcessName -ErrorAction SilentlyContinue | Select-Object -ExpandProperty Id)
    $script:winList = New-Object System.Collections.ArrayList
    $cb = [U32+EnumProc] {
        param($h, $p)
        if (-not [U32]::IsWindowVisible($h)) { return $true }
        $sb = New-Object System.Text.StringBuilder 512
        [void][U32]::GetWindowTextW($h, $sb, 512)
        $title = $sb.ToString()
        if ([string]::IsNullOrWhiteSpace($title)) { return $true }
        $pid2 = 0
        [void][U32]::GetWindowThreadProcessId($h, [ref]$pid2)
        if ($script:traePids -contains $pid2) {
            $r = New-Object U32+RECT
            [void][U32]::GetWindowRect($h, [ref]$r)
            [void]$script:winList.Add([pscustomobject]@{
                    Hwnd = $h
                    Tit  = $title
                    Pid  = $pid2
                    Rect = $r
                    W    = ($r.Right - $r.Left)
                    H    = ($r.Bottom - $r.Top)
                    Icon = [U32]::IsIconic($h)
                })
        }
        return $true
    }
    [void][U32]::EnumWindows($cb, [IntPtr]::Zero)
    return $script:winList
}

# 只对最小化窗口做 SW_RESTORE：对最大化窗口调 9 号会还原成普通尺寸，
# 两次调用之间窗口忽大忽小，坐标全变（2026-11-10 踩过）。
function Set-Foreground($hWnd) {
    if ([U32]::GetForegroundWindow() -eq $hWnd) { return $true }
    if ([U32]::IsIconic($hWnd)) {
        [U32]::ShowWindow($hWnd, 9) | Out-Null
        Start-Sleep -Milliseconds 500
        if ([U32]::GetForegroundWindow() -eq $hWnd) { return $true }
    }
    [U32]::keybd_event(0x12, 0, 0, [UIntPtr]::Zero) | Out-Null
    [U32]::SetForegroundWindow($hWnd) | Out-Null
    [U32]::keybd_event(0x12, 0, 0x0002, [UIntPtr]::Zero) | Out-Null
    Start-Sleep -Milliseconds 500
    if ([U32]::GetForegroundWindow() -eq $hWnd) { return $true }
    [U32]::ShowWindow($hWnd, 5) | Out-Null
    Start-Sleep -Milliseconds 300
    return ([U32]::GetForegroundWindow() -eq $hWnd)
}

function Send-Chord([string]$keys, [int]$holdMs = 60) {
    [System.Windows.Forms.SendKeys]::SendWait($keys)
    Start-Sleep -Milliseconds $holdMs
}

$wins = Get-TraeWindows
if ($wins.Count -eq 0) { Write-Output "NO WINDOW for $ProcessName"; exit 1 }

if (-not $SkipOpen) {
    $agent = $wins | Where-Object { $_.Tit -match 'Agent|TRAE' } | Select-Object -First 1
    if (-not $agent) { $agent = $wins | Select-Object -First 1 }
    if (-not (Set-Foreground $agent.Hwnd)) { Write-Output "WARN: agent window not foreground" }

    $before = @($wins | ForEach-Object { $_.Hwnd })
    $t0 = Get-Date
    Send-Chord "^+n"

    $deadline = (Get-Date).AddSeconds(60)
    $ide = $null
    while ((Get-Date) -lt $deadline) {
        Start-Sleep -Milliseconds 800
        $now = Get-TraeWindows
        $ide = $now | Where-Object { $before -notcontains $_.Hwnd -and $_.Tit -notmatch 'Agent' } | Select-Object -First 1
        if ($ide) { break }
    }
    if (-not $ide) { Write-Output "FAIL: IDE window not found after ctrl+shift+n"; exit 3 }
    Write-Output ("ide-hwnd=" + $ide.Hwnd + " title='" + $ide.Tit + "' " + $ide.W + "x" + $ide.H)

    # 等扩展真正激活再发快捷键：窗口出现到 onStartupFinished 约 6s，
    # 发早了 keybinding 还没注册，按键完全无效（2026-11-10 第一次跑就是这么空的）。
    $logRoot = "$env:APPDATA\Trae CN\logs"
    $actDeadline = (Get-Date).AddSeconds(45)
    $activated = $false
    while ((Get-Date) -lt $actDeadline) {
        Start-Sleep -Milliseconds 1000
        $hit = Get-ChildItem $logRoot -Recurse -File -Filter "exthost.log" -ErrorAction SilentlyContinue |
            Where-Object { $_.LastWriteTime -gt $t0 } |
            Select-String -Pattern "agent-credit\.trae-credit-dump" -List -ErrorAction SilentlyContinue
        if ($hit) { $activated = $true; break }
    }
    Write-Output ("ext-activated=" + $activated)
    Start-Sleep -Seconds 1

    for ($i = 0; $i -lt 3; $i++) {
        if (-not (Set-Foreground $ide.Hwnd)) { Write-Output "WARN: ide window not foreground ($i)" }
        Send-Chord "^%u"
        Start-Sleep -Seconds 3
        $now = Get-TraeWindows
        $extra = $now | Where-Object { $before -notcontains $_.Hwnd -and $_.Hwnd -ne $ide.Hwnd }
        if ($extra) { $ide = @($extra)[0]; Write-Output ("usage-window hwnd=" + $ide.Hwnd + " title='" + $ide.Tit + "'"); break }
    }
    if (-not (Set-Foreground $ide.Hwnd)) { Write-Output "WARN: target window not foreground" }
    Start-Sleep -Seconds $WaitSec
} else {
    $ide = $null
    if ($Hwnd) {
        $want = [IntPtr][long]$Hwnd
        $ide = $wins | Where-Object { $_.Hwnd -eq $want } | Select-Object -First 1
        if (-not $ide) { Write-Output ("hwnd " + $want + " not found in " + $wins.Count + " windows"); exit 4 }
    }
    if (-not $ide) { $ide = $wins | Where-Object { $_.Tit -notmatch 'Agent' } | Select-Object -First 1 }
    if (-not $ide) { $ide = $wins | Select-Object -First 1 }
    if (-not (Set-Foreground $ide.Hwnd)) { Write-Output "WARN: window not foreground"; }
    if ($SendOpen) {
        # 复用调用方已经拉起的 IDE 窗口（不新建），只把用量页调出来。
        # 发 3 次 + 每次重新抢前台：窗口刚创建时单次 SendKeys 会被吞掉
        # （2026-11-10 21:42 实测 1 次无效，21:12 的 3 次间隔重发则稳定成功）。
        for ($i = 0; $i -lt 3; $i++) {
            if (-not (Set-Foreground $ide.Hwnd)) { Write-Output ("WARN: not foreground (send " + $i + ")") }
            Send-Chord "^%u"
            Start-Sleep -Seconds 3
        }
        Write-Output ("sent ctrl+alt+u x3 to hwnd=" + $ide.Hwnd)
        Start-Sleep -Seconds 2
    }
    Start-Sleep -Milliseconds 600
}

# 点开默认折叠的分组：坐标按窗口相对值给（OCR 结果里的 x,y 直接可用）。
function Click-Rel($win, [string]$spec) {
    $parts = $spec.Split(",")
    if ($parts.Count -ne 2) { Write-Output "WARN: bad -Click spec"; return }
    $x = [int]$parts[0]; $y = [int]$parts[1]
    $rr = New-Object U32+RECT
    [void][U32]::GetWindowRect($win.Hwnd, [ref]$rr)
    [void][U32]::SetCursorPos($rr.Left + $x, $rr.Top + $y)
    Start-Sleep -Milliseconds 200
    [U32]::mouse_event(0x0002, 0, 0, 0, [UIntPtr]::Zero)      # 左键按下
    Start-Sleep -Milliseconds 60
    [U32]::mouse_event(0x0004, 0, 0, 0, [UIntPtr]::Zero)      # 左键抬起
    Start-Sleep -Milliseconds 900
    Write-Output ("clicked window-rel " + $x + "," + $y)
}

# 滚动：滚轮事件落在光标位置，所以先把光标放进右侧明细列表（窗口 84% 宽、50% 高处），
# 再按格发 wheel。每格 120 = 约 100px，实测与页面行高 100px 对齐。
function Scroll-Panel($win) {
    $rr = New-Object U32+RECT
    [void][U32]::GetWindowRect($win.Hwnd, [ref]$rr)
    $cx = $rr.Left + [int](($rr.Right - $rr.Left) * 0.84)
    $cy = $rr.Top + [int](($rr.Bottom - $rr.Top) * 0.50)
    [void][U32]::SetCursorPos($cx, $cy)
    Start-Sleep -Milliseconds 200
    $up = [uint32]120
    $down = [uint32]4294967176      # -120 的补码；直接写 -120 会抛 uint32 溢出
    for ($i = 0; $i -lt 45; $i++) {
        [U32]::mouse_event(0x0800, 0, 0, $up, [UIntPtr]::Zero)
        Start-Sleep -Milliseconds 25
    }
    Start-Sleep -Milliseconds 500
    if ($ScrollDown -gt 0) {
        for ($i = 0; $i -lt $ScrollDown; $i++) {
            [U32]::mouse_event(0x0800, 0, 0, $down, [UIntPtr]::Zero)
            Start-Sleep -Milliseconds 60
        }
    }
    Start-Sleep -Milliseconds 1200        # 等惯性滚动/渲染收敛，否则抓到中间帧
}
if ($Click) { Click-Rel $ide $Click }
Scroll-Panel $ide

$r = New-Object U32+RECT
[void][U32]::GetWindowRect($ide.Hwnd, [ref]$r)
$w2 = $r.Right - $r.Left
$h2 = $r.Bottom - $r.Top
Write-Output ("capture hwnd=" + $ide.Hwnd + " rect=" + $r.Left + "," + $r.Top + " " + $w2 + "x" + $h2 + " scroll=" + $ScrollDown)

$bmp = New-Object System.Drawing.Bitmap($w2, $h2)
$g = [System.Drawing.Graphics]::FromImage($bmp)
$hdc = $g.GetHdc()
$ok = [U32]::PrintWindow($ide.Hwnd, $hdc, 2)      # 2 = PW_RENDERFULLCONTENT，Electron 必需
$g.ReleaseHdc($hdc)
$g.Dispose()
if (-not $ok) {
    Write-Output "WARN: PrintWindow failed, fallback CopyFromScreen"
    $g2 = [System.Drawing.Graphics]::FromImage($bmp)
    $g2.CopyFromScreen($r.Left, $r.Top, 0, 0, $bmp.Size)
    $g2.Dispose()
}

if (-not $OutPng) { $OutPng = Join-Path $root "logs\_trae_usage_shot.png" }
$dir = Split-Path -Parent $OutPng
if ($dir -and -not (Test-Path $dir)) { New-Item -ItemType Directory -Path $dir -Force | Out-Null }
$bmp.Save($OutPng, [System.Drawing.Imaging.ImageFormat]::Png)
$bmp.Dispose()
Write-Output ("PNG=" + $OutPng)

if ((-not $SkipOpen) -and (-not $NoClose)) {
    Write-Output "closing IDE window"
    [void][U32]::SendMessage($ide.Hwnd, 0x0010, [IntPtr]::Zero, [IntPtr]::Zero)
}
