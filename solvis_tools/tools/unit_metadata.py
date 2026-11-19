"""Tool `unit_metadata`. Unidades com problema de metadado e o impacto."""

import json  # noqa: F401
import re  # noqa: F401

from .. import ROOT, tool  # noqa: F401
from ..core.db import q  # noqa: F401
from ..core.errors import ToolError  # noqa: F401
from ..core.resolve import _fold  # noqa: F401
from ..core.skill import SKILL, _invariants, _metric_block, _metric_ids, _question_types  # noqa: F401

VALID_UF = set("AC AL AM AP BA CE DF ES GO MA MG MS MT PA PB PE PI PR RJ RN RO RR RS SC SE SP TO".split())
NON_STORE = re.compile(r"pesquisa|teste|webspot|\bweb\b|self.?check", re.I)


@tool("unit_metadata", agents=["data_engineer"], access="engineer",
      description="Unidades com problema de metadado: UF inválida, nome de canal ou unidade que não é loja, "
                  "sem nenhuma propriedade. Mostra quantas avaliações cada problema afeta no que está carregado.",
      params={"issue": ("string", "invalid_uf, not_store ou no_properties (opcional: todos)"),
              "limit": ("integer", "Máximo de unidades por problema (padrão 20)")},
      reads=["raw.units", "raw.unit_properties", "raw.evaluations (unit_id)"], skill=["INV-13", "INV-23"],
      example={"issue": "invalid_uf"})
def unit_metadata(args):
    limit = min(int(args.get("limit") or 20), 200)
    units = q("SELECT unit_id, name, state FROM raw.units")
    with_props = {int(r["unit_id"]) for r in q("SELECT DISTINCT unit_id FROM raw.unit_properties")}
    evals = {int(r["unit_id"]): int(r["n"]) for r in q("SELECT unit_id, count() n FROM raw.evaluations GROUP BY unit_id")}
    tests = {"invalid_uf": lambda u: u["state"] not in VALID_UF,
             "not_store": lambda u: bool(NON_STORE.search(u["name"])),
             "no_properties": lambda u: int(u["unit_id"]) not in with_props}
    pick = [args["issue"]] if args.get("issue") else list(tests)
    if any(p not in tests for p in pick):
        raise ToolError("issue aceita invalid_uf, not_store ou no_properties")
    out = {}
    for p in pick:
        bad = [u for u in units if tests[p](u)]
        out[p] = {"units": len(bad), "evaluations_loaded": sum(evals.get(int(u["unit_id"]), 0) for u in bad),
                  "examples": [{"unit": u["name"], "state": u["state"],
                                "evaluations_loaded": evals.get(int(u["unit_id"]), 0)} for u in bad[:limit]]}
    out["impact"] = ("Recortes por UF e rankings de lojas incluem estas unidades como se fossem lojas ou estados. "
                     "Falta no produto o campo 'tipo de unidade'.")
    return out
