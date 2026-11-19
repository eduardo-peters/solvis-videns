"""Tool `data_coverage`. Dias com dados carregados."""

from ..core.errors import ToolError  # noqa: F401
from ..core.db import ch  # noqa: F401
from ..core.periods import resolve_dates  # noqa: F401
from ..core.resolve import (BASE, _fold, _question_scope, _round_nps, coverage, resolve_group_by,  # noqa: F401
                            resolve_question, resolve_survey)
from .. import tool
from ._params import PERIOD, QUESTION, SURVEY  # noqa: F401


@tool("data_coverage", agents=["analyst", "data_engineer"], access="client",
      description="Dias com dados carregados por pesquisa (primeiro dia, último dia, avaliações).",
      params={}, reads=["raw.evaluations", "raw.surveys"], skill=["INV-24"], example={},
      model_hint=('Dias com dados carregados por pesquisa.'))
def data_coverage(args):
    return ch("SELECT s.name AS survey, min(e.day) AS first_day, max(e.day) AS last_day, count() AS evaluations "
              "FROM raw.evaluations e LEFT JOIN raw.surveys s ON s.survey_id = e.survey_id GROUP BY s.name")
