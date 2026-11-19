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
METRIC_TOOLS = ("nps", "choice_share", "scale_mean", "evaluation_count", "chart")


# ---------------------------------------------------------------- tools (solvis_tools/)
# As tools vivem em solvis_tools/tools/, uma por arquivo. O agente usa as do perfil analyst que
# calculam métricas e catálogo; os nomes abaixo continuam exportados para os testes e o MCP.
import sys as _sys  # noqa: E402
_sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import solvis_tools as _lib  # noqa: E402
from solvis_tools.core.db import ch  # noqa: E402,F401
from solvis_tools.core.errors import ToolError  # noqa: E402,F401
from solvis_tools.core.periods import PRESETS, resolve_dates, resolve_period  # noqa: E402,F401
from solvis_tools.core.resolve import (METRIC_TYPES, _fold, _pick, _round_nps, coverage,  # noqa: E402,F401
                                       resolve_group_by, resolve_question, resolve_survey)

AGENT_TOOLS = ("nps", "scale_mean", "choice_share", "evaluation_count", "chart", "list_surveys", "list_questions",
               "list_unit_properties", "data_coverage")


def _bind(name):
    return lambda args: _lib.call("analyst", name, args, strict=False)


TOOLS = {}
for _n in AGENT_TOOLS:
    _t = _lib.REGISTRY[_n]
    TOOLS[_n] = (_bind(_n), _t["model_hint"] or _t["description"],
                 {k: v["type"] for k, v in _t["input_schema"]["properties"].items()}, _t["input_schema"]["required"])
# Atalhos t_<tool>(args) usados pelos testes.
t_nps, t_scale_mean, t_choice_share, t_evaluation_count, t_chart, t_list_surveys, t_list_questions, \
    t_list_unit_properties, t_data_coverage = (TOOLS[n][0] for n in AGENT_TOOLS)


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
   "mapa de calor das top 10 unidades por hora" -> chart(kind="heatmap", top=10, period="yesterday")
   "gráfico do NPS por regional" -> chart(kind="bar", metric="nps", by="Regional", survey="Satisfação", period="yesterday")
   "curva de respostas por hora" -> chart(kind="line", metric="evaluation_count", by="hour", period="yesterday")
   "composição do NPS por regional" -> chart(kind="stacked", by="Regional", survey="Satisfação", period="yesterday")
   "notas 0 a 10" -> chart(kind="histogram", survey="Satisfação"); "volume × NPS das lojas" -> chart(kind="scatter", survey="Satisfação")
   "notas de todas as perguntas" -> chart(kind="profile", survey="Satisfação"); "NPS e volume por hora" -> chart(kind="combo", survey="Satisfação")
   Com gráfico, a tela já mostra os valores: descreva o padrão (pico, horários fortes) em uma ou duas frases.
   Se o usuário pedir para não ver números, não escreva números.
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
INTENT = [(re.compile(r"gr[aá]fico|visualiz|mapa de calor|heat ?map|curva|plot", re.I), {"chart"}),
          (re.compile(r"quantas? (avalia|respost|pessoas)|volume|mais (respostas|avalia)|menos (respostas|avalia)"
                      r"|recebeu mais|teve mais respostas", re.I), {"evaluation_count"}),
          (re.compile(r"\bnps\b|recomenda", re.I), {"nps"}),
          (re.compile(r"distribui|percentual|porcentagem|% d", re.I), {"choice_share"}),
          (re.compile(r"\bm[ée]dia\b|\bnota\b", re.I), {"scale_mean", "nps"})]


def intent_mismatch(question, trace):
    used = {t["tool"] for t in trace if t["ok"] and t["tool"] in METRIC_TOOLS and t["rows"]}
    if not used or "chart" in used:  # o gráfico já traz a métrica pedida
        return None
    for rx, ok in INTENT:
        if rx.search(question) and not (used & ok):
            label = {"chart": "gráfico", "evaluation_count": "volume de avaliações", "nps": "NPS", "choice_share": "distribuição",
                     "scale_mean": "média"}[sorted(ok)[0]]
            return (f"O usuário pediu {label}, mas você usou {', '.join(sorted(used))}. "
                    f"Chame {' ou '.join(sorted(ok))}.")
    return None


NO_NUMBERS = re.compile(r"(n[aã]o|sem) (quero )?(ver )?(os )?n[uú]meros|apenas o (gr[aá]fico|heat ?map|mapa)"
                        r"|s[oó] o (gr[aá]fico|heat ?map|mapa)", re.I)


def chart_caption(c):
    from solvis_tools.core import charts
    return charts.caption(c)


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


FOLLOW_UP = re.compile(r"^(e|e agora|agora|e por|e no|e na|e o|e a|mesmo|isso|esse|essa|também|tamb[eé]m)\b"
                       r"|^(por|no|na|em|só|apenas)\b", re.I)
TYPOS = [(re.compile(r"\b(o|do|de|no|um|seu|meu|nosso) nos\b", re.I), r"\1 NPS"),
         (re.compile(r"\bnos (por|da|de|atual|geral|das|dos|ontem|hoje)\b", re.I), r"NPS \1"),
         (re.compile(r"\bnsp\b|\bnpss\b|\bnp s\b", re.I), "NPS")]


def normalize_question(q):
    """Corrige erros de digitação comuns em nomes de métrica ('o nos atual' -> 'o NPS atual')."""
    for rx, rep in TYPOS:
        q = rx.sub(rep, q)
    return q


def model_turns(history):
    """Turnos que o modelo vê. Cada pergunta nova é um turno independente: o histórico inteiro fazia o
    modelo pequeno repetir a chamada anterior (ex.: heatmap de novo num pedido de barras). Só uma
    continuação curta ("e por Regional?") leva junto a pergunta anterior, como contexto em texto."""
    users = [m["content"] for m in history if m["role"] == "user"]
    if not users:
        return [], ""
    cur = normalize_question(users[-1])
    if len(users) > 1 and FOLLOW_UP.search(cur.strip()) and len(cur.split()) <= 8:
        prev = normalize_question(users[-2])
        return [{"role": "user", "content": f"Pergunta anterior (contexto): {prev}\nPergunta atual: {cur}"}], cur
    return [{"role": "user", "content": cur}], cur


def follow_up_dimension(question):
    """Recorte citado numa continuação ("e por Regional?"): o código aplica; o modelo pequeno repete o anterior."""
    if not re.search(r"^\s*(e|e agora|agora)?\s*(por|no|na)\b", question, re.I):
        return None
    text = re.sub(r"^\s*(e|e agora|agora)?\s*(por|no|na)\s+", "", question, flags=re.I).strip(" ?.!")
    f = _fold(text)
    if not f:
        return None
    if f[0] in ("unidade", "unidades", "loja", "lojas"):
        return "unit"
    if f[0] in ("hora", "horas", "horario"):
        return "hour"
    if f[0] in ("canal", "canais"):
        return "channel"
    try:
        _, prop = resolve_group_by(text)
        return prop["name"] if prop else None
    except ToolError:
        return None


TOP_N = re.compile(r"\btop\s*(?:n\s*)?(?:superior\s*)?(?:de\s*|a\s*)?(\d{1,2})\b"
                   r"|\b(\d{1,2})\s+(?:melhores|piores|maiores|menores|primeir[ao]s|unidades|lojas)\b", re.I)


def top_from_question(q):
    m = TOP_N.search(q)
    return int(m.group(1) or m.group(2)) if m else None


def ask(history, source="cli"):
    """history: lista de {role, content}. Devolve a resposta e tudo o que aconteceu até ela.

    Toda saída passa por _finish(): checagens de metodologia e registro em ops.* (agent/audit.py).
    """
    import time
    t0 = time.time()
    turns, question = model_turns(history)
    if not turns:
        turns, question = history, ""
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
        from solvis_tools.core import skill_index as context  # trechos da skill por busca vetorial
        picked = context.retrieve(question, ch)
        system += context.render(picked)
        st["context"] = [f"{r['source']} · {r['heading']}" for r in picked]
    notes = unsupported_notes(question)
    if notes:
        system += "\n\nATENÇÃO, nesta pergunta: " + " ".join(notes) + " Diga isso na primeira frase."
    default_period = period_from_question(question)
    messages = [{"role": "system", "content": system}] + turns
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
            spec = (st["table"] or {}).get("chart")
            if spec and NO_NUMBERS.search(question):  # pedido explícito sem números: legenda vem do código
                if _NUM.search(answer):
                    ev("no_numbers", "annotate", "legenda do modelo trocada por uma sem contagens")
                answer = chart_caption(spec)
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
            if name in METRIC_TOOLS and not any(args.get(k) for k in ("period", "start", "end")):
                args = {**args, "period": default_period or "last_7_days"}  # regra 7 do prompt
            n_top = top_from_question(question)
            if name == "chart" and n_top and str(args.get("top") or "") != str(n_top):
                ev("top_n", "annotate", f"top: {args.get('top')} -> {n_top}")
                args = {**args, "top": n_top}
            follow = len(turns) == 1 and turns[0]["content"].startswith("Pergunta anterior")
            dim = follow_up_dimension(question) if follow else None
            if dim and name in ("chart", "nps", "evaluation_count"):
                key = "by" if name == "chart" else "group_by"
                if args.get(key) != dim:
                    ev("follow_up", "annotate", f"{key}: {args.get(key)} -> {dim}")
                    args = {**{k: v for k, v in args.items() if k not in ("by", "group_by")}, key: dim}
            call_args = {**args, "_user_q": question}
            try:
                if name not in TOOLS:
                    raise ToolError("ferramenta inexistente; use uma de: " + ", ".join(TOOLS))
                result, ok = TOOLS[name][0](call_args), True
            except ToolError as e:
                result, ok = {"error": str(e)}, False
            rows = result.get("rows") if isinstance(result, dict) else result
            if ok and name in METRIC_TOOLS and rows and not (st["table"] or {}).get("chart"):
                st["table"] = {"tool": name, "args": args, "rows": rows}
                if isinstance(result, dict) and isinstance(result.get("chart"), dict):
                    st["table"]["chart"] = result["chart"]
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
            if ok and name == "chart" and isinstance(result, dict) and isinstance(result.get("chart"), dict):
                # Gráfico pronto: a resposta é a legenda do código (destaques tirados do próprio gráfico).
                answer = chart_caption(result["chart"])
                if not NO_NUMBERS.search(question):
                    for n_ in result["chart"].get("notes", []):
                        answer += "\n• " + n_
                for n_ in notes:
                    ev("capability", "annotate", n_)
                    answer = n_ + " " + answer
                w = (result.get("coverage") or {}).get("warning")
                if w:
                    ev("coverage", "annotate", w)
                    answer += "\n⚠ " + w.split(" Diga ao usuário")[0]
                ev("chart", "annotate", result["chart"]["type"])
                return _finish(answer, "answered")
    ev("loop", "block", f"{MAX_STEPS} passos sem resposta")
    return _finish("Não consegui concluir em poucos passos. Reformule a pergunta.", "blocked")


if __name__ == "__main__":
    import sys
    print(json.dumps(ask([{"role": "user", "content": " ".join(sys.argv[1:])}]), ensure_ascii=False, indent=2))
