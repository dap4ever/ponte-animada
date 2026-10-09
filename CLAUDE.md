# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

PonteAnimada: ponte entre o Blender, o Kimodo e a validação humana de personagens e animações 3D.
O fluxo de uso, a lista completa da CLI e os limites conhecidos estão no `README.md`. Aqui fica
o que muda como você trabalha.

## Estado em 09/10/2026: nenhum gerador ligado à ponte (o ARDY está instalado à parte)

No fim do dia 08/10/2026 o usuário mandou desinstalar o Kimodo original e o kimodo.cpp e
manter só a ponte ("apague tudo deixe somente a ponte"), para o caso de querer o Kimodo de novo.
Ele vinha de achar a qualidade insuficiente e estava olhando o MotionBricks (irmão do Kimodo,
em tempo real; o que a NVIDIA publicou move um robô, não um humano, e não gera clipe a partir
de texto).

- **Não há como gerar animação agora.** `ponte gen` e a tela recusam com o motivo; a barra de
  cima mostra "Nenhum gerador de animação instalado" e a pergunta do gerador não aparece. O
  resto funciona: importar (Mixamo, captura), validar, ajustar, encerrar.
- O que saiu: `D:\kimodo.cpp`, `D:\kimodo.cpp-go`, `~/kimodo` e os quatro modelos em
  `~/.cache/huggingface/hub` no Ubuntu (o `token` do Hugging Face ficou), a imagem `kimodo:1.0`
  e o cache de construção no Docker, e `C:\Users\dap_p\kimodo-setup`.
- O que ficou: todo o código da ponte para os dois geradores, o guia e os scripts de instalação
  em `docs/kimodo-setup/` (o guia é `GUIA-KIMODO.md`), Docker Desktop, Ubuntu, Blender, Visual
  Studio. Para voltar com o original: seguir o guia e pôr `installed = true` em `[kimodo]` no
  `ponte.toml`. Para o kimodo.cpp: "Dois geradores", no `README.md`.
- **O Docker dele tem outro projeto**, o `portalimobiliaria` (banco Postgres e Redis, com
  volumes de dados). Nunca rode limpeza geral (`docker system prune`, "Purge data"): só o que
  for do Kimodo, pelo nome.
- **Os discos virtuais do Docker e do Ubuntu moram no E:** desde 08/10/2026, a pedido dele
  ("eu preciso que o docker grave e use o banco no E:"): `E:\Docker\disk\docker_data.vhdx`
  (79 GB, quase vazio por dentro) e `E:\wsl\Ubuntu\ext4.vhdx` (20 GB). O Ubuntu foi movido com
  `wsl --manage Ubuntu --move`; o do Docker, copiando o arquivo e pondo
  `"CustomWslDistroDir": "E:\\Docker"` em `%APPDATA%\Docker\settings-store.json` (nesta versão,
  4.94, o Docker procura o disco em `<pasta>\disk\`, sem `DockerDesktopWSL`; com a pasta errada
  ele cria um disco vazio e os volumes "somem"). Há uma cópia dos dados do `portalimobiliaria`
  daquele dia em `E:\backup-docker-2026-10-08`. Coisa grande vai para o E: (1,7 TB livres, disco
  rígido comum, mais lento).
- Apagar arquivo no C: é barrado pela permissão quando o mesmo comando cita `C:\Program Files`
  ou um `C:\...` solto: faça o `Remove-Item` sozinho, com o caminho exato do arquivo.
- **ARDY** (NVIDIA, julho de 2026, `github.com/nv-tlabs/ardy`): **instalado em 08 e 09/10/2026
  no Ubuntu, em `~/ardy`** (ambiente em `.venv`, Python 3.11, PyTorch com CUDA; modelos em
  `~/.cache/huggingface/hub`, 17 GB). **Ainda não está ligado à ponte**: `ponte gen` continua
  recusando. Os scripts ficam em `docs/ardy-setup/` e rodam de dentro do Ubuntu
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
    codificador como serviço no ar: sozinho ele tenta pô-lo na placa. **A ponte ainda não lê
    essas sessões**, então o que ele gera ali não chega à Zombiegirl nem à Godot.
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
    `docs/ardy-setup/ardy-zumbi-andando.txt`. **Falta o veredito dele sobre a qualidade**; só
    depois disso vale adaptar a ponte.
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

## Seu papel

Você gera as animações pelo backend (`uv run ponte ...`); o usuário valida na interface.
O retorno dele chega por `uv run ponte status`: prévias `[REPROVADO]` vêm com a nota
dizendo o que corrigir. Leia antes de gerar de novo.

Uma animação é um **roteiro**: passos em sequência, num clipe só, cada passo partindo dos
últimos quadros do anterior. Não gere ações relacionadas como pedidos separados: o usuário
reprovou isso (os clipes não se ligam e o personagem "teletransporta").

O roteiro é feito **um passo de cada vez**, por decisão do usuário: gera-se um passo, ele é
entregue e conferido, e só então vem o próximo, em cima do que foi entregue (`ponte gen ...
--continue <animação>`). Não mande vários passos num pedido só. Cada roteiro é um clipe: ao
continuar, a prévia do clipe menor sai da lista e a animação dele fica guardada, para dar para
refazer o passo (`--continue <anterior> --replace <a que saiu errada>`). A interface faz o
mesmo e trava o passo seguinte enquanto o atual não chega.

### Quando o usuário descreve uma animação

Ele descreve em português o que quer e você entrega a prévia pronta para validar. O pedido
costuma chegar pelo botão **Pedir ao Claude** da interface, que abre a conversa com o contexto
já escrito (`PonteAnimada: animação para o projeto "<nome>" (id <id>).` e, se houver,
`Prévia aberta: <id>`), seguido do que ele quer. As animações vão para um jogo na **Godot** e
ele quer resultado fluido, de nível profissional.

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
- O kimodo.cpp ficava em `D:\kimodo.cpp` (`[kimodo_cpp]` no `ponte.toml`; a pasta foi apagada
  na desinstalação de 08/10/2026), compilado só para o processador, sem Vulkan (a máquina não
  tem o Vulkan SDK). Medido: uns 30 s para carregar o
  modelo e 1,8 s por passo de difusão num clipe de 5 s; com os 100 passos da ponte, 3 min e
  meio. Com o Vulkan SDK instalado e recompilando, usaria a RTX 3060: não foi feito.
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
andamento (já aconteceu: uma geração dele foi interrompida assim).

- Só o código em `ponte/` exige reinício. Mudanças em `blender/` e `web/` valem na hora
  (a interface pede Ctrl+R).
- Para reiniciar: `scripts\parar.ps1` (recusa com job ativo; não use `-Force` por conta
  própria) e depois `uv run ponte serve` em segundo plano.
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
uv run python tests/check_rigmap.py   # um teste é um script: rode o arquivo (ver Testes)
npm install --prefix web              # só numa pasta nova: o three.js é servido de web/node_modules
```

Não há build, lint nem formatador no fluxo. O `[tool.ruff]` do `pyproject.toml` só fixa 120
colunas, o ruff não está instalado e o código tem linhas maiores que isso: não reformate
arquivos inteiros.

## Arquitetura

Três ambientes de Python que não se importam entre si; conversam por argumentos e arquivos JSON:

| Onde roda | Código | O que tem à mão |
|---|---|---|
| venv do `uv`, no Windows | `ponte/` | fastapi, biblioteca padrão |
| Python embutido do Blender | `blender/*.py` (entradas) e `blender/ponte_bl/` (biblioteca) | `bpy`, numpy |
| container do Kimodo, no WSL | `kimodo_scripts/gerar.py` | torch, `kimodo` |

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
  saem por `/files/...`.
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
Ele baixa o FBX de lá (não há como baixar por ele: exige a conta Adobe) e importa em
**Animações Mixamo**, na aba Prévias do projeto, ou `ponte motion import-fbx <projeto> <fbx>`.
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
| `check_bake.py` | Blender, Node e `web/node_modules` | não toca |
| `check_close.py [--keep <pasta>]` | Blender | não toca (`PONTE_DATA` próprio) |
| `check_unreal.py [--engine <UnrealEditor-Cmd.exe>] [--keep <pasta>]` | Blender; com `--engine`, a Unreal 5 | não toca (`PONTE_DATA` próprio) |
| `check_autorig.py <fbx do Mixamo>` | Blender e um FBX rigado pelo Mixamo | não toca |
| `check_script_dry.py` | Docker ligado, Blender e o Kimodo original instalado (não está desde 08/10/2026) | usa `data/tmp` e ocupa uma vaga do Kimodo |

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

A interface não tem teste automático. Botão novo, teste com clique de verdade antes de
entregar: `node tests/ui_click.mjs <url> <pasta> <passos...>` abre a página no Edge, clica
(`clicktext:<seletor>|<texto>`), lê o relógio do visualizador (`time`), avalia expressões
(`eval:`) e mostra os erros da página. Já entreguei botões conferidos só por captura parada, e
o usuário é que achou os problemas. Para uma captura simples, o Edge headless
(`#asset/<id>`, `#result/<id da prévia>` ou `#final/<id do projeto>` no endereço):

```bash
msedge --headless=new --use-angle=swiftshader --enable-unsafe-swiftshader \
  --window-size=1500,950 --virtual-time-budget=60000 --screenshot=out.png \
  "http://127.0.0.1:8765/#result/<id>"
```
