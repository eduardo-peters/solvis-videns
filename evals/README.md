# Avaliação da skill

Casos que medem se uma LLM, com a skill e as ferramentas, responde certo. Rodam contra o cliente de fixture em staging (dados sintéticos com casos de borda conhecidos), nunca contra dados de cliente.

## Formato

`cases.yaml` tem uma lista de casos:

| Campo | Significado |
|---|---|
| `id` | Identificador estável |
| `category` | `metric_selection`, `pooling`, `comparability`, `time`, `identity`, `scope`, `refusal`, `adversarial`, `text`, `reliability`, `format` |
| `phase` | Fase do plano em que o caso passa a valer |
| `question` | Pergunta do usuário |
| `fixture` | Estado da fixture que o caso pressupõe |
| `expected_calls` | Chamadas que precisam aparecer (subconjunto dos argumentos; ordem não importa salvo `ordered: true`) |
| `must` / `must_not` | Afirmações sobre a resposta final, verificadas por regra (números, `query_id`) ou por avaliador LLM com rubrica |
| `invariants` | Regras de `references/invariants.md` que o caso exercita |

## Como medir

1. Para cada caso e cada modelo avaliado, rodar 3 vezes.
2. Números: extrair da resposta e comparar com os envelopes da mesma execução. Qualquer número sem envelope correspondente é falha (INV-01).
3. Chamadas: comparar com `expected_calls`.
4. `must`/`must_not` textuais: avaliador LLM de fornecedor diferente do avaliado, com a rubrica do caso.
5. Relatório por categoria contra as metas de `docs/PLAN.md`.

## Origem dos casos

- Armadilhas do domínio encontradas no código (ver `docs/architecture.md`).
- Padrões de roteamento do golden set do Data Chat (`app/domain/services/data_chat/golden_set.rb`: 60 casos de roteamento, 8 de período, 6 de continuação), adaptados para chamadas por id.
- Erros reportados no piloto: todo erro vira caso.
