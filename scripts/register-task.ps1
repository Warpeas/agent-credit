# Scheduled task: run checkin at logon + 3min delay, ELEVATED (no UAC inside).
# Run once elevated:  powershell -ExecutionPolicy Bypass -File .\register-task.ps1
# Uses XML registration because older ScheduledTasks modules lack -UserId / Delay on triggers.

$root = Split-Path -Parent $PSScriptRoot
$python = (Get-Command python).Source
$sid = ([System.Security.Principal.WindowsIdentity]::GetCurrent()).User.Value

$xml = @"
<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.2" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <RegistrationInfo>
    <Description>Agent credit daily checkin at logon +3min (elevated, no UAC)</Description>
  </RegistrationInfo>
  <Triggers>
    <LogonTrigger>
      <Enabled>true</Enabled>
      <Delay>PT3M</Delay>
    </LogonTrigger>
  </Triggers>
  <Principals>
    <Principal id="Author">
      <UserId>$sid</UserId>
      <LogonType>InteractiveToken</LogonType>
      <RunLevel>HighestAvailable</RunLevel>
    </Principal>
  </Principals>
  <Settings>
    <MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>
    <DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>
    <StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>
    <AllowHardTerminate>true</AllowHardTerminate>
    <StartWhenAvailable>true</StartWhenAvailable>
    <ExecutionTimeLimit>PT15M</ExecutionTimeLimit>
    <Priority>7</Priority>
  </Settings>
  <Actions Context="Author">
    <Exec>
      <Command>$python</Command>
      <Arguments>"$root\credit.py" checkin</Arguments>
      <WorkingDirectory>$root</WorkingDirectory>
    </Exec>
  </Actions>
</Task>
"@

Register-ScheduledTask -TaskName "agent-credit-checkin" -Xml $xml -Force | Out-Null
Write-Host "Registered agent-credit-checkin: logon +3min delay, RunLevel Highest, interactive session only"
