# Metadados semânticos

Data: 2026-11-19 · Status: em teste no protótipo local (`clickhouse/`, `agent/`). Fluxo: [fluxo.html](fluxo.html)

## Por que importam

A IA erra pouco na conta e muito na interpretação. As fórmulas (NPS, média, distribuição) cabem em poucas linhas de SQL e bateram com as telas de primeira no protótipo. Os erros vêm do que o dado não diz: a qual pergunta pertence uma resposta, se uma unidade é loja de verdade, se a regional de hoje era a mesma no ano passado, por que a pesquisa existe.

Metadado semântico é tudo o que a IA precisa saber **sobre** o dado para usá-lo corretamente. Ele não substitui o cálculo no servidor: a IA lê o metadado para escolher a consulta e ressalvar a resposta, e o ClickHouse calcula o número.

```
Pergunta do gestor
  └─ IA lê metadados (o que existe, o que significa, o que muda)  → escolhe a view e os parâmetros
       └─ View semântica no ClickHouse (fórmula fixa)              → número
            └─ IA responde citando n, período e avisos derivados dos metadados
```

## Princípios

1. **Id estável em tudo.** Texto é rótulo, não chave. Toda pergunta, alternativa, unidade e propriedade tem id.
2. **Vigência explícita.** O que muda com o tempo (propriedade de unidade, questionário, status da loja) tem `valido_de` e `valido_ate`. Sem isso, o histórico é relido com o cadastro de hoje.
3. **Dono e frescor.** Cada campo tem responsável (produto, CX, engenharia) e data da última atualização. Metadado velho é aviso no envelope.
4. **Números nunca vão para o banco vetorial.** Vetores servem para texto: contexto, glossário, comentários. Métricas saem só das views.
5. **O agente lê metadados, não respostas individuais.** Ver `clickhouse/03_access.sql`.

## Os quatro níveis

### 1. Pesquisa

| Campo | Para que a IA usa | Status no protótipo |
|---|---|---|
| `survey_id`, `name` | Resolver o nome dito pelo usuário | **Testando** (`raw.surveys`) |
| `archived`, `last_evaluation_date` | Não sugerir pesquisa encerrada; detectar falha silenciosa | **Testando** (`raw.surveys`) |
| `questionnaire_version` | Avisar que o histórico usa o cadastro atual | Disponível na API, fora do ClickHouse |
| Data Quality ligado | Avisar sobre avaliações não verificadas | **Testando** (`raw.evaluations.dq`, `reliable`) |
| Finalidade e público | Interpretar o resultado no contexto certo | Não disponível: falta o endpoint de contexto |
| Contexto por unidade ("loja em obra de mar a mai") | Explicar variações locais em análises com várias unidades | Não disponível: endpoint de contexto + esforço de CX |
| Sucessão (`substitui`, `substituida_por`) | Não somar nem comparar V1 e V2 sem saber | Não existe no produto |
| Pergunta NPS principal | Escolher a NPS certa quando há mais de uma | Inferido (única NPS da pesquisa) |

### 2. Pergunta e alternativa

| Campo | Para que a IA usa | Status no protótipo |
|---|---|---|
| `question_id`, `number`, `text`, `answer_type` | Resolver "pergunta 3" ou o texto; escolher a métrica | **Testando** (`raw.questions`) |
| `choice_id`, letra, texto, valor | Distribuição e média de escala; "Não se aplica" sem valor | **Testando** (`raw.choices`) |
| `question_id` em cada resposta | Atribuir a resposta à pergunta certa | **Testando**, mas reconstruído pelo motor do piloto (a API V1 não envia) |
| Código semântico (`atendimento_caixa`) | Comparar a mesma pergunta entre pesquisas e versões | Não existe |
| Tema | Agrupar perguntas para panorama | Não existe |
| Métrica recomendada | Não calcular média em pergunta de soma ponderada | Inferido pelo motor do piloto |
| Versão em que entrou e saiu | Comparação histórica honesta | Não existe |
| LGPD | Nunca expor texto pessoal | No motor do piloto; texto pessoal não vai ao ClickHouse |

### 3. Unidade

| Campo | Para que a IA usa | Status no protótipo |
|---|---|---|
| `unit_id`, nome, código, cidade, UF | Resolver a loja; recorte por UF | **Testando** (`raw.units`) |
| Propriedades (Regional, Formato, HUB…) | Recortes de gestão | **Testando** (`raw.unit_properties`), só valor atual |
| Vigência das propriedades | Loja que trocou de regional não leva o passado junto | Não existe |
| Tipo (loja, canal, fictícia) | Tirar "Pesquisa PF x PJ - 2026" (UF "WB") de rankings | Não existe |
| Status (ativa, fechada, em reforma) com datas | Explicar queda de volume | Não existe |
| Natureza da propriedade (recorte ou identificador) | Não usar "Número da Loja" (318 valores) como recorte | Não existe |

### 4. Tags e comentários

| Campo | Para que a IA usa | Status no protótipo |
|---|---|---|
| Tags aplicadas por avaliação | Temas mais citados | No motor do piloto, fora do ClickHouse |
| Hierarquia, definição e regra de rollup | Tag-pai incluir ou não subtags | Não existe (hoje não inclui) |
| Origem (pessoa ou Radar) | Pesar a confiança do tema | Não existe na API V1 |
| Comentários mascarados + embeddings | Busca de trechos e temas parecidos | Aguardando aprovação para carregar no ClickHouse local (a infraestrutura vetorial já existe: `semantic.skill_chunks`) |

## Checagens de saúde

Implementadas em `ops/pipeline.py` (etapa 1), gravadas em `ops.data_health`. Resultado atual em [data-ops.md](data-ops.md#d-nada-vazado-ou-usado-indevidamente); destaque: 26 unidades com UF "WB" (web e autoatendimento).

Cada checagem vira uma consulta no ClickHouse e uma nota de saúde por pesquisa, devolvida junto com o resultado.

| Checagem | Evidência no Assaí |
|---|---|
| Respostas sem pergunta atribuída | 183 de 466 respostas em perguntas de texto repetido (outro cliente, teste de produção) |
| Pares (tipo, texto) repetidos no questionário | Até 6 perguntas com o mesmo texto |
| Unidades com UF inválida ou sem propriedades obrigatórias | UF "WB" |
| Unidades que não são lojas | "Pesquisa PF x PJ - 2026" |
| Pesquisa ativa sem contexto preenchido | Todas (o endpoint não existe) |
| Questionário muito editado | "Açougue V1" na versão 38 |
| Queda brusca de volume por unidade | A medir com mais dias carregados |

## O que estamos testando agora

| Item | Onde |
|---|---|
| Views semânticas com paridade numérica às telas | `clickhouse/02_semantic.sql` (NPS total e por Regional idênticos ao piloto em 17/11) |
| Catálogo de pesquisas, perguntas, alternativas, unidades e propriedades | `clickhouse/01_schema.sql` |
| Isolamento por cliente e sem acesso a respostas individuais | `clickhouse/03_access.sql` |
| Regras da skill vetorizadas (41 trechos) e recuperadas por pergunta | `semantic.skill_chunks`, `solvis_tools/core/skill_index.py` |
| Modelo local (SLM) que escolhe a ferramenta e responde; nomes resolvidos em ids pelo código | `agent/` (Ollama + `qwen3:1.7b`, só em `127.0.0.1`); linha de base em [agent/README.md](../agent/README.md) |

## Próximas entradas

- A lista de metadados que a operação precisa (a levantar com CX e operação) entra como uma quinta tabela neste documento, com dono e status por campo.
- Cada metadado novo ganha uma checagem de saúde e, quando afetar a resposta, um aviso no envelope.
