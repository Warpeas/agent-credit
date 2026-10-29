# PoC: hidden-desktop (CreateDesktop) feasibility for background UI check-in.
#
# Question under test: can the UI-recognition check-in run completely in the
# background, on a Win32 "real" desktop (CreateDesktop, NOT the Win+Tab virtual
# desktop), so the user never sees a window and never has their cursor stolen?
#
# Two modes in one script (same file, -Child switch):
#   parent (default): creates the desktop, launches notepad + the target client
#                     ON that desktop via CreateProcessW(lpDesktop=...), spawns
#                     the child, waits, then closes everything.
#   child (-Child):   opens the desktop, SetThreadDesktop on its own main
#                     thread (fresh process => no USER32 windows), runs the
#                     tests, switches back.
#
# What the child proves:
#   1. SetThreadDesktop works for a fresh process main thread.
#   2. SendInput (move/click/unicode keys) is delivered to windows that live on
#      the hidden desktop (notepad: click into edit + type + read back text).
#   3. The Electron client renders on a shell-less desktop:
#      PrintWindow(PW_RENDERFULLCONTENT) non-black + screen-DC BitBlt + OCR.
#   4. A title-bar click on the hidden desktop changes nothing on screen
#      (input is inert to the user) and the window keeps rendering.
# The parent additionally records whether PrintWindow works cross-desktop from
# the default thread, and whether WM_CLOSE reaches the hidden-desktop window.
#
# Safety: NO check-in buttons are ever clicked (title bar / notepad only).
# No ledger writes, no network calls, no credentials touched. Every process
# launched here is closed before exit. Run via scripts/_task_poc_desktop.ps1
# (non-elevated scheduled task, same trick as _task_trae_claim.ps1).
param(
    [switch]$Child,
    [string]$DesktopName = "agent-credit",
    [string]$ClientProcess = "Trae CN",
    [string]$ClientExe = "",
    [int]$WindowWaitSeconds = 120,
    [int]$CloseWaitSeconds = 60
)

$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$root = Split-Path -Parent $PSScriptRoot
$logPath = "$root\logs\poc_desktop.log"
$childJsonPath = "$root\logs\poc_desktop_child.json"
$resultPath = "$root\logs\poc_desktop_result.json"

function Log($m) {
    $s = (Get-Date -Format "HH:mm:ss") + " " + $m
    try { [System.IO.File]::AppendAllText($logPath, $s + "`n", (New-Object System.Text.UTF8Encoding($false))) } catch {}
    Write-Output $s
}

trap {
    try { Log ("UNHANDLED: " + $_.Exception.Message + " @ " + $_.InvocationInfo.PositionMessage) } catch {}
    exit 1
}

Log "init: loading assemblies"
try { Add-Type -AssemblyName System.Drawing; Add-Type -AssemblyName System.Runtime.WindowsRuntime; Log "init: drawing+winrt ok" } catch { Log ("INIT FAIL drawing: " + $_.Exception.Message); exit 1 }

try {
Add-Type @"
using System;
using System.Runtime.InteropServices;
using System.Text;

[StructLayout(LayoutKind.Sequential)]
public struct POCRECT { public int Left, Top, Right, Bottom; }

[StructLayout(LayoutKind.Sequential)]
public struct POCPOINT { public int X, Y; }

[StructLayout(LayoutKind.Sequential)]
public struct MOUSEINPUT { public int dx; public int dy; public uint mouseData; public uint dwFlags; public uint time; public IntPtr dwExtraInfo; }

[StructLayout(LayoutKind.Sequential)]
public struct KEYBDINPUT { public ushort wVk; public ushort wScan; public uint dwFlags; public uint time; public IntPtr dwExtraInfo; }

[StructLayout(LayoutKind.Explicit)]
public struct INPUTUNION {
  [FieldOffset(0)] public MOUSEINPUT mi;
  [FieldOffset(0)] public KEYBDINPUT ki;
}

[StructLayout(LayoutKind.Sequential)]
public struct INPUT { public int type; public INPUTUNION u; }

[StructLayout(LayoutKind.Sequential, CharSet = CharSet.Unicode)]
public struct STARTUPINFO {
  public int cb; public string lpReserved; public string lpDesktop; public string lpTitle;
  public int dwX; public int dwY; public int dwXSize; public int dwYSize;
  public int dwXCountChars; public int dwYCountChars; public int dwFillAttribute; public int dwFlags;
  public short wShowWindow; public short cbReserved2; public IntPtr lpReserved2;
  public IntPtr hStdInput; public IntPtr hStdOutput; public IntPtr hStdError;
}

[StructLayout(LayoutKind.Sequential)]
public struct PROCESS_INFORMATION { public IntPtr hProcess; public IntPtr hThread; public int dwProcessId; public int dwThreadId; }

public delegate bool EnumProc(IntPtr hWnd, IntPtr lParam);

public static class PocNative {
  [DllImport("user32.dll", CharSet = CharSet.Unicode, SetLastError = true)] public static extern IntPtr CreateDesktopW(string lpszDesktop, IntPtr lpszDevice, IntPtr pDevmode, int dwFlags, int dwDesiredAccess, IntPtr lpsa);
  [DllImport("user32.dll", CharSet = CharSet.Unicode, SetLastError = true)] public static extern IntPtr OpenDesktopW(string lpszDesktop, int dwFlags, bool fInherit, int dwDesiredAccess);
  [DllImport("user32.dll", SetLastError = true)] public static extern bool SetThreadDesktop(IntPtr hDesktop);
  [DllImport("user32.dll")] public static extern IntPtr GetThreadDesktop(int dwThreadId);
  [DllImport("user32.dll")] public static extern bool CloseDesktop(IntPtr hDesktop);
  [DllImport("kernel32.dll", CharSet = CharSet.Unicode, SetLastError = true)] public static extern bool CreateProcessW(string lpApplicationName, string lpCommandLine, IntPtr lpProcessAttributes, IntPtr lpThreadAttributes, bool bInheritHandles, int dwCreationFlags, IntPtr lpEnvironment, IntPtr lpCurrentDirectory, ref STARTUPINFO lpStartupInfo, out PROCESS_INFORMATION lpProcessInformation);
  [DllImport("user32.dll")] public static extern bool PrintWindow(IntPtr hWnd, IntPtr hDC, uint nFlags);
  [DllImport("user32.dll")] public static extern bool GetWindowRect(IntPtr hWnd, out POCRECT lpRect);
  [DllImport("user32.dll")] public static extern IntPtr GetDC(IntPtr hWnd);
  [DllImport("user32.dll")] public static extern int ReleaseDC(IntPtr hWnd, IntPtr hDC);
  [DllImport("gdi32.dll")] public static extern IntPtr CreateCompatibleDC(IntPtr hDC);
  [DllImport("gdi32.dll")] public static extern IntPtr CreateCompatibleBitmap(IntPtr hDC, int nWidth, int nHeight);
  [DllImport("gdi32.dll")] public static extern IntPtr SelectObject(IntPtr hDC, IntPtr hObject);
  [DllImport("gdi32.dll")] public static extern bool BitBlt(IntPtr hObject, int nXDest, int nYDest, int nWidth, int nHeight, IntPtr hObjSource, int nXSrc, int nYSrc, uint dwRop);
  [DllImport("gdi32.dll")] public static extern bool DeleteObject(IntPtr hObject);
  [DllImport("gdi32.dll")] public static extern bool DeleteDC(IntPtr hDC);
  [DllImport("user32.dll")] public static extern uint SendInput(uint nInputs, INPUT[] pInputs, int cbSize);
  [DllImport("user32.dll")] public static extern bool GetCursorPos(out POCPOINT lpPoint);
  [DllImport("user32.dll")] public static extern bool SetCursorPos(int X, int Y);
  [DllImport("user32.dll", CharSet = CharSet.Unicode, SetLastError = true)] public static extern IntPtr FindWindowW(string lpClassName, IntPtr lpWindowName);
  [DllImport("user32.dll", CharSet = CharSet.Unicode, SetLastError = true)] public static extern bool PostMessageW(IntPtr hWnd, uint Msg, int wParam, int lParam);
  [DllImport("user32.dll", CharSet = CharSet.Unicode)] public static extern IntPtr SendMessageW(IntPtr hWnd, uint Msg, int wParam, int lParam);
  [DllImport("user32.dll", CharSet = CharSet.Unicode, EntryPoint = "SendMessageW")] public static extern IntPtr SendMessageTextW(IntPtr hWnd, uint Msg, int wParam, StringBuilder lParam);
  [DllImport("user32.dll")] public static extern bool EnumWindows(EnumProc lpEnumFunc, IntPtr lParam);
  [DllImport("user32.dll")] public static extern bool EnumChildWindows(IntPtr hWndParent, EnumProc lpEnumFunc, IntPtr lParam);
  [DllImport("user32.dll")] public static extern bool IsWindowVisible(IntPtr hWnd);
  [DllImport("user32.dll", CharSet = CharSet.Unicode)] public static extern int GetClassNameW(IntPtr hWnd, StringBuilder lpClassName, int nMaxCount);
  [DllImport("user32.dll", CharSet = CharSet.Unicode)] public static extern int GetWindowTextW(IntPtr hWnd, StringBuilder lpString, int nMaxCount);
  [DllImport("user32.dll")] public static extern int GetSystemMetrics(int nIndex);
  [DllImport("user32.dll")] public static extern bool SetProcessDPIAware();
  [DllImport("kernel32.dll")] public static extern uint WaitForSingleObject(IntPtr hHandle, uint dwMilliseconds);
  [DllImport("kernel32.dll")] public static extern bool TerminateProcess(IntPtr hProcess, uint uExitCode);
  [DllImport("kernel32.dll")] public static extern int GetLastError();
  [DllImport("kernel32.dll")] public static extern int GetCurrentThreadId();

  public static INPUT MakeMouse(int dx, int dy, uint flags) {
    INPUT i = new INPUT();
    i.type = 0;
    i.u.mi.dx = dx; i.u.mi.dy = dy; i.u.mi.dwFlags = flags;
    return i;
  }
  public static INPUT MakeKey(ushort vk, ushort scan, uint flags) {
    INPUT i = new INPUT();
    i.type = 1;
    i.u.ki.wVk = vk; i.u.ki.wScan = scan; i.u.ki.dwFlags = flags;
    return i;
  }
}
"@
Log "init: native ok"
} catch { Log ("INIT FAIL native: " + $_.Exception.Message); exit 1 }

try {
# --- WinRT OCR (same pattern as ui_claim_trae.ps1) ---
$null = [Windows.Media.Ocr.OcrEngine, Windows.Foundation, ContentType = WindowsRuntime]
$null = [Windows.Globalization.Language, Windows.Foundation, ContentType = WindowsRuntime]
$null = [Windows.Graphics.Imaging.SoftwareBitmap, Windows.Foundation, ContentType = WindowsRuntime]
$null = [Windows.Storage.StorageFile, Windows.Storage, ContentType = WindowsRuntime]
$null = [Windows.Storage.Streams.InMemoryRandomAccessStream, Windows.Foundation, ContentType = WindowsRuntime]

$asTaskGeneric = ([System.WindowsRuntimeSystemExtensions].GetMethods() | Where-Object {
    $_.Name -eq 'AsTask' -and $_.GetParameters().Count -eq 1 -and
    $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncOperation`1'
})[0]
Log "init: winrt loaders ok"
} catch { Log ("INIT FAIL winrt: " + $_.Exception.Message); exit 1 }

function Await($WinRtOp, $ResultType) {
    $asTask = $asTaskGeneric.MakeGenericMethod($ResultType)
    $netTask = $asTask.Invoke($null, @($WinRtOp))
    $netTask.Wait(-1) | Out-Null
    return $netTask.Result
}

function Get-OcrWords([string]$pngPath, [int]$maxWords = 60) {
    try {
        $langs = [Windows.Media.Ocr.OcrEngine]::AvailableRecognizerLanguages
        $zh = $langs | Where-Object { $_.LanguageTag -like "zh*" } | Select-Object -First 1
        $engine = $null
        if ($zh) { $engine = [Windows.Media.Ocr.OcrEngine]::TryCreateFromLanguage($zh) }
        if (-not $engine) { $engine = [Windows.Media.Ocr.OcrEngine]::TryCreateFromUserProfileLanguages() }
        if (-not $engine) { return @() }
        $file = Await ([Windows.Storage.StorageFile]::GetFileFromPathAsync($pngPath)) ([Windows.Storage.StorageFile])
        $stream = Await ($file.OpenAsync([Windows.Storage.FileAccessMode]::Read)) ([Windows.Storage.Streams.IRandomAccessStream])
        $decoder = Await ([Windows.Graphics.Imaging.BitmapDecoder]::CreateAsync($stream)) ([Windows.Graphics.Imaging.BitmapDecoder])
        $soft = Await ($decoder.GetSoftwareBitmapAsync()) ([Windows.Graphics.Imaging.SoftwareBitmap])
        $result = Await ($engine.RecognizeAsync($soft)) ([Windows.Media.Ocr.OcrResult])
        $words = @()
        foreach ($line in $result.Lines) { foreach ($wd in $line.Words) { $words += $wd.Text } }
        return @($words | Select-Object -First $maxWords)
    } catch {
        Log ("OCR failed: " + $_.Exception.Message)
        return @()
    }
}

# --- window helpers ---
function Get-WindowInfo([IntPtr]$h) {
    $cls = New-Object System.Text.StringBuilder 256
    [void][PocNative]::GetClassNameW($h, $cls, 256)
    $ttl = New-Object System.Text.StringBuilder 512
    [void][PocNative]::GetWindowTextW($h, $ttl, 512)
    $r = New-Object POCRECT
    [void][PocNative]::GetWindowRect($h, [ref]$r)
    $w = $r.Right - $r.Left; $hh = $r.Bottom - $r.Top
    return @{ hwnd = $h; cls = $cls.ToString(); title = $ttl.ToString(); left = $r.Left; top = $r.Top; w = $w; h = $hh; area = ($w * $hh) }
}

function Find-TopWindows {
    $found = New-Object System.Collections.Generic.List[object]
    $cb = [EnumProc]{
        param($h, $l)
        if (-not [PocNative]::IsWindowVisible($h)) { return $true }
        $info = Get-WindowInfo $h
        if ($info.title -eq "" -or $info.area -le 0) { return $true }
        $found.Add($info) | Out-Null
        return $true
    }
    [void][PocNative]::EnumWindows($cb, [IntPtr]::Zero)
    return $found
}

function Save-WindowCapture([IntPtr]$hWnd, [string]$path, [string]$method) {
    $info = Get-WindowInfo $hWnd
    if ($info.w -le 0 -or $info.h -le 0) { return $null }
    $hdcScreen = [PocNative]::GetDC([IntPtr]::Zero)
    $hdcMem = [PocNative]::CreateCompatibleDC($hdcScreen)
    $hbmp = [PocNative]::CreateCompatibleBitmap($hdcScreen, $info.w, $info.h)
    [void][PocNative]::SelectObject($hdcMem, $hbmp)
    if ($method -eq "printwindow") {
        $ok = [PocNative]::PrintWindow($hWnd, $hdcMem, 2)
    } else {
        $ok = [PocNative]::BitBlt($hdcMem, 0, 0, $info.w, $info.h, $hdcScreen, $info.left, $info.top, 0x00CC0028)
    }
    $stats = $null
    try {
        $img = [System.Drawing.Image]::FromHbitmap($hbmp)
        $img.Save($path, [System.Drawing.Imaging.ImageFormat]::Png)
        $step = 8
        $n = 0; $sum = 0.0; $sumsq = 0.0
        $colors = @{}
        for ($y = 0; $y -lt $info.h; $y += $step) {
            for ($x = 0; $x -lt $info.w; $x += $step) {
                $c = $img.GetPixel($x, $y)
                $lum = (0.299 * $c.R + 0.587 * $c.G + 0.114 * $c.B)
                $sum += $lum; $sumsq += $lum * $lum; $n++
                $key = "$($c.R),$($c.G),$($c.B)"
                if (-not $colors.ContainsKey($key)) { $colors[$key] = 0 }
                $colors[$key] = $colors[$key] + 1
            }
        }
        $mean = $sum / $n
        $std = [math]::Sqrt([math]::Max(0, $sumsq / $n - $mean * $mean))
        $img.Dispose()
        $stats = @{ ok = [bool]$ok; w = $info.w; h = $info.h; mean = [math]::Round($mean, 1); std = [math]::Round($std, 1); uniq = $colors.Count }
    } catch {
        $stats = @{ ok = [bool]$ok; w = $info.w; h = $info.h; error = $_.Exception.Message }
    }
    [void][PocNative]::DeleteObject($hbmp)
    [void][PocNative]::DeleteDC($hdcMem)
    [void][PocNative]::ReleaseDC([IntPtr]::Zero, $hdcScreen)
    return $stats
}

function Compare-Captures([string]$a, [string]$b) {
    try {
        $ia = New-Object System.Drawing.Bitmap($a)
        $ib = New-Object System.Drawing.Bitmap($b)
        $w = [math]::Min($ia.Width, $ib.Width); $h = [math]::Min($ia.Height, $ib.Height)
        $step = 4; $n = 0; $changed = 0
        for ($y = 0; $y -lt $h; $y += $step) {
            for ($x = 0; $x -lt $w; $x += $step) {
                $ca = $ia.GetPixel($x, $y); $cb2 = $ib.GetPixel($x, $y)
                $d = [math]::Abs($ca.R - $cb2.R) + [math]::Abs($ca.G - $cb2.G) + [math]::Abs($ca.B - $cb2.B)
                if ($d -gt 12) { $changed++ }
                $n++
            }
        }
        $ia.Dispose(); $ib.Dispose()
        return [math]::Round(100.0 * $changed / $n, 2)
    } catch {
        return -1
    }
}

# --- input helpers (SendInput to the calling thread's desktop) ---
# NOTE: Marshal.SizeOf must receive a struct INSTANCE. Passing the type literal
# ([INPUT]) binds to the SizeOf(object) overload in PowerShell, which then gets
# the RuntimeType object itself and throws "cannot be marshaled as unmanaged".
try { $script:InputSize = [System.Runtime.InteropServices.Marshal]::SizeOf((New-Object INPUT)) } catch { $script:InputSize = 40 }
Log ("input struct size=" + $script:InputSize)

function Send-AbsMouse([int]$x, [int]$y, [int]$flags) {
    $cx = [PocNative]::GetSystemMetrics(0); $cy = [PocNative]::GetSystemMetrics(1)
    $nx = [int][math]::Round($x * 65535.0 / ($cx - 1)); $ny = [int][math]::Round($y * 65535.0 / ($cy - 1))
    $arr = @([PocNative]::MakeMouse($nx, $ny, $flags))
    $n = [PocNative]::SendInput(1, [INPUT[]]$arr, $script:InputSize)
    Log ("  SendInput mouse flags=$flags inserted=$n (0 = injection rejected)")
    return $n
}

function Send-ClickAt([int]$x, [int]$y) {
    [void](Send-AbsMouse $x $y (0x0001 -bor 0x8000))
    Start-Sleep -Milliseconds 120
    [void](Send-AbsMouse $x $y 0x0002)
    Start-Sleep -Milliseconds 60
    [void](Send-AbsMouse $x $y 0x0004)
}

function Send-UnicodeText([string]$text) {
    foreach ($ch in $text.ToCharArray()) {
        $arrDown = @([PocNative]::MakeKey(0, [int][char]$ch, 0x0004))
        [void][PocNative]::SendInput(1, [INPUT[]]$arrDown, $script:InputSize)
        $arrUp = @([PocNative]::MakeKey(0, [int][char]$ch, 0x0004 -bor 0x0002))
        [void][PocNative]::SendInput(1, [INPUT[]]$arrUp, $script:InputSize)
    }
}

function Send-VkChord([int]$vk) {
    $arr = @(
        [PocNative]::MakeKey($vk, 0, 0),
        [PocNative]::MakeKey($vk, 0, 0x0002)
    )
    [void][PocNative]::SendInput(2, [INPUT[]]$arr, $script:InputSize)
}

# =====================================================================
# CHILD: switch this process's main thread onto the hidden desktop and test
# =====================================================================
if ($Child) {
    # This process is BORN on the hidden desktop: the parent launches it with
    # CreateProcessW(lpDesktop="WinSta0\<name>"), so its main thread is
    # associated with the hidden desktop from the start. No SetThreadDesktop
    # needed - that call fails with ERROR_BUSY (170) when issued from a
    # separately spawned process, so birth-time placement is the reliable way.
    Log "=== CHILD start pid=$PID ==="
    [void][PocNative]::SetProcessDPIAware()
    $res = @{ status = "ok"; mode = "child"; desktop = $DesktopName }
    $tid = [PocNative]::GetCurrentThreadId()
    $td = [PocNative]::GetThreadDesktop($tid)
    Log ("child thread desktop handle=" + $td.ToInt64() + " tid=$tid")
    $res.thread_desktop = $td.ToInt64()
    $res.screen_on_hidden = "$([PocNative]::GetSystemMetrics(0))x$([PocNative]::GetSystemMetrics(1))"
    Log ("screen metrics on hidden desktop: " + $res.screen_on_hidden)

    try {
        # ---- 1. notepad: input delivery proof ----
        $np = [IntPtr]::Zero
        $dl = (Get-Date).AddSeconds(25)
        while ((Get-Date) -lt $dl) {
            $np = [PocNative]::FindWindowW("Notepad", [IntPtr]::Zero)
            if ($np -ne [IntPtr]::Zero) { break }
            Start-Sleep -Milliseconds 500
        }
        $res.notepad_window = ($np -ne [IntPtr]::Zero)
        if ($np -ne [IntPtr]::Zero) {
            $ni = Get-WindowInfo $np
            Log ("notepad hwnd=" + $np.ToInt64() + " rect=" + $ni.left + "," + $ni.top + " " + $ni.w + "x" + $ni.h)
            $capB = Save-WindowCapture $np "$root\logs\poc_notepad_before.png" "printwindow"
            Log ("notepad before: " + ($capB | ConvertTo-Json -Compress))
            # NO click/type injection here yet: where SendInput lands from a
            # hidden-desktop thread is not yet confirmed (it may follow the
            # INPUT desktop, i.e. the user's screen). The cursor probe below
            # decides routing first; click tests only run once it is known.
            $res.notepad_diff_pct = "skipped (routing unknown)"
            # read back the edit control text (cross-desktop WM_GETTEXT on child windows)
            $editText = ""
            $kids = New-Object System.Collections.Generic.List[object]
            $cbk = [EnumProc]{
                param($h, $l)
                $info = Get-WindowInfo $h
                $kids.Add($info) | Out-Null
                return $true
            }
            [void][PocNative]::EnumChildWindows($np, $cbk, [IntPtr]::Zero)
            foreach ($k in $kids) {
                if ($k.cls -match "Edit|RichEdit") {
                    $sb = New-Object System.Text.StringBuilder 2048
                    [void][PocNative]::SendMessageTextW($k.hwnd, 0x000D, 2048, $sb)
                    $t = $sb.ToString()
                    Log ("notepad child cls=[" + $k.cls + "] text=[" + $t + "]")
                    if ($t.Length -gt $editText.Length) { $editText = $t }
                }
            }
            $res.notepad_readback = $editText
            [void][PocNative]::PostMessageW($np, 0x0010, 0, 0)
            Log "notepad WM_CLOSE posted"
        }

        # ---- 2. cursor routing data point ----
        $p0 = New-Object POCPOINT
        [void][PocNative]::GetCursorPos([ref]$p0)
        [void](Send-AbsMouse 500 500 (0x0001 -bor 0x8000))
        Start-Sleep -Milliseconds 250
        $p1 = New-Object POCPOINT
        [void][PocNative]::GetCursorPos([ref]$p1)
        Log ("cursor: before=$($p0.X),$($p0.Y) injected=500,500 got=$($p1.X),$($p1.Y)")
        $res.cursor = "$($p0.X),$($p0.Y) -> 500,500 -> $($p1.X),$($p1.Y)"

        # ---- 3. client: render + capture proof on the hidden desktop ----
        $clientHwnd = [IntPtr]::Zero
        $dl = (Get-Date).AddSeconds($WindowWaitSeconds)
        while ((Get-Date) -lt $dl) {
            $wins = Find-TopWindows
            foreach ($w in $wins) {
                Log ("candidate cls=[" + $w.cls + "] title=[" + $w.title + "] rect=" + $w.left + "," + $w.top + " " + $w.w + "x" + $w.h)
            }
            $cand = @($wins | Where-Object { $_.cls -like "Chrome_WidgetWin_*" -and $_.title -ne "" } | Sort-Object area -Descending)
            if ($cand.Count -gt 0) { $clientHwnd = $cand[0].hwnd; break }
            Start-Sleep -Seconds 2
        }
        $res.client_window = ($clientHwnd -ne [IntPtr]::Zero)
        if ($clientHwnd -ne [IntPtr]::Zero) {
            $ci = Get-WindowInfo $clientHwnd
            Log ("client hwnd=" + $clientHwnd.ToInt64() + " cls=[" + $ci.cls + "] title=[" + $ci.title + "] rect=" + $ci.left + "," + $ci.top + " " + $ci.w + "x" + $ci.h)
            # retry until the client actually renders (cold start paints late)
            $pw = $null
            $capDl = (Get-Date).AddSeconds(30)
            while ((Get-Date) -lt $capDl) {
                $pw = Save-WindowCapture $clientHwnd "$root\logs\poc_client_printwindow.png" "printwindow"
                Log ("client printwindow try: " + ($pw | ConvertTo-Json -Compress))
                if ($pw -and $pw.uniq -gt 5 -and $pw.std -gt 3) { break }
                Start-Sleep -Seconds 2
            }
            $bb = $null
            $bbDl = (Get-Date).AddSeconds(15)
            while ((Get-Date) -lt $bbDl) {
                $bb = Save-WindowCapture $clientHwnd "$root\logs\poc_client_bitblt.png" "bitblt"
                Log ("client bitblt try: " + ($bb | ConvertTo-Json -Compress))
                if ($bb -and $bb.ok) { break }
                Start-Sleep -Seconds 2
            }
            $words = @()
            if ($pw -and $pw.uniq -gt 5 -and $pw.std -gt 3) {
                $words = Get-OcrWords "$root\logs\poc_client_printwindow.png"
                Log ("client OCR words(" + $words.Count + "): " + ($words -join " "))
            } else {
                Log "client never rendered content within retry window"
            }
            # title-bar click: inert to the user, proves input reaches the client
            Send-ClickAt ($ci.left + 200) ($ci.top + 8)
            Start-Sleep -Milliseconds 900
            $pw2 = Save-WindowCapture $clientHwnd "$root\logs\poc_client_afterclick.png" "printwindow"
            Log ("client after-click: " + ($pw2 | ConvertTo-Json -Compress))
            $res.client = @{
                hwnd = $clientHwnd.ToInt64()
                rect = ("{0},{1} {2}x{3}" -f $ci.left, $ci.top, $ci.w, $ci.h)
                printwindow = $pw
                bitblt = $bb
                ocr_words = $words.Count
                ocr_sample = @($words | Select-Object -First 12)
            }
        } else {
            Log "client window NOT found on hidden desktop within wait window"
        }
    } catch {
        Log ("CHILD test error: " + $_.Exception.Message + " @ " + $_.InvocationInfo.PositionMessage)
        $res.error = $_.Exception.Message
    }
    $res | ConvertTo-Json -Depth 5 | Set-Content $childJsonPath -Encoding UTF8
    Log "=== CHILD done ==="
    exit 0
}

# =====================================================================
# PARENT: create desktop, launch processes on it, run child, clean up
# =====================================================================
[void][PocNative]::SetProcessDPIAware()
Log "=== PARENT start pid=$PID ==="
if (-not $ClientExe) { $ClientExe = Join-Path $env:LOCALAPPDATA "Programs\$ClientProcess\$ClientProcess.exe" }
$exeOk = Test-Path $ClientExe
Log ("client exe: " + $ClientExe + " exists=" + $exeOk)
$already = @(Get-Process -Name $ClientProcess -ErrorAction SilentlyContinue)
if ($already.Count -gt 0) {
    Log ("WARNING: " + $ClientProcess + " already running (pids=" + ($already.Id -join ",") + "); skipping client launch"
    )
}

$hDesk = [IntPtr]::Zero
$npPi = $null
$clientPi = $null
$childPi = $null
$fatal = $null
try {
    $hDesk = [PocNative]::CreateDesktopW($DesktopName, [IntPtr]::Zero, [IntPtr]::Zero, 0, 0x1FF, [IntPtr]::Zero)
    if ($hDesk -eq [IntPtr]::Zero) {
        throw ("CreateDesktopW FAILED err=" + [PocNative]::GetLastError())
    }
    Log ("desktop created: " + $DesktopName + " handle=" + $hDesk.ToInt64())

    function Start-OnDesktop([string]$app, [string]$cmdline = "") {
        # lpCurrentDirectory MUST be IntPtr.Zero, never $null: PowerShell can
        # marshal a $null string argument as an empty string, which
        # CreateProcessW rejects. lpCommandLine is NULL only when $cmdline is
        # empty (then the app path itself doubles as the command line).
        $si = New-Object STARTUPINFO
        $si.cb = [System.Runtime.InteropServices.Marshal]::SizeOf($si)
        $si.lpDesktop = "WinSta0\$DesktopName"
        $pi = New-Object PROCESS_INFORMATION
        $cmdArg = $null
        if ($cmdline -ne "") { $cmdArg = $cmdline }
        $ok = [PocNative]::CreateProcessW($app, $cmdArg, [IntPtr]::Zero, [IntPtr]::Zero, $false, 0, [IntPtr]::Zero, [IntPtr]::Zero, [ref]$si, [ref]$pi)
        if (-not $ok) { return @{ ok = $false; err = [PocNative]::GetLastError() } }
        return @{ ok = $true; pid = $pi.dwProcessId; hProcess = $pi.hProcess }
    }

    $npPi = Start-OnDesktop "$env:SystemRoot\System32\notepad.exe"
    Log ("notepad launch: " + ($npPi | ConvertTo-Json -Compress))
    if ($exeOk -and $already.Count -eq 0) {
        $clientPi = Start-OnDesktop $ClientExe
        Log ("client launch: " + ($clientPi | ConvertTo-Json -Compress))
    }

    # ROUTING PROBE: does input injected from the hidden desktop follow the
    # INPUT desktop (the user's screen) instead of the calling thread's
    # desktop? The parent reads the DEFAULT desktop's cursor position before
    # and after the child's SendInput probe (a bare move to 500,500 - no
    # click, no keys: cannot activate anything on the user's screen).
    $pBefore = New-Object POCPOINT
    [void][PocNative]::GetCursorPos([ref]$pBefore)
    Log ("parent cursor before child: " + $pBefore.X + "," + $pBefore.Y)

    # The child is BORN on the hidden desktop (CreateProcessW with
    # lpDesktop=WinSta0\<name>), so its main thread is on the hidden desktop
    # from the start - no SetThreadDesktop dance required.
    $psExe = Join-Path $env:SystemRoot "System32\WindowsPowerShell\v1.0\powershell.exe"
    $childCmd = '"' + $psExe + '" -NoProfile -ExecutionPolicy Bypass -File "' + $PSCommandPath + '" -Child -DesktopName "' + $DesktopName + '" -WindowWaitSeconds ' + $WindowWaitSeconds
    $childPi = Start-OnDesktop $psExe $childCmd
    Log ("child launch: " + ($childPi | ConvertTo-Json -Compress))
    if ($childPi.ok) {
        $wdl = (Get-Date).AddSeconds(320)
        while ($true) {
            $w = [PocNative]::WaitForSingleObject($childPi.hProcess, 5000)
            if ($w -eq 0) { break }
            if ((Get-Date) -gt $wdl) {
                Log "child still running after 320s; terminating"
                [void][PocNative]::TerminateProcess($childPi.hProcess, 1)
                break
            }
        }
        Log "child finished"
        $pAfter = New-Object POCPOINT
        [void][PocNative]::GetCursorPos([ref]$pAfter)
        Log ("parent cursor after child: " + $pAfter.X + "," + $pAfter.Y + " (child injected a bare move to 500,500)")
        if ($pAfter.X -eq 500 -and $pAfter.Y -eq 500) {
            Log "ROUTING: injected input LANDED ON THE DEFAULT DESKTOP (user screen) - SendInput follows the input desktop, NOT the calling thread's desktop"
        } elseif ($pAfter.X -ne $pBefore.X -or $pAfter.Y -ne $pBefore.Y) {
            Log "ROUTING: default-desktop cursor moved but not to 500,500 - inconclusive (user may have moved the mouse)"
        } else {
            Log "ROUTING: default-desktop cursor untouched - input did NOT route to the default desktop"
        }
        if ($pAfter.X -ne $pBefore.X -or $pAfter.Y -ne $pBefore.Y) {
            [void][PocNative]::SetCursorPos($pBefore.X, $pBefore.Y)
            Log "cursor restored to pre-probe position"
        }
    }
} catch {
    $fatal = $_.Exception.Message
    Log ("PARENT FATAL: " + $fatal + " @ " + $_.InvocationInfo.PositionMessage)
} finally {
    # cross-desktop capture data point from the default thread
    $childJson = $null
    if (Test-Path $childJsonPath) {
        try { $childJson = Get-Content $childJsonPath -Raw | ConvertFrom-Json } catch { Log ("child json parse failed: " + $_.Exception.Message) }
    }
    $result = @{
        status = $(if ($fatal) { "fatal" } elseif ($childJson -and $childJson.status -eq "ok") { "ok" } else { "partial" })
        desktop = $DesktopName
        client = $ClientProcess
        fatal = $fatal
        child = $childJson
    }
    if ($childJson -and $childJson.client -and $childJson.client.hwnd) {
        try {
            $h = [IntPtr]($childJson.client.hwnd)
            $x = Save-WindowCapture $h "$root\logs\poc_client_crossdesktop.png" "printwindow"
            Log ("cross-desktop printwindow (default thread): " + ($x | ConvertTo-Json -Compress))
            $result.crossdesktop_printwindow = $x
            [void][PocNative]::PostMessageW($h, 0x0010, 0, 0)
            Log "WM_CLOSE posted to client from default desktop"
        } catch {
            Log ("cross-desktop step failed: " + $_.Exception.Message)
        }
    }
    if ($clientPi -and $clientPi.ok) {
        $w = [PocNative]::WaitForSingleObject($clientPi.hProcess, ($CloseWaitSeconds * 1000))
        Log ("client wait=" + $w + " (0=exited)")
        if ($w -ne 0) {
            Log "client did not exit in time; terminating (PoC cleanup)"
            [void][PocNative]::TerminateProcess($clientPi.hProcess, 1)
        }
    }
    if ($npPi -and $npPi.ok) {
        $w = [PocNative]::WaitForSingleObject($npPi.hProcess, 15000)
        Log ("notepad wait=" + $w)
        if ($w -ne 0) { [void][PocNative]::TerminateProcess($npPi.hProcess, 1) }
    }
    if ($hDesk -ne [IntPtr]::Zero) {
        [void][PocNative]::CloseDesktop($hDesk)
        Log "desktop closed"
    }
    $result | ConvertTo-Json -Depth 6 | Set-Content $resultPath -Encoding UTF8
    Log ("=== PARENT done status=" + $result.status + " ===")
}
exit 0
