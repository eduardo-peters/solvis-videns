# Engenharia de dados do agente: qualidade, metodologia e transparência

Data: 2026-11-19 · Status: em uso no protótipo local (`ops/`, `agent/audit.py`, `tests/agent/`, `tests/mcp/`). Visão de conjunto: [engineering.md](engineering.md). As consultas desta página também estão disponíveis como tools do perfil `data_engineer` ([tools.md](tools.md)): `data_health`, `methodology_rules`, `quality_status`, `metadata_catalog`, `unit_metadata`.

## Ideia

O agente é tratado como um pipeline de dados. Toda pergunta, chamada de ferramenta, atuação de guardrail e checagem de metodologia vira uma linha no banco `ops` do ClickHouse. Sobre esses dados rodam testes, avaliações e um portão de qualidade. Nada muda no comportamento sem passar pelo portão.

```
uso real (tela, terminal) ──┐
avaliação (eval_baseline) ──┼──> agent.ask() ──> _finish(): checagens de metodologia + registro
testes (roteiro, sem LLM) ──┘                                │
                                                             ▼
                          ops.interactions · ops.tool_calls · ops.guardrail_events
                          ops.methodology_checks · ops.eval_runs · ops.eval_results
                          ops.data_health · ops.eval_candidates
                                                             │
                                  ops/pipeline.py: saúde → guardrails → avaliação → metodologia → portão → revisão
```

## Os quatro objetivos

### (a) Os guardrails funcionam

`tests/agent/test_guardrails.py`: 21 testes (mais 13 da biblioteca de tools e do MCP em `tests/mcp/`, total de 34 no portão) que trocam o modelo por um roteiro e reproduzem as falhas reais já vistas. Rodam em menos de 1 segundo, sem LLM, e são a etapa 2 do pipeline.

| Grupo | O que prova | Falha real de origem |
|---|---|---|
| Fundamentação | Resposta sem ferramenta é bloqueada; a nova tentativa sugere a chamada | "Loja A" inventada e marcada como conferida |
| Números e datas | Número ou data sem origem nas ferramentas é bloqueado; números reais passam | NPS "12"; "1 a 31/10/2026" copiado da skill |
| Métrica | Volume no lugar de NPS é bloqueado; NPS em pergunta de escala vira erro; pergunta ambígua volta ao usuário | "Pior loja em NPS" respondida com volume |
| Avisos | Cobertura parcial, CSAT e comparação são avisados pelo código | 7 dias pedidos, 1 dia de dados, sem aviso |
| Leitura de chamadas | Chamada escrita como texto é executada; ferramenta inexistente (ex.: `execute_sql`) não executa | Modelo escreve `nome(arg=...)` no texto |
| Metodologia | Resposta errada falha INV-02 e INV-23; resposta certa passa em tudo | — |
| Isolamento | Agente não lê `raw.answers` nem `ops`, não escreve, só vê o próprio cliente | — |

Cada atuação de guardrail em uso real também fica em `ops.guardrail_events` (`retry`, `block`, `annotate`). Um guardrail que nunca atua ou que atua demais é sinal para olhar.

### (b) Os evals são respeitados

- `agent/eval_baseline.py` grava cada execução em `ops.eval_runs` e cada caso em `ops.eval_results`, com o hash do código, das views e da skill (`code_hash`). Um número de acerto sempre aponta para a versão exata que o produziu.
- O portão (`ops/gate.json`) reprova se:
  - algum teste de guardrail falhar;
  - o acerto da avaliação ficar abaixo de 95%;
  - o acerto cair mais de 5 pontos em relação à última execução aprovada com a mesma configuração;
  - a taxa de metodologia ficar abaixo de 95%;
  - uma checagem de dados crítica falhar (paridade, consistência, isolamento, índice da skill).
- O portão foi testado reprovando nesses quatro cenários e aprovando no correto.

### (c) O modelo se ajusta, com aprovação

Não há ajuste automático de prompt, código ou pesos. O ciclo é:

1. **Captura.** Em uso real (tela e terminal), resposta bloqueada ou que falha numa regra de metodologia vira candidato em `ops.eval_candidates`, com pergunta e resposta.
2. **Revisão.** `python3 ops/pipeline.py --review` lista os pendentes. Uma pessoa decide se é caso novo de avaliação, problema de dado ou ruído.
3. **Correção.** A mudança (regra em código, ferramenta, view, trecho da skill) entra junto com o caso novo.
4. **Portão.** A versão nova só vale se passar em todos os casos, os antigos e o novo.
5. **Fine-tuning,** quando vier, usa os casos aceitos como dados de treino e passa pelo mesmo portão.

Assim o sistema aprende com o uso sem que uma mudança piore um guardrail sem ninguém ver.

### (d) Nada vazado ou usado indevidamente

**Acesso (técnico):**

| Usuário | Pode | Não pode |
|---|---|---|
| `assai_agent` (o agente) | Ler views semânticas e dimensões do próprio cliente | Ler respostas individuais, ler `ops`, escrever, ver outro cliente |
| `agent_audit` (auditoria) | Inserir em `ops.*` | Ler qualquer coisa, inclusive a própria auditoria |
| `engineer_agent` (perfil `data_engineer` do MCP) | Ler metadados, regras vetorizadas e resultados agregados de qualidade | Ler respostas individuais e conversas, escrever |
| administrador local | Pipeline e carga | Nunca usado pelo agente |

**Método (metodologia da skill):** as regras invariantes da skill (`references/invariants.md`) que dá para checar sem LLM rodam em cada resposta (`agent/audit.py`) e ficam em `ops.methodology_checks`:

| Regra | Checagem |
|---|---|
| INV-01 nenhum número sem o motor | Resposta com métrica cita número vindo de ferramenta |
| INV-02 agregado vem do total | "NPS geral" com recorte = o total calculado, não uma linha nem média |
| INV-18 período declarado | Resposta diz o período |
| INV-23 n declarado; amostra pequena não elege pior/melhor | n citado; ranking com `min_n` ≥ 30 ou ressalva de amostra |
| INV-24 cobertura incompleta é dita | Aviso presente quando há dias sem dados |
| INV-25 o que não existe não existe | Recusa sem número inventado |
| INV-28 não reidentificar | Resposta sem e-mail, CPF ou telefone |
| INV-13 propriedade é do cadastro atual | Registrado; aviso exigido em período antigo (pendente) |

**Dados (metadados):** a etapa 1 do pipeline confere a saúde dos dados e grava em `ops.data_health`:

| Checagem | Nível | Achado no Assaí |
|---|---|---|
| Contagens pré-agregadas = respostas brutas | crítico | 114.045 = 114.045 |
| Paridade com o motor do piloto | crítico | NPS 79, n 11.709 |
| Agente sem acesso a respostas individuais | crítico | ok |
| Índice da skill = skill atual | crítico | ok (detecta skill alterada sem reindexar) |
| UF inválida | aviso | **26 unidades com UF "WB"** (web e autoatendimento), 618 avaliações só em 17/11. Um "NPS por UF" as trataria como estado |
| Unidade que não é loja | aviso | "Webspot" e unidades "- Web"; não há campo de tipo de unidade |
| Unidade sem propriedade | aviso | 5 unidades, fora de qualquer recorte por propriedade |
| Propriedade usada como identificador | aviso | "Número da Loja", 318 valores |
| Perguntas de mesmo tipo e texto | aviso | Pesquisa PF x PJ 2025 e 2026: 12 cada |
| Pesquisa sem contexto | aviso | todas (endpoint não existe) |
| Frescor | aviso | 1 dia carregado (17/11) |

## Transparência: o que acompanhar

Consultas prontas para o painel (rodar como administrador):

```sql
-- Desfecho das perguntas por semana
SELECT toStartOfWeek(ts) semana, outcome, count() FROM ops.interactions WHERE source = 'ui' GROUP BY 1, 2 ORDER BY 1;
-- Guardrails que mais atuam
SELECT guardrail, action, count() FROM ops.guardrail_events GROUP BY 1, 2 ORDER BY 3 DESC;
-- Regras de metodologia que mais falham
SELECT rule, count() n, round(100 * avg(passed), 1) pct_ok FROM ops.methodology_checks GROUP BY rule ORDER BY pct_ok;
-- Evolução do acerto por versão
SELECT ts, code_hash, context_on, pass_rate, gate FROM ops.eval_runs ORDER BY ts;
-- Saúde dos dados mais recente
SELECT check_id, argMax(level, ts) nivel, argMax(detail, ts) detalhe FROM ops.data_health GROUP BY check_id;
```

## Limites

- Checagens de metodologia são por regra e padrão de texto, não por entendimento; pegam erros conhecidos, não todos.
- As perguntas e respostas do uso real ficam em `ops.interactions`. Hoje sem retenção definida; em produção, definir prazo e acesso (LGPD).
- A avaliação continua sendo um conjunto de desenvolvimento até receber perguntas da operação.
