# Pendências e itens deferidos

Itens identificados em `docs/revisao-e-melhorias.md` (mai/2026) que **não** foram implementados durante a sessão de melhorias, com motivo, escopo estimado e gatilho para reativação.

---

## 1. Refator arquitetural — Fase 5 #16

**Item:** Quebrar `WhisperWriterApp` em `RecordingController` + `AppController` (lifecycle global, tray, settings).

**Por que pulei:** refator pelo refator. `WhisperWriterApp` tem ~210 linhas hoje, todas coesas em torno do mesmo lifecycle. Não há sintoma real (bug, dificuldade de manutenção, conflito de merge) que justifique o churn de mover código entre arquivos.

**Quando reativar:**
- Se `main.py` passar de ~400 linhas
- Se for adicionar um modo de operação alternativo (ex: CLI/headless) que reuse só a parte de gravação/transcrição sem o tray Qt
- Se for fazer testes unitários do `RecordingController` separado do app

**Escopo estimado:** 1-2 dias. Criar `src/recording_controller.py` extraindo `start_result_thread`/`stop_result_thread`/`on_transcription_complete`/`on_typing_finished`; manter `WhisperWriterApp` como composição (tray, settings, restart, key_listener wiring).

---

## 2. Injeção explícita de `ConfigManager` — Fase 5 #17

**Item:** Substituir o singleton de classe (`ConfigManager._instance`) por instância passada como parâmetro a quem precisa ler config.

**Por que pulei:** o benefício declarado é testabilidade — mas **não temos testes**. Adicionar DI sem testes é só boilerplate (cada classe ganha `__init__(config)` e cada chamada ganha `self.config.get(...)`).

**Quando reativar:**
- Quando começar a escrever testes unitários (vão precisar mockar config)
- Se for criar uma segunda instância do app no mesmo processo (ex: testes de integração com configs paralelas)

**Escopo estimado:** 1 dia. Toca `utils.py`, `transcription.py`, `result_thread.py`, `input_simulation.py`, `key_listener.py`, `main.py` e as 4 windows em `ui/`.

---

## 3. Backend Wayland (`PortalBackend`) — Fase 6 #20

**Item:** Implementar backend `xdg-desktop-portal` GlobalShortcuts em `key_listener.py` para captura de hotkey global em sessões Wayland.

**Por que pulei:** este projeto roda em **X11** (`XDG_SESSION_TYPE=x11`). Implementar Wayland sem ter uma sessão Wayland pra testar é entregar código "que provavelmente funciona" — fluxo D-Bus assíncrono complexo (RequestSession → BindShortcuts → Activated signal) que pode quebrar de formas sutis sem smoke real.

**Mitigação atual:** `src/session.py:enforce_session_compatibility()` (Fase 6 #22) detecta sessão Wayland no startup e emite warning explícito sobre o que vai quebrar (hotkey + typing). Em vez de falhar silenciosamente, o usuário sabe imediatamente.

**Quando reativar:**
- Quando migrar para Ubuntu Wayland-default (Ubuntu 25.04+ usa GNOME 48 que tem GlobalShortcuts portal)
- Se distribuir o app para outros usuários e algum reportar Wayland

**Escopo estimado:** 2-3 dias. Adicionar dependência `dbus-next` (ou usar `qtdbus` que já vem com Qt6); implementar `PortalBackend(InputBackend)` com handshake D-Bus async; expor `pyqtSignal` ao detectar shortcut. Testar pelo menos em GNOME e KDE.

**Referências úteis:**
- [xdg-desktop-portal GlobalShortcuts spec](https://flatpak.github.io/xdg-desktop-portal/docs/doc-org.freedesktop.portal.GlobalShortcuts.html)
- [GNOME 48 GlobalShortcuts release notes](https://ubuntuhandbook.org/index.php/2025/03/gnome-48-rc-global-shortcuts-hdr-luminance/)

---

## 4. Method `ydotool` testado — Fase 6 #21

**Item:** Validar de fato o `input_method: ydotool` em `input_simulation.py`.

**Por que pulei:** `ydotool` requer `ydotoold` daemon rodando + permissão em `/dev/uinput` (típicamente requer adicionar usuário ao grupo `input` ou ajustar udev). Configurar tudo isso em X11 só para testar é trabalho desproporcional ao benefício imediato (X11 já funciona com `xdotool`).

**Mitigação atual:** o código `_typewrite_ydotool` existe em `input_simulation.py` mas é considerado não-validado. `enforce_session_compatibility` warns se você setar `ydotool` em X11.

**Quando reativar:**
- Junto com a migração Wayland (item 3) — `ydotool` é uma das opções de digitação em Wayland
- Se algum usuário pedir suporte oficial

**Escopo estimado:** 0.5-1 dia (assumindo que `ydotool` em si funciona). Inclui: setup de daemon + udev rule no host de testes, gravação de logs, validação de caracteres especiais (acentos, símbolos), validação de delay timing.

---

## 5. Configurações pessoais que divergem do CLAUDE.md

Não são bugs, são escolhas pessoais — mas o CLAUDE.md sugere defaults diferentes:

| Chave (`~/.config/WhisperWriter/config.yaml`) | Atual | CLAUDE.md sugere | Comentário |
|---|---|---|---|
| `model_options.local.condition_on_previous_text` | `true` | `false` (invariante) | CLAUDE.md diz que `true` causa alucinação de repetições. Se você não vê esse sintoma, deixa como está. |
| `post_processing.input_method` | `pynput` | `xdotool` | `xdotool` é mais robusto em terminais (especialmente xterm.js do VS Code). Se digitação no VS Code está OK, deixa `pynput`. |

Reativar: trocar manualmente se observar os sintomas correspondentes.

---

## 6. Suíte de testes automatizados

**Item:** Atualmente o projeto não tem testes — o smoke test prático é `python run.py` + apertar F9. Isso funcionou bem durante a sessão de melhorias mas dois bugs só apareceram em uso real:
- `_TypingWorker already deleted` (Fase 7 → fix em `d6e0a22`)
- `Ctrl+C trava` (fix em `0d9d2ce`)

**Quando reativar:** se a frequência de bugs em produção começar a doer. Os pontos prioritários para cobertura:
- `ConfigManager._validated_update` — vários casos (chave desconhecida, tipo errado, options)
- `KeyChord.update` + `is_active` — combinações com modificadores
- `enforce_session_compatibility` — cobre todos os branches X11/Wayland/desconhecido
- Smoke test E2E que carrega Whisper e transcreve um WAV de fixture

**Escopo estimado:** 2-3 dias para a primeira leva (~30 testes). Stack sugerida: `pytest` + `pytest-qt` para os bits de Qt; `tmp_path` para fixtures de config.

---

## 7. Build PyInstaller — limpeza opcional

O bundle `dist/WhisperWriter/` tem 3 GB; deste total ~700 MB são `nvidia-cudnn-cu12` (várias `.so.9` separadas: `cnn`, `adv`, `engines_*`, `graph`, `heuristic`, `ops`). É possível que algumas não sejam usadas pelo `ctranslate2` em runtime — investigar com `strace -e trace=open` durante uma transcrição revela exatamente quais `.so.9` são abertas. Se sobrar dispensável, dá pra excluir do `WhisperWriter.spec` e enxugar o bundle.

**Quando reativar:** se o tamanho do bundle virar problema (ex: distribuição para outros usuários via download).

**Escopo estimado:** 2-4h. Pode quebrar de formas sutis (uma transcrição funciona, outra não), então testar com áudios variados.

---

## Itens já feitos durante a sessão (referência)

Lista resumida do que foi implementado, por commit:

| Commit | Fase(s) | Resumo |
|---|---|---|
| `6dfd652` | 1, 2, 3 | Modelo turbo + cuDNN 9 + ctranslate2 4.7; race fixed via Signal; queue.Queue; ruff + uv |
| `5a7ebbd` | 4 | Pipeline de eval Parakeet vs Whisper-turbo (decisão: não migrar) |
| `de481ec` | 5 (#18, #19) | Validação de schema + typewrite assíncrono |
| `fcd2374` | 6 (#22) | Detecção de XDG_SESSION_TYPE + warnings |
| `0e2c533` | 7 | Migração PyQt5 → PySide6 |
| `d6e0a22` | (fix) | `_TypingWorker already deleted` regressão PySide6 |
| `0d9d2ce` | (fix) | Ctrl+C trava — SIG_DFL + cleanup via aboutToQuit |
