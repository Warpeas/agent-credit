# UI check-in helper. Names are passed as |-separated ASCII/Unicode args.
param(
    [Parameter(Mandatory = $true)][string]$ProcessMatch,
    [string]$ClickName = "",
    # 可选的一级入口（如小浣熊「账户」）；打开并刷新 UIA 后再找签到按钮。
    [string]$OpenName = "",
    [string]$OpenNamePattern = "",
    [string]$AlreadyName = "",
    [string]$SuccessName = "",
    [string]$SendKeys = "",
    [int]$WaitSeconds = 45,
    # 只读取 UIA 名称，不点击；用于新客户端首次适配，避免盲点。
    [switch]$Explore,
    # 配合 OpenName/Pattern：只打开一级面板再读取 UIA，不点击签到/领取。
    [switch]$ExploreAfterOpen
)

$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
Add-Type -AssemblyName UIAutomationClient
Add-Type -AssemblyName UIAutomationTypes
Add-Type -AssemblyName System.Windows.Forms

Add-Type @"
using System;
using System.Runtime.InteropServices;
public static class UiClaimNative {
  [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr hWnd);
  [DllImport("user32.dll")] public static extern bool ShowWindow(IntPtr hWnd, int nCmdShow);
  [DllImport("user32.dll")] public static extern bool SetCursorPos(int X, int Y);
  [DllImport("user32.dll")] public static extern void mouse_event(int dwFlags, int dx, int dy, int cButtons, int dwExtraInfo);
}
"@

function Split-Names([string]$raw) {
    if ([string]::IsNullOrWhiteSpace($raw)) { return @() }
    return @($raw.Split("|") | ForEach-Object { $_.Trim() } | Where-Object { $_ })
}

function Test-NameMatch([string]$name, [string[]]$needles) {
    if ([string]::IsNullOrWhiteSpace($name)) { return $false }
    foreach ($n in $needles) {
        if ($name -like "*$n*") { return $true }
    }
    return $false
}

function Test-ClickableName([string]$name, [string[]]$needles) {
    if (-not (Test-NameMatch $name $needles)) { return $false }
    $deny = @("规则", "记录", "历史", "日历", "说明", "帮助")
    foreach ($d in $deny) {
        if ($name -like "*$d*") { return $false }
    }
    return $true
}

function Test-ExplicitStatus([string]$name, [string[]]$needles) {
    # 状态文案必须短且不含规则/历史说明，避免把「签到规则」「昨日已签到」
    # 之类的页面文本当成本日已领证据。
    if ([string]::IsNullOrWhiteSpace($name) -or $name.Trim().Length -gt 24) { return $false }
    if ($name -match "规则|记录|历史|日历|说明|帮助|昨日|明天|明日") { return $false }
    return (Test-NameMatch $name.Trim() $needles)
}

function Out-Result([string]$status, [string]$detail) {
    $payload = @{ status = $status; detail = $detail } | ConvertTo-Json -Compress
    Write-Output $payload
    if ($status -eq "ok" -or $status -eq "already") { exit 0 }
    exit 2
}

function Get-TargetProcess2([string[]]$patterns) {
    foreach ($p in Get-Process) {
        if ($p.MainWindowHandle -eq [IntPtr]::Zero) { continue }
        foreach ($pat in $patterns) {
            if ($p.ProcessName -like "*$pat*") { return $p }
        }
    }
    return $null
}

$procPatterns = Split-Names $ProcessMatch
$clickNames = Split-Names $ClickName
$alreadyNames = Split-Names $AlreadyName
$successNames = Split-Names $SuccessName
$openNames = Split-Names $OpenName

$deadline = (Get-Date).AddSeconds($WaitSeconds)
$proc = $null
while ((Get-Date) -lt $deadline) {
    $proc = Get-TargetProcess2 $procPatterns
    if ($proc) { break }
    Start-Sleep -Milliseconds 800
}
if (-not $proc) {
    Out-Result "notfound" "未找到主窗口"
}

[void][UiClaimNative]::ShowWindow($proc.MainWindowHandle, 9)
Start-Sleep -Milliseconds 400
[void][UiClaimNative]::SetForegroundWindow($proc.MainWindowHandle)
Start-Sleep -Milliseconds 400

$root = [System.Windows.Automation.AutomationElement]::FromHandle($proc.MainWindowHandle)
if (-not $root) {
    Out-Result "failed" "无法附加 UI Automation"
}

$types = @(
    [System.Windows.Automation.ControlType]::Button,
    [System.Windows.Automation.ControlType]::Hyperlink,
    [System.Windows.Automation.ControlType]::MenuItem,
    [System.Windows.Automation.ControlType]::ListItem,
    [System.Windows.Automation.ControlType]::Text,
    [System.Windows.Automation.ControlType]::Custom,
    [System.Windows.Automation.ControlType]::Pane
)

function Get-NamedElements($rootEl) {
    $found = New-Object System.Collections.Generic.List[object]
    foreach ($t in $types) {
        $cond = New-Object System.Windows.Automation.PropertyCondition(
            [System.Windows.Automation.AutomationElement]::ControlTypeProperty, $t)
        try {
            $els = $rootEl.FindAll([System.Windows.Automation.TreeScope]::Descendants, $cond)
        } catch {
            continue
        }
        for ($i = 0; $i -lt $els.Count; $i++) {
            $el = $els.Item($i)
            $nm = $el.Current.Name
            if (-not [string]::IsNullOrWhiteSpace($nm)) {
                $found.Add(@{ El = $el; Name = $nm })
            }
        }
    }
    return $found
}

function Invoke-Element($el) {
    try {
        $pat = $el.GetCurrentPattern([System.Windows.Automation.InvokePattern]::Pattern)
        $pat.Invoke()
        return $true
    } catch {}
    try {
        $pt = $el.GetClickablePoint()
        [void][UiClaimNative]::SetCursorPos([int]$pt.X, [int]$pt.Y)
        Start-Sleep -Milliseconds 80
        [UiClaimNative]::mouse_event(0x0002, 0, 0, 0, 0)
        [UiClaimNative]::mouse_event(0x0004, 0, 0, 0, 0)
        return $true
    } catch {
        return $false
    }
}

$named = Get-NamedElements $root

if ($Explore) {
    $names = @($named | Select-Object -First 160 | ForEach-Object { $_.Name })
    Out-Result "explore" ("UIA 名称 " + $named.Count + " 项: " + ($names -join " | "))
}

# 一级入口只接受完整名称（例如「账户」），不点击任务标题里的同名长文本。
$opened = $false
if ($openNames.Count -gt 0 -or $OpenNamePattern) {
    foreach ($item in $named) {
        $name = $item.Name.Trim()
        $matched = ($openNames -contains $name)
        if ($OpenNamePattern -and $name -match $OpenNamePattern) { $matched = $true }
        if ($matched -and $item.El.Current.IsEnabled) {
            if (Invoke-Element $item.El) {
                $opened = $true
                Start-Sleep -Seconds 3
                $named = Get-NamedElements $root
                break
            }
        }
    }
    if (-not $opened) { Out-Result "notfound" ("未找到一级入口: " + ($openNames -join "/") + $OpenNamePattern) }
}
if ($ExploreAfterOpen) {
    $names = @($named | Select-Object -First 200 | ForEach-Object { $_.Name })
    Out-Result "explore" ("一级面板 UIA 名称 " + $named.Count + " 项: " + ($names -join " | "))
}

# 先认明确的已签状态，避免点击已经失效的入口。不用「签到」二字做包含匹配，
# 防止把规则说明/历史记录当成已领。
foreach ($item in $named) {
    if (Test-ExplicitStatus $item.Name $alreadyNames) {
        $prefix = if ($opened) { "已打开「" + ($openNames -join "/") + "」；" } else { "" }
        Out-Result "already" ($prefix + "界面已显示: " + $item.Name)
    }
}

$clicked = $false
$clickedName = ""
foreach ($item in $named) {
    if (Test-ClickableName $item.Name $clickNames) {
        if (Invoke-Element $item.El) {
            $clicked = $true
            $clickedName = $item.Name
            break
        }
    }
}

if ($clicked) {
    Start-Sleep -Seconds 2
    $after = Get-NamedElements $root
    foreach ($item in $after) {
        if (Test-ExplicitStatus $item.Name ($successNames + $alreadyNames)) {
            Out-Result "ok" ("已点击「" + $clickedName + "」，结果: " + $item.Name)
        }
    }
    # 点击动作本身不是签到成功证据。只有界面出现明确成功/已签状态才入账；
    # 否则返回 pending，让上层保存失败，避免凭一次点击虚记积分。
    Out-Result "pending" ("已点击「" + $clickedName + "」，但未确认签到状态")
}

if (-not [string]::IsNullOrWhiteSpace($SendKeys)) {
    [void][UiClaimNative]::SetForegroundWindow($proc.MainWindowHandle)
    Start-Sleep -Milliseconds 300
    [System.Windows.Forms.SendKeys]::SendWait($SendKeys)
    Start-Sleep -Seconds 2
    $after = Get-NamedElements $root
    foreach ($item in $after) {
        if (Test-ExplicitStatus $item.Name ($successNames + $alreadyNames)) {
            Out-Result "ok" ("已发送快捷指令，结果: " + $item.Name)
        }
    }
    Out-Result "pending" "已发送快捷指令，但未确认签到状态"
}

Out-Result "notfound" "窗口内未找到签到按钮"
