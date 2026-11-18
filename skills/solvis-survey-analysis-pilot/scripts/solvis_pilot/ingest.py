"""Normalização: avaliação da API V1 (formatted_answers por texto) → linhas por id.

Formato de entrada (app/domain/services/handler_answers_service.rb):
- NPS:                [{question_text, answer_value, answer_text}]
- Scale:              [{question_text, choice_text, choice_value}]
- Multiple Choice:    [{question_text, choice_text, [additional_field, additional_field_answer]}]
- Multiple Response:  {question_text: [{choice_text, [additional_field, additional_field_answer]}]}
- Text / Short Text:  [{question_text, [choice_value]}]       (choice_value = texto; some se vazio)
- demais tipos:       [[{question_text, choice_text}]]       (lista de listas; valor em choice_text)

Não há question_id nem choice_id: o motor volta aos ids pelo texto, usando o
questionário atual. Tipo + texto repetidos em duas perguntas não têm como ser
separados; essas respostas ficam sem question_id e marcadas como ambíguas.
"""

from __future__ import annotations

import datetime as dt
import re
from collections import Counter
from typing import Any, Dict, Iterable, List, Optional, Tuple

from .privacy import PERSONAL_TYPES, mask_pii
from .semantics import Questionnaire

# kind das linhas em answers
K_NPS, K_CHOICE, K_MULTI, K_OPEN, K_OTHER = "nps", "choice", "multi", "open", "other"


_TS = re.compile(r"(\d{4}-\d{2}-\d{2})[T ](\d{2}:\d{2}:\d{2})(?:\.\d+)?(Z|[+-]\d{2}:?\d{2})?$")


def local_started_at(raw: str) -> dt.datetime:
    """started_at vem com 'Z', mas o valor já é a hora local da unidade: não converter.

    A API serializa sempre em UTC ('Z'); os dígitos são a hora de parede da unidade.
    """
    m = _TS.match(raw.strip())
    if not m:
        raise ValueError(f"started_at inesperado: {raw!r}")
    naive = dt.datetime.fromisoformat(f"{m.group(1)}T{m.group(2)}")
    offset = m.group(3)
    if offset and offset not in ("Z", "+00:00", "+0000"):
        sign = 1 if offset[0] == "+" else -1
        hh, mm = int(offset[1:3]), int(offset[-2:])
        naive -= sign * dt.timedelta(hours=hh, minutes=mm)
    return naive


def eval_ref(started: dt.datetime, api_id: int) -> str:
    """unique_id do sistema: yymmdd(started_at) + id no shard com 12 dígitos (with_unique_id.rb)."""
    return started.strftime("%y%m%d") + "%012d" % int(api_id)


def _items(answer_type: str, answers: Any) -> Iterable[Tuple[str, Dict[str, Any]]]:
    """Itera (question_text, item) para qualquer formato de grupo."""
    if isinstance(answers, dict):  # Multiple Response
        for qtext, entries in answers.items():
            for entry in entries or [{}]:
                yield qtext, entry or {}
        return
    for item in answers or []:
        if isinstance(item, list):  # tipos "default": lista de listas
            for inner in item:
                if isinstance(inner, dict):
                    yield inner.get("question_text") or "", inner
        elif isinstance(item, dict):
            yield item.get("question_text") or "", item


def _clean_text(value: Any) -> Optional[str]:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def resolve_group(qn: Questionnaire, answer_type: str, items: List[Tuple[str, Dict[str, Any]]],
                  issues: Counter, day: str) -> List[Optional[int]]:
    """question_id de cada item de um grupo de formatted_answers.

    Texto único no questionário → id direto. Texto repetido em perguntas do mesmo tipo:
    1. em escala e escolha única, fica só a gêmea que tem a alternativa respondida;
    2. depois, a ordem: dentro de uma avaliação, as respostas de um tipo vêm em ordem
       crescente de posição (conferido em dados reais). Para cada item, calcula as
       perguntas possíveis em ALGUMA atribuição estritamente crescente da sequência
       inteira; se só sobra uma, ela vale em toda atribuição possível e é usada.
    Múltipla resposta não entra: a API funde no mesmo objeto as perguntas de mesmo texto.
    """
    pos = {q.id: q.position for q in qn.questions}
    cands = [qn.by_key.get((answer_type, text or ""), []) for text, _ in items]
    if answer_type in ("Scale", "Multiple Choice"):
        # gêmeas com alternativas diferentes: o texto da alternativa já diz qual foi respondida
        narrowed = []
        for (_, item), c in zip(items, cands):
            if len(c) > 1 and item.get("choice_text") is not None:
                fit = [q for q in c if qn.resolve_choice(q, item.get("choice_text"), item.get("choice_value")) is not None]
                c = fit if len(fit) < len(c) and fit else c
            narrowed.append(c)
        cands = narrowed
    out: List[Optional[int]] = [c[0] if len(c) == 1 else None for c in cands]
    for i, (text, _) in enumerate(items):
        if out[i] is not None and len(qn.by_key.get((answer_type, text or ""), [])) > 1:
            issues[(day, "resolved_by_choice", f"{answer_type}|{text}"[:160])] += 1
    if answer_type != "Multiple Response" and any(len(c) > 1 for c in cands) and all(cands):
        n = len(cands)
        fwd: List[List[int]] = []
        for i in range(n):
            floor = min((pos[q] for q in fwd[i - 1]), default=None) if i else None
            fwd.append([q for q in cands[i] if floor is None or pos[q] > floor])
        bwd: List[List[int]] = [[] for _ in range(n)]
        for i in range(n - 1, -1, -1):
            ceil = max((pos[q] for q in bwd[i + 1]), default=None) if i < n - 1 else None
            bwd[i] = [q for q in cands[i] if ceil is None or pos[q] < ceil]
        feasible = [[q for q in fwd[i] if q in bwd[i]] for i in range(n)]
        if all(feasible):  # a avaliação respeita a ordem
            for i, f in enumerate(feasible):
                if len(cands[i]) > 1 and len(f) == 1:
                    out[i] = f[0]
                    issues[(day, "resolved_by_order", f"{answer_type}|{items[i][0]}"[:160])] += 1
    for (text, _), c, q in zip(items, cands, out):
        if not c:
            issues[(day, "unmapped_question", f"{answer_type}|{text}"[:160])] += 1
        elif q is None:
            issues[(day, "ambiguous_question", f"{answer_type}|{text}"[:160])] += 1
    return out


def normalize_evaluation(
    raw: Dict[str, Any], qn: Questionnaire, issues: Counter
) -> Tuple[Tuple, List[Tuple], List[Tuple]]:
    """Devolve (linha de evaluations, linhas de answers, linhas de answer_tags).

    `issues` acumula (dia, código, detalhe) → contagem.
    web_access_info é ignorado de propósito (IP, fingerprint e identificador do respondente).
    """
    survey_id = qn.survey_id
    started = local_started_at(raw["started_at"])
    day = started.date().isoformat()
    ref = eval_ref(started, raw["id"])
    origin = raw.get("origin")
    channel = "device" if origin == "Totem" else "web" if origin == "Web" else ("device" if raw.get("device_id") else "web")
    unit = raw.get("surveyed_unit") or {}
    has_dq = "reliable" in raw
    reliable = raw.get("reliable")
    evaluation = (
        survey_id,
        ref,
        day,
        started.strftime("%Y-%m-%d %H:%M:%S"),
        unit.get("id"),
        unit.get("name"),
        channel,
        1 if raw.get("completed") else 0,
        None if reliable is None else (1 if reliable else 0),
        1 if has_dq else 0,
        raw.get("duration"),
    )

    answers: List[Tuple] = []
    for group in raw.get("formatted_answers") or []:
        answer_type = group.get("answer_type") or ""
        items = list(_items(answer_type, group.get("answers")))
        qids = resolve_group(qn, answer_type, items, issues, day)
        for (qtext, item), qid in zip(items, qids):
            qgroup = f"{answer_type}|{qtext}"
            question = qn.by_id.get(qid) if qid else None
            lgpd = bool(question and question.lgpd_protected)

            if answer_type == "NPS":
                score = item.get("answer_value")
                score = score if isinstance(score, int) and not isinstance(score, bool) else None
                valid = score is not None and 0 <= score <= 10
                answers.append((survey_id, ref, day, qid, qgroup, K_NPS, None, score, 1 if valid else 0, None))

            elif answer_type in ("Scale", "Multiple Choice", "Multiple Response"):
                kind = K_MULTI if answer_type == "Multiple Response" else K_CHOICE
                ctext = item.get("choice_text")
                cid = qn.resolve_choice(qid, ctext, item.get("choice_value")) if qid else None
                if qid and cid is None and not (kind == K_MULTI and ctext is None):
                    # alternativa que não está no questionário atual: as telas também a ignoram
                    issues[(day, "answer_without_current_choice", str(qid))] += 1
                extra = None if lgpd else _clean_text(item.get("additional_field_answer"))
                answered = 1 if cid is not None or (kind == K_MULTI and ctext is None) else 0
                answers.append(
                    (survey_id, ref, day, qid, qgroup, kind, cid, None, answered, mask_pii(extra) if extra else None)
                )

            elif answer_type in ("Text", "Short Text"):
                text = _clean_text(item.get("choice_value"))
                stored = None if (lgpd or text is None) else mask_pii(text)
                answers.append((survey_id, ref, day, qid, qgroup, K_OPEN, None, None, 1 if text else 0, stored))

            else:  # Numeric, Email, Phone, Date, CPF, CNPJ: só a presença
                text = _clean_text(item.get("choice_text"))
                if answer_type not in PERSONAL_TYPES:
                    issues[(day, "unknown_answer_type", answer_type[:40])] += 1
                answers.append((survey_id, ref, day, qid, qgroup, K_OTHER, None, None, 1 if text else 0, None))

    tags: List[Tuple] = []
    for entry in raw.get("tags") or []:
        qid = entry.get("question_id")
        for tag in entry.get("tags") or []:
            if tag.get("id") is not None:
                tags.append((survey_id, ref, day, qid, int(tag["id"]), tag.get("name")))

    return evaluation, answers, tags
