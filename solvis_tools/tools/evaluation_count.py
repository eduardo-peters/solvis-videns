"""Tool `evaluation_count`. Volume de avaliações, total ou por recorte."""

from ..core.errors import ToolError  # noqa: F401
from ..core.db import ch  # noqa: F401
from ..core.periods import resolve_dates  # noqa: F401
from ..core.resolve import (BASE, _fold, _question_scope, _round_nps, coverage, resolve_group_by,  # noqa: F401
                            resolve_question, resolve_survey)
from .. import tool
from ._params import PERIOD, QUESTION, SURVEY  # noqa: F401


@tool("evaluation_count", agents=["analyst"], access="client",
      description="Quantidade de avaliações, no total ou por pesquisa, unidade ou propriedade. "
                  "A unidade do topo vem com a pesquisa de origem.",
      params={**SURVEY, **PERIOD, "group_by": ("string", "none, survey, unit ou nome da propriedade")},
      reads=["raw.evaluations (client_id, survey_id, day, unit_id)"],
      skill=["metrics.yaml#evaluation_count", "INV-09", "playbooks.md#12"],
      example={"group_by": "unit", "period": "yesterday"},
      model_hint=('Quantidade de avaliações (respostas). survey = nome (opcional: sem ele, todas as pesquisas); '
                  "group_by = none, survey, unit ou propriedade. Use para 'qual loja/pesquisa teve mais respostas'."))
def evaluation_count(args):
    """Volume. Sem survey: todas as pesquisas. group_by: none, survey, unit ou propriedade."""
    start, end = resolve_dates(args)
    p = {"a": start, "b": end}
    where = "e.day BETWEEN {a:Date} AND {b:Date}"
    sname = None
    if args.get("survey"):
        p["s"], sname = resolve_survey(args)
        where += " AND e.survey_id = {s:UInt32}"
    gb = str(args.get("group_by") or "none")
    out = {"survey_filter": sname or "nenhum (todas as pesquisas)", "period": {"start": start, "end": end},
           "coverage": coverage(start, end)}
    total = ch(f"SELECT count() AS evaluations FROM raw.evaluations AS e WHERE {where}", p)
    out["total"] = total[0]
    if _fold(gb) and _fold(gb)[0] in ("survey", "pesquisa", "pesquisas"):
        out["group_by"] = "pesquisa"
        out["rows"] = ch(f"SELECT s.name AS survey, count() AS evaluations FROM raw.evaluations AS e "
                         f"LEFT JOIN raw.surveys AS s ON s.survey_id = e.survey_id WHERE {where} "
                         f"GROUP BY s.name ORDER BY evaluations DESC LIMIT 20", p)
        return out
    kind, prop = resolve_group_by(gb)
    out["group_by"] = prop["name"] if prop else kind
    if kind == "unit":
        out["rows"] = ch(f"SELECT u.name AS unit, count() AS evaluations FROM raw.evaluations AS e "
                         f"LEFT JOIN raw.units AS u ON u.unit_id = e.unit_id WHERE {where} "
                         f"GROUP BY u.name ORDER BY evaluations DESC LIMIT 20", p)
        out["rows_note"] = "só as 20 com mais avaliações; a lista não mostra a de menos avaliações"
    elif kind == "property":
        p["prop"] = int(prop["property_id"])
        out["rows"] = ch(f"SELECT pr.value AS value, count() AS evaluations FROM raw.evaluations AS e "
                         f"INNER JOIN raw.unit_properties AS pr ON pr.unit_id = e.unit_id AND pr.name_id = {{prop:UInt32}} "
                         f"WHERE {where} GROUP BY pr.value ORDER BY evaluations DESC", p)
    else:
        out["rows"] = total
    if len(out["rows"]) > 1:
        out["most"] = dict(out["rows"][0])
        out["rows"] = out["rows"][:10]
        if kind == "unit":  # de qual pesquisa vieram as respostas da loja do topo
            out["most"]["surveys"] = ch(
                f"SELECT s.name AS survey, count() AS evaluations FROM raw.evaluations AS e "
                f"LEFT JOIN raw.surveys AS s ON s.survey_id = e.survey_id "
                f"LEFT JOIN raw.units AS u ON u.unit_id = e.unit_id WHERE {where} AND u.name = {{u:String}} "
                f"GROUP BY s.name ORDER BY evaluations DESC", {**p, "u": out["most"]["unit"]})
    return out
