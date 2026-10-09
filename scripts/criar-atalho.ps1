# Cria (ou recria) o icone e o atalho "PonteAnimada" na Area de Trabalho.
# Rode de novo se mover a pasta do projeto.

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$icon = Join-Path $PSScriptRoot 'ponte.ico'

# --- Icone: o mesmo desenho de web/icon.svg (ponte ambar sobre fundo escuro) -------
Add-Type -AssemblyName System.Drawing
$size = 256
$bmp = New-Object System.Drawing.Bitmap $size, $size
$g = [System.Drawing.Graphics]::FromImage($bmp)
$g.SmoothingMode = 'AntiAlias'
$g.Clear([System.Drawing.Color]::Transparent)

$r = 56
$path = New-Object System.Drawing.Drawing2D.GraphicsPath
$path.AddArc(0, 0, $r * 2, $r * 2, 180, 90)
$path.AddArc($size - $r * 2, 0, $r * 2, $r * 2, 270, 90)
$path.AddArc($size - $r * 2, $size - $r * 2, $r * 2, $r * 2, 0, 90)
$path.AddArc(0, $size - $r * 2, $r * 2, $r * 2, 90, 90)
$path.CloseFigure()
$g.FillPath((New-Object System.Drawing.SolidBrush ([System.Drawing.Color]::FromArgb(27, 30, 36))), $path)

$amber = New-Object System.Drawing.Pen ([System.Drawing.Color]::FromArgb(240, 164, 58)), 16
$amber.StartCap = 'Round'; $amber.EndCap = 'Round'
$thin = New-Object System.Drawing.Pen ([System.Drawing.Color]::FromArgb(240, 164, 58)), 12
$thin.StartCap = 'Round'; $thin.EndCap = 'Round'
$deck = New-Object System.Drawing.Pen ([System.Drawing.Color]::FromArgb(230, 232, 236)), 16
$deck.StartCap = 'Round'; $deck.EndCap = 'Round'

$g.DrawArc($amber, 48, 72, 160, 208, 180, 180)   # arco da ponte
foreach ($x in 88, 128, 168) {                    # pendurais
    $top = if ($x -eq 128) { 76 } else { 112 }
    $g.DrawLine($thin, $x, $top, $x, 176)
}
$g.DrawLine($deck, 32, 176, 224, 176)             # tabuleiro
$g.Dispose()

$png = New-Object System.IO.MemoryStream
$bmp.Save($png, [System.Drawing.Imaging.ImageFormat]::Png)
$bmp.Dispose()
$bytes = $png.ToArray()

# Container ICO com um unico PNG de 256x256 (formato aceito desde o Windows Vista).
$ico = New-Object System.IO.MemoryStream
$w = New-Object System.IO.BinaryWriter $ico
$w.Write([uint16]0); $w.Write([uint16]1); $w.Write([uint16]1)          # reservado, tipo icone, 1 imagem
$w.Write([byte]0); $w.Write([byte]0); $w.Write([byte]0); $w.Write([byte]0)  # 256x256, sem paleta
$w.Write([uint16]1); $w.Write([uint16]32)                                # planos, bits por pixel
$w.Write([uint32]$bytes.Length); $w.Write([uint32]22)                    # tamanho e posicao do PNG
$w.Write($bytes)
$w.Flush()
[System.IO.File]::WriteAllBytes($icon, $ico.ToArray())

# --- Atalho ---------------------------------------------------------------------
$desktop = [Environment]::GetFolderPath('Desktop')
$link = Join-Path $desktop 'PonteAnimada.lnk'
$shell = New-Object -ComObject WScript.Shell
$shortcut = $shell.CreateShortcut($link)
$shortcut.TargetPath = Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe'
$shortcut.Arguments = "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$(Join-Path $PSScriptRoot 'abrir.ps1')`""
$shortcut.WorkingDirectory = $root
$shortcut.IconLocation = "$icon,0"
$shortcut.Description = 'PonteAnimada - validar personagens e animacoes'
$shortcut.WindowStyle = 7
$shortcut.Save()

Write-Host "Atalho criado: $link"
