"""Detecção de tipo de sessão (X11/Wayland) e validação de
compatibilidade dos backends de entrada e métodos de digitação
configurados.

Este módulo não tenta corrigir nada — apenas avisa o usuário cedo
quando a combinação configurada provavelmente não vai funcionar na
sessão atual. Mensagens vão para stdout para ficar visíveis no log.
"""

import os

X11_INPUT_METHODS = {'pynput', 'xdotool', 'clipboard'}
WAYLAND_ONLY_INPUT_METHODS = {'ydotool', 'dotool'}


def session_type() -> str:
    """Retorna o tipo de sessão em lowercase ('x11', 'wayland', 'tty', ...).

    Default 'unknown' se ``XDG_SESSION_TYPE`` não estiver setado.
    """
    return os.environ.get('XDG_SESSION_TYPE', 'unknown').lower()


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
        if method in WAYLAND_ONLY_INPUT_METHODS:
            print(
                f'[session] WARNING: input_method={method!r} é projetado para Wayland. '
                f'Em X11 use {sorted(X11_INPUT_METHODS)} (recomendado: xdotool). '
                f'Continuando, mas a digitação pode falhar.'
            )
    elif session == 'wayland':
        print(
            '[session] WARNING: WhisperWriter ainda não tem backend funcional para Wayland.\n'
            '  - Captura de hotkey global (pynput/evdev) não funciona — pynput em Wayland '
            'só captura teclas no foco da própria janela.\n'
            '  - Digitação (xdotool/pynput) não funciona fora da janela do app.\n'
            '  - input_method=ydotool requer ter o daemon ydotoold rodando e permissão '
            'em /dev/uinput.\n'
            '  - Veja docs/build-e-instalacao.md para o caminho de migração.'
        )
        if method in X11_INPUT_METHODS:
            print(
                f'[session] WARNING: input_method={method!r} não funciona em Wayland; '
                f'tente {sorted(WAYLAND_ONLY_INPUT_METHODS)}.'
            )
    else:
        print(f'[session] Tipo de sessão desconhecido ({session!r}); validação ignorada.')

    return session
