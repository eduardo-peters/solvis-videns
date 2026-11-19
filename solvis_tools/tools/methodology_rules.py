"""Tool `methodology_rules`. Regras invariantes da skill e taxa de aprovação."""

import json  # noqa: F401
import re  # noqa: F401

from .. import ROOT, tool  # noqa: F401
from ..core.db import q  # noqa: F401
from ..core.errors import ToolError  # noqa: F401
from ..core.resolve import _fold  # noqa: F401
from ..core.skill import SKILL, _invariants, _metric_block, _metric_ids, _question_types  # noqa: F401


@tool("methodology_rules", agents=["data_engineer"], access="engineer",
      description="Regras invariantes da skill, quais são checadas automaticamente em cada resposta e a taxa de "
                  "aprovação de cada uma (avaliação e uso real, agregadas).",
      params={},
      reads=["skills/.../references/invariants.md", "ops.methodology_checks (regra e resultado)"],
      skill=["invariants.md"], example={})
def methodology_rules(args):
    inv = _invariants()
    rates = {r["rule"]: r for r in q(
        "SELECT rule, count() n, sum(passed) ok, max(ts) last FROM ops.methodology_checks GROUP BY rule")}
    checked = {}
    for rule, r in rates.items():
        code = rule.split()[0]
        checked.setdefault(code, []).append({"check": rule, "n": int(r["n"]), "passed": int(r["ok"]),
                                             "pass_rate": round(int(r["ok"]) / int(r["n"]), 3), "last": r["last"]})
    return {"rules": [{"id": k, "rule": v, "automated_checks": checked.get(k, [])} for k, v in inv.items()],
            "coverage": f"{len(checked)} de {len(inv)} regras com checagem automática"}
