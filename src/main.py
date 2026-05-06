import os
import signal
import sys

import sounddevice as sd
import soundfile as sf
from PySide6.QtCore import QObject, QProcess, Qt, QTimer
from PySide6.QtGui import QAction, QColor, QFont, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import QApplication, QMenu, QMessageBox, QSystemTrayIcon

from input_simulation import InputSimulator
from key_listener import KeyListener
from paths import resource_path
from result_thread import ResultThread
from session import enforce_session_compatibility, session_type
from transcription import create_local_model
from ui.main_window import MainWindow
from ui.settings_window import SettingsWindow
from ui.status_window import StatusWindow
from utils import ConfigManager


def play_sound(path):
    data, samplerate = sf.read(path)
    sd.play(data, samplerate)
    sd.wait()


class WhisperWriterApp(QObject):
    def __init__(self):
        """
        Initialize the application, opening settings window if no configuration file is found.
        """
        super().__init__()
        self.app = QApplication(sys.argv)
        self.app.setWindowIcon(QIcon(resource_path(os.path.join('assets', 'ww-logo.png'))))

        self.key_listener = None
        self.input_simulator = None
        self.local_model = None
        self.result_thread = None
        self.main_window = None
        self.status_window = None
        self.tray_icon = None

        ConfigManager.initialize()
        enforce_session_compatibility(ConfigManager)

        self.settings_window = SettingsWindow()
        self.settings_window.settings_closed.connect(self.on_settings_closed)
        self.settings_window.settings_saved.connect(self.restart_app)

        if ConfigManager.config_file_exists():
            self.initialize_components()
        else:
            print('No valid configuration file found. Opening settings window...')
            self.settings_window.show()

    def initialize_components(self):
        """
        Initialize the components of the application.
        """
        self.input_simulator = InputSimulator()
        self.input_simulator.finished.connect(self.on_typing_finished)

        self.key_listener = KeyListener()
        self.key_listener.add_callback("on_activate", self.on_activation)
        self.key_listener.add_callback("on_deactivate", self.on_deactivation)
        self.key_listener.terminal_toggle_pressed.connect(self._toggle_paste_mode_via_hotkey)

        model_options = ConfigManager.get_config_section('model_options')
        self.local_model = create_local_model() if not model_options.get('use_api') else None

        self.result_thread = None

        self.main_window = MainWindow()
        self.main_window.openSettings.connect(self.settings_window.show)
        self.main_window.startListening.connect(self.key_listener.start)
        self.main_window.closeApp.connect(self.exit_app)

        hide_status = ConfigManager.get_config_value('misc', 'hide_status_window')
        if not hide_status and session_type() == 'wayland':
            print(
                '[main] Status window suprimida em Wayland: mutter ignora '
                'WindowDoesNotAcceptFocus e a janela rouba foco do ydotool '
                'durante a digitação. Feedback de status vai para o tooltip '
                'do tray icon.'
            )
            hide_status = True
        if not hide_status:
            self.status_window = StatusWindow()

        self.create_tray_icon()
        self.main_window.show()

    def _make_tray_icon(self, terminal_mode):
        """Gera o QIcon do tray com badge ``>_`` quando em modo terminal.

        Renderiza num pixmap escalado (tamanho fixo) para o badge sair
        legível em qualquer DPI. Sem badge no modo editor — visualmente
        idêntico ao ícone original.
        """
        base_path = resource_path(os.path.join('assets', 'ww-logo.png'))
        size = 64
        pixmap = QPixmap(base_path).scaled(
            size, size, Qt.KeepAspectRatio, Qt.SmoothTransformation
        )
        if terminal_mode:
            painter = QPainter(pixmap)
            painter.setRenderHint(QPainter.Antialiasing)
            badge_size = int(size * 0.55)
            x = size - badge_size
            y = size - badge_size
            painter.setBrush(QColor(220, 60, 60))  # vermelho avisador
            painter.setPen(Qt.NoPen)
            painter.drawEllipse(x, y, badge_size, badge_size)
            painter.setPen(QColor(255, 255, 255))
            font = QFont('Sans', int(badge_size * 0.42), QFont.Bold)
            painter.setFont(font)
            painter.drawText(x, y, badge_size, badge_size, Qt.AlignCenter, '>_')
            painter.end()
        return QIcon(pixmap)

    def create_tray_icon(self):
        """
        Create the system tray icon and its context menu.
        """
        initial_terminal_mode = bool(
            self.input_simulator and self.input_simulator.paste_uses_shift_v
        )
        self.tray_icon = QSystemTrayIcon(self._make_tray_icon(initial_terminal_mode), self.app)

        tray_menu = QMenu()

        show_action = QAction('WhisperWriter Main Menu', self.app)
        show_action.triggered.connect(self.main_window.show)
        tray_menu.addAction(show_action)

        settings_action = QAction('Open Settings', self.app)
        settings_action.triggered.connect(self.settings_window.show)
        tray_menu.addAction(settings_action)

        # Toggle de paste shortcut: Ctrl+V (default, editores) vs
        # Ctrl+Shift+V (terminais Wayland: gnome-terminal, tilix, alacritty,
        # kitty, etc). Em GNOME Wayland não há API estável para detectar a
        # janela ativa, então o usuário alterna via tray menu conforme o
        # contexto. Só faz sentido com input_method=clipboard.
        if (
            self.input_simulator
            and ConfigManager.get_config_value('post_processing', 'input_method') == 'clipboard'
        ):
            tray_menu.addSeparator()
            self.shift_v_action = QAction('Modo terminal (Ctrl+Shift+V)', self.app)
            self.shift_v_action.setCheckable(True)
            self.shift_v_action.setChecked(self.input_simulator.paste_uses_shift_v)
            self.shift_v_action.toggled.connect(self._set_paste_uses_shift_v)
            tray_menu.addAction(self.shift_v_action)
            tray_menu.addSeparator()

        exit_action = QAction('Exit', self.app)
        exit_action.triggered.connect(self.exit_app)
        tray_menu.addAction(exit_action)

        self.tray_icon.setContextMenu(tray_menu)
        self.tray_icon.show()
        self._update_tray_status('idle')

    def _set_paste_uses_shift_v(self, checked):
        """Alterna runtime entre Ctrl+V e Ctrl+Shift+V para o paste e
        notifica visualmente (ícone do tray com badge + tooltip + balão)."""
        if self.input_simulator:
            self.input_simulator.paste_uses_shift_v = checked
            mode = 'Ctrl+Shift+V (terminal)' if checked else 'Ctrl+V (editor)'
            print(f'[main] Paste shortcut: {mode}')
            if self.tray_icon:
                self.tray_icon.setIcon(self._make_tray_icon(checked))
            self._update_tray_status('idle')  # refresca tooltip
            if self.tray_icon and self.tray_icon.isSystemTrayAvailable():
                self.tray_icon.showMessage(
                    'WhisperWriter — Modo paste',
                    f'Agora colando com {mode}.',
                    QSystemTrayIcon.Information,
                    2500,
                )

    def _toggle_paste_mode_via_hotkey(self):
        """Disparado pela hotkey ``terminal_toggle_key``; inverte o estado
        e mantém o checkbox do tray menu sincronizado."""
        if not self.input_simulator:
            return
        new_state = not self.input_simulator.paste_uses_shift_v
        if hasattr(self, 'shift_v_action') and self.shift_v_action is not None:
            # setChecked dispara o sinal toggled, que chama _set_paste_uses_shift_v.
            self.shift_v_action.setChecked(new_state)
        else:
            self._set_paste_uses_shift_v(new_state)

    def cleanup(self):
        if self.result_thread and self.result_thread.isRunning():
            self.result_thread.stop()
        if self.key_listener:
            self.key_listener.stop()
        if self.input_simulator:
            self.input_simulator.cleanup()

    def exit_app(self):
        """Quit the Qt event loop. Cleanup runs via app.aboutToQuit."""
        QApplication.quit()

    def restart_app(self):
        """Restart the application to apply the new settings."""
        QApplication.quit()
        QProcess.startDetached(sys.executable, sys.argv)

    def on_settings_closed(self):
        """
        If settings is closed without saving on first run, initialize the components with default values.
        """
        from paths import user_config_path
        if not os.path.exists(user_config_path()):
            QMessageBox.information(
                self.settings_window,
                'Using Default Values',
                'Settings closed without saving. Default values are being used.'
            )
            self.initialize_components()

    def on_activation(self):
        """
        Called when the activation key combination is pressed.
        """
        if self.result_thread and self.result_thread.isRunning():
            recording_mode = ConfigManager.get_config_value('recording_options', 'recording_mode')
            if recording_mode == 'press_to_toggle':
                self.result_thread.stop_recording()
            elif recording_mode == 'continuous':
                self.stop_result_thread()
            return

        self.start_result_thread()

    def on_deactivation(self):
        """
        Called when the activation key combination is released.
        """
        if ConfigManager.get_config_value('recording_options', 'recording_mode') == 'hold_to_record':
            if self.result_thread and self.result_thread.isRunning():
                self.result_thread.stop_recording()

    def start_result_thread(self):
        """
        Start the result thread to record audio and transcribe it.
        """
        if self.result_thread and self.result_thread.isRunning():
            return

        self.result_thread = ResultThread(self.local_model)
        if self.status_window is not None:
            self.result_thread.statusSignal.connect(self.status_window.updateStatus)
            self.status_window.closeSignal.connect(self.stop_result_thread)
        else:
            # Sem status window (típico em Wayland): feedback mínimo via tray tooltip.
            self.result_thread.statusSignal.connect(self._update_tray_status)
        self.result_thread.resultSignal.connect(self.on_transcription_complete)
        self.result_thread.start()

    def _update_tray_status(self, status):
        """Atualiza o tooltip do tray icon. Em estado idle inclui o modo
        paste atual (quando input_method=clipboard) para o usuário
        consultar o estado a qualquer momento sem abrir o tray menu."""
        if not self.tray_icon:
            return
        idle_label = 'WhisperWriter'
        if (
            self.input_simulator
            and ConfigManager.get_config_value('post_processing', 'input_method') == 'clipboard'
        ):
            mode = 'Terminal (Ctrl+Shift+V)' if self.input_simulator.paste_uses_shift_v else 'Editor (Ctrl+V)'
            idle_label = f'WhisperWriter — Modo: {mode}'
        labels = {
            'recording': 'WhisperWriter — Gravando…',
            'transcribing': 'WhisperWriter — Transcrevendo…',
            'idle': idle_label,
            'error': 'WhisperWriter — Erro',
            'cancel': idle_label,
        }
        self.tray_icon.setToolTip(labels.get(status, idle_label))

    def stop_result_thread(self):
        """
        Stop the result thread.
        """
        if self.result_thread and self.result_thread.isRunning():
            self.result_thread.stop()

    def on_transcription_complete(self, result):
        """
        Kick off async typing of the transcription. Post-typing actions
        run via ``on_typing_finished`` so the Qt event loop stays responsive
        while ``xdotool`` / ``pynput`` are sending keystrokes.

        Quando há status_window visível (X11) precisamos fechá-la antes
        de digitar e dar ao compositor um instante para passar foco de
        volta à janela anterior; em Wayland ela é suprimida no
        ``initialize_components`` e digitamos imediatamente.
        """
        if not result:
            self.on_typing_finished()
            return
        if self.status_window and self.status_window.isVisible():
            self.status_window.close()
            QTimer.singleShot(
                150,
                lambda text=result: self.input_simulator.typewrite(text),
            )
        else:
            self.input_simulator.typewrite(result)

    def on_typing_finished(self):
        """Runs on the main Qt thread after the typing worker completes."""
        if ConfigManager.get_config_value('misc', 'noise_on_completion'):
            play_sound(resource_path(os.path.join('assets', 'beep.wav')))

        if ConfigManager.get_config_value('recording_options', 'recording_mode') == 'continuous':
            self.start_result_thread()
        else:
            self.key_listener.start()

    def run(self):
        """
        Start the application.

        Restaura SIG_DFL para SIGINT/SIGTERM: o sinal mata o processo via
        kernel default. Tentar tratar via signal.signal + Python handler
        em Qt event loop é um conhecido buraco — ``app.exec()`` fica preso
        em select() do C, e Python signal handlers só rodam entre
        operações Python. Resultado: Ctrl+C trava.

        Cleanup graceful acontece via QApplication.aboutToQuit (acionado
        quando o usuário fecha pelo tray menu "Exit" → exit_app → quit).
        """
        signal.signal(signal.SIGINT, signal.SIG_DFL)
        signal.signal(signal.SIGTERM, signal.SIG_DFL)
        self.app.aboutToQuit.connect(self.cleanup)
        sys.exit(self.app.exec())


if __name__ == '__main__':
    app = WhisperWriterApp()
    app.run()
