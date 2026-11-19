"""Tool `skill_lookup`. Busca vetorial nas regras da skill."""

import json  # noqa: F401
import re  # noqa: F401

from .. import ROOT, tool  # noqa: F401
from ..core.db import q  # noqa: F401
from ..core.errors import ToolError  # noqa: F401
from ..core.resolve import _fold  # noqa: F401
from ..core.skill import SKILL, _invariants, _metric_block, _metric_ids, _question_types  # noqa: F401


@tool("skill_lookup", agents=["data_engineer", "analyst"], access="engineer",
      description="Busca vetorial nas regras da skill (SKILL.md, invariantes, playbooks, glossário, limitações, "
                  "formato de resposta, tipos de pergunta). Devolve os trechos mais próximos com a fonte.",
      params={"query": ("string", "Assunto ou pergunta (ex.: 'como tratar amostra pequena em ranking')"),
              "k": ("integer", "Quantos trechos (padrão 3, máximo 8)")},
      required=["query"], reads=["semantic.skill_chunks", "Ollama nomic-embed-text"],
      skill=["toda a skill do piloto"], example={"query": "NPS geral de várias lojas", "k": 3})
def skill_lookup(args):
    from ..core import skill_index as context
    k = max(1, min(int(args.get("k") or 3), 8))
    rows = context.retrieve(args["query"], lambda sql, p=None: q(sql, p), k=k, budget=10_000)
    return {"chunks": [{"source": r["source"], "heading": r["heading"], "distance": round(float(r["d"]), 3),
                        "text": r["text"]} for r in rows]}
