"""Perfil de marca: a skill guarda o que aprendeu dos materiais de referência do cliente (na pasta de trabalho)."""

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


class BrandTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fake = fx.build()
        cls.base_url = cls.fake.start()

    @classmethod
    def tearDownClass(cls):
        cls.fake.stop()

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.brand_dir = os.path.join(self.tmp, "config", "brand")
        self.env = mock.patch.dict(os.environ, {
            "SOLVIS_API_BASE_URL": self.base_url, "SOLVIS_API_USERNAME": self.fake.username,
            "SOLVIS_API_PASSWORD": self.fake.password, "SOLVIS_CACHE_DIR": os.path.join(self.tmp, "cache"),
            "SOLVIS_ENV_FILE": os.path.join(self.tmp, "config", ".env"),
            "SOLVIS_BRAND_DIR": self.brand_dir, "SOLVIS_TODAY": "2026-11-17",
        })
        self.env.start()

    def tearDown(self):
        self.env.stop()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def run_cli(self, *args, stdin=None):
        buf = io.StringIO()
        with redirect_stdout(buf):
            if stdin is not None:
                with mock.patch("sys.stdin", io.StringIO(stdin)):
                    code = cli.main([str(a) for a in args])
            else:
                code = cli.main([str(a) for a in args])
        return code, json.loads(buf.getvalue())

    def test_not_asked_until_the_skill_records_something(self):
        code, body = self.run_cli("brand")
        self.assertEqual((code, body["status"], body["profile"], body["assets"]), (0, "not_asked", {}, []))
        self.assertEqual(self.run_cli("setup")[1]["brand_profile"]["status"], "not_asked")
        self.assertIn("colors", body["suggested_keys"])

    def test_profile_from_stdin_is_saved_and_merged(self):
        profile = {"client_name": "Rede Exemplo", "colors": {"primary": "#0A3D62"}, "sources": ["manual da marca v3"]}
        code, body = self.run_cli("brand", "--file", "-", stdin=json.dumps(profile))
        self.assertEqual((code, body["saved"], body["status"]), (0, True, "configured"))
        self.assertEqual(body["profile"]["colors"]["primary"], "#0A3D62")
        self.assertTrue(body["profile"]["updated_at"])
        self.assertTrue(os.path.exists(os.path.join(self.brand_dir, "profile.json")))
        # uma segunda gravação mescla, sem perder o que já havia
        code, body = self.run_cli("brand", "--file", "-", stdin=json.dumps({"fonts": {"body": "Inter"}}))
        self.assertEqual(body["profile"]["client_name"], "Rede Exemplo")
        self.assertEqual(body["profile"]["fonts"]["body"], "Inter")
        self.assertEqual(self.run_cli("setup")[1]["brand_profile"]["status"], "configured")

    def test_assets_are_copied_next_to_the_profile(self):
        logo = os.path.join(self.tmp, "logo.svg")
        with open(logo, "w", encoding="utf-8") as fh:
            fh.write("<svg/>")
        code, body = self.run_cli("brand", "--asset", logo)
        self.assertEqual(code, 0)
        self.assertEqual([a["file"] for a in body["assets"]], ["logo.svg"])
        self.assertEqual(body["profile"]["assets"], ["logo.svg"])
        self.assertTrue(os.path.exists(os.path.join(self.brand_dir, "logo.svg")))
        self.assertEqual(body["status"], "configured")
        code, body = self.run_cli("brand", "--asset", os.path.join(self.tmp, "nao-existe.png"))
        self.assertEqual((code, body["error"]["code"]), (2, "invalid_argument"))

    def test_none_records_the_answer_and_a_later_profile_replaces_it(self):
        code, body = self.run_cli("brand", "--none")
        self.assertEqual((code, body["status"]), (0, "none"))
        self.assertEqual(self.run_cli("setup")[1]["brand_profile"]["status"], "none")
        code, body = self.run_cli("brand", "--file", "-", stdin='{"client_name": "Rede Exemplo"}')
        self.assertEqual(body["status"], "configured")
        self.assertNotIn("none", body["profile"])

    def test_clear_removes_everything(self):
        self.run_cli("brand", "--file", "-", stdin='{"client_name": "Rede Exemplo"}')
        code, body = self.run_cli("brand", "--clear")
        self.assertEqual((code, body["cleared"], body["status"], body["assets"]), (0, True, "not_asked", []))
        self.assertFalse(os.path.exists(self.brand_dir))

    def test_invalid_profile_is_refused(self):
        code, body = self.run_cli("brand", "--file", "-", stdin="[1, 2]")
        self.assertEqual((code, body["error"]["code"]), (2, "invalid_argument"))
        code, body = self.run_cli("brand", "--file", "-", stdin="{nope")
        self.assertEqual((code, body["error"]["code"]), (2, "invalid_argument"))


if __name__ == "__main__":
    unittest.main()
