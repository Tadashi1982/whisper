"""
Gera um manifest de 1 entrada a partir do WAV do usuário + reference.txt.
Manifest é compatível com 02_run_whisper.py e 03_run_parakeet.py.

Roda no venv principal.
"""

import argparse
import json
from pathlib import Path

import soundfile as sf


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--wav', required=True, help='Path to user audio WAV')
    parser.add_argument('--reference', default='eval/data/user_sample/reference.txt')
    parser.add_argument('--out', default='eval/data/user_sample/manifest.jsonl')
    args = parser.parse_args()

    wav_path = Path(args.wav).resolve()
    if not wav_path.exists():
        raise SystemExit(f'WAV not found: {wav_path}')

    info = sf.info(wav_path)
    duration = info.frames / info.samplerate

    reference = Path(args.reference).read_text(encoding='utf-8').strip()

    entry = {
        'id': 0,
        'audio_path': str(wav_path),
        'duration_secs': round(duration, 3),
        'reference': reference,
    }

    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    with open(args.out, 'w', encoding='utf-8') as f:
        f.write(json.dumps(entry, ensure_ascii=False) + '\n')

    print(f'Manifest written: {args.out}')
    print(f'  audio: {wav_path} ({duration:.1f}s, {info.samplerate} Hz, {info.channels}ch)')
    print(f'  reference: {len(reference.split())} palavras')


if __name__ == '__main__':
    main()
