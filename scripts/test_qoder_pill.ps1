# 黑药丸扫描（ui_claim_qodercn.ps1 的 Pill.Find）离线回归。
#
# 为什么需要：这段扫描决定「能不能点到领取按钮」——漏检=当天 pending，
# 误检=点到别的东西。2026-10-30 把它从 PowerShell 逐像素循环换成 LockBits 编译版
# （3600x2090 从 130s 降到 25ms），判据必须逐条锁住：
#   1) 32bpp / 24bpp 截图都能命中（LockBits 只认原图格式，脚本里会转一份 32bpp）
#   2) 命中点落在按钮中心附近
#   3) 只有深绿（非中性色）长条时必须不命中——底栏「查看详情」不能被当成按钮
#
# 运行：powershell -NoProfile -ExecutionPolicy Bypass -File scripts/test_qoder_pill.ps1
$ErrorActionPreference = "Stop"
Add-Type -AssemblyName System.Drawing

$root = Split-Path -Parent $PSScriptRoot
$src = Get-Content -Raw -Encoding UTF8 "$root\scripts\ui_claim_qodercn.ps1"
$m = [regex]::Match($src, '(?s)\$pillSig = @"(.*?)"@')
if (-not $m.Success) { throw "pillSig block not found in ui_claim_qodercn.ps1" }
Add-Type -ReferencedAssemblies System.Drawing -TypeDefinition $m.Groups[1].Value

$W = 1200
$H = 800
$fail = 0

function New-Canvas([System.Drawing.Imaging.PixelFormat]$fmt) {
    $bmp = New-Object System.Drawing.Bitmap($W, $H, $fmt)
    $g = [System.Drawing.Graphics]::FromImage($bmp)
    $g.Clear([System.Drawing.Color]::FromArgb(255, 245, 245, 245))
    $g.Dispose()
    return $bmp
}

function Add-Rect($bmp, [int]$x, [int]$y, [int]$w, [int]$h, [System.Drawing.Color]$c) {
    $g = [System.Drawing.Graphics]::FromImage($bmp)
    $br = New-Object System.Drawing.SolidBrush($c)
    $g.FillRectangle($br, $x, $y, $w, $h)
    $br.Dispose()
    $g.Dispose()
}

# 背景亮度 245；按钮范围 x 0.40-0.74W = 480-888、y 0.40-0.90H = 320-720。
$pillX = 700
$pillY = 500
$pillW = 160
$pillH = 60

foreach ($fmt in @([System.Drawing.Imaging.PixelFormat]::Format32bppArgb,
                   [System.Drawing.Imaging.PixelFormat]::Format24bppRgb)) {
    $bmp = New-Canvas $fmt
    Add-Rect $bmp $pillX $pillY $pillW $pillH ([System.Drawing.Color]::FromArgb(255, 24, 24, 26))
    $hit = [Pill]::Find($bmp, 0.40, 0.74, 0.40, 0.90)
    $name = $fmt.ToString()
    if (-not $hit) {
        Write-Host "FAIL $name : black pill not found"
        $fail++
    } else {
        $dx = [Math]::Abs($hit[0] - ($pillX + [int]($pillW / 2)))
        $dy = [Math]::Abs($hit[1] - ($pillY + [int]($pillH / 2)))
        if ($dx -gt 60 -or $dy -gt 30) {
            Write-Host "FAIL $name : hit $($hit[0]),$($hit[1]) too far from pill centre"
            $fail++
        } else {
            Write-Host "PASS $name : hit $($hit[0]),$($hit[1])"
        }
    }
    $bmp.Dispose()
}

# 深绿长条（模拟底栏「查看详情」）：饱和度高，必须被判成非中性黑。
$bmp = New-Canvas ([System.Drawing.Imaging.PixelFormat]::Format32bppArgb)
Add-Rect $bmp $pillX $pillY $pillW $pillH ([System.Drawing.Color]::FromArgb(255, 10, 92, 58))
$hit = [Pill]::Find($bmp, 0.40, 0.74, 0.40, 0.90)
if ($hit) {
    Write-Host "FAIL green bar : false positive at $($hit[0]),$($hit[1])"
    $fail++
} else {
    Write-Host "PASS green bar : not treated as pill"
}
$bmp.Dispose()

if ($fail -gt 0) {
    Write-Host "FAIL count = $fail"
    exit 1
}
Write-Host "FAIL count = 0"
