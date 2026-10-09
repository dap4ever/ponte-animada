# Cria (ou recria) os icones e os dois atalhos do ARDY na Area de Trabalho:
#   "ARDY - ao vivo"         demo interativo: digita-se o pedido e conduz-se o boneco
#   "ARDY - zumbi de teste"  mostra o clipe de teste ja gerado
# Rode de novo se mover a pasta do projeto.
# Textos sem acento de proposito: o PowerShell 5.1 le .ps1 sem BOM como ANSI.

$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Drawing

function New-ArdyIcon([string]$file, [System.Drawing.Color]$color, [bool]$play) {
    # Boneco andando sobre o mesmo fundo escuro do icone da ponte. Com $play, um triangulo
    # de "tocar" no canto.
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

    $brush = New-Object System.Drawing.SolidBrush $color
    $pen = New-Object System.Drawing.Pen $color, 18
    $pen.StartCap = 'Round'; $pen.EndCap = 'Round'
    $dx = if ($play) { -22 } else { 0 }           # abre espaco para o triangulo
    $g.FillEllipse($brush, 112 + $dx, 34, 46, 46)             # cabeca
    $g.DrawLine($pen, 132 + $dx, 92, 120 + $dx, 160)          # tronco, inclinado para frente
    $g.DrawLine($pen, 130 + $dx, 108, 172 + $dx, 128)         # braco da frente
    $g.DrawLine($pen, 130 + $dx, 108, 96 + $dx, 140)          # braco de tras
    $g.DrawLine($pen, 120 + $dx, 160, 158 + $dx, 214)         # perna da frente
    $g.DrawLine($pen, 120 + $dx, 160, 88 + $dx, 214)          # perna de tras
    if ($play) {
        $triangle = @(
            (New-Object System.Drawing.Point 172, 150),
            (New-Object System.Drawing.Point 172, 222),
            (New-Object System.Drawing.Point 230, 186)
        )
        $g.FillPolygon($brush, [System.Drawing.Point[]]$triangle)
    }
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
    [System.IO.File]::WriteAllBytes($file, $ico.ToArray())
}

function New-ArdyShortcut([string]$name, [string]$script, [string]$icon, [string]$description) {
    $link = Join-Path ([Environment]::GetFolderPath('Desktop')) "$name.lnk"
    $shortcut = (New-Object -ComObject WScript.Shell).CreateShortcut($link)
    $shortcut.TargetPath = Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe'
    $shortcut.Arguments = "-NoProfile -ExecutionPolicy Bypass -File `"$(Join-Path $PSScriptRoot $script)`""
    $shortcut.WorkingDirectory = $PSScriptRoot
    $shortcut.IconLocation = "$icon,0"
    $shortcut.Description = $description
    $shortcut.WindowStyle = 1
    $shortcut.Save()
    Write-Host "Atalho criado: $link"
}

$green = [System.Drawing.Color]::FromArgb(140, 205, 95)
$blue = [System.Drawing.Color]::FromArgb(95, 175, 240)

$iconLive = Join-Path $PSScriptRoot 'ardy-ao-vivo.ico'
New-ArdyIcon $iconLive $blue $true
New-ArdyShortcut 'ARDY - ao vivo' 'ao-vivo-ardy.ps1' $iconLive 'ARDY - digitar o pedido e conduzir o boneco ao vivo'

$iconTest = Join-Path $PSScriptRoot 'ardy.ico'
New-ArdyIcon $iconTest $green $false
New-ArdyShortcut 'ARDY - zumbi de teste' 'ver-ardy.ps1' $iconTest 'ARDY - ver o zumbi andando de teste'
