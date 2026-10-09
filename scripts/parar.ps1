# Encerra o servidor local do PonteAnimada (o processo que escuta na porta configurada).
# Recusa se houver job em andamento: parar o servidor mata a geracao/retarget no meio.
# Use -Force para encerrar mesmo assim. Nao mexe no Kimodo/Docker.

param([switch]$Force)

$root = Split-Path -Parent $PSScriptRoot
$config = Get-Content (Join-Path $root 'ponte.toml') -Raw
$port = if ($config -match '(?m)^\s*port\s*=\s*(\d+)') { [int]$Matches[1] } else { 8765 }

$owners = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue |
    Select-Object -ExpandProperty OwningProcess -Unique
if (-not $owners) {
    Write-Host "PonteAnimada nao esta rodando (porta $port livre)."
    exit 0
}

if (-not $Force) {
    try {
        $state = Invoke-RestMethod "http://127.0.0.1:$port/api/state" -TimeoutSec 5
        $active = @($state.jobs | Where-Object { $_.status -eq 'fila' -or $_.status -eq 'rodando' })
        if ($active.Count -gt 0) {
            Write-Host "Ha $($active.Count) job(s) em andamento; o servidor NAO foi encerrado:"
            foreach ($job in $active) { Write-Host "  - $($job.title)" }
            Write-Host "Espere terminarem, ou rode com -Force para interromper."
            exit 2
        }
    } catch {
        Write-Host "Nao consegui consultar os jobs ($($_.Exception.Message)); encerrando assim mesmo."
    }
}

foreach ($procId in $owners) {
    $proc = Get-Process -Id $procId -ErrorAction SilentlyContinue
    if ($proc -and $proc.ProcessName -match '^python') {
        Stop-Process -Id $procId -Force
        Write-Host "Servidor encerrado (PID $procId)."
    } elseif ($proc) {
        Write-Host "A porta $port esta com '$($proc.ProcessName)' (PID $procId), que nao e o PonteAnimada. Nada foi encerrado."
    }
}
exit 0
