# Plano: skill de análise de resultados de pesquisas

Data: 2026-11-17 · Status: proposto, aguardando decisões em [open-questions.md](open-questions.md)

## Objetivo

Clientes da Solvis fazem perguntas sobre os próprios resultados de pesquisa na LLM que já usam e recebem respostas com números idênticos aos das telas de resultados, com amostra, período e fonte declarados, sem cruzamentos errados e sem métricas inventadas.

## Critérios de sucesso (medidos pelo conjunto de avaliação em `evals/`)

| Critério | Meta |
|---|---|
| Exatidão numérica: valor citado = valor da API = valor da tela | 100% dos casos numéricos |
| Seleção de métrica e recorte corretos | ≥ 95% |
| Recusa correta do que não existe (CSAT como métrica, taxa de resposta, benchmark) | 100% |
| Cobertura de citação (todo número com `query_id`, n e período) | 100% |
| Casos adversariais (injeção em comentário, id de outro cliente, média de médias) | 100% sem vazamento ou erro |
| Vazamento entre clientes nos testes de isolamento | 0 |

## Visão geral das fases

| Fase | Entrega | Depende de | Tamanho relativo |
|---|---|---|---|
| 0 | Segurança da API atual, decisões, escopos OAuth, limite de taxa | — | M |
| 1 | API Analytics v1 mínima: metadados, `resolve`, `query` para 7 métricas, envelope, auditoria | 0 | L |
| 2 | Skill v0.1 + servidor MCP local + avaliação + piloto com 2-3 clientes | 1 | M |
| 3 | Comentários e temas, dimensões de tempo/turno/referência, `choice_set_share`, qualidade de dados | 2 | L |
| 4 | MCP remoto com OAuth (authorization code + PKCE), OpenAPI público, export normalizado, release contínuo | 3 | L |

## Fase 0: pré-requisitos

Entregas:
1. Correção dos achados do relatório interno de segurança e testes de isolamento entre clientes (P0-1, P0-2 em [backend-requirements.md](backend-requirements.md)).
2. Limite de taxa na API (P0-3).
3. Escopos `analytics:*` no Doorkeeper (P0-4).
4. Respostas para Q1 a Q6 de [open-questions.md](open-questions.md).
5. Cliente de fixture em staging com dados sintéticos cobrindo os casos de borda (ver "Testes exigidos" em backend-requirements).

Aceite: specs de isolamento verdes para todos os endpoints `Api::*` e GraphQL; varredura dos logs de uso da API sem leitura entre clientes, ou incidente aberto se houver.

## Fase 1: API Analytics v1 mínima (survey_system)

Escopo:
- `GET /scope`, `/model`, `/surveys`, `/surveys/{id}/questionnaire`, `/units`, `/tags`; `POST /resolve`; `POST /query`; `GET /queries/{id}`.
- Métricas: `evaluation_count`, `response_count`, `nps`, `scale_mean`, `weighted_sum`, `choice_share`, `multi_response_share`.
- Recortes: `unit`, `unit_property`, `day`/`week`/`month`/`quarter`, `channel`, `completion`; `compare_with`.
- Envelope completo, avisos, auditoria `analytics_queries`, usuário ClickHouse `analytics_api_reader`.
- `Analytics::Model` publicando o mesmo conteúdo dos YAML deste repositório.

Tarefas principais:
1. `Analytics::CredentialScope` + restrições na `ApiCredential` + tela.
2. Extrair do `DataChat::Catalog` o que é comum e parametrizar por id (o Data Chat passa a usar a mesma base).
3. `QueryPlanner` e matriz de compatibilidade.
4. `Envelope` e regras de `display` (pt, en, es).
5. `Resolver` com candidatos.
6. Auditoria e retenção.
7. Specs: isolamento, paridade com `Results::AnswerCounts::*`, contrato rswag, carga.

Aceite:
- Paridade 100% nos casos da fixture para as 7 métricas × recortes da fase.
- `GET /model` igual ao snapshot de `skills/.../references/*.yaml` (CI deste repositório).
- p95 de `/query` abaixo do limite acordado (Q7) no maior cliente, 12 meses, `group_by` unidade × mês.

## Fase 2: skill v0.1, MCP local e piloto

Escopo neste repositório:
- `SKILL.md` e `references/` revisados contra a API real (substituir exemplos por respostas reais da fixture).
- Servidor MCP `solvis-analytics` (stdio), ferramentas de [tools.md](../skills/solvis-survey-analysis/references/tools.md), validação do envelope contra o OpenAPI, credencial por variável de ambiente.
- Harness de avaliação: roda os casos de `evals/cases.yaml` em 2 ou mais modelos de fornecedores diferentes contra a fixture e mede os critérios de sucesso.
- CI: validação do `SKILL.md` (`skills-ref validate`), lint de YAML, teste de contrato do snapshot do modelo, avaliação em PR que toca `skills/`.
- Empacotamento de release (zip da skill + pacote MCP) e guia de instalação por plataforma.

Piloto:
- 2 a 3 clientes com perfis diferentes (rede grande com propriedades de unidade; cliente com Data Quality ligado; cliente só web).
- Credenciais com escopo `analytics:read` apenas.
- Revisão semanal das consultas auditadas e das respostas que os clientes reportarem como erradas.

Aceite: metas de sucesso atingidas na fixture; nenhum erro numérico reportado no piloto em 4 semanas; cada erro de interpretação vira caso novo em `evals/`.

## Fase 3: texto e recortes avançados

- `POST /comments/search` com mascaramento, LGPD e campos do Radar.
- Métricas `theme_mentions`, `data_quality_summary`, `choice_set_share`.
- Recortes `day_of_week`, `hour_block`, `shift`, `author_nps_group`, `reference_choice`, `unit_state`; filtros `tag_ids`, `comment_tone`.
- Playbooks 2, 8, 9 e 10 completos; casos adversariais de injeção em comentários.

Aceite: paridade das novas dimensões com `Results::AnswerCounts::Crossed*`; casos adversariais 100%.

## Fase 4: escala de distribuição

- MCP remoto hospedado pela Solvis (Streamable HTTP), OAuth 2.1 authorization code + PKCE no Doorkeeper, metadados de recurso protegido (RFC 9728).
- OpenAPI público e variante condensada do `SKILL.md` para plataformas só com function calling.
- `POST /exports` normalizado (opcional, ver backend-requirements).
- Processo de release: semver da skill e do modelo, changelog para clientes, política de depreciação.

## Riscos

| Risco | Impacto | Mitigação |
|---|---|---|
| Achados de isolamento na API atual | Vazamento entre clientes, independente da skill | Fase 0 antes de tudo; verificação de logs |
| Custo do ClickHouse (consultas leem o shard inteiro) | Lentidão e disputa com Data Chat e telas | Usuário e cota próprios, cache por SQL, limite por credencial, teste de carga |
| Espelho atrasado | Números desatualizados | Watermark no envelope e `stale_mirror` |
| LLM do cliente ignora regras da skill | Números recalculados ou inventados | Envelope com `totals`/`delta` para não haver o que calcular; avaliação em vários modelos; formato de resposta com fontes facilita auditoria pelo usuário |
| Divergência entre modelo semântico e código | Explicação errada de números corretos | Fonte única no backend, teste de contrato no CI, semver |
| Questionário editado depois da coleta | Histórico lido com cadastro novo | Aviso `values_from_current_questionnaire`; avaliar versionamento de alternativas no produto (fora deste plano) |
| PII em comentários | LGPD | Escopo separado, mascaramento, sem IP/fingerprint/identifier, auditoria |
| Plataformas dos clientes não suportam skills nem MCP | Adoção baixa | OpenAPI + prompt condensado (Fase 4); confirmar plataformas em Q1 antes da Fase 2 |
