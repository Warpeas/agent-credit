$root = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
# MonkeyCode 界面探索（只读）：只截 MonkeyCode 窗口本身并 OCR，不点击、不改任何东西。
param([string]$OutPng = "$root\logs\monkey_shot.png")
$ErrorActionPreference = "Stop"
$logPath = "$root\logs\_monkey_explore.txt"
function Log($m){ $s=(Get-Date -Format "HH:mm:ss")+" "+$m; try{[System.IO.File]::AppendAllText($logPath,$s+"`n",(New-Object System.Text.UTF8Encoding($false)))}catch{}; Write-Output $s }
try {
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
Add-Type -AssemblyName System.Drawing
Add-Type -AssemblyName System.Runtime.WindowsRuntime
Add-Type @"
using System; using System.Runtime.InteropServices; using System.Text;
public static class M32 {
  [DllImport("user32.dll")] public static extern bool SetProcessDPIAware();
  [DllImport("user32.dll")] public static extern bool GetWindowRect(IntPtr h, out RECT r);
  [DllImport("user32.dll")] public static extern bool EnumWindows(EnumProc cb, IntPtr lp);
  [DllImport("user32.dll")] public static extern uint GetWindowThreadProcessId(IntPtr h, out uint pid);
  [DllImport("user32.dll")] public static extern bool IsWindowVisible(IntPtr h);
  [DllImport("user32.dll")] public static extern int GetWindowText(IntPtr h, StringBuilder s, int n);
  [DllImport("user32.dll")] public static extern bool PrintWindow(IntPtr h, IntPtr hdcBlt, uint nFlags);
  public struct RECT { public int Left, Top, Right, Bottom; }
  public delegate bool EnumProc(IntPtr h, IntPtr lp);
}
"@
$null = [Windows.Media.Ocr.OcrEngine, Windows.Foundation, ContentType = WindowsRuntime]
$null = [Windows.Globalization.Language, Windows.Foundation, ContentType = WindowsRuntime]
$null = [Windows.Graphics.Imaging.SoftwareBitmap, Windows.Foundation, ContentType = WindowsRuntime]
$null = [Windows.Storage.Streams.InMemoryRandomAccessStream, Windows.Foundation, ContentType = WindowsRuntime]
$asTask = ([System.WindowsRuntimeSystemExtensions].GetMethods() | Where-Object { $_.Name -eq 'AsTask' -and $_.GetParameters().Count -eq 1 -and $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncOperation`1' })[0]
function Await($op,$t){ $m=$asTask.MakeGenericMethod($t); $x=$m.Invoke($null,@($op)); $x.Wait(-1)|Out-Null; return $x.Result }

[void][M32]::SetProcessDPIAware()

# 收集所有窗口，按 pid 属于 monkeycode 或标题命中
$pids = @{}
Get-Process -Name 'monkeycode-desktop' -ErrorAction SilentlyContinue | ForEach-Object { $pids[[uint32]$_.Id] = $true }
Log ("monkeycode pids=" + $pids.Count)

$script:Cands = @()
$cb = [M32+EnumProc]{
    param($h,$lp)
    $o=[uint32]0; [M32]::GetWindowThreadProcessId($h,[ref]$o)|Out-Null
    $isMonkey = $pids.ContainsKey($o)
    if(-not $isMonkey){
        $sb2 = New-Object System.Text.StringBuilder 256
        [M32]::GetWindowText($h,$sb2,256)|Out-Null
        if($sb2.ToString() -match '(?i)monkey'){ $isMonkey = $true }
    }
    if($isMonkey){
        $r = New-Object M32+RECT; [M32]::GetWindowRect($h,[ref]$r)|Out-Null
        $w=$r.Right-$r.Left; $hh=$r.Bottom-$r.Top
        if($w -gt 300 -and $hh -gt 200){
            $sb3 = New-Object System.Text.StringBuilder 256
            [M32]::GetWindowText($h,$sb3,256)|Out-Null
            $script:Cands += @{ h=$h; w=$w; hh=$hh; x=$r.Left; y=$r.Top;
                                vis=[M32]::IsWindowVisible($h); title=$sb3.ToString() }
        }
    }
    return $true
}
[M32]::EnumWindows($cb,[IntPtr]::Zero)|Out-Null

Log ("候选窗口数=" + $script:Cands.Count)
foreach($c in $script:Cands){
    Log ("  hwnd=" + $c.h + " rect=" + $c.x + "," + $c.y + " " + $c.w + "x" + $c.hh + " vis=" + $c.vis + " title=[" + $c.title + "]")
}
if($script:Cands.Count -eq 0){ Log "NO WINDOW"; exit 1 }

$best = $script:Cands | Sort-Object @{e={$_.w*$_.hh}; desc=$true} | Select-Object -First 1
$hwnd = $best.h
Log ("选定 hwnd=" + $hwnd + " " + $best.w + "x" + $best.hh)

$bmp = New-Object System.Drawing.Bitmap($best.w, $best.hh)
$g = [System.Drawing.Graphics]::FromImage($bmp)
$hdc = $g.GetHdc()
$pw = [M32]::PrintWindow($hwnd,$hdc,2)
$g.ReleaseHdc($hdc)
$g.Dispose()
Log ("PrintWindow=" + $pw)
$bmp.Save($OutPng,[System.Drawing.Imaging.ImageFormat]::Png)

# OCR
$ms = New-Object System.IO.MemoryStream
$bmp.Save($ms,[System.Drawing.Imaging.ImageFormat]::Png)
$ras = New-Object Windows.Storage.Streams.InMemoryRandomAccessStream
$w = New-Object Windows.Storage.Streams.DataWriter($ras)
$w.WriteBytes($ms.ToArray())
$null = $w.StoreAsync().AsTask().Result
$null = $ras.FlushAsync().AsTask().Result
$dec = Await ([Windows.Graphics.Imaging.BitmapDecoder]::CreateAsync($ras)) ([Windows.Graphics.Imaging.BitmapDecoder])
$sbm = Await ($dec.GetSoftwareBitmapAsync()) ([Windows.Graphics.Imaging.SoftwareBitmap])
$eng = [Windows.Media.Ocr.OcrEngine]::TryCreateFromLanguage([Windows.Globalization.Language]::new("zh-Hans-CN"))
if(-not $eng){ $eng = [Windows.Media.Ocr.OcrEngine]::TryCreateFromUserProfileLanguages() }
$res = Await ($eng.RecognizeAsync($sbm)) ([Windows.Media.Ocr.OcrResult])
Log ("OCR lines=" + $res.Lines.Count + " lang=" + $eng.RecognizerLanguage.LanguageTag)
foreach($l in $res.Lines){
    $t = ""
    foreach($wd in $l.Words){ $t += $wd.Text }
    $b = $l.BoundingRect
    Log ("  LINE | " + $t + " | " + [int]$b.X + "," + [int]$b.Y + " " + [int]$b.Width + "x" + [int]$b.Height)
}
Log ("png saved: " + $OutPng)
} catch { Log ("ERROR: " + $_.Exception.Message) }