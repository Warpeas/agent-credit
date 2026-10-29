# Qoder CN 每日签到活动 OCR 领取脚本（锚点定位版，不用绝对坐标）。
# 活动是服务端下发进 webview 的「专属活动权益 / 立即查收 / 每天领 100 Credits」弹窗，
# UIA 看不见，只能截图 + OCR + OS 级点击。非提权（Qoder 是普通中完整性安装）。
#
# 为什么全用锚点、不用写死坐标（2026-10-13 主人要求 + 实测）：
#   本机在 200% 缩放下，且窗口会在「最大化 3866x2090 / 还原 2196x1140」之间变，
#   底栏是「左/底锚定」的，绝对像素会随分辨率/DPI/窗口态漂移。每个目标都在本次截图里现找：
#   文字锚点用 OCR 词框，无文字目标用像素/几何特征。
#
# 领取路径（2026-10-16 随客户端改版更新）：
#   情况一：客户端启动时自动弹出活动窗 -> 直接点黑药丸「领取」（最稳，保留）。
#   情况二：弹窗不在 -> 点左下角「用户名」展开账户菜单 -> 点菜单里的「权益中心」
#           -> 弹出同一个活动浮窗 -> 点黑药丸「领取」。
#   2026-10-20 修：情况二的用户名锚点旧按「cy 最靠下」取词，与同行的工作区名
#   （agent-c..）只差 ~4px，首帧渲染动画 / OCR 抖动时会选中工作区名——点它开不了
#   账户菜单，当天定时轮直接 pending（且旧逻辑两轮点击复用同一锚点不重解析）。
#   现改为「底栏行内最左多字词」+ 每轮重抓帧重解析 + 多候选逐一点击。
#   旧路径「用量仪表 -> 我的用量小窗 -> 礼盒图标」已废：2026-10-16 改版后小窗里
#   只剩绿色「查看详情」，礼盒入口被移除（主人确认 + 实测 08:45 旧逻辑把小窗里的
#   别的暗簇误判成礼盒乱点）。
#
# 三条实测坑：
#   1) DPI：进程先 SetProcessDpiAwareness(2)，否则 GetWindowRect/CopyFromScreen/SetCursorPos
#      三套坐标系混用，坐标差 2 倍会点到别的窗口。
#   2) 抓图：非屏外模式仍用 CopyFromScreen(窗口矩形)；屏外条带模式用
#      PrintWindow(PW_RENDERFULLCONTENT=2)。2026-10-22 实测 PrintWindow 能抓到
#      活动弹窗叠加层，但前提是窗口在屏内有一条可见边——整窗屏外/最大化屏外时
#      Chromium 停止合成，抓到的全是空白帧（见文件末尾方案甲说明）。
#   3) 非屏外模式每次点击前抢前台并核对 GetForegroundWindow 确属 Qoder，否则宁可
#      pending 也不点，免得把点击送进重叠的其它 App；屏外模式合成消息零暴露，
#      「领取」走 BringBack 真实点击，点完立刻回条带。
#
# 2026-10-22 方案甲（与 Trae/AutoClaw 同套语义）：识别走 PrintWindow（实测对屏外
# 窗口和活动弹窗叠加层都有效），窗口整窗停到所有屏幕左界外；点击分三级：
#   合成消息（菜单类，零暴露）→ UIA（Qoder 主窗口 UIA 树为空，跳过）
#   → 移回屏内 SendInput 真实点击（光标/前台保存恢复，暴露 ~0.5s）后立刻移回屏外。
# 「领取」按钮实测不吃合成消息（关闭 X 都点不动），所以直接跳 BringBack。
# 空闲闸门：先等用户键鼠空闲 IdleThresholdSec 秒（最多 IdleWaitSec 秒），避免正在
# 用 Qoder 时把窗口搬走。Python 侧会在冷启动/调用前先等一次，届时传 -IdleWaitSec 0。
# 传 -Offscreen:$false 退回旧的抢前台 + CopyFromScreen 行为。
param(
    [switch]$DryRun,
    [switch]$Explore,
    [switch]$Usage,
    [string]$OutFile,
    [string]$ProcessName = 'Qoder CN',
    [string]$ExePath = '',
    [bool]$Offscreen = $true,
    [int]$IdleWaitSec = 120,
    [int]$IdleThresholdSec = 60,
    [int]$OffscreenStripPx = 48,
    # Python 侧已确认主窗口存在时传小值（20s），避免两边各等 90s。
    [int]$WindowWaitSec = 90
)
$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$root = Split-Path -Parent $PSScriptRoot
$logPath = "$root\logs\ps1_qodercn.log"
$shotPath = "$root\logs\_qoder_shot.png"
function Log($m){ $s=(Get-Date -Format "HH:mm:ss")+" "+$m; try{[System.IO.File]::AppendAllText($logPath,$s+"`n",(New-Object System.Text.UTF8Encoding($false)))}catch{}; [Console]::Error.WriteLine($s) }
trap {
    try { if ($script:OriginalRect) { Restore-OriginalRect } } catch {}
    try { $m="FATAL: "+$_.Exception.Message+" @ "+$_.InvocationInfo.PositionMessage; Log $m
        if ($OutFile) { [System.IO.File]::WriteAllText($OutFile,(ConvertTo-Json -Compress @{status='failed';detail=$m})) } } catch {}
    break
}
Add-Type -AssemblyName System.Drawing
Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Runtime.WindowsRuntime
$sig = @"
using System;
using System.Threading;
using System.Runtime.InteropServices;
public static class Q {
  [StructLayout(LayoutKind.Sequential)] public struct R { public int L,T,Rr,B; }
  [StructLayout(LayoutKind.Sequential)] public struct P { public int X,Y; }
  [StructLayout(LayoutKind.Sequential)] public struct LI { public uint cbSize; public uint dwTime; }
  [StructLayout(LayoutKind.Sequential)] public struct MOUSEINPUT { public int dx; public int dy; public uint mouseData; public uint dwFlags; public uint time; public UIntPtr dwExtraInfo; }
  [StructLayout(LayoutKind.Explicit)] public struct INPUT { [FieldOffset(0)] public uint type; [FieldOffset(8)] public MOUSEINPUT mi; }
  [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr h);
  [DllImport("user32.dll")] public static extern bool ShowWindow(IntPtr h, int c);
  [DllImport("user32.dll")] public static extern bool GetWindowRect(IntPtr h, out R r);
  [DllImport("user32.dll")] public static extern IntPtr GetForegroundWindow();
  [DllImport("user32.dll")] public static extern bool SetCursorPos(int x, int y);
  [DllImport("user32.dll")] public static extern bool GetCursorPos(out P p);
  [DllImport("user32.dll")] public static extern uint SendInput(uint n, INPUT[] p, int cb);
  [DllImport("user32.dll")] public static extern void keybd_event(byte vk, byte scan, uint flags, UIntPtr extra);
  [DllImport("shcore.dll")] public static extern int SetProcessDpiAwareness(int a);
  // 方案甲 M1/M4：窗口屏外停放与恢复（SWP_NOACTIVATE，绝不激活）
  [DllImport("user32.dll")] public static extern bool SetWindowPos(IntPtr h, IntPtr after, int x, int y, int cx, int cy, uint flags);
  [DllImport("user32.dll")] public static extern bool IsZoomed(IntPtr h);
  [DllImport("user32.dll")] public static extern int GetSystemMetrics(int n);
  [DllImport("user32.dll")] public static extern bool PrintWindow(IntPtr h, IntPtr hdc, uint flags);
  [DllImport("user32.dll")] public static extern IntPtr WindowFromPoint(P p);
  [DllImport("user32.dll")] public static extern IntPtr GetAncestor(IntPtr h, uint flags);
  [DllImport("user32.dll")] public static extern IntPtr ChildWindowFromPointEx(IntPtr h, P p, uint flags);
  [DllImport("user32.dll")] public static extern bool ScreenToClient(IntPtr h, ref P p);
  [DllImport("user32.dll")] public static extern uint GetWindowThreadProcessId(IntPtr h, out uint pid);
  // 2026-10-29：主窗口被关到托盘（WS_VISIBLE=off）时 MainWindowHandle=0，
  // 需要自己枚举顶层窗口把它还原回来。
  public delegate bool EnumProc(IntPtr h, IntPtr l);
  [DllImport("user32.dll")] public static extern bool EnumWindows(EnumProc cb, IntPtr l);
  [DllImport("user32.dll")] public static extern bool IsWindowVisible(IntPtr h);
  // 2026-10-30：最小化到任务栏的窗口 WS_VISIBLE 还在（IsWindowVisible=true、
  // MainWindowHandle 非 0），但 GetWindowRect 给的是 -32000 哨兵 → 旧 Find-QoderWindow
  // 按 rect 丢掉、Restore-HiddenQoderWindow 又只认 WS_VISIBLE=off，两头都漏，
  // 主人明明开着却白等 90s 报 notfound。最小化态要用 IsIconic 认、用
  // GetWindowPlacement 的还原 rect（rcNormalPosition）判是不是主窗口。
  [DllImport("user32.dll")] public static extern bool IsIconic(IntPtr h);
  [StructLayout(LayoutKind.Sequential)] public struct PTp { public int X,Y; }
  [StructLayout(LayoutKind.Sequential)] public struct RECTn { public int L,T,Rr,B; }
  [StructLayout(LayoutKind.Sequential)] public struct WP { public int length; public int flags; public int showCmd; public PTp minPos; public PTp maxPos; public RECTn normal; }
  [DllImport("user32.dll")] public static extern bool GetWindowPlacement(IntPtr h, ref WP wp);
  [DllImport("user32.dll", CharSet=CharSet.Unicode)] public static extern int GetClassName(IntPtr h, System.Text.StringBuilder s, int n);
  [DllImport("user32.dll", CharSet=CharSet.Unicode)] public static extern int GetWindowTextW(IntPtr h, System.Text.StringBuilder s, int n);
  [DllImport("user32.dll")] public static extern IntPtr SendMessageTimeout(IntPtr h, uint msg, UIntPtr w, IntPtr l, uint flags, uint timeout, out IntPtr result);
  [DllImport("user32.dll")] public static extern bool GetLastInputInfo(ref LI info);
  [DllImport("kernel32.dll")] public static extern uint GetTickCount();
  // 用 SendInput 发真实点击（mouse_event 在本机对 Qoder 的 webview 落不进去，只有 SetCursorPos 的 hover 生效）
  public static int IdleMs() {
    // 距最近一次真实键鼠输入的毫秒数。点击前的「静默闸门」靠它判断主人是否在操作。
    LI li = new LI();
    li.cbSize = (uint)Marshal.SizeOf(typeof(LI));
    if (!GetLastInputInfo(ref li)) { return 1000000; }
    uint idle = unchecked(GetTickCount() - li.dwTime);
    return idle > 1000000u ? 1000000 : (int)idle;
  }
  // 2026-10-30：hover 的 120ms 里主人可能又动了鼠标；此时再按下会把点击落到他
  // 当前光标处（可能点进别的窗口）。每次按下前核对光标仍在目标点，否则放弃本次
  // 点击，由调用方重新过静默闸门后重试。
  public static bool Click(int x, int y) {
    SetCursorPos(x, y);
    Thread.Sleep(120);
    P p;
    if (!GetCursorPos(out p) || p.X != x || p.Y != y) { return false; }
    INPUT[] arr = new INPUT[1];
    arr[0].type = 0; arr[0].mi.dx = 0; arr[0].mi.dy = 0; arr[0].mi.mouseData = 0;
    arr[0].mi.dwFlags = 0x0002; arr[0].mi.time = 0; arr[0].mi.dwExtraInfo = UIntPtr.Zero; // LEFTDOWN
    SendInput(1, arr, Marshal.SizeOf(typeof(INPUT)));
    Thread.Sleep(80);
    arr[0].mi.dwFlags = 0x0004;                                                            // LEFTUP
    SendInput(1, arr, Marshal.SizeOf(typeof(INPUT)));
    return true;
  }
}
"@
Add-Type $sig
# 2026-10-30：黑药丸扫描改编译实现。原 PS 三层嵌套 GetPixel 在 3600x2090 上实测
# 130s（10-30 01:12 那轮光定位按钮就花了 ~95s）；同等判据走 LockBits 只要 25ms。
$pillSig = @"
using System;
using System.Drawing;
using System.Drawing.Imaging;
using System.Runtime.InteropServices;
public static class Pill {
  // 与旧 PS 版完全相同的判据：中央区「中性黑」高密度横条 + 上下 14px 也是黑。
  public static int[] Find(Bitmap bmp, double x0f, double x1f, double y0f, double y1f) {
    int W = bmp.Width, H = bmp.Height;
    // LockBits 只认位图自己的像素格式；截图通常是 32bppArgb，但别赌，统一转一份。
    Bitmap src = bmp;
    if (bmp.PixelFormat != PixelFormat.Format32bppArgb) {
      src = new Bitmap(W, H, PixelFormat.Format32bppArgb);
      using (Graphics g = Graphics.FromImage(src)) { g.DrawImageUnscaled(bmp, 0, 0); }
    }
    var rect = new Rectangle(0, 0, W, H);
    var data = src.LockBits(rect, ImageLockMode.ReadOnly, PixelFormat.Format32bppArgb);
    byte[] buf; int stride;
    try { stride = data.Stride; buf = new byte[stride * H]; Marshal.Copy(data.Scan0, buf, 0, buf.Length); }
    finally { src.UnlockBits(data); if (!ReferenceEquals(src, bmp)) { src.Dispose(); } }
    int x0 = (int)(W * x0f), x1 = (int)(W * x1f);
    int y0 = (int)(H * y0f), y1 = (int)(H * y1f);
    int win = 96;
    Func<int, int, bool> isBlack = (x, y) => {
      if (x < 0 || y < 0 || x >= W || y >= H) return false;
      int o = y * stride + x * 4;           // BGRA
      int b = buf[o], g = buf[o + 1], r = buf[o + 2];
      int lum = (r + g + b) / 3;
      int mx = Math.Max(r, Math.Max(g, b));
      int mn = Math.Min(r, Math.Min(g, b));
      return lum < 95 && (mx - mn) < 40;
    };
    for (int y = y0 + 20; y < y1 - 20; y += 3) {
      for (int x = x0; x < x1 - win; x += 4) {
        int nb = 0, tot = 0;
        for (int k = 0; k < win; k += 3) { tot++; if (isBlack(x + k, y)) nb++; }
        if (tot > 0 && (double)nb / tot > 0.70) {
          int cx = x + win / 2;
          if (isBlack(cx, y - 14) && isBlack(cx, y + 14)) return new int[] { cx, y };
        }
      }
    }
    return null;
  }
}
"@
Add-Type -ReferencedAssemblies System.Drawing -TypeDefinition $pillSig
try { [void][Q]::SetProcessDpiAwareness(2) } catch {}   # per-monitor v2：全程物理像素

# ---- WinRT OCR ----
$null = [Windows.Media.Ocr.OcrEngine, Windows.Foundation, ContentType = WindowsRuntime]
$null = [Windows.Globalization.Language, Windows.Foundation, ContentType = WindowsRuntime]
$null = [Windows.Graphics.Imaging.SoftwareBitmap, Windows.Foundation, ContentType = WindowsRuntime]
$null = [Windows.Storage.Streams.InMemoryRandomAccessStream, Windows.Foundation, ContentType = WindowsRuntime]
$asTask = ([System.WindowsRuntimeSystemExtensions].GetMethods() | Where-Object {
  $_.Name -eq 'AsTask' -and $_.GetParameters().Count -eq 1 -and $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncOperation`1' })[0]
function Await($op,$t){ $m=$asTask.MakeGenericMethod($t); $x=$m.Invoke($null,@($op)); $x.Wait(-1)|Out-Null; return $x.Result }
$engine = [Windows.Media.Ocr.OcrEngine]::TryCreateFromLanguage((New-Object Windows.Globalization.Language "zh-Hans-CN"))
if (-not $engine) { $engine = [Windows.Media.Ocr.OcrEngine]::TryCreateFromUserProfileLanguages() }

# ---- 目标窗口 ----
function Read-Rect($h){ $r=New-Object Q+R; [void][Q]::GetWindowRect($h,[ref]$r)
    return @{Hwnd=$h;X=$r.L;Y=$r.T;W=($r.Rr-$r.L);H=($r.B-$r.T);Area=($r.Rr-$r.L)*($r.B-$r.T)} }
function Get-Placement($h){
    # 最小化窗口的 GetWindowRect 是 -32000 哨兵，拿不到真实尺寸；
    # rcNormalPosition 才是「还原后会占多大」，用它区分主窗口和 314x50 辅助窗。
    # showCmd/flags 一并带出：flags 含 WPF_RESTORETOMAXIMIZED(2) 时说明主人
    # 是从最大化状态最小化的，收尾最小化回去时不用额外处理。
    $wp = New-Object Q+WP
    $wp.length = [System.Runtime.InteropServices.Marshal]::SizeOf($wp)
    if (-not [Q]::GetWindowPlacement($h, [ref]$wp)) { return $null }
    return @{ShowCmd=$wp.showCmd; Flags=$wp.flags;
             X=$wp.normal.L; Y=$wp.normal.T;
             W=($wp.normal.Rr-$wp.normal.L); H=($wp.normal.B-$wp.normal.T)}
}
function Restore-HiddenQoderWindow {
    # 2026-10-29：Qoder 关到托盘后主窗口 WS_VISIBLE=off，Get-Process 的
    # MainWindowHandle 直接给 0，旧逻辑当成「客户端没开」白等 90 秒。
    # 这里枚举同进程的隐藏顶层窗口，按 Chrome_WidgetWin_1 + 非空标题 + 够大
    # 找主窗口，ShowWindow(SW_RESTORE) 还原。找不到返回 Zero。
    $pids = @{}
    Get-Process | Where-Object { $_.ProcessName -like "*$ProcessName*" } |
        ForEach-Object { $pids[[uint32]$_.Id] = $true }
    if ($pids.Count -eq 0) { return [IntPtr]::Zero }
    $script:HiddenHwnd = [IntPtr]::Zero
    $script:HiddenArea = 0
    $cb = [Q+EnumProc]{
        param($h, $lp)
        $owner = [uint32]0
        [Q]::GetWindowThreadProcessId($h, [ref]$owner) | Out-Null
        if (-not $pids.ContainsKey($owner)) { return $true }
        if ([Q]::IsWindowVisible($h)) { return $true }
        $r = New-Object Q+R
        [Q]::GetWindowRect($h, [ref]$r) | Out-Null
        $w = $r.Rr - $r.L
        $hh = $r.B - $r.T
        if ($w -lt 600 -or $hh -lt 400) { return $true }
        $cls = New-Object System.Text.StringBuilder 256
        [void][Q]::GetClassName($h, $cls, 256)
        if ($cls.ToString() -ne 'Chrome_WidgetWin_1') { return $true }
        $t = New-Object System.Text.StringBuilder 512
        [void][Q]::GetWindowTextW($h, $t, 512)
        if (-not $t.ToString().Trim()) { return $true }
        if (($w * $hh) -gt $script:HiddenArea) {
            $script:HiddenArea = $w * $hh
            $script:HiddenHwnd = $h
        }
        return $true
    }
    [Q]::EnumWindows($cb, [IntPtr]::Zero) | Out-Null
    if ($script:HiddenHwnd -eq [IntPtr]::Zero) { return [IntPtr]::Zero }
    # ShowWindow(9) 会把最大化窗口变成还原态；记下来，收尾时还原成最大化。
    if ([Q]::IsZoomed($script:HiddenHwnd)) { $script:WasZoomed = $true }
    Log ("window hidden (tray?); restoring hwnd=" + $script:HiddenHwnd)
    [void][Q]::ShowWindow($script:HiddenHwnd, 9)   # SW_RESTORE
    Start-Sleep -Milliseconds 900
    return $script:HiddenHwnd
}

function Find-QoderWindow {
    # 只要「够大且不在最小化位置(-32000)」的主窗口。2026-10-16 实测最小化时枚举会撞上
    # 一个 314x50 的辅助窗口（rect=-32000,-32000），旧逻辑按最大面积选中它后全链路锚点失效。
    # 2026-10-30：补最小化分支——窗口最小化到任务栏时是「可见但 rect=-32000」，
    # 上面按 rect 过滤会丢掉，Restore-HiddenQoderWindow 只找隐藏窗也接不住，
    # 结果主人开着客户端却报 notfound（当日 00:03 定时轮实况）。
    # 现在用 IsIconic 认最小化、GetWindowPlacement 的还原 rect 判断主窗口，
    # 命中就 SW_RESTORE 干活，收尾 Restore-OriginalRect 再 SW_MINIMIZE 放回去。
    for ($attempt = 1; $attempt -le 2; $attempt++) {
        $pids = @(Get-Process | Where-Object { $_.ProcessName -like "*$ProcessName*" } | ForEach-Object { $_.Id })
        $best=$null
        $minimized=$null
        foreach ($p in Get-Process) {
            if ($p.MainWindowHandle -eq [IntPtr]::Zero) { continue }
            if ($pids -notcontains $p.Id) { continue }
            $h = $p.MainWindowHandle
            if ([Q]::IsIconic($h)) {
                $pl = Get-Placement $h
                if (-not $pl) { continue }
                if ($pl.W -lt 600 -or $pl.H -lt 400) { continue }
                if (-not $minimized -or ($pl.W * $pl.H) -gt $minimized.Area) {
                    $minimized = @{Hwnd=$h;X=$pl.X;Y=$pl.Y;W=$pl.W;H=$pl.H;
                                   Area=($pl.W*$pl.H);ShowCmd=$pl.ShowCmd;Flags=$pl.Flags}
                }
                continue
            }
            $c=Read-Rect $h
            if ($c.W -lt 600 -or $c.H -lt 400) { continue }
            if ($c.X -le -10000 -or $c.Y -le -10000) { continue }
            if (-not $best -or $c.Area -gt $best.Area) { $best=$c }
        }
        if ($best) { return $best }
        if ($minimized) {
            $script:WasMinimized = $true
            $script:MinimizedShowCmd = $minimized.ShowCmd
            Log ("window iconic (minimized); restoring hwnd=" + $minimized.Hwnd + " showCmd=" + $minimized.ShowCmd + " flags=" + $minimized.Flags)
            [void][Q]::ShowWindow($minimized.Hwnd, 9)   # SW_RESTORE
            Start-Sleep -Milliseconds 900
            $c = Read-Rect $minimized.Hwnd
            if ($c.W -ge 600 -and $c.H -ge 400) { return $c }
        }
        if ($attempt -eq 1) {
            $restored = Restore-HiddenQoderWindow
            if ($restored -eq [IntPtr]::Zero) { return $null }
            $c = Read-Rect $restored
            if ($c.W -ge 600 -and $c.H -ge 400) { return $c }
        }
    }
    return $null
}

function Log-WindowProbe {
    # 2026-10-30：notfound 时把 Qoder 的顶层窗口摊开写日志。上次 00:03 只在
    # 结果文件里留下一句「没出现主窗口」，事后没法区分是进程没起、最小化、
    # 托盘隐藏还是类名/标题变了，只能靠猜。这里一次性把判据所需字段都落盘。
    $pids = @{}
    Get-Process | Where-Object { $_.ProcessName -like "*$ProcessName*" } |
        ForEach-Object { $pids[[uint32]$_.Id] = $true }
    if ($pids.Count -eq 0) { Log "probe: 无 Qoder 进程"; return }
    $lines = New-Object System.Collections.ArrayList
    $cb = [Q+EnumProc]{
        param($h, $lp)
        $owner = [uint32]0
        [Q]::GetWindowThreadProcessId($h, [ref]$owner) | Out-Null
        if (-not $pids.ContainsKey($owner)) { return $true }
        $r = New-Object Q+R
        [Q]::GetWindowRect($h, [ref]$r) | Out-Null
        $cls = New-Object System.Text.StringBuilder 256
        [void][Q]::GetClassName($h, $cls, 256)
        $t = New-Object System.Text.StringBuilder 512
        [void][Q]::GetWindowTextW($h, $t, 512)
        $pl = " -"
        if ([Q]::IsIconic($h)) {
            $wp = New-Object Q+WP
            $wp.length = [System.Runtime.InteropServices.Marshal]::SizeOf($wp)
            if ([Q]::GetWindowPlacement($h, [ref]$wp)) {
                $pl = " normal=" + $wp.normal.L + "," + $wp.normal.T + " " + ($wp.normal.Rr-$wp.normal.L) + "x" + ($wp.normal.B-$wp.normal.T) + " cmd=" + $wp.showCmd
            }
        }
        [void]$lines.Add("probe: pid=$owner hwnd=$h class=" + $cls.ToString() +
            " vis=" + [Q]::IsWindowVisible($h) + " iconic=" + [Q]::IsIconic($h) +
            " rect=" + $r.L + "," + $r.T + " " + ($r.Rr-$r.L) + "x" + ($r.B-$r.T) +
            $pl + " title=[" + $t.ToString() + "]")
        return $true
    }
    [Q]::EnumWindows($cb, [IntPtr]::Zero) | Out-Null
    foreach ($ln in $lines) { Log $ln }
}
function Test-Blank($bmp) {
    $first = $bmp.GetPixel([int]($bmp.Width/2), [int]($bmp.Height/2))
    for ($i = 1; $i -le 8; $i++) {
        $px = [int]($bmp.Width * $i / 9)
        for ($j = 1; $j -le 8; $j++) {
            $py = [int]($bmp.Height * $j / 9)
            $c = $bmp.GetPixel($px, $py)
            if ($c.R -ne $first.R -or $c.G -ne $first.G -or $c.B -ne $first.B) { return $false }
        }
    }
    return $true
}
# 抓窗口 -> 位图（供 OCR 与像素扫描）。
# 屏外模式必须用 PrintWindow：CopyFromScreen(屏外坐标) 拍到的是用户桌面内容。
# 实测 v0.4.8 的 PrintWindow(PW_RENDERFULLCONTENT) 能抓到活动弹窗叠加层；
# 屏外窗口受 backgroundThrottling 影响首帧可能空白，2s 间隔重试（上限 8s）。
function Capture-Win($t) {
    # 2026-10-30：上限从 15 降到 5（30s→8s）。空白帧一旦连续出现，整轮重试也很少
    # 能自愈，反而把 240s 的外层预算耗尽（10-27 LobsterAI 就是这么被判 failed 的）。
    $maxTry = 1
    if ($Offscreen) { $maxTry = 5 }
    $bmp = $null
    for ($tryN = 1; $tryN -le $maxTry; $tryN++) {
        $bmp = New-Object System.Drawing.Bitmap($t.W, $t.H)
        $g = [System.Drawing.Graphics]::FromImage($bmp)
        if ($Offscreen) {
            $hdc = $g.GetHdc()
            $ok = [Q]::PrintWindow($t.Hwnd, $hdc, 2)
            $g.ReleaseHdc($hdc)
            $g.Dispose()
            if ($ok -and -not (Test-Blank $bmp)) { break }
            if ($tryN -lt $maxTry) {
                if ($tryN -eq 1) { Log "offscreen: PrintWindow 空白帧，2s 间隔重试（backgroundThrottling 容忍）" }
                $bmp.Dispose()
                Start-Sleep -Seconds 2
            }
        } else {
            $g.CopyFromScreen($t.X, $t.Y, 0, 0, (New-Object System.Drawing.Size $t.W,$t.H))
            $g.Dispose()
            break
        }
    }
    try { $bmp.Save($shotPath,[System.Drawing.Imaging.ImageFormat]::Png) } catch {}
    return $bmp
}
function OcrWords($bmp, [int]$ox, [int]$oy) {
  $ms=New-Object System.IO.MemoryStream; $bmp.Save($ms,[System.Drawing.Imaging.ImageFormat]::Png)
  $bytes=$ms.ToArray(); $ms.Dispose()
  $st=New-Object Windows.Storage.Streams.InMemoryRandomAccessStream
  $dw=New-Object Windows.Storage.Streams.DataWriter($st.GetOutputStreamAt(0)); $dw.WriteBytes($bytes)
  Await ($dw.StoreAsync()) ([uint32])|Out-Null; Await ($dw.FlushAsync()) ([bool])|Out-Null
  $dec=Await ([Windows.Graphics.Imaging.BitmapDecoder]::CreateAsync($st)) ([Windows.Graphics.Imaging.BitmapDecoder])
  $sb=Await ($dec.GetSoftwareBitmapAsync()) ([Windows.Graphics.Imaging.SoftwareBitmap])
  $res=Await ($engine.RecognizeAsync($sb)) ([Windows.Media.Ocr.OcrResult])
  $w=@()
  foreach($ln in $res.Lines){ foreach($wd in $ln.Words){ $tx=($wd.Text -replace "\s",""); if($tx){
    $br=$wd.BoundingRect
    $w+=@{text=$tx; sx=[int]($ox+$br.X+$br.Width/2); sy=[int]($oy+$br.Y+$br.Height/2)
          ix=[int]$br.X; iy=[int]$br.Y; iw=[int]$br.Width; ih=[int]$br.Height
          cx=[int]($br.X+$br.Width/2); cy=[int]($br.Y+$br.Height/2)} } } }
  return $w
}
function Join-Text($words){ return (($words | ForEach-Object { $_.text }) -join " ") }
# 关键：Windows OCR 会把中文拆成单字（实测「权益中心」「领取」都可能被拆开），
# 所以布尔判定一律先去掉空白再匹配；需要坐标的短语用 Find-Phrase 跨字定位。
function Test-Contains([string]$hay,[string[]]$ns){ $h=($hay -replace '\s',''); foreach($n in $ns){ if($h -like "*$n*"){return $true} } return $false }
# 在按阅读顺序拼接的词流里找短语，返回命中处中间字符所属词的坐标（应对单字拆分）
function Find-Phrase($words,[string]$phrase) {
    foreach($w in $words){ if($w.text -eq $phrase){return $w} }
    $concat=''; $owner=@()
    for($i=0;$i -lt $words.Count;$i++){ $tx=[string]$words[$i].text; $concat+=$tx; for($k=0;$k -lt $tx.Length;$k++){ $owner+=$i } }
    $j=$concat.IndexOf($phrase)
    if($j -lt 0){ return $null }
    $mid=$j+[int]([Math]::Floor($phrase.Length/2))
    if($mid -ge $owner.Count){ $mid=$owner.Count-1 }
    return $words[$owner[$mid]]
}

# >>> ANCHOR-REGION（scripts/test_username_anchor.py 抽取本块跑离线回归，勿删标记） >>>
# 左下角「用户名」锚点候选集：底栏 = 全窗口最靠下的一行文字（取 max cy ±12px 容差，
# 天然排除左侧栏「自动化/扩展」——最大化态它们也只到 cy≈0.93H，比底栏高约 100px），
# 在该行内按 cx 升序取「多字非数字词」：最左即用户名（实测 warpeas cx≈161），
# 其后是工作区名（agent-c.. cx≈653）。最多返回 2 个候选——第 3 个往后的词
# （「本地」等模式指示）点了有副作用，不试。
# 为什么不再按 cy 取「最靠下的词」（2026-10-20 实测翻车）：底栏一行里 warpeas 与
# agent-c.. 的 cy 只差 ~4px，OCR 抖动或首帧渲染动画时会翻转；且首帧漏检 warpeas 时
# 会直接选中工作区名——点它开不了账户菜单，当天定时轮白白 pending。改成行内最左后，
# 只要 warpeas 被检出就稳赢（cx 差 3 倍，不存在翻转）；漏检时也能靠多候选逐试点下去。
# 直接点文字中心本身（旧脚本点的是它右边的仪表图标，改版后那条路已废）。
function Find-UsernameCandidates($words,$t) {
    if (-not $words -or $words.Count -eq 0) { return @() }
    # ⚠️ 两个 PS 5.1 哈希表坑，都实测过（2026-10-20）：
    #   1) Sort-Object 的字符串属性名（-Property cx 或 @{Expression='cx'}）对哈希表
    #      数组不生效——键全等，退化成不稳定排序，输出顺序是输入顺序的任意置换。
    #      旧锚点逻辑就是这么静默失效的：平时偶然选中 warpeas，今天 2 元素词表下
    #      选中 agent-c..（工作区名），点它不开账户菜单，整天 pending。
    #      必须用脚本块表达式 @{Expression={$_.cx}}。
    #   2) 不能用 `Measure-Object -Property cy`：它对哈希表数组报「找不到属性」，
    #      $ErrorActionPreference=Stop 会把非终止错误变成致命错误炸掉整个脚本。
    $maxCy = 0
    foreach ($w in $words) { if ([int]$w.cy -gt $maxCy) { $maxCy = [int]$w.cy } }
    $row = @($words | Where-Object { $_.cy -ge ($maxCy - 12) -and $_.cx -lt $t.W*0.30 -and $_.text.Length -ge 2 -and $_.text -notmatch '^[0-9]+$' })
    if ($row.Count -eq 0) {
        # 兜底：底栏行判定失效时，退回「底部 10% + 左 30%」旧判据
        $row = @($words | Where-Object { $_.cy -gt $t.H*0.90 -and $_.cx -lt $t.W*0.30 -and $_.text.Length -ge 2 -and $_.text -notmatch '^[0-9]+$' })
    }
    $sorted = @($row | Sort-Object @{Expression={$_.cx};Ascending=$true})
    if ($sorted.Count -gt 2) { $sorted = $sorted[0..1] }
    return $sorted
}
function Find-Username($bmp,$t,$words) {
    # ⚠️ @() 包裹不能省：函数返回 1 元素数组时调用侧会退化成标量（数组被管道展开），
    # 标量哈希表没有 [0] 索引，$u 会变 $null（2026-10-20 回归测试逮到的）。
    $c = @(Find-UsernameCandidates $words $t)
    if (-not $c -or $c.Count -eq 0) { return $null }
    $u = $c[0]
    return @{ sx=$u.sx; sy=$u.sy; uname=$u.text }
}
# <<< ANCHOR-REGION <<<
# 账户菜单里的「权益中心」：菜单从左下往上弹，条目一律在屏幕左侧（实测还原态 cx≈0.09W）。
# 限定左 1/3 区域 + 用户名上方，排除聊天面板里出现的同名词（主人常在 Qoder 里聊签到脚本，聊天区会有这些字）。
function Find-MenuItem($words,$t,$uname,[string]$phrase) {
    $cand = @($words | Where-Object { $_.cx -lt $t.W*0.33 -and $_.cy -lt $uname.sy - $t.Y - 20 -and $_.cy -gt $t.H*0.25 })
    $hit = Find-Phrase $cand $phrase
    if ($hit) { return $hit }
    # 兜底：不限高度再找一次左侧词（菜单条目可能更高）
    $cand2 = @($words | Where-Object { $_.cx -lt $t.W*0.33 })
    return Find-Phrase $cand2 $phrase
}
# 活动弹窗标记（必须先确认弹窗在，再谈领取/幂等——否则聊天记录里的同名词会污染判定）
function Test-CampaignPopup([string]$text){ return Test-Contains $text @('专属活动权益','立即查收','每天领') }
function Test-Claimed([string]$text){ return Test-Contains $text @('已领取','领取成功','已到账','今日已领','不可领取') }
# 「领取」按钮：黑底白字药丸。OCR 读不出黑底白字（实测），用「中央区高密度中性黑块」定位；
# 要求中性黑是为了排除深绿「查看详情」。只在活动弹窗已确认可见时调用。
# 2026-10-22 活动卡改版：移除了「限时福利/查看详情」，黑色「领取」从右侧小药丸变成
# 整行宽按钮，中心从 ~58%H 下移到 ~75%H。旧扫描上限 0.72H 只差 3px 覆盖不到——
# 启动弹窗和「权益中心」两条路径同一天都 pending，但客户端日志 claimable=true 且从未
# 发出领取请求。y 上限放宽到 0.90H；x 范围不变，底栏最左的深绿「查看详情」仍被排除。
function Find-BlackPill($bmp,$t) {
    # 判据与采样范围原样保留，只把逐像素循环搬进编译代码（Pill.Find）。
    # 复核阶段会再调一次本函数，所以这里必须便宜：编译版全扫 ~25ms。
    $hit = [Pill]::Find($bmp, 0.40, 0.74, 0.40, 0.90)
    if ($hit) {
        Log ("blackpill: HIT img(" + $hit[0] + "," + $hit[1] + ")")
        return @{ ix = [int]$hit[0]; iy = [int]$hit[1] }
    }
    Log "blackpill: no hit"
    return $null
}
function Get-Granted($text){ if($text -match '每天领\D{0,3}(\d+)'){return [int]$matches[1]}; if($text -match '\+\s*(\d+)\s*Credit'){return [int]$matches[1]}; return 0 }

# 「我的用量」小窗里的特征词（面板标题与分桶名都是 OCR 可见的，图标本身没文字）
$USAGE_WORDS = @('我的用量','套餐内','资源包','查看详情')
function Test-UsagePopover($beforeWords,$afterWords) {
    # 判「小窗开了」不能只看全屏 OCR：主人常在 Qoder 里聊签到脚本，聊天区常年出现
    # 「资源包/查看详情」这些词（Trae 也踩过同款自指污染）。所以只认**点击后新出现**
    # 的特征词——小窗一开必然带入一批此前不在屏上的文字。
    $seen = @{}
    foreach ($w in $beforeWords) { $seen["$($w.text)@$($w.ix),$($w.iy)"] = $true }
    foreach ($phrase in $USAGE_WORDS) {
        $hit = Find-Phrase $afterWords $phrase
        if ($hit -and -not $seen.ContainsKey("$($hit.text)@$($hit.ix),$($hit.iy)")) { return $true }
    }
    return $false
}
function Find-UsageGaugeCandidates($bmp,$t,$uword) {
    # 底栏用户名右侧的「用量仪表」图标（2026-10-30 主人确认：第一枚「油表」就是
    # 「我的用量」，第二枚是齿轮=设置）：没有文字，只能按像素簇找。
    # 判据用**相对色差**而不是固定阈值——先在用户名左侧取样底栏背景亮度，
    # 浅色/深色主题下都成立；实测图标是 8~60px 宽的紧凑簇，文字更宽、要排除。
    $bgx = [int]([Math]::Max(0, $uword.ix - 24))
    $sum=0; $cnt=0
    for($y=$uword.iy; $y -le ($uword.iy+$uword.ih); $y+=2){
        if($bgx -lt $bmp.Width){ $p=$bmp.GetPixel($bgx,$y); $sum += (([int]$p.R+[int]$p.G+[int]$p.B)/3); $cnt++ }
    }
    if($cnt -eq 0){ return @() }
    $bg = $sum/$cnt
    function Differs($x,$y){
        if($x -lt 0 -or $y -lt 0 -or $x -ge $bmp.Width -or $y -ge $bmp.Height){return $false}
        $p=$bmp.GetPixel($x,$y); $r=[int]$p.R;$g=[int]$p.G;$b=[int]$p.B
        $lum=($r+$g+$b)/3
        $sat=([Math]::Max($r,[Math]::Max($g,$b)) - [Math]::Min($r,[Math]::Min($g,$b)))
        return (([Math]::Abs($lum-$bg) -gt 45) -or ($sat -gt 60))
    }
    $ix0=[int]($uword.ix+$uword.iw+6); $ix1=[int]([Math]::Min($bmp.Width-1,$ix0+280))
    $iy0=[int]([Math]::Max(0,$uword.iy-16)); $iy1=[int]([Math]::Min($bmp.Height-1,$uword.iy+$uword.ih+16))
    $runs=@(); $runStart=-1
    for($x=$ix0;$x -lt $ix1;$x++){
        $n=0
        for($y=$iy0;$y -le $iy1;$y+=2){ if(Differs $x $y){$n++} }
        if(($n -ge 3) -and ($runStart -lt 0)){ $runStart=$x }
        if(($n -lt 3) -and ($runStart -ge 0)){ $runs += ,@($runStart,($x-1)); $runStart=-1 }
    }
    if($runStart -ge 0){ $runs += ,@($runStart,($ix1-1)) }
    $out=@()
    foreach($r in $runs){
        $w=$r[1]-$r[0]+1
        if($w -ge 8 -and $w -le 60){ $out += @{ ix=[int]($r[0]+$w/2); iy=[int](($iy0+$iy1)/2) } }
    }
    if($out.Count -gt 3){ $out = $out[0..2] }
    return @($out)
}

function Ensure-Foreground($hwnd){
    # 后台进程抢前台受 Windows foreground-lock 限制：SetForegroundWindow 常「返回成功但没真拿到焦点」，
    # 导致点击落空。经典绕法是先模拟一次 Alt 键（解除锁定），再抢前台。
    [Q]::keybd_event(0x12,0,0,[UIntPtr]::Zero)          # VK_MENU down
    [Q]::keybd_event(0x12,0,2,[UIntPtr]::Zero)          # up
    Start-Sleep -Milliseconds 40
    [void][Q]::SetForegroundWindow($hwnd); Start-Sleep -Milliseconds 300
    if ([Q]::GetForegroundWindow() -ne $hwnd) {
        [void][Q]::ShowWindow($hwnd, 5)                  # SW_SHOW
        [void][Q]::SetForegroundWindow($hwnd); Start-Sleep -Milliseconds 300
    }
    return ([Q]::GetForegroundWindow() -eq $hwnd)
}
function Send-Esc{ [Q]::keybd_event(0x1B,0,0,[UIntPtr]::Zero); Start-Sleep -Milliseconds 60; [Q]::keybd_event(0x1B,0,2,[UIntPtr]::Zero) }

# ---- 方案甲：屏外停放 / 恢复（M1/M4） ---------------------------------------
$script:OriginalRect = $null
$script:WasZoomed = $false
$script:WasMinimized = $false
$script:MinimizedShowCmd = 0
$script:Hwnd = [IntPtr]::Zero
$script:SavedForeground = [IntPtr]::Zero
$script:ForegroundBefore = [IntPtr]::Zero
$script:LastSynthTarget = [IntPtr]::Zero

function Move-OffscreenNow {
    # M1：窗口停到虚拟桌面左界外，但**留 OffscreenStripPx 像素**在屏内。
    # 2026-10-22 实测：Qoder 的 Chromium 在整窗屏外/最大化屏外时 PrintWindow 全空白；
    # 还原态留一条 30-100px 边、并用 HWND_TOPMOST 置顶（SWP_NOACTIVATE，绝不激活；收尾摘掉）后，
    # DWM 继续合成，PrintWindow 能完整抓到活动弹窗叠加层。置顶是为了条带不被前台
    # 窗口盖住；收尾时 Restore-OriginalRect 会按启动前的前台窗口把 z-order 放回去。
    # 0x0011 = SWP_NOSIZE | SWP_NOACTIVATE（故意不带 SWP_NOZORDER，好置顶）。
    if (-not $Offscreen) { return }
    if ($script:Hwnd -eq [IntPtr]::Zero) { return }
    $cr = New-Object Q+R
    [void][Q]::GetWindowRect($script:Hwnd,[ref]$cr)
    $w = $cr.Rr - $cr.L
    if ($w -le 0) { return }
    $strip = [Math]::Max(1, [Math]::Min($OffscreenStripPx, $w - 1))
    $vLeft = [Q]::GetSystemMetrics(76)   # SM_XVIRTUALSCREEN
    $vTop  = [Q]::GetSystemMetrics(77)   # SM_YVIRTUALSCREEN
    # HWND_TOPMOST(-1)：实测普通 HWND_TOP 升不过正在前台的全屏窗口，条带会被盖住，
    # 下一次 PrintWindow 又是空白。收尾 Restore-OriginalRect 会 HWND_NOTOPMOST 摘掉。
    $ok = [Q]::SetWindowPos($script:Hwnd,[IntPtr](-1),($vLeft - $w + $strip),$vTop,0,0,0x0011)
    if (-not $ok) { Log "offscreen: topmost strip move failed" }
}
function Restore-OriginalRect {
    # M4：恢复启动 rect / 最大化状态，防 Electron 把屏外位置持久化。
    if (-not $script:OriginalRect) { return }
    if ($script:Hwnd -eq [IntPtr]::Zero) { return }
    try {
        # 摘掉条带模式的 topmost，否则恢复后 Qoder 会压在所有窗口之上。
        [void][Q]::SetWindowPos($script:Hwnd,[IntPtr](-2),0,0,0,0,0x0013)  # HWND_NOTOPMOST
        if ($script:WasZoomed) {
            [void][Q]::ShowWindow($script:Hwnd,3)   # SW_MAXIMIZE
            Log "restore-rect: maximized (was zoomed)"
        } else {
            $r = $script:OriginalRect
            [void][Q]::SetWindowPos($script:Hwnd,[IntPtr]::Zero,$r.X,$r.Y,0,0,0x0015)
            Start-Sleep -Milliseconds 250
            $chk = New-Object Q+R
            [void][Q]::GetWindowRect($script:Hwnd,[ref]$chk)
            Log ("restore-rect: now " + $chk.L + "," + $chk.T + " (expect " + $r.X + "," + $r.Y + ")")
        }
        # 条带模式把窗口提到了普通窗口最上层；按启动前的前台窗口把 z-order 放回去，
        # 否则签到完 Qoder 会一直盖在主人正在用的窗口上面。启动前 Qoder 就是前台
        # 时不动的（主人本来就在用它，保持原样）。0x0013 = NOSIZE|NOMOVE|NOACTIVATE。
        if ($script:ForegroundBefore -ne [IntPtr]::Zero -and $script:ForegroundBefore -ne $script:Hwnd) {
            $zok = [Q]::SetWindowPos($script:Hwnd,$script:ForegroundBefore,0,0,0,0,0x0013)
            Log ("restore-rect: z-order below foreground " + $script:ForegroundBefore + " ok=" + $zok)
            if (-not $zok) {
                # 启动前的窗口已关掉/句柄失效：退到普通窗口最底层，绝不盖住主人。
                [void][Q]::SetWindowPos($script:Hwnd,[IntPtr]1,0,0,0,0,0x0013)  # HWND_BOTTOM
                Log "restore-rect: z-order fallback -> bottom"
            }
        }
        # 2026-10-30：主人本来把窗口最小化在任务栏，签到完原样放回去，
        # 别留一个突然弹到前台的大窗口。
        if ($script:WasMinimized) {
            [void][Q]::ShowWindow($script:Hwnd, 6)   # SW_MINIMIZE
            Log "restore-rect: minimized (was iconic)"
        }
    } catch { try { Log ("restore-rect failed: " + $_.Exception.Message) } catch {} }
}
function Save-Foreground {
    if ($script:SavedForeground -eq [IntPtr]::Zero) {
        $f = [Q]::GetForegroundWindow()
        if ($f -ne $script:Hwnd) { $script:SavedForeground = $f }
    }
}
function Restore-Foreground {
    # 2026-10-22 实测：BringBack 的真实点击会把 Qoder 激活，事后直接
    # SetForegroundWindow(原前台) 会被 Windows foreground-lock 静默拒绝，
    # 主人回来打字会打进 Qoder。这里复用 Ensure-Foreground 的 Alt 解前台锁，
    # 并核对 GetForegroundWindow；失败至少留日志，不假装成功。
    if ($script:SavedForeground -eq [IntPtr]::Zero) { return }
    $target = $script:SavedForeground
    $script:SavedForeground = [IntPtr]::Zero
    try {
        [Q]::keybd_event(0x12,0,0,[UIntPtr]::Zero)
        [Q]::keybd_event(0x12,0,2,[UIntPtr]::Zero)
        Start-Sleep -Milliseconds 40
        [void][Q]::SetForegroundWindow($target)
        Start-Sleep -Milliseconds 200
        if ([Q]::GetForegroundWindow() -ne $target) {
            [void][Q]::SetForegroundWindow($target)
            Start-Sleep -Milliseconds 150
        }
        Log ("restore-foreground: now " + [Q]::GetForegroundWindow() + " (expect " + $target + ")")
    } catch {}
}
function Get-IdleSeconds {
    $li = New-Object Q+LI
    $li.cbSize = [uint32][System.Runtime.InteropServices.Marshal]::SizeOf($li)
    if (-not [Q]::GetLastInputInfo([ref]$li)) { return 999999 }
    $tick = [uint32][Q]::GetTickCount()
    return [int]((($tick - $li.dwTime) -band 0xFFFFFFFF) / 1000)
}
function Wait-InputQuiet([int]$QuietMs = 320, [int]$MaxWaitMs = 20000) {
    # 点击前闸门：主人正在动鼠标/敲键盘时先等。屏外方案可以用 PrintWindow 静默
    # 识别，但真实点击那一下必须占用光标；等他停手后立刻点、点完立刻还原，
    # 才不会出现「脚本把鼠标抢走」的感觉。QuietMs 取 320ms——足够让一次连续
    # 移动/点击结束，又短到不会明显推迟签到。超时仍继续（漏签代价更大），
    # 但会记一行日志。
    $start = Get-Date
    $deadline = $start.AddMilliseconds($MaxWaitMs)
    $logged = $false
    while ($true) {
        $idle = [Q]::IdleMs()
        if ($idle -ge $QuietMs) {
            if ($logged) {
                Log ("input-quiet: 已静默 " + $idle + "ms，开始点击（等了 " +
                     [int]((Get-Date) - $start).TotalMilliseconds + "ms）")
            }
            return $true
        }
        if (-not $logged) {
            Log ("input-quiet: 用户正在操作（idle=" + $idle + "ms），等键鼠停下再点（上限 " + $MaxWaitMs + "ms）")
            $logged = $true
        }
        if ((Get-Date) -ge $deadline) {
            Log ("input-quiet: 等待 " + $MaxWaitMs + "ms 仍有键鼠输入，按最小暴露继续")
            return $false
        }
        Start-Sleep -Milliseconds 25
    }
}
function Wait-UserIdle {
    # 空闲闸门：用户刚动过键鼠就不搬窗口，最多等 IdleWaitSec 秒；超时仍继续
    # （签到不能因为主人在用电脑就整天不做），但此时暴露面只有 BringBack 的 ~0.5s。
    if (-not $Offscreen -or $IdleWaitSec -le 0) { return }
    $idle = Get-IdleSeconds
    if ($idle -ge $IdleThresholdSec) { Log ("idle gate: idle=" + $idle + "s, proceed"); return }
    Log ("idle gate: user active (idle=" + $idle + "s), wait up to " + $IdleWaitSec + "s")
    $deadline = (Get-Date).AddSeconds($IdleWaitSec)
    $lastLog = $idle
    while ((Get-Date) -lt $deadline) {
        Start-Sleep -Seconds 10
        $idle = Get-IdleSeconds
        if ($idle -ge $IdleThresholdSec) { Log ("idle gate: idle=" + $idle + "s, proceed"); return }
        if (($idle - $lastLog) -ge 120) { Log ("idle gate: still active (idle=" + $idle + "s)"); $lastLog = $idle }
    }
    Log ("idle gate: timeout after " + $IdleWaitSec + "s, proceed with minimal exposure")
}
function Test-ClickVisible([int]$cx,[int]$cy) {
    # 反遮挡：点击点最顶层窗口必须是 Qoder 的根窗口/同进程窗口。
    # 2026-10-22 实测：Qoder 内容窗体的 WindowFromPoint 常返回 renderer 子进程
    # （pid 与主进程不同），只比 pid 会误判「被遮挡」而放弃所有点击。用
    # GetAncestor(GA_ROOT) 回溯到顶层窗口，再与主窗口比较；同 pid 的独立
    # 顶层浮层（活动弹窗）也放行。
    $sp = New-Object Q+P
    $sp.X = $cx; $sp.Y = $cy
    $top = [Q]::WindowFromPoint($sp)
    if ($top -eq [IntPtr]::Zero) {
        Log ("click-visible: point $cx,$cy -> WindowFromPoint=0")
        return $false
    }
    $root = [Q]::GetAncestor($top, 2)   # GA_ROOT
    if ($root -eq $script:Hwnd) { return $true }
    $pidTop = [uint32]0; $pidMain = [uint32]0
    [void][Q]::GetWindowThreadProcessId($top,[ref]$pidTop)
    [void][Q]::GetWindowThreadProcessId($script:Hwnd,[ref]$pidMain)
    if ($pidTop -ne $pidMain) {
        Log ("click-visible: point $cx,$cy top=$top pid=$pidTop root=$root main=$script:Hwnd pidMain=$pidMain")
    }
    return ($pidTop -eq $pidMain)
}
function Send-SynthMouse([int]$ax,[int]$ay) {
    # 合成鼠标消息：与窗口屏幕位置无关，屏外也能投递（零暴露）。
    # Electron 的顶层窗口只转发输入，真正的 renderer 是子窗口，必须逐层下钻。
    # 实测 Qoder 的 webview 按钮不吃这套（连关闭 X 都点不动），调用方需复核结果。
    $cr = New-Object Q+R
    [void][Q]::GetWindowRect($script:Hwnd,[ref]$cr)
    $sx = $cr.L + $ax; $sy = $cr.T + $ay
    $sp = New-Object Q+P
    $sp.X = $sx; $sp.Y = $sy
    $top = [Q]::WindowFromPoint($sp)
    $target = $script:Hwnd
    if ($top -ne [IntPtr]::Zero) {
        $pidTop = [uint32]0; $pidMain = [uint32]0
        [void][Q]::GetWindowThreadProcessId($top,[ref]$pidTop)
        [void][Q]::GetWindowThreadProcessId($script:Hwnd,[ref]$pidMain)
        if ($pidTop -eq $pidMain) { $target = $top }
    }
    $cp = New-Object Q+P
    $cp.X = $sx; $cp.Y = $sy
    [void][Q]::ScreenToClient($target,[ref]$cp)
    for ($k = 0; $k -lt 4; $k++) {
        $c = [Q]::ChildWindowFromPointEx($target,$cp,1)
        if ($c -eq [IntPtr]::Zero -or $c -eq $target) { break }
        $target = $c
        $cp.X = $sx; $cp.Y = $sy
        [void][Q]::ScreenToClient($target,[ref]$cp)
    }
    $lp = [IntPtr]((($cp.Y -band 0xFFFF) * 65536) -bor ($cp.X -band 0xFFFF))
    $res = [IntPtr]::Zero
    [void][Q]::SendMessageTimeout($target,0x0200,[UIntPtr]::Zero,$lp,0,1000,[ref]$res)
    $script:LastSynthTarget = $target
    Start-Sleep -Milliseconds 120
    $r1 = [Q]::SendMessageTimeout($target,0x0201,[UIntPtr]::new([uint64]1),$lp,0,1500,[ref]$res)
    Start-Sleep -Milliseconds 80
    $r2 = [Q]::SendMessageTimeout($target,0x0202,[UIntPtr]::Zero,$lp,0,1500,[ref]$res)
    return ($r1 -ne [IntPtr]::Zero -and $r2 -ne [IntPtr]::Zero)
}
function Send-SynthEsc {
    # ESC 的屏外等价物：keybd_event 会落到用户前台窗口，绝不能发。
    $target = $script:Hwnd
    if ($script:LastSynthTarget -ne [IntPtr]::Zero) { $target = $script:LastSynthTarget }
    $res = [IntPtr]::Zero
    [void][Q]::SendMessageTimeout($target,0x0100,[UIntPtr]::new([uint64]0x1B),[IntPtr]::Zero,0,1000,[ref]$res)
    Start-Sleep -Milliseconds 60
    [void][Q]::SendMessageTimeout($target,0x0101,[UIntPtr]::new([uint64]0x1B),[IntPtr]::Zero,0,1000,[ref]$res)
}
function Send-EscSafe {
    if ($Offscreen) { Send-SynthEsc } else { Send-Esc }
}
function BringBack-Click([int]$ax,[int]$ay) {
    # M3：移回屏内 → 保存光标/前台 → SendInput 真实点击 → 恢复光标 → 移回屏外。
    # 暴露面 ~0.5s；点击点被遮挡则试 (0,0)，还不行就放弃（绝不点进别人的窗口）。
    if (-not $script:OriginalRect) { return $false }
    $spots = @(@($script:OriginalRect.X,$script:OriginalRect.Y), @(0,0))
    $placed = $false; $cx = 0; $cy = 0
    foreach ($s in $spots) {
        # 0x0011 = SWP_NOSIZE|SWP_NOACTIVATE + HWND_TOPMOST：把整窗临时提到最上层，
        # 否则主人的最大化/前台窗口会盖住点击点，反遮挡判据只能放弃。这一步是唯一
        # 会露出整窗的 ~0.5s；点完立刻回 48px 条带（条带本身也保持 topmost）。
        [void][Q]::SetWindowPos($script:Hwnd,[IntPtr](-1),$s[0],$s[1],0,0,0x0011)
        Start-Sleep -Milliseconds 300
        $chk = New-Object Q+R
        [void][Q]::GetWindowRect($script:Hwnd,[ref]$chk)
        Log ("bringback: try spot " + $s[0] + "," + $s[1] + " rect now " + $chk.L + "," + $chk.T)
        $cx = $s[0] + $ax; $cy = $s[1] + $ay
        if (Test-ClickVisible $cx $cy) { $placed = $true; break }
        Log ("bringback: spot " + $s[0] + "," + $s[1] + " 被遮挡")
    }
    if (-not $placed) {
        Log "bringback: 两个点击位都被遮挡，跳过真实点击"
        Move-OffscreenNow
        return $false
    }
    Save-Foreground
    # 2026-10-30：真实点击前先等主人停手（静默闸门），点完立刻把光标放回原处——
    # 旧顺序是「点完等 250ms 才还原」，期间鼠标一直停在点击位，主人会以为鼠标被抢。
    [void](Wait-InputQuiet 320 20000)
    $saved = New-Object Q+P
    [void][Q]::GetCursorPos([ref]$saved)
    $clicked = $false
    try {
        $clicked = [bool][Q]::Click($cx,$cy)
        if (-not $clicked) {
            # 120ms hover 里光标被主人挪走了（或系统改了位置）：重新过闸门再点一次。
            Log "bringback: 按下前光标已离开目标点，重试一次"
            [void](Wait-InputQuiet 320 20000)
            $clicked = [bool][Q]::Click($cx,$cy)
        }
        [void][Q]::SetCursorPos($saved.X,$saved.Y)
        if ($clicked) {
            Log ("bringback: real click @ " + $cx + "," + $cy + " (cursor saved " + $saved.X + "," + $saved.Y + ")")
        } else {
            Log ("bringback: 光标两次都被挪走，放弃本次点击 @ " + $cx + "," + $cy)
        }
        Start-Sleep -Milliseconds 250
    } finally {
        [void][Q]::SetCursorPos($saved.X,$saved.Y)
        $now = New-Object Q+P
        [void][Q]::GetCursorPos([ref]$now)
        Log ("bringback: cursor restored " + $now.X + "," + $now.Y + " (expect " + $saved.X + "," + $saved.Y + ")")
        # 顺序很重要：先把键盘焦点还给主人原来的前台窗口，再把 Qoder 条带
        # 以 HWND_TOP + SWP_NOACTIVATE 置顶。反过来做的话，用户的前台窗口会
        # 盖住 48px 条带，下一次 PrintWindow 又是空白帧（Test-Claimed 会误判）。
        Restore-Foreground
        Move-OffscreenNow
    }
    return $clicked
}
function Click-At([int]$ax,[int]$ay,[switch]$SkipSynth) {
    # 坐标一律是窗口位图内的相对坐标；屏幕坐标按窗口当前位置现算。
    if (-not $Offscreen) {
        if (-not (Ensure-Foreground $script:Hwnd)) { return $false }
        $cr = New-Object Q+R
        [void][Q]::GetWindowRect($script:Hwnd,[ref]$cr)
        $sx = $cr.L + $ax; $sy = $cr.T + $ay
        [void](Wait-InputQuiet 320 20000)
        $saved = New-Object Q+P
        [void][Q]::GetCursorPos([ref]$saved)
        $ok = [bool][Q]::Click($sx,$sy)
        [void][Q]::SetCursorPos($saved.X,$saved.Y)
        Log ("click screen($sx,$sy) ok=$ok cursor restored " + $saved.X + "," + $saved.Y)
        return $ok
    }
    if (-not $SkipSynth) {
        $ok = Send-SynthMouse $ax $ay
        Log ("click synth img($ax,$ay) target=$($script:LastSynthTarget) ok=$ok")
        # 这里只报告「消息是否投递」，不自动补真实点击：调用方会用下一帧 OCR
        # 复核，没开出菜单/弹窗再传 -SkipSynth 补一次，避免同一锚点点两下把菜单关掉。
        return $ok
    }
    return (BringBack-Click $ax $ay)
}
function Out-Json([string]$status,[string]$detail){
    # M4：收尾前把窗口恢复原位/最大化，别把屏外位置留给 Electron 持久化。
    if ($script:OriginalRect) { Restore-OriginalRect }
    Restore-Foreground
    Log ("RESULT "+$status+": "+$detail)
    if ($OutFile) { try { [System.IO.File]::WriteAllText($OutFile,(ConvertTo-Json -Compress @{status=$status;detail=$detail}),(New-Object System.Text.UTF8Encoding($false))) } catch {} }
    if ($status -eq 'ok' -or $status -eq 'already') { exit 0 }
    exit 2
}
function Grab-Frame($t){
    $script:bmp.Dispose()
    $script:bmp = Capture-Win $t
    $script:words = OcrWords $script:bmp $t.X $t.Y
    $script:text = Join-Text $script:words
}

# 2026-10-14：冷启动主窗口渲染慢（实测进程起来后还要数秒），轮询等 90s；
# 进程压根没起时用 -ExePath 补拉起一次（Python 侧已先 os.startfile，这里只兜底）。
$script:SelfStarted = $false
$t = $null
$winStart = Get-Date
$winDeadline = $winStart.AddSeconds($WindowWaitSec)
$winBeat = $winStart
while ((Get-Date) -lt $winDeadline) {
    $t = Find-QoderWindow
    if ($t) { break }
    if (-not $script:SelfStarted -and $ExePath -and (Test-Path $ExePath)) {
        $procs = @(Get-Process | Where-Object { $_.ProcessName -like "*$ProcessName*" })
        if ($procs.Count -eq 0) {
            Log "无进程，自愈启动 $ExePath"
            Start-Process $ExePath
            $script:SelfStarted = $true
        }
    }
    # 心跳：Python 侧最多再等 30s，两边都不打日志时主人只会看到黑框不动。
    if (((Get-Date) - $winBeat).TotalSeconds -ge 10) {
        Log ("window wait: " + [int]((Get-Date) - $winStart).TotalSeconds + "s / " + $WindowWaitSec + "s")
        $winBeat = Get-Date
    }
    Start-Sleep -Seconds 2
}
if (-not $t) {
    try { Log-WindowProbe } catch {}
    Out-Json "notfound" ("等待 " + $WindowWaitSec + "s 仍未出现 Qoder CN 主窗口（客户端没开、仍处最小化或冷启动失败；本次窗口探针已写 logs/ps1_qodercn.log）")
}

$hwnd=$t.Hwnd
$script:Hwnd=$hwnd
Log ("window hwnd=$hwnd rect=$($t.X),$($t.Y) $($t.W)x$($t.H)")
# R1 双保险：上一次异常退出可能把窗口留在屏外（Electron 还会持久化位置）。
# 整窗完全在虚拟桌面外时先拨回屏内，再保存/使用 rect；部分越界是用户自己的状态，不动。
$vLeft = [Q]::GetSystemMetrics(76); $vTop = [Q]::GetSystemMetrics(77)
$vW = [Q]::GetSystemMetrics(78); $vH = [Q]::GetSystemMetrics(79)
# 「只剩条带」也算残留：上次被强杀时窗口可能就停在 vLeft - w + 48 且 topmost；
# 若不处理，下次会把条带位置当 OriginalRect，永远恢复不回来。
$residualStrip = ($t.X + $t.W) -le ($vLeft + $OffscreenStripPx + 16)
if ($residualStrip -or $t.X -ge ($vLeft + $vW) -or
    ($t.Y + $t.H) -le $vTop -or $t.Y -ge ($vTop + $vH)) {
    Log ("residual offscreen/strip rect $($t.X),$($t.Y) $($t.W)x$($t.H); move back on-screen")
    [void][Q]::SetWindowPos($hwnd,[IntPtr](-2),0,0,0,0,0x0013)  # HWND_NOTOPMOST
    [void][Q]::SetWindowPos($hwnd,[IntPtr]::Zero,[Math]::Max(0,$vLeft),[Math]::Max(0,$vTop),0,0,0x0015)
    Start-Sleep -Milliseconds 300
    $t = Read-Rect $hwnd
    $hwnd = $t.Hwnd
}
if ($Offscreen) {
    # 空闲闸门必须在任何窗口动作之前：主人正在用电脑时连还原/搬窗都不要做。
    Wait-UserIdle
    $script:ForegroundBefore = [Q]::GetForegroundWindow()
    # 方案甲 M1：最大化窗口即使留条带也抓不到（Chromium 不合成），先还原
    # （收尾时再最大化回去）。还原后先在屏内等 2s，让 renderer 按新尺寸重绘。
    if ([Q]::IsZoomed($hwnd)) {
        $script:WasZoomed = $true
        [void][Q]::ShowWindow($hwnd,9)   # SW_RESTORE
        Start-Sleep -Milliseconds 2000
        $t = Read-Rect $hwnd
        $hwnd = $t.Hwnd
        Log ("window was maximized; restored for offscreen flow rect=$($t.X),$($t.Y) $($t.W)x$($t.H)")
    }
    # 2026-10-29：ShowWindow(9) 会把最大化窗口还原成 1948x1094，侧栏底部（账户 /
    # 用量入口）被挤到视口外，底栏锚点只剩工作区名。放到接近屏高的尺寸再停屏外，
    # 保证「用户名 → 权益中心」和底栏图标都在画面里。收尾按 OriginalRect/最大化恢复。
    $script:OriginalRect = @{X=$t.X;Y=$t.Y;W=$t.W;H=$t.H}
    $sw = [Q]::GetSystemMetrics(0)
    $sh = [Q]::GetSystemMetrics(1)
    $targetW = [Math]::Min([Math]::Max($t.W, 3600), $sw - 40)
    $targetH = [Math]::Min([Math]::Max($t.H, 2090), $sh - 40)
    if ($t.W -lt $targetW -or $t.H -lt $targetH) {
        [void][Q]::SetWindowPos($hwnd, [IntPtr]::Zero, $t.X, $t.Y, $targetW, $targetH, 0x0004)
        Start-Sleep -Milliseconds 2200
        $t = Read-Rect $hwnd
        $hwnd = $t.Hwnd
        Log ("window resized for offscreen flow rect=$($t.X),$($t.Y) $($t.W)x$($t.H)")
    }
    Move-OffscreenNow
    Log ("step: 窗口已停到屏外条带（留 $OffscreenStripPx px，原 rect $($t.X),$($t.Y) $($t.W)x$($t.H)）")
} else {
    # 旧行为：先把 IDE 抢到前台再抓第一帧：桌面可能叠着别的窗口（实测点错图标会拉起 Edge 盖住 IDE）
    [void](Ensure-Foreground $hwnd)
}

$script:bmp = Capture-Win $t
$script:words = OcrWords $script:bmp $t.X $t.Y
$script:text = Join-Text $script:words
if ($Explore) {
    Log ("--- OCR words (" + $script:words.Count + ") 截图 " + $shotPath + " ---")
    # 2026-10-29：导航排查看全量词表（屏幕坐标 + 图像坐标），不再只过滤签到相关词。
    try {
        $all = $script:words | ForEach-Object {
            "{0}`tscreen={1},{2}`timg={3},{4}" -f $_.text, $_.sx, $_.sy, $_.ix, $_.iy
        }
        [System.IO.File]::WriteAllLines("$root\logs\qoder_ocr_all.txt", $all,
            (New-Object System.Text.UTF8Encoding($false)))
    } catch {}
    foreach($w in $script:words){ if($w.text -match '领取|用量|查看|专属|每天|Credit|礼盒|权益|已领'){ Log ("  ["+$w.text+"] screen("+$w.sx+","+$w.sy+")") } }
    $u=Find-Username $script:bmp $t $script:words; if($u){ Log ("  用户名锚点 screen("+$u.sx+","+$u.sy+") uname="+$u.uname) }
    $uc=@(Find-UsernameCandidates $script:words $t); if($uc -and $uc.Count -gt 0){ Log ("  用户名候选: " + (($uc | ForEach-Object { $_.text }) -join " | ")) }
    Log ("  popup="+ (Test-CampaignPopup $script:text) + " claimed=" + (Test-Claimed $script:text))
    Out-Json "explore" ("OCR 词数=" + $script:words.Count)
}

if ($Usage) {
    # -Usage：只做一件事——把「我的用量」小窗点开一次。客户端是在**面板打开时**才向
    # 服务端取用量并把响应摘要写进自己的日志（me/usage -> main.log 的「用量响应摘要」），
    # 所以「有没有取到新数」不由这里判断，交给 agent_credit/qodercn_credits.py 的
    # 新鲜度闸门裁定（它只认当天的记录）。这里宁可不点错：每个候选点一次、验证、
    # 不中就 Esc 复位；绝不连点（底栏点错会拉起 Edge，2026-10-13 实测过副作用）。
    # -Usage -DryRun：只报锚点与候选坐标、不抢前台不点击。可以先在无副作用的前提下
    # 验证图标判据对不对（agent 子进程里跑也安全）。
    if ($DryRun) {
        $cu = @(Find-UsernameCandidates $script:words $t)
        if ($cu.Count -eq 0) { Out-Json "pending" "底栏没定位到用户名锚点" }
        $du = $cu[0]
        $dg = @(Find-UsageGaugeCandidates $script:bmp $t $du)
        Log ("usage-dry: 用户名 '" + $du.text + "' box ix=" + $du.ix + " iy=" + $du.iy +
             " iw=" + $du.iw + " ih=" + $du.ih + " 图标簇候选 " + $dg.Count + " 个：" +
             (($dg | ForEach-Object { "img(" + $_.ix + "," + $_.iy + ")" }) -join " "))
        Log ("usage-dry: 兜底偏移候选 img(" + [int]($du.ix+$du.iw+204) + "," + [int]($du.iy+$du.ih/2) + ")")
        Out-Json "dryrun" "已定位用量仪表候选，未点击"
    }
    if (-not $Offscreen -and -not (Ensure-Foreground $hwnd)) { Out-Json "pending" "无法确认 Qoder 处于前台（桌面有重叠窗口），为安全起见不点击" }
    $opened = $false
    foreach ($round in 1..2) {
        Grab-Frame $t
        $cands = @(Find-UsernameCandidates $script:words $t)
        if (-not $cands -or $cands.Count -eq 0) { Out-Json "pending" "底栏没定位到用户名锚点，找不到用量入口" }
        $u = $cands[0]
        # 2026-10-30：只点第一枚（油表=我的用量）；后面的簇是齿轮（设置），
        # 点到会打开设置面板，宁可 pending 也不要误点。
        $gauge = @(Find-UsageGaugeCandidates $script:bmp $t $u | Select-Object -First 1)
        if ($gauge.Count -eq 0) { Out-Json "pending" "底栏没扫到「我的用量」油表图标（布局可能改版）" }
        Log ("usage: 锚点 '$($u.text)' 油表候选 " + $gauge.Count + " 个（第 $round 轮）")
        foreach ($gc in $gauge) {
            $before = @($script:words)
            # 屏外模式：用量仪表在 webview 底栏，合成消息不可靠，直接一次 BringBack
            # 真实点击（暴露 ~0.5s）；非屏外仍走原来的抢前台 + SendInput。
            if ($Offscreen) { [void](Click-At $gc.ix $gc.iy -SkipSynth) } else { [void](Click-At $gc.ix $gc.iy) }
            Start-Sleep -Milliseconds 1600
            Grab-Frame $t
            if (Test-UsagePopover $before $script:words) { $opened = $true; Log ("usage: 小窗已开 img($($gc.ix),$($gc.iy))"); break }
            Send-EscSafe; Start-Sleep -Milliseconds 400
            Grab-Frame $t
        }
        if ($opened) { break }
    }
    Send-EscSafe
    if ($opened) { Out-Json "ok" "已点开「我的用量」小窗（是否取到新用量由对账闸门判定）" }
    Out-Json "pending" "点了用户名右侧的图标簇但没见「我的用量」小窗出现（底栏可能改版）。手动点开一次后执行: credit sync --only qodercn"
}

$granted = Get-Granted $script:text
$popupNow = Test-CampaignPopup $script:text
# 幂等：只有在活动弹窗确实可见时，「已领取/不可领取」才算数（聊天面板常年出现这些词）
if ($popupNow -and (Test-Claimed $script:text)) {
    Out-Json "already" "活动弹窗显示已领取/不可领取，今日无需重复领取"
}

# 情况一：启动自动弹窗已在 -> 直接找黑药丸「领取」
$claim = $null
if ($popupNow) { $claim = Find-BlackPill $script:bmp $t }

# 情况二：弹窗不在 -> 用户名 -> 权益中心 -> 弹窗（2026-10-16 改版后的新路径）
if (-not $claim) {
    if (-not $Offscreen -and -not (Ensure-Foreground $hwnd)) { Out-Json "pending" "无法确认 Qoder 处于前台（桌面有重叠窗口），为安全起见不点击" }
    # Esc 先关掉可能开着的「我的用量」等浮层（弹窗不在时 Esc 无副作用；实测浮层开着时第一击只会关掉浮层）
    Send-EscSafe; Start-Sleep -Milliseconds 400
    # 2026-10-20：每轮重抓帧、重解析锚点，按「底栏最左」排序逐候选点击——旧逻辑
    # 首帧定死一个锚点连点两轮，选中工作区名（agent-c..）时开不了账户菜单，
    # 直接 pending 收场。任一候选点出「权益中心」即通过；候选间先 Esc 清场。
    $menuOpen = $false
    $qy = $null
    foreach ($round in 1..2) {
        Grab-Frame $t
        $cands = @(Find-UsernameCandidates $script:words $t)
        if (-not $cands -or $cands.Count -eq 0) { Out-Json "pending" "底栏没定位到用户名锚点，无法展开账户菜单（界面可能再次改版）" }
        foreach ($u in $cands) {
            Log ("展开账户菜单（第 $round 轮）锚点 '$($u.text)' img($($u.cx),$($u.cy))")
            # 第一级：合成消息（零暴露）。Qoder 的菜单是 webview 叠加层，实测不一定
            # 响应合成鼠标；没开出菜单就用同一锚点补一次 BringBack 真实点击再等一轮。
            $hit = $null
            [void](Click-At $u.cx $u.cy)
            foreach ($waitMs in 1400, 2300) {
                Start-Sleep -Milliseconds $waitMs
                Grab-Frame $t
                $hit = Find-MenuItem $script:words $t @{sy=$u.sy} '权益中心'
                if ($hit) { break }
            }
            if (-not $hit -and $Offscreen) {
                Log "menu not opened by synth; retry with bringback real click"
                [void](Click-At $u.cx $u.cy -SkipSynth)
                foreach ($waitMs in 1400, 2300) {
                    Start-Sleep -Milliseconds $waitMs
                    Grab-Frame $t
                    $hit = Find-MenuItem $script:words $t @{sy=$u.sy} '权益中心'
                    if ($hit) { break }
                }
            }
            if ($hit) { $qy = $hit; $menuOpen = $true; Log ("菜单「权益中心」img($($qy.cx),$($qy.cy))"); break }
            # 这个候选没点开菜单（可能就是工作区名）-> Esc 清掉它拉起的浮层，换下一个
            Send-EscSafe; Start-Sleep -Milliseconds 300
        }
        if ($menuOpen) { break }
    }
    if (-not $menuOpen) { Out-Json "pending" "点用户名后未在左侧菜单找到「权益中心」（菜单文案/布局可能改版）" }
    $popupNow = $false
    [void](Click-At $qy.cx $qy.cy)
    Start-Sleep -Milliseconds 1800
    Grab-Frame $t
    $popupNow = Test-CampaignPopup $script:text
    if (-not $popupNow -and $Offscreen) {
        Log "popup not opened by synth; retry with bringback real click"
        [void](Click-At $qy.cx $qy.cy -SkipSynth)
        Start-Sleep -Milliseconds 1800
        Grab-Frame $t
        $popupNow = Test-CampaignPopup $script:text
    }
    if (-not $popupNow) {
        # 个别情况下浮窗出得慢，再等一轮
        Start-Sleep -Milliseconds 1500; Grab-Frame $t; $popupNow = Test-CampaignPopup $script:text
    }
    if (-not $popupNow) { Out-Json "pending" "点了「权益中心」但没出现活动弹窗（弹窗可能再次改版或被其他浮层挡住）" }
    if (Test-Claimed $script:text) { Out-Json "already" "活动弹窗显示已领取，今日无需重复领取" }
    $granted = Get-Granted $script:text
    $claim = Find-BlackPill $script:bmp $t
}

if (-not $claim) {
    Out-Json "pending" "活动弹窗已出现但没定位到可点的黑药丸「领取」（可能今日已领或按钮样式改版）。可手动确认后执行: credit record qodercn claimed 100"
}
Log ("定位到「领取」img(" + $claim.ix + "," + $claim.iy + ")，额度=" + $granted)
if ($DryRun) { Out-Json "dryrun" ("已定位「领取」，未点击") }

if (-not $Offscreen -and -not (Ensure-Foreground $hwnd)) { Out-Json "pending" "点击「领取」前无法确认前台，已放弃点击" }
# 领取按钮实测不吃合成鼠标消息（webview），屏外模式直接跳 BringBack 真实点击。
[void](Click-At $claim.ix $claim.iy -SkipSynth)
Start-Sleep -Milliseconds 2200
Grab-Frame $t
if ((Test-Claimed $script:text)) {
    $msg = "领取成功"; if ($granted -gt 0) { $msg += " [granted] $granted" }
    Out-Json "ok" $msg
}
# 复核兜底：领取后黑药丸变灰「已领取」，黑块检测应消失
$still = Find-BlackPill $script:bmp $t
if (-not $still) {
    $msg = "领取成功（黑药丸已消失）"; if ($granted -gt 0) { $msg += " [granted] $granted" }
    Out-Json "ok" $msg
}
Out-Json "pending" "点击了「领取」但复核未见成功信号（可能需二次确认或文案改版），请手动确认"
