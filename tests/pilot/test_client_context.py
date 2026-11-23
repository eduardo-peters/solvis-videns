"""Contexto do cliente: descrição pedida no primeiro uso e guardada em Markdown na pasta de trabalho da skill."""

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

from solvis_pilot import cli  # noqa: E402


class ClientContextTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.env = mock.patch.dict(os.environ, {"SOLVIS_CONTEXT_DIR": os.path.join(self.tmp, "config")})
        self.env.start()

    def tearDown(self):
        self.env.stop()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def run_cli(self, *args, stdin=None):
        buf = io.StringIO()
        with redirect_stdout(buf):
            with mock.patch("sys.stdin", io.StringIO(stdin or "")):
                code = cli.main([str(a) for a in args])
        return code, json.loads(buf.getvalue())

    def test_not_asked_by_default(self):
        code, body = self.run_cli("context")
        self.assertEqual((code, body["status"], body["context"]), (0, "not_asked", None))
        self.assertTrue(any("Finalidade" in s for s in body["suggested_sections"]))
        self.assertTrue(body["file"].endswith(os.path.join("config", "context.md")))

    def test_save_show_append_and_replace(self):
        code, body = self.run_cli("context", "--file", "-", stdin="# Rede Exemplo\n\nVarejo de moda, 120 lojas.\n")
        self.assertEqual((code, body["saved"], body["status"]), (0, True, "configured"))
        self.assertIn("120 lojas", body["context"])
        self.assertIn("atualizado em", body["context"])
        self.assertTrue(os.path.exists(os.path.join(self.tmp, "config", "context.md")))
        code, body = self.run_cli("context", "--file", "-", "--append", stdin="## Metas\n\nNPS alvo 60.")
        self.assertIn("120 lojas", body["context"])
        self.assertIn("NPS alvo 60", body["context"])
        self.assertEqual(body["context"].count("atualizado em"), 1)   # uma única marca de data
        code, body = self.run_cli("context", "--file", "-", stdin="# Outro cliente")
        self.assertNotIn("120 lojas", body["context"])

    def test_none_then_a_description_replaces_it(self):
        code, body = self.run_cli("context", "--none")
        self.assertEqual((code, body["status"], body["context"]), (0, "none", None))
        code, body = self.run_cli("context", "--file", "-", stdin="# Rede Exemplo")
        self.assertEqual(body["status"], "configured")

    def test_empty_text_is_refused_and_clear_removes(self):
        code, body = self.run_cli("context", "--file", "-", stdin="  \n")
        self.assertEqual((code, body["error"]["code"]), (2, "invalid_argument"))
        self.run_cli("context", "--file", "-", stdin="# Rede Exemplo")
        code, body = self.run_cli("context", "--clear")
        self.assertEqual((code, body["cleared"], body["status"]), (0, True, "not_asked"))


if __name__ == "__main__":
    unittest.main()
