-- Métricas da camada semântica como views parametrizadas.
-- As fórmulas seguem skills/solvis-survey-analysis-pilot/references/metrics.yaml
-- e scripts/solvis_pilot/measures.py (regras das telas de resultados).
-- Arredondamento do NPS: meio para longe do zero, como o Float#round do Ruby.

-- NPS por unidade (o recorte mais fino; propriedades e UF agregam a partir das contagens).
CREATE OR REPLACE VIEW semantic.nps_by_unit AS
SELECT
    c.unit_id,
    sumIf(c.answers, c.score >= 9)            AS promoters,
    sumIf(c.answers, c.score BETWEEN 7 AND 8) AS passives,
    sumIf(c.answers, c.score BETWEEN 0 AND 6) AS detractors,
    promoters + passives + detractors         AS n,
    if(n = 0, NULL, 100.0 * (promoters / n - detractors / n)) AS nps_raw,
    if(nps_raw >= 0, floor(nps_raw + 0.5), -floor(-nps_raw + 0.5)) AS nps
FROM semantic.answer_counts_daily AS c
WHERE c.survey_id = {survey:UInt32}
  AND c.question_id = {question:UInt32}
  AND c.kind = 'nps'
  AND c.day BETWEEN {start:Date} AND {end:Date}
GROUP BY c.unit_id;

-- NPS por valor de uma propriedade de unidade (Regional, Formato, HUB...).
-- Agrega contagens, nunca médias de NPS. Cadastro atual da propriedade.
CREATE OR REPLACE VIEW semantic.nps_by_unit_property AS
SELECT
    p.value_id,
    p.value,
    sumIf(c.answers, c.score >= 9)            AS promoters,
    sumIf(c.answers, c.score BETWEEN 7 AND 8) AS passives,
    sumIf(c.answers, c.score BETWEEN 0 AND 6) AS detractors,
    promoters + passives + detractors         AS n,
    if(n = 0, NULL, 100.0 * (promoters / n - detractors / n)) AS nps_raw,
    if(nps_raw >= 0, floor(nps_raw + 0.5), -floor(-nps_raw + 0.5)) AS nps
FROM semantic.answer_counts_daily AS c
INNER JOIN raw.unit_properties AS p
    ON p.client_id = c.client_id AND p.unit_id = c.unit_id AND p.name_id = {property:UInt32}
WHERE c.survey_id = {survey:UInt32}
  AND c.question_id = {question:UInt32}
  AND c.kind = 'nps'
  AND c.day BETWEEN {start:Date} AND {end:Date}
GROUP BY p.value_id, p.value;

-- Distribuição de alternativas (escolha única e escala). "Não se aplica" entra no denominador.
CREATE OR REPLACE VIEW semantic.choice_share AS
SELECT
    ch.choice_id AS choice_id, ch.letter AS letter, ch.text AS text, ch.value AS value,
    sum(c.answers) AS answers,
    sum(sum(c.answers)) OVER () AS n,
    round(100.0 * answers / n, 1) AS share_pct
FROM semantic.answer_counts_daily AS c
INNER JOIN raw.choices AS ch
    ON ch.client_id = c.client_id AND ch.survey_id = c.survey_id
   AND ch.question_id = c.question_id AND ch.choice_id = c.choice_id
WHERE c.survey_id = {survey:UInt32}
  AND c.question_id = {question:UInt32}
  AND c.kind = 'choice'
  AND c.day BETWEEN {start:Date} AND {end:Date}
GROUP BY ch.choice_id, ch.letter, ch.text, ch.value;

-- Média de escala: só alternativas com valor (sem "Não se aplica").
CREATE OR REPLACE VIEW semantic.scale_mean AS
SELECT
    sumIf(c.answers, ch.value IS NOT NULL) AS n,
    if(n = 0, NULL, sumIf(c.answers * ch.value, ch.value IS NOT NULL) / n) AS mean_raw
FROM semantic.answer_counts_daily AS c
INNER JOIN raw.choices AS ch
    ON ch.client_id = c.client_id AND ch.survey_id = c.survey_id
   AND ch.question_id = c.question_id AND ch.choice_id = c.choice_id
WHERE c.survey_id = {survey:UInt32}
  AND c.question_id = {question:UInt32}
  AND c.kind = 'choice'
  AND c.day BETWEEN {start:Date} AND {end:Date};

-- Volume de avaliações.
CREATE OR REPLACE VIEW semantic.evaluation_count AS
SELECT count() AS evaluations
FROM raw.evaluations FINAL
WHERE survey_id = {survey:UInt32}
  AND day BETWEEN {start:Date} AND {end:Date};
