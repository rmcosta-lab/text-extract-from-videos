# Bancada local de clips

Inicie na raiz do projeto, usando o ambiente com Paddle instalado:

```powershell
uv run --group paddle-gpu --group review --env-file .env.local python clip_workbench.py
```

Abra <http://127.0.0.1:8770>. Para trocar a porta, acrescente `--port 8771`.
Sem revisão, o grupo `review` e `--env-file .env.local` são opcionais. Se o
ambiente já estiver sincronizado, também é possível iniciar diretamente com
`.venv/Scripts/python.exe clip_workbench.py`, herdando as variáveis do terminal.
A interface não lê nem exibe a chave; o processo de revisão herda o ambiente.

## Fluxo

1. Informe a pasta dos vídeos ou use **Procurar pasta**. Exemplo:
   `saida/IMG_5885-explorer/clip`. A descoberta não depende de `clips.json`.
   Apenas os vídeos diretamente nessa pasta são listados, sem busca recursiva.
2. Clique no nome de um clip para editar seus ajustes. Marque as caixas dos
   vídeos que deseja processar. Cada clip mantém seus próprios valores.
3. Se necessário, informe início/fim e use **Sugerir crop**. O estado da análise
   aparece junto ao botão; quando terminar, clique em **Abrir preview de crop**
   nessa mesma área. Falhas também aparecem ali. Compare os frames,
   ajuste o recorte e cole os parâmetros em **Crop compartilhado** para usar em todos
   os clips. Para personalizar um vídeo, use o campo em **Ajustes do clip**.
   O campo individual vazio usa o compartilhado; quatro parâmetros com valor `0`
   desativam o recorte nesse vídeo. O padrão permanece ao carregar outra pasta.
   Os mesmos tempos são usados para sugestão e extração, mas as engines podem
   ser escolhidas separadamente.
4. Confira engine, extensão e destinos. A extensão é inferida do sufixo de
   código: `clip_006__vector_names.py.mp4` sugere `py`. Sem um sufixo reconhecido,
   a interface informa a ausência de inferência e permite escolher `txt`, `md`
   ou `py`. Uma extensão não corrige nem valida o código extraído.
5. Escolha **Extrair código**, **Revisar extração existente** ou **Extrair +
   revisar** e inicie a seleção. Os logs e estados são atualizados durante a
   execução. A contagem representa etapas encerradas, inclusive falhas; não é
   uma estimativa inventada do progresso interno do OCR.

## Padrões e caminhos

Os padrões abaixo pertencem somente à interface. Os comandos existentes mantêm
os valores padrão e comportamento anteriores.

| Operação | Padrões da interface |
| --- | --- |
| Sugestão de crop | Engine `paddle`, tempos opcionais |
| Extração | Engine `paddle`, `--prepare-review`, extensão inferida ou `txt` |
| Revisão | `--image-detail original --system-certs --max-output-tokens 64000` |

A revisão visual usa a API paga da OpenAI, com modelo e chave configurados como
no [fluxo de revisão](review-workflow.md). Não existe engine OCR na revisão.
O modo combinado exige a preparação de evidências. Revisão isolada reutiliza
uma extração preparada; valida manifesto e imagens antes da chamada à API.

Para `<projeto>/clip/<nome>.mp4`, a base automática é `<projeto>/extract`:

```text
saida/IMG_5885-explorer/
  clip/clip_006__vector_names.py.mp4
  extract/clip_006__vector_names.py/
    extract/   ← OCR, parâmetros, frames e manifesto
    revisao/   ← cópia revisada, diff, relatório e registros
```

A base pode ser informada antes de carregar a pasta. Para outros layouts, a
interface apresenta a base sugerida explicitamente nos destinos. Uma nova
extração pode limpar/substituir artefatos anteriores, conforme o comportamento
da CLI. A revisão também mantém suas regras existentes para destinos já usados;
para recuperação avançada, use `--resume`/`--reapply` pela CLI.

## Operação local e limites

A extração valida números detectados em caixas separadas na coluna do editor.
Quando ao menos quatro números próximos sustentam a mesma sequência espacial,
ela pode recuperar um dígito lido incorretamente (por exemplo, `0` no lugar de
`9`). A recuperação fica restrita ao intervalo entre referências confiáveis;
não preenche texto ausente nem extrapola números nas bordas do frame.
Casos com evidência geométrica conflitante ficam sem número confiável, e o
número zero nunca participa da reconstrução numerada.

O arquivo `extract/line_number_audit.json` registra o frame, o índice da caixa
entre as caixas não vazias, a leitura original, o número recuperado (ou `null`),
o motivo e os números usados como referências. `ocr_raw.csv` e as evidências
brutas do manifesto continuam intactos. A validação usa as caixas OCR existentes,
sem chamadas adicionais ao motor OCR. Ela se aplica a novas extrações, tanto na
bancada quanto na CLI; resultados antigos precisam ser extraídos novamente.

Durante a revisão, o painel **Etapas da revisão** mostra preparação das evidências,
bloco atual, espera pela resposta, validação e gravação dos arquivos. A etapa
ativa exibe um contador; as anteriores mantêm sua duração e indicação de conclusão
ou falha. A espera inclui o envio realizado pelo SDK e a resposta do modelo, sem
estimar percentual ou alegar quais frames o modelo já analisou. A pré-verificação
local aparece identificada separadamente.

Os tempos são registrados na fila em memória e nos logs da sessão. O histórico
não sobrevive ao reinício do servidor. Novas revisões iniciadas pela bancada
habilitam esses eventos automaticamente; a saída normal dos comandos CLI não muda.
Após atualizar o código Python, aguarde a fila terminar e reinicie a bancada para
ativar o acompanhamento. Execuções anteriores não ganham tempos retroativamente.

- A fila é sequencial e aceita um lote por vez. Uma falha bloqueia a revisão
  dependente daquele clip, mesmo que existam arquivos antigos; os demais seguem.
- O preview é encerrado ao iniciar outra operação, liberando os recursos. Não
  inicie o lote antes de copiar os parâmetros desejados. Fechar a aba não encerra
  o servidor; use Ctrl+C no terminal para parar os processos gerenciados.
- A fila e os logs recentes ficam em memória, não são recuperados após reiniciar.
  São retidos até 20 lotes e 1.000 linhas de log por clip (4.000 caracteres por
  linha). Os artefatos dos scripts continuam persistidos em disco.
- Navegação, assets, crop e extração são locais. Paddle requer modelos já
  disponíveis em cache para uso offline; a instalação inicial pode baixá-los.
- A aplicação escuta apenas `127.0.0.1`; não a exponha por um proxy remoto.
- Sem Node ou build de frontend: FastAPI serve HTML, CSS e JavaScript locais.
  A interface usa um estado pequeno por clip e polling dos jobs; React não
  trouxe benefício suficiente para justificar um novo build nesta fase.
