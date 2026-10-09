$ErrorActionPreference = 'Continue'
$base = 'C:\Users\dap_p\kimodo-setup'
$log  = "$base\stageC.log"

function Log($m) { $m | Out-File -FilePath $log -Append -Encoding utf8 }

"===== STAGE C - $(Get-Date -Format o) =====" | Out-File $log -Encoding utf8

# ---------- 1) Aplicar /etc/wsl.conf (default user + systemd) ----------
Log "--- wsl --shutdown (para aplicar wsl.conf) ---"
Log ((& cmd.exe /c "wsl --shutdown < NUL 2>&1") | Out-String)
Start-Sleep -Seconds 8

Log "--- wsl --status apos shutdown ---"
Log ((& cmd.exe /c "wsl --status < NUL 2>&1") | Out-String)

# ---------- 2) Instalar Docker Desktop ----------
$exe = "$base\DockerDesktopInstaller.exe"
if (-not (Test-Path $exe)) { Log "ERRO: instalador nao encontrado"; exit 1 }

Log "`n--- DockerDesktopInstaller.exe install --quiet --accept-license --backend=wsl-2 ---"
$p = Start-Process $exe -Wait -PassThru -ArgumentList @(
    'install', '--quiet', '--accept-license', '--backend=wsl-2'
)
Log "exit=$($p.ExitCode)"

# ---------- 3) Verificar ----------
$dockerExe = 'C:\Program Files\Docker\Docker\resources\bin\docker.exe'
Log "`n--- docker.exe existe? ---"
Log ("$dockerExe -> " + (Test-Path $dockerExe))

if (Test-Path $dockerExe) {
    Log "`n--- docker --version ---"
    Log ((& cmd.exe /c "`"$dockerExe`" --version < NUL 2>&1") | Out-String)
}

Log "`n--- distros WSL apos Docker ---"
Log ((& cmd.exe /c "wsl --list --verbose < NUL 2>&1") | Out-String)

"FIM STAGE C" | Out-File "$base\stageC.status" -Encoding utf8
