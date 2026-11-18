"""Arredondamento e exibição, iguais aos das telas.

- Ruby Float#round (NPS) arredonda o valor binário exato, meio para longe do zero.
- number_with_precision / number_to_percentage arredondam meio para cima sobre a
  representação decimal do número.
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal
from typing import Optional, Union

Number = Union[int, float, Decimal]

SEPARATORS = {"pt": (".", ","), "es": (".", ","), "en": (",", ".")}
POINTS = {"pt": "pontos", "es": "puntos", "en": "points"}
PP = {"pt": "p.p.", "es": "p.p.", "en": "pp"}


def to_decimal(x: Number) -> Decimal:
    if isinstance(x, Decimal):
        return x
    if isinstance(x, float):
        return Decimal(repr(x))
    return Decimal(x)


def round_half_up(x: Number, places: int) -> Decimal:
    q = Decimal(1).scaleb(-places)
    return to_decimal(x).quantize(q, rounding=ROUND_HALF_UP)


def ruby_round_int(x: float) -> int:
    """(100.0 * fração).round do Ruby: valor binário exato, meio para longe do zero."""
    return int(Decimal(x).to_integral_value(rounding=ROUND_HALF_UP))


def fmt_decimal(x: Number, places: int, locale: str = "pt") -> str:
    thousands, decimal = SEPARATORS.get(locale, SEPARATORS["pt"])
    value = round_half_up(x, places)
    sign = "-" if value < 0 else ""
    value = abs(value)
    text = f"{value:.{places}f}"
    whole, _, frac = text.partition(".")
    groups = []
    while len(whole) > 3:
        groups.insert(0, whole[-3:])
        whole = whole[:-3]
    groups.insert(0, whole)
    out = thousands.join(groups)
    if places > 0:
        out += decimal + frac
    return sign + out


def fmt_count(n: int, locale: str = "pt") -> str:
    return fmt_decimal(n, 0, locale)


def fmt_pct(x: Number, places: int = 1, locale: str = "pt") -> str:
    return fmt_decimal(x, places, locale) + "%"


def signed(text: str, value: Number) -> str:
    return ("+" + text) if to_decimal(value) > 0 else text


def fmt_delta(value: Number, places: int, unit: Optional[str], locale: str = "pt") -> str:
    """unit: 'points' (NPS), 'pp' (pontos percentuais), '%' ou None (mesma unidade da métrica)."""
    text = signed(fmt_decimal(value, places, locale), value)
    if unit == "points":
        return f"{text} {POINTS.get(locale, POINTS['pt'])}"
    if unit == "pp":
        return f"{text} {PP.get(locale, PP['pt'])}"
    if unit == "%":
        return text + "%"
    return text
