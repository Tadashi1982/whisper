import fcntl
import os
import subprocess
import sys


def _acquire_single_instance_lock():
    """Garante uma única instância por user.

    Usa fcntl.flock advisory em ``$XDG_RUNTIME_DIR/whisperwriter.lock``.
    O kernel libera o lock automaticamente quando o processo morre
    (mesmo via SIGKILL), então não há lock fantasma após crash.

    Retorna o file handle (caller deve manter a referência viva durante
    toda a execução para o lock não soltar antes do tempo).
    """
    runtime_dir = os.environ.get('XDG_RUNTIME_DIR') or '/tmp'
    lock_path = os.path.join(runtime_dir, 'whisperwriter.lock')
    lock_file = open(lock_path, 'w')
    try:
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        msg = 'WhisperWriter já está rodando — verifique o tray icon.'
        print(f'[run.py] {msg} (lock: {lock_path})', file=sys.stderr)
        try:
            subprocess.run(
                ['notify-send', '-a', 'WhisperWriter',
                 'WhisperWriter já está rodando', msg],
                check=False, timeout=2.0,
            )
        except (FileNotFoundError, subprocess.TimeoutExpired):
            pass
        sys.exit(0)
    lock_file.write(str(os.getpid()))
    lock_file.flush()
    return lock_file


_INSTANCE_LOCK = _acquire_single_instance_lock()


if getattr(sys, 'frozen', False):
    base_dir = sys._MEIPASS
    # CUDA libs from bundled nvidia-* packages
    nvidia_dir = os.path.join(base_dir, 'nvidia')
    if os.path.isdir(nvidia_dir):
        extra = ':'.join([
            os.path.join(nvidia_dir, 'cublas', 'lib'),
            os.path.join(nvidia_dir, 'cudnn', 'lib'),
            os.path.join(nvidia_dir, 'cuda_nvrtc', 'lib'),
        ])
        os.environ['LD_LIBRARY_PATH'] = (
            extra + (':' + os.environ['LD_LIBRARY_PATH'] if os.environ.get('LD_LIBRARY_PATH') else '')
        )
else:
    base_dir = os.path.dirname(os.path.abspath(__file__))

src_dir = os.path.join(base_dir, 'src')
sys.path.insert(0, src_dir)

from dotenv import load_dotenv  # noqa: E402

load_dotenv()

print('Starting WhisperWriter...')

from main import WhisperWriterApp  # noqa: E402

app = WhisperWriterApp()
app.run()
