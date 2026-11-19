-- Isolamento por cliente (RLS) e acesso só à camada semântica (CLS por omissão).
-- O usuário do agente não lê raw.answers/raw.evaluations diretamente: só as views
-- semânticas e as dimensões. Cada usuário enxerga só o próprio client_id.
-- Senha via parâmetro na criação (ver load.sh); nunca neste arquivo.

CREATE ROLE IF NOT EXISTS semantic_reader;
GRANT SELECT ON semantic.* TO semantic_reader;
GRANT SELECT(client_id, unit_id, name, code, city, state) ON raw.units TO semantic_reader;
GRANT SELECT ON raw.unit_properties TO semantic_reader;
GRANT SELECT ON raw.choices TO semantic_reader;
GRANT SELECT(client_id, survey_id, day, unit_id) ON raw.evaluations TO semantic_reader;
-- raw.answers fica sem grant: o agente nunca lê resposta individual.

GRANT semantic_reader TO assai_agent;
CREATE ROW POLICY IF NOT EXISTS assai_evals ON raw.evaluations
    FOR SELECT USING client_id = 1 TO assai_agent;

-- Uma row policy por cliente. Assaí = client_id 1 neste protótipo.
CREATE ROW POLICY IF NOT EXISTS assai_counts ON semantic.answer_counts_daily
    FOR SELECT USING client_id = 1 TO assai_agent;
CREATE ROW POLICY IF NOT EXISTS assai_units ON raw.units
    FOR SELECT USING client_id = 1 TO assai_agent;
CREATE ROW POLICY IF NOT EXISTS assai_props ON raw.unit_properties
    FOR SELECT USING client_id = 1 TO assai_agent;
CREATE ROW POLICY IF NOT EXISTS assai_choices ON raw.choices
    FOR SELECT USING client_id = 1 TO assai_agent;

-- Limites por usuário: protege o cluster e mede custo por cliente (system.query_log).
CREATE SETTINGS PROFILE IF NOT EXISTS agent_limits SETTINGS
    readonly = 2, max_execution_time = 10, max_result_rows = 10000,
    max_memory_usage = 2000000000
    TO assai_agent;

GRANT SELECT ON raw.surveys TO semantic_reader;
GRANT SELECT ON raw.questions TO semantic_reader;
CREATE ROW POLICY IF NOT EXISTS assai_surveys ON raw.surveys FOR SELECT USING client_id = 1 TO assai_agent;
CREATE ROW POLICY IF NOT EXISTS assai_questions ON raw.questions FOR SELECT USING client_id = 1 TO assai_agent;
