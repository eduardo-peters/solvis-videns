# Treino do modelo local com a skill (LoRA)

Data: 2026-11-19 · Status: experimento local · Log: [`ops/logs/training.log`](../ops/logs/training.log) · Visão geral: [engineering.md](engineering.md)

## O que é treinado e o que não é

| Treinado (comportamento) | Não treinado (fica fora do modelo) |
|---|---|
| Escolher a tool e os argumentos certos a partir da pergunta | Números, nomes de loja, pesquisa ou cliente |
| Recusar o que não existe na Solvis (CSAT, taxa de resposta, benchmark, previsão) | Fórmulas (continuam nas views do ClickHouse) |
| Perguntar quando falta a pesquisa (INV-11) | Regras que mudam o resultado (continuam em código e guardrails) |
| Ler o resultado da tool e responder com número, n, período, pior e melhor e avisos | Qualquer dado de respondente |

O treino ajusta o **jeito de usar** as tools. Os guardrails, as views e o portão de qualidade continuam valendo para o modelo treinado igual ao base.

## Método

- **Base:** `mlx-community/Qwen3-1.7B-4bit` (o mesmo Qwen3 1.7B do Ollama, em formato MLX).
- **Técnica:** LoRA sobre o modelo quantizado (QLoRA) com `mlx_lm`, 8 camadas, taxa de aprendizado 1e-4, lote 1, sequência de até 2.048 tokens, *gradient checkpointing*. A perda conta só a resposta do assistente (`--mask-prompt`).
- **Saída:** um adapter de cerca de 10 MB em `~/.local/mlx-adapters/<nome>`, fora do repositório. Os pesos do modelo base não mudam.
- **Máquina:** M1 com 8 GB. Pico de memória 3,4 GB no teste, cerca de 0,15 iteração por segundo.

## Versões e arquivos

Cada versão tem dados e manifesto em `ops/training/<versão>/` (configuração, hash dos dados, resultado). O gerador é determinístico: `build_dataset.py --version v1` reproduz a v1 byte a byte (hash `7a69986bcd10`, o mesmo do log). Resumo em [agent/train/README.md](../agent/train/README.md).

## Dados de treino (`agent/train/build_dataset.py`)

Os exemplos saem das regras da skill e do contrato das tools, não dos dados do Assaí:

| Gerador | Conversas | Regra da skill |
|---|---|---|
| `nps_total`, `nps_group`, `ranking` | 40, 35, 35 | metrics.yaml#nps, playbooks 3 e 6, INV-23 (`min_n=30` em ranking) |
| `average_of_nps` | 20 | INV-02 (média do NPS das lojas = NPS do conjunto) |
| `scale`, `distribution` | 35, 30 | INV-05, playbook 7 |
| `volume` | 40 | INV-09, playbook 12 |
| `coverage_warning` | 12 | INV-24 |
| `tool_error_ambiguous`, `tool_error_type` | 15, 15 | INV-11, question-types.md |
| `ask_survey` | 15 | INV-11 |
| `refusal` | 60 | INV-25, INV-28, limitações (comparação, comentários, múltipla resposta) |

São 352 conversas. Cada turno do assistente vira um exemplo, o que dá 567 para treino e 62 para validação. Pesquisas, perguntas, unidades e números são fictícios ("Clima", "Loja Norte", "Bandeira A").

O gerador falha se:
- alguma pergunta dos conjuntos de avaliação (dev ou holdout) aparecer no treino;
- algum termo dos dados reais ("Assaí", "Satisfação", "Regional", ids reais) aparecer nos turnos gerados.

**Convenção de chamadas:** no treino, chamadas e resultados de tool são texto, por exemplo `nps(survey="Clima", period="yesterday")` seguido de `[resultado de nps] {...}`. O agente usa a mesma convenção quando roda pelo backend MLX (`AGENT_BACKEND=mlx`).

## Avaliação

| Conjunto | O que mede |
|---|---|
| **dev** (17 casos) | As perguntas usadas para ajustar o agente nas etapas anteriores |
| **holdout** (8 casos) | Perguntas novas, escritas antes do treino e nunca usadas para ajustar nada. É o que mede generalização |

`agent/train/evaluate.py` sobe o `mlx_lm.server` com o base e depois com o adapter e roda os dois conjuntos no mesmo backend, para a diferença medir só o efeito do treino. O veredito no log segue esta regra:
- **adotar:** o holdout melhora e o dev não piora;
- **não adotar:** algum dos dois piora;
- **empate:** fica o base, por ser mais simples.

Referência antes do treino (Ollama, tool calling nativo): dev 100%, holdout 75%. As falhas foram `h_taxa_resposta` (a resposta não usou o termo "taxa de resposta") e `h_pesquisa_volume` (agrupou por unidade em vez de pesquisa).

## Log (`ops/logs/training.log`)

Uma linha por evento, sem dado de respondente:

| Evento | Conteúdo |
|---|---|
| `train_start` | Configuração completa, tamanho e hash dos dados, gerador, onde fica o adapter |
| `train` | A cada 25 iterações: perda de treino, iterações/s, memória de pico |
| `val` | A cada 100 iterações: perda de validação |
| `train_done` | Tempo, perdas inicial e final, memória, tamanho do adapter, `weights_of_base_changed: false` |
| `eval`, `eval_failure` | Acerto por modelo e conjunto; para cada falha, o caso, as chamadas e a resposta |
| `compare` | Diferença de acerto (treinado − base) e o veredito |
| `interrupted`, `error`, `train_failed` | O que deu errado |

A saída completa do `mlx_lm` vai para `agent/results/` (fora do git).

## Rodar

```bash
python3 -m venv ~/.local/mlx-venv && ~/.local/mlx-venv/bin/pip install mlx-lm      # uma vez
~/.local/mlx-venv/bin/python agent/train/download_base.py                           # uma vez, ~1 GB
python3 agent/train/build_dataset.py --version v2                                   # dados em ops/training/v2/data
python3 agent/train/train.py --version v2                                           # adapter solvis-analyst-v2
AGENT_TODAY=2026-11-18 python3 agent/train/evaluate.py --adapter ~/.local/mlx-adapters/solvis-analyst-v1
```

Libere memória antes (descarregue os modelos do Ollama): com 8 GB, treino e Ollama juntos entram em swap.

## Resultados

Ver a seção "Execuções" no fim deste documento, atualizada a cada rodada.

## Execuções

### v1 · 2026-11-19 · `solvis-analyst-v1`

**Treino:** 200 iterações (0,35 época), 32,8 min, pico de 3,45 GB. A perda de validação caiu de 3,535 para 0,255 na iteração 100 e para 0,122 na 200. O adapter tem 29,9 MB e os pesos do base não mudaram.

**Avaliação** (mesmo backend MLX para os dois, chamadas em texto, 1 execução):

| Modelo | dev (17) | holdout (8) | Tempo por resposta |
|---|---|---|---|
| Qwen3 1.7B base | 59% (10) | 25% (2) | 17,5 s / 22,8 s |
| **solvis-analyst-v1** | 59% (10) | **62,5% (5)** | **4,3 s / 3,7 s** |
| Referência: base no Ollama, tool calling nativo | 100% | 75% | 2,6 s / 4,1 s |

**Veredito do log:** "adotar" contra o base no mesmo backend. O holdout subiu 37,5 pontos e o dev não piorou. O treinado também ficou 4 a 6 vezes mais rápido, porque responde direto em vez de gerar texto longo.

**Mas ainda não substitui o agente atual.** O base no Ollama com tool calling nativo continua melhor nos dois conjuntos (100% e 75%). Parte da diferença é o formato: no MLX, as chamadas são texto, e o base não foi feito para isso. O treino recuperou parte dessa perda, não toda.

**Onde o treinado ainda erra** (do log, `eval_failure`):

| Caso | Erro | Causa provável |
|---|---|---|
| `top_unit`, `top_unit_survey`, `h_pesquisa_volume` | Inventa uma pesquisa ("Lojas", "all", "Períodos") em vez de `group_by` | Poucos exemplos de volume sem pesquisa citada |
| `h_taxa_resposta` | Responde com volume em vez de recusar | O guardrail de capacidade não cobre "taxa de resposta" |
| `volume` | Chama `nps` e cita o n como avaliações | O guardrail de métrica não tem a intenção "volume" |
| `choice_share`, `h_primeira_vez` | Chama a tool certa, mas lê mal o resultado | Poucos exemplos de leitura de distribuição |
| `pilot_worst_unit` | Não chama tool | — |

**Incidentes da execução** (registrados como `eval_invalid` no log):
1. O ClickHouse caiu às 15:09 por falta de memória durante o treino, e o `mlx_lm.server` recusava o campo `model`. A primeira avaliação deu 0% para os dois modelos sem rodar nenhuma pergunta e foi descartada.
2. O servidor devolvia `<|im_end|>` no fim do texto, e o agente rejeitava todas as chamadas. A segunda avaliação, com 9 falhas idênticas nos dois modelos, também foi descartada. Isso foi corrigido em `agent/agent.py`.

**Próximos passos:**
1. Mais exemplos de volume sem pesquisa citada e de leitura de distribuição.
2. Fechar no código as duas brechas: "taxa de resposta" nas capacidades e "volume" na checagem de métrica.
3. Treinar a v2 e comparar também com o Ollama nativo.
4. Testar o adapter no Ollama, que tem tool calling nativo, convertendo para GGUF.

### v2 · dados prontos, treino pendente

- **Guardrails** (código, valem para qualquer modelo): volume na checagem de métrica; "taxa de resposta" nos avisos de capacidade. São 3 testes novos em `tests/agent` (`GapsFromTrainingV1`).
- **Dados:** os geradores `volume_no_survey` (50), `volume_not_nps` (30) e `distribution_read` (50) somam-se aos da v1. Total de 482 conversas, com 804 exemplos de treino e 85 de validação.
- **Cuidado:** o gerador só barra cópias exatas das perguntas de avaliação. Há paráfrases próximas das perguntas dev de volume ("Qual a loja que mais teve respostas ontem?"), então o ganho no dev pode vir de memorização. Para decidir, vale o holdout.
- **Para treinar:** `python3 agent/train/train.py --version v2`, depois `agent/train/evaluate.py`. Manifesto: `ops/training/v2/manifest.json`.
