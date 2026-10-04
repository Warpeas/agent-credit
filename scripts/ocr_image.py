#!/usr/bin/env python3
"""对一张 PNG 跑 WinRT OCR，输出行级+ 词级坐标（JSON）。

为什么独立成工具：项目里已有多个脚本需要 OCR（ui_claim_*.ps1、forensics_*），
但它们各自内联一份 WinRT 初始化代码。这里抽成单一只读工具，
新脚本直接调它，不再重复踩WinRT 程序集加载的坑。

**关键坑（本机 PowerShell 5.1 实测）**：
`[System.WindowsRuntimeSystemExtensions]` 在新起的powershell 进程里
**默认不存在**，直接用会报「找不到类型」。必须先
`Add-Type -AssemblyName System.Runtime.WindowsRuntime`。
`ui_claim_*.ps1` 能跑是因为它们在同一进程内先做了别的加载顺序。

用法：
    python scripts/ocr_image.py <png路径> [--json out.json]
输出：stdout 为 JSON 数组 [{text,x,y,w,h}, ...]
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
from pathlib import Path

PS_SRC = r"""param([string]$Png)
$ErrorActionPreference = "Stop"
# 关键：PS 5.1 默认按 GBK 输出，中文会变乱码。
# [Console]::OutputEncoding 只影响控制台，重定向到管道时要用 OutputEncoding。
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$OutputEncoding = [System.Text.Encoding]::UTF8
Add-Type -AssemblyName System.Drawing
Add-Type -AssemblyName System.Runtime.WindowsRuntime
$null = [Windows.Media.Ocr.OcrEngine, Windows.Foundation, ContentType = WindowsRuntime]
$null = [Windows.Globalization.Language, Windows.Foundation, ContentType = WindowsRuntime]
$null = [Windows.Graphics.Imaging.SoftwareBitmap, Windows.Foundation, ContentType = WindowsRuntime]
$null = [Windows.Storage.Streams.InMemoryRandomAccessStream, Windows.Foundation, ContentType = WindowsRuntime]

$asTask = ([System.WindowsRuntimeSystemExtensions].GetMethods() | Where-Object {
  $_.Name -eq 'AsTask' -and $_.GetParameters().Count -eq 1 -and
  $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncOperation`1' })[0]
if (-not $asTask) { Write-Output "ERR: asTask reflection got null"; exit 1 }

function Await($op, $t) {
  $m = $asTask.MakeGenericMethod($t)
  $x = $m.Invoke($null, @($op))
  $x.Wait(-1) | Out-Null
  return $x.Result
}

$langs = [Windows.Media.Ocr.OcrEngine]::AvailableRecognizerLanguages
$zh = $langs | Where-Object { $_.LanguageTag -like "zh*" } | Select-Object -First 1
$engine = $null
if ($zh) { $engine = [Windows.Media.Ocr.OcrEngine]::TryCreateFromLanguage($zh) }
if (-not $engine) { $engine = [Windows.Media.Ocr.OcrEngine]::TryCreateFromUserProfileLanguages() }
if (-not $engine) { Write-Output "ERR: no OCR engine"; exit 1 }

$lines = @()
try {
  $bmp = New-Object System.Drawing.Bitmap($Png)
  $ms = New-Object System.IO.MemoryStream
  $bmp.Save($ms, [System.Drawing.Imaging.ImageFormat]::Png)
  $bmp.Dispose()
  $bytes = $ms.ToArray()
  $ms.Dispose()
  $stream = New-Object Windows.Storage.Streams.InMemoryRandomAccessStream
  $dw = New-Object Windows.Storage.Streams.DataWriter($stream.GetOutputStreamAt(0))
  $dw.WriteBytes($bytes)
  Await ($dw.StoreAsync()) ([uint32]) | Out-Null
  Await ($dw.FlushAsync()) ([bool]) | Out-Null
  $dec = Await ([Windows.Graphics.Imaging.BitmapDecoder]::CreateAsync($stream)) ([Windows.Graphics.Imaging.BitmapDecoder])
  $sbmp = Await ($dec.GetSoftwareBitmapAsync()) ([Windows.Graphics.Imaging.SoftwareBitmap])
  $res = Await ($engine.RecognizeAsync($sbmp)) ([Windows.Media.Ocr.OcrResult])
  foreach ($ln in $res.Lines) {
    $t = ($ln.Text -replace "\s", "")
    if ([string]::IsNullOrWhiteSpace($t)) { continue }
    $minX = 999999; $minY = 999999; $maxX = 0; $maxY = 0
    foreach ($wd in $ln.Words) {
      $br = $wd.BoundingRect
      if ($br.X -lt $minX) { $minX = [int]$br.X }
      if ($br.Y -lt $minY) { $minY = [int]$br.Y }
      if (($br.X + $br.Width) -gt $maxX) { $maxX = [int]($br.X + $br.Width) }
      if (($br.Y + $br.Height) -gt $maxY) { $maxY = [int]($br.Y + $br.Height) }
    }
    $lines += @{ text = $t; x = $minX; y = $minY; w = ($maxX - $minX); h = ($maxY - $minY) }
  }
} catch {
  Write-Output ("ERR: " + $_.Exception.Message)
  exit 1
}
if ($lines.Count -eq 0) { Write-Output "[]"; exit 0 }
$lines | ConvertTo-Json -Compress -Depth 4
"""


def ocr_lines(png: Path) -> list[dict]:
    with tempfile.NamedTemporaryFile("w", suffix=".ps1", delete=False,
                                     encoding="utf-8-sig") as f:
        f.write(PS_SRC)
        script = f.name
    try:
        r = subprocess.run(
            ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass",
             "-File", script, "-Png", str(png)],
            capture_output=True, text=True, encoding="utf-8",
            errors="replace", timeout=120)
    except subprocess.TimeoutExpired:
        return []
    finally:
        Path(script).unlink(missing_ok=True)
    out = (r.stdout or "").strip()
    if not out or out.startswith("ERR"):
        print(f"[ocr_image] {out[:200]}", file=sys.stderr)
        return []
    try:
        data = json.loads(out)
    except json.JSONDecodeError:
        print(f"[ocr_image] parse fail: {out[:200]}", file=sys.stderr)
        return []
    return data if isinstance(data, list) else [data]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("png")
    ap.add_argument("--json", default="", help="同时写入这个文件")
    args = ap.parse_args()
    p = Path(args.png)
    if not p.exists():
        print(f"not found: {p}", file=sys.stderr)
        return 1
    lines = ocr_lines(p)
    blob = json.dumps(lines, ensure_ascii=False, indent=2)
    if args.json:
        Path(args.json).write_text(blob, encoding="utf-8")
    print(blob)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
