# One-shot elevated runner: register task (log errors), then OCR checkin.
$root = Split-Path -Parent $PSScriptRoot
$log = '$root\logs\register_out.txt'
try {
    & '$root\scripts\register-task.ps1' 2>&1 |
        ForEach-Object { $_.ToString() } | Out-File $log -Encoding utf8
} catch {
    $_ | Out-String | Out-File $log -Encoding utf8 -Append
}
& '$root\scripts\ui_claim_autoclaw.ps1' -OutFile '$root\logs\autoclaw_claim.json'
