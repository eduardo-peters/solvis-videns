"""Comandos de atalho: `setup` (primeiro uso: credencial, mês inicial, texto LGPD, contexto do cliente), `update` (/atualizar) e `unit` (/unidade).

`unit` e `update` só combinam chamadas que já existem (resolve, query, sync); nenhum número é calculado aqui.
"""

from __future__ import annotations

import datetime as dt
import sys
from typing import Any, Dict, List, Optional

from . import brand, client_context, periods, privacy
from .api import ApiClient
from .config import (ENV_BASE_URL, ENV_PASSWORD, ENV_USERNAME, credentials_source, data_dir, env_file,
                     load_settings, parse_env_file, workdir, write_env_file)
from .errors import EXIT_API, EngineError
from .query import QueryEngine, QuerySpec
from .resolve import resolve
from .store import Store
from .sync import set_start_month, start_month_info

CONTEXT_ASK_STEP = ("Peça ao usuário uma descrição de quem é o cliente, para que servem as pesquisas, metas, "
                    "sazonalidade e o que mais ajudar a analisar os dados; escreva em Markdown e rode "
                    "`context --file -` (ou `context --none` se ele preferir não descrever).")
REFRESH_MARK = "update_refreshed_at:{}"
REFRESH_SKIP_S = 1800   # /atualizar repetido em menos de 30 min não baixa de novo os dias recentes
UNIT_MAX_SURVEYS = 5
UNIT_MAX_QUESTIONS = 4
# erros que só invalidam um item do relatório; os demais (sync_incomplete, mês inicial...) interrompem
ITEM_ERRORS = ("unsupported_combination", "ambiguous_question_text", "metric_not_available")


# ------------------------------------------------------------------- setup
def cmd_setup(args, _ctx) -> Dict[str, Any]:
    """Sem argumentos: mostra a situação. Com --username/--password: testa o login e grava no .env."""
    saved = False
    if args.username or args.password:
        if not (args.username and args.password):
            raise EngineError("invalid_argument", "Informe --username e --password juntos.")
        password = sys.stdin.readline().rstrip("\r\n") if args.password == "-" else args.password
        if not password:
            raise EngineError("invalid_argument", "Senha vazia.")
        current = parse_env_file(env_file()).get(ENV_USERNAME)
        if current and current != args.username and not args.replace_client:
            raise EngineError(
                "client_mismatch",
                f"Esta pasta de trabalho já é de outro cliente (credencial `{current}`). "
                "Um cliente por pasta: abra outra pasta para este cliente.",
                hint=("Só se o usuário pedir explicitamente para trocar o cliente desta pasta, rode de novo com "
                      "`--replace-client` (o contexto, a marca e o cache do cliente anterior continuam na pasta; "
                      "use `purge --yes`, `context --clear` e `brand --clear` para apagá-los)."),
            )
        candidate = load_settings(username=args.username, password=password, base_url=args.base_url or "")
        ApiClient(candidate).check_login()   # auth_failed: nada é gravado
        values = {ENV_USERNAME: args.username, ENV_PASSWORD: password}
        if args.base_url:
            values[ENV_BASE_URL] = args.base_url
        write_env_file(values)
        saved = True

    source = credentials_source()
    body: Dict[str, Any] = {"workdir": str(workdir()), "data_dir": str(data_dir()),
                            "credentials_configured": source is not None, "credentials_source": source,
                            "env_file": str(env_file()), "saved": saved}
    if saved and source == "environment":
        body["warning"] = ("As variáveis SOLVIS_API_USERNAME/PASSWORD do ambiente têm prioridade sobre o .env: "
                           "a credencial gravada só vale quando elas forem removidas.")
    if source is None:
        if args.start_month:
            raise EngineError("missing_credentials", "Configure a credencial antes do mês inicial.", exit_code=EXIT_API)
        body["next_step"] = "Peça ao usuário o usuário e a senha da API e rode `setup --username U --password -`."
        return body

    s = load_settings()
    body["username"] = s.username
    store = Store(s.cache_dir)
    if args.start_month:
        set_start_month(store, args.start_month, s.today)
    body.update(start_month_info(store))
    if args.lgpd_text:
        body.update(privacy.set_lgpd_text(store, args.lgpd_text))
    body.update(privacy.lgpd_info(store))
    body["brand_profile"] = brand.status()
    body["client_context"] = client_context.status()
    pending = None
    if not body["start_month"]:
        pending = "Pergunte a partir de que mês analisar e rode `setup --start-month AAAA-MM`."
    elif not body["lgpd_text_decided"]:
        pending = privacy.LGPD_ASK_STEP
    elif body["client_context"]["status"] == "not_asked":
        pending = CONTEXT_ASK_STEP
    if pending:   # a nota de recarga do cache (texto LGPD) vem antes do próximo passo
        body["next_step"] = (body["next_step"] + " Em seguida: " + pending) if body.get("next_step") else pending
    return body


# ------------------------------------------------------------------ update
def _active_survey_ids(ctx, today: dt.date) -> List[Dict[str, Any]]:
    since = (today - dt.timedelta(days=89)).isoformat()
    index = [s for s in ctx.catalog.survey_index() if not s["archived"] and (s["last_evaluation_date"] or "") >= since]
    return sorted(index, key=lambda s: s["last_evaluation_date"] or "", reverse=True)


def cmd_update(args, ctx) -> Dict[str, Any]:
    """Atualiza cadastros e baixa o que falta; os últimos --days dias são baixados de novo (pega tags novas)."""
    t0 = dt.datetime.now(dt.timezone.utc)
    budget = float(args.budget or ctx.syncer.budget_s)
    today = ctx.s.today
    ctx.catalog.survey_index(refresh=True)
    ctx.catalog.units(refresh=True)
    first = start_month_info(ctx.store)["earliest_day"]
    if not first:   # mesma recusa e mesma orientação do sync
        ctx.syncer._check_start_month(today)
    start = dt.date.fromisoformat(first)
    recent_start = max(start, today - dt.timedelta(days=max(1, args.days) - 1))

    if args.survey:
        ctx.catalog.require_survey(args.survey)
        targets = [{"id": args.survey, "name": ctx.catalog.require_survey(args.survey).survey_name}]
    else:
        targets = _active_survey_ids(ctx, today)

    results: List[Dict[str, Any]] = []
    for s in targets:
        left = budget - (dt.datetime.now(dt.timezone.utc) - t0).total_seconds()
        item: Dict[str, Any] = {"survey_id": s["id"], "name": s["name"]}
        if left <= 1:
            item.update(complete=False, skipped="sem tempo nesta rodada")
            results.append(item)
            continue
        ctx.syncer.budget_s = left
        mark = REFRESH_MARK.format(s["id"])
        last = ctx.store.get_meta(mark)
        age = (dt.datetime.now(dt.timezone.utc) - dt.datetime.fromisoformat(last)).total_seconds() if last else None
        refreshed = age is not None and age < REFRESH_SKIP_S and not args.force
        reports = []
        if not refreshed:
            rep = ctx.syncer.ensure(s["id"], recent_start, today, refresh=True)
            reports.append(rep)
            if rep["complete"]:
                ctx.store.set_meta(mark, dt.datetime.now(dt.timezone.utc).isoformat())
        if refreshed or reports[-1]["complete"]:
            ctx.syncer.budget_s = max(1.0, budget - (dt.datetime.now(dt.timezone.utc) - t0).total_seconds())
            reports.append(ctx.syncer.ensure(s["id"], start, today))   # preenche o que falta desde o mês inicial
        item.update(
            complete=reports[-1]["complete"] and all(r["complete"] for r in reports),
            recent_days_refreshed=not refreshed and reports[0]["complete"],
            days_fetched=sum(r["days_fetched"] + r["days_updated_incrementally"] for r in reports),
            days_remaining=reports[-1]["days_remaining"],
            failed_windows=[w for r in reports for w in r["failed_windows"]],
        )
        results.append(item)

    done = all(r["complete"] for r in results)
    body: Dict[str, Any] = {
        "period": {"start": start.isoformat(), "end": today.isoformat(), "recent_refresh_from": recent_start.isoformat()},
        "catalog_refreshed": ["surveys", "units"],
        "surveys_updated": sum(1 for r in results if r["complete"]),
        "surveys_total": len(results),
        "complete": done,
        "surveys": results,
    }
    if not done:
        body["next_step"] = "Rode `update` de novo: ele continua de onde parou."
    return body


# -------------------------------------------------------------------- unit
def _compact(env: Dict[str, Any]) -> Dict[str, Any]:
    cov = env["coverage"]["period"]
    ok = not (cov["days_missing"] or cov["days_partial"] or cov["failed_windows"])
    out: Dict[str, Any] = {"query_id": env["query_id"], "totals": env["totals"],
                           "warnings": [w["code"] for w in env["warnings"]]}
    if not ok:
        out["coverage"] = env["coverage"]
    if env.get("exposure"):
        out["exposure"] = env["exposure"]
    return out


def cmd_unit(args, ctx) -> Dict[str, Any]:
    """Visão de uma unidade: volume e notas principais de cada pesquisa ativa, contra a rede toda."""
    if args.unit_id is None and not args.text:
        raise EngineError("invalid_argument", "Informe o nome/código da unidade ou --unit-id.")
    if args.unit_id is not None:
        found = [u for u in ctx.catalog.units() if u["id"] == args.unit_id]
        if not found:
            raise EngineError("not_found", f"Unidade {args.unit_id} não está disponível para esta credencial.")
        unit = {"id": found[0]["id"], "label": found[0]["name"], "code": found[0]["code"],
                "city": found[0]["city"], "state": found[0]["state"]}
    else:
        res = resolve("unit", args.text, ctx.catalog, ctx.store)
        cands = res["candidates"]
        exact = [c for c in cands if c["match"] == "exact"]
        pick = exact if exact else cands
        if len(pick) != 1:
            return {"needs_choice": True, "text": args.text, "candidates": cands,
                    "note": "Nenhuma unidade encontrada." if not cands else
                            "Mais de uma unidade casa com o texto: pergunte ao usuário qual e rode de novo com --unit-id."}
        unit = {k: v for k, v in pick[0].items() if k != "match"}

    period = periods.resolve_period(ctx.s.today, args.period, args.start, args.end)
    if args.survey:
        surveys = [{"id": args.survey, "name": ctx.catalog.require_survey(args.survey).survey_name}]
    else:
        surveys = [s for s in _active_survey_ids(ctx, ctx.s.today)
                   if (s["last_evaluation_date"] or "") >= period.start.isoformat()][:UNIT_MAX_SURVEYS]

    engine = QueryEngine(ctx.store, ctx.catalog, ctx.syncer, ctx.s)
    common = dict(preset=args.period, start=args.start, end=args.end, compare_with="previous_period")

    def run(metric: str, sid: int, qid: Optional[int], units: List[int]) -> Dict[str, Any]:
        return engine.run(QuerySpec(metric=metric, survey_id=sid, question_id=qid, unit_ids=units, **common))

    out_surveys: List[Dict[str, Any]] = []
    meta: Dict[str, Any] = {}
    for s in surveys:
        qn = ctx.catalog.require_survey(s["id"])
        count = run("evaluation_count", s["id"], None, [unit["id"]])
        meta = {"period": count["period"], "comparison": count.get("comparison")}
        item: Dict[str, Any] = {"survey": {"id": s["id"], "name": s["name"]}, "evaluation_count": _compact(count),
                                "questions": []}
        if count["totals"]["value"]:
            item["network_evaluation_count"] = _compact(run("evaluation_count", s["id"], None, []))
            main = [q for q in qn.questions if q.answer_type in ("NPS", "Scale") and not q.lgpd_protected
                    and q.id not in qn.ambiguous_ids][:UNIT_MAX_QUESTIONS]
            for q in main:
                sm = q.summary()
                entry: Dict[str, Any] = {"question": {"id": q.id, "number": q.number, "text": q.label,
                                                      "answer_type": q.answer_type}, "metric": sm["metric"]}
                try:
                    entry["unit"] = _compact(run(sm["metric"], s["id"], q.id, [unit["id"]]))
                    entry["network"] = _compact(run(sm["metric"], s["id"], q.id, []))
                except EngineError as exc:
                    if exc.code not in ITEM_ERRORS:
                        raise
                    entry["error"] = exc.to_dict()["error"]
                item["questions"].append(entry)
        else:
            item["note"] = "Sem avaliações da unidade nesta pesquisa no período."
        out_surveys.append(item)

    return {"unit": unit, **meta, "surveys": out_surveys,
            "notes": ["Cada pergunta vem com a unidade (`unit`) e a rede inteira (`network`, mesma pesquisa e período).",
                      "Pesquisas: as ativas no período (até %d); use --survey para outra." % UNIT_MAX_SURVEYS,
                      "Para aprofundar: query --group-by day_of_week|hour_block|channel e comments, com --unit."]}
