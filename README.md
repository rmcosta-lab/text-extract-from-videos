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

### Extensão da saída e preparação para revisão visual

Use `--output-extension txt`, `md` ou `py` (sem ponto). O padrão é `txt`.
A extensão selecionada gera `codigo_extraido.md` ou `codigo_extraido.py`,
mantendo também `codigo_extraido.txt` como registro do OCR. O conteúdo é
idêntico, inclusive os marcadores de incerteza: a extensão não formata nem
corrige o texto, e um `.py` não é necessariamente Python válido.

```powershell
uv run --group paddle-gpu python extract_code_from_video.py --video example/IMG_1128.MOV --engine paddle --output saida/trecho-md --start-time 3.5 --end-time 9 --crop-left 62 --crop-top 471 --crop-right 162 --crop-bottom 0 --output-extension md --prepare-review
```

`--prepare-review` salva os frames originais dos frames aceitos, além das imagens
processadas pelo OCR e dos WebPs coloridos já recortados para revisão
(`frames_usados/frame_1320_review.jpg`, por exemplo). Também cria
`review_manifest.json` com texto bruto, confiança,
tempos e correspondência entre linhas da saída e frames. Isso usa mais espaço
em disco. Essa opção apenas prepara evidências locais: não chama LLM nem envia
imagens a uma API.

### Revisão com a API da OpenAI

Configure localmente `.env.local` (ignorado pelo Git). Use `.env.example` como
referência; nunca coloque a chave real em arquivos versionados:

```dotenv
OPENAI_API_KEY=sua_chave_aqui
OPENAI_REVIEW_MODEL=gpt-6-sol
OPENAI_REVIEW_REASONING=high
```

O comando lê o modelo e o nível de raciocínio desse ambiente. `--model` e
`--reasoning-effort` prevalecem sobre as variáveis quando informados.

```powershell
uv sync --locked --group paddle-gpu --group review --system-certs
# Valida os arquivos e mostra o modelo configurado, sem chamar a API:
uv run --group review --env-file .env.local python review_ocr.py --extraction saida/trecho-md --output saida/trecho-md/revisao-sol --dry-run
# Envia o texto e os frames recortados para revisão (API paga):
uv run --group review --env-file .env.local python review_ocr.py --extraction saida/trecho-md --output saida/trecho-md/revisao-sol --image-detail original --system-certs
```

`--system-certs` usa os certificados confiáveis do sistema e mantém TLS validado.
`--image-detail original` deve ser usado com um modelo que suporte essa opção;
o padrão é `high`. A extração prepara o JPEG de alta qualidade (qualidade 95,
sem subsampling), sem reduzir a resolução do recorte. A revisão lê o campo
`review_image` e envia esses bytes sem novo crop ou conversão. Os PNGs originais
permanecem locais. Manifestos antigos ainda funcionam: quando não há JPEG
preparado, a revisão o gera em memória a partir do original. Se o crop registrado
em `parameters.crop` diferir de `review_crop`, ela também usa o original para
não enviar um recorte desatualizado. A chamada usa Responses API, saída
estruturada e `store=False`.

A revisão gera `codigo_revisado.md` (ou a extensão escolhida), `comparativo.diff`
e `revisao.json`, com justificativas, frames citados, uso de tokens e dúvidas.
O OCR original não é alterado. Edições com posição/texto incompatível, sobrepostas
ou citando frames não enviados são rejeitadas. Correções visuais exigem referência
a um frame; mudanças classificadas como formatação só podem alterar whitespace.
Essas validações não provam que a interpretação do modelo está correta: confira
as sugestões e o diff. Um `.py` revisado também não é executado pelo programa.

Uma revisão existente não é sobrescrita: use outra pasta em `--output`.
O limite padrão é 12 frames, 100 mil caracteres e 25 MB de imagens codificadas
antes de base64. O comando falha sem omitir evidências se exceder os limites.
Use trechos menores ou ajuste `--max-frames` quando apropriado. O limite de saída
é controlado por `--max-output-tokens` (padrão 12000, incluindo reasoning);
respostas incompletas não são aplicadas e não há repetição automática de chamadas.

Referências oficiais: [visão](https://developers.openai.com/api/docs/guides/images-vision),
[saída estruturada](https://developers.openai.com/api/docs/guides/structured-outputs)
e [GPT-6 Sol](https://developers.openai.com/api/docs/models/gpt-6-sol).

Ao reutilizar a pasta de saída, os artefatos da execução anterior são limpos,
incluindo a extensão registrada nos parâmetros. Use outra pasta para guardar
comparações ou edições manuais.

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

## Avaliação do trecho e melhorias implementadas

O caso de referência usa exatamente este intervalo e crop:

```powershell
uv run --group paddle-gpu python extract_code_from_video.py --video example/IMG_1128.MOV --engine paddle --output saida/trecho --start-time 3.5 --end-time 9 --crop-left 62 --crop-top 471 --crop-right 162 --crop-bottom 0
```

- **Fidelidade:** transcrição visual parcial de 30 ocorrências de linhas em três
  frames, com CER, WER, numeração e indentação. Veja o
  [relatório e limitações](benchmarks/IMG_1128.md) e a
  [referência manual](tests/fixtures/IMG_1128.reference.json).
- **Crop direito:** texto retido em qualquer frame impede que a sugestão corte
  essa região, mesmo contra uma maioria de votos de ruído. Testes incluem
  linhas longas, minimap e frames sem coluna de números. Ainda é uma heurística
  sobre frames amostrados: confirme visualmente o recorte antes da extração.
- **Pré-processamento:** `--preprocess legacy` continua padrão. `native`
  preserva cores e resolução após crop; `bounded` usa cores com `--ocr-scale`
  (padrão 1) e `--ocr-max-side` (padrão 4000). Estes dois controles só afetam
  `bounded`. A configuração fica em `extraction_parameters.json`. O preview
  de crop continua usando `legacy`, com suas coordenadas em escala 2×.
- **Módulos:** implementação em `video_ocr/`; os comandos existentes continuam
  funcionando. O script principal reexporta os símbolos antigos por compatibilidade.
- **CI:** Windows e Linux rodam Ruff, mypy e testes sem vídeo/GPU em push e PR.
  A integração GPU é manual e separada, com referência local e métricas.

No trecho medido, `legacy` teve CER de 7,08%; as variantes coloridas ficaram
próximas de 28%. Por isso, não houve troca automática do padrão. A medição é
parcial e não garante fidelidade do documento inteiro.

```powershell
# Comparação na GPU; salva métricas, OCR bruto e imagens para conferência:
uv run --group paddle-gpu python evaluate_ocr.py --require-gpu
# Testes rápidos, sem vídeo, Tesseract ou GPU:
uv run pytest -m "not integration and not gpu"
# Integração local com o vídeo:
$env:TEST_OCR_ENGINE = "paddle"
$env:REQUIRE_TEST_VIDEO = "1"
uv run --group paddle-gpu pytest -m integration
Remove-Item Env:TEST_OCR_ENGINE, Env:REQUIRE_TEST_VIDEO
```

### Organização

| Módulo | Responsabilidade |
|---|---|
| `video_ocr/models.py` | Modelos compartilhados, constantes e utilitários básicos |
| `video_ocr/video.py` | Metadados, intervalo e amostragem |
| `video_ocr/imaging.py` | Crop, seleção visual e pré-processamento |
| `video_ocr/ocr.py` | Tesseract e PaddleOCR |
| `video_ocr/pipeline.py` | Seleção e OCR dos frames |
| `video_ocr/reconstruction.py` | Numeração, fusão, lacunas e trechos não extraídos |
| `video_ocr/reports.py` | Artefatos e relatório de falhas |
| `video_ocr/quality.py` | Comparação com transcrições manuais |
| `video_ocr/cli.py` | Comando de extração |

### Integração GPU no GitHub Actions

O workflow manual `Local GPU integration` requer um runner próprio Windows x64
com label `gpu`, driver NVIDIA, `ffprobe` no PATH e a variável de ambiente
`OCR_TEST_VIDEO` apontando para o MOV fora do checkout. A preparação copia esse
arquivo para `example/IMG_1128.MOV`; o vídeo não é enviado ao repositório.
Os modelos precisam estar em cache ou a primeira execução precisa de rede.
O workflow registra métricas e verifica CER ≤10% e numeração ≥85% no perfil
`legacy`, além dos testes e da execução do trecho. Os workflows foram preparados
localmente; sua execução no GitHub depende de commit/push e do runner configurado.

Fontes de configuração: [uv no GitHub Actions](https://docs.astral.sh/uv/guides/integration/github/)
e [seleção de runners](https://docs.github.com/en/actions/how-tos/write-workflows/choose-where-workflows-run/choose-the-runner-for-a-job).

### Resposta de revis?o incompleta

O limite padr?o de sa?da ? 12.000 tokens. Para revis?es maiores, use
`--max-output-tokens 32000` ou defina `OPENAI_REVIEW_MAX_OUTPUT_TOKENS=32000`
no `.env.local`. A op??o da linha de comando tem prioridade sobre o ambiente.
O or?amento inclui racioc?nio e o JSON de corre??es; aumentar esse limite pode
permitir maior consumo de tokens. N?o ? necess?rio executar o OCR novamente.
Respostas incompletas ou inv?lidas n?o s?o aplicadas e n?o geram nova tentativa
autom?tica. Se o limite continuar insuficiente, revise um trecho menor.
