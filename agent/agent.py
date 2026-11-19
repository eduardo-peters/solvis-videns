"""Agente local (protótipo): SLM no Ollama + camada semântica no ClickHouse.

O modelo não escreve SQL, não calcula e não manipula ids. Ele escolhe uma
ferramenta e passa nomes como o usuário disse ("Satisfação", "Atendimento",
"Regional", "yesterday"). O código resolve nomes, datas e tipos de forma
determinística, chama uma view semântica com parâmetros tipados como o usuário
isolado do cliente (row policy) e confere os números da resposta final.
Só Python 3.9, sem dependências.

Variáveis: OLLAMA_URL (http://127.0.0.1:11434), AGENT_MODEL (qwen3:1.7b),
AGENT_THINK (0), AGENT_TODAY (hoje), CLICKHOUSE_URL (http://127.0.0.1:8123),
CLICKHOUSE_USER (assai_agent), CLICKHOUSE_PASSWORD_FILE (~/.local/clickhouse/assai_agent.pw).
"""
import datetime as dt
import difflib
import json
import os
import re
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

OLLAMA = os.environ.get("OLLAMA_URL", "http://127.0.0.1:11434")
MODEL = os.environ.get("AGENT_MODEL", "qwen3:1.7b")
THINK = os.environ.get("AGENT_THINK", "0") == "1"
TODAY = os.environ.get("AGENT_TODAY", dt.date.today().isoformat())
CH_URL = os.environ.get("CLICKHOUSE_URL", "http://127.0.0.1:8123")
CH_USER = os.environ.get("CLICKHOUSE_USER", "assai_agent")
CH_PW_FILE = Path(os.environ.get("CLICKHOUSE_PASSWORD_FILE", Path.home() / ".local/clickhouse/assai_agent.pw"))
MAX_STEPS = 8
USE_CONTEXT = os.environ.get("AGENT_CONTEXT", "1") == "1"
# ollama: modelo base com tool calling nativo. mlx: mlx_lm.server (modelo base ou com adapter LoRA),
# chamadas e resultados em texto, mesma convenção do treino (agent/train/build_dataset.py).
BACKEND = os.environ.get("AGENT_BACKEND", "ollama")
MLX_URL = os.environ.get("MLX_URL", "http://127.0.0.1:8090")
METRIC_TOOLS = ("nps", "choice_share", "scale_mean", "evaluation_count")


class ToolError(Exception):
    pass


# ---------------------------------------------------------------- ClickHouse

def ch(sql, params=None):
    """SQL fixo com parâmetros tipados ({nome:Tipo}); devolve lista de dicts."""
    qs = {"default_format": "JSON"}
    for k, v in (params or {}).items():
        qs["param_" + k] = str(v)
    req = urllib.request.Request(CH_URL + "/?" + urllib.parse.urlencode(qs), data=sql.encode(), method="POST")
    req.add_header("X-ClickHouse-User", CH_USER)
    req.add_header("X-ClickHouse-Key", CH_PW_FILE.read_text().strip())
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.loads(r.read())["data"]
    except urllib.error.HTTPError as e:
        raise ToolError("clickhouse: " + e.read().decode()[:300])


# ---------------------------------------------------------------- períodos

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


# ---------------------------------------------------------------- resolução de nomes

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


def resolve_survey(args):
    text = args.get("survey") or args.get("survey_name") or args.get("search") or ""
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
    elif not text and metric == "nps" and args.get("_user_q") and not re.search(r"recomend", args["_user_q"], re.I):
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


# ---------------------------------------------------------------- ferramentas

def coverage(start, end):
    """Dias do período com dados carregados no protótipo. A resposta precisa dizer quando é parcial."""
    days = ch("SELECT uniqExact(day) AS d, min(day) AS first, max(day) AS last FROM raw.evaluations "
              "WHERE day BETWEEN {a:Date} AND {b:Date}", {"a": start, "b": end})[0]
    expected = (dt.date.fromisoformat(end) - dt.date.fromisoformat(start)).days + 1
    c = {"days_in_period": expected, "days_with_data": int(days["d"])}
    if int(days["d"]) and int(days["d"]) < expected:
        c["warning"] = (f"Só há dados de {days['first']} a {days['last']} neste período. "
                        f"Diga ao usuário que o resultado cobre só esses dias.")
    return c


def t_list_surveys(args):
    return ch("SELECT name, archived, last_evaluation_date FROM raw.surveys "
              "WHERE positionCaseInsensitiveUTF8(name, {s:String}) > 0 "
              "ORDER BY archived, last_evaluation_date DESC LIMIT 20", {"s": str(args.get("search") or "")[:80]})


def t_list_questions(args):
    survey, name = resolve_survey(args)
    return {"survey": name, "questions": ch(
        "SELECT number, answer_type, text FROM raw.questions WHERE survey_id = {s:UInt32} ORDER BY number",
        {"s": survey})}


def t_list_unit_properties(args):
    return ch("SELECT any(name) AS name, uniqExact(value_id) AS values FROM raw.unit_properties "
              "GROUP BY name_id ORDER BY name")


def t_data_coverage(args):
    return ch("SELECT s.name AS survey, min(e.day) AS first_day, max(e.day) AS last_day, count() AS evaluations "
              "FROM raw.evaluations e LEFT JOIN raw.surveys s ON s.survey_id = e.survey_id GROUP BY s.name")


def _question_scope(metric, args):
    survey, sname = resolve_survey(args)
    qid, number, qtext = resolve_question(metric, survey, args)
    start, end = resolve_dates(args)
    scope = {"survey": sname, "question": f"{number}. {qtext[:80]}", "period": {"start": start, "end": end},
             "coverage": coverage(start, end)}
    return {"survey": survey, "question": qid, "start": start, "end": end}, scope


BASE = "survey={survey:UInt32}, question={question:UInt32}, start={start:Date}, end={end:Date}"


def t_nps(args):
    p, scope = _question_scope("nps", args)
    kind, prop = resolve_group_by(args.get("group_by"))
    scope["group_by"] = prop["name"] if prop else kind
    total = ch(f"SELECT sum(promoters) AS promoters, sum(passives) AS passives, sum(detractors) AS detractors, "
               f"sum(n) AS n FROM semantic.nps_by_unit({BASE})", p)[0]
    n = int(total["n"])
    if n == 0:
        return {**scope, "rows": [], "note": "sem avaliações no período"}
    total["nps"] = _round_nps(100.0 * (int(total["promoters"]) / n - int(total["detractors"]) / n))
    out = {**scope, "total": total,
           "total_note": "total = NPS geral do conjunto, calculado pelas contagens (não é média das linhas)"}
    if kind == "unit":  # todas as unidades; o corte para o modelo vem depois de achar pior e melhor
        out["rows"] = ch(f"SELECT u.name AS unit, v.nps AS nps, v.n AS n FROM semantic.nps_by_unit({BASE}) v "
                         f"LEFT JOIN raw.units u ON u.unit_id = v.unit_id ORDER BY nps, n DESC", p)
    elif kind == "property":
        out["rows"] = ch(f"SELECT value, nps, n FROM semantic.nps_by_unit_property({BASE}, property={{property:UInt32}}) "
                         f"ORDER BY nps, n DESC", {**p, "property": int(prop["property_id"])})
    else:
        out["rows"] = [total]
    min_n = int(args.get("min_n") or 0) if str(args.get("min_n") or "0").isdigit() else 0
    if min_n and kind != "none":
        hidden = [r for r in out["rows"] if int(r["n"]) < min_n]
        out["rows"] = [r for r in out["rows"] if int(r["n"]) >= min_n]
        out["hidden_rows_below_min_n"] = len(hidden)
    for r in out["rows"]:
        if int(r["n"]) < 30:
            r["small_sample"] = True
    if len(out["rows"]) > 1:
        out["worst"], out["best"] = out["rows"][0], out["rows"][-1]
        reliable = [r for r in out["rows"] if int(r["n"]) >= 30]
        if reliable and (out["worst"].get("small_sample") or out["best"].get("small_sample")):
            out["worst_with_n_30"], out["best_with_n_30"] = reliable[0], reliable[-1]
    small = [r for r in out["rows"] if r.get("small_sample")]
    if small:
        out["small_sample_rows"] = len(small)
    if len(out["rows"]) > 30:  # pior e melhor já foram calculados sobre todas as linhas
        out["rows_total"] = len(out["rows"])
        out["rows"] = out["rows"][:15] + out["rows"][-15:]
        out["rows_note"] = f"mostrando as 15 piores e as 15 melhores de {out['rows_total']}"
    return out


def t_choice_share(args):
    p, scope = _question_scope("choice_share", args)
    rows = ch(f"SELECT letter, text, answers, share_pct, n FROM semantic.choice_share({BASE}) ORDER BY letter", p)
    return {**scope, "rows": rows} if rows else {**scope, "rows": [], "note": "sem avaliações no período"}


def t_scale_mean(args):
    p, scope = _question_scope("scale_mean", args)
    r = ch(f"SELECT n, mean_raw FROM semantic.scale_mean({BASE})", p)[0]
    if int(r["n"]) == 0:
        return {**scope, "rows": [], "note": "sem avaliações no período"}
    return {**scope, "rows": [{"mean": round(float(r["mean_raw"]), 2), "n": r["n"]}]}


def t_evaluation_count(args):
    """Volume. Sem survey: todas as pesquisas. group_by: none, survey, unit ou propriedade."""
    start, end = resolve_dates(args)
    p = {"a": start, "b": end}
    where = "e.day BETWEEN {a:Date} AND {b:Date}"
    sname = None
    if args.get("survey"):
        p["s"], sname = resolve_survey(args)
        where += " AND e.survey_id = {s:UInt32}"
    gb = str(args.get("group_by") or "none")
    out = {"survey_filter": sname or "nenhum (todas as pesquisas)", "period": {"start": start, "end": end},
           "coverage": coverage(start, end)}
    total = ch(f"SELECT count() AS evaluations FROM raw.evaluations AS e WHERE {where}", p)
    out["total"] = total[0]
    if _fold(gb) and _fold(gb)[0] in ("survey", "pesquisa", "pesquisas"):
        out["group_by"] = "pesquisa"
        out["rows"] = ch(f"SELECT s.name AS survey, count() AS evaluations FROM raw.evaluations AS e "
                         f"LEFT JOIN raw.surveys AS s ON s.survey_id = e.survey_id WHERE {where} "
                         f"GROUP BY s.name ORDER BY evaluations DESC LIMIT 20", p)
        return out
    kind, prop = resolve_group_by(gb)
    out["group_by"] = prop["name"] if prop else kind
    if kind == "unit":
        out["rows"] = ch(f"SELECT u.name AS unit, count() AS evaluations FROM raw.evaluations AS e "
                         f"LEFT JOIN raw.units AS u ON u.unit_id = e.unit_id WHERE {where} "
                         f"GROUP BY u.name ORDER BY evaluations DESC LIMIT 20", p)
        out["rows_note"] = "só as 20 com mais avaliações; a lista não mostra a de menos avaliações"
    elif kind == "property":
        p["prop"] = int(prop["property_id"])
        out["rows"] = ch(f"SELECT pr.value AS value, count() AS evaluations FROM raw.evaluations AS e "
                         f"INNER JOIN raw.unit_properties AS pr ON pr.unit_id = e.unit_id AND pr.name_id = {{prop:UInt32}} "
                         f"WHERE {where} GROUP BY pr.value ORDER BY evaluations DESC", p)
    else:
        out["rows"] = total
    if len(out["rows"]) > 1:
        out["most"] = dict(out["rows"][0])
        out["rows"] = out["rows"][:10]
        if kind == "unit":  # de qual pesquisa vieram as respostas da loja do topo
            out["most"]["surveys"] = ch(
                f"SELECT s.name AS survey, count() AS evaluations FROM raw.evaluations AS e "
                f"LEFT JOIN raw.surveys AS s ON s.survey_id = e.survey_id "
                f"LEFT JOIN raw.units AS u ON u.unit_id = e.unit_id WHERE {where} AND u.name = {{u:String}} "
                f"GROUP BY s.name ORDER BY evaluations DESC", {**p, "u": out["most"]["unit"]})
    return out


S = "string"
PERIOD = {"period": S, "start": S, "end": S}
TOOLS = {
    "nps": (t_nps, "NPS de uma pesquisa. survey = nome da pesquisa; question = texto ou número da pergunta "
                   "(opcional se a pesquisa tem uma só NPS); group_by = none, unit ou nome da propriedade "
                   "(Regional, Formato da loja, HUB...); min_n esconde linhas com menos respostas.",
            {"survey": S, "question": S, "group_by": S, "min_n": "integer", **PERIOD}, ["survey"]),
    "scale_mean": (t_scale_mean, "Média de uma pergunta de escala (ex.: estrelas). survey = nome; "
                                 "question = texto ou número da pergunta.",
                   {"survey": S, "question": S, **PERIOD}, ["survey", "question"]),
    "choice_share": (t_choice_share, "Distribuição (%) das alternativas de uma pergunta de escala ou escolha. "
                                     "survey = nome; question = texto ou número da pergunta.",
                     {"survey": S, "question": S, **PERIOD}, ["survey", "question"]),
    "evaluation_count": (t_evaluation_count, "Quantidade de avaliações (respostas). survey = nome (opcional: sem ele, "
                                             "todas as pesquisas); group_by = none, survey, unit ou propriedade. "
                                             "Use para 'qual loja/pesquisa teve mais respostas'.",
                         {"survey": S, "group_by": S, **PERIOD}, []),
    "list_surveys": (t_list_surveys, "Busca pesquisas pelo nome.", {"search": S}, []),
    "list_questions": (t_list_questions, "Lista as perguntas de uma pesquisa. survey = nome.", {"survey": S},
                       ["survey"]),
    "list_unit_properties": (t_list_unit_properties, "Lista propriedades de unidade (Regional, Formato...).", {}, []),
    "data_coverage": (t_data_coverage, "Dias com dados carregados por pesquisa.", {}, []),
}


def tool_schemas():
    return [{"type": "function", "function": {
        "name": name, "description": desc,
        "parameters": {"type": "object", "required": req, "properties": {k: {"type": v} for k, v in props.items()}}}}
        for name, (_, desc, props, req) in TOOLS.items()]


SYSTEM = f"""Você é o assistente de análise de pesquisas da Solvis. Responda em português do Brasil.
Hoje é {TODAY}. Períodos: period = yesterday, today, last_7_days, this_month, last_month ou month:AAAA-MM.

Regras:
1. Nunca calcule nem invente números. Todo número vem de uma ferramenta.
2. Chame direto a ferramenta da métrica, passando os nomes como o usuário disse. Exemplo:
   nps(survey="Satisfação", period="yesterday", group_by="Regional")
   scale_mean(survey="Satisfação", question="Atendimento", period="yesterday")
   "qual loja teve mais respostas?" -> evaluation_count(group_by="unit", period="last_7_days")
   "qual pesquisa teve mais respostas?" -> evaluation_count(group_by="survey", period="last_7_days")
   "pior loja em NPS" -> nps(survey=..., group_by="unit", min_n=30)   (ranking de nota nunca é volume)
   "distribuição"/"% de cada alternativa" -> choice_share; "média"/"nota média" -> scale_mean
   NPS de cada loja e NPS geral -> uma chamada nps(group_by="unit"); o NPS geral está em total.
   O resultado por loja traz em most.surveys a pesquisa de onde vieram as respostas da loja do topo.
3. NPS é só para a pergunta de recomendação. Média e distribuição são para escalas e alternativas.
4. Se a ferramenta devolver erro, leia a mensagem: corrija a chamada ou explique ao usuário.
5. Cite o número, o n e o período. Se o resultado tiver coverage.warning, repita o aviso. Com várias linhas, cite a pior e a melhor (com n).
   Se houver small_sample_rows, diga que algumas linhas têm amostra pequena. Em ranking, se a pior ou a melhor
   tiver small_sample, use worst_with_n_30 / best_with_n_30 e diga que as de amostra pequena foram deixadas de lado.
6. Nunca cite nome de loja, pesquisa ou pergunta que não veio de uma ferramenta.
   Sem dados no período: diga que não há dados. Benchmark, CSAT e taxa de resposta não existem: diga que não
   estão disponíveis, sem chamar ferramentas.
7. Se o usuário não disser o período, use period="last_7_days" e diga qual período usou.
8. Seja breve: no máximo três frases."""


def _tools_as_text():
    lines = []
    for name, (_, desc, props, req) in TOOLS.items():
        args = ", ".join(f"{k}{'' if k in req else '?'}" for k in props)
        lines.append(f"- {name}({args}): {desc}")
    return "\n".join(lines)


MLX_SYSTEM = SYSTEM + f"""

Ferramentas (para chamar, responda SÓ com a chamada, ex.: nps(survey="X", period="yesterday")):
{_tools_as_text()}
O resultado chega numa mensagem que começa com [resultado de <ferramenta>]. Depois dele, responda ao usuário."""


# ---------------------------------------------------------------- guardrails de saída

_MONTHS = "janeiro|fevereiro|março|abril|maio|junho|julho|agosto|setembro|outubro|novembro|dezembro"
_DATE = re.compile(r"\d{4}-\d{2}-\d{2}|\d{1,2}/\d{1,2}(/\d{2,4})?|\d{1,2}º? de (%s)( de \d{4})?|(%s) de \d{4}"
                   % (_MONTHS, _MONTHS), re.I)
_NUM = re.compile(r"-?\d[\d.,]*")


def _norm(tok):
    """'11.709' -> 11709; '82,9' -> 82.9; '4.78' -> 4.78."""
    tok = tok.strip(".,")
    if re.fullmatch(r"-?\d{1,3}(\.\d{3})+", tok):
        tok = tok.replace(".", "")
    try:
        return float(tok.replace(",", "."))
    except ValueError:
        return None


def verify_numbers(answer, tool_outputs, question=""):
    """Números da resposta que não aparecem em nenhum resultado de ferramenta nem na pergunta."""
    allowed = set()
    for out in list(tool_outputs) + [question]:
        for t in _NUM.findall(_DATE.sub(" ", out)):
            v = _norm(t)
            if v is not None:
                allowed.update({v, abs(v), round(v), round(v, 1), round(v, 2)})
    bad = []
    for t in _NUM.findall(_DATE.sub(" ", answer)):
        v = _norm(t)
        if v is not None and v not in allowed and round(v, 1) not in allowed and v not in (1, 2, 3):
            bad.append(t.strip(".,"))
    return bad


_FULL_DATE = re.compile(r"\b(\d{1,2})/(\d{1,2})/(\d{4})\b|\b(\d{4})-(\d{2})-(\d{2})\b")


def verify_dates(answer, tool_outputs):
    """Datas completas da resposta precisam aparecer nos resultados (pega período copiado de exemplo)."""
    seen = " ".join(tool_outputs)
    bad = []
    for m in _FULL_DATE.finditer(answer):
        iso = ("%s-%02d-%02d" % (m.group(3), int(m.group(2)), int(m.group(1)))) if m.group(3) else m.group(0)
        if iso not in seen:
            bad.append(m.group(0))
    return bad


def _tool_name(name):
    if name in TOOLS:
        return name
    near = difflib.get_close_matches(str(name), list(TOOLS), n=1, cutoff=0.75)
    return near[0] if near else None


def _text_tool_calls(content):
    """SLMs pequenos às vezes escrevem a chamada no texto: JSON ou nome(arg=valor, ...)."""
    content = re.sub(r"</?tool_call>", "", content or "").strip().strip("`")
    f = re.fullmatch(r"\s*([a-z_]+)\((.*)\)\s*", content, re.S)
    if f and _tool_name(f.group(1)):
        args = {k: v.strip("\"'") for k, v in
                re.findall(r"(\w+)\s*=\s*(\"[^\"]*\"|'[^']*'|[^,\s)]+)", f.group(2))}
        return [{"function": {"name": _tool_name(f.group(1)), "arguments": args}}]
    m = re.search(r"\{.*\}", content, re.S)
    if m:
        try:
            obj = json.loads(m.group(0))
        except ValueError:
            return []
        if isinstance(obj, dict) and _tool_name(obj.get("name")):
            return [{"function": {"name": _tool_name(obj["name"]), "arguments": obj.get("arguments") or {}}}]
    return []


# ---------------------------------------------------------------- laço do agente

def mlx_chat(messages):
    """mlx_lm.server (API compatível com OpenAI). Tool role vira texto, como no treino."""
    conv = []
    for m in messages:
        if m["role"] == "system":
            conv.append({"role": "system", "content": MLX_SYSTEM + m["content"][len(SYSTEM):]})
        elif m["role"] == "tool":
            conv.append({"role": "user", "content": f"[resultado de {m.get('tool_name', '?')}]\n{m['content']}"})
        elif m["role"] == "assistant" and m.get("tool_calls"):
            c = m["tool_calls"][0]["function"]
            conv.append({"role": "assistant", "content": c["name"] + "(" + ", ".join(
                f'{k}="{v}"' for k, v in (c.get("arguments") or {}).items()) + ")"})
        else:
            conv.append({"role": m["role"], "content": m.get("content", "")})
    body = json.dumps({"messages": conv, "temperature": 0, "max_tokens": 400}).encode()
    req = urllib.request.Request(MLX_URL + "/v1/chat/completions", data=body,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=180) as r:
        text = json.loads(r.read())["choices"][0]["message"]["content"] or ""
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.S)
    text = re.sub(r"<\|[a-z_]+\|>", "", text).strip()  # tokens especiais (<|im_end|>) que o servidor não remove
    return {"role": "assistant", "content": text}


def ollama_chat(messages):
    if BACKEND == "mlx":
        return mlx_chat(messages)
    body = json.dumps({"model": MODEL, "messages": messages, "tools": tool_schemas(), "stream": False,
                       "think": THINK, "options": {"temperature": 0, "num_ctx": 6144, "num_predict": 600}}).encode()
    req = urllib.request.Request(OLLAMA + "/api/chat", data=body, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=120) as r:
        return json.loads(r.read())["message"]


# Palavras do pedido -> ferramentas aceitáveis. Pega a resposta com número real da métrica errada
# (ex.: "pior loja em NPS" respondida com volume de respostas).
INTENT = [(re.compile(r"quantas? (avalia|respost|pessoas)|volume|mais (respostas|avalia)|menos (respostas|avalia)"
                      r"|recebeu mais|teve mais respostas", re.I), {"evaluation_count"}),
          (re.compile(r"\bnps\b|recomenda", re.I), {"nps"}),
          (re.compile(r"distribui|percentual|porcentagem|% d", re.I), {"choice_share"}),
          (re.compile(r"\bm[ée]dia\b|\bnota\b", re.I), {"scale_mean", "nps"})]


def intent_mismatch(question, trace):
    used = {t["tool"] for t in trace if t["ok"] and t["tool"] in METRIC_TOOLS and t["rows"]}
    if not used:
        return None
    for rx, ok in INTENT:
        if rx.search(question) and not (used & ok):
            label = {"evaluation_count": "volume de avaliações", "nps": "NPS", "choice_share": "distribuição",
                     "scale_mean": "média"}[sorted(ok)[0]]
            return (f"O usuário pediu {label}, mas você usou {', '.join(sorted(used))}. "
                    f"Chame {' ou '.join(sorted(ok))}.")
    return None


REFUSAL = re.compile(r"não (há|existe|está disponível|estão disponíveis|temos|tenho|possu|consigo|é possível)"
                     r"|indispon|sem dados|nenhum dado|não encontr|qual (pesquisa|pergunta|período)", re.I)


PERIOD_WORDS = [(r"\bontem\b", "yesterday"), (r"\bhoje\b", "today"), (r"[uú]ltimos 7 dias|semana passada", "last_7_days"),
                (r"m[eê]s passado", "last_month"), (r"este m[eê]s|neste m[eê]s", "this_month")]
_MONTH_N = {m: i + 1 for i, m in enumerate(_MONTHS.split("|"))}


def period_from_question(q):
    """Período dito pelo usuário, para quando o modelo esquece de passar."""
    m = re.search(r"(%s) de (\d{4})" % _MONTHS, q, re.I)
    if m:
        return "month:%s-%02d" % (m.group(2), _MONTH_N[m.group(1).lower()])
    for rx, preset in PERIOD_WORDS:
        if re.search(rx, q, re.I):
            return preset
    return None


# Pedidos que este protótipo ainda não atende: o aviso entra na resposta pelo código.
UNSUPPORTED = [
    (re.compile(r"taxa de (resposta|ades[aã]o|participa)|percentual (dos clientes|de clientes) que respond"
                r"|quantos por cento .*respond", re.I),
     "Taxa de resposta não existe na Solvis: o sistema não sabe quantas pessoas foram convidadas ou passaram pela "
     "loja. Posso mostrar a quantidade de avaliações."),
    (re.compile(r"\bcsat\b|top.?2|% de satisfeitos|percentual de satisfeitos", re.I),
     "O sistema não tem métrica CSAT. Diga qual pergunta de escala é o seu CSAT (ex.: Atendimento) e mostro a "
     "média ou a distribuição dela."),
    (re.compile(r"em rela[cç][aã]o a|compara|\bvs\.?\b|versus|subiu|caiu|evolu|melhorou|piorou", re.I),
     "Comparação entre períodos e evolução ainda não estão disponíveis neste protótipo."),
    (re.compile(r"coment|est[aã]o dizendo|falando|reclama", re.I),
     "Comentários e temas ainda não estão disponíveis neste protótipo."),
    (re.compile(r"motivos?|multipla|múltipla", re.I),
     "Perguntas de múltipla resposta (como motivos) ainda não estão disponíveis neste protótipo."),
]


def suggested_call(q, default_period):
    """Chamada sugerida a partir das palavras do pedido. Só orienta; o modelo ainda decide."""
    tool = "evaluation_count"
    for rx, ok in INTENT:
        if rx.search(q):
            tool = sorted(ok)[0] if len(ok) == 1 else "scale_mean"
            break
    if re.search(r"\bnps\b", q, re.I):
        tool = "nps"
    args = {}
    sv = ch("SELECT name FROM raw.surveys WHERE archived = 0")
    for r in sv:
        if r["name"].lower() in q.lower():
            args["survey"] = r["name"]
    if re.search(r"loja|unidade", q, re.I):
        args["group_by"] = "unit"
    if re.search(r"regional", q, re.I):
        args["group_by"] = "Regional"
    if re.search(r"pior|melhor|ranking", q, re.I) and tool == "nps":
        args["min_n"] = 30
    if default_period:
        args["period"] = default_period
    return f"{tool}({', '.join(f'{k}={v!r}' for k, v in args.items())})"


def unsupported_notes(q):
    return [msg for rx, msg in UNSUPPORTED if rx.search(q)]


def ask(history, source="cli"):
    """history: lista de {role, content}. Devolve a resposta e tudo o que aconteceu até ela.

    Toda saída passa por _finish(): checagens de metodologia e registro em ops.* (agent/audit.py).
    """
    import time
    t0 = time.time()
    question = history[-1]["content"] if history else ""
    st = {"events": [], "trace": [], "table": None, "outputs": [], "context": []}

    def ev(guardrail, action, detail):
        st["events"].append({"guardrail": guardrail, "action": action, "detail": str(detail)[:500]})

    def _finish(answer, outcome):
        out = {"answer": answer, "outcome": outcome, "trace": st["trace"], "table": st["table"],
               "context": st["context"], "guardrail_events": st["events"], "verified": True,
               "secs": round(time.time() - t0, 2)}
        try:
            import audit
            out["methodology"] = audit.methodology_checks(question, out, st["outputs"])
            out["interaction_id"] = audit.record(question, out, source=source, model=MODEL, context_on=USE_CONTEXT)
        except Exception as e:  # auditoria nunca derruba a resposta, mas a falha fica visível
            out["audit_error"] = f"{type(e).__name__}: {e}"
        return out

    system = SYSTEM
    if USE_CONTEXT and question:
        import context  # recuperação vetorial dos trechos da skill (agent/context.py)
        picked = context.retrieve(question, ch)
        system += context.render(picked)
        st["context"] = [f"{r['source']} · {r['heading']}" for r in picked]
    notes = unsupported_notes(question)
    if notes:
        system += "\n\nATENÇÃO, nesta pergunta: " + " ".join(notes) + " Diga isso na primeira frase."
    default_period = period_from_question(question)
    messages = [{"role": "system", "content": system}] + history
    trace, outputs, retried = st["trace"], st["outputs"], False
    for _ in range(MAX_STEPS):
        msg = ollama_chat(messages)
        messages.append(msg)
        calls = msg.get("tool_calls") or _text_tool_calls(msg.get("content", ""))
        if not calls:
            answer = msg.get("content", "").strip()
            bad_n = verify_numbers(answer, outputs, question)
            bad_d = verify_dates(answer, outputs)
            mismatch = intent_mismatch(question, trace)
            if mismatch and not REFUSAL.search(answer):
                ev("metric", "block" if retried else "retry", mismatch)
                if not retried:
                    retried = True
                    messages.append({"role": "user", "content": mismatch})
                    continue
                return _finish("Não consegui consultar a métrica pedida, então não vou responder com outra. "
                               "Tente reformular dizendo a pesquisa e a métrica.", "blocked")
            grounded = any(t["ok"] for t in trace)
            if not grounded and notes:  # pedido fora do que existe: a recusa com o aviso é a resposta certa
                ev("capability", "annotate", "; ".join(notes))
                answer = " ".join(n_ for n_ in notes if n_[:25].lower() not in answer.lower()) + " " + answer
                return _finish(answer.strip(), "refused")
            if not grounded and not REFUSAL.search(answer):
                ev("grounding", "block" if retried else "retry", answer[:200])
                if not retried:
                    retried = True
                    messages.append({"role": "user", "content": "Você respondeu sem consultar nenhuma ferramenta. "
                                     "Nomes e números só podem vir de ferramentas. Chame agora, por exemplo: "
                                     + suggested_call(question, default_period)})
                    continue
                return _finish("Não tenho uma ferramenta que responda isso com dados. Não vou responder sem "
                               "consultar os dados.", "blocked")
            bad = bad_n + bad_d
            if bad:
                ev("numbers" if bad_n else "dates", "block" if retried else "retry", ", ".join(bad))
                if not retried:
                    retried = True
                    messages.append({"role": "user", "content": f"Os valores {', '.join(bad)} não vieram de nenhuma "
                                     "ferramenta. Chame a ferramenta certa ou responda sem eles."})
                    continue
                return _finish("Não consegui obter esse valor das ferramentas, então não vou citá-lo. "
                               "Tente dizer a pesquisa e a pergunta pelo nome.", "blocked")
            for n_ in notes:  # aviso de capacidade não depende do modelo lembrar
                if n_[:25].lower() not in answer.lower():
                    ev("capability", "annotate", n_)
                    answer = n_ + " " + answer
            warns = sorted({w for o in outputs for w in re.findall(r'"warning": "([^"]+)"', o)})
            for w in warns:  # aviso de cobertura não depende do modelo lembrar
                ev("coverage", "annotate", w)
                answer += "\n⚠ " + w.split(" Diga ao usuário")[0]
            return _finish(answer, "refused" if not grounded or REFUSAL.search(answer[:120]) else "answered")
        for c in calls:
            name = _tool_name(c["function"]["name"]) or c["function"]["name"]
            args = c["function"].get("arguments") or {}
            if isinstance(args, str):
                args = json.loads(args or "{}")
            if name in METRIC_TOOLS and default_period and not any(args.get(k) for k in ("period", "start", "end")):
                args = {**args, "period": default_period}
            call_args = {**args, "_user_q": question}
            try:
                if name not in TOOLS:
                    raise ToolError("ferramenta inexistente; use uma de: " + ", ".join(TOOLS))
                result, ok = TOOLS[name][0](call_args), True
            except ToolError as e:
                result, ok = {"error": str(e)}, False
            rows = result.get("rows") if isinstance(result, dict) else result
            if ok and name in METRIC_TOOLS and rows:
                st["table"] = {"tool": name, "args": args, "rows": rows}
            trace.append({"tool": name, "args": args, "ok": ok,
                          "rows": len(rows) if isinstance(rows, list) else 0,
                          "error": None if ok else result["error"],
                          "scope": {k: result.get(k, result.get("survey_filter") if k == "survey" else None)
                                    for k in ("survey", "question", "group_by", "period", "coverage", "min_n")
                                    if isinstance(result, dict) and (k in result or
                                                                     (k == "survey" and "survey_filter" in result))}})
            if name == "nps" and ok and isinstance(result, dict):
                trace[-1]["scope"]["min_n"] = call_args.get("min_n")
                trace[-1]["scope"]["small_sample_rows"] = result.get("small_sample_rows", 0)
            content = json.dumps(result, ensure_ascii=False, default=str)[:6000]
            outputs.append(content)
            messages.append({"role": "tool", "tool_name": name, "content": content})
    ev("loop", "block", f"{MAX_STEPS} passos sem resposta")
    return _finish("Não consegui concluir em poucos passos. Reformule a pergunta.", "blocked")


if __name__ == "__main__":
    import sys
    print(json.dumps(ask([{"role": "user", "content": " ".join(sys.argv[1:])}]), ensure_ascii=False, indent=2))
