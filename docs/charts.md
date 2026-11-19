# Gráficos

Data: 2026-11-19 · Código: `solvis_tools/core/charts.py` (especificação), `solvis_tools/tools/chart.py` (tool) e `agent/static/charts.js` (desenho em SVG, sem bibliotecas) · Tool: `chart` ([tools.md](tools.md#chart))

O modelo escolhe o tipo, a métrica e o recorte. O código calcula com as mesmas views e contagens das tools de métrica, com as mesmas fórmulas: NPS pelas contagens, média sem "Não se aplica", distribuição com N/A no denominador. A tela desenha. A legenda da resposta vem do próprio gráfico, gerada pelo código. O modelo não reescreve números.

## Tipos

| `kind` | O que mostra | Métricas | Recorte (`by`) | Exemplo de pedido |
|---|---|---|---|---|
| `bar` | Barras verticais, ordenadas | `evaluation_count`, `nps`, `scale_mean`, `choice_share` | unit, hour, channel, completion, survey (volume) ou propriedade | "gráfico do NPS por Regional" |
| `hbar` | Ranking horizontal com n por linha | idem | idem | "ranking das lojas por NPS" |
| `line` | Linha ao longo das horas | `evaluation_count`, `nps`, `scale_mean` | hour | "curva de respostas por hora" |
| `area` | Área ao longo das horas | idem | hour | "volume ao longo do dia" |
| `combo` | Barras de volume e linha de NPS, dois eixos | volume + `nps` | hour | "volume e NPS por hora" |
| `stacked` | 100% empilhado: detratores, neutros, promotores | `nps` | unit, propriedade, hour, channel | "composição do NPS por formato" |
| `donut` | Rosca | `choice_share` (com pergunta) ou volume por recorte | channel, completion, propriedade | "divisão por canal" |
| `histogram` | Notas de 0 a 10, coloridas por grupo NPS | `nps` | — | "distribuição das notas do NPS" |
| `scatter` | Unidades: respostas (x) × NPS (y), linha da mediana | `nps` | unit | "volume contra NPS das lojas" |
| `heatmap` | Unidades × hora | `evaluation_count` ou `nps` | unidades com mais avaliações × hora | "mapa de calor por hora" |
| `profile` | Média de cada pergunta de escala da pesquisa | `scale_mean` | pergunta | "nota de cada pergunta" |

## Regras de metodologia embutidas

| Regra | Onde |
|---|---|
| Amostra pequena (n < 30) aparece mais clara e listada nas notas | bar, line, stacked, combo |
| Rankings e dispersão de unidades excluem n < `min_n` (padrão 30) e dizem quantas ficaram de fora (INV-23) | bar e hbar por unidade, scatter |
| Mapa de calor de NPS deixa vazia a célula com poucas respostas | heatmap (`metric=nps`) |
| NPS de grupo é calculado pelas contagens, nunca como média das linhas (INV-02) | todos |
| Escalas de amplitude diferente não são comparadas (INV-05), com aviso | profile |
| Hora é a hora local de início da avaliação (INV-17) | line, area, combo, heatmap |
| "Não quero ver os números": rótulos, eixos e dicas sem valores; a legenda só cita nomes e horas | todos |

## Correções feitas pelo código

O modelo pequeno às vezes escolhe o tipo mais genérico. O código corrige:
- "média de cada pergunta" vira `profile`;
- "volume e NPS por hora" vira `combo`;
- o gráfico encerra a resposta, e o modelo não pede outras tools que apagariam o desenho;
- a checagem de métrica aceita o gráfico como resposta a pedidos de NPS ou de volume.

## Testes

Os testes de `tests/agent` (classes `Charts`, `ChartFlow`, `ChartKindFixes`, `Heatmap`) conferem:
- os 11 tipos geram especificação;
- o NPS das barras é igual ao da tool `nps`;
- o histograma soma o n do NPS (11.709);
- a composição soma 100%;
- o `profile` é igual ao `scale_mean`;
- o combo soma o volume do dia;
- o heatmap soma o volume das unidades;
- a legenda não vaza valores do gráfico;
- o ranking exclui a loja com n = 2.

O desenho foi validado pelo motor de JavaScript do macOS (30 gráficos, com e sem números, sem `NaN`) e por inspeção visual.

## Validação com o modelo (qwen3:1.7b, 2026-11-19)

Sete pedidos em português, ponta a ponta pela tela: mapa de calor sem números, NPS por Regional, composição por formato, notas 0 a 10, dispersão, média de cada pergunta e volume com NPS por hora. Todos geraram o gráfico certo, em 2 a 7 s cada.

## Limites

- Só um dia de dados carregado: sem gráficos por dia, semana ou mês (a tool recusa `line` fora de `by=hour`).
- O heatmap de NPS usa as unidades com mais avaliações de todas as pesquisas, não só da pesquisa pedida.
- A cor do heatmap de NPS é centrada em 50.
