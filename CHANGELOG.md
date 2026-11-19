# Changelog

## Não lançado
### Protótipo local: ClickHouse, agente, MCP, qualidade e treino (2026-11-18 a 2026-11-19)
Tudo local (`127.0.0.1`), na branch `slm-trainning`, com dados reais agregados do Assaí de 17/11/2026 (ver aviso no README). Visão geral em `docs/engineering.md`.
- **Camada semântica no ClickHouse** (`clickhouse/`): schema `raw.*`, contagens pré-agregadas por materialized view e métricas como views parametrizadas (`nps_by_unit`, `nps_by_unit_property`, `choice_share`, `scale_mean`, `evaluation_count`). Paridade com o motor do piloto (NPS 79, n 11.709) em 0,03 s, contra 1min42s do download. Row policy por cliente; o agente não lê respostas individuais.
- **Agente local** (`agent/`): `qwen3:1.7b` no Ollama com ferramentas fixas. Nomes, períodos e tipos de pergunta resolvidos em código. Tela de terminal em `127.0.0.1:8080`. Contexto da skill por busca vetorial (`semantic.skill_chunks`, `nomic-embed-text`).
- **Guardrails:** números e datas com origem nas ferramentas, fundamentação (resposta sem ferramenta é recusada), métrica pedida × métrica usada, tipo de pergunta, avisos de cobertura e de capacidade inseridos pelo código. Cada um nasceu de uma falha real (a "Loja A" inventada, o NPS "12", a data copiada da skill, volume no lugar de NPS).
- **Qualidade e auditoria** (`ops/`, `agent/audit.py`): banco `ops` com interações, chamadas, guardrails, checagens de metodologia (8 das 31 regras invariantes da skill), avaliações, saúde dos dados e candidatos a caso. `ops/pipeline.py` roda saúde dos dados, testes sem LLM, avaliação, metodologia, portão (`ops/gate.json`) e revisão. Ajuste só com aprovação humana. Achados nos metadados: 26 unidades com UF "WB", unidades que não são lojas, "Número da Loja" usado como propriedade.
- **MCP local e biblioteca de tools** (`mcp/`): servidor stdio por perfil de agente, `analyst` (13 tools) e `data_engineer` (11 tools de metadados, qualidade e skill). Credencial `engineer_agent`, sem respostas individuais e sem conversas. `docs/tools.md` é gerado do registro e um teste falha se divergir. Catálogo de metadados em `ops/metadata_catalog.json`.
- **Treino LoRA v1** (`agent/train/`, `docs/training.md`, log em `ops/logs/training.log`): 352 conversas fictícias geradas da skill, MLX sobre Qwen3 1.7B 4 bits, 33 min no M1 8 GB. No mesmo backend, o holdout subiu de 25% para 62,5% e o tempo caiu de cerca de 20 s para 4 s por resposta, mas ainda abaixo do agente no Ollama (75%). Não adotado. Duas avaliações descartadas e registradas como inválidas (ClickHouse fora do ar; token `<|im_end|>` não removido).
- **Brechas da v1 fechadas** (2026-11-19): o guardrail de métrica passa a reconhecer pedidos de volume ("quantas avaliações", "mais respostas") e bloqueia resposta tirada do n do NPS. "Taxa de resposta" entra nos avisos de capacidade e é recusada mesmo quando o modelo consulta o volume. São 3 testes novos, 37 no portão.
- **Dados de treino v2:** geradores novos `volume_no_survey` (volume por loja ou pesquisa com `group_by`, sem inventar pesquisa), `volume_not_nps` e `distribution_read` (leitura de cada alternativa com % e n). Total de 482 conversas, com 804 exemplos de treino e 85 de validação. O gerador barrou duas perguntas da avaliação copiadas por engano; elas foram trocadas. A v2 ainda não foi treinada.
- **Tools reorganizadas em módulo** (`solvis_tools/`, `solvis_tools/README.md`): uma tool por arquivo em `tools/` (18 arquivos) e núcleo compartilhado em `core/`:
  - `db`: ClickHouse por credencial;
  - `periods`: presets em datas;
  - `resolve`: nomes em ids e cobertura;
  - `skill`: leitura da skill;
  - `skill_index`: índice vetorial;
  - `charts`: especificação dos gráficos.

  O agente, o MCP e o gerador de documentação usam o mesmo registro. Validação em dois modos: estrita no MCP e tolerante no agente. Saem `mcp/solvis_tools/`, `agent/charts.py` e `agent/context.py`, e o `agent/agent.py` cai de 861 para 554 linhas, sem mudar o resultado (portão: 63/63). Novo teste: um arquivo por tool.
- **Contexto entre turnos da conversa** (falhas reais na tela):
  - **Turnos independentes:** cada pergunta nova vai ao modelo sozinha. O histórico inteiro fazia o modelo repetir a chamada anterior: depois de um heatmap, "gráfico do NPS por unidade, top 10" virava heatmap de novo.
  - **Continuações:** só continuações curtas ("e por Regional?") levam a pergunta anterior, e o recorte novo é aplicado pelo código.
  - **Pedido do usuário prevalece no gráfico:** o tipo, a métrica e o "top N" saem do pedido. "Top N superior de 10" devolvia 15 linhas.
  - **Erros de digitação:** "o nos atual" vira "o NPS atual".
  - **Pesquisa não citada:** quando só uma tem dados, o código a usa e declara. Isso também vale quando o modelo copia o marcador `"..."` do prompt (exemplos do prompt sem marcador).
  - **Testes:** 9 novos.
- **Biblioteca de gráficos** (hoje em `solvis_tools/core/charts.py`; desenho em `agent/static/charts.js`; `docs/charts.md`): a tool `chart` tem 11 tipos: barras, ranking horizontal, linha, área, combo volume+NPS, 100% empilhado, rosca, histograma 0-10, dispersão, mapa de calor (volume ou NPS) e perfil de notas por pergunta. A hora entra nas respostas e nas contagens pré-agregadas (`hour` em `raw.answers` e `semantic.answer_counts_daily`) e o agente passa a ler `started_at`, `channel` e `completed` das avaliações. A legenda é gerada pelo código. O pedido "não quero ver os números" esconde valores no desenho e na legenda. Amostra pequena, `min_n` em rankings e escalas de amplitude diferente seguem a skill. Há 17 testes novos (54 no portão) e 7 pedidos reais validados com o modelo. Também foi corrigida a tela, que caía com "Load failed" quando o servidor do agente estava parado.
- **Treino organizado por versão:** `ops/training/v1/` e `ops/training/v2/` trazem dados e manifesto (configuração, hash, resultado ou plano). A v1 se reproduz byte a byte pelo gerador. `train.py --version` lê a pasta da versão, e `agent/train/README.md` resume o processo. Removido `agent/enrich.py` (enriquecimento por Modelfile, nunca executado, substituído pelo treino).

### Motor do piloto
- Desempenho das consultas: o cache ganha o índice `ans_ev_q` (pesquisa, avaliação, pergunta), que cobre a junção de respostas, e roda `ANALYZE` depois de cada download (e ao abrir um cache antigo sem estatísticas). Sem isso o planejador do SQLite escolhia o índice por pergunta e uma `query` de pergunta em pesquisa grande (500 mil avaliações em 90 dias) levava horas; agora leva segundos.
- Download mais rápido: página de 10.000 avaliações (limite da API), janelas baixadas em paralelo (4 por rodada; `SOLVIS_SYNC_WORKERS` ajusta) e `sync --until-complete`, que repete rodadas de `--budget` segundos até o período terminar, sem o usuário precisar repetir o comando.
- Robustez: timeout de leitura (`socket.timeout`, que no Python 3.9 não é `TimeoutError`) e desconexões no meio da resposta passam a ser retentados em vez de derrubar o comando com traceback.
- Fluxo da pesquisa: o motor passa a ler `entry_rules` e `branching_rules` do questionário. `questionnaire` mostra `flow` (regras de entrada, perguntas puladas por ramificação, ramificações que saem da pergunta) e `shown_to: conditional`; `query` emite `conditional_question` quando a pergunta não aparece para todas as avaliações; o erro `ambiguous_question_text` traz `twin_flow` com o público de cada gêmea. Nova regra INV-31 e instruções no `SKILL.md`: perguntas de mesmo texto não são redundância e o n de uma pergunta condicional é de quem a viu. Quem viu cada pergunta é inferido: o motor refaz o caminho de cada avaliação (regras de entrada, ramificações por alternativa, grupo NPS e pulou/respondeu, como o navegador da pesquisa) e `query` traz `exposure` (avaliações no recorte, viram, responderam, proporções prontas, avaliações incertas), também por `--group-by`. Limites: pergunta inicial suposta na posição 1, perguntas escondidas por variação não aparecem na API, avaliação incompleta vale até a última resposta gravada, e a atribuição de respostas de texto repetido ainda não usa as regras.
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
