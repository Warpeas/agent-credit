# Phase 1 helper: launch a GUI app DE-ELEVATED by handing it to the running
# (non-elevated) shell. The app becomes a child of explorer, survives this
# process exit, and can then be driven by NON-elevated scripts (no UAC).
# ASCII code only. Run elevated (runas) ONCE per session.
param([string]$Exe)
if(-not (Test-Path $Exe)){ Write-Output ("EXE MISSING: " + $Exe); exit 1 }
Start-Process explorer.exe -ArgumentList ('"' + $Exe + '"')
Write-Output ("handed to shell: " + $Exe)
