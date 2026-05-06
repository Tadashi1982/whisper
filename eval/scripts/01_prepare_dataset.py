"""
Streama um dataset PT-BR do HuggingFace Hub e salva ~N amostras
de áudio com transcrição-gabarito em formato pronto para benchmark.

Default: Common Voice 17 (config 'pt') — bem mantido, streamable.
Alternativas (override --dataset / --config / --split):
  - mozilla-foundation/common_voice_17_0, pt, test
  - nilc-nlp/CORAA-NURC-SP-Audio-Corpus (PT-BR espontâneo de SP)
"""

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import soundfile as sf
from datasets import load_dataset


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--out-dir', default='eval/data/ptbr_sample')
    parser.add_argument('--dataset', default='mozilla-foundation/common_voice_17_0')
    parser.add_argument('--config', default='pt')
    parser.add_argument('--split', default='test')
    parser.add_argument('--n', type=int, default=50, help='Number of samples to keep')
    parser.add_argument('--min-secs', type=float, default=4.0)
    parser.add_argument('--max-secs', type=float, default=18.0)
    parser.add_argument('--target-sr', type=int, default=16000)
    parser.add_argument('--text-key', default='sentence', help='Field name for ground-truth text')
    args = parser.parse_args()

    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)

    print(f'Streaming {args.dataset} (config={args.config}, split={args.split})...', file=sys.stderr)
    ds = load_dataset(args.dataset, args.config, split=args.split, streaming=True, trust_remote_code=True)

    manifest = []
    saved = 0
    rejected = 0
    for example in ds:
        if saved >= args.n:
            break

        audio = example.get('audio')
        text = example.get(args.text_key) or example.get('text') or example.get('sentence') or example.get('transcription')
        if audio is None or text is None:
            rejected += 1
            continue

        arr = audio.get('array')
        sr = audio.get('sampling_rate')
        if arr is None or sr is None:
            rejected += 1
            continue

        duration = len(arr) / sr
        if duration < args.min_secs or duration > args.max_secs:
            rejected += 1
            continue

        # Resample to target_sr (simple linear if needed)
        if sr != args.target_sr:
            ratio = args.target_sr / sr
            new_len = int(len(arr) * ratio)
            x = np.linspace(0, len(arr) - 1, new_len)
            arr = np.interp(x, np.arange(len(arr)), arr)
            sr = args.target_sr

        # Normalize to int16 if float
        if arr.dtype == np.float32 or arr.dtype == np.float64:
            arr = (arr * 32767).clip(-32768, 32767).astype(np.int16)

        fname = f'sample_{saved:04d}.wav'
        sf.write(out / fname, arr, sr)
        manifest.append({
            'id': saved,
            'audio_path': str(out / fname),
            'duration_secs': round(duration, 3),
            'reference': text.strip(),
        })
        saved += 1
        if saved % 10 == 0:
            print(f'  saved {saved}/{args.n}', file=sys.stderr)

    manifest_path = out / 'manifest.jsonl'
    with manifest_path.open('w', encoding='utf-8') as f:
        for entry in manifest:
            f.write(json.dumps(entry, ensure_ascii=False) + '\n')

    total_secs = sum(e['duration_secs'] for e in manifest)
    print(f'\nSaved {saved} samples ({total_secs:.1f}s total). Rejected: {rejected}.', file=sys.stderr)
    print(f'Manifest: {manifest_path}', file=sys.stderr)


if __name__ == '__main__':
    main()
