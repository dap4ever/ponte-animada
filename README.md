# PonteAnimada

Ponte entre o **Blender**, o **Kimodo** e **você**: os personagens 3D entram aqui (com ou
sem esqueleto), as animações são geradas no Kimodo e aplicadas neles pelo Blender, e você
valida cada uma nesta interface. Quando o personagem está completo, você o encerra e sai o
resultado: um arquivo só, com todas as animações.

## Abrir

Dê dois cliques no atalho **PonteAnimada** da Área de Trabalho (ou em `Abrir-PonteAnimada.cmd`).
Ele sobe o servidor local e abre a interface numa janela própria. Para encerrar o servidor,
use `Parar-PonteAnimada.cmd` (ele se recusa a parar enquanto houver animação sendo gerada
ou aplicada). Se mover a pasta do projeto, rode `scripts\criar-atalho.ps1` para refazer o atalho.

## Fluxo

1. **Novo projeto** — cada personagem enviado vira um projeto separado: FBX, GLB, BLEND, OBJ
   ou um ZIP com o modelo e as texturas (arraste para a janela). O Blender faz o laudo: tipo
   de rig, ossos reconhecidos, pose de descanso, escala, pesos, texturas. Só personagem com
   laudo *Pronto para animar* recebe animação. Se veio sem esqueleto, o laudo diz *Precisa de
   rig* e dá para rigar aqui (veja abaixo).
2. **Pedir animação** — monte o roteiro em inglês na barra de baixo. O Kimodo gera, o Blender
   aplica no personagem do projeto aberto e a **prévia** aparece na lista do projeto.
3. **Validar** — assista no visualizador (Espaço pausa, setas avançam quadro a quadro,
   *Ossos* mostra o esqueleto) e clique **Aprovar** ou **Reprovar**. As notas da reprovação
   são o que quem gera as animações lê para corrigir.
4. **Encerrar o personagem** — é só aqui que o **resultado** existe. Veja abaixo.

## Projetos, prévias e resultado

Cada upload de personagem cria um projeto, e tudo que nasce dele fica dentro dele: as
animações, as prévias, os acessórios. A interface abre na tela de **Projetos**; abrir um
projeto leva a uma tela só dele, com as abas *Prévias*, *Animações* e *Personagem* (o botão
**←** volta aos projetos). O **×** no canto do cartão exclui o projeto, com confirmação: vão
embora o personagem, as animações, as prévias e o resultado dele. Uma animação é sempre gerada para o personagem do projeto aberto
e não é usada em outro.

A **prévia** é a animação aplicada no personagem, para você validar. Ela não é a entrega.

O **resultado** só sai quando você **encerra o personagem** (botão *Encerrar personagem* na
aba Personagem, ou `uv run ponte close <projeto>`). Aí todas as prévias que você não reprovou
viram clipes de um arquivo só — `<nome>.glb`, `<nome>.fbx` e `<nome>.blend`, cada um com o
personagem, as texturas, os acessórios e todas as animações. O que sai é exatamente o que
foi validado: as animações vêm das prévias, sem recalcular. Reprovadas ficam de fora; as
que ainda não foram validadas entram, e o aviso de confirmação diz quantas são.

O resultado aparece **fora da pasta do projeto, como atalho**: na seção **Resultados** da
tela de projetos (e no alto da tela do projeto encerrado) e, no disco, em
`data\resultados\<Nome do personagem>.lnk`, que abre a pasta com os arquivos. O projeto não fica travado: se mexer depois (animação nova, prévia reprovada, arma
em outra posição), o resultado aparece como *desatualizado* e basta encerrar de novo.
*Desfazer o encerramento* apaga o resultado e o atalho, e deixa o projeto como estava.

**Para a Unreal 5**: marque *Gerar também para a Unreal 5* antes de encerrar (ou
`uv run ponte close <projeto> --unreal`). O resultado ganha `unreal5\SK_<nome>.fbx`: o mesmo
personagem e as mesmas animações, no esqueleto do Mannequin (`root`, `pelvis`, `spine_01`...),
em centímetros. Arraste o arquivo para o Content Browser: entram a malha, o esqueleto e uma
animação por clipe, com o nome `SK_<nome>_<clipe>`. A opção fica guardada no personagem, e
ligá-la ou desligá-la deixa o resultado desatualizado. O que sai para a Godot não muda.
Detalhes em [Unreal 5](#unreal-5).

```
data\projects\<projeto>\
    personagem\    o arquivo enviado, texturas, rig, acessórios e o laudo
    animacoes\     o que o Kimodo gerou (BVH no esqueleto SOMA 77)
    previas\       cada animação aplicada no personagem (GLB para ver, BLEND para conferir)
    resultado\     só depois de encerrado: <nome>.glb, .fbx e .blend com todas as animações
        unreal5\   com a opção ligada: SK_<nome>.fbx, no esqueleto do Mannequin da Unreal 5
data\resultados\    um atalho por personagem encerrado, apontando para o resultado\ dele
```

## Rigar aqui (padrão Mixamo)

Para personagem que chega sem esqueleto — ou que o Mixamo recusou. No personagem, clique
**Rigar este personagem**: o Blender estima 8 marcadores (queixo, virilha, pulsos, cotovelos,
joelhos) e a vista vira de frente, como no Mixamo. Arraste cada círculo para o lugar certo
(*Simetria* espelha um lado no outro) e clique **Rigar**. Sai um esqueleto com os mesmos
nomes e a mesma hierarquia do Mixamo (`mixamorig:Hips`…), com 65 ossos ou 25 sem dedos, e os
pesos calculados. **Testar com caminhada** aplica uma caminhada de exemplo para ver a malha
deformando. O arquivo enviado fica guardado; *Rigar de novo* parte sempre dele.

Os braços precisam estar afastados do corpo (T-pose ou A-pose) e o personagem de frente,
como o Mixamo também exige. Os pesos são calculados numa cópia fechada da malha e
transferidos para a original, o que funciona em malha aberta ou gerada por IA.

Para comparar o rigador com um personagem rigado pelo próprio Mixamo:
`uv run python tests/check_autorig.py <arquivo_do_mixamo.fbx>`.

## Roteiro: uma animação com começo, meio e transições

Uma animação não é uma frase solta, é um **roteiro**: passos em sequência, num clipe só. O
roteiro é escrito **um passo de cada vez**: você escreve o passo, ele é gerado e entregue, você
vê a prévia e só então escreve o próximo, em cima do que foi entregue.

- **Passo**: a ação do trecho, em inglês (`stands still, breathing`, depois `walks forward
  slowly`…), com os segundos dele. O Kimodo gera cada passo partindo dos últimos quadros do
  anterior, então há **transição** entre eles e o clipe continua um só. Pedidos separados não
  se ligam: trocar de um para outro teletransporta o personagem.
- **O próximo passo fica travado** enquanto o atual não é entregue. Com a prévia aberta, o
  roteiro mostra os passos já entregues e o campo do passo seguinte; **nova animação** começa
  outra, do zero.
- **Refazer** (no último passo entregue): gera esse passo de novo, partindo do fim do anterior.
  O que veio antes fica igual, e a versão antiga só é apagada quando a nova fica pronta.
- **Um clipe por roteiro**: quando um passo novo chega, a prévia do clipe menor sai da lista
  (o novo a contém). A animação menor fica guardada na aba *Animações*: é dela que se parte
  para refazer o passo.
- **Contexto** (opcional): quem é e o que carrega (`A zombie`). É repetido em todo passo — o
  Kimodo não lembra do prompt anterior — e não gera trecho próprio.
- **Em laço**: o passo termina na pose em que começou, para o jogo tocar em repetição (o
  ocioso, o andar). Precisa de um passo antes dele, com o personagem já na postura, e de pelo
  menos 2 s; num passo que anda, escolha também a direção. No roteiro, **↻ laço** toca só
  aquele passo em repetição, como o jogo vai tocar.
- **Força do gesto**: quanto o Kimodo obedece ao texto. Se o passo saiu parecido com o
  anterior, sem o gesto pedido, refaça com *gesto marcado* ou *exagerado*.
- **Direção e ritmo**, por passo: ele anda em linha reta para frente, trás, lados ou
  diagonais. Com *corpo para frente* ele não vira — anda de lado ou de ré. O texto precisa
  concordar com a direção: o Kimodo se perde quando o texto diz uma coisa e a trajetória outra.
- **Desenhar caminho**: clique pontos no chão do visualizador e ele passa por eles no passo
  que você está escrevendo. O caminho sai de onde o personagem está no começo do passo: da
  origem numa animação nova, do fim do clipe numa continuação. Vale para a geração: uma
  animação já pronta não muda de trajeto.
- **Pedir ao Claude** (abaixo de *Gerar passo*): abre uma conversa do Claude Code no VS Code
  com o projeto e a prévia aberta já escritos na caixa. Você completa em português com a
  animação que quer; o roteiro em inglês, a geração e a prévia ficam por conta dele. O VS Code
  precisa estar com a pasta do PonteAnimada aberta: o link abre na janela que estiver em foco.
- **Ações**: no alto da lista de prévias ficam as ações do personagem, uma por linha (parado,
  andando, ataque…). Clicar numa abre a prévia que a tem e toca só ela, em repetição. As
  marcadas com ★ são as principais; as outras ficam recolhidas em *outras ações*.
- **Nomes**: o roteiro e cada passo podem ter um nome curto, em português (*renomear* no alto
  do painel, *nome* em cada passo, ou o campo *nome do passo* ao escrever). É o que aparece
  na lista de prévias e na lista de passos, no lugar do texto em inglês.
- Na prévia, a lista **Roteiro** fica no alto do painel: clicar num passo leva ao quadro em
  que ele começa, e **▶** toca só aquele passo, em repetição.
- **Parado** (no visualizador) mostra qualquer prévia sem o deslocamento, só para ver.
  *Criar versão parada* cria outra prévia assim, para a engine mover o personagem; as duas
  versões entram no resultado, a não ser que você reprove uma.

## Animações do Mixamo

Para as ações que o Mixamo já tem prontas (parado, andar, ataque…), não é preciso gerar: baixe
a animação de lá em FBX e, no projeto do personagem, na aba *Prévias*, clique **Importar FBX**
em **Animações Mixamo** (dá para escolher vários de uma vez). Cada arquivo é aplicado no
personagem do projeto e vira uma ação dele, com o nome do arquivo: aparece em **Ações**, é
validada como as outras e sai no resultado quando o personagem é encerrado.

A animação passa pelo mesmo retarget das do Kimodo, então serve em qualquer personagem do
projeto, tenha ele ou não o esqueleto do arquivo, e tanto faz baixar com ou sem a malha
(*With Skin* / *Without Skin*). Tudo é amostrado a 30 quadros por segundo. Soltar um FBX na
janela com um projeto aberto pergunta se ele é uma animação do Mixamo ou um personagem novo.

Pela linha de comando: `uv run ponte motion import-fbx <projeto> "Zombie Idle.fbx"`.

## Capturas de movimento (BVH)

Captura de movimento pronta, em BVH de qualquer esqueleto humanoide (XSens, conjuntos abertos
como a [100STYLE](https://www.ianxmason.com/100style/)), entra pela linha de comando:

```powershell
uv run ponte motion import-capture <projeto> DragLeftLeg_FW.bvh --label "Andar arrastando a perna" `
    --start 7.15 --end 168.55 --loop --credit "The 100STYLE Dataset - Ian Mason (CC BY 4.0)"
```

- `--start` e `--end` recortam a tomada, em segundos do arquivo (quadro ÷ quadros por segundo).
- `--loop` fica só com o melhor laço do recorte e o fecha: procura o trecho em que o fim mais
  repete o começo (num andar, uma passada), tira aos poucos o giro que o ator fez nele e
  reparte pelo trecho a diferença que sobra. `--loop 2.4 3.4` pede outra duração, em segundos
  (padrão: de 0,6 a 4). Um laço que anda sai reto, na direção de `--direction` (padrão: a mais
  próxima entre frente, lados e trás).
- `--credit` guarda o crédito que a licença do arquivo pede; ele aparece na tela da animação.

A captura vira uma ação do personagem, como as do Mixamo, e aparece em **Capturas de
movimento**, na aba *Prévias*. Na pasta da animação ficam o arquivo como veio (`captura.bvh`)
e o convertido (`motion.bvh`: nomes do SOMA 77, centímetros, 30 quadros por segundo), que é o
que o retarget e as medidas (`step_stats.py`) leem. Ainda não há campo na interface para isto.

## Ajustar a pose

Quando a animação é boa mas um braço ou a mão ficou no lugar errado, no painel da prévia
escolha a parte do corpo em **Ajustar pose**: aparece um manipulador de rotação no osso, como
no Blender. O ajuste vale para a animação inteira e é gravado na prévia ao salvar.

## Arma e acessórios

Em **Acessórios** (no personagem ou numa prévia), envie o arquivo da arma, escolha o osso
que a carrega (mão direita, costas…) e posicione com *Mover*, *Girar* e *Escala*. O acessório
pertence ao personagem: acompanha todas as animações dele e sai junto no resultado.
Prévias feitas antes de mexer na posição avisam que estão desatualizadas.

## Texturas

O personagem aparece texturizado no visualizador, nas prévias e no resultado (GLB, FBX, BLEND).

- **Embutidas no arquivo** (GLB; FBX com mídia embutida; BLEND com recursos empacotados):
  não precisa fazer nada.
- **Em arquivos separados**: selecione o modelo **junto com as texturas**, ou arraste a
  **pasta inteira** para a janela — as subpastas são mantidas. Dá também para acrescentar
  depois, com *Adicionar texturas* na tela do personagem (ou soltando as imagens com ele aberto).
- **Modelo que não referencia as texturas**: elas são aplicadas pelo nome do arquivo, que
  precisa conter o nome do material e o papel — `Corpo_BaseColor.png`, `Corpo_Normal.png`,
  `Corpo_Roughness.png`, `Corpo_Metallic.png`. Se o modelo tem um material só, basta o papel.

O laudo diz o que foi encontrado, o que faltou e o que foi deduzido. Um ajuste é automático:
material marcado como transparente cuja textura tem o canal alfa todo opaco volta a ser opaco
(senão o personagem renderiza "falhado", com faces de trás aparecendo na frente).

Prévias feitas antes de as texturas chegarem não mudam sozinhas: use *Refazer retarget*.

## Regras fixas do Kimodo

Estão travadas no código (`ponte/config.py` e `ponte/kimodo.py`), não em configuração:

- **Sempre o mesmo esqueleto**: SOMA 77, modelo `Kimodo-SOMA-RP-v1.1`. Todo BVH que entra
  é conferido contra a assinatura desse esqueleto e recusado se for diferente.
- **Um pedido de cada vez**: nunca duas gerações ao mesmo tempo, para não sobrecarregar a
  máquina. O que chega com outro gerando espera na fila e entra na ordem em que foi pedido,
  valendo entre a interface e a linha de comando. As variações de um pedido saem uma depois
  da outra, dentro da vez dele.

O Kimodo liga sozinho quando você pede uma animação (na primeira vez do dia o text encoder
leva uns 5 minutos carregando). Ligado, ele ocupa ~17 GB de RAM: o botão **Desligar** no
topo da interface libera.

## Dois geradores: Kimodo original e kimodo.cpp

> Nesta máquina os dois foram desinstalados em 08/10/2026. Enquanto nenhum estiver instalado, a
> ponte mostra "Nenhum gerador de animação instalado", não pergunta nada ao abrir e não gera;
> importar, validar e encerrar continuam funcionando. Para reinstalar o original, siga
> `docs/kimodo-setup/GUIA-KIMODO.md` e ponha `installed = true` em `[kimodo]`, no `ponte.toml`.

Com pelo menos um instalado, ao abrir a ponte a primeira tela pergunta **qual gerador você vai usar**. Os dois rodam o
mesmo modelo, no mesmo esqueleto, e a fila é uma só (um pedido de cada vez, somando os dois).
Para trocar depois: *trocar gerador*, na barra de cima, ou `uv run ponte engine kimodo|cpp`.

| | Kimodo original | kimodo.cpp |
|---|---|---|
| Onde roda | Docker dentro do WSL | direto no Windows (`D:\kimodo.cpp`) |
| Laço, caminho e direção, força do gesto | sim | ainda não: a tela desliga esses controles |
| Continuar um roteiro | parte do fim do clipe gravado | gera o roteiro inteiro de novo, com a mesma semente (o passo anterior sai igual) |
| Refazer um passo | sai diferente a cada vez | com o mesmo texto sai igual: mude o texto |
| Memória | o text encoder ocupa uns 17 GB de RAM enquanto ligado | carrega uns 9 GB de pesos a cada geração e solta ao terminar (uso de RAM não medido) |
| Tempo para 5 s de animação | — | uns 3 min e meio (só processador) |

O kimodo.cpp foi compilado sem Vulkan, então gera no processador. Um clipe gerado num não
pode ser continuado no outro. Para instalar noutra máquina: clonar
[kimodo.cpp](https://github.com/localai-org/kimodo.cpp) com o submódulo, compilar
`kmd-generate` com o CMake do Visual Studio 2022, baixar os pesos com
`scripts/download_gguf_weights.py --model soma-rp-v1.1` e apontar `[kimodo_cpp] repo` no
`ponte.toml`.

## Linha de comando

É por onde as animações são feitas pelo backend. Tudo que ela faz aparece na interface.

`<projeto>` é o id do projeto, que é o do personagem (aparece em `ponte status`).

```powershell
uv run ponte status                      # projetos, fila, o que foi aprovado/reprovado (com as notas) e o que já foi encerrado
uv run ponte asset add personagem.fbx    # cria o projeto e faz o laudo
uv run ponte asset add personagem.fbx --textures pasta_das_texturas
uv run ponte asset textures <projeto> cor.png normal.png   # acrescenta texturas e refaz o laudo
uv run ponte asset show <projeto>        # laudo e mapeamento de ossos
# Roteiro, um passo de cada vez: gere, confira a prévia e só então o próximo, com --continue.
uv run ponte gen "stands still, breathing." --premise "A zombie" --duration 6 --asset <projeto>
uv run ponte gen "walks forward slowly." --premise "A zombie" --duration 5 --continue <animacao> --asset <projeto>
# Refazer o último passo: parte da animação anterior e toma o lugar da que saiu errada.
uv run ponte gen "shuffles forward." --premise "A zombie" --duration 5 --continue <anterior> --replace <errada> --asset <projeto>
# Passo em laço (termina na pose em que começou); --text-weight para um gesto mais marcado.
uv run ponte gen "sways from side to side." --premise "A zombie" --duration 6 --loop --text-weight 4 --continue <animacao> --asset <projeto>
uv run ponte gen "..." --dry-run         # só confere que o roteiro monta; não gera nada
uv run ponte retarget <projeto> <animacao> [--in-place]   # refaz a prévia
uv run ponte close <projeto>             # encerra o personagem: monta o resultado e cria o atalho
uv run ponte close <projeto> --unreal    # idem, e liga o arquivo para a Unreal 5 (--no-unreal desliga)
uv run ponte reopen <projeto>            # desfaz o encerramento
uv run ponte kimodo status|start|stop
uv run ponte fixture                     # recria o boneco de teste
```

## Como o retarget funciona

O Kimodo exporta BVH em T-pose padrão. Para cada osso mapeado do personagem, o Blender
recebe a rotação **global** da junta correspondente do SOMA, corrigida pela diferença entre
as poses de descanso (é o que resolve A-pose × T-pose). O deslocamento do quadril é escalado
pela altura do quadril do personagem, para o tamanho da passada acompanhar o tamanho da perna.
Detalhes em `blender/ponte_bl/retarget.py` e `blender/ponte_bl/rigmap.py`.

Conferir depois de mexer no retarget:

```powershell
uv run python tests/check_rigmap.py      # nomes de ossos: Mixamo, Unreal, Unity, Blender, VRM, Biped, captura
uv run python tests/check_retarget.py    # boneco de teste em 3 variantes + caminhada real do Kimodo
uv run python tests/check_textures.py    # textura embutida, separada, solta e com falso alfa
uv run python tests/check_bake.py        # ajuste de pose e arma: visualizador × arquivos do Blender
uv run python tests/check_script_dry.py  # roteiro: os passos se encadeiam e o laço fecha (ensaio a seco, não gera)
uv run python tests/check_chain.py       # um passo de cada vez: o clipe novo toma o lugar do que estende ou refaz
uv run python tests/check_fila.py        # Kimodo: um pedido de cada vez, na ordem de chegada
uv run python tests/check_mixamo.py      # animação em FBX: mesmo movimento do caminho direto, vira ação e sai no resultado
uv run python tests/check_capture.py     # captura em BVH de outro esqueleto: mesmo movimento, laço fechado, vira ação e sai no resultado
uv run python tests/check_engine.py      # os dois geradores: kimodo.cpp sai no SOMA 77, continua refazendo o roteiro, divide a fila com o original
uv run python tests/check_close.py       # encerrar: resultado único igual às prévias, atalho fora do projeto
uv run python tests/check_unreal.py      # Unreal 5: esqueleto do Mannequin, mesmas animações (--engine <UnrealEditor-Cmd.exe> importa de verdade)
uv run python tests/check_migration.py   # acervo de versões antigas vai para as pastas de projeto
uv run python tests/check_autorig.py <arquivo_do_mixamo.fbx>   # rigador × rig do próprio Mixamo
```

A geração usa `kimodo_scripts/gerar.py`, que roda dentro do container do Kimodo: cada passo
do roteiro parte dos últimos quadros do anterior, com a trajetória de cada um, tudo com o
modelo carregado uma vez. Para conferir uma animação com trajetória imposta:
`blender --background --python blender/motion_stats.py -- <motion.bvh>`. Para conferir se cada
passo entregou o gesto pedido (quanto andou, virou, balançou, e se o laço fecha):
`blender --background --python blender/step_stats.py -- <pasta da animação>`.

## Unreal 5

Com *Gerar também para a Unreal 5* ligado, o encerramento grava mais um arquivo,
`resultado\unreal5\SK_<nome>.fbx`, feito em `blender/ponte_bl/unreal.py`:

- **O esqueleto é o do Mannequin** (`SK_Mannequin`, o do Manny e da Quinn): mesmos nomes,
  mesma hierarquia e mesmos eixos em cada osso, com `root` no chão. As juntas ficam onde já
  estavam no personagem. Os ossos do Mannequin que o personagem não tem (os da coluna e do
  pescoço que sobram, os metacarpos) entram sem peso, para a hierarquia bater; os de IK copiam
  o pé e a mão; os de torção e de correção ficam de fora. Ossos do personagem sem par no
  Mannequin (cabelo, roupa) continuam com o nome que tinham.
- **As animações são as mesmas**: cada osso novo anda preso ao osso de onde veio, sem
  recalcular nada. A conversão mede quanto a malha e as juntas mudaram e o número sai no log
  do encerramento (no boneco de teste, até 0,0006 cm).
- **Na Unreal**: arraste o arquivo para o Content Browser e importe com as opções padrão.
  Entram `SK_<nome>` (a malha), `SK_<nome>_Skeleton`, `SK_<nome>_PhysicsAsset` e uma animação
  por clipe, `SK_<nome>_<clipe>`.

Conferido importando na Unreal 5.8.3, sem interface, num projeto de rascunho
(`tests/check_unreal.py --engine <UnrealEditor-Cmd.exe>`): nenhum aviso, `root` com escala 1,
pose de descanso certa e as juntas de cada clipe nas mesmas posições do resultado normal. A
Unreal também aceita o personagem no `SK_Mannequin`, e uma animação do Mannequin tocada nele
deixa braços e pernas na mesma direção que no Manny (0°; coluna e cabeça até 4°, pés 6°).

O que saber:

- Escolha o esqueleto do próprio arquivo (o padrão) ao importar. Com o `SK_Mannequin`
  escolhido como esqueleto, as animações do arquivo levam as proporções do personagem, e a
  Unreal as reescala (medido: coxa de 37 para 32 cm) enquanto o *Retarget Source* de cada uma
  não for a malha dele.
- Um personagem com um clipe só: a Unreal chama a animação de `SK_<nome>_Anim`.
- `root` fica parado: o deslocamento continua no `pelvis`, como no resultado normal. O root
  motion da Unreal não tem o que extrair dali; para o jogo mover o personagem, use as prévias
  *parado*.
- A arma ou acessório entra na malha, preso ao osso. Isso foi conferido por número (materiais
  e limites da malha), não na tela.
- Coluna com mais de 5 ossos ou pescoço com mais de 2 não cabem no Mannequin. Quando a
  conversão não dá, o resultado normal sai assim mesmo, com um aviso dizendo o motivo.
- Foi conferido com o boneco de teste, em duas variantes (uma com a armature em 0,01, como
  vem do Mixamo), e com uma cópia de um personagem de verdade (581 mil triângulos, 4 texturas,
  uma animação de 10 s): entrou na Unreal 5.8.3 com as texturas, 1,70 m de altura, sem avisos,
  e a animação com as juntas onde deviam estar. Tudo isso por número, sem interface: falta
  olhar na tela do editor e usar num projeto de jogo.

## Limites conhecidos

- Validado com o boneco de teste e com um personagem real (gerado no Tripo, esqueleto com
  nomes do Mixamo). Outras convenções de ossos só foram testadas pelos nomes, não com modelos.
- Texturas grandes pesam: cada prévia guarda um GLB e um BLEND com as texturas dentro.
- O encerramento foi conferido com o boneco de teste (três animações e uma arma) e com uma
  cópia de um personagem real: os clipes do GLB batem com as prévias, e o FBX e o BLEND
  reabrem no Blender com os mesmos clipes. A tela foi conferida por imagem e pela API, não
  com mouse. Falta encerrar com animações de verdade do Kimodo e importar o resultado numa engine.
- No FBX do resultado o acessório vai preso ao osso (filho dele na hierarquia). Ao reabrir
  esse FBX no Blender 5.2, o importador novo mostra o acessório deslocado pelo comprimento
  do osso; o arquivo está certo (o importador antigo do Blender o põe no lugar). Para
  conferir no Blender, use o `.blend` do resultado.
- O nome de cada clipe sai do texto do pedido (sem a premissa); ainda não dá para trocá-lo.
- Não há trava de pés por IK: em personagens com proporções muito diferentes do SOMA os pés
  deslizam um pouco. O número aparece em cada prévia (*Deslize dos pés*).
- O ajuste de pose é uma rotação fixa por osso, igual em todos os quadros. Não há IK (puxar
  a mão e o braço acompanhar) nem ajuste que mude ao longo do tempo.
- Animações do Mixamo: a importação foi testada pela tela e pelo teste com um FBX fabricado
  aqui, e pela linha de comando com três arquivos baixados do Mixamo (um parado, um andar e
  um ataque de um pacote de zumbi, sem malha), aplicados num personagem de outro tamanho:
  as prévias saíram certas. Só foi importado FBX sem malha vindo de lá. O laço de uma
  animação de lá (parado, andar) depende de ela já vir em laço; nada aqui a corrige.
- Um ZIP de pacote do Mixamo (o personagem e várias animações) enviado como projeto novo traz
  só o personagem: as animações do pacote são importadas uma a uma em **Animações Mixamo**.
- Capturas em BVH: testadas com uma captura fabricada aqui (a caminhada do Kimodo com os nomes
  de osso, a unidade, os eixos e o ritmo de uma captura) e com dois arquivos de verdade da
  100STYLE (XSens, 60 quadros por segundo), aplicados num personagem. O laço só foi procurado
  em andar para frente: parado, de lado e de costas não foram testados. O chão é o Y = 0 do
  arquivo, corrigido só se os dedos do pé ficarem a mais de 3 cm disso. A captura é crua: o
  pé de apoio desliza um pouco (o número aparece na prévia) e nada aqui o prende.
- Laço: só o passo marcado como *em laço* emenda o fim no começo. Foi conferido por medida em
  dois passos gerados de verdade (um ocioso e um andar: pose final igual à inicial). Tocar o
  laço na tela (**↻ laço**) e pedir um laço pela interface ainda não foram testados com mouse,
  e nenhum laço foi levado a uma engine.
- A força do gesto foi comparada num caso só (um ocioso): deu mais movimento de cabeça e mãos,
  pouco no corpo inteiro.
- O manipulador, o caminho desenhado e os acessórios foram conferidos por conta (testes) e
  por imagem, mas não com mouse numa janela real.
- O roteiro passo a passo foi gerado de verdade uma vez pela linha de comando (um passo
  continuando um clipe pronto, medido depois). A tela dele foi conferida por imagem e por teste
  com o Kimodo trocado por um dublê, não com mouse nem com uma geração pedida por ela.
- O caminho desenhado num passo que continua um clipe: a conta de onde o personagem está e
  para onde olha foi conferida com números numa prévia real (bate com o Kimodo a milímetros e
  0,1°). Desenhar com o mouse e gerar por esse caminho ainda não foi testado.
- O rigador foi calibrado e comparado com **um** personagem rigado pelo Mixamo (juntas a
  1–3 % da altura das do Mixamo). Em corpos muito diferentes os marcadores estimados podem
  sair longe: confira-os. A tela de marcadores e o envio de ZIP ainda não foram testados.
- O esqueleto do rigador tem os nomes e a hierarquia do Mixamo; a orientação interna de cada
  osso não foi igualada à do Mixamo. As animações geradas aqui funcionam (o retarget não
  depende disso). Aplicar nele uma animação baixada do site do Mixamo não foi testado.
- Rigs de controle (Rigify) são detectados e recusados.
- Mapeamento manual de ossos existe só pela API (`PUT /api/assets/<id>/mapping`), sem tela.

## Pastas

| Pasta | Conteúdo |
|---|---|
| `ponte/` | backend: armazenamento, fila, runners do Blender e do Kimodo, API, CLI |
| `blender/` | scripts que rodam dentro do Blender (laudo, rig, retarget, acessórios, tira de quadros, boneco de teste) |
| `kimodo_scripts/` | o gerador que roda dentro do container do Kimodo (roteiro, transições, trajetória) |
| `web/` | interface (three.js, sem build) |
| `scripts/` | atalho de desktop, abrir e parar |
| `data/` | acervo local: `projects/` (um projeto por personagem), `resultados/` (atalhos dos encerrados), `jobs/` |
| `tests/` | verificações e os BVHs de referência |
#   p o n t e - a n i m a d a  
 #   p o n t e - a n i m a d a  
 