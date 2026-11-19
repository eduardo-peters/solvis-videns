"""Tool `chart`. Gráficos (11 tipos); especificação em core/charts.py, desenho em agent/static/charts.js."""

from .. import tool
from ..core import charts
from ._params import PERIOD, QUESTION, SURVEY


@tool("chart", agents=["analyst"], access="client",
      description="Especificação de gráfico pronta para desenhar, com 11 tipos: bar, hbar (ranking), line e area "
                  "(por hora), combo (volume + NPS por hora), stacked (promotores/neutros/detratores), donut, "
                  "histogram (notas 0-10), scatter (unidades: respostas × NPS), heatmap (unidades × hora, volume ou "
                  "NPS) e profile (média de cada pergunta de escala). Valores das mesmas views das tools de métrica, "
                  "com amostra pequena marcada e notas de metodologia. Desenho de referência: agent/static/charts.js.",
      params={**SURVEY, **QUESTION, **PERIOD,
              "kind": ("string", "bar, hbar, line, area, combo, stacked, donut, histogram, scatter, heatmap, profile"),
              "metric": ("string", "evaluation_count, nps, scale_mean ou choice_share (padrão conforme o tipo)"),
              "by": ("string", "unit, hour, channel, completion, survey ou nome da propriedade (Regional...)"),
              "top": ("integer", "Máximo de itens (padrão 15; heatmap 10; máximo 40)"),
              "min_n": ("integer", "Amostra mínima por unidade em rankings, dispersão e heatmap de NPS (padrão 30)")},
      reads=["semantic.answer_counts_daily", "raw.evaluations (client_id, survey_id, day, unit_id, started_at, "
             "channel, completed)", "raw.units", "raw.unit_properties", "raw.choices", "raw.questions"],
      skill=["metrics.yaml#nps", "metrics.yaml#scale_mean", "metrics.yaml#choice_share", "metrics.yaml#evaluation_count",
             "INV-02", "INV-05", "INV-17", "INV-23", "playbooks.md#3", "playbooks.md#11"],
      example={"kind": "stacked", "by": "Regional", "survey": "Satisfação", "period": "yesterday"},
      model_hint=('Gráfico desenhado pela tela. kind: bar, hbar (ranking), line ou area (por hora), combo (volume +'
                  ' NPS por hora), stacked (promotores/neutros/detratores), donut, histogram (notas 0-10), scatter '
                  '(unidades: respostas × NPS), heatmap (unidades × hora), profile (média de cada pergunta de '
                  'escala). metric: evaluation_count, nps, scale_mean, choice_share. by: unit, hour, channel, '
                  'completion, survey ou nome da propriedade (Regional...). Use sempre que pedirem gráfico, '
                  'visualização, mapa de calor, curva, ranking visual.'))
def chart(args):
    return charts.build(args)
