"""Configuração: credencial, URL da API, pasta de cache e data de hoje.

A credencial nunca é impressa. Ela vem de variáveis de ambiente ou de um
arquivo JSON criado pelo próprio usuário (nunca pela LLM).
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import stat
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

from .errors import EXIT_API, EngineError

DEFAULT_BASE_URL = "https://sistema.solvis.net.br"
APP_DIR_NAME = "solvis-survey-analysis"


@dataclass(frozen=True)
class Settings:
    base_url: str
    username: str
    password: str
    cache_dir: Path          # pasta desta credencial (cache, token e auditoria)
    today: dt.date
    small_sample: int
    cache_ttl_days: int


def _home_config_dir() -> Path:
    if sys.platform.startswith("win"):
        return Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming")) / APP_DIR_NAME
    return Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / APP_DIR_NAME


def _home_cache_dir() -> Path:
    if sys.platform.startswith("win"):
        return Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local")) / APP_DIR_NAME
    return Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache")) / APP_DIR_NAME


def credentials_file() -> Path:
    custom = os.environ.get("SOLVIS_CREDENTIALS_FILE")
    return Path(custom) if custom else _home_config_dir() / "credentials.json"


def _validate_base_url(url: str) -> str:
    parsed = urlparse(url)
    local = parsed.hostname in ("localhost", "127.0.0.1")
    if parsed.scheme != "https" and not (parsed.scheme == "http" and local):
        raise EngineError(
            "invalid_config",
            "SOLVIS_API_BASE_URL precisa usar https.",
            exit_code=EXIT_API,
        )
    return url.rstrip("/")


def _sao_paulo_tz() -> dt.tzinfo:
    try:
        from zoneinfo import ZoneInfo  # Python 3.9+

        return ZoneInfo("America/Sao_Paulo")
    except Exception:  # Windows sem base tzdata: o Brasil não tem horário de verão desde 2019
        return dt.timezone(dt.timedelta(hours=-3))


def today_local() -> dt.date:
    """Hoje no fuso de São Paulo (padrão dos presets de período)."""
    forced = os.environ.get("SOLVIS_TODAY")
    if forced:
        return dt.date.fromisoformat(forced)
    return dt.datetime.now(_sao_paulo_tz()).date()


def local_time(iso_utc: Optional[str]) -> Optional[str]:
    """Horário de download (UTC) em São Paulo, para citar ao usuário."""
    if not iso_utc:
        return None
    return dt.datetime.fromisoformat(iso_utc).astimezone(_sao_paulo_tz()).strftime("%d/%m/%Y %H:%M")


def _private_dir(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(path, stat.S_IRWXU)
    except OSError:
        pass
    return path


def load_settings(require_credentials: bool = True) -> Settings:
    username = os.environ.get("SOLVIS_API_USERNAME", "")
    password = os.environ.get("SOLVIS_API_PASSWORD", "")
    base_url = os.environ.get("SOLVIS_API_BASE_URL", "")

    if not (username and password):
        cred_path = credentials_file()
        if cred_path.exists():
            try:
                data = json.loads(cred_path.read_text(encoding="utf-8"))
            except (OSError, ValueError) as exc:
                raise EngineError(
                    "invalid_config",
                    f"Não consegui ler o arquivo de credencial ({cred_path}): {exc}",
                    exit_code=EXIT_API,
                )
            username = username or str(data.get("username", ""))
            password = password or str(data.get("password", ""))
            base_url = base_url or str(data.get("base_url", ""))

    if require_credentials and not (username and password):
        raise EngineError(
            "missing_credentials",
            "Credencial da API Solvis não configurada.",
            hint=(
                "O usuário deve definir SOLVIS_API_USERNAME e SOLVIS_API_PASSWORD, ou criar "
                f"{credentials_file()} com {{\"username\": ..., \"password\": ...}}. "
                "Não peça a senha no chat."
            ),
            exit_code=EXIT_API,
        )

    base_url = _validate_base_url(base_url or DEFAULT_BASE_URL)

    root = Path(os.environ["SOLVIS_CACHE_DIR"]) if os.environ.get("SOLVIS_CACHE_DIR") else _home_cache_dir()
    key = hashlib.sha256(f"{base_url}|{username}".encode("utf-8")).hexdigest()[:16]
    cache_dir = _private_dir(_private_dir(root) / key)

    return Settings(
        base_url=base_url,
        username=username,
        password=password,
        cache_dir=cache_dir,
        today=today_local(),
        small_sample=int(os.environ.get("SOLVIS_SMALL_SAMPLE", "30")),
        cache_ttl_days=int(os.environ.get("SOLVIS_CACHE_TTL_DAYS", "7")),
    )


def cache_root() -> Optional[Path]:
    root = Path(os.environ["SOLVIS_CACHE_DIR"]) if os.environ.get("SOLVIS_CACHE_DIR") else _home_cache_dir()
    return root if root.exists() else None
