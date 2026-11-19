"""Tool `question_types`. Tipos de pergunta e métricas que existem para cada um."""

import json  # noqa: F401
import re  # noqa: F401

from .. import ROOT, tool  # noqa: F401
from ..core.db import q  # noqa: F401
from ..core.errors import ToolError  # noqa: F401
from ..core.resolve import _fold  # noqa: F401
from ..core.skill import SKILL, _invariants, _metric_block, _metric_ids, _question_types  # noqa: F401


@tool("question_types", agents=["data_engineer", "analyst"], access="engineer",
      description="Tipos de pergunta da Solvis pela skill: o que é cada tipo, quais métricas existem e observações.",
      params={"answer_type": ("string", "Tipo (ex.: Scale, Multiple Response). Vazio lista todos")},
      reads=["skills/.../references/question-types.md"], skill=["question-types.md"],
      example={"answer_type": "Multiple Response"})
def question_types(args):
    types = _question_types()
    t = args.get("answer_type")
    if t:
        if t not in types:
            raise ToolError(f"tipo '{t}' desconhecido. Tipos: {', '.join(types)}")
        return {t: types[t]}
    return types
