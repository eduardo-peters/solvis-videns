"""Testes de `validate` (verify.py) contra a API falsa. Valores calculados à mão a partir de fixture.py.

Outubro/2026 na pesquisa 56 (NPS, pergunta 812): unidades 102 (n=4, NPS 100), 101 (n=10, NPS 20), 103 (n=6, NPS -50);
total n=20, NPS 15. Unidade 104 sem avaliações em outubro. Regional Sul = valor 71.
"""

import io
import json
import os
import shutil
import sys
import tempfile
import time
import unittest
from contextlib import redirect_stdout
from unittest import mock

HERE = os.path.dirname(__file__)
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "..", "..", "skills", "solvis-videns", "scripts"))

import fixture as fx  # noqa: E402
from solvis_pilot import cli, verify  # noqa: E402


class NumberTest(unittest.TestCase):
    def test_parse_shown(self):
        from decimal import Decimal
        self.assertEqual(verify.parse_shown("1.234,5%"), (Decimal("1234.5"), 1))
        self.assertEqual(verify.parse_shown("-3 pontos"), (Decimal("-3"), 0))
        self.assertEqual(verify.parse_shown("1,234.5", "en"), (Decimal("1234.5"), 1))

    def test_rounding_rule_and_boundary_tolerance(self):
        from decimal import Decimal as D
        self.assertTrue(verify.compare_number(D("14.4"), D("14"), 0)["ok"])
        self.assertFalse(verify.compare_number(D("14.4"), D("15"), 0)["ok"])
        # 14,496 está a 0,004 da fronteira 14,5: aceita 15 (tolerância de 1 unidade)
        res = verify.compare_number(D("14.496"), D("15"), 0)
        self.assertTrue(res["ok"] and res["tolerance_used"])
        # 14,4 está longe da fronteira: 15 não passa
        self.assertFalse(verify.compare_number(D("14.4"), D("15"), 0)["ok"])


class ValidateTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fake = fx.build()
        cls.base_url = cls.fake.start()

    @classmethod
    def tearDownClass(cls):
        cls.fake.stop()

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.env = mock.patch.dict(os.environ, {
            "SOLVIS_API_BASE_URL": self.base_url, "SOLVIS_API_USERNAME": self.fake.username,
            "SOLVIS_API_PASSWORD": self.fake.password, "SOLVIS_CACHE_DIR": self.tmp, "SOLVIS_TODAY": "2026-11-17",
        })
        self.env.start()
        self.run_cli("config", "--start-month", "2025-01")
        self.nps_q = self.run_cli("query", "--metric", "nps", "--survey", 56, "--question", fx.NPS,
                                  "--period", "month:2026-10")["query_id"]
        self.eval_q = self.run_cli("query", "--metric", "evaluation_count", "--survey", 56,
                                   "--period", "month:2026-10")["query_id"]

    def tearDown(self):
        self.env.stop()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def run_cli(self, *args):
        buf = io.StringIO()
        with redirect_stdout(buf):
            code = cli.main([str(a) for a in args])
        body = json.loads(buf.getvalue())
        self.assertEqual(code, 0, body)
        return body

    def validate(self, *claims, **material):
        path = os.path.join(self.tmp, "claims.json")
        with open(path, "w", encoding="utf-8") as fh:
            json.dump({"material": {"kind": "report", **material}, "claims": list(claims)}, fh)
        return self.run_cli("validate", "--claims", path)

    def one(self, claim):
        rep = self.validate(claim)
        return rep, rep["annex"][0]["verdict"], (rep["corrections"] + rep["adjustments"] + rep["confirmed"] + rep["not_checked"])[0]

    # ---------------------------------------------------------------- N
    def test_N_exact_adjustment_and_correction(self):
        base = {"type": "N", "query_id": self.nps_q, "select": {}, "field": "value"}
        _, v, r = self.one({**base, "shown": "15"})
        self.assertEqual((v, r["verification"]), ("confere", "independent"))
        _, v, _ = self.one({**base, "shown": "16"})          # 6,7% de desvio, não muda a conclusão
        self.assertEqual(v, "ajuste")
        rep, v, r = self.one({**base, "shown": "18"})        # 20% de desvio
        self.assertEqual(v, "correcao")
        self.assertEqual(rep["verdict"], "do_not_send_as_is")
        self.assertTrue(rep["decision_required"])
        self.assertEqual(len(rep["options"]), 3)

    def test_N_by_unit_and_n(self):
        _, v, _ = self.one({"type": "N", "query_id": self.nps_q, "select": {"unit": 101}, "shown": "20"})
        self.assertEqual(v, "confere")
        _, v, _ = self.one({"type": "N", "query_id": self.nps_q, "select": {"unit": "Shopping Centro"}, "shown": "-50"})
        self.assertEqual(v, "confere")
        _, v, _ = self.one({"type": "N", "query_id": self.nps_q, "select": {}, "field": "n", "shown": "20"})
        self.assertEqual(v, "confere")

    def test_N_unsupported_filter_falls_back_to_envelope(self):
        qid = self.run_cli("query", "--metric", "nps", "--survey", 56, "--question", fx.NPS, "--period", "month:2026-10",
                           "--property-value", 71)["query_id"]
        rep, v, r = self.one({"type": "N", "query_id": qid, "select": {}, "shown": "-50"})
        self.assertEqual((v, r["verification"]), ("confere", "envelope_only"))
        self.assertFalse(rep["how_checked"]["queries"][0]["independent_recalculation"])

    # ---------------------------------------------------------------- B
    def test_B_base(self):
        _, v, _ = self.one({"type": "B", "query_id": self.nps_q, "label": "respondentes", "shown": "20"})
        self.assertEqual(v, "confere")
        _, v, r = self.one({"type": "B", "query_id": self.nps_q, "label": "respondentes", "shown": "25"})
        self.assertEqual(v, "correcao")

    # ---------------------------------------------------------------- Q
    def test_Q_ordinal_and_qualifiers(self):
        q = {"type": "Q", "query_id": self.nps_q, "qualifier": "ordinal", "order": "desc", "min_n": 5}
        _, v, _ = self.one({**q, "select": {"unit": 101}, "position": 1})            # 102 (n=4) sai pelo n mínimo
        self.assertEqual(v, "confere")
        _, v, _ = self.one({**q, "select": {"unit": 101}, "position": 2})
        self.assertEqual(v, "correcao")
        # NPS é 15: "maioria" sobre NPS não se aplica, mas o valor 15 não passa de 50
        _, v, _ = self.one({"type": "Q", "query_id": self.nps_q, "qualifier": "maioria", "select": {}})
        self.assertEqual(v, "correcao")

    # ---------------------------------------------------------------- E
    def test_E_active_units_and_registry(self):
        _, v, _ = self.one({"type": "E", "query_id": self.eval_q, "kind": "count", "shown": "3"})
        self.assertEqual(v, "confere")
        rep, v, r = self.one({"type": "E", "query_id": self.eval_q, "kind": "count", "shown": "4", "presented_as": "active"})
        self.assertEqual(v, "correcao")                    # 4 é o cadastro; ativas são 3
        self.assertIn("cadastro", r["detail"])
        _, v, _ = self.one({"type": "E", "query_id": self.eval_q, "kind": "list", "listed": [101, 102],
                            "expected_count": 2})
        self.assertEqual(v, "correcao")                    # faltam 103

    # ---------------------------------------------------------------- R
    def test_R_ranking_is_exhaustive_and_respects_min_n(self):
        base = {"type": "R", "query_id": self.nps_q, "kind": "top", "order": "desc", "min_n": 5, "k": 1}
        _, v, _ = self.one({**base, "listed": [101]})
        self.assertEqual(v, "confere")
        _, v, r = self.one({**base, "listed": [102]})      # 102 tem n=4 < 5
        self.assertEqual(v, "correcao")
        _, v, _ = self.one({"type": "R", "query_id": self.nps_q, "kind": "below", "threshold": 30, "min_n": 5,
                            "listed": [103]})
        self.assertEqual(v, "correcao")                     # 101 (NPS 20) também está abaixo de 30
        _, v, _ = self.one({"type": "R", "query_id": self.nps_q, "kind": "below", "threshold": 30, "min_n": 5,
                            "listed": [101, 103], "shown_count": 2})
        self.assertEqual(v, "confere")

    def test_R_declared_base_must_match_query(self):
        _, v, r = self.one({"type": "R", "query_id": self.nps_q, "kind": "top", "order": "desc", "min_n": 5, "k": 1,
                            "listed": [101], "base": "detractors"})
        self.assertEqual(v, "correcao")
        self.assertIn("detratores", r["detail"])

    # ---------------------------------------------------------------- C / T / G
    def test_C_non_robust_variation_as_fact_is_an_adjustment(self):
        qid = self.run_cli("query", "--metric", "nps", "--survey", 56, "--question", fx.NPS, "--period", "month:2026-10",
                           "--compare-with", "previous_period")["query_id"]
        rep, v, r = self.one({"type": "C", "query_id": qid, "select": {}, "framing": "fact"})
        self.assertEqual(r["classification"], "robust")      # 15 contra 100 (n=3): z = -4,18 na API falsa
        self.assertEqual(v, "confere")
        _, v, r = self.one({"type": "C", "query_id": qid, "select": {}, "framing": "fact", "selected_among_many": True})
        self.assertEqual(v, "confere")                        # |z| = 4,18 >= 3,29

    def test_C_selected_unit_below_3_29_stated_as_fact_is_an_adjustment(self):
        qid = self.run_cli("query", "--metric", "nps", "--survey", 56, "--question", fx.NPS, "--period", "month:2026-10",
                           "--compare-with", "previous_period", "--group-by", "unit")["query_id"]
        # unidade 101: NPS 20 (n=10) contra setembro (n=2, NPS 100); z = -2,90 em seleção
        _, v, r = self.one({"type": "C", "query_id": qid, "select": {"unit": 101}, "framing": "fact"})
        self.assertEqual((v, r["classification"], r["z"]), ("ajuste", "signal_to_monitor", -2.9))
        _, v, _ = self.one({"type": "C", "query_id": qid, "select": {"unit": 101}, "framing": "signal"})
        self.assertEqual(v, "confere")

    def test_T_composition_uses_independent_counts(self):
        qid = self.run_cli("query", "--metric", "nps", "--survey", 56, "--question", fx.NPS, "--start", "2026-09-01",
                           "--end", "2026-10-31", "--group-by", "month")["query_id"]
        rep, v, r = self.one({"type": "T", "query_id": qid, "bucket": "month", "direction": "down"})
        self.assertEqual(r["verdict_composition"], "no_composition_effect")
        self.assertEqual(r["steps"][0]["delta_aggregate"], -85.0)
        self.assertEqual(v, "confere")

    def test_G_small_group(self):
        _, v, r = self.one({"type": "G", "query_id": self.nps_q, "group": {"state": "PR"}})
        self.assertEqual(v, "ajuste")                          # 1 unidade ativa
        _, v, _ = self.one({"type": "G", "query_id": self.nps_q, "group": {"state": "SP"}})
        self.assertEqual(v, "ajuste")                          # 2 unidades ativas (101 e 102)

    # ---------------------------------------------------------------- D / U
    def test_D_rate_per_day_and_business_day(self):
        base = {"type": "D", "query_id": self.eval_q, "extraction_time": "2026-11-17T12:00"}
        rep, v, r = self.one({**base, "per": "day", "shown": "0,6"})        # 20 / 31
        self.assertEqual(v, "confere")
        self.assertEqual(r["business_days"], "22.00")
        _, v, _ = self.one({**base, "per": "business_day", "shown": "0,9"})  # 20 / 22
        self.assertEqual(v, "confere")
        _, v, _ = self.one({**base, "per": "day", "shown": "1,2"})
        self.assertEqual(v, "correcao")

    def test_U_unit_without_evaluations_and_plan_criterion(self):
        _, v, r = self.one({"type": "U", "query_id": self.eval_q, "unit": 104, "kind": "interrupted"})
        self.assertEqual(v, "ajuste")
        self.assertEqual(r["n"], 0)
        _, v, _ = self.one({"type": "U", "query_id": self.nps_q, "unit": 101, "kind": "criterion",
                            "criterion": {"op": "<", "value": 50}})
        self.assertEqual(v, "confere")
        _, v, _ = self.one({"type": "U", "query_id": self.nps_q, "unit": 102, "kind": "criterion",
                            "criterion": {"op": "<", "value": 50}})
        self.assertEqual(v, "ajuste")                         # 102 tem NPS 100

    # ------------------------------------------------------- estrutura geral
    def test_every_claim_gets_a_verdict_and_unchecked_types_are_explicit(self):
        rep = self.validate(
            {"type": "N", "query_id": self.nps_q, "select": {}, "shown": "15", "id": "a"},
            {"type": "Z", "text": "tipo que não existe", "id": "b"},
            {"type": "N", "shown": "7", "id": "c", "text": "número sem fonte"},
        )
        self.assertEqual(len(rep["annex"]), 3)
        by_id = {a["id"]: a["verdict"] for a in rep["annex"]}
        self.assertEqual(by_id, {"a": "confere", "b": "nao_verificado", "c": "correcao"})
        self.assertEqual(rep["verdict"], "do_not_send_as_is")
        self.assertIn("Decisão do usuário", rep["parecer_md"])

    def test_all_good_needs_no_decision(self):
        rep = self.validate({"type": "N", "query_id": self.nps_q, "select": {}, "shown": "15"})
        self.assertEqual(rep["verdict"], "can_send")
        self.assertFalse(rep["decision_required"])
        self.assertEqual(rep["options"], [])

    def test_cache_refresh_after_query_is_flagged(self):
        time.sleep(1.1)  # fetched_at tem resolução de segundos
        self.run_cli("sync", "--survey", 56, "--period", "month:2026-10", "--refresh")
        rep = self.validate({"type": "N", "query_id": self.nps_q, "select": {}, "shown": "15"})
        self.assertTrue(rep["how_checked"]["queries"][0]["cache_changed_since_query"])

    def test_duplicate_ids_and_empty_claims_are_rejected(self):
        path = os.path.join(self.tmp, "bad.json")
        for payload in ({"claims": []}, {"claims": [{"id": "x", "type": "L"}, {"id": "x", "type": "L"}]}):
            with open(path, "w", encoding="utf-8") as fh:
                json.dump(payload, fh)
            buf = io.StringIO()
            with redirect_stdout(buf):
                code = cli.main(["validate", "--claims", path])
            self.assertEqual(code, 2)


if __name__ == "__main__":
    unittest.main()
