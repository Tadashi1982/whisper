"""
Compara latência por-frame de webrtcvad (atual) vs TEN-VAD em frames sintéticos.

Critério do doc: TEN-VAD reduz pelo menos 100ms na latência fim-de-fala
sem aumentar falsos positivos. Aqui medimos:

1. Latência média por inferência (em ms)
2. Comportamento em frames de silêncio puro (todos devem retornar False/0)
3. Comportamento em frames de fala simulada (ruído branco modulado)

webrtcvad usa frames de 10/20/30 ms. TEN-VAD usa hop 10 ou 16 ms.
Para comparação justa, usamos frames de 10 ms em ambos.

Roda no venv eval (eval/.venv-eval) — depende de ten_vad + webrtcvad.
"""

import argparse
import json
import statistics
import sys
import time
from pathlib import Path

import numpy as np


def gen_silence(n_frames: int, frame_size: int) -> np.ndarray:
    """Gera silêncio puro (16-bit PCM)."""
    return np.zeros(n_frames * frame_size, dtype=np.int16)


def gen_speech(n_frames: int, frame_size: int, sr: int) -> np.ndarray:
    """Simula fala com ruído branco com envelope (modulação tipo speech)."""
    n_samples = n_frames * frame_size
    rng = np.random.default_rng(42)
    noise = rng.normal(0, 0.3, n_samples)
    # Envelope simulando picos de energia tipo fala (~5 Hz)
    t = np.arange(n_samples) / sr
    envelope = 0.5 + 0.5 * np.abs(np.sin(2 * np.pi * 5 * t))
    signal = noise * envelope
    return (signal * 32767 * 0.5).astype(np.int16)


def bench_webrtc(audio: np.ndarray, sr: int, frame_size: int, aggressiveness: int = 2):
    import webrtcvad
    vad = webrtcvad.Vad(aggressiveness)
    n_frames = len(audio) // frame_size
    latencies = []
    detections = []
    for i in range(n_frames):
        frame = audio[i * frame_size : (i + 1) * frame_size]
        t0 = time.perf_counter()
        is_speech = vad.is_speech(frame.tobytes(), sr)
        latencies.append((time.perf_counter() - t0) * 1000)  # ms
        detections.append(int(is_speech))
    return latencies, detections


def bench_ten(audio: np.ndarray, sr: int, hop_size: int):
    from ten_vad import TenVad
    vad = TenVad(hop_size=hop_size, threshold=0.5)
    n_frames = len(audio) // hop_size
    latencies = []
    detections = []
    probs = []
    for i in range(n_frames):
        frame = audio[i * hop_size : (i + 1) * hop_size]
        t0 = time.perf_counter()
        prob, flag = vad.process(frame)
        latencies.append((time.perf_counter() - t0) * 1000)
        detections.append(int(flag))
        probs.append(float(prob))
    return latencies, detections, probs


def stats(latencies):
    return {
        'mean_ms': round(statistics.mean(latencies), 4),
        'median_ms': round(statistics.median(latencies), 4),
        'p95_ms': round(sorted(latencies)[int(len(latencies) * 0.95)], 4),
        'max_ms': round(max(latencies), 4),
        'n': len(latencies),
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--out', default='eval/results/vad_bench.json')
    parser.add_argument('--sr', type=int, default=16000)
    parser.add_argument('--seconds', type=float, default=30.0)
    args = parser.parse_args()

    Path(args.out).parent.mkdir(parents=True, exist_ok=True)

    sr = args.sr
    # 30 ms = 480 samples @ 16kHz (webrtc-friendly), 10 ms = 160 samples (ten-vad)
    n_frames_30ms = int(args.seconds * 1000 / 30)
    n_frames_10ms = int(args.seconds * 1000 / 10)

    audio_silence_30 = gen_silence(n_frames_30ms, 480)
    audio_speech_30 = gen_speech(n_frames_30ms, 480, sr)
    audio_silence_10 = gen_silence(n_frames_10ms, 160)
    audio_speech_10 = gen_speech(n_frames_10ms, 160, sr)

    out = {}

    # WebRTC VAD: 30ms frames
    print('Benching webrtcvad (30ms frames)...', file=sys.stderr)
    lat_sil, det_sil = bench_webrtc(audio_silence_30, sr, 480)
    lat_sp, det_sp = bench_webrtc(audio_speech_30, sr, 480)
    out['webrtcvad_30ms'] = {
        'silence': {'latency': stats(lat_sil), 'speech_detected_pct': round(100 * sum(det_sil) / len(det_sil), 2)},
        'speech': {'latency': stats(lat_sp), 'speech_detected_pct': round(100 * sum(det_sp) / len(det_sp), 2)},
    }

    # TEN-VAD: 10ms hop (~3x mais frames pra mesma duração)
    try:
        import ten_vad  # noqa: F401
        ten_available = True
    except ImportError:
        print('ten_vad not installed; skipping. Install: pip install git+https://github.com/TEN-framework/ten-vad.git', file=sys.stderr)
        ten_available = False

    if ten_available:
        print('Benching TEN-VAD (10ms hop)...', file=sys.stderr)
        lat_sil, det_sil, probs_sil = bench_ten(audio_silence_10, sr, 160)
        lat_sp, det_sp, probs_sp = bench_ten(audio_speech_10, sr, 160)
        out['ten_vad_10ms'] = {
            'silence': {
                'latency': stats(lat_sil),
                'speech_detected_pct': round(100 * sum(det_sil) / len(det_sil), 2),
                'mean_prob': round(statistics.mean(probs_sil), 4),
            },
            'speech': {
                'latency': stats(lat_sp),
                'speech_detected_pct': round(100 * sum(det_sp) / len(det_sp), 2),
                'mean_prob': round(statistics.mean(probs_sp), 4),
            },
        }

    Path(args.out).write_text(json.dumps(out, indent=2, ensure_ascii=False))
    print(f'\nResults written to {args.out}')
    print(json.dumps(out, indent=2, ensure_ascii=False))


if __name__ == '__main__':
    main()
