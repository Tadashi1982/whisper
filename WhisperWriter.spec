# -*- mode: python ; coding: utf-8 -*-
import os
from pathlib import Path
from PyInstaller.utils.hooks import collect_all, collect_dynamic_libs

datas = []
binaries = []
hiddenimports = []

for pkg in ('faster_whisper', 'ctranslate2', 'tokenizers', 'huggingface_hub',
            'onnxruntime', 'av'):
    d, b, h = collect_all(pkg)
    datas += d
    binaries += b
    hiddenimports += h

site = Path('.venv/lib/python3.12/site-packages/nvidia')
for sub in ('cublas', 'cudnn', 'cuda_nvrtc'):
    lib_dir = site / sub / 'lib'
    if lib_dir.is_dir():
        for so in lib_dir.iterdir():
            if so.is_file() and ('.so' in so.name):
                binaries.append((str(so), f'nvidia/{sub}/lib'))

datas += [
    ('assets', 'assets'),
    ('src/config_schema.yaml', '.'),
]

hiddenimports += [
    'pynput.keyboard._xorg',
    'pynput.mouse._xorg',
    'sounddevice',
    'soundfile',
    'numpy',
    'numba',
    'llvmlite',
    'pyperclip',
]


a = Analysis(
    ['run.py'],
    pathex=['src'],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=['hooks'],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['tkinter'],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='WhisperWriter',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon='assets/ww-logo.png',
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name='WhisperWriter',
)
