# Requisitos para o survey_system

O que o backend precisa ter para a skill funcionar, com o código existente a reaproveitar. Caminhos relativos à raiz do `survey_system` (commit `f594c4a6`). Contrato HTTP: [api/openapi.analytics.v1.yaml](../api/openapi.analytics.v1.yaml).

## P0. Pré-requisitos (bloqueiam o piloto)

| # | Item | Notas |
|---|---|---|
| P0-1 | Corrigir os achados do relatório interno de segurança da API pública | Relatório restrito, fora deste repositório. Inclui isolamento entre clientes em endpoints existentes |
| P0-2 | Testes de isolamento entre clientes para todo endpoint `Api::*` e resolvers GraphQL | Spec com dois clientes: o segundo recebe 404/vazio para ids do primeiro |
| P0-3 | Limite de taxa na API (hoje inexistente) | `Rack::Attack` por `api_credential_id`, ou contador em Valkey como `Services::DataChat::RateLimit` |
| P0-4 | Escopos no Doorkeeper (`analytics:read`, `analytics:comments`, `analytics:lgpd`, `analytics:reliability`) | `config/initializers/doorkeeper.rb` (`default_scopes`/`optional_scopes`); `doorkeeper_authorize! 'analytics:read'` nos controllers novos |

## Componentes novos

| Componente | Responsabilidade | Reaproveita |
|---|---|---|
| `Api::Analytics::V1::*Controller` | Endpoints do contrato; JSON; erros no formato `Error` | `Api::ApplicationController` (Doorkeeper), `Api::UsageLogging` |
| `Analytics::CredentialScope` | Mesma interface de `Services::DataChat::Session` (`client_id`, `survey_ids`, `surveyed_unit_ids`, `reliable_only_survey_ids`, `lgpd?`, `reliability_permission?`) a partir de `ApiCredential` + escopos + restrições | `app/domain/services/data_chat/session.rb` |
| Restrições na `ApiCredential` | Colunas `allowed_scopes`, `survey_ids` (JSON, nulo = todas), `surveyed_unit_ids` ou `property_value_ids` (nulo = todas) e tela de edição | `app/models/api_credential.rb`, `ApiCredentialsController` |
| `Analytics::Model` | Registro de métricas, dimensões, entidades e matriz de compatibilidade; serializa `GET /model`; fonte para o snapshot da skill | Conteúdo de `skills/solvis-survey-analysis/references/*.yaml` deste repositório |
| `Analytics::QueryPlanner` | Valida `MetricQuery` contra o modelo (métrica × tipo de pergunta × `group_by` × fase), resolve período e comparação, escolhe a entrada de catálogo | `Services::DataChat::Period`, `Period::Reader`, `Catalog::Comparison` |
| Catálogo de métricas | Templates SQL por métrica com parâmetros por id, `group_by` explícito, totais agregados, `min_n` | `app/domain/services/data_chat/catalog/{evaluation_volume,evaluations_by_unit,survey_nps,question_scores,choice_distribution,comment_themes,data_quality_summary}.rb` e módulos `question_measure`, `nps_measures`, `choice_measures`, `theme_measures`, `measure_cuts`, `monthly_series`, `scope_predicates` |
| Execução segura | Bindings tipados, conferência de escopo, union de shards, cache | `QueryCompiler`, `ScopeGuard`, `Warehouse`, `CachedWarehouse`, `ReaderClient`, `ReaderDdl` |
| `Analytics::Envelope` | Monta o envelope: `display` por locale e regra de casas, `breakdown`, `compared`/`delta`, `totals`, avisos | Regras de exibição em `app/helpers/surveys/results_helper.rb:133-153`, `app/models/question.rb:323-335` |
| `Analytics::Resolver` | Candidatos com tipo de casamento em vez de união silenciosa | `Services::DataChat::Resolver` (normalização sem acento, número de pergunta, filtro LGPD) |
| `Analytics::QueryAudit` | Tabela `analytics_queries`: credencial, cliente, endpoint, pedido JSON, SQL, linhas, envelope (ou hash), tempos; retenção igual à do Data Chat (180 dias) | `DataChatMessage`/`DataChatMessageQuery`, `DataCleaner#clear_data_chat_messages` |
| Freshness | Watermark e `stale_mirror` | `Services::DataChat::Freshness` |
| Usuário ClickHouse `analytics_api_reader` | Mesmo perfil readonly do `data_chat_reader`, com cota própria | `ReaderDdl` (parametrizar nome e cotas) |
| Mascaramento de PII em comentários | E-mail, telefone, CPF, CNPJ → marcadores | Validadores existentes de e-mail, CPF, CNPJ, telefone em `app/models/answer.rb` / `app/validators/` como referência de padrão |

## Endpoints

| Endpoint | Fonte dos dados | Lacunas a resolver |
|---|---|---|
| `GET /scope` | `CredentialScope`, `Freshness`, configuração de limites | — |
| `GET /model` | `Analytics::Model` | Definir onde o registro mora (`config/analytics/*.yml` ou classes Ruby) |
| `GET /surveys` | `Survey` no escopo | `comment_radar_enabled` = `Survey#comment_radar_prompt_configured?` e flag do ambiente; `questionnaire_edited_after_collection` = `questionnaire.version > 1` |
| `GET /surveys/{id}/questionnaire` | `Questionnaire`, `Question`, `Choice` | Texto sem `<br>`/HTML; `value` como número (hoje decimal sai como string); `is_valueless`; `branching_summary` via `Services::Exports::BranchingConditionalText`; `scale_min/max` via `Question#value_range` |
| `GET /units` | `SurveyedUnit` no escopo + propriedades | Incluir `timezone` e `disabled`; `survey_id` filtra por `surveyed_units_sent_to` |
| `GET /tags` | `Tag` do cliente | `display_name`, `parent_tag_id` (`tag_id`), `description` |
| `POST /resolve` | `Analytics::Resolver` | Devolver candidatos e `match`, nunca unir |
| `POST /query` | Planner + catálogo + execução + envelope + auditoria | Ver tabela de métricas abaixo |
| `GET /queries/{id}` | `analytics_queries` | Só da mesma credencial |
| `POST /comments/search` (fase 3) | SQL de `Catalog::RecentComments` + `comment_radar_analysis` + `CommentAuthors` | Mascaramento; `readable_comment_question_ids` (LGPD); só Text/Short Text; cursor; `evaluation_ref` = `unique_id` como string |

## Métricas: origem e paridade

Cada métrica precisa de teste de paridade: num cliente de fixture, o valor da API é igual ao das telas (`Results::AnswerCounts::*`) para o mesmo filtro.

| Métrica | Entrada de catálogo existente | Paridade com | Trabalho |
|---|---|---|---|
| `evaluation_count` | `EvaluationVolume`, `EvaluationsByUnit` | `Results::EvaluationCounts::ConsolidatedCount` | `group_by` channel/completion |
| `response_count` | parte de `QuestionMeasure` (`answer_count`) | `CountBase#for_question` | Expor como métrica própria; regra de MR (avaliações distintas) |
| `nps` | `SurveyNps` + `NpsMeasures` | `CountBase#nps` | `group_by` por propriedade (pooled); `null` quando n = 0 |
| `scale_mean` | `QuestionScores` | `CountBase` média | Por id de pergunta; casas por amplitude |
| `weighted_sum` | — (o chat exclui) | `CountBase#weighted_sum` (`count_base.rb:153-167`) | Template novo |
| `choice_share` / `multi_response_share` | `ChoiceDistribution` + `ChoiceMeasures` | `CountBase#for_choice`, `ConsolidatedCount` MR | Rótulos por id; `is_valueless` |
| `choice_set_share` (fase 3) | — | soma de `for_choice` do conjunto ÷ `for_question` | Template novo |
| `theme_mentions` (fase 3) | `CommentThemes` + `ThemeMeasures` | — (só existe no chat) | Filtro por `author_nps_group` |
| `data_quality_summary` (fase 3) | `DataQualitySummary` | — | Exige `analytics:reliability` |

Dimensões de fase 3 que não existem no catálogo e existem nas telas: dia da semana, faixa de horário, turno, resposta a pergunta de referência (`app/models/results/answer_counts/crossed_by_{day_of_week,hour,shift,choice,customer_type}.rb`). Precisam de template ClickHouse equivalente e teste de paridade.

## Avisos: de onde vêm

| Aviso | Regra no servidor |
|---|---|
| `small_sample` | `n < limiar` (padrão 30, configurável) |
| `no_data` | `n = 0` em todas as linhas |
| `multi_response_sum_exceeds_100` | métrica `multi_response_share` |
| `values_from_current_questionnaire` | `questionnaire.version > 1` |
| `partial_comment_coverage` | `analysed_comments < period_comments` |
| `partial_bucket` | balde temporal contém hoje |
| `comparison_window_adjusted` | `previous_year` com período > 1 ano (`Catalog::Comparison`) |
| `stale_mirror` | `Freshness#stale?` |

## Fase 4 (opcional): export normalizado

Para clientes cujas LLMs executam código (análises que o modelo semântico não cobre):

- `POST /exports` assíncrono, formato longo (uma linha por resposta): `evaluation_ref`, `started_at_local`, `unit_id`, `channel`, `completed`, `reliable`, `shift_id`, `question_id`, `choice_id`, `score`, `value` (numérico da alternativa), `text` (mascarado, só com `analytics:comments`).
- Limites do `ResultsExport` atual (31 dias, 2 milhões de avaliações); LGPD aplicada; sem IP/fingerprint/identifier.
- Acompanha dicionário de dados gerado do modelo semântico e o aviso de que os números oficiais são os de `/query`.

## Testes exigidos

1. Isolamento: cada endpoint com dois clientes e com credencial restrita a subconjunto de pesquisas/unidades.
2. Paridade: cada métrica × recorte da fase contra `Results::AnswerCounts::*` em fixture com casos de borda (N/A, MR em branco, `weighted_sum`, incompletas, não confiáveis, duas perguntas NPS, unidade que mudou de propriedade, shards diferentes no mesmo período).
3. Contrato: rswag gera o OpenAPI a partir dos specs; o CI da skill compara com `api/openapi.analytics.v1.yaml`.
4. Carga: maior cliente, 12 meses, `group_by` unidade × mês, dentro das cotas do `analytics_api_reader`.
5. Segurança: `ScopeGuard` com ids forjados, `group_by` e `filters` inválidos, injeção em campos de texto do `/resolve`.
