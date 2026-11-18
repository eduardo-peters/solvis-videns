"""API V1 falsa, fiel ao formato e às falhas da real (survey_system@f594c4a6).

Reproduz:
- OAuth password/refresh em POST /api/v1/oauth/token;
- listas paginadas (will_paginate, per_page padrão 100);
- evaluations_with_tags com search_date_scope=received_at (filtra created_at, mas os shards
  seguem o started_at da avaliação), SEM filtro de cliente (como o código real), paginação
  por shard mensal concatenada, end_date comparado no segundo;
- formatted_answers só com textos (HandlerAnswersService), Multiple Response
  como objeto, tipos "default" como lista de listas, choice_value como string;
- HTTP 200 com lista vazia quando a montagem falha (avaliação "poison");
- HTTP 400 quando uma unidade da janela não existe (avaliação "bad_unit");
- chave reliable só em pesquisa com Data Quality; web_access_info presente.
"""

from __future__ import annotations

import datetime as dt
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Dict, List, Optional
from urllib.parse import parse_qs, urlparse

NPS_LABEL = {range(0, 7): "Detrator", range(7, 9): "Neutro", range(9, 11): "Promotor"}


def nps_text(score):
    for r, label in NPS_LABEL.items():
        if score in r:
            return label
    return None


class FakeSolvis:
    def __init__(self) -> None:
        self.username, self.password = "rede-exemplo", "segredo"
        self.client_id = 1
        self.surveys: Dict[int, Dict[str, Any]] = {}
        self.units: Dict[int, Dict[str, Any]] = {}
        self.tags: Dict[int, str] = {}
        self.evaluations: List[Dict[str, Any]] = []
        self.requests: List[Dict[str, Any]] = []
        self.token_posts = 0
        self._next_id: Dict[str, int] = {}
        self._tokens = set()
        self.server: Optional[ThreadingHTTPServer] = None

    # --------------------------------------------------------------- cadastro
    def add_survey(self, sid, name, questions, client_id=1, dq=False, archived=False, questionnaire_version=1):
        self.surveys[sid] = {"id": sid, "name": name, "client_id": client_id, "dq": dq, "archived": archived,
                             "questions": questions, "qversion": questionnaire_version}

    def add_unit(self, uid, name, state, props=(), client_id=1, code=None, city="Cidade"):
        self.units[uid] = {"id": uid, "name": name, "state": state, "props": list(props), "client_id": client_id,
                           "code": code, "city": city}

    def add_eval(self, survey_id, unit_id, started_at, answers, completed=True, reliable=True, web=False,
                 tags=(), poison=False, bad_unit=False):
        day_key = started_at.strftime("%Y-%m")
        self._next_id[day_key] = self._next_id.get(day_key, 0) + 1  # id por shard: colide entre shards
        self.evaluations.append({
            "id": self._next_id[day_key], "survey_id": survey_id, "unit_id": unit_id, "started_at": started_at,
            "created_at": started_at + dt.timedelta(hours=3, seconds=len(self.evaluations) % 7),
            "device_id": None if web else 333, "completed": completed, "reliable": reliable,
            "answers": answers, "tags": list(tags), "poison": poison, "bad_unit": bad_unit,
            "duration": 95,
        })

    # ---------------------------------------------------------- serialização
    def _question_json(self, q):
        return {
            "id": q["id"], "questionnaire_id": 1, "position_in_survey": q["position"], "text": q["text"],
            "answer_type": q["type"], "options": q.get("options", {}), "annotation": None, "translations": {},
            "number": q["position"] + 1, "text_with_tags": f"{q['position'] + 1}. {q['text']}",
            "choices": [
                {"id": c["id"], "question_id": q["id"], "text": c["text"], "position_in_question": i,
                 "value": None if c.get("value") is None else f"{float(c['value']):.1f}",
                 "options": ({"additional_field": c["additional"]} if c.get("additional") else {}),
                 "translations": {}}
                for i, c in enumerate(q.get("choices", []))
            ],
            "branching_rules": q.get("branching_rules", []), "entry_rules": q.get("entry_rules", []),
        }

    def survey_json(self, s):
        evs = [e for e in self.evaluations if e["survey_id"] == s["id"]]
        last = max((e["started_at"].date() for e in evs), default=None)
        return {
            "id": s["id"], "name": s["name"], "evaluation_count_cache": len(evs),
            "last_evaluation_date_cache": last.isoformat() if last else None, "archived": s["archived"],
            "version": 3, "questionnaire": {"version": s["qversion"],
                                            "questions": [self._question_json(q) for q in s["questions"]]},
        }

    def unit_json(self, u):
        return {
            "id": u["id"], "name": u["name"], "client_specific_identifier": u["code"], "city": u["city"],
            "state": u["state"], "created_at": "2025-01-01T00:00:00.000Z", "web_survey_enabled": True,
            "ads_profile": None, "schedules": [], "total_devices": 1,
            "surveyed_unit_properties": [
                {"id": 1000 + i, "surveyed_unit_property_value": {"id": vid, "value": value},
                 "surveyed_unit_property_name": {"id": nid, "name": name}}
                for i, (nid, name, vid, value) in enumerate(u["props"])
            ],
        }

    def _formatted(self, survey, ev):
        qs = {q["id"]: q for q in survey["questions"]}
        groups: Dict[str, Any] = {}
        order: List[str] = []
        for qid, cid, score, text in ev["answers"]:
            q = qs[qid]
            t = q["type"]
            if t not in groups:
                order.append(t)
                groups[t] = {} if t == "Multiple Response" else []
            choice = next((c for c in q.get("choices", []) if c["id"] == cid), None)
            if t == "NPS":
                groups[t].append({"question_text": q["text"], "answer_value": score, "answer_text": nps_text(score)})
            elif t == "Scale":
                groups[t].append({"question_text": q["text"], "choice_text": choice["text"] if choice else None,
                                  "choice_value": None if not choice or choice.get("value") is None
                                  else f"{float(choice['value']):.1f}"})
            elif t in ("Multiple Choice", "Multiple Response"):
                item: Dict[str, Any] = {"choice_text": choice["text"] if choice else None}
                if choice and choice.get("additional"):
                    item["additional_field"] = f"(campo adicional: {choice['additional']})"
                    item["additional_field_answer"] = text
                if t == "Multiple Choice":
                    groups[t].append({"question_text": q["text"], **item})
                else:
                    groups[t].setdefault(q["text"], []).append(item)
            elif t in ("Text", "Short Text"):
                entry = {"question_text": q["text"]}
                if text:
                    entry["choice_value"] = text
                groups[t].append(entry)
            else:
                if not groups[t]:
                    groups[t].append([])
                groups[t][0].append({"question_text": q["text"], "choice_text": text})
        return [{"answer_type": t, "answers": groups[t]} for t in order]

    def evaluation_json(self, survey, ev):
        unit = self.units.get(ev["unit_id"])
        data = {
            "id": ev["id"], "survey_id": ev["survey_id"], "duration": ev["duration"],
            "started_at": ev["started_at"].strftime("%Y-%m-%dT%H:%M:%S.000Z"),
            "completed": ev["completed"], "device_id": ev["device_id"],
            "created_at": ev["created_at"].strftime("%Y-%m-%dT%H:%M:%S.000Z"),
            "shard_unique_code": 1234567890123, "origin": "Web" if ev["device_id"] is None else "Totem",
            "formatted_answers": self._formatted(survey, ev),
            "web_access_info": ({"ip_address": "200.200.200.1", "browser_fingerprint": "fp", "identifier": "cliente-123"}
                                if ev["device_id"] is None else None),
            "surveyed_unit": {"id": unit["id"], "name": unit["name"]} if unit else None,
            "tags": [
                {"question_id": qid, "question": next(q["text"] for q in survey["questions"] if q["id"] == qid),
                 "tags": [{"id": tid, "name": self.tags[tid]}]}
                for qid, tid in ev["tags"]
            ],
        }
        if survey["dq"]:
            data["reliable"] = ev["reliable"]
        return data

    # ---------------------------------------------------------------- servidor
    def start(self) -> str:
        fake = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):  # silencioso
                pass

            def _send(self, status, body):
                raw = json.dumps(body).encode("utf-8") if body is not None else b""
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

            def do_POST(self):
                length = int(self.headers.get("Content-Length") or 0)
                body = json.loads(self.rfile.read(length) or b"{}")
                fake.requests.append({"method": "POST", "path": self.path, "ua": self.headers.get("User-Agent")})
                if self.path != "/api/v1/oauth/token":
                    return self._send(404, None)
                fake.token_posts += 1
                if body.get("password") == fake.password and body.get("username") == fake.username:
                    pass
                elif body.get("refresh_token", "").startswith("refresh-"):
                    pass
                else:
                    return self._send(400, {"error": "invalid_grant"})
                token = f"tok-{fake.token_posts}"
                fake._tokens.add(token)
                return self._send(200, {"access_token": token, "token_type": "Bearer", "expires_in": 7200,
                                        "refresh_token": f"refresh-{fake.token_posts}", "created_at": 0})

            def do_GET(self):
                url = urlparse(self.path)
                qs = {k: v[0] for k, v in parse_qs(url.query).items()}
                fake.requests.append({"method": "GET", "path": url.path, "params": qs,
                                      "ua": self.headers.get("User-Agent")})
                auth = self.headers.get("Authorization", "")
                if auth.replace("Bearer ", "") not in fake._tokens:
                    return self._send(401, None)
                parts = url.path.strip("/").split("/")
                try:
                    return self._route(parts, qs)
                except Exception as exc:  # pragma: no cover
                    return self._send(500, {"status": 500, "error": str(exc)})

            def _route(self, parts, qs):
                page = int(qs.get("page", 1))
                per_page = int(qs.get("per_page", 100))
                if parts == ["api", "v1", "surveys"]:
                    items = [fake.survey_json(s) for s in fake.surveys.values() if s["client_id"] == fake.client_id]
                    return self._send(200, {"data": items[(page - 1) * per_page: page * per_page]})
                if parts == ["api", "v1", "surveyed_units"]:
                    items = [fake.unit_json(u) for u in fake.units.values() if u["client_id"] == fake.client_id]
                    return self._send(200, {"data": items[(page - 1) * per_page: page * per_page]})
                if len(parts) == 4 and parts[:3] == ["api", "v1", "surveys"]:
                    s = fake.surveys.get(int(parts[3]))
                    ok = s and s["client_id"] == fake.client_id
                    return self._send(200, {"data": fake.survey_json(s) if ok else None})
                if len(parts) == 5 and parts[:3] == ["api", "v1", "surveys"] and parts[4] == "evaluations_with_tags":
                    return self._evaluations(int(parts[3]), qs)
                return self._send(404, None)

            def _evaluations(self, survey_id, qs):
                if not qs.get("start_date"):
                    return self._send(400, {"error": "The start_date field is required"})
                s = fake.surveys.get(survey_id)  # sem filtro de cliente, como o controller real
                if not s:
                    return self._send(404, {"error": "Pesquisa não encontrada"})
                start = dt.datetime.fromisoformat(qs["start_date"])
                end = dt.datetime.fromisoformat(qs["end_date"])
                per_page = int(qs.get("per_page", 10000))
                page = int(qs.get("page", 1))
                if per_page > 10000:
                    return self._send(400, {"error": "per_page não pode ser maior que 100"})
                column = "created_at" if qs.get("search_date_scope") == "received_at" else "started_at"
                months = []
                m = dt.date(start.year, start.month, 1)
                while m <= end.date():
                    months.append(m.strftime("%Y-%m"))
                    m = (m.replace(day=28) + dt.timedelta(days=4)).replace(day=1)
                selected = []
                for month in months:  # um shard por mês, do mais antigo ao mais novo
                    shard = [e for e in fake.evaluations if e["survey_id"] == survey_id
                             and e["started_at"].strftime("%Y-%m") == month and start <= e[column] <= end]
                    shard.sort(key=lambda e: e["created_at"], reverse=True)
                    selected.extend(shard[(page - 1) * per_page: page * per_page])
                if any(e["bad_unit"] for e in selected):
                    return self._send(400, {"error": "Couldn't find all SurveyedUnits with 'id': (105)"})
                if any(e["poison"] for e in selected):
                    return self._send(200, {"data": []})
                return self._send(200, {"data": [fake.evaluation_json(s, e) for e in selected]})

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        return f"http://127.0.0.1:{self.server.server_address[1]}"

    def stop(self) -> None:
        if self.server:
            self.server.shutdown()
            self.server.server_close()

    def evaluation_requests(self):
        return [r for r in self.requests if r["path"].endswith("/evaluations_with_tags")]
