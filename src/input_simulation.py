import os
import signal
import subprocess
import time

import pyperclip
from pynput.keyboard import Controller as PynputController
from pynput.keyboard import Key as PynputKey
from PySide6.QtCore import QObject, QThread, Signal

from utils import ConfigManager


def run_command_or_exit_on_failure(command):
    """
    Run a shell command and exit if it fails.

    Args:
        command (list): The command to run as a list of strings.
    """
    try:
        subprocess.run(command, check=True)
    except subprocess.CalledProcessError as e:
        print(f"Error running command: {e}")
        exit(1)


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
        previous = ""
        try:
            previous = pyperclip.paste()
        except pyperclip.PyperclipException:
            pass

        pyperclip.copy(text)
        time.sleep(0.15)

        self.keyboard.press(PynputKey.ctrl)
        time.sleep(0.03)
        self.keyboard.press('v')
        time.sleep(0.03)
        self.keyboard.release('v')
        time.sleep(0.03)
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
        """
        Simulate typing using ydotool.

        Args:
            text (str): The text to type.
            interval (float): The interval between keystrokes in seconds.
        """
        cmd = "ydotool"
        run_command_or_exit_on_failure([
            cmd,
            "type",
            "--key-delay",
            str(interval * 1000),
            "--",
            text,
        ])

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
