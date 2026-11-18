"""Texto → candidatos com id. Nunca une candidatos: quem escolhe é a skill (ou o usuário)."""

from __future__ import annotations

import re
import unicodedata
from typing import Any, Dict, List, Optional, Tuple

from .catalog import Catalog
from .errors import EngineError
from .store import Store

RANK = {"exact": 0, "prefix": 1, "word": 2, "contains": 3}
_QNUM = re.compile(r"^(?:pergunta|questao|q|p|item|n)?\s*\.?\s*(\d+)$")


def norm(text: Optional[str]) -> str:
    if not text:
        return ""
    text = unicodedata.normalize("NFKD", text)
    text = "".join(ch for ch in text if not unicodedata.combining(ch)).lower()
    text = re.sub(r"[^\w]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def match(query: str, candidate: str) -> Optional[str]:
    q, c = norm(query), norm(candidate)
    if not q or not c:
        return None
    if q == c:
        return "exact"
    if c.startswith(q):
        return "prefix"
    if re.search(r"\b" + re.escape(q) + r"\b", c):
        return "word"
    if q in c:
        return "contains"
    return None


def _ranked(cands: List[Tuple[str, Dict[str, Any]]], limit: int = 15) -> List[Dict[str, Any]]:
    cands.sort(key=lambda t: (RANK[t[0]], str(t[1].get("label", "")).lower()))
    return [{**c, "match": m} for m, c in cands[:limit]]


def resolve(kind: str, text: str, catalog: Catalog, store: Store,
            survey_id: Optional[int] = None, question_id: Optional[int] = None) -> Dict[str, Any]:
    cands: List[Tuple[str, Dict[str, Any]]] = []
    if kind == "survey":
        for s in catalog.survey_index():
            m = match(text, s.get("name") or "")
            if m:
                cands.append((m, {"id": s["id"], "label": s.get("name"), "archived": s["archived"],
                                  "last_evaluation_date": s.get("last_evaluation_date")}))
    elif kind in ("question", "choice"):
        if survey_id is None:
            raise EngineError("invalid_argument", f"resolve --kind {kind} exige --survey.")
        qn = catalog.require_survey(survey_id)
        if kind == "question":
            num = _QNUM.match(norm(text))
            for q in qn.questions:
                if num and int(num.group(1)) == q.number:
                    m: Optional[str] = "exact"
                else:
                    m = match(text, q.label)
                if m:
                    cands.append((m, {"id": q.id, "number": q.number, "label": q.label, "answer_type": q.answer_type,
                                      **({"mapping": "ambiguous_text"} if q.id in qn.ambiguous_ids else {})}))
        else:
            if question_id is None or question_id not in qn.by_id:
                raise EngineError("invalid_argument", "resolve --kind choice exige --question <id> da pesquisa.")
            q = qn.by_id[question_id]
            for c in q.choices:
                m = "exact" if norm(text) == c.letter.lower() else match(text, c.label)
                if m:
                    cands.append((m, {"id": c.id, "letter": c.letter, "label": c.label,
                                      **({"value": float(c.value)} if c.value is not None else {})}))
    elif kind == "unit":
        for u in catalog.units():
            m = match(text, u.get("name") or "") or (match(text, u.get("code") or "") if u.get("code") else None)
            if m:
                cands.append((m, {"id": u["id"], "label": u.get("name"), "code": u.get("code"),
                                  "city": u.get("city"), "state": u.get("state")}))
    elif kind == "property":
        for nid, meta in catalog.property_names().items():
            m = match(text, meta["name"] or "")
            if m:
                cands.append((m, {"id": nid, "label": meta["name"], "values": len(meta["values"])}))
    elif kind == "property_value":
        for nid, meta in catalog.property_names().items():
            for vid, value in meta["values"].items():
                m = match(text, value or "")
                if m:
                    cands.append((m, {"id": vid, "label": value, "property_name_id": nid, "property_name": meta["name"]}))
    elif kind == "tag":
        sql = "SELECT tag_id, MAX(tag_name) FROM answer_tags" + (" WHERE survey_id = ?" if survey_id else "") + " GROUP BY tag_id"
        for tag_id, name in store.db.execute(sql, (survey_id,) if survey_id else ()).fetchall():
            m = match(text, name or "")
            if m:
                cands.append((m, {"id": tag_id, "label": name}))
    else:
        raise EngineError(
            "invalid_argument", f"Tipo desconhecido: {kind}.",
            hint="Use survey, question, choice, unit, property, property_value ou tag.",
        )
    out = _ranked(cands)
    exact = [c for c in out if c["match"] == "exact"]
    body: Dict[str, Any] = {"kind": kind, "text": text, "candidates": out, "exact_match": len(exact) == 1}
    if not out:
        body["note"] = "Nenhum candidato disponível para esta credencial."
        if kind == "tag":
            body["note"] += " Tags só aparecem depois que o período foi baixado (query ou sync)."
    elif len(exact) > 1:
        body["note"] = (f"{len(exact)} candidatos com casamento exato (mesmo nome): são entidades diferentes. "
                        "Pergunte ao usuário qual, ou trate cada um separadamente; nunca junte.")
    elif len(out) > 1 and not exact:
        body["note"] = "Mais de um candidato sem casamento exato: pergunte ao usuário ou declare qual usou."
    return body
