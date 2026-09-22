# One-shot elevated runner: register task (log errors), then OCR checkin.
$log = 'C:\Users\Hunter\Documents\Warpeas\agent-credit\logs\register_out.txt'
try {
    & 'C:\Users\Hunter\Documents\Warpeas\agent-credit\scripts\register-task.ps1' 2>&1 |
        ForEach-Object { $_.ToString() } | Out-File $log -Encoding utf8
} catch {
    $_ | Out-String | Out-File $log -Encoding utf8 -Append
}
& 'C:\Users\Hunter\Documents\Warpeas\agent-credit\scripts\ui_claim_autoclaw.ps1' -OutFile 'C:\Users\Hunter\Documents\Warpeas\agent-credit\logs\autoclaw_claim.json'
