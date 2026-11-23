"""Linha de comando do motor. Toda saída é JSON em stdout; erros também.

Comandos: scope, config, setup, brand, context, questionnaire, units, unit, resolve, query, comments, sync, update, explain, validate, model, purge.
Referência completa: references/cli.md.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import shutil
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

from . import ENGINE_VERSION, MODEL_VERSION, periods, privacy
from . import store as store_mod
from .api import ApiClient
from .catalog import Catalog
from .comments import CommentSpec, list_comments
from .config import Settings, cache_root, load_settings, workdir
from .errors import EngineError
from .query import METRICS, NOT_AVAILABLE, QueryEngine, QuerySpec, find_query
from .resolve import resolve
from .brand import cmd_brand
from .client_context import cmd_context
from .shortcuts import cmd_setup, cmd_unit, cmd_update
from .store import Store
from .sync import Syncer, coverage, set_start_month, start_month_info
from .verify import Validator


def _ints(values: Optional[List[str]]) -> List[int]:
    out: List[int] = []
    for v in values or []:
        for part in str(v).split(","):
            part = part.strip()
            if part:
                if not part.lstrip("-").isdigit():
                    raise EngineError("invalid_argument", f"Esperava id numérico, recebi {part!r}.")
                out.append(int(part))
    return out


def _strs(values: Optional[List[str]]) -> List[str]:
    return [p.strip() for v in values or [] for p in str(v).split(",") if p.strip()]


class Context:
    def __init__(self, args: argparse.Namespace) -> None:
        self.s: Settings = load_settings()
        self.store = Store(self.s.cache_dir)
        self.api = ApiClient(self.s)
        self.catalog = Catalog(self.store, self.api)
        self.syncer = Syncer(self.store, self.api, self.catalog, self.s, getattr(args, "budget", None))


# ------------------------------------------------------------------ comandos
def cmd_scope(args, ctx: Context) -> Dict[str, Any]:
    index = ctx.catalog.survey_index(refresh=args.refresh)
    units = ctx.catalog.units(refresh=args.refresh)
    props = ctx.catalog.property_names()
    since = (ctx.s.today - dt.timedelta(days=89)).isoformat()
    active = [s for s in index if not s["archived"] and (s["last_evaluation_date"] or "") >= since]
    recent = sorted(active, key=lambda s: s["last_evaluation_date"] or "", reverse=True)[:15]
    return {
        "engine_version": ENGINE_VERSION,
        "model_version": MODEL_VERSION,
        "api": ctx.s.base_url,
        "workdir": str(workdir()),
        "username": ctx.s.username,
        "today": ctx.s.today.isoformat(),
        **start_month_info(ctx.store),
        "surveys": {
            "total": len(index),
            "archived": sum(1 for s in index if s["archived"]),
            "active_last_90_days": len(active),
            "most_recent": recent,
        },
        "units": {"count": len(units), "states": sorted({u["state"] for u in units if u.get("state")})},
        "unit_properties": [{"id": nid, "name": m["name"], "values": len(m["values"])} for nid, m in props.items()],
        "capabilities": {
            "comments": True,
            "tags": "tags aplicadas (por pessoas ou pelo Radar), sem a base de comentários analisados",
            "comment_tone": False,
            "data_quality": "só o resultado (confiável, reprovada, não verificada); regras violadas não saem na API",
            "lgpd_texts": privacy.lgpd_text_enabled(ctx.store),
        },
        "notes": [
            "Use `surveys --search <nome>` para achar outras pesquisas.",
            "evaluation_count_all_time é um contador em cache da API (histórico inteiro, pode estar defasado). "
            "Não use como número de análise: consulte query --metric evaluation_count.",
        ],
    }


def cmd_surveys(args, ctx: Context) -> Dict[str, Any]:
    index = ctx.catalog.survey_index(refresh=args.refresh)
    items = [s for s in index if args.include_archived or not s["archived"]]
    if args.search:
        found = resolve("survey", args.search, ctx.catalog, ctx.store)
        rank = {c["id"]: i for i, c in enumerate(found["candidates"])}
        items = sorted((s for s in items if s["id"] in rank), key=lambda s: rank[s["id"]])
    else:
        items = sorted(items, key=lambda s: s["last_evaluation_date"] or "", reverse=True)
    if args.active_in:
        since = periods.resolve_period(ctx.s.today, args.active_in).start.isoformat()
        items = [s for s in items if (s["last_evaluation_date"] or "") >= since]
    body: Dict[str, Any] = {"count": len(items), "surveys": items[: args.limit]}
    if args.active_in:
        body["active_since"] = since
        body["note"] = ("Filtra pela data da última avaliação registrada na pesquisa. Para saber quantas avaliações "
                        "cada uma teve no período, use query --metric evaluation_count por pesquisa.")
    if len(items) > args.limit:
        body["truncated"] = True
    return body


def cmd_questionnaire(args, ctx: Context) -> Dict[str, Any]:
    qn = ctx.catalog.refresh_questionnaire(args.survey) if args.refresh else ctx.catalog.require_survey(args.survey)
    return qn.summary()


def cmd_units(args, ctx: Context) -> Dict[str, Any]:
    units = ctx.catalog.units(refresh=args.refresh)
    out = units
    if args.search:
        found = resolve("unit", args.search, ctx.catalog, ctx.store)
        ids = {c["id"] for c in found["candidates"]}
        out = [u for u in units if u["id"] in ids]
    body: Dict[str, Any] = {"count": len(out), "units": out[: args.limit]}
    if len(out) > args.limit:
        body["truncated"] = True
    if args.properties:
        body["unit_properties"] = [
            {"id": nid, "name": m["name"], "values": [{"id": vid, "value": v} for vid, v in m["values"].items()]}
            for nid, m in ctx.catalog.property_names().items()
        ]
    body["notes"] = ["Cidade, UF e propriedades são do cadastro atual e valem para todo o histórico da unidade."]
    return body


def cmd_config(args, ctx: Context) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    if args.start_month:
        out.update(set_start_month(ctx.store, args.start_month, ctx.s.today))
    else:
        out.update(start_month_info(ctx.store))
    if args.lgpd_text:
        out.update(privacy.set_lgpd_text(ctx.store, args.lgpd_text))
    out.update(privacy.lgpd_info(ctx.store))
    return out


def cmd_resolve(args, ctx: Context) -> Dict[str, Any]:
    return resolve(args.kind, args.text, ctx.catalog, ctx.store, args.survey, args.question)


def cmd_sync(args, ctx: Context) -> Dict[str, Any]:
    period = periods.resolve_period(ctx.s.today, args.period, args.start, args.end)
    report = ctx.syncer.ensure(args.survey, period.start, period.end, refresh=args.refresh)
    rounds = 1
    while getattr(args, "until_complete", False) and not report["complete"]:
        # repete rodadas de `budget` segundos até terminar; para se uma rodada não avançar
        nxt = ctx.syncer.ensure(args.survey, period.start, period.end, refresh=False)
        rounds += 1
        progressed = nxt["days_fetched"] > 0 or nxt["days_updated_incrementally"] > 0
        for k in ("days_fetched", "days_updated_incrementally", "api_calls", "elapsed_s"):
            nxt[k] = round(report[k] + nxt[k], 1) if k == "elapsed_s" else report[k] + nxt[k]
        nxt["failed_windows"] = report["failed_windows"] + nxt["failed_windows"]
        nxt["questionnaire_refreshed"] = report["questionnaire_refreshed"] or nxt["questionnaire_refreshed"]
        report = nxt
        if not progressed:
            break
    report["rounds"] = rounds
    report["coverage"] = coverage(ctx.store, args.survey, period.start, period.end, ctx.s.today)
    if not report["complete"]:
        report["next_step"] = "Rode o mesmo comando de novo para continuar o download."
    return report


def cmd_query(args, ctx: Context) -> Dict[str, Any]:
    spec = QuerySpec(
        metric=args.metric, survey_id=args.survey, question_id=args.question,
        preset=args.period, start=args.start, end=args.end, compare_with=args.compare_with,
        group_by=_strs(args.group_by), unit_ids=_ints(args.unit), property_value_ids=_ints(args.property_value),
        channel=args.channel, completion=args.completion, reliability=args.reliability,
        nps_groups=_strs(args.nps_group), reference_question_id=args.reference_question,
        reference_choice_ids=_ints(args.choice_filter), tag_ids=_ints(args.tag), choice_ids=_ints(args.choices),
        order=args.order, limit=args.limit, min_n=args.min_n, locale=args.locale, refresh=args.refresh,
        composition_check=args.composition_check,
    )
    return QueryEngine(ctx.store, ctx.catalog, ctx.syncer, ctx.s).run(spec)


def cmd_comments(args, ctx: Context) -> Dict[str, Any]:
    spec = CommentSpec(
        survey_id=args.survey, preset=args.period, start=args.start, end=args.end, question_id=args.question,
        unit_ids=_ints(args.unit), nps_groups=_strs(args.nps_group), reference_question_id=args.reference_question,
        tag_ids=_ints(args.tag), contains=args.contains, include_additional=not args.no_additional,
        reliability=args.reliability, limit=args.limit, refresh=args.refresh,
    )
    return list_comments(spec, ctx.store, ctx.catalog, ctx.syncer, ctx.s)


def cmd_explain(args, _ctx: Optional[Context]) -> Dict[str, Any]:
    s = load_settings()
    record = find_query(s, args.query_id)
    if not record:
        raise EngineError("not_found", f"Consulta {args.query_id} não encontrada no registro local.")
    return record


def cmd_validate(args, ctx: Context) -> Dict[str, Any]:
    raw = sys.stdin.read() if args.claims == "-" else Path(args.claims).read_text(encoding="utf-8")
    try:
        payload = json.loads(raw)
    except ValueError as exc:
        raise EngineError("invalid_argument", f"O arquivo de afirmações não é um JSON válido: {exc}.")
    return Validator(ctx.store, ctx.catalog, ctx.s).run(payload, args.locale)


def cmd_model(_args, _ctx) -> Dict[str, Any]:
    return {
        "engine_version": ENGINE_VERSION,
        "model_version": MODEL_VERSION,
        "metrics": {k: {"label": v["label"], "unit": v["unit"], "question": v["question"],
                        **({"answer_types": list(v["types"])} if v.get("types") else {})} for k, v in METRICS.items()},
        "not_available": NOT_AVAILABLE,
        "group_by": ["unit", "unit_property:<property_name_id>", "unit_state", "day", "week", "month", "quarter",
                     "day_of_week", "hour_block[:1|2|3|4|6|8|12]", "channel", "completion", "reliability",
                     "nps_group[:<question_id>]", "choice:<question_id>"],
        "period_presets": list(periods.PRESETS),
        "compare_with": ["previous_period", "previous_year"],
        "reference": "Definições completas em references/metrics.yaml e references/dimensions.yaml.",
    }


def cmd_purge(args, _ctx) -> Dict[str, Any]:
    if not args.yes:
        raise EngineError("confirmation_required", "purge apaga o cache local, o token e o registro de consultas.",
                          hint="Confirme com o usuário e rode `purge --yes`.")
    root = cache_root()
    if root and root.exists():
        shutil.rmtree(root)
        return {"purged": str(root)}
    return {"purged": None, "note": "Não havia cache local."}


# ------------------------------------------------------------------- parser
def _period_args(p: argparse.ArgumentParser) -> None:
    p.add_argument("--period", help="preset: " + ", ".join(periods.PRESETS) + f" (padrão {periods.DEFAULT_PRESET})")
    p.add_argument("--start", help="AAAA-MM-DD (com --end)")
    p.add_argument("--end", help="AAAA-MM-DD (com --start)")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="solvis.py", description="Motor local da skill solvis-videns")
    parser.add_argument("--pretty", action="store_true", help="JSON indentado")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("scope", help="resumo do que a credencial vê: pesquisas ativas, unidades, capacidades")
    p.add_argument("--refresh", action="store_true")

    p = sub.add_parser("surveys", help="lista ou busca pesquisas (mais recentes primeiro)")
    p.add_argument("--search", help="parte do nome (sem diferenciar acento e caixa)")
    p.add_argument("--active-in", help="preset de período (ex.: last_90_days): só pesquisas com avaliação nele")
    p.add_argument("--include-archived", action="store_true")
    p.add_argument("--limit", type=int, default=30)
    p.add_argument("--refresh", action="store_true")

    p = sub.add_parser("questionnaire", help="perguntas, tipos, escalas e alternativas de uma pesquisa")
    p.add_argument("--survey", type=int, required=True)
    p.add_argument("--refresh", action="store_true")

    p = sub.add_parser("units", help="unidades com cidade, UF e propriedades")
    p.add_argument("--search")
    p.add_argument("--properties", action="store_true", help="lista nomes e valores de propriedades")
    p.add_argument("--limit", type=int, default=200)
    p.add_argument("--refresh", action="store_true")

    p = sub.add_parser("config", help="mostra ou define o mês inicial da análise e a política de texto LGPD")
    p.add_argument("--lgpd-text", choices=["on", "off"],
                   help="decisão do usuário sobre o texto de perguntas protegidas por LGPD: on guarda (mascarado), "
                        "off não guarda; registrada em lgpd_text_decided. Mudar a política limpa o cache")
    p.add_argument("--start-month", help="AAAA-MM")

    p = sub.add_parser("resolve", help="texto -> candidatos com id")
    p.add_argument("--kind", required=True, choices=["survey", "question", "choice", "unit", "property", "property_value", "tag"])
    p.add_argument("--text", required=True)
    p.add_argument("--survey", type=int)
    p.add_argument("--question", type=int)

    p = sub.add_parser("sync", help="baixa avaliações de um período para o cache (retomável)")
    p.add_argument("--survey", type=int, required=True)
    _period_args(p)
    p.add_argument("--refresh", action="store_true", help="baixa de novo mesmo o que está em cache")
    p.add_argument("--budget", type=float, help="segundos máximos de cada rodada (padrão 90)")
    p.add_argument("--until-complete", action="store_true",
                   help="repete rodadas até o período estar completo (para se uma rodada não avançar)")

    p = sub.add_parser("query", help="calcula uma métrica e devolve o envelope de evidência")
    p.add_argument("--metric", required=True)
    p.add_argument("--survey", type=int, required=True)
    p.add_argument("--question", type=int)
    _period_args(p)
    p.add_argument("--compare-with", choices=["previous_period", "previous_year"])
    p.add_argument("--group-by", action="append", help="até 2, separados por vírgula ou repetidos")
    p.add_argument("--unit", action="append", help="ids de unidade")
    p.add_argument("--property-value", action="append", help="ids de valor de propriedade")
    p.add_argument("--channel", choices=["device", "web"])
    p.add_argument("--completion", default="all", choices=["all", "completed", "incomplete"])
    p.add_argument("--reliability", default="all",
                   choices=["all", "reliable_only", "unreliable_only", "unclassified_only"])
    p.add_argument("--nps-group", action="append", help="promoter, passive, detractor (grupo do respondente)")
    p.add_argument("--reference-question", type=int, help="pergunta NPS de referência para nps_group")
    p.add_argument("--choice-filter", action="append", help="ids de alternativas de outra pergunta (avaliações que as marcaram)")
    p.add_argument("--tag", action="append", help="ids de tag (avaliações com a tag em qualquer pergunta)")
    p.add_argument("--choices", action="append", help="conjunto de alternativas para choice_set_share")
    p.add_argument("--order", help="value|n|delta com :asc ou :desc (padrão desc)")
    p.add_argument("--limit", type=int, default=50)
    p.add_argument("--min-n", type=int)
    p.add_argument("--composition-check", action="store_true",
                   help="teste de painel fixo da tendência (exige --group-by de tempo; nps ou choice_set_share)")
    p.add_argument("--locale", default="pt", choices=["pt", "en", "es"])
    p.add_argument("--refresh", action="store_true")
    p.add_argument("--budget", type=float)

    p = sub.add_parser("comments", help="comentários mascarados, mais recentes primeiro")
    p.add_argument("--survey", type=int, required=True)
    _period_args(p)
    p.add_argument("--question", type=int)
    p.add_argument("--unit", action="append")
    p.add_argument("--nps-group", action="append")
    p.add_argument("--reference-question", type=int)
    p.add_argument("--tag", action="append")
    p.add_argument("--contains", help="trecho de texto (sem diferenciar acento e caixa)")
    p.add_argument("--no-additional", action="store_true", help="exclui textos de campos adicionais (Outro: ___)")
    p.add_argument("--reliability", default="all", choices=["all", "reliable_only"])
    p.add_argument("--limit", type=int, default=20)
    p.add_argument("--refresh", action="store_true")
    p.add_argument("--budget", type=float)

    p = sub.add_parser("setup", help="primeiro uso: testa e grava a credencial no .env, define o mês inicial e a decisão sobre texto LGPD; sem argumentos mostra a situação")
    p.add_argument("--username")
    p.add_argument("--password", help="a senha, ou - para ler da entrada padrão (preferível: não aparece na lista de processos)")
    p.add_argument("--base-url", help="só se a Solvis indicar outro endereço")
    p.add_argument("--start-month", help="AAAA-MM")
    p.add_argument("--lgpd-text", choices=["on", "off"],
                   help="resposta do usuário à pergunta do primeiro uso: guardar (mascarado) o texto de perguntas LGPD?")
    p.add_argument("--replace-client", action="store_true",
                   help="troca a credencial desta pasta por outro cliente (só com pedido explícito do usuário)")

    p = sub.add_parser("brand", help="perfil de marca do cliente (materiais de referência para relatórios e decks); "
                                        "sem argumentos mostra o perfil e os arquivos guardados")
    p.add_argument("--file", help="JSON do perfil (ou - para ler da entrada padrão); mescla com o perfil atual")
    p.add_argument("--asset", action="append", help="copia um arquivo (logo, fonte, modelo) para a pasta da marca; repetível")
    p.add_argument("--none", action="store_true", help="registra que o usuário não tem materiais de referência (estilo neutro)")
    p.add_argument("--clear", action="store_true", help="apaga o perfil e os arquivos da marca")

    p = sub.add_parser("context", help="contexto do cliente (quem é, finalidade das pesquisas, metas, sazonalidade...) "
                                          "escrito pela skill no primeiro uso; sem argumentos mostra o texto")
    p.add_argument("--file", help="Markdown do contexto (ou - para ler da entrada padrão); substitui o atual")
    p.add_argument("--append", action="store_true", help="com --file: acrescenta ao contexto atual em vez de substituir")
    p.add_argument("--none", action="store_true", help="registra que o usuário preferiu não descrever o cliente")
    p.add_argument("--clear", action="store_true", help="apaga o contexto")

    p = sub.add_parser("unit", help="visão de uma unidade: volume e notas principais por pesquisa ativa, contra a rede")
    p.add_argument("text", nargs="?", help="nome ou código da unidade")
    p.add_argument("--unit-id", type=int)
    p.add_argument("--survey", type=int, help="só esta pesquisa (padrão: as ativas no período, até 5)")
    _period_args(p)

    p = sub.add_parser("update", help="atualiza cadastros e baixa dados novos das pesquisas ativas (retomável)")
    p.add_argument("--survey", type=int, help="só esta pesquisa")
    p.add_argument("--days", type=int, default=7, help="quantos dias recentes baixar de novo (padrão 7; pega tags novas)")
    p.add_argument("--force", action="store_true", help="baixa de novo os dias recentes mesmo se acabou de fazer")
    p.add_argument("--budget", type=float, help="segundos máximos desta rodada (padrão 90)")

    p = sub.add_parser("explain", help="reabre uma consulta pelo query_id")
    p.add_argument("--query-id", required=True)

    p = sub.add_parser("validate", help="confere as afirmações de um material gerado contra o cache e devolve o parecer")
    p.add_argument("--claims", required=True, help="arquivo JSON com as afirmações, ou - para a entrada padrão")
    p.add_argument("--locale", default="pt", choices=["pt", "en", "es"], help="formato dos números mostrados no material")

    sub.add_parser("model", help="métricas, recortes e presets disponíveis")

    p = sub.add_parser("purge", help="apaga cache local, token e registro de consultas")
    p.add_argument("--yes", action="store_true")
    return parser


COMMANDS = {
    "scope": cmd_scope, "surveys": cmd_surveys, "questionnaire": cmd_questionnaire, "units": cmd_units,
    "config": cmd_config, "resolve": cmd_resolve, "sync": cmd_sync, "query": cmd_query, "comments": cmd_comments, "explain": cmd_explain,
    "model": cmd_model, "validate": cmd_validate, "purge": cmd_purge, "setup": cmd_setup, "unit": cmd_unit, "update": cmd_update, "brand": cmd_brand, "context": cmd_context,
}
NO_CONTEXT = ("explain", "model", "purge", "setup", "brand", "context")


def main(argv: Optional[List[str]] = None) -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    except (AttributeError, ValueError):
        pass
    parser = build_parser()
    args = parser.parse_args(argv)
    indent = 2 if args.pretty else None
    try:
        ctx = None if args.command in NO_CONTEXT else Context(args)
        result = COMMANDS[args.command](args, ctx)
        print(json.dumps(result, ensure_ascii=False, indent=indent, default=str))
        return 0
    except EngineError as exc:
        print(json.dumps(exc.to_dict(), ensure_ascii=False, indent=indent, default=str))
        return exc.exit_code
