"""
Lê os JSONL de Whisper-turbo e Parakeet, calcula WER por amostra e
agregado, e gera um relatório markdown.

Roda no venv principal (.venv) ou no eval — só precisa de jiwer.
"""

import argparse
import json
import re
import sys
import unicodedata
from pathlib import Path

from jiwer import process_words


def normalize(text: str) -> str:
    """Normalização padrão para WER em PT-BR:
    - lowercase
    - remove pontuação
    - colapsa espaços
    - mantém acentos (são fonéticos em PT)
    """
    text = text.lower()
    # Remove punctuation but keep letters/numbers/space/accents
    text = re.sub(r'[^\w\sÀ-ɏ]', ' ', text, flags=re.UNICODE)
    # Collapse whitespace
    text = re.sub(r'\s+', ' ', text).strip()
    return text


def normalize_no_accents(text: str) -> str:
    """Normalização agressiva (sem acentos) — útil pra comparar modelos
    que tratam acentuação de forma diferente."""
    text = normalize(text)
    text = unicodedata.normalize('NFD', text)
    text = ''.join(c for c in text if not unicodedata.combining(c))
    return text


def load_results(path: Path):
    summary = None
    rows = []
    with path.open() as f:
        for line in f:
            obj = json.loads(line)
            if obj.get('_summary'):
                summary = obj
            else:
                rows.append(obj)
    return summary, rows


def aggregate(rows, normalizer):
    refs = [normalizer(r['reference']) for r in rows]
    hyps = [normalizer(r['hypothesis']) for r in rows]
    out = process_words(refs, hyps)
    return {
        'wer': out.wer,
        'mer': out.mer,
        'wil': out.wil,
        'substitutions': out.substitutions,
        'deletions': out.deletions,
        'insertions': out.insertions,
        'hits': out.hits,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--whisper', default='eval/results/whisper_turbo.jsonl')
    parser.add_argument('--parakeet', default='eval/results/parakeet_v3.jsonl')
    parser.add_argument('--out', default='eval/results/report.md')
    args = parser.parse_args()

    paths = [Path(args.whisper), Path(args.parakeet)]
    labels = ['whisper-large-v3-turbo', 'parakeet-tdt-0.6b-v3']

    if not all(p.exists() for p in paths):
        missing = [str(p) for p in paths if not p.exists()]
        print(f'Missing input files: {missing}', file=sys.stderr)
        sys.exit(1)

    md = ['# Resultados da spike — Parakeet vs Whisper-turbo (PT-BR)\n']
    md.append('Critério do doc: migra se `WER(parakeet) <= WER(whisper) + 1% absoluto`.\n')

    summaries = []
    rowsets = []
    for p in paths:
        s, r = load_results(p)
        summaries.append(s)
        rowsets.append(r)

    # --- Tabela de performance ---
    md.append('## Performance\n')
    md.append('| Métrica | Whisper-turbo | Parakeet v3 |')
    md.append('|---|---|---|')
    md.append(f'| Load time (s) | {summaries[0]["load_secs"]} | {summaries[1]["load_secs"]} |')
    md.append(f'| Total audio (s) | {summaries[0]["total_audio_secs"]} | {summaries[1]["total_audio_secs"]} |')
    md.append(f'| Total infer (s) | {summaries[0]["total_infer_secs"]} | {summaries[1]["total_infer_secs"]} |')
    md.append(f'| Overall RTFx | {summaries[0]["overall_rtfx"]} | {summaries[1]["overall_rtfx"]} |')
    md.append(f'| VRAM model (MB) | {summaries[0].get("vram_model_mb")} | {summaries[1].get("vram_model_mb")} |')
    md.append(f'| VRAM peak (MB) | {summaries[0].get("vram_peak_mb")} | {summaries[1].get("vram_peak_mb")} |')
    md.append('')

    # --- WER agregado, com e sem acentos ---
    md.append('## WER agregado\n')
    md.append('| Modelo | WER (com acentos) | WER (sem acentos) | MER | WIL |')
    md.append('|---|---|---|---|---|')
    wers_per_model = []
    for label, rows in zip(labels, rowsets, strict=False):
        agg_with = aggregate(rows, normalize)
        agg_no = aggregate(rows, normalize_no_accents)
        md.append(f'| {label} | {agg_with["wer"]:.4f} | {agg_no["wer"]:.4f} | {agg_with["mer"]:.4f} | {agg_with["wil"]:.4f} |')
        wers_per_model.append((label, agg_with['wer'], agg_no['wer']))
    md.append('')

    md.append('## Decisão (critério do doc)\n')
    delta_with = wers_per_model[1][1] - wers_per_model[0][1]
    delta_no = wers_per_model[1][2] - wers_per_model[0][2]
    md.append(f'- ΔWER (com acentos): Parakeet − Whisper = **{delta_with:+.4f}** ({delta_with*100:+.2f} pp)')
    md.append(f'- ΔWER (sem acentos): Parakeet − Whisper = **{delta_no:+.4f}** ({delta_no*100:+.2f} pp)')
    threshold = 0.01
    decision_with = 'MIGRAR' if delta_with <= threshold else 'NÃO migrar'
    decision_no = 'MIGRAR' if delta_no <= threshold else 'NÃO migrar'
    md.append(f'- Critério (≤ +1.00 pp): com acentos → **{decision_with}** | sem acentos → **{decision_no}**')
    md.append('')

    # --- Erros qualitativos ---
    md.append('## Comparação qualitativa (5 amostras com maior divergência)\n')
    rows_w, rows_p = rowsets
    by_id_w = {r['id']: r for r in rows_w}
    by_id_p = {r['id']: r for r in rows_p}
    deltas = []
    for i in by_id_w:
        if i not in by_id_p:
            continue
        ref = normalize(by_id_w[i]['reference'])
        hw = normalize(by_id_w[i]['hypothesis'])
        hp = normalize(by_id_p[i]['hypothesis'])
        wer_w = process_words([ref], [hw]).wer
        wer_p = process_words([ref], [hp]).wer
        deltas.append((abs(wer_w - wer_p), i, ref, by_id_w[i]['hypothesis'], by_id_p[i]['hypothesis'], wer_w, wer_p))

    deltas.sort(reverse=True)
    for delta, i, ref, hw, hp, wer_w, wer_p in deltas[:5]:
        md.append(f'### Amostra {i} (Δ={delta:.3f})')
        md.append(f'- **Ref:** {ref}')
        md.append(f'- **Whisper** ({wer_w:.3f}): {hw}')
        md.append(f'- **Parakeet** ({wer_p:.3f}): {hp}')
        md.append('')

    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text('\n'.join(md), encoding='utf-8')
    print(f'\nReport written to {args.out}')
    print('\n'.join(md))


if __name__ == '__main__':
    main()
