"""Biblioteca de tools da Solvis para agentes (protótipo local).

Cada tool é registrada uma vez, com tudo o que a documenta e a protege:
  - name, description, input_schema (JSON Schema, o mesmo que o MCP publica)
  - agents: perfis de agente que recebem a tool (analyst, data_engineer)
  - access: credencial do ClickHouse que a executa ("client" = assai_agent, "engineer" = engineer_agent)
  - reads: o que ela lê (para auditoria e documentação)
  - skill: regras e arquivos da skill a que ela está ligada
  - example: chamada de exemplo
A documentação (docs/tools.md) e o servidor MCP (mcp/server.py) saem deste registro.
Uma tool sem descrição, esquema, leitura ou exemplo não registra (falha ao importar).
"""
import json
import os
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CH_URL = os.environ.get("CLICKHOUSE_URL", "http://127.0.0.1:8123")
CREDENTIALS = {  # perfil de acesso -> (usuário ClickHouse, arquivo de senha)
    "client": ("assai_agent", Path.home() / ".local/clickhouse/assai_agent.pw"),
    "engineer": ("engineer_agent", Path.home() / ".local/clickhouse/engineer_agent.pw"),
}
AGENTS = {
    "analyst": "Responde perguntas de negócio sobre os resultados: métricas calculadas no servidor, catálogo e regras da skill.",
    "data_engineer": "Cuida da qualidade e do significado dos dados: metadados, saúde, metodologia, avaliações e regras da skill.",
}

REGISTRY = {}


class ToolError(Exception):
    pass


def tool(name, *, agents, access, description, params, required=(), reads, skill, example):
    """Decorador de registro. params: {nome: (tipo JSON, descrição)}."""
    for k, v in {"description": description, "reads": reads}.items():
        if not v:
            raise ValueError(f"tool {name}: '{k}' obrigatório")
    if example is None or (params and not example):
        raise ValueError(f"tool {name}: 'example' obrigatório quando a tool tem parâmetros")
    if set(example) - set(params):
        raise ValueError(f"tool {name}: exemplo usa parâmetros que não existem")
    unknown = set(agents) - set(AGENTS)
    if unknown:
        raise ValueError(f"tool {name}: perfis desconhecidos {unknown}")
    schema = {"type": "object", "additionalProperties": False, "required": list(required),
              "properties": {k: {"type": t, "description": d} for k, (t, d) in params.items()}}

    def wrap(fn):
        REGISTRY[name] = {"name": name, "agents": list(agents), "access": access, "description": description,
                          "input_schema": schema, "reads": list(reads), "skill": list(skill),
                          "example": example, "fn": fn}
        return fn
    return wrap


def ch(access, sql, params=None):
    """SQL fixo com parâmetros tipados, executado com a credencial do perfil de acesso."""
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


def validate(t, args):
    """Valida os argumentos contra o esquema publicado (tipos, obrigatórios, sem extras)."""
    sch = t["input_schema"]
    extra = set(args) - set(sch["properties"])
    if extra:
        raise ToolError(f"argumentos desconhecidos para {t['name']}: {', '.join(sorted(extra))}")
    for k in sch["required"]:
        if args.get(k) in (None, ""):
            raise ToolError(f"{t['name']}: '{k}' é obrigatório")
    py = {"string": str, "integer": int, "boolean": bool, "number": (int, float)}
    for k, v in args.items():
        want = sch["properties"][k]["type"]
        if want == "integer" and isinstance(v, str) and v.lstrip("-").isdigit():
            args[k] = int(v)
        elif not isinstance(args[k], py[want]) or (want == "integer" and isinstance(v, bool)):
            raise ToolError(f"{t['name']}: '{k}' precisa ser {want}")
    return args


def for_agent(agent):
    if agent not in AGENTS:
        raise ValueError(f"perfil desconhecido: {agent}. Use um de: {', '.join(AGENTS)}")
    return {n: t for n, t in REGISTRY.items() if agent in t["agents"]}


def call(agent, name, args):
    tools = for_agent(agent)
    if name not in tools:
        raise ToolError(f"a tool '{name}' não existe para o perfil {agent}")
    t = tools[name]
    return t["fn"](validate(t, dict(args or {})))


from . import analyst, engineer  # noqa: E402,F401  (registram as tools)
