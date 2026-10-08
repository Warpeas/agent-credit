# One-shot: run LobsterAI claim/verify NON-elevated via scheduled task.
# Sandboxed session cannot Start-Process a GUI client directly (procs stay 0),
# but a RunLevel=Limited + LogonType=Interactive task runs in the real desktop
# session and can. Registered on demand, started, then unregistered.
#
# The task's -UserId must be the INTERACTIVE desktop user (not SYSTEM): a GUI
# client launched as SYSTEM has no visible desktop, so the window never appears.
# Derived from the current identity rather than hardcoded, to stay portable.
#
# Usage (from PowerShell tool):
#   powershell -ExecutionPolicy Bypass -File scripts\_task_lobsterai.ps1 -Mode verify

param([string]$Mode = "claim")

$root = Split-Path -Parent $PSScriptRoot
$name = "agent-credit-lobsterai-once"
$claim = Join-Path $root "scripts\ui_claim_lobsterai.ps1"
$out= Join-Path $root "logs\lobsterai_claim.json"

if (Test-Path $out) { Remove-Item $out -Force }

$flag = if ($Mode -eq "verify") { "-Verify" } else { "" }
$arg ='-NoProfile -ExecutionPolicy Bypass -File "' + $claim + '" ' + $flag + ' -OutFile "' + $out + '"'

$me = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name
$action = New-ScheduledTaskAction -Execute "powershell.exe" -Argument $arg -WorkingDirectory $root
$principal = New-ScheduledTaskPrincipal -UserId $me -LogonType Interactive -RunLevel Limited
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 10) -MultipleInstances IgnoreNew

Unregister-ScheduledTask -TaskName $name -Confirm:$false -ErrorAction SilentlyContinue
Register-ScheduledTask -TaskName $name -Action $action -Principal $principal -Settings $settings | Out-Null
Start-ScheduledTask -TaskName $name
Write-Host "started $name mode=$Mode user=$me"