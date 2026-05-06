# Resultados da spike — Parakeet vs Whisper-turbo (PT-BR)

Critério do doc: migra se `WER(parakeet) <= WER(whisper) + 1% absoluto`.

## Performance

| Métrica | Whisper-turbo | Parakeet v3 |
|---|---|---|
| Load time (s) | 1.45 | 14.67 |
| Total audio (s) | 104.81 | 104.81 |
| Total infer (s) | 1.96 | 0.53 |
| Overall RTFx | 53.54 | 198.87 |
| VRAM model (MB) | 2216 | 5036 |
| VRAM peak (MB) | 3733 | 4940 |

## WER agregado

| Modelo | WER (com acentos) | WER (sem acentos) | MER | WIL |
|---|---|---|---|---|
| whisper-large-v3-turbo | 0.0968 | 0.0968 | 0.0942 | 0.1349 |
| parakeet-tdt-0.6b-v3 | 0.1290 | 0.1290 | 0.1257 | 0.1851 |

## Decisão (critério do doc)

- ΔWER (com acentos): Parakeet − Whisper = **+0.0323** (+3.23 pp)
- ΔWER (sem acentos): Parakeet − Whisper = **+0.0323** (+3.23 pp)
- Critério (≤ +1.00 pp): com acentos → **NÃO migrar** | sem acentos → **NÃO migrar**

## Comparação qualitativa (5 amostras com maior divergência)

### Amostra 0 (Δ=0.032)
- **Ref:** hoje dia 12 05 2026 eu falei com a mariana lá em são paulo e depois com o joão em curitiba a reunião começou às 14 30 e terminou quase às 16 15 tipo assim meio corrida mas deu certo o orçamento ficou em r 1 234 56 e o contato principal é teste asr example com se precisar liga no 11 98765 4321 e fala com calma porque às vezes o áudio corta um pedaço no sistema a gente vai revisar a api checar os logs e validar o deploy antes de subir em produção também precisamos observar a cpu a memória e se o serviço respondeu sem erro a cidade de belo horizonte teve um retorno melhor mas em recife apareceu uma latência estranha ah e aí ahn eu acho que a melhor opção é testar de novo porque ficou meio confuso na primeira gravação mano isso acontece às vezes viu depois a gente ajusta o texto confirma os dados e segue normal se quiser eu também posso transformar isso em versão mais natural versão mais longa versão com ainda mais ruído para asr
- **Whisper** (0.097): Hoje dia 12 do 5 de 2026 eu falei com a Mariana lá em São Paulo e depois com o João em Curitiba. A reunião começou às 14h30 e terminou quase às 16h15. Tipo assim, meio corrida, mas deu certo. O orçamento ficou em 1.234,56 e o contato principal é teste.asr.exemplos.com Se precisar, liga no 011 98 765 4321 e fala com calma, porque às vezes o áudio corta um pedaço. No sistema, a gente vai revisar a API, checar os logs e validar o deploy antes de subir em produção Também precisamos observar a CPU, a memória e se o serviço respondeu sem erro A cidade de Belo Horizonte teve um retorno melhor, mas em Recife apareceu uma latência estranha e aí eu acho que a melhor opção é testar de novo porque ficou meio confuso na primeira gravação mano isso aconteceu às vezes viu e depois a gente ajusta o texto confirma os dados e segue normal Se quiser, eu também posso transformar isso em versão mais natural, versão mais longa, versão com ainda mais ruído para a SR.
- **Parakeet** (0.129): Hoje dia 12 de 5 de 2026 eu falei com a Mariana lá em São Paulo e depois com o João em Curitiba. A reunião começou às 14h30 e terminou quase às 16h15 Tipo assim meio corrida mas deu certo O orçamento ficou em 1234 e 56 E o contato principal é teste.asr arroba exemplos.com Se precisar liga no 011 98 765 4321 e fala com calma Porque às vezes o áudio corta um pedaço No sistema a gente vai revisar a API checar os logs e validar o deploy antes de subir em produção Também precisamos observar a CPU a memória e seu serviço respondeu sem eu a cidade Belo Horizonte teve um retorno melhor mas em Recife apareceu uma latência estranha e aí eu acho que a melhor opção é testar de novo porque ficou meio confuso na primeira gravação Mano Isso aconteceu às vezes viu depois a gente ajusta o texto confirma os dados e segue normal se quiser eu também posso transformar isso em versão mais natural versão mais longa versão com ainda mais ruído para a SR
