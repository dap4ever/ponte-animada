$ErrorActionPreference = 'Continue'
$base = 'C:\Users\dap_p\kimodo-setup'
$log  = "$base\stageA.log"

function Log($m) { $m | Out-File -FilePath $log -Append -Encoding utf8 }

"===== STAGE A - $(Get-Date -Format o) =====" | Out-File $log -Encoding utf8

# Helper: roda wsl.exe com stdin em NUL para NUNCA travar em prompt interativo.
function Wsl([string]$cmdline) {
    return (& cmd.exe /c "wsl $cmdline < NUL 2>&1" | Out-String)
}

# ---------- 1) Estado ANTES ----------
Log "--- ANTES: wsl --version ---"
Log (Wsl "--version")

# ---------- 2) Instalar o MSI do WSL 3.0.1 ----------
$msi = "$base\wsl.3.0.1.0.x64.msi"
if (-not (Test-Path $msi)) { Log "ERRO: MSI nao encontrado em $msi"; exit 1 }

Log "--- msiexec /i wsl.3.0.1.0.x64.msi /qn /norestart ---"
$proc = Start-Process msiexec.exe -Wait -PassThru -ArgumentList @(
    '/i', "`"$msi`"", '/qn', '/norestart', '/l*v', "`"$base\wsl-msi-verbose.log`""
)
Log "msiexec exit=$($proc.ExitCode)"
# 0 = sucesso, 3010 = sucesso com reboot pendente

# ---------- 3) Estado DEPOIS ----------
Log "`n--- DEPOIS: wsl --version ---"
Log (Wsl "--version")

Log "`n--- DEPOIS: wsl --status ---"
Log (Wsl "--status")

Log "`n--- pacotes Appx WSL ---"
Log ((Get-AppxPackage -Name '*WindowsSubsystemForLinux*' | Select-Object Name, Version, Status | Format-Table -AutoSize | Out-String))

"FIM STAGE A" | Out-File "$base\stageA.status" -Encoding utf8
