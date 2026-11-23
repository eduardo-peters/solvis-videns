"""Desempenho e robustez do download: janelas em paralelo, página de 10.000, `--until-complete`,
timeout de leitura retentado e estatísticas do planejador no cache."""

import http.client
import io
import json
import os
import shutil
import socket
import sqlite3
import sys
import tempfile
import unittest
import urllib.request
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

HERE = os.path.dirname(__file__)
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "..", "..", "skills", "solvis-videns", "scripts"))

import fixture as fx  # noqa: E402
from solvis_pilot import api, cli, sync  # noqa: E402


class SyncSpeedTest(unittest.TestCase):
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
        self.ok("config", "--start-month", "2025-01")

    def tearDown(self):
        self.env.stop()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def run_cli(self, *args):
        buf = io.StringIO()
        with redirect_stdout(buf):
            code = cli.main([str(a) for a in args])
        return code, json.loads(buf.getvalue())

    def ok(self, *args):
        code, body = self.run_cli(*args)
        self.assertEqual(code, 0, body)
        return body

    def cache_db(self) -> sqlite3.Connection:
        files = list(Path(self.tmp).glob("*/cache.sqlite3"))
        self.assertEqual(len(files), 1, files)
        return sqlite3.connect(str(files[0]))

    # ------------------------------------------------------- janelas em paralelo
    def test_parallel_windows_give_the_same_counts_as_sequential(self):
        # página de 10 força dezenas de janelas; 3 threads contra 1 devem dar o mesmo total sem duplicar
        with mock.patch.object(sync, "PER_PAGE", 10), mock.patch.dict(os.environ, {"SOLVIS_SYNC_WORKERS": "3"}):
            env = self.ok("query", "--metric", "evaluation_count", "--survey", 61, "--start", "2026-11-01",
                          "--end", "2026-11-04")
        self.assertEqual(env["totals"]["value"], 100)
        with mock.patch.object(sync, "PER_PAGE", 10), mock.patch.dict(os.environ, {"SOLVIS_SYNC_WORKERS": "1"}):
            env = self.ok("query", "--metric", "evaluation_count", "--survey", 61, "--start", "2026-11-01",
                          "--end", "2026-11-04", "--refresh")
        self.assertEqual(env["totals"]["value"], 100)

    def test_page_size_is_the_api_limit(self):
        self.assertEqual(sync.PER_PAGE, 10000)
        self.ok("query", "--metric", "evaluation_count", "--survey", 61, "--start", "2026-11-01", "--end", "2026-11-01")
        pages = [r for r in self.fake.requests if "evaluations_with_tags" in r["path"]]
        self.assertTrue(pages)
        self.assertEqual(pages[-1]["params"]["per_page"], "10000")

    # ------------------------------------------------------------ until-complete
    def test_until_complete_stops_when_a_round_makes_no_progress(self):
        report = self.ok("sync", "--survey", 56, "--period", "last_90_days", "--budget", "0", "--until-complete")
        self.assertFalse(report["complete"])
        self.assertEqual(report["rounds"], 2)  # a segunda rodada não avançou: para em vez de girar para sempre
        self.assertEqual(report["days_fetched"], 0)

    def test_until_complete_finishes_a_long_period_in_several_rounds(self):
        with mock.patch.object(sync, "MAX_CHUNK_DAYS", 2):
            report = self.ok("sync", "--survey", 56, "--period", "last_90_days", "--budget", "0.05", "--until-complete")
        self.assertTrue(report["complete"])
        self.assertEqual(report["days_remaining"], 0)
        self.assertEqual(report["days_fetched"], 90)
        self.assertGreaterEqual(report["rounds"], 1)
        self.assertEqual(report["coverage"]["days_missing"], 0)

    # ----------------------------------------------------- timeout retentado
    def test_read_timeout_and_broken_response_are_retried(self):
        real = urllib.request.urlopen
        failures = [socket.timeout("The read operation timed out"), http.client.IncompleteRead(b"")]

        def flaky(req, timeout=None):
            if failures:
                raise failures.pop(0)
            return real(req, timeout=timeout)

        with mock.patch.object(api.urllib.request, "urlopen", side_effect=flaky), \
                mock.patch.object(api, "RETRY_DELAYS_S", (0, 0, 0)):
            body = self.ok("scope")
        self.assertIn("surveys", body)
        self.assertEqual(failures, [])

    # -------------------------------------------------- estatísticas no cache
    def test_cache_has_covering_index_and_statistics_after_sync(self):
        self.ok("query", "--metric", "nps", "--survey", 56, "--question", fx.NPS, "--period", "month:2026-10")
        db = self.cache_db()
        names = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='index' AND tbl_name='answers'")}
        self.assertIn("ans_ev_q", names)
        self.assertNotIn("ans_ev", names)
        self.assertTrue(db.execute("SELECT 1 FROM sqlite_stat1 LIMIT 1").fetchone())
        plan = [r[3] for r in db.execute(
            "EXPLAIN QUERY PLAN SELECT COUNT(*) FROM evaluations e JOIN answers a ON a.survey_id = e.survey_id "
            "AND a.eval_ref = e.eval_ref AND a.question_id = ? WHERE e.survey_id = ? AND e.day BETWEEN ? AND ?",
            (fx.NPS, 56, "2026-10-01", "2026-10-31"))]
        self.assertTrue(any("ans_ev_q" in p for p in plan), plan)
        db.close()

    def test_old_cache_without_statistics_is_analyzed_on_open(self):
        self.ok("query", "--metric", "nps", "--survey", 56, "--question", fx.NPS, "--period", "month:2026-10")
        db = self.cache_db()
        db.execute("DROP TABLE sqlite_stat1")
        db.commit()
        db.close()
        self.ok("scope")  # qualquer comando abre o cache e refaz as estatísticas
        db = self.cache_db()
        self.assertTrue(db.execute("SELECT 1 FROM sqlite_stat1 LIMIT 1").fetchone())
        db.close()


if __name__ == "__main__":
    unittest.main()
