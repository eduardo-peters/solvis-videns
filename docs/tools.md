# Biblioteca de tools

Gerado por `python3 mcp/gen_docs.py` a partir de `mcp/solvis_tools/`. Não edite à mão: o teste `tests/mcp` falha se este arquivo e o código divergirem.

Cada perfil de agente roda uma instância do servidor MCP (`python3 mcp/server.py --agent <perfil>`) e enxerga só as próprias tools. Todas são somente leitura. Como a engenharia funciona: [engineering.md](engineering.md).

## Perfis

| Perfil | Para quê | Tools |
|---|---|---|
| `analyst` | Responde perguntas de negócio sobre os resultados: métricas calculadas no servidor, catálogo e regras da skill. | [`nps`](#nps), [`scale_mean`](#scale_mean), [`choice_share`](#choice_share), [`evaluation_count`](#evaluation_count), [`list_surveys`](#list_surveys), [`list_questions`](#list_questions), [`list_unit_properties`](#list_unit_properties), [`data_coverage`](#data_coverage), [`metadata_catalog`](#metadata_catalog), [`describe_survey`](#describe_survey), [`explain_metric`](#explain_metric), [`skill_lookup`](#skill_lookup), [`question_types`](#question_types) |
| `data_engineer` | Cuida da qualidade e do significado dos dados: metadados, saúde, metodologia, avaliações e regras da skill. | [`list_surveys`](#list_surveys), [`data_coverage`](#data_coverage), [`metadata_catalog`](#metadata_catalog), [`describe_survey`](#describe_survey), [`unit_metadata`](#unit_metadata), [`data_health`](#data_health), [`explain_metric`](#explain_metric), [`skill_lookup`](#skill_lookup), [`methodology_rules`](#methodology_rules), [`quality_status`](#quality_status), [`question_types`](#question_types) |

## Matriz

| Tool | `analyst` | `data_engineer` | Credencial | Lê |
|---|---|---|---|---|
| [`nps`](#nps) | ✓ |  | client | semantic.nps_by_unit, semantic.nps_by_unit_property, raw.units |
| [`scale_mean`](#scale_mean) | ✓ |  | client | semantic.scale_mean |
| [`choice_share`](#choice_share) | ✓ |  | client | semantic.choice_share |
| [`evaluation_count`](#evaluation_count) | ✓ |  | client | raw.evaluations (client_id, survey_id, day, unit_id) |
| [`list_surveys`](#list_surveys) | ✓ | ✓ | client | raw.surveys |
| [`list_questions`](#list_questions) | ✓ |  | client | raw.questions |
| [`list_unit_properties`](#list_unit_properties) | ✓ |  | client | raw.unit_properties |
| [`data_coverage`](#data_coverage) | ✓ | ✓ | client | raw.evaluations, raw.surveys |
| [`metadata_catalog`](#metadata_catalog) | ✓ | ✓ | engineer | ops/metadata_catalog.json, ops.data_health |
| [`describe_survey`](#describe_survey) | ✓ | ✓ | engineer | raw.surveys, raw.questions, raw.choices, raw.evaluations (dia) |
| [`unit_metadata`](#unit_metadata) |  | ✓ | engineer | raw.units, raw.unit_properties, raw.evaluations (unit_id) |
| [`data_health`](#data_health) |  | ✓ | engineer | ops.data_health |
| [`explain_metric`](#explain_metric) | ✓ | ✓ | engineer | skills/.../references/metrics.yaml |
| [`skill_lookup`](#skill_lookup) | ✓ | ✓ | engineer | semantic.skill_chunks, Ollama nomic-embed-text |
| [`methodology_rules`](#methodology_rules) |  | ✓ | engineer | skills/.../references/invariants.md, ops.methodology_checks (regra e resultado) |
| [`quality_status`](#quality_status) |  | ✓ | engineer | ops.eval_runs, ops.guardrail_events (guardrail e ação) |
| [`question_types`](#question_types) | ✓ | ✓ | engineer | skills/.../references/question-types.md |

## Credenciais

- **client**: `assai_agent`: views semânticas e dimensões do cliente; sem respostas individuais
- **engineer**: `engineer_agent`: metadados e resultados agregados de qualidade; sem respostas individuais e sem conversas

## nps

NPS de uma pesquisa, com total calculado pelas contagens, pior e melhor linha, linhas com amostra pequena e cobertura do período. Recusa pergunta que não é do tipo NPS.

- **Perfis:** `analyst`
- **Credencial:** `client`
- **Lê:** semantic.nps_by_unit, semantic.nps_by_unit_property, raw.units
- **Skill:** metrics.yaml#nps, INV-02, INV-23, playbooks.md#3, playbooks.md#6

| Parâmetro | Tipo | Obrigatório | Descrição |
|---|---|---|---|
| `survey` | string | sim | Nome da pesquisa como o usuário disse (ex.: 'Satisfação') |
| `question` | string |  | Texto ou número da pergunta (ex.: 'Atendimento', '2') |
| `period` | string |  | yesterday, today, last_7_days, this_month, last_month ou month:AAAA-MM |
| `start` | string |  | Data inicial AAAA-MM-DD (em vez de period) |
| `end` | string |  | Data final AAAA-MM-DD (em vez de period) |
| `group_by` | string |  | none, unit ou nome da propriedade de unidade (Regional, Formato da loja...) |
| `min_n` | integer |  | Esconde linhas com menos respostas (use 30 em rankings) |

Exemplo (`tools/call`):

```json
{"name": "nps", "arguments": {"survey": "Satisfação", "group_by": "Regional", "period": "yesterday"}}
```

## scale_mean

Média de uma pergunta de escala, sem as alternativas sem valor ('Não se aplica').

- **Perfis:** `analyst`
- **Credencial:** `client`
- **Lê:** semantic.scale_mean
- **Skill:** metrics.yaml#scale_mean, INV-05, INV-06

| Parâmetro | Tipo | Obrigatório | Descrição |
|---|---|---|---|
| `survey` | string | sim | Nome da pesquisa como o usuário disse (ex.: 'Satisfação') |
| `question` | string | sim | Texto ou número da pergunta (ex.: 'Atendimento', '2') |
| `period` | string |  | yesterday, today, last_7_days, this_month, last_month ou month:AAAA-MM |
| `start` | string |  | Data inicial AAAA-MM-DD (em vez de period) |
| `end` | string |  | Data final AAAA-MM-DD (em vez de period) |

Exemplo (`tools/call`):

```json
{"name": "scale_mean", "arguments": {"survey": "Satisfação", "question": "Atendimento", "period": "yesterday"}}
```

## choice_share

Distribuição (%) das alternativas de uma pergunta de escala ou escolha única. 'Não se aplica' entra no denominador.

- **Perfis:** `analyst`
- **Credencial:** `client`
- **Lê:** semantic.choice_share
- **Skill:** metrics.yaml#choice_share, playbooks.md#7

| Parâmetro | Tipo | Obrigatório | Descrição |
|---|---|---|---|
| `survey` | string | sim | Nome da pesquisa como o usuário disse (ex.: 'Satisfação') |
| `question` | string | sim | Texto ou número da pergunta (ex.: 'Atendimento', '2') |
| `period` | string |  | yesterday, today, last_7_days, this_month, last_month ou month:AAAA-MM |
| `start` | string |  | Data inicial AAAA-MM-DD (em vez de period) |
| `end` | string |  | Data final AAAA-MM-DD (em vez de period) |

Exemplo (`tools/call`):

```json
{"name": "choice_share", "arguments": {"survey": "Satisfação", "question": "Atendimento", "period": "yesterday"}}
```

## evaluation_count

Quantidade de avaliações, no total ou por pesquisa, unidade ou propriedade. A unidade do topo vem com a pesquisa de origem.

- **Perfis:** `analyst`
- **Credencial:** `client`
- **Lê:** raw.evaluations (client_id, survey_id, day, unit_id)
- **Skill:** metrics.yaml#evaluation_count, INV-09, playbooks.md#12

| Parâmetro | Tipo | Obrigatório | Descrição |
|---|---|---|---|
| `survey` | string |  | Nome da pesquisa como o usuário disse (ex.: 'Satisfação') |
| `period` | string |  | yesterday, today, last_7_days, this_month, last_month ou month:AAAA-MM |
| `start` | string |  | Data inicial AAAA-MM-DD (em vez de period) |
| `end` | string |  | Data final AAAA-MM-DD (em vez de period) |
| `group_by` | string |  | none, survey, unit ou nome da propriedade |

Exemplo (`tools/call`):

```json
{"name": "evaluation_count", "arguments": {"group_by": "unit", "period": "yesterday"}}
```

## list_surveys

Busca pesquisas pelo nome (ativas primeiro).

- **Perfis:** `analyst`, `data_engineer`
- **Credencial:** `client`
- **Lê:** raw.surveys
- **Skill:** INV-11

| Parâmetro | Tipo | Obrigatório | Descrição |
|---|---|---|---|
| `search` | string |  | Parte do nome |

Exemplo (`tools/call`):

```json
{"name": "list_surveys", "arguments": {"search": "Açougue"}}
```

## list_questions

Perguntas de uma pesquisa (número, tipo, texto).

- **Perfis:** `analyst`
- **Credencial:** `client`
- **Lê:** raw.questions
- **Skill:** question-types.md

| Parâmetro | Tipo | Obrigatório | Descrição |
|---|---|---|---|
| `survey` | string | sim | Nome da pesquisa como o usuário disse (ex.: 'Satisfação') |

Exemplo (`tools/call`):

```json
{"name": "list_questions", "arguments": {"survey": "Satisfação"}}
```

## list_unit_properties

Propriedades de unidade disponíveis para recorte (Regional, Formato...), com quantidade de valores.

- **Perfis:** `analyst`
- **Credencial:** `client`
- **Lê:** raw.unit_properties
- **Skill:** INV-13, playbooks.md#6

Sem parâmetros.

Exemplo (`tools/call`):

```json
{"name": "list_unit_properties", "arguments": {}}
```

## data_coverage

Dias com dados carregados por pesquisa (primeiro dia, último dia, avaliações).

- **Perfis:** `analyst`, `data_engineer`
- **Credencial:** `client`
- **Lê:** raw.evaluations, raw.surveys
- **Skill:** INV-24

Sem parâmetros.

Exemplo (`tools/call`):

```json
{"name": "data_coverage", "arguments": {}}
```

## metadata_catalog

Catálogo de metadados semânticos: para cada campo (pesquisa, pergunta, unidade, tag), para que a IA o usa, se existe (testing, engine, inferred, missing), fonte, dono, regra da skill ligada e o resultado mais recente da checagem de saúde correspondente.

- **Perfis:** `data_engineer`, `analyst`
- **Credencial:** `engineer`
- **Lê:** ops/metadata_catalog.json, ops.data_health
- **Skill:** invariants.md, docs/metadata-semantics.md

| Parâmetro | Tipo | Obrigatório | Descrição |
|---|---|---|---|
| `level` | string |  | survey, question, unit ou tag (opcional) |
| `status` | string |  | testing, engine, inferred ou missing (opcional) |

Exemplo (`tools/call`):

```json
{"name": "metadata_catalog", "arguments": {"level": "unit"}}
```

## describe_survey

Ficha de uma pesquisa para interpretar antes de consultar: perguntas com tipo, métricas que existem para cada uma (pela skill), alternativas sem valor, textos repetidos, dias carregados e avisos de metadado que faltam.

- **Perfis:** `data_engineer`, `analyst`
- **Credencial:** `engineer`
- **Lê:** raw.surveys, raw.questions, raw.choices, raw.evaluations (dia)
- **Skill:** question-types.md, INV-04, INV-05, INV-10, INV-16

| Parâmetro | Tipo | Obrigatório | Descrição |
|---|---|---|---|
| `survey` | string | sim | Nome da pesquisa |

Exemplo (`tools/call`):

```json
{"name": "describe_survey", "arguments": {"survey": "Satisfação"}}
```

## unit_metadata

Unidades com problema de metadado: UF inválida, nome de canal ou unidade que não é loja, sem nenhuma propriedade. Mostra quantas avaliações cada problema afeta no que está carregado.

- **Perfis:** `data_engineer`
- **Credencial:** `engineer`
- **Lê:** raw.units, raw.unit_properties, raw.evaluations (unit_id)
- **Skill:** INV-13, INV-23

| Parâmetro | Tipo | Obrigatório | Descrição |
|---|---|---|---|
| `issue` | string |  | invalid_uf, not_store ou no_properties (opcional: todos) |
| `limit` | integer |  | Máximo de unidades por problema (padrão 20) |

Exemplo (`tools/call`):

```json
{"name": "unit_metadata", "arguments": {"issue": "invalid_uf"}}
```

## data_health

Resultado mais recente de cada checagem de saúde dos dados (paridade com o piloto, consistência, isolamento, índice da skill, UF, tipo de unidade, perguntas repetidas, contexto, frescor). Para rodar de novo: python3 ops/pipeline.py.

- **Perfis:** `data_engineer`
- **Credencial:** `engineer`
- **Lê:** ops.data_health
- **Skill:** docs/data-ops.md

| Parâmetro | Tipo | Obrigatório | Descrição |
|---|---|---|---|
| `level` | string |  | ok, warn ou fail (opcional) |

Exemplo (`tools/call`):

```json
{"name": "data_health", "arguments": {"level": "warn"}}
```

## explain_metric

Definição de uma métrica pela skill (metrics.yaml): o que é, o que conta em n, armadilhas, e se existe no protótipo. Também responde métricas que não existem (csat, response_rate...).

- **Perfis:** `data_engineer`, `analyst`
- **Credencial:** `engineer`
- **Lê:** skills/.../references/metrics.yaml
- **Skill:** metrics.yaml, INV-25

| Parâmetro | Tipo | Obrigatório | Descrição |
|---|---|---|---|
| `metric` | string |  | Id da métrica (ex.: nps, scale_mean, csat). Vazio lista os ids |

Exemplo (`tools/call`):

```json
{"name": "explain_metric", "arguments": {"metric": "csat"}}
```

## skill_lookup

Busca vetorial nas regras da skill (SKILL.md, invariantes, playbooks, glossário, limitações, formato de resposta, tipos de pergunta). Devolve os trechos mais próximos com a fonte.

- **Perfis:** `data_engineer`, `analyst`
- **Credencial:** `engineer`
- **Lê:** semantic.skill_chunks, Ollama nomic-embed-text
- **Skill:** toda a skill do piloto

| Parâmetro | Tipo | Obrigatório | Descrição |
|---|---|---|---|
| `query` | string | sim | Assunto ou pergunta (ex.: 'como tratar amostra pequena em ranking') |
| `k` | integer |  | Quantos trechos (padrão 3, máximo 8) |

Exemplo (`tools/call`):

```json
{"name": "skill_lookup", "arguments": {"query": "NPS geral de várias lojas", "k": 3}}
```

## methodology_rules

Regras invariantes da skill, quais são checadas automaticamente em cada resposta e a taxa de aprovação de cada uma (avaliação e uso real, agregadas).

- **Perfis:** `data_engineer`
- **Credencial:** `engineer`
- **Lê:** skills/.../references/invariants.md, ops.methodology_checks (regra e resultado)
- **Skill:** invariants.md

Sem parâmetros.

Exemplo (`tools/call`):

```json
{"name": "methodology_rules", "arguments": {}}
```

## quality_status

Estado da qualidade do agente: últimas avaliações (acerto, tempo, versão do código, portão) e quantas vezes cada guardrail atuou.

- **Perfis:** `data_engineer`
- **Credencial:** `engineer`
- **Lê:** ops.eval_runs, ops.guardrail_events (guardrail e ação)
- **Skill:** docs/data-ops.md

| Parâmetro | Tipo | Obrigatório | Descrição |
|---|---|---|---|
| `limit` | integer |  | Quantas avaliações recentes (padrão 5) |

Exemplo (`tools/call`):

```json
{"name": "quality_status", "arguments": {"limit": 3}}
```

## question_types

Tipos de pergunta da Solvis pela skill: o que é cada tipo, quais métricas existem e observações.

- **Perfis:** `data_engineer`, `analyst`
- **Credencial:** `engineer`
- **Lê:** skills/.../references/question-types.md
- **Skill:** question-types.md

| Parâmetro | Tipo | Obrigatório | Descrição |
|---|---|---|---|
| `answer_type` | string |  | Tipo (ex.: Scale, Multiple Response). Vazio lista todos |

Exemplo (`tools/call`):

```json
{"name": "question_types", "arguments": {"answer_type": "Multiple Response"}}
```
