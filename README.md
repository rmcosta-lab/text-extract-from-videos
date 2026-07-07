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

## Instalação

### 1. Python 3.13

> ⚠️ **Use Python 3.13.** O PaddleOCR (backend opcional) depende do
> `paddlepaddle`, que **não publica wheels para Python 3.14+**. Mesmo que você
> use só o Tesseract, recomendamos o 3.13 para manter o ambiente compatível com
> o engine `paddle`.

```bash
# macOS
brew install python@3.13

# Windows: baixe o instalador do Python 3.13 em https://www.python.org/downloads/
# e marque "Add python.exe to PATH" durante a instalação.
```

### 2. Dependências de sistema (ffmpeg + tesseract)

Estas ferramentas **não** são instaladas pelo `pip` — precisam do gerenciador de
pacotes do sistema:

```bash
# macOS (Homebrew)
brew install ffmpeg tesseract
```

```powershell
# Windows (Chocolatey, em PowerShell como Administrador)
choco install ffmpeg tesseract
```

No Windows, se o `tesseract` não ficar no `PATH`, adicione a pasta de instalação
(ex.: `C:\Program Files\Tesseract-OCR`) às variáveis de ambiente, ou use o
instalador da UB Mannheim: <https://github.com/UB-Mannheim/tesseract/wiki>.

### 3. Ambiente virtual e pacotes Python

```bash
# macOS / Linux
python3.13 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

```powershell
# Windows (PowerShell)
py -3.13 -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

### 4. (Opcional) PaddleOCR

O OCR padrão é o Tesseract. Para usar o engine `paddle`, instale o backend
opcional:

```bash
python -m pip install paddleocr paddlepaddle
```

> ⚠️ **No macOS o PaddleOCR roda apenas em CPU** — o `paddlepaddle` não oferece
> aceleração CUDA no macOS (não há suporte a GPU NVIDIA nesta plataforma). Não
> instale `paddlepaddle-gpu` no Mac. Em Windows/Linux com GPU NVIDIA é possível
> usar a variante CUDA, mas a CPU é suficiente para esta ferramenta.

## Exemplo de comando de execução

```bash
python extract_code_from_video.py --video caminho/do/video.mp4 --output saida/
```

Com crop, para recortar bordas do editor (barra lateral, abas, minimap) antes
do OCR — valores em pixels a partir de cada borda:

```bash
python extract_code_from_video.py --video caminho/do/video.mp4 --output saida/ \
  --crop-left 60 --crop-top 40 --crop-right 20 --crop-bottom 30
```

Para extrair apenas um trecho do vídeo, informe o intervalo no tempo original
do arquivo. Os formatos aceitos são segundos (`12.5`), `MM:SS(.mmm)` ou
`HH:MM:SS(.mmm)`:

```bash
python extract_code_from_video.py --video caminho/do/video.mp4 --output saida/ \
  --start-time 00:00:10 --end-time 00:00:25.500
```

O OCR padrão é o Tesseract. Depois de instalar o backend opcional (ver
[Instalação → PaddleOCR](#4-opcional-paddleocr)), selecione o engine `paddle`:

```bash
python extract_code_from_video.py --video caminho/do/video.mp4 --output saida/ \
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
python suggest_crop.py --video sample-video/IMG_5430.MOV
```

Para restringir a análise a um trecho do vídeo, use `--start-time` e
`--end-time` (mesmos formatos do comando principal: segundos, `MM:SS(.mmm)`
ou `HH:MM:SS(.mmm)`); apenas frames dentro do intervalo são amostrados:

```bash
python suggest_crop.py --video sample-video/IMG_5430.MOV \
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
