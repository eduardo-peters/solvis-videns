# Como a engenharia funciona

Data: 2026-11-19 · Protótipo local, só em `127.0.0.1`. Fluxo ilustrado: [fluxo.html](fluxo.html) · Tools: [tools.md](tools.md) · Qualidade: [data-ops.md](data-ops.md) · Metadados: [metadata-semantics.md](metadata-semantics.md)

## Visão geral

Cinco camadas. Cada uma tem uma responsabilidade só, e nenhuma depende de o modelo acertar.

```
┌─ 5. Agentes ───────────────────────────────────────────────────────────────────────┐
│  qualquer host MCP (Kiro, Claude, Cursor...) ou o agente local (agent/, qwen3:1.7b)  │
│  perfil analyst · perfil data_engineer                                               │
└──────────────────────────────┬──────────────────────────────────────────────────────┘
┌─ 4. Tools (mcp/) ─────────────▼──────────────────────────────────────────────────────┐
│  biblioteca registrada: esquema, descrição, credencial, o que lê, regras da skill    │
│  servidor MCP stdio, uma instância por perfil, cada uma vê só as próprias tools      │
└──────────────────────────────┬──────────────────────────────────────────────────────┘
┌─ 3. Conhecimento ─────────────▼──────────────────────────────────────────────────────┐
│  skill do piloto (regras, métricas, tipos)  ·  catálogo de metadados (ops/)           │
│  semantic.skill_chunks: regras vetorizadas para busca                                │
└──────────────────────────────┬──────────────────────────────────────────────────────┘
┌─ 2. Camada semântica (clickhouse/) ▼─────────────────────────────────────────────────┐
│  views com as fórmulas das telas · contagens pré-agregadas · row policy por cliente  │
└──────────────────────────────┬──────────────────────────────────────────────────────┘
┌─ 1. Dados ────────────────────▼──────────────────────────────────────────────────────┐
│  API V1 → motor do piloto (normaliza, mascara) → raw.* no ClickHouse                 │
└─────────────────────────────────────────────────────────────────────────────────────┘
        ▲ tudo o que acontece em 4 e 5 é gravado em ops.* e checado por ops/pipeline.py
```

## 1. Dados

| Etapa | Onde | O que garante |
|---|---|---|
| Extração | `skills/solvis-survey-analysis-pilot/scripts/` (motor do piloto) | Janelas por dia local, divisão em página cheia, livro de cobertura |
| Normalização | idem | Respostas por `question_id`/`choice_id` reconstruídos (a API V1 não envia) |
| Privacidade | idem | IP e identificador descartados; texto LGPD e pessoal nunca guardado; comentários mascarados |
| Carga | `clickhouse/load_from_pilot_cache.py` | Só ids, contagens e dimensões. Nenhum texto livre |
| Pré-agregação | materialized view → `semantic.answer_counts_daily` | Contagens por dia, unidade, canal, confiabilidade |

Em produção, o espelho PeerDB substitui o motor do piloto nesta camada. As camadas de cima não mudam.

## 2. Camada semântica

As métricas são views parametrizadas (`clickhouse/02_semantic.sql`), com as fórmulas das telas: NPS pelas contagens, média sem "Não se aplica", distribuição com N/A no denominador. Quem consulta não escreve fórmula.

| Proteção | Como |
|---|---|
| Fórmula única | Uma view por métrica; skill, MCP e agente usam as mesmas |
| Paridade | `ops/pipeline.py` compara com o motor do piloto (NPS 79, n 11.709 em 17/11) |
| Consistência | Contagens pré-agregadas = respostas brutas (114.045 = 114.045) |
| Isolamento | Row policy por `client_id`; credenciais sem acesso a respostas individuais |

## 3. Conhecimento: skill e metadados

Três fontes, todas lidas por tools (não coladas no prompt):

| Fonte | Arquivo | Lida por |
|---|---|---|
| Regras e métricas da skill | `skills/solvis-survey-analysis-pilot/references/` | `explain_metric`, `question_types`, `methodology_rules`, `skill_lookup` |
| Catálogo de metadados | `ops/metadata_catalog.json` (26 campos em 4 níveis) | `metadata_catalog`, `describe_survey` |
| Regras vetorizadas | `semantic.skill_chunks` (41 trechos, `nomic-embed-text`) | `skill_lookup`, contexto do agente local |

O catálogo liga cada campo de metadado a três coisas: a regra da skill que depende dele (ex.: tipo de unidade → INV-23, amostra pequena em ranking), a checagem de saúde que o mede (`units_not_stores`) e o dono (produto, CX, engenharia). A lista que a operação levantar entra neste arquivo.

## 4. Tools e MCP

Cada tool é registrada uma vez em `mcp/solvis_tools/` com: nome, descrição, esquema de entrada com descrição por parâmetro, perfis que a recebem, credencial que a executa, o que ela lê, regras da skill ligadas e um exemplo. Sem esses campos ela não registra. A documentação ([tools.md](tools.md)) é gerada desse registro, e um teste falha se divergir.

| Perfil | Tools | Credencial |
|---|---|---|
| `analyst` (13) | Métricas (`nps`, `scale_mean`, `choice_share`, `evaluation_count`), catálogo (`list_*`, `data_coverage`) e leitura de conhecimento (`metadata_catalog`, `describe_survey`, `explain_metric`, `skill_lookup`, `question_types`) | `assai_agent` nas métricas; `engineer_agent` nas de conhecimento |
| `data_engineer` (11) | Metadados (`metadata_catalog`, `describe_survey`, `unit_metadata`), qualidade (`data_health`, `methodology_rules`, `quality_status`) e skill (`explain_metric`, `skill_lookup`, `question_types`), mais `list_surveys` e `data_coverage` | `engineer_agent` |

Regras do desenho:
- **Menor privilégio por perfil.** O analista não vê auditoria nem saúde dos dados; o engenheiro não calcula métricas de negócio. Tool de outro perfil é recusada pelo servidor.
- **Somente leitura.** Toda tool é anotada `readOnlyHint`; as credenciais não escrevem.
- **Sem SQL vindo do modelo.** Argumentos são validados contra o esquema (tipos, obrigatórios, nada extra) e entram em SQL fixo como parâmetros tipados.
- **Erro de negócio volta para o modelo** (`isError: true`) com o motivo e o que fazer ("pergunta ambígua, pergunte qual destas"). Erro de protocolo (tool de outro perfil, método desconhecido) volta como erro JSON-RPC.
- **Toda chamada é auditada** em `ops.tool_calls`, com sessão por instância do servidor.

| Credencial | Lê | Não lê | Escreve |
|---|---|---|---|
| `assai_agent` | Views semânticas, dimensões do cliente | `raw.answers`, `ops.*` | Nada |
| `engineer_agent` | Metadados, `semantic.skill_chunks`, `ops.data_health`, `ops.eval_runs`, regra e resultado de `ops.methodology_checks` e `ops.guardrail_events` | `raw.answers`, `ops.interactions`, `ops.tool_calls` (conversas) | Nada |
| `agent_audit` | Nada | Tudo | Só `INSERT` em `ops.*` |

## 5. Agentes

- **Hosts MCP** (Kiro, Claude, Cursor): conectam um servidor por perfil ([mcp/README.md](../mcp/README.md)).
- **Agente local** (`agent/`): o `qwen3:1.7b` com as tools de métrica, resolução de nomes em código, guardrails de saída e a tela em `127.0.0.1:8080`.

## Qualidade: o ciclo que fecha tudo

```
uso real / avaliação / testes ──> ops.* ──> ops/pipeline.py ──> portão ──> revisão humana ──> caso novo + correção
```

| Etapa do pipeline | O que verifica |
|---|---|
| 1. Saúde dos dados | Paridade, consistência, isolamento, índice da skill atual, UF, tipo de unidade, propriedades, perguntas repetidas, contexto, frescor |
| 2. Testes sem LLM (34) | 21 de guardrails e isolamento do agente; 13 da biblioteca de tools e do MCP (documentação em dia, referências da skill reais, exemplos executam, menor privilégio, protocolo) |
| 3. Avaliação | Casos com o modelo, versionados pelo hash de todo o código, das views, dos acessos, do catálogo e da skill |
| 4. Metodologia | 8 das 31 regras invariantes da skill checadas em cada resposta |
| 5. Portão | Reprova abaixo dos limites de `ops/gate.json` ou com regressão |
| 6. Revisão | Falhas de uso real viram candidatos; só entram com aprovação |

Detalhes e consultas de acompanhamento: [data-ops.md](data-ops.md).

## Treino do modelo

LoRA no MLX sobre o Qwen3 1.7B, com dados gerados das regras da skill (sem dados de cliente). Ensina comportamento (escolher a tool, recusar, ler o resultado). Não ensina números. Detalhes, log e resultados: [training.md](training.md). v1: no holdout, 62,5% contra 25% do base no mesmo backend, mas ainda abaixo do agente atual no Ollama (75%).

## Como evoluir

| Quero | Faço | O pipeline confere |
|---|---|---|
| Novo metadado da operação | Linha em `ops/metadata_catalog.json` (+ checagem em `ops/pipeline.py` se mensurável) | Checagem citada existe; regra da skill citada existe |
| Nova tool | `@tool(...)` em `mcp/solvis_tools/`, depois `python3 mcp/gen_docs.py` | Documentação em dia; exemplo executa; perfil e credencial certos |
| Nova métrica | View em `clickhouse/02_semantic.sql` + tool | Paridade (acrescente o valor esperado em `ops/gate.json`) |
| Mudar regra da skill | Editar a skill e `python3 agent/context.py index` | `skill_index_current` falha se esquecer de reindexar |
| Novo perfil de agente | Entrada em `AGENTS` (`mcp/solvis_tools/__init__.py`) e `agents=[...]` nas tools | Testes de menor privilégio |

## Limites atuais

- Um dia de dados (17/11/2026), um cliente.
- `describe_survey` não traz LGPD, `metric_kind` nem fluxo da pesquisa, que estão só no motor do piloto.
- 23 das 31 regras invariantes ainda não têm checagem automática (`methodology_rules` lista quais).
- MCP só em stdio local; o remoto com OAuth é a Fase 4 do [plano](PLAN.md).
