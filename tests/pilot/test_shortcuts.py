"""Atalhos: setup (credencial no .env e mês inicial), unit (/unidade) e update (/atualizar)."""

import io
import json
import os
import shutil
import stat
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

HERE = os.path.dirname(__file__)
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "..", "..", "skills", "solvis-videns", "scripts"))

import fixture as fx  # noqa: E402
from solvis_pilot import cli, config  # noqa: E402


class ShortcutsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fake = fx.build()
        cls.base_url = cls.fake.start()

    @classmethod
    def tearDownClass(cls):
        cls.fake.stop()

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.env_path = os.path.join(self.tmp, "config", ".env")
        patcher = mock.patch.dict(os.environ, {
            "SOLVIS_API_BASE_URL": self.base_url,
            "SOLVIS_CACHE_DIR": os.path.join(self.tmp, "cache"),
            "SOLVIS_ENV_FILE": self.env_path,
            "SOLVIS_CONTEXT_DIR": os.path.join(self.tmp, "config"),
            "SOLVIS_BRAND_DIR": os.path.join(self.tmp, "config", "brand"),
            "SOLVIS_CREDENTIALS_FILE": os.path.join(self.tmp, "nao-existe.json"),
            "SOLVIS_TODAY": "2026-11-17",
        })
        patcher.start()
        self.addCleanup(patcher.stop)
        for k in ("SOLVIS_API_USERNAME", "SOLVIS_API_PASSWORD"):
            os.environ.pop(k, None)
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def run_cli(self, *args, stdin=None):
        buf = io.StringIO()
        with redirect_stdout(buf):
            if stdin is not None:
                with mock.patch("sys.stdin", io.StringIO(stdin)):
                    code = cli.main([str(a) for a in args])
            else:
                code = cli.main([str(a) for a in args])
        return code, json.loads(buf.getvalue())

    def configure(self, start="2025-01"):
        code, _ = self.run_cli("setup", "--username", self.fake.username, "--password", self.fake.password,
                               "--start-month", start)
        self.assertEqual(code, 0)

    # ---------------------------------------------------------------- setup
    def test_setup_status_without_credentials(self):
        code, body = self.run_cli("setup")
        self.assertEqual(code, 0)
        self.assertFalse(body["credentials_configured"])
        self.assertIn("next_step", body)

    def test_missing_credentials_error_points_to_setup(self):
        code, body = self.run_cli("scope")
        self.assertEqual(body["error"]["code"], "missing_credentials")
        self.assertIn("setup", body["error"]["hint"])

    def test_setup_saves_env_and_never_prints_password(self):
        buf = io.StringIO()
        with redirect_stdout(buf):
            code = cli.main(["setup", "--username", self.fake.username, "--password", self.fake.password])
        body = json.loads(buf.getvalue())
        self.assertEqual(code, 0)
        self.assertTrue(body["saved"] and body["credentials_configured"])
        self.assertEqual(body["credentials_source"], self.env_path)
        self.assertNotIn(self.fake.password, buf.getvalue())
        self.assertIsNone(body["start_month"])
        self.assertIn("next_step", body)
        saved = Path(self.env_path).read_text(encoding="utf-8")
        self.assertIn('SOLVIS_API_PASSWORD="%s"' % self.fake.password, saved)
        if os.name == "posix":
            self.assertEqual(stat.S_IMODE(os.stat(self.env_path).st_mode), 0o600)
        # a partir daqui o motor encontra a credencial sozinho
        self.assertEqual(self.run_cli("config")[0], 0)

    def test_setup_password_from_stdin(self):
        with mock.patch("sys.stdin", io.StringIO(self.fake.password + "\n")):
            code, body = self.run_cli("setup", "--username", self.fake.username, "--password", "-")
        self.assertEqual(code, 0)
        self.assertTrue(body["saved"])

    def test_setup_wrong_password_saves_nothing(self):
        code, body = self.run_cli("setup", "--username", self.fake.username, "--password", "errada")
        self.assertEqual(body["error"]["code"], "auth_failed")
        self.assertFalse(os.path.exists(self.env_path))

    def test_setup_sets_start_month(self):
        self.configure("2026-03")
        code, body = self.run_cli("setup")
        self.assertEqual(body["start_month"], "2026-03")
        # com credencial e mês inicial, falta só a decisão sobre o texto LGPD: o setup pede para perguntar
        self.assertFalse(body["lgpd_text_decided"])
        self.assertIn("LGPD", body["next_step"])
        code, body = self.run_cli("setup", "--lgpd-text", "off")
        self.assertEqual(code, 0)
        self.assertEqual((body["lgpd_text"], body["lgpd_text_decided"]), (False, True))
        self.assertNotIn("cache_cleared", body)   # "não" não muda a política: nada a baixar de novo
        # falta o contexto do cliente: o setup pede para perguntar
        self.assertEqual(body["client_context"]["status"], "not_asked")
        self.assertIn("quem é o cliente", body["next_step"])
        self.run_cli("context", "--file", "-", stdin="# Rede Exemplo\n\nVarejo de moda, 120 lojas.")
        code, body = self.run_cli("setup")
        self.assertEqual(body["client_context"]["status"], "configured")
        self.assertNotIn("next_step", body)

    def test_setup_lgpd_yes_records_consent(self):
        self.configure("2026-03")
        code, body = self.run_cli("setup", "--lgpd-text", "on")
        self.assertEqual(code, 0)
        self.assertTrue(body["lgpd_text"] and body["lgpd_text_decided"] and body["lgpd_text_consent_at"])
        self.assertTrue(body["cache_cleared"])
        self.assertIn("baixados de novo", body["next_step"])

    def test_start_month_without_credentials_is_refused(self):
        code, body = self.run_cli("setup", "--start-month", "2026-03")
        self.assertEqual(body["error"]["code"], "missing_credentials")

    def test_env_file_roundtrip_keeps_other_lines_and_special_chars(self):
        Path(self.env_path).parent.mkdir(parents=True)
        Path(self.env_path).write_text('# meu\nOUTRA=1\nSOLVIS_API_USERNAME=velho\n', encoding="utf-8")
        tricky = 'se"nh\\a #$ \'x\''
        config.write_env_file({"SOLVIS_API_USERNAME": "novo", "SOLVIS_API_PASSWORD": tricky})
        text = Path(self.env_path).read_text(encoding="utf-8")
        self.assertIn("# meu\nOUTRA=1\n", text)
        self.assertEqual(text.count("SOLVIS_API_USERNAME"), 1)
        parsed = config.parse_env_file(Path(self.env_path))
        self.assertEqual(parsed, {"SOLVIS_API_USERNAME": "novo", "SOLVIS_API_PASSWORD": tricky})

    def test_environment_variables_win_over_env_file(self):
        self.configure()
        with mock.patch.dict(os.environ, {"SOLVIS_API_USERNAME": "x", "SOLVIS_API_PASSWORD": "y"}):
            self.assertEqual(config.load_settings().username, "x")
            self.assertEqual(config.credentials_source(), "environment")

    # ----------------------------------------------------------------- unit
    def test_unit_report_compares_unit_with_network(self):
        self.configure()
        code, body = self.run_cli("unit", "Loja Centro", "--period", "month:2026-10")
        self.assertEqual(code, 0, body)
        self.assertEqual(body["unit"]["id"], 101)
        survey = next(s for s in body["surveys"] if s["survey"]["id"] == 56)
        self.assertGreater(survey["evaluation_count"]["totals"]["value"], 0)
        nps = next(q for q in survey["questions"] if q["metric"] == "nps")
        self.assertIn("query_id", nps["unit"])
        self.assertGreaterEqual(nps["network"]["totals"]["n"], nps["unit"]["totals"]["n"])
        # a unidade 101 tem os mesmos números da consulta direta
        direct = self.run_cli("query", "--metric", "nps", "--survey", 56, "--question", nps["question"]["id"],
                              "--period", "month:2026-10", "--unit", 101, "--compare-with", "previous_period")[1]
        self.assertEqual(direct["totals"], nps["unit"]["totals"])

    def test_unit_ambiguous_name_asks_for_choice(self):
        self.configure()
        code, body = self.run_cli("unit", "Centro", "--period", "month:2026-10")
        self.assertEqual(code, 0)
        self.assertTrue(body["needs_choice"])
        self.assertGreater(len(body["candidates"]), 1)

    def test_unit_by_id(self):
        self.configure()
        body = self.run_cli("unit", "--unit-id", 104, "--period", "month:2026-10", "--survey", 56)[1]
        self.assertEqual(body["unit"]["label"], "Loja Sul")

    def test_unit_requires_start_month(self):
        self.run_cli("setup", "--username", self.fake.username, "--password", self.fake.password)
        code, body = self.run_cli("unit", "Loja Centro", "--period", "month:2026-10")
        self.assertEqual(body["error"]["code"], "start_month_required")

    # --------------------------------------------------------------- update
    def test_update_downloads_then_skips_recent_refresh(self):
        self.configure()
        code, first = self.run_cli("update")
        self.assertEqual(code, 0, first)
        self.assertTrue(first["complete"])
        self.assertGreater(first["surveys_total"], 0)
        self.assertGreater(sum(s["days_fetched"] for s in first["surveys"]), 0)
        self.assertTrue(all(s["recent_days_refreshed"] for s in first["surveys"]))
        _, second = self.run_cli("update")
        self.assertFalse(any(s["recent_days_refreshed"] for s in second["surveys"]))
        _, forced = self.run_cli("update", "--force")
        self.assertTrue(all(s["recent_days_refreshed"] for s in forced["surveys"]))

    def test_update_requires_start_month(self):
        self.run_cli("setup", "--username", self.fake.username, "--password", self.fake.password)
        code, body = self.run_cli("update")
        self.assertEqual(body["error"]["code"], "start_month_required")


if __name__ == "__main__":
    unittest.main()
