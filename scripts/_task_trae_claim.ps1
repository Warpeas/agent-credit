# One-shot: run Trae claim NON-elevated via scheduled task.
# The client was launched by a RunLevel=Limited task, so it runs at medium
# integrity — a medium-integrity claim script can drive it without UAC.
# (UIPI only blocks LOW -> HIGH injection; both sides are equal here.)
#
# The task's -UserId must be the INTERACTIVE desktop user (not SYSTEM): the
# claim script needs the same visible desktop the client lives on.
# Derived from the current identity rather than hardcoded, to stay portable.
#
# Usage (from PowerShell tool):
#   powershell -ExecutionPolicy Bypass -File scripts\_task_trae_claim.ps1
#   ... -Mode dry-run -ProcessName "Trae CN"

param(
    [string]$Mode = "claim",            # claim | dry-run | explore
    [string]$ProcessName = "Trae CN",   # 2026-10-11: TRAE SOLO CN 已并入 Trae CN
    [string]$Extra = "",                # 原样透传给 ui_claim_trae.ps1，如 "-Offscreen:$false"
    [switch]$Foreground,                # 前台模式（-Offscreen:$false），屏外点击被遮挡时用
    [int]$IdleWaitSec = -1,             # 前台模式下等待用户空闲的上限；-1 用脚本默认
    [int]$IdleThresholdSec = -1         # 前台模式要求的空闲秒数；-1 用脚本默认
)

$root = Split-Path -Parent $PSScriptRoot
$name = "agent-credit-trae-claim"
$script = Join-Path $root "scripts\ui_claim_trae.ps1"
$out   = Join-Path $root "logs\trae_claim.json"

if (Test-Path $out) { Remove-Item $out -Force }

$flag = switch ($Mode) {
    "dry-run" { "-DryRun" }
    "explore" { "-Explore" }
    default   { "" }
}

$idleArgs = ""
if ($IdleWaitSec -ge 0) { $idleArgs += " -IdleWaitSec $IdleWaitSec" }
if ($IdleThresholdSec -ge 0) { $idleArgs += " -IdleThresholdSec $IdleThresholdSec" }
$extraArg = if ($Foreground) { ' -Foreground' + $idleArgs } elseif ($Extra) { " " + $Extra } else { "" }
$arg = '-NoProfile -ExecutionPolicy Bypass -File "' + $script + '" ' + $flag +
       ' -ProcessName "' + $ProcessName + '"' + $extraArg +
       ' -OutFile "' + $out + '"'

$me = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name
$action= New-ScheduledTaskAction -Execute "powershell.exe" -Argument $arg -WorkingDirectory $root
$principal = New-ScheduledTaskPrincipal -UserId $me -LogonType Interactive -RunLevel Limited
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 8) -MultipleInstances IgnoreNew

Unregister-ScheduledTask -TaskName $name -Confirm:$false -ErrorAction SilentlyContinue
Register-ScheduledTask -TaskName $name -Action $action -Principal $principal -Settings $settings | Out-Null
Start-ScheduledTask -TaskName $name
Write-Host "started $name mode=$Mode proc=$ProcessName user=$me"