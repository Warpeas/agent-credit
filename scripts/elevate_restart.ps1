# Elevated helper: kill all AutoClaw processes, then relaunch with accessibility flag.
$ErrorActionPreference = "SilentlyContinue"
taskkill /IM AutoClaw.exe /F | Out-Null
Start-Sleep -Seconds 3
Start-Process 'C:\Program Files\AutoClaw\AutoClaw.exe' -ArgumentList '--force-renderer-accessibility'
