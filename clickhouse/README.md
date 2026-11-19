# Protótipo: camada semântica no ClickHouse (local)

Prova de conceito da proposta "ClickHouse como motor da camada semântica" (ver ADR-0005).
Metadados em teste e lacunas: [docs/metadata-semantics.md](../docs/metadata-semantics.md).
Os dados vêm do cache normalizado do motor do piloto, não do espelho PeerDB.

| Arquivo | O que faz |
|---|---|
| `01_schema.sql` | `raw.*` (avaliações, respostas por id, unidades, propriedades, alternativas, pesquisas, perguntas) e `semantic.answer_counts_daily`, alimentada por materialized view |
| `02_semantic.sql` | Métricas como views parametrizadas: `nps_by_unit`, `nps_by_unit_property`, `choice_share`, `scale_mean`, `evaluation_count` |
| `03_access.sql` | Role `semantic_reader`, row policy por cliente, sem acesso a `raw.answers` (de `raw.evaluations`, só `client_id`, `survey_id`, `day`, `unit_id`), limites por usuário |
| `semantic.skill_chunks` | Criada por `agent/context.py index`: trechos das regras da skill com embedding, para busca vetorial (`cosineDistance`). Sem dado de cliente |
| `load_from_pilot_cache.py` | Copia o cache SQLite do piloto para o ClickHouse (sem texto livre) |

## Rodar

```bash
# 1. ClickHouse (binário único, fora do repositório)
mkdir -p ~/.local/clickhouse && cd ~/.local/clickhouse && curl https://clickhouse.com/ | sh
nohup ./clickhouse server > server.log 2>&1 &     # escuta só em localhost

# 2. Dados: rode antes uma consulta do piloto para o período desejado (enche o cache)
CH=~/.local/clickhouse/clickhouse
$CH client --multiquery < clickhouse/01_schema.sql
$CH client --multiquery < clickhouse/02_semantic.sql
python3 clickhouse/load_from_pilot_cache.py --client-id 1

# 3. Usuário do agente, isolado (senha fora do repositório)
PW=$(openssl rand -hex 16); echo "$PW" > ~/.local/clickhouse/assai_agent.pw; chmod 600 ~/.local/clickhouse/assai_agent.pw
$CH client -q "CREATE USER IF NOT EXISTS assai_agent IDENTIFIED WITH sha256_password BY '$PW'"
$CH client --multiquery < clickhouse/03_access.sql

# 4. Consulta como o agente
$CH client --user assai_agent --password "$PW" -q "
  SELECT value, nps, n FROM semantic.nps_by_unit_property(
    survey=40851, question=1607201, start='2026-11-17', end='2026-11-17', property=691)
  ORDER BY nps"
```

## Resultado (Assaí, pesquisa Satisfação, 17/11/2026, 11.709 avaliações)

| | Motor do piloto (API V1) | ClickHouse |
|---|---|---|
| NPS total / n | 79 / 11.709 | 79 / 11.709 |
| NPS por Regional (14 linhas) | — | idêntico, linha a linha |
| Tempo | 1min42s (download) | 0,03 s |
| Agente lê `raw.answers` | — | negado |
| Agente vê outro cliente | — | 0 linhas (row policy) |

## Limitações do protótipo

- Só 1 dia carregado; não mede custo em volume de produção.
- Arredondamento do NPS com `floor(x + 0.5)`, que pode divergir do `Float#round` do Ruby em valores binários limítrofes.
- Consumidor: o agente local de [agent/](../agent/README.md).
- Faltam filtros de confiabilidade, canal e conclusão nas views (as colunas já existem nas contagens), comparação de períodos, multi-resposta e média de escala por recorte.
- Em produção, `raw.answers` vem do espelho PeerDB, com JOIN com avaliações na MV ou desnormalização no pipeline.
