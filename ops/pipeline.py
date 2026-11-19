#!/usr/bin/env python3
"""Pipeline de qualidade do agente: dados, guardrails, avaliação, metodologia e portão.

Etapas (cada uma grava em ops.* e entra no relatório):
  1. health      checagens de saúde dos dados e metadados        -> ops.data_health
  2. guardrails  testes determinísticos sem LLM (tests/agent)    -> resultado no relatório
  3. eval        avaliação com o modelo (opcional, --eval)       -> ops.eval_runs, ops.eval_results
  4. method      taxa de aprovação nas regras da skill (INV-xx)  -> lida de ops.methodology_checks
  5. gate        compara com ops/gate.json e com a última execução aprovada
  6. review      candidatos a caso de avaliação vindos de uso real (ops.eval_candidates)

Uso:
  AGENT_TODAY=2026-11-18 python3 ops/pipeline.py            # sem LLM (segundos)
  AGENT_TODAY=2026-11-18 python3 ops/pipeline.py --eval     # com avaliação (minutos; pesa em 8 GB)
  python3 ops/pipeline.py --review                          # lista candidatos pendentes
Código de saída: 0 aprovado, 1 reprovado.
"""
import argparse
import datetime as dt
import hashlib
import json
import os
import subprocess
import sys
import time
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CH = os.environ.get("CLICKHOUSE_BIN", str(Path.home() / ".local/clickhouse/clickhouse"))
AUDIT_PW = Path.home() / ".local/clickhouse/agent_audit.pw"
GATE = json.loads((ROOT / "ops" / "gate.json").read_text())
VALID_UF = set("AC AL AM AP BA CE DF ES GO MA MG MS MT PA PB PE PI PR RJ RN RO RR RS SC SE SP TO".split())


def q(sql):
    """Consulta como administrador local (só o pipeline; o agente nunca usa este acesso)."""
    out = subprocess.run([CH, "client", "-q", sql + " FORMAT JSON"], capture_output=True, text=True, check=True)
    return json.loads(out.stdout)["data"]


def insert(table, rows):
    if not rows:
        return
    body = "\n".join(json.dumps(r, ensure_ascii=False, default=str) for r in rows)
    subprocess.run([CH, "client", "--user", "agent_audit", "--password", AUDIT_PW.read_text().strip(),
                    "-q", f"INSERT INTO {table} FORMAT JSONEachRow"], input=body, text=True, check=True)


def code_hash():
    """Versão do que define o comportamento: agente, tools/MCP, views, acessos, catálogo, portão e skill."""
    h = hashlib.sha256()
    files = sorted(list((ROOT / "agent").glob("*.py")) + list((ROOT / "clickhouse").glob("*.sql")) +
                   list((ROOT / "mcp").rglob("*.py")) + list((ROOT / "solvis_tools").rglob("*.py")) + list((ROOT / "ops").glob("*.sql")) +
                   [ROOT / "ops/metadata_catalog.json", ROOT / "ops/gate.json"] +
                   list((ROOT / "skills/solvis-survey-analysis-pilot/references").glob("*.md")) +
                   [ROOT / "skills/solvis-survey-analysis-pilot/SKILL.md"])
    for f in files:
        h.update(f.read_bytes())
    return h.hexdigest()[:12]


# ------------------------------------------------------------------ 1. saúde dos dados

def health():
    checks = []

    def add(cid, level, value, threshold, detail):
        checks.append({"check_id": cid, "level": level, "value": float(value), "threshold": float(threshold),
                       "detail": detail})

    # Consistência: contagens pré-agregadas (materialized view) = respostas brutas.
    a = q("SELECT sum(answers) s FROM semantic.answer_counts_daily")[0]["s"]
    b = q("SELECT count() c FROM raw.answers WHERE answered = 1")[0]["c"]
    add("mv_consistency", "ok" if int(a) == int(b) else "fail", abs(int(a) - int(b)), 0,
        f"contagens {a} × respostas {b}")

    # Paridade com o valor conhecido do motor do piloto (NPS 79, n 11.709 em 17/11/2026).
    for p in GATE["parity"]:
        r = q(f"SELECT sum(promoters) p, sum(detractors) d, sum(n) n FROM semantic.nps_by_unit("
              f"survey={p['survey']}, question={p['question']}, start='{p['day']}', end='{p['day']}')")[0]
        n = int(r["n"])
        raw = 100.0 * (int(r["p"]) / n - int(r["d"]) / n) if n else 0
        nps = int(raw + 0.5) if raw >= 0 else -int(-raw + 0.5)
        ok = nps == p["nps"] and n == p["n"]
        add(f"parity_{p['survey']}_{p['day']}", "ok" if ok else "fail", nps, p["nps"],
            f"NPS {nps} n {n} (esperado {p['nps']} / {p['n']}, motor do piloto)")

    # Isolamento: o agente só vê o próprio cliente.
    pw = (Path.home() / ".local/clickhouse/assai_agent.pw").read_text().strip()
    out = subprocess.run([CH, "client", "--user", "assai_agent", "--password", pw, "-q",
                          "SELECT count() FROM raw.answers"], capture_output=True, text=True)
    add("isolation_raw_answers", "ok" if out.returncode != 0 else "fail", 0 if out.returncode else 1, 0,
        "agente sem acesso a respostas individuais")

    # Metadados das unidades.
    units = q("SELECT unit_id, name, state FROM raw.units")
    bad_uf = [u for u in units if u["state"] not in VALID_UF]
    add("units_invalid_uf", "warn" if bad_uf else "ok", len(bad_uf), 0,
        "; ".join(f"{u['name'][:30]} ({u['state'] or 'vazio'})" for u in bad_uf[:5]))
    non_store = [u for u in units if any(w in u["name"].lower() for w in ("pesquisa", "teste", "web"))]
    add("units_not_stores", "warn" if non_store else "ok", len(non_store), 0,
        "; ".join(u["name"][:40] for u in non_store[:5]) + " (sem campo de tipo de unidade no produto)")
    no_props = q("SELECT count() c FROM raw.units u LEFT ANTI JOIN raw.unit_properties p USING (client_id, unit_id)")
    add("units_without_properties", "warn" if int(no_props[0]["c"]) else "ok", no_props[0]["c"], 0,
        "unidades fora de qualquer recorte por propriedade")
    ident = q("SELECT any(name) name, uniqExact(value_id) v FROM raw.unit_properties GROUP BY name_id "
              "HAVING v > 100")
    add("property_used_as_identifier", "warn" if ident else "ok", len(ident), 0,
        "; ".join(f"{r['name']} ({r['v']} valores)" for r in ident) + " (não usar como recorte)")

    # Metadados das perguntas: (tipo, texto) repetidos em pesquisas ativas.
    dup = q("SELECT s.name survey, count() - uniqExact((q.answer_type, q.text)) d FROM raw.questions q "
            "JOIN raw.surveys s USING (client_id, survey_id) WHERE s.archived = 0 GROUP BY s.name HAVING d > 0")
    add("questions_repeated_text", "warn" if dup else "ok", sum(int(r["d"]) for r in dup), 0,
        "; ".join(f"{r['survey'][:35]}: {r['d']}" for r in dup[:5]))

    # Contexto da pesquisa (endpoint ainda não existe).
    active = q("SELECT count() c FROM raw.surveys WHERE archived = 0")[0]["c"]
    add("surveys_without_context", "warn", active, 0, "endpoint de contexto e finalidade ainda não existe")

    # Frescor e cobertura.
    today = dt.date.fromisoformat(os.environ.get("AGENT_TODAY", dt.date.today().isoformat()))
    last = q("SELECT max(day) d, uniqExact(day) n FROM raw.evaluations")[0]
    lag = (today - dt.date.fromisoformat(last["d"])).days
    add("freshness_days", "ok" if lag <= GATE["max_data_lag_days"] else "warn", lag, GATE["max_data_lag_days"],
        f"último dia carregado {last['d']}; {last['n']} dia(s) no total")

    # Regras da skill indexadas = arquivos atuais (detecta skill alterada sem reindexar).
    sys.path.insert(0, str(ROOT))
    from solvis_tools.core import skill_index as context
    expected = len(context.chunks())
    have = int(q("SELECT count() c FROM semantic.skill_chunks")[0]["c"])
    add("skill_index_current", "ok" if have == expected else "fail", have, expected,
        "trechos indexados × trechos da skill atual (rode python3 -m solvis_tools.core.skill_index index)")

    insert("ops.data_health", checks)
    return checks


# ------------------------------------------------------------------ 2. guardrails

def guardrails():
    """Testes sem LLM: guardrails do agente (tests/agent) e biblioteca de tools + MCP (tests/mcp)."""
    t0 = time.time()
    env = {**os.environ, "AGENT_TODAY": os.environ.get("AGENT_TODAY", "2026-11-18")}
    total = failed = 0
    output, parts = "", {}
    for suite in ("tests/agent", "tests/mcp"):
        out = subprocess.run([sys.executable, "-m", "unittest", "discover", "-s", str(ROOT / suite)],
                             capture_output=True, text=True, env=env)
        last = [l for l in out.stderr.strip().splitlines() if l.startswith("Ran ")]
        n = int(last[0].split()[1]) if last else 0
        f = 0
        for l in out.stderr.splitlines():
            if l.startswith("FAILED"):
                f = sum(int(x.split("=")[1]) for x in l[l.find("(") + 1:l.find(")")].split(", "))
        if n == 0 or out.returncode and not f:  # suíte que nem rodou conta como falha
            f = max(f, 1)
        total, failed, parts[suite] = total + n, failed + f, f"{n - f}/{n}"
        if f:
            output += out.stderr[-1500:]
    return {"total": total, "failed": failed, "secs": round(time.time() - t0, 1), "parts": parts, "output": output}


# ------------------------------------------------------------------ 3. avaliação

def evaluate(runs, context_on):
    run_id = "r_" + uuid.uuid4().hex[:10]
    started = q("SELECT toString(now64(3)) t")[0]["t"]  # relógio do ClickHouse, mesmo fuso de ops.*.ts
    out_file = ROOT / "agent/results" / f"{run_id}.json"
    env = {**os.environ, "AGENT_CONTEXT": "1" if context_on else "0",
           "AGENT_TODAY": os.environ.get("AGENT_TODAY", "2026-11-18")}
    subprocess.run([sys.executable, str(ROOT / "agent/eval_baseline.py"), "--runs", str(runs), "--out",
                    str(out_file)], env=env, check=True)
    res = json.loads(out_file.read_text())
    passed = sum(r["pass"] for r in res)
    insert("ops.eval_results", [{"run_id": run_id, "case_id": r["id"], "run": r["run"], "passed": int(r["pass"]),
                                 "checks": json.dumps(r.get("checks", {})), "answer": r.get("answer", ""),
                                 "secs": r["secs"]} for r in res])
    summary = {"run_id": run_id, "model": os.environ.get("AGENT_MODEL", "qwen3:1.7b"), "context_on": int(context_on),
               "cases": len(res), "passed": passed, "pass_rate": passed / len(res),
               "mean_secs": sum(r["secs"] for r in res) / len(res), "code_hash": code_hash(), "started": started,
               "failed_cases": sorted({r["id"] for r in res if not r["pass"]})}
    return summary


# ------------------------------------------------------------------ 4. metodologia

def methodology(since):
    rows = q(f"SELECT m.rule rule, count() n, sum(m.passed) ok FROM ops.methodology_checks m "
             f"JOIN ops.interactions i USING interaction_id WHERE i.source = 'eval' AND i.ts >= '{since}' "
             f"GROUP BY m.rule ORDER BY m.rule")
    return [{"rule": r["rule"], "n": int(r["n"]), "ok": int(r["ok"])} for r in rows]


# ------------------------------------------------------------------ 5. portão

def gate(health_checks, guard, ev, meth):
    reasons = []
    fails = [c for c in health_checks if c["level"] == "fail"]
    if fails:
        reasons.append("dados: " + ", ".join(c["check_id"] for c in fails))
    if guard["failed"] or guard["total"] < GATE["min_guardrail_tests"]:
        reasons.append(f"guardrails: {guard['failed']} falha(s) em {guard['total']} testes")
    if ev:
        if ev["pass_rate"] < GATE["min_eval_pass_rate"]:
            reasons.append(f"avaliação: {ev['pass_rate']:.0%} < {GATE['min_eval_pass_rate']:.0%}")
        prev = q(f"SELECT pass_rate FROM ops.eval_runs WHERE gate = 'pass' AND context_on = {ev['context_on']} "
                 f"ORDER BY ts DESC LIMIT 1")
        if prev and ev["pass_rate"] < float(prev[0]["pass_rate"]) - GATE["max_eval_regression"]:
            reasons.append(f"avaliação regrediu: {ev['pass_rate']:.0%} × {float(prev[0]['pass_rate']):.0%} "
                           f"da última aprovada")
        total = sum(m["n"] for m in meth)
        if not total:  # avaliação sem checagens registradas = auditoria quebrada, não aprovação
            reasons.append("metodologia: nenhuma checagem registrada para a avaliação (auditoria falhou?)")
        rate = sum(m["ok"] for m in meth) / total if total else 0
        if total and rate < GATE["min_methodology_pass_rate"]:
            reasons.append(f"metodologia: {rate:.0%} < {GATE['min_methodology_pass_rate']:.0%}")
    return ("fail" if reasons else "pass"), reasons


# ------------------------------------------------------------------ 6. revisão

def review():
    return q("SELECT interaction_id, reason, question, answer FROM ops.eval_candidates FINAL "
             "WHERE status = 'pending' ORDER BY ts DESC LIMIT 20")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--eval", action="store_true", help="roda a avaliação com o modelo")
    ap.add_argument("--runs", type=int, default=1)
    ap.add_argument("--context", type=int, default=int(os.environ.get("AGENT_CONTEXT", "1")))
    ap.add_argument("--review", action="store_true")
    a = ap.parse_args()

    if a.review:
        for c in review():
            print(f"[{c['reason']}] {c['interaction_id']}\n  P: {c['question'][:160]}\n  R: {c['answer'][:200]}\n")
        return 0

    print("1. Saúde dos dados")
    hc = health()
    for c in hc:
        mark = {"ok": "✓", "warn": "!", "fail": "✗"}[c["level"]]
        print(f"   {mark} {c['check_id']:<28} {c['detail'][:110]}")

    print("2. Guardrails, tools e MCP (testes sem LLM)")
    gr = guardrails()
    print(f"   {'✓' if not gr['failed'] else '✗'} {gr['total'] - gr['failed']}/{gr['total']} em {gr['secs']} s "
          f"({', '.join(f'{k}: {v}' for k, v in gr['parts'].items())})")
    if gr["output"]:
        print(gr["output"])

    ev, meth = None, []
    if a.eval:
        print(f"3. Avaliação com o modelo (contexto {'ligado' if a.context else 'desligado'}, {a.runs} execução)")
        ev = evaluate(a.runs, a.context)
        print(f"   {ev['passed']}/{ev['cases']} ({ev['pass_rate']:.0%}), {ev['mean_secs']:.1f} s por resposta"
              + (f"; falharam: {', '.join(ev['failed_cases'])}" if ev["failed_cases"] else ""))
        print("4. Metodologia (regras da skill nas respostas da avaliação)")
        meth = methodology(ev["started"])
        for m in meth:
            print(f"   {'✓' if m['ok'] == m['n'] else '✗'} {m['rule']:<38} {m['ok']}/{m['n']}")
    else:
        print("3-4. Avaliação e metodologia: puladas (use --eval)")

    status, reasons = gate(hc, gr, ev, meth)
    if ev:
        insert("ops.eval_runs", [{k: ev[k] for k in ("run_id", "model", "context_on", "cases", "passed", "pass_rate",
                                                     "mean_secs", "code_hash")} | {"gate": status}])
    print(f"5. Portão: {'APROVADO' if status == 'pass' else 'REPROVADO'} (versão {code_hash()})")
    for r in reasons:
        print(f"   ✗ {r}")
    pend = review()
    print(f"6. Revisão: {len(pend)} candidato(s) a caso de avaliação vindos de uso real "
          f"(python3 ops/pipeline.py --review)")
    return 0 if status == "pass" else 1


if __name__ == "__main__":
    sys.exit(main())
