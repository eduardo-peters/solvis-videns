# Arquitetura

## Problema

Uma LLM que recebe respostas brutas de pesquisa e calcula métricas sozinha erra de formas previsíveis no domínio da Solvis. Todos os exemplos abaixo vêm do código atual:

| Armadilha | Por que a LLM erra | Regra correta |
|---|---|---|
| NPS de uma rede = média dos NPS das lojas | Parece razoável | Somar promotores, detratores e respostas de todas as lojas e recalcular |
| Média de escala com "Não se aplica" | A alternativa tem texto, não parece especial | Alternativa sem `value` sai da média e fica no denominador da distribuição |
| Percentuais de múltipla resposta | Espera que somem 100% | Denominador = avaliações distintas; a soma passa de 100% |
| Pergunta com `metric_kind = weighted_sum` | Trata como média | O valor é `round(100 × média)`, exibido em % |
| `started_at` com sufixo `Z` | Converte de UTC para o fuso local | O valor já é a hora local da unidade |
| Mesma pergunta em pesquisas diferentes | Junta pelo texto | Só agrega por `question_id` dentro de uma pesquisa |
| Ids de avaliação | Usa `id` como chave | `id` colide entre shards; a chave é `unique_id` |
| Avaliações não confiáveis | Não sabe que existem | A política de confiabilidade depende da pesquisa e da permissão |
| CSAT, top-box, taxa de resposta | Inventa a fórmula | O sistema não tem essas métricas nem os denominadores |

A API REST pública atual não resolve isso: `formatted_answers` não traz `question_id` nem `choice_id`, agrupa respostas por tipo com formatos diferentes, devolve `[]` com HTTP 200 quando falha, pagina por shard sem total e não aplica LGPD. Também há problemas de isolamento entre clientes que bloqueiam o uso (relatório interno, fora deste repositório).

## Decisão central

**A LLM nunca calcula métricas.** Ela escolhe a métrica e os recortes de um modelo semântico fechado, resolve nomes para ids, pede o resultado ao servidor e redige a resposta citando a evidência. O servidor aplica fórmula, escopo e políticas e devolve um envelope auditável. Ver [ADR-0001](adr/0001-metricas-calculadas-no-servidor.md).

Esse é o desenho que o próprio `survey_system` já adotou no Data Chat ("Fale com a Olvi"): catálogo fechado, bindings tipados, `ScopeGuard`, espelho ClickHouse, frescor declarado e auditoria por mensagem. A API Analytics reaproveita esse motor e tira dele as duas chamadas de LLM, que passam a ser responsabilidade da LLM do cliente.

## Camadas

```
┌────────────────────────────────────────────────────────────────────────────┐
│ LLM do cliente (Claude, ChatGPT, Gemini, Copilot, modelo próprio...)        │
│   lê SKILL.md → escolhe métrica/recortes → chama ferramentas → redige       │
└───────────────┬────────────────────────────────────────────────────────────┘
                │ Agent Skill (instruções + modelo semântico + playbooks)
┌───────────────▼────────────────────────────────────────────────────────────┐
│ Adaptador de ferramentas (sem regra de negócio)                              │
│   • servidor MCP solvis-analytics (stdio local → depois remoto)             │
│   • ou chamadas HTTP diretas descritas pelo OpenAPI                          │
└───────────────┬────────────────────────────────────────────────────────────┘
                │ HTTPS + OAuth (escopos analytics:*)
┌───────────────▼────────────────────────────────────────────────────────────┐
│ API Analytics v1 (survey_system, a construir)                                │
│   CredentialScope → Resolver → QueryPlanner (valida contra o modelo)         │
│   → templates do Catálogo → QueryCompiler → ScopeGuard → Warehouse           │
│   → Envelope (n, período, filtros, políticas, frescor, avisos, query_id)     │
│   → Auditoria (analytics_queries)                                            │
└───────────────┬────────────────────────────────────────────────────────────┘
                │ usuário somente leitura dedicado, cotas próprias
┌───────────────▼────────────────────────────────────────────────────────────┐
│ Espelho ClickHouse (PeerDB) dos shards MariaDB + tabelas principais          │
└────────────────────────────────────────────────────────────────────────────┘
```

### Responsabilidades

| Camada | Faz | Não faz |
|---|---|---|
| Skill | Interpretar a pergunta, escolher métrica e recortes do modelo, resolver ambiguidade com o usuário, redigir com citações, recusar o que não existe | Aritmética sobre métricas, inventar métricas, ler dados fora das ferramentas |
| Adaptador MCP/HTTP | Autenticar, repassar chamadas, validar o envelope contra o schema, devolver erros legíveis | Calcular, filtrar, guardar dados |
| API Analytics | Escopo por credencial, resolução de nomes, fórmulas, políticas de confiabilidade/LGPD, comparação entre períodos, totais agregados corretamente, avisos, auditoria | Narrar, interpretar |
| Espelho | Leitura analítica sem carga nos shards transacionais | Escrita |

## Fluxo de uma pergunta

Exemplo: "Por que o NPS da loja Centro caiu em outubro?"

1. `get_scope` → cliente, pesquisas e unidades visíveis, políticas, frescor do espelho.
2. `resolve_entities({kind: unit, text: "Centro"})` → 3 candidatos ("Centro", "Centro Norte", "Shopping Centro"). A skill pergunta qual, ou declara que usou o casamento exato.
3. `get_questionnaire(survey_id)` → pergunta NPS id 812, número 1.
4. Playbook "diagnóstico de queda" (o mesmo padrão de 4 consultas do Data Chat):
   - `query_metric(nps, period=month:2026-10, compare_with=previous_period, unit_ids=[…])`
   - `query_metric(nps, …, group_by=[unit])` para localizar a queda
   - `query_metric(theme_mentions, tone=negative, …)`
   - `search_comments(sentiment_author=detractor, …)`
5. A skill redige: confirma a queda com os dois NPS e os n, mostra se veio de menos promotores ou mais detratores (pelas porcentagens), cita os temas com contagem e um trecho curto, apresenta os temas como o que os respondentes disseram, e lista os `query_id`.

## Modelo semântico

O modelo semântico é o contrato entre as camadas. Ele descreve entidades, métricas, dimensões, combinações permitidas e regras invariantes.

- **Fonte da verdade:** o `survey_system`, porque é lá que as fórmulas rodam. O endpoint `GET /api/analytics/v1/model` serve a versão em uso.
- **Cópia na skill:** `skills/solvis-survey-analysis/references/*.yaml` é um snapshot versionado, para a LLM ler sem chamar a API. O CI deste repositório compara o snapshot com o endpoint e falha se divergirem. Ver [ADR-0002](adr/0002-modelo-semantico-versionado.md).
- **Versão:** semver. MAJOR quando uma métrica muda de significado, MINOR quando entram métricas ou dimensões, PATCH para texto. Todo envelope traz `model_version`.

## Segurança e privacidade

- Escopo por credencial equivalente ao `Session` do Data Chat: pesquisas com `:view_results`, unidades acessíveis, LGPD e confiabilidade. Ver [ADR-0004](adr/0004-autenticacao-e-escopo.md).
- A API nunca devolve IP, fingerprint ou `identifier` do respondente.
- Respostas de perguntas `lgpd_protected` só saem com o escopo `analytics:lgpd`.
- Comentários saem com mascaramento de e-mail, telefone, CPF e CNPJ, em campo de dados delimitado. A skill trata texto de respondente e contexto cadastrado pelo cliente como dado, nunca como instrução. Ver [ADR-0007](adr/0007-texto-livre-e-injecao.md).
- Toda chamada é auditada com credencial, parâmetros, SQL e linhas devolvidas.

## Distribuição

Ver [distribution.md](distribution.md) e [ADR-0003](adr/0003-distribuicao-skill-mcp-openapi.md).
