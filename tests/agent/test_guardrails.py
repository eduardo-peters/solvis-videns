"""Testes determinísticos dos guardrails do agente local (sem LLM).

O modelo é trocado por um roteiro: cada teste reproduz um comportamento ruim que já
aconteceu de verdade (nome inventado, número inventado, data copiada da skill, métrica
trocada...) e confere que o guardrail atua. Precisa do ClickHouse local com os dados
do protótipo (clickhouse/README.md); o Ollama não é usado.

Rodar: AGENT_TODAY=2026-11-18 python3 -m unittest discover -s tests/agent -v
"""
import json
import re
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


class Charts(unittest.TestCase):
    def test_barras_de_nps_por_regional_iguais_a_tool_nps(self):
        c = agent.t_chart({"kind": "bar", "metric": "nps", "by": "Regional", "survey": "Satisfação",
                           "period": "yesterday"})["chart"]
        ref = {r["value"]: int(r["nps"]) for r in agent.t_nps({"survey": "Satisfação", "group_by": "Regional",
                                                               "period": "yesterday"})["rows"]}
        self.assertEqual(dict(zip(c["labels"], c["series"][0]["values"])), ref)

    def test_linha_de_volume_por_hora_soma_o_dia(self):
        c = agent.t_chart({"kind": "line", "by": "hour", "period": "yesterday"})["chart"]
        self.assertEqual(sum(c["series"][0]["values"]), 11709)

    def test_ranking_de_nps_por_loja_respeita_amostra_minima(self):
        out = agent.t_chart({"kind": "bar", "metric": "nps", "by": "unit", "survey": "Satisfação",
                             "period": "yesterday"})
        self.assertNotIn("027 - Washington Soares", out["chart"]["labels"])  # n = 2

    B = {"survey": "Satisfação", "period": "yesterday"}

    def test_todos_os_tipos_geram_especificacao(self):
        cases = [dict(kind="bar", metric="nps", by="Regional", **self.B), dict(kind="hbar", metric="nps", **self.B),
                 dict(kind="line", by="hour", period="yesterday"), dict(kind="area", metric="nps", by="hour", **self.B),
                 dict(kind="combo", **self.B), dict(kind="stacked", by="Regional", **self.B),
                 dict(kind="donut", by="channel", period="yesterday"), dict(kind="histogram", **self.B),
                 dict(kind="scatter", **self.B), dict(kind="heatmap", period="yesterday"),
                 dict(kind="heatmap", metric="nps", **self.B), dict(kind="profile", **self.B)]
        for c in cases:
            with self.subTest(kind=c["kind"], metric=c.get("metric")):
                spec = agent.t_chart(dict(c))["chart"]
                self.assertEqual(spec["type"], "hbar" if c["kind"] == "profile" else c["kind"])
                self.assertTrue(spec["title"])

    def test_histograma_soma_o_n_do_nps(self):
        out = agent.t_chart({"kind": "histogram", **self.B})
        self.assertEqual(out["n"], 11709)

    def test_composicao_soma_100(self):
        spec = agent.t_chart({"kind": "stacked", "by": "Regional", **self.B})["chart"]
        for i in range(len(spec["labels"])):
            self.assertAlmostEqual(sum(sr["values"][i] for sr in spec["series"]), 100, delta=0.2)

    def test_media_por_pergunta_igual_a_scale_mean(self):
        rows = agent.t_chart({"kind": "profile", **self.B})["rows"]
        ref = agent.t_scale_mean({"survey": "Satisfação", "question": "3", "period": "yesterday"})["rows"][0]["mean"]
        self.assertEqual([r["mean"] for r in rows if r["label"].startswith("3.")][0], ref)

    def test_combo_volume_igual_ao_dia(self):
        rows = agent.t_chart({"kind": "combo", **self.B})["rows"]
        self.assertEqual(sum(r["evaluations"] for r in rows), 11709)

    def test_legenda_sem_numeros_para_todos_os_tipos(self):
        for k in ("bar", "stacked", "scatter", "heatmap", "donut", "histogram"):
            args = {"kind": k, **self.B, **({"metric": "nps", "by": "Regional"} if k == "bar" else {})}
            if k == "donut":
                args = {"kind": "donut", "by": "channel", "period": "yesterday"}
            spec = agent.t_chart(args)["chart"]
            cap = agent.chart_caption(spec)
            values = set()
            for sr in spec.get("series", []):
                values |= {v for v in sr["values"] if v is not None}
            values |= set(spec.get("values", [])) | {p["y"] for p in spec.get("points", [])} | {p["x"] for p in spec.get("points", [])}
            values |= {v for row in spec.get("matrix", []) for v in row if v is not None}
            labels = " ".join(map(str, spec.get("labels", []) + spec.get("x", []) + spec.get("y", [])
                                  + [p["label"] for p in spec.get("points", [])])) + " " + spec["title"]
            said = {float(t) for t in re.findall(r"-?\d+(?:[.,]\d+)?", cap.replace(",", "."))
                    if t not in re.findall(r"-?\d+(?:[.,]\d+)?", labels)}
            self.assertFalse(said & {float(v) for v in values}, (k, cap))

    def test_tipo_invalido_recusado(self):
        with self.assertRaises(agent.ToolError):
            agent.t_chart({"kind": "pizza", "period": "yesterday"})


class ChartFlow(unittest.TestCase):
    """Falhas reais no teste ponta a ponta dos gráficos."""

    def test_grafico_encerra_e_nao_e_apagado(self):
        out, fake = run("Faz um gráfico do NPS por Regional ontem na pesquisa Satisfação",
                        call("chart", kind="bar", metric="nps", by="Regional", survey="Satisfação", period="yesterday"),
                        call("nps", survey="Satisfação", group_by="Regional", period="yesterday"))
        self.assertEqual(out["table"]["chart"]["type"], "bar")
        self.assertEqual(len(fake.seen), 1)
        self.assertTrue(out["answer"].startswith("NPS por Regional"))

    def test_dispersao_nao_e_bloqueada_pela_checagem_de_metrica(self):
        out, _ = run("Gráfico de dispersão das lojas: volume contra NPS, ontem, pesquisa Satisfação",
                     call("chart", kind="scatter", survey="Satisfação", period="yesterday"))
        self.assertEqual(out["outcome"], "answered")
        self.assertEqual(out["table"]["chart"]["type"], "scatter")


class ChartKindFixes(unittest.TestCase):
    B = {"survey": "Satisfação", "period": "yesterday"}

    def test_media_de_cada_pergunta_vira_profile(self):
        out = agent.t_chart({"kind": "bar", "metric": "scale_mean", "by": "question", **self.B,
                             "_user_q": "Gráfico com a média de cada pergunta de escala da Satisfação ontem"})
        self.assertEqual(out["chart"]["title"], "Média de cada pergunta de escala")

    def test_volume_e_nps_por_hora_vira_combo(self):
        out = agent.t_chart({"kind": "line", "metric": "evaluation_count", "by": "hour", **self.B,
                             "_user_q": "Mostra num gráfico o volume de respostas e o NPS por hora ontem na Satisfação"})
        self.assertEqual(out["chart"]["type"], "combo")


class Heatmap(unittest.TestCase):
    Q = ("preciso visualizar um mapa de calor pelas top 10 unidades e hora de respostas, preenchido com a "
         "quantidade de respostas de cada unidade por hora. nao quero ver os números, apenas o heatmap.")

    def test_heatmap_chega_na_tela_e_bate_com_o_volume(self):
        out, _ = run(self.Q, call("chart", kind="heatmap", top=10, period="yesterday"))
        h = out["table"]["chart"]
        self.assertEqual(len(h["y"]), 10)
        self.assertEqual(len(h["matrix"]), 10)
        total = agent.ch("SELECT count() c FROM raw.evaluations WHERE unit_id IN (SELECT unit_id FROM raw.evaluations "
                         "GROUP BY unit_id ORDER BY count() DESC LIMIT 10)")[0]["c"]
        self.assertEqual(sum(map(sum, h["matrix"])), int(total))
        self.assertEqual(out["outcome"], "answered")

    def test_pedido_sem_numeros_nao_mostra_contagens(self):
        """Falha real: o modelo escreveu '373' e '217' com o usuário pedindo só o heatmap."""
        out, _ = run(self.Q, call("chart", kind="heatmap", top=10, period="yesterday"))
        self.assertNotIn("373", out["answer"])
        self.assertNotIn("217", out["answer"])
        self.assertIn("Mapa de calor", out["answer"])
        self.assertEqual(events(out, "chart"), ["annotate"])

    def test_heatmap_respondido_com_outra_metrica_e_bloqueado(self):
        out, _ = run(self.Q, call("evaluation_count", group_by="unit", period="yesterday"),
                     say("A loja com mais respostas foi 288 - Aracajú Adélia Franco."),
                     say("Foi a 288 - Aracajú Adélia Franco."))
        self.assertEqual(out["outcome"], "blocked")
        self.assertEqual(events(out, "metric"), ["retry", "block"])


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
