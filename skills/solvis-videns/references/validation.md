# Validação do que a skill produz (`validate`)

O comando `validate` confere cada afirmação do texto final contra o cache, com recálculo em SQL próprio (independente do `query`). Protocolo completo: [validation-protocol.md](validation-protocol.md).

## Quando rodar

- **Sempre** antes de entregar relatório ou deck.
- **Em resposta de chat**, só quando ela tiver comparação (`--compare-with`), ranking (`--order`, "top N", "N abaixo de X") ou tendência (série por tempo, "subiu/caiu todo mês").
- Resposta de chat só com um número, uma distribuição ou comentários não precisa.

## Como rodar

1. Escreva o texto final como rascunho (sem entregar).
2. Liste **cada afirmação verificável** num JSON (uma frase com vários números vira várias linhas) e rode `validate --claims arquivo.json` (ou `--claims -` com o JSON na entrada padrão).
3. Leia o resultado. Se `decision_required` for `true`, **apresente o parecer (`parecer_md`) e as `options` ao usuário e espere ele escolher**: corrigir, entregar com as ressalvas ou descartar. Não entregue nem corrija sozinho.
4. Se ele escolher corrigir, ajuste o texto e rode `validate` de novo.

Cada afirmação precisa do `query_id` do envelope (ou do `comments`) que a sustenta, exceto o tipo L. Sem `query_id` ela vira correção ("número sem fonte"). Tipo desconhecido ou forma que o verificador não entende sai como `nao_verificado`: diga isso ao usuário, não o trate como conferido.

## Formato

```json
{"material": {"kind": "report", "title": "...", "locale": "pt"},
 "claims": [
  {"id": "c1", "section": "2", "text": "O NPS de outubro foi 32", "type": "N",
   "query_id": "q_ab12cd34", "select": {}, "field": "value", "shown": "32"}
 ]}
```

`select` escolhe a linha: `{}` (totais), `{"unit": 101}` (id ou nome exato), `{"month": "2026-10"}` (também `week`, `day`, `quarter`), `{"channel": "web"}`, `{"choice": 55}` (em `choice_share`). `shown` é o texto como aparece no material, na localidade de `material.locale`.

| Tipo | Campos além de `id`, `section`, `text`, `type`, `query_id` |
|---|---|
| **N** número | `select`, `field` (`value` padrão, `n`, `promoters_pct`, `passives_pct`, `detractors_pct`, `chosen`), `shown` |
| **B** base | `select`, `label` (`respondentes`, `elegiveis`, `avaliacoes`), `shown` (o n citado) |
| **Q** qualificador | `qualifier`: `quase_totalidade`, `maioria`, `metade` (com `select`); `ordinal` (`select: {"unit"}`, `position`, `order`, `min_n`, `places`); `sem_abaixo` (`threshold`, `bucket`); `faixa` (`min`, `max`, `places`); `estavel`; `todo_mes` (`direction`, `group` opcional) |
| **E** entidades | `kind: count` (`shown`, `presented_as`: `active`/`registry`, `group` opcional) ou `kind: list` (`listed`, `expected_count`, `group`). `group` = `{"unit_ids": [...]}`, `{"state": "SP"}` ou `{"property_value_ids": [...]}` |
| **T** tendência | `bucket` (`month` padrão), `direction`, `group` opcional. A consulta deve ser de `nps` ou `choice_set_share` |
| **C** comparação | `select`, `framing`: `fact` (padrão) ou `signal`; `selected_among_many` (padrão: verdadeiro se há `select`); `shown_delta` opcional. A consulta deve ter `--compare-with` |
| **R** ranking | `kind`: `top` (`k`, `order`, `listed`, `ordered`) ou `below` (`threshold`, `listed`, `shown_count`); `min_n`, `places`, `base` (`all` ou `detractors`). `listed` aceita ids, nomes ou `{"unit": id, "shown": "—"}` |
| **G** grupo | `group` (como em E) ou `select: {"unit"}` |
| **D** taxa | `per` (`day` ou `business_day`), `shown`, `extraction_time` (`AAAA-MM-DDTHH:MM`, hora local; fraciona o dia em andamento) |
| **U** unidade citada | `unit`, `kind`: `interrupted` ou `criterion` (`criterion: {"op": "<", "value": 50}`) |
| **K** contagem de palavras | `terms` (lista), `match` (`whole` palavra inteira, ou `stem` radical), `combine` (`union` ou `sum`), `count_mode` (`comments` ou `occurrences`), `shown_total`, `shown_detractors` + `reference_question` (pergunta NPS), `question_id` opcional. A consulta pode ser um `comments` |
| **A** tag | `tag_id`, `field` (`count` ou `pct`), `shown`, `group` (`all` ou `detractors` + `reference_question`), `text` (a frase, para checar atribuição indevida) |
| **V** citação | `quote` (≥ 4 palavras), `unit`, `date` (`AAAA-MM-DD` ou `AAAA-MM`). Aceita pequena correção de digitação |
| **P** padrão | `pattern` (expressão regular **sem acentos**, minúscula), `threshold` (padrão 10), `cases: [{"unit", "date"}]` |
| **L** causal | `text` (a frase). Não precisa de `query_id` |
| **O** título × slide | `kind`: `trend_up`, `trend_down` (`bucket`, `every_step`), `highest`, `lowest` (`select: {"unit"}`), `above`, `below` (`select`, `other_select`). Título livre sai `nao_verificado` |
| **X** exemplos | `items` (unidades), `criterion: {"op", "value"}` |

## O que sai

`verdict`: `can_send`, `can_send_with_caveats` ou `do_not_send_as_is`. Há ainda `how_checked` (consultas, cobertura, Data Quality, se o cache mudou depois da consulta), `corrections`, `adjustments`, `confirmed`, `not_checked`, `annex` (uma linha por afirmação) e `parecer_md` pronto para mostrar.

Por afirmação: `verdict` (`confere`, `ajuste`, `correcao`, `nao_verificado`) e `verification`:
- `independent`: recalculado em SQL próprio.
- `envelope_only`: a consulta tem recorte que o recálculo não refaz (propriedade de unidade, grupo NPS, tag...); só se conferiu o texto contra o envelope. Diga isso.

Regras de gravidade (do protocolo): correção obrigatória para número sem base plausível com desvio > 10%, qualificador ou ordinal falso, lista ou contagem errada, tendência que é efeito de composição, ranking não exaustivo ou com base diferente da declarada, taxa com desvio > 10%, cadastro apresentado como unidades ativas. Ajuste para base mal descrita com número certo, desvio ≤ 10%, variação selecionada com |z| < 3,29 apresentada como fato, grupo pequeno em destaque, unidade do plano fora do critério, unidade sem avaliações no último período.

Regras de texto (protocolo): em K o número é reproduzido por variantes (só comentário × somando campos adicionais, com e sem acento, radical × palavra inteira, união × soma). O parecer devolve `strict` (só comentário, a regra do rótulo, sem acento) e `reproduced_by`. É correção se a reprodução exige misturar campos cujos autores não são classificáveis no grupo, usar regra diferente do rótulo, ou somar onde o rótulo indica união. Em A, a base são os comentários com ao menos uma tag, e a cobertura por mês vem em `coverage_by_month`; a frase que fala de turno, refeição ou causa sem a tag medir isso é "atribuição indevida" (verificação por palavras-chave). Em P, um caso é `confirmado` (≥ limiar), `parcial` (≥ metade) ou `nao_sustentado`, e os casos que atendem e não foram citados vêm em `uncited_qualifying_cases`. L marca transformar, causar, provocar, levar a, resultar em e fazer com que.

Texto de perguntas protegidas por LGPD só entra nas buscas (K, A, V, P) se o usuário autorizou (decisão do primeiro uso; `setup --lgpd-text on`). O parecer diz isso em `how_checked.lgpd_text`; sem autorização, uma citação dessas perguntas aparece como "não localizada". Se o usuário ainda não decidiu (`lgpd_text_decided` falso), pergunte antes de concluir que a citação não existe.

Se `cache_changed_since_query` for verdadeiro, o cache foi baixado de novo depois da consulta: refaça a consulta antes de decidir.
