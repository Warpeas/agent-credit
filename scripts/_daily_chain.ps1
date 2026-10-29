# 每日任务 agent-credit-checkin 的唯一 action 入口。
# 为什么需要它：本机 Register-ScheduledTask -Xml 会静默丢掉第二个 <Exec>
# （与丢 TimeTrigger 同类怪癖，2026-10-19 实测），所以多个步骤包进一个脚本：
#   1. python credit.py checkin      —— 各家签到（Trae 走计划任务 OCR 链路）
#                                      末尾自动对账（WorkBuddy 逐条 / MonkeyCode 总量）并刷新积分看板
#                                      可见控制台先弹启动闸门：Y/Enter 立即开始，N/Esc 跳过今天的
#                                      UI 组，15s 无输入自动开始（无人值守不弹、不等空闲）
#   2. credit.py sync --only trae    —— checkin 领取成功时已顺带同步过明细；只有
#      trae_credit_sync.ps1           dump 不是今天的、且本轮不是 pending/failed 才补开 IDE 窗
#   3. credit.py sync --only qodercn —— 同理；本轮 pending/failed 不补点（同轮二次尝试只会
#      ui_claim_qodercn.ps1 -Usage    再白等一次窗口，2026-10-30 00:06 实况）
#   4. python credit.py board        —— 只有 2/3 的补拉真的跑过才再刷一次；checkin 末尾已刷过
# 补不补由 logs/checkin_last.json 决定（checkin 每轮都会写本轮各账户状态）。
#
# -Unattended：计划任务的 action 显式传入时直接按无人值守处理；
# 老任务/手动触发没有这个开关时，再看父进程是不是 Task Scheduler（svchost）。
# 不靠「控制台窗口是否可见」猜：任务里的可见性判定不可靠，2026-10-29 00:34
# 那轮就被误判成可见，白等 15 秒。
param([switch]$Unattended)

$ErrorActionPreference = "Continue"
$root = Split-Path -Parent $PSScriptRoot

$isTaskHost = $false
$parentName = ""
try {
    $self = Get-CimInstance Win32_Process -Filter "ProcessId=$PID" -ErrorAction Stop
    if ($self -and $self.ParentProcessId) {
        $parent = Get-CimInstance Win32_Process -Filter ("ProcessId=" + $self.ParentProcessId) -ErrorAction SilentlyContinue
        if ($parent) {
            $parentName = [string]$parent.Name
            if ($parentName -match '^(svchost|taskhostw|taskeng)\.exe$') { $isTaskHost = $true }
        }
    }
} catch { }
$unattended = ($Unattended -or $isTaskHost)
if ($unattended) { $env:AGENT_CREDIT_GATE_UNATTENDED = "1" }
try {
    Add-Content -Path (Join-Path $root "logs\_chain_env.txt") -Encoding UTF8 -Value (
        (Get-Date -Format "yyyy-MM-dd HH:mm:ss") + " pid=$PID parent='$parentName' " +
        "flag=$Unattended taskhost=$isTaskHost unattended=$unattended " +
        "cmd=[" + [Environment]::CommandLine + "]")
} catch { }

$py = "$env:USERPROFILE\.workbuddy\binaries\python\versions\3.13.12\python.exe"
if (-not (Test-Path $py)) { $py = (Get-Command python).Source }

# ---- 防撞锁 ----------------------------------------------------------------
# 2026-10-29 的漏签：前一条链路 23:58 启动、跨过零点跑到 00:03，计划任务
# IgnoreNew 把 00:00:45 的触发直接丢了。现在计划任务改 Queue（见
# register-daily-task.ps1），这里再用一把锁兜住手动/重叠触发：
# 整条链持有 logs\checkin.lock（FileShare.None），Python 端 credit checkin 抢同一把。
# 进程被结束/崩溃时句柄自动释放，不会有需要人工删的残留锁。
$lockPath = Join-Path $root "logs\checkin.lock"
New-Item -ItemType Directory -Force -Path (Split-Path $lockPath) | Out-Null
$lockStream = $null
$lockDeadline = (Get-Date).AddMinutes(20)
$lockWaitLogged = $false
while ($null -eq $lockStream) {
    try {
        $lockStream = [System.IO.File]::Open(
            $lockPath,
            [System.IO.FileMode]::OpenOrCreate,
            [System.IO.FileAccess]::ReadWrite,
            [System.IO.FileShare]::None)
    } catch {
        if ((Get-Date) -ge $lockDeadline) {
            Write-Host "另一个签到链路已持有 logs\checkin.lock 超过 20 分钟，本次放弃（下次触发照常）"
            exit 0
        }
        if (-not $lockWaitLogged) {
            Write-Host "另一个签到链路正在运行，等它结束后自动继续（最多 20 分钟）…"
            $lockWaitLogged = $true
        }
        Start-Sleep -Seconds 5
    }
}
# 子进程（credit checkin）看到这个变量就不再抢锁，否则会自己把自己锁在门外。
$env:AGENT_CREDIT_LOCK_HELD = "1"

try {
    & $py -u "$root\credit.py" checkin

    # 启动闸门（agent_credit/gate.py）：主人按 N/Esc 就跳过今天会弹窗的后续步骤，
    # 别签到都拒了还去开 IDE 窗口 / 搬 Qoder。date + at 都要对得上（60 分钟内），
    # 防止 checkin 没跑到闸门时读到昨天/今早的旧结论。
    $skipUi = $false
    $gateFile = Join-Path $root "logs\gate_last.json"
    if (Test-Path $gateFile) {
        try {
            $gate = Get-Content -Raw -Encoding UTF8 $gateFile | ConvertFrom-Json
            $gateAt = [datetime]::ParseExact($gate.at, "yyyy-MM-dd HH:mm:ss", $null)
            $fresh = ((Get-Date) - $gateAt).TotalMinutes -lt 60
            if ($gate.action -eq "skip_ui" -and
                $gate.date -eq (Get-Date -Format "yyyy-MM-dd") -and $fresh) {
                $skipUi = $true
            }
        } catch { }
    }
    if ($skipUi) {
        Write-Host "启动闸门：主人按 N 跳过了今天的 UI 签到，跳过 Trae 明细同步与 Qoder 用量刷新。"
        exit 0
    }

    # 2026-10-30：读 checkin 本轮结果快照。pending/failed 说明领取没成，1 分钟后再开
    # 一次 UI/IDE 拉明细没有任何收益——10-30 00:06 那轮 Qoder 刚报 notfound，这里又跑
    # 一遍 -Usage 白等 90s。skipped（今日已签）与 ok 都允许补拉：已签日也可能只是
    # 台账里的用量记录过期，补点一次能自愈。没有记录（--only 单账户跑）按允许处理。
    $resFile = Join-Path $root "logs\checkin_last.json"
    $statusOf = @{}
    if (Test-Path $resFile) {
        try {
            $snap = Get-Content -Raw -Encoding UTF8 $resFile | ConvertFrom-Json
            if ($snap.accounts) {
                foreach ($p in $snap.accounts.PSObject.Properties) {
                    $statusOf[$p.Name] = [string]$p.Value.status
                }
            }
        } catch { }
    }
    $fallbackRan = $false

    # Trae：checkin 里「领取 + 明细同步」已经合并做过（领取成功后趁客户端还开着开
    # IDE 窗、等扩展 dump、登记），这里先对账；只有 dump 不是今天的才补开一次 IDE 窗。
    & $py -u "$root\credit.py" sync --only trae
    if ($LASTEXITCODE -ne 0) {
        if ($statusOf.ContainsKey('trae') -and ($statusOf['trae'] -eq 'pending' -or $statusOf['trae'] -eq 'failed')) {
            Write-Host ("Trae 本轮状态 " + $statusOf['trae'] + "，不补开 IDE 窗（拉明细不会改变领取结果）")
        } else {
            $fallbackRan = $true
            & powershell.exe -NoProfile -ExecutionPolicy Bypass -File "$root\scripts\trae_credit_sync.ps1"
            & $py -u "$root\credit.py" sync --only trae
        }
    }

    # Qoder CN：同理，领取成功后已经在同一个客户端里点开过「我的用量」，先对账；
    # 记录不新鲜才补点一次（这次不再等空闲，启动闸门早就拿到授权了）。
    & $py -u "$root\credit.py" sync --only qodercn
    if ($LASTEXITCODE -ne 0) {
        if ($statusOf.ContainsKey('qodercn') -and ($statusOf['qodercn'] -eq 'pending' -or $statusOf['qodercn'] -eq 'failed')) {
            Write-Host ("Qoder CN 本轮状态 " + $statusOf['qodercn'] + "，不补点用量（避免同轮二次白等）")
        } else {
            $fallbackRan = $true
            & powershell.exe -NoProfile -ExecutionPolicy Bypass -File "$root\scripts\ui_claim_qodercn.ps1" `
                -Usage -IdleWaitSec 0 -WindowWaitSec 20 -ExePath "$env:LOCALAPPDATA\Programs\Qoder CN\Qoder CN.exe"
            & $py -u "$root\credit.py" sync --only qodercn
        }
    }

    # 看板：checkin 末尾已经刷过一次（含上面同样的对账数据）。只有补拉真的跑过、
    # 数据可能变了，才再刷一次。
    if ($fallbackRan) { & $py -u "$root\credit.py" board }
} finally {
    if ($lockStream) {
        $lockStream.Close()
        $lockStream = $null
    }
}
