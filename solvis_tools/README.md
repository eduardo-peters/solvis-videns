# solvis_tools: biblioteca de tools

Uma tool por arquivo. O mesmo registro alimenta:
- o agente local (`agent/`);
- o servidor MCP (`mcp/server.py --agent <perfil>`);
- a documentação gerada ([docs/tools.md](../docs/tools.md)).

```
solvis_tools/
├── __init__.py          registro: @tool, perfis (AGENTS), validação, call(), carga automática de tools/
├── core/                código compartilhado, sem tools
│   ├── errors.py        ToolError: erro de negócio que volta para o modelo corrigir
│   ├── db.py            ch(sql, params, access): ClickHouse por credencial (client, engineer)
│   ├── periods.py       presets → datas (yesterday, last_7_days, month:AAAA-MM...)
│   ├── resolve.py       nomes → ids (pesquisa, pergunta, propriedade), tipos de pergunta, cobertura
│   ├── skill.py         leitura da skill do piloto (invariantes, métricas, tipos de pergunta)
│   ├── skill_index.py   índice vetorial da skill (semantic.skill_chunks) e busca
│   └── charts.py        especificação dos 11 tipos de gráfico
└── tools/               uma tool por arquivo; o nome do arquivo é o nome da tool
    ├── _params.py       parâmetros comuns (survey, question, period)
    ├── nps.py  scale_mean.py  choice_share.py  evaluation_count.py  chart.py
    ├── list_surveys.py  list_questions.py  list_unit_properties.py  data_coverage.py
    └── metadata_catalog.py  describe_survey.py  unit_metadata.py  data_health.py  explain_metric.py
        skill_lookup.py  methodology_rules.py  quality_status.py  question_types.py
```

## Regras

- **Um arquivo, uma tool.** `tests/mcp` falha se o nome do arquivo e o da tool divergirem ou se sobrar arquivo sem tool.
- **Tool fina, núcleo compartilhado.** A tool valida, chama `core/` e monta a saída. Fórmulas ficam nas views do ClickHouse. Resolução de nomes, períodos e gráficos ficam em `core/`.
- **Registro completo.** `@tool` exige:
  - nome, perfis e credencial;
  - descrição;
  - parâmetros com descrição;
  - o que a tool lê;
  - regras da skill ligadas;
  - um exemplo.

  Opcional: `model_hint`, uma descrição curta para o modelo local pequeno.
- **Só SQL fixo**, com parâmetros tipados (`{nome:Tipo}`). Nada vindo do modelo vira SQL.
- **Dois modos de validação.**
  - MCP (`strict=True`): recusa argumento desconhecido e exige os obrigatórios.
  - Agente local (`strict=False`): ignora o que não existe e deixa a tool explicar o que falta.
  - Chaves que começam com `_` (ex.: `_user_q`, o pedido original) são contexto interno.

## Adicionar uma tool

1. Crie `solvis_tools/tools/<nome>.py` com uma função decorada por `@tool("<nome>", ...)`. Use uma tool parecida como modelo (`nps.py` para métrica, `data_health.py` para engenharia).
2. Se precisar de lógica compartilhada, ponha em `core/`.
3. Rode `python3 mcp/gen_docs.py` para atualizar `docs/tools.md`.
4. Rode `python3 ops/pipeline.py`. Os testes:
   - executam o exemplo;
   - conferem a documentação e as referências da skill;
   - conferem o arquivo e o perfil.
5. Para o agente local usar a tool, acrescente o nome em `AGENT_TOOLS` (`agent/agent.py`).

## Índice da skill

```bash
python3 -m solvis_tools.core.skill_index index                        # reindexar depois de mudar a skill
python3 -m solvis_tools.core.skill_index search "qual o nosso CSAT?"  # ver o que seria recuperado
```
