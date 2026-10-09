# Kimodo — Guia de Uso

Instalado e validado em 06/10/2026. Geração de teste: **150 frames, 77 juntas, 6,4 m de caminhada**.

---

## Onde está instalado

| Item | Local |
|---|---|
| Repositório Kimodo | `\\wsl$\Ubuntu\home\dap_p\kimodo` (dentro do WSL, no NVMe) |
| Distro Ubuntu | `C:\wsl\Ubuntu\ext4.vhdx` (SSD NVMe) |
| Imagem Docker | `kimodo:1.0` — **35,2 GB** |
| Cache de modelos | `\\wsl$\Ubuntu\home\dap_p\.cache\huggingface` — **~17 GB** |
| Scripts de instalação | `C:\Users\dap_p\kimodo-setup\` |

---

## Como usar

### Abrir um terminal no Linux

```powershell
wsl -d Ubuntu
```

### Demo interativa (interface visual)

```powershell
wsl -d Ubuntu -u dap_p
cd ~/kimodo
docker compose up -d
```

Depois abra **http://localhost:7860** no navegador.

Para parar: `docker compose down` (dentro do WSL).

### Gerar por linha de comando

```powershell
wsl -d Ubuntu -u dap_p
cd ~/kimodo
docker compose run --rm -T demo kimodo_gen "A person walks forward." --model Kimodo-SOMA-RP-v1.1 --duration 5.0 --output minha_motion
```

O arquivo sai em `~/kimodo/minha_motion.npz`.

**Dica:** coloque `--output /workspace/saida/nome` para organizar em pasta.

### Modelos disponíveis

| Modelo | Esqueleto |
|---|---|
| `Kimodo-SOMA-RP-v1.1` | SOMA (humano) — **recomendado** |
| `Kimodo-SOMA-SEED-v1.1` | SOMA, treinado no BONES-SEED público |
| `Kimodo-G1-RP-v1` | Unitree G1 (robô humanoide) |
| `Kimodo-SMPLX-RP-v1` | SMPL-X (compatível com AMASS) |

---

## Formato da saída (.npz)

| Chave | Formato | Descrição |
|---|---|---|
| `posed_joints` | `[T, J, 3]` | Posições globais das juntas |
| `global_rot_mats` | `[T, J, 3, 3]` | Rotações globais |
| `local_rot_mats` | `[T, J, 3, 3]` | Rotações relativas ao pai |
| `foot_contacts` | `[T, 4]` | Contato dos pés |
| `smooth_root_pos` | `[T, 3]` | Root suavizado |
| `root_positions` | `[T, 3]` | Trajetória real do root |
| `global_root_heading` | `[T, 2]` | Direção |

`T` = frames (30 fps), `J` = 77 (SOMA).

---

## Desempenho medido nesta máquina

| Etapa | Tempo |
|---|---|
| Difusão (100 passos, 150 frames) | **~14 s** (~7 it/s) |
| Geração completa (modelo já em cache) | ~1–2 min |
| Primeira carga do text encoder | ~5 min (CPU) |

**Uso de recursos:** o modelo Kimodo roda na GPU (`cuda:0`, <3 GB de VRAM). O text encoder roda na **CPU**, consumindo ~17,5 GB de RAM.

---

## Configurações aplicadas (e por quê)

### 1. `C:\Users\dap_p\.wslconfig`

```ini
[wsl2]
memory=24GB
swap=16GB
```

**Motivo:** o WSL2 limita a VM a 50% da RAM por padrão (16 GB), e só o Llama-3-8B em `bfloat16` consome ~16 GB. Sem isso, a geração morreria por OOM.

### 2. `~/kimodo/docker-compose.override.yaml`

```yaml
services:
  text-encoder:
    environment:
      TEXT_ENCODER_DEVICE: cpu
      PYTORCH_CUDA_ALLOC_CONF: "expandable_segments:True"
  demo:
    environment:
      TEXT_ENCODER_DEVICE: cpu
      PYTORCH_CUDA_ALLOC_CONF: "expandable_segments:True"
```

**Motivo:** sua RTX 3060 tem 12 GB e o Kimodo pediria ~17 GB. Forçando o text encoder para a CPU, o consumo de VRAM cai para <3 GB.

O `TEXT_ENCODER_DEVICE: cpu` também está no serviço `demo` como **rede de segurança**: o `load_model.py` usa `TEXT_ENCODER_MODE="auto"`, que faz *fallback silencioso* para o encoder local se a API cair — sem isso, esse fallback subiria o Llama na GPU e estouraria a VRAM.

### 3. `~/kimodo/Dockerfile` — modificado

Adicionadas duas variáveis (linhas 16-17):

```dockerfile
ENV PIP_INDEX_URL=https://pypi.org/simple \
    PIP_EXTRA_INDEX_URL=https://pypi.org/simple
```

**Motivo:** a imagem base da NVIDIA configura o pip para `pypi.ngc.nvidia.com`, que não resolve aqui. O pip gastava 5 retries falhos por pacote — medi **179 linhas de retry para 35 pacotes**. Com a correção, o `pip install` caiu de ~20 min para **150 s**.

Para ver a diferença: `cd ~/kimodo && git diff Dockerfile`

---

## Observações

- **O WSL não inicia sozinho.** O Docker Desktop precisa estar rodando para os containers funcionarem. Ele não está configurado para iniciar com o Windows (`AutoStart: false`). Para mudar: Docker Desktop → Settings → General → *Start Docker Desktop when you sign in*.
- **Token Hugging Face:** gravado em `~/.cache/huggingface/token` (modo 600). Como ele foi exposto no histórico do chat, recomendo revogá-lo em https://huggingface.co/settings/tokens e gerar outro.
- **Desinstalar:** `docker compose down` no WSL, depois remover a distro com `wsl --unregister Ubuntu` (apaga tudo do Linux) e desinstalar o Docker Desktop.

---

## Solução de problemas

**`wsl` retorna `REGDB_E_CLASSNOTREG`**
O WSL veio quebrado pelo Windows Update. Corrigido instalando o MSI oficial:
```powershell
# https://github.com/microsoft/WSL/releases
msiexec /i wsl.3.0.1.0.x64.msi /qn /norestart
```

**Container `text-encoder` fica `unhealthy` por vários minutos**
Normal na primeira vez — ele está carregando 8B de parâmetros na CPU. Aguarde; acompanhe com `docker logs -f text-encoder`.

**Erro de VRAM / CUDA out of memory**
Confirme que `TEXT_ENCODER_DEVICE: cpu` está no `docker-compose.override.yaml` e valide com:
```bash
cd ~/kimodo && docker compose config | grep TEXT_ENCODER_DEVICE
```

**Os avisos `MISSING`/`UNEXPECTED` do LLM2Vec ao carregar**
São esperados — a própria NVIDIA documenta isso como ruído inofensivo.
