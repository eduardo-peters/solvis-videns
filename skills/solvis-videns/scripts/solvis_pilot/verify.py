"""Verificador de afirmações (references/validation-protocol.md).

Recebe a lista de afirmações do material gerado pela skill (JSON) e devolve o parecer no formato do protocolo.

Independência: o recálculo NÃO usa `query.py`. Ele lê o período e os filtros do registro da consulta
(`query_id`) e refaz a conta em SQL próprio sobre o cache (tabelas `evaluations` e `answers`). Só os testes
estatísticos puros de `stats.py` (verificados à mão em tests/pilot/test_stats.py) são compartilhados.
Consulta com recortes que este módulo não sabe refazer (propriedade de unidade, grupo NPS, tag...) é
conferida só contra o envelope (`verification: envelope_only`) e isso aparece no parecer.

Tipos conferidos: N, B, Q, E, T, C, R, G, D, U (números) e K, A, V, P, L, O, X (texto e redação).
Texto de perguntas protegidas por LGPD só existe no cache se o usuário autorizou (`config --lgpd-text on`).
Tipo desconhecido ou afirmação mal formada sai como `nao_verificado`, nunca como "confere".
"""

from __future__ import annotations

import datetime as dt
import difflib
import json
import re
import secrets
from decimal import Decimal
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from . import fmt, periods, privacy, stats
from .config import Settings, local_time
from .errors import EngineError
from .resolve import norm
from .store import Store

CHECKED_TYPES = ("N", "B", "Q", "E", "T", "C", "R", "G", "D", "U", "K", "A", "V", "P", "L", "O", "X")
ALL_TYPES = CHECKED_TYPES
NO_QUERY_TYPES = ("L",)
TIME_KINDS = ("day", "week", "month", "quarter")
SUPPORTED_METRICS = ("evaluation_count", "response_count", "nps", "choice_set_share", "choice_share")
UNSUPPORTED_FILTERS = ("property_value_ids", "nps_groups", "reference_choice_ids", "tag_ids")
DEVIATION = Decimal("0.10")          # >10%: correção obrigatória
BOUNDARY_TOLERANCE = Decimal("0.05")  # fração da última casa, a partir da fronteira de arredondamento

OK, ADJ, FIX, SKIP = "confere", "ajuste", "correcao", "nao_verificado"


class Unsupported(Exception):
    """A consulta tem um recorte que o recálculo independente não refaz."""


# =============================================================== números
def parse_shown(text: Any, locale: str = "pt") -> Tuple[Decimal, int]:
    """'12,5%' -> (Decimal('12.5'), 1). Separadores conforme a localidade (pt: 1.234,5; en: 1,234.5)."""
    s = str(text).strip().replace("\u2212", "-")
    s = re.sub(r"[^\d,.\-]", "", s)
    s = s.replace(".", "").replace(",", ".") if locale in ("pt", "es") else s.replace(",", "")
    if not re.fullmatch(r"-?\d+(\.\d+)?", s):
        raise ValueError(f"número ilegível: {text!r}")
    return Decimal(s), (len(s.split(".")[1]) if "." in s else 0)


def compare_number(exact: Decimal, shown: Decimal, places: int) -> Dict[str, Any]:
    """Regra N: igual na precisão exibida; tolera 1 unidade se o exato está a <= 0,05 da fronteira de arredondamento."""
    unit = Decimal(1).scaleb(-places)
    rounded = fmt.round_half_up(exact, places)
    if rounded == shown:
        return {"ok": True, "tolerance_used": False, "rounded": rounded}
    scaled = exact / unit
    frac = scaled - scaled.to_integral_value(rounding="ROUND_FLOOR")
    near_boundary = abs(frac - Decimal("0.5")) * unit <= BOUNDARY_TOLERANCE * unit
    if abs(rounded - shown) == unit and near_boundary:
        return {"ok": True, "tolerance_used": True, "rounded": rounded}
    return {"ok": False, "tolerance_used": False, "rounded": rounded}


def deviation(exact: Decimal, shown: Decimal) -> Decimal:
    if exact == 0:
        return Decimal(0) if shown == 0 else Decimal("Infinity")
    return abs(exact - shown) / abs(exact)


# ====================================================== recálculo em SQL
class Recompute:
    """Refaz contagens direto nas tabelas do cache, a partir do registro de uma consulta."""

    def __init__(self, store: Store, catalog: Any, settings: Settings) -> None:
        self.db = store.db
        self.catalog = catalog
        self.s = settings
        self._records: Dict[str, Dict[str, Any]] = {}

    # ---------------------------------------------------------- consulta
    def record(self, query_id: str) -> Dict[str, Any]:
        if query_id not in self._records:
            rec = self._read_record(query_id)
            if not rec:
                raise EngineError("not_found", f"Consulta {query_id} não encontrada no registro local.")
            self._records[query_id] = rec
        return self._records[query_id]

    def _read_record(self, query_id: str) -> Optional[Dict[str, Any]]:
        path = self.s.cache_dir / "queries.jsonl"
        if not path.exists():
            return None
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                if f'"{query_id}"' in line:
                    rec = json.loads(line)
                    if rec.get("query_id") == query_id:
                        return rec
        return None

    @staticmethod
    def window(env: Dict[str, Any], compared: bool = False) -> Tuple[str, str]:
        src = env["comparison"] if compared else env["period"]
        return src["start"], src["end"]

    @staticmethod
    def supports(req: Dict[str, Any]) -> Optional[str]:
        """None se o recálculo independente cobre a consulta; senão o motivo."""
        if req.get("metric") not in SUPPORTED_METRICS:
            return f"métrica {req.get('metric')} não tem recálculo independente"
        for key in UNSUPPORTED_FILTERS:
            if req.get(key):
                return f"filtro {key} não tem recálculo independente"
        if req["metric"] == "response_count" and not req.get("question_id"):
            return "response_count sem pergunta"
        return None

    # --------------------------------------------------------- unidades
    def units(self) -> List[Dict[str, Any]]:
        return self.catalog.units()

    def resolve_unit(self, ref: Any) -> int:
        if isinstance(ref, int) or (isinstance(ref, str) and ref.isdigit()):
            return int(ref)
        hits = [u["id"] for u in self.units() if (u.get("name") or "").casefold() == str(ref).casefold()]
        if len(hits) != 1:
            raise Unsupported(f"unidade {ref!r} resolve para {len(hits)} cadastros")
        return hits[0]

    def group_unit_ids(self, group: Dict[str, Any]) -> List[int]:
        if group.get("unit_ids"):
            return [int(x) for x in group["unit_ids"]]
        units = self.units()
        if group.get("state"):
            return [u["id"] for u in units if u.get("state") == group["state"]]
        if group.get("property_value_ids"):
            want = {int(v) for v in group["property_value_ids"]}
            return [u["id"] for u in units if want & {p["value_id"] for p in u["properties"]}]
        raise Unsupported("grupo sem unit_ids, state ou property_value_ids")

    # ------------------------------------------------------------- SQL
    def _where(self, req: Dict[str, Any], start: str, end: str, select: Optional[Dict[str, Any]],
               unit_ids: Optional[Sequence[int]] = None) -> Tuple[str, List[Any]]:
        where = ["e.survey_id = ?", "e.day BETWEEN ? AND ?"]
        args: List[Any] = [req["survey_id"], start, end]
        ids = list(req.get("unit_ids") or [])
        if unit_ids is not None:
            ids = [i for i in ids if i in set(unit_ids)] if ids else list(unit_ids)
            if not ids:
                where.append("0")
        if ids:
            where.append("e.unit_id IN (%s)" % ",".join("?" * len(ids)))
            args += ids
        if req.get("channel"):
            where.append("e.channel = ?")
            args.append(req["channel"])
        if req.get("completion") in ("completed", "incomplete"):
            where.append("e.completed = ?")
            args.append(1 if req["completion"] == "completed" else 0)
        rel = req.get("reliability")
        if rel == "reliable_only":
            where.append("e.reliable = 1")
        elif rel == "unreliable_only":
            where.append("e.reliable = 0")
        elif rel == "unclassified_only":
            where.append("e.reliable IS NULL")
        for key, val in (select or {}).items():
            if key == "unit":
                where.append("e.unit_id = ?")
                args.append(self.resolve_unit(val))
            elif key == "channel":
                where.append("e.channel = ?")
                args.append(val)
            elif key == "completion":
                where.append("e.completed = ?")
                args.append(1 if val == "completed" else 0)
            elif key in TIME_KINDS:
                lo, hi = periods.bucket_bounds(key, str(val))
                where.append("e.day BETWEEN ? AND ?")
                args += [max(lo.isoformat(), start), min(hi.isoformat(), end)]
            elif key in ("choice",):
                continue  # tratado em counts()
            else:
                raise Unsupported(f"recorte {key} não tem recálculo independente")
        return " AND ".join(where), args

    def counts(self, req: Dict[str, Any], start: str, end: str, select: Optional[Dict[str, Any]] = None,
               group: Optional[str] = None, unit_ids: Optional[Sequence[int]] = None) -> Dict[Any, Dict[str, int]]:
        """Contagens por grupo (None | 'unit' | balde de tempo | 'bucket_unit'). Chaves: evals, answered, p, pa, d, chosen."""
        why = self.supports(req)
        if why:
            raise Unsupported(why)
        metric, qid = req["metric"], req.get("question_id")
        where, args = self._where(req, start, end, select, unit_ids)
        gcols = {"unit": "e.unit_id", "bucket_unit": "e.day, e.unit_id", None: ""}.get(group, "e.day")
        sel = (gcols + ", ") if gcols else ""
        tail = f" GROUP BY {gcols}" if gcols else ""

        def key_of(row: Tuple, width: int) -> Any:
            if group is None:
                return None
            if group == "unit":
                return row[0]
            day = row[0]
            if group == "bucket_unit":
                return (periods.bucket_key(req["_bucket"], day), row[1])
            return periods.bucket_key(group, day)

        width = 2 if group == "bucket_unit" else (1 if group else 0)
        out: Dict[Any, Dict[str, int]] = {}

        def add(key: Any, **vals: int) -> None:
            slot = out.setdefault(key, {"evals": 0, "answered": 0, "p": 0, "pa": 0, "d": 0, "chosen": 0})
            for k, v in vals.items():
                slot[k] += int(v or 0)

        for r in self.db.execute(f"SELECT {sel}COUNT(*) FROM evaluations e WHERE {where}{tail}", args):
            add(key_of(tuple(r), width), evals=r[width])
        if metric == "evaluation_count":
            return out
        if not qid:
            raise Unsupported("métrica de pergunta sem question_id")
        if metric in ("nps", "response_count"):
            q = (f"SELECT {sel}COUNT(*), SUM(a.score >= 9), SUM(a.score BETWEEN 7 AND 8), SUM(a.score <= 6) "
                 f"FROM evaluations e JOIN answers a ON a.survey_id = e.survey_id AND a.eval_ref = e.eval_ref "
                 f"AND a.question_id = ? AND a.kind = 'nps' AND a.answered = 1 WHERE {where}{tail}")
            for r in self.db.execute(q, [qid] + args):
                add(key_of(tuple(r), width), answered=r[width], p=r[width + 1], pa=r[width + 2], d=r[width + 3])
            return out
        # perguntas de escolha: só alternativas atuais da pergunta
        qn = self.catalog.require_survey(req["survey_id"])
        current = [c.id for q_ in qn.questions if q_.id == qid for c in q_.choices]
        if not current:
            raise Unsupported("pergunta sem alternativas")
        marks = ",".join("?" * len(current))
        chosen_ids = [int(x) for x in (req.get("choice_ids") or [])]
        if metric == "choice_share":
            pick = (select or {}).get("choice")
            chosen_ids = [int(pick)] if pick is not None else []
        cmark = ",".join("?" * len(chosen_ids)) if chosen_ids else "NULL"
        q = (f"SELECT {sel}COUNT(*), SUM(a.choice_id IN ({cmark})) FROM evaluations e "
             f"JOIN answers a ON a.survey_id = e.survey_id AND a.eval_ref = e.eval_ref AND a.question_id = ? "
             f"AND a.kind = 'choice' AND a.choice_id IN ({marks}) WHERE {where}{tail}")
        for r in self.db.execute(q, chosen_ids + [qid] + current + args):
            add(key_of(tuple(r), width), answered=r[width], chosen=r[width + 1])
        return out

    def active_units(self, req: Dict[str, Any], start: str, end: str, select: Optional[Dict[str, Any]] = None,
                     unit_ids: Optional[Sequence[int]] = None, bucket: Optional[str] = None) -> Any:
        """Unidades com >= 1 avaliação (no recorte). Com `bucket`, um conjunto por balde de tempo."""
        where, args = self._where(req, start, end, select, unit_ids)
        rows = self.db.execute(f"SELECT DISTINCT e.day, e.unit_id FROM evaluations e WHERE {where}", args).fetchall()
        if not bucket:
            return {r[1] for r in rows if r[1] is not None}
        out: Dict[str, set] = {}
        for day, unit in rows:
            if unit is not None:
                out.setdefault(periods.bucket_key(bucket, day), set()).add(unit)
        return out

    # ---------------------------------------------------- textos
    def texts(self, req: Dict[str, Any], start: str, end: str, question_id: Optional[int] = None,
              reference_question: Optional[int] = None, with_additional: bool = True) -> List[Dict[str, Any]]:
        """Textos guardados no recorte (já mascarados), com a nota NPS de quem escreveu, se houver."""
        where, args = self._where(req, start, end, None)
        kinds = "('open','choice','multi')" if with_additional else "('open')"
        q = (f"SELECT a.eval_ref, e.day, e.unit_id, e.unit_name, a.kind, a.text, a.question_id, r.score "
             f"FROM answers a JOIN evaluations e ON e.survey_id = a.survey_id AND e.eval_ref = a.eval_ref "
             f"LEFT JOIN answers r ON r.survey_id = a.survey_id AND r.eval_ref = a.eval_ref AND r.question_id = ? "
             f"AND r.kind = 'nps' AND r.answered = 1 "
             f"WHERE {where} AND a.text IS NOT NULL AND a.kind IN {kinds}")
        params: List[Any] = [reference_question if reference_question is not None else -1] + args
        if question_id is not None:
            q += " AND a.question_id = ?"
            params.append(question_id)
        cols = ("eval_ref", "day", "unit_id", "unit_name", "kind", "text", "question_id", "score")
        return [dict(zip(cols, r)) for r in self.db.execute(q, params).fetchall()]

    def tags_by_comment(self, survey_id: int, start: str, end: str) -> Dict[Tuple[str, Any], Dict[int, str]]:
        out: Dict[Tuple[str, Any], Dict[int, str]] = {}
        for ev, qid, tid, name in self.db.execute(
                "SELECT eval_ref, question_id, tag_id, tag_name FROM answer_tags WHERE survey_id = ? AND day BETWEEN ? AND ?",
                (survey_id, start, end)):
            out.setdefault((ev, qid), {})[tid] = name
        return out

    # ----------------------------------------------------- valores
    @staticmethod
    def value(req: Dict[str, Any], c: Dict[str, int], field: str = "value") -> Optional[Decimal]:
        m = req["metric"]
        if m == "evaluation_count":
            return Decimal(c["evals"])
        if m == "response_count":
            return Decimal(c["answered"])
        if m == "nps":
            n = c["answered"]
            if field == "n":
                return Decimal(n)
            if not n:
                return None
            if field == "promoters_pct":
                return Decimal(100) * c["p"] / n
            if field == "passives_pct":
                return Decimal(100) * c["pa"] / n
            if field == "detractors_pct":
                return Decimal(100) * c["d"] / n
            return Decimal(100) * (c["p"] - c["d"]) / n
        if field == "n":
            return Decimal(c["answered"])
        if field == "chosen":
            return Decimal(c["chosen"])
        return Decimal(100) * c["chosen"] / c["answered"] if c["answered"] else None

    @staticmethod
    def base_n(req: Dict[str, Any], c: Dict[str, int]) -> int:
        return c["evals"] if req["metric"] == "evaluation_count" else c["answered"]


# ============================================================== parecer
def _row(claim: Dict[str, Any], verdict: str, test: str, **extra: Any) -> Dict[str, Any]:
    return {"id": claim.get("id"), "section": claim.get("section"), "text": claim.get("text"),
            "type": claim.get("type"), "test": test, "verdict": verdict,
            "severity": {OK: None, ADJ: "ajuste", FIX: "correcao", SKIP: None}[verdict], **extra}


def _env_lookup(env: Dict[str, Any], select: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Linha (ou totals) do envelope que casa com o recorte pedido."""
    if not select:
        t = env.get("totals")
        return t if isinstance(t, dict) else None
    for r in env.get("rows") or []:
        dims = r.get("dims") or {}
        ok = True
        for k, v in select.items():
            dv = dims.get(k)
            if isinstance(dv, dict):
                if str(dv.get("id")) != str(v) and str(dv.get("name", "")).casefold() != str(v).casefold():
                    ok = False
            elif str(dv) != str(v):
                ok = False
        if ok:
            return r
    return None


def _env_field(row: Dict[str, Any], field: str) -> Optional[Decimal]:
    src = row if field in ("value", "n") else (row.get("breakdown") or {})
    v = src.get(field)
    return None if v is None else Decimal(str(v))


class Validator:
    def __init__(self, store: Store, catalog: Any, settings: Settings) -> None:
        self.rc = Recompute(store, catalog, settings)
        self.rc.store = store
        self.s = settings
        self.locale = "pt"
        self.queries: Dict[str, Dict[str, Any]] = {}

    # ------------------------------------------------------------ N
    def _selected_value(self, claim: Dict[str, Any], req: Dict[str, Any], env: Dict[str, Any]) -> Tuple[Optional[Decimal], Dict[str, Any], str]:
        start, end = self.rc.window(env)
        select = claim.get("select") or {}
        field = claim.get("field", "value")
        counts = self.rc.counts(req, start, end, select)
        c = counts.get(None) or {"evals": 0, "answered": 0, "p": 0, "pa": 0, "d": 0, "chosen": 0}
        return self.rc.value(req, c, field), c, "independent"

    def check_N(self, claim: Dict[str, Any]) -> Dict[str, Any]:
        rec = self.rc.record(claim["query_id"])
        req, env = rec["request"], rec["envelope"]
        self.queries[claim["query_id"]] = rec
        shown, places = parse_shown(claim["shown"], self.locale)
        level, exact, c = "independent", None, None
        try:
            exact, c, level = self._selected_value(claim, req, env)
        except Unsupported as exc:
            row = _env_lookup(env, claim.get("select") or {})
            if row is None:
                return _row(claim, SKIP, "N", reason=f"{exc}; e a linha não está no envelope")
            exact, level = _env_field(row, claim.get("field", "value")), "envelope_only"
        if exact is None:
            return _row(claim, FIX, "N", shown=str(claim["shown"]), recalculated=None, verification=level,
                        detail="Sem dados no recorte: não há valor a mostrar.")
        res = compare_number(exact, shown, places)
        base = {"shown": str(claim["shown"]), "recalculated": str(fmt.round_half_up(exact, places)),
                "exact": str(exact.quantize(Decimal("0.0001"))), "verification": level}
        if res["ok"]:
            note = "Tolerância de 1 unidade na última casa (fronteira de arredondamento)." if res["tolerance_used"] else None
            return _row(claim, OK, "N", **base, **({"detail": note} if note else {}))
        alt = self._other_base(claim, req, c, shown, places) if c else None
        if alt:
            return _row(claim, ADJ, "N", **base, detail=f"O número bate com outra base ({alt}); a base está mal descrita.")
        dev = deviation(exact, shown)
        verdict = FIX if dev > DEVIATION else ADJ
        return _row(claim, verdict, "N", **base, relative_deviation=None if dev.is_infinite() else float(round(dev, 4)),
                    detail="Número sem base plausível que o reproduza." if verdict == FIX else
                           "Desvio relativo de até 10%, sem mudar a conclusão.")

    def _other_base(self, claim: Dict[str, Any], req: Dict[str, Any], c: Dict[str, int], shown: Decimal, places: int) -> Optional[str]:
        """Testa se o número mostrado bate com outra base plausível (total × respondentes)."""
        cands: Dict[str, Decimal] = {}
        field = claim.get("field", "value")
        if field == "n":
            cands = {"total de avaliações": Decimal(c["evals"]), "respondentes": Decimal(c["answered"])}
        elif req["metric"] == "choice_set_share" and c["evals"]:
            cands = {"total de avaliações": Decimal(100) * c["chosen"] / c["evals"]}
        elif req["metric"] == "choice_share" and c["evals"]:
            cands = {"total de avaliações": Decimal(100) * c["chosen"] / c["evals"]}
        for label, val in cands.items():
            if compare_number(val, shown, places)["ok"]:
                return label
        return None

    # ------------------------------------------------------------ B
    def check_B(self, claim: Dict[str, Any]) -> Dict[str, Any]:
        rec = self.rc.record(claim["query_id"])
        req, env = rec["request"], rec["envelope"]
        self.queries[claim["query_id"]] = rec
        label = claim.get("label", "respondentes")
        shown, places = parse_shown(claim["shown"], self.locale)
        start, end = self.rc.window(env)
        select = claim.get("select") or {}
        level = "independent"
        try:
            base_req = dict(req)
            counts = self.rc.counts(base_req, start, end, select).get(None) or {"evals": 0, "answered": 0}
            total = Decimal(counts["evals"]) if "evals" in counts else Decimal(0)
            if base_req["metric"] != "evaluation_count":
                ev_req = dict(base_req, metric="evaluation_count")
                total = Decimal((self.rc.counts(ev_req, start, end, select).get(None) or {"evals": 0})["evals"])
            answered = Decimal(counts["answered"])
        except Unsupported as exc:
            row = _env_lookup(env, select)
            if row is None:
                return _row(claim, SKIP, "B", reason=str(exc))
            total = Decimal(str(row.get("n") or 0))
            answered, level = total, "envelope_only"
        exposure = (env.get("exposure") or {})
        reached = None
        if not select and isinstance(exposure.get("totals"), dict) and exposure["totals"].get("reached") is not None:
            reached = Decimal(str(exposure["totals"]["reached"]))
        bases = {"avaliacoes": total, "respondentes": answered}
        bases["elegiveis"] = reached if reached is not None else total
        label_key = {"avaliações": "avaliacoes", "elegíveis": "elegiveis"}.get(label, label)
        if label_key not in bases:
            return _row(claim, SKIP, "B", reason=f"rótulo de base desconhecido: {label}")
        out = {"shown": str(claim["shown"]), "label": label, "bases": {k: str(v) for k, v in bases.items()},
               "verification": level}
        if compare_number(bases[label_key], shown, places)["ok"]:
            return _row(claim, OK, "B", **out)
        for other, val in bases.items():
            if other != label_key and compare_number(val, shown, places)["ok"]:
                return _row(claim, ADJ, "B", **out, detail=f"Número certo para a base '{other}', rotulado como '{label}': base mal descrita.")
        dev = deviation(bases[label_key], shown)
        return _row(claim, FIX if dev > DEVIATION else ADJ, "B", **out, detail="Nenhuma base plausível reproduz o número.")

    # ------------------------------------------------------------ Q
    def check_Q(self, claim: Dict[str, Any]) -> Dict[str, Any]:
        rec = self.rc.record(claim["query_id"])
        req, env = rec["request"], rec["envelope"]
        self.queries[claim["query_id"]] = rec
        kind = claim.get("qualifier")
        start, end = self.rc.window(env)
        select = claim.get("select") or {}
        places = int(claim.get("places", 0))
        try:
            if kind in ("quase_totalidade", "maioria", "metade"):
                c = self.rc.counts(req, start, end, select).get(None)
                v = self.rc.value(req, c) if c else None
                if v is None:
                    return _row(claim, FIX, "Q", detail="Sem dados no recorte.")
                ok = {"quase_totalidade": v >= 90, "maioria": v > 50, "metade": Decimal(45) <= v <= Decimal(55)}[kind]
                need = {"quase_totalidade": "≥ 90%", "maioria": "> 50%", "metade": "entre 45% e 55%"}[kind]
                return _row(claim, OK if ok else FIX, "Q", recalculated=str(v.quantize(Decimal("0.1"))), criterion=need,
                            verification="independent", **({} if ok else {"detail": f"O valor não atende {need}."}))
            if kind == "ordinal":
                return self._ordinal(claim, req, start, end)
            if kind in ("sem_abaixo", "faixa", "estavel", "todo_mes"):
                return self._series_qualifier(claim, req, start, end, kind, places)
        except Unsupported as exc:
            return _row(claim, SKIP, "Q", reason=str(exc))
        return _row(claim, SKIP, "Q", reason=f"qualificador desconhecido: {kind}")

    def _ranking(self, claim: Dict[str, Any], req: Dict[str, Any], start: str, end: str) -> List[Tuple[int, Decimal, int]]:
        counts = self.rc.counts(req, start, end, group="unit")
        min_n = int(claim.get("min_n") or 0)
        rows = []
        for unit, c in counts.items():
            n = self.rc.base_n(req, c)
            v = self.rc.value(req, c)
            if v is not None and unit is not None and n >= min_n:
                rows.append((unit, v, n))
        reverse = claim.get("order", "desc") != "asc"
        rows.sort(key=lambda r: (-r[1] if reverse else r[1], r[0]))
        return rows

    def _ordinal(self, claim: Dict[str, Any], req: Dict[str, Any], start: str, end: str) -> Dict[str, Any]:
        unit = self.rc.resolve_unit((claim.get("select") or {}).get("unit"))
        rows = self._ranking(claim, req, start, end)
        places = int(claim.get("places", 0))
        rounded = [(u, fmt.round_half_up(v, places)) for u, v, _ in rows]
        mine = next((v for u, v in rounded if u == unit), None)
        if mine is None:
            return _row(claim, FIX, "Q", detail="A unidade não está no ranking completo do recorte (n mínimo ou sem dados).")
        best = 1 + sum(1 for _, v in rounded if (v > mine if claim.get("order", "desc") != "asc" else v < mine))
        worst = sum(1 for _, v in rounded if (v >= mine if claim.get("order", "desc") != "asc" else v <= mine))
        pos = int(claim["position"])
        ok = best <= pos <= worst
        return _row(claim, OK if ok else FIX, "Q", criterion=f"posição {pos} no ranking completo ({len(rows)} unidades)",
                    recalculated=f"posição {best}" + (f" a {worst} (empate)" if worst != best else ""), verification="independent",
                    **({} if ok else {"detail": "Ordinal não confere com a posição no ranking completo do mesmo recorte."}))

    def _series(self, claim: Dict[str, Any], req: Dict[str, Any], start: str, end: str) -> List[Tuple[str, Decimal]]:
        bucket = claim.get("bucket", "month")
        counts = self.rc.counts(req, start, end, claim.get("select") or {}, group=bucket)
        out = []
        for k in sorted(counts):
            v = self.rc.value(req, counts[k])
            if v is not None:
                out.append((k, v))
        return out

    def _series_qualifier(self, claim, req, start, end, kind, places) -> Dict[str, Any]:
        series = self._series(claim, req, start, end)
        if len(series) < 2 and kind != "faixa" and kind != "sem_abaixo":
            return _row(claim, SKIP, "Q", reason="menos de 2 períodos")
        vals = [v for _, v in series]
        out: Dict[str, Any] = {"series": {k: str(fmt.round_half_up(v, 1)) for k, v in series}, "verification": "independent"}
        if kind == "sem_abaixo":
            x = Decimal(str(claim["threshold"]))
            ok = min(vals) >= x - Decimal("0.5")
            return _row(claim, OK if ok else FIX, "Q", **out, criterion=f"mínimo sem arredondar ≥ {x} − 0,5",
                        recalculated=str(min(vals).quantize(Decimal("0.01"))), **({} if ok else {"detail": "Há valor abaixo do piso afirmado."}))
        if kind == "faixa":
            a, b = Decimal(str(claim["min"])), Decimal(str(claim["max"]))
            shown_vals = [fmt.round_half_up(v, places) for v in vals]
            ok = all(a <= v <= b for v in shown_vals)
            worst = max([a - v for v in shown_vals if v < a] + [v - b for v in shown_vals if v > b] + [Decimal(0)])
            verdict = OK if ok else (ADJ if worst <= Decimal("0.5") else FIX)
            return _row(claim, verdict, "Q", **out, criterion=f"todos os valores em [{a}, {b}]",
                        **({} if ok else {"detail": f"Violação máxima de {worst} p.p. na precisão exibida."}))
        if kind == "estavel":
            first, last = series[0][0], series[-1][0]
            c1 = self.rc.counts(req, *self._bounds(first, claim, start, end), claim.get("select") or {}).get(None)
            c2 = self.rc.counts(req, *self._bounds(last, claim, start, end), claim.get("select") or {}).get(None)
            z = self._z(req, c2, c1)
            ok = z is not None and abs(z) < stats.Z_SINGLE
            return _row(claim, OK if ok else FIX, "Q", **out, criterion="variação primeiro→último dentro do IC95 (|z| < 1,96)",
                        recalculated=None if z is None else f"z = {z:.2f}", **({} if ok else {"detail": "A variação sai do IC95: não é estável."}))
        # todo_mes: mesma direção em todos os passos E aprovação no teste T
        steps = [b - a for a, b in zip(vals, vals[1:])]
        direction = claim.get("direction", "up")
        mono = all((s > 0) if direction == "up" else (s < 0) for s in steps)
        comp = self._composition(claim, req, start, end)
        passed = mono and comp.get("verdict") != "composition_effect"
        why = []
        if not mono:
            why.append("a direção não é a mesma em todos os passos")
        if comp.get("verdict") == "composition_effect":
            why.append("a tendência é efeito de composição")
        return _row(claim, OK if passed else FIX, "Q", **out, criterion="mesma direção em todos os passos e aprovação no teste T",
                    **({} if passed else {"detail": "; ".join(why).capitalize() + "."}), composition_verdict=comp.get("verdict"))

    def _bounds(self, key: str, claim: Dict[str, Any], start: str, end: str) -> Tuple[str, str]:
        lo, hi = periods.bucket_bounds(claim.get("bucket", "month"), key)
        return max(lo.isoformat(), start), min(hi.isoformat(), end)

    @staticmethod
    def _z(req: Dict[str, Any], a: Optional[Dict[str, int]], b: Optional[Dict[str, int]]) -> Optional[float]:
        if not a or not b:
            return None
        if req["metric"] == "nps":
            return stats.nps_z((a["p"], a["d"], a["answered"]), (b["p"], b["d"], b["answered"]))
        return stats.prop_z(a["chosen"], a["answered"], b["chosen"], b["answered"])

    # ------------------------------------------------------------ E
    def check_E(self, claim: Dict[str, Any]) -> Dict[str, Any]:
        rec = self.rc.record(claim["query_id"])
        req, env = rec["request"], rec["envelope"]
        self.queries[claim["query_id"]] = rec
        start, end = self.rc.window(env)
        try:
            group_ids = self.rc.group_unit_ids(claim["group"]) if claim.get("group") else None
            active = self.rc.active_units(req, start, end, claim.get("select"), group_ids)
        except Unsupported as exc:
            return _row(claim, SKIP, "E", reason=str(exc))
        registry = set(group_ids) if group_ids is not None else {u["id"] for u in self.rc.units()}
        out = {"active_units": len(active), "registry_units": len(registry), "verification": "independent"}
        if claim.get("kind") == "list":
            listed = {self.rc.resolve_unit(x) for x in claim.get("listed", [])}
            problems = []
            if listed != active:
                problems.append(f"lista diz {len(listed)} unidade(s), a base mostra {len(active)} ativa(s)")
            if claim.get("expected_count") is not None and int(claim["expected_count"]) != len(active):
                problems.append(f"o texto diz {claim['expected_count']}, a base mostra {len(active)}")
            return _row(claim, FIX if problems else OK, "E", **out, **({"detail": "; ".join(problems) + "."} if problems else {}))
        shown, places = parse_shown(claim["shown"], self.locale)
        if compare_number(Decimal(len(active)), shown, 0)["ok"]:
            return _row(claim, OK, "E", **out, shown=str(claim["shown"]))
        if claim.get("presented_as", "active") == "active" and compare_number(Decimal(len(registry)), shown, 0)["ok"]:
            return _row(claim, FIX, "E", **out, shown=str(claim["shown"]),
                        detail="O número é o do cadastro, apresentado como unidades ativas.")
        return _row(claim, FIX, "E", **out, shown=str(claim["shown"]), detail="A contagem não bate com as unidades ativas.")

    # ------------------------------------------------------------ T
    def _composition(self, claim: Dict[str, Any], req: Dict[str, Any], start: str, end: str) -> Dict[str, Any]:
        bucket = claim.get("bucket", "month")
        req2 = dict(req, _bucket=bucket)
        group_ids = self.rc.group_unit_ids(claim["group"]) if claim.get("group") else None
        raw = self.rc.counts(req2, start, end, group="bucket_unit", unit_ids=group_ids)
        kind = "nps" if req["metric"] == "nps" else "prop"
        counts: Dict[str, Dict[Any, Tuple[int, ...]]] = {}
        for (b, u), c in raw.items():
            counts.setdefault(b, {})[u] = (c["p"], c["d"], c["answered"]) if kind == "nps" else (c["chosen"], c["answered"])
        ev_req = dict(req2, metric="evaluation_count")
        active = {b: set(us) for b, us in self.rc.active_units(ev_req, start, end, None, group_ids, bucket).items()}
        return stats.composition(kind, sorted(set(counts) | set(active)), counts, active)

    def check_T(self, claim: Dict[str, Any]) -> Dict[str, Any]:
        rec = self.rc.record(claim["query_id"])
        req, env = rec["request"], rec["envelope"]
        self.queries[claim["query_id"]] = rec
        if req["metric"] not in ("nps", "choice_set_share"):
            return _row(claim, SKIP, "T", reason="teste de composição vale para nps e choice_set_share")
        start, end = self.rc.window(env)
        try:
            comp = self._composition(claim, req, start, end)
        except Unsupported as exc:
            return _row(claim, SKIP, "T", reason=str(exc))
        summary = {"verdict_composition": comp["verdict"], "contradiction": comp.get("contradiction"),
                   "steps": comp.get("steps"), "verification": "independent"}
        if comp["verdict"] == "composition_effect":
            return _row(claim, FIX, "T", **summary, detail="Efeito de composição: " + " ".join(comp["reasons"]))
        if comp.get("contradiction"):
            return _row(claim, ADJ, "T", **summary, detail="O painel fixo se move no sentido oposto ao afirmado (contradição registrada).")
        if comp["verdict"] in ("insufficient_data", "no_panel"):
            return _row(claim, SKIP, "T", **summary, reason="sem painel fixo ou períodos suficientes")
        return _row(claim, OK, "T", **summary)

    # ------------------------------------------------------------ C
    def check_C(self, claim: Dict[str, Any]) -> Dict[str, Any]:
        rec = self.rc.record(claim["query_id"])
        req, env = rec["request"], rec["envelope"]
        self.queries[claim["query_id"]] = rec
        if not env.get("comparison"):
            return _row(claim, SKIP, "C", reason="a consulta não tem período de comparação")
        select = claim.get("select") or {}
        selected = bool(claim.get("selected_among_many", bool(select)))
        try:
            cur = self.rc.counts(req, *self.rc.window(env), select).get(None)
            prev = self.rc.counts(req, *self.rc.window(env, True), select).get(None)
        except Unsupported as exc:
            return _row(claim, SKIP, "C", reason=str(exc))
        if req["metric"] not in ("nps", "choice_set_share", "choice_share"):
            return _row(claim, SKIP, "C", reason="métrica sem teste de significância definido")
        z = self._z(req, cur, prev)
        verdict_s = stats.classify(z, selected)
        framing = claim.get("framing", "fact")
        out = {"z": None if z is None else round(z, 2), "classification": verdict_s,
               "threshold": stats.Z_SELECTED if selected else stats.Z_SINGLE, "selected_among_many": selected,
               "optimistic_margins": True, "verification": "independent"}
        if claim.get("shown_delta") is not None and cur and prev:
            sd, places = parse_shown(claim["shown_delta"], self.locale)
            v1, v0 = self.rc.value(req, cur), self.rc.value(req, prev)
            if v1 is not None and v0 is not None:
                exact = v1 - v0
                seen = fmt.round_half_up(v1, places) - fmt.round_half_up(v0, places)
                if not (compare_number(exact, sd, places)["ok"] or seen == sd):
                    dev = deviation(exact, sd)
                    return _row(claim, FIX if dev > DEVIATION else ADJ, "C", **out, shown=str(claim["shown_delta"]),
                                recalculated=str(fmt.round_half_up(exact, places)), detail="A variação mostrada não bate com o recálculo.")
        if verdict_s == "robust":
            return _row(claim, OK, "C", **out)
        if framing == "fact":
            what = ("variação selecionada com |z| < 3,29 apresentada como fato" if selected
                    else "comparação agregada sem diferença estatística apresentada como fato")
            return _row(claim, ADJ, "C", **out, detail=f"Ajuste: {what}. Use 'sinal a acompanhar' ou 'sem diferença estatística'.")
        return _row(claim, OK, "C", **out, detail="Apresentada com a ressalva adequada.")

    # ------------------------------------------------------------ R
    def check_R(self, claim: Dict[str, Any]) -> Dict[str, Any]:
        rec = self.rc.record(claim["query_id"])
        req, env = rec["request"], rec["envelope"]
        self.queries[claim["query_id"]] = rec
        start, end = self.rc.window(env)
        problems: List[str] = []
        declared = claim.get("base")
        has_det = req.get("nps_groups") == ["detractor"]
        if declared == "detractors" and not has_det:
            problems.append("o título declara só detratores, mas a consulta usa todas as notas")
        if declared == "all" and req.get("nps_groups"):
            problems.append("o título declara todas as notas, mas a consulta filtra por grupo NPS")
        try:
            rows = self._ranking(claim, req, start, end)
        except Unsupported as exc:
            return _row(claim, SKIP, "R", reason=str(exc))
        places = int(claim.get("places", 0))
        listed_raw = claim.get("listed", [])
        listed = []
        for item in listed_raw:
            ref = item["unit"] if isinstance(item, dict) else item
            listed.append(self.rc.resolve_unit(ref))
            if isinstance(item, dict) and str(item.get("shown", "")).strip() in ("—", "-", "") and any(
                    u == listed[-1] for u, _, _ in rows):
                problems.append(f"campo vazio para a unidade {ref} havendo dado disponível")
        out = {"ranking_size": len(rows), "verification": "independent"}
        if claim.get("kind", "top") == "below":
            thr = Decimal(str(claim["threshold"]))
            expected = {u for u, v, _ in rows if v < thr}
            missing, extra = expected - set(listed), set(listed) - expected
            if missing:
                problems.append(f"faltam {len(missing)} unidade(s) que atendem o critério: {sorted(missing)}")
            if extra:
                problems.append(f"{len(extra)} unidade(s) listada(s) não atendem o critério: {sorted(extra)}")
            if claim.get("shown_count") is not None and int(claim["shown_count"]) != len(expected):
                problems.append(f"o texto diz {claim['shown_count']}, a base mostra {len(expected)}")
            out["expected_units"] = sorted(expected)
        else:
            k = int(claim.get("k", len(listed)))
            if len(listed) != k:
                problems.append(f"a lista tem {len(listed)} item(ns) e o título diz {k}")
            rounded = [(u, fmt.round_half_up(v, places)) for u, v, _ in rows]
            if len(rounded) >= k > 0:
                cut = rounded[k - 1][1]
                better = (lambda v: v > cut) if claim.get("order", "desc") != "asc" else (lambda v: v < cut)
                required = {u for u, v in rounded if better(v)}
                allowed = required | {u for u, v in rounded if v == cut}
                if not required <= set(listed) or not set(listed) <= allowed:
                    problems.append("os itens listados não são exatamente os k primeiros do ranking completo")
                if claim.get("ordered", True):
                    vals = {u: v for u, v in rounded}
                    seq = [vals[u] for u in listed if u in vals]
                    desc = claim.get("order", "desc") != "asc"
                    if seq != sorted(seq, reverse=desc):
                        problems.append("a ordem listada não segue o ranking")
            out["expected_units"] = [u for u, _ in rounded[:k]]
        empty_only = [p for p in problems if p.startswith("campo vazio")]
        if not problems:
            return _row(claim, OK, "R", **out)
        verdict = ADJ if len(empty_only) == len(problems) else FIX
        return _row(claim, verdict, "R", **out, detail="; ".join(problems) + ".")

    # ------------------------------------------------------------ G
    def check_G(self, claim: Dict[str, Any]) -> Dict[str, Any]:
        rec = self.rc.record(claim["query_id"])
        req, env = rec["request"], rec["envelope"]
        self.queries[claim["query_id"]] = rec
        start, end = self.rc.window(env)
        try:
            ids = self.rc.group_unit_ids(claim["group"]) if claim.get("group") else [self.rc.resolve_unit((claim.get("select") or {}).get("unit"))]
            active = self.rc.active_units(req, start, end, None, ids)
            mine = self.rc.counts(req, start, end, unit_ids=ids).get(None) or {"evals": 0, "answered": 0}
            total = self.rc.counts(req, start, end).get(None) or {"evals": 0, "answered": 0}
        except Unsupported as exc:
            return _row(claim, SKIP, "G", reason=str(exc))
        n_mine, n_total = self.rc.base_n(req, mine), self.rc.base_n(req, total)
        share = Decimal(100) * n_mine / n_total if n_total else Decimal(0)
        small = len(active) <= 2 or share < 1
        out = {"active_units": len(active), "share_of_responses_pct": str(share.quantize(Decimal("0.1"))), "verification": "independent"}
        if small:
            return _row(claim, ADJ, "G", **out, detail="Grupo com até 2 unidades ativas ou menos de 1% das respostas não sustenta "
                                                        "'puxa a média' nem pode ser o extremo de uma comparação em título.")
        return _row(claim, OK, "G", **out)

    # ------------------------------------------------------------ D
    def check_D(self, claim: Dict[str, Any]) -> Dict[str, Any]:
        rec = self.rc.record(claim["query_id"])
        req, env = rec["request"], rec["envelope"]
        self.queries[claim["query_id"]] = rec
        if req["metric"] not in ("evaluation_count", "response_count"):
            return _row(claim, SKIP, "D", reason="taxa por dia vale para evaluation_count e response_count")
        start, end = [dt.date.fromisoformat(x) for x in self.rc.window(env)]
        try:
            c = self.rc.counts(req, start.isoformat(), end.isoformat(), claim.get("select") or {}).get(None) or {"evals": 0, "answered": 0}
        except Unsupported as exc:
            return _row(claim, SKIP, "D", reason=str(exc))
        total = Decimal(self.rc.base_n(req, c))
        extraction = claim.get("extraction_time")
        now = dt.datetime.fromisoformat(extraction) if extraction else None
        last = min(end, self.s.today if now is None else now.date())
        days = Decimal(0)
        biz = Decimal(0)
        d = start
        while d <= last:
            frac = Decimal(1)
            if now is not None and d == now.date():
                frac = (Decimal(now.hour) * 60 + Decimal(now.minute)) / Decimal(1440)
            days += frac
            if d.weekday() < 5:
                biz += frac
            d += dt.timedelta(days=1)
        if not days:
            return _row(claim, SKIP, "D", reason="período sem dias decorridos")
        per = claim.get("per", "day")
        rate = total / (biz if per == "business_day" and biz else days)
        shown, places = parse_shown(claim["shown"], self.locale)
        res = compare_number(rate, shown, places)
        out = {"total": str(total), "elapsed_days": str(days.quantize(Decimal("0.01"))),
               "business_days": str(biz.quantize(Decimal("0.01"))), "per_day": str((total / days).quantize(Decimal("0.01"))),
               "per_business_day": str((total / biz).quantize(Decimal("0.01"))) if biz else None,
               "shown": str(claim["shown"]), "recalculated": str(fmt.round_half_up(rate, places)), "verification": "independent"}
        if res["ok"]:
            return _row(claim, OK, "D", **out)
        dev = deviation(rate, shown)
        return _row(claim, FIX if dev > DEVIATION else ADJ, "D", **out, relative_deviation=float(round(dev, 4)),
                    detail="Taxa fora do recálculo (dias corridos, dia parcial fracionado).")

    # ------------------------------------------------------------ U
    def check_U(self, claim: Dict[str, Any]) -> Dict[str, Any]:
        rec = self.rc.record(claim["query_id"])
        req, env = rec["request"], rec["envelope"]
        self.queries[claim["query_id"]] = rec
        start, end = self.rc.window(env)
        try:
            unit = self.rc.resolve_unit(claim["unit"])
            counts = self.rc.counts(dict(req, metric="evaluation_count"), start, end, {"unit": unit}).get(None) or {"evals": 0}
            if claim.get("kind", "interrupted") == "interrupted":
                if counts["evals"] == 0:
                    return _row(claim, ADJ, "U", n=0, verification="independent",
                                detail="Unidade citada sem avaliações no último período: coleta interrompida; sinalize no material.")
                return _row(claim, OK, "U", n=counts["evals"], verification="independent")
            crit = claim["criterion"]
            c = self.rc.counts(req, start, end, {"unit": unit}).get(None)
            v = self.rc.value(req, c) if c else None
            if v is None:
                return _row(claim, ADJ, "U", detail="Sem valor da unidade no período para testar o critério.")
            thr = Decimal(str(crit["value"]))
            ok = {"<": v < thr, "<=": v <= thr, ">": v > thr, ">=": v >= thr}[crit["op"]]
            return _row(claim, OK if ok else ADJ, "U", recalculated=str(v.quantize(Decimal("0.1"))),
                        criterion=f"{crit['op']} {thr}", verification="independent",
                        **({} if ok else {"detail": "A unidade do plano de ação não atende o critério que motivou a ação."}))
        except Unsupported as exc:
            return _row(claim, SKIP, "U", reason=str(exc))

    # ------------------------------------------------------------ K
    @staticmethod
    def _term_count(texts: Sequence[str], terms: Sequence[str], whole: bool, combine: str, accents: bool,
                    mode: str) -> int:
        prep = (lambda s: norm(s)) if accents else (lambda s: s.lower())
        pats = [re.compile(r"(?<!\w)" + re.escape(prep(x)) + (r"(?!\w)" if whole else "")) for x in terms]
        total = 0
        for text in texts:
            s = prep(text)
            if combine == "union":
                hits = [m for m in re.finditer("|".join(p.pattern for p in pats), s)]
                total += (len(hits) if mode == "occurrences" else (1 if hits else 0))
            else:
                for p in pats:
                    n = len(p.findall(s))
                    total += n if mode == "occurrences" else (1 if n else 0)
        return total

    def check_K(self, claim: Dict[str, Any]) -> Dict[str, Any]:
        rec = self.rc.record(claim["query_id"])
        req, env = rec["request"], rec["envelope"]
        self.queries[claim["query_id"]] = rec
        start, end = self.rc.window(env)
        terms = [str(x) for x in claim["terms"]]
        declared_match = claim.get("match", "whole")
        declared_combine = claim.get("combine", "union")
        mode = claim.get("count_mode", "comments")
        ref = claim.get("reference_question")
        qid = claim.get("question_id", req.get("question_id"))
        shown_total = parse_shown(claim["shown_total"], self.locale)[0] if claim.get("shown_total") is not None else None
        shown_det = parse_shown(claim["shown_detractors"], self.locale)[0] if claim.get("shown_detractors") is not None else None
        if shown_total is None and shown_det is None:
            return _row(claim, SKIP, "K", reason="informe shown_total e/ou shown_detractors")
        if shown_det is not None and ref is None:
            return _row(claim, SKIP, "K", reason="detratores exigem reference_question (pergunta NPS de referência)")
        rows_all = self.rc.texts(req, start, end, qid, ref, True)

        def counts(fields: str, accents: bool, match: str, combine: str) -> Tuple[int, int]:
            rows = [r for r in rows_all if fields == "comment+additional" or r["kind"] == "open"]
            tot = self._term_count([r["text"] for r in rows], terms, match == "whole", combine, accents, mode)
            det = self._term_count([r["text"] for r in rows if r["score"] is not None and r["score"] <= 6], terms,
                                   match == "whole", combine, accents, mode)
            return tot, det

        strict = counts("comment", True, declared_match, declared_combine)
        out = {"strict": {"total": strict[0], "detractors": strict[1] if ref is not None else None,
                          "rule": f"só campo de comentário, {'palavra inteira' if declared_match == 'whole' else 'radical'}, "
                                  f"{'união' if declared_combine == 'union' else 'soma'} dos termos, sem diferenciar acento"},
               "verification": "independent"}

        def hits(v: Tuple[int, int]) -> bool:
            return ((shown_total is None or v[0] == shown_total) and (shown_det is None or v[1] == shown_det))

        if hits(strict):
            return _row(claim, OK, "K", **out)
        variants = [(f, a, m, c) for f in ("comment", "comment+additional") for a in (True, False)
                    for m in (declared_match, "stem" if declared_match == "whole" else "whole")
                    for c in (declared_combine, "sum" if declared_combine == "union" else "union")]
        found = next((v for v in variants if hits(counts(*v))), None)
        if found is None:
            ref_v = shown_total if shown_total is not None else shown_det
            got = strict[0] if shown_total is not None else strict[1]
            dev = deviation(Decimal(got), ref_v)
            return _row(claim, FIX if dev > DEVIATION else ADJ, "K", **out, shown=str(claim.get("shown_total", claim.get("shown_detractors"))),
                        detail="Nenhuma variante de contagem reproduz o número do material.")
        fields, accents, match, combine = found
        problems = []
        if fields == "comment+additional":
            problems.append("mistura o campo de comentário com outros campos de texto (cujos autores podem não ser classificáveis no grupo comparado)")
        if match != declared_match:
            problems.append(f"o rótulo diz {'palavra inteira' if declared_match == 'whole' else 'radical'}, mas a contagem usa {'palavra inteira' if match == 'whole' else 'radical'}")
        if combine != declared_combine:
            problems.append("soma os termos onde o rótulo indica união" if declared_combine == "union"
                            else "une os termos onde o rótulo indica soma")
        out["reproduced_by"] = {"fields": fields, "accents_normalized": accents, "match": match, "combine": combine}
        if problems:
            return _row(claim, FIX, "K", **out, detail="O número só se reproduz assim: " + "; ".join(problems) + ".")
        return _row(claim, ADJ, "K", **out, detail="O número só se reproduz sem normalizar acentos; declare a regra de contagem.")

    # ------------------------------------------------------------ A
    # padrões sobre texto sem acento e em minúsculas (norm)
    _UNMEASURED = (("turno", r"\b(turno|manha|tarde|noite|madrugada)\b"),
                   ("refeição", r"\b(almoco|jantar|cafe da manha|lanche|refeicao)\b"),
                   ("causa", r"\b(porque|por causa|devido|causa|motivo|culpa)\b"))

    def check_A(self, claim: Dict[str, Any]) -> Dict[str, Any]:
        rec = self.rc.record(claim["query_id"])
        req, env = rec["request"], rec["envelope"]
        self.queries[claim["query_id"]] = rec
        start, end = self.rc.window(env)
        tag_id = int(claim["tag_id"])
        ref = claim.get("reference_question")
        group = claim.get("group", "all")
        rows = [r for r in self.rc.texts(req, start, end, claim.get("question_id", req.get("question_id")), ref, False) if r["kind"] == "open"]
        if group == "detractors":
            if ref is None:
                return _row(claim, SKIP, "A", reason="grupo detratores exige reference_question")
            rows = [r for r in rows if r["score"] is not None and r["score"] <= 6]
        tags = self.rc.tags_by_comment(req["survey_id"], start, end)
        tagged = [r for r in rows if tags.get((r["eval_ref"], r["question_id"]))]
        with_tag = [r for r in tagged if tag_id in tags[(r["eval_ref"], r["question_id"])]]
        names = {n for d in tags.values() for i, n in d.items() if i == tag_id}
        by_month: Dict[str, List[int]] = {}
        for r in rows:
            m = by_month.setdefault(r["day"][:7], [0, 0])
            m[1] += 1
            m[0] += 1 if tags.get((r["eval_ref"], r["question_id"])) else 0
        out = {"base_comments_with_tag": len(tagged), "with_this_tag": len(with_tag), "comments": len(rows),
               "coverage_by_month": {k: f"{v[0]}/{v[1]}" for k, v in sorted(by_month.items())}, "verification": "independent"}
        problems: List[str] = []
        text = norm(claim.get("text") or "")
        tag_name = norm(" ".join(names) or str(claim.get("tag_name", "")))
        for label, pat in self._UNMEASURED:
            m = re.search(pat, text)
            if m and m.group(0) not in tag_name:
                problems.append(f"a frase fala de {label} ('{m.group(0)}'), que a tag '{', '.join(names) or claim.get('tag_name', tag_id)}' não mede")
        if claim.get("shown") is not None:
            shown, places = parse_shown(claim["shown"], self.locale)
            exact = (Decimal(100) * len(with_tag) / len(tagged)) if (claim.get("field") == "pct" and tagged) else Decimal(len(with_tag))
            if not compare_number(exact, shown, places)["ok"]:
                dev = deviation(exact, shown)
                out.update({"shown": str(claim["shown"]), "recalculated": str(fmt.round_half_up(exact, places))})
                return _row(claim, FIX if dev > DEVIATION else ADJ, "A", **out,
                            detail="Número de tag não confere (base: comentários com ao menos uma tag).")
            out.update({"shown": str(claim["shown"]), "recalculated": str(fmt.round_half_up(exact, places))})
        if problems:
            return _row(claim, FIX, "A", **out, detail="Atribuição indevida (verificação por palavras-chave): " + "; ".join(problems) + ".")
        return _row(claim, OK, "A", **out)

    # ------------------------------------------------------------ V
    def check_V(self, claim: Dict[str, Any]) -> Dict[str, Any]:
        rec = self.rc.record(claim["query_id"])
        req, env = rec["request"], rec["envelope"]
        self.queries[claim["query_id"]] = rec
        start, end = self.rc.window(env)
        quote = privacy.mask_pii(str(claim["quote"]))
        words = norm(quote).split()
        if len(words) < 4:
            return _row(claim, SKIP, "V", reason="o trecho tem menos de 4 palavras")
        needle = " ".join(words)
        hits = []
        for r in self.rc.texts(req, start, end, claim.get("question_id", req.get("question_id")), None, True):
            hay = " ".join(norm(r["text"]).split())
            if needle in hay:
                hits.append((r, 1.0))
                continue
            ws = hay.split()
            n = len(words)
            best = 0.0
            for i in range(0, max(1, len(ws) - n + 1)):
                best = max(best, difflib.SequenceMatcher(None, needle, " ".join(ws[i:i + n])).ratio())
            if best >= 0.9:
                hits.append((r, best))
        out = {"matches": len(hits), "verification": "independent"}
        if not hits:
            lgpd = not privacy.lgpd_text_enabled(self.rc.store)
            return _row(claim, FIX, "V", **out, detail="Citação não localizada na base." + (
                " Se vier de pergunta protegida por LGPD, o texto não é guardado (o usuário pode autorizar com `config --lgpd-text on`)." if lgpd else ""))
        unit = claim.get("unit")
        date = str(claim.get("date") or "")
        ok = []
        for r, ratio in hits:
            u_ok = unit is None or self.rc.resolve_unit(unit) == r["unit_id"]
            d_ok = not date or r["day"].startswith(date)
            if u_ok and d_ok:
                ok.append((r, ratio))
        if ok:
            return _row(claim, OK, "V", **out, **({"note": "pequena correção de digitação aceita"} if ok[0][1] < 1.0 else {}))
        found = hits[0][0]
        return _row(claim, FIX, "V", **out, detail=f"A citação existe, mas na unidade {found['unit_name']} em {found['day']}, "
                                                  "não na unidade e data atribuídas.")

    # ------------------------------------------------------------ P
    def check_P(self, claim: Dict[str, Any]) -> Dict[str, Any]:
        rec = self.rc.record(claim["query_id"])
        req, env = rec["request"], rec["envelope"]
        self.queries[claim["query_id"]] = rec
        start, end = self.rc.window(env)
        pattern = re.compile(str(claim["pattern"]).lower())  # sem acentos, aplicado ao texto normalizado
        threshold = int(claim.get("threshold", 10))
        counts: Dict[Tuple[Any, str], int] = {}
        for r in self.rc.texts(req, start, end, claim.get("question_id", req.get("question_id")), None, True):
            if pattern.search(norm(r["text"])):
                k = (r["unit_id"], r["day"])
                counts[k] = counts.get(k, 0) + 1
        qualifying = {k for k, n in counts.items() if n >= threshold}
        cited, report = set(), []
        worst = OK
        for case in claim.get("cases", []):
            k = (self.rc.resolve_unit(case["unit"]), str(case["date"]))
            cited.add(k)
            n = counts.get(k, 0)
            status = "confirmado" if n >= threshold else ("parcial" if n * 2 >= threshold else "nao_sustentado")
            if status != "confirmado":
                worst = ADJ
            report.append({"unit": case["unit"], "date": case["date"], "comments": n, "status": status})
        uncited = sorted(f"{u}@{d}" for u, d in qualifying - cited)
        out = {"rule": f"surto = >= {threshold} comentários com /{claim['pattern']}/ no mesmo dia e unidade",
               "cases": report, "uncited_qualifying_cases": uncited, "verification": "independent"}
        if worst == ADJ:
            return _row(claim, ADJ, "P", **out, detail="Há caso citado parcial ou não sustentado pela regra declarada.")
        return _row(claim, OK, "P", **out, **({"detail": f"{len(uncited)} caso(s) atendem o critério e não foram citados."} if uncited else {}))

    # ------------------------------------------------------------ L
    _CAUSAL = (
        (r"\btransform(ou|ar|ando|acao|ada|ado)\b", "acompanha / aparece junto de"),
        (r"\bcaus(ou|ar|ando|ado|a)\b", "aparece mais entre / acompanha"),
        (r"\bprovoc(ou|ar|ando|ado)\b", "acompanha"),
        (r"\b(levou|levar|levando|leva)\s+a\b", "aparece junto de"),
        (r"\b(resultou|resultar|resultando|resulta)\s+em\b", "aparece junto de"),
        (r"\b(fez|fazer|fazendo|faz)\s+com\s+que\b", "acompanha"),
    )

    def check_L(self, claim: Dict[str, Any]) -> Dict[str, Any]:
        text = norm(claim.get("text") or "")
        found = [(m.group(0), alt) for pat, alt in self._CAUSAL for m in [re.search(pat, text)] if m]
        if not found:
            return _row(claim, OK, "L", verification="independent")
        return _row(claim, ADJ, "L", verification="independent", causal_terms=[w for w, _ in found],
                    detail="Linguagem causal sobre dado observacional: " + "; ".join(f"'{w}' → '{alt}'" for w, alt in found) + ".")

    # ------------------------------------------------------------ O
    def check_O(self, claim: Dict[str, Any]) -> Dict[str, Any]:
        rec = self.rc.record(claim["query_id"])
        req, env = rec["request"], rec["envelope"]
        self.queries[claim["query_id"]] = rec
        start, end = self.rc.window(env)
        kind = claim.get("kind")
        try:
            if kind in ("trend_up", "trend_down"):
                series = self._series(claim, req, start, end)
                if len(series) < 2:
                    return _row(claim, SKIP, "O", reason="menos de 2 períodos")
                vals = [v for _, v in series]
                diff = vals[-1] - vals[0]
                up = diff > 0
                ok = up if kind == "trend_up" else (diff < 0)
                if claim.get("every_step"):
                    steps = [b - a for a, b in zip(vals, vals[1:])]
                    ok = ok and all((s > 0) if kind == "trend_up" else (s < 0) for s in steps)
                return _row(claim, OK if ok else FIX, "O", verification="independent",
                            series={k: str(fmt.round_half_up(v, 1)) for k, v in series},
                            **({} if ok else {"detail": "O título afirma o contrário do que o dado do próprio slide mostra."}))
            if kind in ("highest", "lowest"):
                r = self._ordinal({**claim, "qualifier": "ordinal", "position": 1,
                                   "order": "desc" if kind == "highest" else "asc"}, req, start, end)
                return {**r, "type": "O", "test": "O", **({"detail": "O título destaca como extremo uma unidade que não é o extremo do slide."} if r["verdict"] != OK else {})}
            if kind in ("above", "below"):
                a = self.rc.counts(req, start, end, claim["select"]).get(None)
                b = self.rc.counts(req, start, end, claim["other_select"]).get(None)
                va, vb = (self.rc.value(req, a) if a else None), (self.rc.value(req, b) if b else None)
                if va is None or vb is None:
                    return _row(claim, SKIP, "O", reason="sem dados em um dos lados")
                ok = va > vb if kind == "above" else va < vb
                return _row(claim, OK if ok else FIX, "O", verification="independent",
                            recalculated=f"{va.quantize(Decimal('0.1'))} vs {vb.quantize(Decimal('0.1'))}",
                            **({} if ok else {"detail": "O título contradiz a comparação dos dados do slide."}))
        except Unsupported as exc:
            return _row(claim, SKIP, "O", reason=str(exc))
        return _row(claim, SKIP, "O", reason="forma de título não estruturada; informe kind: trend_up, trend_down, highest, lowest, above ou below")

    # ------------------------------------------------------------ X
    def check_X(self, claim: Dict[str, Any]) -> Dict[str, Any]:
        rec = self.rc.record(claim["query_id"])
        req, env = rec["request"], rec["envelope"]
        self.queries[claim["query_id"]] = rec
        start, end = self.rc.window(env)
        crit = claim["criterion"]
        thr = Decimal(str(crit["value"]))
        bad, results = [], {}
        try:
            for item in claim["items"]:
                uid = self.rc.resolve_unit(item)
                c = self.rc.counts(req, start, end, {"unit": uid}).get(None)
                v = self.rc.value(req, c) if c else None
                results[str(item)] = None if v is None else str(v.quantize(Decimal("0.1")))
                ok = v is not None and {"<": v < thr, "<=": v <= thr, ">": v > thr, ">=": v >= thr}[crit["op"]]
                if not ok:
                    bad.append(item)
        except Unsupported as exc:
            return _row(claim, SKIP, "X", reason=str(exc))
        out = {"criterion": f"{crit['op']} {thr}", "values": results, "verification": "independent"}
        if bad:
            return _row(claim, ADJ, "X", **out, detail=f"Exemplo(s) que não atendem o critério declarado: {bad}.")
        return _row(claim, OK, "X", **out)

    # ------------------------------------------------------------ geral
    def run(self, payload: Dict[str, Any], locale: str = "pt") -> Dict[str, Any]:
        self.locale = payload.get("material", {}).get("locale", locale)
        claims = payload.get("claims")
        if not isinstance(claims, list) or not claims:
            raise EngineError("invalid_argument", "O arquivo precisa de `claims`: lista não vazia de afirmações.")
        results: List[Dict[str, Any]] = []
        seen = set()
        for i, claim in enumerate(claims, 1):
            claim.setdefault("id", f"c{i}")
            if claim["id"] in seen:
                raise EngineError("invalid_argument", f"Id de afirmação repetido: {claim['id']}.")
            seen.add(claim["id"])
            ctype = claim.get("type")
            if ctype not in ALL_TYPES:
                results.append(_row(claim, SKIP, str(ctype), reason=f"tipo desconhecido: {ctype}"))
                continue
            if not claim.get("query_id") and ctype not in NO_QUERY_TYPES:
                results.append(_row(claim, FIX, ctype, detail="Afirmação sem query_id: número sem fonte (INV-01)."))
                continue
            try:
                results.append(getattr(self, f"check_{ctype}")(claim))
            except EngineError as exc:
                results.append(_row(claim, SKIP, ctype, reason=exc.message))
            except (KeyError, ValueError) as exc:
                results.append(_row(claim, SKIP, ctype, reason=f"afirmação mal formada: {exc}"))
        assert len(results) == len(claims)  # cada afirmação tem veredito
        return build_report(payload, results, self.queries, self.rc, self.s)


# ============================================================== saída
def build_report(payload: Dict[str, Any], results: List[Dict[str, Any]], queries: Dict[str, Dict[str, Any]],
                 rc: Recompute, settings: Settings) -> Dict[str, Any]:
    fixes = [r for r in results if r["verdict"] == FIX]
    adjs = [r for r in results if r["verdict"] == ADJ]
    skipped = [r for r in results if r["verdict"] == SKIP]
    oks = [r for r in results if r["verdict"] == OK]
    checked = []
    for qid, rec in queries.items():
        env = rec["envelope"]
        pol = (env.get("policies") or {}).get("reliability") or {}
        cov = (env.get("coverage") or {}).get("period") or {}
        newest = (env.get("freshness") or {}).get("fetched_newest")
        row = rc.db.execute("SELECT MAX(fetched_at) FROM days WHERE survey_id = ? AND day BETWEEN ? AND ?",
                            (rec["request"]["survey_id"], *rc.window(env))).fetchone()
        checked.append({
            "query_id": qid, "survey": (env.get("scope") or {}).get("survey"), "period": env.get("period"),
            "coverage_complete": not (cov.get("days_partial") or cov.get("days_missing")),
            "data_quality": {"survey_has_data_quality": bool(pol.get("survey_has_data_quality")), "applied": pol.get("applied")},
            "fetched_newest": newest, "fetched_newest_sao_paulo": local_time(newest),
            "cache_changed_since_query": bool(row and row[0] and newest and row[0] > newest),
            "independent_recalculation": rc.supports(rec["request"]) is None,
        })
    if fixes:
        verdict, text = "do_not_send_as_is", f"Não enviar como está: {len(fixes)} correção(ões) obrigatória(s); a de maior impacto é a afirmação {fixes[0]['id']} ({fixes[0].get('detail') or fixes[0]['test']})"
    elif adjs or skipped:
        verdict, text = "can_send_with_caveats", (f"Pode enviar com ressalvas: nenhuma correção obrigatória, mas há {len(adjs)} ajuste(s) e "
                                                  f"{len(skipped)} afirmação(ões) não verificada(s).")
    else:
        verdict, text = "can_send", "Pode enviar: todas as afirmações conferem."
    decision = bool(fixes or adjs or skipped)
    report: Dict[str, Any] = {
        "validation_id": "v_" + secrets.token_hex(4),
        "engine_note": "Parecer gerado a partir do cache local; recálculo independente do query.py nas consultas marcadas 'independent'.",
        "material": payload.get("material", {}),
        "verdict": verdict, "verdict_text": text,
        "decision_required": decision,
        "options": (["corrigir o material e validar de novo", "entregar com as ressalvas listadas no parecer", "descartar o material"]
                    if decision else []),
        "how_checked": {"queries": checked,
                        "citations": _citation_status(results),
                        "lgpd_text": ("lido (mascarado), por autorização do usuário" if privacy.lgpd_text_enabled(rc.store)
                                      else "não guardado: perguntas protegidas por LGPD ficaram fora das buscas de texto"),
                        "unit_note": "Hora local da unidade; n total do material conferido por afirmações do tipo N/B."},
        "summary": {"claims": len(results), OK: len(oks), ADJ: len(adjs), FIX: len(fixes), SKIP: len(skipped)},
        "corrections": fixes, "adjustments": adjs, "confirmed": oks, "not_checked": skipped,
        "annex": [{k: r.get(k) for k in ("section", "text", "type", "shown", "recalculated", "test", "verdict", "severity", "id")} for r in results],
    }
    report["parecer_md"] = render_md(report)
    with open(settings.cache_dir / "validations.jsonl", "a", encoding="utf-8") as fh:
        fh.write(json.dumps({"at": dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat(),
                             "validation_id": report["validation_id"], "summary": report["summary"],
                             "verdict": verdict}, ensure_ascii=False) + "\n")
    return report


def _citation_status(results: List[Dict[str, Any]]) -> str:
    cites = [r for r in results if r["type"] == "V"]
    if not cites:
        return "nenhuma citação no material"
    ok = sum(1 for r in cites if r["verdict"] == OK)
    return f"{ok} de {len(cites)} citação(ões) localizada(s) com a unidade e a data atribuídas"


def render_md(r: Dict[str, Any]) -> str:
    L: List[str] = [f"**Veredito:** {r['verdict_text']}", "", "**Como conferi**"]
    for q in r["how_checked"]["queries"]:
        s = q.get("survey") or {}
        p = q.get("period") or {}
        L.append(f"- Consulta `{q['query_id']}`: pesquisa {s.get('id')} ({s.get('name')}), {p.get('start')} a {p.get('end')}; "
                 f"dados baixados em {q.get('fetched_newest_sao_paulo')}; cobertura {'completa' if q['coverage_complete'] else 'INCOMPLETA'}; "
                 f"Data Quality {'ligado, política ' + str(q['data_quality']['applied']) if q['data_quality']['survey_has_data_quality'] else 'desligado'}; "
                 f"recálculo {'independente' if q['independent_recalculation'] else 'só contra o envelope'}"
                 + ("; **o cache foi atualizado depois da consulta**" if q["cache_changed_since_query"] else "") + ".")
    L.append(f"- Citações: {r['how_checked']['citations']}.")
    L.append(f"- Texto de perguntas LGPD: {r['how_checked']['lgpd_text']}.")
    if r["confirmed"]:
        L += ["", "**O que confere**"] + [f"- [{c['type']}] {c.get('section') or ''} {c.get('text') or ''}".rstrip() for c in r["confirmed"]]
    for title, items in (("Correções obrigatórias", r["corrections"]), ("Ajustes de redação e método", r["adjustments"])):
        if items:
            L += ["", f"**{title}**"]
            for i, c in enumerate(items, 1):
                L.append(f"{i}. [{c['type']}] seção {c.get('section') or '-'}: \"{c.get('text') or ''}\". "
                         f"Material: {c.get('shown', '-')}; base: {c.get('recalculated', '-')}. {c.get('detail', '')}".strip())
    if r["not_checked"]:
        L += ["", "**Não verificadas**"] + [f"- [{c['type']}] {c.get('text') or ''}: {c.get('reason', '')}" for c in r["not_checked"]]
    L += ["", "**Anexo**", "| id | seção | tipo | afirmação | material | recalculado | teste | veredito |", "|---|---|---|---|---|---|---|---|"]
    for a in r["annex"]:
        L.append(f"| {a['id']} | {a.get('section') or ''} | {a['type']} | {(a.get('text') or '').replace('|', '/')} | "
                 f"{a.get('shown') or ''} | {a.get('recalculated') or ''} | {a['test']} | {a['verdict']} |")
    if r["decision_required"]:
        L += ["", "**Decisão do usuário:** " + "; ".join(f"({i}) {o}" for i, o in enumerate(r["options"], 1))]
    return "\n".join(L)
