# Build e Instalação — WhisperWriter (Linux/GPU)

Documentação do processo para empacotar o WhisperWriter num executável standalone (sem precisar de `python run.py`) e instalá-lo no sistema seguindo os padrões XDG.

Este documento cobre o fluxo em **Linux x86_64 com GPU NVIDIA** (testado em Ubuntu 24.04 + RTX 4070 + driver 580, sessões X11 e Wayland/GNOME 46). Para CPU-only ou Windows, há observações no final.

---

## Pré-requisitos do sistema

Pacotes apt comuns às duas sessões:

```bash
sudo apt install -y python3.12-dev pkg-config libportaudio2
```

| Pacote | Para quê |
|---|---|
| `python3.12-dev` | Header `Python.h` para compilar `evdev` e `webrtcvad-wheels` durante o `pip install` |
| `pkg-config` | Localização de bibliotecas em build |
| `libportaudio2` | Biblioteca runtime que o `sounddevice` usa para gravar áudio |

### X11

```bash
sudo apt install -y xdotool
```

`xdotool` é usado pelo `input_method: xdotool` (recomendado em X11) — simulação de digitação via XTest, mais robusta que `pynput` em terminais.

### Wayland (GNOME/mutter)

```bash
sudo apt install -y ydotool ydotoold wl-clipboard
sudo usermod -aG input $USER   # depois faça LOGOUT + LOGIN
```

| Pacote / passo | Para quê |
|---|---|
| `ydotool` | CLI que envia keystrokes via `/dev/uinput`. Usado pelo `input_method: ydotool` (char-a-char) e pelo `input_method: clipboard` (envia 1 Ctrl+V) |
| `ydotoold` | Daemon do ydotool (pacote separado!) — sem ele, `ydotool` reabre `/dev/uinput` por chamada e fica instável em alta velocidade |
| `wl-clipboard` | Provê `wl-copy`/`wl-paste`. Usado pelo `input_method: clipboard` em Wayland |
| Grupo `input` | Necessário para o `EvdevBackend` ler `/dev/input/event*` (captura da hotkey global em Wayland). Requer relogar pra ser aplicado |

`/dev/uinput` precisa estar acessível pelo seu user — geralmente já vem via ACL do systemd-logind em sessões desktop modernas (`getfacl /dev/uinput` mostrar `user:<seu_user>:rw-`). Caso não esteja, instale uma udev rule.

#### Habilitar `ydotoold` como user systemd service

O daemon precisa rodar no contexto do seu login (não system-wide) para o socket ficar exclusivo da sessão:

```bash
mkdir -p ~/.config/systemd/user
cat > ~/.config/systemd/user/ydotoold.service <<'EOF'
[Unit]
Description=ydotool input daemon (user)
Documentation=https://github.com/ReimuNotMoe/ydotool

[Service]
Type=simple
ExecStart=/usr/bin/ydotoold
Restart=on-failure
RestartSec=2

[Install]
WantedBy=default.target
EOF

systemctl --user daemon-reload
systemctl --user enable --now ydotoold.service
systemctl --user status ydotoold.service   # confirme "active (running)" + "listening on socket /tmp/.ydotool_socket"
```

#### Configuração recomendada do app em Wayland

Após o setup acima, ajuste `~/.config/WhisperWriter/config.yaml`:

```yaml
recording_options:
  input_backend: evdev
  recording_mode: hold_to_record   # opcional — segura F9 enquanto fala, solta pra transcrever
post_processing:
  input_method: clipboard
  paste_uses_shift_v: false        # alterne via tray menu ou hotkey ctrl+alt+v
```

**Por que `clipboard` e não `ydotool` em Wayland?** O ydotool 0.1.8 do Ubuntu 24.04 (versão antiga) corrompe keystrokes em rate alto (`writing_key_press_delay < 50ms`) mesmo com daemon. O `clipboard` envia o texto via `wl-copy` e dispara **um único** `Ctrl+V` via ydotool — atômico, sem perda de char, sem janela de "perda de foco no meio". Para terminais Wayland (gnome-terminal, tilix, alacritty, kitty) que usam `Ctrl+Shift+V`, alterne via item "Modo terminal" no tray menu ou hotkey global `Ctrl+Alt+V`.

### Driver NVIDIA

Driver NVIDIA já instalado (verifique com `nvidia-smi`). **Não é necessário instalar o CUDA Toolkit do sistema** — usamos os pacotes pip `nvidia-cublas-cu12` e `nvidia-cudnn-cu12` que carregam as libs CUDA dentro do venv.

---

## Setup do ambiente de desenvolvimento

A partir da raiz do projeto. Recomendado: usar **[`uv`](https://github.com/astral-sh/uv)** (10–100x mais rápido que `pip`); fallback para `pip` puro está documentado abaixo.

```bash
# Recomendado — uv (instale uma vez: curl -LsSf https://astral.sh/uv/install.sh | sh)
uv venv -p 3.12 .venv
source .venv/bin/activate
uv pip install -r requirements.txt
```

```bash
# Alternativa — pip puro
python3.12 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
```

O `requirements.txt` já está calibrado para Python 3.12 (`numpy 1.26+`, `numba 0.59+`, `av 12+`, `aiohttp 3.9+`, etc.) e inclui as libs CUDA pip (`nvidia-cublas-cu12`, `nvidia-cudnn-cu12 ≥ 9.1`, `ctranslate2 ≥ 4.5`).

### Hook do `LD_LIBRARY_PATH` no `activate`

O arquivo `.venv/bin/activate` está **patchado** para exportar `LD_LIBRARY_PATH` apontando para as libs CUDA empacotadas pelos pacotes `nvidia-*`. Sem isso, o `ctranslate2` não encontra `libcudnn.so.9` em runtime.

O patch adiciona estes paths ao `LD_LIBRARY_PATH` quando você roda `source .venv/bin/activate`:

```
.venv/lib/python3.12/site-packages/nvidia/cublas/lib
.venv/lib/python3.12/site-packages/nvidia/cudnn/lib
.venv/lib/python3.12/site-packages/nvidia/cuda_nvrtc/lib
```

E reverte automaticamente no `deactivate`.

> Se você recriar o venv do zero (`rm -rf .venv && python3.12 -m venv .venv`), o patch é perdido. Precisa ser reaplicado — veja a seção "Recriando o venv do zero" mais abaixo.

### Rodar em modo dev

```bash
source .venv/bin/activate
python run.py
```

A primeira execução baixa o modelo `large-v3-turbo` (~1.6 GB) do HuggingFace para `~/.cache/huggingface/`.

### Linting (ruff)

O projeto usa `ruff` (configurado em `pyproject.toml`) para checagem estática:

```bash
ruff check src/ run.py        # verifica
ruff check src/ run.py --fix  # corrige o que for auto-fixable
```

---

## Empacotamento com PyInstaller

### Componentes do empacotamento

| Arquivo | Função |
|---|---|
| `WhisperWriter.spec` | Spec do PyInstaller — define entrypoint, libs CUDA, hidden imports |
| `hooks/hook-webrtcvad.py` | Hook custom que corrige metadata: o pacote real é `webrtcvad-wheels`, não `webrtcvad` |
| `run.py` | Entrypoint adaptado: importa `main` direto (sem `subprocess`) e exporta `LD_LIBRARY_PATH` quando rodando empacotado (`sys.frozen`) |
| `src/paths.py` | Helpers `resource_path()` e `user_config_path()` para abstrair caminhos entre dev e bundle |
| `install.sh` | Move o bundle de `dist/` para `~/.local/share/WhisperWriter/` e cria o `.desktop` |

### Build

```bash
source .venv/bin/activate
pyinstaller WhisperWriter.spec --noconfirm
```

Saída: `dist/WhisperWriter/` (~3 GB no modo GPU — cuDNN 9 é maior que cuDNN 8). Tempo de build: ~1 minuto numa máquina razoável.

### Instalação

```bash
./install.sh
```

O script:

1. Copia `dist/WhisperWriter/` → `~/.local/share/WhisperWriter/`
2. Cria `~/.local/share/applications/whisperwriter.desktop`
3. Atualiza o database de aplicativos do GNOME

Após isso, o app aparece no menu do GNOME (tecla Super → "WhisperWriter").

### Limpeza pós-instalação

A pasta `dist/` (3 GB) e `build/` (~70 MB) são regeneráveis. Pode apagar:

```bash
rm -rf dist build
```

---

## Estrutura final pós-instalação

```
~/Projetos/whisper/                     # repositório (dev)
├── .venv/                              # ambiente virtual com activate patchado
├── src/                                # código-fonte
├── hooks/hook-webrtcvad.py             # hook custom
├── WhisperWriter.spec                  # spec do PyInstaller
├── install.sh                          # script de instalação
└── docs/                               # esta documentação

~/.local/share/WhisperWriter/           # APP INSTALADO
├── WhisperWriter                       # executável
└── _internal/                          # libs (Python, CUDA, PySide6, faster-whisper, etc.)

~/.local/share/applications/
└── whisperwriter.desktop               # atalho do menu GNOME

~/.config/WhisperWriter/
└── config.yaml                         # configurações persistentes do usuário

~/.cache/huggingface/                   # modelos baixados (large-v3-turbo ≈ 1.6 GB)
```

---

## Atualizando após mudanças no código

```bash
cd ~/Projetos/whisper
source .venv/bin/activate
pyinstaller WhisperWriter.spec --noconfirm
./install.sh
```

A configuração do usuário em `~/.config/WhisperWriter/config.yaml` é preservada entre atualizações.

---

## Desinstalação

```bash
rm -rf ~/.local/share/WhisperWriter \
       ~/.local/share/applications/whisperwriter.desktop \
       ~/.config/WhisperWriter
```

Para liberar também o cache do modelo (~1.6 GB):

```bash
rm -rf ~/.cache/huggingface/hub/models--Systran--faster-whisper-large-v3-turbo
```

---

## Recriando o venv do zero

Se precisar recriar o `.venv` (ex: bumpou Python, mudou requirements drasticamente):

```bash
rm -rf .venv
uv venv -p 3.12 .venv          # ou: python3.12 -m venv .venv
source .venv/bin/activate
uv pip install -r requirements.txt   # ou: pip install -r requirements.txt
```

Depois **reaplique o patch do `LD_LIBRARY_PATH`** no `.venv/bin/activate`. Em resumo, adicione:

1. Dentro da função `deactivate ()`, logo após o bloco que restaura `PYTHONHOME`:
   ```bash
   if ! [ -z "${_OLD_VIRTUAL_LD_LIBRARY_PATH+_}" ] ; then
       LD_LIBRARY_PATH="$_OLD_VIRTUAL_LD_LIBRARY_PATH"
       export LD_LIBRARY_PATH
       unset _OLD_VIRTUAL_LD_LIBRARY_PATH
   elif [ -n "${_VIRTUAL_LD_LIBRARY_PATH_SET+_}" ] ; then
       unset LD_LIBRARY_PATH
       unset _VIRTUAL_LD_LIBRARY_PATH_SET
   fi
   ```

2. Logo após o `export PATH` (no fim do script):
   ```bash
   _NVIDIA_LIB_DIR="$VIRTUAL_ENV/lib/python3.12/site-packages/nvidia"
   if [ -d "$_NVIDIA_LIB_DIR" ] ; then
       if [ -n "${LD_LIBRARY_PATH+_}" ] ; then
           _OLD_VIRTUAL_LD_LIBRARY_PATH="$LD_LIBRARY_PATH"
       else
           _VIRTUAL_LD_LIBRARY_PATH_SET=1
       fi
       LD_LIBRARY_PATH="$_NVIDIA_LIB_DIR/cublas/lib:$_NVIDIA_LIB_DIR/cudnn/lib:$_NVIDIA_LIB_DIR/cuda_nvrtc/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
       export LD_LIBRARY_PATH
   fi
   unset _NVIDIA_LIB_DIR
   ```

---

## Notas e armadilhas

### Por que `webrtcvad` precisa de hook custom?

O pacote distribuído é `webrtcvad-wheels` (que disponibiliza wheels pré-compiladas), mas em runtime o módulo Python se chama `webrtcvad`. O hook padrão do PyInstaller (`hook-webrtcvad.py` em `pyinstaller-hooks-contrib`) faz `copy_metadata('webrtcvad')`, que falha porque o nome real do dist-info é `webrtcvad_wheels-x.x.x.dist-info`. Nosso `hooks/hook-webrtcvad.py` chama `copy_metadata('webrtcvad-wheels')` e contorna.

### Por que pinar `setuptools<81`?

O `webrtcvad` (v2.0.11) ainda usa `pkg_resources`, que foi removido do core do `setuptools` na v81. Pinar para `<81` garante compatibilidade. Há um warning de deprecação inócuo na inicialização — pode ignorar.

### Por que `xdotool` em vez de `pynput.type`?

`pynput` em alguns terminais (xterm.js do VS Code, principalmente) perde caracteres quando digita rápido. `xdotool type` usa a extensão XTest do X11, é nativo, e respeita o `--delay` de forma confiável. O custo é depender do binário `xdotool` instalado no sistema (uma única dependência apt leve).

### Como encerrar o app

- **Tray icon → Exit**: cleanup graceful (para `result_thread`, `key_listener`, `input_simulator`) via `QApplication.aboutToQuit`
- **Ctrl+C** no terminal: mata o processo direto via `SIG_DFL`. Threads filhas e descritores de áudio são liberados pelo OS — sem vazamento prático mas sem cleanup graceful

### Single instance

O app garante uma única instância por user via `fcntl.flock` em `$XDG_RUNTIME_DIR/whisperwriter.lock`. Se você tentar abrir uma segunda vez (terminal ou ícone do menu), aparece uma notificação do desktop ("WhisperWriter já está rodando") e o processo novo sai com exit 0 sem quebrar a primeira instância. O lock é liberado automaticamente pelo kernel quando o processo morre — sem lock fantasma após crash.

### CPU-only build

Se quiser empacotar sem GPU (~400 MB em vez de ~3 GB):

1. Remova do `requirements.txt`:
   - `nvidia-cublas-cu12`
   - `nvidia-cudnn-cu12`
2. Edite `WhisperWriter.spec`:
   - Comente o bloco que adiciona libs `nvidia/*` em `binaries`
3. Em `~/.config/WhisperWriter/config.yaml`:
   - `device: cpu`
   - `compute_type: int8` (ou `default`)
4. Build normalmente.

### Windows (TODO)

PyInstaller não faz cross-compile. Para gerar `WhisperWriter.exe` é necessário rodar todo o setup em Windows. Mudanças mínimas necessárias:

- Trocar `input_method` para `pynput` ou `clipboard` no `config.yaml` (no Windows ambos funcionam — `clipboard` usa pyperclip nativo + pynput para Ctrl+V)
- Os passos Wayland (ydotool, ydotoold, wl-clipboard, grupo input) **não se aplicam** em Windows
- O lock single-instance funciona via `fcntl` em Unix; em Windows precisaria adaptar para `msvcrt.locking` ou `QLockFile` do Qt
- O patch do `LD_LIBRARY_PATH` em `activate` é Linux-only e não tem efeito (Windows usa `PATH` e os pacotes `nvidia-*` carregam DLLs automaticamente)
- Pacotes apt (`python3.12-dev`, `libportaudio2`, `xdotool`) são desnecessários — no Windows essas dependências vêm com os respectivos pacotes pip ou com o instalador do Python
