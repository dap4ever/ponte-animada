$ErrorActionPreference = 'Continue'
$dockerBin = 'C:\Program Files\Docker\Docker\resources\bin'
$env:PATH = "$dockerBin;$env:PATH"

Write-Host ""
Write-Host "  ====================================" -ForegroundColor DarkCyan
Write-Host "            K I M O D O" -ForegroundColor Cyan
Write-Host "  ====================================" -ForegroundColor DarkCyan
Write-Host ""

# ---------- 1) Docker Desktop ----------
if (-not (Get-Process 'Docker Desktop' -ErrorAction SilentlyContinue)) {
    Write-Host "  [1/4] Iniciando o Docker Desktop..." -ForegroundColor Yellow
    Start-Process 'C:\Program Files\Docker\Docker\Docker Desktop.exe'
} else {
    Write-Host "  [1/4] Docker Desktop ja esta rodando." -ForegroundColor Green
}

# ---------- 2) Esperar o motor do Docker ----------
Write-Host "  [2/4] Aguardando o motor do Docker..." -ForegroundColor Yellow
$motorOk = $false
for ($i = 1; $i -le 60; $i++) {
    $v = (docker version --format '{{.Server.Version}}' 2>$null | Out-String).Trim()
    if ($v -match '^\d+\.') {
        Write-Host "        motor pronto (versao $v)" -ForegroundColor Green
        $motorOk = $true
        break
    }
    Start-Sleep -Seconds 5
    if ($i % 6 -eq 0) { Write-Host "        ...aguardando $($i * 5)s" }
}
if (-not $motorOk) {
    Write-Host "  ERRO: o motor do Docker nao subiu. Abra o Docker Desktop manualmente." -ForegroundColor Red
    exit 1
}

# ---------- 3) Subir os servicos ----------
Write-Host "  [3/4] Subindo os servicos do Kimodo..." -ForegroundColor Yellow
& wsl.exe -d Ubuntu -u dap_p -- bash -lc "cd ~/kimodo && docker compose up -d" 2>&1 | Out-Null
Write-Host "        containers solicitados" -ForegroundColor Green

# ---------- 4) Esperar a interface ----------
Write-Host "  [4/4] Aguardando a interface responder..." -ForegroundColor Yellow
Write-Host "        (na primeira vez do dia pode levar ~5 min" -ForegroundColor DarkGray
Write-Host "         enquanto o text encoder carrega na CPU)" -ForegroundColor DarkGray

$pronto = $false
for ($i = 1; $i -le 120; $i++) {
    try {
        $r = Invoke-WebRequest 'http://localhost:7860/' -UseBasicParsing -TimeoutSec 4 -ErrorAction Stop
        if ($r.StatusCode -eq 200) { $pronto = $true; break }
    } catch { }
    Start-Sleep -Seconds 4
    if ($i % 15 -eq 0) { Write-Host "        ...$($i * 4)s" }
}

Write-Host ""
if ($pronto) {
    Write-Host "  PRONTO! Abrindo http://localhost:7860" -ForegroundColor Green
    Start-Process 'http://localhost:7860'
} else {
    Write-Host "  A interface ainda nao respondeu." -ForegroundColor Yellow
    Write-Host "  Veja o que esta acontecendo com:" -ForegroundColor Yellow
    Write-Host '    wsl -d Ubuntu -u dap_p -- bash -lc "docker logs -f demo"' -ForegroundColor Gray
}
Write-Host ""
