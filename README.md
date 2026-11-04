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

### Recuperação de frames desfocados

Antes do OCR, a extração agora também verifica estabilidade temporal, inclusive
em candidatos nítidos. `--stability-window-seconds 0.5` busca a primeira sequência
estável de pelo menos 0,1 s (mínimo três frames) e usa seu frame mais nítido.
O crop é respeitado. A comparação aceita pequenas alterações localizadas, como
cursor piscando, mas rejeita movimento amplo e compara também com o início da
sequência para evitar aceitar rolagem lenta acumulada.

Sem confirmação, o candidato é descartado e o processo segue para a próxima
amostra; não há fallback para a imagem instável. A busca pode atravessar candidatos
obrigatórios próximos, que são pulados se anteriores ao frame já escolhido, mas
nunca ultrapassa o fim do trecho. No fim de trechos curtos pode faltar tempo para
confirmar estabilidade. Números de frame e horários do substituto são preservados.

`stability_selection.json` registra tentativas, sequência confirmada e substituto;
o relatório informa descartes e substituições. Desative com
`--stability-window-seconds 0` para manter apenas a recuperação por desfoque abaixo.
Com estabilidade ativa, ela também exige nitidez; não se usa um frame nítido
instável como fallback. Há custo adicional de decodificação para cada candidato.

O método é heurístico: tolera até 2% dos pixels com diferença acima de 20/255
em miniaturas com largura máxima de 640 pixels. Movimento da câmera e mudanças
de iluminação podem causar rejeições. Sobreposição que permaneça estática pode
passar: estabilidade não certifica legibilidade nem fidelidade do OCR.

Quando um candidato reprova no filtro de nitidez, a extração procura o frame
mais nítido nos próximos **0,25 s**, sem atingir o próximo candidato regular ou
obrigatório e sem sair do trecho selecionado. Só substitui por um frame que
também passe no filtro; caso contrário mantém o descarte. A medição usa o crop.
Empates favorecem o frame mais próximo. Não mistura nem interpola imagens.

Configure `--blur-retry-seconds 0.25` (padrão, máximo 1 s) ou use
`--blur-retry-seconds 0` para desativar. O custo adicional ocorre nos candidatos
desfocados, com decodificação local dos vizinhos e sem OCR em cada tentativa.

`blur_recovery.json` registra candidatos examinados, nitidez, motivo e frame
escolhido. Os arquivos, OCR e evidências de revisão usam o número/tempo reais do
substituto. O original rejeitado continua registrado como não lido, pois uma
imagem posterior não comprova que todo seu conteúdo foi recuperado. Tempos usam
a mesma convenção frame/FPS do pipeline de extração existente.

Isso não detecta todos os artefatos: texto duplicado/sobreposto pode ter alta
nitidez e passar no filtro. O `frame_0.png` apresentado em `saida/readme` já havia
passado no filtro com pré-processamento `native`; esta mudança não garante sua
rejeição. Ela também não modifica resultados já existentes.

### PaddleOCR com GPU NVIDIA

Para testar **PaddleOCR-VL-1.6** na extração de código, use o grupo opcional
`paddle-vl`, `--engine paddle-vl` e `--preprocess native`.
Veja [instalação, exemplo e limitações](docs/paddle-vl.md).
O detector do Explorer permanece com PP-OCRv6.

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

Os testes automatizados ficam em `tests/`, e os arquivos de referência em
`tests/fixtures/`. Execute a suíte a partir da raiz com `uv run pytest`; para
um arquivo específico, use `uv run pytest tests/test_suggest_crop.py`.

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
o padrão é `high`. A extração prepara WebP com qualidade 90 (compressão com perdas,
método 4), sem reduzir a resolução do recorte. A revisão lê o campo
`review_image` e envia esses bytes sem novo crop ou conversão. Os PNGs originais
permanecem locais. JPEGs já preparados continuam aceitos. Quando não há imagem
preparada, a revisão gera WebP em memória a partir do original. Se o crop registrado
em `parameters.crop` diferir de `review_crop`, ela também usa o original para
não enviar um recorte desatualizado. A chamada usa Responses API, saída
estruturada e `store=False`.

A revisão gera `codigo_revisado.md` (ou a extensão escolhida), `comparativo.diff`
e `revisao.json`, com justificativas, frames citados, uso de tokens e dúvidas.
Também gera `relatorio_revisao.md`, com alterações e pendências legíveis e links
para os frames, e `line_mapping.json`, com a correspondência entre linhas originais
e revisadas. Substituições apontam para intervalos, não equivalências individuais.
O OCR original não é alterado. Edições com posição/texto incompatível, sobrepostas
ou citando frames não enviados são rejeitadas. Correções visuais exigem referência
a um frame; mudanças classificadas como formatação só podem alterar whitespace.
Essas validações não provam que a interpretação do modelo está correta: confira
as sugestões e o diff. Um `.py` revisado também não é executado pelo programa.

Uma revisão existente não é sobrescrita: use outra pasta em `--output`.
O limite padrão por chamada é 12 frames, 100 mil caracteres e 25 MB de imagens codificadas
antes de base64. O comando falha sem omitir evidências se exceder os limites.
Use trechos menores ou ajuste `--max-frames` quando apropriado. O limite de saída
é controlado por `--max-output-tokens` (padrão 12000, incluindo reasoning);
respostas incompletas não são aplicadas e não há repetição automática de chamadas.

### Recuperar, retomar e consultar a revisão

Novas execuções salvam cada resposta em `responses/block_0001/attempt_0001.json`
**antes da interpretação e validação**, inclusive recusas e respostas incompletas.
`review_run.json` registra configuração, hashes das entradas e estado dos blocos.
Nenhuma chave ou imagem em base64 é gravada nesses registros.

```powershell
# Relatório de uma revisão existente, sem API:
uv run python review_ocr.py --extraction saida/casos_de_uso --output saida/casos_de_uso/revisao-gpt --report-only

# Reaplicar respostas completas salvas de uma execução interrompida, sem API:
uv run python review_ocr.py --extraction saida/casos_de_uso --output saida/casos_de_uso/revisao-nova --reapply

# Planejar blocos e cobertura de imagens sem enviar nem escrever resultados:
uv run --group review --env-file .env.local python review_ocr.py --extraction saida/casos_de_uso --output saida/casos_de_uso/revisao-blocos --chunk-lines 100 --context-lines 10 --frame-selection coverage --max-frames 30 --max-output-tokens 32000 --image-detail original --system-certs --dry-run
```

Remova `--dry-run` para executar a revisão em blocos. Em caso de falha, repita o
comando com **os mesmos parâmetros** e `--resume`: blocos válidos não são reenviados.
`--reapply` usa a configuração salva e exige uma resposta válida para cada bloco;
não aceita JSON parcial nem sobrescreve resultados finais existentes.

Blocos e seleção de imagens continuam **opcionais**. Sem `--chunk-lines`, há uma
chamada única; `--frame-selection all` é o padrão. `coverage` mantém evidências
obrigatórias e alternativas distintas, priorizando nitidez. Se a associação não
for confiável, mantém todos os frames e informa o motivo. Blocos repetem contexto
e imagens, portanto podem aumentar o consumo total mesmo reduzindo cada chamada.

### Medir a fidelidade da revisão

```powershell
uv run python evaluate_review.py --extraction saida/casos_de_uso --review saida/casos_de_uso/revisao-gpt --reference tests/fixtures/casos_de_uso.review.reference.json --output saida/casos_de_uso/avaliacao-revisao
```

Compara OCR e revisão com uma referência visual parcial de 30 linhas, sem API.
Produz métricas de caracteres, palavras, exatidão, indentação e regressões em JSON
e Markdown. Linhas ambíguas e intervalos sem referência completa são explicitamente
excluídos. A transcrição visual do assistente ainda requer conferência humana
independente; a amostra não certifica o documento inteiro.

Consulte [o fluxo completo de revisão](docs/review-workflow.md) para conhecer os
arquivos, as regras de recuperação, os limites, a seleção e o método de avaliação.

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

## Cortes quando o Explorer está oculto

Pipeline **independente, automático e local**: `split_explorer_video.py`.
O padrão é `--interval-mode strict --max-clip-seconds 0`: apenas sequências
classificadas como ausentes, excluindo lacunas incertas.
O modo opcional `--interval-mode continuous` inclui lacunas incertas e pode
manter o Explorer visível quando a árvore não corresponde à referência.
O modo `auto` usa PaddleOCR local para localizar o Explorer e gerar as referências
sem pedir tempos ou regiões. OpenCV identifica ocultação/reabertura e refina as
transições. Não chama OpenAI, não altera o vídeo original e não baixa modelos:
usa os pesos PaddleOCR já instalados. Veja [comandos, pré-requisitos e limites](docs/explorer-segmentation.md).

```powershell
uv run --group paddle-gpu python split_explorer_video.py auto --video example/IMG_5886.MOV --output saida/explorer-5886-auto --scan-fps 2 --analyze-only
uv run python split_explorer_video.py export --report saida/explorer-5886-auto/analysis/segments.json --output saida/explorer-5886-auto/clips --encoder h264_nvenc
```

Para outro vídeo, troque `--video` e `--output`. Remova `--analyze-only` para analisar
e exportar em uma etapa. A calibração manual continua opcional. As posições são
proporcionais, sem coordenadas fixas no código. O padrão amostra
4 fps e refina transições frame a frame; `--scan-fps 0` analisa todos os frames.
Amostragem pode perder mudanças breves, e a classificação requer conferência visual.
Se a descoberta não confirmar os dois estados com segurança, não exporta clipes.

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

### Resposta de revisão incompleta

O limite padrão de saída é 12.000 tokens. Para revisões maiores, use
`--max-output-tokens 32000` ou defina `OPENAI_REVIEW_MAX_OUTPUT_TOKENS=32000`
no `.env.local`. A opção da linha de comando tem prioridade sobre o ambiente.
O orçamento inclui raciocínio e o JSON de correções; aumentar esse limite pode
permitir maior consumo de tokens. Não é necessário executar o OCR novamente.
Respostas incompletas ou inválidas são preservadas para diagnóstico, mas não são
aplicadas e não geram nova tentativa automática. Para mudar o orçamento de uma
execução registrada, use outra pasta. Se o limite continuar insuficiente, use
blocos menores ou revise um trecho menor.
