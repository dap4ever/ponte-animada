# ARDY: o que deu certo e o que deu errado

Registro do tempo em que o ARDY esteve neste PC, de 08 a 10/10/2026. Ele foi desinstalado em
10/10/2026, a pedido do dono do projeto, para liberar espaço; o gerador passou a ser o kimodo.cpp.
Este arquivo existe para que ninguém precise descobrir tudo de novo se um dia ele voltar.

O ARDY é um gerador de movimento da NVIDIA (`github.com/nv-tlabs/ardy`, julho de 2026): recebe um
texto em inglês e devolve um corpo se mexendo. É irmão do Kimodo, treinado nas mesmas gravações.

## Em poucas linhas

- **O melhor dele são as pernas e o corpo.** O andar em patrulha do Soldado, aprovado em
  10/10/2026 ("ficou excelente", "aprovados com honra"), é o corpo inteiro de um clipe do ARDY.
- **O pior são as mãos e a arma.** Ele não gera dedos, não sabe onde o fuzil está e, com a palavra
  "rifle", quase sempre põe o personagem mirando. A pegada do fuzil teve de ser refeita no Blender.
- **Pedir tudo de uma vez deu errado.** O pacote de 38 animações foi reprovado inteiro. O que
  funcionou foi uma animação de cada vez, mostrada ao lado da anterior, esperando o veredito.

## O que deu certo

1. **Movimento de pernas natural.** Foi o primeiro elogio ("o movimento de pernas deles é muito
   bom") e o que sobreviveu até o fim.
2. **Laço, direção e velocidade.** Ele anda para o lado pedido, na velocidade pedida, e o laço
   fecha sem salto: num teste de 09/10, pedindo 0,8 m/s andou 0,80 e o laço de 4 s fechou em
   0,0 cm. A emenda entre dois passos de um roteiro sai sem tranco (0,4 a 0,8 cm).
3. **Gera rápido**, quando o Ubuntu já está acordado: uns 10 segundos por pedido.
4. **O texto que dá a arma baixa, de patrulha:**
   `A person is steadily walking forward while carrying a rifle low in front of their waist with
   both hands, the barrel pointing down at the ground.`
   Com ele as mãos ficam de 16 a 22 cm e de 25 a 36 cm abaixo do ombro, o cano de 22 a 30 graus
   para baixo e o tronco em pé. `...holding a rifle at the low ready position` deu quase o mesmo.
5. **Testar o texto antes de produzir.** `soldado_ardy.py probe` gera 3 segundos em 10 s e mede
   a altura das mãos: dá para saber se saiu mirando ou de arma baixa sem olhar um por um. Os dez
   textos testados e os números estão em `data/tmp/soldado-ardy/provar_patrulha.log`.
6. **Escrever no jeito das legendas do treino**: começar por `A person...`, uma ou duas ações por
   texto, a direção e o ritmo com as palavras de lá (`is walking sideways to their right at a
   steady pace`, `jogs forward at a steady pace`, `A crouched person walks forward at a slow
   pace`). As legendas públicas estão em `nvidia/SEED-Timeline-Annotations`, no Hugging Face.
7. **Laço em dois pedidos**: primeiro um passo de entrada (3 s), depois o laço continuando dele.
   O laço fecha na pose em que começa.
8. **Dois cuidados que poupam muito tempo**: deixar um `wsl.exe -d Ubuntu -- sleep 3600` rodando
   enquanto se gera (senão o Ubuntu desliga em 1 minuto e cada pedido passa de 10 para 80 s), e
   codificar todos os textos novos numa subida só do codificador.
9. **Como o andar aprovado saiu dele** (os scripts estão em `D:\Blender-Animacoes\Soldado\scripts`):
   o clipe inteiro do ARDY vai para uma cópia do personagem ao lado do que já existe; os pés são
   acertados no chão; o tronco, o pescoço e a cabeça ficam como vieram; os braços e as mãos são
   refeitos para segurar o fuzil.

## O que deu errado

1. **O pacote de uma vez.** Foram gerados 38 clipes (andar, correr, disparar, agachado, parado,
   viradas, nas oito direções) e ele mandou apagar todos: "todas estão ruins". Não disse o que
   achou ruim no conjunto. Lição: uma amostra de cada tipo, e esperar o veredito.
2. **"Rifle" puxa para a mira.** `while aiming a rifle` e `holding a rifle with both hands` (até
   com `at waist height`) deixam o fuzil no ombro, com as mãos a menos de 10 cm do ombro. Parado,
   `pointing it down at the ground`, `carrying` e `stands guard` também saíram com a arma erguida.
   O primeiro andar trazido para o Blender veio assim, e a cobrança foi: "fez o prompt errado,
   ele está mirando, não patrulhando".
3. **As mãos não servem como vêm.** Não há dedos; a mão esquerda fica por cima da arma; com o
   fuzil preso à mão direita, a coronha entra até 2,7 cm no peito o tempo todo. A pegada tem de
   ser refeita fora dele.
4. **De lado, mirando, ele não cruza as pernas**: quatro passadas curtas em 2 segundos, os
   "pulinhos" que ele reprovou ("o ideal seria entrelaçar as pernas"). Sem arma no texto, cruza.
5. **Correr de lado e de costas não existe nos dados.** A 5 m/s a diagonal saiu torta (331 graus
   em vez de 315) e o pé não para no chão; a 3,4 m/s de lado o pé escorrega de 47 a 56 cm/s.
6. **A mão da arma muda com a direção**, porque metade do treino é espelhada: para a direita sai
   destro, para a esquerda canhoto, nas diagonais o contrário, para frente e para trás ao acaso.
   Conserta-se espelhando o clipe inteiro, ou juntando pernas espelhadas com o tronco original.
7. **Os pés vêm com defeitos pequenos, diferentes em cada clipe**: afundam de 0,7 a 2,6 cm no
   chão, o pé apoiado escorrega até 4 cm e às vezes vem inclinado uns 4 graus. No andar
   aprovado isso foi corrigido no Blender (0 cm afundado, 0 cm de escorregão).
8. **O codificador de texto é pesado**: todo texto novo pede 16 GB de memória e de 3 a 5 minutos
   para carregar (na placa não cabe: pede 14 GB e a RTX 3060 tem 12). Com o Blender e a Godot
   abertos o Windows ficou com 0,8 GB livres. Em 08/10 ele mandou cancelar uma geração por causa
   disso. Texto já usado não precisa do codificador.
9. **As legendas públicas do treino não têm arma nenhuma.** A palavra "rifle" funciona porque o
   treino completo tem, mas não dá para consultar como ela é descrita lá: só testando.
10. **O que eu errei no caminho**, para não repetir: mostrar o lote inteiro em vez de uma amostra;
    fazer a parte de cima à mão com o tronco travado (o peito girava 1,6 grau por passada, contra
    11 no ARDY, e ele achou "sem naturalidade"); e não conferir a pose do primeiro andar antes de
    mostrar.
11. **Ficou sem testar de verdade**: o demo "ao vivo" exportando uma sessão feita por ele, e o
    veredito dele sobre o primeiro clipe (o zumbi andando).

## Os números

| O quê | Quanto |
|---|---|
| Espaço no Ubuntu | 26 GB: 7,8 do programa, 17 dos modelos, 1,3 de cache da instalação |
| Memória do codificador de texto | 16 GB, por 3 a 5 minutos, a cada leva de textos novos |
| Um pedido com texto já usado | uns 10 s (80 s se o Ubuntu estava desligado) |
| Esqueleto | Core, 27 juntas, 20 quadros por segundo, sem dedos |
| Andar aprovado | laço de 2 s, 1,1 m/s pedidos, 0,625 m/s na escala do Soldado (1 m de altura) |

## O que saiu do PC e o que ficou

Saiu (por `ardy-desinstalar.sh`, nesta pasta): `~/ardy` no Ubuntu, os quatro modelos em
`~/.cache/huggingface/hub`, o cache do pip, os registros da instalação e os dois atalhos da Área
de Trabalho ("ARDY - ao vivo" e "ARDY - zumbi de teste").

Ficou:

- o código da ponte que fala com ele (`ponte/ardy.py`, `ardy_scripts/`) e os scripts desta pasta;
- `data/tmp/ardy-guardado/`: os 105 textos já codificados, os três clipes do zumbi de teste e o
  número da versão que estava instalada;
- `data/tmp/soldado-ardy/`: os scripts e os registros dos testes de texto;
- a prévia `walk-forward-60a1`, de onde saiu o andar aprovado: há cópia em
  `D:\Blender-Animacoes\Soldado\fontes\`. O projeto "Soldado ARDY" da ponte, onde ela nasceu,
  saiu na limpeza do acervo feita no mesmo dia (está na cópia de segurança do acervo);
- no Ubuntu: o token do Hugging Face, o `uv` com o Python 3.11 e o compilador. São pequenos.

**O arquivo do disco do Ubuntu não encolheu sozinho.** `E:\wsl\Ubuntu\ext4.vhdx` continuou com
28,5 GB, embora por dentro só haja 2,3 GB. Para devolver esse espaço ao E:, rode
`compactar-disco-do-ubuntu.ps1` (nesta pasta): ele pede permissão de administrador e desliga o
Ubuntu e o Docker por alguns minutos.

## Para instalar de novo

Na ordem, de dentro do Ubuntu (`wsl.exe -d Ubuntu -- bash /mnt/d/PonteAnimada/docs/ardy-setup/<script>`):
`ardy-root.sh` (como root), `ardy-prep.sh`, `ardy-install.sh`, `ardy-modelos.sh` (17 GB; precisa do
token do Hugging Face, que ficou). Depois, `installed = true` na seção `[ardy]` do `ponte.toml`.
Para aproveitar os textos já codificados, copie `data/tmp/ardy-guardado/text_embeddings` para
`~/ardy/.cache/`. O conserto da página do demo é `ardy-corrigir-caixa-de-texto.py`.

## E o kimodo.cpp, que ficou no lugar

Gera 5 segundos em uns 30 segundos, na placa de vídeo, e texto novo não custa nada a mais. Em
compensação não faz laço nem obedece direção e velocidade: o ciclo do andar tem de ser recortado
e fechado no Blender. E os textos não são os mesmos: o que deu a arma baixa no ARDY saiu mirando
no kimodo.cpp; lá funcionaram `holding a rifle at the low ready position` e `on patrol with a
lowered rifle held in both hands in front of their hips`.
