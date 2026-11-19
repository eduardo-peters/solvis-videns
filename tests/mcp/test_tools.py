"""Testes da biblioteca de tools e do servidor MCP (sem LLM).

Precisa do ClickHouse local do protótipo. skill_lookup usa o Ollama (embeddings) e é
pulado se ele não responder.

Rodar: AGENT_TODAY=2026-11-18 python3 -m unittest discover -s tests/mcp -v
"""
import json
import os
import subprocess
import sys
import unittest
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
os.environ.setdefault("AGENT_TODAY", "2026-11-18")
os.environ["AUDIT_DISABLED"] = "1"
sys.path.insert(0, str(ROOT))
import solvis_tools as lib  # noqa: E402


def ollama_up():
    try:
        urllib.request.urlopen("http://127.0.0.1:11434/api/tags", timeout=2)
        return True
    except Exception:
        return False


class Registry(unittest.TestCase):
    def test_toda_tool_documentada(self):
        for n, t in lib.REGISTRY.items():
            self.assertGreater(len(t["description"]), 40, n)
            self.assertTrue(t["reads"] and t["skill"], n)
            for p, spec in t["input_schema"]["properties"].items():
                self.assertTrue(spec.get("description"), f"{n}.{p} sem descrição")

    def test_docs_em_dia(self):
        out = subprocess.run([sys.executable, str(ROOT / "mcp/gen_docs.py"), "--check"], capture_output=True, text=True)
        self.assertEqual(out.returncode, 0, out.stderr or out.stdout)

    def test_skill_ligada_existe(self):
        """Toda referência de skill aponta para uma regra ou arquivo que existe."""
        from solvis_tools.core.skill import _invariants
        inv = _invariants()
        refs = ROOT / "skills/solvis-survey-analysis-pilot/references"
        for n, t in lib.REGISTRY.items():
            for ref in t["skill"]:
                if ref.startswith("INV-"):
                    self.assertIn(ref, inv, f"{n}: {ref}")
                elif ref.endswith(".md") or ".md#" in ref or ".yaml" in ref:
                    f = ref.split("#")[0]
                    ok = (refs / f).exists() or (ROOT / f).exists()
                    self.assertTrue(ok, f"{n}: {ref}")

    def test_catalogo_aponta_para_checagens_e_regras_reais(self):
        from solvis_tools.core.skill import _invariants
        inv = _invariants()
        src = (ROOT / "ops/pipeline.py").read_text()
        for f in json.loads((ROOT / "ops/metadata_catalog.json").read_text())["fields"]:
            if f["check"]:
                self.assertIn(f'"{f["check"]}"', src, f"checagem inexistente: {f['check']}")
            if f["skill"] and f["skill"].startswith("INV-"):
                self.assertIn(f["skill"], inv)

    def test_exemplos_respeitam_o_esquema(self):
        for n, t in lib.REGISTRY.items():
            lib.validate(t, dict(t["example"]))


class Layout(unittest.TestCase):
    """Uma tool por arquivo: o nome do arquivo é o nome da tool."""

    def test_uma_tool_por_arquivo(self):
        files = {p.stem for p in (ROOT / "solvis_tools/tools").glob("*.py") if not p.stem.startswith("_")}
        self.assertEqual(files, set(lib.REGISTRY))
        for n, t in lib.REGISTRY.items():
            self.assertEqual(t["module"], f"solvis_tools.tools.{n}", n)


class LeastPrivilege(unittest.TestCase):
    def test_analista_nao_tem_tools_de_auditoria(self):
        a = lib.for_agent("analyst")
        for n in ("data_health", "unit_metadata", "methodology_rules", "quality_status"):
            self.assertNotIn(n, a)

    def test_engenheiro_nao_calcula_metricas(self):
        e = lib.for_agent("data_engineer")
        for n in ("nps", "scale_mean", "choice_share", "evaluation_count"):
            self.assertNotIn(n, e)

    def test_tool_de_outro_perfil_recusada(self):
        with self.assertRaises(lib.ToolError):
            lib.call("analyst", "data_health", {})

    def test_argumento_extra_recusado(self):
        with self.assertRaisesRegex(lib.ToolError, "desconhecidos"):
            lib.call("analyst", "nps", {"survey": "Satisfação", "sql": "DROP TABLE raw.units"})

    def test_credencial_do_engenheiro_sem_respostas_nem_conversas(self):
        for table in ("raw.answers", "ops.interactions", "ops.tool_calls"):
            with self.assertRaises(lib.ToolError, msg=table):
                lib.ch("engineer", f"SELECT count() FROM {table}")

    def test_credencial_do_engenheiro_so_le(self):
        with self.assertRaises(lib.ToolError):
            lib.ch("engineer", "INSERT INTO ops.data_health (check_id, level, value, threshold, detail) "
                               "VALUES ('x', 'ok', 0, 0, 'x')")


class Examples(unittest.TestCase):
    """Cada exemplo documentado roda de verdade e devolve algo."""

    def test_exemplos_executam(self):
        for n, t in lib.REGISTRY.items():
            if n == "skill_lookup" and not ollama_up():
                continue
            with self.subTest(tool=n):
                out = lib.call(t["agents"][0], n, dict(t["example"]))
                self.assertTrue(out)


class Server(unittest.TestCase):
    def _session(self, agent, msgs):
        p = subprocess.run([sys.executable, str(ROOT / "mcp/server.py"), "--agent", agent],
                           input="\n".join(json.dumps(m) for m in msgs) + "\n", capture_output=True, text=True,
                           timeout=120, env={**os.environ})
        return [json.loads(l) for l in p.stdout.splitlines()]

    def test_protocolo(self):
        r = self._session("data_engineer", [
            {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-06-18"}},
            {"jsonrpc": "2.0", "method": "notifications/initialized"},
            {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
            {"jsonrpc": "2.0", "id": 3, "method": "tools/call",
             "params": {"name": "explain_metric", "arguments": {"metric": "nps"}}},
            {"jsonrpc": "2.0", "id": 4, "method": "tools/call",
             "params": {"name": "explain_metric", "arguments": {"metric": "inexistente"}}},
            {"jsonrpc": "2.0", "id": 5, "method": "tools/call", "params": {"name": "nps", "arguments": {}}},
            {"jsonrpc": "2.0", "id": 6, "method": "metodo/inexistente"}])
        self.assertEqual(len(r), 6)  # a notificação não tem resposta
        self.assertEqual(r[0]["result"]["protocolVersion"], "2025-06-18")
        names = [t["name"] for t in r[1]["result"]["tools"]]
        self.assertEqual(set(names), set(lib.for_agent("data_engineer")))
        self.assertTrue(all(t["annotations"]["readOnlyHint"] for t in r[1]["result"]["tools"]))
        self.assertFalse(r[2]["result"]["isError"])
        self.assertTrue(r[3]["result"]["isError"])        # erro de negócio: o modelo lê e corrige
        self.assertEqual(r[4]["error"]["code"], -32602)   # tool de outro perfil
        self.assertEqual(r[5]["error"]["code"], -32601)   # método desconhecido


if __name__ == "__main__":
    unittest.main()
