# Playbooks de análise

Receitas para os pedidos mais comuns. Cada passo é uma chamada de ferramenta; o texto final segue `answer-format.md`. Os padrões vêm do roteamento do Data Chat da Solvis, validado contra um conjunto de perguntas reais.

Antes de qualquer playbook: `get_scope` (uma vez por conversa), resolver nomes com `resolve_entities` e ler `get_questionnaire` da pesquisa.

## 1. Panorama / fechamento de um período

Pedido: "como foi outubro?", "resumo do trimestre", "me dá os indicadores".

1. `query_metric(evaluation_count, period)`
2. `query_metric(nps, question_id=<cada pergunta NPS>, period)`
3. `query_metric(scale_mean, question_id=<perguntas de escala principais>, period)`; se forem muitas, pergunte quais importam ou use as 3 primeiras e diga isso
4. Fase 3: `query_metric(theme_mentions, period)` e `search_comments(period, limit=20)`

Resposta: uma frase por bloco (volume, NPS, notas, o que disseram). Sem conclusões que os números não sustentem.

## 2. Por que o NPS caiu (ou subiu)

Pedido: "NPS caiu, por quê?", "o que explica a queda?".

1. `query_metric(nps, compare_with=previous_period | previous_year)` — confirma a variação
2. `query_metric(nps, compare_with=..., group_by=[unit], order={by: delta, direction: asc})` — onde caiu
3. `query_metric(theme_mentions, filters={comment_tone: [negative]}, compare_with=...)` — assuntos das reclamações (fase 3)
4. `search_comments(reference_question_id=<NPS>, filters={author_nps_group: [detractor]}, limit=20)` — trechos (fase 3)

Resposta, nesta ordem, em até 8 frases:
1. Confirme a variação com os dois NPS, os n e as datas.
2. Diga onde se concentra (a primeira linha do passo 2 é a maior queda) e se veio de menos promotores ou de mais detratores, pelas porcentagens (`promoters_pct`, `detractors_pct`), nunca pelas contagens.
3. Os 2 ou 3 temas mais citados nas reclamações, com número e porcentagem, e um trecho curto.
4. O que vale investigar primeiro.

Apresente temas como o que os respondentes disseram, não como causa provada. Se a fase 3 não estiver disponível, pare no passo 2 e diga que a análise de comentários não está habilitada.

## 3. Ranking de unidades

Pedido: "pior loja em NPS", "top 10 unidades em satisfação".

1. `query_metric(<métrica>, group_by=[unit], order={by: value, direction: asc|desc}, limit=10)`
2. Se houver linhas com `small_sample`, rode de novo com `min_n` (sugira 30) ou diga explicitamente quais posições têm amostra pequena.

Resposta: a primeira linha é a resposta; as demais são contexto. Cite n de cada uma mencionada. Para volume de avaliações por unidade use `evaluation_count` com `group_by=[unit]`, não a métrica de nota.

## 4. Evolução mês a mês

Pedido: "evolução do NPS no ano", "mês a mês".

1. `query_metric(<métrica>, group_by=[month], period={preset: this_year | last_year} ou datas)`

Resposta: valor do primeiro e do último mês e onde fica a maior variação entre dois meses seguidos (use `delta` se vier; se não vier, peça `compare_with` em vez de subtrair). Se o último mês tiver `partial_bucket`, diga que está em andamento. "Tendência" é descrição da série; não projete.

## 5. Comparação entre períodos

Pedido: "comparado com o ano passado", "melhorou em relação ao mês anterior?".

1. Uma única chamada com `compare_with`. Nunca duas chamadas com datas calculadas.

Resposta: valor de cada período, n de cada um e a variação do envelope (`delta.display`).

## 6. Comparar regionais, bandeiras ou outro atributo de unidade

1. `list_units` ou `resolve_entities(kind=property_name)` para achar o `property_name_id`
2. `query_metric(<métrica>, group_by=["unit_property:<id>"])`

Resposta: os números de cada valor vêm do agregado das lojas que hoje têm aquele valor. Se o usuário perguntar de um período antigo, avise que lojas que mudaram de regional aparecem na regional atual.

## 7. Distribuição de uma pergunta de escolha

1. `get_questionnaire` para confirmar o tipo
2. `query_metric(choice_share | multi_response_share, question_id)`

Resposta: porcentagens com vírgula decimal, n (`answered`). Em múltipla resposta, diga que somam mais de 100%.

## 8. "Qual é o nosso CSAT?" (ou top-2-box, % satisfeitos)

1. Localize a pergunta que o cliente chama de CSAT (pergunte se houver mais de uma escala).
2. Se `metric_kind = weighted_sum`, use `weighted_sum`. Se não, ofereça `scale_mean` e, na fase 3, `choice_set_share` com as alternativas que o usuário considerar "satisfeito".
3. Declare: "O sistema não tem uma métrica chamada CSAT; usei <métrica> da pergunta <n>, <texto>".

## 9. O que os clientes estão dizendo (fase 3)

1. `query_metric(theme_mentions, period)` — panorama de temas
2. `search_comments(period, filters={comment_tone: [negative]}, limit=20)` e/ou `[positive]`

Resposta: temas com contagem e %, cobertura do Radar, 1 a 3 trechos curtos. Não conte comentários lidos como se fosse estatística; a contagem vem de `theme_mentions`.

## 10. Confiabilidade dos dados

Pedido: "quantas avaliações foram reprovadas?", "tem fraude?".

1. `get_scope` — confirme o escopo `analytics:reliability`; sem ele, diga que a credencial não tem acesso
2. `query_metric(data_quality_summary, period, detail=true)` (fase 3)

Resposta: confiáveis, reprovadas, não processadas; regras que mais falharam. "Reprovada" significa que regras automáticas apontaram padrão suspeito, não que houve fraude comprovada.
