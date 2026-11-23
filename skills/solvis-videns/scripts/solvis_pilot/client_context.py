"""Contexto do cliente: quem é, para que servem as pesquisas e o que mais ajuda a analisar os dados.

É um texto em Markdown escrito pela skill a partir do que o usuário contou no primeiro uso (e atualizado
depois). O motor só guarda e devolve; nada aqui muda cálculo, filtro ou regra. Fica em `.solvis-videns/`
na pasta de trabalho (a mesma do `.env` e da marca): um cliente por pasta.
"""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path
from typing import Any, Dict

from .config import data_dir, ensure_data_dir, _private_dir
from .errors import EngineError
from .store import now_utc

CONTEXT_NAME = "context.md"
NONE_MARK = "<!-- solvis: o usuário preferiu não descrever o cliente -->"
MAX_BYTES = 256 * 1024
# o que a skill deve tentar cobrir ao perguntar; títulos sugeridos para o Markdown
SUGGESTED_SECTIONS = (
    "Quem é o cliente (setor, porte, o que vende, para quem)",
    "Finalidade das pesquisas (o que cada pesquisa mede e em que momento é aplicada)",
    "Como a operação se organiza (unidades, regionais, bandeiras, canais)",
    "Metas e referências internas (NPS alvo, indicador principal, o que é 'bom' para eles)",
    "Calendário e sazonalidade (campanhas, datas fortes, mudanças recentes que afetam os números)",
    "Vocabulário e mapeamentos (como chamam as coisas; qual pergunta é o CSAT deles)",
    "Quem lê as análises e para quê (diretoria, gerentes de loja, franqueados)",
)


def context_dir() -> Path:
    custom = os.environ.get("SOLVIS_CONTEXT_DIR")
    return Path(custom) if custom else data_dir()


def context_path() -> Path:
    return context_dir() / CONTEXT_NAME


def _read() -> str:
    try:
        return context_path().read_text(encoding="utf-8")
    except OSError:
        return ""


def status() -> Dict[str, Any]:
    """`configured` (há descrição), `none` (o usuário preferiu não descrever), `not_asked`."""
    text = _read()
    if not text.strip():
        st = "not_asked"
    elif text.strip() == NONE_MARK:
        st = "none"
    else:
        st = "configured"
    return {"status": st, "file": str(context_path())}


def _write(text: str) -> None:
    if context_dir() == data_dir():
        ensure_data_dir()
    else:
        _private_dir(context_dir())
    context_path().write_text(text.rstrip("\n") + "\n", encoding="utf-8")


def cmd_context(args, _ctx) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    if args.clear:
        path = context_path()
        if path.exists():
            path.unlink()
        out["cleared"] = True
    if args.none:
        _write(NONE_MARK)
        out["saved"] = True
    if args.file:
        text = sys.stdin.read() if args.file == "-" else Path(args.file).read_text(encoding="utf-8")
        if len(text.encode("utf-8")) > MAX_BYTES:
            raise EngineError("invalid_argument", "Contexto do cliente acima de 256 KB.")
        if not text.strip():
            raise EngineError("invalid_argument", "Contexto vazio. Para registrar que o usuário não quis descrever, use --none.")
        if args.append and status()["status"] == "configured":
            text = _read().rstrip("\n") + "\n\n" + text.strip()
        stamp = f"<!-- solvis: atualizado em {now_utc()} -->"
        lines = [ln for ln in text.strip().splitlines() if not ln.startswith("<!-- solvis: atualizado em")]
        _write("\n".join(lines) + "\n\n" + stamp)
        out["saved"] = True
    out.update(status())
    out["context"] = _read() if out["status"] == "configured" else None
    out["suggested_sections"] = list(SUGGESTED_SECTIONS)
    return out
