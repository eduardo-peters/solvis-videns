"""Consulta de métricas sobre o cache normalizado, com envelope de evidência.

O envelope tem a mesma forma do contrato planejado da API Analytics v1
(query_id, metric, scope, period, comparison, filters, policies, coverage,
freshness, rows, totals, warnings), para a skill não mudar quando o cálculo
passar para o servidor.
"""

from __future__ import annotations

import datetime as dt
import json
import secrets
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Tuple

from . import ENGINE_VERSION, MODEL_VERSION, fmt, measures, periods
from .catalog import Catalog
from .config import Settings, local_time
from .errors import EXIT_SYNC, EngineError
from .semantics import CHOICE_TYPES, OPEN_TEXT_TYPES, Question, Questionnaire
from .store import Store
from .sync import Syncer, coverage

METRICS: Dict[str, Dict[str, Any]] = {
    "evaluation_count": {"label": "Avaliações", "unit": "count", "question": "none"},
    "response_count": {"label": "Respostas à pergunta", "unit": "count", "question": "required"},
    "nps": {"label": "NPS", "unit": "points", "question": "required", "types": ("NPS",)},
    "scale_mean": {"label": "Média da escala", "unit": "scale", "question": "required", "types": ("Scale",)},
    "weighted_sum": {"label": "Soma ponderada", "unit": "weighted_sum", "question": "required", "types": ("Scale",)},
    "choice_share": {"label": "Distribuição das alternativas", "unit": "percent", "question": "required",
                     "types": CHOICE_TYPES, "distribution": True},
    "choice_set_share": {"label": "Parte num conjunto de alternativas", "unit": "percent", "question": "required",
                         "types": CHOICE_TYPES},
    "multi_response_share": {"label": "Distribuição de múltipla resposta", "unit": "percent",
                             "question": "required", "types": ("Multiple Response",), "distribution": True},
    "tag_mentions": {"label": "Menções de tags", "unit": "percent", "question": "optional", "distribution": True},
    "data_quality_summary": {"label": "Qualidade de dados", "unit": "count", "question": "none"},
}

NOT_AVAILABLE: Dict[str, str] = {
    "csat": "O sistema não tem métrica CSAT. Use scale_mean, weighted_sum ou choice_set_share da pergunta que o "
            "cliente chama de CSAT e declare o mapeamento.",
    "ces": "Não há métrica de esforço. Mesmo tratamento do CSAT, se houver pergunta de escala correspondente.",
    "response_rate": "Não há denominador (convidados, visitantes, envios) na API.",
    "abandonment_rate": "Não há métrica de abandono. Use evaluation_count com group_by completion, sem chamar de taxa de abandono.",
    "numeric_mean": "Perguntas Numeric não têm agregação no sistema; a API nem expõe o valor ao motor.",
    "comment_tone": "O tom do Radar de Comentários não sai na API pública V1. Use tag_mentions e comments.",
    "sentiment": "O tom do Radar de Comentários não sai na API pública V1; os sentimentos da API V2 exigem um id de resposta que a V1 não expõe.",
    "theme_mentions": "A base de comentários analisados pelo Radar não sai na API pública. Use tag_mentions (tags aplicadas por pessoas ou pelo Radar).",
    "radar_summary_gut": "Resumo, sugestão e matriz GUT do Radar não saem na API pública. Use comments.",
    "shift": "Turno não sai na API pública. Use --group-by hour_block.",
    "market_benchmark": "A base não tem dados de mercado nem de outros clientes.",
    "forecast": "O motor não projeta valores futuros.",
}

DIM_SIMPLE = ("unit", "unit_state", "channel", "completion", "reliability", "day_of_week") + periods.TIME_BUCKETS
MAX_LIMIT = 500


@dataclass
class QuerySpec:
    metric: str
    survey_id: int
    question_id: Optional[int] = None
    preset: Optional[str] = None
    start: Optional[str] = None
    end: Optional[str] = None
    compare_with: Optional[str] = None
    group_by: List[str] = field(default_factory=list)
    unit_ids: List[int] = field(default_factory=list)
    property_value_ids: List[int] = field(default_factory=list)
    channel: Optional[str] = None
    completion: str = "all"
    reliability: str = "all"
    nps_groups: List[str] = field(default_factory=list)
    reference_question_id: Optional[int] = None
    reference_choice_ids: List[int] = field(default_factory=list)
    tag_ids: List[int] = field(default_factory=list)
    choice_ids: List[int] = field(default_factory=list)
    order: Optional[str] = None
    limit: int = 50
    min_n: Optional[int] = None
    locale: str = "pt"
    refresh: bool = False


@dataclass
class Dim:
    token: str
    kind: str
    param: Optional[int] = None
    select: str = ""
    join: Optional[Tuple[str, List[Any]]] = None


def _w(code: str, message: str, **extra: Any) -> Dict[str, Any]:
    body = {"code": code, "message": message}
    body.update(extra)
    return body


class QueryEngine:
    def __init__(self, store: Store, catalog: Catalog, syncer: Syncer, settings: Settings) -> None:
        self.store = store
        self.catalog = catalog
        self.syncer = syncer
        self.s = settings
        self.db = store.db

    # ============================================================ validação
    def _question(self, qn: Questionnaire, qid: Optional[int], role: str = "question") -> Question:
        if qid is None or qid not in qn.by_id:
            raise EngineError(
                "not_found",
                f"A pergunta {qid} não existe na pesquisa {qn.survey_id}.",
                hint="Leia o questionário com `questionnaire --survey <id>` e use o id da pergunta.",
            )
        return qn.by_id[qid]

    def _check_ambiguity(self, qn: Questionnaire, questions: Sequence[Question],
                         windows: Sequence[periods.Period]) -> List[Dict[str, Any]]:
        """Pergunta com tipo e texto iguais aos de outra: só calcula se toda resposta foi atribuída pela ordem."""
        warnings: List[Dict[str, Any]] = []
        for q in questions:
            if q.id not in qn.ambiguous_ids:
                continue
            group = f"{q.answer_type}|{q.text}"
            twins = [x.number for x in qn.questions if x.id in qn.ambiguous_ids and x.answer_type == q.answer_type
                     and x.text == q.text]
            assigned = unassigned = others = 0
            for w in windows:
                a, u, o = self.db.execute(
                    "SELECT SUM(CASE WHEN question_id = ? THEN 1 ELSE 0 END), "
                    "SUM(CASE WHEN question_id IS NULL THEN 1 ELSE 0 END), "
                    "SUM(CASE WHEN question_id IS NOT NULL AND question_id != ? THEN 1 ELSE 0 END) FROM answers "
                    "WHERE survey_id = ? AND qgroup = ? AND day BETWEEN ? AND ?",
                    (q.id, q.id, qn.survey_id, group, w.start.isoformat(), w.end.isoformat()),
                ).fetchone()
                assigned += a or 0
                unassigned += u or 0
                others += o or 0
            if unassigned:
                raise EngineError(
                    "ambiguous_question_text",
                    f"As perguntas {twins} têm o mesmo tipo e texto, e a API pública devolve as respostas só com o texto. "
                    f"No período há {assigned + unassigned + others} respostas com esse texto: {assigned} identificadas como "
                    f"da pergunta {q.number}, {others} como de outra pergunta gêmea e {unassigned} sem como saber de qual.",
                    hint="Diga isso ao usuário e não dê número desta pergunta nem some as gêmeas. Perguntas de outro texto "
                         "seguem disponíveis; a tela de resultados da Solvis separa as gêmeas.",
                    details={"question_numbers": twins, "this_question": assigned, "other_twins": others,
                             "unassigned": unassigned},
                )
            warnings.append(_w(
                "answers_assigned_by_order",
                f"As perguntas {twins} têm o mesmo texto; as respostas da pergunta {q.number} foram identificadas pela "
                "alternativa escolhida ou pela ordem em que vieram na avaliação (todas as do período foram identificadas).",
            ))
        return warnings

    def _validate(self, spec: QuerySpec, qn: Questionnaire) -> Optional[Question]:
        m = spec.metric
        if m in NOT_AVAILABLE:
            raise EngineError("metric_not_available", NOT_AVAILABLE[m])
        if m not in METRICS:
            raise EngineError("unknown_metric", f"Métrica desconhecida: {m}.", hint="Métricas: " + ", ".join(METRICS))
        meta = METRICS[m]
        q: Optional[Question] = None
        if meta["question"] == "required" and spec.question_id is None:
            types = meta.get("types")
            options = [{"id": x.id, "number": x.number, "text": x.label[:80]} for x in qn.questions
                       if (not types or x.answer_type in types)
                       and not (m == "scale_mean" and x.metric_kind == "weighted_sum")
                       and not (m == "weighted_sum" and x.metric_kind != "weighted_sum")]
            raise EngineError("question_required", f"A métrica {m} exige --question <id>.",
                              hint="Com mais de uma opção e o usuário sem dizer qual, veja SKILL.md (Quando perguntar).",
                              details={"applicable_questions": options[:40]})
        if meta["question"] == "none" and spec.question_id is not None:
            raise EngineError("question_not_applicable", f"A métrica {m} é da pesquisa inteira; não use --question.")
        if spec.question_id is not None:
            q = self._question(qn, spec.question_id)
            types = meta.get("types")
            if types and q.answer_type not in types:
                raise EngineError(
                    "metric_not_applicable",
                    f"A pergunta {q.number} é do tipo {q.answer_type}; {m} vale para {', '.join(types)}.",
                    hint="Veja references/question-types.md para a métrica de cada tipo.",
                )
            if m == "scale_mean" and q.metric_kind == "weighted_sum":
                raise EngineError(
                    "metric_not_applicable",
                    f"A pergunta {q.number} é configurada como soma ponderada; as telas não mostram média dela.",
                    hint="Use --metric weighted_sum.",
                )
            if m == "weighted_sum" and q.metric_kind != "weighted_sum":
                raise EngineError(
                    "metric_not_applicable",
                    f"A pergunta {q.number} não é configurada como soma ponderada.",
                    hint="Use --metric scale_mean.",
                )
            if m in ("scale_mean", "weighted_sum") and not q.valued_choices:
                raise EngineError("metric_not_applicable", f"A pergunta {q.number} não tem alternativas com valor.")
        if m == "choice_set_share":
            if not spec.choice_ids:
                raise EngineError("choices_required", "choice_set_share exige --choices <ids das alternativas do conjunto>.")
            own = {c.id for c in q.choices} if q else set()
            bad = [c for c in spec.choice_ids if c not in own]
            if bad:
                raise EngineError("not_found", f"Alternativas {bad} não são da pergunta {q.number if q else '?'}.")
        elif spec.choice_ids:
            raise EngineError("invalid_argument", "--choices só vale para choice_set_share.")
        if m == "tag_mentions" and spec.tag_ids:
            raise EngineError("invalid_argument", "Em tag_mentions, leia a linha da tag em vez de filtrar por --tag.")
        if spec.completion not in ("all", "completed", "incomplete"):
            raise EngineError("invalid_argument", "--completion aceita all, completed ou incomplete.")
        if spec.reliability not in ("all", "reliable_only", "unreliable_only", "unclassified_only"):
            raise EngineError("invalid_argument", "--reliability aceita all, reliable_only, unreliable_only ou unclassified_only.")
        if spec.channel not in (None, "device", "web"):
            raise EngineError("invalid_argument", "--channel aceita device (totem) ou web.")
        if spec.compare_with not in (None, "previous_period", "previous_year"):
            raise EngineError("invalid_comparison", "--compare-with aceita previous_period ou previous_year.")
        if not 1 <= spec.limit <= MAX_LIMIT:
            raise EngineError("invalid_argument", f"--limit vai de 1 a {MAX_LIMIT}.")
        if spec.locale not in fmt.SEPARATORS:
            raise EngineError("invalid_argument", "--locale aceita pt, en ou es.")
        return q

    def _reference_nps(self, qn: Questionnaire, explicit: Optional[int]) -> Question:
        if explicit is not None:
            q = self._question(qn, explicit)
            if q.answer_type != "NPS":
                raise EngineError("metric_not_applicable", f"A pergunta {q.number} não é NPS; grupo NPS exige pergunta NPS.")
            return q
        nps = [q for q in qn.nps_questions() if q.id not in qn.ambiguous_ids]
        if len(nps) == 1:
            return nps[0]
        if not nps:
            raise EngineError("not_found", "A pesquisa não tem pergunta NPS para definir o grupo do respondente.")
        raise EngineError(
            "reference_question_required",
            "A pesquisa tem mais de uma pergunta NPS.",
            hint="Informe qual com --reference-question <id> ou nps_group:<id>.",
            details={"nps_questions": [{"id": q.id, "number": q.number, "text": q.label} for q in nps]},
        )

    def _dims(self, spec: QuerySpec, qn: Questionnaire) -> List[Dim]:
        if len(spec.group_by) > 2:
            raise EngineError("unsupported_combination", "group_by aceita no máximo 2 recortes.")
        if len(set(spec.group_by)) != len(spec.group_by):
            raise EngineError("invalid_argument", "Recorte repetido em group_by.")
        dims: List[Dim] = []
        for i, token in enumerate(spec.group_by):
            kind, _, raw = token.partition(":")
            if kind in DIM_SIMPLE and not raw:
                d = Dim(token, kind)
                d.select = {
                    "unit": "e.unit_id",
                    "unit_state": "u.state",
                    "channel": "e.channel",
                    "completion": "CASE WHEN e.completed = 1 THEN 'completed' ELSE 'incomplete' END",
                    "reliability": "CASE WHEN e.reliable = 1 THEN 'reliable' WHEN e.reliable = 0 THEN 'unreliable' "
                                   "ELSE 'unclassified' END",
                    "day_of_week": "dow(e.day)",
                }.get(kind) or f"bucket('{kind}', e.day)"
            elif kind == "hour_block":
                size = int(raw) if raw else 6
                if size not in periods.HOUR_BLOCKS:
                    raise EngineError("invalid_argument", f"hour_block aceita blocos de {periods.HOUR_BLOCKS} horas.")
                d = Dim(token, kind, size, f"hour_block(e.started_at, {size})")
            elif kind == "unit_property":
                if not raw.isdigit():
                    raise EngineError("invalid_argument", "Use unit_property:<property_name_id>.")
                name_id = int(raw)
                if name_id not in self.catalog.property_names():
                    raise EngineError(
                        "not_found", f"Propriedade de unidade {name_id} não existe.",
                        hint="Use `units --properties` ou `resolve --kind property` para achar o id.",
                    )
                alias = f"p{i}"
                d = Dim(token, kind, name_id, f"{alias}.value_id",
                        (f"LEFT JOIN tmp_prop {alias} ON {alias}.unit_id = e.unit_id AND {alias}.name_id = ?", [name_id]))
            elif kind == "nps_group":
                ref = self._reference_nps(qn, int(raw) if raw else spec.reference_question_id)
                alias = f"r{i}"
                d = Dim(token, kind, ref.id,
                        f"CASE WHEN {alias}.score >= 9 THEN 'promoter' WHEN {alias}.score >= 7 THEN 'passive' "
                        f"WHEN {alias}.score IS NOT NULL THEN 'detractor' END",
                        (f"LEFT JOIN answers {alias} ON {alias}.survey_id = e.survey_id AND {alias}.eval_ref = e.eval_ref "
                         f"AND {alias}.question_id = ? AND {alias}.kind = 'nps' AND {alias}.answered = 1", [ref.id]))
            elif kind == "choice":
                if not raw.isdigit():
                    raise EngineError("invalid_argument", "Use choice:<question_id> (pergunta de escolha de referência).")
                ref = self._question(qn, int(raw))
                if ref.answer_type not in CHOICE_TYPES + ("Multiple Response",):
                    raise EngineError("metric_not_applicable", f"choice:<id> exige pergunta de escolha; a {ref.number} é {ref.answer_type}.")
                alias = f"r{i}"
                d = Dim(token, kind, ref.id, f"{alias}.choice_id",
                        (f"LEFT JOIN answers {alias} ON {alias}.survey_id = e.survey_id AND {alias}.eval_ref = e.eval_ref "
                         f"AND {alias}.question_id = ? AND {alias}.choice_id IS NOT NULL", [ref.id]))
            elif kind == "shift":
                raise EngineError("unsupported_combination", NOT_AVAILABLE["shift"])
            else:
                raise EngineError(
                    "invalid_argument", f"Recorte desconhecido: {token}.",
                    hint="Recortes: unit, unit_property:<id>, unit_state, day, week, month, quarter, day_of_week, "
                         "hour_block[:horas], channel, completion, reliability, nps_group[:<id>], choice:<id>.",
                )
            dims.append(d)
        if spec.metric == "data_quality_summary" and any(d.kind == "reliability" for d in dims):
            raise EngineError("unsupported_combination", "data_quality_summary já separa por confiabilidade.")
        return dims

    # =============================================================== SQL
    def _prepare_units(self, need_props: bool, need_state: bool) -> None:
        self.db.execute("CREATE TEMP TABLE IF NOT EXISTS tmp_prop (unit_id INTEGER, name_id INTEGER, value_id INTEGER)")
        self.db.execute("CREATE TEMP TABLE IF NOT EXISTS tmp_unit (unit_id INTEGER PRIMARY KEY, state TEXT)")
        if not (need_props or need_state):
            return
        units = self.catalog.units()
        self.db.execute("DELETE FROM tmp_prop")
        self.db.execute("DELETE FROM tmp_unit")
        self.db.executemany(
            "INSERT INTO tmp_prop VALUES (?,?,?)",
            [(u["id"], p["name_id"], p["value_id"]) for u in units for p in u["properties"]],
        )
        self.db.executemany("INSERT INTO tmp_unit VALUES (?,?)", [(u["id"], u["state"]) for u in units])

    def _base(self, spec: QuerySpec, period: periods.Period, dims: Sequence[Dim],
              target_join: Optional[Tuple[str, List[Any]]], ref_nps: Optional[Question],
              ref_choice_q: Optional[int]) -> Tuple[str, List[Any]]:
        joins: List[str] = []
        params: List[Any] = []
        if target_join:
            joins.append(target_join[0])
            params.extend(target_join[1])
        for d in dims:
            if d.join:
                joins.append(d.join[0])
                params.extend(d.join[1])
        if any(d.kind == "unit_state" for d in dims):
            joins.append("LEFT JOIN tmp_unit u ON u.unit_id = e.unit_id")
        where = ["e.survey_id = ?", "e.day BETWEEN ? AND ?"]
        params.extend([spec.survey_id, period.start.isoformat(), period.end.isoformat()])
        if spec.unit_ids:
            where.append("e.unit_id IN (%s)" % ",".join("?" * len(spec.unit_ids)))
            params.extend(spec.unit_ids)
        if spec.property_value_ids:
            by_name: Dict[int, List[int]] = {}
            names = self.catalog.property_names()
            value_to_name = {vid: nid for nid, meta in names.items() for vid in meta["values"]}
            for vid in spec.property_value_ids:
                if vid not in value_to_name:
                    raise EngineError("not_found", f"Valor de propriedade {vid} não existe.")
                by_name.setdefault(value_to_name[vid], []).append(vid)
            for vids in by_name.values():  # OU dentro do mesmo nome, E entre nomes
                where.append("e.unit_id IN (SELECT unit_id FROM tmp_prop WHERE value_id IN (%s))" % ",".join("?" * len(vids)))
                params.extend(vids)
        if spec.channel:
            where.append("e.channel = ?")
            params.append(spec.channel)
        if spec.completion != "all":
            where.append("e.completed = ?")
            params.append(1 if spec.completion == "completed" else 0)
        if spec.metric != "data_quality_summary":
            if spec.reliability == "reliable_only":
                where.append("e.reliable = 1")
            elif spec.reliability == "unreliable_only":
                where.append("e.reliable = 0")
            elif spec.reliability == "unclassified_only":
                where.append("e.reliable IS NULL")
        if spec.nps_groups and ref_nps:
            ranges = {"promoter": "f.score >= 9", "passive": "f.score BETWEEN 7 AND 8", "detractor": "f.score <= 6"}
            cond = " OR ".join(ranges[g] for g in spec.nps_groups)
            where.append(
                "EXISTS (SELECT 1 FROM answers f WHERE f.survey_id = e.survey_id AND f.eval_ref = e.eval_ref "
                f"AND f.question_id = ? AND f.kind = 'nps' AND f.answered = 1 AND ({cond}))"
            )
            params.append(ref_nps.id)
        if spec.reference_choice_ids and ref_choice_q:
            where.append(
                "EXISTS (SELECT 1 FROM answers f WHERE f.survey_id = e.survey_id AND f.eval_ref = e.eval_ref "
                "AND f.question_id = ? AND f.choice_id IN (%s))" % ",".join("?" * len(spec.reference_choice_ids))
            )
            params.extend([ref_choice_q, *spec.reference_choice_ids])
        if spec.tag_ids:
            where.append(
                "EXISTS (SELECT 1 FROM answer_tags t2 WHERE t2.survey_id = e.survey_id AND t2.eval_ref = e.eval_ref "
                "AND t2.tag_id IN (%s))" % ",".join("?" * len(spec.tag_ids))
            )
            params.extend(spec.tag_ids)
        if spec.metric == "data_quality_summary":
            where.append("e.dq = 1")
        sql = "FROM evaluations e " + " ".join(joins) + " WHERE " + " AND ".join(where)
        return sql, params

    def _grouped(self, select_extra: str, base: Tuple[str, List[Any]], dims: Sequence[Dim],
                 extra_group: str = "") -> List[Tuple]:
        dsel = [d.select for d in dims]
        cols = ", ".join(dsel + ([select_extra] if select_extra else []))
        group = ", ".join(dsel + ([extra_group] if extra_group else []))
        sql = f"SELECT {cols} {base[0]}" + (f" GROUP BY {group}" if group else "")
        return [tuple(r) for r in self.db.execute(sql, base[1]).fetchall()]

    # ============================================================ cálculo
    def _compute(self, spec: QuerySpec, qn: Questionnaire, q: Optional[Question], period: periods.Period,
                 dims: Sequence[Dim], ref_nps: Optional[Question], ref_choice_q: Optional[int]) -> Dict[Tuple, Any]:
        """{chave das dimensões: resultado}. Distribuições: {chave: [linhas por categoria]}."""
        m, nd = spec.metric, len(dims)
        loc = spec.locale

        def base(target_join=None):
            return self._base(spec, period, dims, target_join, ref_nps, ref_choice_q)

        def ans_join(pred: str):
            return (f"JOIN answers a ON a.survey_id = e.survey_id AND a.eval_ref = e.eval_ref AND a.question_id = ? "
                    f"AND {pred}", [q.id])

        out: Dict[Tuple, Any] = {}
        if m == "evaluation_count":
            for r in self._grouped("COUNT(DISTINCT e.eval_ref)", base(), dims):
                out[r[:nd]] = measures.count_result(r[nd], loc)
        elif m == "data_quality_summary":
            sel = ("COUNT(DISTINCT e.eval_ref), SUM(CASE WHEN e.reliable = 1 THEN 1 ELSE 0 END), "
                   "SUM(CASE WHEN e.reliable = 0 THEN 1 ELSE 0 END), SUM(CASE WHEN e.reliable IS NULL THEN 1 ELSE 0 END)")
            for r in self._grouped(sel, base(), dims):
                out[r[:nd]] = measures.dq_result(r[nd], r[nd + 1] or 0, r[nd + 2] or 0, r[nd + 3] or 0, loc)
        elif m == "response_count":
            pred = {
                "NPS": "a.kind = 'nps' AND a.answered = 1",
                "Multiple Response": "a.kind = 'multi' AND a.answered = 1",
            }.get(q.answer_type, "a.choice_id IS NOT NULL" if q.answer_type in CHOICE_TYPES else "a.answered = 1")
            for r in self._grouped("COUNT(DISTINCT e.eval_ref)", base(ans_join(pred)), dims):
                out[r[:nd]] = measures.count_result(r[nd], loc)
        elif m == "nps":
            sel = ("SUM(CASE WHEN a.score >= 9 THEN 1 ELSE 0 END), SUM(CASE WHEN a.score BETWEEN 7 AND 8 THEN 1 ELSE 0 END), "
                   "SUM(CASE WHEN a.score <= 6 THEN 1 ELSE 0 END)")
            for r in self._grouped(sel, base(ans_join("a.kind = 'nps' AND a.answered = 1")), dims):
                out[r[:nd]] = measures.nps_result(r[nd] or 0, r[nd + 1] or 0, r[nd + 2] or 0, q, loc)
        elif m in ("scale_mean", "weighted_sum", "choice_share", "choice_set_share"):
            counts: Dict[Tuple, Dict[int, int]] = {}
            rows = self._grouped("a.choice_id, COUNT(*)", base(ans_join("a.kind = 'choice' AND a.choice_id IS NOT NULL")),
                                 dims, "a.choice_id")
            current = {c.id for c in q.choices}
            for r in rows:
                if r[nd] in current:
                    counts.setdefault(r[:nd], {})[r[nd]] = r[nd + 1]
            random_order = q.options.get("choices_ordering") in ("random", "random_with_last_fixed")
            for key, cmap in counts.items():
                answered = sum(cmap.values())
                if m == "scale_mean":
                    out[key] = measures.scale_mean_result(cmap, q, loc)
                elif m == "weighted_sum":
                    out[key] = measures.weighted_sum_result(cmap, q, loc)
                elif m == "choice_set_share":
                    out[key] = measures.choice_set_result(cmap, answered, spec.choice_ids, q, loc)
                else:
                    out[key] = measures.choice_rows(cmap, answered, q, loc, by_count=random_order)
        elif m == "multi_response_share":
            j = ans_join("a.kind = 'multi' AND a.answered = 1")
            answered = {r[:nd]: r[nd] for r in self._grouped("COUNT(DISTINCT e.eval_ref)", base(j), dims)}
            chosen: Dict[Tuple, Dict[int, int]] = {}
            for r in self._grouped("a.choice_id, COUNT(DISTINCT e.eval_ref)", base(j), dims, "a.choice_id"):
                if r[nd] is not None:
                    chosen.setdefault(r[:nd], {})[r[nd]] = r[nd + 1]
            random_order = q.options.get("choices_ordering") in ("random", "random_with_last_fixed")
            for key, total in answered.items():
                out[key] = measures.choice_rows(chosen.get(key, {}), total, q, loc, by_count=random_order)
        elif m == "tag_mentions":
            qcond = " AND t.question_id = ?" if q else ""
            tj = (f"JOIN answer_tags t ON t.survey_id = e.survey_id AND t.eval_ref = e.eval_ref{qcond}", [q.id] if q else [])
            pair = "e.eval_ref || '|' || COALESCE(t.question_id, '')"
            bases = {r[:nd]: r[nd] for r in self._grouped(f"COUNT(DISTINCT {pair})", base(tj), dims)}
            if q:
                oj = ans_join("a.kind = 'open' AND a.answered = 1")
            else:
                oj = ("JOIN answers a ON a.survey_id = e.survey_id AND a.eval_ref = e.eval_ref "
                      "AND a.kind = 'open' AND a.answered = 1", [])
            texts = {r[:nd]: r[nd] for r in self._grouped("COUNT(*)", base(oj), dims)}
            per_tag: Dict[Tuple, List[Tuple[int, str, int]]] = {}
            for r in self._grouped(f"t.tag_id, MAX(t.tag_name), COUNT(DISTINCT {pair})", base(tj), dims, "t.tag_id"):
                per_tag.setdefault(r[:nd], []).append((r[nd], r[nd + 1], r[nd + 2]))
            for key in set(bases) | set(texts):
                tagged = bases.get(key, 0)
                rows_out = []
                for tag_id, name, mentions in sorted(per_tag.get(key, []), key=lambda t: (-t[2], t[1] or "")):
                    pct = measures.share_pct(mentions, tagged)
                    rows_out.append({
                        "tag": {"id": tag_id, "name": name}, "value": measures._f(pct), "n": tagged,
                        "mentions": mentions, "display": fmt.fmt_pct(pct, 1, loc) if pct is not None else "-",
                    })
                out[key] = {"tagged_comments": tagged, "text_responses": texts.get(key, 0), "rows": rows_out}
        return out

    # ============================================================ rótulos
    def _dim_labels(self, dims: Sequence[Dim], key: Tuple, qn: Questionnaire, period: periods.Period,
                    unit_names: Dict[int, str]) -> Tuple[Dict[str, Any], Dict[str, Any]]:
        labels: Dict[str, Any] = {}
        bucket: Dict[str, Any] = {}
        for d, v in zip(dims, key):
            if d.kind == "unit":
                labels["unit"] = {"id": v, "name": unit_names.get(v)} if v is not None else None
            elif d.kind == "unit_property":
                meta = self.catalog.property_names().get(d.param, {})
                labels[d.token] = {"name_id": d.param, "name": meta.get("name"), "value_id": v,
                                   "value": meta.get("values", {}).get(v) if v is not None else None}
            elif d.kind == "day_of_week":
                labels["day_of_week"] = {"key": v, "label": periods.DOW_LABELS_PT[periods.DOW_KEYS.index(v)]}
            elif d.kind == "choice":
                ref = qn.by_id[d.param]
                c = next((c for c in ref.choices if c.id == v), None)
                labels[d.token] = ({"question_id": ref.id, "id": c.id, "letter": c.letter, "text": c.label}
                                   if c else None)
            elif d.kind in periods.TIME_BUCKETS:
                labels[d.kind] = v
                bs, be = periods.bucket_bounds(d.kind, v)
                bucket = {"start": bs.isoformat(), "end": be.isoformat()}
                if bs < period.start or be > period.end:
                    bucket["clipped_by_period"] = True
                if bs <= self.s.today <= be:
                    bucket["in_progress"] = True
            else:
                labels[d.token] = v
        return labels, bucket

    @staticmethod
    def _sort_key(dims: Sequence[Dim], key: Tuple, unit_names: Dict[int, str]) -> Tuple:
        out = []
        for d, v in zip(dims, key):
            if v is None:
                out.append((1, ""))
            elif d.kind == "unit":
                out.append((0, (unit_names.get(v) or "").lower()))
            elif d.kind == "day_of_week":
                out.append((0, periods.DOW_KEYS.index(v)))
            else:
                out.append((0, v))
        return tuple(out)

    # ============================================================ execução
    def run(self, spec: QuerySpec) -> Dict[str, Any]:
        qn = self.catalog.require_survey(spec.survey_id)
        q = self._validate(spec, qn)
        dims = self._dims(spec, qn)
        period = periods.resolve_period(self.s.today, spec.preset, spec.start, spec.end)
        warnings: List[Dict[str, Any]] = []

        cperiod = None
        comparison: Optional[Dict[str, Any]] = None
        if spec.compare_with:
            if spec.compare_with == "previous_period" and any(d.kind in periods.TIME_BUCKETS for d in dims):
                raise EngineError(
                    "unsupported_combination",
                    "Série temporal com previous_period não tem casamento claro entre baldes.",
                    hint="Use --compare-with previous_year, ou tire o recorte de tempo e compare o período inteiro.",
                )
            cperiod, rule, adjusted = periods.comparison_period(period, spec.compare_with)
            comparison = {"kind": spec.compare_with, "start": cperiod.start.isoformat(),
                          "end": cperiod.end.isoformat(), "rule": rule}
            if adjusted:
                comparison["kind"] = "previous_period"
                warnings.append(_w("comparison_window_adjusted",
                                   "Período maior que um ano: a comparação usou o período imediatamente anterior."))

        # referências de filtros
        ref_nps = self._reference_nps(qn, spec.reference_question_id) if spec.nps_groups else None
        if spec.nps_groups and any(g not in ("promoter", "passive", "detractor") for g in spec.nps_groups):
            raise EngineError("invalid_argument", "--nps-group aceita promoter, passive ou detractor.")
        ref_choice_q = None
        if spec.reference_choice_ids:
            owners = {qq.id for qq in qn.questions for c in qq.choices if c.id in spec.reference_choice_ids}
            if len(owners) != 1:
                raise EngineError("invalid_argument", "--choice-filter aceita alternativas de uma única pergunta da pesquisa.")
            ref_choice_q = self._question(qn, owners.pop()).id

        # dados: baixa o que falta para os dois períodos
        sync_reports = [self.syncer.ensure(spec.survey_id, period.start, period.end, spec.refresh)]
        if cperiod:
            sync_reports.append(self.syncer.ensure(spec.survey_id, cperiod.start, cperiod.end, spec.refresh))
        if not all(r["complete"] for r in sync_reports):
            done = sum(r["days_fetched"] + r["days_reused"] for r in sync_reports)
            left = sum(r["days_remaining"] for r in sync_reports)
            raise EngineError(
                "sync_incomplete",
                f"Ainda baixando avaliações da API: {done} dias prontos, faltam {left}.",
                hint="Rode o mesmo comando de novo; o download continua de onde parou.",
                details={"sync": sync_reports},
                exit_code=EXIT_SYNC,
            )
        used = [x for x in [q, ref_nps] if x is not None]
        used += [qn.by_id[d.param] for d in dims if d.kind in ("nps_group", "choice")]
        if ref_choice_q:
            used.append(qn.by_id[ref_choice_q])
        warnings.extend(self._check_ambiguity(qn, used, [p for p in (period, cperiod) if p]))

        self._prepare_units(
            need_props=any(d.kind == "unit_property" for d in dims) or bool(spec.property_value_ids),
            need_state=any(d.kind == "unit_state" for d in dims),
        )
        if spec.unit_ids:
            known = self.catalog.units_by_id()
            missing = [u for u in spec.unit_ids if u not in known]
            if missing:
                raise EngineError("not_found", f"Unidades {missing} não estão disponíveis para esta credencial.")

        cur = self._compute(spec, qn, q, period, dims, ref_nps, ref_choice_q)
        cur_tot = self._compute(spec, qn, q, period, [], ref_nps, ref_choice_q).get((), None)
        cmp: Dict[Tuple, Any] = {}
        cmp_tot = None
        if cperiod:
            cmp = self._compute(spec, qn, q, cperiod, dims, ref_nps, ref_choice_q)
            cmp_tot = self._compute(spec, qn, q, cperiod, [], ref_nps, ref_choice_q).get((), None)

        unit_names = dict(self.db.execute(
            "SELECT unit_id, MAX(unit_name) FROM evaluations WHERE survey_id = ? GROUP BY unit_id", (spec.survey_id,)
        ).fetchall())
        try:
            unit_names.update({u["id"]: u["name"] for u in (self.store.get_catalog("units")[0] or [])})
        except (TypeError, KeyError):
            pass

        def shift(key: Tuple) -> Optional[Tuple]:
            if spec.compare_with != "previous_year":
                return key
            out = []
            for d, v in zip(dims, key):
                if d.kind in periods.TIME_BUCKETS and v is not None:
                    v = periods.shift_bucket_one_year(d.kind, v)
                    if v is None:
                        return None
                out.append(v)
            return tuple(out)

        distribution = METRICS[spec.metric].get("distribution", False)
        count_metric = spec.metric in ("evaluation_count", "response_count", "data_quality_summary")
        keys = list(cur)
        if cperiod and not distribution and not any(d.kind in periods.TIME_BUCKETS for d in dims):
            # recorte que só tem dado no período comparado (ex.: unidade que parou de responder)
            keys += [k for k in cmp if k not in cur]
        rows: List[Dict[str, Any]] = []
        small = 0
        for key in sorted(keys, key=lambda k: self._sort_key(dims, k, unit_names)):
            labels, bucket = self._dim_labels(dims, key, qn, period, unit_names)
            ckey = shift(key) if cperiod else None
            base_extra: Dict[str, Any] = {}
            if bucket:
                base_extra["bucket"] = bucket
            if distribution:
                group = cur[key]
                cgroup = cmp.get(ckey) if ckey is not None else None
                cats = group["rows"] if spec.metric == "tag_mentions" else group
                ccats = (cgroup["rows"] if spec.metric == "tag_mentions" else cgroup) if cgroup else []
                cindex = {_cat_id(c): c for c in ccats}
                extra = ({"tagged_comments": group["tagged_comments"], "text_responses": group["text_responses"]}
                         if spec.metric == "tag_mentions" else {})
                for cat in cats:
                    row = {"dims": {**labels, **({"choice": cat["choice"]} if "choice" in cat else {"tag": cat["tag"]})},
                           **{k: v for k, v in cat.items() if k not in ("choice", "tag")}, **extra, **base_extra}
                    if cperiod:
                        prev = cindex.get(_cat_id(cat))
                        row["compared"] = _compact(prev) if prev else {"value": None, "n": 0, "display": "-"}
                        row["delta"] = measures.delta(cat, prev or {}, spec.metric, q, spec.locale)
                    rows.append(row)
                n_group = group["tagged_comments"] if spec.metric == "tag_mentions" else (cats[0]["n"] if cats else 0)
                if n_group < self.s.small_sample and cats:
                    small += len(cats)
                    for r in rows[-len(cats):]:
                        r["warnings"] = ["small_sample"]
            else:
                res = dict(cur[key]) if key in cur else {"value": None, "n": 0, "display": "-"}
                row = {"dims": labels, **res, **base_extra}
                if key not in cur:
                    row["only_in_comparison"] = True
                if cperiod:
                    prev = cmp.get(ckey) if ckey is not None else None
                    row["compared"] = _compact(prev) if prev else {"value": None, "n": 0, "display": "-"}
                    row["delta"] = measures.delta(res, prev or {}, spec.metric, q, spec.locale)
                if not count_metric and 0 < res["n"] < self.s.small_sample:
                    row["warnings"] = ["small_sample"]
                    small += 1
                rows.append(row)

        hidden = 0
        if spec.min_n:
            kept = [r for r in rows if (r.get("n") or 0) >= spec.min_n]
            hidden = len(rows) - len(kept)
            rows = kept

        if spec.order:
            by, _, direction = spec.order.partition(":")
            if by not in ("value", "n", "delta"):
                raise EngineError("invalid_argument", "--order aceita value, n ou delta, com :asc ou :desc.")
            if by == "delta" and not cperiod:
                raise EngineError("invalid_argument", "--order delta exige --compare-with.")
            desc = direction != "asc"

            def sort_val(r):
                v = (r.get("delta") or {}).get("value") if by == "delta" else r.get(by)
                return (v is None, -(v or 0) if desc else (v or 0))

            rows.sort(key=sort_val)

        available = len(rows)
        truncated = available > spec.limit
        rows = rows[: spec.limit]

        # totais (agregado do conjunto inteiro, pelas contagens)
        totals: Any = None
        if distribution:
            if cur_tot is not None:
                cats = cur_tot["rows"] if spec.metric == "tag_mentions" else cur_tot
                ccats = ((cmp_tot["rows"] if spec.metric == "tag_mentions" else cmp_tot) if cmp_tot else [])
                cindex = {_cat_id(c): c for c in ccats}
                totals = []
                for cat in cats:
                    t = dict(cat)
                    if cperiod:
                        prev = cindex.get(_cat_id(cat))
                        t["compared"] = _compact(prev) if prev else {"value": None, "n": 0, "display": "-"}
                        t["delta"] = measures.delta(cat, prev or {}, spec.metric, q, spec.locale)
                    totals.append(t)
                if spec.metric == "tag_mentions":
                    tagged, texts = cur_tot["tagged_comments"], cur_tot["text_responses"]
                    share = measures.share_pct(tagged, texts)
                    totals = {"tagged_comments": tagged, "text_responses": texts,
                              "tagged_share_display": fmt.fmt_pct(share, 1, spec.locale) if share is not None else "-",
                              "rows": totals}
                    if cperiod and cmp_tot is not None:
                        totals["compared"] = {"tagged_comments": cmp_tot["tagged_comments"],
                                              "text_responses": cmp_tot["text_responses"]}
        elif cur_tot is not None:
            totals = dict(cur_tot)
            if cperiod:
                totals["compared"] = _compact(cmp_tot) if cmp_tot else {"value": None, "n": 0, "display": "-"}
                totals["delta"] = measures.delta(cur_tot, cmp_tot or {}, spec.metric, q, spec.locale)

        # ---------------------------------------------------------- avisos
        cov = coverage(self.store, spec.survey_id, period.start, period.end, self.s.today)
        ccov = coverage(self.store, spec.survey_id, cperiod.start, cperiod.end, self.s.today) if cperiod else None
        all_in_period = self.db.execute(
            "SELECT COUNT(*), SUM(dq), SUM(CASE WHEN dq = 1 AND reliable = 1 THEN 1 ELSE 0 END), "
            "SUM(CASE WHEN dq = 1 AND reliable = 0 THEN 1 ELSE 0 END), "
            "SUM(CASE WHEN dq = 1 AND reliable IS NULL THEN 1 ELSE 0 END) "
            "FROM evaluations WHERE survey_id = ? AND day BETWEEN ? AND ?",
            (spec.survey_id, period.start.isoformat(), period.end.isoformat()),
        ).fetchone()
        n_all, n_dq = all_in_period[0] or 0, all_in_period[1] or 0

        tag_texts_only = (spec.metric == "tag_mentions" and isinstance(totals, dict)
                          and not totals.get("tagged_comments") and totals.get("text_responses"))
        if tag_texts_only:
            warnings.append(_w("no_tags", f"Há {totals['text_responses']} comentário(s) no recorte, mas nenhum tem tag: "
                                          "não há classificação de temas. Use comments para ler os trechos."))
        elif not rows and not (totals and (totals.get("n") if isinstance(totals, dict) else totals)):
            warnings.append(_w("no_data", "Nenhum dado no período e recorte pedidos."))
        if small:
            warnings.append(_w("small_sample", f"{small} linha(s) com menos de {self.s.small_sample} respostas: "
                                               "mostrar com o n e a ressalva.", threshold=self.s.small_sample))
        for label, c in (("período", cov), ("período comparado", ccov)):
            if c and (c["days_partial"] or c["days_missing"]):
                warnings.append(_w("incomplete_coverage",
                                   f"A API falhou em parte do {label}; os números excluem as janelas listadas em coverage.",
                                   failed_windows=c["failed_windows"]))
        if n_all == 0 and qn.last_evaluation_date and qn.last_evaluation_date >= period.start.isoformat():
            warnings.append(_w(
                "possible_silent_failure",
                f"A API não devolveu avaliações no período, mas a pesquisa registra avaliação até "
                f"{qn.last_evaluation_date}. A API pública devolve lista vazia quando falha ao montar as respostas. "
                "Não afirme que não houve avaliações: diga que a API não devolveu dados e sugira conferir na tela de resultados.",
            ))
        gaps = _suspicious_gaps(self.store, spec.survey_id, period, self.s.today)
        if gaps:
            warnings.append(_w("suspicious_empty_days",
                               "Dias seguidos sem avaliações no meio de dias movimentados; pode ser pausa real ou falha "
                               "silenciosa da API. Mencione ao usuário.", ranges=gaps))
        if period.end >= self.s.today:
            warnings.append(_w("period_in_progress", "O período inclui hoje e ainda está em andamento."))
        if any((r.get("bucket") or {}).get("in_progress") or (r.get("bucket") or {}).get("clipped_by_period") for r in rows):
            warnings.append(_w("partial_bucket", "Há baldes de tempo incompletos (em andamento ou cortados pelo período); "
                                                 "não compare como se fossem cheios."))
        if spec.metric == "multi_response_share":
            warnings.append(_w("multi_response_sum_exceeds_100", "Cada avaliação marca várias alternativas; as "
                                                                 "porcentagens somam mais de 100%."))
        if any(d.kind == "choice" and qn.by_id[d.param].answer_type == "Multiple Response" for d in dims):
            warnings.append(_w("overlapping_categories", "O recorte é uma pergunta de múltipla resposta: uma avaliação "
                                                         "entra em várias categorias e as linhas não somam o total."))
        if q is not None and qn.edited_after_lock():
            warnings.append(_w("values_from_current_questionnaire",
                               "O questionário foi editado depois de travado; textos e valores atuais valem para todo o histórico."))
        if q is not None:
            excl = self.db.execute(
                "SELECT SUM(count) FROM issues WHERE survey_id = ? AND day BETWEEN ? AND ? "
                "AND code = 'answer_without_current_choice' AND detail = ?",
                (spec.survey_id, period.start.isoformat(), period.end.isoformat(), str(q.id)),
            ).fetchone()[0]
            if excl:
                warnings.append(_w("answers_excluded", f"{excl} resposta(s) apontam para alternativas que não existem mais "
                                                       "no questionário e ficaram fora, como nas telas.", count=excl))
        if spec.metric == "tag_mentions":
            warnings.append(_w("tag_semantics", "Tags podem ter sido aplicadas por pessoas ou pelo Radar de Comentários. "
                                                "A base é o número de comentários com ao menos uma tag; um comentário pode ter várias, "
                                                "então as porcentagens somam mais de 100%."))
            tt = totals if isinstance(totals, dict) else {}
            if tt.get("text_responses", 0) > tt.get("tagged_comments", 0):
                warnings.append(_w("partial_tag_coverage",
                                   f"Só {tt.get('tagged_comments', 0)} de {tt.get('text_responses', 0)} comentários "
                                   "têm tag; os demais não foram classificados ou não citaram tema da lista do cliente."))
        if spec.metric == "data_quality_summary" and n_dq == 0:
            warnings.append(_w("data_quality_not_enabled", "A pesquisa não tem Data Quality ligado (a API não traz o campo reliable)."))
        if qn.archived:
            warnings.append(_w("archived_survey", "A pesquisa está arquivada."))
        if period.end > self.s.today:
            warnings.append(_w("includes_future_days", "O período termina depois de hoje; os dias futuros não têm dados."))
        if hidden:
            warnings.append(_w("rows_hidden_by_min_n", f"{hidden} linha(s) ocultas por terem n abaixo de {spec.min_n}."))

        reliability_policy: Dict[str, Any] = {"applied": spec.reliability}
        if n_dq:
            reliability_policy["survey_has_data_quality"] = True
            reliability_policy["survey_mix_in_period"] = {
                "reliable": all_in_period[2] or 0, "unreliable": all_in_period[3] or 0, "unclassified": all_in_period[4] or 0,
                "scope": "todas as avaliações da pesquisa no período, sem os filtros desta consulta",
            }
            not_reliable = (all_in_period[3] or 0) + (all_in_period[4] or 0)
            if spec.reliability == "all" and spec.metric != "data_quality_summary" and not_reliable:
                warnings.append(_w(
                    "includes_unverified_evaluations",
                    f"Pesquisa com Data Quality: no período há {all_in_period[3] or 0} avaliação(ões) reprovada(s) e "
                    f"{all_in_period[4] or 0} não verificada(s), e elas entram nos números. Nas telas, quem não gerencia "
                    "confiabilidade vê só as confiáveis (--reliability reliable_only).",
                ))

        envelope: Dict[str, Any] = {
            "query_id": "q_" + secrets.token_hex(4),
            "engine_version": ENGINE_VERSION,
            "model_version": MODEL_VERSION,
            "metric": {"id": spec.metric, "label": METRICS[spec.metric]["label"], "unit": METRICS[spec.metric]["unit"]},
            "scope": {
                "survey": {"id": qn.survey_id, "name": qn.survey_name},
                **({"question": q.summary()} if q else {}),
            },
            "period": period.to_dict(self.s.today),
            **({"comparison": comparison} if comparison else {}),
            "group_by": spec.group_by,
            "filters": _filters_view(spec, ref_nps, ref_choice_q),
            "policies": {
                "reliability": reliability_policy,
                "completion": spec.completion,
                "lgpd": "aggregates_only",
                "free_text": "masked_pii",
            },
            "coverage": {"period": cov, **({"comparison": ccov} if ccov else {})},
            "freshness": {
                "source": "api_v1",
                "fetched_oldest": cov["fetched_oldest"],
                "fetched_newest": cov["fetched_newest"],
                "fetched_newest_sao_paulo": local_time(cov["fetched_newest"]),
                "api_last_evaluation_date": qn.last_evaluation_date,
            },
            "rows": rows,
            "totals": totals,
            "truncated": truncated,
            "available_rows": available,
            "warnings": warnings,
        }
        audit(self.s, "query", asdict(spec), envelope)
        return envelope


def _cat_id(cat: Dict[str, Any]) -> Any:
    return cat["choice"]["id"] if "choice" in cat else cat["tag"]["id"]


def _compact(res: Dict[str, Any]) -> Dict[str, Any]:
    out = {k: res[k] for k in ("value", "n", "display") if k in res}
    for extra in ("chosen", "mentions", "breakdown", "reference_zone"):
        if extra in res:
            out[extra] = res[extra]
    return out


def _filters_view(spec: QuerySpec, ref_nps: Optional[Question], ref_choice_q: Optional[int]) -> Dict[str, Any]:
    view: Dict[str, Any] = {}
    if spec.unit_ids:
        view["unit_ids"] = spec.unit_ids
    if spec.property_value_ids:
        view["property_value_ids"] = spec.property_value_ids
    if spec.channel:
        view["channel"] = spec.channel
    if spec.nps_groups:
        view["nps_group"] = {"groups": spec.nps_groups, "reference_question_id": ref_nps.id if ref_nps else None}
    if spec.reference_choice_ids:
        view["choice_filter"] = {"question_id": ref_choice_q, "choice_ids": spec.reference_choice_ids}
    if spec.tag_ids:
        view["tag_ids"] = spec.tag_ids
    if spec.choice_ids:
        view["choice_set"] = spec.choice_ids
    return view


def _suspicious_gaps(store: Store, survey_id: int, period: periods.Period, today: dt.date) -> List[List[str]]:
    """Dias vazios numa série movimentada (média >= 20 por dia com dados).

    Vale para buracos entre dias com dados (1 dia ou mais) e para sequências de 3+ dias
    vazios no começo do período. Pode ser pausa real ou falha silenciosa da API.
    """
    end = min(period.end, today)
    rows = store.day_rows(survey_id, period.start, end)
    series = [(d.isoformat(), rows[d.isoformat()]["evaluations"]) for d in periods.iter_days(period.start, end)
              if d.isoformat() in rows]
    busy = [n for _, n in series if n > 0]
    if not busy or sum(busy) / len(busy) < 20:
        return []
    # dia da semana normalmente fechado (ex.: domingo) não é suspeito
    by_dow: Dict[int, List[int]] = {}
    for day, n in series:
        by_dow.setdefault(dt.date.fromisoformat(day).weekday(), []).append(n)

    def usually_open(day: str) -> bool:
        values = by_dow[dt.date.fromisoformat(day).weekday()]
        others = len(values) - 1
        if others == 0:  # série curta: sem outro dia igual da semana para comparar
            rest = [n for d, n in series if d != day]
            return bool(rest) and sum(1 for n in rest if n > 0) / len(rest) >= 0.9
        return sum(1 for v in values if v > 0) / others >= 0.75

    gaps: List[List[str]] = []
    run: List[str] = []
    seen_busy = False
    for day, n in series:
        if n == 0:
            run.append(day)
            continue
        if run and (seen_busy or len(run) >= 3) and any(usually_open(d) for d in run):
            gaps.append([run[0], run[-1]])
        run = []
        seen_busy = True
    return gaps[:10]


def audit(settings: Settings, command: str, request: Dict[str, Any], envelope: Dict[str, Any]) -> None:
    """Registro local de cada consulta: permite reabrir um número citado pelo query_id."""
    record = {
        "query_id": envelope.get("query_id"),
        "at": dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat(),
        "command": command,
        "request": request,
        "envelope": envelope,
    }
    path = settings.cache_dir / "queries.jsonl"
    with open(path, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")


def find_query(settings: Settings, query_id: str) -> Optional[Dict[str, Any]]:
    path = settings.cache_dir / "queries.jsonl"
    if not path.exists():
        return None
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            if f'"{query_id}"' in line:
                record = json.loads(line)
                if record.get("query_id") == query_id:
                    return record
    return None
