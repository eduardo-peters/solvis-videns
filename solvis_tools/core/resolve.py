"""Resolução de nomes em ids (pesquisa, pergunta, propriedade), tipos de pergunta e cobertura.

Determinístico: casamento exato > todas as palavras > alguma palavra; ambiguidade vira erro com
as opções, para o modelo perguntar ao usuário.
"""
import datetime as dt
import re
import unicodedata

from .db import ch
from .errors import ToolError
from .periods import resolve_dates

METRIC_TYPES = {"nps": ("NPS",), "scale_mean": ("Scale",), "choice_share": ("Scale", "Multiple Choice")}


def _fold(t):
    t = unicodedata.normalize("NFKD", str(t)).encode("ascii", "ignore").decode().lower()
    return re.sub(r"<[^>]+>|[^a-z0-9 ]", " ", t).split()


def _pick(candidates, text, label, key, name_key):
    """Exato > todas as palavras > alguma palavra. Empate vira erro com as opções."""
    words = _fold(text)
    if not words:
        raise ToolError(f"informe {label}")
    scored = []
    for c in candidates:
        cw = _fold(c[name_key])
        if cw == words:
            scored.append((3, c))
        elif all(w in cw for w in words):
            scored.append((2, c))
        elif any(w in cw for w in words if len(w) > 3):
            scored.append((1, c))
    if not scored:
        raise ToolError(f"{label} '{text}' não encontrado(a)")
    best = max(sc for sc, _ in scored)
    top = [c for sc, c in scored if sc == best]
    if len(top) > 1 and best < 3:
        opts = "; ".join(c[name_key][:50] for c in top[:8])
        raise ToolError(f"{label} '{text}' é ambíguo(a). Pergunte ao usuário qual destas: {opts}")
    return top[0]


PLACEHOLDER = re.compile(r"^\W*$|^(pesquisa|survey|nome|nome da pesquisa|x|s)$", re.I)


def resolve_survey(args):
    text = str(args.get("survey") or args.get("survey_name") or args.get("search") or "").strip()
    if PLACEHOLDER.match(text):
        # Sem pesquisa (ou marcador copiado do exemplo, como "..."): se só uma pesquisa tem avaliações
        # carregadas, usa e declara (SKILL.md, passo 3); senão pede ao usuário.
        loaded = ch("SELECT s.survey_id AS survey_id, s.name AS name FROM raw.evaluations AS e INNER JOIN "
                    "raw.surveys AS s ON s.survey_id = e.survey_id GROUP BY survey_id, name")
        if len(loaded) == 1:
            args["_survey_note"] = f"pesquisa não citada; usada a única com dados: {loaded[0]['name']}"
            return int(loaded[0]["survey_id"]), loaded[0]["name"]
        names = "; ".join(r["name"] for r in loaded[:8]) or "nenhuma"
        raise ToolError("informe a pesquisa. Com dados: " + names)
    rows = ch("SELECT survey_id, name, archived FROM raw.surveys ORDER BY archived, last_evaluation_date DESC")
    active = [r for r in rows if not int(r["archived"])]
    try:
        hit = _pick(active, text, "pesquisa", "survey_id", "name")
    except ToolError:
        hit = _pick(rows, text, "pesquisa", "survey_id", "name")
    return int(hit["survey_id"]), hit["name"]


def resolve_question(metric, survey, args):
    rows = ch("SELECT question_id, number, answer_type, text FROM raw.questions WHERE survey_id = {s:UInt32} "
              "ORDER BY number", {"s": survey})
    typed = [r for r in rows if r["answer_type"] in METRIC_TYPES[metric]]
    valid = "; ".join(f"{r['number']}: {re.sub('<[^>]+>', ' ', r['text'])[:45]}" for r in typed[:10])
    text = str(args.get("question") or "").strip()
    m = re.fullmatch(r"(pergunta\s*)?(\d{1,3})", text, re.I) or re.match(r"()(\d{1,3})\.\s", text)
    if m:
        hit = [r for r in rows if int(r["number"]) == int(m.group(2))]
        if not hit:
            raise ToolError(f"não há pergunta {m.group(2)}. Perguntas válidas para {metric}: {valid}")
        q = hit[0]
    elif not text and metric != "nps" and args.get("_user_q"):
        # o modelo esqueceu a pergunta: tenta pelas palavras do pedido, só entre as do tipo certo
        words = [w for w in _fold(args["_user_q"]) if len(w) > 4]
        hits = [r for r in typed if any(w in _fold(r["text"]) for w in words)]
        if len(hits) != 1:
            raise ToolError(f"informe a pergunta. Perguntas válidas para {metric}: {valid or 'nenhuma'}")
        q = hits[0]
    elif not text and metric == "nps" and args.get("_user_q") and not re.search(r"recomend", args["_user_q"], re.I) \
            and re.search(r"\bpergunta\b", args["_user_q"], re.I):
        # "NPS da pergunta de Atendimento": o usuário citou outra pergunta pelo nome
        words = [w for w in _fold(args["_user_q"]) if len(w) > 4 and w not in ("pesquisa", "pergunta", "ontem")]
        others = [r for r in rows if r not in typed and any(w in _fold(r["text"]) for w in words)]
        if others and not any(any(w in _fold(r["text"]) for w in words) for r in typed):
            q = others[0]
        elif len(typed) == 1:
            q = typed[0]
        else:
            raise ToolError(f"informe a pergunta. Perguntas válidas para {metric}: {valid or 'nenhuma'}")
    elif not text or (metric == "nps" and _fold(text) in (["nps"], ["recomendacao"])):
        if len(typed) != 1:
            raise ToolError(f"informe a pergunta. Perguntas válidas para {metric}: {valid or 'nenhuma'}")
        q = typed[0]
    else:
        try:  # primeiro só entre as perguntas do tipo certo para a métrica
            q = _pick(typed, text, "pergunta", "question_id", "text")
        except ToolError as typed_err:
            if "ambíguo" in str(typed_err):
                raise ToolError(f"{typed_err}")
            words = _fold(text)
            others = [r for r in rows if r not in typed and any(w in _fold(r["text"]) for w in words if len(w) > 3)]
            if not others:
                raise ToolError(f"pergunta '{text}' não encontrada. Perguntas válidas para {metric}: {valid or 'nenhuma'}")
            q = others[0]
    if q["answer_type"] not in METRIC_TYPES[metric]:
        ok = [m_ for m_, ts in METRIC_TYPES.items() if q["answer_type"] in ts]
        raise ToolError(f"A pergunta {q['number']} ('{q['text'][:50]}') é do tipo {q['answer_type']}: "
                        f"{metric} não existe para ela. Diga isso ao usuário. "
                        f"Métricas que existem para ela: {', '.join(ok) or 'nenhuma numérica'}.")
    return int(q["question_id"]), int(q["number"]), re.sub("<[^>]+>", " ", q["text"])


def resolve_group_by(raw):
    gb = str(raw or "none").strip()
    if _fold(gb) in ([], ["none"], ["total"], ["geral"], ["all"], ["todos"], ["todas"]):
        return "none", None
    if _fold(gb)[0] in ("unit", "unidade", "unidades", "loja", "lojas"):
        return "unit", None
    rows = ch("SELECT name_id AS property_id, any(name) AS name FROM raw.unit_properties GROUP BY name_id")
    m = re.fullmatch(r"property:(\d+)", gb)
    if m:
        hit = [r for r in rows if int(r["property_id"]) == int(m.group(1))]
        if not hit:
            raise ToolError("propriedade inexistente; use o nome, ex.: group_by='Regional'")
        return "property", hit[0]
    return "property", _pick(rows, re.sub(r"^property:", "", gb), "propriedade", "property_id", "name")


def _round_nps(raw):
    return int(raw + 0.5) if raw >= 0 else -int(-raw + 0.5)


def coverage(start, end):
    """Dias do período com dados carregados no protótipo. A resposta precisa dizer quando é parcial."""
    days = ch("SELECT uniqExact(day) AS d, min(day) AS first, max(day) AS last FROM raw.evaluations "
              "WHERE day BETWEEN {a:Date} AND {b:Date}", {"a": start, "b": end})[0]
    expected = (dt.date.fromisoformat(end) - dt.date.fromisoformat(start)).days + 1
    c = {"days_in_period": expected, "days_with_data": int(days["d"])}
    if int(days["d"]) and int(days["d"]) < expected:
        c["warning"] = (f"Só há dados de {days['first']} a {days['last']} neste período. "
                        f"Diga ao usuário que o resultado cobre só esses dias.")
    if not int(days["d"]):
        near = ch("SELECT maxIf(day, day < {a:Date}) AS before, minIf(day, day > {b:Date}) AS after, "
                  "countIf(day < {a:Date}) AS nb, countIf(day > {b:Date}) AS na FROM raw.evaluations",
                  {"a": start, "b": end})[0]
        d = near["before"] if int(near["nb"]) else (near["after"] if int(near["na"]) else None)
        if d:
            c["nearest_day_with_data"] = d
            per = start if start == end else f"{start} a {end}"
            c["warning"] = (f"Não há avaliações carregadas em {per}. O dia com dados mais próximo é {d}; "
                            f"responda 'sim' para ver esse dia. Diga ao usuário que não há dados no período.")
    return c


def _question_scope(metric, args):
    survey, sname = resolve_survey(args)
    qid, number, qtext = resolve_question(metric, survey, args)
    start, end = resolve_dates(args)
    scope = {"survey": sname, "question": f"{number}. {qtext[:80]}", "period": {"start": start, "end": end},
             "coverage": coverage(start, end)}
    if args.get("_survey_note"):
        scope["survey_note"] = args["_survey_note"]
    return {"survey": survey, "question": qid, "start": start, "end": end}, scope


BASE = "survey={survey:UInt32}, question={question:UInt32}, start={start:Date}, end={end:Date}"
