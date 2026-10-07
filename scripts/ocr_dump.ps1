# 通用窗口 OCR 抓屏：给进程名，抓它主窗口的完整布局（行级 + 词级坐标）。不做任何点击。
#
# 用法：
#   powershell -ExecutionPolicy Bypass -File scripts\ocr_dump.ps1 -ProcessName "TRAE SOLO CN"
#   powershell -ExecutionPolicy Bypass -File scripts\ocr_dump.ps1 -ProcessName "TRAE SOLO CN" -LaunchPath "C:\...\TRAE SOLO CN.exe"
param(
    [string]$ProcessName = "AutoClaw",
    [string]$LaunchPath = "",
    [string]$OutFile = ""
)
$root = Split-Path -Parent $PSScriptRoot
$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

Add-Type -AssemblyName System.Drawing
Add-Type -AssemblyName System.Runtime.WindowsRuntime

Add-Type @"
using System;
using System.Runtime.InteropServices;
public static class D32 {
  [DllImport("user32.dll")] public static extern bool SetProcessDPIAware();
  [DllImport("user32.dll")] public static extern bool GetWindowRect(IntPtr hWnd, out RECT rect);
  [DllImport("user32.dll")] public static extern IntPtr GetForegroundWindow();
  [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr hWnd);
  [DllImport("user32.dll")] public static extern bool ShowWindow(IntPtr hWnd, int nCmdShow);
  [DllImport("user32.dll")] public static extern bool IsIconic(IntPtr hWnd);
  [DllImport("user32.dll")] public static extern void keybd_event(byte bVk, byte bScan, uint dwFlags, UIntPtr extra);
  [DllImport("user32.dll")] public static extern bool AttachThreadInput(uint idAttach, uint idAttachTo, bool fAttach);
  [DllImport("user32.dll")] public static extern uint GetWindowThreadProcessId(IntPtr hWnd, out uint pid);
  [DllImport("kernel32.dll")] public static extern uint GetCurrentThreadId();
  public struct RECT { public int Left, Top, Right, Bottom; }
}
"@

$null = [Windows.Media.Ocr.OcrEngine, Windows.Foundation, ContentType = WindowsRuntime]
$null = [Windows.Globalization.Language, Windows.Foundation, ContentType = WindowsRuntime]
$null = [Windows.Graphics.Imaging.SoftwareBitmap, Windows.Foundation, ContentType = WindowsRuntime]
$null = [Windows.Storage.Streams.InMemoryRandomAccessStream, Windows.Foundation, ContentType = WindowsRuntime]

$asTaskGeneric = ([System.WindowsRuntimeSystemExtensions].GetMethods() | Where-Object {
        $_.Name -eq 'AsTask' -and $_.GetParameters().Count -eq 1 -and
        $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncOperation`1'
    })[0]

function Await($WinRtOp, $ResultType) {
    $asTask = $asTaskGeneric.MakeGenericMethod($ResultType)
    $netTask = $asTask.Invoke($null, @($WinRtOp))
    $netTask.Wait(-1) | Out-Null
    return $netTask.Result
}

[D32]::SetProcessDPIAware() | Out-Null

# 逐级加码抢前台：单靠 SetForegroundWindow 在用户正在操作电脑时会被 Windows 拒绝，
# 那样抓到的会是别的窗口，调研结论就全错了。
function EnsureForeground($hWnd) {
    if ([D32]::GetForegroundWindow() -eq $hWnd) { return $true }
    if ([D32]::IsIconic($hWnd)) {
        [D32]::ShowWindow($hWnd, 9) | Out-Null
        Start-Sleep -Milliseconds 400
        if ([D32]::GetForegroundWindow() -eq $hWnd) { return $true }
    }
    # void 方法调用必须接管道，否则解析器会把后续语句吞掉（本机 5.1 实测）
    [D32]::keybd_event(0x12, 0, 0, [UIntPtr]::Zero) | Out-Null
    [D32]::SetForegroundWindow($hWnd) | Out-Null
    [D32]::keybd_event(0x12, 0, 0x0002, [UIntPtr]::Zero) | Out-Null
    Start-Sleep -Milliseconds 500
    if ([D32]::GetForegroundWindow() -eq $hWnd) { return $true }

    # 第三级（绑输入队列强切）暂未启用：该段在本机 PowerShell 解析器上有语法歧义，
    # 前两级（还原 + Alt 技巧）在 AutoClaw 上已验证够用。
    return ([D32]::GetForegroundWindow() -eq $hWnd)
}

$proc = Get-Process -Name $ProcessName -ErrorAction SilentlyContinue |
    Where-Object { $_.MainWindowHandle -ne 0 } | Select-Object -First 1

if (-not $proc -and $LaunchPath -and (Test-Path $LaunchPath)) {
    Write-Output ("launching: " + $LaunchPath)
    Start-Process $LaunchPath
    $deadline = (Get-Date).AddSeconds(90)
    while ((Get-Date) -lt $deadline) {
        Start-Sleep -Seconds 3
        $proc = Get-Process -Name $ProcessName -ErrorAction SilentlyContinue |
            Where-Object { $_.MainWindowHandle -ne 0 } | Select-Object -First 1
        if ($proc) { break }
    }
}

if (-not $proc) { Write-Output ("NO WINDOW for process: " + $ProcessName); exit 1 }

$hwnd = $proc.MainWindowHandle
$rect = New-Object D32+RECT
[D32]::GetWindowRect($hwnd, [ref]$rect) | Out-Null
$w = $rect.Right - $rect.Left
$h = $rect.Bottom - $rect.Top
Write-Output ("HWND=" + $hwnd + " RECT=" + $rect.Left + "," + $rect.Top + " " + $w + "x" + $h)

$deadline2 = (Get-Date).AddSeconds(45)
$ok = $false
while ((Get-Date) -lt $deadline2) {
    if (EnsureForeground $hwnd) { $ok = $true; break }
    Start-Sleep -Milliseconds 600
}
if (-not $ok) { Write-Output "WARN: not foreground, capture may be wrong" }

$bmp = New-Object System.Drawing.Bitmap($w, $h)
$g = [System.Drawing.Graphics]::FromImage($bmp)
$g.CopyFromScreen($rect.Left, $rect.Top, 0, 0, $bmp.Size)
$g.Dispose()

$ms = New-Object System.IO.MemoryStream
$bmp.Save($ms, [System.Drawing.Imaging.ImageFormat]::Png)
$bmp.Dispose()
$stream = New-Object Windows.Storage.Streams.InMemoryRandomAccessStream
$writer = New-Object Windows.Storage.Streams.DataWriter($stream.GetOutputStreamAt(0))
$writer.WriteBytes($ms.ToArray())
Await ($writer.StoreAsync()) ([uint32]) | Out-Null
Await ($writer.FlushAsync()) ([bool]) | Out-Null
$decoder = Await ([Windows.Graphics.Imaging.BitmapDecoder]::CreateAsync($stream)) ([Windows.Graphics.Imaging.BitmapDecoder])
$softBmp = Await ($decoder.GetSoftwareBitmapAsync()) ([Windows.Graphics.Imaging.SoftwareBitmap])

$langs = [Windows.Media.Ocr.OcrEngine]::AvailableRecognizerLanguages
$zh = $langs | Where-Object { $_.LanguageTag -like "zh*" } | Select-Object -First 1
$engine = $null
if ($zh) { $engine = [Windows.Media.Ocr.OcrEngine]::TryCreateFromLanguage($zh) }
if (-not $engine) { $engine = [Windows.Media.Ocr.OcrEngine]::TryCreateFromUserProfileLanguages() }
if (-not $engine) { Write-Output "NO OCR ENGINE"; exit 1 }
Write-Output ("OCR-LANG: " + $engine.RecognizerLanguage.LanguageTag)

$result = Await ($engine.RecognizeAsync($softBmp)) ([Windows.Media.Ocr.OcrResult])

$out = New-Object System.Collections.ArrayList
[void]$out.Add("=== OCR " + $ProcessName + " " + (Get-Date -Format "yyyy-MM-dd HH:mm:ss") +
    " hwnd=" + $hwnd + " rect=" + $rect.Left + "," + $rect.Top + " " + $w + "x" + $h + " ===")
[void]$out.Add("--- LINES ---")
foreach ($line in $result.Lines) {
    $t = ($line.Text -replace "\s", "")
    if ([string]::IsNullOrWhiteSpace($t)) { continue }
    $minX = 999999; $minY = 999999; $maxX = 0; $maxY = 0
    foreach ($wd in $line.Words) {
        $br = $wd.BoundingRect
        if ($br.X -lt $minX) { $minX = [int]$br.X }
        if ($br.Y -lt $minY) { $minY = [int]$br.Y }
        if (($br.X + $br.Width) -gt $maxX) { $maxX = [int]($br.X + $br.Width) }
        if (($br.Y + $br.Height) -gt $maxY) { $maxY = [int]($br.Y + $br.Height) }
    }
    [void]$out.Add("LINE | " + $t + " | " + $minX + "," + $minY + " " + ($maxX - $minX) + "x" + ($maxY - $minY))
}
[void]$out.Add("--- WORDS ---")
foreach ($line in $result.Lines) {
    foreach ($wd in $line.Words) {
        $br = $wd.BoundingRect
        $wt = ($wd.Text -replace "\s", "")
        [void]$out.Add("WORD | " + $wt + " | " + [int]$br.X + "," + [int]$br.Y + " " + [int]$br.Width + "x" + [int]$br.Height)
    }
}

$text = ($out -join "`n")
Write-Output $text

if (-not $OutFile) {
    $safe = ($ProcessName -replace '[\\/:*?"<>| ]', '_')
    $OutFile = "$root\logs\ocr_dump_" + $safe + ".txt"
}
[System.IO.File]::AppendAllText($OutFile, $text + "`n---`n", (New-Object System.Text.UTF8Encoding($false)))
Write-Output ("SAVED: " + $OutFile)
