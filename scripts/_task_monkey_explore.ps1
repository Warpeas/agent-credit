# One-shot: run MonkeyCode explore NON-elevated via scheduled task.
# Same trick as _task_traework.ps1 - the sandboxed session cannot start GUI apps.
param([int]$Steps = 2)
$root = Split-Path -Parent $PSScriptRoot
$name = "agent-credit-monkey-explore"
# 不硬编码本机路径：优先 PATH 里的 python，回退到 WorkBuddy 托管运行时
# （仓库是 public 的，写死 C:\Users\<name>\... 既不通用也泄露本机信息）。
$py = (Get-Command python.exe -ErrorAction SilentlyContinue).Source
if (-not $py -or -not (Test-Path $py)) {
    $py = Join-Path $env:USERPROFILE '.workbuddy\binaries\python\versions\3.13.12\python.exe'
}
if (-not (Test-Path $py)) { Write-Host "python.exe not found"; exit 1 }
$script = Join-Path $root "scripts\ui_claim_monkeycode.py"
$me = [Security.Principal.WindowsIdentity]::GetCurrent().Name

$action = New-ScheduledTaskAction -Execute $py `
    -Argument ('-X utf8 "' + $script + '" --explore --steps ' + $Steps) `
    -WorkingDirectory $root
$principal = New-ScheduledTaskPrincipal -UserId $me -LogonType Interactive -RunLevel Limited
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 5) -MultipleInstances IgnoreNew

Unregister-ScheduledTask -TaskName $name -Confirm:$false -ErrorAction SilentlyContinue
Register-ScheduledTask -TaskName $name -Action $action -Principal $principal -Settings $settings | Out-Null
Start-ScheduledTask -TaskName $name
Write-Host "started $name"
