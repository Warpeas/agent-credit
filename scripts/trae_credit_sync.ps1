# Trae 积分余额/过期时间自动同步：签到后把最新明细登记进台账。
#
# 流程（2026-11-21 适配 Trae CN 3.4.20：dataFolderName .trae→.trae-cn、裸启动
# 进项目选择欢迎页、Agent(SOLO) 主窗不再必然出现——三档降级找 dump 通道）：
#   ① 有 Agent 窗（旧版 SOLO）：发 Ctrl+Shift+N 开 IDE 窗（旧路线）
#   ② 无 Agent 窗但有其他有标题主窗（欢迎页/IDE 窗，均加载扩展宿主）：
#      同样发键开新 IDE 窗（或聚焦触发 focus dump）
#   ③ 一个窗都没有：`exe <agent-credit 路径>` 带项目直接启动——IDE 窗直出且
#      加载用户扩展（装在 ~/.trae-cn/extensions），startup 15s 自动 dump
#      （fix4 2026-11-21 实测 dump_fresh + record exit=0）
#   之后统一：等 logs/trae_credit_detail.json 出现新鲜 dump（startup 15s / focus 触发）
#   → trae_credit_detail.py --record 走标准对账登记 → 关掉本次拉开的窗口/实例
#
# 运行环境：每日计划任务 agent-credit-checkin 的第二个 action（HighestAvailable +
# InteractiveToken），或手动经 _task_trae_credit_sync.ps1 一次性任务跑。
# 结果落 logs/trae_credit_sync_result.json；过程日志追加 logs\_trae_credit_sync.log。

param(
    [int]$OpenWaitSec = 60,     # 等 IDE 窗口出现
    [int]$DumpWaitSec = 150,    # 等新鲜 dump
    # 2026-10-29：签到流程内部调用时传本开关——只负责把 dump 拉新鲜，
    # 台账登记交给 checkin 末尾的 sync 统一做，避免两个进程同时写 ledger.json
    # （checkin 内存里的 data 最后会整体落盘，会盖掉这边的写入）。
    [switch]$NoRecord
)

$ErrorActionPreference = "Continue"
$root  = Split-Path -Parent $PSScriptRoot
$dump  = Join-Path $root "logs\trae_credit_detail.json"
$logF  = Join-Path $root "logs\_trae_credit_sync.log"
$resF  = Join-Path $root "logs\trae_credit_sync_result.json"
$start = Get-Date

function Log([string]$m) {
    $line = (Get-Date -Format "yyyy-MM-dd HH:mm:ss") + " " + $m
    Add-Content -Path $logF -Value $line -Encoding UTF8
}

Add-Type -ReferencedAssemblies System.Windows.Forms -TypeDefinition @"
using System;
using System.Text;
using System.Collections.Generic;
using System.Runtime.InteropServices;
public class TraeWin {
    [DllImport("user32.dll")] static extern bool EnumWindows(EnumProc cb, IntPtr lp);
    delegate bool EnumProc(IntPtr h, IntPtr l);
    [DllImport("user32.dll")] static extern uint GetWindowThreadProcessId(IntPtr h, out uint pid);
    [DllImport("user32.dll")] static extern bool IsWindowVisible(IntPtr h);
    [DllImport("user32.dll")] static extern int GetWindowText(IntPtr h, StringBuilder sb, int n);
    [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr h);
    [DllImport("user32.dll")] public static extern bool ShowWindow(IntPtr h, int cmd);
    [DllImport("user32.dll")] public static extern bool PostMessage(IntPtr h, uint msg, IntPtr w, IntPtr l);
    [DllImport("user32.dll")] static extern bool IsWindow(IntPtr h);
    [DllImport("user32.dll")] static extern IntPtr GetForegroundWindow();
    [DllImport("user32.dll")] static extern void keybd_event(byte vk, byte scan, uint flags, UIntPtr extra);

    public class Info { public IntPtr H; public string Title; }

    public static List<Info> WindowsOf(uint targetPid) {
        var list = new List<Info>();
        EnumWindows((h, l) => {
            uint pid; GetWindowThreadProcessId(h, out pid);
            if (pid == targetPid && IsWindowVisible(h)) {
                var sb = new StringBuilder(512);
                GetWindowText(h, sb, 512);
                var t = sb.ToString();
                if (t.Length > 0) list.Add(new Info { H = h, Title = t });
            }
            return true;
        }, IntPtr.Zero);
        return list;
    }
    public static bool Alive(IntPtr h) { return IsWindow(h); }
    // 2026-10-22：SendKeys 是全桌面注入，不认目标窗口。签到刚结束时 Qoder 仍在前台，
    // 直接 SetForegroundWindow 又会被 Windows foreground-lock 静默拒绝，第一次
    // Ctrl+Shift+N 就落进 Qoder，开出多余窗口（Qoder 的 Ctrl+Shift+N 也是新建窗口）。
    // 必须像 ui_claim_qodercn.ps1 一样先用 Alt 解前台锁并核对 GetForegroundWindow，
    // 没拿到前台就不发键，宁可重试也不能把快捷键送进别的 App。
    public static bool EnsureForeground(IntPtr h) {
        keybd_event(0x12, 0, 0, UIntPtr.Zero);   // Alt down
        keybd_event(0x12, 0, 2, UIntPtr.Zero);   // Alt up
        System.Threading.Thread.Sleep(40);
        ShowWindow(h, 9);                        // SW_RESTORE
        SetForegroundWindow(h);
        System.Threading.Thread.Sleep(300);
        return GetForegroundWindow() == h;
    }
}
"@

function Get-TraePids {
    (Get-Process "Trae CN" -ErrorAction SilentlyContinue | Select-Object -ExpandProperty Id)
}

function Get-AllTraeWindows {
    $wins = @()
    foreach ($procId in (Get-TraePids)) {
        foreach ($w in [TraeWin]::WindowsOf([uint32]$procId)) { $wins += $w }
    }
    $wins
}

$result = [ordered]@{ ts = $start.ToString("s"); steps = @(); ok = $false; error = "" }
try {
    $before = @{}
    foreach ($w in (Get-AllTraeWindows)) { $before[$w.H.ToInt64()] = $true }
    $result.steps += "windows_before=$($before.Count)"
    Log "sync start; trae windows before=$($before.Count)"

    # 1+2a. 找「可触发 dump 的目标窗」，三档降级（2026-11-21 适配 3.4.20）：
    #       ① Agent 窗（<=3.4.x SOLO 主窗标题）→ 发 Ctrl+Shift+N 开 IDE 窗（旧路线）
    #       ② 其他有标题主窗（3.4.20 裸启动常只出项目选择欢迎页/已开 IDE 窗，
    #          二者都加载扩展宿主）→ 聚焦触发 focus dump
    #       ③ 一个窗都没有（客户端未运行/只剩无窗 headless）→ 带 agent-credit
    #          项目路径直接启动——3.4.20 的 dataFolderName 已改 .trae-cn、扩展装在
    #          ~/.trae-cn/extensions，`exe <路径>` 直接开出加载用户扩展的 IDE 窗，
    #          扩展 startup 15s 自动 dump，无需发键（fix4 2026-11-21 实测
    #          dump_fresh + record exit=0）
    $ideHwnd = [IntPtr]::Zero
    $launchedBySync = $false
    $target = Get-AllTraeWindows | Where-Object { $_.Title -eq "Agent" } | Select-Object -First 1
    if (-not $target) {
        $target = Get-AllTraeWindows | Where-Object { $_.Title -ne "Trae CN" } | Select-Object -First 1
    }
    if ($target) {
        # 2026-10-22：发键前必须核对前台。SetForegroundWindow 失败时 SendKeys 会落进
        # 当时前台的 Qoder，Ctrl+Shift+N 在那边的语义是新建窗口——当天 00:08:42 就是
        # 这么开出一个多余 Qoder 窗口的。拿不到前台就跳过本轮，绝不盲发。
        # （00:03 实测：锁屏/焦点未到位时单次 SendKeys 会被吞掉，故重试最多 3 轮）
        for ($attempt = 1; $attempt -le 3 -and $ideHwnd -eq [IntPtr]::Zero; $attempt++) {
            if (-not [TraeWin]::EnsureForeground($target.H)) {
                Log "focus check failed; skip Ctrl+Shift+N (attempt $attempt)"
                $result.steps += "focus_failed#$attempt"
                Start-Sleep -Seconds 2
                continue
            }
            Start-Sleep -Milliseconds 800
            [System.Windows.Forms.SendKeys]::SendWait("^+n")
            $result.steps += "sent_ctrl_shift_n#$attempt"
            Log ("sent Ctrl+Shift+N to '" + $target.Title + "' window (attempt $attempt)")
            $t0 = Get-Date
            while ($ideHwnd -eq [IntPtr]::Zero -and ((Get-Date) - $t0).TotalSeconds -lt 20) {
                Start-Sleep -Seconds 2
                foreach ($w in (Get-AllTraeWindows)) {
                    if (-not $before.ContainsKey($w.H.ToInt64())) { $ideHwnd = $w.H; break }
                }
            }
        }
        if ($ideHwnd -ne [IntPtr]::Zero) {
            $result.steps += "ide_window_opened"
            Log "new IDE window hwnd=$ideHwnd"
        }
    }
    if ($ideHwnd -eq [IntPtr]::Zero) {
        # 2b. 复用既有非 Agent/Trae CN 窗口（用户之前开的 IDE 窗口，扩展 v0.0.2 聚焦即 dump）。
        #     3.4.20 的欢迎页标题 "TRAE CN" 会被 -ne "Trae CN"（大小写不敏感）排除，
        #     folder-arg 开出的 IDE 窗标题是 "agent-credit - TRAE CN"，不受影响。
        $existing = Get-AllTraeWindows | Where-Object { $_.Title -ne "Agent" -and $_.Title -ne "Trae CN" } | Select-Object -First 1
        if ($existing) {
            $ideHwnd = $existing.H
            $result.steps += "reuse_existing_ide"
            Log "reuse existing IDE-like window title=$($existing.Title)"
        }
    }
    if ($ideHwnd -eq [IntPtr]::Zero -and -not $target) {
        # 2d. 带项目路径启动（3.4.20 路线）：跳过欢迎页，IDE 窗直出且加载扩展
        $exe = Join-Path $env:LOCALAPPDATA "Programs\Trae CN\Trae CN.exe"
        if (-not (Test-Path $exe)) { $exe = Join-Path $env:USERPROFILE "AppData\Local\Programs\Trae CN\Trae CN.exe" }
        if (Test-Path $exe) {
            Start-Process -FilePath $exe -ArgumentList ('"' + $root + '"')
            $launchedBySync = $true
            $result.steps += "launched_with_repo_folder"
            Log ("launched Trae with repo folder: " + $root)
            $t0 = Get-Date
            while ($ideHwnd -eq [IntPtr]::Zero -and ((Get-Date) - $t0).TotalSeconds -lt 60) {
                Start-Sleep -Seconds 3
                $w = Get-AllTraeWindows | Where-Object { $_.Title -ne "Trae CN" } | Select-Object -First 1
                if ($w) { $ideHwnd = $w.H }
            }
            if ($ideHwnd -ne [IntPtr]::Zero) {
                $result.steps += "ide_window_opened"
                Log "new IDE window hwnd=$ideHwnd (folder-arg launch; startup dump in ~15s, no keystroke needed)"
            }
        } else {
            Log ("exe missing, cannot folder-arg launch: " + $exe)
            $result.steps += "exe_missing"
        }
    }

    # 2c. 聚焦 IDE 窗口触发 focus dump，再等文件变新
    $fresh = $false
    if ($ideHwnd -ne [IntPtr]::Zero) {
        [TraeWin]::ShowWindow($ideHwnd, 9) | Out-Null
        [TraeWin]::SetForegroundWindow($ideHwnd) | Out-Null
        Start-Sleep -Milliseconds 500
        $t0 = Get-Date
        while (((Get-Date) - $t0).TotalSeconds -lt $DumpWaitSec) {
            if ((Test-Path $dump) -and ((Get-Item $dump).LastWriteTime -gt $start)) { $fresh = $true; break }
            Start-Sleep -Seconds 3
        }
        $result.steps += $(if ($fresh) { "dump_fresh" } else { "dump_timeout" })
        Log "dump freshness: $fresh"
    } else {
        $result.steps += "no_ide_window"
    }

    # 3. 解析 + 登记（写账只走 credit.py CLI）
    #    只有新鲜 dump 才登记——2026-10-20 00:03 实测：IDE 窗没开成时拿昨天
    #    的旧 dump set-balance，会把 claim 后的真实余额覆盖成旧值。
    $py = "$env:USERPROFILE\.workbuddy\binaries\python\versions\3.13.12\python.exe"
    if (-not (Test-Path $py)) { $py = (Get-Command python).Source }
    [Console]::OutputEncoding = [Text.Encoding]::UTF8
    $env:PYTHONIOENCODING = "utf-8"

    # 2d. 逐包明细（2026-11-10）：趁刚拉新的 IDE 窗口还开着，让客户端自己打开
    #     「设置→用量管理」，滚动截图 + OCR 出当天的 logs/trae_usage.json。
    #     结构化通道只给聚合值，逐包只能这么读。失败绝不影响签到/对账：
    #     trae_credits 的日期闸门会让对账自动退回聚合口径，这里只留原因。
    if ($fresh -and $ideHwnd -ne [IntPtr]::Zero -and [TraeWin]::Alive($ideHwnd)) {
        $ocrOut = & $py -u "$root\scripts\trae_usage_collect.py" `
            --hwnd $ideHwnd.ToInt64() --out "$root\logs\trae_usage.json" 2>&1 | Out-String
        $ocrExit = $LASTEXITCODE
        $ocrTail = (($ocrOut -split "`r?`n") | Where-Object { $_.Trim() } | Select-Object -Last 1)
        if ($ocrExit -eq 0) {
            $result.steps += "usage_ocr_ok"
            Log "usage ocr ok: $ocrTail"
        } else {
            $result.steps += "usage_ocr_failed(exit=$ocrExit)"
            Log "usage ocr failed exit=${ocrExit}: $(($ocrOut -replace "`r?`n", " | ").Trim())"
        }
    } else {
        $result.steps += "usage_ocr_skipped"
        Log "usage ocr skipped: fresh=$fresh hwnd=$ideHwnd"
    }

    if ($fresh -and $NoRecord) {
        # 由签到流程内部调用：dump 已新鲜，登记留给 checkin 末尾的 sync（同一进程、
        # 同一份内存账本），这里绝不另开一条写账路径。
        $result.ok = $true
        $result.steps += "record_skipped_no_record"
        Log "record skipped (-NoRecord; 由 checkin 末尾的 sync 统一登记)"
    } elseif ($fresh) {
        $out = & $py -u "$root\scripts\trae_credit_detail.py" --record 2>&1 | Out-String
        $recordExit = $LASTEXITCODE
        Log "parser output: $out"
        $result.steps += "record_ran(exit=$recordExit)"
        # 登记走标准对账通道（credit.py sync --only trae），自带新鲜度闸门；
        # 退出码非 0 说明登记没生效，如实上报，别把 ok 写成 true。
        if ($recordExit -eq 0) {
            $result.ok = $true
        } else {
            $result.error = "record failed exit=$recordExit"
            Log "record failed exit=$recordExit"
        }
    } else {
        $result.error = "no fresh dump (session locked or IDE window failed)"
        Log "skip record: no fresh dump"
        $result.steps += "skip_record_stale"
    }

    # 4. 关掉本次拉开的 IDE 窗口；launchedBySync 时整个实例都是本次拉的，全部关闭
    if ($launchedBySync) {
        foreach ($h in (Get-AllTraeWindows)) {
            [TraeWin]::PostMessage($h.H, 0x10, [IntPtr]::Zero, [IntPtr]::Zero) | Out-Null  # WM_CLOSE
        }
        $result.steps += "launched_client_closed"
        Log "WM_CLOSE sent to all Trae windows (instance launched by sync)"
    } elseif ($result.steps -contains "ide_window_opened" -and $ideHwnd -ne [IntPtr]::Zero -and [TraeWin]::Alive($ideHwnd)) {
        [TraeWin]::PostMessage($ideHwnd, 0x10, [IntPtr]::Zero, [IntPtr]::Zero) | Out-Null  # WM_CLOSE
        $result.steps += "ide_window_closed"
        Log "closed opened IDE window"
    }
} catch {
    $result.error = $_.Exception.Message
    Log "FATAL: $($_.Exception.Message)"
}

$result.elapsedSec = [int]((Get-Date) - $start).TotalSeconds
[IO.File]::WriteAllText($resF, ($result | ConvertTo-Json -Compress))
Log "sync done ok=$($result.ok) steps=$($result.steps -join ',')"
Write-Output ($result | ConvertTo-Json -Compress)
