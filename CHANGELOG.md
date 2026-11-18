# Changelog

## Não lançado

- Mês inicial da análise: o motor recusa `query`, `comments` e `sync` até o usuário escolher o primeiro mês que interessa (`config --start-month AAAA-MM`, mostrado também em `scope`) e recusa períodos e comparações que comecem antes dele (`start_month_required`, `period_before_start`). Nada anterior ao mês inicial é baixado.
- Aviso `tags_as_of_last_sync` em `tag_mentions`, em `--tag` e nos comentários: tags só mudam no cache quando o dia é baixado de novo. A skill passa a sugerir a rotina de ressincronização (dia anterior todo dia, semana anterior na segunda, mês anterior no dia 1).
- Atualização incremental: hoje e os dias até 3 dias atrás deixam de ser baixados por inteiro; o motor pede só o que o servidor recebeu depois do último download (`search_date_scope=received_at`, literal fixo) e acrescenta ao cache. Limite assumido: avaliação atrasada que cai num shard antigo não é vista por essa busca (ver `docs/pilot/data-engineering.md`).

## 0.2.0-pilot (2026-11-17)

- Nova skill `solvis-survey-analysis-pilot`, utilizável hoje sobre a API pública V1, sem mudança no backend.
- Motor local `scripts/solvis.py` (Python 3.9+, só biblioteca padrão): extração incremental com tratamento das falhas da API (página por shard, lista vazia silenciosa, HTTP 400), normalização de respostas por texto para ids (com atribuição pela ordem em perguntas de texto repetido), cache SQLite por credencial, privacidade na ingestão e cálculo com as fórmulas das telas.
- Métricas: `evaluation_count`, `response_count`, `nps`, `scale_mean`, `weighted_sum`, `choice_share`, `choice_set_share`, `multi_response_share`, `tag_mentions`, `data_quality_summary`. Recortes por unidade, propriedade, UF, tempo, dia da semana, faixa de horário, canal, completude, confiabilidade, grupo NPS e alternativa de referência.
- Envelope com a mesma forma do contrato da API Analytics v1, mais `coverage`.
- Testes (`tests/pilot/`, 47 casos com API falsa), casos de avaliação (`evals/cases-pilot.yaml`), plano do piloto, documentação da camada de dados, guia de instalação e ADR-0010.
- Validado contra a produção com credencial de teste (só leitura) e por um agente de contexto limpo seguindo só o `SKILL.md`.

## 0.1.0-draft (2026-11-17)

- Planejamento inicial: plano por fases, arquitetura, ADRs 0001-0009, requisitos para o backend, distribuição e perguntas em aberto.
- Rascunho da skill `solvis-survey-analysis` (`SKILL.md` e referências).
- Modelo semântico 1.0.0-draft: métricas, dimensões, entidades e regras invariantes extraídas do `survey_system@f594c4a6`.
- Contrato proposto da API Analytics v1 (`api/openapi.analytics.v1.yaml`).
- Casos iniciais de avaliação (`evals/cases.yaml`).
