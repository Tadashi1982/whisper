import os
import signal
import subprocess
import time

import pyperclip
from pynput.keyboard import Controller as PynputController
from pynput.keyboard import Key as PynputKey
from PySide6.QtCore import QObject, QThread, Signal

from utils import ConfigManager


class _TypingWorker(QThread):
    """Background QThread that runs the actual blocking typewrite call.

    Lives long enough for the simulator to capture its ``finished`` signal,
    then deletes itself via ``deleteLater``.
    """

    def __init__(self, simulator, text):
        super().__init__()
        self._simulator = simulator
        self._text = text

    def run(self):
        self._simulator._typewrite_sync(self._text)


class InputSimulator(QObject):
    """
    A class to simulate keyboard input using various methods.

    ``typewrite`` is asynchronous: it starts a worker thread and returns
    immediately. Listeners should connect to the ``finished`` signal to
    sequence post-typing actions.
    """

    finished = Signal()

    def __init__(self):
        """
        Initialize the InputSimulator with the specified configuration.
        """
        super().__init__()
        self.input_method = ConfigManager.get_config_value('post_processing', 'input_method')
        self.dotool_process = None
        self._worker = None
        # Runtime flag — alternável via tray menu. Inicializa do config.
        self.paste_uses_shift_v = ConfigManager.get_config_value(
            'post_processing', 'paste_uses_shift_v'
        )

        if self.input_method == 'pynput':
            self.keyboard = PynputController()
        elif self.input_method == 'clipboard':
            self.keyboard = PynputController()
        elif self.input_method == 'xdotool':
            pass
        elif self.input_method == 'dotool':
            self._initialize_dotool()

    def _initialize_dotool(self):
        """
        Initialize the dotool process for input simulation.
        """
        self.dotool_process = subprocess.Popen("dotool", stdin=subprocess.PIPE, text=True)
        assert self.dotool_process.stdin is not None

    def _terminate_dotool(self):
        """
        Terminate the dotool process if it's running.
        """
        if self.dotool_process:
            os.kill(self.dotool_process.pid, signal.SIGINT)
            self.dotool_process = None

    def typewrite(self, text):
        """Start typing ``text`` asynchronously on a worker QThread.

        Returns immediately; emits ``finished`` when the typing completes.
        """
        prev = self._worker
        if prev is not None:
            try:
                if prev.isRunning():
                    prev.wait()
            except RuntimeError:
                pass
        worker = _TypingWorker(self, text)
        worker.finished.connect(self.finished.emit)
        worker.finished.connect(self._clear_worker)
        self._worker = worker
        worker.start()

    def _clear_worker(self):
        """Drop reference to the finished worker so Python can collect it."""
        self._worker = None

    def _typewrite_sync(self, text):
        """Run the configured typing backend on the calling thread (blocking)."""
        interval = ConfigManager.get_config_value('post_processing', 'writing_key_press_delay')
        if self.input_method == 'pynput':
            self._typewrite_pynput(text, interval)
        elif self.input_method == 'clipboard':
            self._typewrite_clipboard(text)
        elif self.input_method == 'xdotool':
            self._typewrite_xdotool(text, interval)
        elif self.input_method == 'ydotool':
            self._typewrite_ydotool(text, interval)
        elif self.input_method == 'dotool':
            self._typewrite_dotool(text, interval)

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

    def _typewrite_clipboard(self, text):
        """Insere texto via clipboard + paste shortcut.

        Robusto em Wayland: o ydotool envia 1 keystroke combo (Ctrl+V),
        evitando o problema de perdas em digitação char-a-char.
        Em X11 mantém o caminho legado (pyperclip + pynput).

        ``self.paste_uses_shift_v`` é runtime (alternável pelo tray menu),
        então cada chamada lê o estado atual.
        """
        session = os.environ.get('XDG_SESSION_TYPE', '').lower()
        use_shift = self.paste_uses_shift_v
        if session == 'wayland':
            self._clipboard_paste_wayland(text, use_shift)
        else:
            self._clipboard_paste_x11(text, use_shift)

    def _clipboard_paste_wayland(self, text, use_shift):
        """wl-copy → ydotool key ctrl+v → restaura clipboard."""
        previous = None
        try:
            r = subprocess.run(
                ['wl-paste', '--no-newline'],
                capture_output=True, text=True, check=False, timeout=1.0,
            )
            if r.returncode == 0:
                previous = r.stdout
        except (FileNotFoundError, subprocess.TimeoutExpired):
            pass

        try:
            r = subprocess.run(
                ['wl-copy'], input=text, text=True, check=False, timeout=2.0,
            )
        except FileNotFoundError:
            print('[input] wl-copy não encontrado — instale wl-clipboard.')
            return
        except subprocess.TimeoutExpired:
            print('[input] wl-copy timeout.')
            return
        if r.returncode != 0:
            print(f'[input] wl-copy falhou (rc={r.returncode})')
            return

        # Pequeno delay pra clipboard manager registrar o conteúdo novo.
        time.sleep(0.05)

        combo = 'ctrl+shift+v' if use_shift else 'ctrl+v'
        try:
            r = subprocess.run(
                ['ydotool', 'key', combo],
                capture_output=True, text=True, check=False, timeout=2.0,
            )
        except FileNotFoundError:
            print('[input] ydotool não encontrado no PATH.')
            return
        except subprocess.TimeoutExpired:
            print('[input] ydotool key timeout.')
            return
        if r.returncode != 0:
            stderr = (r.stderr or '').strip()
            print(f'[input] ydotool key {combo} falhou (rc={r.returncode}): {stderr}')

        # Janela curta pra app consumir o paste antes de restaurar clipboard.
        time.sleep(0.15)

        if previous is not None:
            try:
                subprocess.run(
                    ['wl-copy'], input=previous, text=True,
                    check=False, timeout=2.0,
                )
            except (FileNotFoundError, subprocess.TimeoutExpired):
                pass

    def _clipboard_paste_x11(self, text, use_shift):
        """pyperclip (xclip/xsel) + pynput Ctrl+V (caminho legado)."""
        previous = ""
        try:
            previous = pyperclip.paste()
        except pyperclip.PyperclipException:
            pass

        pyperclip.copy(text)
        time.sleep(0.15)

        self.keyboard.press(PynputKey.ctrl)
        if use_shift:
            self.keyboard.press(PynputKey.shift)
        time.sleep(0.03)
        self.keyboard.press('v')
        time.sleep(0.03)
        self.keyboard.release('v')
        time.sleep(0.03)
        if use_shift:
            self.keyboard.release(PynputKey.shift)
        self.keyboard.release(PynputKey.ctrl)

        time.sleep(0.25)
        if previous:
            try:
                pyperclip.copy(previous)
            except pyperclip.PyperclipException:
                pass

    def _typewrite_pynput(self, text, interval):
        """
        Simulate typing using pynput.

        Args:
            text (str): The text to type.
            interval (float): The interval between keystrokes in seconds.
        """
        for char in text:
            self.keyboard.press(char)
            self.keyboard.release(char)
            time.sleep(interval)

    def _typewrite_ydotool(self, text, interval):
        """Simulate typing using ydotool.

        Em Wayland, requer ``ydotoold`` rodando + acesso a ``/dev/uinput``
        (usuário no grupo ``input`` ou udev rule). Falha de IPC apenas loga
        e retorna — não derruba o app.
        """
        try:
            delay_ms = max(1, int(float(interval) * 1000))
        except (TypeError, ValueError):
            delay_ms = 12
        safe_text = text.replace('\x00', '')
        try:
            result = subprocess.run(
                ['ydotool', 'type', '--key-delay', str(delay_ms), '--', safe_text],
                check=False,
                capture_output=True,
                text=True,
            )
        except FileNotFoundError:
            print('[input] ydotool não encontrado no PATH — instale o pacote ydotool.')
            return
        if result.returncode != 0:
            stderr = (result.stderr or '').strip()
            print(f'[input] ydotool falhou (rc={result.returncode}): {stderr}')

    def _typewrite_dotool(self, text, interval):
        """
        Simulate typing using dotool.

        Args:
            text (str): The text to type.
            interval (float): The interval between keystrokes in seconds.
        """
        assert self.dotool_process and self.dotool_process.stdin
        self.dotool_process.stdin.write(f"typedelay {interval * 1000}\n")
        self.dotool_process.stdin.write(f"type {text}\n")
        self.dotool_process.stdin.flush()

    def cleanup(self):
        """
        Perform cleanup operations, such as terminating the dotool process.
        """
        if self.input_method == 'dotool':
            self._terminate_dotool()
