-- Acesso do agente de engenharia de dados (perfil data_engineer do MCP).
-- Lê metadados e resultados agregados de qualidade. Não lê respostas individuais (raw.answers),
-- não lê as conversas (ops.interactions, ops.tool_calls) e não escreve.
-- Senha criada fora deste arquivo (ver mcp/README.md).

CREATE ROLE IF NOT EXISTS metadata_reader;
GRANT SELECT ON raw.surveys TO metadata_reader;
GRANT SELECT ON raw.questions TO metadata_reader;
GRANT SELECT ON raw.choices TO metadata_reader;
GRANT SELECT ON raw.units TO metadata_reader;
GRANT SELECT ON raw.unit_properties TO metadata_reader;
GRANT SELECT(client_id, survey_id, day, unit_id) ON raw.evaluations TO metadata_reader;
GRANT SELECT ON semantic.skill_chunks TO metadata_reader;
GRANT SELECT ON ops.data_health TO metadata_reader;
GRANT SELECT ON ops.eval_runs TO metadata_reader;
GRANT SELECT(ts, interaction_id, rule, passed) ON ops.methodology_checks TO metadata_reader;
GRANT SELECT(ts, interaction_id, guardrail, action) ON ops.guardrail_events TO metadata_reader;
GRANT metadata_reader TO engineer_agent;

-- Row policies existentes passam a valer também para o engenheiro (cliente 1 no protótipo).
-- Tabela com row policy esconde tudo de quem não está em nenhuma policy.
ALTER ROW POLICY assai_units ON raw.units TO assai_agent, engineer_agent;
ALTER ROW POLICY assai_props ON raw.unit_properties TO assai_agent, engineer_agent;
ALTER ROW POLICY assai_choices ON raw.choices TO assai_agent, engineer_agent;
ALTER ROW POLICY assai_evals ON raw.evaluations TO assai_agent, engineer_agent;
ALTER ROW POLICY assai_surveys ON raw.surveys TO assai_agent, engineer_agent;
ALTER ROW POLICY assai_questions ON raw.questions TO assai_agent, engineer_agent;

CREATE SETTINGS PROFILE IF NOT EXISTS engineer_limits SETTINGS
    readonly = 2, max_execution_time = 10, max_result_rows = 10000, max_memory_usage = 1000000000
    TO engineer_agent;
