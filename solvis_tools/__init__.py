"""Biblioteca de tools da Solvis para agentes (protótipo local).

Estrutura:
  solvis_tools/__init__.py   registro: @tool, perfis, validação, chamada
  solvis_tools/core/         código compartilhado (banco, períodos, nomes, skill, gráficos)
  solvis_tools/tools/        uma tool por arquivo; cada arquivo registra a sua com @tool

Cada tool declara nome, perfis (AGENTS), credencial, descrição, parâmetros com descrição, o que lê,
regras da skill ligadas e um exemplo. Sem esses campos ela não registra. Opcional: model_hint, uma
descrição curta para modelos locais pequenos (o agente em agent/ usa essa, quando existe).
O servidor MCP (mcp/server.py), o agente local (agent/) e a documentação (docs/tools.md) saem daqui.
"""
import importlib
import pkgutil
from pathlib import Path

from .core.db import ch as _ch
from .core.errors import ToolError

ROOT = Path(__file__).resolve().parents[1]
AGENTS = {
    "analyst": "Responde perguntas de negócio sobre os resultados: métricas calculadas no servidor, catálogo e regras da skill.",
    "data_engineer": "Cuida da qualidade e do significado dos dados: metadados, saúde, metodologia, avaliações e regras da skill.",
}
REGISTRY = {}


def tool(name, *, agents, access, description, params, required=(), reads, skill, example, model_hint=None):
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
    if name in REGISTRY:
        raise ValueError(f"tool {name} registrada duas vezes")
    schema = {"type": "object", "additionalProperties": False, "required": list(required),
              "properties": {k: {"type": t, "description": d} for k, (t, d) in params.items()}}

    def wrap(fn):
        REGISTRY[name] = {"name": name, "agents": list(agents), "access": access, "description": description,
                          "model_hint": model_hint, "input_schema": schema, "reads": list(reads),
                          "skill": list(skill), "example": example, "fn": fn, "module": fn.__module__}
        return fn
    return wrap


def ch(access, sql, params=None):
    """Compatibilidade: ch(perfil, sql, params)."""
    return _ch(sql, params, access=access)


def validate(t, args, strict=True):
    """Valida contra o esquema publicado. strict=False (agente local): ignora argumentos desconhecidos
    e não exige obrigatórios (a tool explica o que falta). Chaves com '_' são contexto interno
    (ex.: _user_q, o pedido original do usuário) e passam sem validação."""
    sch = t["input_schema"]
    ctx = {k: v for k, v in args.items() if k.startswith("_")}
    args = {k: v for k, v in args.items() if not k.startswith("_")}
    extra = set(args) - set(sch["properties"])
    if extra and strict:
        raise ToolError(f"argumentos desconhecidos para {t['name']}: {', '.join(sorted(extra))}")
    args = {k: v for k, v in args.items() if k in sch["properties"]}
    if strict:
        for k in sch["required"]:
            if args.get(k) in (None, ""):
                raise ToolError(f"{t['name']}: '{k}' é obrigatório")
    py = {"string": str, "integer": int, "boolean": bool, "number": (int, float)}
    for k, v in list(args.items()):
        want = sch["properties"][k]["type"]
        if want == "integer" and isinstance(v, str) and v.strip().lstrip("-").isdigit():
            args[k] = int(v)
        elif want == "string" and isinstance(v, (int, float)) and not strict:
            args[k] = str(v)
        elif not isinstance(args[k], py[want]) or (want == "integer" and isinstance(v, bool)):
            raise ToolError(f"{t['name']}: '{k}' precisa ser {want}")
    return {**args, **ctx}


def for_agent(agent):
    if agent not in AGENTS:
        raise ValueError(f"perfil desconhecido: {agent}. Use um de: {', '.join(AGENTS)}")
    return {n: t for n, t in REGISTRY.items() if agent in t["agents"]}


def call(agent, name, args, strict=True):
    tools = for_agent(agent)
    if name not in tools:
        raise ToolError(f"a tool '{name}' não existe para o perfil {agent}")
    t = tools[name]
    return t["fn"](validate(t, dict(args or {}), strict=strict))


def _autoload():
    from . import tools
    for m in sorted(pkgutil.iter_modules(tools.__path__), key=lambda m: m.name):
        if not m.name.startswith("_"):
            importlib.import_module(f"{tools.__name__}.{m.name}")


_autoload()
