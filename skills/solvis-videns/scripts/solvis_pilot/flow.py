"""Quem viu cada pergunta: inferido do questionário e das respostas guardadas.

A API pública não diz quais perguntas foram exibidas. O motor refaz o caminho de cada avaliação com a
mesma lógica do navegador da pesquisa:

1. começa na pergunta de posição 0;
2. uma pergunta com regras de entrada só aparece se alguma regra vale (todas as condições da regra, contra as
   respostas já dadas); se nenhuma vale, é pulada e segue-se pela ramificação dela sem resposta;
3. depois de uma pergunta, vale a ramificação de maior prioridade que casa com a resposta (alternativa,
   grupo NPS, pulou/respondeu); sem casamento, segue para a próxima posição; -1 ou posição inexistente é o fim.

Limites (declarados ao usuário no envelope): perguntas escondidas por variação de pesquisa não saem na API;
a posição inicial é suposta 0; em avaliação incompleta o caminho vai só até a última pergunta com resposta
gravada; respostas de perguntas de texto repetido sem dono podem tornar o caminho incerto.
"""

from __future__ import annotations

import sqlite3
from itertools import groupby
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple

from .semantics import EntryRule, Question, Questionnaire

Answer = Tuple[Optional[int], Optional[int], int]  # (choice_id, score, answered)

_CUSTOMER_TYPES = (("promoters", 9, 10), ("passives", 7, 8), ("detractors", 0, 6))


def _customer_type(score: int) -> Optional[str]:
    return next((name for name, lo, hi in _CUSTOMER_TYPES if lo <= score <= hi), None)


def conditions_match(answers: Sequence[Answer], cond: Dict[str, Any]) -> bool:
    """Equivale a WebSurveys::BranchingRules::ConditionsMatcher.matches?."""
    if not cond:
        return True
    for choice_id, score, answered in answers:
        if choice_id is not None and cond.get("choice_id") is not None and int(cond["choice_id"]) == choice_id:
            return True
        if score is not None and answered and cond.get("customer_type") == _customer_type(score):
            return True
        if not answered:
            if cond.get("skipped") is True:
                return True
        elif cond.get("skipped") is False:
            return True
    return False


def _entry_matches(rule: EntryRule, recs: Dict[int, List[Answer]]) -> bool:
    return all(conditions_match(recs.get(qid, []), cond) for qid, cond in rule.terms.items()) if rule.terms else True


def _next_position(q: Question, recs: Dict[int, List[Answer]]) -> int:
    answers = recs.get(q.id, [])
    if q.answer_type != "Multiple Response":
        answers = answers[-1:]
    rules = sorted(q.branching_rules, key=lambda r: r.priority)[::-1]  # maior prioridade primeiro
    if not answers:  # pergunta sem resposta: só a ramificação incondicional vale
        rule = next((r for r in rules if r.is_default), None)
    else:
        rule = next((r for r in rules
                     if conditions_match(answers, {"choice_id": r.choice_id} if r.choice_id else r.conditions)), None)
    return rule.next_position if rule else q.position + 1


def path(qn: Questionnaire, recs: Dict[int, List[Answer]], completed: bool) -> List[int]:
    """Ids das perguntas exibidas, em ordem."""
    by_pos = {q.position: q for q in qn.questions}
    shown: List[Question] = []
    seen: Set[int] = set()
    current: Optional[Question] = None
    pos = 0
    while True:
        pos = 0 if current is None else _next_position(current, recs)
        nxt = by_pos.get(pos)
        if nxt is None or nxt.id in seen:  # fim da pesquisa (ou ciclo)
            break
        seen.add(nxt.id)
        current = nxt
        if nxt.entry_rules and not any(_entry_matches(r, recs) for r in nxt.entry_rules):
            continue
        shown.append(nxt)
    if not completed:  # abandonou em algum ponto: só vale até a última pergunta com resposta gravada
        last = max((i for i, q in enumerate(shown) if q.id in recs), default=-1)
        shown = shown[: last + 1]
    return [q.id for q in shown]


def _source_groups(qn: Questionnaire) -> Set[str]:
    """Textos (tipo|texto) de perguntas cuja resposta decide o caminho."""
    ids = {q.id for q in qn.questions if q.branching_rules}
    ids |= {qid for q in qn.questions for r in q.entry_rules for qid in r.terms}
    return {f"{q.answer_type}|{q.text}" for q in qn.questions if q.id in ids and q.id in qn.ambiguous_ids}


def reached_evaluations(db: sqlite3.Connection, qn: Questionnaire, survey_id: int, start: str, end: str,
                        target_id: int) -> Dict[str, bool]:
    """{eval_ref: incerta} das avaliações do período em que a pergunta foi exibida."""
    completed = {r[0]: bool(r[1]) for r in db.execute(
        "SELECT eval_ref, completed FROM evaluations WHERE survey_id = ? AND day BETWEEN ? AND ?",
        (survey_id, start, end))}
    rows = db.execute(
        "SELECT eval_ref, question_id, choice_id, score, answered, qgroup FROM answers "
        "WHERE survey_id = ? AND day BETWEEN ? AND ? ORDER BY eval_ref", (survey_id, start, end))
    sources = _source_groups(qn)
    recs_by_eval: Dict[str, Tuple[Dict[int, List[Answer]], bool]] = {}
    for ref, group in groupby(rows, key=lambda r: r[0]):
        recs: Dict[int, List[Answer]] = {}
        uncertain = False
        for _, qid, cid, score, answered, qgroup in group:
            if qid is None:
                uncertain = uncertain or qgroup in sources
            else:
                recs.setdefault(qid, []).append((cid, score, answered))
        recs_by_eval[ref] = (recs, uncertain)
    out: Dict[str, bool] = {}
    for ref, done in completed.items():
        recs, uncertain = recs_by_eval.get(ref, ({}, False))
        if target_id in path(qn, recs, done):
            out[ref] = uncertain
    return out
