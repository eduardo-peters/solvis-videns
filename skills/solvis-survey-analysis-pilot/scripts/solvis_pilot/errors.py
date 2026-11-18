"""Erros do motor, sempre com código estável que a skill sabe tratar."""

from __future__ import annotations

from typing import Any, Dict, Optional

# Códigos de saída do processo
EXIT_USAGE = 2      # pedido inválido, id fora do escopo, métrica inaplicável
EXIT_API = 3        # credencial, rede ou erro da API
EXIT_SYNC = 4       # extração não terminou dentro do orçamento de tempo


class EngineError(Exception):
    def __init__(
        self,
        code: str,
        message: str,
        hint: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None,
        exit_code: int = EXIT_USAGE,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.hint = hint
        self.details = details or {}
        self.exit_code = exit_code

    def to_dict(self) -> Dict[str, Any]:
        body: Dict[str, Any] = {"code": self.code, "message": self.message}
        if self.hint:
            body["hint"] = self.hint
        if self.details:
            body["details"] = self.details
        return {"error": body}
