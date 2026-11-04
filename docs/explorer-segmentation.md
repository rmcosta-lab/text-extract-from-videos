# Cortes locais quando o Explorer está oculto

Novas descobertas automáticas usam PP-OCRv6 medium (detecção e reconhecimento).
Os pesos locais precisam estar no cache antes de executar `auto`. A atualização
não altera `profile.json`/`discovery.json` antigos: eles descrevem a execução
original. Use uma nova pasta para descobrir referências com PP-OCRv6.

## Cortes conservadores (padrão)

`auto` e `split` usam `--interval-mode strict --max-clip-seconds 0`, excluindo
lacunas incertas. Uma árvore alterada pode ficar incerta mesmo com o Explorer
visível; esses trechos não devem entrar nos clipes de ausência.

### Intervalos inteiros (opcional)

Com `--interval-mode continuous --max-clip-seconds 0`, o resultado é
um arquivo desde a ausência confirmada até o primeiro frame de reaparecimento
confirmado (fim exclusivo). Lacunas incertas internas são mantidas, inclusive
oscilações menores que `--confirm-seconds`. Isso pode incluir aparições breves
não confirmadas. Sem reaparecimento, termina no último timestamp analisado.
Sem ausência confirmada, nenhum clipe é gerado.

Use o padrão `--interval-mode strict` para excluir lacunas incertas.
O padrão de duração máxima agora é zero (sem subdivisão); um valor positivo
em `--max-clip-seconds` continua permitindo dividir intervalos longos.

Na execução IMG_1128, seis transições produzem três intervalos inteiros:
3,268–17,842 s, 22,010–35,732 s e 39,133–75,598 s. A detecção foi reaproveitada
sem alterar os resultados antigos. Os novos arquivos estão em
`saida/IMG_1128-explorer/continuous/clips/`.

Pipeline independente: `split_explorer_video.py` e `explorer_segments/`. Não
importa `video_ocr`, não usa `.env.local` e não chama APIs. O modo automático usa
modelos PaddleOCR já instalados localmente, sem downloads durante a execução.

## Uso automático — sem referências nem regiões manuais

```powershell
uv run --group paddle-gpu python split_explorer_video.py auto --video example/IMG_5886.MOV --output saida/explorer-5886-auto --scan-fps 2 --analyze-only
uv run python split_explorer_video.py export --report saida/explorer-5886-auto/analysis/segments.json --output saida/explorer-5886-auto/clips --encoder h264_nvenc
```

Para outro vídeo, basta trocar `--video` e usar uma nova pasta em `--output`.
Remova `--analyze-only` para analisar e exportar em uma etapa; `--encoder h264_nvenc`
também pode ser usado no comando `auto`. CPU é o padrão da codificação, enquanto
`--device gpu:0` é o padrão da inferência; `--device cpu` seleciona inferência CPU
quando a instalação do Paddle for compatível.

O modo automático:

1. Procura, com OCR local, o título `Explorer`/`Explorador` e uma árvore vertical
   de pelo menos quatro entradas. Um tooltip ou a palavra isolada não bastam.
2. Encontra exemplos com e sem painel e uma região estável da aplicação fora
   do painel. Gera as referências e regiões proporcionalmente, sem coordenadas
   específicas do vídeo no código.
3. Usa OpenCV para a varredura temporal e refinamento das transições. Evidência
   apenas do título, sem a árvore, fica incerta: pode ser tooltip ou árvore alterada.
4. Grava `automatic_profile/` com evidências da descoberta e `analysis/` com
   transições, observações e cortes. A calibração manual abaixo é opcional.

Pré-requisitos: bibliotecas do grupo `paddle-gpu` e modelos
`PP-OCRv6_medium_det` / `PP-OCRv6_medium_rec` completos em
`~/.paddlex/official_models` (ou no diretório indicado por `--model-root`).
O cache também respeita `PADDLE_PDX_CACHE_HOME`. Os caminhos dos modelos são
passados explicitamente e a verificação remota é desativada. Se faltarem pesos,
o comando falha com instrução local; não tenta baixar silenciosamente.

`--discovery-samples` (32 por padrão) controla a amostragem distribuída usada para
descobrir os estados, além de alguns pontos iniciais. Se não encontrar evidência
segura dos dois estados e da aplicação, não exporta clipes. Isso inclui vídeos em
que o Explorer nunca aparece, nunca some ou aparece apenas entre amostras de
descoberta. Aumente a amostragem para ampliar a busca; ausência de detecção não
é tratada como prova de que o painel está oculto.

## Generalização e avaliação de IA

A implementação usa OpenCV, já instalado, com correspondência visual normalizada
em várias escalas. Não há nome de vídeo, resolução ou posição fixa do Explorer
no detector. O perfil externo define regiões proporcionais à imagem orientada.

É uma solução **automaticamente calibrada por IA local**, não um reconhecedor
semântico universal de qualquer aplicativo. O modo `auto` gera
duas referências (com/sem Explorer), a região do painel, seu título e uma
âncora visual da aplicação fora do painel, visível nos dois estados.
Na calibração manual opcional, escolha botões estáveis; evite nomes de arquivos,
relógios, cursores e código.
A referência sem Explorer valida a separação dos estados, não o conteúdo do código.
Inclua o título e parte estável da árvore de pastas: somente o título pode ser
encoberto por cursor/tooltip enquanto o painel continua aberto. Não inclua áreas
que mudam de conteúdo entre arquivos; árvore recolhida/reorganizada pode exigir
nova referência. A validação negativa é necessária, mas não prova generalização.

**Foi necessário OCR local para dispensar a calibração manual.** O PaddleOCR já
estava disponível no ambiente, então não foi adicionada uma biblioteca de VLM ou
segmentação de vídeo. A IA identifica os elementos da interface; OpenCV faz
o acompanhamento mais barato. Os pesos são compartilhados com a instalação existente,
mas este pipeline não chama nem depende dos módulos dos demais pipelines.
Mudanças grandes de tema, idioma, zoom, árvore ou perspectiva dentro da mesma
gravação ainda podem causar incerteza ou erro. Não se promete reconhecimento universal.

Base técnica: [template matching do OpenCV](https://docs.opencv.org/4.x/d4/dc6/tutorial_py_template_matching.html).
Para movimentos mais fortes, [features e homografia](https://docs.opencv.org/4.x/d7/dff/tutorial_feature_homography.html)
são uma possível evolução do acompanhamento visual.

## Calibração manual opcional (modo avançado)

Extraia dois frames conhecidos:

```powershell
uv run python split_explorer_video.py frame --video example/outro.MOV --at 2 --output saida/outro-com.png
uv run python split_explorer_video.py frame --video example/outro.MOV --at 12 --output saida/outro-sem.png
```

Abra as imagens para escolher as regiões. Cada região é `x,y,largura,altura`,
normalizada: divida x/largura por W e y/altura por H. São coordenadas da imagem
depois da rotação do MOV; o comando `frame` informa as dimensões.

Os valores abaixo são **apenas para o enquadramento de IMG_5886.MOV**, não estão
embutidos no detector:

```powershell
uv run python split_explorer_video.py calibrate --video example/IMG_5886.MOV --output saida/explorer-5886-profile-v2 --present-at 0 --absent-at 10 --panel-roi 0.0185,0.06875,0.20,0.16 --anchor-roi 0.454,0.03958,0.36,0.025 --present-threshold 0.8 --absent-threshold 0.25
```

São gravados `present.png`, `absent.png`, `profile.json` e `calibration.json`.
Regiões planas ou referências incapazes de separar os estados são rejeitadas.
Um perfil pode ser reutilizado em outros vídeos com a mesma aparência/enquadramento.

## Analisar as transições

```powershell
uv run python split_explorer_video.py split --video example/IMG_5886.MOV --profile saida/explorer-5886-profile-v2/profile.json --output saida/explorer-5886-final --scan-fps 2 --analyze-only
```

O detector busca os modelos em uma vizinhança configurável, nas escalas 0,95/1/1,05.
Se a âncora não for reconhecida, a proporção da imagem mudar ou o score do Explorer
ficar entre os limites, classifica como `uncertain`. Scores não são probabilidades.

O exemplo de validação usa 2 fps; o padrão é 4 fps. Ambos refinam frame a frame os intervalos com mudanças ou
incerteza. Usa timestamps do decodificador, não só frame dividido pelo FPS médio.
Isso importa em MOV com taxa variável. Cada transição registra:

- `hidden`: Explorer passou de visível a oculto; `shown`: reapareceu.
- Último frame/timestamp do estado anterior e primeiro do novo estado confirmado.
- Faixa de incerteza temporal e imagens antes/depois para conferir.

Uma sequência precisa durar 0,15 s para confirmar o estado. O início reportado
é o primeiro frame dessa sequência, não o fim da confirmação. Isso identifica
a mudança visual, não o instante de um atalho de teclado que não foi filmado.

**Amostragem pode perder mudanças curtas entre amostras.** Para verificar todos os
frames, use `--scan-fps 0`, com custo maior. O relatório informa a cobertura e o
maior intervalo observado. Mesmo no modo exaustivo, o classificador pode errar.

## Exportar arquivos menores

Remova `--analyze-only` para analisar e exportar em uma etapa, ou reaproveite a
análise existente sem repetir a varredura:

```powershell
uv run python split_explorer_video.py export --report saida/explorer-5886-final/segments.json --output saida/explorer-5886-clips
```

Com NVIDIA/NVENC disponível, acrescente `--encoder h264_nvenc`. O padrão é CPU
(`libx264`, CRF 18); NVENC usa CQ 18, sem fallback silencioso. Os cortes são
recodificados: `-c copy` limitaria os inícios aos keyframes.

MP4 preserva a orientação exibida e resolução (padding de um pixel se necessário),
taxa variável e a primeira faixa de áudio em AAC quando houver. Outras faixas e
metadados auxiliares do iPhone não são exportados. O original não é alterado.
Não se aplica crop espacial, apenas cortes temporais. A precisão final é limitada
pelos frames e amostras de áudio disponíveis.

| Opção | Padrão | Efeito |
|---|---:|---|
| `--scan-fps` | 4 | Zero analisa todos os frames |
| `--confirm-seconds` | 0,15 | Rejeita oscilações breves de classificação |
| `--min-duration` | 1 | Duração mínima do clipe em segundos |
| `--max-clip-seconds` | 60 | Divide intervalos longos; zero desativa a divisão |
| `--margin-seconds` | 0 | Retira uma margem de ambas as pontas do intervalo |
| `--analyze-only` | falso | Gera relatório sem codificar clipes |
| `--encoder` | libx264 | CPU ou h264_nvenc |
| `--ffmpeg`, `--ffprobe` | PATH | Caminhos explícitos para os executáveis |

Cada clipe começa no primeiro frame confirmado sem Explorer e termina no timestamp
do último frame observado sem Explorer, excluindo conservadoramente sua duração.
Intervalos incertos nunca são unidos. Trechos e sobras inferiores à duração mínima
são descartados. As subdivisões dos intervalos contínuos são registradas em segundos.

## Arquivos e validação

`segments.json` guarda perfil, parâmetros, hashes das referências, tamanho/data do
vídeo, observações com scores, intervalos ambíguos, transições e clipes planejados.
`report.md` mostra tempos e links para imagens. `export.json` registra os clipes
exportados e o hash da análise. A exportação confere tamanho/data do vídeo, o que
detecta substituições usuais, mas não equivale a um hash completo do MOV.

Pastas existentes são recusadas. Em uma falha de exportação, clipes concluídos
permanecem e o `.partial.mp4` da tentativa é removido. Escolha outra pasta para
repetir; não há retomada automática nesta versão.

Testes locais usam imagens e vídeo sintéticos: resolução, região inválida, tela
desconhecida, ambiguidade, oscilações curtas, fronteiras de transição, análise de
todos os frames e recodificação. O MOV real é validação adicional, não requisito
da suíte unitária.

### Validação local de IMG_5886.MOV

Execução automática com modelos já em cache, amostragem de 2 fps e refinamento
das fronteiras: 17 transições e 19 clipes, somando aproximadamente 422,28 s.
A primeira ocultação ficou entre 7,320 s (último frame reconhecido com painel)
e 7,528 s (primeiro frame confirmado sem painel). Os intervalos incertos foram
excluídos; clipes contínuos têm no máximo 60 s.

Artefatos locais: `saida/explorer-5886-auto/analysis/report.md`,
`analysis/segments.json`, `analysis/transitions_overview.jpg` e `clips/`.
Os 19 MP4 foram conferidos com ffprobe: 1080×1920, áudio presente e diferença
de duração inferior a 4 ms em relação aos cortes planejados. O detector
classificou os frames inicial e final de cada clipe como sem painel; isso é
uma verificação de consistência, não uma avaliação independente de acurácia.
A montagem das 17 transições também foi inspecionada visualmente.

Essa execução não certifica todos os frames nem outros vídeos. Mudanças muito
breves podem escapar da amostragem; `--scan-fps 0` permite análise exaustiva.
