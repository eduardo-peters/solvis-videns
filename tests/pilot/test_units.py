"""Testes das partes puras do motor: fórmulas, arredondamento, períodos, privacidade, ingestão."""

import datetime as dt
import os
import sys
import unittest
from collections import Counter
from decimal import Decimal

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "skills", "solvis-videns", "scripts"))

from solvis_pilot import fmt, measures, periods  # noqa: E402
from solvis_pilot.ingest import eval_ref, local_started_at, normalize_evaluation, resolve_group  # noqa: E402
from solvis_pilot.privacy import mask_pii  # noqa: E402
from solvis_pilot.semantics import Questionnaire  # noqa: E402


def scale_question(metric_kind=None, values=(5, 4, 3, 2, 1, None)):
    options = {"metric_kind": metric_kind} if metric_kind else {}
    texts = ["Ótimo", "Bom", "Regular", "Ruim", "Péssimo", "Não se aplica"]
    survey = {
        "id": 1, "name": "S", "questionnaire": {"version": 1, "questions": [{
            "id": 10, "position_in_survey": 0, "text": "Como avalia?", "answer_type": "Scale", "options": options,
            "choices": [{"id": 100 + i, "text": texts[i], "position_in_question": i,
                         "value": None if v is None else str(v)} for i, v in enumerate(values)],
        }]},
    }
    return Questionnaire.from_api(survey).by_id[10]


class FormulaTests(unittest.TestCase):
    def test_nps_rounding_matches_ruby_float(self):
        # 100.0 * 0.145 = 14.499999999999998 em ponto flutuante: as telas mostram 14
        q = Questionnaire.from_api({"id": 1, "name": "S", "questionnaire": {"questions": [
            {"id": 1, "position_in_survey": 0, "text": "NPS", "answer_type": "NPS", "choices": []}]}}).by_id[1]
        self.assertEqual(measures.nps_result(29, 171, 0, q, "pt")["value"], 14)
        r = measures.nps_result(190, 60, 62, q, "pt")
        self.assertEqual(r["value"], 41)
        self.assertEqual(r["n"], 312)
        self.assertEqual(r["breakdown"]["promoters_pct"], 60.9)
        self.assertEqual(r["breakdown"]["detractors_pct"], 19.9)
        self.assertEqual(r["reference_zone"]["key"], "improvement")
        self.assertIsNone(measures.nps_result(0, 0, 0, q, "pt")["value"])

    def test_reference_zones(self):
        def zone(nps, mode):
            options = {"reference_zone": mode} if mode else {}
            q = Questionnaire.from_api({"id": 1, "name": "S", "questionnaire": {"questions": [
                {"id": 1, "position_in_survey": 0, "text": "N", "answer_type": "NPS", "options": options}]}}).by_id[1]
            z = measures.reference_zone(nps, q, "pt")
            return z["key"] if z else None
        self.assertEqual(zone(0, None), "critical")
        self.assertEqual(zone(50, None), "improvement")
        self.assertEqual(zone(51, None), "quality")
        self.assertEqual(zone(95, None), "excellence")
        self.assertEqual(zone(95, "with_enchantment"), "enchantment")
        self.assertEqual(zone(90, "with_enchantment"), "excellence")
        self.assertIsNone(zone(95, "none"))

    def test_scale_mean_excludes_valueless_choice(self):
        q = scale_question()
        r = measures.scale_mean_result({100: 3, 101: 1, 105: 2}, q, "pt")
        self.assertEqual(r["n"], 4)
        self.assertEqual(r["display"], "4,75")
        self.assertEqual(r["breakdown"]["valueless_answers"], 2)
        self.assertEqual(r["breakdown"]["scale_min"], 1)

    def test_choice_share_includes_valueless_in_denominator(self):
        q = scale_question()
        rows = measures.choice_rows({100: 3, 101: 1, 105: 2}, 6, q, "pt")
        self.assertEqual(rows[0]["display"], "50,0%")
        self.assertEqual(rows[5]["choice"]["text"], "Não se aplica")
        self.assertEqual(rows[5]["display"], "33,3%")

    def test_weighted_sum_is_100_times_mean_and_percent(self):
        q = scale_question("weighted_sum", values=(1, 0))
        r = measures.weighted_sum_result({100: 3, 101: 1}, q, "pt")
        self.assertEqual(r["value"], 75)
        self.assertEqual(r["display"], "75%")

    def test_percent_scale_mean(self):
        q = scale_question(values=(100, 50, 0))
        r = measures.scale_mean_result({100: 1, 101: 1, 102: 1}, q, "pt")
        self.assertEqual(r["display"], "50%")

    def test_formatting(self):
        self.assertEqual(fmt.fmt_count(12451, "pt"), "12.451")
        self.assertEqual(fmt.fmt_count(12451, "en"), "12,451")
        self.assertEqual(fmt.fmt_decimal(Decimal("4.305"), 2, "pt"), "4,31")
        self.assertEqual(fmt.fmt_delta(-14, 0, "points", "pt"), "-14 pontos")
        self.assertEqual(fmt.fmt_delta(3.4, 1, "pp", "pt"), "+3,4 p.p.")
        self.assertEqual(fmt.fmt_pct(Decimal("60.9"), 1, "en"), "60.9%")

    def test_delta_uses_rounded_values(self):
        d = measures.delta({"value": 41}, {"value": 55}, "nps", None, "pt")
        self.assertEqual(d, {"value": -14, "display": "-14 pontos"})
        d = measures.delta({"value": 41, "breakdown": {"detractors_pct": 19.9}},
                           {"value": 55, "breakdown": {"detractors_pct": 11.4}}, "nps", None, "pt")
        self.assertEqual(d["detractors_pct_display"], "+8,5 p.p.")
        d = measures.delta({"value": 120}, {"value": 100}, "evaluation_count", None, "pt")
        self.assertEqual(d["pct_change"], 20.0)


class PeriodTests(unittest.TestCase):
    today = dt.date(2026, 11, 17)

    def test_presets(self):
        p = periods.resolve_period(self.today, "last_month")
        self.assertEqual((p.start, p.end), (dt.date(2026, 10, 1), dt.date(2026, 10, 31)))
        p = periods.resolve_period(self.today, None)
        self.assertEqual(p.days, 90)
        self.assertEqual(p.end, self.today)
        p = periods.resolve_period(self.today, "quarter:2026-Q3")
        self.assertEqual((p.start, p.end), (dt.date(2026, 7, 1), dt.date(2026, 9, 30)))
        with self.assertRaises(Exception):
            periods.resolve_period(self.today, "month:2026-13")

    def test_previous_period_is_calendar_aware(self):
        oct_ = periods.resolve_period(self.today, "month:2026-10")
        prev, rule, _ = periods.comparison_period(oct_, "previous_period")
        self.assertEqual((prev.start, prev.end), (dt.date(2026, 9, 1), dt.date(2026, 9, 30)))
        self.assertEqual(rule, "previous_calendar_month")
        p90 = periods.resolve_period(self.today, "last_90_days")
        prev, rule, _ = periods.comparison_period(p90, "previous_period")
        self.assertEqual(prev.end, p90.start - dt.timedelta(days=1))
        self.assertEqual(prev.days, 90)

    def test_previous_year(self):
        p = periods.Period(dt.date(2024, 2, 1), dt.date(2024, 2, 29))
        prev, _, adjusted = periods.comparison_period(p, "previous_year")
        self.assertEqual(prev.end, dt.date(2023, 2, 28))
        self.assertFalse(adjusted)
        long_p = periods.Period(dt.date(2025, 1, 1), dt.date(2026, 3, 31))
        _, _, adjusted = periods.comparison_period(long_p, "previous_year")
        self.assertTrue(adjusted)

    def test_buckets(self):
        self.assertEqual(periods.bucket_key("week", "2026-01-01"), "2026-W01")
        self.assertEqual(periods.bucket_key("quarter", "2026-11-17"), "2026-Q4")
        self.assertEqual(periods.shift_bucket_one_year("month", "2026-10"), "2025-10")
        self.assertIsNone(periods.shift_bucket_one_year("week", "2026-W53"))  # 2026 tem 53 semanas ISO; 2025 não
        self.assertEqual(periods.hour_block_key("2026-10-01 23:10:00", 6), "18-24")
        self.assertEqual(periods.dow_key("2026-11-16"), "mon")


class PrivacyTests(unittest.TestCase):
    def test_masks(self):
        text = "Meu email é ana.souza@exemplo.com.br, cpf 123.456.789-09, tel (11) 98765-4321 e CNPJ 12.345.678/0001-90"
        out = mask_pii(text)
        for leaked in ("ana.souza", "123.456.789-09", "98765-4321", "12.345.678/0001-90"):
            self.assertNotIn(leaked, out)
        self.assertIn("[email]", out)
        self.assertIn("[cpf]", out)
        self.assertIn("[telefone]", out)
        self.assertIn("[cnpj]", out)

    def test_keeps_ordinary_text(self):
        self.assertEqual(mask_pii("Fila enorme entre 2024-2025, nota 10"), "Fila enorme entre 2024-2025, nota 10")


class IngestTests(unittest.TestCase):
    def test_started_at_is_local_not_converted(self):
        self.assertEqual(local_started_at("2026-07-10T14:21:07.000Z"), dt.datetime(2026, 7, 10, 14, 21, 7))
        self.assertEqual(eval_ref(dt.datetime(2026, 7, 10, 14, 21, 7), 48213), "260710000000048213")

    def test_normalize_discards_access_info_and_lgpd_text(self):
        survey = {"id": 5, "name": "S", "questionnaire": {"version": 1, "questions": [
            {"id": 1, "position_in_survey": 0, "text": "Nota", "answer_type": "NPS", "choices": []},
            {"id": 2, "position_in_survey": 1, "text": "E-mail", "answer_type": "Email",
             "options": {"lgpd_protected": True}, "choices": []},
            {"id": 3, "position_in_survey": 2, "text": "Comente", "answer_type": "Text", "choices": []},
        ]}}
        qn = Questionnaire.from_api(survey)
        raw = {
            "id": 7, "started_at": "2026-10-01T09:00:00.000Z", "origin": "Web", "completed": True,
            "web_access_info": {"ip_address": "1.2.3.4", "browser_fingerprint": "x", "identifier": "joao"},
            "surveyed_unit": {"id": 101, "name": "Loja"},
            "formatted_answers": [
                {"answer_type": "NPS", "answers": [{"question_text": "Nota", "answer_value": 9, "answer_text": "Promotor"}]},
                {"answer_type": "Email", "answers": [[{"question_text": "E-mail", "choice_text": "joao@x.com"}]]},
                {"answer_type": "Text", "answers": [{"question_text": "Comente", "choice_value": "ligue 11 98765-4321"}]},
            ],
        }
        ev, answers, _ = normalize_evaluation(raw, qn, Counter())
        flat = repr((ev, answers))
        for leaked in ("1.2.3.4", "joao", "98765-4321"):
            self.assertNotIn(leaked, flat)
        self.assertEqual(ev[6], "web")
        self.assertEqual(ev[9], 0)  # sem Data Quality: chave reliable ausente

    def test_twin_questions_split_by_choice_then_by_order(self):
        def scale(qid, pos, labels):
            return {"id": qid, "position_in_survey": pos, "text": "Como foi?", "answer_type": "Scale",
                    "choices": [{"id": qid * 10 + i, "text": t, "position_in_question": i, "value": str(5 - i)}
                                for i, t in enumerate(labels)]}
        qn = Questionnaire.from_api({"id": 1, "name": "S", "questionnaire": {"questions": [
            scale(1, 0, ["Ótimo", "Bom"]), scale(2, 5, ["Muito boa", "Boa"]),
            scale(3, 9, ["Ótimo", "Bom"]), scale(4, 12, ["Ótimo", "Bom"])]}})
        issues = Counter()
        # "Boa" só existe na gêmea 2; depois, duas respostas "Ótimo"/"Bom" depois da posição 5: só cabem 3 e 4 em ordem
        items = [("Como foi?", {"choice_text": "Boa"}), ("Como foi?", {"choice_text": "Ótimo"}),
                 ("Como foi?", {"choice_text": "Bom"})]
        self.assertEqual(resolve_group(qn, "Scale", items, issues, "2026-10-01"), [2, 3, 4])
        # sozinha e com alternativa comum a 1, 3 e 4: não há como saber
        self.assertEqual(resolve_group(qn, "Scale", [("Como foi?", {"choice_text": "Ótimo"})], issues, "d"), [None])


if __name__ == "__main__":
    unittest.main()
