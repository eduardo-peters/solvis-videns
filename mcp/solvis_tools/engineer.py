"""Tools de metadados e engenharia, ligadas à skill.

Perfil data_engineer recebe todas. O analyst recebe as de leitura da skill e de descrição
(describe_survey, explain_metric, skill_lookup), para entender o dado antes de consultar.
Executam com engineer_agent: metadados e resultados agregados de qualidade, sem respostas
individuais e sem conversas.
"""
import json
import re
import sys

from . import ROOT, ToolError, ch, tool

SKILL = ROOT / "skills" / "solvis-survey-analysis-pilot"
CATALOG = ROOT / "ops" / "metadata_catalog.json"
VALID_UF = set("AC AL AM AP BA CE DF ES GO MA MG MS MT PA PB PE PI PR RJ RN RO RR RS SC SE SP TO".split())
NON_STORE = re.compile(r"pesquisa|teste|webspot|\bweb\b|self.?check", re.I)


def q(sql, params=None):
    return ch("engineer", sql, params)


def _fold(t):
    sys.path.insert(0, str(ROOT / "agent"))
    import agent
    return agent._fold(t)


# ------------------------------------------------------------------ skill: leitura estruturada

def _question_types():
    """Tabela de question-types.md: answer_type -> {what, metrics, notes}."""
    out = {}
    for line in (SKILL / "references/question-types.md").read_text().splitlines():
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) == 4 and cells[0].startswith("`") and cells[0] != "`answer_type`":
            for t in re.findall(r"`([^`]+)`", cells[0]):
                out[t] = {"what": cells[1], "metrics": re.findall(r"`([a-z_]+)`", cells[2]), "notes": cells[3]}
    return out


def _metric_block(metric_id):
    """Bloco do metrics.yaml de uma métrica (texto, sem depender de PyYAML)."""
    text = (SKILL / "references/metrics.yaml").read_text()
    m = re.search(r"^  - id: %s\n(.*?)(?=^  - id: |\Z)" % re.escape(metric_id), text, re.S | re.M)
    return m.group(0).rstrip() if m else None


def _metric_ids():
    return re.findall(r"^  - id: ([a-z_]+)", (SKILL / "references/metrics.yaml").read_text(), re.M)


def _invariants():
    text = (SKILL / "references/invariants.md").read_text()
    return {m.group(1): m.group(2).strip().rstrip(".") for m in re.finditer(r"\[(INV-\d+)\]\s*(.+?)\*\*", text)}


# ------------------------------------------------------------------ tools

@tool("metadata_catalog", agents=["data_engineer", "analyst"], access="engineer",
      description="Catálogo de metadados semânticos: para cada campo (pesquisa, pergunta, unidade, tag), "
                  "para que a IA o usa, se existe (testing, engine, inferred, missing), fonte, dono, regra da skill "
                  "ligada e o resultado mais recente da checagem de saúde correspondente.",
      params={"level": ("string", "survey, question, unit ou tag (opcional)"),
              "status": ("string", "testing, engine, inferred ou missing (opcional)")},
      reads=["ops/metadata_catalog.json", "ops.data_health"], skill=["invariants.md", "docs/metadata-semantics.md"],
      example={"level": "unit"})
def metadata_catalog(args):
    cat = json.loads(CATALOG.read_text())
    health = {r["check_id"]: r for r in q(
        "SELECT check_id, argMax(level, ts) level, argMax(value, ts) value, argMax(detail, ts) detail, "
        "max(ts) checked_at FROM ops.data_health GROUP BY check_id")}
    inv = _invariants()
    fields = [f for f in cat["fields"] if (not args.get("level") or f["level"] == args["level"])
              and (not args.get("status") or f["status"] == args["status"])]
    for f in fields:
        if f.get("check") in health:
            f["health"] = {k: health[f["check"]][k] for k in ("level", "value", "detail", "checked_at")}
        if f.get("skill", "") and f["skill"] in inv:
            f["skill_rule"] = inv[f["skill"]]
    summary = {}
    for f in fields:
        summary[f["status"]] = summary.get(f["status"], 0) + 1
    return {"version": cat["version"], "summary": summary, "fields": fields}


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


@tool("data_health", agents=["data_engineer"], access="engineer",
      description="Resultado mais recente de cada checagem de saúde dos dados (paridade com o piloto, consistência, "
                  "isolamento, índice da skill, UF, tipo de unidade, perguntas repetidas, contexto, frescor). "
                  "Para rodar de novo: python3 ops/pipeline.py.",
      params={"level": ("string", "ok, warn ou fail (opcional)")},
      reads=["ops.data_health"], skill=["docs/data-ops.md"], example={"level": "warn"})
def data_health(args):
    rows = q("SELECT check_id, argMax(level, ts) level, argMax(value, ts) value, argMax(threshold, ts) threshold, "
             "argMax(detail, ts) detail, max(ts) checked_at FROM ops.data_health GROUP BY check_id ORDER BY check_id")
    if args.get("level"):
        rows = [r for r in rows if r["level"] == args["level"]]
    return {"checks": rows, "counts": {lv: sum(r["level"] == lv for r in rows) for lv in ("ok", "warn", "fail")}}


@tool("explain_metric", agents=["data_engineer", "analyst"], access="engineer",
      description="Definição de uma métrica pela skill (metrics.yaml): o que é, o que conta em n, armadilhas, "
                  "e se existe no protótipo. Também responde métricas que não existem (csat, response_rate...).",
      params={"metric": ("string", "Id da métrica (ex.: nps, scale_mean, csat). Vazio lista os ids")},
      reads=["skills/.../references/metrics.yaml"], skill=["metrics.yaml", "INV-25"], example={"metric": "csat"})
def explain_metric(args):
    ids = _metric_ids()
    m = (args.get("metric") or "").strip().lower()
    if not m:
        return {"metrics": ids}
    block = _metric_block(m)
    if not block:
        raise ToolError(f"métrica '{m}' não está no modelo da skill. Ids: {', '.join(ids)}")
    return {"metric": m, "in_prototype": m in ("nps", "scale_mean", "choice_share", "evaluation_count"),
            "definition_from_skill": block}


@tool("skill_lookup", agents=["data_engineer", "analyst"], access="engineer",
      description="Busca vetorial nas regras da skill (SKILL.md, invariantes, playbooks, glossário, limitações, "
                  "formato de resposta, tipos de pergunta). Devolve os trechos mais próximos com a fonte.",
      params={"query": ("string", "Assunto ou pergunta (ex.: 'como tratar amostra pequena em ranking')"),
              "k": ("integer", "Quantos trechos (padrão 3, máximo 8)")},
      required=["query"], reads=["semantic.skill_chunks", "Ollama nomic-embed-text"],
      skill=["toda a skill do piloto"], example={"query": "NPS geral de várias lojas", "k": 3})
def skill_lookup(args):
    sys.path.insert(0, str(ROOT / "agent"))
    import context
    k = max(1, min(int(args.get("k") or 3), 8))
    rows = context.retrieve(args["query"], lambda sql, p=None: q(sql, p), k=k, budget=10_000)
    return {"chunks": [{"source": r["source"], "heading": r["heading"], "distance": round(float(r["d"]), 3),
                        "text": r["text"]} for r in rows]}


@tool("methodology_rules", agents=["data_engineer"], access="engineer",
      description="Regras invariantes da skill, quais são checadas automaticamente em cada resposta e a taxa de "
                  "aprovação de cada uma (avaliação e uso real, agregadas).",
      params={},
      reads=["skills/.../references/invariants.md", "ops.methodology_checks (regra e resultado)"],
      skill=["invariants.md"], example={})
def methodology_rules(args):
    inv = _invariants()
    rates = {r["rule"]: r for r in q(
        "SELECT rule, count() n, sum(passed) ok, max(ts) last FROM ops.methodology_checks GROUP BY rule")}
    checked = {}
    for rule, r in rates.items():
        code = rule.split()[0]
        checked.setdefault(code, []).append({"check": rule, "n": int(r["n"]), "passed": int(r["ok"]),
                                             "pass_rate": round(int(r["ok"]) / int(r["n"]), 3), "last": r["last"]})
    return {"rules": [{"id": k, "rule": v, "automated_checks": checked.get(k, [])} for k, v in inv.items()],
            "coverage": f"{len(checked)} de {len(inv)} regras com checagem automática"}


@tool("quality_status", agents=["data_engineer"], access="engineer",
      description="Estado da qualidade do agente: últimas avaliações (acerto, tempo, versão do código, portão) e "
                  "quantas vezes cada guardrail atuou.",
      params={"limit": ("integer", "Quantas avaliações recentes (padrão 5)")},
      reads=["ops.eval_runs", "ops.guardrail_events (guardrail e ação)"], skill=["docs/data-ops.md"],
      example={"limit": 3})
def quality_status(args):
    lim = min(int(args.get("limit") or 5), 50)
    runs = q("SELECT ts, run_id, model, context_on, cases, passed, round(pass_rate, 3) pass_rate, "
             "round(mean_secs, 1) mean_secs, code_hash, gate FROM ops.eval_runs ORDER BY ts DESC LIMIT {l:UInt8}",
             {"l": lim})
    guards = q("SELECT guardrail, action, count() n FROM ops.guardrail_events GROUP BY guardrail, action ORDER BY n DESC")
    return {"eval_runs": runs, "guardrail_events": guards,
            "note": "Rodar de novo: python3 ops/pipeline.py --eval. Candidatos de uso real: --review."}


@tool("question_types", agents=["data_engineer", "analyst"], access="engineer",
      description="Tipos de pergunta da Solvis pela skill: o que é cada tipo, quais métricas existem e observações.",
      params={"answer_type": ("string", "Tipo (ex.: Scale, Multiple Response). Vazio lista todos")},
      reads=["skills/.../references/question-types.md"], skill=["question-types.md"],
      example={"answer_type": "Multiple Response"})
def question_types(args):
    types = _question_types()
    t = args.get("answer_type")
    if t:
        if t not in types:
            raise ToolError(f"tipo '{t}' desconhecido. Tipos: {', '.join(types)}")
        return {t: types[t]}
    return types
