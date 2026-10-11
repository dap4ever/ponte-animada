# Devolve ao E: o espaco que o ARDY ocupava dentro do disco do Ubuntu.
#
# O ARDY foi apagado, mas o arquivo do disco do Ubuntu (E:\wsl\Ubuntu\ext4.vhdx) nao encolhe sozinho.
# Este script desliga o Ubuntu e o Docker por alguns minutos e compacta o arquivo. Nada e apagado.
#
# Como usar: clique com o botao direito neste arquivo e escolha "Executar com o PowerShell".
# Ele pede permissao de administrador. Se o Docker estiver aberto, ele para e avisa: feche o
# Docker Desktop antes (o banco do outro projeto que roda no Docker volta quando o Docker for aberto de novo).

$disk = "E:\wsl\Ubuntu\ext4.vhdx"

$admin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $admin) {
    Start-Process powershell.exe -Verb RunAs -ArgumentList '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', "`"$PSCommandPath`""
    exit
}

if (-not (Test-Path $disk)) {
    Write-Host "Nao achei $disk. Nada foi feito." -ForegroundColor Yellow
    Read-Host "Enter para fechar"
    exit 1
}
if (Get-Process "Docker Desktop", "com.docker.backend" -ErrorAction SilentlyContinue) {
    Write-Host "O Docker Desktop esta aberto. Feche-o (icone da baleia, Quit Docker Desktop) e rode de novo." -ForegroundColor Yellow
    Write-Host "Nada foi feito."
    Read-Host "Enter para fechar"
    exit 1
}

$before = (Get-Item $disk).Length / 1GB
Write-Host ("Antes: {0:N1} GB" -f $before)
Write-Host "Desligando o Ubuntu..."
wsl.exe --shutdown
Start-Sleep -Seconds 8

$script = Join-Path $env:TEMP "compactar-ubuntu.txt"
@"
select vdisk file="$disk"
attach vdisk readonly
compact vdisk
detach vdisk
"@ | Set-Content -Path $script -Encoding ASCII
Write-Host "Compactando (pode levar alguns minutos)..."
diskpart /s $script
Remove-Item $script -ErrorAction SilentlyContinue

$after = (Get-Item $disk).Length / 1GB
Write-Host ("Depois: {0:N1} GB (voltaram {1:N1} GB para o E:)" -f $after, ($before - $after)) -ForegroundColor Green
Read-Host "Enter para fechar"
