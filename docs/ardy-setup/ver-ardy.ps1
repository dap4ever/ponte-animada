# Mostra o zumbi andando de teste do ARDY (gerador de animacao da NVIDIA, instalado no Ubuntu).
# Na primeira vez gera o clipe: uns 10 minutos e 16 GB de memoria. Depois so abre o visualizador.
# E o que o atalho "ARDY - zumbi de teste" da Area de Trabalho chama.
# Textos sem acento de proposito: o PowerShell 5.1 le .ps1 sem BOM como ANSI.

$ErrorActionPreference = 'Continue'
$ProgressPreference = 'SilentlyContinue'
$Host.UI.RawUI.WindowTitle = 'ARDY - zumbi de teste'
try { [Console]::OutputEncoding = [System.Text.Encoding]::UTF8 } catch {}

$clip = 'zumbi_andando'
$url = 'http://localhost:2334'
$probe = 'http://127.0.0.1:2334'
$log = Join-Path $env:TEMP 'ardy-visualizador.log'
# A pasta deste script vista de dentro do Ubuntu: D:\pasta -> /mnt/d/pasta
$dir = '/mnt/' + $PSScriptRoot.Substring(0, 1).ToLower() + ($PSScriptRoot.Substring(2) -replace '\\', '/')

function Say([string]$text = '') { Write-Host "  $text" }

function Invoke-Ardy([string]$script, [string]$arguments = '') {
    # Roda um script da pasta dentro do Ubuntu; o resultado fica em $LASTEXITCODE.
    # Pelo cmd, com a entrada vinda de NUL: o wsl.exe nao disputa o teclado com esta janela.
    & cmd.exe /c "wsl.exe -d Ubuntu -- bash $dir/$script $arguments < NUL"
}

function Release-Memory {
    # O Ubuntu so devolve a memoria ao Windows quando desliga. Nao desliga se outra janela do
    # ARDY ainda estiver em uso (o demo ao vivo, por exemplo). Com o Docker no ar, o WSL e
    # dividido com ele: ai so o Ubuntu e encerrado.
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
    Invoke-Ardy 'ardy-parar.sh' 'visualizador' | Out-Null
    Release-Memory
    exit 1
}

Say
Say 'ARDY - zumbi andando de teste'
Say

# Resto de uma vez anterior. So o visualizador: o codificador de texto pode estar em uso por
# uma geracao ou pelo demo ao vivo, e encerra-lo derruba os dois sem mensagem de erro.
Invoke-Ardy 'ardy-parar.sh' 'visualizador' | Out-Null

Invoke-Ardy 'ardy-montar-visualizador.sh' '--so-conferir' | Out-Null
$needPage = ($LASTEXITCODE -ne 0)
Invoke-Ardy 'ardy-tem-clipe.sh' $clip | Out-Null
$needClip = ($LASTEXITCODE -ne 0)

if ($needPage -or $needClip) {
    $free = [math]::Round((Get-CimInstance Win32_OperatingSystem).FreePhysicalMemory / 1MB, 1)
    Say 'O clipe ainda nao foi gerado. Para gerar, o ARDY usa uns 16 GB de memoria por cerca'
    Say 'de 10 minutos, e o computador fica lento nesse tempo. So acontece na primeira vez.'
    Say
    Say 'FECHE A UNREAL e outros programas pesados antes de continuar.'
    Say "Memoria livre agora: $free GB."
    Say
    Read-Host '  Aperte Enter para gerar (ou feche esta janela para desistir)' | Out-Null
    Say
}

if ($needPage) {
    Invoke-Ardy 'ardy-montar-visualizador.sh'
    if ($LASTEXITCODE -ne 0) { Stop-Here 'O visualizador do ARDY nao ficou pronto.' }
}

if ($needClip) {
    Invoke-Ardy 'ardy-gerar-zumbi.sh' $clip
    $code = $LASTEXITCODE
    Release-Memory                          # devolve os 16 GB antes de abrir o visualizador
    if ($code -ne 0) { Stop-Here 'A geracao do clipe falhou.' }
}

Say
Say 'Abrindo o visualizador...'
$viewer = Start-Process cmd.exe -NoNewWindow -PassThru -ArgumentList '/c', "wsl.exe -d Ubuntu -- bash $dir/ardy-ver.sh $clip < NUL > `"$log`" 2>&1"
$up = $false
$deadline = (Get-Date).AddMinutes(5)
while (-not $viewer.HasExited -and (Get-Date) -lt $deadline) {
    try {
        if ((Invoke-WebRequest $probe -UseBasicParsing -TimeoutSec 3).StatusCode -eq 200) { $up = $true; break }
    } catch {}
    Start-Sleep -Seconds 2
}
if (-not $up) {
    if (Test-Path $log) { Get-Content $log -Tail 15 | ForEach-Object { Say $_ } }
    Stop-Here 'O visualizador do ARDY nao abriu.'
}

Start-Process $url
Say
Say "O zumbi esta aberto no navegador: $url"
Say 'Sao 3 tentativas do mesmo pedido. Para trocar: caixa "Sample", no painel da direita.'
Say 'O boneco cinza e o do proprio ARDY, nao a Zombiegirl.'
Say
Read-Host '  Quando terminar de ver, aperte Enter aqui para fechar o ARDY' | Out-Null

Invoke-Ardy 'ardy-parar.sh' 'visualizador' | Out-Null
Release-Memory
