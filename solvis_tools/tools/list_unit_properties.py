"""Tool `list_unit_properties`. Propriedades de unidade para recorte."""

from ..core.errors import ToolError  # noqa: F401
from ..core.db import ch  # noqa: F401
from ..core.periods import resolve_dates  # noqa: F401
from ..core.resolve import (BASE, _fold, _question_scope, _round_nps, coverage, resolve_group_by,  # noqa: F401
                            resolve_question, resolve_survey)
from .. import tool
from ._params import PERIOD, QUESTION, SURVEY  # noqa: F401


@tool("list_unit_properties", agents=["analyst"], access="client",
      description="Propriedades de unidade disponíveis para recorte (Regional, Formato...), com quantidade de valores.",
      params={}, reads=["raw.unit_properties"], skill=["INV-13", "playbooks.md#6"], example={},
      model_hint=('Lista propriedades de unidade (Regional, Formato...).'))
def list_unit_properties(args):
    return ch("SELECT any(name) AS name, uniqExact(value_id) AS values FROM raw.unit_properties "
              "GROUP BY name_id ORDER BY name")
