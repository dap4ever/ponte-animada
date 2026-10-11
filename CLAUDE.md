# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

PonteAnimada: a tela em que o usuário vê seus personagens 3D e as animações deles, com o Blender
por trás, os geradores de animação e um terminal por projeto, onde ele chama a IA que faz as
animações. O uso, a lista completa da CLI e os limites conhecidos estão no `README.md`. Aqui
fica o que muda como você trabalha.

**O repositório é público** (`github.com/dap4ever/ponte-animada`): este arquivo, o README e os
`docs/` são lidos por qualquer um. Chave, senha, dado pessoal e nome de outros projetos dele não
entram aqui, nem imagem de personagem do jogo. Só grave e envie (`git commit`, `git push`)
quando ele pedir.

## A tela nova (10 e 11/10/2026): projeto = visor + animações + terminal

Depois de aprovar o parado e o andar do Soldado, o usuário mandou mudar a ponte inteira: "vamos
usar apenas o que nos interessa"; "terá apenas do lado esquerdo uma tela do tipo blender onde
vejo a textura animada ou não"; "o blender vai rodar apenas no backend, com você manipulando
ele"; "retarget com modelo do mixamo eu continuo fazendo manualmente como já é agora, mas existe
muita informação desnecessária"; "dentro do projeto da ponte terá uma janela de terminal onde ele
já abrir na pasta do projeto em questão" ("terminal é pra falar com você"); "meshy continua";
"pode apagar tudo, só deixe o fbx com as texturas"; "me entregue o primeiro formato de design que
depois discutiremos melhorias". **O que está no ar é esse primeiro formato: as melhorias são
combinadas com ele, uma de cada vez.** A primeira veio em 11/10, com ele já olhando a tela: "o
terminal tem que vir sem chamar o claude, ele tem que vir apenas dentro da pasta, pronto para ser
chamado, pois posso querer usar outra IA".

**Como se trabalha agora.** Ele abre o projeto do personagem, chama no terminal da tela a IA que
quiser (o `claude` ou outra) e escreve para ela. Essa IA (você, se está lendo isto a partir da
pasta de um projeto) faz a animação no Blender escondido, exporta um GLB e o põe na lista com
`ponte anim add`. Ele vê no visor ao lado e diz o que achou. Uma animação de cada vez. O Blender
com janela, que ele usava para acompanhar o Soldado, saiu do caminho: o que ele vê é o visor da
ponte.

- **A tela** (`web/index.html`, `app.js`, `style.css`; `viewer.js` é o de antes). Entrada: os
  projetos, um cartão cada, "Novo personagem", os pedidos do Meshy e o que está rodando. Projeto:
  à esquerda o visor (vistas Frente/Lado/Trás/Cima, tocar e pausar, barra de tempo, velocidade,
  Seguir, Parado, Ossos, Malha); à direita, em cima, **Animações** ("Modelo parado" e uma linha por
  animação, com a duração e de onde veio: Mixamo, Blender ou gerada; × apaga, dois cliques mudam
  o nome; o botão **+ Mixamo (.fbx)**) e, embaixo, o **terminal**. A divisória entre as metades
  arrasta. O endereço guarda o projeto e a animação (`#p/<projeto>/<animação>`). Animação que
  chega com a tela aberta abre sozinha.
- **O que a tela nova não tem**: laudo, rig automático, acessórios (prender o fuzil na mão),
  roteiros e passos, revisão (aprovar/reprovar), encerrar, Unreal, troca de gerador. Tudo isso
  continua funcionando por baixo (CLI e API) e na tela anterior, guardada em **`/antiga/`**
  (`web/antiga/`, sem link na tela nova). Não a apague: é por ela que se dá esqueleto a um modelo
  do Meshy que chega sem.
- **Animação pronta** (`pipeline.add_ready_animation`, `uv run ponte anim add <projeto>
  <arquivo.glb> --name "<nome>" [--blend <arquivo>] [--replace]`): um GLB com o personagem (e os
  acessórios) já animado entra na lista sem retarget. Vira uma animação (`source: "blender"`) e
  uma prévia com o mesmo id, com `result.glb`. A tela a enxerga em 2 s. O GLB tem de começar no
  tempo 0 (`export_anim_slide_to_zero` no exportador do Blender): sem isso o laço ganha um
  quadro parado. Os do Soldado saem por `D:\Blender-Animacoes\Soldado\scripts\exportar_glb.py`.
- **O terminal** (`ponte/terminal.py`, rotas `/api/terminal...` em `server.py`, xterm.js em
  `web/node_modules/@xterm`): um PowerShell de verdade, parado no prompt da pasta do projeto.
  **Ele não chama IA nenhuma sozinho, por ordem do usuário** (a primeira versão já subia com o
  `claude`; ele mandou tirar, porque pode querer outra IA). Não volte a chamar o `claude` ao
  abrir, nem ponha botão que chame, sem ele pedir. Há faxina, porque o que se chama ali pesa
  (um Claude Code são uns 250 MB e mais de dez processos, com os conectores): sem ninguém olhando
  e sem que ninguém tenha escrito nele, fecha em 20 s (`GRACE`); com algo escrito, espera a volta
  e só fecha depois de 3 h calado sem ninguém olhando (`IDLE`) ou quando o servidor para. Na
  primeira versão, sem faxina e chamando o Claude, ele abriu os sete projetos para olhar e
  ficaram sete Claudes ligados (2 GB). "reiniciar" fecha o terminal com o que estiver rodando e
  abre outro; num terminal novo, `claude --continue` retoma a conversa anterior do Claude. Apagar
  um projeto fecha o terminal dele antes (o Windows não apaga a pasta em que um programa está).
- **Um terminal na página é um shell na máquina.** Só atende à própria página da ponte: origem
  local na mesma porta e o `TOKEN` sorteado a cada subida do servidor (`/api/terminal` o entrega;
  página de outro site não lê a resposta). Não afrouxe isso nem ponha o servidor para escutar
  fora do `127.0.0.1`.
- **O guia de cada projeto**: ao abrir o terminal, a ponte grava na pasta do projeto o mesmo
  texto com dois nomes, `CLAUDE.md` (o que o Claude Code lê) e `AGENTS.md` (o que o Codex, o
  opencode e outras leem), por `terminal.write_guide`: quem está escrevendo, a pasta, o
  personagem, como rodar o Blender escondido e como pôr a animação na tela. Cada arquivo é
  regravado a cada abertura enquanto começar com a linha de marca; para escrever à mão num
  projeto, apague essa linha, e a ponte não toca mais naquele arquivo. O que for específico de um
  personagem (o do Soldado, por exemplo) vai num arquivo à parte na pasta dele, apontado pelo
  guia, e não aqui.
- **O acervo foi esvaziado em 10/10/2026**, por ordem dele: de cada projeto ficou só o personagem
  (`personagem/`, com o FBX, as texturas e, no Soldado, o fuzil). Saíram 124 animações e prévias
  (3,7 GB), o projeto "Soldado ARDY" (cópia do Soldado para o teste do ARDY) e 1042 registros de
  jobs. Foi `data/tmp/limpar_acervo_2026-10-10.py`. **Antes, cópia de tudo em
  `E:\backup-ponteanimada-2026-10-10`** (4,1 GB): é de lá que se traz de volta o que fizer falta
  (as animações do Mixamo do Swat e da Zombiegirl, por exemplo). Não apague essa cópia sem ele
  mandar. Em 11/10, já na tela nova, ele mesmo excluiu o projeto "Zombiegirl W Kurniawan" (era o
  mesmo modelo do "Zombiegirl Kimodo"). Ficaram seis: zumbi1, sobrevivente, survivor-parana, Swat,
  Soldado e Zombiegirl Kimodo. No Soldado estão as duas aprovadas, `idle` e `walk_forward`.
- **Como foi provado**: o terminal, por `tests/check_terminal.py` (servidor próprio na porta 8767
  e acervo descartável: abre parado na pasta, recusa quem vem de fora, fecha sozinho, espera
  quando há algo escrito, reinicia, apaga projeto com o terminal aberto). A tela, num Edge
  escondido em tempo real, com `tests/ui_click.mjs` (ver "Testes"): entrada com os projetos, o
  Soldado andando e parado com o relógio correndo, vistas e ossos, e o botão do Mixamo num
  acervo descartável (um FBX da cópia de segurança entrou na lista em 8 s, abriu sozinho e
  tocou; o × o apagou). A captura parada do Edge (`--screenshot`) não serve para esta tela: o
  relógio virtual não espera o GLB nem o terminal.
- **Em aberto, para combinar com ele**: miniatura do personagem no cartão do projeto (hoje é a
  inicial do nome); os GLB do Soldado têm 40 MB cada (a textura vai inteira em cada um) e levam
  uns 4 s para abrir; o que da tela antiga faz falta na nova; tirar do código o Kimodo original
  e o ARDY, que só a tela antiga mostra.
- **Encerrar não conhece a animação pronta.** `ponte close` monta o resultado a partir do
  `.blend` de cada prévia do retarget (`pipeline.close_project`): com uma animação posta por
  `ponte anim add` sem `--blend` ele recusa ("Prévia sem o arquivo de trabalho"), e com `--blend`
  não foi testado (não se sabe se o `.blend` de trabalho serve ao `build_result.py`).
  Isso foi lido no código, não rodado. Enquanto for assim, o que vai do Soldado para o jogo é o
  GLB de cada animação (`previas/<id>/result.glb`). Não encerre por conta própria, como sempre.
- **O README foi refeito para esta versão** em 11/10/2026, com a imagem da tela nova
  (`docs/img/tela-projeto.png`, tirada com o boneco de teste num acervo descartável; não use
  personagem dele em imagem do repositório, que é público). As seções da tela anterior ficaram
  juntas, depois de "A tela anterior".

## Estado em 10/10/2026: o kimodo.cpp é o gerador, o ARDY foi desinstalado

No fim do dia 10/10/2026, logo depois de aprovar o parado e o andar do Soldado (o andar veio do
ARDY), o usuário mandou: "agora instale o kimodo.cpp vamos usar ele de agora em diante" e, com ele
funcionando, "feche todos os processos do ardy, e delete ele do meu pc, não quero ele tomando
espaço, mas deixe documentado todos os acertos e erros". Eu tinha avisado antes que o kimodo.cpp
não faz laço nem direção e velocidade; a decisão foi dele.

- **O kimodo.cpp é o único gerador instalado e o que está em uso** (`ponte engine` mostra `cpp`;
  eu troquei, porque ele mandou usar esse dali em diante). Está em `D:\kimodo.cpp`, compilado
  **com Vulkan**: gera na RTX 3060. Medido: 5 s de animação em 33 s pelo programa e 31 s pela
  ponte, já com o retarget e a prévia; texto novo não custa mais (o codificador de texto roda
  na placa, dentro desse tempo). Os pesos são 8,7 GB. Como foi instalado: "Dois geradores", abaixo.
- **O ARDY saiu do PC**: `~/ardy`, os quatro modelos e o cache do pip no Ubuntu (26 GB), e os dois
  atalhos da Área de Trabalho, por `docs/ardy-setup/ardy-desinstalar.sh`. O `[ardy]` do
  `ponte.toml` está com `installed = false`. Ficaram: o código da ponte para ele, os scripts de
  `docs/ardy-setup/`, o registro **`docs/ardy-setup/ACERTOS-E-ERROS.md`** (leia antes de qualquer
  conversa sobre voltar com ele), e `data/tmp/ardy-guardado/` (os 105 textos já codificados e os
  clipes de teste). No Ubuntu ficaram o `token` do Hugging Face, o `uv` com o Python 3.11 e o
  compilador. **O arquivo do disco do Ubuntu, `E:\wsl\Ubuntu\ext4.vhdx`, continuou com 28,5 GB**:
  só encolhe com `docs/ardy-setup/compactar-disco-do-ubuntu.ps1`, que pede administrador e
  desliga o WSL; não rodei, ficou para ele.
- O servidor da ponte foi reiniciado em 11/10/2026, com a tela nova: já lê o `ponte.toml` de
  agora (ARDY e Kimodo original como não instalados, kimodo.cpp em uso).
- **Não troque o gerador por conta própria** (`ponte engine ...` vale para o servidor inteiro): a
  escolha é dele. Para um pedido num gerador específico, `--engine` no `ponte gen`.
- O Kimodo original continua fora (desinstalado em 08/10/2026, "apague tudo deixe somente a
  ponte"; ele vinha de achar a qualidade insuficiente). O que saiu naquele dia: `~/kimodo` e os
  quatro modelos dele no Ubuntu, a imagem `kimodo:1.0` e o cache de construção no Docker, e
  `C:\Users\dap_p\kimodo-setup`.
- O que ficou do original: todo o código da ponte para ele, o guia e os scripts de instalação
  em `docs/kimodo-setup/` (o guia é `GUIA-KIMODO.md`), Docker Desktop, Ubuntu, Blender, Visual
  Studio. Para voltar com ele: seguir o guia e pôr `installed = true` em `[kimodo]` no
  `ponte.toml`.
- **O Docker dele tem outro projeto**, que não é desta ponte (banco Postgres e Redis, com
  volumes de dados). Nunca rode limpeza geral (`docker system prune`, "Purge data"): só o que
  for do Kimodo, pelo nome.
- **Os discos virtuais do Docker e do Ubuntu moram no E:** desde 08/10/2026, a pedido dele
  ("eu preciso que o docker grave e use o banco no E:"): `E:\Docker\disk\docker_data.vhdx`
  (79 GB, quase vazio por dentro) e `E:\wsl\Ubuntu\ext4.vhdx` (20 GB). O Ubuntu foi movido com
  `wsl --manage Ubuntu --move`; o do Docker, copiando o arquivo e pondo
  `"CustomWslDistroDir": "E:\\Docker"` em `%APPDATA%\Docker\settings-store.json` (nesta versão,
  4.94, o Docker procura o disco em `<pasta>\disk\`, sem `DockerDesktopWSL`; com a pasta errada
  ele cria um disco vazio e os volumes "somem"). Há uma cópia dos dados desse outro projeto,
  daquele dia, em `E:\backup-docker-2026-10-08`. Coisa grande vai para o E: (1,7 TB livres, disco
  rígido comum, mais lento).
- Apagar arquivo no C: é barrado pela permissão quando o mesmo comando cita `C:\Program Files`
  ou um `C:\...` solto: faça o `Remove-Item` sozinho, com o caminho exato do arquivo.
- **ARDY** (NVIDIA, julho de 2026, `github.com/nv-tlabs/ardy`): **desinstalado em 10/10/2026**
  (ver o estado, acima). O que segue descreve como era enquanto esteve aqui, e como volta a ser
  se ele reinstalar: **instalado em 08 e 09/10/2026
  no Ubuntu, em `~/ardy`** (ambiente em `.venv`, Python 3.11, PyTorch com CUDA; modelos em
  `~/.cache/huggingface/hub`, 17 GB) e **ligado à ponte em 09/10/2026** (`[ardy]` no
  `ponte.toml`, `ponte/ardy.py`, `ardy_scripts/gerar.py`; detalhes em "O ARDY na ponte", abaixo).
  Os scripts de `docs/ardy-setup/` são os da instalação e dos atalhos, e rodam de dentro do Ubuntu
  (`wsl.exe -d Ubuntu -- bash /mnt/d/PonteAnimada/docs/ardy-setup/<script>`):
  `ardy-gerar-zumbi.sh` (sobe o codificador de texto, gera e encerra), `ardy-gerar.sh` (um
  clipe qualquer, com o codificador já no ar), `ardy-ver.sh` (visualizador em
  `localhost:2334`), `ardy-ao-vivo.sh` (demo interativo em `localhost:2333`), `ardy-parar.sh`,
  `ardy-estado.sh` e `ardy_stats.py` (números de um clipe). Há dois atalhos na Área de
  Trabalho, criados por `criar-atalho-ardy.ps1`: "ARDY - ao vivo" (`ao-vivo-ardy.ps1`) e
  "ARDY - zumbi de teste" (`ver-ardy.ps1`). Cada um abre uma janela que fica esperando um Enter
  para encerrar o ARDY e devolver a memória.
  - **Ele quer gerar as animações ele mesmo** ("eu quero que eu possa gerar as animações",
    09/10/2026). O caminho hoje é o atalho "ARDY - ao vivo": o demo do próprio ARDY, em que se
    digita o pedido em inglês (aba Text), conduz-se o boneco (`T` e setas, ou `P` e cliques no
    chão) e exporta-se a sessão (aba IO, `.pkl` em `~/ardy/.cache/export/`). Roda a 20 quadros
    por segundo na RTX 3060 sem TensorRT (`--no-compile`); um pedido novo leva uns 6 s para
    ser codificado no processador, e os já usados ficam guardados. O demo precisa do
    codificador como serviço no ar: sozinho ele tenta pô-lo na placa. A ponte lê essas sessões
    desde 09/10/2026 (**Sessões do ARDY**, na aba Prévias): é o caminho para o que ele gera
    ali chegar à Zombiegirl e à Godot.
  - O codificador de texto (o mesmo Llama 3 do Kimodo) roda no processador: 16 GB de RAM e uns
    3 minutos para carregar; na placa pediria 14 GB e a RTX 3060 daqui tem 12. Com ele no ar o
    Windows fica com 1 a 2 GB livres: avise antes e confira se a Unreal está fechada (em 08/10
    ele mandou cancelar por isso). Depois de gerar, `wsl --shutdown` devolve a memória (com o
    Docker no ar, só `wsl --terminate Ubuntu`).
  - Gerar é rápido: 3 tomadas de 8 s em 53 s. Saída `.npz` em `~/ardy/outputs/` (modelo `core`:
    27 juntas com nomes no estilo do Mixamo, 20 quadros por segundo, sem BVH). Aceita caminho e
    poses-chave e tem correção de pé.
  - **`ardy-parar.sh` sem argumento encerra tudo do ARDY**, e encerrar o codificador derruba
    uma geração ou o demo sem mensagem de erro (aconteceu em 09/10: ele abriu o atalho do zumbi
    enquanto uma geração rodava pelo Claude). Por isso cada atalho só encerra o que é dele e
    só desliga o Ubuntu se `ardy-no-ar.sh` disser que não há mais nada rodando. Antes de gerar
    ou encerrar algo, rode `ardy-estado.sh` e veja se há janela de atalho aberta.
  - Primeiro clipe (09/10/2026): `~/ardy/outputs/zumbi_andando/`, 3 tomadas do texto em
    `docs/ardy-setup/ardy-zumbi-andando.txt`. **Falta o veredito dele sobre a qualidade.**
  - **A página do demo foi consertada aqui** (09/10/2026): com dois cliques na barra azul do
    pedido, na linha do tempo, a caixa de edição nascia com a largura do pedido inteiro e o
    texto ficava fora da tela ("aparece preto e a letra some"). O conserto está em
    `docs/ardy-setup/ardy-corrigir-caixa-de-texto.py`, que mexe no `Timeline.tsx` do viser
    dentro do `.venv` e remonta a página; rode de novo se o ARDY for reinstalado. A página só
    muda depois de reiniciar o demo e recarregar a aba. O conserto foi conferido no arquivo
    servido, não com um clique na tela.
  - Com o demo aberto o Windows fica com menos de 1 GB livre até o cache de arquivos do Ubuntu
    ser solto (`ardy-liberar-cache.sh`, como root; o atalho já faz isso). O "ao vivo" não roda
    dentro da Godot.
  - Do modelo: irmão em tempo real do Kimodo, do mesmo grupo e treinado nas mesmas gravações
    (Bones Rigplay 1); o artigo não compara a qualidade com a do Kimodo e avisa de pé
    deslizando e tremor. Tem também o robô G1; o do SOMA está como "em breve". Só Linux,
    testado numa RTX 4090. Uso comercial liberado.

As seções abaixo sobre gerar no Kimodo descrevem como era e como volta a ser se ele reinstalar.

## O ARDY na ponte

É o terceiro gerador (`engines.ENGINES["ardy"]`), com o contrato dos outros (`ardy.generate`).

- **Quem fala com o modelo é `ardy_scripts/gerar.py`**, que roda no ambiente do ARDY, dentro do
  Ubuntu (`ponte/ardy.py` o chama por `wsl.exe`; os scripts de shell são gravados na hora em
  `data/tmp/ardy/`, com fim de linha do Linux). Usa `model.autoregressive_step`, como o demo:
  janelas de 40 quadros (2 s), cada uma partindo do que já existe. Mexer nele não pede reinício
  do servidor.
- **Esqueleto Core, 27 juntas, 20 quadros por segundo.** A regra do SOMA 77 é do Kimodo. O
  clipe entra pelo caminho das capturas (`pipeline._register_ardy_motion`): `ardy.bvh` (já a
  30 quadros por segundo), `motion.bvh` (nomes do SOMA), `motion.npz` (de onde continuar, a 20)
  e `stand_height` no registro. No registro, `source` é `"kimodo"` (gerado aqui) e `engine`,
  `"ardy"`.
- **Texto novo precisa do codificador (16 GB de RAM)**; texto já usado, não: o script guarda
  cada texto codificado na pasta do demo (`~/ardy/.cache/text_embeddings`), e os dois se
  aproveitam. Para um texto novo a ponte sobe o codificador, codifica e o desliga antes de
  gerar; se já estava no ar (demo aberto, ou **Ligar**), não mexe. **Com a Unreal aberta ou
  menos de 14 GB livres ela recusa** (`ardy.encoder_blocker`): é a trava para o que aconteceu
  em 08/10. Os dez textos de exemplo do demo já estão codificados (`A person is walking.`,
  `A person is standing.`, `A young lady walks forward elegantly.`...): servem para testar sem
  o codificador.
- **Medido em 09/10/2026, com gerações de verdade** (RTX 3060, uns 40 s por pedido):
  - emenda entre passos sem tranco (0,4 a 0,8 cm, dentro do normal do movimento) e o que já
    foi entregue não muda ao continuar;
  - andar em laço de 4 s com direção e ritmo: fecha em 0,0 cm, andou 0,80 m/s para 0,8 pedidos;
  - o passo novo enxerga só 4 quadros do anterior (`CARRY`, o padrão do demo). Com 1 s o
    movimento novo fica preso ao antigo (chute com metade da altura; "parado" que não parava);
  - a correção de pé roda nos quadros novos com 1 s de contexto e o desvio some em 0,5 s
    (`polish`). Corrigir cada passo sozinho dava um tranco de 7 cm na emenda;
  - o BVH é reamostrado para 30 quadros por segundo passo a passo (`to_project_rate`).
    Reamostrado como um clipe corrido, o laço saía um quadro curto e pulava 5 cm.
- **Escreva o que o corpo faz**: `A person is walking.` depois de um passo parado não andou
  (0,6 m em 5 s, nem com peso 4); `A young lady walks forward elegantly.` andou 5,3 m em 6 s.
- **Laço depois de um movimento**: o laço fecha na pose em que o passo começa. Um "parado em
  laço" logo depois de um andar fechou numa pose de meio de passada, dando voltas até lá.
  Gere antes o passo de entrada (parar), como no Kimodo.
- **Sessões do demo ao vivo**: `ponte ardy sessions`, `ponte motion import-ardy <projeto>` e
  **Sessões do ARDY**, na aba Prévias. A sessão vira um roteiro (um passo por texto) e dá para
  continuar dela. Testado com um arquivo fabricado no formato que o `session_io.py` do demo
  grava: **falta uma sessão exportada de verdade por ele**.
- **Não rodado de verdade**: subir o codificador pela ponte, codificar um texto novo e
  desligar (a Unreal estava aberta em 09/10; só com dublê). Na primeira vez, confira a
  memória e que ele desligou (`ponte ardy status`).
- Teste: `tests/check_ardy.py` (dublê no lugar do script do Ubuntu; precisa de Blender).

## O Soldado pelo ARDY: reprovado em 10/10/2026

O usuário pediu a movimentação do Soldado pelo ARDY, sem as do Mixamo, para a Godot ("todas as
animações"), e depois: "primeiro quero testar todas as animações dentro da ponte, ou seja crie
um novo projeto do soldado". O projeto novo é `soldado-ardy-121a` (**Soldado ARDY**): o mesmo FBX
rigado, sem acessório ("a arma vamos arrumar no blender"). O Soldado antigo
(`tripo-convert-…`) não foi tocado: continua com as 38 do Mixamo e o fuzil.

- **Foram gerados 38 clipes e ele mandou apagar todos.** Vendo os primeiros: "o movimento de
  pernas deles é muito bom, faça todos". Vendo o pacote: "walk left e right não ficaram legais,
  ele dá pulinhos, o ideal seria entrelaçar as pernas"; reprovou 7 das 8 disparadas, sem nota;
  e por fim "por favor pare" e "apague todas as animações, todas estão ruins". O projeto ficou
  vazio. Do resto ele não disse o que achou ruim: não suponha, pergunte.
- **Não gere o pacote de novo sem ele pedir.** Se pedir, mostre um clipe de cada tipo (andar,
  de lado, correr, agachado, parado) e espere o veredito antes de produzir o resto.
- Os scripts usados ficaram fora do git, em `data/tmp/soldado-ardy/` (`soldado_ardy.py`, que
  chama `pipeline.generate_motion` e `import_capture`, e `soldado_clip.py`, no Python do Blender).
- **Uma prévia voltou ao projeto no mesmo dia, a pedido dele: `walk-forward-60a1`.** As animações
  passaram a ser feitas no Blender (`D:\Blender-Animacoes\Soldado`) e, no andar, ele perguntou
  "tem como você pegar o movimentar das pernas do ARDY?" e depois pediu "traga toda a animação
  do ARDY pra cá e nós arrumamos ela". A prévia é a fonte desse trabalho (há cópia em
  `D:\Blender-Animacoes\Soldado\fontes\`): não é para aprovar na ponte, nem sinal para gerar o
  resto. A primeira tentativa (`walk-forward-eb92`, "walking while holding a rifle with both
  hands") saiu mirando e ele cobrou: "fez o prompt errado, ele está mirando, não patrulhando".
  Da `60a1`, com o texto de arma baixa, ele disse: "ficou excelente, parabéns, só precisa
  ajustar agora o rifle na mão" (o que o ARDY entrega nas mãos não serve: sem dedos, a mão
  esquerda por cima da arma e a coronha 2,7 cm dentro do peito; a pegada é refeita no Blender).

O que se aprendeu do ARDY, e vale para outro personagem:

- **Como escrever o texto** (ele pediu: "pesquise melhores formas para evitar erro no prompt").
  O [guia do Kimodo](https://research.nvidia.com/labs/sil/projects/kimodo/docs/key_concepts/limitations.html),
  que é o mesmo treino: comece por `A person…`, uma ou duas ações por texto, nem curto demais nem
  detalhe de parte do corpo, cada texto se basta, e o caminho pedido não pode contradizer o texto.
  O vocabulário está nas legendas públicas, `nvidia/SEED-Timeline-Annotations` no Hugging Face
  (`timelines.jsonl`, 80 MB): os conjuntos são `walk_ff_loop_<ângulo>`, `jog_ff_…`, `crouch_ff_…`,
  "ff" de olhando para frente (180 frente, 225 diagonal, 270 de lado para a direita, 315 e 360
  para trás), e o lado esquerdo é a cópia espelhada (`_M`), com `left` e `right` trocados na
  legenda. Lá: `is walking sideways in the right direction at a medium pace in a crisscross
  manner`, `jogs forward at a steady pace`, `A crouched person walks forward at a slow pace`.
- **Arma**: o subconjunto público não tem legenda de arma, mas o treino tem. `while aiming a
  rifle` entrega a pose de mira, e `holding a rifle with both hands` (mesmo com `at waist height`)
  também: fuzil no ombro, mãos a menos de 10 cm abaixo do ombro. Parado, `pointing it down at
  the ground`, `carrying` e `stands guard` saíram com a arma erguida do mesmo jeito.
- **Arma baixa, de patrulha, andando**: sai com `A person is steadily walking forward while
  carrying a rifle low in front of their waist with both hands, the barrel pointing down at the
  ground.` (mãos 16 a 22 e 25 a 36 cm abaixo do ombro, cano 22° a 30° para baixo, tronco em pé,
  o peito girando uns 11° a cada passada). `…holding a rifle at the low ready position` deu quase
  o mesmo. Sem a palavra fuzil (`holding an object with both hands at waist height`) as mãos
  ficam baixas, mas na mesma altura. Os dez textos testados e os números estão em
  `data/tmp/soldado-ardy/provar_patrulha.log`; `soldado_ardy.py probe` testa um texto em 10 s.
- **A mão da arma depende da direção**, porque metade do treino é espelhada: de lado para a
  direita sai destro e para a esquerda, canhoto (8 de 8); nas diagonais para a frente, o
  contrário; para frente e para trás, ao acaso. Espelhar o clipe inteiro conserta frente e trás.
  O outro lado de cada par só sai destro juntando as pernas e o quadril espelhados com o tronco
  e os braços do clipe original. Quem é a mão de apoio: a que tem a palma para cima.
- **Mirando, de lado ele não cruza as pernas**: 4 passadas curtas em 2 s (os "pulinhos"), com os
  pés sempre a mais de 7 cm um do outro, mesmo com `crisscross` no texto. Sem arma o mesmo texto
  cruza (pés a −53 cm). Juntar essas pernas com o tronco de mira não chegou a ser mostrado a ele.
- **Disparada** (5 m/s) de lado e de costas não existe nos dados: a diagonal saiu a 331° em vez
  de 315° e o pé não para no chão. O correr a 3,4 m/s de lado escorrega 47 a 56 cm/s.
- **O Ubuntu desliga depois de 1 minuto sem processo**, e aí cada pedido leva 80 s em vez de 10
  (o modelo é relido do E:). Num lote, deixe um `wsl.exe -d Ubuntu -- sleep <segundos>` solto em
  segundo plano e encerre-o no fim.
- **Codifique todos os textos de uma vez** (`ardy._encode_texts` com um `job.json` só de
  textos): 4,5 minutos para subir o codificador e 5 s por texto. Foram quatro subidas nesse dia.

## Personagem pelo Meshy

Em 09/10/2026 o usuário pediu a ligação com o Meshy em etapas: "vc solicita a api com passo,
primeiro imagem do solicitado, caso imagem aprovado vc solicita o projeto 3d e já alocada na
tela". É `ponte/meshy.py` (API REST do Meshy, só biblioteca padrão) e `pipeline.approve_meshy`.

- **Você faz o pedido da imagem; quem aprova é ele.** `uv run ponte meshy image "<em inglês>"
  --name "<nome em português>"` gera a imagem (3 créditos) e ela aparece em **Pedidos ao
  Meshy**, na tela de entrada. Avise que ela está lá e pare: **não rode `ponte meshy approve`
  por conta própria**. O modelo custa dezenas de créditos e só sai com a aprovação dele, pelo
  botão **Aprovar e gerar o 3D** ou dizendo a você que aprovou.
- **Reprovada, a nota volta por `ponte status`** (linha `Meshy :`) e por `ponte meshy status`.
  Refaça com outro texto e `--replace <pedido>`: o reprovado sai da lista quando a imagem nova
  chega.
- Descreva o personagem inteiro, de corpo inteiro, sozinho, sem cenário (`full body, single
  character, plain background`). A pose padrão é `a-pose`, com os braços afastados do corpo,
  que é o que o rig daqui pede.
- O modelo aprovado vira **projeto novo**, com laudo, sem esqueleto: o passo seguinte é ele
  rigar aqui (o QA do rig é dele). A malha vem reduzida a 50 mil triângulos (`--polycount`).
- A chave fica em `meshy.key`, na raiz (fora do git; `ponte meshy key <chave>`), ou em
  `MESHY_API_KEY`. Não a ponha em `data/`, que a interface serve, nem no `ponte.toml`.
- Nada é pago duas vezes: aprovar marca o pedido no clique (`meshy.claim`), e um modelo que já
  estava sendo gerado é retomado pela tarefa guardada (`model_task`).
- **Nenhum pedido foi feito ao Meshy de verdade até 09/10/2026** (não havia chave): só com
  dublê (`tests/check_meshy.py`) e cliques na tela. Na primeira vez, confira a resposta de
  verdade contra o que o código espera (`image_urls`, `model_urls.glb`, `consumed_credits`).
- O Meshy tem servidor MCP oficial (`npx add-mcp @meshy-ai/meshy-mcp-server --env
  MESHY_API_KEY=...`). Não foi instalado: mexe na configuração do Claude Code dele e pula a
  aprovação da imagem. Só com ele pedindo.

## Seu papel

Você faz as animações por trás (o Blender escondido, `uv run ponte ...`) e as põe na lista do
projeto; o usuário assiste no visor e diz o que achou na própria conversa, que desde 11/10/2026
costuma ser no terminal da tela do projeto (ver "A tela nova", no alto). A tela nova não tem
aprovar e reprovar. Se ele usar a tela anterior para isso, o retorno chega por
`uv run ponte status`: prévias `[REPROVADO]` vêm com a nota dizendo o que corrigir. Leia antes
de fazer de novo.

O que segue, sobre roteiros, vale quando a animação é **gerada por texto** (`ponte gen`). Uma
animação gerada é um **roteiro**: passos em sequência, num clipe só, cada passo partindo dos
últimos quadros do anterior. Não gere ações relacionadas como pedidos separados: o usuário
reprovou isso (os clipes não se ligam e o personagem "teletransporta").

O roteiro é feito **um passo de cada vez**, por decisão do usuário: gera-se um passo, ele é
entregue e conferido, e só então vem o próximo, em cima do que foi entregue (`ponte gen ...
--continue <animação>`). Não mande vários passos num pedido só. Cada roteiro é um clipe: ao
continuar, a prévia do clipe menor sai da lista e a animação dele fica guardada, para dar para
refazer o passo (`--continue <anterior> --replace <a que saiu errada>`). A interface faz o
mesmo e trava o passo seguinte enquanto o atual não chega.

### Quando o usuário descreve uma animação

Ele descreve em português o que quer e você entrega a animação na tela, pronta para ele ver. Na
tela nova o pedido chega pelo terminal do projeto: você foi chamado na pasta dele e o guia de
lá diz qual é o projeto. Na tela anterior havia o botão **Pedir ao Claude**, que abre a conversa
com o contexto já escrito (`PonteAnimada: animação para o projeto "<nome>" (id <id>).` e, se
houver, `Prévia aberta: <id>`), seguido do que ele quer. As animações vão para um jogo na
**Godot** e ele quer resultado fluido, de nível profissional.

- **Entregue o que ele pediu, e só.** Ele pensa em ações (parado, andando, ouviu barulho,
  ataque), não em roteiros. Pediu quatro coisas simples e recebeu doze passos em três roteiros,
  com variações e reações que eu propus: "estou vendo mais dificuldade que entrega". Extras,
  só se ele pedir.
- **Dê nome ao roteiro e a cada passo, em português** (`--name "Reações"`, `--label
  "agitado"`; depois, `ponte motion label <id> --name ... --steps ...`), e marque as ações que
  ele pediu como principais (`pipeline.label_motion(..., stars=[...])`, ou ★ na interface): são
  as que aparecem no alto da lista **Ações**, uma por linha, e o resto fica recolhido. Sem
  nome a prévia aparece com o texto em inglês do roteiro inteiro, e ele já deixou de achar uma
  animação que estava lá por causa disso.
- **Você escreve o roteiro em inglês.** Descreva o que o corpo faz, não a intenção: `looking
  back cause he heard something` em 3 s não virou a cabeça (10°); `suddenly stops and turns his
  head and upper body to look behind him over his shoulder` em 5 s entregou.
- **Pense nos segundos de cada passo.** A ação precisa de tempo para começar, acontecer e
  assentar; parar e virar não cabem em 3 s. Diga ao usuário quanto tempo deu a cada passo.
- **Pense no comportamento dentro do jogo**: que estados o personagem tem (ocioso, vagando,
  parar, virar, alerta) e como um leva ao outro. Diga o que supôs.
- **Trajetória só em passo que anda.** Caminho ou direção num passo cujo texto manda ficar
  parado faz o personagem deslizar (já aconteceu: 3,65 m num passo "parado").
- **Confira antes de dizer que saiu, com números.** O texto estar no roteiro não garante o
  gesto, e a tira de quadros engana em gesto pequeno (já aconteceu: dei por bom um ocioso que
  "balançava" 13 cm e o usuário viu que estava parado). Meça o passo:
  `blender --background --python blender/step_stats.py -- <pasta da animação>` mostra, por
  passo, quanto andou, virou, balançou, inclinou a cabeça, tirou os pés do chão e mexeu as mãos,
  e se o laço fecha. Para ver, `blender/render_sheet.py --start <quadro>`. Passo que falhou,
  refaça com `--replace`: a versão errada some quando a nova fica pronta.
- **Laço** (`--loop`, com `--continue`): o passo termina na pose em que começou, para o jogo
  tocar em repetição (ocioso, andar). Precisa de um passo de entrada antes (o personagem já na
  postura) e de pelo menos 2 s; num passo que anda, dê `--direction` e `--speed`. O gerador o
  faz em duas partes, uma livre e uma de volta à pose inicial: numa parte só, presa nas duas
  pontas, o modelo quase não se mexe.
- **Gesto fraco**: `--text-weight` (padrão do Kimodo 2; usei 4) faz o modelo obedecer mais ao
  texto. Num ocioso, junto com o laço em duas partes, levou a cabeça de 12° para 45° de
  inclinação e as mãos de 0,11 para 0,29 m/s; o balanço do corpo inteiro continuou moderado.
- Gere quando ele pedir. Para testar código, use `--dry-run`, não uma geração de verdade.

### O zumbi do jogo

O usuário quer zumbis lentos, que **não correm**: a arma deles é a quantidade. A referência é
The Last of Us, pesquisada em 07/10/2026:

- No primeiro jogo ([capítulo de Mark Botta, Game AI Pro 2](http://www.gameaipro.com/GameAIPro2/GameAIPro2_Chapter33_Infected_AI_in_The_Last_of_Us.pdf))
  o infectado que não tem nada para fazer **vaga** (anda, para, olha em volta); ao começar a
  ouvir algo entra num estado **agitado**, que avisa o jogador; ao perceber a presa **vira na
  direção do estímulo** com uma animação escolhida de um conjunto por direção; e quem não ouviu
  nada **segue** o que saiu atrás de algo. A variedade vem de um conjunto de animações curtas
  escolhidas na hora, evitando a que acabou de tocar, e não de um laço longo.
- No Part II a locomoção usa motion matching (um banco grande de captura de movimento picado
  em pedaços, escolhidos quadro a quadro). Não está ao nosso alcance: aqui o caminho é o do
  primeiro jogo, laços curtos e clipes de transição ligados por estados.
- Em horda, o que evita o "exército sincronizado" é cada zumbi começar o laço num ponto
  diferente, com velocidade um pouco diferente, e haver mais de uma variação de cada clipe.

Um roteiro de comportamento alterna laços e transições (entrada, ocioso em laço, começa a
andar, andar em laço, parar): os laços são os estados do jogo e as transições saem de um para
o outro. Andar de zumbi: 0,5 m/s.

- **O conjunto que o usuário quer é o básico**: parado, andando, virar à esquerda e à direita
  (é a reação a barulho) e ataque. Ele descartou as reações que eu tinha proposto (agitado,
  levar pancada, variações): "ficaram ruins". Não as refaça sem ele pedir.
- **O ataque é simples**: ele anda com os braços baixos e, ao chegar perto, joga a cabeça para
  frente para morder. Parte do andar e avança (continue da animação que termina no andar, com
  direção para frente). O que ele recusou: agarrão parado saindo do ocioso ("não teria que ir
  para cima andando?") e braços erguidos ("ruim e forçado").
- **Texto de ataque faz o Kimodo levantar os braços**: `grab`, `reach out`, `lunges at someone`
  deram braço acima da cabeça três vezes, mesmo com `keeps his arms down`. Funcionou descrever
  só a cabeça: `walks forward with his arms hanging down and quickly thrusts his head forward
  like a headbutt to bite, then pulls his head back`, com `--text-weight 2.5`. Peso 5 deixa o
  gesto forçado. `step_stats.py` mostra a altura das mãos em relação ao ombro e à cabeça.
- **Morte é ragdoll na Godot**, por decisão do usuário: não gere animação de morrer.
- **Ação que volta de onde saiu** (o ataque volta ao andar): gere com `--loop`, mesmo não
  sendo laço. É o que a faz terminar na pose em que começou, e o jogo emenda sem tranco.
- Pedir um ângulo de virada não garante o ângulo (pedi 90° e saíram 107° e 86°): meça e informe.

## Projetos, prévias e resultado

- Cada personagem enviado é um **projeto** separado (`data/projects/<id>/`). Animações e
  prévias nascem dentro do projeto do personagem e não são usadas em outro. O id do projeto
  é o do personagem: é o que `--asset` e `ponte close` recebem.
- **Prévia** (`result` no código, pasta `previas/`) é a animação aplicada no personagem, para
  o usuário validar. Não é a entrega.
- O **resultado** (`asset.final`, pasta `resultado/`) só existe depois de encerrado: um GLB,
  um FBX e um BLEND com todas as prévias não reprovadas, mais um atalho em
  `data/resultados/<Nome>.lnk`, fora da pasta do projeto.
- Quando o usuário disser **"encerremos esse personagem"**, rode `uv run ponte close <id>`.
  Não encerre por conta própria: quem decide que o personagem está completo é ele.

## Regras do usuário para o Kimodo

- Sempre o esqueleto SOMA 77 (`Kimodo-SOMA-RP-v1.1`). Não troque de modelo.
- Um pedido de cada vez: nunca duas gerações ao mesmo tempo, para não sobrecarregar a máquina.
  O que chega com outro gerando espera na fila e entra na ordem em que foi pedido.

As duas já são impostas por `ponte/kimodo.py`. Não contorne chamando `docker compose run`
ou `kimodo_gen` direto: use a CLI ou a API, que passam pela trava e pela fila.

A vaga e a fila são arquivos em `<acervo>/.locks`, e o acervo muda com `PONTE_DATA`: num
acervo descartável a vaga é outra, separada da do acervo real. Gerar de verdade ali fura a
regra do usuário; use só o ensaio a seco (`ponte gen ... --dry-run`).

## Dois geradores: Kimodo original e kimodo.cpp

Em 08/10/2026 o usuário pediu o kimodo.cpp instalado e a escolha entre os dois **ao abrir a
ponte**: a interface pergunta "Qual gerador você vai usar?" uma vez por janela aberta
(`sessionStorage`), e dá para trocar depois em *trocar gerador*, na barra de cima. A escolha é
uma só para tudo (`data/gerador.json`, `ponte/engines.py`): vale para a tela e para o `ponte gen`
sem `--engine`. `ponte engine [kimodo|cpp]` mostra e troca.

- **Não troque o gerador por ele**, nem em teste: a escolha é do servidor inteiro. Em 08/10
  um teste de cliques meu trocou o gerador no mesmo minuto em que ele escolhia. Para testar a
  pergunta, use um segundo servidor num acervo descartável (`PONTE_DATA` + `--port 8766`).
- O kimodo.cpp fica em `D:\kimodo.cpp` (`[kimodo_cpp]` no `ponte.toml`). Da primeira vez (08/10,
  apagado no mesmo dia) foi compilado só para o processador: uns 30 s para carregar o modelo e
  1,8 s por passo de difusão num clipe de 5 s; com os 100 passos da ponte, 3 min e meio.
- **Reinstalado em 10/10/2026 com Vulkan** (o programa usa a placa sozinho quando é compilado
  assim; `KIMODO_BACKEND=cpu` força o processador): 0,1 s por passo de difusão, 33 s o clipe de
  5 s contando a carga dos pesos, que acontece a cada pedido. Como foi feito, para repetir:
  - `git clone --recurse-submodules https://github.com/localai-org/kimodo.cpp D:\kimodo.cpp`
    (commit `5679ff1`, de 17/09/2026; o `ggml` vem como submódulo);
  - pesos: `uv run --no-project --with huggingface_hub python scripts/download_gguf_weights.py
    --output D:/kimodo.cpp --model soma-rp-v1.1` (1,06 GB do movimento, 7,58 GB do codificador
    de texto Q8 e o `tokenizer.gguf`; sem token do Hugging Face);
  - Vulkan SDK 1.4.363.0 do site da LunarG, instalado como cópia simples, sem administrador e
    sem mexer no sistema: `vulkansdk-windows-X64-1.4.363.0.exe --root D:\VulkanSDK\1.4.363.0
    --accept-licenses --default-answer --confirm-command install copy_only=1` (1,7 GB; só é
    preciso para compilar, o programa pronto usa o `vulkan-1.dll` do Windows);
  - com `VULKAN_SDK=D:\VulkanSDK\1.4.363.0` no ambiente e o CMake que vem nas Ferramentas de
    Build do Visual Studio 2022: `cmake -S D:\kimodo.cpp -B D:\kimodo.cpp\build -G "Visual
    Studio 17 2022" -A x64 -DKIMODO_ENABLE_VULKAN=ON -DKIMODO_BUILD_TESTS=OFF` e
    `cmake --build D:\kimodo.cpp\build --config Release --target kmd-generate --parallel 8`
    (uns 5 minutos, quase tudo nos programas de placa do `ggml`).
- **Dá para ficar mais rápido**: o `kmd-generate` tem um modo `--server` (lê pedidos da entrada
  e mantém os pesos na placa), que a ponte ainda não usa. A conta deles: 150 quadros em 4,5 s
  numa RTX 5070 Ti com tudo carregado.
- **Texto de arma no Kimodo não é o do ARDY** (cinco testes em 10/10/2026, andando para a
  frente, 5 s cada; a tira de imagens está em `data/tmp/soldado-ardy/provar_kimodo_cpp.png`):
  `holding a rifle at the low ready position`, `on patrol with a lowered rifle held in both hands
  in front of their hips` e `holding an object with both hands at waist height` saíram com as
  mãos baixas; `carrying a rifle low in front of their waist... the barrel pointing down at the
  ground` (o texto que deu certo no ARDY) e `...down by their thighs` saíram mirando.
- É o mesmo modelo (`Kimodo-SOMA-RP-v1.1`). Ele devolve 30 juntas; `ponte/kimodo_cpp.py` as
  grava no SOMA 77 de sempre, com os dedos na pose relaxada fixa que o oficial põe em toda
  animação (molde em `ponte/soma77_relaxed.bvh`). A assinatura do esqueleto é conferida igual.
- A vaga e a fila são as mesmas (`kimodo.generation_slots`): um pedido de cada vez, somando os
  dois geradores.
- **O que o kimodo.cpp não faz**: caminho, direção e velocidade, laço e força do gesto. A
  tela desliga esses controles e o backend recusa antes de gerar. Não tem pós-processamento.
- **Continuar um roteiro** nele é gerar o roteiro inteiro de novo com a mesma semente: o passo
  anterior sai igual (conferido: 86 de 90 quadros idênticos, os 4 últimos são a emenda). Por
  isso refazer um passo com o mesmo texto dá o mesmo resultado: mude o texto. O tempo cresce
  com o roteiro. Um gerador não continua o clipe do outro (`motion.json` guarda `engine`).
- Teste: `tests/check_engine.py` (dublê no lugar do programa; precisa de Blender).

## Não derrube o trabalho do usuário

O usuário usa a interface enquanto você trabalha. Reiniciar o servidor mata os jobs em
andamento (já aconteceu: uma geração dele foi interrompida assim) **e fecha os terminais da
tela, com a conversa que estiver rodando neles** (a IA que ele chamou ali, que pode ser você
mesmo: se você está num terminal da tela, parar o servidor encerra a sua própria sessão).

- Só o código em `ponte/` exige reinício. Mudanças em `blender/` e `web/` valem na hora
  (a interface pede Ctrl+R).
- Antes de reiniciar, olhe `GET /api/terminal`: `talking` lista os projetos em cujo terminal
  alguém já escreveu. Com algum ali, não reinicie sem ele mandar. O `parar.ps1` não confere
  isso: só os jobs.
- Para reiniciar: `scripts\parar.ps1` (recusa com job ativo; não use `-Force` por conta
  própria) e depois `uv run ponte serve` em segundo plano, com a saída em `data\server.log` e
  `data\server.err.log`, como faz o `scripts\abrir.ps1`.
- `uv add` e `uv sync` falham com o servidor no ar (o `ponte.exe` fica em uso), e mudar o
  `pyproject.toml` faz o `uv run` seguinte tentar o mesmo e falhar também (aconteceu em
  10/10/2026, ao pôr o `pywinpty`). Mexa nas dependências só com o servidor parado.
- Projetos em `data/` que você não criou são do usuário: não apague.
- `ponte retarget` (e o *Refazer retarget* da interface) apaga a prévia e grava outra com a
  revisão de volta em `pendente`: a aprovação ou a nota de reprovação do usuário some. Só existe
  uma prévia por animação (o id dela é o da animação, ou `<animação>--parado`). Leia a nota em
  `ponte status` antes de refazer.
- Para testar sem tocar no acervo dele, aponte `PONTE_DATA` para uma pasta descartável:
  vale para a CLI, para os testes e para um segundo servidor (`uv run ponte serve --port 8766`).

## Ambiente

- Windows, sem Python de sistema: use `uv run`. Blender 5.2 em `ponte.toml`.
- O Kimodo rodava em Docker dentro do WSL (`~/kimodo`, distro Ubuntu) e foi desinstalado em
  08/10/2026; o guia para reinstalar está em `docs/kimodo-setup/GUIA-KIMODO.md`. O text encoder
  ocupava ~17 GB de RAM.
- Prompts do Kimodo em inglês. Cada frase terminada em ponto é um trecho com duração própria,
  de no máximo 10 s: a API recusa mais que isso, mas `ponte gen` não confere.
- Scripts `.ps1` sem acentos: o PowerShell 5.1 lê arquivo sem BOM como ANSI.
- Dentro de `data/`, não conte com renomear ou mover **pasta**: o Windows nega (WinError 5)
  enquanto outro programa tiver algo aberto dentro dela, e isso aconteceu aqui com a pasta do
  personagem. Arquivo renomeia normalmente. Para trocar o conteúdo de uma pasta, copie arquivo
  por arquivo (é o que a migração e o encerramento fazem).

## Comandos

```powershell
uv run ponte serve                    # API + interface em http://127.0.0.1:8765 (rotas em /api/docs)
uv run ponte status                   # acervo, fila e as revisões do usuário, com as notas
uv run ponte gen "..." --dry-run      # confere que o roteiro monta, sem gerar
uv run ponte anim add <projeto> <arquivo.glb> --name "<nome>"   # põe na tela uma animação feita no Blender
uv run python tests/check_rigmap.py   # um teste é um script: rode o arquivo (ver Testes)
npm install --prefix web              # só numa pasta nova: o three.js e o xterm.js são servidos de web/node_modules
```

Não há build, lint nem formatador no fluxo. O `[tool.ruff]` do `pyproject.toml` só fixa 120
colunas, o ruff não está instalado e o código tem linhas maiores que isso: não reformate
arquivos inteiros.

## Arquitetura

Quatro ambientes de Python que não se importam entre si; conversam por argumentos e arquivos JSON:

| Onde roda | Código | O que tem à mão |
|---|---|---|
| venv do `uv`, no Windows | `ponte/` | fastapi, biblioteca padrão |
| Python embutido do Blender | `blender/*.py` (entradas) e `blender/ponte_bl/` (biblioteca) | `bpy`, numpy |
| container do Kimodo, no WSL | `kimodo_scripts/gerar.py` | torch, `kimodo` |
| ambiente do ARDY, no Ubuntu do WSL | `ardy_scripts/gerar.py` | torch, numpy, `ardy` |

- **Camadas do backend**: `store` (registros em arquivo) → `pipeline` (as operações: laudo, rig,
  gerar, retarget, encerrar) → `server` (FastAPI) e `cli`. Toda função de `pipeline` recebe um
  `log` e só mexe no store, então serve igual para os dois: regra nova vai em `pipeline`, e
  `server`/`cli` ficam com a validação da entrada e o registro do job.
- **Sem banco**: o estado é o que está em `data/`, um `asset.json`, `motion.json` ou
  `result.json` por pasta (layout no cabeçalho de `ponte/store.py`). Servidor e CLI leem e
  gravam os mesmos arquivos; é assim que um vê o que o outro fez. Os ids não se repetem entre
  projetos (`store.folder` acha animação e prévia procurando em todos).
- **Nomes**: código e API em inglês (`asset`, `motion`, `result`, `final`); interface e pastas em
  português (personagem/projeto, animação, prévia, resultado). `results` na API são as
  **prévias**. Os estados são strings em português: laudo `pronto` / `precisa_rig` /
  `precisa_mapeamento` / `nao_suportado` / `so_animacao`; revisão `pendente` / `aprovado` / `reprovado`; job
  `fila` / `rodando` / `ok` / `erro` / `interrompido`.
- **Jobs** (`ponte/jobs.py`): um JSON por job em `data/jobs/`, com o PID de quem o roda. O
  servidor roda os dele em threads; a CLI roda no próprio processo e só registra o job para a
  interface mostrar. Por isso a CLI funciona com o servidor fora do ar, e por isso job ativo
  de processo morto aparece como `interrompido`.
- **Blender** (`ponte/blender.py`): `run_script` chama `blender --background --factory-startup
  --python blender/<script> -- <args>` e lê o JSON que o script grava por `ponte_bl.cli.run`
  (`{"ok": true, ...}` ou `{"ok": false, "error", "traceback"}`), não a saída padrão. As
  entradas em `blender/*.py` só leem argumentos; a lógica fica em `ponte_bl/`. `bvh.py` e
  `rigmap.py` não usam `bpy` e são testáveis fora do Blender.
- **Interface** (`web/`): `app.js` (telas) e `viewer.js` (three.js), sem build nem framework. A
  cada 2 s ela busca `GET /api/state`, que devolve tudo, e redesenha; os arquivos de `data/`
  saem por `/files/...`. O terminal usa o xterm.js (`web/node_modules/@xterm`, servido em
  `/vendor/xterm...`) e um WebSocket por projeto. A tela anterior é uma cópia completa em
  `web/antiga/` (`index.html`, `app.js`, `style.css`, `viewer.js`): as duas leem a mesma API,
  então o que muda no formato dos registros tem de ser conferido nas duas (a antiga quebrava
  ao abrir uma animação pronta, sem as medidas do retarget; consertado em 11/10/2026).
- **Quando falha**: o log do job fica em `data/jobs/<id>.log`, e o do Blender ao lado da saída
  (`personagem/inspect.log`, `personagem/rig/*.log`, `previas/<id>/retarget.log`). Retarget que
  falha apaga a pasta da prévia com o log junto: aí resta o do job. Encerramento que falha deixa
  `data/tmp/encerrar-<id>/build.log`. Servidor aberto pelo atalho grava em `data/server.err.log`.

## Onde o Kimodo é chamado

`ponte/kimodo.py` copia `kimodo_scripts/gerar.py` para dentro de `~/kimodo/ponte_out/<job>/` e
o roda no container (`docker compose run demo python …`). É esse script que usa a API do
Kimodo: constraints de trajetória (`root2d` + heading), continuação (os 5 primeiros quadros
presos aos 5 últimos da animação anterior) e várias tomadas em sequência. Convenções lá no
cabeçalho. Ao rodar `wsl.exe ... bash -lc '...'` à mão, variáveis `$x` são expandidas por um
shell intermediário: ponha o script num arquivo e rode o arquivo.

O que a interface edita e o Blender grava (ajuste de pose, acessórios) usa o espaço local do
osso, que é o mesmo no three.js e no Blender; o conteúdo de um acessório precisa da troca
Z-para-cima → Y-para-cima (`ponte_bl/props.py`). `tests/check_bake.py` confere os dois.

## Animações do Mixamo

Para o básico (parado, andar, ataque) o usuário decidiu usar as animações prontas do Mixamo: o
Kimodo precisou de várias tentativas por ação e o resultado não ficou de nível profissional.
Ele baixa o FBX de lá (não há como baixar por ele: exige a conta Adobe) e importa pelo botão
**+ Mixamo (.fbx)**, no alto da lista de animações do projeto (na tela anterior: **Animações
Mixamo**, na aba Prévias), ou `ponte motion import-fbx <projeto> <fbx>`.
O Kimodo fica para o que o Mixamo não tem.

Por dentro: o arquivo fica em `animacoes/<id>/motion.fbx` (`source: "mixamo"`) e
`blender/ponte_bl/mixamo.py` lê a armature animada quadro a quadro e a entrega ao mesmo
`retarget()` do Kimodo, com cada osso chamado pela junta do SOMA de mesmo papel. Por isso a
animação serve em personagem de outro esqueleto, pose de descanso ou escala. Vira um roteiro
de um passo só, já com nome e marcado como ação principal. `tests/check_mixamo.py` confere.
Testado com FBX fabricado aqui e com três animações de verdade do Mixamo (sem malha) numa cópia
do zumbi1. Um pacote do Mixamo é um ZIP com o personagem e um FBX por animação; enviado como
projeto novo, só o personagem entra (`add_zip` fica com o maior modelo). As animações do
pacote são importadas pelo campo, no projeto do personagem que vai recebê-las.

O usuário tem dois pacotes de zumbi do Mixamo em Downloads (`Not So Scary Zombie Pack` e
`Scary Zombie Pack`), cada um com a personagem Zombiegirl e um FBX por animação. Medidos em
07/10/2026 no primeiro: `zombie idle` e `zombie idle (2)` e `walking` fecham em laço exato
(`walking`: 1,6 s, 0,61 m/s, com deslocamento embutido); `walking (2)` não fecha (emenda de
19°); `zombie punching` é o ataque curto (1,1 s); `zombie attack` ergue os braços acima da
cabeça, que ele não quer; `zombie turn` vira ~110°; `zombie transition` leva do ereto ao
curvado; `stand up` levanta do chão; `stumbling` termina caído. A mordida (`zombie biting`,
`zombie neck bite`) está no segundo pacote. O Kimodo entra no que falta: virar 90° para cada
lado, variações para o bando e ações próprias do jogo. Ele não continua a partir de uma pose
do Mixamo; entre um clipe e outro, a mistura é da Godot.

Arquivo só com esqueleto e movimento não é personagem: o laudo dá `so_animacao` e ele não
recebe animação (o usuário já criou 24 projetos assim, soltando o pacote na tela inicial).

## Capturas de movimento

Em 08/10/2026 o usuário perguntou se dava para "clonar" as animações do Game Animation Sample
da Unreal para a Godot, e depois esclareceu que a ideia era se inspirar nelas. O que ficou:

- **Os clipes de lá não vêm para a Godot.** A licença é só para a Unreal (pela notícia do
  lançamento; a página da Fab não abriu para conferir). Exportar e passar pelo retarget, ou
  usá-los de guia para o gerador, é cópia. Tecnicamente seria fácil (o `rigmap` reconhece o
  esqueleto da Unreal como fonte): a trava é a licença, não a ponte.
- **Dá para tirar de lá a receita**, não o movimento: partida e parada entre parado e andando,
  a velocidade do clipe presa à da unidade, cada unidade num ponto do laço. O projeto está em
  `D:\Unreal-games\GameAnimationSample` (2.345 arquivos de animação, 1.947 deles clipes; só o
  andar são 452, em duas posturas e um por pé). Não tem clipe de zumbi nem de arma.
- **O movimento com cara de real vem de captura que possa ir para a Godot.** Ele aprovou
  testar a [100STYLE](https://www.ianxmason.com/100style/): CC BY 4.0 (uso comercial com
  crédito: `The 100STYLE Dataset - Ian Mason`), XSens a 60 quadros por segundo, um ator só,
  100 jeitos de andar, cada um com parado (`ID`), andar e correr para frente (`FW`, `FR`),
  para trás (`BW`, `BR`), de lado (`SW`, `SR`) e transições (`TR1`). Cada arquivo tem link
  próprio na página (Google Drive); `Frame_Cuts.csv` dá, em quadros a 60 por segundo, onde
  cortar a pose T do começo e do fim; `Dataset_List.csv` descreve cada jeito. Uma tomada tem
  uns 3 minutos, com o ator andando em curvas numa sala de 4 m.

**Ele reprovou a 100STYLE** no mesmo dia, ao ver dois andares dela na Zombiegirl: "horrível, o
kimodo tá bem melhor que esse cara". Eram `DragLeftLeg_FW` (braços soltos, quadril 30° virado
em relação ao caminho, laço de 1,33 s a 0,60 m/s) e `Zombie_FW` (braços esticados para frente,
1,47 s a 0,51 m/s); as duas prévias foram apagadas. Não proponha a 100STYLE de novo, nem outro
conjunto aberto de captura crua, sem ele pedir: do que foi testado para a Godot, ele põe o
Kimodo acima disto. Ele não disse o que achou ruim (o jeito do ator, o movimento duro, a
emenda): não suponha. O importador de captura ficou na ponte, sem uso.

Captura com licença de crédito: a linha vai em `--credit`, fica em `motion.json` (campo
`credit`) e aparece na tela da animação. Se o clipe for para o jogo, ela tem de ir aos créditos.

Por dentro: `ponte motion import-capture <projeto> <bvh> [--label] [--start s] [--end s]
[--loop [min max]] [--direction] [--credit]` (`pipeline.import_capture`). Não há campo na
interface nem rota na API. `blender/ponte_bl/capture.py` (sem `bpy`) converte a captura para o
formato do BVH do Kimodo e `blender/import_capture.py` grava: o original fica em
`animacoes/<id>/captura.bvh` e o convertido em `motion.bvh` (`source: "captura"`), com
`captura.json` e `captura.log` ao lado. Por ser um `motion.bvh` com os nomes do SOMA, o
retarget, o `step_stats.py` e a versão parada funcionam sem saber que é captura. O que não é
óbvio:

- O esqueleto de captura chama o osso pela junta em que ele começa (`LeftShoulder` é o braço,
  `LeftHip` a coxa): `rigmap.named_by_joint` percebe pelo cotovelo e pelo joelho.
- O tornozelo de lá fica a 11,6 cm do chão (o do SOMA, a 7): a altura do quadril em pé vai
  em `motion.json` (`stand_height`) e o retarget a recebe por `--stand-height`. Sem ela o
  personagem sai uns 5 % fora do chão.
- `Frame Time: 0.016667` dá 59,9988 quadros por segundo: a conversão trata como 60.
- O laço: a busca compara pose e velocidade no espaço do personagem e fica com o trecho mais
  curto entre os que emendam quase tão bem quanto o melhor (uma passada, não duas). O giro
  do trecho sai aos poucos e a sobra é repartida; o último quadro repete o primeiro (não o
  quadro de antes, como nos laços do Kimodo: a interface e o `step_stats.py` tratam os dois).
- Um laço que anda é virado para o caminho ir reto para frente (ou para `--direction`). A
  direção automática escolhe entre quatro, não oito: num andar torto o quadril fica 30° fora
  do caminho, e a escolha entre oito o tomou por diagonal.
- Não há trava de pé: o pé de apoio deslizou de 4 a 8 cm/s nos dois andares testados (na
  origem, 2 a 5).

## O jogo na Godot

O jogo é o ZombiHordeZ, em `D:\Godot\zombi-horde-z` (RTS, Godot 4.7.2, GDScript). Ele tem
`CLAUDE.md` e `AGENTS.md` próprios, mais rígidos que este: tarefa vem do usuário e fica
registrada em `docs/`, QA é só dele (não rodar jogo, cena nem teste), skills obrigatórias
(`godot-master`, `godot-genre-rts`) e edição pelo MCP `godot-ai` com o editor aberto. Leia os
dois antes de mexer lá. Em 07/10/2026 o usuário decidiu levar a **Zombiegirl** primeiro; os
documentos de lá ainda citam o zumbi1 (Sprint 7, ragdoll).

O que o jogo tem hoje e o que isso pede daqui:

- O zumbi é a Zombiegirl (`scenes/units/zombie_girl.tscn`), que em 07/10/2026 tomou o lugar do
  cubo na arena, na missão e na onda, a pedido do usuário (registro em `docs/SPRINTS.md` de lá).
  O cérebro é o `ZombieBrain` (estados parado, perseguindo, atacando, morto). Não existe estado
  de "ouviu barulho": virar para o som ainda não tem onde entrar.
- Quem move o corpo é a navegação do jogo (`UnitMover`, soldado a 3,5 m/s). O andar tem de tocar
  **parado no lugar**. Há dois caminhos, e o segundo é o que vale para pacotes grandes:
  - `ponte retarget <projeto> <animação> --in-place` cria a prévia e o clipe sai como
    `<nome>_parado`. É o da Zombiegirl (`walking_parado`, 0,61 m/s na altura do arquivo).
  - Tirar o deslocamento na Godot, ao carregar (`ClipTravel`, usado pelo `SoldierModelView`).
    É o do Soldado, com 32 clipes de locomoção: não crie 32 prévias "parado" para isso.
- A frente da unidade no jogo é −Z e o personagem sai olhando para +Z: o modelo entra girado 180°.
- O Soldado está no jogo desde 07/10/2026 (`art/characters/soldado/`, tarefa em
  `docs/tasks/SOLDADO_ANIMADO.md` de lá, em validação): parado, mirando, andar / correr /
  disparada em oito direções e os mesmos estados agachado, por um `AnimationTree` montado em
  código. Os nomes dos clipes vêm do texto da prévia (`walk forward left` →
  `walk_forward_left`) e o código do jogo depende deles: não renomeie essas prévias. Medido no
  arquivo, na altura dele (1,0 m): andar 1,03 m/s, correr 2,59, disparada 3,88, andar agachado
  1,10. O modelo não tem arma na mão nem clipes de tiro e de morte; os dois de virar 90° ficaram
  sem uso. O modelo está no lugar da cápsula: `unit_placeholder.tscn` (o soldado) e
  `protagonist.tscn` instanciam `scenes/units/soldier_model.tscn`, o que vale para a arena e a
  missão. O usuário quer o personagem **dentro do jogo**, no lugar da forma provisória, e não
  numa cena de vitrine ("é pra vc colocar no lugar dos soldados fakes foi por isso que pedi").
- No projeto do jogo costuma haver outra sessão trabalhando ao mesmo tempo, no mesmo editor.
  Não troque nem salve cena pelo MCP; confira datas dos arquivos e `editor_state` antes. Ao
  alterar uma cena que já existe, grave o arquivo inteiro de uma vez: edições em pedaços
  paralelos já foram barradas pela metade pela permissão e deixaram a cena quebrada.
- Encerrar um personagem (`ponte close`) e exportar o resultado por outro caminho são barrados
  pela permissão desta sessão, mesmo com a ordem do usuário. Peça logo no começo que ele clique
  em **Encerrar personagem** (aba Personagem): para ele, isso é "exportar".

Conferido em 07/10/2026 com um encerramento de ensaio numa biblioteca descartável e um projeto
Godot de rascunho (`D:\Godot_v4.7.2-stable_win64_console.exe --headless --path <pasta> --import`,
depois `--script`): o GLB do resultado importa sem erro, com 63 ossos (`mixamorig_Hips`...),
texturas e um clipe por prévia (`zombie_idle`, `walking_parado`). Nenhum clipe sai marcado como
laço: isso se liga na Godot. O nó `Armature` chega com escala 0,01 e rotação de 90° em X,
herdadas do FBX do Mixamo; funciona para animar, mas corpo físico sob nó com escala costuma dar
problema, então confira antes do ragdoll. A Zombiegirl mede 2,07 m; o soldado do jogo, 1,8 m.

## Unreal 5

Em 08/10/2026 o usuário pediu uma opção para o esqueleto da Unreal 5 e disse, na mesma frase,
que **por enquanto o jogo continua na Godot**. A opção existe e é desligada por padrão: não
ligue em personagem dele nem leve nada para a Unreal sem ele pedir. Ele tem a Unreal 5.8.3 em
`D:\EpicGames\UE_5.8` e um projeto `D:\Unreal-games\ZombiHordeZ`, criado nesse dia (em branco)
e aberto no editor: não mexa nele.

- A caixa *Gerar também para a Unreal 5* (aba Personagem, no quadro Resultado) grava
  `asset.unreal`; `ponte close <id> --unreal` faz o mesmo. No encerramento seguinte sai
  `resultado/unreal5/SK_<nome>.fbx` (`final.unreal`). O resultado de sempre não muda, e se a
  conversão falhar ele sai assim mesmo, com um aviso.
- `blender/ponte_bl/unreal.py` troca a armature pela do Mannequin (`ue5_mannequin.json`, tirado
  do `SK_Mannequin` da 5.8), com as juntas onde estavam, e regrava os clipes nela: cada osso
  novo anda preso ao osso de origem. A correção de descanso é a do retarget
  (`rigmap.build_plan`). `convert` devolve `check` (quanto a malha e as juntas mudaram).
- A Unreal cobra duas coisas do FBX, achadas importando de verdade:
  - **centímetros sem escala em objeto**: a escala do objeto da armature vira escala do osso
    `root` (100 com a armature em metros). `FBX_SCALE_UNITS` não resolve.
  - **pose de vinculação exata**: com o ruído de 32 bits do Blender, nessa escala, o SDK do FBX
    dá a pose por inválida e a Unreal usa o primeiro quadro da primeira animação como pose de
    referência (aviso "invalid bind poses... rebind using the time zero pose"). O FBX normal de
    personagem com armature em 0,01 (todo o que vem do Mixamo) tem esse defeito na Unreal.
    `unreal.clean_bind_pose` regrava as matrizes ortonormais, com o leitor e o gravador de FBX
    do próprio Blender (`io_scene_fbx.parse_fbx` e `encode_bin`).
- O GLB não serve para isto: a Unreal põe a troca de eixos (90° em X) no osso `root`.
- A Unreal chama cada animação de `<arquivo><tomada>`, sem separador: por isso as faixas do
  FBX se chamam `_<clipe>`. Com uma tomada só, o nome vira `SK_<nome>_Anim`.
- Para conferir: `uv run python tests/check_unreal.py --engine
  D:\EpicGames\UE_5.8\Engine\Binaries\Win64\UnrealEditor-Cmd.exe` importa num projeto de
  rascunho, sem interface (uns 15 s, mesmo com o editor dele aberto). Por dentro é
  `-run=pythonscript` com `tests/ue_import.py`; com `-nullrhi`, exportar malha pela Unreal
  derruba o processo. Sem `--engine` o teste confere o FBX só pelo Blender
  (`blender/check_unreal_fbx.py`).
- Conferido em 08/10/2026 com o boneco de teste e com uma cópia descartável do sobrevivente
  (581 mil triângulos, 4 texturas): a Unreal importou malha, texturas, 71 ossos e a animação,
  sem avisos. Tudo por número, sem interface. Não testado: o arquivo visto no editor e o uso
  dentro de um projeto. Os limites para quem usa estão em **Unreal 5** no `README.md`.

## Rig automático

`blender/ponte_bl/autorig.py` monta o esqueleto do Mixamo a partir de 8 marcadores e calcula
os pesos numa cópia da malha refeita por voxels. As proporções foram calibradas com um único
personagem rigado pelo Mixamo; `tests/check_autorig.py <fbx do Mixamo>` compara junta a junta.
`?rig` no endereço (`/?rig#asset/<id>`) abre direto na tela de marcadores.

Em 09/10/2026 o usuário achou ruim o rig de um personagem do Meshy (mãos e ombros fora do lugar)
e pediu para o rigador "sempre entregar melhor". O que mudou em `autorig.py`:

- **Dedos no eixo da própria mão** (`_hand_frame`): o gabarito dos dedos era posto na reta do
  antebraço; agora o eixo e o plano da mão são medidos nos vértices além do pulso. Sem malha
  bastante, ou se o medido não parece uma mão, vale a regra antiga.
- **Pulso estimado na seção mais estreita do braço** (`_wrist_fraction`), medida em largura e
  profundidade; o cotovelo estimado fica a 55 % do caminho até ele.
- **Meia largura mínima do ombro: 8,5 % da altura** (`SHOULDER_MIN_HALF_WIDTH`, era 6 %). O ombro
  continua saindo da continuação do antebraço; com o cotovelo um pouco dobrado essa reta aponta
  para o pescoço, e é este limite que o segura.
- **Centro do corpo** (`Body.x0`): a do meio entre a mediana dos vértices, o meio da cabeça e o
  meio dos pés. Só a mediana era puxada 5 cm por um coldre de um lado.
- **Ponta da mão só acima do joelho**: uma bota larga já tinha sido tomada pela mão.

Medido com `check_autorig.py` na Zombiegirl e no Swat (antes → depois, em % da altura): dedos,
média de 2,4–2,8 para 1,3–1,5; braços, média de 1,35–1,45 para 1,0; marcador do pulso, de
0,7–2,8 para 0,1–0,3. O teste continua dando `FALHA` como dava antes, por `Spine2` (3,87 %) e
`LeftToeBase` (3,90 %), que não foram mexidos.

**O que não deu certo:** medir a direção do braço na malha, acima do cotovelo, para achar o
ombro. No Swat o pior caso foi de 3,0 % para 5,4 %; foi retirado. Não tente de novo sem um
jeito de separar o braço do tronco e do deltoide. O original de antes dessas mudanças está em
`D:\Blender-Animacoes\Survivors_CortarMadeira\rig_alternativo\autorig_original_2026-10-09.py`.
Nada disso foi testado pela tela de marcadores.

## Testes

Não há pytest. Cada `tests/check_*.py` roda sozinho (`uv run python tests/<arquivo>`), imprime
`ok` ou `FALHA` por caso e sai com código 1 se algo falhou.

| Teste | Precisa de | Acervo real |
|---|---|---|
| `check_rigmap.py`, `check_migration.py`, `check_fila.py` | só Python | não toca |
| `check_retarget.py`, `check_textures.py` | Blender | não toca (pasta temporária) |
| `check_chain.py` | Blender (o Kimodo é trocado por um dublê) | não toca (`PONTE_DATA` próprio) |
| `check_mixamo.py` | Blender | não toca (`PONTE_DATA` próprio) |
| `check_capture.py` | Blender | não toca (`PONTE_DATA` próprio) |
| `check_engine.py` | Blender (o kimodo.cpp é trocado por um dublê) | não toca (`PONTE_DATA` próprio) |
| `check_ardy.py` | Blender (o script do ARDY é trocado por um dublê) | não toca (`PONTE_DATA` próprio) |
| `check_meshy.py` | Blender (a rede é trocada por um dublê: não fala com o Meshy) | não toca (`PONTE_DATA` próprio) |
| `check_bake.py` | Blender, Node e `web/node_modules` | não toca |
| `check_close.py [--keep <pasta>]` | Blender | não toca (`PONTE_DATA` próprio) |
| `check_unreal.py [--engine <UnrealEditor-Cmd.exe>] [--keep <pasta>]` | Blender; com `--engine`, a Unreal 5 | não toca (`PONTE_DATA` próprio) |
| `check_autorig.py <fbx do Mixamo>` | Blender e um FBX rigado pelo Mixamo | não toca |
| `check_script_dry.py` | Docker ligado, Blender e o Kimodo original instalado (não está desde 08/10/2026) | usa `data/tmp` e ocupa uma vaga do Kimodo |
| `check_terminal.py` | só Python e Windows (sobe um servidor na porta 8767; leva uns 2 min) | não toca (`PONTE_DATA` próprio) |

`check_adjust.mjs` e `check_props.mjs` são chamados pelo `check_bake.py`, não à mão.

Ao mexer na vaga ou na fila do Kimodo, rode `check_fila.py`; no roteiro passo a passo
(`pipeline.animate`), `check_chain.py`.

Ao mexer no retarget, no mapeamento ou no encerramento, rode
`uv run python tests/check_rigmap.py`, `tests/check_retarget.py` e `tests/check_textures.py`;
para o encerramento, `tests/check_close.py` (`blender/build_result.py` traz a ação de cada
prévia do `.blend` dela, então o resultado tem de bater com as prévias); para o arquivo da
Unreal 5, `tests/check_unreal.py`; para a captura em BVH (e o mapeamento de um esqueleto que
é a fonte da animação), `tests/check_capture.py` e `tests/check_mixamo.py`.
Para ver uma prévia sem navegador, cada uma tem `data/projects/<projeto>/previas/<id>/sheet.png`
(tira de 6 quadros); `blender/render_sheet.py` gera outras vistas (`--view side|front`).

Ao mexer no terminal da tela (`ponte/terminal.py`, as rotas dele), rode `tests/check_terminal.py`.

A interface não tem teste automático. Botão novo, teste com clique de verdade antes de
entregar: `node tests/ui_click.mjs <url> <pasta> <passos...>` abre a página no Edge, clica
(`clicktext:<seletor>|<texto>`), escolhe arquivo num campo de envio (`file:<seletor>|<arquivo>`,
é assim que se prova o botão do Mixamo: `file:#mixamo-input|<animação.fbx>`), lê o relógio do
visualizador (`time`), avalia expressões (`eval:`), tira retratos (`shot:<nome>`) e mostra os
erros da página. Na tela nova o endereço é `#p/<projeto>` ou `#p/<projeto>/<animação>`. O que
grava (importar, apagar) prove num segundo servidor com acervo descartável (`PONTE_DATA` e
`uv run ponte serve --port 8766`), não no acervo dele. Já entreguei botões conferidos só por
captura parada, e o usuário é que achou os problemas. Para uma captura simples da tela antiga,
o Edge headless (`/antiga/#asset/<id>`, `#result/<id da prévia>` ou `#final/<id do projeto>`):

```bash
msedge --headless=new --use-angle=swiftshader --enable-unsafe-swiftshader \
  --window-size=1500,950 --virtual-time-budget=60000 --screenshot=out.png \
  "http://127.0.0.1:8765/antiga/#result/<id>"
```
