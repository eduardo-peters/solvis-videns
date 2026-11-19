"""Testes determinísticos dos guardrails do agente local (sem LLM).

O modelo é trocado por um roteiro: cada teste reproduz um comportamento ruim que já
aconteceu de verdade (nome inventado, número inventado, data copiada da skill, métrica
trocada...) e confere que o guardrail atua. Precisa do ClickHouse local com os dados
do protótipo (clickhouse/README.md); o Ollama não é usado.

Rodar: AGENT_TODAY=2026-11-18 python3 -m unittest discover -s tests/agent -v
"""
import json
import os
import sys
import unittest
import urllib.error
from pathlib import Path

os.environ.setdefault("AGENT_TODAY", "2026-11-18")
os.environ["AGENT_CONTEXT"] = "0"     # contexto vetorial usa o Ollama; aqui só a lógica
os.environ["AUDIT_DISABLED"] = "1"    # testes não poluem ops.*
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "agent"))
import agent  # noqa: E402


def call(name, **args):
    return {"role": "assistant", "content": "", "tool_calls": [{"function": {"name": name, "arguments": args}}]}


def say(text):
    return {"role": "assistant", "content": text}


class Scripted:
    """Substitui agent.ollama_chat: devolve as mensagens do roteiro, em ordem."""

    def __init__(self, *msgs):
        self.msgs, self.seen = list(msgs), []

    def __call__(self, messages):
        self.seen.append(messages[-1])
        if not self.msgs:
            raise AssertionError("o agente pediu mais respostas do que o roteiro tem")
        return self.msgs.pop(0)


def run(question, *script):
    fake = Scripted(*script)
    agent.ollama_chat = fake
    return agent.ask([{"role": "user", "content": question}], source="test"), fake


def events(out, guardrail):
    return [e["action"] for e in out["guardrail_events"] if e["guardrail"] == guardrail]


NPS_Q = "Qual foi o NPS da pesquisa Satisfação ontem?"


class Grounding(unittest.TestCase):
    def test_nome_inventado_sem_ferramenta_e_bloqueado(self):
        """Falha real: 'Loja A' e 'Pergunta de Satisfação', sem chamar ferramenta."""
        out, _ = run("qual foi a loja que mais teve respostas?",
                     say('A loja foi a "Loja A", na "Pergunta de Satisfação".'),
                     say('Foi a "Loja A".'))
        self.assertEqual(out["outcome"], "blocked")
        self.assertNotIn("Loja A", out["answer"])
        self.assertEqual(events(out, "grounding"), ["retry", "block"])

    def test_nova_tentativa_sugere_a_chamada(self):
        out, fake = run("Qual a pior loja em NPS ontem na pesquisa Satisfação?",
                        say("É a Loja A."),
                        call("nps", survey="Satisfação", group_by="unit", min_n=30, period="yesterday"),
                        say("A pior é 234 - Fortaleza Tapioqueiras, NPS -3 (n = 119), ontem."))
        self.assertIn("nps(", fake.seen[1]["content"])
        self.assertEqual(out["outcome"], "answered")
        self.assertIn("Tapioqueiras", out["answer"])


class Numbers(unittest.TestCase):
    def test_numero_inventado_e_bloqueado(self):
        """Falha real: NPS '12' que não existia em nenhum resultado."""
        out, _ = run(NPS_Q, call("nps", survey="Satisfação", period="yesterday"),
                     say("O NPS foi 12."), say("O NPS foi 12, com n = 11709."))
        self.assertEqual(out["outcome"], "blocked")
        self.assertNotIn("12", out["answer"])
        self.assertEqual(events(out, "numbers"), ["retry", "block"])

    def test_numero_real_passa(self):
        out, _ = run(NPS_Q, call("nps", survey="Satisfação", period="yesterday"),
                     say("O NPS foi 79, com 11.709 respostas, em 17/11/2026."))
        self.assertEqual(out["outcome"], "answered")
        self.assertEqual(out["guardrail_events"], [])

    def test_data_copiada_da_skill_e_bloqueada(self):
        """Falha real: '1 a 31/10/2026' copiado de um exemplo da skill."""
        out, _ = run(NPS_Q, call("nps", survey="Satisfação", period="yesterday"),
                     say("NPS 79 (11709 respostas, 1 a 31/10/2026)."),
                     say("NPS 79 (11709 respostas, 31/10/2026)."))
        self.assertEqual(out["outcome"], "blocked")
        self.assertEqual(events(out, "dates"), ["retry", "block"])


class Metric(unittest.TestCase):
    def test_volume_no_lugar_de_nps_e_bloqueado(self):
        """Falha real: 'pior loja em NPS' respondida com volume de respostas."""
        out, _ = run("Qual a pior loja em NPS ontem na pesquisa Satisfação?",
                     call("evaluation_count", survey="Satisfação", group_by="unit", period="yesterday"),
                     say("A pior é 288 - Aracajú Adélia Franco com 373 respostas."),
                     say("É a 288 - Aracajú Adélia Franco (373)."))
        self.assertEqual(out["outcome"], "blocked")
        self.assertEqual(events(out, "metric"), ["retry", "block"])

    def test_nps_em_pergunta_de_escala_vira_erro_da_ferramenta(self):
        out, _ = run("Qual o NPS da pergunta de Atendimento da pesquisa Satisfação ontem?",
                     call("nps", survey="Satisfação", question="Atendimento", period="yesterday"),
                     say("O NPS não existe para a pergunta de Atendimento, que é de escala."))
        self.assertFalse(out["trace"][0]["ok"])
        self.assertIn("nps não existe para ela", out["trace"][0]["error"])
        self.assertEqual(out["outcome"], "refused")

    def test_pergunta_ambigua_volta_para_o_usuario(self):
        self.assertRaisesRegex(agent.ToolError, "ambíguo|informe",
                               agent.resolve_question, "choice_share", 40851, {"question": "loja"})


class GapsFromTrainingV1(unittest.TestCase):
    """Brechas vistas na avaliação do modelo treinado v1 (docs/training.md)."""

    def test_volume_respondido_com_nps_e_bloqueado(self):
        out, fake = run("Quantas avaliações a pesquisa Satisfação teve ontem?",
                        call("nps", survey="Satisfação", period="yesterday"),
                        say("A pesquisa Satisfação teve 11.709 avaliações em 17/11/2026."),
                        say("Foram 11.709 avaliações."))
        self.assertEqual(out["outcome"], "blocked")
        self.assertEqual(events(out, "metric"), ["retry", "block"])
        self.assertIn("volume de avaliações", fake.seen[2]["content"])

    def test_taxa_de_resposta_recusada_mesmo_com_volume(self):
        out, _ = run("Qual a taxa de resposta da pesquisa Satisfação ontem?",
                     call("evaluation_count", survey="Satisfação", period="yesterday"),
                     say("A pesquisa Satisfação teve 11.709 avaliações em 17/11/2026."))
        self.assertTrue(out["answer"].startswith("Taxa de resposta não existe"))
        self.assertIn("capability", [e["guardrail"] for e in out["guardrail_events"]])

    def test_volume_certo_passa(self):
        out, _ = run("Quantas avaliações a pesquisa Satisfação teve ontem?",
                     call("evaluation_count", survey="Satisfação", period="yesterday"),
                     say("A pesquisa Satisfação teve 11.709 avaliações em 17/11/2026."))
        self.assertEqual(out["outcome"], "answered")


class Annotations(unittest.TestCase):
    def test_cobertura_parcial_e_avisada_pelo_codigo(self):
        """Falha real: 'últimos 7 dias' respondido com 1 dia de dados, sem aviso."""
        out, _ = run("NPS da Satisfação nos últimos 7 dias",
                     call("nps", survey="Satisfação", period="last_7_days"),
                     say("O NPS foi 79 (n = 11709) de 2026-11-11 a 2026-11-17."))
        self.assertIn("Só há dados de 2026-11-17 a 2026-11-17", out["answer"])
        self.assertEqual(events(out, "coverage"), ["annotate"])

    def test_csat_recusado_com_aviso(self):
        out, _ = run("Qual o nosso CSAT de atendimento?", say("Não sei."))
        self.assertEqual(out["outcome"], "refused")
        self.assertIn("não tem métrica CSAT", out["answer"])

    def test_comparacao_avisada_mesmo_quando_o_modelo_esquece(self):
        out, _ = run("O NPS da Satisfação subiu em relação à semana anterior?",
                     call("nps", survey="Satisfação", period="last_7_days"),
                     say("O NPS foi 79 (n = 11709) de 2026-11-11 a 2026-11-17."))
        self.assertTrue(out["answer"].startswith("Comparação entre períodos"))


class Parsing(unittest.TestCase):
    def test_chamada_escrita_como_texto_e_executada(self):
        out, _ = run("Quantas avaliações a Satisfação teve ontem?",
                     say('evaluation_count(survey="Satisfação", period="yesterday")'),
                     say("Foram 11.709 avaliações em 17/11/2026."))
        self.assertEqual(out["trace"][0]["tool"], "evaluation_count")
        self.assertTrue(out["trace"][0]["ok"])

    def test_nome_de_ferramenta_parecido_e_corrigido(self):
        self.assertEqual(agent._tool_name("list_evaluation_count"), "evaluation_count")
        self.assertIsNone(agent._tool_name("drop_table"))

    def test_ferramenta_inexistente_nao_executa(self):
        out, _ = run(NPS_Q, call("execute_sql", sql="SELECT * FROM raw.answers"),
                     say("Não consigo executar SQL."))
        self.assertFalse(out["trace"][0]["ok"])


class Methodology(unittest.TestCase):
    def test_nps_geral_errado_falha_inv02(self):
        """O agregado do grupo tem de ser o total, nunca uma linha ou média."""
        out, _ = run("Me dá o NPS de cada loja e o NPS geral de ontem na pesquisa Satisfação.",
                     call("nps", survey="Satisfação", group_by="unit", period="yesterday"),
                     say("O NPS geral foi -3 (n = 119), ontem."))
        inv02 = [c for c in out["methodology"] if c["rule"].startswith("INV-02")]
        self.assertTrue(inv02 and not inv02[0]["passed"])

    def test_ranking_com_amostra_pequena_falha_inv23(self):
        out, _ = run("Qual a pior loja em NPS ontem na pesquisa Satisfação?",
                     call("nps", survey="Satisfação", group_by="unit", period="yesterday"),
                     say("A pior é 027 - Washington Soares, NPS -100 (n = 2), ontem."))
        rule = [c for c in out["methodology"] if c["rule"] == "INV-23 ranking sem amostra pequena"]
        self.assertTrue(rule and not rule[0]["passed"])

    def test_resposta_certa_passa_em_tudo(self):
        out, _ = run("Qual a pior loja em NPS ontem na pesquisa Satisfação?",
                     call("nps", survey="Satisfação", group_by="unit", min_n=30, period="yesterday"),
                     say("A pior é 234 - Fortaleza Tapioqueiras, NPS -3 (n = 119), ontem."))
        self.assertTrue(all(c["passed"] for c in out["methodology"]), out["methodology"])


class Isolation(unittest.TestCase):
    """O agente consulta como assai_agent: limites do banco, não do prompt."""

    def _denied(self, sql):
        with self.assertRaises(agent.ToolError) as e:
            agent.ch(sql)
        self.assertIn("ACCESS_DENIED", str(e.exception).replace("Not enough privileges", "ACCESS_DENIED"))

    def test_sem_respostas_individuais(self):
        self._denied("SELECT * FROM raw.answers LIMIT 1")

    def test_sem_auditoria(self):
        self._denied("SELECT * FROM ops.interactions LIMIT 1")

    def test_sem_escrita(self):
        with self.assertRaises(agent.ToolError):
            agent.ch("INSERT INTO raw.units VALUES (2, 1, 'x', 'x', 'x', 'SP')")

    def test_so_o_proprio_cliente(self):
        rows = agent.ch("SELECT DISTINCT client_id FROM semantic.answer_counts_daily")
        self.assertEqual([int(r["client_id"]) for r in rows], [1])


if __name__ == "__main__":
    unittest.main()
