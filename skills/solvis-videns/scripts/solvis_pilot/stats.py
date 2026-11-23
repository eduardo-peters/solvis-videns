"""Testes estatísticos do protocolo de validação (references/validation-protocol.md), em funções puras.

Sem acesso ao cache nem ao motor de consulta: recebem contagens e devolvem números. Isso permite
testar com valores calculados à mão e, mais tarde, usar o mesmo módulo no verificador de afirmações.

Limiares fixos (não afrouxar):
- comparação agregada única: robusta se |z| >= 1,96;
- variação selecionada entre muitas linhas: robusta se |z| >= 3,29 (Bonferroni, ~50 comparações);
- abaixo disso e com |z| >= 1,96 (ou 3,29 em seleção): "sinal a acompanhar";
- as margens são otimistas: um mesmo respondente pode avaliar várias vezes.
"""

from __future__ import annotations

from math import sqrt
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

Z_SINGLE = 1.96
Z_SELECTED = 3.29

PROPORTION_METRICS = ("choice_share", "choice_set_share", "multi_response_share", "tag_mentions")

DISPLAY = {
    "pt": {"robust": "variação robusta", "signal_to_monitor": "sinal a acompanhar",
           "not_significant": "sem diferença estatística", "not_testable": "não testável"},
    "en": {"robust": "robust change", "signal_to_monitor": "signal to monitor",
           "not_significant": "not statistically different", "not_testable": "not testable"},
    "es": {"robust": "variación robusta", "signal_to_monitor": "señal a seguir",
           "not_significant": "sin diferencia estadística", "not_testable": "no evaluable"},
}


# ------------------------------------------------------------------ NPS
def nps_value(p: int, d: int, n: int) -> Optional[float]:
    """NPS em pontos, sem arredondar."""
    return 100.0 * (p / n - d / n) if n else None


def nps_se(p: int, d: int, n: int) -> Optional[float]:
    """SE = sqrt[(p + d - (p - d)^2) / n], p e d em proporção. Devolvido em pontos de NPS."""
    if not n:
        return None
    pp, dd = p / n, d / n
    return 100.0 * sqrt(max(0.0, pp + dd - (pp - dd) ** 2) / n)


def nps_z(cur: Tuple[int, int, int], prev: Tuple[int, int, int]) -> Optional[float]:
    """z da diferença de NPS entre dois conjuntos (p, d, n): delta / sqrt(SE1^2 + SE2^2)."""
    s1, s2 = nps_se(*cur), nps_se(*prev)
    if s1 is None or s2 is None:
        return None
    den = sqrt(s1 ** 2 + s2 ** 2)
    if den == 0:
        return None
    return (nps_value(*cur) - nps_value(*prev)) / den


# ----------------------------------------------------------- proporções
def prop_z(x1: int, n1: int, x2: int, n2: int) -> Optional[float]:
    """z de duas proporções (variância combinada)."""
    if not n1 or not n2:
        return None
    pooled = (x1 + x2) / (n1 + n2)
    den = sqrt(pooled * (1 - pooled) * (1 / n1 + 1 / n2))
    if den == 0:
        return None
    return (x1 / n1 - x2 / n2) / den


# ---------------------------------------------------------- classificação
def classify(z: Optional[float], selected: bool) -> str:
    if z is None:
        return "not_testable"
    a = abs(z)
    if a < Z_SINGLE:
        return "not_significant"
    if a >= (Z_SELECTED if selected else Z_SINGLE):
        return "robust"
    return "signal_to_monitor"


def _verdict(z: Optional[float], selected: bool, test: str, locale: str, extra: Dict[str, Any]) -> Dict[str, Any]:
    verdict = classify(z, selected)
    return {
        "test": test, "z": None if z is None else round(z, 2),
        "threshold": Z_SELECTED if selected else Z_SINGLE, "selected_among_many": selected,
        "verdict": verdict, "display": DISPLAY.get(locale, DISPLAY["pt"])[verdict],
        "optimistic_margins": True, **extra,
    }


def _nps_counts(res: Dict[str, Any]) -> Optional[Tuple[int, int, int]]:
    b = res.get("breakdown") or {}
    if "promoters" in b and "detractors" in b and res.get("n"):
        return int(b["promoters"]), int(b["detractors"]), int(res["n"])
    return None


def _prop_counts(res: Dict[str, Any]) -> Optional[Tuple[int, int]]:
    b = res.get("breakdown") or {}
    if "chosen" in b and "answered" in b:
        return int(b["chosen"]), int(b["answered"])
    if "chosen" in res and res.get("n"):
        return int(res["chosen"]), int(res["n"])
    if "mentions" in res and res.get("n"):
        return int(res["mentions"]), int(res["n"])
    return None


def significance(metric: str, current: Dict[str, Any], compared: Dict[str, Any], selected: bool,
                 locale: str = "pt") -> Optional[Dict[str, Any]]:
    """Teste da variação entre dois resultados do motor; None quando a métrica não tem teste definido."""
    if metric == "nps":
        a, b = _nps_counts(current), _nps_counts(compared)
        if not a or not b:
            return None
        return _verdict(nps_z(a, b), selected, "nps_difference", locale, {
            "se_current": round(nps_se(*a), 2), "se_compared": round(nps_se(*b), 2), "unit": "points"})
    if metric in PROPORTION_METRICS:
        a, b = _prop_counts(current), _prop_counts(compared)
        if not a or not b:
            return None
        return _verdict(prop_z(a[0], a[1], b[0], b[1]), selected, "two_proportions", locale, {"unit": "pp"})
    return None


# ------------------------------------------------- composição (painel fixo)
def _sum(counts: Iterable[Sequence[int]], width: int) -> Tuple[int, ...]:
    total = [0] * width
    for c in counts:
        for i in range(width):
            total[i] += c[i]
    return tuple(total)


def composition(kind: str, buckets: Sequence[str], counts: Dict[str, Dict[Any, Tuple[int, ...]]],
                active: Dict[str, set]) -> Dict[str, Any]:
    """Teste de composição de uma tendência de agregado.

    kind: "nps" (contagens (promotores, detratores, n)) ou "prop" (contagens (x, n)).
    counts[balde][unidade]: contagens da métrica. active[balde]: unidades com >= 1 avaliação no balde.
    Painel fixo = unidades ativas em todos os baldes.
    """
    width = 3 if kind == "nps" else 2
    value = (lambda c: nps_value(*c)) if kind == "nps" else (lambda c: 100.0 * c[0] / c[1] if c[1] else None)
    zfn = (lambda a, b: nps_z(a, b)) if kind == "nps" else (lambda a, b: prop_z(a[0], a[1], b[0], b[1]))
    n_of = (lambda c: c[2]) if kind == "nps" else (lambda c: c[1])

    def r(x: Optional[float], places: int = 2) -> Optional[float]:
        return None if x is None else round(x, places)

    if len(buckets) < 2:
        return {"verdict": "insufficient_data", "reasons": ["É preciso ao menos 2 períodos."]}
    panel = set.intersection(*(set(active.get(b, ())) for b in buckets)) if buckets else set()
    rows: List[Dict[str, Any]] = []
    agg: Dict[str, Tuple[int, ...]] = {}
    pan: Dict[str, Tuple[int, ...]] = {}
    for b in buckets:
        units = counts.get(b, {})
        agg[b] = _sum(units.values(), width)
        pan[b] = _sum((c for u, c in units.items() if u in panel), width)
        out = tuple(x - y for x, y in zip(agg[b], pan[b]))
        rows.append({
            "bucket": b, "active_units": len(active.get(b, ())), "panel_units": len(panel),
            "aggregate": {"value": r(value(agg[b])), "n": n_of(agg[b])},
            "panel": {"value": r(value(pan[b])), "n": n_of(pan[b])},
            "outside_panel": {"value": r(value(out)) if n_of(out) else None, "n": n_of(out)},
        })
    steps: List[Dict[str, Any]] = []
    for a, b in zip(buckets, buckets[1:]):
        va, vb, pa, pb = value(agg[a]), value(agg[b]), value(pan[a]), value(pan[b])
        d_agg = None if va is None or vb is None else vb - va
        d_pan = None if pa is None or pb is None else pb - pa
        z = zfn(pan[b], pan[a]) if n_of(pan[a]) and n_of(pan[b]) else None
        share = None if d_agg in (None, 0) or d_pan is None else 1 - d_pan / d_agg
        steps.append({"from": a, "to": b, "delta_aggregate": r(d_agg), "delta_panel": r(d_pan),
                      "z_panel": r(z), "composition_share": r(share, 3)})

    reasons: List[str] = []
    testable = [s for s in steps if s["composition_share"] is not None and s["z_panel"] is not None]
    cond_a = bool(testable) and sum(
        1 for s in testable if s["composition_share"] > 0.5 and abs(s["z_panel"]) < Z_SINGLE) > len(testable) / 2
    if cond_a:
        reasons.append("Na maioria dos passos, mais de 50% da variação vem da composição e o painel fixo não varia de forma significativa.")

    first, last = buckets[0], buckets[-1]
    cohort = set(active.get(first, ())) & {u for u, c in counts.get(last, {}).items() if n_of(c)}
    c_first = _sum((c for u, c in counts.get(first, {}).items() if u in cohort), width)
    c_last = _sum((c for u, c in counts.get(last, {}).items() if u in cohort), width)
    v_first, v_last = value(agg[first]), value(agg[last])
    d_total = None if v_first is None or v_last is None else v_last - v_first
    cohort_info: Dict[str, Any] = {"units": len(cohort)}
    cond_b = False
    if n_of(c_first) and n_of(c_last):
        d_cohort = value(c_last) - value(c_first)
        z_cohort = zfn(c_last, c_first)
        cohort_info.update({"delta": r(d_cohort), "z": r(z_cohort)})
        changed = len(active.get(first, ())) != len(active.get(last, ()))
        opposite = d_total not in (None, 0) and d_cohort * d_total < 0
        if changed and ((z_cohort is not None and abs(z_cohort) < Z_SINGLE) or (z_cohort is None) or opposite):
            cond_b = True
            reasons.append("O número de unidades do agregado mudou e as unidades presentes no início não repetem a tendência.")

    contradiction = False
    if n_of(pan[first]) and n_of(pan[last]) and d_total not in (None, 0):
        d_panel_total = value(pan[last]) - value(pan[first])
        contradiction = d_panel_total * d_total < 0
        if contradiction:
            reasons.append("O painel fixo se move no sentido oposto ao do agregado.")
    if not panel:
        reasons.append("Nenhuma unidade tem avaliação em todos os períodos: não há painel fixo.")

    verdict = "composition_effect" if (cond_a or cond_b) else ("no_panel" if not panel else "no_composition_effect")
    return {"kind": kind, "buckets": rows, "steps": steps, "start_cohort": cohort_info,
            "contradiction": contradiction, "verdict": verdict, "reasons": reasons,
            "optimistic_margins": True}
