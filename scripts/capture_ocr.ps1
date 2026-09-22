# Capture a client window + OCR all text with positions. ASCII code only; match words passed via args.
param(
    [int]$WaitSeconds = 3,
    [string]$ProcessName = "AutoClaw"
)
$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

Add-Type -AssemblyName System.Drawing
Add-Type -AssemblyName System.Runtime.WindowsRuntime

Add-Type @"
using System;
using System.Runtime.InteropServices;
public static class Cap32 {
  [DllImport("user32.dll")] public static extern bool SetProcessDPIAware();
  [DllImport("user32.dll")] public static extern bool GetWindowRect(IntPtr hWnd, out RECT rect);
  [DllImport("user32.dll")] public static extern bool PrintWindow(IntPtr hWnd, IntPtr hdcBlt, uint nFlags);
  [DllImport("user32.dll")] public static extern IntPtr GetForegroundWindow();
  public struct RECT { public int Left, Top, Right, Bottom; }
}
"@

# --- WinRT loaders ---
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

# --- Pick OCR language (prefer Chinese) ---
$langs = [Windows.Media.Ocr.OcrEngine]::AvailableRecognizerLanguages
$zh = $langs | Where-Object { $_.LanguageTag -like "zh*" } | Select-Object -First 1
$engine = $null
if ($zh) { $engine = [Windows.Media.Ocr.OcrEngine]::TryCreateFromLanguage($zh) }
if (-not $engine) { $engine = [Windows.Media.Ocr.OcrEngine]::TryCreateFromUserProfileLanguages() }
if (-not $engine) { Write-Output "NO OCR ENGINE"; exit 1 }
Write-Output ("OCR-LANG: " + $engine.RecognizerLanguage.LanguageTag)

# --- Window rect ---
[Cap32]::SetProcessDPIAware() | Out-Null
$proc = Get-Process $ProcessName -ErrorAction SilentlyContinue | Where-Object { $_.MainWindowHandle -ne 0 } | Select-Object -First 1
if (-not $proc) { Write-Output "NO WINDOW"; exit 1 }
$rect = New-Object Cap32+RECT
[Cap32]::GetWindowRect($proc.MainWindowHandle, [ref]$rect) | Out-Null
$w = $rect.Right - $rect.Left
$h = $rect.Bottom - $rect.Top
Write-Output ("RECT: " + $rect.Left + "," + $rect.Top + " " + $w + "x" + $h)

# --- Wait until AutoClaw is the foreground window (max 45s) ---
$fg = [IntPtr]::Zero
$fgDeadline = (Get-Date).AddSeconds(45)
Write-Output "waiting for AutoClaw to be foreground (click its window)..."
while ((Get-Date) -lt $fgDeadline) {
    $fg = [Cap32]::GetForegroundWindow()
    if ($fg -eq $proc.MainWindowHandle) { break }
    Start-Sleep -Milliseconds 600
}
if ($fg -ne $proc.MainWindowHandle) { Write-Output "NOT FOREGROUND"; exit 1 }
Write-Output "FOREGROUND OK"

# --- Capture via CopyFromScreen (window must be foreground & unoccluded) ---
$bmp = New-Object System.Drawing.Bitmap($w, $h)
$g = [System.Drawing.Graphics]::FromImage($bmp)
$g.CopyFromScreen($rect.Left, $rect.Top, 0, 0, $bmp.Size)
$g.Dispose()
$bmp.Save("$env:TEMP\autoclaw_capture.png", [System.Drawing.Imaging.ImageFormat]::Png)

# --- Bitmap -> SoftwareBitmap ---
$ms = New-Object System.IO.MemoryStream
$bmp.Save($ms, [System.Drawing.Imaging.ImageFormat]::Png)
$stream = New-Object Windows.Storage.Streams.InMemoryRandomAccessStream
$writer = New-Object Windows.Storage.Streams.DataWriter($stream.GetOutputStreamAt(0))
$writer.WriteBytes($ms.ToArray())
Await ($writer.StoreAsync()) ([uint32]) | Out-Null
Await ($writer.FlushAsync()) ([bool]) | Out-Null
$decoder = Await ([Windows.Graphics.Imaging.BitmapDecoder]::CreateAsync($stream)) ([Windows.Graphics.Imaging.BitmapDecoder])
$softBmp = Await ($decoder.GetSoftwareBitmapAsync()) ([Windows.Graphics.Imaging.SoftwareBitmap])

# --- OCR (word-level coordinates) ---
$result = Await ($engine.RecognizeAsync($softBmp)) ([Windows.Media.Ocr.OcrResult])
foreach ($line in $result.Lines) {
    foreach ($word in $line.Words) {
        $r = $word.BoundingRect
        Write-Output ("WORD | " + $word.Text + " | " + [int]$r.X + "," + [int]$r.Y + " " + [int]$r.Width + "x" + [int]$r.Height)
    }
}
Write-Output ("SAVED: $env:TEMP\autoclaw_capture.png")
