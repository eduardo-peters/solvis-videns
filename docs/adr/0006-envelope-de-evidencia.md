# ADR-0006: todo resultado vem num envelope de evidência

- Status: proposto
- Data: 2026-11-17

## Contexto

Para não alucinar, a LLM precisa de mais que o valor: precisa saber o tamanho da amostra, o que foi incluído, o período efetivo, o frescor e como citar. No Data Chat esse contexto vai para o narrador como tabela e regras; para uma LLM externa ele precisa vir estruturado.

## Decisão

Toda resposta de métrica tem a forma descrita em `components.schemas.MetricEnvelope` do [OpenAPI](../../api/openapi.analytics.v1.yaml). Campos obrigatórios:

| Campo | Para quê |
|---|---|
| `query_id` | Citação e auditoria. `GET /queries/{id}` devolve o pedido e o resultado gravados |
| `model_version` | Saber com qual definição o número foi calculado |
| `metric` | id, rótulo, unidade e definição curta |
| `scope` | pesquisa(s) e pergunta(s) com id, número, texto e tipo |
| `period` / `comparison` | datas efetivas, base temporal (`started_at` local da unidade), de onde veio (preset ou datas) |
| `filters` | filtros aplicados já resolvidos (ids e nomes) |
| `policies` | confiabilidade, incompletas, LGPD aplicadas a esta consulta |
| `freshness` | watermark do espelho e se está defasado |
| `rows[]` | dimensões, `value`, `n`, decomposição (ex.: promotores/neutros/detratores), valor comparado e variação |
| `totals` | o mesmo calculado sobre o conjunto inteiro, pelas contagens |
| `truncated`, `available_rows` | se a lista foi cortada |
| `warnings[]` | códigos fixos: `small_sample`, `multi_response_sum_exceeds_100`, `values_from_current_questionnaire`, `partial_comment_coverage`, `partial_bucket`, `comparison_window_adjusted`, `stale_mirror`, `no_data` |

A skill exige que todo número citado venha de um envelope e cite o `query_id`.

## Consequências

- Respostas maiores que uma tabela simples; o adaptador MCP pode compactar campos repetidos.
- A auditoria grava o envelope inteiro (ou um hash dele) para que um número citado num relatório possa ser reconferido depois.
