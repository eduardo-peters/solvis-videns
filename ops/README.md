# ops: qualidade, metodologia e auditoria do agente local

Explicação completa: [docs/data-ops.md](../docs/data-ops.md).

| Arquivo | O que faz |
|---|---|
| `01_ops.sql` | Banco `ops` (interações, chamadas, guardrails, metodologia, avaliações, saúde dos dados, candidatos) e permissões |
| `pipeline.py` | Saúde dos dados → testes de guardrail → avaliação (opcional) → metodologia → portão → revisão |
| `gate.json` | Limites do portão e valores de paridade conhecidos |
| `../agent/audit.py` | Checagens de metodologia por resposta e gravação em `ops.*` |
| `../tests/agent/test_guardrails.py` | 21 testes de guardrail e isolamento, sem LLM |

## Instalar (uma vez)

```bash
CH=~/.local/clickhouse/clickhouse
PW=$(openssl rand -hex 16); echo "$PW" > ~/.local/clickhouse/agent_audit.pw; chmod 600 ~/.local/clickhouse/agent_audit.pw
$CH client -q "CREATE USER IF NOT EXISTS agent_audit IDENTIFIED WITH sha256_password BY '$PW'"
$CH client --multiquery < ops/01_ops.sql
```

## Usar

```bash
AGENT_TODAY=2026-11-18 python3 ops/pipeline.py                          # sem LLM, segundos
AGENT_TODAY=2026-11-18 python3 ops/pipeline.py --eval --context 0       # com avaliação, minutos
python3 ops/pipeline.py --review                                        # candidatos vindos de uso real
AGENT_TODAY=2026-11-18 python3 -m unittest discover -s tests/agent -v   # só os testes de guardrail
```

Código de saída 0 = aprovado. Rode antes de considerar qualquer mudança no agente, nas views ou na skill.
