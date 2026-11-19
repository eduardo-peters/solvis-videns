"""Tool `metadata_catalog`. Catálogo de metadados semânticos ligado à skill e à saúde dos dados."""

import json  # noqa: F401
import re  # noqa: F401

from .. import ROOT, tool  # noqa: F401
from ..core.db import q  # noqa: F401
from ..core.errors import ToolError  # noqa: F401
from ..core.resolve import _fold  # noqa: F401
from ..core.skill import SKILL, _invariants, _metric_block, _metric_ids, _question_types  # noqa: F401

CATALOG = ROOT / "ops" / "metadata_catalog.json"


@tool("metadata_catalog", agents=["data_engineer", "analyst"], access="engineer",
      description="Catálogo de metadados semânticos: para cada campo (pesquisa, pergunta, unidade, tag), "
                  "para que a IA o usa, se existe (testing, engine, inferred, missing), fonte, dono, regra da skill "
                  "ligada e o resultado mais recente da checagem de saúde correspondente.",
      params={"level": ("string", "survey, question, unit ou tag (opcional)"),
              "status": ("string", "testing, engine, inferred ou missing (opcional)")},
      reads=["ops/metadata_catalog.json", "ops.data_health"], skill=["invariants.md", "docs/metadata-semantics.md"],
      example={"level": "unit"})
def metadata_catalog(args):
    cat = json.loads(CATALOG.read_text())
    health = {r["check_id"]: r for r in q(
        "SELECT check_id, argMax(level, ts) level, argMax(value, ts) value, argMax(detail, ts) detail, "
        "max(ts) checked_at FROM ops.data_health GROUP BY check_id")}
    inv = _invariants()
    fields = [f for f in cat["fields"] if (not args.get("level") or f["level"] == args["level"])
              and (not args.get("status") or f["status"] == args["status"])]
    for f in fields:
        if f.get("check") in health:
            f["health"] = {k: health[f["check"]][k] for k in ("level", "value", "detail", "checked_at")}
        if f.get("skill", "") and f["skill"] in inv:
            f["skill_rule"] = inv[f["skill"]]
    summary = {}
    for f in fields:
        summary[f["status"]] = summary.get(f["status"], 0) + 1
    return {"version": cat["version"], "summary": summary, "fields": fields}
