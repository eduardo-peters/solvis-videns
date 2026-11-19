#!/usr/bin/env python3
"""Servidor MCP local da Solvis (stdio, JSON-RPC 2.0, uma mensagem por linha). Protótipo.

Uma instância por perfil de agente; cada perfil enxerga só a própria biblioteca de tools:
  python3 mcp/server.py --agent analyst
  python3 mcp/server.py --agent data_engineer

Métodos: initialize, notifications/initialized, ping, tools/list, tools/call.
Cada chamada é registrada em ops.tool_calls (usuário agent_audit, só INSERT).
Sem dependências: Python 3.9 da biblioteca padrão. Logs só no stderr (stdout é o protocolo).
"""
import argparse
import json
import os
import sys
import time
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import solvis_tools as lib  # noqa: E402

SERVER = {"name": "solvis-analytics-local", "version": "0.1.0"}
PROTOCOLS = ["2025-11-25", "2025-06-18", "2025-03-26", "2024-11-05"]


def log(*a):
    print(*a, file=sys.stderr, flush=True)


def audit(session, step, name, args, ok, error, rows):
    if os.environ.get("AUDIT_DISABLED") == "1":
        return
    try:
        sys.path.insert(0, str(lib.ROOT / "agent"))
        import audit as au
        au._insert("ops.tool_calls", [{"interaction_id": session, "step": step % 256, "tool": name,
                                       "args": json.dumps(args, ensure_ascii=False), "resolved_scope": "{}",
                                       "ok": int(ok), "error": error or "", "rows": rows}])
    except Exception as e:  # auditoria não derruba o protocolo, mas aparece no log
        log(f"audit falhou: {e}")


class Server:
    def __init__(self, agent):
        self.agent = agent
        self.tools = lib.for_agent(agent)
        self.session = f"mcp_{agent}_{uuid.uuid4().hex[:8]}"
        self.step = 0

    def handle(self, msg):
        method, mid = msg.get("method"), msg.get("id")
        if mid is None:  # notificação: não responde
            return None
        try:
            result = self.dispatch(method, msg.get("params") or {})
            return {"jsonrpc": "2.0", "id": mid, "result": result}
        except KeyError:
            return {"jsonrpc": "2.0", "id": mid, "error": {"code": -32601, "message": f"método desconhecido: {method}"}}
        except ValueError as e:
            return {"jsonrpc": "2.0", "id": mid, "error": {"code": -32602, "message": str(e)}}

    def dispatch(self, method, params):
        if method == "initialize":
            asked = params.get("protocolVersion")
            return {"protocolVersion": asked if asked in PROTOCOLS else PROTOCOLS[0],
                    "capabilities": {"tools": {"listChanged": False}},
                    "serverInfo": SERVER,
                    "instructions": f"Perfil {self.agent}: {lib.AGENTS[self.agent]} Números só vêm das tools; "
                                    "regras de interpretação em skill_lookup e explain_metric. Documentação: docs/tools.md."}
        if method == "ping":
            return {}
        if method == "tools/list":
            return {"tools": [{"name": t["name"], "description": t["description"], "inputSchema": t["input_schema"],
                               "annotations": {"readOnlyHint": True, "destructiveHint": False,
                                               "openWorldHint": False}} for t in self.tools.values()]}
        if method == "tools/call":
            name, args = params.get("name"), params.get("arguments") or {}
            if name not in self.tools:
                raise ValueError(f"tool desconhecida para o perfil {self.agent}: {name}")
            self.step += 1
            t0 = time.time()
            try:
                out = lib.call(self.agent, name, args)
                rows = len(out.get("rows", [])) if isinstance(out, dict) else len(out) if isinstance(out, list) else 0
                audit(self.session, self.step, name, args, True, None, rows)
                log(f"{name} ok {time.time() - t0:.2f}s")
                text = json.dumps(out, ensure_ascii=False, default=str)
                res = {"content": [{"type": "text", "text": text}], "isError": False}
                if isinstance(out, dict):
                    res["structuredContent"] = json.loads(text)
                return res
            except lib.ToolError as e:  # erro de negócio volta para o modelo ler e corrigir
                audit(self.session, self.step, name, args, False, str(e), 0)
                log(f"{name} erro: {e}")
                return {"content": [{"type": "text", "text": str(e)}], "isError": True}
        raise KeyError(method)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--agent", default="analyst", choices=list(lib.AGENTS))
    a = ap.parse_args()
    srv = Server(a.agent)
    log(f"solvis MCP pronto: perfil {a.agent}, {len(srv.tools)} tools")
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except ValueError:
            reply = {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "JSON inválido"}}
        else:
            reply = srv.handle(msg)
        if reply is not None:
            sys.stdout.write(json.dumps(reply, ensure_ascii=False, default=str) + "\n")
            sys.stdout.flush()


if __name__ == "__main__":
    main()
