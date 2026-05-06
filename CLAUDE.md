# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Visão geral

WhisperWriter — app de speech-to-text que grava do microfone com um atalho global, transcreve via `faster-whisper` (local, na GPU) e insere o resultado na janela ativa. Fork customizado para rodar em Linux x86_64 com Python 3.12 e GPU NVIDIA. Testado em Ubuntu 24.04 / RTX 4070, sessões **X11 e Wayland (GNOME 46/mutter)**.

Documentação detalhada do build/install em `docs/build-e-instalacao.md` — leia antes de mexer em empacotamento ou ambiente. Itens deferidos da revisão técnica estão em `docs/pendencias.md` — consulte antes de reabrir um desses tópicos.

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

`run.py` → adquire single-instance lock (`fcntl.flock` em `$XDG_RUNTIME_DIR/whisperwriter.lock`) → `src/main.py:WhisperWriterApp` → loop QApplication PySide6 (Qt6) com tray icon.

Quando o usuário aperta o atalho (`F9` por padrão):

1. `src/key_listener.py:KeyListener` detecta a hotkey (via `EvdevBackend` em Wayland, `PynputBackend` em X11)
2. `src/main.py:on_activation` dispara `src/result_thread.py:ResultThread`
3. `ResultThread` grava com `sounddevice` até `recording_mode` indicar parada (silêncio VAD em `voice_activity_detection`/`continuous`, soltar tecla em `hold_to_record`, novo press em `press_to_toggle`)
4. `src/transcription.py:transcribe_local` envia o áudio ao `faster-whisper` em `cuda`+`float16`
5. `src/main.py:on_transcription_complete` chama `src/input_simulation.py:InputSimulator.typewrite` para inserir o texto na janela ativa

### Pontos de extensibilidade com múltiplos backends

- **`src/key_listener.py`** — abstração `InputBackend` com implementações `EvdevBackend` e `PynputBackend`. `KeyListener` herda de `QObject` e expõe `activated`/`deactivated`/`terminal_toggle_pressed` como PySide6 `Signal` — emissão da thread do backend cruza pra main thread Qt via `QueuedConnection` automática (elimina race em F9 duplo). `EvdevBackend.is_available()` valida permissão de fato em `/dev/input/event*` (abre e fecha um device). **`EvdevBackend.start()` filtra devices virtuais** com nome contendo `ydotoold`/`dotool`: ler suas próprias keystrokes injetadas cria backpressure que corrompe a digitação. **Não instala signal handlers próprios** (signal.signal Python sobrescreve o SIG_DFL de `main.py` e Qt event loop fica preso em select() C — Ctrl+C trava). Suporta um 2º chord opcional (`terminal_toggle_key` na config) para alternar paste mode em runtime. Em Wayland o backend selecionado é `EvdevBackend`; em X11 funciona qualquer um (default `PynputBackend`).
- **`src/input_simulation.py`** — métodos: `pynput`, `clipboard`, `xdotool`, `ydotool`, `dotool`. Recomendações:
  - **Wayland: `clipboard`** (mais robusto). Usa `wl-copy` + `ydotool key ctrl+v` — 1 keystroke combo atômico, sem perda de char, sem janela pra "perder foco no meio". A flag runtime `paste_uses_shift_v` alterna pra Ctrl+Shift+V (terminais Wayland nativos: gnome-terminal, tilix, alacritty, kitty). Toggle via tray menu "Modo terminal" ou hotkey `terminal_toggle_key` (default `ctrl+alt+v`).
  - **Wayland: `ydotool`** (alternativa). Char-a-char via `/dev/uinput`. Em alta velocidade (delay < 50ms) o `ydotool 0.1.8` do Ubuntu 24.04 perde caracteres mesmo com daemon — limitação da versão. Mantido por compatibilidade e como fallback.
  - **X11: `xdotool`** (recomendado, digitação real via XTest, robusto em xterm.js do VS Code).
  - `pynput` perde caracteres em terminais e não captura/digita global em Wayland.
  - `_typewrite_clipboard` faz split por sessão: `_clipboard_paste_wayland` (wl-copy + ydotool key) e `_clipboard_paste_x11` (pyperclip + pynput).
  - `InputSimulator` é `QObject` com sinal `finished`; `typewrite()` é assíncrono via `_TypingWorker(QThread)` para não congelar o event loop. **Cuidado PySide6**: o worker NÃO usa `deleteLater` (o shiboken obedece de imediato e a referência Python fica apontando pra C++ destruído); em vez disso, o sinal `finished` é conectado a `_clear_worker` que zera `self._worker = None` para Python GC coletar.
- **`src/main.py:WhisperWriterApp`** — em Wayland **suprime `StatusWindow`** automaticamente (ver "Lifecycle e shutdown") e usa o tooltip do tray icon (`_update_tray_status`) como feedback alternativo. Tray menu inclui toggle "Modo terminal (Ctrl+Shift+V)" quando `input_method=clipboard`, sincronizado bidirecionalmente com a hotkey `terminal_toggle_key` via `_toggle_paste_mode_via_hotkey`. **Indicador visual no ícone do tray**: `_make_tray_icon(terminal_mode)` desenha em runtime uma badge vermelha `>_` no canto inferior do logo quando o modo terminal está ativo (sem assets extras — usa QPainter sobre `assets/ww-logo.png`). A troca dispara também um balão de notificação via `tray_icon.showMessage`.

### Configuração e paths

- **Schema** (read-only): `src/config_schema.yaml` — fonte de verdade dos campos válidos com defaults.
- **Config do usuário** (writable): `~/.config/WhisperWriter/config.yaml`. Lido por `src/utils.py:ConfigManager`. Salvo no menu Settings do app.
- **Validação na carga** — `ConfigManager.load_user_config()` valida cada chave contra o schema (tipo declarado e `options`). Chave desconhecida, tipo errado ou valor fora das options → warning no stdout + mantém default. Implementado por `_validated_update` + `_coerce`.
- **`src/config.yaml`** existe na pasta como artefato legado da migração — **ignorado**, não confiar nele.
- **`src/paths.py`** abstrai dois casos:
  - `resource_path('assets/...')` → resolve para repo em dev, `sys._MEIPASS` no bundle PyInstaller
  - `user_config_path()` → sempre `~/.config/WhisperWriter/config.yaml`

Sempre use esses helpers em vez de paths relativos crus, senão o bundle PyInstaller quebra.

### Single instance

`run.py:_acquire_single_instance_lock()` adquire um lock advisory via `fcntl.flock(LOCK_EX | LOCK_NB)` em `$XDG_RUNTIME_DIR/whisperwriter.lock` (fallback `/tmp` se a env var não estiver setada). Se já há instância rodando, imprime no stderr e dispara `notify-send` (best effort) avisando o usuário, então `sys.exit(0)`. O lock é liberado pelo kernel quando o processo morre — mesmo SIGKILL — então não há lock fantasma após crash. O file handle é mantido em `_INSTANCE_LOCK` (módulo-global) para a referência não ser garbage-collected antes da hora.

### Lifecycle e shutdown

- **Cleanup graceful** roda via `QApplication.aboutToQuit` conectado a `WhisperWriterApp.cleanup()` (para `result_thread`, `key_listener.stop()`, `input_simulator.cleanup()`). Disparado quando o usuário escolhe "Exit" no tray (`exit_app` → `QApplication.quit()`).
- **Ctrl+C / SIGINT / SIGTERM** caem no handler default do kernel (`SIG_DFL`) — mata o processo direto. **Não tente interceptar com `signal.signal(SIGINT, custom_handler)`**: em Qt + Python o event loop bloqueia em `select()` C e o handler nunca roda; tentei `set_wakeup_fd + QSocketNotifier` e o sinal ainda não chegou no nosso ambiente. SIG_DFL resolve o "Ctrl+C trava". Threads filhas e descritores de áudio são liberados pelo OS quando o processo morre — sem vazamento prático. **Atenção**: o `EvdevBackend.start()` antigo instalava signal handlers Python que sobrescreviam esse SIG_DFL — foi removido (ver `_setup_signal_handler` no histórico do `key_listener.py`). Se reintroduzir, Ctrl+C trava de novo.

### Status window e foco em Wayland

- **`StatusWindow`** (`src/ui/status_window.py`) usa `Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool | Qt.WindowDoesNotAcceptFocus` + `WA_ShowWithoutActivating`. Em **X11** funciona normal (não rouba foco). Em **Wayland/mutter** essas hints são ignoradas — a janela top-level rouba foco, e em modo `continuous`+`ydotool` ela reaparece a cada nova gravação no meio da digitação anterior, corrompendo o texto.
- **Mitigação**: `WhisperWriterApp.initialize_components` força `hide_status_window=True` quando `session_type() == 'wayland'` e migra o feedback de status para o tooltip do tray icon. Em X11 a janela continua visível como antes.
- O delay de 150ms no `on_transcription_complete` (entre `status_window.close()` e `typewrite`) só roda quando há status_window visível — caminho X11.

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
- **Wayland** — funciona com `input_backend=evdev` (lê `/dev/input/event*`, requer usuário no grupo `input`) + `input_method=clipboard` ou `ydotool` (ambos requerem `/dev/uinput` acessível, tipicamente via ACL do systemd-logind). `pynput` não captura hotkey global em Wayland nem digita em outras janelas — só funciona em XWayland. Setup completo em `docs/build-e-instalacao.md`.
- **`ydotool 0.1.8` (Ubuntu 24.04)** — versão antiga (2018), abandonada em favor da 1.x. Sem o daemon `ydotoold` reabre `/dev/uinput` por chamada e perde keystrokes em alta velocidade. Com daemon ainda corrompe quando `--key-delay < 50ms` (limite do mutter consumir eventos). **Por isso `clipboard` é o método preferido em Wayland**: 1 paste atômico em vez de N keystrokes. Pra char-a-char rápido, compilar `ydotool 1.x` do source resolve.
- **Detecção de sessão** (`src/session.py`) — `WhisperWriterApp.__init__` chama `enforce_session_compatibility()` logo após `ConfigManager.initialize()`. Loga `XDG_SESSION_TYPE` e a config corrente; emite warnings claros se a combinação `input_backend`/`input_method` é incompatível (ex: `ydotool` em X11, `pynput` em Wayland, ou método `ydotool/dotool/clipboard` sem permissão em `/dev/uinput`). `clipboard` é válido em ambas sessões. Não corrige automaticamente — só avisa cedo.
- **Versões de pacotes em `requirements.txt`** — bumpadas vs upstream para Python 3.12: `numpy>=1.26`, `numba>=0.59`, `llvmlite>=0.42`, `av>=12`, `aiohttp>=3.9`, `Pillow>=10`, `cffi>=1.16`, `frozenlist>=1.4.1`, `MarkupSafe>=2.1.5`, `multidict>=6.0.5`, `onnxruntime>=1.17`, `tiktoken>=0.7`. Se reduzir alguma, vai bater em "no wheel for cp312" e tentar compilar do fonte.
- **Stack faster-whisper / CUDA** — pinado em `ctranslate2>=4.5,<5`, `faster-whisper>=1.2`, `nvidia-cudnn-cu12>=9.1,<10`. Reduzir o cuDNN para 8.x quebra: o `ctranslate2 4.5+` linka contra `libcudnn.so.9`.
- **Modelo padrão** — `large-v3-turbo` (~1.6 GB VRAM, ~5x mais rápido que `large-v3` com queda de WER de ~1%). Voltar para `large-v3` é seguro mas mais lento; está nas opções do schema.
- **Qt** — usa PySide6 (Qt6, LGPL). Migração de PyQt5 feita na fase 7. Sinais usam `Signal`/`Slot` (não `pyqtSignal`/`pyqtSlot`); `QAction` vive em `PySide6.QtGui` (não `QtWidgets`); `app.exec()` (não `exec_()`). Qt6 também tem suporte Wayland melhor — relevante quando os itens #20/#21 da fase 6 forem implementados.

## Dependências do sistema

Comuns:
- `python3.12-dev` — para compilar `evdev` e `webrtcvad-wheels` no `pip install`
- `libportaudio2` — runtime do `sounddevice`
- `pkg-config` — usado em build

X11:
- `xdotool` — usado pelo `input_method: xdotool`

Wayland (GNOME mutter):
- `ydotool` + `ydotoold` (daemon) — usado pelo `input_method: clipboard` (envia 1 Ctrl+V) e pelo `input_method: ydotool` (char-a-char). O `ydotoold` é pacote separado no Ubuntu.
- `wl-clipboard` (provê `wl-copy`/`wl-paste`) — usado pelo `input_method: clipboard` em Wayland.
- Usuário no grupo `input` (`sudo usermod -aG input $USER` + relogar) — para `EvdevBackend` ler `/dev/input/event*`.
- `/dev/uinput` acessível pelo user — geralmente já vem via ACL do systemd-logind em sessões desktop modernas.
- `ydotoold` rodando como user systemd service (não system-wide).

Driver NVIDIA suficiente; **não é preciso CUDA Toolkit do sistema** — usa-se `nvidia-cublas-cu12` e `nvidia-cudnn-cu12` via pip.
