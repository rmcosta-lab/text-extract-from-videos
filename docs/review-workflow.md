# Revisão recuperável, auditável e mensurável

O OCR e a revisão continuam separados. A revisão preserva o texto extraído,
propõe alterações apoiadas pelos frames e publica uma cópia com diff. Nenhum
comando de recuperação local precisa da API ou da chave.

## Fluxo e arquivos

1. Validar texto, manifesto e evidências; montar todos os blocos e conferir limites.
2. Registrar `review_run.json`: configuração, hashes do texto, manifesto, imagens
   enviadas, instruções, schema e plano; intervalos e seleção de frames por bloco.
3. Fazer uma chamada por vez. Antes de interpretar ou aplicar a resposta, salvar
   `responses/block_0001/attempt_0001.json` e assim por diante.
4. Validar status, JSON, linhas, texto anterior, evidências e fronteiras dos blocos.
5. Depois de validar todos os blocos, publicar os arquivos e marcar a execução
   como `completed` por último.

Cada tentativa contém texto retornado, recusas, motivo de interrupção, ID,
modelo, orçamento e consumo informado pela API. Não contém a chave, cabeçalhos
de autenticação ou imagens em base64. Respostas incompletas ficam guardadas para
diagnóstico, mas nunca são aplicadas parcialmente. Uma falha de transporte pode
não produzir resposta recuperável; repetir esse bloco pode gerar outra cobrança.

Os registros usam arquivo temporário e substituição atômica. Os resultados são
preparados em uma pasta temporária antes da publicação; `revisao.json` é publicado
por último. Não há transação única do sistema de arquivos para toda a pasta:
após encerramento abrupto durante publicação, pode haver arquivos parciais.
Resultados finais existentes não são sobrescritos; preserve-os antes de tentar
novamente. Use uma pasta por execução e não execute dois processos na mesma pasta.

Arquivos finais:

| Arquivo | Uso |
|---|---|
| `codigo_revisado.md` / `.py` / `.txt` | Cópia com sugestões aplicadas |
| `comparativo.diff` | Diferenças entre original e revisado |
| `revisao.json` | Edições, pendências, configuração e auditoria |
| `line_mapping.json` | Correspondência de linhas físicas |
| `relatorio_revisao.md` | Resumo, motivos, antes/depois, pendências e links para imagens |

Linhas inalteradas têm correspondência exata. Cada linha de uma substituição
aponta para o intervalo resultante completo, sem inventar equivalência individual.
Exclusões aparecem com destino nulo. As pendências referem-se sempre ao original;
o relatório também mostra sua localização ou intervalo no revisado.

## Recuperação e relatório sem API

Para uma execução interrompida que já tenha respostas completas válidas para
todos os blocos:

```powershell
uv run python review_ocr.py --extraction saida/casos_de_uso --output saida/casos_de_uso/revisao-nova --reapply
```

`--reapply` usa a configuração gravada, sem carregar o SDK, exigir chave ou
reenviar dados. Recalcula hashes das entradas e revalida as respostas. Se faltar
um bloco válido, informa a falha e não publica o resultado. Não é um comando para
forçar a aceitação de edições inválidas ou sobrescrever revisões concluídas.

Para gerar ou atualizar somente o relatório e o mapa de uma revisão antiga:

```powershell
uv run python review_ocr.py --extraction saida/casos_de_uso --output saida/casos_de_uso/revisao-gpt --report-only
```

O comando confere hashes do original e manifesto e reconstrói o resultado para
verificar se coincide com o arquivo revisado. Não altera código, diff ou a resposta
salva. Revisões antigas suportam este relatório, mas não possuem respostas brutas
retroativamente: o salvamento de tentativas vale para novas execuções.

## Blocos e seleção de imagens: opcionais

Sem opções novas, a revisão continua em uma única chamada com todos os frames.
Para experimentar blocos de 100 linhas com dez linhas de contexto de cada lado:

```powershell
uv run --group review --env-file .env.local python review_ocr.py --extraction saida/casos_de_uso --output saida/casos_de_uso/revisao-blocos --chunk-lines 100 --context-lines 10 --frame-selection coverage --max-frames 30 --max-output-tokens 32000 --image-detail original --system-certs --dry-run
```

Remova `--dry-run` para executar chamadas pagas. Para retomar após uma falha,
repita o mesmo comando de execução com `--resume`: modelo, raciocínio, orçamento,
contexto, seleção e demais parâmetros devem permanecer iguais. Alterações no
`.env.local` também podem alterar a configuração efetiva. Mudar configuração exige
uma nova pasta. Blocos válidos são reaproveitados; tentativas anteriores são mantidas.

| Opção | Padrão e comportamento |
|---|---|
| `--chunk-lines N` | Ausente: chamada única; sugestão experimental: 100 |
| `--context-lines N` | 10 linhas de contexto somente para leitura |
| `--frame-selection all` | Todos os frames; em blocos, todas as observações associadas ao intervalo e contexto |
| `--frame-selection coverage` | Frames escolhidos na reconstrução e melhor evidência de cada leitura alternativa |
| `--max-frames` | 12 por chamada; não descarta imagens para caber |
| `--max-output-tokens` | 12000, ou `OPENAI_REVIEW_MAX_OUTPUT_TOKENS`; CLI tem prioridade; inclui raciocínio e JSON |
| `--resume` | Retoma execução com mesmo plano e entradas |
| `--reapply` | Recuperação local usando configuração e respostas salvas |
| `--report-only` | Relatório local de revisão concluída, inclusive antiga |

Os três modos de recuperação/relatório são mutuamente exclusivos. `--dry-run`
não escreve resultados nem chama a API; mostra intervalos, frames, bytes e motivo
de eventual seleção de todos os frames. `--report-only` não aceita `--dry-run`.

Cada bloco mantém a numeração física global. Edições e pendências são permitidas
apenas no intervalo principal. Alterações que atravessem a fronteira são rejeitadas;
não são cortadas automaticamente. Nesse caso, uma nova execução pode usar blocos
maiores ou revisão única. Nada é publicado enquanto algum bloco estiver inválido.

O limite local de imagens é 25.000.000 bytes por chamada, antes de base64; texto
é limitado a 100.000 caracteres por intervalo enviado. Todos os blocos passam
pelo planejamento antes da primeira chamada. Não há redução silenciosa de evidência
nem aumento automático do orçamento. O contexto aumenta texto e imagens repetidos.

### Como funciona a cobertura

Usa a proveniência da linha reconstruída e a numeração do editor para localizar
as demais leituras OCR. O frame escolhido para cada linha/contexto é obrigatório.
Para cada leitura alternativa distinta, prioriza nitidez, depois confiança e,
em empate, menor número do frame. Similaridade textual isolada não prova cobertura.

Sem numeração ou proveniência confiável, mantém todos os frames e registra o
motivo. O plano guarda selecionados, descartados e justificativas. Mantém WebP
qualidade 90, crop e resolução atuais; JPEG preparado continua aceito.

Blocos podem aumentar o consumo total por repetir imagens/contexto. WebP reduz
bytes, mas não garante economia proporcional de tokens. `usage` soma respostas
aproveitadas; `attempt_usage` inclui todas as tentativas recebidas nesta execução,
inclusive inválidas. Isso não inclui chamadas cuja resposta não foi recebida.

## Avaliação de fidelidade

```powershell
uv run python evaluate_review.py --extraction saida/casos_de_uso --review saida/casos_de_uso/revisao-gpt --reference tests/fixtures/casos_de_uso.review.reference.json --output saida/casos_de_uso/avaliacao-revisao
```

O avaliador é local e não precisa de GPU, vídeo completo ou SDK da OpenAI. Confere
o hash do original e usa o mapa de alterações, sem buscar no documento uma linha
que coincida melhor com a referência. Produz `avaliacao_revisao.json` e
`avaliacao_revisao.md` com CER, WER, texto exato, indentação, linhas corrigidas e
regressões. O JSON inclui os textos e intervalos efetivamente comparados.

A referência inicial contém 30 linhas distintas transcritas visualmente pelo
assistente nos frames 2400, 2790 e 3210, sem usar a revisão como verdade. Uma
conferência humana independente ainda é necessária. O literal com `A` tem
espaçamento interno ambíguo e foi excluído integralmente. Substituições que
abrangem linhas não transcritas ou mudam a quantidade de linhas também são
excluídas: precisam de uma referência do intervalo completo. Não se escolhe a
melhor linha de uma substituição para inflar o resultado.

CER e texto exato preservam espaços internos; WER usa palavras separadas por
espaços. Indentação usa espaços equivalentes à imagem; tabs e espaços não são
distinguíveis no vídeo. Métricas de exatidão/indentação contam intervalos quando
uma substituição reúne várias linhas; o relatório informa os denominadores.

Esta amostra não mede todos os erros, conteúdo não amostrado ou a correção
semântica do código. Muitas alterações e poucas pendências não certificam
fidelidade. Comparar revisão única, blocos e cobertura exige execuções explícitas,
com modelo e parâmetros registrados; os novos modos continuam opcionais.

### Medição inicial: revisão existente de casos_de_uso

Sem repetir a chamada paga, a revisão existente apresentou:

| Métrica | OCR original | Revisado |
|---|---:|---:|
| CER | 1,36% | 0,42% |
| WER | 10,47% | 1,16% |
| Texto exato | 13/21 | 17/21 |
| Indentação correta | 18/21 | 18/21 |

Foram comparadas 21 das 30 linhas: uma excluída por espaçamento ambíguo e oito
por ausência de referência completa para a substituição. Quatro linhas passaram
a coincidir exatamente; nenhuma regressão apareceu nas linhas comparáveis.
Não houve avaliação humana independente nem novas chamadas para comparar modos.
Os resultados detalhados ficam em `saida/casos_de_uso/avaliacao-revisao/` e podem
ser regenerados com o comando acima. A referência é vinculada ao hash do OCR:
outra extração exige uma referência com âncoras conferidas para essa extração.
