"""Tool `nps`. NPS com total, pior e melhor, amostra pequena e cobertura."""

from ..core.errors import ToolError  # noqa: F401
from ..core.db import ch  # noqa: F401
from ..core.periods import resolve_dates  # noqa: F401
from ..core.resolve import (BASE, _fold, _question_scope, _round_nps, coverage, resolve_group_by,  # noqa: F401
                            resolve_question, resolve_survey)
from .. import tool
from ._params import PERIOD, QUESTION, SURVEY  # noqa: F401


@tool("nps", agents=["analyst"], access="client",
      description="NPS de uma pesquisa, com total calculado pelas contagens, pior e melhor linha, linhas com "
                  "amostra pequena e cobertura do período. Recusa pergunta que não é do tipo NPS.",
      params={**SURVEY, **QUESTION, **PERIOD,
              "group_by": ("string", "none, unit ou nome da propriedade de unidade (Regional, Formato da loja...)"),
              "min_n": ("integer", "Esconde linhas com menos respostas (use 30 em rankings)")},
      required=["survey"], reads=["semantic.nps_by_unit", "semantic.nps_by_unit_property", "raw.units"],
      skill=["metrics.yaml#nps", "INV-02", "INV-23", "playbooks.md#3", "playbooks.md#6"],
      example={"survey": "Satisfação", "group_by": "Regional", "period": "yesterday"},
      model_hint=('NPS de uma pesquisa. survey = nome da pesquisa; question = texto ou número da pergunta (opcional'
                  ' se a pesquisa tem uma só NPS); group_by = none, unit ou nome da propriedade (Regional, Formato '
                  'da loja, HUB...); min_n esconde linhas com menos respostas.'))
def nps(args):
    p, scope = _question_scope("nps", args)
    kind, prop = resolve_group_by(args.get("group_by"))
    scope["group_by"] = prop["name"] if prop else kind
    total = ch(f"SELECT sum(promoters) AS promoters, sum(passives) AS passives, sum(detractors) AS detractors, "
               f"sum(n) AS n FROM semantic.nps_by_unit({BASE})", p)[0]
    n = int(total["n"])
    if n == 0:
        return {**scope, "rows": [], "note": "sem avaliações no período"}
    total["nps"] = _round_nps(100.0 * (int(total["promoters"]) / n - int(total["detractors"]) / n))
    out = {**scope, "total": total,
           "total_note": "total = NPS geral do conjunto, calculado pelas contagens (não é média das linhas)"}
    if kind == "unit":  # todas as unidades; o corte para o modelo vem depois de achar pior e melhor
        out["rows"] = ch(f"SELECT u.name AS unit, v.nps AS nps, v.n AS n FROM semantic.nps_by_unit({BASE}) v "
                         f"LEFT JOIN raw.units u ON u.unit_id = v.unit_id ORDER BY nps, n DESC", p)
    elif kind == "property":
        out["rows"] = ch(f"SELECT value, nps, n FROM semantic.nps_by_unit_property({BASE}, property={{property:UInt32}}) "
                         f"ORDER BY nps, n DESC", {**p, "property": int(prop["property_id"])})
    else:
        out["rows"] = [total]
    min_n = int(args.get("min_n") or 0) if str(args.get("min_n") or "0").isdigit() else 0
    if min_n and kind != "none":
        hidden = [r for r in out["rows"] if int(r["n"]) < min_n]
        out["rows"] = [r for r in out["rows"] if int(r["n"]) >= min_n]
        out["hidden_rows_below_min_n"] = len(hidden)
    for r in out["rows"]:
        if int(r["n"]) < 30:
            r["small_sample"] = True
    if len(out["rows"]) > 1:
        out["worst"], out["best"] = out["rows"][0], out["rows"][-1]
        reliable = [r for r in out["rows"] if int(r["n"]) >= 30]
        if reliable and (out["worst"].get("small_sample") or out["best"].get("small_sample")):
            out["worst_with_n_30"], out["best_with_n_30"] = reliable[0], reliable[-1]
    small = [r for r in out["rows"] if r.get("small_sample")]
    if small:
        out["small_sample_rows"] = len(small)
    if len(out["rows"]) > 30:  # pior e melhor já foram calculados sobre todas as linhas
        out["rows_total"] = len(out["rows"])
        out["rows"] = out["rows"][:15] + out["rows"][-15:]
        out["rows_note"] = f"mostrando as 15 piores e as 15 melhores de {out['rows_total']}"
    return out
