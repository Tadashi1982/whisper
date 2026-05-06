# Resultados da spike — Parakeet vs Whisper-turbo (PT-BR)

Critério do doc: migra se `WER(parakeet) <= WER(whisper) + 1% absoluto`.

## Performance

| Métrica | Whisper-turbo | Parakeet v3 |
|---|---|---|
| Load time (s) | 1.46 | 59.89 |
| Total audio (s) | 577.32 | 577.32 |
| Total infer (s) | 14.96 | 3.4 |
| Overall RTFx | 38.58 | 169.61 |
| VRAM model (MB) | 2216 | 4988 |
| VRAM peak (MB) | 3433 | 3990 |

## WER agregado

| Modelo | WER (com acentos) | WER (sem acentos) | MER | WIL |
|---|---|---|---|---|
| whisper-large-v3-turbo | 0.0416 | 0.0407 | 0.0414 | 0.0685 |
| parakeet-tdt-0.6b-v3 | 0.0434 | 0.0425 | 0.0432 | 0.0729 |

## Decisão (critério do doc)

- ΔWER (com acentos): Parakeet − Whisper = **+0.0018** (+0.18 pp)
- ΔWER (sem acentos): Parakeet − Whisper = **+0.0018** (+0.18 pp)
- Critério (≤ +1.00 pp): com acentos → **MIGRAR** | sem acentos → **MIGRAR**

## Comparação qualitativa (5 amostras com maior divergência)

### Amostra 2 (Δ=0.200)
- **Ref:** giancarlo fisichella perdeu o controle do carro e acabou a corrida logo após a largada
- **Whisper** (0.267): Jean-Carlo fez aquela, perdeu o controle do carro e acabou a corrida logo após a largada.
- **Parakeet** (0.067): Giancarlo Zekella perdeu o controle do carro e acabou a corrida logo após a largada.

### Amostra 39 (Δ=0.143)
- **Ref:** para ter as melhores vistas de hong kong saia da ilha e vá até a orla de kowloon do lado oposto
- **Whisper** (0.000): Para ter as melhores vistas de Hong Kong, saia da ilha e vá até a orla de Kowloon, do lado oposto.
- **Parakeet** (0.143): Para ter as melhores vistas de Hongkong, saia da Ilha e vá até a Orla de Gulun, do lado oposto.

### Amostra 3 (Δ=0.118)
- **Ref:** o romantismo tinha um grande elemento de determinismo cultural extraído de escritores como goethe fichte e schlegel
- **Whisper** (0.059): O romantismo tinha um grande elemento de determinismo cultural, extraído de escritores como Goethe, Fichte e Skellige.
- **Parakeet** (0.176): O romantismo tinha um grande elemento de determinismo cultural, extraído de escritores como Gold, Fricht e Selfie.

### Amostra 37 (Δ=0.111)
- **Ref:** o próprio veículo foi tirado do local do acidente mais ou menos às 12h gmt do mesmo dia
- **Whisper** (0.222): O próprio veículo foi tirado do local do acidente mais ou menos às 12 horas de MT do mesmo dia.
- **Parakeet** (0.111): O próprio veículo foi tirado do local do acidente mais ou menos às 12:00 GMT, do mesmo dia.

### Amostra 47 (Δ=0.091)
- **Ref:** também ao norte visite o grande santuário de nossa senhora de fátima relicário um lugar famoso no mundo todo por aparições marianas
- **Whisper** (0.000): Também ao norte visite o grande santuário de Nossa Senhora de Fátima Relicário, um lugar famoso no mundo todo por aparições marianas.
- **Parakeet** (0.091): Também ao norte, visite o Grande Santuário de Nossa Senhora de Fatima Helicário, um lugar famoso no mundo todo por aparições marianas.
