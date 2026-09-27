# Register (or re-register) the daily auto-checkin scheduled task.
# ASCII code only. Run once ELEVATED (UAC).
#
# Design (owner requirement): every day, as long as the machine is on, the
# check-in runs exactly once.
#   * CalendarTrigger 00:05 (+<=10min random) -> for machines left running
#     overnight; lands right after midnight.
#   * LogonTrigger with Delay=PT5M -> for machines booted during the day. The
#     delay is deliberate: do NOT compete with startup auto-launch apps, which
#     would slow the machine down right after boot.
#   * StartWhenAvailable -> if the scheduled moment was missed (machine was
#     off), run as soon as possible once it is back on.
# Check-in is idempotent (already-claimed is detected), so the rare case of
# both triggers firing in one day is harmless.
#
# Why HighestAvailable + InteractiveToken:
#   * InteractiveToken -> runs only while the user is logged on, so desktop GUI
#     clients really appear and can be clicked by the OCR scripts.
#   * HighestAvailable -> the task itself is already elevated, so the
#     ShellExecuteW "runas" calls inside the claim scripts do NOT raise UAC.
param([switch]$RunNow)

$root = Split-Path -Parent $PSScriptRoot

# Prefer the managed python we actually verified; fall back to PATH python.
$py = "C:\Users\Hunter\.workbuddy\binaries\python\versions\3.13.12\python.exe"
if (-not (Test-Path $py)) { $py = (Get-Command python).Source }
$sid = ([System.Security.Principal.WindowsIdentity]::GetCurrent()).User.Value

# -RunNow moves the DAILY trigger's start boundary to ~100s from now so the
# scheduler fires the task itself, right away, at highest privilege.
#
# Why not a one-shot TimeTrigger on the same task? Verified 2026-09-28: the
# TimeTrigger is silently dropped (it never shows up in Get-ScheduledTask and
# never fires). Why not a brand-new separate task? This environment can re-
# register an existing task but Register-ScheduledTask for a NEW task name
# silently does nothing. Why not trigger it ourselves with ShellExecuteW
# "runas"? The elevated shell frequently never starts (UAC path unreliable
# from the automation session).
# RandomDelay is dropped in RunNow mode, otherwise the run would be postponed
# by up to 10 minutes. Re-run WITHOUT -RunNow afterwards to restore 00:05.
$dailyStart = "2026-09-28T00:05:00"
$randomXml  = "      <RandomDelay>PT10M</RandomDelay>`n"
if ($RunNow) {
    $dailyStart = (Get-Date).AddSeconds(100).ToString("yyyy-MM-ddTHH:mm:ss")
    $randomXml  = ""
}

$xml = @"
<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.2" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <RegistrationInfo>
    <Description>Agent credit daily checkin: daily 00:05 (plus up to 10m random) and logon+5min; elevated, interactive, no UAC inside</Description>
  </RegistrationInfo>
  <Triggers>
    <CalendarTrigger>
      <StartBoundary>$dailyStart</StartBoundary>
      <Enabled>true</Enabled>
      <ScheduleByDay>
        <DaysInterval>1</DaysInterval>
      </ScheduleByDay>
$randomXml    </CalendarTrigger>
    <LogonTrigger>
      <Enabled>true</Enabled>
      <Delay>PT5M</Delay>
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
    <RunOnlyIfNetworkAvailable>false</RunOnlyIfNetworkAvailable>
    <IdleSettings>
      <StopOnIdleEnd>false</StopOnIdleEnd>
      <RestartOnIdle>false</RestartOnIdle>
    </IdleSettings>
    <AllowStartOnDemand>true</AllowStartOnDemand>
    <Enabled>true</Enabled>
    <Hidden>false</Hidden>
    <RunOnlyIfIdle>false</RunOnlyIfIdle>
    <WakeToRun>false</WakeToRun>
    <ExecutionTimeLimit>PT30M</ExecutionTimeLimit>
    <Priority>7</Priority>
  </Settings>
  <Actions Context="Author">
    <Exec>
      <Command>$py</Command>
      <Arguments>"$root\credit.py" checkin</Arguments>
      <WorkingDirectory>$root</WorkingDirectory>
    </Exec>
  </Actions>
</Task>
"@

$out = "script started; python=$py`n"
[System.IO.File]::WriteAllText("$root\logs\_task_xml.txt", $xml)
try {
    # IMPORTANT: Register-ScheduledTask -Xml -Force does NOT reliably overwrite
    # the triggers of an already-existing task (verified: it kept the old
    # 09:05/PT15M/PT3M values). Delete it first, then register fresh.
    Unregister-ScheduledTask -TaskName "agent-credit-checkin" -Confirm:$false -ErrorAction SilentlyContinue | Out-Null
    Start-Sleep -Seconds 1
    Register-ScheduledTask -TaskName "agent-credit-checkin" -Xml $xml -Force | Out-Null
    $t = Get-ScheduledTask -TaskName "agent-credit-checkin"
    $out += "REGISTERED agent-credit-checkin`n"
    $out += "  state:  " + $t.State + "`n"
    foreach ($tr in $t.Triggers) {
        $extra = ""
        if ($tr.CimClass.CimClassName -eq "MSFT_TaskLogonTrigger") { $extra = " delay=" + $tr.Delay }
        if ($tr.CimClass.CimClassName -eq "MSFT_TaskTimeTrigger") { $extra = " start=" + $tr.StartBoundary + " end=" + $tr.EndBoundary }
        if ($tr.CimClass.CimClassName -eq "MSFT_TaskDailyTrigger" -or $tr.CimClass.CimClassName -eq "MSFT_TaskCalendarTrigger") { $extra = " start=" + $tr.StartBoundary + " randomDelay=" + $tr.RandomDelay }
        $out += "  trigger: " + $tr.CimClass.CimClassName + $extra + "`n"
    }
    $out += "  RunLevel: " + $t.Principal.RunLevel + " / LogonType: " + $t.Principal.LogonType + "`n"
    $info = Get-ScheduledTaskInfo -TaskName "agent-credit-checkin" -ErrorAction SilentlyContinue
    if ($info) { $out += "  NextRun: " + $info.NextRunTime + "`n" }
} catch {
    $out += "ERROR: " + $_.Exception.Message + "`n"
}

[System.IO.File]::WriteAllText("$root\logs\_register_task_out.txt", $out)
Write-Output $out
