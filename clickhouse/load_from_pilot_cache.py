#!/usr/bin/env python3
"""Carrega o cache SQLite do motor do piloto no ClickHouse local (protótipo).

Uso: python3 clickhouse/load_from_pilot_cache.py --client-id 1 [--cache PATH]

Lê ~/.cache/solvis-survey-analysis/<credencial>/cache.sqlite3 e envia JSONEachRow
para `clickhouse client` (variável CLICKHOUSE_BIN, padrão ~/.local/clickhouse/clickhouse).
Nenhum texto livre é carregado: só ids, contagens e dimensões.
"""
import argparse
import json
import os
import sqlite3
import subprocess
from pathlib import Path

CH = os.environ.get("CLICKHOUSE_BIN", str(Path.home() / ".local/clickhouse/clickhouse"))


def insert(table, rows):
    payload = "\n".join(json.dumps(r, ensure_ascii=False) for r in rows).encode()
    subprocess.run([CH, "client", "-q", f"INSERT INTO {table} FORMAT JSONEachRow"],
                   input=payload, check=True)
    print(f"{table}: {len(rows)} linhas")


def find_cache():
    root = Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache")) / "solvis-survey-analysis"
    found = sorted(root.glob("*/cache.sqlite3"))
    if len(found) != 1:
        raise SystemExit(f"Esperava 1 cache em {root}, achei {len(found)}. Use --cache.")
    return found[0]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--client-id", type=int, required=True)
    ap.add_argument("--cache", type=Path)
    a = ap.parse_args()
    db = sqlite3.connect(str(a.cache or find_cache()))
    cid = a.client_id

    evs = {}
    rows = []
    for (sid, ref, day, started, unit, ch, comp, rel, dq, dur) in db.execute(
            "SELECT survey_id, eval_ref, day, started_at, unit_id, channel, completed, reliable, dq, duration "
            "FROM evaluations"):
        evs[(sid, ref)] = (unit or 0, ch, comp, rel)
        rows.append({"client_id": cid, "survey_id": sid, "eval_ref": ref, "day": day,
                     "started_at": started[:19].replace("T", " "), "unit_id": unit or 0, "channel": ch,
                     "completed": comp, "reliable": rel, "dq": dq, "duration": dur})
    insert("raw.evaluations", rows)

    rows = []
    for (sid, ref, day, qid, kind, choice, score, answered) in db.execute(
            "SELECT survey_id, eval_ref, day, question_id, kind, choice_id, score, answered "
            "FROM answers WHERE question_id IS NOT NULL"):
        unit, ch, comp, rel = evs[(sid, ref)]
        rows.append({"client_id": cid, "survey_id": sid, "eval_ref": ref, "day": day, "unit_id": unit,
                     "channel": ch, "completed": comp, "reliable": rel, "question_id": qid, "kind": kind,
                     "choice_id": choice, "score": score, "answered": answered})
    insert("raw.answers", rows)

    units = json.loads(db.execute("SELECT payload FROM catalog WHERE kind='units'").fetchone()[0])
    insert("raw.units", [{"client_id": cid, "unit_id": u["id"], "name": u["name"], "code": u.get("code") or "",
                          "city": u.get("city") or "", "state": u.get("state") or ""} for u in units])
    insert("raw.unit_properties", [
        {"client_id": cid, "unit_id": u["id"], "name_id": p["name_id"], "name": p["name"],
         "value_id": p["value_id"], "value": p["value"]} for u in units for p in u.get("properties", [])])

    choices = []
    for (kind, payload) in db.execute("SELECT kind, payload FROM catalog WHERE kind LIKE 'survey:%'"):
        s = json.loads(payload)
        for q in s["questionnaire"]["questions"]:
            for i, c in enumerate(q.get("choices") or []):
                v = c.get("value")
                choices.append({"client_id": cid, "survey_id": s["id"], "question_id": q["id"],
                                "choice_id": c["id"], "letter": chr(65 + i) if i < 26 else str(i + 1),
                                "text": c["text"], "value": float(v) if v not in (None, "") else None})
    insert("raw.choices", choices)

    surveys, questions = [], []
    for (kind, payload) in db.execute("SELECT kind, payload FROM catalog WHERE kind LIKE 'survey:%'"):
        s = json.loads(payload)
        surveys.append({"client_id": cid, "survey_id": s["id"], "name": s["name"],
                        "archived": int(bool(s.get("archived"))),
                        "last_evaluation_date": (s.get("last_evaluation_date_cache") or "")[:10] or None})
        for q in s["questionnaire"]["questions"]:
            questions.append({"client_id": cid, "survey_id": s["id"], "question_id": q["id"],
                              "number": q.get("number") or 0, "text": q["text"],
                              "answer_type": q["answer_type"]})
    insert("raw.surveys", surveys)
    insert("raw.questions", questions)


if __name__ == "__main__":
    main()
