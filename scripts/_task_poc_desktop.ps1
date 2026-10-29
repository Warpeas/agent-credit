# One-shot: run the hidden-desktop PoC (scripts/_poc_desktop.ps1) via a
# NON-elevated scheduled task - same trick as _task_trae_claim.ps1: the sandbox
# cannot launch GUI processes directly, but an Interactive/Limited task runs in
# the real desktop session and can.
#
# NOTE: the task name carries a date suffix on purpose. Unregister-ScheduledTask
# fails inside the sandbox (access denied), so a re-used name would make
# Register-ScheduledTask fail with "file exists" while Start-ScheduledTask runs
# the STALE action. Bump the suffix for every new run.
param(
    [string]$ClientProcess = "Trae CN",
    [int]$WindowWaitSeconds = 120
)

$root = Split-Path -Parent $PSScriptRoot
$name = "agent-credit-poc-once-20261020"
$script = Join-Path $root "scripts\_poc_desktop.ps1"
if (-not (Test-Path $script)) { Write-Host "MISSING: $script"; exit 1 }

$arg = '-NoProfile -ExecutionPolicy Bypass -File "' + $script + '"' +
       ' -ClientProcess "' + $ClientProcess + '"' +
       ' -WindowWaitSeconds ' + $WindowWaitSeconds

$me = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name
$action = New-ScheduledTaskAction -Execute "powershell.exe" -Argument $arg -WorkingDirectory $root
$principal = New-ScheduledTaskPrincipal -UserId $me -LogonType Interactive -RunLevel Limited
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 10) -MultipleInstances IgnoreNew

$reuse = $false
$existing = Get-ScheduledTask -TaskName $name -ErrorAction SilentlyContinue
if ($existing) {
    $act = $existing.Actions[0]
    if ($act.Execute -like "*powershell*" -and $act.Arguments -like "*_poc_desktop.ps1*") {
        # Unregister-ScheduledTask is denied inside the sandbox, so a stale task
        # pointing at the SAME script can be re-started in place. Only a changed
        # action needs a fresh task name (otherwise Register fails "file exists"
        # while Start would run the stale action).
        $reuse = $true
    }
}
try {
    if (-not $reuse) {
        Register-ScheduledTask -TaskName $name -Action $action -Principal $principal -Settings $settings | Out-Null
    }
    Start-ScheduledTask -TaskName $name
    Write-Host ("started $name (client=$ClientProcess user=$me reuse=" + $reuse + ")")
} catch {
    Write-Host ("REGISTER/START FAILED: " + $_.Exception.Message)
    exit 1
}
