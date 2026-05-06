# Revisão técnica e plano de melhorias — WhisperWriter

**Data:** maio/2026
**Escopo:** revisão completa do projeto após o setup customizado para Linux/Python 3.12/GPU NVIDIA, com pesquisa de tendências state-of-the-art em STT, packaging e tooling Python.

---

## Sumário executivo (TL;DR)

| # | Item | Custo | Impacto | Prioridade |
|---|---|---|---|---|
| 1 | Trocar `whisper-large-v3` → `whisper-large-v3-turbo` | 1 linha de config | ~5x menos latência, VRAM 10→6 GB | **alta** |
| 2 | Bumpar `ctranslate2 4.2.1` → `4.5+` (cuDNN 9) | ajustar spec/activate | bugs corrigidos, ganho de kernels Hopper/Ada | alta |
| 3 | Corrigir thread-safety de `on_activation` (race no F9 duplo) | refator pequeno | elimina vazamento de threads/streams de áudio | **alta (bug)** |
| 4 | Sanitizar texto antes do `xdotool type` (newline/NUL) | helper 5 linhas | evita digitação truncada silenciosa | **alta (bug)** |
| 5 | Substituir `deque(maxlen)` por `queue.Queue` no buffer de áudio | refator pequeno | elimina perda silenciosa de frames sob carga | alta |
| 6 | `EvdevBackend.is_available()` checar permissão de fato | 5 linhas | elimina armadilha do `auto` (já documentada como conhecida) | média |
| 7 | Migrar `pip+venv` → `uv` no dev workflow | ~30 min | DX 10-100x, lockfile reproduzível | média |
| 8 | Adicionar `ruff` via `pyproject.toml` | ~30 min | linting/formatação consistentes | média |
| 9 | Trocar `webrtcvad` → TEN-VAD (detecção de silêncio no ResultThread) | 1 dep + adapter | latência de fim-de-fala mais responsiva | baixa |
| 10 | Avaliar Parakeet-TDT 0.6B v3 como alternativa ao Whisper | spike de 1 dia | VRAM 6→2 GB, 20x mais rápido — mas treinado em PT-PT | spike |
| 11 | Migrar `PyQt5` → `PySide6` | ~1 dia | Wayland melhor, LGPL, futuro-proof | esperar (só se for mexer na UI) |
| 12 | Suporte Wayland (GlobalShortcuts portal + ydotool/libei) | ~3-5 dias | desbloqueia Ubuntu 25+/GNOME 48+/KDE/Hyprland | esperar (só se houver demanda) |

**Veredicto geral:** o projeto está sólido e funcional. A maior parte das melhorias são incrementos de qualidade ou ganhos óbvios de performance (large-v3-turbo). Os bugs de thread-safety e o buffer de áudio com `deque(maxlen)` são correções pontuais que valem ser feitas antes de qualquer adição de funcionalidade.

---

## 1. Diagnóstico arquitetural

### 1.1 Fluxo de runtime (uma ativação completa)

```
Tecla F9 pressionada
   │
   ├─ thread interna pynput → PynputBackend._on_keyboard_press     (key_listener.py:798)
   │     │
   │     ▼
   ├─ KeyChord.update() detecta acorde ativo                        (key_listener.py:255)
   │     │
   │     ▼
   ├─ KeyListener._trigger_callbacks("on_activate")                 (key_listener.py:406)
   │     │  ⚠ THREAD-HOP NÃO PROTEGIDO
   │     ▼
   ├─ WhisperWriterApp.on_activation()                              (main.py:132)
   │     │
   │     ▼
   ├─ start_result_thread() → ResultThread.start()                  (main.py:154)
   │     │
   │     ▼ (thread Qt do ResultThread)
   ├─ ResultThread.run() emite statusSignal('recording')            (result_thread.py:62)
   │     │
   │     ▼
   ├─ _record_audio() — sd.InputStream + webrtcvad.Vad(2)           (result_thread.py:107)
   │     │  ⚠ deque(maxlen=frame_size) pode descartar frames
   │     ▼ (bloco coletado quando silêncio detectado)
   ├─ transcribe_local() → faster_whisper.WhisperModel.transcribe   (transcription.py:47)
   │     │
   │     ▼
   ├─ resultSignal.emit(text) — fila Qt, atravessa pra main thread  (result_thread.py:98)
   │     │
   │     ▼ (main thread)
   └─ on_transcription_complete → InputSimulator.typewrite          (main.py:175)
         │
         ▼
         subprocess.run(['xdotool','type','--clearmodifiers',...])  (input_simulation.py:80)
                ⚠ bloqueia event loop Qt durante a digitação
```

### 1.2 Pontos fortes da arquitetura

- **Strategy bem aplicado** em `key_listener.py:202` (`InputBackend` ABC) e em `input_simulation.py:54` (`typewrite` despacha por `input_method`). Ambos permitem trocar implementação por config sem mexer no resto.
- **`paths.py`** (`resource_path()` / `user_config_path()`) — solução enxuta e correta para o problema de dois ambientes (dev vs PyInstaller `_MEIPASS`).
- **`KeyChord`** (`key_listener.py:245`) encapsula o estado do acorde de forma limpa, suportando modificadores via `frozenset`.
- **`BaseWindow`** (`ui/base_window.py`) elimina duplicação entre as três janelas Qt.
- **Migração de config para `~/.config/WhisperWriter/`** — XDG-compliant, sobrevive a reinstalações do bundle.

### 1.3 Pontos fracos da arquitetura

- **`WhisperWriterApp` acumula responsabilidades demais** (`main.py`): orquestra threads, gerencia ciclo do modelo, conecta sinais, cria tray, gerencia settings/restart. É o ponto de acoplamento de tudo no app.
- **`ConfigManager` é singleton de classe** (`utils.py`) com estado em variável de classe `_instance`. Todo módulo (`result_thread.py`, `input_simulation.py`, `transcription.py`) lê config diretamente em runtime — `typewrite` lê `writing_key_press_delay` a cada chamada (`input_simulation.py:66`). Isso impede testes unitários sem monkey-patching.
- **`key_listener.py` tem 963 linhas, das quais ~500 são mapeamentos de keycodes hardcoded** para os dois backends. Esses mapas deveriam ser tabelas de dados separadas, não métodos.
- **`settings_window.py`** acopla dado de domínio com apresentação ao tratar `api_key` e `model_path` por nome de chave hardcoded dentro de `create_line_edit` (`settings_window.py:136-149`).
- **`load_user_config` faz merge cego**, sem validação de tipos contra o schema (que já tem `type` e `options`). Config malformada gera erros crípticos em runtime.

### 1.4 Threading

Há três contextos simultâneos após uma ativação:

| Thread | Origem | Responsabilidade |
|---|---|---|
| Main Qt | `QApplication.exec_()` | UI, sinais Qt, `on_transcription_complete` |
| Backend | pynput interno / `threading.Thread` (evdev) | Captura de teclas |
| ResultThread | `QThread` | Gravação VAD + transcrição |

**Problema crítico:** `KeyListener._trigger_callbacks` (`key_listener.py:406`) é chamado da thread do backend e invoca `WhisperWriterApp.on_activation` diretamente, que lê e muta `self.result_thread` sem nenhum lock (`main.py:132`). Em F9 duplo rápido, duas threads podem criar dois `ResultThread`s simultâneos, com o primeiro sendo abandonado sem cleanup. Stream do `sounddevice` aberto duas vezes é comportamento indefinido.

**O padrão correto** seria emitir um `pyqtSignal` do callback (cruzando threads via fila Qt automática) em vez de chamar o método da main diretamente.

### 1.5 Trade-offs do setup customizado

| Decisão | Alternativa considerada | Por que está OK | Risco residual |
|---|---|---|---|
| Patch em `.venv/bin/activate` exportando `LD_LIBRARY_PATH` | wrapper `run-dev.sh` | mais transparente pro user que faz `source` | recriar o venv apaga o patch silenciosamente |
| `hooks/hook-webrtcvad.py` custom | renomear o pacote | nome `webrtcvad-wheels` é da distribuição, módulo é `webrtcvad` mesmo | atualização de `pyinstaller-hooks-contrib` que conserte upstream pode causar conflito |
| `xdotool` como `input_method` | `pynput.type` | pynput perde caracteres em xterm.js (terminal VS Code) | dependência de runtime no binário do sistema |
| `nvidia-cublas-cu12` + `nvidia-cudnn-cu12` via pip | CUDA Toolkit do sistema | self-contained, não precisa root | quebra silenciosa se layout dos pacotes nvidia-* mudar entre versões |

---

## 2. Bugs e issues encontrados (com confiança ≥ 80%)

### 2.1 Críticos

**#1 — Race condition em `on_activation` lendo `self.result_thread` sem lock**
`src/main.py:132-144` · severidade: **critical** · confiança: 92%

`KeyListener._trigger_callbacks` chama o método diretamente da thread do pynput. Duas teclas F9 rápidas → duas threads concorrentes em `on_activation` → dois `ResultThread` criados, primeiro abandonado, stream de áudio aberto duas vezes.

**Fix:**
- `KeyListener` deve expor um `pyqtSignal` (ex: `activated = pyqtSignal()`) e emiti-lo no lugar do callback raw.
- `WhisperWriterApp.on_activation` conecta-se a esse signal — Qt automaticamente faz thread-hop via `Qt.QueuedConnection`.

```python
# key_listener.py
class KeyListener(QObject):
    activated = pyqtSignal()
    deactivated = pyqtSignal()

    def _trigger_callbacks(self, name):
        if name == "on_activate":
            self.activated.emit()
        elif name == "on_deactivate":
            self.deactivated.emit()
```

**#2 — Texto do usuário não sanitizado antes do `xdotool type`**
`src/input_simulation.py:80-83` · severidade: **critical** · confiança: 95%

Texto contendo `\n` ou `\x00` quebra o protocolo do xdotool. Resultado: digitação truncada silenciosa, sem erro.

**Fix:**

```python
def _typewrite_xdotool(self, text, interval):
    try:
        delay_ms = max(1, int(float(interval) * 1000))
    except (TypeError, ValueError):
        delay_ms = 12
    safe_text = text.replace('\x00', '')
    subprocess.run(
        ['xdotool', 'type', '--clearmodifiers', '--delay', str(delay_ms), '--', safe_text],
        check=False,
    )
```

### 2.2 Altos

**#3 — `audio_buffer = deque(maxlen=frame_size)` descarta frames sob carga**
`src/result_thread.py:131` · severidade: **high** · confiança: 85%

`extend()` com exatamente `frame_size` elementos sobre um deque de mesmo `maxlen` funciona na primeira chamada, mas se o callback do `sounddevice` for invocado duas vezes antes do loop processar (situação real sob CPU loaded), o segundo `extend` **descarta os primeiros `frame_size` samples silenciosamente**. Sintoma: transcrições com buracos em palavras.

**Fix:** trocar por `queue.Queue` (FIFO sem perda) ou `deque` sem `maxlen` + lock.

**#4 — `EvdevBackend.is_available()` retorna True mesmo sem permissão**
`src/key_listener.py:421-427` · severidade: **high** · confiança: 97%

Já documentado no CLAUDE.md como armadilha conhecida, mas o código continua propagando o problema para qualquer usuário com `input_backend: auto`.

**Fix:**

```python
@classmethod
def is_available(cls) -> bool:
    try:
        import evdev
        devices = evdev.list_devices()
        if not devices:
            return False
        evdev.InputDevice(devices[0]).close()
        return True
    except (ImportError, PermissionError, OSError):
        return False
```

**#5 — `create_local_model` fallback para CPU com `compute_type` errado**
`src/transcription.py:36-43` · severidade: **high** · confiança: 90%

Em fallback de erro, usa o mesmo `compute_type` (ex: `float16`) que **não existe em CPU**. Se a primeira tentativa em GPU falhar, o fallback também falha sem catch, derrubando `initialize_components`. Bonus: `download_root=None if model_path else None` é tautologia (sempre `None`).

**Fix:** usar `compute_type='int8'` (único garantido em CPU) e re-lançar se falhar de novo.

**#6 — `_typewrite_dotool` não escapa newlines**
`src/input_simulation.py:150-152` · severidade: **high** · confiança: 85%

Texto com `\n` quebra o protocolo do dotool: "type olá\nmundo" vira `type olá` + comando `mundo` (rejeitado). Mesma classe de bug que o #2 mas em outro backend.

**Fix:** substituir `\n` por espaço antes de enviar ou enviar uma chamada `type` por linha.

**#7 — Loop de gravação acessa flags sem lock; `stop()` pode travar**
`src/result_thread.py:145` + `stop()` · severidade: **high** · confiança: 88%

`while self.is_running and self.is_recording:` lê sem mutex. Mais grave: a thread de gravação faz `data_ready.wait()` sem timeout. Se o dispositivo de áudio congelar (acontece em troca de device default por exemplo), `stop()` chama `self.wait()` mas a thread nunca sai do `wait()` interno — deadlock.

**Fix:** `data_ready.wait(timeout=0.5)` + verificar flags após cada timeout.

### 2.3 Médios

**#8 — `cleanup()` falha com AttributeError se settings nunca foi salvo**
`src/main.py:100-104` · severidade: **medium** · confiança: 88%

`self.key_listener` e `self.input_simulator` só existem após `initialize_components()`. Se o usuário fechar antes (Settings → fechar sem salvar → Exit no tray), AttributeError.

**Fix:** inicializar os dois como `None` no `__init__` da classe.

### 2.4 Baixo

**#9 — Docstring deslocada em `load_user_config`**
`src/utils.py:97-101` · severidade: **low** · confiança: 100%

A string `"""Load user configuration..."""` está depois de 3 linhas de código. Python não a reconhece como docstring (`help()` retorna vazio). Mover para imediatamente após `def`.

---

## 3. Tendências state-of-the-art (maio/2026)

### 3.1 Modelos STT — o ecossistema fragmentou

A era "Whisper é tudo" acabou. Em PT-BR, ranking prático em GPU 8 GB:

| Modelo | VRAM (fp16) | RTFx | WER PT (estimado) | Local? |
|---|---|---|---|---|
| `whisper-large-v3` (atual) | ~10 GB | ~30x | ~7-9% | tight em 8 GB |
| **`whisper-large-v3-turbo`** | **~6 GB** | **~150x** | ~8-10% | sim |
| `parakeet-tdt-0.6b-v3` (NVIDIA) | ~2 GB | ~3000x | ~5-7% (PT-PT melhor) | sim |
| `voxtral-mini-3b` (Mistral) | ~7 GB Q8 | ~50x | ~7% | tight |
| `canary-1b-v2` (NVIDIA) | ~3 GB | ~1000x | **sem PT** | não serve |

**Whisper-large-v3-turbo** (out/2024) é drop-in no `faster-whisper`: 4 decoder layers em vez de 32, ~6x mais rápido, queda de WER de ~1%, mantém os 99 idiomas. **É a vitória mais fácil do projeto.**

**Parakeet-TDT 0.6B v3** (set/2025) é o mais interessante a longo prazo: arquitetura RNN-T com TDT pula frames de silêncio nativamente, cabe em 2 GB VRAM, RTFx absurdo. Ressalva: foi treinado em PT-PT, não PT-BR — para ditado livre brasileiro pode perder qualidade em sotaque/giria. Vale uma spike de 1 dia para avaliar.

**Distil-Whisper** continua inglês-only — descartar para PT-BR. **Canary** não tem PT — descartar. **Voxtral-24B** não cabe em 8 GB — descartar.

### 3.2 Backends de inferência

`faster-whisper` + `ctranslate2` continua o sweet spot para desktop single-stream. Versão 1.2.1 (out/2025) bumpada de 1.0.2 que está pinada no projeto.

`ctranslate2 ≥ 4.5.0` requer **cuDNN 9 + CUDA ≥ 12.3** — migrar agora vale a pena: bugs corrigidos em decoder transducer, kernels novos para Hopper/Ada (relevante para a 4070). Custo: substituir `nvidia-cudnn-cu12==8.9.7.29` por `nvidia-cudnn-cu12>=9` no `requirements.txt`, ajustar paths no `WhisperWriter.spec` e `LD_LIBRARY_PATH` (`libcudnn.so.8` → `libcudnn.so.9`).

`whisper.cpp` ganhou suporte CUDA decente em 2025; vale se quiser fugir do stack Python+CUDA wheels. `WhisperX` usa faster-whisper por baixo + alinhamento — não serve para o caso de ditado curto. `TensorRT-LLM` extrai mais 2-3x mas exige compilar engine por GPU — overhead alto demais para desktop pessoal.

### 3.3 VAD

`Silero VAD` (usado pelo faster-whisper internamente) continua o default razoável.

`webrtcvad` (usado no `ResultThread` para detectar fim-de-fala) é funcional mas datado. **TEN-VAD** (out/2025, projeto TEN-framework) tem latência menor de transição fala→silêncio e melhor precisão em benchmarks, distribuído como ONNX leve. **Drop-in candidate** se você sentir que está demorando demais para o app perceber que você parou de falar.

### 3.4 PyQt5 vs PyQt6 vs PySide6

PyQt5 não está EOL formalmente, mas Riverbank concentra desenvolvimento em PyQt6 desde 2021. Qt5 da Qt Company saiu de LTS em 2023 — manutenção mínima.

Qt6 tem suporte Wayland substancialmente melhor (`qtwayland` mais estável, fractional scaling decente, IME).

**PySide6** (Qt Company, LGPL) é o caminho recomendado para projeto pessoal: API quase 100% idêntica ao PyQt6, custo de migração ~1 dia para um app desse tamanho (substituir imports, `pyqtSignal` → `Signal`, enums totalmente qualificados como `Qt.AlignmentFlag.AlignCenter`).

**Esperar para migrar** — só vale quando for mexer na UI ou habilitar Wayland.

### 3.5 Wayland em 2026 — finalmente viável

Mudanças de 2024-2025:

- **`xdg-desktop-portal` GlobalShortcuts**: KDE/Hyprland implementaram em 2024; **GNOME 48** (mar/2025, default no Ubuntu 25.04) tem suporte. Hoje é viável registrar hotkey global em Wayland via portal D-Bus em todos os DEs principais.
- **`libei`** (Emulated Input, freedesktop.org): sucessor moderno de uinput/ydotool, "abençoado" pelo compositor, sem daemon root. Bindings Python ainda imaturos.
- **`ydotool`/`dotool`** (uinput): caminho seguro hoje, mas exige permissão em `/dev/uinput`.
- **`wtype`**: só em compositores wlroots (Sway, Hyprland). Não funciona em GNOME/KDE.

**Plano para Wayland**: adicionar um `PortalBackend` em `key_listener.py` (D-Bus GlobalShortcuts via `dbus-next` ou `qtdbus`) e usar `ydotool` no `input_simulation.py` para Wayland. Manter `pynput` + `xdotool` como caminho X11.

### 3.6 Empacotamento Python desktop

Para app GPU com 2.9 GB de libs CUDA:

- **PyInstaller (atual)**: continua o default mais testado. Frágil mas funciona.
- **Nuitka**: build de 5-15 min vs 30s, ganho Python→C imperceptível para workload GPU-bound. **Não vale.**
- **Flatpak**: **não suporta CUDA bem**. Driver nvidia precisa bater com runtime, complicado para usuário final. **Ignorar.**
- **AppImage**: viável tecnicamente; resultado similar ao PyInstaller `onedir` empacotado em squashfs. Vale para distribuir um arquivo único.
- **Briefcase (BeeWare)**: focado no Toga GUI. Overhead sem ganho para Qt+CUDA.

**Recomendação:** manter PyInstaller. Se for distribuir mais largo, gerar um `.AppImage` por cima do `dist/` (`appimagetool` é simples).

### 3.7 Tooling Python — stack 2026

- **`uv`** (Astral, agora OpenAI): substitui `pip + venv + pip-tools + pyenv`. 10-100x mais rápido. Lockfile universal compatível. **Vale migrar agora**: `uv venv`, `uv pip install -r requirements.txt`, `uv lock`.
- **`ruff`**: substitui `flake8 + black + isort + pyupgrade`. 10-100x mais rápido. Drop-in via `pyproject.toml`.
- **`pyproject.toml`** (PEP 621): formato canônico, todos os tools modernos leem dele.

Migrar para `uv` + adicionar `ruff` em um `pyproject.toml` mínimo é ~30 min de trabalho com ganho permanente em DX.

---

## 4. Plano de melhorias priorizado

### Fase 1 — Correções e ganhos imediatos (2-4 horas)

1. **`whisper-large-v3` → `whisper-large-v3-turbo`** no `config.yaml`. Validar com smoke test. Drop-in.
2. **Bumpar `ctranslate2` para 4.5+** e `nvidia-cudnn-cu12` para v9. Ajustar `WhisperWriter.spec` (path `cudnn/lib` continua, mas as libs são `.so.9` agora) e `run.py:8-15` (ainda aponta para `cudnn/lib`, OK). Pinagem certa: `nvidia-cudnn-cu12>=9.1,<10` + `ctranslate2>=4.5,<5` + `faster-whisper>=1.2`.
3. **Sanitizar texto antes do `xdotool type`** (issue #2 acima).
4. **Substituir `deque(maxlen)` por `queue.Queue`** no `audio_buffer` (issue #3).
5. **Inicializar `key_listener=None` e `input_simulator=None`** no `WhisperWriterApp.__init__` (issue #8).
6. **Mover docstring** em `load_user_config` (issue #9).
7. **Corrigir fallback CPU em `create_local_model`** com `compute_type='int8'` (issue #5).

### Fase 2 — Refator de thread-safety (1 dia)

8. **`KeyListener` herdar de `QObject` e expor `activated`/`deactivated` como `pyqtSignal`** em vez de chamar callbacks raw da thread do pynput (issue #1). Isso é a correção mais impactante para estabilidade.
9. **`EvdevBackend.is_available()`** validar permissão de fato (issue #4).
10. **`ResultThread.stop()` com timeout** no `data_ready.wait()` (issue #7).

### Fase 3 — Modernização do tooling (1 dia)

11. Migrar para **`uv`** mantendo `requirements.txt` como entrada (substituir `pip install` por `uv pip install` no fluxo dev e na doc). Considerar `uv lock` e commitar `uv.lock` para reproducibilidade.
12. Adicionar **`pyproject.toml`** mínimo com `[tool.ruff]` e rodar `ruff check src/ run.py`. Corrigir o fácil; ignorar regras estilísticas que não agregam.
13. Atualizar `docs/build-e-instalacao.md` e `CLAUDE.md` com o novo workflow.

### Fase 4 — Avaliação de modelos alternativos (1-2 dias, spike)

14. **Spike Parakeet-TDT 0.6B v3 em PT-BR**: criar um script que transcreve 30 min de áudio variado (entrevistas, noticiários, ditado de email) e mede WER vs `whisper-large-v3-turbo`. Critério de migração: WER <= turbo + 1% absoluto.
15. **Spike TEN-VAD vs webrtcvad** no `ResultThread`: medir latência fim-de-fala em 50 frases com pausas naturais. Critério: TEN-VAD reduz pelo menos 100ms na latência sem aumentar falsos positivos de fim-de-fala.

### Fase 5 — Refatoração arquitetural (2-3 dias, opcional)

16. Quebrar `WhisperWriterApp` em `RecordingController` + `AppController` (lifecycle global, tray, settings).
17. Mover `ConfigManager` para injeção explícita (passar instância de `Config` como parâmetro a quem precisa ler).
18. Mover digitação de texto para thread separada (evitar congelar event loop Qt em frases longas com delay alto).
19. Validação de config contra schema em `load_user_config`.

### Fase 6 — Suporte Wayland (3-5 dias, opcional, sob demanda)

20. Adicionar `PortalBackend` em `key_listener.py` usando `xdg-desktop-portal` GlobalShortcuts.
21. Adicionar `input_method: ydotool` testado de fato (atualmente está implementado mas nunca foi exercitado neste projeto).
22. Implementar detecção de sessão (`XDG_SESSION_TYPE`) no `WhisperWriterApp.__init__` e forçar backends compatíveis automaticamente.

### Fase 7 — Migração para Qt6 (2-3 dias, opcional)

23. PyQt5 → PySide6. Dependência indireta da Fase 6 — Qt6 tem Wayland substancialmente melhor.

---

## 5. O que NÃO vale fazer

- **Migrar para Nuitka** — build lento, ganho irrelevante para workload GPU-bound.
- **Empacotar via Flatpak** — CUDA não funciona bem.
- **Adotar Voxtral 24B** — não cabe em 8 GB.
- **Adotar Distil-Whisper** — inglês-only.
- **Adotar Canary** — sem suporte a PT.
- **Trocar `xdotool` no X11** — continua sendo o padrão e funciona bem.
- **Migrar para `keyboard` lib** — exige root no Linux, regressão.

---

## 6. Riscos e mitigações

| Risco | Probabilidade | Mitigação |
|---|---|---|
| Migração para `large-v3-turbo` deteriora qualidade em PT-BR específico do usuário | baixa | manter possibilidade de voltar trocando `model:` no config |
| Bump de `ctranslate2` 4.2.1 → 4.5+ quebra runtime | baixa | testar com smoke test antes de empacotar |
| Refator de thread-safety com `pyqtSignal` introduz regressão | média | adicionar teste manual de F9 duplo-pressionado antes/depois |
| Spike Parakeet em PT-BR mostra WER pior — desperdício de tempo | média | timeboxar a 1 dia; se inconclusivo, descartar |
| `uv` não cobre algum caso edge do `requirements.txt` atual | baixa | manter `pip` como fallback documentado |

---

## 7. Próximos passos sugeridos

1. Implementar **Fase 1** integralmente em uma única sessão (todos são changes pequenos e independentes; não vale dividir em PRs separados).
2. Implementar **Fase 2** numa segunda sessão, com testes manuais focados em estabilidade.
3. Decidir caso a caso sobre Fases 3-7 conforme prioridade do usuário.

---

## 8. Fontes consultadas

Modelos e benchmarks:
- [openai/whisper-large-v3-turbo · Hugging Face](https://huggingface.co/openai/whisper-large-v3-turbo)
- [nvidia/parakeet-tdt-0.6b-v3 · Hugging Face](https://huggingface.co/nvidia/parakeet-tdt-0.6b-v3)
- [Canary-1B-v2 & Parakeet-TDT-0.6B-v3 paper (arXiv 2509.14128)](https://arxiv.org/abs/2509.14128)
- [Voxtral — Mistral AI](https://mistral.ai/news/voxtral)
- [Best open source STT model in 2026 — Northflank](https://northflank.com/blog/best-open-source-speech-to-text-stt-model-in-2026-benchmarks)

Inferência:
- [SYSTRAN/faster-whisper](https://github.com/SYSTRAN/faster-whisper)
- [CUDNN 9 support · OpenNMT/CTranslate2 #1780](https://github.com/OpenNMT/CTranslate2/issues/1780)

VAD:
- [TEN-framework/ten-vad](https://github.com/TEN-framework/ten-vad)
- [snakers4/silero-vad](https://github.com/snakers4/silero-vad)

Qt/Wayland:
- [PyQt6 vs PySide6 Licensing — pythonguis](https://www.pythonguis.com/faq/pyqt6-vs-pyside6/)
- [GNOME 48 RC Released with Global Shortcuts — UbuntuHandbook](https://ubuntuhandbook.org/index.php/2025/03/gnome-48-rc-global-shortcuts-hdr-luminance/)
- [xdg-desktop-portal-hyprland — Hyprland Wiki](https://wiki.hypr.land/Hypr-Ecosystem/xdg-desktop-portal-hyprland/)

Tooling:
- [astral-sh/uv](https://github.com/astral-sh/uv)
- [Ruff docs — Astral](https://docs.astral.sh/ruff/)
- [PyInstaller vs Nuitka 2026 — AhmedSyntax](https://ahmedsyntax.com/2026-comparison-pyinstaller-vs-cx-freeze-vs-nui/)
- [Flatpak Is Not the Future (CUDA limitations)](https://ludocode.com/blog/flatpak-is-not-the-future)
