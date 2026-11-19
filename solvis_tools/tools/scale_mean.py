"""Tool `scale_mean`. Média de pergunta de escala, sem 'Não se aplica'."""

from ..core.errors import ToolError  # noqa: F401
from ..core.db import ch  # noqa: F401
from ..core.periods import resolve_dates  # noqa: F401
from ..core.resolve import (BASE, _fold, _question_scope, _round_nps, coverage, resolve_group_by,  # noqa: F401
                            resolve_question, resolve_survey)
from .. import tool
from ._params import PERIOD, QUESTION, SURVEY  # noqa: F401


@tool("scale_mean", agents=["analyst"], access="client",
      description="Média de uma pergunta de escala, sem as alternativas sem valor ('Não se aplica').",
      params={**SURVEY, **QUESTION, **PERIOD}, required=["survey", "question"],
      reads=["semantic.scale_mean"], skill=["metrics.yaml#scale_mean", "INV-05", "INV-06"],
      example={"survey": "Satisfação", "question": "Atendimento", "period": "yesterday"},
      model_hint=('Média de uma pergunta de escala (ex.: estrelas). survey = nome; question = texto ou número da '
                  'pergunta.'))
def scale_mean(args):
    p, scope = _question_scope("scale_mean", args)
    r = ch(f"SELECT n, mean_raw FROM semantic.scale_mean({BASE})", p)[0]
    if int(r["n"]) == 0:
        return {**scope, "rows": [], "note": "sem avaliações no período"}
    return {**scope, "rows": [{"mean": round(float(r["mean_raw"]), 2), "n": r["n"]}]}
