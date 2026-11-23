"""Atualização incremental por created_at (search_date_scope=received_at), com relógio controlado."""

import datetime as dt
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
sys.path.insert(0, os.path.join(HERE, "..", "..", "skills", "solvis-videns", "scripts"))

import fixture as fx  # noqa: E402
from solvis_pilot import cli  # noqa: E402

SURVEY = 70
QUESTION = 7001


def utc(day, hh, mm=0):
    return dt.datetime(2026, 11, day, hh, mm)


class IncrementalTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fake = fx.build()
        cls.fake.add_survey(SURVEY, "Pesquisa Incremental", [fx._q(QUESTION, 0, "Nota", "NPS")])
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
        with redirect_stdout(io.StringIO()):
            cli.main(["config", "--start-month", "2025-01"])
        self.fake.evaluations = [e for e in self.fake.evaluations if e["survey_id"] != SURVEY]
        self.add(utc(16, 10), created=utc(16, 13))   # dia anterior, ainda "nao assentado"
        self.add(utc(17, 8), created=utc(17, 11))    # hoje, recebida antes do primeiro download

    def tearDown(self):
        self.env.stop()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def add(self, started, created):
        self.fake.add_eval(SURVEY, 101, started, [(QUESTION, None, 10, None)])
        self.fake.evaluations[-1]["created_at"] = created

    def at(self, day, hh, mm=0):
        """Fixa o relógio (UTC) usado para fetched_at e para a idade do cache."""
        return mock.patch("solvis_pilot.store.now_utc", return_value=utc(day, hh, mm).isoformat() + "+00:00")

    def count(self):
        buf = io.StringIO()
        with redirect_stdout(buf):
            code = cli.main(["query", "--metric", "evaluation_count", "--survey", str(SURVEY),
                             "--start", "2026-11-16", "--end", "2026-11-17"])
        body = json.loads(buf.getvalue())
        self.assertEqual(code, 0, body)
        return body["totals"]["value"]

    def requests_since(self, mark):
        return [r["params"] for r in self.fake.evaluation_requests()[mark:]]

    def test_recent_days_are_updated_with_only_what_was_received_since(self):
        with self.at(17, 12):
            self.assertEqual(self.count(), 2)
        self.add(utc(17, 9, 30), created=utc(17, 12, 30))
        mark = len(self.fake.evaluation_requests())
        with self.at(17, 13, 30):
            self.assertEqual(self.count(), 3)
        calls = self.requests_since(mark)
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0]["search_date_scope"], "received_at")
        self.assertEqual(calls[0]["start_date"], "2026-11-17T11:55:00")  # 12:00 do ultimo download - 5 min
        self.assertEqual(calls[0]["end_date"], "2026-11-17T13:30:00")

    def test_overlap_with_the_previous_download_is_not_counted_twice(self):
        self.add(utc(17, 8, 57), created=utc(17, 11, 57))  # recebida nos 5 min antes do primeiro download
        with self.at(17, 12):
            self.assertEqual(self.count(), 3)
        self.add(utc(17, 9, 30), created=utc(17, 12, 10))
        mark = len(self.fake.evaluation_requests())
        with self.at(17, 12, 20):
            self.assertEqual(self.count(), 4)  # a janela (11:55) traz a de 11:57 de novo; ela nao conta duas vezes
        self.assertEqual(self.requests_since(mark)[0]["start_date"], "2026-11-17T11:55:00")
    def test_fresh_days_cost_no_request(self):
        with self.at(17, 12):
            self.count()
        mark = len(self.fake.evaluation_requests())
        with self.at(17, 12, 5):
            self.assertEqual(self.count(), 2)
        self.assertEqual(self.requests_since(mark), [])

    def test_late_evaluation_for_an_unsettled_day_is_added(self):
        with self.at(17, 12):
            self.assertEqual(self.count(), 2)
        self.add(utc(16, 18), created=utc(17, 12, 40))  # totem offline: started_at de ontem, recebida hoje
        with self.at(17, 13, 30):
            self.assertEqual(self.count(), 3)

    def test_gap_longer_than_a_week_downloads_the_days_whole(self):
        with self.at(17, 12):
            self.count()
        mark = len(self.fake.evaluation_requests())
        with mock.patch.dict(os.environ, {"SOLVIS_TODAY": "2026-11-27"}):
            with self.at(27, 12):
                body_total = self.count()
        calls = self.requests_since(mark)
        self.assertTrue(calls)
        self.assertTrue(all("search_date_scope" not in c for c in calls))
        self.assertEqual(body_total, 2)

    def test_failed_window_falls_back_to_full_day_download(self):
        with self.at(17, 12):
            self.assertEqual(self.count(), 2)
        self.add(utc(17, 9, 30), created=utc(17, 12, 30))
        self.fake.evaluations[-1]["bad_unit"] = True  # a janela por created_at falha (HTTP 400)
        with self.at(17, 13, 30):
            self.assertEqual(self.count(), 2)  # nada some; o dia fica parcial em vez de ser dado como atual


if __name__ == "__main__":
    unittest.main()
