# Abre o demo interativo do ARDY (gerador de animacao da NVIDIA, instalado no Ubuntu): voce
# digita o pedido e o boneco se move ao vivo, no navegador, e da para conduzir pelo teclado e
# pelo mouse. Enquanto esta janela estiver aberta usa uns 16 GB de memoria: o modelo de texto
# roda no processador, porque a placa de video nao tem memoria para ele.
# E o que o atalho "ARDY - ao vivo" da Area de Trabalho chama.
# Textos sem acento de proposito: o PowerShell 5.1 le .ps1 sem BOM como ANSI.

$ErrorActionPreference = 'Continue'
$ProgressPreference = 'SilentlyContinue'
$Host.UI.RawUI.WindowTitle = 'ARDY - ao vivo'
try { [Console]::OutputEncoding = [System.Text.Encoding]::UTF8 } catch {}

$url = 'http://localhost:2333'
$probe = 'http://127.0.0.1:2333'
$logEncoder = Join-Path $env:TEMP 'ardy-codificador.log'
$logDemo = Join-Path $env:TEMP 'ardy-ao-vivo.log'
# A pasta deste script vista de dentro do Ubuntu: D:\pasta -> /mnt/d/pasta
$dir = '/mnt/' + $PSScriptRoot.Substring(0, 1).ToLower() + ($PSScriptRoot.Substring(2) -replace '\\', '/')

function Say([string]$text = '') { Write-Host "  $text" }

function Invoke-Ardy([string]$script, [string]$arguments = '') {
    # Roda um script da pasta dentro do Ubuntu; o resultado fica em $LASTEXITCODE.
    # Pelo cmd, com a entrada vinda de NUL: o wsl.exe nao disputa o teclado com esta janela.
    & cmd.exe /c "wsl.exe -d Ubuntu -- bash $dir/$script $arguments < NUL"
}

function Start-Ardy([string]$script, [string]$log) {
    # Deixa um script da pasta rodando no Ubuntu em segundo plano, com a saida num arquivo.
    Start-Process cmd.exe -NoNewWindow -PassThru -ArgumentList '/c', "wsl.exe -d Ubuntu -- bash $dir/$script < NUL > `"$log`" 2>&1"
}

function Show-Log([string]$log) {
    if (Test-Path $log) { Get-Content $log -Tail 15 | ForEach-Object { Say $_ } }
}

function Release-Memory {
    # O Ubuntu so devolve a memoria ao Windows quando desliga. Nao desliga se outra janela do
    # ARDY ainda estiver em uso. Com o Docker no ar, o WSL e dividido com ele: ai so o Ubuntu
    # e encerrado.
    Invoke-Ardy 'ardy-no-ar.sh' | Out-Null
    if ($LASTEXITCODE -eq 0) { return }
    $running = @((& wsl.exe -l --running -q) -replace "`0", '' | Where-Object { $_.Trim() })
    if ($running -match 'docker') { & wsl.exe --terminate Ubuntu | Out-Null } else { & wsl.exe --shutdown | Out-Null }
}

function Stop-Here([string]$message) {
    Say
    Say $message
    Say 'Copie o que apareceu nesta janela e mostre ao Claude.'
    Say
    Read-Host '  Aperte Enter para fechar' | Out-Null
    Invoke-Ardy 'ardy-parar.sh' 'demo codificador' | Out-Null
    Release-Memory
    exit 1
}

Say
Say 'ARDY - ao vivo'
Say

Invoke-Ardy 'ardy-parar.sh' 'demo' | Out-Null    # resto de uma vez anterior

Invoke-Ardy 'ardy-esperar-codificador.sh' '--so-conferir' | Out-Null
if ($LASTEXITCODE -ne 0) {
    $free = [math]::Round((Get-CimInstance Win32_OperatingSystem).FreePhysicalMemory / 1MB, 1)
    $unreal = @(Get-Process UnrealEditor* -ErrorAction SilentlyContinue).Count -gt 0
    Say 'O ARDY usa uns 16 GB de memoria enquanto esta janela estiver aberta'
    Say 'e leva uns 3 minutos para carregar.'
    Say "Memoria livre agora: $free GB."
    if ($unreal -or $free -lt 14) {
        Say
        if ($unreal) { Say 'A UNREAL ESTA ABERTA: feche antes de continuar, ou o computador fica muito lento.' }
        else { Say 'Pouca memoria livre: feche programas pesados antes de continuar.' }
        Read-Host '  Aperte Enter para continuar (ou feche esta janela para desistir)' | Out-Null
    }
    Say
    Say 'Carregando o modelo de texto...'
    Start-Ardy 'ardy-codificador.sh' $logEncoder | Out-Null
    Invoke-Ardy 'ardy-esperar-codificador.sh'
    if ($LASTEXITCODE -ne 0) {
        Show-Log $logEncoder
        Stop-Here 'O modelo de texto do ARDY nao carregou.'
    }
}

Say
Say 'Abrindo o demo...'
$demo = Start-Ardy 'ardy-ao-vivo.sh' $logDemo
$up = $false
$deadline = (Get-Date).AddMinutes(5)
while (-not $demo.HasExited -and (Get-Date) -lt $deadline) {
    try {
        if ((Invoke-WebRequest $probe -UseBasicParsing -TimeoutSec 3).StatusCode -eq 200) { $up = $true; break }
    } catch {}
    Start-Sleep -Seconds 2
}
if (-not $up) {
    Show-Log $logDemo
    Stop-Here 'O demo do ARDY nao abriu.'
}

Start-Process $url
# O carregamento deixa uns 6 GB de copias de arquivo na memoria do Ubuntu. Solta-las devolve
# essa folga ao Windows aos poucos, sem mexer no demo.
& cmd.exe /c "wsl.exe -d Ubuntu -u root -- bash $dir/ardy-liberar-cache.sh < NUL" | Out-Null
Say
Say "O ARDY esta aberto no navegador: $url"
Say 'Feche o aviso "Welcome" e espere aparecer "Model loaded".'
Say
Say 'Clique na imagem do boneco antes de usar as teclas.'
Say '  Espaco ........ toca / pausa'
Say '  T ............. liga o controle pelas setas: esquerda e direita viram,'
Say '                  cima e baixo mudam a velocidade'
Say '  P ............. liga o modo de pontos: clique no chao e o boneco vai ate la'
Say '  R ............. a camera volta a seguir o boneco'
Say
Say 'Para pedir um movimento: aba "Text", escreva em ingles em "Prompt Text"'
Say 'e clique "Update Text Prompt". Os botoes de "Prompt List" sao pedidos prontos.'
Say 'Para salvar: aba "IO", botao "Export Session".'
Say
Read-Host '  Quando terminar, aperte Enter aqui para fechar o ARDY e liberar a memoria' | Out-Null

Invoke-Ardy 'ardy-parar.sh' 'demo codificador' | Out-Null
Release-Memory
