"""Acesso ao ClickHouse por perfil de credencial. SQL sempre fixo, com parâmetros tipados ({nome:Tipo}).

Perfis:
  client    usuário do cliente (CLICKHOUSE_USER, padrão assai_agent): views semânticas e dimensões
  engineer  engineer_agent: metadados e resultados agregados de qualidade
Senhas em arquivos fora do repositório (~/.local/clickhouse/*.pw).
"""
import json
import os
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from .errors import ToolError

CH_URL = os.environ.get("CLICKHOUSE_URL", "http://127.0.0.1:8123")
CREDENTIALS = {
    "client": (os.environ.get("CLICKHOUSE_USER", "assai_agent"),
               Path(os.environ.get("CLICKHOUSE_PASSWORD_FILE", Path.home() / ".local/clickhouse/assai_agent.pw"))),
    "engineer": ("engineer_agent", Path.home() / ".local/clickhouse/engineer_agent.pw"),
}


def ch(sql, params=None, access="client"):
    """Executa SQL fixo com a credencial do perfil; devolve lista de dicts."""
    user, pw_file = CREDENTIALS[access]
    qs = {"default_format": "JSON", **{"param_" + k: str(v) for k, v in (params or {}).items()}}
    req = urllib.request.Request(CH_URL + "/?" + urllib.parse.urlencode(qs), data=sql.encode(), method="POST")
    req.add_header("X-ClickHouse-User", user)
    req.add_header("X-ClickHouse-Key", pw_file.read_text().strip())
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.loads(r.read())["data"]
    except urllib.error.HTTPError as e:
        raise ToolError("clickhouse: " + e.read().decode()[:300])


def q(sql, params=None):
    """Atalho para o perfil engineer."""
    return ch(sql, params, access="engineer")
