$ErrorActionPreference = 'Continue'
$base = 'C:\Users\dap_p\kimodo-setup'
$log  = "$base\after-reboot.log"
$stat = "$base\after-reboot.status"

function Log($m) { $m | Tee-Object -FilePath $log -Append }

"===== INICIO $(Get-Date -Format o) =====" | Set-Content $log
$isAdmin = (New-Object Security.Principal.WindowsPrincipal([Security.Principal.WindowsIdentity]::GetCurrent())).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
Log "Elevado: $isAdmin"

# ---------- 1) Kernel/app do WSL ----------
Log "`n--- wsl --update ---"
Log ((& wsl.exe --update 2>&1) | Out-String)
Log "exit=$LASTEXITCODE"
if ($LASTEXITCODE -ne 0) {
    # Fallback: baixa do GitHub em vez da Microsoft Store.
    Log "`n--- fallback: wsl --update --web-download ---"
    Log ((& wsl.exe --update --web-download 2>&1) | Out-String)
    Log "exit=$LASTEXITCODE"
}

# ---------- 2) Distro Ubuntu no NVMe (C:) ----------
# --location forca a distro (ext4.vhdx) para o SSD NVMe, e nao para o HD (E:).
Log "`n--- wsl --install -d Ubuntu --no-launch --location C:\wsl\Ubuntu ---"
Log ((& wsl.exe --install -d Ubuntu --no-launch --location 'C:\wsl\Ubuntu' 2>&1) | Out-String)
Log "exit=$LASTEXITCODE"

# ---------- 3) Estado ----------
Log "`n--- wsl --status ---"
Log ((& wsl.exe --status 2>&1) | Out-String)
Log "`n--- wsl --list --verbose ---"
Log ((& wsl.exe --list --verbose 2>&1) | Out-String)

# ---------- 4) Docker Desktop ----------
$installer = "$base\DockerDesktopInstaller.exe"
if (Test-Path $installer) {
    Log "`n--- Docker Desktop: instalador local encontrado ---"
    Log ((& $installer 'install' '--quiet' '--accept-license' '--backend=wsl-2' 2>&1) | Out-String)
    Log "exit=$LASTEXITCODE"
} else {
    Log "`n--- Docker Desktop via winget ---"
    Log ((& winget.exe install -e --id Docker.DockerDesktop --accept-package-agreements --accept-source-agreements --disable-interactivity 2>&1) | Out-String)
    Log "exit=$LASTEXITCODE"
}

Log "`n--- docker --version ---"
Log ((& docker.exe --version 2>&1) | Out-String)

"OK" | Set-Content $stat
Log "`n===== FIM $(Get-Date -Format o) ====="
