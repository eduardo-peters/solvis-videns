"""Proteção de dados pessoais aplicada na ingestão.

- web_access_info (IP, fingerprint, identificador do respondente) é descartado.
- Respostas de perguntas lgpd_protected e dos tipos pessoais nunca têm o texto
  guardado; só a presença da resposta, para contagem.
- Comentários são mascarados antes de ir para o cache: e-mail, CPF, CNPJ,
  telefone e sequências longas de dígitos. Nomes próprios NÃO são mascarados
  (risco residual documentado).
"""

from __future__ import annotations

import re

# Tipos cujo conteúdo é dado pessoal ou valor livre sem agregação: nunca guardar o texto.
PERSONAL_TYPES = {"Email", "Phone", "CPF", "CNPJ", "Date", "Numeric"}

_EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
_CNPJ = re.compile(r"(?<!\d)\d{2}\.?\d{3}\.?\d{3}/?\d{4}-?\d{2}(?!\d)")
_CPF = re.compile(r"(?<!\d)\d{3}\.?\d{3}\.?\d{3}-?\d{2}(?!\d)")
_PHONE = re.compile(
    r"(?<!\d)(?:\+?55[\s.-]?)?(?:\(?\d{2}\)?[\s.-]?)?9?\d{4}[\s.-]?\d{4}(?!\d)"
)
_LONG_DIGITS = re.compile(r"\d{8,}")
_YEAR_PAIR = re.compile(r"^(19|20)\d{2}\D(19|20)\d{2}$")


def _phone(match: "re.Match[str]") -> str:
    text = match.group(0)
    if _YEAR_PAIR.match(text.strip()):  # "2024-2025" é intervalo de anos, não telefone
        return text
    return "[telefone]"


def mask_pii(text: str) -> str:
    text = _EMAIL.sub("[email]", text)
    text = _CNPJ.sub("[cnpj]", text)
    text = _CPF.sub("[cpf]", text)
    text = _PHONE.sub(_phone, text)
    text = _LONG_DIGITS.sub("[número]", text)
    return text
