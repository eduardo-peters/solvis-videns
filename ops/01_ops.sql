-- Engenharia de dados do próprio agente: tudo o que ele faz vira dado auditável.
-- Banco separado (ops) para não misturar com os dados do cliente (raw/semantic).

CREATE DATABASE IF NOT EXISTS ops;

-- Uma linha por pergunta respondida.
CREATE TABLE IF NOT EXISTS ops.interactions
(
    ts              DateTime64(3) DEFAULT now64(3),
    interaction_id  String,
    client_id       UInt32,
    source          LowCardinality(String),   -- ui | cli | eval | test
    model           LowCardinality(String),
    context_on      UInt8,
    question        String,                   -- texto do usuário (sem dado de respondente)
    answer          String,
    tools           Array(String),
    tool_errors     UInt16,
    outcome         LowCardinality(String),   -- answered | refused | blocked
    secs            Float32,
    context_chunks  Array(String)
)
ENGINE = MergeTree ORDER BY (client_id, ts);

-- Uma linha por chamada de ferramenta: o que foi pedido e o que foi resolvido.
CREATE TABLE IF NOT EXISTS ops.tool_calls
(
    ts              DateTime64(3) DEFAULT now64(3),
    interaction_id  String,
    step            UInt8,
    tool            LowCardinality(String),
    args            String,                   -- JSON pedido pelo modelo
    resolved_scope  String,                   -- JSON resolvido pelo código (pesquisa, pergunta, período)
    ok              UInt8,
    error           String,
    rows            UInt32
)
ENGINE = MergeTree ORDER BY (interaction_id, step);

-- Cada vez que um guardrail atua (bloqueio, nova tentativa, aviso inserido).
CREATE TABLE IF NOT EXISTS ops.guardrail_events
(
    ts              DateTime64(3) DEFAULT now64(3),
    interaction_id  String,
    guardrail       LowCardinality(String),   -- numbers | dates | grounding | metric | coverage | capability
    action          LowCardinality(String),   -- retry | block | annotate
    detail          String
)
ENGINE = MergeTree ORDER BY (guardrail, ts);

-- Checagens de metodologia sobre cada resposta (regras da skill aplicadas depois).
CREATE TABLE IF NOT EXISTS ops.methodology_checks
(
    ts              DateTime64(3) DEFAULT now64(3),
    interaction_id  String,
    rule            LowCardinality(String),   -- INV-xx da skill
    passed          UInt8,
    detail          String
)
ENGINE = MergeTree ORDER BY (rule, ts);

-- Execuções de avaliação e resultado por caso.
CREATE TABLE IF NOT EXISTS ops.eval_runs
(
    ts DateTime64(3) DEFAULT now64(3), run_id String, model LowCardinality(String), context_on UInt8,
    cases UInt16, passed UInt16, pass_rate Float32, mean_secs Float32, code_hash String, gate LowCardinality(String)
)
ENGINE = MergeTree ORDER BY ts;

CREATE TABLE IF NOT EXISTS ops.eval_results
(
    ts DateTime64(3) DEFAULT now64(3), run_id String, case_id String, run UInt8, passed UInt8,
    checks String, answer String, secs Float32
)
ENGINE = MergeTree ORDER BY (run_id, case_id);

-- Saúde dos dados e metadados (ver docs/metadata-semantics.md).
CREATE TABLE IF NOT EXISTS ops.data_health
(
    ts DateTime64(3) DEFAULT now64(3), check_id String, level LowCardinality(String),  -- ok | warn | fail
    value Float64, threshold Float64, detail String
)
ENGINE = MergeTree ORDER BY (check_id, ts);

-- Candidatos a caso de avaliação, vindos de falhas reais. Só entram em evals com aprovação.
CREATE TABLE IF NOT EXISTS ops.eval_candidates
(
    ts DateTime64(3) DEFAULT now64(3), interaction_id String, reason LowCardinality(String),
    question String, answer String, status LowCardinality(String) DEFAULT 'pending'  -- pending | accepted | rejected
)
ENGINE = ReplacingMergeTree ORDER BY interaction_id;

-- Usuário que só grava auditoria. Não lê dado de cliente, não lê a própria auditoria.
-- Senha criada fora deste arquivo (ver ops/README.md).
GRANT INSERT ON ops.* TO agent_audit;
-- O agente do cliente não enxerga ops.
REVOKE ALL ON ops.* FROM assai_agent;
