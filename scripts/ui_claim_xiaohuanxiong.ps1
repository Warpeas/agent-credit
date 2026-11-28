# Xiaohuanxiong desktop check-in verification (no sign-in button exists).
# Opening the signed-in client grants the daily credits. Success requires the
# client's own points details to show today's grant and its extended expiry.
param(
    [Parameter(Mandatory = $true)][string]$ProcessMatch,
    [string]$OutFile = "",
    [string]$Today = "",
    [int]$ExpectedAmount = 300,
    [int]$WaitSeconds = 45
)

$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
Add-Type -AssemblyName UIAutomationClient
Add-Type -AssemblyName UIAutomationTypes
Add-Type @"
using System;
using System.Runtime.InteropServices;
public static class XiaoHuanNative {
  [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr hWnd);
  [DllImport("user32.dll")] public static extern bool ShowWindow(IntPtr hWnd, int nCmdShow);
  [DllImport("user32.dll")] public static extern void mouse_event(int dwFlags, int dx, int dy, int dwButtons, int dwExtraInfo);
}
"@

function Save-Result([string]$status, [string]$detail) {
    $payload = @{ status = $status; detail = $detail } | ConvertTo-Json -Compress
    if ($OutFile) {
        [System.IO.File]::WriteAllText($OutFile, $payload, (New-Object System.Text.UTF8Encoding($false)))
    }
    Write-Output $payload
    if ($status -eq "ok") { exit 0 }
    exit 2
}

if (-not $Today) { $Today = (Get-Date).ToString("yyyy-MM-dd") }
$grantDay = [datetime]::ParseExact($Today, "yyyy-MM-dd", $null)
$expectedExpiry = $grantDay.AddDays(6).ToString("MM-dd")
$patterns = @($ProcessMatch.Split("|") | Where-Object { $_ })

$proc = $null
$deadline = (Get-Date).AddSeconds($WaitSeconds)
while ((Get-Date) -lt $deadline) {
    $proc = Get-Process | Where-Object {
        $candidate = $_
        if ($candidate.MainWindowHandle -eq [IntPtr]::Zero) { return $false }
        foreach ($pattern in $patterns) {
            if ($candidate.ProcessName -like "*$pattern*") { return $true }
        }
        return $false
    } | Select-Object -First 1
    if ($proc) { break }
    Start-Sleep -Milliseconds 800
}
if (-not $proc) { Save-Result "notfound" "未找到小浣熊客户端主窗口" }

[void][XiaoHuanNative]::ShowWindow($proc.MainWindowHandle, 9)
Start-Sleep -Milliseconds 400
[void][XiaoHuanNative]::SetForegroundWindow($proc.MainWindowHandle)
Start-Sleep -Milliseconds 500
$root = [System.Windows.Automation.AutomationElement]::FromHandle($proc.MainWindowHandle)
if (-not $root) { Save-Result "failed" "无法附加 UI Automation" }

$types = @(
    [System.Windows.Automation.ControlType]::Button,
    [System.Windows.Automation.ControlType]::Hyperlink,
    [System.Windows.Automation.ControlType]::Text,
    [System.Windows.Automation.ControlType]::Custom,
    [System.Windows.Automation.ControlType]::Pane
)
function Get-Names($rootEl) {
    $names = New-Object System.Collections.Generic.List[string]
    foreach ($type in $types) {
        $cond = New-Object System.Windows.Automation.PropertyCondition(
            [System.Windows.Automation.AutomationElement]::ControlTypeProperty, $type)
        try { $els = $rootEl.FindAll([System.Windows.Automation.TreeScope]::Descendants, $cond) }
        catch { continue }
        for ($i = 0; $i -lt $els.Count; $i++) {
            $name = $els.Item($i).Current.Name
            if (-not [string]::IsNullOrWhiteSpace($name)) { $names.Add($name.Trim()) }
        }
    }
    return $names
}
function Invoke-Element($el) {
    try {
        $pat = $el.GetCurrentPattern([System.Windows.Automation.InvokePattern]::Pattern)
        $pat.Invoke()
        return $true
    } catch {}
    try {
        $point = $el.GetClickablePoint()
        [void][XiaoHuanNative]::SetForegroundWindow($proc.MainWindowHandle)
        Start-Sleep -Milliseconds 100
        [System.Windows.Forms.Cursor]::Position = New-Object System.Drawing.Point([int]$point.X, [int]$point.Y)
        Start-Sleep -Milliseconds 100
        [XiaoHuanNative]::mouse_event(0x0002, 0, 0, 0, 0)
        [XiaoHuanNative]::mouse_event(0x0004, 0, 0, 0, 0)
        return $true
    } catch { return $false }
}
Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing

$names = @(Get-Names $root)
# 详情可能已开着（用户刚看过或上一轮成功）；此时只读，不再次点击入口。
$opened = (($names -join "`n") -match "积分构成" -and ($names -join "`n") -match "积分明细")
if (-not $opened) {
foreach ($type in $types) {
    if ($opened) { break }
    $cond = New-Object System.Windows.Automation.PropertyCondition(
        [System.Windows.Automation.AutomationElement]::ControlTypeProperty, $type)
    try { $els = $root.FindAll([System.Windows.Automation.TreeScope]::Descendants, $cond) }
    catch { continue }
    for ($i = 0; $i -lt $els.Count; $i++) {
        $el = $els.Item($i)
        if ($el.Current.Name.Trim() -match "^可用积分(?::|\s)*\d+$" -and $el.Current.IsEnabled) {
            if (Invoke-Element $el) { $opened = $true; break }
        }
    }
}
}
if (-not $opened) { Save-Result "failed" "未找到可点击的「可用积分」详情入口" }

$body = ""
$detailDeadline = (Get-Date).AddSeconds(20)
while ((Get-Date) -lt $detailDeadline) {
    Start-Sleep -Seconds 1
    $names = @(Get-Names $root)
    $body = $names -join "`n"
    if ($body -match "积分构成" -and $body -match "积分明细") { break }
}
if ($body -notmatch "积分构成" -or $body -notmatch "积分明细") {
    Save-Result "failed" "已点击积分入口，但积分详情未打开（可能页面改版）"
}

$extensionRule = $body -match "每日积分每天\s+00:00\s+发放[^\n]*有效期延长至\s+7\s*天"
$entryPattern = "每日积分发放\s*\n" + [regex]::Escape($Today) +
    "\s+00:00\s*·\s*有效期至\s+" + [regex]::Escape($expectedExpiry) +
    "\s+24:00\s*\n\+" + [regex]::Escape([string]$ExpectedAmount) + '(?:\s|$)'
$entry = [regex]::Match($body, $entryPattern)
if (-not $entry.Success) {
    $nearby = @($names | Where-Object {
        $_ -match "每日积分发放|$([regex]::Escape($Today))|有效期至|^\+"
    } | Select-Object -Last 12) -join " | "
    Save-Result "pending" ("积分详情已打开，但未确认今日 +$ExpectedAmount 且有效期至 $expectedExpiry 24:00；页面: " + $nearby)
}
if (-not $extensionRule) {
    Save-Result "pending" ("已确认今日 +$ExpectedAmount、有效期至 $expectedExpiry 24:00，但未确认登录延长 7 天的规则文案")
}
Save-Result "ok" ("客户端积分详情确认：$Today 00:00 发放 +$ExpectedAmount，有效期至 $expectedExpiry 24:00；登录延长 7 天规则仍在 [granted] $ExpectedAmount")
