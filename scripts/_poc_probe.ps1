# Diagnostic probe for CreateDesktopW failure inside the scheduled-task context.
# Run via a one-off Interactive/Limited task (same context as _poc_desktop.ps1).
# Answers: are we in WinSta0? can we open Default desktop? what is the REAL
# last-error for CreateDesktopW (with SetLastError=true)? does the desktop name
# or the access mask matter?
param(
    [string]$LogFile = ""
)

$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$root = Split-Path -Parent $PSScriptRoot
if (-not $LogFile) { $LogFile = "$root\logs\poc_probe.log" }

function Log($m) {
    $s = (Get-Date -Format "HH:mm:ss") + " " + $m
    try { [System.IO.File]::AppendAllText($LogFile, $s + "`n", (New-Object System.Text.UTF8Encoding($false))) } catch {}
    Write-Output $s
}

Add-Type @"
using System;
using System.Runtime.InteropServices;

public static class PocProbe {
  [DllImport("user32.dll", CharSet = CharSet.Unicode, SetLastError = true)] public static extern IntPtr CreateDesktopW(string lpszDesktop, string lpszDevice, IntPtr pDevmode, int dwFlags, int dwDesiredAccess, IntPtr lpsa);
  [DllImport("user32.dll", CharSet = CharSet.Unicode, SetLastError = true)] public static extern IntPtr OpenDesktopW(string lpszDesktop, int dwFlags, bool fInherit, int dwDesiredAccess);
  [DllImport("user32.dll", CharSet = CharSet.Unicode, SetLastError = true)] public static extern IntPtr OpenWindowStationW(string lpszWinSta, bool fInherit, int dwDesiredAccess);
  [DllImport("user32.dll", SetLastError = true)] public static extern bool SetThreadDesktop(IntPtr hDesktop);
  [DllImport("user32.dll", SetLastError = true)] public static extern IntPtr GetThreadDesktop(int dwThreadId);
  [DllImport("user32.dll", SetLastError = true)] public static extern IntPtr GetProcessWindowStation();
  [DllImport("user32.dll")] public static extern bool CloseDesktop(IntPtr hDesktop);
  [DllImport("user32.dll")] public static extern bool CloseWindowStation(IntPtr hWinSta);
  [DllImport("kernel32.dll", SetLastError = true)] public static extern int GetCurrentThreadId();
  [DllImport("kernel32.dll", SetLastError = true)] public static extern int GetLastError();
  [DllImport("kernel32.dll")] public static extern int GetCurrentProcessId();
}
"@

Log "=== PROBE start pid=$PID mgrpid=$([PocProbe]::GetCurrentProcessId()) ==="
$tid = [PocProbe]::GetCurrentThreadId()
$td = [PocProbe]::GetThreadDesktop($tid)
Log ("thread desktop handle=" + $td.ToInt64())
$ws = [PocProbe]::GetProcessWindowStation()
Log ("process window station handle=" + $ws.ToInt64())

$wsOpen = [PocProbe]::OpenWindowStationW("WinSta0", $false, 0x37F)
if ($wsOpen -eq [IntPtr]::Zero) {
    Log ("OpenWindowStation(WinSta0, ALL) FAIL err=" + [PocProbe]::GetLastError())
} else {
    Log ("OpenWindowStation(WinSta0, ALL) ok handle=" + $wsOpen.ToInt64())
    [void][PocProbe]::CloseWindowStation($wsOpen)
}

$def = [PocProbe]::OpenDesktopW("Default", 0, $false, 0x1FF)
if ($def -eq [IntPtr]::Zero) {
    Log ("OpenDesktop(Default) FAIL err=" + [PocProbe]::GetLastError())
} else {
    Log ("OpenDesktop(Default) ok handle=" + $def.ToInt64())
    [void][PocProbe]::CloseDesktop($def)
}

foreach ($name in @("agent-credit", "PocProbe1")) {
    foreach ($access in @(0x1FF, 0x10000000, 0)) {
        $h = [PocProbe]::CreateDesktopW($name, $null, [IntPtr]::Zero, 0, $access, [IntPtr]::Zero)
        $err = [PocProbe]::GetLastError()
        if ($h -eq [IntPtr]::Zero) {
            $msg = ""
            try { $msg = (New-Object ComponentModel.Win32Exception($err)).Message } catch {}
            Log ("CreateDesktop name=$name access=$access FAIL err=$err msg=$msg")
        } else {
            Log ("CreateDesktop name=$name access=$access OK handle=" + $h.ToInt64())
            $h2 = [PocProbe]::OpenDesktopW($name, 0, $false, 0x1FF)
            if ($h2 -eq [IntPtr]::Zero) {
                Log ("  reopen FAIL err=" + [PocProbe]::GetLastError())
            } else {
                Log ("  reopen ok handle=" + $h2.ToInt64())
                [void][PocProbe]::CloseDesktop($h2)
            }
            [void][PocProbe]::CloseDesktop($h)
            Log "  closed"
        }
    }
}
Log "=== PROBE done ==="
exit 0
