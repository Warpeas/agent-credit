# MonkeyCode UIA probe.
# 用 Windows UI Automation 读取 WebView2 的可访问树，按控件名定位：
#   - 设置（齿轮按钮：面板关着时存在）
#   - 账号（面板左侧导航：面板开着时存在）
#   - 签到 / 今日已签到（账号页的积分卡片按钮）
#   - 用微信扫一扫登录等（登录态失效时的扫码页）
# 只报告状态和屏幕坐标，不点击。点击由 Python 侧用 SetCursorPos+mouse_event 完成，
# 这样既不受分辨率/DPI/窗口比例影响，又能绕开 WebView2 对 isTrusted 的过滤。
#
# 结果写入 -OutFile（UTF-8 无 BOM 的 JSON），stdout 保持安静。
param(
    [Parameter(Mandatory = $true)][int]$Hwnd,
    [string]$OutFile = "",
    # 方案甲：窗口停在屏外时 IsOffscreen 全为 true，仍需按名字定位控件。
    [switch]$AllowOffscreen
)

$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName UIAutomationClient
Add-Type -AssemblyName UIAutomationTypes

if (-not $OutFile) {
    $OutFile = Join-Path (Split-Path -Parent $PSScriptRoot) 'logs\_monkeycode_uia.json'
}

function Write-Result($obj) {
    $dir = Split-Path -Parent $OutFile
    if ($dir -and -not (Test-Path $dir)) { New-Item -ItemType Directory -Path $dir -Force | Out-Null }
    $json = $obj | ConvertTo-Json -Compress -Depth 4
    [System.IO.File]::WriteAllText($OutFile, $json, (New-Object System.Text.UTF8Encoding($false)))
}

function Get-Center($el) {
    $r = $el.Current.BoundingRectangle
    return @{
        name = $el.Current.Name
        x    = [int]($r.X + $r.Width / 2)
        y    = [int]($r.Y + $r.Height / 2)
        w    = [int]$r.Width
        h    = [int]$r.Height
    }
}

try {
    $root = [System.Windows.Automation.AutomationElement]::FromHandle([IntPtr]$Hwnd)
} catch {
    $root = $null
}
if ($null -eq $root) {
    Write-Result @{ state = 'unavailable'; detail = 'FromHandle failed' }
    exit 1
}

$all = $root.FindAll(
    [System.Windows.Automation.TreeScope]::Descendants,
    [System.Windows.Automation.Condition]::TrueCondition)

$settings = $null
$claim = $null
$already = $null
$nav = $null
$login = $null
$connect = $null

foreach ($e in $all) {
    try {
        $ct = $e.Current.ControlType.ProgrammaticName
        $n = $e.Current.Name
        $off = $e.Current.IsOffscreen
    } catch {
        continue
    }
    if (-not $n -or ($off -and -not $AllowOffscreen)) { continue }

    # 会话失效时账号页会出现绿色「连接 / 重新连接」按钮（2026-10-26 主人实测：
    # 点一下即可恢复登录态并回写 cookies.json）。只认整词，排除「断开连接」。
    if (-not $connect -and $n -match '^\s*(重新)?连接(\s*MonkeyCode.*)?\s*$') {
        $connect = $e
    }

    if ($ct -eq 'ControlType.Button') {
        if ($n -eq '设置') {
            $settings = $e
        }
        elseif ($n -match '^\s*今日已签到') {
            $already = $e
        }
        elseif ($n -match '^\s*签到') {
            $claim = $e
        }
        elseif ($n -eq '账号') {
            $nav = $e
        }
    }
    if (-not $login -and $n -match '用微信扫一扫登录|微信扫码|扫码登录') {
        $login = $e
    }
}

# 面板打开时「今日已签到」可能被前端渲染成 Text 而不是 Button。
# 屏外模式下 AllowOffscreen 会让主界面聊天记录里的同一句话也进入结果，
# 所以只在「账号」按钮所在的容器内扫描（自指污染防护）。
if ($nav) {
    $panel = $null
    try {
        $panel = [System.Windows.Automation.TreeWalker]::ControlViewWalker.GetParent($nav)
    } catch { }
    $scope = $all
    if ($panel) {
        try {
            $scope = $panel.FindAll(
                [System.Windows.Automation.TreeScope]::Descendants,
                [System.Windows.Automation.Condition]::TrueCondition)
        } catch {
            $scope = $all
        }
    }
    if (-not $already) {
        foreach ($e in $scope) {
            try {
                $n = $e.Current.Name
                $off = $e.Current.IsOffscreen
            } catch {
                continue
            }
            if ((-not $off -or $AllowOffscreen) -and $n -match '^\s*今日已签到') {
                $already = $e
                break
            }
        }
    }
    # 面板打开时只信面板内的登录标记，避免主界面聊天文本里的「微信扫码」误判。
    $login = $null
    foreach ($e in $scope) {
        try {
            $n = $e.Current.Name
            $off = $e.Current.IsOffscreen
        } catch {
            continue
        }
        if ((-not $off -or $AllowOffscreen) -and $n -match '用微信扫一扫登录|微信扫码|扫码登录') {
            $login = $e
            break
        }
    }
}

# 状态判定顺序刻意固定：
#  1) 面板关着时，主界面聊天记录里也有大量「签到/微信扫码」文字，
#     但它们不是 Button 且不在账号页；所以先看设置齿轮，避免把聊天文本当登录页。
#  2) 面板打开后 UIA 树只剩面板内容，这时再看登录标记才不会误判。
if ($claim -or $already) {
    $state = 'account'
}
elseif ($nav) {
    if ($login) { $state = 'login' } else { $state = 'other' }
}
elseif ($settings) {
    $state = 'closed'
}
else {
    $state = 'unknown'
}

$obj = @{
    state = $state
    count = [int]$all.Count
}

if ($state -eq 'closed') {
    $obj.settings = Get-Center $settings
}
elseif ($state -eq 'account') {
    $obj.already = [bool]$already
    if ($already) {
        $obj.claim_name = $already.Current.Name
    }
    else {
        $obj.claim = Get-Center $claim
    }
}
elseif ($state -eq 'other') {
    $obj.account_nav = Get-Center $nav
    if ($connect) { $obj.connect = Get-Center $connect }
}
elseif ($state -eq 'login') {
    $obj.login_marker = $login.Current.Name
    $obj.login = Get-Center $login
}

Write-Result $obj
exit 0
