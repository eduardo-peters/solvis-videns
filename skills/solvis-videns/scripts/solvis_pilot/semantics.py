"""Questionário atual de uma pesquisa, lido de GET /api/v1/surveys/:id.

É a base da camada semântica: diz o tipo de cada pergunta, o valor de cada
alternativa e como as respostas da API (que vêm só com textos) voltam a ser
ids. Tudo é lido do cadastro ATUAL, como nas telas de resultados.
"""

from __future__ import annotations

import html
import json
import re
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from typing import Any, Dict, List, Optional, Tuple

ANSWER_TYPES = (
    "NPS", "Scale", "Multiple Choice", "Multiple Response", "Text", "Short Text",
    "Numeric", "Email", "Phone", "Date", "CPF", "CNPJ",
)
CHOICE_TYPES = ("Scale", "Multiple Choice")
OPEN_TEXT_TYPES = ("Text", "Short Text")
# métrica principal de cada tipo (Scale com metric_kind = weighted_sum usa weighted_sum)
RECOMMENDED_METRIC = {
    "NPS": "nps", "Scale": "scale_mean", "Multiple Choice": "choice_share",
    "Multiple Response": "multi_response_share", "Text": "tag_mentions", "Short Text": "response_count",
}

_TAG = re.compile(r"<[^>]+>")
_BR = re.compile(r"<br\s*/?>", re.IGNORECASE)
_LETTERS = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ"


def plain_text(raw: Optional[str]) -> str:
    """Texto para exibição: sem <br> e sem HTML."""
    if not raw:
        return ""
    text = _BR.sub(" ", raw)
    text = _TAG.sub("", text)
    return re.sub(r"\s+", " ", html.unescape(text)).strip()


def _options(raw: Any) -> Dict[str, Any]:
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str) and raw.strip():
        try:
            parsed = json.loads(raw)
            return parsed if isinstance(parsed, dict) else {}
        except ValueError:
            return {}
    return {}


def _decimal(raw: Any) -> Optional[Decimal]:
    if raw is None or raw == "":
        return None
    try:
        return Decimal(str(raw).replace(",", "."))
    except InvalidOperation:
        return None


def _conditions(raw: Any) -> Dict[str, Any]:
    """Condições de uma regra: hash (ou JSON em texto) → dict; qualquer outra coisa → vazio."""
    if isinstance(raw, str) and raw.strip():
        try:
            raw = json.loads(raw)
        except ValueError:
            return {}
    return raw if isinstance(raw, dict) else {}


def _int_or_none(raw: Any) -> Optional[int]:
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None


@dataclass
class BranchingRule:
    """Regra de ramificação de uma pergunta: ao responder como `conditions`, segue para `next_position` (-1 = fim)."""
    choice_id: Optional[int]
    conditions: Dict[str, Any]
    next_position: int
    priority: int

    @property
    def is_default(self) -> bool:
        return self.choice_id is None and not self.conditions


@dataclass
class EntryRule:
    """Regra de entrada: a pergunta só aparece se TODOS os termos valem (pergunta → condição).
    Com mais de uma regra, basta uma valer."""
    terms: Dict[int, Dict[str, Any]]


@dataclass
class Choice:
    id: int
    position: int
    text: str
    value: Optional[Decimal]
    has_additional_field: bool

    @property
    def letter(self) -> str:
        return _LETTERS[self.position % 52]

    @property
    def label(self) -> str:
        return plain_text(self.text)


@dataclass
class Question:
    id: int
    position: int
    text: str
    answer_type: str
    options: Dict[str, Any]
    choices: List[Choice] = field(default_factory=list)
    branching_rules: List[BranchingRule] = field(default_factory=list)
    entry_rules: List[EntryRule] = field(default_factory=list)

    @property
    def number(self) -> int:
        return self.position + 1

    @property
    def label(self) -> str:
        return plain_text(self.text)

    @property
    def metric_kind(self) -> Optional[str]:
        kind = self.options.get("metric_kind")
        return str(kind) if kind else None

    @property
    def lgpd_protected(self) -> bool:
        return bool(self.options.get("lgpd_protected"))

    @property
    def reference_zone(self) -> Optional[str]:
        """None = zonas padrão; 'none' = sem zona; 'with_enchantment'."""
        zone = self.options.get("reference_zone")
        return str(zone) if zone else None

    @property
    def valued_choices(self) -> List[Choice]:
        return [c for c in self.choices if c.value is not None]

    def value_range(self) -> Tuple[Optional[Decimal], Optional[Decimal]]:
        """[mín, máx] dos valores; ×100 em soma ponderada."""
        values = [c.value for c in self.choices if c.value is not None]
        if not values:
            return None, None
        lo, hi = min(values), max(values)
        if self.metric_kind == "weighted_sum":
            return lo * 100, hi * 100
        return lo, hi

    def decimal_places(self) -> int:
        """Casas da média pela amplitude da escala."""
        lo, hi = self.value_range()
        if lo is None and hi is None:
            return 0
        amplitude = (hi or 0) - (lo or 0)
        if amplitude < 10:
            return 2
        if amplitude < 100:
            return 1
        return 0

    def is_percentual_scale(self) -> bool:
        lo, hi = self.value_range()
        return lo is not None and lo == 0 and hi == 100

    def summary(self, ambiguous: bool = False) -> Dict[str, Any]:
        body: Dict[str, Any] = {
            "id": self.id,
            "number": self.number,
            "text": self.label,
            "answer_type": self.answer_type,
            "metric": RECOMMENDED_METRIC.get(self.answer_type, "response_count")
            if not (self.answer_type == "Scale" and self.metric_kind == "weighted_sum") else "weighted_sum",
        }
        if self.metric_kind:
            body["metric_kind"] = self.metric_kind
        if self.lgpd_protected:
            body["lgpd_protected"] = True
        if self.answer_type == "Scale":
            lo, hi = self.value_range()
            raw = [c.value for c in self.valued_choices]
            body["scale_min"] = _num(min(raw)) if raw else None
            body["scale_max"] = _num(max(raw)) if raw else None
            if self.metric_kind == "weighted_sum":
                body["weighted_sum_range"] = [_num(lo), _num(hi)]
        if self.answer_type == "NPS":
            body["reference_zone"] = self.reference_zone or "default"
        if self.choices:
            body["choices"] = [
                {
                    "id": c.id,
                    "letter": c.letter,
                    "text": c.label,
                    **({"value": _num(c.value)} if c.value is not None else {}),
                    **({"is_valueless": True} if self.answer_type == "Scale" and c.value is None else {}),
                    **({"has_additional_field": True} if c.has_additional_field else {}),
                }
                for c in self.choices
            ]
        if ambiguous:
            body["mapping"] = "ambiguous_text"
        return body


def _num(value: Optional[Decimal]) -> Any:
    if value is None:
        return None
    return int(value) if value == value.to_integral_value() else float(value)


@dataclass
class Questionnaire:
    survey_id: int
    survey_name: str
    archived: bool
    survey_version: Optional[int]
    questionnaire_version: Optional[int]
    last_evaluation_date: Optional[str]
    evaluation_count_cache: Optional[int]
    questions: List[Question]

    def __post_init__(self) -> None:
        self.by_id: Dict[int, Question] = {q.id: q for q in self.questions}
        # A API devolve respostas sem question_id: só tipo + texto da pergunta.
        self.by_key: Dict[Tuple[str, str], List[int]] = {}
        for q in self.questions:
            self.by_key.setdefault((q.answer_type, q.text), []).append(q.id)
        self.ambiguous_ids = {qid for ids in self.by_key.values() if len(ids) > 1 for qid in ids}

    @classmethod
    def from_api(cls, survey: Dict[str, Any]) -> "Questionnaire":
        qn = survey.get("questionnaire") or {}
        questions: List[Question] = []
        for rq in qn.get("questions") or []:
            choices = [
                Choice(
                    id=int(rc["id"]),
                    position=int(rc.get("position_in_question") or 0),
                    text=rc.get("text") or "",
                    value=_decimal(rc.get("value")),
                    has_additional_field=bool(_options(rc.get("options")).get("additional_field")),
                )
                for rc in rq.get("choices") or []
            ]
            choices.sort(key=lambda c: c.position)
            questions.append(
                Question(
                    id=int(rq["id"]),
                    position=int(rq.get("position_in_survey") or 0),
                    text=rq.get("text") or "",
                    answer_type=rq.get("answer_type") or "",
                    options=_options(rq.get("options")),
                    choices=choices,
                    branching_rules=[
                        BranchingRule(
                            choice_id=_int_or_none(br.get("choice_id")),
                            conditions=_conditions(br.get("conditions")),
                            next_position=_int_or_none(br.get("next_question_position")),
                            priority=_int_or_none(br.get("priority_level")) or 0,
                        )
                        for br in rq.get("branching_rules") or []
                        if _int_or_none(br.get("next_question_position")) is not None
                    ],
                    entry_rules=[
                        EntryRule({int(k): _conditions(v) for k, v in _conditions(er.get("conditions")).items()
                                   if _int_or_none(k) is not None})
                        for er in rq.get("entry_rules") or []
                    ],
                )
            )
        questions.sort(key=lambda q: q.position)
        return cls(
            survey_id=int(survey["id"]),
            survey_name=survey.get("name") or "",
            archived=bool(survey.get("archived")),
            survey_version=survey.get("version"),
            questionnaire_version=qn.get("version"),
            last_evaluation_date=survey.get("last_evaluation_date_cache"),
            evaluation_count_cache=survey.get("evaluation_count_cache"),
            questions=questions,
        )

    def resolve_choice(self, question_id: int, text: Optional[str], value: Any = None) -> Optional[int]:
        if text is None:
            return None
        q = self.by_id[question_id]
        matches = [c for c in q.choices if c.text == text]
        if len(matches) > 1 and value is not None:
            v = _decimal(value)
            matches = [c for c in matches if c.value == v] or matches
        return matches[0].id if matches else None

    def edited_after_lock(self) -> bool:
        """questionnaires.version > 1: perguntas ou alternativas editadas com a pesquisa travada."""
        return bool(self.questionnaire_version and int(self.questionnaire_version) > 1)

    def nps_questions(self) -> List[Question]:
        return [q for q in self.questions if q.answer_type == "NPS"]

    # ------------------------------------------------------------ fluxo da pesquisa
    def _number_of(self, position: int) -> Any:
        """Número da pergunta que está na posição, ou 'fim' (posição -1 ou sem pergunta)."""
        target = next((q for q in self.questions if q.position == position), None)
        return target.number if target else "fim"

    def describe_condition(self, source: Question, cond: Dict[str, Any], choice_id: Optional[int] = None) -> str:
        """Condição sobre a resposta de `source`, em português (ex.: escolheu "Sim")."""
        parts: List[str] = []
        cid = choice_id if choice_id is not None else _int_or_none(cond.get("choice_id"))
        if cid is not None:
            choice = next((c for c in source.choices if c.id == cid), None)
            verb = "marcou" if source.answer_type == "Multiple Response" else "escolheu"
            parts.append(f'{verb} "{choice.label}"' if choice else f"{verb} uma alternativa que já não existe")
        if cond.get("customer_type"):
            parts.append({"promoters": "deu nota de promotor (9 e 10)", "passives": "deu nota de neutro (7 e 8)",
                          "detractors": "deu nota de detrator (0 a 6)"}.get(str(cond["customer_type"]), "deu nota de um grupo NPS"))
        if cond.get("skipped") is True:
            parts.append("pulou a pergunta")
        elif cond.get("skipped") is False:
            parts.append("respondeu a pergunta")
        if cond.get("full_match_regexp"):
            parts.append("respondeu um texto que casa com a expressão")
        return " ou ".join(parts) or "condição não identificada"

    def describe_entry_rule(self, rule: EntryRule) -> Dict[str, Any]:
        texts: List[str] = []
        for qid, cond in rule.terms.items():
            src = self.by_id.get(qid)
            texts.append(f"na pergunta {src.number} {self.describe_condition(src, cond)}" if src
                         else "em uma pergunta que já não existe")
        return {
            "requires": " e ".join(texts) or "condição não identificada",
            "depends_on_questions": sorted(self.by_id[k].number for k in rule.terms if k in self.by_id),
        }

    def bypassed_by(self, q: Question) -> List[Dict[str, Any]]:
        """Regras de perguntas anteriores que pulam `q` (o destino fica depois dela, ou é o fim)."""
        out: List[Dict[str, Any]] = []
        for p in self.questions:
            if p.position >= q.position:
                continue
            for br in p.branching_rules:
                if self._number_of(br.next_position) == "fim" or br.next_position > q.position:
                    out.append({
                        "question": p.number,
                        "when": "sempre" if br.is_default else self.describe_condition(p, br.conditions, br.choice_id),
                        "goes_to": self._number_of(br.next_position),
                    })
        return out

    def flow(self, q: Question) -> Optional[Dict[str, Any]]:
        """Quem pode ver a pergunta. None = não há regra que restrinja (todos que chegam a ela)."""
        entry = [self.describe_entry_rule(r) for r in q.entry_rules]
        bypass = self.bypassed_by(q)
        if not entry and not bypass:
            return None
        body: Dict[str, Any] = {}
        if entry:
            body["entry_rules"] = entry  # com mais de uma regra, basta uma valer
        if bypass:
            body["skipped_by_branching"] = bypass
        return body

    def flow_summary(self, q: Question) -> Dict[str, Any]:
        """`flow` + as ramificações que saem da pergunta."""
        body = self.flow(q) or {}
        if q.branching_rules:
            body["branches"] = [
                {"when": "sempre" if br.is_default else self.describe_condition(q, br.conditions, br.choice_id),
                 "goes_to": self._number_of(br.next_position)}
                for br in q.branching_rules
            ]
        return body

    def summary(self) -> Dict[str, Any]:
        has_flow = any(q.entry_rules or q.branching_rules for q in self.questions)
        questions = []
        for q in self.questions:
            body = q.summary(ambiguous=q.id in self.ambiguous_ids)
            flow = self.flow_summary(q)
            if flow:
                body["flow"] = flow
                if "entry_rules" in flow or "skipped_by_branching" in flow:
                    body["shown_to"] = "conditional"
            questions.append(body)
        return {
            "survey": {
                "id": self.survey_id,
                "name": self.survey_name,
                "archived": self.archived,
                "last_evaluation_date": self.last_evaluation_date,
                "questionnaire_edited_after_lock": self.edited_after_lock(),
            },
            "questions": questions,
            "notes": [
                "Textos e valores são os do cadastro atual e valem para todo o histórico.",
            ]
            + (
                [
                    "Perguntas com shown_to=conditional não aparecem para todas as avaliações: têm regra de entrada "
                    "(`entry_rules`: basta uma valer; dentro de uma regra, todas as condições) ou podem ser puladas por "
                    "uma ramificação de pergunta anterior (`skipped_by_branching`). A base de cada uma é quem a viu, "
                    "não o total de avaliações. A API pública não diz quem viu cada pergunta."
                ]
                if has_flow and any("shown_to" in x for x in questions)
                else []
            )
            + (
                [
                    "Perguntas com mapping=ambiguous_text têm o mesmo tipo e texto de outra pergunta. A API devolve as "
                    "respostas só com o texto; o motor atribui pela ordem das respostas quando só há uma possibilidade "
                    "e só calcula a métrica se todas as respostas do período foram atribuídas. Perguntas de mesmo "
                    "texto não são redundantes: podem aparecer para públicos diferentes (veja `flow`)."
                ]
                if self.ambiguous_ids
                else []
            ),
        }
