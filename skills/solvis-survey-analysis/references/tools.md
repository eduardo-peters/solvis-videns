# Ferramentas

As ferramentas têm o mesmo nome no servidor MCP `solvis-analytics` e correspondem 1:1 a endpoints da API Analytics v1 (`/api/analytics/v1`). Contrato completo: `api/openapi.analytics.v1.yaml` no repositório da skill.

| Ferramenta | Endpoint | Para quê | Fase |
|---|---|---|---|
| `get_scope` | `GET /scope` | Cliente, quantas pesquisas/unidades a credencial vê, escopos (`comments`, `lgpd`, `reliability`), políticas padrão, frescor, limites de uso | 1 |
| `get_semantic_model` | `GET /model` | Modelo semântico em uso (`model_version`). Use se o envelope trouxer MAJOR diferente do snapshot | 1 |
| `list_surveys` | `GET /surveys` | Pesquisas com id, nome, arquivada, Data Quality ligado, primeira/última avaliação, contexto de negócio | 1 |
| `get_questionnaire` | `GET /surveys/{survey_id}/questionnaire` | Perguntas, tipos, escalas, alternativas, desvios | 1 |
| `list_units` | `GET /units` | Unidades com cidade, UF, propriedades, contexto de negócio | 1 |
| `list_tags` | `GET /tags` | Temas/tags do cliente com hierarquia e descrição | 1 |
| `resolve_entities` | `POST /resolve` | Texto → candidatos com id (pesquisa, pergunta, alternativa, unidade, valor de propriedade, tag) | 1 |
| `query_metric` | `POST /query` | Calcula uma métrica do modelo e devolve o envelope | 1 |
| `get_query` | `GET /queries/{query_id}` | Reabre uma consulta já feita (pedido, datas efetivas, resultado) | 1 |
| `search_comments` | `POST /comments/search` | Comentários com unidade, data, grupo NPS do autor e análise do Radar | 3 |

## `query_metric`

```json
{
  "metric": "nps",
  "survey_id": 56,
  "question_id": 812,
  "period": {"preset": "last_month"},
  "compare_with": "previous_year",
  "filters": {
    "unit_ids": [101, 102],
    "property_value_ids": [],
    "channel": "web",
    "completion": "all",
    "reliability": "default"
  },
  "group_by": ["unit"],
  "order": {"by": "value", "direction": "asc"},
  "limit": 50
}
```

- `metric`: um id de `metrics.yaml` com `status: available` na fase vigente.
- `question_id`: obrigatório para métricas de pergunta. Confira o tipo em `get_questionnaire` antes.
- `period`: `{"preset": "..."}` ou `{"start": "AAAA-MM-DD", "end": "AAAA-MM-DD"}`. Sempre envie; sem pedido do usuário, use `last_90_days`.
- `compare_with`: `previous_period` ou `previous_year`. Cada linha traz `compared` e `delta`.
- `group_by`: até 2 de `unit`, `unit_property:<property_name_id>`, `day`, `week`, `month`, `quarter`, `channel`, `completion` (fase 1). A API recusa combinações fora de `dimensions.yaml#compatibility` com `422 unsupported_combination`.
- `order` + `limit`: para rankings ("pior loja"). Com `order.by = value`, a primeira linha é de fato a pior/melhor do conjunto inteiro.
- `min_n` (opcional): oculta linhas com n menor; por padrão nada é ocultado e linhas pequenas vêm com aviso.

## Como ler o envelope

```json
{
  "query_id": "q_7Hk2mP",
  "model_version": "1.0.0",
  "metric": {"id": "nps", "label": "NPS", "unit": "points"},
  "scope": {"survey": {"id": 56, "name": "Pesquisa Lojas"},
            "question": {"id": 812, "number": 1, "text": "De 0 a 10...", "answer_type": "NPS"}},
  "period": {"start": "2026-10-01", "end": "2026-10-31", "basis": "started_at_unit_local", "from_preset": "last_month"},
  "comparison": {"kind": "previous_year", "start": "2025-10-01", "end": "2025-10-31"},
  "filters": {"units": [{"id": 101, "name": "Loja Centro"}], "channel": "web"},
  "policies": {"reliability": "reliable_only", "completion": "all", "lgpd": "aggregates_only"},
  "freshness": {"watermark": "2026-11-17T09:40:00Z", "stale": false},
  "rows": [
    {"dims": {"unit": {"id": 101, "name": "Loja Centro"}},
     "value": 41, "n": 312, "display": "41",
     "breakdown": {"promoters": 190, "passives": 60, "detractors": 62,
                   "promoters_pct": 60.9, "passives_pct": 19.2, "detractors_pct": 19.9},
     "compared": {"value": 55, "n": 298, "display": "55"},
     "delta": {"value": -14, "display": "-14 pontos"},
     "warnings": []}
  ],
  "totals": {"value": 41, "n": 312, "display": "41"},
  "truncated": false,
  "available_rows": 1,
  "warnings": []
}
```

| Campo | Use para |
|---|---|
| `value`, `display` | O número. Fale o `display` |
| `n` | Sempre junto do número |
| `breakdown` | Explicar o número (ex.: queda veio de mais detratores: `detractors_pct`) |
| `compared`, `delta` | Comparação; não recalcule |
| `totals` | O número do conjunto; nunca a média das linhas |
| `period`, `comparison` | Dizer as datas efetivas |
| `policies` | Dizer o que foi incluído/excluído quando não for o padrão óbvio |
| `freshness` | Dizer até quando há dados |
| `truncated`, `available_rows` | Se cortado, "pior/melhor" só vale entre as linhas mostradas, salvo ordenação pela própria métrica |
| `warnings` | Ver códigos abaixo |

## Códigos de aviso

| Código | O que fazer |
|---|---|
| `small_sample` | Dar o valor com o n e a ressalva de amostra pequena |
| `no_data` | Dizer que não há dados no período/recorte; não culpar o período se a consulta não tem período |
| `multi_response_sum_exceeds_100` | Avisar que as porcentagens não somam 100% |
| `values_from_current_questionnaire` | Avisar que o questionário foi editado depois da coleta e que os números usam o cadastro atual |
| `partial_comment_coverage` | Dizer que o Radar analisou só parte dos comentários |
| `partial_bucket` | O último período está em andamento |
| `comparison_window_adjusted` | A API trocou `previous_year` por `previous_period` (período maior que um ano) |
| `stale_mirror` | Não responder com números; dizer até quando há dados e sugerir tentar mais tarde |

## Erros

| HTTP / código | Significado | O que fazer |
|---|---|---|
| `404 not_found` | Id inexistente ou fora do escopo da credencial | Dizer que não está disponível; não insistir com outros ids |
| `422 unsupported_combination` | Métrica × recorte não suportado | Oferecer o recorte suportado mais próximo |
| `422 metric_not_applicable` | Métrica incompatível com o tipo da pergunta | Rever o tipo em `get_questionnaire` |
| `403 scope_required` | Falta escopo (`analytics:comments`, `analytics:lgpd`, `analytics:reliability`) | Dizer qual permissão falta |
| `409 stale_mirror` | Espelho defasado | Ver `stale_mirror` acima |
| `429 rate_limited` | Limite de uso | Esperar `Retry-After`; agrupar consultas com `group_by` em vez de várias chamadas |
