"""Tool `explain_metric`. Definição de métrica pela skill (metrics.yaml)."""

import json  # noqa: F401
import re  # noqa: F401

from .. import ROOT, tool  # noqa: F401
from ..core.db import q  # noqa: F401
from ..core.errors import ToolError  # noqa: F401
from ..core.resolve import _fold  # noqa: F401
from ..core.skill import SKILL, _invariants, _metric_block, _metric_ids, _question_types  # noqa: F401


@tool("explain_metric", agents=["data_engineer", "analyst"], access="engineer",
      description="Definição de uma métrica pela skill (metrics.yaml): o que é, o que conta em n, armadilhas, "
                  "e se existe no protótipo. Também responde métricas que não existem (csat, response_rate...).",
      params={"metric": ("string", "Id da métrica (ex.: nps, scale_mean, csat). Vazio lista os ids")},
      reads=["skills/.../references/metrics.yaml"], skill=["metrics.yaml", "INV-25"], example={"metric": "csat"})
def explain_metric(args):
    ids = _metric_ids()
    m = (args.get("metric") or "").strip().lower()
    if not m:
        return {"metrics": ids}
    block = _metric_block(m)
    if not block:
        raise ToolError(f"métrica '{m}' não está no modelo da skill. Ids: {', '.join(ids)}")
    return {"metric": m, "in_prototype": m in ("nps", "scale_mean", "choice_share", "evaluation_count"),
            "definition_from_skill": block}
