"""Tool `data_health`. Checagens de saúde dos dados mais recentes."""

import json  # noqa: F401
import re  # noqa: F401

from .. import ROOT, tool  # noqa: F401
from ..core.db import q  # noqa: F401
from ..core.errors import ToolError  # noqa: F401
from ..core.resolve import _fold  # noqa: F401
from ..core.skill import SKILL, _invariants, _metric_block, _metric_ids, _question_types  # noqa: F401


@tool("data_health", agents=["data_engineer"], access="engineer",
      description="Resultado mais recente de cada checagem de saúde dos dados (paridade com o piloto, consistência, "
                  "isolamento, índice da skill, UF, tipo de unidade, perguntas repetidas, contexto, frescor). "
                  "Para rodar de novo: python3 ops/pipeline.py.",
      params={"level": ("string", "ok, warn ou fail (opcional)")},
      reads=["ops.data_health"], skill=["docs/data-ops.md"], example={"level": "warn"})
def data_health(args):
    rows = q("SELECT check_id, argMax(level, ts) level, argMax(value, ts) value, argMax(threshold, ts) threshold, "
             "argMax(detail, ts) detail, max(ts) checked_at FROM ops.data_health GROUP BY check_id ORDER BY check_id")
    if args.get("level"):
        rows = [r for r in rows if r["level"] == args["level"]]
    return {"checks": rows, "counts": {lv: sum(r["level"] == lv for r in rows) for lv in ("ok", "warn", "fail")}}
