"""Auditoria e checagens de metodologia de cada resposta do agente.

- methodology_checks(): aplica, depois da resposta, as regras invariantes da skill
  (skills/solvis-survey-analysis-pilot/references/invariants.md) que dá para checar sem LLM.
  Não muda a resposta; mede se ela respeitou a metodologia.
- record(): grava a interação em ops.* com o usuário agent_audit (só INSERT).
  Falhas de metodologia e bloqueios viram candidatos a caso de avaliação (ops.eval_candidates).

Variáveis: AUDIT_PASSWORD_FILE (~/.local/clickhouse/agent_audit.pw), AUDIT_CLIENT_ID (1),
AUDIT_DISABLED=1 desliga a gravação (as checagens continuam).
"""
import json
import os
import re
import urllib.parse
import urllib.request
import uuid
from pathlib import Path

CH_URL = os.environ.get("CLICKHOUSE_URL", "http://127.0.0.1:8123")
PW_FILE = Path(os.environ.get("AUDIT_PASSWORD_FILE", Path.home() / ".local/clickhouse/agent_audit.pw"))
CLIENT_ID = int(os.environ.get("AUDIT_CLIENT_ID", "1"))

_NUM = re.compile(r"-?\d[\d.,]*")
_PII = re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+|\b\d{3}\.?\d{3}\.?\d{3}-?\d{2}\b|\(?\d{2}\)?\s?9?\d{4}-?\d{4}\b")


def _nums(text):
    out = set()
    for t in _NUM.findall(text or ""):
        t = t.strip(".,")
        if re.fullmatch(r"-?\d{1,3}(\.\d{3})+", t):
            t = t.replace(".", "")
        try:
            out.add(float(t.replace(",", ".")))
        except ValueError:
            pass
    return out


def methodology_checks(question, out, tool_outputs):
    """Lista de {rule, passed, detail}. Só regras aplicáveis à resposta entram."""
    answer, trace = out["answer"], out["trace"]
    metric_calls = [t for t in trace if t["ok"] and t["tool"] in ("nps", "scale_mean", "choice_share", "evaluation_count")
                    and t["rows"]]
    said = _nums(answer)
    checks = []

    def add(rule, passed, detail):
        checks.append({"rule": rule, "passed": bool(passed), "detail": detail})

    if out["outcome"] == "answered" and metric_calls:
        # INV-01: o número principal veio de ferramenta (o guardrail de números já bloqueia; aqui mede).
        add("INV-01 número com origem", said, "resposta cita ao menos um número" if said else "resposta sem número")
        # INV-23: n declarado junto do resultado.
        ns = set()
        for o in tool_outputs:
            ns |= {float(x) for x in re.findall(r'"(?:n|evaluations|answers)": "?(\d+)', o)}
        add("INV-23 n declarado", said & ns, "n citado" if said & ns else "nenhum n dos resultados aparece na resposta")
        # INV-18: período efetivo declarado.
        dated = re.search(r"\d{4}-\d{2}-\d{2}|\d{1,2}/\d{1,2}|ontem|hoje|semana|m[eê]s|per[ií]odo|\bde \w+ de \d{4}",
                          answer, re.I)
        add("INV-18 período declarado", dated, "período citado" if dated else "resposta sem período")
        for t in metric_calls:
            sc = t.get("scope", {})
            gb = str(sc.get("group_by") or "none")
            # INV-02: agregado do grupo é o total calculado, nunca média das linhas.
            if t["tool"] == "nps" and gb != "none" and re.search(r"geral|total|no geral|conjunto", answer, re.I):
                m = re.search(r'"total": \{[^}]*"nps": (-?\d+)', " ".join(tool_outputs))
                ok = bool(m) and float(m.group(1)) in said
                add("INV-02 agregado pelo total", ok, f"total={m.group(1) if m else '?'}")
            # INV-23: não eleger pior/melhor com amostra pequena.
            if t["tool"] == "nps" and gb != "none" and re.search(r"pior|melhor|ranking", question, re.I):
                ok = int(sc.get("min_n") or 0) >= 30 or re.search(r"amostra", answer, re.I) \
                    or not sc.get("small_sample_rows")
                add("INV-23 ranking sem amostra pequena", ok, f"min_n={sc.get('min_n')}, "
                    f"linhas pequenas={sc.get('small_sample_rows')}")
            # INV-13: recorte por propriedade é do cadastro atual (avisar em período longo; aqui só registra).
            if t["tool"] == "nps" and gb not in ("none", "unit"):
                add("INV-13 propriedade do cadastro atual", True, "registrado; aviso exigido só em período antigo")
        # INV-24: cobertura incompleta dita.
        if any('"warning": "Só há dados' in o for o in tool_outputs):
            add("INV-24 cobertura dita", "Só há dados" in answer, "aviso de cobertura presente na resposta")
    if out["outcome"] == "refused":
        # INV-25: recusa não inventa número.
        add("INV-25 recusa sem número inventado", not (said - _nums(question) - {1, 2, 3}) or bool(metric_calls),
            "recusa sem números" if not said else f"números na recusa: {sorted(said)[:5]}")
    # INV-28: nenhum dado pessoal na resposta.
    add("INV-28 sem dado pessoal", not _PII.search(answer), "sem e-mail, CPF ou telefone")
    return checks


# ------------------------------------------------------------------ gravação

def _insert(table, rows):
    if not rows or os.environ.get("AUDIT_DISABLED") == "1":
        return
    body = "\n".join(json.dumps(r, ensure_ascii=False, default=str) for r in rows).encode()
    qs = urllib.parse.urlencode({"query": f"INSERT INTO {table} FORMAT JSONEachRow"})
    req = urllib.request.Request(f"{CH_URL}/?{qs}", data=body, method="POST")
    req.add_header("X-ClickHouse-User", "agent_audit")
    req.add_header("X-ClickHouse-Key", PW_FILE.read_text().strip())
    with urllib.request.urlopen(req, timeout=10):
        pass


def record(question, out, source, model, context_on):
    iid = "i_" + uuid.uuid4().hex[:12]
    trace = out["trace"]
    _insert("ops.interactions", [{
        "interaction_id": iid, "client_id": CLIENT_ID, "source": source, "model": model,
        "context_on": int(bool(context_on)), "question": question[:4000], "answer": out["answer"][:8000],
        "tools": [t["tool"] for t in trace], "tool_errors": sum(not t["ok"] for t in trace),
        "outcome": out["outcome"], "secs": out["secs"], "context_chunks": out.get("context", [])}])
    _insert("ops.tool_calls", [{
        "interaction_id": iid, "step": i, "tool": t["tool"], "args": json.dumps(t["args"], ensure_ascii=False),
        "resolved_scope": json.dumps(t.get("scope", {}), ensure_ascii=False, default=str), "ok": int(t["ok"]),
        "error": t.get("error") or "", "rows": t["rows"]} for i, t in enumerate(trace)])
    _insert("ops.guardrail_events", [{"interaction_id": iid, **e} for e in out["guardrail_events"]])
    _insert("ops.methodology_checks", [{"interaction_id": iid, "rule": c["rule"], "passed": int(c["passed"]),
                                        "detail": c["detail"]} for c in out.get("methodology", [])])
    failed = [c["rule"] for c in out.get("methodology", []) if not c["passed"]]
    reason = "methodology" if failed else ("blocked" if out["outcome"] == "blocked" else "")
    if reason and source in ("ui", "cli"):  # avaliação e testes já são casos; só uso real vira candidato
        _insert("ops.eval_candidates", [{"interaction_id": iid, "reason": reason, "question": question[:4000],
                                         "answer": out["answer"][:4000]}])
    return iid
