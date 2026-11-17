# ADR-0001: métricas calculadas no servidor, nunca pela LLM

- Status: proposto
- Data: 2026-11-17

## Contexto

As fórmulas de resultado têm regras que não são óbvias (denominador de múltipla resposta, "Não se aplica" fora da média, `weighted_sum`, NPS agregado por contagens, valor da escala lido do cadastro atual, hora local agnóstica). A API REST pública atual devolve respostas brutas sem `question_id`/`choice_id`, em formatos que variam por tipo, com paginação por shard e falhas silenciosas.

## Decisão

Toda métrica é calculada pela API Analytics no `survey_system`, com as mesmas funções de contagem das telas (`Results::AnswerCounts::*`) ou com os templates do catálogo do Data Chat que as reproduzem. A skill proíbe a LLM de somar, fazer média, recalcular ou estimar métricas. Se a resposta exige um número que não veio de uma chamada, a LLM faz outra chamada.

Totais de grupos (rede, propriedade, "todas as unidades") são calculados pelo servidor a partir das contagens e devolvidos em `totals`, para que a LLM não precise agregar linhas.

## Alternativas consideradas

| Alternativa | Por que não |
|---|---|
| A LLM lê `/api/v1/surveys/:id/evaluations` e calcula | Formato sem ids, falhas silenciosas, sem LGPD, isolamento entre clientes quebrado, volume alto (até 10.000 itens por shard) |
| Biblioteca Python na skill calcula a partir de export bruto | Duplica as fórmulas fora do sistema e diverge na primeira mudança. Fica como recurso avançado (Fase 4), com aviso de que os números oficiais são os da API |
| Expor o GraphQL interno | Sem escopo de tenant nos resolvers de gráficos, contrato instável, serviços JSON com divergências (ex.: `evaluation_count` sem filtros, `incomplete_evaluation_count` fixo em 10) |
| Expor o Data Chat inteiro (`/ask`) | Uma LLM chamando outra LLM: custo duplo, resposta em texto narrado e não em dado estruturado, erro composto. Pode existir como ferramenta auxiliar, não como base |

## Consequências

- O backend precisa de endpoints novos (ver [backend-requirements.md](../backend-requirements.md)).
- Perguntas que o modelo não cobre são recusadas com motivo, em vez de respondidas com aproximação.
- O conjunto de métricas cresce por decisão de produto, com teste, e não pela criatividade da LLM.
