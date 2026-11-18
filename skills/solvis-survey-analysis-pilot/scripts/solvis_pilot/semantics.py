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
        """[mín, máx] dos valores; ×100 em soma ponderada (question.rb:298-304)."""
        values = [c.value for c in self.choices if c.value is not None]
        if not values:
            return None, None
        lo, hi = min(values), max(values)
        if self.metric_kind == "weighted_sum":
            return lo * 100, hi * 100
        return lo, hi

    def decimal_places(self) -> int:
        """Casas da média pela amplitude da escala (question.rb:323-335)."""
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

    def summary(self) -> Dict[str, Any]:
        return {
            "survey": {
                "id": self.survey_id,
                "name": self.survey_name,
                "archived": self.archived,
                "last_evaluation_date": self.last_evaluation_date,
                "questionnaire_edited_after_lock": self.edited_after_lock(),
            },
            "questions": [q.summary(ambiguous=q.id in self.ambiguous_ids) for q in self.questions],
            "notes": [
                "Textos e valores são os do cadastro atual e valem para todo o histórico.",
            ]
            + (
                [
                    "Perguntas com mapping=ambiguous_text têm o mesmo tipo e texto de outra pergunta. A API devolve as "
                    "respostas só com o texto; o motor atribui pela ordem das respostas quando só há uma possibilidade "
                    "e só calcula a métrica se todas as respostas do período foram atribuídas."
                ]
                if self.ambiguous_ids
                else []
            ),
        }
