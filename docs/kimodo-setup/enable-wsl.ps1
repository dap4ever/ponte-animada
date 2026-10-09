$ErrorActionPreference = 'Continue'
$log = 'C:\Users\dap_p\kimodo-setup\enable-wsl.log'
$status = 'C:\Users\dap_p\kimodo-setup\enable-wsl.status'

function Log($m) { $m | Tee-Object -FilePath $log -Append }

"===== INICIO $(Get-Date -Format o) =====" | Set-Content $log
Log "Elevado: $((New-Object Security.Principal.WindowsPrincipal([Security.Principal.WindowsIdentity]::GetCurrent())).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator))"

# 1) Recursos opcionais do Windows exigidos pelo WSL2
foreach ($f in @('Microsoft-Windows-Subsystem-Linux','VirtualMachinePlatform')) {
    Log "--- Habilitando $f ---"
    $out = & dism.exe /online /enable-feature /featurename:$f /all /norestart 2>&1
    Log ($out | Out-String)
    Log "exit=$LASTEXITCODE"
}

# 2) Estado resultante
foreach ($f in @('Microsoft-Windows-Subsystem-Linux','VirtualMachinePlatform')) {
    $s = (Get-WindowsOptionalFeature -Online -FeatureName $f).State
    Log "$f = $s"
}

# 3) Instalar/atualizar o WSL (kernel + app) sem distro
Log "--- wsl --install --no-distribution ---"
$out = & wsl.exe --install --no-distribution 2>&1
Log ($out | Out-String)
Log "exit=$LASTEXITCODE"

Log "--- wsl --version ---"
$out = & wsl.exe --version 2>&1
Log ($out | Out-String)

"OK" | Set-Content $status
Log "===== FIM $(Get-Date -Format o) ====="
