"""Tools do perfil analyst: métricas e catálogo para responder perguntas de negócio.

Reaproveitam as funções de agent/agent.py (uma implementação só): o modelo passa nomes,
o código resolve ids, períodos e tipos, e as views semânticas calculam.
"""
import sys

from . import ROOT, ToolError, tool

sys.path.insert(0, str(ROOT / "agent"))
import agent as _agent  # noqa: E402

PERIOD = {"period": ("string", "yesterday, today, last_7_days, this_month, last_month ou month:AAAA-MM"),
          "start": ("string", "Data inicial AAAA-MM-DD (em vez de period)"),
          "end": ("string", "Data final AAAA-MM-DD (em vez de period)")}
SURVEY = {"survey": ("string", "Nome da pesquisa como o usuário disse (ex.: 'Satisfação')")}
QUESTION = {"question": ("string", "Texto ou número da pergunta (ex.: 'Atendimento', '2')")}


def _run(fn, args):
    try:
        return fn(dict(args))
    except _agent.ToolError as e:
        raise ToolError(str(e))


@tool("nps", agents=["analyst"], access="client",
      description="NPS de uma pesquisa, com total calculado pelas contagens, pior e melhor linha, linhas com "
                  "amostra pequena e cobertura do período. Recusa pergunta que não é do tipo NPS.",
      params={**SURVEY, **QUESTION, **PERIOD,
              "group_by": ("string", "none, unit ou nome da propriedade de unidade (Regional, Formato da loja...)"),
              "min_n": ("integer", "Esconde linhas com menos respostas (use 30 em rankings)")},
      required=["survey"], reads=["semantic.nps_by_unit", "semantic.nps_by_unit_property", "raw.units"],
      skill=["metrics.yaml#nps", "INV-02", "INV-23", "playbooks.md#3", "playbooks.md#6"],
      example={"survey": "Satisfação", "group_by": "Regional", "period": "yesterday"})
def nps(args):
    return _run(_agent.t_nps, args)


@tool("scale_mean", agents=["analyst"], access="client",
      description="Média de uma pergunta de escala, sem as alternativas sem valor ('Não se aplica').",
      params={**SURVEY, **QUESTION, **PERIOD}, required=["survey", "question"],
      reads=["semantic.scale_mean"], skill=["metrics.yaml#scale_mean", "INV-05", "INV-06"],
      example={"survey": "Satisfação", "question": "Atendimento", "period": "yesterday"})
def scale_mean(args):
    return _run(_agent.t_scale_mean, args)


@tool("choice_share", agents=["analyst"], access="client",
      description="Distribuição (%) das alternativas de uma pergunta de escala ou escolha única. "
                  "'Não se aplica' entra no denominador.",
      params={**SURVEY, **QUESTION, **PERIOD}, required=["survey", "question"],
      reads=["semantic.choice_share"], skill=["metrics.yaml#choice_share", "playbooks.md#7"],
      example={"survey": "Satisfação", "question": "Atendimento", "period": "yesterday"})
def choice_share(args):
    return _run(_agent.t_choice_share, args)


@tool("evaluation_count", agents=["analyst"], access="client",
      description="Quantidade de avaliações, no total ou por pesquisa, unidade ou propriedade. "
                  "A unidade do topo vem com a pesquisa de origem.",
      params={**SURVEY, **PERIOD, "group_by": ("string", "none, survey, unit ou nome da propriedade")},
      reads=["raw.evaluations (client_id, survey_id, day, unit_id)"],
      skill=["metrics.yaml#evaluation_count", "INV-09", "playbooks.md#12"],
      example={"group_by": "unit", "period": "yesterday"})
def evaluation_count(args):
    return _run(_agent.t_evaluation_count, args)


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
      example={"kind": "stacked", "by": "Regional", "survey": "Satisfação", "period": "yesterday"})
def chart(args):
    return _run(_agent.t_chart, args)


@tool("list_surveys", agents=["analyst", "data_engineer"], access="client",
      description="Busca pesquisas pelo nome (ativas primeiro).",
      params={"search": ("string", "Parte do nome")}, reads=["raw.surveys"], skill=["INV-11"],
      example={"search": "Açougue"})
def list_surveys(args):
    return _run(_agent.t_list_surveys, args)


@tool("list_questions", agents=["analyst"], access="client",
      description="Perguntas de uma pesquisa (número, tipo, texto).",
      params=SURVEY, required=["survey"], reads=["raw.questions"], skill=["question-types.md"],
      example={"survey": "Satisfação"})
def list_questions(args):
    return _run(_agent.t_list_questions, args)


@tool("list_unit_properties", agents=["analyst"], access="client",
      description="Propriedades de unidade disponíveis para recorte (Regional, Formato...), com quantidade de valores.",
      params={}, reads=["raw.unit_properties"], skill=["INV-13", "playbooks.md#6"], example={})
def list_unit_properties(args):
    return _run(_agent.t_list_unit_properties, args)


@tool("data_coverage", agents=["analyst", "data_engineer"], access="client",
      description="Dias com dados carregados por pesquisa (primeiro dia, último dia, avaliações).",
      params={}, reads=["raw.evaluations", "raw.surveys"], skill=["INV-24"], example={})
def data_coverage(args):
    return _run(_agent.t_data_coverage, args)
