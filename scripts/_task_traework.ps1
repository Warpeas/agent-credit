# One-shot: launch TraeWork NON-elevated via scheduled task, then wait for its main window.
# Same trick as _task_lobsterai.ps1: the sandboxed session cannot Start-Process a
# GUI client (procs stay 0), but a RunLevel=Limited + LogonType=Interactive task
# runs inside the real desktop session and can. Registered on demand.
#
# The task's -UserId must be the INTERACTIVE desktop user (not SYSTEM): a GUI
# client launched as SYSTEM has no visible desktop, so the window never appears.
# Derived from the current identity rather than hardcoded, to stay portable.
#
# Usage (from PowerShell tool):
#   powershell -ExecutionPolicy Bypass -File scripts\_task_traework.ps1
#   ... -ProcessName "Trae CN"     # TraeCode variant

param(
    [string]$ProcessName = "TRAE SOLO CN",
    [switch]$WaitReady
)

$root = Split-Path -Parent $PSScriptRoot
$name = "agent-credit-traework-once"

if ($ProcessName -eq "TRAE SOLO CN") {
    $exe = Join-Path $env:LOCALAPPDATA 'Programs\TRAE SOLO CN\TRAE SOLO CN.exe'
} else {
    $exe = Join-Path $env:LOCALAPPDATA "Programs\$ProcessName\$ProcessName.exe"
}

if (-not (Test-Path $exe)) { Write-Host "EXE MISSING: $exe"; exit 1 }

$before = @(Get-Process -Name $ProcessName -ErrorAction SilentlyContinue).Count
Write-Host "preexisting procs=$before"

if ($before -eq 0) {
    $me = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name
    $action = New-ScheduledTaskAction -Execute $exe -WorkingDirectory (Split-Path -Parent $exe)
    $principal = New-ScheduledTaskPrincipal -UserId $me -LogonType Interactive -RunLevel Limited
    $settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
        -ExecutionTimeLimit (New-TimeSpan -Minutes 10) -MultipleInstances IgnoreNew

    Unregister-ScheduledTask -TaskName $name -Confirm:$false -ErrorAction SilentlyContinue
    Register-ScheduledTask -TaskName $name -Action $action -Principal $principal -Settings $settings | Out-Null
    Start-ScheduledTask -TaskName $name
    Write-Host "started $name (launching $ProcessName as $me)"

    # The task stays registered while the app runs (its lifetime == task lifetime),
    # so do NOT unregister it here — Stop-ScheduledTask would kill the client.
} else {
    Write-Host "already running, not launching"
}

if ($WaitReady) {
    $dl = (Get-Date).AddSeconds(90)
    while ((Get-Date) -lt $dl) {
        Start-Sleep -Seconds 3
        $n = @(Get-Process -Name $ProcessName -ErrorAction SilentlyContinue).Count
        if ($n -gt 0) { Write-Host "procs=$n"; break }
    }
    $final = @(Get-Process -Name $ProcessName -ErrorAction SilentlyContinue).Count
    Write-Host "final procs=$final"
}