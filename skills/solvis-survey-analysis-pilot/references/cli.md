# Motor da skill: comandos

`python3 <pasta da skill>/scripts/solvis.py [--pretty] <comando> [opções]`

Saída sempre em JSON no stdout. Em erro, `{"error": {"code", "message", "hint"?, "details"?}}` e código de saída diferente de 0 (2 = pedido inválido ou fora do escopo, 3 = credencial/rede/API, 4 = download ainda em andamento).

Listas aceitam vírgula ou repetição: `--group-by unit,month` ou `--group-by unit --group-by month`.

## Comandos

| Comando | Para quê |
|---|---|
| `scope` | Resumo da credencial: pesquisas ativas nos últimos 90 dias (até 15), total de pesquisas, unidades, UFs, propriedades de unidade e capacidades desta versão |
| `config [--start-month AAAA-MM]` | Mostra ou define o primeiro mês que o usuário quer analisar. Sem ele, `query`, `comments` e `sync` recusam (`start_month_required`); nada antes dele é baixado. `scope` também mostra `start_month` |
| `surveys [--search T] [--active-in PRESET] [--include-archived] [--limit N]` | Lista ou busca pesquisas, mais recentes primeiro. `--active-in last_90_days` mostra só as que têm avaliação no período (pela data da última avaliação; arquivadas só com `--include-archived`) |
| `questionnaire --survey ID` | Perguntas (id, número, texto, tipo, `metric` recomendada, `metric_kind`, escala, LGPD, zona de referência, alternativas com id/letra/valor, e `flow` com regras de entrada, perguntas puladas por ramificação e ramificações que saem da pergunta; `shown_to: conditional` marca quem não aparece para todos). Campos opcionais só aparecem quando definidos: sem `metric_kind`, a escala é de média |
| `units [--search T] [--properties]` | Unidades com cidade, UF e propriedades; `--properties` lista nomes e valores de propriedade com ids |
| `resolve --kind K --text T [--survey ID] [--question ID]` | Texto → candidatos com id e tipo de casamento (`exact`, `prefix`, `word`, `contains`). K: `survey`, `question` (aceita "pergunta 3"), `choice` (aceita a letra), `unit`, `property`, `property_value`, `tag`. `exact_match` só é verdadeiro com um único casamento exato |
| `query ...` | Calcula uma métrica e devolve o envelope (abaixo) |
| `comments ...` | Comentários mascarados, mais recentes primeiro (abaixo) |
| `sync --survey ID --period P` | Baixa um período para o cache sem consultar. Útil para períodos longos; `query` e `comments` já baixam o que falta |
| `explain --query-id ID` | Reabre uma consulta feita antes (pedido e envelope) |
| `model` | Métricas, recortes e presets aceitos |
| `purge --yes` | Apaga cache, token e registro de consultas (confirme com o usuário) |

## `query`

```
query --metric nps --survey 56 --question 812 --period last_month \
      --compare-with previous_year --group-by unit --order value:asc --limit 10
```

| Opção | Valores |
|---|---|
| `--metric` | `evaluation_count`, `response_count`, `nps`, `scale_mean`, `weighted_sum`, `choice_share`, `choice_set_share`, `multi_response_share`, `tag_mentions`, `data_quality_summary` |
| `--question` | Obrigatório nas métricas de pergunta; opcional em `tag_mentions` (restringe às tags daquela pergunta) |
| `--period` | `today`, `yesterday`, `this_week`, `last_week`, `last_7_days`, `last_30_days`, `last_90_days` (padrão), `this_month`, `last_month`, `this_quarter`, `last_quarter`, `this_year`, `last_year`, `month:AAAA-MM`, `quarter:AAAA-Qn`, `year:AAAA` |
| `--start`, `--end` | Datas AAAA-MM-DD inclusivas, em vez de `--period`. Máximo 731 dias |
| `--compare-with` | `previous_period` (mês, trimestre ou ano de calendário anterior quando o período é um deles; senão a mesma duração imediatamente antes) ou `previous_year` (mesmas datas um ano antes). Com recorte de tempo, só `previous_year` |
| `--group-by` | Até 2: `unit`, `unit_property:<id do nome>`, `unit_state`, `day`, `week`, `month`, `quarter`, `day_of_week`, `hour_block[:1\|2\|3\|4\|6\|8\|12]`, `channel`, `completion`, `reliability`, `nps_group[:<id da pergunta NPS>]`, `choice:<id da pergunta>` |
| `--unit` | Ids de unidade |
| `--property-value` | Ids de valor de propriedade (OU dentro do mesmo nome, E entre nomes) |
| `--channel` | `device` (totem) ou `web` |
| `--completion` | `all` (padrão), `completed`, `incomplete` |
| `--reliability` | `all` (padrão), `reliable_only`, `unreliable_only`, `unclassified_only` |
| `--nps-group` | `promoter`, `passive`, `detractor`: avaliações cujo respondente está no grupo, numa pergunta NPS de referência (`--reference-question`, ou a única NPS da pesquisa) |
| `--choice-filter` | Ids de alternativas de outra pergunta: só avaliações que as marcaram |
| `--tag` | Ids de tag: só avaliações com a tag em qualquer pergunta. Tag-pai não inclui subtags |
| `--choices` | Conjunto de alternativas de `choice_set_share` (ex.: as duas melhores da escala) |
| `--order` | `value`, `n` ou `delta`, com `:asc` ou `:desc` (padrão desc). Para "pior unidade", `value:asc` |
| `--limit` | Linhas devolvidas (padrão 50, máximo 500). `truncated` e `available_rows` dizem se cortou |
| `--min-n` | Esconde linhas com n menor (o envelope diz quantas) |
| `--locale` | `pt` (padrão), `en`, `es`: formato de `display` |
| `--refresh` | Baixa de novo o período, ignorando o cache |
| `--budget` | Segundos máximos de download nesta execução (padrão 90) |

## Envelope

```json
{
  "query_id": "q_c20ad66b",
  "metric": {"id": "nps", "label": "NPS", "unit": "points"},
  "scope": {"survey": {"id": 56, "name": "Pesquisa Lojas"},
            "question": {"id": 812, "number": 1, "text": "De 0 a 10...", "answer_type": "NPS", "reference_zone": "default"}},
  "period": {"start": "2026-10-01", "end": "2026-10-31", "basis": "started_at_unit_local", "from_preset": "month:2026-10"},
  "comparison": {"kind": "previous_year", "start": "2025-10-01", "end": "2025-10-31", "rule": "same_dates_previous_year"},
  "group_by": ["unit"],
  "filters": {},
  "policies": {"reliability": {"applied": "all"}, "completion": "all", "lgpd": "aggregates_only", "free_text": "masked_pii"},
  "coverage": {"period": {"days_expected": 31, "days_complete": 31, "days_partial": 0, "days_missing": 0,
                          "days_without_evaluations": 11, "failed_windows": [], "fetched_oldest": "...", "fetched_newest": "..."}},
  "freshness": {"source": "api_v1", "fetched_oldest": "...", "fetched_newest": "...", "api_last_evaluation_date": "2026-10-20"},
  "rows": [
    {"dims": {"unit": {"id": 101, "name": "Loja Centro"}},
     "value": 20, "n": 10, "display": "20",
     "breakdown": {"promoters": 5, "passives": 2, "detractors": 3,
                   "promoters_pct": 50.0, "passives_pct": 20.0, "detractors_pct": 30.0},
     "reference_zone": {"key": "improvement", "label": "Zona de Aperfeiçoamento"},
     "compared": {"value": 100, "n": 5, "display": "100"},
     "delta": {"value": -80, "display": "-80 pontos", "detractors_pct": 30.0, "detractors_pct_display": "+30,0 p.p."},
     "warnings": ["small_sample"]}
  ],
  "totals": {"value": 15, "n": 20, "display": "15", "breakdown": {}, "compared": {}, "delta": {}},
  "truncated": false, "available_rows": 3,
  "warnings": [{"code": "small_sample", "message": "...", "threshold": 30}]
}
```

| Campo | Use para |
|---|---|
| `display` | O número a falar, já formatado |
| `n` | Sempre junto do número |
| `breakdown` | Explicar o número (promotores/detratores, escala, N/A, alternativas do conjunto). Percentuais têm `<campo>_display` pronto |
| `compared`, `delta` | Comparação. `delta` já vem calculado sobre os valores exibidos; não recalcule. Em NPS, `delta.<grupo>_pct_display` dá a variação em p.p. Em contagens, `delta.pct_change_display` dá a variação percentual |
| `only_in_comparison` | Linha que só tem dado no período comparado (ex.: unidade que parou de responder) |
| `totals` | O número do conjunto, calculado pelas contagens. Nunca a média das linhas |
| `rows[].bucket` | Em recortes de tempo: `start`, `end`, `in_progress`, `clipped_by_period` |
| `period`, `comparison` | Datas efetivas a citar |
| `policies.reliability` | `applied` e, em pesquisa com Data Quality, `survey_mix_in_period` (confiáveis, reprovadas, não verificadas da pesquisa inteira no período, sem os filtros da consulta) |
| `coverage` | Quantos dias foram baixados completos; janelas em que a API falhou |
| `freshness` | Quando os dados foram baixados (`fetched_newest_sao_paulo` para citar) e a última avaliação registrada na pesquisa |

Distribuições (`choice_share`, `multi_response_share`, `tag_mentions`) têm uma linha por alternativa ou tag (`dims.choice` ou `dims.tag`, mais `chosen` ou `mentions`). Em `choice_share` e `multi_response_share`, `totals` é uma lista com uma entrada por alternativa. Em `tag_mentions`, `totals` é um objeto com `tagged_comments`, `text_responses`, `tagged_share_display` (parte dos comentários que tem tag), `rows` e, com comparação, `compared`.

Em pergunta condicional (`shown_to: conditional`), o envelope traz também `exposure`: `totals` e, com `--group-by`, `rows`, cada um com `evaluations` (no recorte), `reached` (viram a pergunta, inferido das regras e das respostas), `answered`, `reached_of_evaluations_display`, `answered_of_reached_display` e `uncertain_evaluations` (avaliações cujo caminho depende de resposta de pergunta de texto repetido sem dono). `assumptions` lista as premissas da inferência. Não aparece em pergunta exibida a todos nem em `tag_mentions`.

## Avisos

| Código | O que fazer |
|---|---|
| `small_sample` | Métricas de nota e percentual com n < 30. Dar o valor com o n e a ressalva. Não eleger melhor/pior entre linhas com amostra pequena sem dizer. Contagens não recebem este aviso |
| `no_data` | Dizer que não há dados no período e recorte |
| `no_tags` | Há comentários, mas nenhum com tag: não há classificação de temas; use `comments` |
| `period_in_progress` | O período inclui hoje |
| `partial_bucket` | Há balde de tempo em andamento ou cortado pelo período; não comparar como se fosse cheio |
| `includes_future_days` | O período termina depois de hoje |
| `comparison_window_adjusted` | Período maior que um ano: `previous_year` virou `previous_period` |
| `multi_response_sum_exceeds_100` | As porcentagens não somam 100% |
| `overlapping_categories` | O recorte é uma pergunta de múltipla resposta; as linhas não somam o total |
| `values_from_current_questionnaire` | O questionário foi editado depois de travado; textos e valores atuais valem para todo o histórico |
| `conditional_question` | A pergunta tem regra de entrada ou pode ser pulada por ramificação; só parte das avaliações a viu. Diga a condição (`flow` no aviso) e que o n é de quem a viu. O envelope traz `exposure` |
| `answers_excluded` | Respostas apontam para alternativas que não existem mais; ficaram fora, como nas telas |
| `answers_assigned_by_order` | A pergunta tem texto repetido; as respostas foram separadas pela ordem. Pode citar o número; mencione a ressalva se o usuário for comparar perguntas gêmeas |
| `includes_unverified_evaluations` | Pesquisa com Data Quality, política `all` e avaliações reprovadas ou não verificadas no período: dizer quantas entram |
| `data_quality_not_enabled` | A pesquisa não tem Data Quality |
| `tags_as_of_last_sync` | Tags só mudam no cache quando o dia é baixado de novo. Dizer isso e, se importar, sugerir `sync --refresh` do período |
| `tag_semantics` | Tags vêm de pessoas ou do Radar; base = comentários com tag; soma passa de 100% |
| `partial_tag_coverage` | Só parte dos comentários tem tag; dizer a proporção |
| `incomplete_coverage` | A API falhou em parte do período; os números excluem as janelas em `failed_windows`. Dizer isso |
| `possible_silent_failure` | A API devolveu zero avaliações, mas a pesquisa registra avaliações no período. Não dizer que não houve avaliações; sugerir conferir na tela de resultados |
| `suspicious_empty_days` | Dias sem avaliações no meio de dias movimentados; mencionar as datas (pode ser pausa real ou falha da API) |
| `archived_survey` | A pesquisa está arquivada |
| `rows_hidden_by_min_n` | Linhas ocultas por `--min-n` |

## Erros

| Código | O que fazer |
|---|---|
| `missing_credentials`, `auth_failed` | Explicar ao usuário como configurar a credencial (SKILL.md). Não pedir a senha no chat |
| `api_unreachable`, `api_error` | Dizer que a API Solvis não respondeu e sugerir tentar mais tarde |
| `not_found` | Pesquisa, pergunta, unidade ou valor fora do escopo da credencial. Dizer que não está disponível; não tentar outros ids |
| `start_month_required` | Perguntar ao usuário o primeiro mês que interessa e rodar `config --start-month AAAA-MM` |
| `period_before_start` | O período (ou a comparação) começa antes do mês inicial. Usar datas a partir de `details.earliest_day`, ou perguntar se o usuário quer antecipar o mês inicial |
| `sync_incomplete` | O download não terminou no tempo desta execução. Rodar o mesmo comando de novo |
| `metric_not_available` | A métrica não existe; o `message` diz a alternativa |
| `metric_not_applicable` | Métrica incompatível com o tipo da pergunta; rever em `questionnaire` |
| `ambiguous_question_text` | Perguntas com mesmo tipo e texto que o motor não conseguiu separar; dizer isso com os números do `message` (`details`: desta pergunta, das gêmeas, sem dono) |
| `unsupported_combination` | Recorte não suportado; o `hint` diz a alternativa |
| `reference_question_required` | Há mais de uma pergunta NPS; perguntar qual ou usar `details` |
| `question_required` | Faltou `--question`; `details.applicable_questions` lista as perguntas em que a métrica vale |
| `invalid_argument`, `invalid_period`, `period_too_long`, `choices_required` | Corrigir o comando |

## `comments`

```
comments --survey 56 --period last_month [--question 816] [--unit 101] \
         [--nps-group detractor] [--reference-question 812] [--tag 12] [--contains fila] [--limit 20]
```

Devolve `total_matching` (quantos comentários atendem ao filtro), `comments[]` com `eval_ref`, `started_at_local`, `unit`, `question`, `source` (`comment` ou `additional_field`), `author_nps_group` (grupo NPS de quem escreveu, quando há pergunta NPS de referência), `tags` e `text` (até 400 caracteres, mascarado), mais `data_notice`, `notes`, `coverage` e `freshness`. Ordem: mais recentes primeiro. `--limit` até 100. `--no-additional` exclui textos de "Outro: ___".

`total_matching` é uma contagem válida ("23 comentários citam fila"). Os comentários devolvidos são uma amostra dos mais recentes; não conte temas lendo a amostra, use `query --metric tag_mentions`.
