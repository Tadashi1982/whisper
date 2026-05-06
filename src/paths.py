import os
import sys


def resource_path(relative_path):
    if getattr(sys, 'frozen', False):
        base = sys._MEIPASS
    else:
        base = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
    return os.path.join(base, relative_path)


def user_config_dir():
    path = os.path.join(os.path.expanduser('~'), '.config', 'WhisperWriter')
    os.makedirs(path, exist_ok=True)
    return path


def user_config_path():
    return os.path.join(user_config_dir(), 'config.yaml')
