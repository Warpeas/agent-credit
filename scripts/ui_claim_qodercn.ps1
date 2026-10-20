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
#   2) 抓图用 CopyFromScreen(窗口矩形) 而非 PrintWindow(主窗口)：菜单/弹窗可能是
#      叠在主窗口上的独立层，PrintWindow 只渲染主窗口自身会漏掉它；抢前台后 CopyFromScreen
#      抓到的是屏幕上真实内容（含叠加层）。
#   3) 每次点击前抢前台并核对 GetForegroundWindow 确属 Qoder，否则宁可 pending 也不点，
#      免得把点击送进重叠的其它 App（实测桌面可能叠着别的 agent 会话窗口）。
param(
    [switch]$DryRun,
    [switch]$Explore,
    [string]$OutFile,
    [string]$ProcessName = 'Qoder CN',
    [string]$ExePath = ''
)
$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$root = Split-Path -Parent $PSScriptRoot
$logPath = "$root\logs\ps1_qodercn.log"
$shotPath = "$root\logs\_qoder_shot.png"
function Log($m){ $s=(Get-Date -Format "HH:mm:ss")+" "+$m; try{[System.IO.File]::AppendAllText($logPath,$s+"`n",(New-Object System.Text.UTF8Encoding($false)))}catch{}; [Console]::Error.WriteLine($s) }
trap {
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
  [StructLayout(LayoutKind.Sequential)] public struct MOUSEINPUT { public int dx; public int dy; public uint mouseData; public uint dwFlags; public uint time; public UIntPtr dwExtraInfo; }
  [StructLayout(LayoutKind.Explicit)] public struct INPUT { [FieldOffset(0)] public uint type; [FieldOffset(8)] public MOUSEINPUT mi; }
  [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr h);
  [DllImport("user32.dll")] public static extern bool ShowWindow(IntPtr h, int c);
  [DllImport("user32.dll")] public static extern bool GetWindowRect(IntPtr h, out R r);
  [DllImport("user32.dll")] public static extern IntPtr GetForegroundWindow();
  [DllImport("user32.dll")] public static extern bool SetCursorPos(int x, int y);
  [DllImport("user32.dll")] public static extern uint SendInput(uint n, INPUT[] p, int cb);
  [DllImport("user32.dll")] public static extern void keybd_event(byte vk, byte scan, uint flags, UIntPtr extra);
  [DllImport("shcore.dll")] public static extern int SetProcessDpiAwareness(int a);
  // 用 SendInput 发真实点击（mouse_event 在本机对 Qoder 的 webview 落不进去，只有 SetCursorPos 的 hover 生效）
  public static void Click(int x, int y) {
    SetCursorPos(x, y);
    Thread.Sleep(120);
    INPUT[] arr = new INPUT[1];
    arr[0].type = 0; arr[0].mi.dx = 0; arr[0].mi.dy = 0; arr[0].mi.mouseData = 0;
    arr[0].mi.dwFlags = 0x0002; arr[0].mi.time = 0; arr[0].mi.dwExtraInfo = UIntPtr.Zero; // LEFTDOWN
    SendInput(1, arr, Marshal.SizeOf(typeof(INPUT)));
    Thread.Sleep(80);
    arr[0].mi.dwFlags = 0x0004;                                                            // LEFTUP
    SendInput(1, arr, Marshal.SizeOf(typeof(INPUT)));
  }
}
"@
Add-Type $sig
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
function Find-QoderWindow {
    # 只要「够大且不在最小化位置(-32000)」的主窗口。2026-10-16 实测最小化时枚举会撞上
    # 一个 314x50 的辅助窗口（rect=-32000,-32000），旧逻辑按最大面积选中它后全链路锚点失效。
    $pids = @(Get-Process | Where-Object { $_.ProcessName -like "*$ProcessName*" } | ForEach-Object { $_.Id })
    $best=$null
    foreach ($p in Get-Process) {
        if ($p.MainWindowHandle -eq [IntPtr]::Zero) { continue }
        if ($pids -notcontains $p.Id) { continue }
        $c=Read-Rect $p.MainWindowHandle
        if ($c.W -lt 600 -or $c.H -lt 400) { continue }
        if ($c.X -le -10000 -or $c.Y -le -10000) { continue }
        if (-not $best -or $c.Area -gt $best.Area) { $best=$c }
    }
    return $best
}

# 抓窗口矩形对应的屏幕区域 -> 位图（供 OCR 与像素扫描）
function Capture-Win($t) {
    $bmp = New-Object System.Drawing.Bitmap($t.W, $t.H)
    $g = [System.Drawing.Graphics]::FromImage($bmp)
    $g.CopyFromScreen($t.X, $t.Y, 0, 0, (New-Object System.Drawing.Size $t.W,$t.H))
    $g.Dispose()
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
function Find-BlackPill($bmp,$t) {
    $y0=[int]($t.H*0.40); $y1=[int]($t.H*0.72); $x0=[int]($t.W*0.40); $x1=[int]($t.W*0.74)
    function IsBlack($x,$y){ if($x -lt 0 -or $y -lt 0 -or $x -ge $bmp.Width -or $y -ge $bmp.Height){return $false}; $p=$bmp.GetPixel($x,$y); $r=[int]$p.R;$g=[int]$p.G;$b=[int]$p.B; $lum=($r+$g+$b)/3; $mx=[Math]::Max($r,[Math]::Max($g,$b)); $mn=[Math]::Min($r,[Math]::Min($g,$b)); return ($lum -lt 95) -and (($mx-$mn) -lt 40) }
    $win=96; $step=3
    for($y=$y0+20; $y -lt $y1-20;$y+=3){
        for($x=$x0; $x -lt ($x1-$win);$x+=4){
            $nb=0; $tot=0
            for($k=0;$k -lt $win;$k+=$step){ $tot++; if((IsBlack ($x+$k) $y)){$nb++} }
            if($tot -gt 0 -and ($nb/$tot) -gt 0.70){
                $cx=[int]($x+$win/2)
                if((IsBlack $cx ($y-14)) -and (IsBlack $cx ($y+14))){
                    Log ("blackpill: HIT img($cx,$y) dens=" + [math]::Round($nb/$tot,2))
                    return @{ ix=$cx; iy=$y }
                }
            }
        }
    }
    Log "blackpill: no hit"
    return $null
}
function Get-Granted($text){ if($text -match '每天领\D{0,3}(\d+)'){return [int]$matches[1]}; if($text -match '\+\s*(\d+)\s*Credit'){return [int]$matches[1]}; return 0 }

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
function Click-Screen([int]$x,[int]$y){
    [Q]::Click($x,$y)
    Log ("click screen($x,$y)")
}
function Out-Json([string]$status,[string]$detail){
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
$winDeadline = (Get-Date).AddSeconds(90)
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
    Start-Sleep -Seconds 2
}
if (-not $t) { Out-Json "notfound" "等待 90s 仍未出现 Qoder CN 主窗口（客户端没开、仍处最小化或冷启动失败）" }
$hwnd=$t.Hwnd
Log ("window hwnd=$hwnd rect=$($t.X),$($t.Y) $($t.W)x$($t.H)")
# 先把 IDE 抢到前台再抓第一帧：桌面可能叠着别的窗口（实测点错图标会拉起 Edge 盖住 IDE）
[void](Ensure-Foreground $hwnd)

$script:bmp = Capture-Win $t
$script:words = OcrWords $script:bmp $t.X $t.Y
$script:text = Join-Text $script:words
if ($Explore) {
    Log ("--- OCR words (" + $script:words.Count + ") 截图 " + $shotPath + " ---")
    foreach($w in $script:words){ if($w.text -match '领取|用量|查看|专属|每天|Credit|礼盒|权益|已领'){ Log ("  ["+$w.text+"] screen("+$w.sx+","+$w.sy+")") } }
    $u=Find-Username $script:bmp $t $script:words; if($u){ Log ("  用户名锚点 screen("+$u.sx+","+$u.sy+") uname="+$u.uname) }
    $uc=@(Find-UsernameCandidates $script:words $t); if($uc -and $uc.Count -gt 0){ Log ("  用户名候选: " + (($uc | ForEach-Object { $_.text }) -join " | ")) }
    Log ("  popup="+ (Test-CampaignPopup $script:text) + " claimed=" + (Test-Claimed $script:text))
    Out-Json "explore" ("OCR 词数=" + $script:words.Count)
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
    if (-not (Ensure-Foreground $hwnd)) { Out-Json "pending" "无法确认 Qoder 处于前台（桌面有重叠窗口），为安全起见不点击" }
    # Esc 先关掉可能开着的「我的用量」等浮层（弹窗不在时 Esc 无副作用；实测浮层开着时第一击只会关掉浮层）
    Send-Esc; Start-Sleep -Milliseconds 400
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
            Log ("展开账户菜单（第 $round 轮）锚点 '$($u.text)' screen($($u.sx),$($u.sy))")
            Click-Screen $u.sx $u.sy
            $hit = $null
            foreach ($waitMs in 1400, 2300) {
                Start-Sleep -Milliseconds $waitMs
                Grab-Frame $t
                $hit = Find-MenuItem $script:words $t @{sy=$u.sy} '权益中心'
                if ($hit) { break }
            }
            if ($hit) { $qy = $hit; $menuOpen = $true; Log ("菜单「权益中心」screen($($qy.sx),$($qy.sy))"); break }
            # 这个候选没点开菜单（可能就是工作区名）-> Esc 清掉它拉起的浮层，换下一个
            Send-Esc; Start-Sleep -Milliseconds 300
        }
        if ($menuOpen) { break }
    }
    if (-not $menuOpen) { Out-Json "pending" "点用户名后未在左侧菜单找到「权益中心」（菜单文案/布局可能改版）" }
    Click-Screen $qy.sx $qy.sy
    Start-Sleep -Milliseconds 1800
    Grab-Frame $t
    $popupNow = Test-CampaignPopup $script:text
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
Log ("定位到「领取」screen(" + $claim.ix + "," + $claim.iy + ")，额度=" + $granted)
if ($DryRun) { Out-Json "dryrun" ("已定位「领取」，未点击") }

if (-not (Ensure-Foreground $hwnd)) { Out-Json "pending" "点击「领取」前无法确认前台，已放弃点击" }
# claim 是相对窗口位图的坐标 -> 换算屏幕坐标
Click-Screen ($t.X + $claim.ix) ($t.Y + $claim.iy)
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
