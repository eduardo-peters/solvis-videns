"""Biblioteca de gráficos do agente local.

Cada gráfico é uma especificação (JSON) que a tela desenha (agent/static/charts.js) e que qualquer
cliente MCP pode desenhar. Os números saem das mesmas views e contagens das tools de métrica, com as
mesmas fórmulas (NPS por contagens, média sem "Não se aplica", distribuição com N/A no denominador).
O modelo só escolhe o tipo, a métrica e o recorte; não calcula nem desenha.

Tipos (KINDS):
  bar        barras verticais: métrica por recorte
  hbar       barras horizontais: ranking (unidades, regionais...)
  line       linha: métrica ao longo das horas do dia
  area       área: volume ao longo das horas do dia
  combo      barras de volume + linha de NPS por hora (dois eixos)
  stacked    100% empilhado: promotores, neutros e detratores por recorte
  donut      rosca: distribuição de uma pergunta ou volume por canal
  histogram  notas de 0 a 10 da pergunta NPS, coloridas por grupo
  scatter    unidades: volume (x) × NPS (y), tamanho = respostas
  heatmap    unidades × hora: volume ou NPS
  profile    média de todas as perguntas de escala da pesquisa
Recortes (by): unit, hour, channel, completion, survey (só volume) ou nome da propriedade de unidade.
Métricas: evaluation_count, nps, scale_mean, choice_share.
"""
import re

import agent as A

KINDS = ("bar", "hbar", "line", "area", "combo", "stacked", "donut", "histogram", "scatter", "heatmap", "profile")
METRICS = ("evaluation_count", "nps", "scale_mean", "choice_share")
SMALL_N = 30
NPS_COLORS = {"promoters": "#3fb950", "passives": "#d29922", "detractors": "#f85149"}

# Recorte -> (expressão SQL sobre a tabela de contagens/avaliações, rótulo).
DIMS = {"unit": ("unit_id", "unidade"), "hour": ("hour", "hora local de início"),
        "channel": ("channel", "canal"), "completion": ("completed", "completude")}
CHANNEL = {"device": "totem", "web": "web"}


def _norm_by(by):
    f = A._fold(by or "")
    if not f:
        return None
    w = f[0]
    if w in ("unit", "unidade", "unidades", "loja", "lojas"):
        return "unit"
    if w in ("hour", "hora", "horas", "horario"):
        return "hour"
    if w in ("channel", "canal", "canais"):
        return "channel"
    if w in ("completion", "completude", "completas"):
        return "completion"
    if w in ("survey", "pesquisa", "pesquisas"):
        return "survey"
    return "property"


def _scope(args, metric):
    start, end = A.resolve_dates(args)
    p = {"a": start, "b": end}
    out = {"period": {"start": start, "end": end}, "coverage": A.coverage(start, end)}
    if metric != "evaluation_count" or args.get("survey"):  # survey_only: pesquisa sem pergunta (profile)
        p["s"], out["survey"] = A.resolve_survey(args)
    if metric in ("nps", "scale_mean", "choice_share"):
        qid, num, text = A.resolve_question(metric, p["s"], args)
        p["q"] = qid
        out["question"] = f"{num}. {text[:80]}"
    return p, out


def _dim_sql(by, args, p, table_alias="c"):
    """(expressão do grupo, JOIN extra, nome do recorte para o título)."""
    if by in DIMS:
        col, label = DIMS[by]
        return f"{table_alias}.{col}", "", label
    if by == "property":
        _, prop = A.resolve_group_by(args.get("by"))
        p["prop"] = int(prop["property_id"])
        return ("pr.value", f" INNER JOIN raw.unit_properties AS pr ON pr.unit_id = {table_alias}.unit_id "
                f"AND pr.name_id = {{prop:UInt32}}", prop["name"])
    raise A.ToolError("recorte não suportado para esta métrica")


def _label(by, key, units):
    if by == "unit":
        return units.get(int(key), f"unidade {key}")
    if by == "hour":
        return f"{int(key)}h"
    if by == "channel":
        return CHANNEL.get(key, key)
    if by == "completion":
        return "completas" if int(key) else "incompletas"
    return key


def _units():
    return {int(r["unit_id"]): r["name"] for r in A.ch("SELECT unit_id, name FROM raw.units")}


# ------------------------------------------------------------------ séries por métrica

def volume_by(by, args, p):
    where = "e.day BETWEEN {a:Date} AND {b:Date}" + (" AND e.survey_id = {s:UInt32}" if "s" in p else "")
    if by == "survey":
        rows = A.ch(f"SELECT s.name AS k, count() AS n FROM raw.evaluations AS e LEFT JOIN raw.surveys AS s "
                    f"ON s.survey_id = e.survey_id WHERE {where} GROUP BY k ORDER BY n DESC", p)
        return [(r["k"], int(r["n"])) for r in rows], "pesquisa"
    col = {"unit": "e.unit_id", "hour": "toHour(e.started_at)", "channel": "e.channel",
           "completion": "e.completed"}.get(by)
    join, label = "", DIMS.get(by, (None, None))[1]
    if by == "property":
        col, join, label = _dim_sql(by, args, p, "e")
    if not col:
        raise A.ToolError("recorte não suportado para volume")
    rows = A.ch(f"SELECT {col} AS k, count() AS n FROM raw.evaluations AS e{join} WHERE {where} GROUP BY k "
                f"ORDER BY {'k' if by == 'hour' else 'n DESC'}", p)
    units = _units() if by == "unit" else {}
    return [(_label(by, r["k"], units), int(r["n"])) for r in rows], label


def nps_by(by, args, p):
    expr, join, label = _dim_sql(by, args, p)
    rows = A.ch(f"SELECT {expr} AS k, sumIf(c.answers, c.score >= 9) AS pr, sumIf(c.answers, c.score BETWEEN 7 AND 8) "
                f"AS pa, sumIf(c.answers, c.score BETWEEN 0 AND 6) AS de FROM semantic.answer_counts_daily AS c{join} "
                f"WHERE c.survey_id = {{s:UInt32}} AND c.question_id = {{q:UInt32}} AND c.kind = 'nps' "
                f"AND c.day BETWEEN {{a:Date}} AND {{b:Date}} GROUP BY k", p)
    units = _units() if by == "unit" else {}
    out = []
    for r in rows:
        pr, pa, de = int(r["pr"]), int(r["pa"]), int(r["de"])
        n = pr + pa + de
        if n:
            out.append({"label": _label(by, r["k"], units), "key": r["k"], "n": n, "promoters": pr,
                        "passives": pa, "detractors": de, "nps": A._round_nps(100.0 * (pr / n - de / n))})
    if by == "hour":
        out.sort(key=lambda x: int(x["key"]))
    return out, label


def scale_by(by, args, p):
    expr, join, label = _dim_sql(by, args, p)
    rows = A.ch(f"SELECT {expr} AS k, sumIf(c.answers, ch.value IS NOT NULL) AS n, "
                f"sumIf(c.answers * ch.value, ch.value IS NOT NULL) AS s FROM semantic.answer_counts_daily AS c "
                f"INNER JOIN raw.choices AS ch ON ch.survey_id = c.survey_id AND ch.question_id = c.question_id "
                f"AND ch.choice_id = c.choice_id{join} WHERE c.survey_id = {{s:UInt32}} AND c.question_id = "
                f"{{q:UInt32}} AND c.kind = 'choice' AND c.day BETWEEN {{a:Date}} AND {{b:Date}} GROUP BY k", p)
    units = _units() if by == "unit" else {}
    out = [{"label": _label(by, r["k"], units), "key": r["k"], "n": int(r["n"]),
            "mean": round(float(r["s"]) / int(r["n"]), 2)} for r in rows if int(r["n"])]
    if by == "hour":
        out.sort(key=lambda x: int(x["key"]))
    return out, label


# ------------------------------------------------------------------ montagem

def _top(items, top, key):
    return sorted(items, key=key, reverse=True)[:top]


def _small(items):
    return [i["label"] for i in items if i.get("n", SMALL_N) < SMALL_N]


def build(args):
    kind = str(args.get("kind") or "bar").lower()
    uq = str(args.get("_user_q") or "")
    # Correções de tipo pelo pedido do usuário (o modelo pequeno escolhe o tipo mais genérico).
    if A._fold(args.get("by") or "")[:1] in (["question"], ["pergunta"], ["perguntas"]) or \
            re.search(r"cada pergunta|todas as perguntas|perguntas de escala", uq, re.I):
        kind, args = "profile", {k: v for k, v in args.items() if k not in ("by", "question", "metric")}
    elif kind in ("line", "bar", "area") and re.search(r"\bnps\b", uq, re.I) and \
            re.search(r"volume|quantidade|respostas e|avalia[cç][oõ]es e", uq, re.I) and \
            re.search(r"hora", uq, re.I):
        kind, args = "combo", {k: v for k, v in args.items() if k not in ("by", "metric")}
    if kind not in KINDS:
        raise A.ToolError(f"kind aceita: {', '.join(KINDS)}")
    metric = str(args.get("metric") or {"stacked": "nps", "histogram": "nps", "scatter": "nps", "combo": "nps",
                                        "donut": "choice_share" if args.get("question") else "evaluation_count",
                                        "profile": "scale_mean"}.get(kind, "evaluation_count"))
    if metric not in METRICS:
        raise A.ToolError(f"metric aceita: {', '.join(METRICS)}")
    default_by = {"line": "hour", "area": "hour", "combo": "hour", "heatmap": "hour", "scatter": "unit",
                  "hbar": "unit", "donut": "channel"}.get(kind, "unit")
    by = _norm_by(args.get("by")) or default_by
    top = int(args["top"]) if str(args.get("top") or "").isdigit() else (10 if kind == "heatmap" else 15)
    top = max(1, min(top, 40))
    min_n = int(args["min_n"]) if str(args.get("min_n") or "").isdigit() else SMALL_N
    scope_metric = {"combo": "nps", "scatter": "nps", "profile": "survey_only"}.get(kind, metric)
    p, out = _scope(args, scope_metric)
    notes = []

    if kind == "heatmap":
        return {**out, **_heatmap(metric, args, p, top, min_n)}

    if kind == "profile":
        return {**out, **_profile(p)}

    if kind == "histogram":
        rows = A.ch("SELECT c.score AS sc, sum(c.answers) AS n FROM semantic.answer_counts_daily AS c WHERE "
                    "c.survey_id = {s:UInt32} AND c.question_id = {q:UInt32} AND c.kind = 'nps' AND c.score BETWEEN 0 "
                    "AND 10 AND c.day BETWEEN {a:Date} AND {b:Date} GROUP BY sc ORDER BY sc", p)
        cnt = {int(r["sc"]): int(r["n"]) for r in rows}
        vals = [cnt.get(i, 0) for i in range(11)]
        colors = [NPS_COLORS["detractors"]] * 7 + [NPS_COLORS["passives"]] * 2 + [NPS_COLORS["promoters"]] * 2
        spec = {"type": "histogram", "title": "Notas de 0 a 10 da pergunta NPS", "labels": [str(i) for i in range(11)],
                "series": [{"name": "respostas", "values": vals}], "colors": colors, "x_label": "nota",
                "y_label": "respostas", "legend": {"detratores (0-6)": NPS_COLORS["detractors"],
                                                   "neutros (7-8)": NPS_COLORS["passives"],
                                                   "promotores (9-10)": NPS_COLORS["promoters"]}}
        return {**out, "rows": [{"label": str(i), "value": v} for i, v in enumerate(vals)], "chart": spec,
                "n": sum(vals)}

    if kind == "scatter":
        items, _ = nps_by("unit", args, p)
        items = [i for i in items if i["n"] >= min_n]
        if not items:
            raise A.ToolError(f"nenhuma unidade com n ≥ {min_n}")
        spec = {"type": "scatter", "title": "Unidades: respostas × NPS", "x_label": "respostas na pergunta NPS",
                "y_label": "NPS", "points": [{"label": i["label"], "x": i["n"], "y": i["nps"]} for i in items],
                "notes": [f"só unidades com n ≥ {min_n}"]}
        return {**out, "rows": [{"label": i["label"], "n": i["n"], "nps": i["nps"]} for i in items], "chart": spec}

    if kind == "combo":
        vol, _ = volume_by("hour", args, dict(p))
        nps, _ = nps_by("hour", args, p)
        by_h = {i["label"]: i for i in nps}
        labels = [l for l, _ in vol]
        spec = {"type": "combo", "title": "Volume de avaliações e NPS por hora", "labels": labels,
                "series": [{"name": "avaliações", "values": [v for _, v in vol], "axis": "left", "as": "bar"},
                           {"name": "NPS", "values": [by_h[l]["nps"] if l in by_h else None for l in labels],
                            "axis": "right", "as": "line"}],
                "x_label": "hora local de início", "notes": [f"horas com NPS de n < {SMALL_N}: " +
                                                             ", ".join(_small(nps))] if _small(nps) else []}
        return {**out, "rows": [{"label": l, "evaluations": v, "nps": by_h.get(l, {}).get("nps")} for l, v in vol],
                "chart": spec}

    if kind == "stacked":
        if metric != "nps":
            raise A.ToolError("stacked disponível para nps (promotores, neutros, detratores)")
        items, label = nps_by(by, args, p)
        if by in ("unit",):
            items = [i for i in items if i["n"] >= min_n]
        items = items if by == "hour" else _top(items, top, lambda i: i["n"])
        pct = lambda i, k: round(100.0 * i[k] / i["n"], 1)  # noqa: E731
        spec = {"type": "stacked", "title": f"Composição do NPS por {label}", "labels": [i["label"] for i in items],
                "series": [{"name": nm, "values": [pct(i, k) for i in items], "color": NPS_COLORS[k]}
                           for k, nm in (("detractors", "detratores"), ("passives", "neutros"),
                                         ("promoters", "promotores"))],
                "unit": "%", "x_label": label, "y_label": "% das respostas", "n": [i["n"] for i in items]}
        small = _small(items)
        if small:
            spec["notes"] = [f"amostra pequena (n < {SMALL_N}): {', '.join(small)}"]
        return {**out, "rows": [{k: i[k] for k in ("label", "n", "nps", "promoters", "passives", "detractors")}
                                for i in items], "chart": spec}

    if kind == "donut":
        if metric == "choice_share":
            r = A.t_choice_share({**args})
            labels, vals = [x["text"] for x in r["rows"]], [float(x["share_pct"]) for x in r["rows"]]
            spec = {"type": "donut", "title": "Distribuição das respostas", "labels": labels, "values": vals,
                    "unit": "%", "center": f"n {r['rows'][0]['n']}" if r["rows"] else ""}
            return {**out, "rows": [{"label": l, "value": v} for l, v in zip(labels, vals)], "chart": spec}
        items, label = volume_by(by, args, p)
        total = sum(v for _, v in items) or 1
        spec = {"type": "donut", "title": f"Avaliações por {label}", "labels": [l for l, _ in items][:top],
                "values": [round(100.0 * v / total, 1) for _, v in items][:top], "unit": "%"}
        return {**out, "rows": [{"label": l, "evaluations": v} for l, v in items[:top]], "chart": spec}

    # bar, hbar, line, area
    if kind in ("line", "area") and by != "hour":
        raise A.ToolError("linha e área são ao longo das horas: use by=hour")
    if metric == "evaluation_count":
        items, label = volume_by(by, args, p)
        series = [{"name": "avaliações", "values": [v for _, v in items]}]
        labels, ns = [l for l, _ in items], None
        name = "avaliações"
    elif metric == "nps":
        items, label = nps_by(by, args, p)
        if by in ("unit",):
            hidden = len([i for i in items if i["n"] < min_n])
            items = [i for i in items if i["n"] >= min_n]
            if hidden:
                notes.append(f"{hidden} unidades com n < {min_n} ficaram de fora")
        if by != "hour":
            items = sorted(items, key=lambda i: -i["nps"])
        labels, ns, name = [i["label"] for i in items], [i["n"] for i in items], "NPS"
        series = [{"name": "NPS", "values": [i["nps"] for i in items]}]
        small = _small(items)
        if small:
            notes.append(f"amostra pequena (n < {SMALL_N}): {', '.join(small[:8])}")
    elif metric == "scale_mean":
        items, label = scale_by(by, args, p)
        if by != "hour":
            items = sorted(items, key=lambda i: -i["mean"])
        labels, ns, name = [i["label"] for i in items], [i["n"] for i in items], "média"
        series = [{"name": "média", "values": [i["mean"] for i in items]}]
    else:
        r = A.t_choice_share({**args})
        labels = [x["text"] for x in r["rows"]]
        series = [{"name": "% das respostas", "values": [float(x["share_pct"]) for x in r["rows"]]}]
        ns, name, label = None, "% das respostas", "alternativa"
    if by != "hour" and len(labels) > top:
        notes.append(f"mostrando {top} de {len(labels)}")
        labels, series[0]["values"] = labels[:top], series[0]["values"][:top]
        ns = ns[:top] if ns else ns
    if not labels:
        return {**out, "rows": [], "note": "sem dados no período"}
    if kind in ("line", "area") and len(labels) < 2:
        raise A.ToolError("linha precisa de pelo menos 2 pontos; use kind=bar")
    spec = {"type": kind, "title": f"{name[0].upper() + name[1:]} por {label}", "labels": labels, "series": series,
            "x_label": label, "y_label": name, "unit": "%" if metric == "choice_share" else ""}
    if ns:
        spec["n"] = ns
    if notes:
        spec["notes"] = notes
    rows = [{"label": l, "value": v, **({"n": n} if ns else {})}
            for l, v, n in zip(labels, series[0]["values"], ns or [None] * len(labels))]
    return {**out, "rows": rows, "chart": spec}


def _heatmap(metric, args, p, top, min_n):
    if metric not in ("evaluation_count", "nps"):
        raise A.ToolError("heatmap disponível para evaluation_count e nps (unidades × hora)")
    where = "e.day BETWEEN {a:Date} AND {b:Date}" + (" AND e.survey_id = {s:UInt32}" if "s" in p else "")
    p["top"] = top
    tops = [int(r["unit_id"]) for r in A.ch(f"SELECT unit_id FROM raw.evaluations AS e WHERE {where} GROUP BY unit_id "
                                            f"ORDER BY count() DESC LIMIT {{top:UInt8}}", p)]
    if not tops:
        return {"rows": [], "note": "sem avaliações no período"}
    units = _units()
    if metric == "evaluation_count":
        rows = A.ch(f"SELECT unit_id AS u, toHour(started_at) AS h, count() AS v FROM raw.evaluations AS e WHERE "
                    f"{where} AND unit_id IN ({','.join(map(str, tops))}) GROUP BY u, h", p)
        cells = {(int(r["u"]), int(r["h"])): int(r["v"]) for r in rows}
        ncells = cells
        title = "Mapa de calor de avaliações por hora, nas unidades com mais respostas"
    else:
        rows = A.ch(f"SELECT unit_id AS u, hour AS h, sumIf(answers, score >= 9) AS pr, sumIf(answers, score BETWEEN 0 "
                    f"AND 6) AS de, sumIf(answers, score BETWEEN 0 AND 10) AS n FROM semantic.answer_counts_daily WHERE "
                    f"survey_id = {{s:UInt32}} AND question_id = {{q:UInt32}} AND kind = 'nps' AND day BETWEEN {{a:Date}} "
                    f"AND {{b:Date}} AND unit_id IN ({','.join(map(str, tops))}) GROUP BY u, h", p)
        ncells = {(int(r["u"]), int(r["h"])): int(r["n"]) for r in rows}
        cells = {k: A._round_nps(100.0 * (int(r["pr"]) - int(r["de"])) / int(r["n"]))
                 for k, r in zip(ncells, rows) if int(r["n"])}
        title = "Mapa de calor de NPS por hora, nas unidades com mais respostas"
    hours = list(range(min(h for _, h in ncells), max(h for _, h in ncells) + 1))
    matrix = [[cells.get((u, h)) if metric == "evaluation_count" or ncells.get((u, h), 0) >= max(5, min_n // 6)
               else None for h in hours] for u in tops]
    matrix = [[0 if v is None and metric == "evaluation_count" else v for v in row] for row in matrix]
    flat = [v for row in matrix for v in row if v is not None]
    spec = {"type": "heatmap", "title": title, "x": [f"{h}h" for h in hours], "y": [units.get(u, str(u)) for u in tops],
            "matrix": matrix, "min": min(flat), "max": max(flat), "x_label": "hora local de início", "y_label": "unidade",
            "scale": "volume" if metric == "evaluation_count" else "diverging"}
    if metric == "nps":
        spec["notes"] = ["células vazias: poucas respostas naquela hora"]
    totals = [sum(ncells.get((u, h), 0) for h in hours) for u in tops]
    return {"rows": [{"label": spec["y"][i], "n": totals[i]} for i in range(len(tops))], "chart": spec,
            "summary": {"units": len(tops), "hours": f"{hours[0]}h a {hours[-1]}h"}}


def _profile(p):
    rows = A.ch("SELECT q.number AS num, q.text AS text, sumIf(c.answers, ch.value IS NOT NULL) AS n, "
                "sumIf(c.answers * ch.value, ch.value IS NOT NULL) AS s, min(ch.value) AS lo, max(ch.value) AS hi "
                "FROM semantic.answer_counts_daily AS c INNER JOIN raw.choices AS ch ON ch.survey_id = c.survey_id "
                "AND ch.question_id = c.question_id AND ch.choice_id = c.choice_id INNER JOIN raw.questions AS q ON "
                "q.survey_id = c.survey_id AND q.question_id = c.question_id WHERE c.survey_id = {s:UInt32} AND "
                "q.answer_type = 'Scale' AND c.kind = 'choice' AND c.day BETWEEN {a:Date} AND {b:Date} "
                "GROUP BY num, text ORDER BY num", p)
    items = [{"label": f"{r['num']}. {re.sub('<[^>]+>', ' ', r['text'])[:38]}", "n": int(r["n"]),
              "mean": round(float(r["s"]) / int(r["n"]), 2), "lo": r["lo"], "hi": r["hi"]} for r in rows if int(r["n"])]
    if not items:
        raise A.ToolError("a pesquisa não tem perguntas de escala com respostas no período")
    spec = {"type": "hbar", "title": "Média de cada pergunta de escala", "labels": [i["label"] for i in items],
            "series": [{"name": "média", "values": [i["mean"] for i in items]}], "n": [i["n"] for i in items],
            "x_label": "pergunta", "y_label": "média", "domain": [min(i["lo"] for i in items), max(i["hi"] for i in items)],
            "notes": ["médias sem 'Não se aplica'; não compare escalas de amplitude diferente (INV-05)"]}
    return {"rows": items, "chart": spec}


def caption(c):
    """Legenda sem números, para quem pediu só o gráfico."""
    if c["type"] == "heatmap" and c.get("scale") == "diverging":
        cells = [(v, c["y"][i], c["x"][j]) for i, row in enumerate(c["matrix"]) for j, v in enumerate(row) if v is not None]
        hi, lo = max(cells), min(cells)
        return (f"{c['title']}. NPS mais alto em {hi[1]} às {hi[2]}; mais baixo em {lo[1]} às {lo[2]}. "
                f"Células vazias têm poucas respostas.")
    if c["type"] == "heatmap":
        cols = list(zip(*[[v or 0 for v in row] for row in c["matrix"]]))
        tot = [sum(col) for col in cols]
        strong = [c["x"][j] for j, v in enumerate(tot) if v >= 0.8 * max(tot)]
        faixa = strong[0] if len(strong) == 1 else f"entre {strong[0]} e {strong[-1]}"
        return f"{c['title']}. Os horários mais fortes ficam {faixa}; {c['y'][0]} é a unidade mais movimentada."
    if c["type"] == "scatter":
        best = max(c["points"], key=lambda q: q["y"])
        big = max(c["points"], key=lambda q: q["x"])
        return f"{c['title']}. Maior NPS: {best['label']}; mais respostas: {big['label']}."
    if c["type"] == "donut":
        return f"{c['title']}. Maior fatia: {c['labels'][c['values'].index(max(c['values']))]}."
    if c["type"] == "stacked":
        det = c["series"][0]["values"]
        return f"{c['title']}. Mais detratores: {c['labels'][det.index(max(det))]}."
    vals = [v for v in c["series"][0]["values"] if v is not None]
    hi = c["labels"][c["series"][0]["values"].index(max(vals))]
    lo = c["labels"][c["series"][0]["values"].index(min(vals))]
    return f"{c['title'][0].upper() + c['title'][1:]}. Maior: {hi}; menor: {lo}."
