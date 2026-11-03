# Extração local com PaddleOCR-VL-1.6

Engine experimental `--engine paddle-vl`, exclusivo da extração de código.
O pipeline do Explorer continua usando suas referências e modelos PP-OCRv6.
O engine `paddle` também fixa PP-OCRv6 para evitar mudança implícita após atualizar
a biblioteca compartilhada. O padrão da extração continua sendo Tesseract.

```powershell
uv sync --locked --group paddle-vl --group review
uv run --group paddle-vl python extract_code_from_video.py --video example/IMG_1128.MOV --engine paddle-vl --preprocess native --output saida/trecho-vl --start-time 3.5 --end-time 9 --crop-left 62 --crop-top 471 --crop-right 162 --crop-bottom 0 --output-extension py --prepare-review
```

O grupo inclui PaddleOCR 3.7.x com `doc-parser` e Paddle GPU 3.2.2 CUDA 12.9.
O lock também atualiza PaddleX e ajusta NumPy às dependências do parser.
Inferência direta em `gpu:0`, pipeline `v1.6`, modelo
`PaddleOCR-VL-1.6-0.9B`. Não usa OpenAI, chave ou servidor remoto.
A primeira execução pode baixar pesos oficiais; depois usa o cache PaddleX.
Falhas de dependência, GPU ou versão são explícitas, sem fallback para outro modelo.

Use `--preprocess native` para preservar cores e evitar binarização/upscale de 2x.
Os valores de crop do exemplo pertencem a esse vídeo; ajuste para outras gravações.
O crop deve manter os números de linha do editor, necessários à reconstrução.

O layout é desativado: cada frame recortado é lido inteiro, evitando separar a
coluna de números do código. Orientação automática, desentortamento e formatação
Markdown também ficam desativados. O adaptador preserva espaços e quebras de linha
do conteúdo bruto retornado. Não remove cercas Markdown eventualmente geradas,
não inventa números, caixas individuais de linha ou scores de confiança.
Consequentemente, a reconstrução não dispõe das mesmas evidências geométricas
do PP-OCRv6; frames sem numeração utilizável podem não ser reconstruídos.

VL pode omitir ou gerar caracteres e alterar indentação. Compare a saída com os
frames e a transcrição manual antes de escolher esse engine como padrão.
Testes do adaptador verificam contrato e preservação de texto, não fidelidade visual.

Referência: [guia oficial PaddleOCR-VL](https://www.paddleocr.ai/main/en/version3.x/pipeline_usage/PaddleOCR-VL.html).
