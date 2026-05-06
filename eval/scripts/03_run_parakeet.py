"""
Roda Parakeet-TDT 0.6B v3 (NeMo) sobre o manifest preparado.
Saída: JSONL com hipótese + métricas.

Roda no venv eval (eval/.venv-eval).
"""

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path


def gpu_used_mb():
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
    parser.add_argument('--out', default='eval/results/parakeet_v3.jsonl')
    parser.add_argument('--model', default='nvidia/parakeet-tdt-0.6b-v3')
    parser.add_argument('--device', default='cuda')
    parser.add_argument('--language', default='pt')
    parser.add_argument('--fp16', action='store_true', help='Use float16 inference')
    args = parser.parse_args()

    Path(args.out).parent.mkdir(parents=True, exist_ok=True)

    samples = []
    with open(args.manifest) as f:
        for line in f:
            samples.append(json.loads(line))
    print(f'Loaded {len(samples)} samples from manifest', file=sys.stderr)

    vram_baseline_mb = gpu_used_mb()
    print(f'GPU baseline VRAM: {vram_baseline_mb} MB', file=sys.stderr)

    print(f'Loading {args.model}...', file=sys.stderr)
    t0 = time.time()

    import nemo.collections.asr as nemo_asr
    import torch

    model = nemo_asr.models.ASRModel.from_pretrained(args.model)
    model = model.to(args.device)
    model.eval()
    if args.fp16:
        model = model.half()
    load_time = time.time() - t0
    print(f'  load_time: {load_time:.1f}s', file=sys.stderr)
    vram_after_load_mb = gpu_used_mb()

    audio_paths = [s['audio_path'] for s in samples]

    # Warmup com a primeira amostra (descartar resultado pra não enviesar)
    print('Warmup...', file=sys.stderr)
    with torch.no_grad():
        _ = model.transcribe([audio_paths[0]])

    print('Transcribing...', file=sys.stderr)
    results = []
    total_audio = 0.0
    total_infer = 0.0

    # Parakeet aceita lista mas pra medir per-sample, vou loop
    for i, s in enumerate(samples):
        t1 = time.time()
        with torch.no_grad():
            output = model.transcribe([s['audio_path']])
        infer_time = time.time() - t1

        # output[0] tem .text em NeMo recente
        item = output[0]
        if hasattr(item, 'text'):
            text = item.text
        elif isinstance(item, str):
            text = item
        else:
            text = str(item)
        text = text.strip()

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
        'fp16': args.fp16,
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
