# text-extract-from-videos

Ferramenta local (sem APIs externas) que reconstrói o código-fonte a partir de
um vídeo de gravação de tela onde o código é rolado verticalmente.

## Conceito

O script identifica o FPS real do vídeo (30/60/120), amostra frames de forma
adaptativa, pré-processa cada frame (grayscale, resize, binarização, remoção de
borrões e quase-duplicatas) e roda OCR para extrair o texto. Quando o editor
mostra números de linha, as múltiplas leituras de cada linha são consolidadas e
ordenadas pelo número, com detecção de linhas faltantes; sem numeração, a ordem
vem do tempo do vídeo e as duplicatas do scroll são removidas por similaridade
fuzzy. O código nunca é inventado: trechos de baixa confiança recebem o marcador
`# [OCR_UNCERTAIN]` e um `relatorio_falhas.md` resume frames descartados, linhas
ausentes e recomendações de captura. A saída inclui `codigo_extraido.txt`,
`relatorio_falhas.md`, `ocr_raw.csv`, `metadata_video.json`,
`extraction_parameters.json` e a pasta `frames_usados/`.

> 🔒 **Locked spec.** A especificação canônica completa está em [`specs/`](specs/):
> [mission](specs/mission.md) · [tech-stack](specs/tech-stack.md) · [roadmap](specs/roadmap.md).

## Ambiente com uv

Use Python **3.13**. O `uv` cria a `.venv` a partir de `pyproject.toml` e
`uv.lock`, sem precisar ativar o ambiente. Instalação do uv:
<https://docs.astral.sh/uv/getting-started/installation/>.

```powershell
uv sync --locked
uv run python extract_code_from_video.py --help
```

Reutilize o `ffmpeg`/`ffprobe` já instalado, disponível no `PATH`.
O executável Tesseract só é necessário para o engine `tesseract` (padrão).
Se necessário, instale com `winget install --id UB-Mannheim.TesseractOCR --exact`.

### PaddleOCR com GPU NVIDIA

```powershell
uv sync --locked --group paddle-gpu
uv run --group paddle-gpu python -c "import paddle; print(paddle.version.cuda()); paddle.utils.run_check()"
uv run --group paddle-gpu python suggest_crop.py --video example/IMG_1128.MOV --engine paddle --sample-count 3
```

O grupo `paddle-gpu` instala PaddleOCR e `paddlepaddle-gpu==3.2.2` pelo índice
oficial `https://www.paddlepaddle.org.cn/packages/stable/cu129/`.
Destinado a Windows/Linux x64 com GPU NVIDIA e driver compatível, não macOS.
Não instale `paddlepaddle` CPU junto com a variante GPU. Continue usando
`--group paddle-gpu` nos próximos `uv sync` para manter o backend instalado.
Na primeira execução, o PaddleOCR baixa modelos em `~/.paddlex`; depois
reutiliza o cache local. Os vídeos são processados localmente.

Se houver erro de certificado na rede, acrescente `--system-certs` ao comando
`uv sync`, ou defina `$env:UV_SYSTEM_CERTS = "true"` no PowerShell.

### Testes com IMG_1128.MOV

Mantenha o vídeo em `example/IMG_1128.MOV`. Ele é ignorado pelo Git pelo tamanho.
Os testes de amostragem e preview usam esse arquivo; sem ele, são pulados.

```powershell
uv run pytest
uv run ruff check .
uv run mypy
# Integração com PaddleOCR (falha se o engine solicitado não estiver disponível):
$env:TEST_OCR_ENGINE = "paddle"
uv run --group paddle-gpu pytest
Remove-Item Env:TEST_OCR_ENGINE
# Extração curta para validar o pipeline:
uv run --group paddle-gpu python extract_code_from_video.py --video example/IMG_1128.MOV --output saida/IMG_1128-smoke --engine paddle --start-time 2 --end-time 4
```

Para processar o vídeo inteiro, remova `--start-time` e `--end-time`.
Revise o crop no preview e confira o texto extraído com o vídeo original.

`requirements.txt` é uma exportação de compatibilidade; altere dependências
com `uv add` e regenere a exportação:

```powershell
uv export --locked --no-dev --format requirements-txt --output-file requirements.txt
```

## Exemplo de comando de execução

Nos exemplos abaixo, acrescente `--group paddle-gpu` depois de `uv run` e
`--engine paddle` às opções para usar a GPU em vez do Tesseract.

```bash
uv run python extract_code_from_video.py --video caminho/do/video.mp4 --output saida/
```

Com crop, para recortar bordas do editor (barra lateral, abas, minimap) antes
do OCR — valores em pixels a partir de cada borda:

```bash
uv run python extract_code_from_video.py --video caminho/do/video.mp4 --output saida/ \
  --crop-left 60 --crop-top 40 --crop-right 20 --crop-bottom 30
```

Para extrair apenas um trecho do vídeo, informe o intervalo no tempo original
do arquivo. Os formatos aceitos são segundos (`12.5`), `MM:SS(.mmm)` ou
`HH:MM:SS(.mmm)`:

```bash
uv run python extract_code_from_video.py --video caminho/do/video.mp4 --output saida/ \
  --start-time 00:00:10 --end-time 00:00:25.500
```

O OCR padrão é o Tesseract. Depois de instalar o backend opcional (ver
[PaddleOCR com GPU](#paddleocr-com-gpu-nvidia)), selecione o engine `paddle`:

```bash
uv run --group paddle-gpu python extract_code_from_video.py --video caminho/do/video.mp4 --output saida/ \
  --engine paddle
```

## Sugestão de crop com preview web (`suggest_crop.py`)

Antes de processar o vídeo inteiro, use a ferramenta de sugestão de crop para
descobrir os valores de `--crop-*` que isolam a coluna de números de linha e o
código. Ela analisa com OCR (Tesseract por padrão) **vários frames
distribuídos ao longo do vídeo** (12 por padrão, a partir do frame 30) e
combina os resultados em um único recorte válido para o vídeo inteiro: o crop
esquerdo nunca corta a coluna de números mais larga observada (9 → 10 → 100…)
e o crop direito só remove a coluna de ruído (minimap/scrollbar), sem nunca
cortar o código de nenhum frame amostrado. A página local (`127.0.0.1`)
mostra um frame de referência antes e depois do crop e quais frames
informaram a sugestão:

```bash
uv run python suggest_crop.py --video example/IMG_1128.MOV
```

Para restringir a análise a um trecho do vídeo, use `--start-time` e
`--end-time` (mesmos formatos do comando principal: segundos, `MM:SS(.mmm)`
ou `HH:MM:SS(.mmm)`); apenas frames dentro do intervalo são amostrados:

```bash
uv run python suggest_crop.py --video example/IMG_1128.MOV \
  --start-time 00:00:10 --end-time 00:00:25.500
```

Na página é possível editar os quatro valores (o backend recorta o frame de
novo e atualiza o preview), trocar o engine (`tesseract`/`paddle`) e copiar a
string pronta com as flags `--crop-left/--crop-top/--crop-right/--crop-bottom`
para colar no comando principal. A página também lista todos os frames
amostrados em miniatura — os que informaram a sugestão ficam destacados — com
o retângulo do crop sobreposto em cada um; qualquer imagem pode ser clicada
para ampliar (o retângulo acompanha o zoom nos frames inteiros e some na
imagem já recortada), e no zoom de um frame amostrado as setas ← e → do
teclado navegam entre eles. Frames sem texto não contribuem para a sugestão; se o
OCR não detectar texto em nenhum frame amostrado, a ferramenta mostra o frame
inteiro com crop zero e avisa — ela nunca inventa uma região. Opções:
`--engine`, `--sample-count` (número de frames amostrados), `--start-time` /
`--end-time` (janela de tempo analisada), `--host`, `--port` e `--no-open`
(não abrir o navegador automaticamente).

## Explicação curta da lógica

1. **Metadados** — `ffprobe` lê FPS, duração, resolução, total de frames e
   codec; se o `ffprobe` faltar ou falhar, o OpenCV entra como fallback (com
   aviso). `metadata_video.json` é gravado já nesta etapa, para que mesmo uma
   execução que falhe depois fique inspecionável.
2. **Parâmetros de extração** — crop, intervalo de tempo (`--start-time` /
   `--end-time`) e o engine de OCR (`--engine`) são validados contra os
   metadados do vídeo e gravados em `extraction_parameters.json`, incluindo os
   valores pedidos e os valores efetivamente usados.
3. **Amostragem adaptativa** — o passo de amostragem é escolhido pelo FPS
   detectado (30/60/120 fps), gerando cerca de um frame candidato a cada 0,5 s
   em vez de processar todos os frames. Quando há intervalo selecionado, só
   frames dentro desse trecho são considerados, mantendo os números de frame e
   tempos do vídeo original.
4. **Pré-processamento e seleção** — cada candidato é cortado (crop),
   convertido para grayscale, ampliado, binarizado (Otsu) e limpo. Frames
   borrados (variância do Laplaciano baixa) e quase duplicados (SSIM alto)
   são descartados; os frames aproveitados são salvos em `frames_usados/`.
5. **OCR** — o engine escolhido por `--engine` (Tesseract via `pytesseract`
   por padrão; PaddleOCR opcional) lê cada frame mantido atrás da mesma
   interface `OCREngine`; toda leitura bruta vai para `ocr_raw.csv` com frame,
   tempo e confiança.
6. **Reconstrução** — se o editor mostra números de linha, as múltiplas
   leituras de cada linha são consolidadas e ordenadas pelo número; sem
   numeração, a ordem é o tempo do vídeo e as duplicatas do scroll são
   removidas por similaridade fuzzy. A melhor leitura vence por frequência,
   confiança e nitidez — o texto nunca é misturado nem inventado; linhas de
   baixa confiança recebem o marcador `# [OCR_UNCERTAIN]`.
7. **Lacunas e relatório** — com numeração visível, saltos (ex.: linha 32 →
   34) viram registros de linha faltante; `relatorio_falhas.md` resume frames
   descartados, linhas faltantes, trechos de baixa confiança, trechos
   impossíveis de extrair e recomendações de captura.
8. **Saídas** — o código reconstruído vai para `codigo_extraido.txt`, ao lado
   de `relatorio_falhas.md`, `ocr_raw.csv`, `metadata_video.json`,
   `extraction_parameters.json` e `frames_usados/`.

## Avaliação e próximas melhorias

A preparação com uv também corrigiu dois problemas reproduzidos no Windows:
metadados ignorando a rotação do MOV (crop validado nas dimensões erradas) e
setas Unicode nos logs causando falha em consoles CP1252.

Prioridades para as próximas alterações:

1. **Medir fidelidade do OCR.** Criar uma transcrição manual de alguns frames
   de `IMG_1128.MOV` e comparar texto, indentação e numeração. O teste de
   execução confirma o pipeline, mas não a correção do código reconstruído.
   No trecho 2–4 s sem crop, o OCR incluiu ruído da interface e produziu erros
   de caracteres; a contagem de linhas faltantes sozinha não mede qualidade.
2. **Revisar a proteção do crop direito.** `combine_observations` assume que
   texto além da coluna de ruído é lixo. Essa hipótese merece exemplos com
   linhas longas e minimap antes de prometer que nenhum código será cortado.
3. **Ajustar pré-processamento por engine.** O upscale fixo de 2x transforma
   este vídeo em frames de 4320×7680, que o PaddleOCR reduz novamente para seu
   limite de 4000 pixels. Comparar qualidade e tempo com resolução original,
   crop e limites configuráveis antes de mudar os padrões.
4. **Separar responsabilidades.** Extrair metadados, engines OCR,
   reconstrução e relatórios do script principal para módulos menores,
   mantendo os testes das funções e as duas interfaces de comando.
5. **Automatizar validação.** CI com `uv sync --locked`, Ruff, mypy e testes
   unitários; integração GPU em execução separada, com vídeo local e métricas
   de qualidade. Evitar depender do MOV de 818 MB para testes unitários.
