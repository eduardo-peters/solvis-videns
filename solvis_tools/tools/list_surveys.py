"""Tool `list_surveys`. Busca de pesquisas pelo nome."""

from ..core.errors import ToolError  # noqa: F401
from ..core.db import ch  # noqa: F401
from ..core.periods import resolve_dates  # noqa: F401
from ..core.resolve import (BASE, _fold, _question_scope, _round_nps, coverage, resolve_group_by,  # noqa: F401
                            resolve_question, resolve_survey)
from .. import tool
from ._params import PERIOD, QUESTION, SURVEY  # noqa: F401


@tool("list_surveys", agents=["analyst", "data_engineer"], access="client",
      description="Busca pesquisas pelo nome (ativas primeiro).",
      params={"search": ("string", "Parte do nome")}, reads=["raw.surveys"], skill=["INV-11"],
      example={"search": "Açougue"},
      model_hint=('Busca pesquisas pelo nome.'))
def list_surveys(args):
    return ch("SELECT name, archived, last_evaluation_date FROM raw.surveys "
              "WHERE positionCaseInsensitiveUTF8(name, {s:String}) > 0 "
              "ORDER BY archived, last_evaluation_date DESC LIMIT 20", {"s": str(args.get("search") or "")[:80]})
