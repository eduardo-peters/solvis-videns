"""Fluxo da pesquisa: regras de entrada e ramificações mudam quem viu cada pergunta.

Pesquisa 90 (formato das regras como na API V1: conditions em hash, entry_rules por question_id):
  1 "Comprou algo?" (Sim 9101 / Não 9102)   Não → pergunta 4
  2 NPS                                     entrada: pergunta 1 = Sim
  3 "Por quê?" (texto)                      entrada: pergunta 1 = Sim
  4 "Por quê?" (texto)                      entrada: pergunta 1 = Não
  5 Escala "Atendimento?"                   sem regra e nenhuma ramificação a pula
"""

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

from fake_api import FakeSolvis  # noqa: E402
from solvis_pilot import cli  # noqa: E402

SURVEY, COMPROU, NPS, POR_QUE_A, POR_QUE_B, ATEND = 90, 901, 902, 903, 904, 905
SIM, NAO = 9101, 9102
BOM, RUIM = 9501, 9502


def _q(qid, pos, text, qtype, choices=(), **extra):
    return {"id": qid, "position": pos, "text": text, "type": qtype, "options": {}, "choices": list(choices), **extra}


def build() -> FakeSolvis:
    f = FakeSolvis()
    f.add_unit(101, "Loja Centro", "SP")
    f.add_survey(SURVEY, "Pesquisa com fluxo", [
        _q(COMPROU, 0, "Comprou algo?", "Multiple Choice", [{"id": SIM, "text": "Sim"}, {"id": NAO, "text": "Não"}],
           branching_rules=[{"id": 1, "question_id": COMPROU, "choice_id": NAO, "next_question_position": 3,
                             "conditions": {}, "priority_level": 5}]),
        _q(NPS, 1, "Recomendaria?", "NPS",
           entry_rules=[{"id": 1, "question_id": NPS, "conditions": {str(COMPROU): {"choice_id": SIM}}}]),
        _q(POR_QUE_A, 2, "Por quê?", "Short Text",
           entry_rules=[{"id": 2, "question_id": POR_QUE_A, "conditions": {str(COMPROU): {"choice_id": SIM}}}]),
        _q(POR_QUE_B, 3, "Por quê?", "Short Text",
           entry_rules=[{"id": 3, "question_id": POR_QUE_B, "conditions": json.dumps({str(COMPROU): {"choice_id": NAO}})}]),
        _q(ATEND, 4, "Atendimento?", "Scale", [{"id": BOM, "text": "Bom", "value": 5}, {"id": RUIM, "text": "Ruim", "value": 1}]),
    ])
    at = lambda d: dt.datetime(2026, 10, d, 10, 0, 0)  # noqa: E731
    for d in (1, 2, 3):  # compraram: NPS e "Por quê?" da trilha Sim
        f.add_eval(SURVEY, 101, at(d), [(COMPROU, SIM, None, None), (NPS, None, 10, None),
                                        (POR_QUE_A, None, None, "Gostei"), (ATEND, BOM, None, None)])
    f.add_eval(SURVEY, 101, at(4), [(COMPROU, NAO, None, None), (POR_QUE_B, None, None, "Preço"), (ATEND, RUIM, None, None)])
    # viu a pergunta 2 e pulou; e uma que abandonou logo depois da pergunta 1 (não chegou à 2)
    f.add_eval(SURVEY, 101, at(5), [(COMPROU, SIM, None, None), (NPS, None, None, None), (ATEND, BOM, None, None)])
    f.add_eval(SURVEY, 101, at(6), [(COMPROU, SIM, None, None)], completed=False)
    return f


class FlowTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fake = build()
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
        self.ok("config", "--start-month", "2026-10")

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

    def questions(self):
        return {q["id"]: q for q in self.ok("questionnaire", "--survey", SURVEY)["questions"]}

    def test_questionnaire_exposes_entry_rules_and_branching(self):
        qs = self.questions()
        self.assertNotIn("shown_to", qs[COMPROU])
        self.assertEqual(qs[COMPROU]["flow"]["branches"], [{"when": 'escolheu "Não"', "goes_to": 4}])
        nps = qs[NPS]
        self.assertEqual(nps["shown_to"], "conditional")
        self.assertEqual(nps["flow"]["entry_rules"],
                         [{"requires": 'na pergunta 1 escolheu "Sim"', "depends_on_questions": [1]}])
        self.assertEqual(nps["flow"]["skipped_by_branching"],
                         [{"question": 1, "when": 'escolheu "Não"', "goes_to": 4}])
        # a regra em JSON texto também é lida; a pergunta 4 é o destino do salto, não é pulada por ele
        self.assertEqual(qs[POR_QUE_B]["flow"]["entry_rules"][0]["requires"], 'na pergunta 1 escolheu "Não"')
        self.assertNotIn("skipped_by_branching", qs[POR_QUE_B]["flow"])
        self.assertNotIn("shown_to", qs[ATEND])

    def test_query_warns_when_question_is_conditional(self):
        env = self.ok("query", "--metric", "nps", "--survey", SURVEY, "--question", NPS, "--period", "month:2026-10")
        warn = [w for w in env["warnings"] if w["code"] == "conditional_question"]
        self.assertEqual(len(warn), 1)
        self.assertEqual(warn[0]["question_number"], 2)
        self.assertIn('na pergunta 1 escolheu "Sim"', warn[0]["message"])
        self.assertEqual(env["totals"]["n"], 3)  # há 6 avaliações no mês: a pergunta só foi vista por 4

    def test_exposure_is_inferred_from_rules_and_answers(self):
        env = self.ok("query", "--metric", "nps", "--survey", SURVEY, "--question", NPS, "--period", "month:2026-10")
        exp = env["exposure"]
        self.assertEqual(exp["method"], "inferred_from_questionnaire_rules")
        t = exp["totals"]
        # 6 avaliações; viram a pergunta 2 as 3 que escolheram Sim e responderam e a que a pulou
        # (o "Não" desvia dela; a incompleta parou na pergunta 1); 3 responderam
        self.assertEqual((t["evaluations"], t["reached"], t["answered"]), (6, 4, 3))
        self.assertEqual((t["reached_of_evaluations_display"], t["answered_of_reached_display"]), ("66,7%", "75,0%"))
        self.assertEqual(t["uncertain_evaluations"], 0)
        self.assertEqual(env["totals"]["n"], t["answered"])

    def test_exposure_follows_group_by_and_has_no_noise_on_unconditional_questions(self):
        env = self.ok("query", "--metric", "nps", "--survey", SURVEY, "--question", NPS, "--period", "month:2026-10",
                      "--group-by", "unit")
        self.assertEqual(env["exposure"]["rows"][0]["reached"], 4)
        flat = self.ok("query", "--metric", "scale_mean", "--survey", SURVEY, "--question", ATEND, "--period", "month:2026-10")
        self.assertNotIn("exposure", flat)

    def test_path_follows_nps_group_priority_and_skipped(self):
        from solvis_pilot import flow
        from solvis_pilot.semantics import Questionnaire

        def rq(i, pos, typ, **kw):
            return {"id": i, "position_in_survey": pos, "text": f"P{i}", "answer_type": typ, "options": {},
                    "choices": [], "branching_rules": [], "entry_rules": [], **kw}
        qn = Questionnaire.from_api({"id": 1, "name": "x", "questionnaire": {"version": 1, "questions": [
            rq(1, 0, "NPS", branching_rules=[
                {"choice_id": None, "conditions": {"customer_type": "detractors"}, "next_question_position": 1, "priority_level": 5},
                {"choice_id": None, "conditions": {}, "next_question_position": 2, "priority_level": 1}]),
            rq(2, 1, "Text"),
            rq(3, 2, "Text", branching_rules=[
                {"choice_id": None, "conditions": {"skipped": True}, "next_question_position": -1, "priority_level": 5}]),
            rq(4, 3, "Text"),
        ]}})
        self.assertEqual(flow.path(qn, {1: [(None, 3, 1)]}, True), [1, 2, 3, 4])  # detrator vê a 2; a 3 sem registro segue pelo caminho natural
        self.assertEqual(flow.path(qn, {1: [(None, 10, 1)], 3: [(None, None, 0)]}, True), [1, 3])  # promotor pula a 2; pulou a 3: fim
        self.assertEqual(flow.path(qn, {1: [(None, 10, 1)], 3: [(None, None, 1)]}, True), [1, 3, 4])
        self.assertEqual(flow.path(qn, {1: [(None, 3, 1)]}, False), [1])  # incompleta: só até a última com resposta

    def test_unconditional_question_has_no_flow_warning(self):
        env = self.ok("query", "--metric", "scale_mean", "--survey", SURVEY, "--question", ATEND, "--period", "month:2026-10")
        self.assertNotIn("conditional_question", {w["code"] for w in env["warnings"]})

    def test_twin_questions_report_their_different_audiences(self):
        code, body = self.run_cli("query", "--metric", "response_count", "--survey", SURVEY, "--question", POR_QUE_A,
                                  "--period", "month:2026-10")
        err = body["error"]
        self.assertEqual(err["code"], "ambiguous_question_text")
        self.assertIn("não são redundantes", err["message"])
        self.assertEqual(sorted(err["details"]["twin_flow"]), ["3", "4"])  # chaves viram texto no JSON
        self.assertEqual(err["details"]["twin_flow"]["4"]["entry_rules"][0]["requires"], 'na pergunta 1 escolheu "Não"')


if __name__ == "__main__":
    unittest.main()
