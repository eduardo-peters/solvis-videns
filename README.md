# solvis-survey-analysis-skill

Skill de análise de resultados de pesquisas da plataforma Solvis, para clientes usarem nas próprias LLMs.

> **Status:** duas versões convivem neste repositório.
> - **`solvis-survey-analysis-pilot` (v0.2.0-pilot), utilizável hoje.** Funciona sobre a API pública V1, sem mudança no backend: um motor local em Python calcula as métricas com as regras das telas. Ver [docs/pilot/README.md](docs/pilot/README.md).
> - **`solvis-survey-analysis` (v0.1.0-draft), plano principal.** Depende da API Analytics v1, que ainda não existe no `survey_system`. Nada dela deve ser entregue a cliente antes da Fase 2 do [plano](docs/PLAN.md).

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
| `docs/` | Plano, arquitetura, decisões (ADRs), requisitos para o backend, distribuição, perguntas em aberto; `docs/pilot/` para o piloto | Não |

Este repositório é privado. O que chega ao cliente é o artefato de release montado a partir de `skills/` (e, depois, o pacote do servidor MCP). Ver [docs/distribution.md](docs/distribution.md).

## Por onde começar

1. [docs/PLAN.md](docs/PLAN.md): fases, entregas e critérios de aceite.
2. [docs/architecture.md](docs/architecture.md): camadas e fluxo de uma pergunta.
3. [docs/backend-requirements.md](docs/backend-requirements.md): o que o `survey_system` precisa implementar e qual código existente reaproveitar.
4. [skills/solvis-survey-analysis/SKILL.md](skills/solvis-survey-analysis/SKILL.md): a skill em si.
5. [docs/open-questions.md](docs/open-questions.md): decisões que dependem de vocês.

## Fontes

O conteúdo semântico foi extraído do código do `survey_system` (commit `f594c4a6`, 2026-11-17), com citação `arquivo:linha` nos relatórios de pesquisa. Os relatórios completos ficam fora deste repositório, em `~/work/_interno_skill_analise/pesquisa/`, porque descrevem detalhes internos e falhas de segurança.

## Validação da skill

Validador de referência do padrão Agent Skills ([skills-ref](https://github.com/agentskills/agentskills/tree/main/skills-ref), uso de demonstração):

```bash
git clone --depth 1 https://github.com/agentskills/agentskills /tmp/agentskills
cd /tmp/agentskills/skills-ref && uv sync && . .venv/bin/activate
skills-ref validate ~/work/solvis-survey-analysis-skill/skills/solvis-survey-analysis
```
