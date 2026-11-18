# Piloto: skill sobre a API pública (v0.2.0-pilot)

Data: 2026-11-17 · Status: pronto para teste interno; piloto com clientes depende das decisões no fim deste documento.

## Objetivo

Colocar a skill nas mãos de 2 a 3 clientes sem mudar nada no `survey_system`, para medir se há demanda antes de construir a API Analytics v1 ([PLAN.md](../PLAN.md)).

## O que muda em relação ao plano principal

| | Plano principal (v0.1.0-draft) | Piloto (v0.2.0-pilot) |
|---|---|---|
| Onde a métrica é calculada | API Analytics v1 no servidor (a construir) | Motor local da skill (`skills/solvis-survey-analysis-pilot/scripts/`), sobre a API pública V1 |
| Mudança no backend | Fases 0 e 1 | Nenhuma |
| A LLM calcula? | Não | Não. O motor determinístico calcula; a LLM escolhe a consulta e cita o envelope |
| Envelope | `MetricEnvelope` do OpenAPI | Mesma forma (query_id, rows, totals, delta, period, policies, warnings), mais `coverage` |
| Comentários e temas | Fase 3, com tom e base do Radar | Comentários mascarados e tags aplicadas; sem tom nem base do Radar |
| Distribuição | Skill + MCP + OpenAPI | Só Agent Skill com script (o host precisa executar Python e ter rede) |

A forma do envelope foi mantida de propósito: quando a API Analytics existir, o motor local vira um cliente fino dela e o `SKILL.md` muda pouco.

## API usada

Só leitura da API V1: `POST /api/v1/oauth/token` (emissão do token), `GET /api/v1/surveys`, `GET /api/v1/surveys/:id`, `GET /api/v1/surveyed_units` e `GET /api/v1/surveys/:id/evaluations_with_tags`.

A API V2 não é usada. Ela tem duas operações de escrita (`POST`/`PATCH /api/v2/sentiments`) e uma leitura (`GET /api/v2/answers/:answer_id/sentiments`) que exige um `answer_id` que nenhum endpoint da V1 devolve. Além disso, a tabela de sentimentos legada não é usada nas telas.

Os documentos publicados em `https://sistema.solvis.net.br/api-docs/` (V1 e V2) são idênticos aos de `swagger/` no repositório (conferido em 2026-11-17). O terceiro documento publicado (Data Quality, Comment Radar e Chat de dados) usa o JWT de usuário, não a credencial de API, e ficou fora.

## Camada semântica

Detalhes em [data-engineering.md](data-engineering.md). Resumo:

1. **Extração** por dia local, com janelas que cabem numa página e divisão automática quando a página volta cheia, quando a API devolve 400 ou quando devolve lista vazia suspeita.
2. **Normalização** de `formatted_answers` (só textos) para linhas por `question_id`/`choice_id`, usando o questionário atual. Perguntas de mesmo tipo e texto são separadas pela ordem das respostas quando só há uma possibilidade.
3. **Privacidade na ingestão**: `web_access_info` descartado; texto de perguntas LGPD e de tipos pessoais nunca guardado; comentários mascarados.
4. **Cálculo** com as fórmulas das telas (NPS em ponto flutuante como o Ruby, média sem "Não se aplica", soma ponderada, distribuição com N/A no denominador, múltipla resposta por avaliação, agregação por contagens).
5. **Envelope** com cobertura e avisos, registro local de cada consulta (`explain --query-id`).

## Validação feita

- 47 testes automatizados (`tests/pilot/`), com uma API falsa que reproduz o formato e as falhas da real.
- Teste contra a produção com a credencial de teste da Solvis (só leitura), em 2026-11-17: 4 pesquisas, 90 dias cada, 366 avaliações; todas as respostas mapeadas para id nas pesquisas sem texto repetido; métricas, recortes, comparações, tags e comentários funcionando. Achados que mudaram o motor estão em [data-engineering.md](data-engineering.md#achados-do-teste-em-produção).
- Um agente com contexto limpo, seguindo só o `SKILL.md`, respondeu 5 perguntas de gestor na API real (panorama, diagnóstico de queda, CSAT, temas, pergunta de texto repetido). As respostas citaram só números do motor, com fontes, e recusaram o que não existe. Os ajustes que ele apontou já estão nesta versão.

Ainda não validado: paridade numérica com as telas de resultados para um mesmo filtro. É o primeiro passo do teste interno (abaixo).

## Como medir demanda sem mudar o backend

O `Api::UsageLogging` (desde a v0.8.0) grava em cada requisição da API `api_credential_id`, `client_id` e `user_agent`. O motor envia `User-Agent: solvis-survey-analysis-pilot/<versão>`. Com isso, nos logs:

| Indicador | Como medir |
|---|---|
| Clientes ativos | `client_id` distintos com o User-Agent do piloto, por semana |
| Uso | Dias com uso por cliente; requisições de `evaluations_with_tags` por semana (cada pergunta nova de período gera algumas) |
| Retenção | Clientes que usaram na semana 1 e voltaram na semana 3 ou 4 |
| Qualidade | Respostas erradas reportadas pelos clientes, com o `query_id` (o cliente roda `explain --query-id` e manda o envelope) |

Junto disso, uma conversa curta com cada cliente nas semanas 2 e 4: que perguntas fizeram, o que não conseguiram, se usariam sem a Solvis acompanhando.

## Roteiro

| Etapa | O que fazer | Critério para seguir |
|---|---|---|
| 1. Teste interno (1 semana) | Comparar 10 a 20 números do motor com as telas de resultados (NPS, média, distribuição, volume; com e sem Data Quality; por unidade e por mês). Rodar os casos de [evals/cases-pilot.yaml](../../evals/cases-pilot.yaml) em 2 hosts (ex.: Claude Code e Codex) | Todos os números batem, ou a diferença está explicada e documentada |
| 2. Piloto (4 semanas) | 2 a 3 clientes, uma credencial nova para cada, instalação acompanhada ([onboarding.md](onboarding.md)) | — |
| 3. Decisão | Ler os indicadores acima | Ver "Sinais de demanda" |

### Sinais de demanda (proposta)

- Pelo menos 2 dos 3 clientes usam em 3 das 4 semanas.
- Cada cliente ativo faz perguntas em pelo menos 2 tipos de playbook (ex.: panorama e ranking).
- Nenhum número errado não explicado.

Se os sinais aparecerem, o próximo passo é a Fase 0 + Fase 1 do [plano principal](../PLAN.md); as limitações deste piloto (abaixo) viram a lista de prioridades da API Analytics.

## Limitações conhecidas

| Limitação | Efeito | Resolve na API Analytics |
|---|---|---|
| Sem métricas no servidor | O motor baixa avaliações; períodos longos de pesquisas grandes demoram no primeiro uso | Sim (`POST /query`) |
| Respostas sem `question_id` | Perguntas de mesmo texto às vezes não podem ser calculadas | Sim |
| Sem tom, base e resumo do Radar | Diagnóstico de queda só com tags e trechos | Sim (Fase 3) |
| Sem turno e sem regras do Data Quality | `hour_block` no lugar de turno; só o resultado da confiabilidade | Sim |
| Lista vazia em falha da API | Detectada e avisada, não recuperável | Sim |
| Credencial por cliente, sem restrição de pesquisa/unidade | Quem tem a credencial vê o cliente inteiro | Sim (Fase 0, escopos) |
| Host precisa executar Python com rede | Exclui assistentes só de chat (ChatGPT sem código, Copilot no Office) | Parcial (MCP remoto, Fase 4) |
| Cache local no computador do usuário | Dados do cliente ficam na máquina (sem dados pessoais diretos) | Sim |

## Decisões pendentes antes do piloto com clientes

1. **Segurança da API atual.** Os achados críticos do relatório interno (`~/work/_interno_skill_analise/ACHADOS-SEGURANCA-API.md`) continuam abertos e expõem dados independentemente da skill. O motor não os exercita (lista de permissão por `GET /api/v1/surveys/:id`, nenhum parâmetro além de datas e paginação, nenhuma escrita), mas o piloto aumenta o uso da API e dá aos clientes um motivo para olhá-la de perto. Pilotar com eles abertos é uma decisão de produto/segurança, não técnica.
2. **Política de confiabilidade padrão.** O piloto usa "todas as avaliações" (o que vê quem tem permissão de gerenciar confiabilidade) e avisa quando a pesquisa tem Data Quality. Alternativa: `reliable_only` por padrão em pesquisa com Data Quality, como vê quem não tem a permissão.
3. **Quais clientes e quais hosts.** O host precisa ler Agent Skills e executar Python com acesso de rede a `sistema.solvis.net.br`: agentes de código e de terminal (Claude Code, Codex, Cursor, VS Code com Copilot em modo agente, Gemini CLI, Kiro) servem. Assistentes de chat com execução de código em sandbox só servem se a sandbox liberar rede para esse domínio; confirmar com cada cliente antes de instalar.
4. **Nome da skill.** `solvis-survey-analysis-pilot` deixa claro que é piloto. Para continuar com o nome definitivo depois, troque a pasta e o campo `name` do `SKILL.md`.
