import os
import sys

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

from dotenv import load_dotenv
load_dotenv()

print('Starting WhisperWriter...')

from main import WhisperWriterApp
app = WhisperWriterApp()
app.run()
