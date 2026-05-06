"""Detecção de tipo de sessão (X11/Wayland) e validação de
compatibilidade dos backends de entrada e métodos de digitação
configurados.

Este módulo não tenta corrigir nada — apenas avisa o usuário cedo
quando a combinação configurada provavelmente não vai funcionar na
sessão atual. Mensagens vão para stdout para ficar visíveis no log.
"""

import os

# Métodos de digitação por sessão.
# X11: pynput/xdotool/clipboard usam o protocolo X (XTest, XSendEvent).
# Wayland-nativo: ydotool/dotool escrevem em /dev/uinput, então funcionam
# em qualquer compositor independente de portal. clipboard em Wayland
# usa wl-copy + ydotool key ctrl+v (1 keystroke combo, robusto).
X11_INPUT_METHODS = {'pynput', 'xdotool', 'clipboard'}
WAYLAND_INPUT_METHODS = {'ydotool', 'dotool', 'clipboard'}

# Backends de captura de hotkey global.
# evdev lê /dev/input/event* abaixo do display server, então funciona em
# X11 e Wayland (assumindo permissão no grupo input).
# pynput em Wayland só captura teclas no foco da própria janela do app.
WAYLAND_INPUT_BACKENDS = {'evdev'}


def session_type() -> str:
    """Retorna o tipo de sessão em lowercase ('x11', 'wayland', 'tty', ...).

    Default 'unknown' se ``XDG_SESSION_TYPE`` não estiver setado.
    """
    return os.environ.get('XDG_SESSION_TYPE', 'unknown').lower()


def _can_open_uinput() -> bool:
    """True se o usuário consegue abrir /dev/uinput para escrita.

    ydotool/dotool dependem disso. Sem permissão, a digitação falha
    silenciosamente em sessões Wayland nativas.
    """
    try:
        fd = os.open('/dev/uinput', os.O_WRONLY | os.O_NONBLOCK)
        os.close(fd)
        return True
    except (PermissionError, FileNotFoundError, OSError):
        return False


def enforce_session_compatibility(config_manager) -> str:
    """Inspeciona a sessão e a configuração de input/output. Imprime
    avisos quando a combinação é provavelmente incompatível.

    Retorna o tipo de sessão detectado.
    """
    session = session_type()
    backend = config_manager.get_config_value('recording_options', 'input_backend')
    method = config_manager.get_config_value('post_processing', 'input_method')

    print(f'[session] XDG_SESSION_TYPE={session} input_backend={backend} input_method={method}')

    if session == 'x11':
        if method not in X11_INPUT_METHODS:
            print(
                f'[session] WARNING: input_method={method!r} é projetado para Wayland. '
                f'Em X11 use {sorted(X11_INPUT_METHODS)} (recomendado: xdotool ou clipboard). '
                f'Continuando, mas a digitação pode falhar.'
            )
    elif session == 'wayland':
        if backend == 'pynput':
            print(
                '[session] WARNING: input_backend=pynput não captura hotkey global em '
                'Wayland (só recebe teclas no foco da própria janela). Use '
                'input_backend=evdev (requer usuário no grupo input — veja '
                'docs/build-e-instalacao.md).'
            )
        if method not in WAYLAND_INPUT_METHODS:
            print(
                f'[session] WARNING: input_method={method!r} só atinge janelas XWayland '
                f'numa sessão Wayland. Use input_method=clipboard (mais robusto) ou '
                f'ydotool/dotool para digitar em janelas Wayland nativas.'
            )
        elif method in {'ydotool', 'dotool', 'clipboard'} and not _can_open_uinput():
            print(
                f'[session] WARNING: input_method={method!r} depende de /dev/uinput '
                f'(via ydotool), mas o usuário não tem permissão de escrita. Adicione-se '
                f'ao grupo input (sudo usermod -aG input $USER e relogue). Veja '
                f'docs/build-e-instalacao.md.'
            )
    else:
        print(f'[session] Tipo de sessão desconhecido ({session!r}); validação ignorada.')

    return session
