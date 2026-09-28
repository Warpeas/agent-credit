# LobsterAI daily check-in: -Explore (layout only, no click) / default (claim).
# ASCII code only. Same pattern as MiniMax: runas-elevated launch, wait for the
# WINDOW (not just the process), poll until the loading screen is gone, OCR, click.
param(
    [switch]$Explore,
    [switch]$Verify,
    # Phase separation: with -NoLaunch this script NEVER starts the app; it only
    # operates on an already-running window (fails fast with notfound otherwise).
    # Lets recognize/claim/verify run repeatedly without re-launching.
    [switch]$NoLaunch,
    [string]$OutFile = ""
)
$ErrorActionPreference = "Stop"
$logPath = "C:\Users\Hunter\Documents\Warpeas\agent-credit\logs\_lobsterai_log.txt"
function Log($m){ $s=(Get-Date -Format "HH:mm:ss")+" "+$m; try{[System.IO.File]::AppendAllText($logPath,$s+"`n",(New-Object System.Text.UTF8Encoding($false)))}catch{}; Write-Output $s }
try {
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
Add-Type -AssemblyName System.Drawing
Add-Type -AssemblyName System.Runtime.WindowsRuntime
Add-Type @"
using System; using System.Runtime.InteropServices; using System.Text;
public static class L32 {
  [DllImport("user32.dll")] public static extern bool SetProcessDPIAware();
  [DllImport("user32.dll")] public static extern bool GetWindowRect(IntPtr h, out RECT r);
  [DllImport("user32.dll")] public static extern IntPtr GetForegroundWindow();
  [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr h);
  [DllImport("user32.dll")] public static extern bool ShowWindow(IntPtr h, int n);
  [DllImport("user32.dll")] public static extern bool EnumWindows(EnumProc cb, IntPtr lp);
  [DllImport("user32.dll")] public static extern uint GetWindowThreadProcessId(IntPtr h, out uint pid);
  [DllImport("user32.dll")] public static extern bool IsWindowVisible(IntPtr h);
  [DllImport("user32.dll")] public static extern int GetWindowText(IntPtr h, StringBuilder s, int n);
  [DllImport("user32.dll")] public static extern bool SetCursorPos(int X, int Y);
  [DllImport("user32.dll")] public static extern void mouse_event(uint flags, uint dx, uint dy, uint data, UIntPtr extra);
  [DllImport("user32.dll")] public static extern bool PrintWindow(IntPtr h, IntPtr hdcBlt, uint nFlags);
  [DllImport("user32.dll")] public static extern IntPtr SendMessageTimeout(IntPtr h, uint msg, UIntPtr wParam, IntPtr lParam, uint fuFlags, uint uTimeout, out IntPtr lpdwResult);
  [DllImport("user32.dll")] public static extern bool ScreenToClient(IntPtr h, ref POINT lpPoint);
  [DllImport("user32.dll")] public static extern IntPtr WindowFromPoint(POINT p);
  [DllImport("user32.dll")] public static extern IntPtr ChildWindowFromPointEx(IntPtr h, POINT p, uint flags);
  public struct RECT { public int Left, Top, Right, Bottom; }
  public struct POINT { public int X, Y; }
  public delegate bool EnumProc(IntPtr h, IntPtr lp);
}
"@
$null = [Windows.Media.Ocr.OcrEngine, Windows.Foundation, ContentType = WindowsRuntime]
$null = [Windows.Globalization.Language, Windows.Foundation, ContentType = WindowsRuntime]
$null = [Windows.Graphics.Imaging.SoftwareBitmap, Windows.Foundation, ContentType = WindowsRuntime]
$null = [Windows.Storage.Streams.InMemoryRandomAccessStream, Windows.Foundation, ContentType = WindowsRuntime]
$asTask = ([System.WindowsRuntimeSystemExtensions].GetMethods() | Where-Object { $_.Name -eq 'AsTask' -and $_.GetParameters().Count -eq 1 -and $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncOperation`1' })[0]
function Await($op,$t){ $m=$asTask.MakeGenericMethod($t); $x=$m.Invoke($null,@($op)); $x.Wait(-1)|Out-Null; return $x.Result }

[void][L32]::SetProcessDPIAware()
$exe='C:\Users\Hunter\AppData\Local\Programs\LobsterAI\LobsterAI.exe'
$AppProcess='LobsterAI'
$shotPath='C:\Users\Hunter\Documents\Warpeas\agent-credit\logs\lobsterai_shot.png'
$ocrPath='C:\Users\Hunter\Documents\Warpeas\agent-credit\logs\lobsterai_explore_ocr.txt'
$frameDir='C:\Users\Hunter\Documents\Warpeas\agent-credit\logs'

function Get-PidSet { $s=@{}; Get-Process $AppProcess -ErrorAction SilentlyContinue | ForEach-Object { $s[[uint32]$_.Id]=$true }; return $s }

function Find-AppWindow($pids) {
    $script:BestHwnd=[IntPtr]::Zero; $script:BestArea=0
    if($pids.Count -eq 0){ return [IntPtr]::Zero }
    $cb=[L32+EnumProc]{
        param($h,$lp)
        $o=[uint32]0; [L32]::GetWindowThreadProcessId($h,[ref]$o)|Out-Null
        if($pids.ContainsKey($o)){
            $r=New-Object L32+RECT; [L32]::GetWindowRect($h,[ref]$r)|Out-Null
            $w=$r.Right-$r.Left; $hh=$r.Bottom-$r.Top
            if($w-gt 500 -and $hh -gt 400 -and ($w*$hh) -gt $script:BestArea){ $script:BestHwnd=$h; $script:BestArea=$w*$hh }
        }
        return $true
    }
    [L32]::EnumWindows($cb,[IntPtr]::Zero)|Out-Null
    return $script:BestHwnd
}

function Find-ByTitle {
    $script:TBest=[IntPtr]::Zero; $script:TArea=0
    $cb=[L32+EnumProc]{
        param($h,$lp)
        if([L32]::IsWindowVisible($h)){
            $sb=New-Object System.Text.StringBuilder 256
            [L32]::GetWindowText($h,$sb,256)|Out-Null
            if($sb.ToString() -match '(?i)lobster'){
                $r=New-Object L32+RECT; [L32]::GetWindowRect($h,[ref]$r)|Out-Null
                $w=$r.Right-$r.Left; $hh=$r.Bottom-$r.Top
                if($w-gt 500 -and $hh -gt 400 -and ($w*$hh) -gt $script:TArea){ $script:TBest=$h; $script:TArea=$w*$hh }
            }
        }
        return $true
    }
    [L32]::EnumWindows($cb,[IntPtr]::Zero)|Out-Null
    return $script:TBest
}

$pidSet = Get-PidSet
$script:LaunchedByUs = $false
Log ("preexisting procs="+$pidSet.Count)
$hwnd=[IntPtr]::Zero
if($pidSet.Count -gt 0){ $hwnd = Find-AppWindow $pidSet; Log ("existing window="+$hwnd) }

if($hwnd -eq [IntPtr]::Zero -and $NoLaunch){
    Log "NoLaunch set and app not running"
    Restore-Scene; if($OutFile){ [System.IO.File]::WriteAllText($OutFile,'{"status":"notfound","detail":"app not running (run the launcher first)"}',(New-Object System.Text.UTF8Encoding($false))) }
    exit 1
}
if($hwnd -eq [IntPtr]::Zero){
    if(Test-Path $exe){ Log "launching LobsterAI"; Start-Process $exe; $script:LaunchedByUs = $true } else { Log "EXE MISSING" }
    $dl=(Get-Date).AddSeconds(70)
    while((Get-Date) -lt $dl){
        Start-Sleep -Seconds 2
        $pidSet = Get-PidSet
        $hwnd = Find-AppWindow $pidSet
        if($hwnd -ne [IntPtr]::Zero){ Log ("window appeared hwnd="+$hwnd); break }
    }
}
if($hwnd -eq [IntPtr]::Zero){ $hwnd = Find-ByTitle; if($hwnd -ne [IntPtr]::Zero){ Log ("found by title hwnd="+$hwnd) } }
if($hwnd -eq [IntPtr]::Zero){ Restore-Scene; Log "NO WINDOW"; if($OutFile){ [System.IO.File]::WriteAllText($OutFile,'{"status":"notfound","detail":"no main window"}',(New-Object System.Text.UTF8Encoding($false))) } exit 1 }

[void][L32]::ShowWindow($hwnd,9); Start-Sleep -Milliseconds 400; [void][L32]::SetForegroundWindow($hwnd); Start-Sleep -Milliseconds 700
$r=New-Object L32+RECT; [L32]::GetWindowRect($hwnd,[ref]$r)|Out-Null
$winX=$r.Left; $winY=$r.Top; $winW=$r.Right-$r.Left; $winH=$r.Bottom-$r.Top
Log ("RECT="+$winX+","+$winY+" "+$winW+"x"+$winH)

# --- OCR engine (built once) ---
$eng=[Windows.Media.Ocr.OcrEngine]::TryCreateFromLanguage([Windows.Globalization.Language]::new("zh-Hans-CN"))
if(-not $eng){ $eng=[Windows.Media.Ocr.OcrEngine]::TryCreateFromUserProfileLanguages() }
Log ("OCR engine="+$eng.RecognizerLanguage.LanguageTag)

function Test-Blank($bmp){
    $f=$bmp.GetPixel([int]($winW/2),[int]($winH/2))
    for($i=1;$i -le 8;$i++){
        $px=[int]($winW*$i/9)
        for($j=1;$j -le 8;$j++){
            $py=[int]($winH*$j/9)
            $c=$bmp.GetPixel($px,$py)
            if($c.R -ne $f.R -or $c.G -ne $f.G -or $c.B -ne $f.B){ return $false }
        }
    }
    return $true
}

function Get-OcrLines($pngPath) {
    $bmp=New-Object System.Drawing.Bitmap($winW,$winH)
    $g=[System.Drawing.Graphics]::FromImage($bmp)
    # PrintWindow captures the window itself: works while occluded / not in front.
    $hdc=$g.GetHdc()
    $pw=[L32]::PrintWindow($hwnd,$hdc,2)
    $g.ReleaseHdc($hdc)
    if(-not $pw -or (Test-Blank $bmp)){ $g.CopyFromScreen($winX,$winY,0,0,$bmp.Size) }
    $g.Dispose()
    if($pngPath){ $bmp.Save($pngPath,[System.Drawing.Imaging.ImageFormat]::Png) }
    $ms=New-Object System.IO.MemoryStream
    $bmp.Save($ms,[System.Drawing.Imaging.ImageFormat]::Png)
    $bmp.Dispose()
    $stream=New-Object Windows.Storage.Streams.InMemoryRandomAccessStream
    $dw=New-Object Windows.Storage.Streams.DataWriter($stream.GetOutputStreamAt(0))
    $dw.WriteBytes($ms.ToArray())
    Await ($dw.StoreAsync()) ([uint32])|Out-Null
    Await ($dw.FlushAsync()) ([bool])|Out-Null
    $dec=Await ([Windows.Graphics.Imaging.BitmapDecoder]::CreateAsync($stream)) ([Windows.Graphics.Imaging.BitmapDecoder])
    $sbmp=Await ($dec.GetSoftwareBitmapAsync()) ([Windows.Graphics.Imaging.SoftwareBitmap])
    $res=Await ($eng.RecognizeAsync($sbmp)) ([Windows.Media.Ocr.OcrResult])
    $lines=@()
    foreach($ln in $res.Lines){
        $t=($ln.Text-replace "\s","")
        if([string]::IsNullOrWhiteSpace($t)){ continue }
        $minX=999999;$minY=999999;$maxX=0;$maxY=0
        foreach($wd in $ln.Words){ $br=$wd.BoundingRect; if($br.X-lt$minX){$minX=[int]$br.X} if($br.Y-lt$minY){$minY=[int]$br.Y} if(($br.X+$br.Width)-gt$maxX){$maxX=[int]($br.X+$br.Width)} if(($br.Y+$br.Height)-gt$maxY){$maxY=[int]($br.Y+$br.Height)} }
        $lines += @{ text=$t; x=$minX; y=$minY; w=($maxX-$minX); h=($maxY-$minY) }
    }
    return $lines
}

function Click-At($ax,$ay) {
    $sx=$winX+$ax; $sy=$winY+$ay

    # 1) Already in front -> real input injection (most reliable).
    if([L32]::GetForegroundWindow() -eq $hwnd){
        [void][L32]::SetCursorPos($sx,$sy)
        Start-Sleep -Milliseconds 150
        [L32]::mouse_event(0x0002,0,0,0,[UIntPtr]::Zero)
        Start-Sleep -Milliseconds 80
        [L32]::mouse_event(0x0004,0,0,0,[UIntPtr]::Zero)
        return
    }

    # 2) No foreground needed: deliver the click into the window's message queue.
    $sp=[L32+POINT]::new(); $sp.X=$sx; $sp.Y=$sy
    $top=[L32]::WindowFromPoint($sp)
    $target=$hwnd
    if($top -ne [IntPtr]::Zero){
        $pt=[uint32]0; [L32]::GetWindowThreadProcessId($top,[ref]$pt)|Out-Null
        $pm=[uint32]0; [L32]::GetWindowThreadProcessId($hwnd,[ref]$pm)|Out-Null
        if($pt -eq $pm){ $target=$top }
    }
    $cp=[L32+POINT]::new(); $cp.X=$sx; $cp.Y=$sy
    [L32]::ScreenToClient($target,[ref]$cp)|Out-Null
    for($k=0;$k -lt 4;$k++){
        $c=[L32]::ChildWindowFromPointEx($target,$cp,1)
        if($c -eq [IntPtr]::Zero -or $c -eq $target){ break }
        $target=$c
        $cp.X=$sx; $cp.Y=$sy
        [L32]::ScreenToClient($target,[ref]$cp)|Out-Null
    }
    $lp=[IntPtr]((($cp.Y -band 0xFFFF)*65536) -bor ($cp.X -band 0xFFFF))
    $res=[IntPtr]::Zero
    [L32]::SendMessageTimeout($target,0x0200,[UIntPtr]::Zero,$lp,0,1000,[ref]$res)|Out-Null
    Start-Sleep -Milliseconds 150
    $r1=[L32]::SendMessageTimeout($target,0x0201,[UIntPtr]::new([uint64]1),$lp,0,1500,[ref]$res)
    Start-Sleep -Milliseconds 90
    $r2=[L32]::SendMessageTimeout($target,0x0202,[UIntPtr]::Zero,$lp,0,1500,[ref]$res)
    if($r1 -ne [IntPtr]::Zero -and $r2 -ne [IntPtr]::Zero){ return }

    # 3) Last resort: real cursor input anyway.
    [void][L32]::SetCursorPos($sx,$sy)
    Start-Sleep -Milliseconds 150
    [L32]::mouse_event(0x0002,0,0,0,[UIntPtr]::Zero)
    Start-Sleep -Milliseconds 80
    [L32]::mouse_event(0x0004,0,0,0,[UIntPtr]::Zero)
}

$script:SavedForeground=[IntPtr]::Zero
function Save-Foreground {
    if($script:SavedForeground -eq [IntPtr]::Zero){
        $f=[L32]::GetForegroundWindow()
        if($f -ne $hwnd){ $script:SavedForeground=$f }
    }
}
function Restore-Foreground {
    try{ if($script:SavedForeground -ne [IntPtr]::Zero){ [void][L32]::SetForegroundWindow($script:SavedForeground) } }catch{}
}
# 运行结束一律恢复现场：关掉本次自己拉起的实例（签到前就开着的保留），
# 并把前台还给运行前那个窗口。失败也不留窗口——无人值守跑完桌面不该堆着客户端。
function Restore-Scene { Close-LaunchedApp; Restore-Foreground }

function Ensure-Foreground {
    Save-Foreground
    [void][L32]::ShowWindow($hwnd,9)
    Start-Sleep -Milliseconds 300
    [void][L32]::SetForegroundWindow($hwnd)
    Start-Sleep -Milliseconds 500
}

# Startup promo modal ("新用户专享 0.01 解锁 1000积分") covers the whole page and
# blocks everything. Dismiss: ESC first, then click the round X at the modal's
# top-right (~69% width, ~27% height of the window, measured 2026-09-28).
function Dismiss-Ads {
    $cap = Get-OcrLines ""
    $adLine=$null
    foreach($l in $cap){ if($l.text -match '新用户专享|立即解锁|自动续订|专享'){ if($null -eq $adLine -or $l.y -lt $adLine.y){ $adLine=$l } } }
    if(-not $adLine){ return $false }
    Log ("ad modal detected: "+$adLine.text)
    try { $ws=New-Object -ComObject WScript.Shell; $ws.SendKeys("{ESC}") } catch { }
    Start-Sleep -Milliseconds 1500
    $cap2 = Get-OcrLines ""
    $still=$false
    foreach($l in $cap2){ if($l.text -match '新用户专享|立即解锁|自动续订'){ $still=$true; break } }
    if($still){
        $cx=[int]($winW*0.690); $cy=[int]($winH*0.274)
        Log ("ad persists, clicking X at "+$cx+","+$cy)
        Click-At $cx $cy
        Start-Sleep -Milliseconds 1500
    }
    return $true
}

# 只关本次由脚本拉起的实例；签到前用户已开着的必须保留（三段式的「退出」步骤）。
function Close-LaunchedApp {
    if (-not $script:LaunchedByUs) { Log "keep client (was already running)"; return }
    Log "closing the client we launched"
    Start-Sleep -Seconds 2
    foreach($p in @(Get-Process $AppProcess -ErrorAction SilentlyContinue)){
        try { $p.CloseMainWindow() | Out-Null } catch { }
    }
    Start-Sleep -Seconds 5
    foreach($p in @(Get-Process $AppProcess -ErrorAction SilentlyContinue)){
        try { Stop-Process -Id $p.Id -Force -ErrorAction SilentlyContinue } catch { }
    }
}

# --- wait until the loading screen is gone (LobsterAI boots an "AI engine") ---
$lines=@()
$ready=$false
$dl2=(Get-Date).AddSeconds(110)
while((Get-Date) -lt $dl2){
    Start-Sleep -Seconds 6
    $lines = Get-OcrLines ""
    $loading=$false
    foreach($l in $lines){ if($l.text -match '启动中|正在启动|％|%$|加载中'){ $loading=$true; break } }
    Log ("poll lines="+$lines.Count+" loading="+$loading)
    if(-not $loading -and $lines.Count -gt 5){ $ready=$true; break }
}
Log ("ready="+$ready)
[void](Dismiss-Ads)

# final capture with screenshot
$lines = Get-OcrLines $shotPath
$out=New-Object System.Collections.ArrayList
[void]$out.Add("RECT="+$winX+","+$winY+" "+$winW+"x"+$winH)
foreach($l in $lines){ [void]$out.Add("LINE | "+$l.text+" | "+$l.x+","+$l.y+" "+$l.w+"x"+$l.h) }
[System.IO.File]::WriteAllText($ocrPath,($out -join "`n"),(New-Object System.Text.UTF8Encoding($false)))
Log ("OCR lines="+$out.Count)

if($Explore){ Log "EXPLORE done (no click)"; if($OutFile){ [System.IO.File]::WriteAllText($OutFile,'{"status":"explored","detail":"layout only"}',(New-Object System.Text.UTF8Encoding($false))) } exit 0 }

# --- VERIFY: open the bottom-left user bar and read today's check-in state ---
# Phase-2 only: never launches/closes anything else, safe to run repeatedly
# against an already-open client (no extra UAC beyond this run's elevation).
if($Verify){
    Ensure-Foreground
    [void](Dismiss-Ads)
    $lines = Get-OcrLines $shotPath
    $bar=$null
    foreach($l in $lines){ if($l.x -lt ($winW*0.15) -and $l.y -gt ($winH*0.80)){ $bar=$l; break } }
    if(-not $bar){ $bar = @{ text="(fallback)"; x=[int]($winW*0.03); y=[int]($winH*0.93); w=140; h=44 } }
    $bx=$bar.x+[int]($bar.w/2); $by=$bar.y+[int]($bar.h/2)
    Log ("verify: click user bar '"+$bar.text+"' at "+$bx+","+$by)
    Click-At $bx $by

    $verdict="unknown"; $hit=""; $unclaimed=$null; $giftRow=$null
    $vi=0
    foreach($delay in @(1500,2000,2500)){
        Start-Sleep -Milliseconds $delay
        $vi++
        $cap = Get-OcrLines ($frameDir+"\lobsterai_verify"+$vi+".png")
        $panel = ($cap | ForEach-Object { $_.text+"@"+$_.x+","+$_.y }) -join " | "
        Log ("verify frame"+$vi+": "+$panel.Substring(0,[Math]::Min(700,$panel.Length)))
        foreach($l in $cap){
            if($l.text -match '今日已签到|已签到|今日已领|已领取|连续签到|签到成功'){ $verdict="claimed"; $hit=$l.text }
            if(-not $giftRow -and $l.x -lt ($winW*0.35) -and $l.text -match '每日积分礼'){ $giftRow=$l }
            if(-not $unclaimed -and $l.x -lt ($winW*0.35) -and $l.text -match '立即领取'){ $unclaimed=$l }
        }
        if($verdict -ne "unknown"){ break }
    }
    if($verdict -eq "claimed"){
        Log ("VERIFY claimed: "+$hit)
        if($OutFile){ [System.IO.File]::WriteAllText($OutFile,'{"status":"ok","detail":"verify: '+$hit+'"}',(New-Object System.Text.UTF8Encoding($false))) }
        exit 0
    }
    if($unclaimed){
        Log ("VERIFY unclaimed: panel still shows the claim button")
        if($OutFile){ [System.IO.File]::WriteAllText($OutFile,'{"status":"unclaimed","detail":"claim button still shown"}',(New-Object System.Text.UTF8Encoding($false))) }
        exit 2
    }
    # This UI has NO "already claimed" text: after claiming, the 立即领取 button
    # simply disappears from the gift row (and the balance +100). Verified 00:25
    # -> 00:27 on 2026-09-28: 1000 -> 1100 with the button gone.
    if($giftRow){
        Log ("VERIFY claimed: gift row present but claim button gone")
        if($OutFile){ [System.IO.File]::WriteAllText($OutFile,'{"status":"ok","detail":"claim button gone from gift row"}',(New-Object System.Text.UTF8Encoding($false))) }
        exit 0
    }
    Log ("VERIFY inconclusive")
    Restore-Scene; if($OutFile){ [System.IO.File]::WriteAllText($OutFile,'{"status":"pending","detail":"verify inconclusive"}',(New-Object System.Text.UTF8Encoding($false))) }
    exit 2
}

# --- CLAIM ---
# Path A (preferred, found 2026-09-28): expand the bottom-left user panel; it
# always lists "每日积分礼" with either "立即领取" (unclaimed) or "今日已领"
# (claimed). More reliable than the top-right card, which comes and goes.
Ensure-Foreground
[void](Dismiss-Ads)
$lines = Get-OcrLines $shotPath

$bar=$null
foreach($l in $lines){ if($l.x -lt ($winW*0.15) -and $l.y -gt ($winH*0.80)){ $bar=$l; break } }

$claimBtn=$null; $alreadyHit=$null
if($bar){
    $bx=$bar.x+[int]($bar.w/2); $by=$bar.y+[int]($bar.h/2)
    Log ("open user panel '"+$bar.text+"' at "+$bx+","+$by)
    Click-At $bx $by
    $pi=0
    foreach($delay in @(1500,2000)){
        Start-Sleep -Milliseconds $delay
        $pi++
        $cap = Get-OcrLines ($frameDir+"\lobsterai_panel"+$pi+".png")
        $dump = ($cap | ForEach-Object { $_.text+"@"+$_.x+","+$_.y }) -join " | "
        Log ("panel"+$pi+": "+$dump.Substring(0,[Math]::Min(500,$dump.Length)))
        foreach($l in $cap){
            if(-not $alreadyHit -and $l.text -match '今日已领|已领取|已签到'){ $alreadyHit=$l }
            if(-not $claimBtn -and $l.x -lt ($winW*0.35) -and $l.text -match '立即领取'){ $claimBtn=$l }
        }
        if($claimBtn -or $alreadyHit){ break }
    }
}

if($alreadyHit){ Log ("already: "+$alreadyHit.text); Close-LaunchedApp; if($OutFile){ [System.IO.File]::WriteAllText($OutFile,'{"status":"already","detail":"'+$alreadyHit.text+'"}',(New-Object System.Text.UTF8Encoding($false))) } exit 0 }

if($claimBtn){
    $cx2=$claimBtn.x+[int]($claimBtn.w/2); $cy2=$claimBtn.y+[int]($claimBtn.h/2)
    Log ("click panel claim btn '"+$claimBtn.text+"' at "+$cx2+","+$cy2)
    Click-At $cx2 $cy2
    $okHit=$null
    foreach($delay in @(2000,2500,3000)){
        Start-Sleep -Milliseconds $delay
        $fcap = Get-OcrLines ""
        foreach($l in $fcap){ if($l.text -match '今日已领|已领|领取成功|成功'){ $okHit=$l } }
        if(-not $okHit){
            # This UI gives no "claimed" text: success = the 立即领取 button
            # disappears from the gift row (balance ticks up instead).
            $btnStill=$false; $rowStill=$false
            foreach($l in $fcap){
                if($l.x -lt ($winW*0.35)){
                    if($l.text -match '立即领取'){ $btnStill=$true }
                    if($l.text -match '每日积分礼'){ $rowStill=$true }
                }
            }
            if($rowStill -and -not $btnStill){ $okHit=@{ text="领取按钮消失，判定已领取" } }
        }
        if($okHit){ break }
    }
    if($okHit){ Log ("ok marker: "+$okHit.text); Close-LaunchedApp; if($OutFile){ [System.IO.File]::WriteAllText($OutFile,'{"status":"ok","detail":"'+$okHit.text+'"}',(New-Object System.Text.UTF8Encoding($false))) } exit 0 }
    Log "clicked panel claim, no confirm marker"
    Restore-Scene; if($OutFile){ [System.IO.File]::WriteAllText($OutFile,'{"status":"pending","detail":"clicked panel claim, no confirm"}',(New-Object System.Text.UTF8Encoding($false))) }
    exit 2
}

# Path B fallback: the top-right daily card
$anchor=$null
foreach($l in $lines){ if($l.text -match '每日积分礼'){ $anchor=$l } }
if(-not $anchor){ foreach($l in $lines){ if($l.text -match '积分礼'){ $anchor=$l } } }
if($anchor){
    $ax=$anchor.x+[int]($anchor.w/2); $ay=$anchor.y+[int]($anchor.h/2)
    Log ("fallback: click top-right card '"+$anchor.text+"' at "+$ax+","+$ay)
    Click-At $ax $ay
    $foundBtn=$null; $foundAlready=$null; $fi=0
    foreach($delay in @(1500,2000,2500)){
        Start-Sleep -Milliseconds $delay
        $fi++
        $cap = Get-OcrLines ($frameDir+"\lobsterai_frame"+$fi+".png")
        foreach($l in $cap){ if(-not $foundAlready -and $l.text -match '今日已领|已领取|本期已完成'){ $foundAlready=$l } }
        if(-not $foundBtn){ foreach($l in $cap){ if($l.text -match '立即领取|领取|签到'){ $foundBtn=$l } } }
        if($foundAlready){ break }
    }
    if($foundAlready){ Log ("already: "+$foundAlready.text); Close-LaunchedApp; if($OutFile){ [System.IO.File]::WriteAllText($OutFile,'{"status":"already","detail":"'+$foundAlready.text+'"}',(New-Object System.Text.UTF8Encoding($false))) } exit 0 }
    if($foundBtn){
        $bx2=$foundBtn.x+[int]($foundBtn.w/2); $by2=$foundBtn.y+[int]($foundBtn.h/2)
        Log ("click card claim btn '"+$foundBtn.text+"' at "+$bx2+","+$by2)
        Click-At $bx2 $by2
        $okHit2=$null
        foreach($delay in @(2000,2500,3000)){
            Start-Sleep -Milliseconds $delay
            $fcap2 = Get-OcrLines ""
            foreach($l in $fcap2){ if($l.text -match '今日已领|已领|领取成功|成功'){ $okHit2=$l } }
            if($okHit2){ break }
        }
        if($okHit2){ Log ("ok marker: "+$okHit2.text); Close-LaunchedApp; if($OutFile){ [System.IO.File]::WriteAllText($OutFile,'{"status":"ok","detail":"'+$okHit2.text+'"}',(New-Object System.Text.UTF8Encoding($false))) } exit 0 }
    }
}

Log "no claim path worked"
Restore-Scene; if($OutFile){ [System.IO.File]::WriteAllText($OutFile,'{"status":"pending","detail":"no claim path worked"}',(New-Object System.Text.UTF8Encoding($false))) }
exit 2
} catch { Log ("ERROR: "+$_.Exception.Message) }
