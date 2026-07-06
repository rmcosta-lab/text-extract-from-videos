# text-extract-from-videos

> 🔒 **Locked spec.** This README is the canonical specification for the tool's
> behavior and deliverables. Change it deliberately, not casually. The project
> constitution lives in [`specs/`](specs/):
> [mission](specs/mission.md) · [tech-stack](specs/tech-stack.md) · [roadmap](specs/roadmap.md).

brew install ffmpeg tesseract

python3 -m venv .venv
source .venv/bin/activate

python -m pip install --upgrade pip

python -m pip install \
  opencv-python \
  numpy \
  pillow \
  pandas \
  tqdm \
  rich \
  rapidfuzz \
  scikit-image \
  pytesseract \
  typer \
  pydantic

  Quero que você gere um script Python completo, robusto e executável localmente para extrair código-fonte a partir de um vídeo de gravação de tela.

Contexto:

* O vídeo mostra uma tela com código sendo rolado verticalmente.
* Os vídeos podem ter sido gravados em 30 fps, 60 fps ou 120 fps.
* O script precisa identificar o FPS real do vídeo.
* Alguns vídeos mostram número de linha no editor de código; outros não.
* O objetivo é reconstruir o código real a partir dos frames do vídeo.
* Quando não for possível extrair um trecho com confiança, o script deve indicar o tempo do vídeo, o número do frame e, se disponível, o número da linha.
* Se houver lacuna de linhas, por exemplo linha 32 seguida da linha 34, o script deve registrar que a linha 33 está faltando.

Requisitos funcionais:

1. Criar uma CLI em Python usando `typer` ou `argparse`.

2. O usuário deve conseguir rodar assim:

   python extract_code_from_video.py --video caminho/do/video.mp4 --output saida/

3. O script deve criar a seguinte estrutura de saída:

   saida/
   ├── codigo_extraido.txt
   ├── relatorio_falhas.md
   ├── ocr_raw.csv
   ├── metadata_video.json
   ├── extraction_parameters.json
   └── frames_usados/

4. O script deve identificar metadados do vídeo:

   * FPS;
   * duração;
   * resolução;
   * total de frames;
   * codec, se possível;
   * estratégia de amostragem usada.

5. Usar `ffprobe` para extrair metadados do vídeo quando disponível.

6. Usar `OpenCV` como fallback para FPS, total de frames, resolução e leitura dos frames.

7. O script deve ajustar automaticamente a amostragem conforme o FPS:

   * 30 fps: sample_step padrão menor;
   * 60 fps: sample_step intermediário;
   * 120 fps: sample_step maior.

8. O script deve evitar processar todos os frames se não for necessário.

Processamento de imagem:

1. Para cada frame candidato:

   * converter para grayscale;
   * aplicar resize para melhorar OCR;
   * aplicar threshold adaptativo ou Otsu;
   * aplicar sharpen ou denoise quando necessário.
2. Calcular nitidez do frame usando variância do Laplaciano.
3. Ignorar frames borrados durante o scroll.
4. Usar SSIM ou diferença entre imagens para evitar processar frames quase idênticos.
5. Permitir parâmetros opcionais de crop:

   * --crop-left
   * --crop-top
   * --crop-right
   * --crop-bottom
6. Se crop não for informado, usar o frame inteiro.

OCR:

1. Implementar OCR com `pytesseract` como primeira opção.
2. Estruturar o código de forma que seja fácil trocar para `PaddleOCR` depois.
3. Preservar caracteres importantes de código:

   * indentação;
   * parênteses;
   * colchetes;
   * chaves;
   * aspas;
   * dois pontos;
   * ponto;
   * vírgula;
   * operadores;
   * underscores.
4. Para cada resultado OCR, salvar:

   * texto extraído;
   * frame;
   * tempo no vídeo;
   * confiança, se disponível;
   * caminho da imagem do frame usado.

Reconstrução do código:

1. Se houver números de linha:

   * detectar o número da linha no começo da linha;
   * separar número da linha e conteúdo;
   * consolidar múltiplas leituras da mesma linha;
   * escolher a melhor versão com base em confiança, nitidez e frequência;
   * ordenar o código pelo número da linha.

2. Se não houver números de linha:

   * reconstruir a ordem pelo tempo do vídeo;
   * remover duplicatas causadas pelo scroll;
   * usar similaridade fuzzy para consolidar linhas repetidas.

3. Detectar linhas faltantes quando houver numeração.

4. Detectar trechos com baixa confiança.

5. Nunca inventar código.

6. Quando houver dúvida, marcar no código final com comentário:

   # [OCR_UNCERTAIN] frame=1234 time=00:01:23.400 texto_original="..."

7. Se uma linha estiver faltando, registrar no relatório:

   Linha 45 possivelmente ausente entre os tempos 00:01:10.200 e 00:01:12.800.

Relatório:
Gerar `relatorio_falhas.md` contendo:

* resumo do vídeo;
* FPS detectado;
* quantidade de frames analisados;
* quantidade de frames descartados por baixa nitidez;
* quantidade de linhas extraídas;
* linhas faltantes;
* linhas com baixa confiança;
* trechos impossíveis de extrair;
* recomendações para melhorar a extração, como gravar em maior resolução, reduzir velocidade do scroll, aumentar fonte do editor e usar tema de alto contraste.

Qualidade do código:

1. Código modularizado com funções claras:

   * get_video_metadata()
   * sample_frames()
   * preprocess_frame()
   * is_frame_blurry()
   * run_ocr()
   * parse_code_lines()
   * merge_ocr_results()
   * detect_missing_lines()
   * write_outputs()
2. Usar type hints.
3. Usar dataclasses ou Pydantic para estruturar resultados.
4. Ter logs claros usando `rich` ou `logging`.
5. Tratar erros comuns:

   * vídeo inexistente;
   * ffprobe não instalado;
   * tesseract não instalado;
   * vídeo sem FPS detectável;
   * OCR vazio;
   * diretório de saída sem permissão.
6. Incluir instruções de instalação no topo do arquivo ou em um README.
7. O script deve rodar localmente, sem enviar dados para APIs externas.

Bibliotecas esperadas:

* opencv-python
* numpy
* pillow
* pandas
* tqdm
* rich
* rapidfuzz
* scikit-image
* pytesseract
* typer ou argparse
* pydantic ou dataclasses

Entregáveis:

1. Código completo do script `extract_code_from_video.py`.
2. Exemplo de comando de execução.
3. Explicação curta da lógica.
4. Lista de instalação das dependências.
5. Sugestões de melhoria futura, como PaddleOCR, modelo vision-language local ou integração com LLM para revisar o código extraído sem inventar trechos.

---

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

## Explicação curta da lógica

1. **Metadados** — `ffprobe` lê FPS, duração, resolução, total de frames e
   codec; se o `ffprobe` faltar ou falhar, o OpenCV entra como fallback (com
   aviso). `metadata_video.json` é gravado já nesta etapa, para que mesmo uma
   execução que falhe depois fique inspecionável.
2. **Parâmetros de extração** — crop e intervalo de tempo (`--start-time` /
   `--end-time`) são validados contra os metadados do vídeo e gravados em
   `extraction_parameters.json`, incluindo os valores pedidos e os valores
   efetivamente usados.
3. **Amostragem adaptativa** — o passo de amostragem é escolhido pelo FPS
   detectado (30/60/120 fps), gerando cerca de um frame candidato a cada 0,5 s
   em vez de processar todos os frames. Quando há intervalo selecionado, só
   frames dentro desse trecho são considerados, mantendo os números de frame e
   tempos do vídeo original.
4. **Pré-processamento e seleção** — cada candidato é cortado (crop),
   convertido para grayscale, ampliado, binarizado (Otsu) e limpo. Frames
   borrados (variância do Laplaciano baixa) e quase duplicados (SSIM alto)
   são descartados; os frames aproveitados são salvos em `frames_usados/`.
5. **OCR** — o Tesseract (via `pytesseract`, atrás de uma interface trocável
   por PaddleOCR no futuro) lê cada frame mantido; toda leitura bruta vai para
   `ocr_raw.csv` com frame, tempo e confiança.
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
