"""Fórmulas das métricas a partir de contagens, iguais às das telas de resultados.

Referências no survey_system:
- NPS: app/models/results/answer_counts/count_base.rb:86-90 e utils.rb:10-12
- média de escala: count_base.rb:131-147; casas: question.rb:323-335
- soma ponderada: count_base.rb:153-167
- distribuição: count_base.rb:44-62; múltipla resposta: consolidated_count.rb:43-51
- zonas de referência: app/helpers/results/reference_zone_helper.rb:18-50
Agregar grupos é sempre somar contagens e recalcular (nunca média de valores).
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any, Dict, Iterable, List, Optional, Tuple

from . import fmt
from .semantics import Question

ZONE_LABELS = {
    "pt": {
        "critical": "Zona Crítica", "improvement": "Zona de Aperfeiçoamento", "quality": "Zona de Qualidade",
        "excellence": "Zona de Excelência", "enchantment": "Zona de Encantamento",
    },
    "en": {
        "critical": "Critical zone", "improvement": "Improvement zone", "quality": "Quality zone",
        "excellence": "Excellence zone", "enchantment": "Enchantment zone",
    },
    "es": {
        "critical": "Zona Crítica", "improvement": "Zona de Perfeccionamiento", "quality": "Zona de Calidad",
        "excellence": "Zona de Excelencia", "enchantment": "Zona de Encanto",
    },
}


def share_pct(part: int, whole: int) -> Optional[Decimal]:
    """Percentual com 1 casa (print_percentage), ou None sem denominador."""
    if not whole:
        return None
    return fmt.round_half_up((part / whole) * 100, 1)


def reference_zone(nps: int, question: Question, locale: str) -> Optional[Dict[str, str]]:
    mode = question.reference_zone
    if mode == "none":
        return None
    if nps <= 0:
        key = "critical"
    elif nps <= 50:
        key = "improvement"
    elif nps <= 75:
        key = "quality"
    elif mode == "with_enchantment" and nps >= 91:
        key = "enchantment"
    else:
        key = "excellence"
    return {"key": key, "label": ZONE_LABELS.get(locale, ZONE_LABELS["pt"])[key]}


def _pct_with_display(breakdown: Dict[str, Any], locale: str) -> Dict[str, Any]:
    """Acrescenta <campo>_display a cada percentual do breakdown, para a LLM não formatar números."""
    out = dict(breakdown)
    for key, value in breakdown.items():
        if key.endswith("_pct"):
            out[key + "_display"] = fmt.fmt_pct(value, 1, locale) if value is not None else "-"
    return out


def nps_result(p: int, ne: int, d: int, question: Question, locale: str) -> Dict[str, Any]:
    n = p + ne + d
    breakdown = _pct_with_display({
        "promoters": p, "passives": ne, "detractors": d,
        "promoters_pct": _f(share_pct(p, n)), "passives_pct": _f(share_pct(ne, n)),
        "detractors_pct": _f(share_pct(d, n)),
    }, locale)
    if n == 0:
        return {"value": None, "n": 0, "display": "-", "breakdown": breakdown}
    value = fmt.ruby_round_int(100.0 * (p / n - d / n))
    out = {"value": value, "n": n, "display": str(value), "breakdown": breakdown}
    zone = reference_zone(value, question, locale)
    if zone:
        out["reference_zone"] = zone
    return out


def scale_mean_result(counts: Dict[int, int], question: Question, locale: str) -> Dict[str, Any]:
    valued = question.valued_choices
    n = sum(counts.get(c.id, 0) for c in valued)
    answered = sum(counts.get(c.id, 0) for c in question.choices)
    lo = min((c.value for c in valued), default=None)
    hi = max((c.value for c in valued), default=None)
    breakdown = {
        "scale_min": _f(lo), "scale_max": _f(hi),
        "valueless_answers": answered - n, "answered_including_valueless": answered,
    }
    if n == 0:
        return {"value": None, "n": 0, "display": "-", "breakdown": breakdown}
    total = sum(Decimal(counts.get(c.id, 0)) * c.value for c in valued)
    mean = float(total) / float(n)
    places = question.decimal_places()
    rounded = fmt.round_half_up(mean, places)
    display = fmt.fmt_decimal(rounded, places, locale) + ("%" if question.is_percentual_scale() else "")
    return {"value": float(rounded), "n": n, "display": display, "breakdown": breakdown}


def weighted_sum_result(counts: Dict[int, int], question: Question, locale: str) -> Dict[str, Any]:
    valued = question.valued_choices
    n = sum(counts.get(c.id, 0) for c in valued)
    lo, hi = question.value_range()
    breakdown = {"weighted_min": _f(lo), "weighted_max": _f(hi)}
    if n == 0:
        return {"value": None, "n": 0, "display": "-", "breakdown": breakdown}
    total = Decimal(0)
    for c in valued:
        pct = counts.get(c.id, 0) * 100.0 / n
        total += fmt.to_decimal(pct) * c.value
    value = int(fmt.round_half_up(total, 0))
    places = question.decimal_places()
    display = fmt.fmt_decimal(value, places, locale) + ("%" if question.is_percentual_scale() else "")
    return {"value": value, "n": n, "display": display, "breakdown": breakdown}


def choice_rows(
    counts: Dict[int, int], answered: int, question: Question, locale: str, by_count: bool = False
) -> List[Dict[str, Any]]:
    """Uma linha por alternativa atual da pergunta (inclusive as sem resposta)."""
    rows = []
    for c in question.choices:
        chosen = counts.get(c.id, 0)
        pct = share_pct(chosen, answered)
        rows.append({
            "choice": {"id": c.id, "letter": c.letter, "text": c.label,
                       **({"value": _f(c.value)} if c.value is not None else {})},
            "value": _f(pct), "n": answered, "chosen": chosen,
            "display": fmt.fmt_pct(pct, 1, locale) if pct is not None else "-",
        })
    if by_count:
        rows.sort(key=lambda r: -r["chosen"])
    return rows


def choice_set_result(counts: Dict[int, int], answered: int, choice_ids: Iterable[int],
                      question: Question, locale: str) -> Dict[str, Any]:
    ids = set(choice_ids)
    chosen = sum(counts.get(cid, 0) for cid in ids)
    pct = share_pct(chosen, answered)
    return {
        "value": _f(pct), "n": answered,
        "display": fmt.fmt_pct(pct, 1, locale) if pct is not None else "-",
        "breakdown": {
            "chosen": chosen, "answered": answered,
            "choice_set": [{"id": c.id, "letter": c.letter, "text": c.label} for c in question.choices if c.id in ids],
        },
    }


def count_result(n: int, locale: str) -> Dict[str, Any]:
    return {"value": n, "n": n, "display": fmt.fmt_count(n, locale)}


def dq_result(total: int, reliable: int, unreliable: int, unclassified: int, locale: str) -> Dict[str, Any]:
    return {
        "value": total, "n": total, "display": fmt.fmt_count(total, locale),
        "breakdown": _pct_with_display({
            "reliable": reliable, "unreliable": unreliable, "unclassified": unclassified,
            "reliable_pct": _f(share_pct(reliable, total)), "unreliable_pct": _f(share_pct(unreliable, total)),
            "unclassified_pct": _f(share_pct(unclassified, total)),
        }, locale),
    }


def delta(current: Dict[str, Any], compared: Dict[str, Any], metric: str, question: Optional[Question],
          locale: str) -> Optional[Dict[str, Any]]:
    """Variação calculada sobre os valores já arredondados (o que o leitor vê)."""
    a, b = current.get("value"), compared.get("value")
    if a is None or b is None:
        return None
    da, db = fmt.to_decimal(a), fmt.to_decimal(b)
    diff = da - db
    if metric == "nps":
        out_nps: Dict[str, Any] = {"value": int(diff), "display": fmt.fmt_delta(diff, 0, "points", locale)}
        cb, pb = current.get("breakdown") or {}, compared.get("breakdown") or {}
        for key in ("promoters_pct", "passives_pct", "detractors_pct"):
            if cb.get(key) is not None and pb.get(key) is not None:
                d = fmt.to_decimal(cb[key]) - fmt.to_decimal(pb[key])
                out_nps[key] = float(d)
                out_nps[key + "_display"] = fmt.fmt_delta(d, 1, "pp", locale)
        return out_nps
    if metric in ("scale_mean", "weighted_sum"):
        places = question.decimal_places() if question else 2
        return {"value": float(diff), "display": fmt.fmt_delta(diff, places, None, locale)}
    if metric in ("evaluation_count", "response_count", "data_quality_summary"):
        out: Dict[str, Any] = {"value": int(diff), "display": fmt.signed(fmt.fmt_count(int(diff), locale), diff)}
        if db > 0:
            change = fmt.round_half_up(float(diff) / float(db) * 100, 1)
            out["pct_change"] = float(change)
            out["pct_change_display"] = fmt.fmt_delta(change, 1, "%", locale)
        return out
    # percentuais (distribuições, conjunto de alternativas, tags)
    return {"value": float(diff), "display": fmt.fmt_delta(diff, 1, "pp", locale)}


def _f(x: Optional[Decimal]) -> Any:
    if x is None:
        return None
    return int(x) if x == x.to_integral_value() and x.as_tuple().exponent >= 0 else float(x)


def pooled_counts(rows: Iterable[Tuple[Any, int]]) -> Dict[Any, int]:
    out: Dict[Any, int] = {}
    for key, n in rows:
        out[key] = out.get(key, 0) + n
    return out
