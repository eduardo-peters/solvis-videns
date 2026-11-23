"""Proteção de dados pessoais aplicada na ingestão.

- web_access_info (IP, fingerprint, identificador do respondente) é descartado.
- Respostas dos tipos pessoais (e-mail, telefone, CPF, CNPJ, data, numérico) nunca têm o
  texto guardado; só a presença da resposta, para contagem.
- Respostas de texto de perguntas lgpd_protected: a decisão é do usuário e é perguntada no
  primeiro uso (`setup`/`config --lgpd-text on|off`, guardada em `meta`). Enquanto ele não
  decidir, o texto não é guardado (padrão seguro) e `lgpd_text_decided` fica falso para a skill
  perguntar. Autorizado, o texto passa pelo mesmo mascaramento dos comentários.
- Comentários são mascarados antes de ir para o cache: e-mail, CPF, CNPJ,
  telefone e sequências longas de dígitos. Nomes próprios não são mascarados.
"""

from __future__ import annotations

import re
from typing import Any, Dict

from .store import now_utc

LGPD_TEXT_KEY = "lgpd_text"
LGPD_CONSENT_KEY = "lgpd_text_consent_at"


def lgpd_text_enabled(store) -> bool:
    return store.get_meta(LGPD_TEXT_KEY) == "1"


def lgpd_text_decided(store) -> bool:
    """O usuário já foi perguntado e respondeu (sim ou não)? Sem resposta, a skill deve perguntar."""
    return store.get_meta(LGPD_TEXT_KEY) in ("0", "1")


LGPD_ASK_STEP = ("Pergunte ao usuário se autoriza guardar, mascarado e só no computador dele, o texto das perguntas "
                 "protegidas por LGPD (sem isso, essas perguntas só rendem contagens) e rode "
                 "`setup --lgpd-text on|off` (ou `config --lgpd-text on|off`) com a resposta.")


def lgpd_info(store) -> Dict[str, Any]:
    on = lgpd_text_enabled(store)
    return {"lgpd_text": on, "lgpd_text_decided": lgpd_text_decided(store),
            "lgpd_text_consent_at": store.get_meta(LGPD_CONSENT_KEY) if on else None}


def set_lgpd_text(store, choice: str) -> Dict[str, Any]:
    """Registra a decisão do usuário (`on`/`off`). Só limpa o cache quando a política de fato muda."""
    want = choice == "on"
    out: Dict[str, Any] = {}
    changed = want != lgpd_text_enabled(store)
    if changed or not lgpd_text_decided(store):
        store.set_meta(LGPD_TEXT_KEY, "1" if want else "0")
        if want:
            store.set_meta(LGPD_CONSENT_KEY, now_utc())
    if changed:
        store.clear_evaluations()
        out["cache_cleared"] = True
        out["next_step"] = ("Os dados serão baixados de novo, já " +
                            ("guardando (mascarado) o texto de perguntas protegidas por LGPD." if want
                             else "sem guardar o texto de perguntas protegidas por LGPD."))
    return out


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
