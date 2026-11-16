# One-shot: run trae_credit_sync.ps1 via scheduled task (interactive desktop).
# Same pattern as _task_trae_claim.ps1 — the sandboxed session cannot drive GUI.
#
# Usage:
#   powershell -ExecutionPolicy Bypass -File scripts\_task_trae_credit_sync.ps1

$root = Split-Path -Parent $PSScriptRoot
$name = "agent-credit-trae-credit-sync"
$script = Join-Path $root "scripts\trae_credit_sync.ps1"

$arg = '-NoProfile -ExecutionPolicy Bypass -File "' + $script + '"'

$me = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name
$action= New-ScheduledTaskAction -Execute "powershell.exe" -Argument $arg -WorkingDirectory $root
$principal = New-ScheduledTaskPrincipal -UserId $me -LogonType Interactive -RunLevel Limited
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 6) -MultipleInstances IgnoreNew

Unregister-ScheduledTask -TaskName $name -Confirm:$false -ErrorAction SilentlyContinue
Register-ScheduledTask -TaskName $name -Action $action -Principal $principal -Settings $settings | Out-Null
Start-ScheduledTask -TaskName $name
Write-Host "started $name user=$me"
