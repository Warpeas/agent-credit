# UI check-in helper. Names are passed as |-separated ASCII/Unicode args.
param(
    [Parameter(Mandatory = $true)][string]$ProcessMatch,
    [string]$ClickName = "",
    [string]$AlreadyName = "",
    [string]$SuccessName = "",
    [string]$SendKeys = "",
    [int]$WaitSeconds = 45
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
        if (Test-NameMatch $item.Name ($successNames + $alreadyNames)) {
            Out-Result "ok" ("已点击「" + $clickedName + "」，结果: " + $item.Name)
        }
    }
    Out-Result "ok" ("已点击「" + $clickedName + "」")
}

if (-not [string]::IsNullOrWhiteSpace($SendKeys)) {
    [void][UiClaimNative]::SetForegroundWindow($proc.MainWindowHandle)
    Start-Sleep -Milliseconds 300
    [System.Windows.Forms.SendKeys]::SendWait($SendKeys)
    Start-Sleep -Seconds 2
    $after = Get-NamedElements $root
    foreach ($item in $after) {
        if (Test-NameMatch $item.Name ($successNames + $alreadyNames)) {
            Out-Result "ok" ("已发送快捷指令，结果: " + $item.Name)
        }
    }
    Out-Result "ok" "已向窗口发送签到指令"
}

Out-Result "notfound" "窗口内未找到签到按钮"
