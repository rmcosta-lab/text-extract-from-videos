# Validação da numeração

Sem limite manual, a extração tenta confirmar automaticamente o fim visível do
arquivo. Exige cinco números finais consecutivos, confiantes e alinhados, código
ao lado da margem e espaço vazio abaixo equivalente a pelo menos seis linhas.
Esse espaço é verificado nos pixels do frame: ausência de texto no OCR não basta.
O mesmo final deve aparecer em dois frames distintos separados por pelo menos
0,15 segundo. Finais conflitantes ou uma sequência final confiável com números
maiores impedem a inferência.

Sem confirmação, o limite fica `null` e o relatório declara **desconhecido**;
os filtros de numeração suspeita continuam ativos. `line_limit` nos parâmetros,
manifesto e auditoria registra origem (`inferred`, `manual`, `unknown`), motivo
e frames de confirmação. A opção manual tem precedência. A inferência é
conservadora: imagens indisponíveis, cortes próximos à última linha e margem
sem geometria suficiente deixam o limite desconhecido. Área vazia aparente
por oclusão ou edição do vídeo ainda pode enganar a análise visual.

Use `--max-line-number 548` na extração quando souber que a última linha do
arquivo fonte é 548. Esse limite é opcional, positivo e fica registrado em
`extraction_parameters.json`. Ele se refere à numeração do arquivo fonte,
não à quantidade de linhas do arquivo extraído.

Leituras acima do limite e números isolados ou pequenos grupos distantes da
sequência predominante de um frame são classificados como suspeitos. O relatório
lista o número lido, o frame, o tempo e o motivo em **Erros suspeitos de numeração**.
Essas leituras não participam da reconstrução numerada nem geram linhas faltantes.
Seu conteúdo continua disponível em `ocr_raw.csv`, no manifesto de revisão e em
`line_number_audit.json` (`rejected_reads`).

O filtro automático exige uma sequência dominante com pelo menos quatro números
distintos e 75% dos números do frame; grupos equilibrados são inconclusivos.
Um salto grande entre frames, sozinho, não é motivo de rejeição: pode ser scroll.
O limite conhecido é a garantia contra números acima do final do arquivo; o maior
número retornado pelo OCR não é um limite confiável. Erros dentro desse limite
ainda podem ocorrer e exigem inspeção dos frames.

As recuperações espaciais de numeração existentes continuam documentadas em
`line_number_audit.json` (`decisions`), com o OCR original preservado.
