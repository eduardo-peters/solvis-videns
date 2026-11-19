# Agente local (protótipo): SLM + camada semântica no ClickHouse

Modelo pequeno rodando na máquina (Ollama, `qwen3:1.7b`) conversando com as views semânticas de `clickhouse/`. Nada sai de `127.0.0.1`.

```
navegador (127.0.0.1:8080, tela de terminal)
  └─ server.py
       └─ agent.py ── Ollama (127.0.0.1:11434, qwen3:1.7b): escolhe a ferramenta e escreve a resposta
            └─ ferramentas fixas ── ClickHouse (127.0.0.1:8123), usuário assai_agent (row policy, sem raw.answers)
```

## Divisão de trabalho

O modelo pequeno erra ids, datas e tipos. Por isso ele só faz o que é linguagem; o resto é código determinístico.

| Quem | Faz |
|---|---|
| Modelo | Escolhe a ferramenta; passa nomes como o usuário disse (`survey="Satisfação"`, `question="Atendimento"`, `group_by="Regional"`, `period="yesterday"`); escreve a resposta |
| `agent.py` | Resolve nomes em ids (pesquisas ativas primeiro; perguntas do tipo certo para a métrica primeiro; ambiguidade vira pergunta ao usuário); resolve períodos em datas; recusa métrica no tipo errado de pergunta; chama a view com parâmetros tipados |
| ClickHouse | Calcula (views de `clickhouse/02_semantic.sql`) e isola o cliente |
| Guardrail de números | Confere cada número da resposta contra os resultados das ferramentas. Número sem origem: o modelo tenta de novo uma vez; se repetir, a resposta é trocada por uma recusa |
| Guardrail de fundamentação | Resposta afirmativa sem nenhuma ferramenta chamada com sucesso é recusada (o modelo tem uma chance de chamar a ferramenta). Pega nomes inventados, que o guardrail de números não vê |
| Aviso de cobertura | Quando o período pedido tem dias sem dados carregados, o código anexa o aviso à resposta, sem depender do modelo |

## Rodar

Pré-requisitos: ClickHouse com os dados carregados ([clickhouse/README.md](../clickhouse/README.md)) e Ollama.

```bash
# Ollama (binário avulso, fora do repositório)
mkdir -p ~/.local/ollama && cd ~/.local/ollama
curl -fsSL -o ollama.tgz https://ollama.com/download/ollama-darwin.tgz && tar xzf ollama.tgz && rm ollama.tgz
OLLAMA_HOST=127.0.0.1:11434 nohup ./ollama serve > serve.log 2>&1 &
./ollama pull qwen3:1.7b

# Tela no navegador (AGENT_TODAY fixa o "hoje" para os dados do protótipo, que são de 17/11/2026)
AGENT_TODAY=2026-11-18 python3 agent/server.py --port 8080   # abra http://127.0.0.1:8080

# Uma pergunta pelo terminal
AGENT_TODAY=2026-11-18 python3 agent/agent.py "NPS da Satisfação ontem por Regional"

# Linha de base
AGENT_TODAY=2026-11-18 python3 agent/eval_baseline.py --runs 3 --out agent/results/baseline.json
```

Trocar de modelo: `AGENT_MODEL=qwen3:4b` (depois de `ollama pull qwen3:4b`). Raciocínio do Qwen3: `AGENT_THINK=1` (cerca de 5 vezes mais lento, sem ganho na linha de base).

## Ferramentas

| Ferramenta | View | Observação |
|---|---|---|
| `nps` | `nps_by_unit`, `nps_by_unit_property` | `group_by`: total, unidade ou propriedade pelo nome; devolve total, pior, melhor e linhas com n < 30 |
| `scale_mean` | `scale_mean` | Só pergunta Scale |
| `choice_share` | `choice_share` | Scale ou Multiple Choice |
| `evaluation_count` | `raw.evaluations` (só `client_id`, `survey_id`, `day`, `unit_id`) | Pesquisa opcional; `group_by` survey, unit ou propriedade; a loja do topo vem com a pesquisa de origem |
| `list_surveys`, `list_questions`, `list_unit_properties`, `data_coverage` | catálogo | Sem ids na saída, para o modelo não copiá-los errado |

## Linha de base (2026-11-18, M1 8 GB, `qwen3:1.7b`, 8 casos × 3 execuções)

| Versão | Acerto | Tempo médio | O que mudou |
|---|---|---|---|
| Modelo escolhe ids e datas | 25% (4/16) | 42 s | — (ids inventados, "ontem" passado como data, NPS em pergunta de escala, travamento de 300 s) |
| + checagem de tipo, limite de geração | 38% (6/16) | 6 s | Recusas certas; ids ainda inventados (copiava os do exemplo) |
| + nomes resolvidos no código, períodos por preset | **100% (24/24)** | **2,8 s** | O modelo só passa nomes |

| + guardrail de fundamentação, volume por loja/pesquisa, aviso de cobertura (11 casos) | **100% (33/33)** | 3,0 s | Caso real que falhou na tela: "qual loja teve mais respostas?" foi respondido com "Loja A", inventado, sem chamar ferramenta, e marcado como conferido |

Leitura: com 1,7B parâmetros, o modelo dá conta de linguagem e escolha de ferramenta, desde que não precise de ids, datas e tipos. Em nenhuma execução o guardrail de números precisou bloquear uma resposta.

**Cuidado com o 100%.** Os 8 casos foram usados para ajustar o agente; é um conjunto de desenvolvimento, não de teste. Antes de tirar conclusão, rodar um conjunto novo de perguntas escritas por quem não viu o código (operação, CX) e os casos de `evals/cases-pilot.yaml` que se aplicam.

## Limitações

- Dados de um dia só (17/11/2026, Assaí, pesquisa Satisfação com respostas; as outras pesquisas só têm catálogo).
- Sem comparação de períodos, filtros (canal, confiabilidade), comentários e busca vetorial.
- Respostas às vezes com português truncado ("A pior valor"); texto da pergunta cortado em 80 caracteres no escopo.
- Gráfico simples em SVG gerado pela tela a partir da tabela; o modelo não gera código.
- Conversas longas não foram testadas (a tela manda as últimas 12 mensagens).

## Contexto da skill por busca vetorial (`context.py`)

As regras da skill do piloto (`SKILL.md`, invariantes, playbooks, glossário, limitações, formato de resposta, tipos de pergunta) foram divididas em 41 trechos por seção e indexadas com `nomic-embed-text` (Ollama) na tabela `semantic.skill_chunks` do ClickHouse. A cada pergunta entram os trechos mais próximos, até 3.000 caracteres, com uma nota que traduz os comandos do motor de linha de comando para as ferramentas deste agente. `cli.md` e os YAML ficam fora. Só conteúdo da skill é vetorizado, nenhum dado de cliente.

```bash
python3 agent/context.py index                       # reindexar depois de mudar a skill
python3 agent/context.py search "qual o nosso CSAT?"  # ver o que seria recuperado
AGENT_CONTEXT=0 ...                                   # desliga o contexto (padrão: ligado)
```

### Resultado (17 casos × 2 execuções, 6 deles adaptados de `evals/cases-pilot.yaml`)

| Rodada | Sem contexto | Com contexto |
|---|---|---|
| Primeira, só com o contexto ligado | 71% | 82% |
| Contexto de 5.000 caracteres, `num_ctx` 12.288 | 76% | 76% (e a máquina entrou em swap) |
| Final | **100% (34/34), 4,5 s** | **100% (34/34), 7,7 s** |

O que levou ao 100% foi código, não contexto:
- `nps` calcula pior e melhor sobre todas as unidades (antes, só sobre as 50 primeiras) e aceita `min_n`; em ranking, devolve `worst_with_n_30`.
- Período tirado da pergunta quando o modelo esquece de passar ("ontem", "março de 2025").
- Pergunta tirada do pedido quando o modelo não passa `question`; "NPS da pergunta de Atendimento" é recusado como tipo errado.
- Avisos de capacidade inseridos pelo código: CSAT, comparação de períodos, comentários e múltipla resposta.
- Guardrails novos: métrica diferente da pedida (ex.: "pior loja em NPS" respondida com volume) e datas que não vieram das ferramentas (o modelo copiou "1 a 31/10/2026" de um trecho da skill).
- Quando o modelo responde sem consultar nada, a nova tentativa sugere a chamada concreta.

Leitura: com o `qwen3:1.7b`, o contexto da skill não melhorou o acerto e dobrou o tempo. Em rodadas intermediárias, ajudou nas recusas (CSAT, comparação) e atrapalhou nas consultas simples, porque o modelo copiou exemplos e números da fixture da skill. As regras que mudam o resultado funcionaram melhor como código. O contexto deve render mais num modelo maior (a máquina de 32B), onde vale repetir a comparação. A máquina de 8 GB ficou no limite: com contexto maior entrou em swap e algumas perguntas levaram de 6 a 10 minutos.

O 100% continua sendo de um conjunto de desenvolvimento: o agente foi ajustado olhando estas perguntas.
