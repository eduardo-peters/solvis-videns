#!/usr/bin/env python3
"""Gera o conjunto de treino LoRA a partir da skill e do contrato das tools.

O que o modelo aprende é COMPORTAMENTO, nunca dados de cliente:
  1. escolher a chamada certa (tool e argumentos) a partir da pergunta;
  2. recusar o que não existe na Solvis (pela skill: metrics.yaml, invariantes);
  3. perguntar quando falta informação (INV-11);
  4. escrever a resposta a partir do resultado da tool (n, período, pior/melhor, avisos).
Pesquisas, perguntas, propriedades e números são fictícios. Nenhuma pergunta de
agent/eval_baseline.py (dev ou holdout) entra no treino; o script confere e falha se entrar.

Formato: JSONL com {"messages": [...]} no padrão chat do mlx_lm. Chamadas de tool e
resultados são texto (mesma convenção do backend mlx do agente, ver agent/agent.py):
  assistant: nps(survey="Clima", period="yesterday")
  user:      [resultado de nps]\\n{...json...}

  python3 agent/train/build_dataset.py --version v2   → ops/training/v2/data/{train,valid}.jsonl
  python3 agent/train/build_dataset.py --version v1   reproduz os dados da v1 (mesma semente e mistura)
"""
import json
import random
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "agent"))
import agent  # noqa: E402
import eval_baseline  # noqa: E402

TRAINING = ROOT / "ops" / "training"
rng = random.Random(20261119)

SURVEYS = ["Clima", "Pós-venda", "Refeitório Central", "Atendimento Digital", "Lojas Sul", "Entrega Expressa",
           "Experiência no Balcão", "Hotelaria"]
PROPS = ["Bandeira", "Região", "Diretoria", "Cluster", "Formato", "Supervisor"]
SCALES = ["Atendimento no caixa", "Limpeza", "Rapidez", "Variedade", "Preço", "Cordialidade", "Temperatura da comida"]
CHOICES = ["Canal de compra", "Forma de pagamento", "Frequência de visita", "Motivo da visita"]
UNITS = ["Loja Centro", "Loja Norte", "Unidade Paulista", "Restaurante Leste", "Filial 12", "Loja Shopping Sul",
         "Unidade Aeroporto", "Loja Bairro Alto"]
PERIODS = [("ontem", "yesterday", ("2026-03-11", "2026-03-11")), ("hoje", "today", ("2026-03-12", "2026-03-12")),
           ("nos últimos 7 dias", "last_7_days", ("2026-03-05", "2026-03-11")),
           ("este mês", "this_month", ("2026-03-01", "2026-03-12")),
           ("no mês passado", "last_month", ("2026-02-01", "2026-02-28")),
           ("em janeiro de 2026", "month:2026-01", ("2026-01-01", "2026-01-31"))]


def fmt_call(tool, **args):
    return tool + "(" + ", ".join(f'{k}={v}' if isinstance(v, int) else f'{k}="{v}"' for k, v in args.items()) + ")"


def br(n):
    return f"{n:,}".replace(",", ".")


def date_br(iso):
    y, m, d = iso.split("-")
    return f"{d}/{m}/{y}"


def period_text(p):
    s, e = p[2]
    return f"em {date_br(s)}" if s == e else f"de {date_br(s)} a {date_br(e)}"


def convo(user, *turns):
    msgs = [{"role": "system", "content": agent.MLX_SYSTEM}, {"role": "user", "content": user}]
    for role, content in turns:
        msgs.append({"role": role, "content": content})
    return {"messages": msgs}


def result(tool, payload):
    return ("user", f"[resultado de {tool}]\n" + json.dumps(payload, ensure_ascii=False))


# ------------------------------------------------------------------ geradores

def nps_total():
    s, p = rng.choice(SURVEYS), rng.choice(PERIODS)
    q = rng.choice(["Qual o NPS da pesquisa {s} {p}?", "Me diz o NPS da {s} {p}.", "Como está o NPS na {s} {p}?",
                    "NPS {p} da pesquisa {s}", "Como ficou a recomendação na {s} {p}?"]).format(s=s, p=p[0])
    n = rng.randint(80, 20000)
    pr, de = rng.randint(30, 85), rng.randint(2, 30)
    v = round(pr - de)
    res = {"survey": s, "period": {"start": p[2][0], "end": p[2][1]},
           "total": {"promoters": round(n * pr / 100), "detractors": round(n * de / 100), "n": n, "nps": v},
           "rows": [{"nps": v, "n": n}]}
    return convo(q, ("assistant", fmt_call("nps", survey=s, period=p[1])), result("nps", res),
                 ("assistant", f"O NPS da pesquisa {s} foi {v}, com {br(n)} respostas, {period_text(p)}."))


def nps_group():
    s, p, prop = rng.choice(SURVEYS), rng.choice(PERIODS), rng.choice(PROPS)
    q = rng.choice(["NPS por {g} na pesquisa {s} {p}", "Quero o NPS da {s} quebrado por {g} {p}.",
                    "Como está o NPS de cada {g} na {s} {p}?"]).format(s=s, p=p[0], g=prop.lower())
    vals = sorted(rng.sample(range(-10, 95), 4))
    names = rng.sample(["A", "B", "C", "D", "E", "F"], 4)
    rows = [{"value": f"{prop} {nm}", "nps": v, "n": rng.randint(35, 4000)} for nm, v in zip(names, vals)]
    tot_n = sum(r["n"] for r in rows)
    tot = rng.randint(vals[0] + 1, vals[-1] - 1)
    res = {"survey": s, "group_by": prop, "period": {"start": p[2][0], "end": p[2][1]},
           "total": {"n": tot_n, "nps": tot}, "rows": rows, "worst": rows[0], "best": rows[-1]}
    w, b = rows[0], rows[-1]
    return convo(q, ("assistant", fmt_call("nps", survey=s, group_by=prop, period=p[1])), result("nps", res),
                 ("assistant", f"Na pesquisa {s}, {period_text(p)}, o NPS geral foi {tot} (n = {br(tot_n)}). "
                               f"Por {prop.lower()}, o menor foi {w['value']} com {w['nps']} (n = {br(w['n'])}) e o "
                               f"maior foi {b['value']} com {b['nps']} (n = {br(b['n'])})."))


def ranking():
    s, p = rng.choice(SURVEYS), rng.choice(PERIODS)
    worst = rng.random() < 0.5
    word = rng.choice(["loja", "unidade"])
    q = rng.choice(["Qual a {w} {u} em NPS na pesquisa {s} {p}?", "Qual {u} teve o {w2} NPS na {s} {p}?",
                    "Ranking: {w} {u} da {s} {p}"]).format(
        w="pior" if worst else "melhor", w2="pior" if worst else "melhor", u=word, s=s, p=p[0])
    u = rng.sample(UNITS, 3)
    rows = sorted([{"unit": x, "nps": rng.randint(-20, 99), "n": rng.randint(30, 900)} for x in u],
                  key=lambda r: r["nps"])
    hidden = rng.randint(0, 40)
    res = {"survey": s, "group_by": "unit", "period": {"start": p[2][0], "end": p[2][1]},
           "total": {"n": sum(r["n"] for r in rows) + hidden * 10, "nps": rng.randint(20, 80)}, "rows": rows,
           "worst": rows[0], "best": rows[-1], "hidden_rows_below_min_n": hidden}
    pick = rows[0] if worst else rows[-1]
    extra = f" {hidden} unidades com menos de 30 respostas ficaram de fora." if hidden else ""
    return convo(q, ("assistant", fmt_call("nps", survey=s, group_by="unit", min_n=30, period=p[1])),
                 result("nps", res),
                 ("assistant", f"A {'pior' if worst else 'melhor'} {word} em NPS na pesquisa {s}, {period_text(p)}, "
                               f"foi {pick['unit']}, com NPS {pick['nps']} (n = {pick['n']}).{extra}"))


def average_of_nps():
    """INV-02: 'média do NPS das lojas' é o NPS do conjunto, nunca média das linhas."""
    s, p = rng.choice(SURVEYS), rng.choice(PERIODS)
    q = rng.choice(["Qual a média do NPS das lojas da {s} {p}?", "Faz a média dos NPS das unidades da {s} {p}",
                    "Qual o NPS médio das lojas na pesquisa {s} {p}?"]).format(s=s, p=p[0])
    n, v = rng.randint(500, 9000), rng.randint(10, 85)
    res = {"survey": s, "group_by": "unit", "period": {"start": p[2][0], "end": p[2][1]},
           "total": {"n": n, "nps": v},
           "total_note": "total = NPS geral do conjunto, calculado pelas contagens (não é média das linhas)",
           "rows": [{"unit": x, "nps": rng.randint(-10, 99), "n": rng.randint(30, 400)} for x in rng.sample(UNITS, 3)]}
    return convo(q, ("assistant", fmt_call("nps", survey=s, group_by="unit", period=p[1])), result("nps", res),
                 ("assistant", f"O NPS do conjunto das lojas na pesquisa {s}, {period_text(p)}, foi {v} "
                               f"(n = {br(n)}). Ele é calculado pelas contagens de todas as respostas; uma média "
                               f"simples dos NPS de cada loja daria um número errado."))


def scale():
    s, p, qn = rng.choice(SURVEYS), rng.choice(PERIODS), rng.choice(SCALES)
    q = rng.choice(["Qual a nota média de {q} na pesquisa {s} {p}?", "Média de {q} na {s} {p}",
                    "Como está a avaliação de {q} na {s} {p}? Quero a média."]).format(q=qn, s=s, p=p[0])
    m, n = round(rng.uniform(2.5, 4.95), 2), rng.randint(50, 12000)
    res = {"survey": s, "question": f"{rng.randint(2, 9)}. {qn}", "period": {"start": p[2][0], "end": p[2][1]},
           "rows": [{"mean": m, "n": n}]}
    return convo(q, ("assistant", fmt_call("scale_mean", survey=s, question=qn, period=p[1])),
                 result("scale_mean", res),
                 ("assistant", f"A média de {qn} na pesquisa {s} foi {m}, com {br(n)} respostas, {period_text(p)}. "
                               f"Respostas 'Não se aplica' não entram na média."))


def distribution():
    s, p = rng.choice(SURVEYS), rng.choice(PERIODS)
    qn = rng.choice(SCALES + CHOICES)
    q = rng.choice(["Qual a distribuição das respostas de {q} na {s} {p}?", "Percentual de cada alternativa de "
                    "{q} na pesquisa {s} {p}", "Como se dividem as respostas de {q} na {s} {p}?"]).format(
        q=qn, s=s, p=p[0])
    a = rng.randint(40, 80)
    b = rng.randint(5, 100 - a - 2)
    c = 100 - a - b
    n = rng.randint(100, 8000)
    rows = [{"letter": "A", "text": "Opção A", "share_pct": a, "n": n}, {"letter": "B", "text": "Opção B",
            "share_pct": b, "n": n}, {"letter": "C", "text": "Não se aplica", "share_pct": c, "n": n}]
    res = {"survey": s, "question": f"4. {qn}", "period": {"start": p[2][0], "end": p[2][1]}, "rows": rows}
    return convo(q, ("assistant", fmt_call("choice_share", survey=s, question=qn, period=p[1])),
                 result("choice_share", res),
                 ("assistant", f"Em {qn}, na pesquisa {s}, {period_text(p)}: Opção A {a}%, Opção B {b}% e "
                               f"'Não se aplica' {c}%, sobre {br(n)} respostas."))


def volume():
    p = rng.choice(PERIODS)
    kind = rng.choice(["total", "unit", "survey"])
    if kind == "survey":
        q = rng.choice(["Qual pesquisa teve mais respostas {p}?", "Que pesquisa recebeu mais avaliações {p}?",
                        "Volume por pesquisa {p}"]).format(p=p[0])
        s = rng.sample(SURVEYS, 3)
        rows = [{"survey": x, "evaluations": v} for x, v in zip(s, sorted(rng.sample(range(50, 9000), 3), reverse=True))]
        res = {"survey_filter": "nenhum (todas as pesquisas)", "group_by": "pesquisa",
               "period": {"start": p[2][0], "end": p[2][1]}, "rows": rows, "most": rows[0]}
        ans = f"A pesquisa com mais avaliações {period_text(p)} foi {rows[0]['survey']}, com {br(rows[0]['evaluations'])}."
        return convo(q, ("assistant", fmt_call("evaluation_count", group_by="survey", period=p[1])),
                     result("evaluation_count", res), ("assistant", ans))
    if kind == "unit":
        q = rng.choice(["Qual loja teve mais respostas {p}?", "Que unidade recebeu mais avaliações {p}?"]).format(p=p[0])
        u = rng.sample(UNITS, 3)
        rows = [{"unit": x, "evaluations": v} for x, v in zip(u, sorted(rng.sample(range(20, 900), 3), reverse=True))]
        res = {"survey_filter": "nenhum (todas as pesquisas)", "group_by": "unit",
               "period": {"start": p[2][0], "end": p[2][1]}, "rows": rows,
               "most": {**rows[0], "surveys": [{"survey": rng.choice(SURVEYS), "evaluations": rows[0]["evaluations"]}]}}
        ans = (f"A unidade com mais avaliações {period_text(p)} foi {rows[0]['unit']}, com "
               f"{br(rows[0]['evaluations'])}, todas da pesquisa {res['most']['surveys'][0]['survey']}.")
        return convo(q, ("assistant", fmt_call("evaluation_count", group_by="unit", period=p[1])),
                     result("evaluation_count", res), ("assistant", ans))
    s = rng.choice(SURVEYS)
    q = rng.choice(["Quantas avaliações a {s} teve {p}?", "Quantas pessoas responderam a {s} {p}?"]).format(s=s, p=p[0])
    n = rng.randint(10, 20000)
    res = {"survey_filter": s, "period": {"start": p[2][0], "end": p[2][1]}, "rows": [{"evaluations": n}]}
    return convo(q, ("assistant", fmt_call("evaluation_count", survey=s, period=p[1])),
                 result("evaluation_count", res),
                 ("assistant", f"A pesquisa {s} teve {br(n)} avaliações {period_text(p)}. Avaliações não são "
                               f"pessoas únicas: a mesma pessoa pode responder mais de uma vez."))


def coverage_warning():
    s = rng.choice(SURVEYS)
    q = f"NPS da {s} nos últimos 7 dias"
    n, v = rng.randint(300, 5000), rng.randint(10, 85)
    res = {"survey": s, "period": {"start": "2026-03-05", "end": "2026-03-11"},
           "coverage": {"days_in_period": 7, "days_with_data": 2,
                        "warning": "Só há dados de 2026-03-10 a 2026-03-11 neste período."},
           "total": {"n": n, "nps": v}, "rows": [{"nps": v, "n": n}]}
    return convo(q, ("assistant", fmt_call("nps", survey=s, period="last_7_days")), result("nps", res),
                 ("assistant", f"O NPS da pesquisa {s} foi {v} (n = {br(n)}). Atenção: dos 7 dias pedidos, só há "
                               f"dados de 10/03/2026 a 11/03/2026, então o resultado cobre só esses dois dias."))


def tool_error_ambiguous():
    s, p = rng.choice(SURVEYS), rng.choice(PERIODS)
    a, b = rng.sample(SCALES, 2)
    q = f"Qual a média de atendimento na {s} {p[0]}?"
    err = {"error": f"pergunta 'atendimento' é ambíguo(a). Pergunte ao usuário qual destas: {a}; {b}"}
    return convo(q, ("assistant", fmt_call("scale_mean", survey=s, question="atendimento", period=p[1])),
                 ("user", "[resultado de scale_mean]\n" + json.dumps(err, ensure_ascii=False)),
                 ("assistant", f"Há mais de uma pergunta que pode ser 'atendimento' na pesquisa {s}: {a} e {b}. "
                               f"Qual delas você quer?"))


def tool_error_type():
    s, p, qn = rng.choice(SURVEYS), rng.choice(PERIODS), rng.choice(SCALES)
    q = f"Qual o NPS da pergunta de {qn} na {s} {p[0]}?"
    err = {"error": f"A pergunta 3 ('{qn}') é do tipo Scale: nps não existe para ela. Diga isso ao usuário. "
                    f"Métricas que existem para ela: scale_mean, choice_share."}
    return convo(q, ("assistant", fmt_call("nps", survey=s, question=qn, period=p[1])),
                 ("user", "[resultado de nps]\n" + json.dumps(err, ensure_ascii=False)),
                 ("assistant", f"NPS só existe para a pergunta de recomendação. {qn} é uma pergunta de escala: "
                               f"posso mostrar a média ou a distribuição das respostas dela."))


def ask_survey():
    """INV-11: sem pesquisa citada, pergunta em vez de adivinhar."""
    p = rng.choice(PERIODS)
    q = rng.choice(["Qual foi o NPS {p}?", "Me dá a nota média de limpeza {p}", "Qual a pior loja em NPS {p}?"]).format(p=p[0])
    return convo(q, ("assistant", "De qual pesquisa? Se não souber o nome, posso listar as pesquisas disponíveis."))


# --- v2: volume e distribuição (falhas da v1 em docs/training.md) ---------------------------

def volume_no_survey():
    """Sem pesquisa citada, volume por loja/pesquisa usa group_by e NÃO inventa 'survey'."""
    p = rng.choice(PERIODS)
    by = rng.choice(["unit", "survey"])
    if by == "unit":
        q = rng.choice(["Qual a loja que mais teve respostas {p}?", "Qual unidade recebeu mais avaliações {p}?",
                        "Que loja teve o maior volume de respostas {p}?", "Onde tivemos mais avaliações {p}?",
                        "Qual loja liderou em avaliações {p} e de qual pesquisa elas vieram?",
                        "Ranking de lojas por quantidade de avaliações {p}"]).format(p=p[0])
    else:
        q = rng.choice(["Que pesquisa juntou mais respostas {p}?", "Que pesquisa teve mais avaliações {p}?",
                        "Quantas avaliações teve cada pesquisa {p}?", "Volume de respostas por pesquisa {p}",
                        "Qual a pesquisa mais respondida {p}?"]).format(p=p[0])
    has_period = any(w in q for w in ("ontem", "hoje", "dias", "mês", "janeiro"))
    per = p[1] if has_period else "last_7_days"
    ptxt = period_text(p) if has_period else "de 05/03/2026 a 11/03/2026"
    if by == "unit":
        u = rng.sample(UNITS, 3)
        rows = [{"unit": x, "evaluations": v} for x, v in zip(u, sorted(rng.sample(range(20, 900), 3), reverse=True))]
        sv = rng.choice(SURVEYS)
        res = {"survey_filter": "nenhum (todas as pesquisas)", "group_by": "unit", "rows": rows,
               "most": {**rows[0], "surveys": [{"survey": sv, "evaluations": rows[0]["evaluations"]}]}}
        ans = (f"A unidade com mais avaliações {ptxt} foi {rows[0]['unit']}, com {br(rows[0]['evaluations'])}, "
               f"todas da pesquisa {sv}.")
    else:
        sv = rng.sample(SURVEYS, 3)
        rows = [{"survey": x, "evaluations": v} for x, v in zip(sv, sorted(rng.sample(range(30, 15000), 3), reverse=True))]
        res = {"survey_filter": "nenhum (todas as pesquisas)", "group_by": "pesquisa", "rows": rows, "most": rows[0]}
        ans = (f"A pesquisa com mais avaliações {ptxt} foi {rows[0]['survey']}, com {br(rows[0]['evaluations'])}. "
               f"Em seguida vêm {rows[1]['survey']} ({br(rows[1]['evaluations'])}) e {rows[2]['survey']} "
               f"({br(rows[2]['evaluations'])}).")
    return convo(q, ("assistant", fmt_call("evaluation_count", group_by=by, period=per)),
                 result("evaluation_count", res), ("assistant", ans))


def volume_not_nps():
    """'Quantas avaliações' é evaluation_count, nunca o n do NPS."""
    s, p = rng.choice(SURVEYS), rng.choice(PERIODS)
    q = rng.choice(["Quantas avaliações a {s} teve {p}?", "Quantas respostas a pesquisa {s} recebeu {p}?",
                    "Qual o volume de avaliações da {s} {p}?", "Quantas pessoas avaliaram a {s} {p}?"]).format(s=s, p=p[0])
    n = rng.randint(10, 20000)
    res = {"survey_filter": s, "period": {"start": p[2][0], "end": p[2][1]}, "total": {"evaluations": n},
           "rows": [{"evaluations": n}]}
    return convo(q, ("assistant", fmt_call("evaluation_count", survey=s, period=p[1])),
                 result("evaluation_count", res),
                 ("assistant", f"A pesquisa {s} teve {br(n)} avaliações {period_text(p)}."))


def distribution_read():
    """Ler choice_share: citar cada alternativa com o %, o n, e a pergunta pelo nome."""
    s, p = rng.choice(SURVEYS), rng.choice(PERIODS)
    kind = rng.choice(["stars", "yesno", "choice"])
    if kind == "stars":
        qn = rng.choice(SCALES)
        labels = ["5 estrelas", "4 estrelas", "3 estrelas", "2 estrelas", "1 estrela"]
        q = rng.choice(["Qual a distribuição de estrelas de {q} na {s} {p}?", "Quantos por cento deram cada nota em "
                        "{q} na {s} {p}?", "Como se distribuem as notas de {q} na pesquisa {s} {p}?"]).format(q=qn, s=s, p=p[0])
    elif kind == "yesno":
        qn = rng.choice(["É a primeira vez que você visita a loja?", "Você encontrou tudo o que procurava?",
                         "Recomendaria para um amigo?"])
        labels = ["Sim", "Não"]
        q = rng.choice(["Qual o percentual de quem respondeu sim em '{q}' na {s} {p}?",
                        "Quantos por cento disseram sim para '{q}' na pesquisa {s} {p}?"]).format(q=qn, s=s, p=p[0])
    else:
        qn = rng.choice(CHOICES)
        labels = rng.sample(["Loja física", "Aplicativo", "Site", "Telefone", "Cartão", "Pix", "Dinheiro"], 3)
        q = rng.choice(["Qual a distribuição das respostas de {q} na {s} {p}?",
                        "Percentual de cada opção de {q} na pesquisa {s} {p}"]).format(q=qn, s=s, p=p[0])
    cuts = sorted(rng.sample(range(1, 100), len(labels) - 1))
    shares = [b - a for a, b in zip([0] + cuts, cuts + [100])]
    shares.sort(reverse=True)
    n = rng.randint(80, 9000)
    rows = [{"letter": chr(65 + i), "text": t, "answers": round(n * v / 100), "share_pct": v, "n": n}
            for i, (t, v) in enumerate(zip(labels, shares))]
    num = rng.randint(2, 14)
    res = {"survey": s, "question": f"{num}. {qn}", "period": {"start": p[2][0], "end": p[2][1]}, "rows": rows}
    parts = ", ".join(f"{r['text']} {r['share_pct']}%" for r in rows)
    if kind == "yesno":
        sim = rows[[r["text"] for r in rows].index("Sim")]
        ans = (f"Em '{qn}', na pesquisa {s}, {period_text(p)}, {sim['share_pct']}% responderam Sim, de "
               f"{br(n)} respostas ({parts}).")
    else:
        ans = f"Em {qn}, na pesquisa {s}, {period_text(p)}: {parts}, sobre {br(n)} respostas."
    return convo(q, ("assistant", fmt_call("choice_share", survey=s, question=qn, period=p[1])),
                 result("choice_share", res), ("assistant", ans))


REFUSALS = [
    (["Qual o CSAT da pesquisa {s}?", "Me passa o CSAT de atendimento da {s}", "Qual o percentual de satisfeitos da {s}?"],
     "A Solvis não tem métrica CSAT. Diga qual pergunta de escala é o seu CSAT e quais alternativas contam como "
     "satisfeito, e eu mostro a média ou a distribuição dela."),
    (["Qual a taxa de resposta da {s}?", "Quantos por cento dos clientes responderam a {s}?"],
     "Taxa de resposta não existe na Solvis: o sistema não sabe quantas pessoas foram convidadas ou passaram pela "
     "loja. Posso mostrar a quantidade de avaliações."),
    (["Como o NPS da {s} se compara com o mercado?", "Qual o benchmark de NPS do setor para a {s}?"],
     "Não há benchmark de mercado na Solvis. Posso mostrar o NPS da pesquisa e comparar unidades ou recortes entre si."),
    (["O NPS da {s} melhorou em relação ao mês anterior?", "Compara o NPS da {s} desta semana com a anterior",
      "O NPS da {s} caiu?"],
     "Comparação entre períodos ainda não está disponível neste ambiente. Posso mostrar o NPS de cada período "
     "separadamente."),
    (["O que os clientes estão comentando na {s}?", "Quais as principais reclamações na {s}?",
      "Me mostra os comentários negativos da {s}"],
     "Comentários e temas ainda não estão disponíveis neste ambiente. Posso mostrar o NPS e as notas da pesquisa."),
    (["Quais os motivos de insatisfação na {s}?", "Quais pontos de melhoria os clientes marcaram na {s}?"],
     "Perguntas de múltipla resposta, como motivos, ainda não estão disponíveis neste ambiente."),
    (["Qual vai ser o NPS da {s} no mês que vem?", "Faz uma previsão do NPS da {s}"],
     "Não faço previsão: os números vêm só do que foi respondido. Posso mostrar o NPS dos períodos disponíveis."),
    (["Qual o faturamento das lojas da {s}?", "Quanto as lojas da {s} venderam?"],
     "Faturamento e vendas não estão nos dados de pesquisa da Solvis. Posso mostrar NPS, notas e volume de avaliações."),
    (["Qual o sentimento dos comentários da {s}?", "Qual o tom das respostas da {s}?"],
     "Tom e sentimento dos comentários não estão disponíveis neste ambiente."),
    (["Quem foi o cliente que deu nota zero na {s}?", "Me passa o e-mail de quem reclamou na {s}"],
     "Não identifico respondentes nem mostro dados pessoais. Posso mostrar resultados agregados."),
]


def refusal():
    qs, ans = rng.choice(REFUSALS)
    return convo(rng.choice(qs).format(s=rng.choice(SURVEYS)), ("assistant", ans))


MIX_V1 = [(nps_total, 40), (nps_group, 35), (ranking, 35), (average_of_nps, 20), (scale, 35), (distribution, 30),
          (volume, 40), (coverage_warning, 12), (tool_error_ambiguous, 15), (tool_error_type, 15), (ask_survey, 15),
          (refusal, 60)]
MIX_V2 = [(nps_total, 40), (nps_group, 35), (ranking, 35), (average_of_nps, 20), (scale, 35), (distribution, 30),
       (volume, 40), (coverage_warning, 12), (tool_error_ambiguous, 15), (tool_error_type, 15), (ask_survey, 15),
       (refusal, 60),
       # v2
       (volume_no_survey, 50), (volume_not_nps, 30), (distribution_read, 50)]


MIXES = {"v1": MIX_V1, "v2": MIX_V2}


def main():
    import argparse
    import hashlib
    ap = argparse.ArgumentParser()
    ap.add_argument("--version", choices=list(MIXES), default="v2")
    a = ap.parse_args()
    MIX = MIXES[a.version]
    OUT = TRAINING / a.version / "data"
    data = [fn() for fn, k in MIX for _ in range(k)]
    rng.shuffle(data)
    banned = {re.sub(r"\W+", " ", c["q"].lower()).strip() for c in eval_baseline.CASES + eval_baseline.HOLDOUT}
    for ex in data:
        u = re.sub(r"\W+", " ", ex["messages"][1]["content"].lower()).strip()
        if u in banned:
            sys.exit(f"pergunta de avaliação no treino: {u}")
        generated = json.dumps(ex["messages"][1:], ensure_ascii=False)  # o system é o prompt do agente
        if any(w in generated for w in ("Assaí", "Satisfação", "Tapioqueiras", "Regional", "40851", "1607201")):
            sys.exit("termo dos dados reais no treino")
    # --mask-prompt treina só a última mensagem do assistente: cada turno vira um exemplo,
    # para treinar tanto a chamada da tool quanto a resposta final.
    n_conv_valid = max(20, len(data) // 10)
    def explode(convs):
        out = []
        for ex in convs:
            m = ex["messages"]
            out += [{"messages": m[:i + 1]} for i, x in enumerate(m) if x["role"] == "assistant"]
        return out
    valid, train = explode(data[:n_conv_valid]), explode(data[n_conv_valid:])
    rng.shuffle(train)
    data, n_valid = valid + train, len(valid)
    OUT.mkdir(parents=True, exist_ok=True)
    for name, part in (("valid", data[:n_valid]), ("train", data[n_valid:])):
        (OUT / f"{name}.jsonl").write_text("\n".join(json.dumps(x, ensure_ascii=False) for x in part) + "\n")
    print(json.dumps({"version": a.version, "train_sha": hashlib.sha256((OUT / "train.jsonl").read_bytes()).hexdigest()[:12],
                      "train": len(data) - n_valid, "valid": n_valid, "conversations": sum(k for _, k in MIX),
                      "mix": {fn.__name__: k for fn, k in MIX}}, ensure_ascii=False))


if __name__ == "__main__":
    main()
