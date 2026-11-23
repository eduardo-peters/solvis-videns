"""Texto de perguntas LGPD: a decisão é do usuário, perguntada no primeiro uso. Só é guardado (mascarado)
depois que ele autoriza (`config --lgpd-text on`); enquanto não decide, `lgpd_text_decided` é falso."""

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

LGPD_Q = 901


class LgpdTextTest(unittest.TestCase):
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

    def tearDown(self):
        self.env.stop()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def run_cli(self, *args):
        buf = io.StringIO()
        with redirect_stdout(buf):
            code = cli.main([str(a) for a in args])
        self.assertEqual(code, 0, buf.getvalue())
        return json.loads(buf.getvalue())

    def comments(self):
        return self.run_cli("comments", "--survey", 57, "--question", LGPD_Q, "--period", "month:2026-10")

    def test_default_never_stores_lgpd_text(self):
        body = self.comments()
        self.assertEqual(body["total_matching"], 0)
        self.assertTrue(any("ainda não decidiu" in n for n in body["notes"]))   # pede para perguntar, não assume "não"
        cfg = self.run_cli("config")
        self.assertEqual((cfg["lgpd_text"], cfg["lgpd_text_decided"]), (False, False))
        env = self.run_cli("query", "--metric", "evaluation_count", "--survey", 57, "--period", "month:2026-10")
        self.assertEqual(env["policies"]["lgpd"], "aggregates_only")

    def test_opt_in_stores_masked_text_and_clears_cache(self):
        self.comments()  # baixa o dia sem o texto
        out = self.run_cli("config", "--lgpd-text", "on")
        self.assertTrue(out["lgpd_text"] and out["cache_cleared"] and out["lgpd_text_consent_at"])
        self.assertEqual(out["start_month"], "2025-01")  # a configuração não se perde
        body = self.comments()
        self.assertEqual(body["total_matching"], 1)
        c = body["comments"][0]
        self.assertTrue(c["lgpd_protected"])
        self.assertIn("[telefone]", c["text"])
        self.assertNotIn("98765", c["text"])           # o mascaramento continua valendo
        self.assertTrue(any("autorizou" in n for n in body["notes"]))
        env = self.run_cli("query", "--metric", "evaluation_count", "--survey", 57, "--period", "month:2026-10")
        self.assertEqual(env["policies"]["lgpd"], "text_enabled_masked")
        self.assertTrue(self.run_cli("scope")["capabilities"]["lgpd_texts"])

    def test_validate_finds_lgpd_quotes_only_after_opt_in(self):
        def cite():
            qid = self.run_cli("comments", "--survey", 57, "--period", "month:2026-10")["query_id"]
            path = os.path.join(self.tmp, "c.json")
            with open(path, "w", encoding="utf-8") as fh:
                json.dump({"claims": [{"type": "V", "query_id": qid, "quote": "Entregador atrasou, ligue 11 98765-4321",
                                       "unit": "Loja Centro", "date": "2026-10-03"}]}, fh)
            return self.run_cli("validate", "--claims", path)
        self.assertEqual(cite()["summary"]["correcao"], 1)
        self.run_cli("config", "--lgpd-text", "on")
        rep = cite()
        self.assertEqual(rep["summary"]["confere"], 1)
        self.assertIn("autorização", rep["how_checked"]["lgpd_text"])

    def test_declining_is_recorded_without_clearing_the_cache(self):
        self.comments()
        out = self.run_cli("config", "--lgpd-text", "off")
        self.assertEqual((out["lgpd_text"], out["lgpd_text_decided"]), (False, True))
        self.assertNotIn("cache_cleared", out)
        body = self.comments()
        self.assertTrue(any("optou por não guardar" in n for n in body["notes"]))
        all_comments = self.run_cli("comments", "--survey", 57, "--period", "month:2026-10")
        self.assertTrue(any("optou por não guardar" in n for n in all_comments["notes"]))

    def test_opt_out_removes_the_text_again(self):
        self.run_cli("config", "--lgpd-text", "on")
        self.assertEqual(self.comments()["total_matching"], 1)
        out = self.run_cli("config", "--lgpd-text", "off")
        self.assertTrue(out["cache_cleared"])
        self.assertEqual(self.comments()["total_matching"], 0)

    def test_repeating_the_same_choice_does_not_clear_the_cache(self):
        self.run_cli("config", "--lgpd-text", "on")
        self.comments()
        out = self.run_cli("config", "--lgpd-text", "on")
        self.assertNotIn("cache_cleared", out)

    def test_personal_types_never_store_text_even_when_enabled(self):
        self.run_cli("config", "--lgpd-text", "on")
        self.run_cli("sync", "--survey", 56, "--period", "month:2026-10")
        import sqlite3
        db = sqlite3.connect(os.path.join(self.tmp, next(d for d in os.listdir(self.tmp) if os.path.isdir(os.path.join(self.tmp, d))),
                                          "cache.sqlite3"))
        leaked = db.execute("SELECT COUNT(*) FROM answers WHERE text LIKE '%cliente@exemplo.com%'").fetchone()[0]
        self.assertEqual(leaked, 0)


if __name__ == "__main__":
    unittest.main()
