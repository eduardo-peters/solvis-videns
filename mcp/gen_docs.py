#!/usr/bin/env python3
"""Gera docs/tools.md a partir do registro de tools (solvis_tools/).

  python3 mcp/gen_docs.py           escreve docs/tools.md
  python3 mcp/gen_docs.py --check   falha se docs/tools.md está desatualizado (usado nos testes)
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import solvis_tools as lib  # noqa: E402

OUT = lib.ROOT / "docs" / "tools.md"
ACCESS = {"client": "`assai_agent`: views semânticas e dimensões do cliente; sem respostas individuais",
          "engineer": "`engineer_agent`: metadados e resultados agregados de qualidade; sem respostas individuais "
                      "e sem conversas"}


def render():
    L = ["# Biblioteca de tools", "",
         "Gerado por `python3 mcp/gen_docs.py` a partir de `solvis_tools/` (uma tool por arquivo em `solvis_tools/tools/`). Não edite à mão: o teste "
         "`tests/mcp` falha se este arquivo e o código divergirem.", "",
         "Cada perfil de agente roda uma instância do servidor MCP (`python3 mcp/server.py --agent <perfil>`) e "
         "enxerga só as próprias tools. Todas são somente leitura. Como a engenharia funciona: "
         "[engineering.md](engineering.md).", "", "## Perfis", "",
         "| Perfil | Para quê | Tools |", "|---|---|---|"]
    for a, desc in lib.AGENTS.items():
        names = ", ".join(f"[`{n}`](#{n})" for n in lib.for_agent(a))
        L.append(f"| `{a}` | {desc} | {names} |")
    L += ["", "## Matriz", "", "| Tool | " + " | ".join(f"`{a}`" for a in lib.AGENTS) + " | Credencial | Lê |",
          "|---|" + "---|" * len(lib.AGENTS) + "---|---|"]
    for n, t in lib.REGISTRY.items():
        marks = " | ".join("✓" if a in t["agents"] else "" for a in lib.AGENTS)
        L.append(f"| [`{n}`](#{n}) | {marks} | {t['access']} | {', '.join(t['reads'])} |")
    L += ["", "## Credenciais", ""] + [f"- **{k}**: {v}" for k, v in ACCESS.items()]
    for n, t in lib.REGISTRY.items():
        sch = t["input_schema"]
        L += ["", f"## {n}", "", t["description"], "",
              f"- **Arquivo:** [`solvis_tools/tools/{n}.py`](../solvis_tools/tools/{n}.py)",
              f"- **Perfis:** {', '.join(f'`{a}`' for a in t['agents'])}",
              f"- **Credencial:** `{t['access']}`",
              f"- **Lê:** {', '.join(t['reads'])}",
              f"- **Skill:** {', '.join(t['skill'])}", ""]
        if sch["properties"]:
            L += ["| Parâmetro | Tipo | Obrigatório | Descrição |", "|---|---|---|---|"]
            for p, spec in sch["properties"].items():
                L.append(f"| `{p}` | {spec['type']} | {'sim' if p in sch['required'] else ''} | {spec['description']} |")
        else:
            L.append("Sem parâmetros.")
        L += ["", "Exemplo (`tools/call`):", "", "```json",
              json.dumps({"name": n, "arguments": t["example"]}, ensure_ascii=False), "```"]
    return "\n".join(L) + "\n"


if __name__ == "__main__":
    text = render()
    if "--check" in sys.argv:
        if not OUT.exists() or OUT.read_text() != text:
            sys.exit("docs/tools.md desatualizado: rode python3 mcp/gen_docs.py")
        print("docs/tools.md em dia")
    else:
        OUT.write_text(text)
        print(f"{OUT.relative_to(lib.ROOT)}: {len(lib.REGISTRY)} tools, {len(lib.AGENTS)} perfis")
