"""Tool `quality_status`. Avaliações recentes e atuação dos guardrails."""

import json  # noqa: F401
import re  # noqa: F401

from .. import ROOT, tool  # noqa: F401
from ..core.db import q  # noqa: F401
from ..core.errors import ToolError  # noqa: F401
from ..core.resolve import _fold  # noqa: F401
from ..core.skill import SKILL, _invariants, _metric_block, _metric_ids, _question_types  # noqa: F401


@tool("quality_status", agents=["data_engineer"], access="engineer",
      description="Estado da qualidade do agente: últimas avaliações (acerto, tempo, versão do código, portão) e "
                  "quantas vezes cada guardrail atuou.",
      params={"limit": ("integer", "Quantas avaliações recentes (padrão 5)")},
      reads=["ops.eval_runs", "ops.guardrail_events (guardrail e ação)"], skill=["docs/data-ops.md"],
      example={"limit": 3})
def quality_status(args):
    lim = min(int(args.get("limit") or 5), 50)
    runs = q("SELECT ts, run_id, model, context_on, cases, passed, round(pass_rate, 3) pass_rate, "
             "round(mean_secs, 1) mean_secs, code_hash, gate FROM ops.eval_runs ORDER BY ts DESC LIMIT {l:UInt8}",
             {"l": lim})
    guards = q("SELECT guardrail, action, count() n FROM ops.guardrail_events GROUP BY guardrail, action ORDER BY n DESC")
    return {"eval_runs": runs, "guardrail_events": guards,
            "note": "Rodar de novo: python3 ops/pipeline.py --eval. Candidatos de uso real: --review."}
