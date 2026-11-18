# Camada de engenharia de dados semântica do piloto

Como o motor local transforma a API pública V1 num modelo por id e calcula as métricas com as regras das telas. Código em `skills/solvis-survey-analysis-pilot/scripts/solvis_pilot/`. Referências ao `survey_system` são do commit `f594c4a6`.

```
API V1 (só leitura)
  │  api.py       token OAuth (password/refresh), GET com repetição em 429/5xx, User-Agent do piloto
  ▼
catalog.py        lista de permissão (GET /surveys/:id é filtrado pelo cliente), questionário, unidades
  │
sync.py           janelas por dia local, divisão em página cheia / HTTP 400 / lista vazia, livro de cobertura
  │
ingest.py         formatted_answers (textos) → answers por question_id/choice_id; privacidade
  │
store.py          SQLite local por credencial: evaluations, answers, answer_tags, days, issues
  │
query.py          SQL por métrica e recorte → measures.py (fórmulas) → envelope com avisos e cobertura
comments.py       comentários mascarados com grupo NPS do autor e tags
```

## 1. Extração (`sync.py`)

| Comportamento da API (`app/controllers/api/v1/surveys_controller.rb`) | Tratamento |
|---|---|
| `end_date` é comparado no segundo (`BETWEEN start AND end`), sem fim do dia | Janela enviada como `AAAA-MM-DDT00:00:00` a `AAAA-MM-DDT23:59:59` |
| `started_at` é a hora local da unidade; os parâmetros sem fuso são comparados direto com ele | Datas sem offset; cada janela é um intervalo de dias locais |
| Paginação aplicada **por shard** e ordenada por `created_at` (com empates nos lotes de totem), sem total | Não pagina: pede janelas que cabem numa página (`per_page=5000`); se a resposta vier com 5000 ou mais, divide a janela ao meio (por dia, depois por segundos) e descarta a resposta cheia |
| Qualquer erro na montagem das respostas devolve **HTTP 200 com `data: []`** para a janela inteira (`handler_answers_service.rb:14-19`) | Janela de vários dias vazia, em pesquisa com avaliação registrada depois do início da janela, é conferida dia a dia. Uma falha custa só o próprio dia |
| Unidade inexistente na janela devolve **HTTP 400** (`SurveyedUnit.find`) | Divide a janela até menos de 1 hora; o trecho que continua falhando entra em `coverage.failed_windows` e o dia fica `partial` |
| `GET /surveys/:id/evaluations` não filtra por cliente | O motor só pede avaliações de pesquisa que `GET /surveys/:id` (filtrado por cliente) devolve |
| `search_date_scope` e `reliable` passam para o SQL sem tratamento | `reliable` nunca é enviado (a confiabilidade é filtrada localmente). `search_date_scope` só vai com o literal fixo `received_at`, nunca com valor externo, para a atualização incremental (seção abaixo) |

Livro de cobertura (`days`): uma linha por (pesquisa, dia local) com status `ok`/`partial`, contagem e `fetched_at`. Regras de atualização: hoje, a cada 10 minutos; até 3 dias atrás (totens offline enviam atrasado), a cada hora; dias antigos, a cada 7 dias (`SOLVIS_CACHE_TTL_DAYS`); `partial`, a cada hora. Hoje e os dias até 3 dias atrás são atualizados de forma incremental (abaixo); os demais são baixados por inteiro. O tamanho da janela inicial (até 7 dias) se adapta ao volume e fica guardado por pesquisa.

**Mês inicial.** A API não informa quando a pesquisa começou (`first_evaluation_date_cache` e `created_at` não saem no serializer da V1), então o usuário escolhe o primeiro mês que interessa na primeira consulta. O valor fica no cache da credencial (`meta.start_month`). `Syncer.ensure`, por onde passam `query`, a comparação, `comments` e `sync`, recusa a chamada sem ele (`start_month_required`) e recusa período que comece antes dele (`period_before_start`), antes de qualquer requisição de avaliações.

**Atualização incremental por `created_at`.** Para os dias recentes já baixados, o motor pede só o que o servidor recebeu depois do download mais antigo entre eles (`search_date_scope=received_at`, janela em UTC, com 5 minutos de folga), descarta o que já está no cache (`eval_ref`) e acrescenta o restante aos dias de `started_at` correspondentes. Isso também pega a avaliação atrasada de totem offline, cujo `started_at` é de dias atrás. Volta ao download inteiro por dia quando a janela passa de 7 dias ou quando a API falha em algum trecho dela.

Limites assumidos:
- A API escolhe os shards pelas datas da janela, e cada avaliação fica no shard do mês do seu `started_at`. Uma avaliação recebida agora com `started_at` num shard antigo não aparece na busca por `created_at`. Os shards antigos quase não recebem dados novos, e a decisão foi ignorar esse caso. Dias antigos continuam sendo relidos por inteiro a cada 7 dias.
- Tags aplicadas depois a avaliações que já estão no cache só entram na releitura por inteiro do dia.
- Uma janela vazia não é conferida dia a dia, como na busca por `started_at`. Se uma avaliação que não monta zerar a janela, ela some até a releitura por inteiro do dia.

Orçamento de tempo: cada execução baixa por até 90 s (abaixo do tempo limite de comando dos hosts) e devolve `sync_incomplete`; a execução seguinte continua.

## 2. Normalização (`ingest.py`, `semantics.py`)

A API não devolve `question_id` nem `choice_id` nas respostas. O motor volta aos ids pelo questionário atual, que é o mesmo que a API usou para montar os textos (`question.text` e `choice.text`, cadastro atual).

| Tipo | Formato na API | Linha normalizada |
|---|---|---|
| NPS | `[{question_text, answer_value, answer_text}]` | `score`; válida se 0..10 (o totem grava sem validar) |
| Scale | `[{question_text, choice_text, choice_value}]` (valor em string, "5.0") | `choice_id` pelo texto da alternativa (desempate pelo valor) |
| Multiple Choice | `[{question_text, choice_text, additional_field?, additional_field_answer?}]` | `choice_id` + texto do campo adicional mascarado |
| Multiple Response | objeto `{question_text: [{choice_text...}]}`; `choice_text: null` = deixou em branco | uma linha por alternativa; branco conta no denominador |
| Text, Short Text | `[{question_text, choice_value?}]` (a chave some se vazio) | texto mascarado; vazio conta como não respondida |
| Numeric, Email, Phone, Date, CPF, CNPJ | lista de listas `[[{question_text, choice_text}]]` | só a presença da resposta |

**Chave da avaliação:** `eval_ref = yymmdd(started_at) + id com 12 dígitos`, igual ao `unique_id` do sistema (`with_unique_id.rb`). O `id` sozinho colide entre shards.

**Perguntas de mesmo tipo e texto.** A API funde essas perguntas: o texto não diz qual foi respondida. O motor separa em duas etapas. Primeiro, em escala e escolha única, fica só a gêmea que tem a alternativa respondida (gêmeas com alternativas diferentes se separam assim). Depois, a ordem: nos dados reais, a ordem das respostas dentro de um tipo segue a posição das perguntas (426 pares conferidos, nenhum fora de ordem). O motor calcula, para cada item, as perguntas possíveis em alguma atribuição estritamente crescente da sequência inteira, e atribui quando sobra uma. A métrica de uma pergunta gêmea só sai se todas as respostas do período foram atribuídas; senão, `ambiguous_question_text` com as contagens. Múltipla resposta não entra (a API funde as gêmeas no mesmo objeto).

**Alternativa que não existe mais** (`choice_text: null` em Scale/MC): fica fora das métricas, como nas telas (`choice_id IN alternativas atuais`), e entra em `issues` → aviso `answers_excluded`.

**Questionário editado durante o download:** se aparecer resposta de pergunta desconhecida, o motor relê o questionário e mapeia de novo.

## 3. Privacidade na ingestão (`privacy.py`)

- `web_access_info` (IP, fingerprint, identificador do respondente) é descartado antes de qualquer gravação.
- Perguntas `lgpd_protected` e tipos pessoais (e-mail, telefone, CPF, CNPJ, data, numérico): só a presença da resposta é guardada.
- Comentários e campos adicionais: e-mail, CNPJ, CPF, telefone e sequências de 8+ dígitos viram `[email]`, `[cnpj]`, `[cpf]`, `[telefone]`, `[número]`. Nomes próprios não são mascarados (risco residual).
- Cache, token e registro de consultas ficam numa pasta por credencial com permissão 700 (`~/.cache/solvis-survey-analysis/`). `purge --yes` apaga tudo.

## 4. Cálculo (`measures.py`, `query.py`)

| Métrica | Regra das telas reproduzida |
|---|---|
| NPS | `round(100.0 × (P/n − D/n))` com o arredondamento do `Float#round` do Ruby sobre o valor binário (29 P, 0 D, n = 200 → 14) |
| Média de escala | Σ(contagem × valor)/Σ(contagem) só com alternativas com valor; casas pela amplitude (`question.rb:323-335`); % em escala 0..100 |
| Soma ponderada | `round(Σ(100 × contagem/n × valor))`; recusa `scale_mean` nessas perguntas e vice-versa |
| Distribuição | denominador com "Não se aplica"; ordem por contagem quando as alternativas são aleatórias |
| Múltipla resposta | avaliações que marcaram / avaliações com linha na pergunta (inclusive em branco) |
| Agregados | sempre por contagens: `totals` é uma consulta sem recortes, não a soma das linhas |
| Propriedade de unidade | agregado das unidades que hoje têm o valor (cadastro atual) |
| Variação | sobre os valores exibidos; NPS também por grupo em p.p.; contagens com variação percentual |
| Comparação | `previous_period` respeita mês, trimestre e ano de calendário; `previous_year` casa baldes de tempo com o mesmo balde do ano anterior |

Tudo é feito em SQL sobre o cache (contagens) e Python (fórmulas e exibição). Não há dependências fora da biblioteca padrão do Python 3.9.

## 5. Avisos de qualidade

| Aviso | Origem |
|---|---|
| `incomplete_coverage` | dias `partial` ou faltando no período |
| `possible_silent_failure` | zero avaliações no período, mas `last_evaluation_date_cache` da pesquisa é posterior ao início |
| `suspicious_empty_days` | dia vazio no meio de série com média ≥ 20 por dia, num dia da semana que costuma ter avaliação |
| `includes_unverified_evaluations` | pesquisa com Data Quality (a chave `reliable` só vem nessas pesquisas) e política `all` |
| `values_from_current_questionnaire` | `questionnaire.version > 1` |
| `answers_assigned_by_order`, `answers_excluded` | normalização |
| `small_sample` | n < 30 (`SOLVIS_SMALL_SAMPLE`) |

## Achados do teste em produção

Credencial de teste, 2026-11-17, só leitura.

| Achado | Efeito | Mudança no motor |
|---|---|---|
| A credencial vê 1.453 pesquisas (742 arquivadas) e `GET /api/v1/surveys` devolve o questionário inteiro de cada uma: 21,5 MB, cerca de 5 s por página de 100 | `scope` levava minutos e a saída tinha 343 mil caracteres | O motor usa `GET /surveys/:id` por pesquisa; a lista inteira só é baixada para `scope`/`surveys`/busca e vira um índice compacto; `scope` mostra só as 15 mais recentes ativas |
| Uma pesquisa real tinha 24 pares (tipo, texto) repetidos, até 6 perguntas com o mesmo texto ("Telefone:") | 466 respostas em perguntas de texto repetido, nenhuma com pergunta definida | Atribuição pela alternativa e pela ordem: 283 atribuídas, 183 continuam sem dono (sobretudo e-mail, telefone e comentários repetidos em blocos de clientes diferentes); métrica recusada só quando sobra resposta sem dono no período |
| Teste com agente de contexto limpo seguindo só o `SKILL.md`, 5 perguntas de gestor na API real | Respostas corretas e com fontes; 20 pontos de ajuste nas instruções e no envelope | Percentuais com `*_display`, lista de perguntas aplicáveis em `question_required`, unidades que pararam de responder no diagnóstico, `small_sample` só em notas e percentuais, aviso de Data Quality só quando há reprovadas ou não verificadas, regras para várias perguntas NPS, CSAT e homônimos exatos, fontes em recusas, horário de download em São Paulo, separação de gêmeas pela alternativa |
| A ordem das respostas dentro de um tipo segue a posição das perguntas | — | Base da atribuição pela ordem |
| Valores de alternativa chegam em string ("100.0"); `options` chega como objeto | Conforme o previsto | — |
| Pesquisa esparsa (8 dias com avaliação em 90) gera 55 chamadas por causa da conferência dia a dia de janelas vazias | 43 s no primeiro download de 90 dias | Aceito no piloto; o cache evita repetir |
