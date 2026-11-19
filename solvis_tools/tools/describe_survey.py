"""Tool `describe_survey`. Ficha de uma pesquisa antes de consultar."""

import json  # noqa: F401
import re  # noqa: F401

from .. import ROOT, tool  # noqa: F401
from ..core.db import q  # noqa: F401
from ..core.errors import ToolError  # noqa: F401
from ..core.resolve import _fold  # noqa: F401
from ..core.skill import SKILL, _invariants, _metric_block, _metric_ids, _question_types  # noqa: F401


@tool("describe_survey", agents=["data_engineer", "analyst"], access="engineer",
      description="Ficha de uma pesquisa para interpretar antes de consultar: perguntas com tipo, métricas que "
                  "existem para cada uma (pela skill), alternativas sem valor, textos repetidos, dias carregados "
                  "e avisos de metadado que faltam.",
      params={"survey": ("string", "Nome da pesquisa")}, required=["survey"],
      reads=["raw.surveys", "raw.questions", "raw.choices", "raw.evaluations (dia)"],
      skill=["question-types.md", "INV-04", "INV-05", "INV-10", "INV-16"], example={"survey": "Satisfação"})
def describe_survey(args):
    words = _fold(args["survey"])
    surveys = q("SELECT survey_id, name, archived, last_evaluation_date FROM raw.surveys")
    hits = [s for s in surveys if all(w in _fold(s["name"]) for w in words)]
    if not hits:
        raise ToolError(f"pesquisa '{args['survey']}' não encontrada")
    exact = [s for s in hits if _fold(s["name"]) == words]
    active = [s for s in hits if not int(s["archived"])]
    pick = exact or (active if len(active) == 1 else hits)
    if len(pick) > 1:
        raise ToolError("pesquisa ambígua: " + "; ".join(s["name"] for s in pick[:8]))
    s = pick[0]
    sid = int(s["survey_id"])
    qs = q("SELECT question_id, number, answer_type, text FROM raw.questions WHERE survey_id = {s:UInt32} "
           "ORDER BY number", {"s": sid})
    choices = q("SELECT question_id, count() n, countIf(value IS NULL) valueless, min(value) vmin, max(value) vmax "
                "FROM raw.choices WHERE survey_id = {s:UInt32} GROUP BY question_id", {"s": sid})
    ch_by = {int(c["question_id"]): c for c in choices}
    types = _question_types()
    seen = {}
    for x in qs:
        seen.setdefault((x["answer_type"], x["text"]), []).append(int(x["number"]))
    out_q = []
    for x in qs:
        c = ch_by.get(int(x["question_id"]), {})
        t = types.get(x["answer_type"], {})
        item = {"number": int(x["number"]), "type": x["answer_type"], "text": re.sub("<[^>]+>", " ", x["text"])[:120],
                "metrics_in_skill": t.get("metrics", []),
                "metrics_in_prototype": [m for m in t.get("metrics", [])
                                         if m in ("nps", "scale_mean", "choice_share")]}
        if c:
            item["choices"] = int(c["n"])
            if int(c["valueless"]):
                item["valueless_choices"] = int(c["valueless"])
            if c["vmax"] is not None:
                item["scale"] = [c["vmin"], c["vmax"]]
        twins = seen[(x["answer_type"], x["text"])]
        if len(twins) > 1:
            item["same_type_and_text_as"] = [n for n in twins if n != int(x["number"])]
        out_q.append(item)
    days = q("SELECT min(day) first, max(day) last, uniqExact(day) days, count() evaluations FROM raw.evaluations "
             "WHERE survey_id = {s:UInt32}", {"s": sid})[0]
    warnings = ["Finalidade, público e contexto por unidade não estão disponíveis (endpoint de contexto não existe).",
                "Textos e valores são do questionário atual, também para dados antigos (INV-10)."]
    if any("same_type_and_text_as" in i for i in out_q):
        warnings.append("Há perguntas de mesmo tipo e texto: respostas podem não ter pergunta definida (INV-16).")
    nps_q = [i for i in out_q if i["type"] == "NPS"]
    if len(nps_q) > 1:
        warnings.append(f"{len(nps_q)} perguntas NPS: pergunte qual antes de responder (INV-04).")
    return {"survey": s["name"], "archived": bool(int(s["archived"])),
            "last_evaluation_date": s["last_evaluation_date"],
            "loaded": days if int(days["evaluations"]) else "nenhum dia carregado no protótipo",
            "questions": out_q, "warnings": warnings}
