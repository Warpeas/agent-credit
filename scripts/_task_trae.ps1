# One-shot: launch Trae NON-elevated via scheduled task, then wait for its main window.
# Same trick as _task_lobsterai.ps1: the sandboxed session cannot Start-Process a
# GUI client (procs stay 0), but a RunLevel=Limited + LogonType=Interactive task
# runs inside the real desktop session and can. Registered on demand.
#
# The task's -UserId must be the INTERACTIVE desktop user (not SYSTEM): a GUI
# client launched as SYSTEM has no visible desktop, so the window never appears.
# Derived from the current identity rather than hardcoded, to stay portable.
#
# Usage (from PowerShell tool):
#   powershell -ExecutionPolicy Bypass -File scripts\_task_trae.ps1
#   ... -ProcessName "Trae CN"     # 2026-10-11: 默认已改成合并后的客户端

param(
    [string]$ProcessName = "Trae CN",
    # 调用方（agent_credit/apps.find_exe）已经探过真实路径，显式传进来最稳：
    # 2026-10-12 00:01 那轮 $exe 在计划任务上下文里推导成了空值，客户端根本没拉起，
    # 白等 90s 后报 pending。显式路径优先，推导只作兜底。
    [string]$ExePath = "",
    [switch]$WaitReady
)

$root = Split-Path -Parent $PSScriptRoot
$name = "agent-credit-trae-once"

# 诊断：计划任务进程的环境变量不一定完整。失败时没有这几行就只能看到一句
# 「参数是空值」，看不出到底缺哪个变量。
Write-Host ("env: LOCALAPPDATA=" + $env:LOCALAPPDATA + " USERPROFILE=" + $env:USERPROFILE)

# 2026-10-11：TRAE SOLO CN 已合并进 Trae CN，旧目录只剩 debug.log。
# 统一按「<ProcessName>\<ProcessName>.exe」推导，与 _task_trae_claim.ps1 一致。
$exe = $ExePath
if (-not $exe) { $exe = Join-Path $env:LOCALAPPDATA "Programs\$ProcessName\$ProcessName.exe" }
if (-not $exe -or -not (Test-Path $exe)) {
    # LOCALAPPDATA 缺失/指向沙箱时退回 USERPROFILE 拼一次
    $exe = Join-Path $env:USERPROFILE "AppData\Local\Programs\$ProcessName\$ProcessName.exe"
}
if (-not $exe -or -not (Test-Path $exe)) {
    Write-Host "EXE MISSING: exe=[$exe] proc=[$ProcessName] exepath=[$ExePath]"
    exit 1
}
Write-Host "exe=$exe"

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