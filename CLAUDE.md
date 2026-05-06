# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Visão geral

WhisperWriter — app de speech-to-text que grava do microfone com um atalho global, transcreve via `faster-whisper` (local, na GPU) e digita o resultado na janela ativa. Fork customizado para rodar em Linux x86_64 com Python 3.12 e GPU NVIDIA. Testado em Ubuntu 24.04 / X11 / RTX 4070.

Documentação detalhada do build/install em `docs/build-e-instalacao.md` — leia antes de mexer em empacotamento ou ambiente. Itens deferidos da revisão técnica (refator arquitetural, Wayland, testes) estão em `docs/pendencias.md` — consulte antes de reabrir um desses tópicos.

## Comandos comuns

```bash
# Dev — sempre source o venv primeiro (o activate exporta LD_LIBRARY_PATH para CUDA)
source .venv/bin/activate
python run.py

# Instalar deps (uv recomendado; pip funciona também)
uv pip install -r requirements.txt

# Linting
ruff check src/ run.py            # verifica
ruff check src/ run.py --fix      # corrige auto-fixáveis

# Build do executável standalone (~3 GB, gera dist/WhisperWriter/)
pyinstaller WhisperWriter.spec --noconfirm

# Instalar em ~/.local/share/WhisperWriter/ + atalho .desktop no menu GNOME
./install.sh

# Rodar o app instalado
~/.local/share/WhisperWriter/WhisperWriter
```

Não há suíte de testes — o smoke test prático é `python run.py` + apertar F9 num editor.

## Arquitetura

### Fluxo de runtime

`run.py` → `src/main.py:WhisperWriterApp` → loop QApplication PySide6 (Qt6) com tray icon.

Quando o usuário aperta o atalho (`F9` por padrão):

1. `src/key_listener.py:KeyListener` detecta a hotkey (via `PynputBackend` em X11)
2. `src/main.py:on_activation` dispara `src/result_thread.py:ResultThread`
3. `ResultThread` grava com `sounddevice` até detectar silêncio (usa `webrtcvad` para VAD em tempo real)
4. `src/transcription.py:transcribe_local` envia o áudio ao `faster-whisper` em `cuda`+`float16`
5. `src/main.py:on_transcription_complete` chama `src/input_simulation.py:InputSimulator.typewrite` para digitar na janela ativa

### Pontos de extensibilidade com múltiplos backends

- **`src/key_listener.py`** — abstração `InputBackend` com implementações `EvdevBackend` e `PynputBackend`. `KeyListener` herda de `QObject` e expõe `activated`/`deactivated` como PySide6 `Signal` — emissão da thread do backend cruza pra main thread Qt via `QueuedConnection` automática (elimina race em F9 duplo). `EvdevBackend.is_available()` valida permissão de fato em `/dev/input/event*` (abre e fecha um device), então `auto` não vai mais falhar silenciosamente quando o user não está no grupo `input`. Em Linux X11 o backend selecionado continua sendo `PynputBackend`.
- **`src/input_simulation.py`** — métodos: `pynput`, `clipboard`, `xdotool`, `ydotool`, `dotool`. Em Linux X11 use `xdotool` (digitação real via XTest, robusta em terminais embedded como o do VS Code). `pynput` perde caracteres em terminais. `clipboard` falha em terminais (eles usam Ctrl+Shift+V, não Ctrl+V). `InputSimulator` é `QObject` com sinal `finished`; `typewrite()` é assíncrono via `_TypingWorker(QThread)` para não congelar o event loop em frases longas com `writing_key_press_delay` alto. **Cuidado PySide6**: o worker NÃO usa `deleteLater` (o shiboken obedece de imediato e a referência Python fica apontando pra C++ destruído); em vez disso, o sinal `finished` é conectado a `_clear_worker` que zera `self._worker = None` para Python GC coletar.

### Configuração e paths

- **Schema** (read-only): `src/config_schema.yaml` — fonte de verdade dos campos válidos com defaults.
- **Config do usuário** (writable): `~/.config/WhisperWriter/config.yaml`. Lido por `src/utils.py:ConfigManager`. Salvo no menu Settings do app.
- **Validação na carga** — `ConfigManager.load_user_config()` valida cada chave contra o schema (tipo declarado e `options`). Chave desconhecida, tipo errado ou valor fora das options → warning no stdout + mantém default. Implementado por `_validated_update` + `_coerce`.
- **`src/config.yaml`** existe na pasta como artefato legado da migração — **ignorado**, não confiar nele.
- **`src/paths.py`** abstrai dois casos:
  - `resource_path('assets/...')` → resolve para repo em dev, `sys._MEIPASS` no bundle PyInstaller
  - `user_config_path()` → sempre `~/.config/WhisperWriter/config.yaml`

Sempre use esses helpers em vez de paths relativos crus, senão o bundle PyInstaller quebra.

### Lifecycle e shutdown

- **Cleanup graceful** roda via `QApplication.aboutToQuit` conectado a `WhisperWriterApp.cleanup()` (para `result_thread`, `key_listener.stop()`, `input_simulator.cleanup()`). Disparado quando o usuário escolhe "Exit" no tray (`exit_app` → `QApplication.quit()`).
- **Ctrl+C / SIGINT / SIGTERM** caem no handler default do kernel (`SIG_DFL`) — mata o processo direto. **Não tente interceptar com `signal.signal(SIGINT, custom_handler)`**: em Qt + Python o event loop bloqueia em `select()` C e o handler nunca roda; tentei `set_wakeup_fd + QSocketNotifier` e o sinal ainda não chegou no nosso ambiente. SIG_DFL resolve o "Ctrl+C trava". Threads filhas e descritores de áudio são liberados pelo OS quando o processo morre — sem vazamento prático.

### Empacotamento (PyInstaller)

- **`WhisperWriter.spec`** — entrypoint `run.py`, modo `onedir`, inclui libs CUDA dos pacotes pip `nvidia-cublas-cu12` e `nvidia-cudnn-cu12` no destino `nvidia/cublas/lib`, `nvidia/cudnn/lib`, `nvidia/cuda_nvrtc/lib`.
- **`hooks/hook-webrtcvad.py`** — hook custom obrigatório. O hook padrão do `pyinstaller-hooks-contrib` faz `copy_metadata('webrtcvad')` que falha porque o pacote distribuído chama-se `webrtcvad-wheels`. Não remova.
- **`run.py` em modo `sys.frozen`** — exporta `LD_LIBRARY_PATH` apontando para `_internal/nvidia/*/lib` para o `ctranslate2` achar `libcudnn.so.9` em runtime.

### Patch do venv para CUDA em modo dev

`.venv/bin/activate` está modificado para exportar `LD_LIBRARY_PATH` apontando para `.venv/lib/python3.12/site-packages/nvidia/{cublas,cudnn,cuda_nvrtc}/lib` quando o venv é ativado, e reverter no `deactivate`. **Se recriar o `.venv`, o patch é perdido** — o procedimento para reaplicar está em `docs/build-e-instalacao.md` (seção "Recriando o venv do zero").

## Pinagens e armadilhas conhecidas

- **`setuptools<81`** — `webrtcvad-wheels` (v2.0.11) ainda usa `pkg_resources`, removido do core em setuptools 81. O warning de deprecação na inicialização é inócuo.
- **`condition_on_previous_text: false`** em `transcription.py` — invariante. Ligar causa alucinação de repetições e transcrições vazias (sintoma típico: `Transcription completed in 0.05 seconds` com texto vazio).
- **`vad_parameters`** explícitos em `transcription.py` (`min_silence_duration_ms=500`, `speech_pad_ms=200`, `threshold=0.45`) — calibrados para não cortar começo/fim de palavras. O VAD default é agressivo demais.
- **Wayland** — `pynput` não captura hotkey global em Wayland nem digita em outras janelas. O setup atual assume X11 (verifique com `echo $XDG_SESSION_TYPE`). Para Wayland seria necessário trocar `input_method` para `ydotool` (e mexer no input_backend).
- **Detecção de sessão** (`src/session.py`) — `WhisperWriterApp.__init__` chama `enforce_session_compatibility()` logo após `ConfigManager.initialize()`. Loga `XDG_SESSION_TYPE` e a config corrente; emite warnings claros se a combinação `input_backend`/`input_method` é incompatível com a sessão (ex: `ydotool` em X11, ou qualquer config rodando em Wayland sem PortalBackend implementado). Não corrige automaticamente — só avisa cedo, antes do app falhar silenciosamente.
- **Versões de pacotes em `requirements.txt`** — bumpadas vs upstream para Python 3.12: `numpy>=1.26`, `numba>=0.59`, `llvmlite>=0.42`, `av>=12`, `aiohttp>=3.9`, `Pillow>=10`, `cffi>=1.16`, `frozenlist>=1.4.1`, `MarkupSafe>=2.1.5`, `multidict>=6.0.5`, `onnxruntime>=1.17`, `tiktoken>=0.7`. Se reduzir alguma, vai bater em "no wheel for cp312" e tentar compilar do fonte.
- **Stack faster-whisper / CUDA** — pinado em `ctranslate2>=4.5,<5`, `faster-whisper>=1.2`, `nvidia-cudnn-cu12>=9.1,<10`. Reduzir o cuDNN para 8.x quebra: o `ctranslate2 4.5+` linka contra `libcudnn.so.9`.
- **Modelo padrão** — `large-v3-turbo` (~1.6 GB VRAM, ~5x mais rápido que `large-v3` com queda de WER de ~1%). Voltar para `large-v3` é seguro mas mais lento; está nas opções do schema.
- **Qt** — usa PySide6 (Qt6, LGPL). Migração de PyQt5 feita na fase 7. Sinais usam `Signal`/`Slot` (não `pyqtSignal`/`pyqtSlot`); `QAction` vive em `PySide6.QtGui` (não `QtWidgets`); `app.exec()` (não `exec_()`). Qt6 também tem suporte Wayland melhor — relevante quando os itens #20/#21 da fase 6 forem implementados.

## Dependências do sistema

- `python3.12-dev` — para compilar `evdev` e `webrtcvad-wheels` no `pip install`
- `libportaudio2` — runtime do `sounddevice`
- `xdotool` — usado pelo `input_method: xdotool`
- `pkg-config` — usado em build

Driver NVIDIA suficiente; **não é preciso CUDA Toolkit do sistema** — usa-se `nvidia-cublas-cu12` e `nvidia-cudnn-cu12` via pip.
