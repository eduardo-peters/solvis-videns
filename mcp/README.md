# MCP local da Solvis (protótipo)

Servidor MCP em stdio, sem dependências (Python 3.9), com uma biblioteca de tools por perfil de agente. Lista completa e documentação de cada tool: [docs/tools.md](../docs/tools.md), gerada deste código. Como tudo se encaixa: [docs/engineering.md](../docs/engineering.md).

| Arquivo | O que faz |
|---|---|
| `solvis_tools/__init__.py` | Registro: perfis, decorador `@tool`, validação de argumentos, credencial por tool |
| `solvis_tools/analyst.py` | Métricas e catálogo (reaproveita `agent/agent.py`, uma implementação só) |
| `solvis_tools/engineer.py` | Metadados e engenharia ligados à skill |
| `server.py` | Protocolo MCP: `initialize`, `tools/list`, `tools/call`, `ping`; uma instância por perfil |
| `gen_docs.py` | Gera `docs/tools.md`; `--check` falha se a documentação divergir do código |

## Pré-requisitos

ClickHouse e dados do protótipo ([clickhouse/README.md](../clickhouse/README.md)), banco `ops` ([ops/README.md](../ops/README.md)) e o usuário do engenheiro:

```bash
CH=~/.local/clickhouse/clickhouse
PW=$(openssl rand -hex 16); echo "$PW" > ~/.local/clickhouse/engineer_agent.pw; chmod 600 ~/.local/clickhouse/engineer_agent.pw
$CH client -q "CREATE USER IF NOT EXISTS engineer_agent IDENTIFIED WITH sha256_password BY '$PW'"
$CH client --multiquery < ops/02_engineer_access.sql
```

`skill_lookup` precisa do Ollama com `nomic-embed-text`.

## Conectar num host MCP

Kiro (`.kiro/settings/mcp.json` do workspace), Claude Desktop ou Claude Code usam o mesmo formato. Um servidor por perfil:

```json
{
  "mcpServers": {
    "solvis-analyst": {
      "command": "python3",
      "args": ["/caminho/para/solvis-survey-analysis-skill/mcp/server.py", "--agent", "analyst"],
      "env": {"AGENT_TODAY": "2026-11-18"}
    },
    "solvis-data-engineer": {
      "command": "python3",
      "args": ["/caminho/para/solvis-survey-analysis-skill/mcp/server.py", "--agent", "data_engineer"]
    }
  }
}
```

`AGENT_TODAY` fixa o "hoje" porque o protótipo só tem 17/11/2026 carregado; tire quando houver dados atuais. As senhas ficam nos arquivos `~/.local/clickhouse/*.pw`, nunca na configuração.

## Testar sem host

```bash
AGENT_TODAY=2026-11-18 python3 -m unittest discover -s tests/mcp -v
printf '%s\n' '{"jsonrpc":"2.0","id":1,"method":"tools/list"}' | python3 mcp/server.py --agent data_engineer
```

## Adicionar uma tool

1. Escreva a função num módulo de `solvis_tools/` com `@tool(...)`: nome, perfis, credencial, descrição, parâmetros com descrição, o que lê, regras da skill ligadas e um exemplo. Sem esses campos ela não registra.
2. SQL só com parâmetros tipados (`{nome:Tipo}`), nunca texto concatenado vindo do modelo.
3. `python3 mcp/gen_docs.py` para atualizar `docs/tools.md`.
4. `python3 ops/pipeline.py`: os testes rodam o exemplo de verdade, conferem a documentação e as referências da skill.
