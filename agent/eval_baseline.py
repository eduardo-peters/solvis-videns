#!/usr/bin/env python3
"""Linha de base do agente local: perguntas de gestor com resposta esperada.

Uso: AGENT_TODAY=2026-11-18 python3 agent/eval_baseline.py [--runs 1]
Os valores esperados vêm do ClickHouse (dados de 17/11/2026 do Assaí no protótipo).
Critérios por caso: ferramenta final certa, argumentos certos, número esperado na
resposta, nenhum número sem origem (guardrail), e recusa quando não existe.
"""
import argparse
import json
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import agent  # noqa: E402

CASES = [
    {"id": "nps_total", "q": "Qual foi o NPS da pesquisa Satisfação ontem?",
     "tool": "nps", "scope": {"survey": "Satisfação", "question": "1."}, "expect": ["79"]},
    {"id": "nps_regional", "q": "Qual foi o NPS da pesquisa Satisfação ontem por Regional?",
     "tool": "nps", "scope": {"survey": "Satisfação", "group_by": "Regional"}, "expect": ["52", "91"]},
    {"id": "volume", "q": "Quantas avaliações a pesquisa Satisfação teve ontem?",
     "tool": "evaluation_count", "scope": {"survey": "Satisfação"}, "expect": ["11709", "11.709"]},
    {"id": "scale_mean", "q": "Qual a média da nota de Atendimento na pesquisa Satisfação ontem?",
     "tool": "scale_mean", "scope": {"survey": "Satisfação", "question": "2."}, "expect": ["4.78", "4,78", "4.8", "4,8"]},
    {"id": "choice_share", "q": "Qual a distribuição de estrelas de Atendimento na pesquisa Satisfação ontem?",
     "tool": "choice_share", "scope": {"survey": "Satisfação", "question": "2."}, "expect": ["82.9", "82,9"]},
    {"id": "top_unit", "q": "Qual foi a loja que mais teve respostas ontem?",
     "tool": "evaluation_count", "scope": {"group_by": "unit"}, "expect": ["288", "373"]},
    {"id": "top_unit_survey", "q": "qual foi a loja que mais teve respostas? e qual foi a pesquisa?",
     "tool": "evaluation_count", "scope": {}, "expect": ["Aracaj"], "period_any": True},
    {"id": "faturamento", "q": "Qual o faturamento da loja de Belém?", "tool": None, "refuse": True, "expect": []},
    # --- casos adaptados de evals/cases-pilot.yaml para os dados do Assaí ---
    {"id": "pilot_csat", "q": "Qual o nosso CSAT de atendimento?", "tool": None, "refuse": True, "expect": [],
     "must_match": r"CSAT", "allow_metric": True},
    {"id": "pilot_pooling", "q": "Me dá o NPS de cada loja e o NPS geral de ontem na pesquisa Satisfação.",
     "tool": "nps", "scope": {"survey": "Satisfação", "group_by": "unit"}, "expect": ["79"]},
    {"id": "pilot_worst_unit", "q": "Qual a pior loja em NPS ontem na pesquisa Satisfação?",
     "tool": "nps", "scope": {"survey": "Satisfação"}, "expect": ["Tapioqueiras", "-3"],
     "must_not": r"Washington Soares(?![^.]*amostra)"},
    {"id": "pilot_compare", "q": "O NPS da Satisfação subiu em relação à semana anterior?", "tool": None,
     "refuse": True, "expect": [], "allow_metric": True, "must_match": r"compara|anterior"},
    # Aceita número junto, desde que a resposta abra dizendo que comentários não estão disponíveis.
    {"id": "pilot_comments", "q": "O que os clientes estão comentando na pesquisa Satisfação?", "tool": None,
     "refuse": True, "expect": [], "allow_metric": True, "must_match": r"^Coment[aá]rios.{0,40}n[aã]o est[aã]o dispon"},
    {"id": "pilot_multi", "q": "Quais foram os principais motivos de insatisfação ontem na pesquisa Satisfação?",
     "tool": None, "refuse": True, "expect": []},
    {"id": "nps_wrong_type", "q": "Qual o NPS da pergunta de Atendimento da pesquisa Satisfação ontem?",
     "tool": None, "refuse": True, "expect": []},
    {"id": "benchmark", "q": "Como o NPS do Assaí se compara com o benchmark do varejo?",
     "tool": None, "refuse": True, "expect": []},
    {"id": "no_data", "q": "Qual foi o NPS da pesquisa Satisfação em março de 2025?",
     "tool": None, "refuse": True, "expect": []},
]

# Holdout: perguntas novas, escritas antes do enriquecimento e nunca usadas para ajustar o agente
# nem o modelo. Medem generalização. Valores esperados tirados do ClickHouse (17/11/2026).
HOLDOUT = [
    {"id": "h_recomendacao", "q": "Como está a recomendação dos clientes na Satisfação ontem?",
     "tool": "nps", "scope": {"survey": "Satisfação"}, "expect": ["79"]},
    {"id": "h_hub", "q": "Quero ver o NPS por HUB ontem na pesquisa Satisfação.",
     "tool": "nps", "scope": {"survey": "Satisfação", "group_by": "HUB"}, "expect": ["77", "82"]},
    {"id": "h_produtos", "q": "Qual a nota média de Produtos (qualidade/variedades) ontem na Satisfação?",
     "tool": "scale_mean", "scope": {"survey": "Satisfação", "question": "3."}, "expect": ["4.64", "4,64", "4,6", "4.6"]},
    {"id": "h_primeira_vez", "q": "Qual o percentual de quem comprou no Assaí pela primeira vez ontem, na pesquisa Satisfação?",
     "tool": "choice_share", "scope": {"survey": "Satisfação", "question": "13."}, "expect": ["5%", "5 %", "5,0", "95"]},
    {"id": "h_taxa_resposta", "q": "Qual a taxa de resposta da pesquisa Satisfação ontem?", "tool": None,
     "refuse": True, "expect": [], "allow_metric": True, "must_match": r"taxa de resposta"},
    {"id": "h_media_das_lojas", "q": "Qual a média do NPS das lojas ontem na Satisfação?",
     "tool": "nps", "scope": {"survey": "Satisfação"}, "expect": ["79"]},
    {"id": "h_reclamacoes", "q": "Do que os clientes reclamaram ontem na pesquisa Satisfação?", "tool": None,
     "refuse": True, "expect": [], "allow_metric": True, "must_match": r"n[aã]o est[aã]o dispon|n[aã]o est[aá] dispon"},
    {"id": "h_pesquisa_volume", "q": "Qual pesquisa recebeu mais respostas ontem?",
     "tool": "evaluation_count", "scope": {"group_by": "pesquisa"}, "expect": ["Satisfação"]},
]

REFUSAL = re.compile(r"não (há|existe|está disponível|estão disponíveis|temos|tenho|possu|consigo|é possível|é suportad|oferec)|indispon|sem dados|nenhum dado|não encontr|ainda não|qual (pergunta|das perguntas)", re.I)


def run_case(c):
    t0 = time.time()
    try:
        out = agent.ask([{"role": "user", "content": c["q"]}], source="eval")
    except Exception as e:
        return {"id": c["id"], "pass": False, "error": str(e), "secs": round(time.time() - t0, 1)}
    calls = [t for t in out["trace"] if t["ok"]]
    metric_calls = [t for t in calls if t["tool"] in ("nps", "choice_share", "scale_mean", "evaluation_count")]
    last = metric_calls[-1] if metric_calls else None
    checks = {}
    if c.get("refuse"):
        got_rows = any(t["rows"] for t in metric_calls)
        checks["refused"] = bool(REFUSAL.search(out["answer"])) and (c.get("allow_metric") or not got_rows)
        if c.get("must_match"):
            checks["mentions"] = bool(re.search(c["must_match"], out["answer"], re.I))
    else:
        checks["tool"] = bool(last and last["tool"] == c["tool"])
        sc = (last or {}).get("scope", {})
        checks["scope"] = bool(last and all(str(sc.get(k, "")).startswith(v) for k, v in c["scope"].items()))
        checks["period"] = bool(last and (c.get("period_any") or sc.get("period", {}).get("start") == "2026-11-17"))
        checks["number"] = (all if c["id"] == "pilot_worst_unit" else any)(e in out["answer"] for e in c["expect"])
        if c.get("must_not"):
            checks["must_not"] = not re.search(c["must_not"], out["answer"])
        if c["id"] == "top_unit_survey":
            checks["survey"] = "Satisfação" in out["answer"]
            checks["coverage_warned"] = "Só há dados" in out["answer"]
    return {"id": c["id"], "pass": all(checks.values()), "checks": checks, "secs": round(time.time() - t0, 1),
            "answer": out["answer"][:240], "calls": [(t["tool"], t["args"]) for t in out["trace"]],
            "blocked_numbers": out.get("blocked_numbers", []), "ungrounded": out.get("ungrounded", False),
            "context": out.get("context", [])}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs", type=int, default=1)
    ap.add_argument("--out", type=Path)
    ap.add_argument("--set", choices=["dev", "holdout", "all"], default="dev",
                    help="dev: casos usados no ajuste; holdout: perguntas novas; all: ambos")
    a = ap.parse_args()
    results = []
    cases = {"dev": CASES, "holdout": HOLDOUT, "all": CASES + HOLDOUT}[a.set]
    for r in range(a.runs):
        for c in cases:
            res = run_case(c)
            res["run"] = r
            results.append(res)
            mark = "PASS" if res["pass"] else "FAIL"
            print(f"[{mark}] {res['id']:<15} {res['secs']:>5}s {res.get('checks', res.get('error'))}", flush=True)
    passed = sum(r["pass"] for r in results)
    blocked = sum(bool(r.get("blocked_numbers")) for r in results)
    for cid in dict.fromkeys(r["id"] for r in results):
        rs = [r for r in results if r["id"] == cid]
        if not all(r["pass"] for r in rs):
            print(f"  falhou: {cid} {sum(r['pass'] for r in rs)}/{len(rs)}")
    print(f"\nguardrail de números bloqueou {blocked} resposta(s)")
    print(f"modelo {agent.MODEL}: {passed}/{len(results)} casos ({100 * passed / len(results):.0f}%), "
          f"tempo médio {sum(r['secs'] for r in results) / len(results):.1f}s")
    if a.out:
        a.out.write_text(json.dumps(results, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
