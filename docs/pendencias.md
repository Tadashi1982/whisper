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

## 3. Backend Wayland — Fase 6 #20 — **RESOLVIDO POR CAMINHO ALTERNATIVO**

**Plano original:** implementar `PortalBackend` via `xdg-desktop-portal GlobalShortcuts` (D-Bus async).

**O que foi feito (mai/2026):** ao tentar implementar, descobri que o **GNOME 46 (Ubuntu 24.04 default) NÃO expõe o portal `GlobalShortcuts`** — só apareceu no GNOME 48. Em vez de esperar pelo upgrade do compositor, usei o **`EvdevBackend` que já existia** no código: lê `/dev/input/event*` direto do kernel, abaixo do display server, então funciona igual em X11 e Wayland sem depender de portal nenhum.

Setup necessário (documentado em `docs/build-e-instalacao.md`):
- `sudo apt install ydotool ydotoold wl-clipboard`
- `sudo usermod -aG input $USER` + relogar
- user systemd service do `ydotoold`
- `EvdevBackend.start()` filtra devices virtuais do `ydotoold`/`dotool` para evitar feedback loop

**Quando o `PortalBackend` ainda faria sentido:** distribuição em sandbox Flatpak (que bloqueia `/dev/input/event*`), ou se o usuário não quiser/puder entrar no grupo `input`. Em GNOME 48+ vale a pena implementar como caminho "blessed" pelo padrão Wayland — fica como tarefa futura opcional.

**Referências úteis:**
- [xdg-desktop-portal GlobalShortcuts spec](https://flatpak.github.io/xdg-desktop-portal/docs/doc-org.freedesktop.portal.GlobalShortcuts.html)
- [GNOME 48 GlobalShortcuts release notes](https://ubuntuhandbook.org/index.php/2025/03/gnome-48-rc-global-shortcuts-hdr-luminance/)

---

## 4. Method `ydotool` testado — Fase 6 #21 — **RESOLVIDO**

**Status (mai/2026):** `_typewrite_ydotool` validado em sessão Wayland real. Confirmado funcionando com:
- `ydotool 0.1.8-3build1` + `ydotoold 0.1.8-3build1` (Ubuntu 24.04 universe)
- `ydotoold` rodando como user systemd service em `/tmp/.ydotool_socket`
- `/dev/uinput` acessível via ACL do systemd-logind (não precisa udev rule)

**Limitação descoberta:** o `ydotool 0.1.8` perde caracteres em rate alto (`writing_key_press_delay < 50ms`) **mesmo com daemon**. É bug do upstream 0.1.x; resolvido em 1.x. Por isso passamos a recomendar `input_method=clipboard` em Wayland (1 paste atômico em vez de N keystrokes — ver pendência nova #8 abaixo). `ydotool` continua disponível como fallback.

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

## 8. Compilar `ydotool 1.x` do source — performance Wayland

**Item:** Substituir o `ydotool 0.1.8-3build1` (Ubuntu universe, antiga e abandonada) pela versão upstream 1.x.

**Por que pode importar:** o 0.1.x perde caracteres em `--key-delay < 50ms` mesmo com daemon (limitação reconhecida do upstream antigo). Hoje contornamos com `input_method=clipboard` (1 paste atômico, sem o problema). Mas se quisermos voltar a usar `input_method=ydotool` char-a-char com performance real (delay 5-10ms) — útil em casos onde paste não rola (apps que filtram clipboard, formulários com handlers JS pesados) — precisaríamos do 1.x.

**Quando reativar:**
- Se algum app importante recusar paste e precisarmos de char-a-char rápido
- Se quisermos eliminar a dependência de `wl-clipboard` no fluxo principal
- Se outros usuários reportarem casos de uso onde clipboard não serve

**Escopo estimado:** 2-4h. Inclui: `git clone https://github.com/ReimuNotMoe/ydotool.git`, `cmake -B build`, `make -j`, `sudo make install`; ajustar systemd user service (mesmo `/usr/local/bin/ydotoold`); validar que `--key-delay 5` funciona limpo; documentar que o pacote apt não pode ser usado em paralelo.

---

## 9. Indicador da janela ativa em Wayland (auto-toggle do modo terminal)

**Item:** Detectar automaticamente se a janela em foco é um terminal e escolher Ctrl+V vs Ctrl+Shift+V sozinho, eliminando a necessidade de toggle manual via tray menu / hotkey `Ctrl+Alt+V`.

**Por que pulei:** o GNOME 46 bloqueia `org.gnome.Shell.Introspect.GetWindows` por segurança (testado: `AccessDenied`). Sem extension custom não há API estável. Alternativas:
- GNOME Shell extension custom expõe método D-Bus que retorna `wm_class` da janela ativa
- Heurística por tamanho do texto (curto = código = terminal) — frágil
- Lista hardcoded de wm_class de terminais — funciona se o usuário aceitar instalar a extension

**Mitigação atual:** toggle manual via tray menu "Modo terminal" + hotkey `Ctrl+Alt+V` + indicador visual no ícone do tray (badge `>_` quando em modo terminal). UX adequada — usuário alterna ao trocar contexto, vê confirmação imediata.

**Quando reativar:** se uso real mostrar que o toggle manual incomoda demais.

**Escopo estimado:** 1-2 dias. Escrever GNOME extension mínima (~50 linhas GJS), publicar no repo do app, documentar instalação.

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
| (próximo) | Wayland | Suporte completo Wayland: evdev + ydotool/clipboard, status window suprimida, filtro de devices virtuais do ydotoold, fix Ctrl+C com EvdevBackend (signal handler removido), tray icon dinâmico com badge `>_`, toggle Ctrl+V↔Ctrl+Shift+V via tray menu + hotkey Ctrl+Alt+V, single instance lock via fcntl, recommendation `recording_mode=hold_to_record` |
