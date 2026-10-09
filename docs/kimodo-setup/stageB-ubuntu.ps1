$ErrorActionPreference = 'Continue'
$base = 'C:\Users\dap_p\kimodo-setup'
$log  = "$base\stageB.log"

function Log($m) { $m | Out-File -FilePath $log -Append -Encoding utf8 }
function Wsl([string]$cmdline) { return (& cmd.exe /c "wsl $cmdline < NUL 2>&1" | Out-String) }

"===== STAGE B - $(Get-Date -Format o) =====" | Out-File $log -Encoding utf8

Log "--- distros disponiveis online ---"
Log (Wsl "--list --online")

Log "`n--- instalando Ubuntu (sem launch) em C:\wsl\Ubuntu ---"
Log (Wsl "--install -d Ubuntu --no-launch --location C:\wsl\Ubuntu")

Log "`n--- wsl --list --verbose ---"
Log (Wsl "--list --verbose")

Log "`n--- wsl --status ---"
Log (Wsl "--status")

Log "`n--- C:\wsl ---"
if (Test-Path 'C:\wsl') {
    Log ((Get-ChildItem 'C:\wsl' -Recurse -Depth 1 | Select-Object FullName, Length | Format-Table -AutoSize | Out-String))
} else { Log "C:\wsl nao existe" }

"FIM STAGE B" | Out-File "$base\stageB.status" -Encoding utf8
