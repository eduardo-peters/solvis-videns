# ADR-0005: reaproveitar o motor do catálogo do Data Chat sobre o espelho ClickHouse

- Status: proposto
- Data: 2026-11-17

## Contexto

O Data Chat já tem, em `app/domain/services/data_chat/`:

- 14 entradas de catálogo com SQL em templates e parâmetros tipados (`Catalog::*`);
- `QueryCompiler`, que só aceita inteiros, listas de inteiros e datas, e recusa lista vazia;
- `ScopeGuard`, que confere o SQL final contra o escopo da sessão (só `SELECT`, allowlist de tabelas, listas `IN` iguais às da sessão, predicado de confiabilidade);
- `Warehouse` com union de shards por colunas nomeadas, `Freshness` com watermark do PeerDB, `CachedWarehouse` e um usuário ClickHouse somente leitura com limites;
- fórmulas alinhadas às telas (NPS com a mesma conta em ponto flutuante, média só com alternativas valoradas, múltipla resposta por avaliações distintas).

## Decisão

A API Analytics usa esse motor, sem o roteador e o narrador:

1. Extrair as entradas de métrica para um namespace compartilhado (`Analytics::Catalog` ou manter em `DataChat::Catalog` e expor por um adaptador). O Data Chat continua usando as mesmas classes, então qualquer correção vale para os dois.
2. Acrescentar o que a API precisa e o chat não tinha: parâmetros por id em vez de nome, `group_by` explícito, totais agregados, `min_n`, filtros de canal/turno/dia/hora/propriedade/tag, e saída estruturada em vez de tabela para narrar.
3. Usuário ClickHouse dedicado (`analytics_api_reader`), gerado pelo mesmo `ReaderDdl`, com cotas próprias. O chat e a API não podem disputar a mesma quota horária.
4. Cache por SQL compilado (já existe) e limite de taxa por credencial.

## Riscos

- As tabelas do PeerDB não têm chave em `started_at`; cada consulta lê o shard inteiro (`reader_ddl.rb:71-72`). Precisa de teste de carga com o maior cliente antes do piloto.
- O espelho pode ter até 24 h de atraso. O envelope declara o watermark e a API recusa com `stale_mirror` acima do limite, como o chat.
- O `ReaderDdl` precisa ser regenerado quando entra um shard novo; hoje é manual.
- Algumas fórmulas das telas não estão no catálogo (comparativo por turno, dia, hora, referência cruzada; evolução semanal/trimestral). Entram por fase, com teste de paridade contra `Results::AnswerCounts::*`.
