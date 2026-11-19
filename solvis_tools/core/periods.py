"""Períodos: presets resolvidos em datas pelo código (o modelo nunca faz conta de data)."""
import datetime as dt
import os
import re

from .errors import ToolError

TODAY = os.environ.get("AGENT_TODAY", dt.date.today().isoformat())

PRESETS = {"ontem": "yesterday", "yesterday": "yesterday", "hoje": "today", "today": "today",
           "last_7_days": "last_7_days", "ultimos_7_dias": "last_7_days", "this_month": "this_month",
           "este_mes": "this_month", "last_month": "last_month", "mes_passado": "last_month"}


def resolve_period(preset):
    """Preset -> (start, end). O modelo nunca faz conta de data."""
    t = dt.date.fromisoformat(TODAY)
    raw = str(preset).strip().lower()
    m = re.fullmatch(r"month:(\d{4})-(\d{2})", raw)
    if m:
        first = dt.date(int(m.group(1)), int(m.group(2)), 1)
        nxt = (first + dt.timedelta(days=32)).replace(day=1)
        return first.isoformat(), (nxt - dt.timedelta(days=1)).isoformat()
    key = PRESETS.get(raw)
    if key == "today":
        return t.isoformat(), t.isoformat()
    if key == "yesterday":
        y = t - dt.timedelta(days=1)
        return y.isoformat(), y.isoformat()
    if key == "last_7_days":
        return (t - dt.timedelta(days=7)).isoformat(), (t - dt.timedelta(days=1)).isoformat()
    if key == "this_month":
        return t.replace(day=1).isoformat(), t.isoformat()
    if key == "last_month":
        last = t.replace(day=1) - dt.timedelta(days=1)
        return last.replace(day=1).isoformat(), last.isoformat()
    raise ToolError("period aceita yesterday, today, last_7_days, this_month, last_month ou month:AAAA-MM")


def resolve_dates(args):
    if args.get("period"):
        return resolve_period(args["period"])
    for k in ("start", "end"):  # o modelo às vezes manda o preset no lugar da data
        if str(args.get(k, "")).strip().lower() in PRESETS:
            return resolve_period(args[k])
    try:
        s, e = dt.date.fromisoformat(str(args["start"])), dt.date.fromisoformat(str(args["end"]))
    except (KeyError, ValueError):
        raise ToolError("informe period (ex.: yesterday, month:2026-10) ou start/end AAAA-MM-DD")
    if s > e:
        raise ToolError("start depois de end")
    return s.isoformat(), e.isoformat()
