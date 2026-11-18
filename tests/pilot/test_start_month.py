"""Mês inicial da análise: sem ele nada é baixado, e nada antes dele é pedido à API."""

import io
import json
import os
import shutil
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from unittest import mock

HERE = os.path.dirname(__file__)
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "..", "..", "skills", "solvis-survey-analysis-pilot", "scripts"))

import fixture as fx  # noqa: E402
from solvis_pilot import cli  # noqa: E402


class StartMonthTest(unittest.TestCase):
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
            "SOLVIS_API_BASE_URL": self.base_url,
            "SOLVIS_API_USERNAME": self.fake.username,
            "SOLVIS_API_PASSWORD": self.fake.password,
            "SOLVIS_CACHE_DIR": self.tmp,
            "SOLVIS_TODAY": "2026-11-17",
        })
        self.env.start()
        self.mark = len(self.fake.requests)

    def tearDown(self):
        self.env.stop()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def run_cli(self, *args):
        buf = io.StringIO()
        with redirect_stdout(buf):
            code = cli.main([str(a) for a in args])
        return code, json.loads(buf.getvalue())

    def evaluation_calls(self):
        return [r for r in self.fake.evaluation_requests() if r in self.fake.requests[self.mark:]]

    def nps(self, *extra, period="month:2026-10"):
        return self.run_cli("query", "--metric", "nps", "--survey", 56, "--question", fx.NPS,
                            "--period", period, *extra)

    def test_without_start_month_nothing_is_downloaded(self):
        code, body = self.nps()
        self.assertEqual(code, 2)
        self.assertEqual(body["error"]["code"], "start_month_required")
        self.assertIn("config --start-month", body["error"]["hint"])
        self.assertEqual(self.evaluation_calls(), [])
        code, body = self.run_cli("comments", "--survey", 56, "--period", "month:2026-10")
        self.assertEqual(body["error"]["code"], "start_month_required")
        code, body = self.run_cli("sync", "--survey", 56, "--period", "month:2026-10")
        self.assertEqual(body["error"]["code"], "start_month_required")

    def test_scope_and_config_show_the_start_month(self):
        self.assertIsNone(self.run_cli("scope")[1]["start_month"])
        code, body = self.run_cli("config", "--start-month", "2026-10")
        self.assertEqual((code, body), (0, {"start_month": "2026-10", "earliest_day": "2026-10-01"}))
        self.assertEqual(self.run_cli("config")[1]["start_month"], "2026-10")
        self.assertEqual(self.run_cli("scope")[1]["earliest_day"], "2026-10-01")

    def test_invalid_start_month_is_refused(self):
        for value in ("outubro", "2026-13", "2026-12"):  # 2026-12 é futuro (hoje = 2026-11-17)
            code, body = self.run_cli("config", "--start-month", value)
            self.assertEqual((code, body["error"]["code"]), (2, "invalid_argument"), value)
        self.assertIsNone(self.run_cli("config")[1]["start_month"])

    def test_period_before_the_start_month_is_refused_without_calling_the_api(self):
        self.run_cli("config", "--start-month", "2026-10")
        mark = len(self.fake.evaluation_requests())
        code, body = self.nps(period="month:2026-09")
        self.assertEqual((code, body["error"]["code"]), (2, "period_before_start"))
        self.assertEqual(body["error"]["details"]["earliest_day"], "2026-10-01")
        code, body = self.nps(period="last_year")
        self.assertEqual(body["error"]["code"], "period_before_start")
        self.assertEqual(len(self.fake.evaluation_requests()), mark)

    def test_comparison_before_the_start_month_is_refused(self):
        self.run_cli("config", "--start-month", "2026-10")
        code, body = self.nps("--compare-with", "previous_year")
        self.assertEqual((code, body["error"]["code"]), (2, "period_before_start"))

    def test_period_from_the_start_month_on_works_and_only_those_days_are_requested(self):
        self.run_cli("config", "--start-month", "2026-10")
        code, body = self.nps()
        self.assertEqual(code, 0, body)
        self.assertEqual(body["totals"]["value"], 15)
        starts = {r["params"]["start_date"] for r in self.fake.evaluation_requests()[-5:]}
        self.assertTrue(all(s >= "2026-10-01" for s in starts), starts)

    def test_moving_the_start_month_back_allows_older_periods(self):
        self.run_cli("config", "--start-month", "2026-10")
        self.assertEqual(self.nps(period="month:2025-10")[1]["error"]["code"], "period_before_start")
        self.run_cli("config", "--start-month", "2025-10")
        code, body = self.nps(period="month:2025-10")
        self.assertEqual(code, 0, body)

    def test_tag_results_warn_that_tags_follow_the_last_download(self):
        self.run_cli("config", "--start-month", "2026-10")
        code, body = self.run_cli("query", "--metric", "tag_mentions", "--survey", 56, "--question", fx.COMENT,
                                  "--period", "month:2026-10")
        self.assertEqual(code, 0, body)
        self.assertIn("tags_as_of_last_sync", {w["code"] for w in body["warnings"]})
        code, body = self.run_cli("comments", "--survey", 56, "--period", "month:2026-10", "--tag", fx.FILA)
        self.assertEqual(code, 0, body)
        self.assertTrue(any("tags valem" in n for n in body["notes"]))
        code, body = self.nps()
        self.assertNotIn("tags_as_of_last_sync", {w["code"] for w in body["warnings"]})


if __name__ == "__main__":
    unittest.main()
