"""Pasta de trabalho: credencial, contexto, marca e cache ficam em `.solvis-videns/` dentro da pasta em que o host
roda (ou `SOLVIS_WORKDIR`). Um cliente por pasta: `setup` recusa trocar de cliente sem pedido explícito."""

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


class WorkdirTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fake = fx.build()
        cls.base_url = cls.fake.start()

    @classmethod
    def tearDownClass(cls):
        cls.fake.stop()

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.work_a = os.path.join(self.tmp, "cliente-a")
        self.work_b = os.path.join(self.tmp, "cliente-b")
        os.makedirs(self.work_a)
        os.makedirs(self.work_b)
        # só a URL da API falsa e a data; nenhum dos caminhos é forçado: tudo deve cair na pasta de trabalho
        self.env = mock.patch.dict(os.environ, {"SOLVIS_API_BASE_URL": self.base_url, "SOLVIS_TODAY": "2026-11-17",
                                                "SOLVIS_WORKDIR": self.work_a})
        self.env.start()
        for k in ("SOLVIS_API_USERNAME", "SOLVIS_API_PASSWORD", "SOLVIS_CACHE_DIR", "SOLVIS_ENV_FILE",
                  "SOLVIS_CREDENTIALS_FILE", "SOLVIS_BRAND_DIR", "SOLVIS_CONTEXT_DIR"):
            os.environ.pop(k, None)

    def tearDown(self):
        self.env.stop()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def run_cli(self, *args, stdin=None):
        buf = io.StringIO()
        with redirect_stdout(buf):
            with mock.patch("sys.stdin", io.StringIO(stdin or "")):
                code = cli.main([str(a) for a in args])
        return code, json.loads(buf.getvalue())

    def data(self, work):
        return os.path.join(work, ".solvis-videns")

    def test_everything_lands_in_the_workdir(self):
        code, body = self.run_cli("setup")
        self.assertEqual((code, body["credentials_configured"]), (0, False))
        self.assertEqual(body["workdir"], os.path.realpath(self.work_a))
        self.assertEqual(body["data_dir"], os.path.join(os.path.realpath(self.work_a), ".solvis-videns"))
        self.assertIn("pasta de trabalho", self.run_cli("scope")[1]["error"]["hint"])

        code, body = self.run_cli("setup", "--username", self.fake.username, "--password", "-",
                                  "--start-month", "2026-10", stdin=self.fake.password + "\n")
        self.assertEqual((code, body["saved"]), (0, True))
        data = self.data(self.work_a)
        self.assertTrue(os.path.exists(os.path.join(data, ".env")))
        self.assertEqual(open(os.path.join(data, ".gitignore"), encoding="utf-8").read().strip().splitlines()[-1], "*")
        self.assertEqual(oct(os.stat(data).st_mode & 0o777), "0o700")

        self.run_cli("context", "--file", "-", stdin="# Cliente A")
        logo = os.path.join(self.tmp, "logo.svg")
        open(logo, "w").write("<svg/>")
        self.run_cli("brand", "--asset", logo)
        code, body = self.run_cli("query", "--metric", "evaluation_count", "--survey", 56, "--period", "month:2026-10")
        self.assertEqual(code, 0)
        self.assertTrue(os.path.exists(os.path.join(data, "context.md")))
        self.assertTrue(os.path.exists(os.path.join(data, "brand", "logo.svg")))
        self.assertTrue(os.path.isdir(os.path.join(data, "cache")))
        self.assertEqual(self.run_cli("scope")[1]["workdir"], os.path.realpath(self.work_a))
        # nada foi parar na pasta pessoal nem na pasta atual do processo
        self.assertFalse(os.path.exists(os.path.join(os.getcwd(), ".solvis-videns")))

    def test_each_workdir_is_a_separate_client(self):
        self.run_cli("setup", "--username", self.fake.username, "--password", self.fake.password, "--start-month", "2026-10")
        self.run_cli("context", "--file", "-", stdin="# Cliente A")
        with mock.patch.dict(os.environ, {"SOLVIS_WORKDIR": self.work_b}):
            code, body = self.run_cli("setup")
            self.assertFalse(body["credentials_configured"])          # a credencial de A não vale em B
            self.assertEqual(self.run_cli("context")[1]["status"], "not_asked")
            self.assertFalse(os.path.exists(self.data(self.work_b)))
        code, body = self.run_cli("setup")
        self.assertEqual((body["credentials_configured"], body["client_context"]["status"]), (True, "configured"))

    def test_setup_refuses_another_client_in_the_same_folder(self):
        self.run_cli("setup", "--username", self.fake.username, "--password", self.fake.password)
        code, body = self.run_cli("setup", "--username", "outro-cliente", "--password", "x")
        self.assertEqual((code, body["error"]["code"]), (2, "client_mismatch"))
        self.assertIn("--replace-client", body["error"]["hint"])
        self.assertEqual(self.run_cli("setup")[1]["username"], self.fake.username)   # nada mudou
        # com pedido explícito, troca (a API falsa só aceita a credencial dela: auth_failed prova que tentou)
        code, body = self.run_cli("setup", "--username", "outro-cliente", "--password", "x", "--replace-client")
        self.assertEqual(body["error"]["code"], "auth_failed")
        # mesma credencial de novo não é troca de cliente
        code, body = self.run_cli("setup", "--username", self.fake.username, "--password", self.fake.password)
        self.assertEqual((code, body["saved"]), (0, True))


if __name__ == "__main__":
    unittest.main()
