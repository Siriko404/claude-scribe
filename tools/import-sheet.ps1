# Cuts an upscaled contact sheet back into assets/frames/frame-NN.png.
#
# Cell size is derived from the returned image, so any output resolution works
# as long as the 8x6 grid and frame order survive. Magenta is keyed back out to
# transparency, and near-magenta edge pixels are de-fringed rather than kept --
# an upscaler will always blend some key colour into the sprite outline.
#
#   powershell -ExecutionPolicy Bypass -File tools/import-sheet.ps1 -Sheet upscaled.png
#   ... add -DryRun to inspect without overwriting the current frames

param(
  [Parameter(Mandatory = $true)][string]$Sheet,
  [int]$Cols = 8,
  [int]$Rows = 6,
  [int]$Frames = 44,
  [switch]$DryRun
)

Add-Type -AssemblyName System.Drawing

$src = [System.Drawing.Image]::FromFile((Resolve-Path $Sheet))
$cellW = [int]($src.Width / $Cols)
$cellH = [int]($src.Height / $Rows)
Write-Host "sheet $($src.Width)x$($src.Height) -> $Cols x $Rows grid, cells ${cellW}x${cellH}"

if ($cellW -lt 32 -or $cellH -lt 32) { throw "cells too small - is this the right sheet?" }

$outDir = Join-Path $PSScriptRoot "..\assets\frames"
if (-not $DryRun) {
  $backup = Join-Path $PSScriptRoot "..\assets\frames-original"
  if (-not (Test-Path $backup)) {
    Copy-Item $outDir $backup -Recurse
    Write-Host "kept the originals in assets/frames-original"
  }
}

$kept = 0
for ($n = 0; $n -lt $Frames; $n++) {
  $rect = New-Object System.Drawing.Rectangle (($n % $Cols) * $cellW), ([int][math]::Floor($n / $Cols) * $cellH), $cellW, $cellH
  $cell = $src.Clone($rect, [System.Drawing.Imaging.PixelFormat]::Format32bppArgb)

  # Key out the magenta and soften whatever the upscaler bled into the edges.
  $keyed = 0
  for ($y = 0; $y -lt $cell.Height; $y++) {
    for ($x = 0; $x -lt $cell.Width; $x++) {
      $p = $cell.GetPixel($x, $y)
      $magentaness = [math]::Min($p.R, $p.B) - $p.G
      if ($magentaness -gt 60) {
        $cell.SetPixel($x, $y, [System.Drawing.Color]::FromArgb(0, 0, 0, 0))
        $keyed++
      }
      elseif ($magentaness -gt 20) {
        # fringe: drop the magenta cast, keep the pixel
        $g = [int][math]::Min(255, $p.G + $magentaness * 0.5)
        $cell.SetPixel($x, $y, [System.Drawing.Color]::FromArgb($p.A, $p.R, $g, $p.B))
      }
    }
  }

  if (-not $DryRun) {
    $cell.Save((Join-Path $outDir ("frame-{0:d2}.png" -f $n)), [System.Drawing.Imaging.ImageFormat]::Png)
  }
  $cell.Dispose()
  $kept++
  if ($n % 11 -eq 0) { Write-Host "  frame $n : $keyed px keyed to transparent" }
}
$src.Dispose()

if ($DryRun) { Write-Host "dry run - $kept frames sliced, nothing written" }
else { Write-Host "wrote $kept frames to assets/frames at ${cellW}x${cellH}" }
Write-Host "restart the panel to pick them up"
