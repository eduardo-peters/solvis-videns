"""Tool `choice_share`. Distribuição das alternativas, com N/A no denominador."""

from ..core.errors import ToolError  # noqa: F401
from ..core.db import ch  # noqa: F401
from ..core.periods import resolve_dates  # noqa: F401
from ..core.resolve import (BASE, _fold, _question_scope, _round_nps, coverage, resolve_group_by,  # noqa: F401
                            resolve_question, resolve_survey)
from .. import tool
from ._params import PERIOD, QUESTION, SURVEY  # noqa: F401


@tool("choice_share", agents=["analyst"], access="client",
      description="Distribuição (%) das alternativas de uma pergunta de escala ou escolha única. "
                  "'Não se aplica' entra no denominador.",
      params={**SURVEY, **QUESTION, **PERIOD}, required=["survey", "question"],
      reads=["semantic.choice_share"], skill=["metrics.yaml#choice_share", "playbooks.md#7"],
      example={"survey": "Satisfação", "question": "Atendimento", "period": "yesterday"},
      model_hint=('Distribuição (%) das alternativas de uma pergunta de escala ou escolha. survey = nome; question '
                  '= texto ou número da pergunta.'))
def choice_share(args):
    p, scope = _question_scope("choice_share", args)
    rows = ch(f"SELECT letter, text, answers, share_pct, n FROM semantic.choice_share({BASE}) ORDER BY letter", p)
    return {**scope, "rows": rows} if rows else {**scope, "rows": [], "note": "sem avaliações no período"}
