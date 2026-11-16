# Register the on-demand task that runs scripts/codebuddy-worker.py in the CURRENT
# user session (InteractiveToken, LeastPrivilege). No admin prompt is expected for
# a task owned by the logged-on user; if Task Scheduler refuses, run this script
# from an elevated PowerShell and it will succeed (details in
# doc/ledger-lock-and-scheduled-dispatch.md).
#
# Usage:
#   powershell -ExecutionPolicy Bypass -File .\scripts\register-codebuddy-task.ps1
#   powershell -ExecutionPolicy Bypass -File .\scripts\register-codebuddy-task.ps1 -Remove
param([switch]$Remove)

$TaskName = "agent-credit-codebuddy"

if ($Remove) {
  Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction Stop
  Write-Host "Removed task $TaskName"
  exit 0
}

$root = Split-Path -Parent $PSScriptRoot
$python = (Get-Command python).Source
$sid = ([System.Security.Principal.WindowsIdentity]::GetCurrent()).User.Value
$worker = Join-Path $root "scripts\codebuddy-worker.py"

$xml = @"
<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.2" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <RegistrationInfo>
    <Description>agent-credit codebuddy queue worker (on demand, interactive user session, no elevation)</Description>
  </RegistrationInfo>
  <Triggers />
  <Principals>
    <Principal id="Author">
      <UserId>$sid</UserId>
      <LogonType>InteractiveToken</LogonType>
      <RunLevel>LeastPrivilege</RunLevel>
    </Principal>
  </Principals>
  <Settings>
    <MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>
    <DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>
    <StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>
    <AllowHardTerminate>true</AllowHardTerminate>
    <StartWhenAvailable>false</StartWhenAvailable>
    <ExecutionTimeLimit>PT30M</ExecutionTimeLimit>
    <Priority>7</Priority>
  </Settings>
  <Actions Context="Author">
    <Exec>
      <Command>$python</Command>
      <Arguments>"$worker"</Arguments>
      <WorkingDirectory>$root</WorkingDirectory>
    </Exec>
  </Actions>
</Task>
"@

Register-ScheduledTask -TaskName $TaskName -Xml $xml -Force | Out-Null
Write-Host "Registered $TaskName (InteractiveToken, LeastPrivilege, IgnoreNew, on demand)"
schtasks /Query /TN $TaskName
