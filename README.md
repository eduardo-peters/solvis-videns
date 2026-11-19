# solvis-survey-analysis-skill

Skill de análise de resultados de pesquisas da plataforma Solvis, para clientes usarem nas próprias LLMs.

> **Status:** duas versões da skill e um protótipo local convivem neste repositório.
> - **`solvis-survey-analysis-pilot` (v0.2.0-pilot), utilizável hoje.** Funciona sobre a API pública V1, sem mudança no backend: um motor local em Python calcula as métricas com as regras das telas. Ver [docs/pilot/README.md](docs/pilot/README.md).
> - **`solvis-survey-analysis` (v0.1.0-draft), plano principal.** Depende da API Analytics v1, que ainda não existe no `survey_system`. Nada dela deve ser entregue a cliente antes da Fase 2 do [plano](docs/PLAN.md).
> - **Protótipo local `clickhouse/` + `agent/` (2026-11-19), só para teste interno.** Camada semântica no ClickHouse e um modelo local (Ollama, `qwen3:1.7b`) conversando com ela numa tela de terminal no navegador. Ver [Protótipo local](#protótipo-local-clickhouse--modelo-local) e o fluxo ilustrado em [docs/fluxo.html](docs/fluxo.html).

> [!WARNING]
> **Dados reais de cliente nesta branch (`slm-trainning`).** O protótipo local (`clickhouse/`, `agent/`, `mcp/`, `ops/`, `tests/agent/`, `tests/mcp/` e os documentos em `docs/` ligados a ele) traz dados reais do Assaí de 17/11/2026: nomes de lojas, resultados agregados (NPS, médias, volumes), metadados de unidades e ids de pesquisa e pergunta. Não há respostas individuais, comentários, dados pessoais nem credenciais. A inclusão foi decidida com ciência do CTO para revisão interna. Antes de levar isso para `main` ou para fora do time, anonimize esses arquivos ou tire-os do repositório. Os dados de treino (`ops/training/`) são fictícios.

## O que é

A skill ensina uma LLM a responder perguntas sobre resultados de pesquisas (NPS, notas de escala, distribuição de alternativas, volume, comentários e temas) **sem calcular nada sozinha**. Todo número vem de uma camada semântica servida pela Solvis, que aplica as mesmas fórmulas, filtros e regras de escopo das telas de resultados e devolve cada resultado com a evidência necessária para citá-lo (n, período, filtros, políticas, frescor e `query_id`).

```
LLM do cliente
  └─ Skill (este repositório)          instruções, modelo semântico, playbooks, formato de resposta
       └─ Ferramentas (MCP ou HTTP)    adaptador fino, sem regra de negócio
            └─ API Analytics v1        survey_system: escopo, fórmulas, auditoria (a construir)
                 └─ espelho ClickHouse dos shards de resultados
```

## Estrutura

| Caminho | Conteúdo | Vai para o cliente? |
|---|---|---|
| `skills/solvis-survey-analysis-pilot/` | Skill do piloto: `SKILL.md`, `references/` e o motor `scripts/solvis.py` (API pública V1, Python 3.9+, sem dependências) | Sim, no piloto |
| `skills/solvis-survey-analysis/` | A skill no padrão [Agent Skills](https://agentskills.io/specification): `SKILL.md`, `references/` (modelo semântico e regras) | Sim, como artefato de release |
| `api/openapi.analytics.v1.yaml` | Contrato proposto da API Analytics v1 | Sim, quando a API existir (versão publicada) |
| `evals/` | Casos de avaliação da skill (perguntas, chamadas esperadas, armadilhas); `cases-pilot.yaml` para o piloto | Não |
| `tests/pilot/` | Testes do motor do piloto com uma API V1 falsa | Não |
| `tests/agent/` | Testes dos guardrails e do isolamento do agente local, sem LLM | Não |
| `tests/mcp/` | Testes da biblioteca de tools e do protocolo MCP, sem LLM | Não |
| `clickhouse/` | Protótipo: schema, views semânticas (métricas), isolamento por cliente e carga a partir do cache do piloto | Não |
| `mcp/` | Protótipo: servidor MCP stdio com biblioteca de tools por perfil de agente (`analyst`, `data_engineer`); gera `docs/tools.md` | Não |
| `ops/` | Protótipo: auditoria em `ops.*`, saúde dos dados, metodologia da skill por resposta e portão de qualidade | Não |
| `agent/` | Protótipo: agente com modelo local, ferramentas fixas, guardrails, contexto da skill por busca vetorial, tela no navegador e avaliação | Não |
| `docs/` | Plano, arquitetura, decisões (ADRs), requisitos para o backend, distribuição, perguntas em aberto; `docs/pilot/` para o piloto | Não |

Este repositório é privado. O que chega ao cliente é o artefato de release montado a partir de `skills/` (e, depois, o pacote do servidor MCP). Ver [docs/distribution.md](docs/distribution.md).

## Por onde começar

1. [docs/PLAN.md](docs/PLAN.md): fases, entregas e critérios de aceite.
2. [docs/architecture.md](docs/architecture.md): camadas e fluxo de uma pergunta.
3. [docs/backend-requirements.md](docs/backend-requirements.md): o que o `survey_system` precisa implementar e qual código existente reaproveitar.
4. [skills/solvis-survey-analysis/SKILL.md](skills/solvis-survey-analysis/SKILL.md): a skill em si.
5. [docs/open-questions.md](docs/open-questions.md): decisões que dependem de vocês.
6. [docs/engineering.md](docs/engineering.md): como a engenharia funciona, camada por camada; [docs/tools.md](docs/tools.md): biblioteca de tools por perfil (gerada do código).
7. [docs/training.md](docs/training.md): treino LoRA do modelo local com a skill; log em `ops/logs/training.log`.
8. [docs/fluxo.html](docs/fluxo.html): fluxo ilustrado de uma pergunta no protótipo local (abra no navegador).
9. [docs/data-ops.md](docs/data-ops.md): engenharia de dados do agente: guardrails testados, evals com portão, ajuste com aprovação, metodologia e auditoria.
10. [docs/metadata-semantics.md](docs/metadata-semantics.md): metadados semânticos, o que já está em teste no protótipo ClickHouse (`clickhouse/`) e o que falta.

## Protótipo local (ClickHouse + modelo local)

Prova de conceito da ideia de usar o ClickHouse como motor da camada semântica e um modelo pequeno, rodando na máquina, como interface de conversa. Tudo escuta só em `127.0.0.1`. Fluxo detalhado em [docs/fluxo.html](docs/fluxo.html).

```
navegador (127.0.0.1:8080)
  └─ agent/server.py           tela de terminal
       └─ agent/agent.py       laço do agente, resolução de nomes, guardrails
            ├─ Ollama          qwen3:1.7b (conversa) + nomic-embed-text (embeddings)
            └─ ClickHouse      views semânticas (métricas) + semantic.skill_chunks (regras da skill vetorizadas)
                 └─ dados      cache do motor do piloto (API V1), carregado por clickhouse/load_from_pilot_cache.py
```

Divisão de trabalho: o modelo escolhe a ferramenta e escreve; o código resolve nomes em ids, períodos em datas e tipos de pergunta; o ClickHouse calcula e isola o cliente; os guardrails conferem números, datas, métrica e fundamentação de cada resposta.

| Resultado (Assaí, 17/11/2026, 11.709 avaliações) | Valor |
|---|---|
| Paridade com o motor do piloto (NPS total e por Regional) | Idêntica |
| Tempo de consulta no ClickHouse | 0,03 s (o piloto leva 1min42s para baixar o dia) |
| Isolamento: agente lendo outro cliente / respostas individuais | 0 linhas / negado |
| Avaliação do agente (17 casos × 2) | 100% sem e com contexto da skill; 4,5 s e 7,7 s por resposta |

Tools: as mesmas capacidades saem como servidor MCP local, com uma biblioteca por perfil de agente: `analyst` (13 tools) e `data_engineer` (11 tools de metadados, qualidade e skill). Ver [docs/tools.md](docs/tools.md) e [mcp/README.md](mcp/README.md).

Qualidade: `ops/pipeline.py` roda saúde dos dados, 34 testes sem LLM (guardrails, tools e MCP), avaliação, metodologia e um portão; tudo fica auditado no banco `ops` ([docs/data-ops.md](docs/data-ops.md)).

Rodar: [clickhouse/README.md](clickhouse/README.md), depois [agent/README.md](agent/README.md), [ops/README.md](ops/README.md) e [mcp/README.md](mcp/README.md). Visão de conjunto: [docs/engineering.md](docs/engineering.md). O 100% é de um conjunto de desenvolvimento; ver as ressalvas no README do agente.

## Fontes

O conteúdo semântico foi extraído do código do `survey_system` (commit `f594c4a6`, 2026-11-17), com citação `arquivo:linha` nos relatórios de pesquisa. Os relatórios completos ficam fora deste repositório, em `~/work/_interno_skill_analise/pesquisa/`, porque descrevem detalhes internos e falhas de segurança.

## Validação da skill

Validador de referência do padrão Agent Skills ([skills-ref](https://github.com/agentskills/agentskills/tree/main/skills-ref), uso de demonstração):

```bash
git clone --depth 1 https://github.com/agentskills/agentskills /tmp/agentskills
cd /tmp/agentskills/skills-ref && uv sync && . .venv/bin/activate
skills-ref validate ~/work/solvis-survey-analysis-skill/skills/solvis-survey-analysis
```
