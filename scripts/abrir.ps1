# Abre o PonteAnimada como aplicativo de desktop: sobe o servidor local (se ainda
# nao estiver no ar) e abre a interface numa janela propria do Edge.
# Textos sem acento de proposito: o PowerShell 5.1 le .ps1 sem BOM como ANSI.

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$config = Get-Content (Join-Path $root 'ponte.toml') -Raw
$port = if ($config -match '(?m)^\s*port\s*=\s*(\d+)') { $Matches[1] } else { '8765' }
$url = "http://127.0.0.1:$port/"

function Test-Server {
    try { return (Invoke-WebRequest "${url}api/state" -UseBasicParsing -TimeoutSec 2).StatusCode -eq 200 }
    catch { return $false }
}

function Show-Error([string]$message) {
    Add-Type -AssemblyName System.Windows.Forms
    [System.Windows.Forms.MessageBox]::Show($message, 'PonteAnimada', 'OK', 'Error') | Out-Null
}

if (-not (Test-Server)) {
    $uv = (Get-Command uv -ErrorAction SilentlyContinue).Source
    if (-not $uv) { $uv = Join-Path $env:USERPROFILE '.local\bin\uv.exe' }
    if (-not (Test-Path $uv)) {
        Show-Error "Nao encontrei o uv (gerenciador de Python). Instale em https://docs.astral.sh/uv/ e tente de novo."
        exit 1
    }
    $data = Join-Path $root 'data'
    New-Item -ItemType Directory -Force $data | Out-Null
    $errLog = Join-Path $data 'server.err.log'
    Start-Process -FilePath $uv -ArgumentList 'run', 'ponte', 'serve' -WorkingDirectory $root -WindowStyle Hidden `
        -RedirectStandardOutput (Join-Path $data 'server.log') -RedirectStandardError $errLog

    $ready = $false
    for ($i = 0; $i -lt 120; $i++) {
        if (Test-Server) { $ready = $true; break }
        Start-Sleep -Milliseconds 500
    }
    if (-not $ready) {
        $tail = if (Test-Path $errLog) { (Get-Content $errLog -Tail 8) -join "`n" } else { '(sem log)' }
        Show-Error "O servidor do PonteAnimada nao subiu em 60 segundos.`n`n$tail"
        exit 1
    }
}

$edge = @(
    (Join-Path ${env:ProgramFiles(x86)} 'Microsoft\Edge\Application\msedge.exe'),
    (Join-Path $env:ProgramFiles 'Microsoft\Edge\Application\msedge.exe')
) | Where-Object { Test-Path $_ } | Select-Object -First 1

if ($edge) {
    Start-Process -FilePath $edge -ArgumentList "--app=$url", '--window-size=1500,950'
} else {
    Start-Process $url
}
