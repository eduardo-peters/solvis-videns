-- Protótipo local: camada semântica da Solvis sobre ClickHouse.
-- Fonte dos dados: cache normalizado do motor do piloto (SQLite), não o espelho PeerDB.
-- Em produção, `raw.*` seria substituído pelas tabelas do espelho, e o resto continua igual.

CREATE DATABASE IF NOT EXISTS raw;
CREATE DATABASE IF NOT EXISTS semantic;

-- Avaliações (uma linha por avaliação). client_id existe para isolamento (row policy).
CREATE TABLE IF NOT EXISTS raw.evaluations
(
    client_id   UInt32,
    survey_id   UInt32,
    eval_ref    String,                 -- yymmdd(started_at) + id: único entre shards
    day         Date,                   -- dia local da unidade
    started_at  DateTime,               -- hora local da unidade, sem fuso
    unit_id     UInt32,
    channel     LowCardinality(String), -- device | web
    completed   UInt8,
    reliable    Nullable(UInt8),        -- só em pesquisa com Data Quality
    dq          UInt8,
    duration    Nullable(UInt32)
)
ENGINE = ReplacingMergeTree
PARTITION BY toYYYYMM(day)
ORDER BY (client_id, survey_id, day, eval_ref);

-- Respostas normalizadas por question_id / choice_id. Atributos da avaliação
-- desnormalizados para a materialized view não precisar de JOIN.
CREATE TABLE IF NOT EXISTS raw.answers
(
    client_id   UInt32,
    survey_id   UInt32,
    eval_ref    String,
    day         Date,
    unit_id     UInt32,
    channel     LowCardinality(String),
    completed   UInt8,
    reliable    Nullable(UInt8),
    question_id UInt32,
    kind        LowCardinality(String), -- nps | choice | multi | open | presence
    choice_id   Nullable(UInt32),
    score       Nullable(Int8),
    answered    UInt8
)
ENGINE = MergeTree
PARTITION BY toYYYYMM(day)
ORDER BY (client_id, survey_id, question_id, day, unit_id);

-- Dimensões
CREATE TABLE IF NOT EXISTS raw.units
(
    client_id UInt32, unit_id UInt32, name String, code String, city String, state LowCardinality(String)
)
ENGINE = ReplacingMergeTree ORDER BY (client_id, unit_id);

CREATE TABLE IF NOT EXISTS raw.unit_properties
(
    client_id UInt32, unit_id UInt32, name_id UInt32, name String, value_id UInt32, value String
)
ENGINE = ReplacingMergeTree ORDER BY (client_id, name_id, value_id, unit_id);

CREATE TABLE IF NOT EXISTS raw.choices
(
    client_id UInt32, survey_id UInt32, question_id UInt32, choice_id UInt32,
    letter String, text String, value Nullable(Float64)
)
ENGINE = ReplacingMergeTree ORDER BY (client_id, survey_id, question_id, choice_id);

-- Contagens pré-agregadas: base de todas as métricas de pergunta.
-- NPS: score; escala/escolha: choice_id. Uma linha por combinação de recorte por dia.
CREATE TABLE IF NOT EXISTS semantic.answer_counts_daily
(
    client_id   UInt32,
    survey_id   UInt32,
    question_id UInt32,
    day         Date,
    unit_id     UInt32,
    channel     LowCardinality(String),
    completed   UInt8,
    reliable    Int8,                   -- -1 = sem classificação
    kind        LowCardinality(String),
    choice_id   UInt32,                 -- 0 = não se aplica ao tipo
    score       Int8,                   -- -1 = não se aplica ao tipo
    answers     UInt64
)
ENGINE = SummingMergeTree(answers)
PARTITION BY toYYYYMM(day)
ORDER BY (client_id, survey_id, question_id, day, unit_id, channel, completed, reliable, kind, choice_id, score);

CREATE MATERIALIZED VIEW IF NOT EXISTS semantic.answer_counts_daily_mv
TO semantic.answer_counts_daily AS
SELECT client_id, survey_id, question_id, day, unit_id, channel, completed,
       ifNull(toInt8(reliable), -1) AS reliable, kind,
       ifNull(choice_id, 0) AS choice_id, ifNull(score, -1) AS score,
       count() AS answers
FROM raw.answers
WHERE answered = 1
GROUP BY client_id, survey_id, question_id, day, unit_id, channel, completed, reliable, kind, choice_id, score;

-- Catálogo de pesquisas e perguntas (para o agente resolver nomes em ids).
CREATE TABLE IF NOT EXISTS raw.surveys
(
    client_id UInt32, survey_id UInt32, name String, archived UInt8, last_evaluation_date Nullable(Date)
)
ENGINE = ReplacingMergeTree ORDER BY (client_id, survey_id);

CREATE TABLE IF NOT EXISTS raw.questions
(
    client_id UInt32, survey_id UInt32, question_id UInt32, number UInt16, text String,
    answer_type LowCardinality(String)
)
ENGINE = ReplacingMergeTree ORDER BY (client_id, survey_id, question_id);
