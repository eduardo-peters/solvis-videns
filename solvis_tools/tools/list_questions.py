"""Tool `list_questions`. Perguntas de uma pesquisa."""

from ..core.errors import ToolError  # noqa: F401
from ..core.db import ch  # noqa: F401
from ..core.periods import resolve_dates  # noqa: F401
from ..core.resolve import (BASE, _fold, _question_scope, _round_nps, coverage, resolve_group_by,  # noqa: F401
                            resolve_question, resolve_survey)
from .. import tool
from ._params import PERIOD, QUESTION, SURVEY  # noqa: F401


@tool("list_questions", agents=["analyst"], access="client",
      description="Perguntas de uma pesquisa (número, tipo, texto).",
      params=SURVEY, required=["survey"], reads=["raw.questions"], skill=["question-types.md"],
      example={"survey": "Satisfação"},
      model_hint=('Lista as perguntas de uma pesquisa. survey = nome.'))
def list_questions(args):
    survey, name = resolve_survey(args)
    return {"survey": name, "questions": ch(
        "SELECT number, answer_type, text FROM raw.questions WHERE survey_id = {s:UInt32} ORDER BY number",
        {"s": survey})}
