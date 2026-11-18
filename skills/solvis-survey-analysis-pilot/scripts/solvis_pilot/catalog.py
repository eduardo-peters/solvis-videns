"""Cadastros da credencial (pesquisas, questionários, unidades) com cache.

Lista de permissão: o motor só pede avaliações de uma pesquisa que a própria
credencial enxerga em GET /api/v1/surveys/:id (esse endpoint filtra pelo
cliente e devolve data: null para pesquisa de outro cliente).

A lista completa de pesquisas (GET /api/v1/surveys) traz o questionário inteiro
de cada uma e pode passar de 20 MB; ela só é baixada para `scope`, `surveys` e
busca por nome, e fica guardada como índice compacto.
"""

from __future__ import annotations

import datetime as dt
from typing import Any, Dict, List, Optional

from .api import ApiClient
from .errors import EngineError
from .semantics import Questionnaire
from .store import Store

INDEX_TTL_S = 6 * 3600
QUESTIONNAIRE_TTL_S = 15 * 60
UNITS_TTL_S = 6 * 3600


def _age_s(fetched_at: Optional[str]) -> float:
    if not fetched_at:
        return float("inf")
    then = dt.datetime.fromisoformat(fetched_at)
    return (dt.datetime.now(dt.timezone.utc) - then).total_seconds()


def _index_entry(raw: Dict[str, Any]) -> Dict[str, Any]:
    qn = raw.get("questionnaire") or {}
    qs = qn.get("questions") or []
    return {
        "id": int(raw["id"]),
        "name": raw.get("name"),
        "archived": bool(raw.get("archived")),
        "last_evaluation_date": raw.get("last_evaluation_date_cache"),
        "evaluation_count_all_time": raw.get("evaluation_count_cache"),
        "questionnaire_version": qn.get("version"),
        "questions": len(qs),
        "nps_questions": [q["id"] for q in qs if q.get("answer_type") == "NPS"],
    }


class Catalog:
    def __init__(self, store: Store, api: ApiClient) -> None:
        self.store = store
        self.api = api
        self._qn: Dict[int, Questionnaire] = {}

    # --------------------------------------------------------------- surveys
    def survey_index(self, refresh: bool = False) -> List[Dict[str, Any]]:
        index, fetched_at = self.store.get_catalog("survey_index")
        if refresh or index is None or _age_s(fetched_at) > INDEX_TTL_S:
            raws = self.api.list_surveys()
            index = [_index_entry(r) for r in raws]
            self.store.put_catalog("survey_index", index)
            for r in raws:  # aproveita a lista para não pedir o questionário de novo
                self.store.put_catalog(f"survey:{int(r['id'])}", r)
            self._qn.clear()
        return index

    def require_survey(self, survey_id: int, refresh: bool = False) -> Questionnaire:
        survey_id = int(survey_id)
        if survey_id in self._qn and not refresh:
            return self._qn[survey_id]
        raw, fetched_at = self.store.get_catalog(f"survey:{survey_id}")
        if refresh or raw is None or _age_s(fetched_at) > QUESTIONNAIRE_TTL_S:
            raw = self.api.get_survey(survey_id)  # filtrado pelo cliente da credencial
            if not raw or int(raw.get("id", -1)) != survey_id:
                raise EngineError(
                    "not_found",
                    f"A pesquisa {survey_id} não está disponível para esta credencial.",
                    hint="Use `surveys` ou `resolve --kind survey` para ver as pesquisas disponíveis. Não tente outros ids.",
                )
            self.store.put_catalog(f"survey:{survey_id}", raw)
        qn = Questionnaire.from_api(raw)
        self._qn[survey_id] = qn
        return qn

    def refresh_questionnaire(self, survey_id: int) -> Questionnaire:
        return self.require_survey(survey_id, refresh=True)

    # ----------------------------------------------------------------- units
    def units(self, refresh: bool = False) -> List[Dict[str, Any]]:
        payload, fetched_at = self.store.get_catalog("units")
        if refresh or payload is None or _age_s(fetched_at) > UNITS_TTL_S:
            payload = [_unit(u) for u in self.api.list_units()]
            self.store.put_catalog("units", payload)
        return payload

    def units_by_id(self) -> Dict[int, Dict[str, Any]]:
        return {u["id"]: u for u in self.units()}

    def property_names(self) -> Dict[int, Dict[str, Any]]:
        names: Dict[int, Dict[str, Any]] = {}
        for unit in self.units():
            for prop in unit["properties"]:
                entry = names.setdefault(prop["name_id"], {"name": prop["name"], "values": {}})
                entry["values"][prop["value_id"]] = prop["value"]
        return names


def _unit(raw: Dict[str, Any]) -> Dict[str, Any]:
    props = []
    for p in raw.get("surveyed_unit_properties") or []:
        name = p.get("surveyed_unit_property_name") or {}
        value = p.get("surveyed_unit_property_value") or {}
        if name.get("id") is None or value.get("id") is None:
            continue
        props.append(
            {"name_id": int(name["id"]), "name": name.get("name"), "value_id": int(value["id"]), "value": value.get("value")}
        )
    return {
        "id": int(raw["id"]),
        "name": raw.get("name"),
        "code": raw.get("client_specific_identifier"),
        "city": raw.get("city"),
        "state": raw.get("state"),
        "properties": props,
    }
