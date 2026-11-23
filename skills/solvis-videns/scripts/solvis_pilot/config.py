"""Configuração: credencial, URL da API, pasta de trabalho e data de hoje.

Tudo que o motor guarda (credencial, contexto do cliente, marca, cache) fica na PASTA DE TRABALHO:
a pasta em que o host está rodando (`SOLVIS_WORKDIR` para forçar outra), dentro de `.solvis-videns/`.
Um cliente por pasta de trabalho: quem atende vários clientes na mesma máquina usa uma pasta para cada.
A pasta `.solvis-videns/` ganha um `.gitignore` próprio para nunca ir para o git.

A credencial nunca é impressa. Ordem de leitura: variáveis de ambiente, arquivo
`.env` (o do comando `setup`, em `.solvis-videns/`, ou um `.env` na raiz da pasta de trabalho) e,
por último, `credentials.json`.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import re
import stat
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Optional
from urllib.parse import urlparse

from .errors import EXIT_API, EngineError

DEFAULT_BASE_URL = "https://sistema.solvis.net.br"
DATA_DIR_NAME = ".solvis-videns"


@dataclass(frozen=True)
class Settings:
    base_url: str
    username: str
    password: str
    cache_dir: Path          # pasta desta credencial (cache, token e auditoria)
    today: dt.date
    small_sample: int
    cache_ttl_days: int


def workdir() -> Path:
    """Pasta de trabalho: a pasta atual do host, ou `SOLVIS_WORKDIR`."""
    custom = os.environ.get("SOLVIS_WORKDIR")
    return (Path(custom) if custom else Path.cwd()).resolve()


def data_dir() -> Path:
    """`.solvis-videns/` dentro da pasta de trabalho: credencial, contexto, marca e cache deste cliente."""
    return workdir() / DATA_DIR_NAME


def ensure_data_dir() -> Path:
    """Cria `.solvis-videns/` (permissão 700) com um `.gitignore` que ignora tudo dentro dela."""
    path = _private_dir(data_dir())
    ignore = path / ".gitignore"
    if not ignore.exists():
        ignore.write_text("# criado pelo Solvis Videns: credencial, contexto, marca e cache deste cliente nunca vão para o git\n*\n",
                          encoding="utf-8")
    return path


def _cache_dir() -> Path:
    custom = os.environ.get("SOLVIS_CACHE_DIR")
    return Path(custom) if custom else data_dir() / "cache"


def credentials_file() -> Path:
    custom = os.environ.get("SOLVIS_CREDENTIALS_FILE")
    return Path(custom) if custom else data_dir() / "credentials.json"


ENV_USERNAME, ENV_PASSWORD, ENV_BASE_URL = "SOLVIS_API_USERNAME", "SOLVIS_API_PASSWORD", "SOLVIS_API_BASE_URL"


def env_file() -> Path:
    """Arquivo .env que o comando `setup` grava, em `.solvis-videns/` na pasta de trabalho (ignorado pelo git)."""
    custom = os.environ.get("SOLVIS_ENV_FILE")
    return Path(custom) if custom else data_dir() / ".env"


def _env_key(line: str) -> str:
    key = line.split("=", 1)[0].strip()
    return key[len("export "):].strip() if key.startswith("export ") else key


def parse_env_file(path: Path) -> Dict[str, str]:
    """Lê linhas CHAVE=valor (valor opcionalmente entre aspas). Só devolve chaves SOLVIS_*."""
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return {}
    out: Dict[str, str] = {}
    for line in lines:
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = _env_key(line), line.split("=", 1)[1].strip()
        if len(value) >= 2 and value[0] == value[-1] == '"':
            value = re.sub(r'\\(["\\])', r"\1", value[1:-1])
        elif len(value) >= 2 and value[0] == value[-1] == "'":
            value = value[1:-1]
        if key.startswith("SOLVIS_"):
            out[key] = value
    return out


def _file_env() -> Dict[str, str]:
    merged = parse_env_file(workdir() / ".env")
    merged.update(parse_env_file(env_file()))  # o .env do setup vale mais que o da raiz da pasta de trabalho
    return merged


def _env_line(key: str, value: str) -> str:
    return '%s="%s"' % (key, value.replace("\\", "\\\\").replace('"', '\\"'))


def write_env_file(values: Dict[str, str]) -> Path:
    """Grava ou atualiza chaves no .env do setup, preservando as outras linhas. Permissão 600."""
    if any("\n" in v or "\r" in v for v in values.values()):
        raise EngineError("invalid_argument", "Valor com quebra de linha não é aceito.")
    path = env_file()
    if path.parent == data_dir():
        ensure_data_dir()
    else:
        _private_dir(path.parent)
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        lines = []
    pending = dict(values)
    for i, line in enumerate(lines):
        if "=" in line and not line.lstrip().startswith("#") and _env_key(line) in pending:
            key = _env_key(line)
            lines[i] = _env_line(key, pending.pop(key))
    lines += [_env_line(k, v) for k, v in pending.items()]
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")
    try:
        os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)
    except OSError:
        pass
    return path


def credentials_source() -> Optional[str]:
    """De onde vem a credencial hoje (nunca o valor)."""
    if os.environ.get(ENV_USERNAME) and os.environ.get(ENV_PASSWORD):
        return "environment"
    for path in (env_file(), workdir() / ".env"):
        env = parse_env_file(path)
        if env.get(ENV_USERNAME) and env.get(ENV_PASSWORD):
            return str(path)
    path = credentials_file()
    return str(path) if path.exists() else None


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


def load_settings(require_credentials: bool = True, username: str = "", password: str = "",
                  base_url: str = "") -> Settings:
    """Os argumentos (usados pelo `setup` para testar uma credencial nova) passam na frente de tudo."""
    file_env = _file_env()
    username = username or os.environ.get(ENV_USERNAME) or file_env.get(ENV_USERNAME, "")
    password = password or os.environ.get(ENV_PASSWORD) or file_env.get(ENV_PASSWORD, "")
    base_url = base_url or os.environ.get(ENV_BASE_URL) or file_env.get(ENV_BASE_URL, "")

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
                "Peça ao usuário o usuário e a senha da API (Arquivo > Cliente > Lista de credenciais da API) "
                "e rode `setup --username U --password -` com a senha na entrada padrão: o motor testa o login e "
                f"grava em {env_file()} (pasta de trabalho: {workdir()}; um cliente por pasta). O usuário também "
                "pode definir SOLVIS_API_USERNAME e SOLVIS_API_PASSWORD no ambiente."
            ),
            exit_code=EXIT_API,
        )

    base_url = _validate_base_url(base_url or DEFAULT_BASE_URL)

    root = _cache_dir()
    if root.parent == data_dir():
        ensure_data_dir()
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
    root = _cache_dir()
    return root if root.exists() else None
