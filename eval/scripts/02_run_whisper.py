"""
Roda Whisper-large-v3-turbo (faster-whisper) sobre o manifest preparado.
Saída: JSONL com hipótese + métricas (carga, inferência, RTFx, VRAM peak).

Roda no venv principal (.venv).
"""

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

import numpy as np
import soundfile as sf
from faster_whisper import WhisperModel


def gpu_used_mb():
    """Return current GPU memory used (MB) via nvidia-smi, or None if unavailable."""
    try:
        out = subprocess.check_output(
            ['nvidia-smi', '--query-gpu=memory.used', '--format=csv,nounits,noheader'],
            text=True, timeout=2,
        )
        return int(out.strip().splitlines()[0])
    except Exception:
        return None


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--manifest', default='eval/data/coraa_sample/manifest.jsonl')
    parser.add_argument('--out', default='eval/results/whisper_turbo.jsonl')
    parser.add_argument('--model', default='large-v3-turbo')
    parser.add_argument('--device', default='cuda')
    parser.add_argument('--compute-type', default='float16')
    parser.add_argument('--language', default='pt')
    args = parser.parse_args()

    Path(args.out).parent.mkdir(parents=True, exist_ok=True)

    samples = []
    with open(args.manifest) as f:
        for line in f:
            samples.append(json.loads(line))
    print(f'Loaded {len(samples)} samples from manifest', file=sys.stderr)

    vram_baseline_mb = gpu_used_mb()
    print(f'GPU baseline VRAM: {vram_baseline_mb} MB', file=sys.stderr)

    print(f'Loading {args.model} on {args.device}/{args.compute_type}...', file=sys.stderr)
    t0 = time.time()
    model = WhisperModel(args.model, device=args.device, compute_type=args.compute_type)
    load_time = time.time() - t0
    print(f'  load_time: {load_time:.1f}s', file=sys.stderr)
    vram_after_load_mb = gpu_used_mb()

    results = []
    total_audio = 0.0
    total_infer = 0.0

    for i, s in enumerate(samples):
        arr, sr = sf.read(s['audio_path'])
        if arr.dtype == np.int16:
            arr = arr.astype(np.float32) / 32768.0
        else:
            arr = arr.astype(np.float32)

        t1 = time.time()
        segs, _info = model.transcribe(
            audio=arr,
            language=args.language,
            beam_size=5,
            best_of=5,
            condition_on_previous_text=False,
            no_speech_threshold=0.6,
            compression_ratio_threshold=2.4,
            log_prob_threshold=-1.0,
            word_timestamps=False,
            vad_filter=False,
        )
        text = ''.join(seg.text for seg in segs).strip()
        infer_time = time.time() - t1

        total_audio += s['duration_secs']
        total_infer += infer_time

        results.append({
            'id': s['id'],
            'reference': s['reference'],
            'hypothesis': text,
            'duration_secs': s['duration_secs'],
            'infer_secs': round(infer_time, 4),
            'rtfx': round(s['duration_secs'] / max(infer_time, 1e-6), 2),
        })
        if (i + 1) % 10 == 0:
            print(f'  {i+1}/{len(samples)} done', file=sys.stderr)

    vram_peak_mb = gpu_used_mb()

    summary = {
        '_summary': True,
        'model': args.model,
        'device': args.device,
        'compute_type': args.compute_type,
        'n_samples': len(samples),
        'load_secs': round(load_time, 2),
        'total_audio_secs': round(total_audio, 2),
        'total_infer_secs': round(total_infer, 2),
        'overall_rtfx': round(total_audio / max(total_infer, 1e-6), 2),
        'vram_baseline_mb': vram_baseline_mb,
        'vram_after_load_mb': vram_after_load_mb,
        'vram_peak_mb': vram_peak_mb,
        'vram_model_mb': (vram_after_load_mb - vram_baseline_mb) if (vram_after_load_mb and vram_baseline_mb) else None,
    }

    with open(args.out, 'w', encoding='utf-8') as f:
        f.write(json.dumps(summary, ensure_ascii=False) + '\n')
        for r in results:
            f.write(json.dumps(r, ensure_ascii=False) + '\n')

    print(f'\nWritten {args.out}', file=sys.stderr)
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
