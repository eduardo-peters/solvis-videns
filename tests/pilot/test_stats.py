"""Testes de stats.py com valores calculados à mão (sem motor, sem API)."""

import os
import sys
import unittest

HERE = os.path.dirname(__file__)
sys.path.insert(0, os.path.join(HERE, "..", "..", "skills", "solvis-videns", "scripts"))

from solvis_pilot import stats  # noqa: E402


class NpsTest(unittest.TestCase):
    def test_se_and_z_by_hand(self):
        # p=.5 d=.2 n=100: var=.7-.09=.61 -> SE=sqrt(.0061)=7.81 pontos
        self.assertAlmostEqual(stats.nps_se(50, 20, 100), 7.810, places=2)
        # p=.4 d=.3: var=.7-.01=.69 -> SE=8.307. delta=20; z=20/sqrt(7.81^2+8.307^2)=1.754
        self.assertAlmostEqual(stats.nps_se(40, 30, 100), 8.307, places=2)
        self.assertAlmostEqual(stats.nps_z((50, 20, 100), (40, 30, 100)), 1.754, places=2)

    def test_no_variance_is_not_testable(self):
        self.assertIsNone(stats.nps_z((10, 0, 10), (10, 0, 10)))
        self.assertEqual(stats.classify(None, False), "not_testable")


class ProportionTest(unittest.TestCase):
    def test_two_proportions_by_hand(self):
        # .6 x .4, n=100 cada, pooled .5: SE=sqrt(.25*.02)=.0707; z=2.828
        self.assertAlmostEqual(stats.prop_z(60, 100, 40, 100), 2.828, places=2)

    def test_empty_base(self):
        self.assertIsNone(stats.prop_z(0, 0, 4, 10))


class ClassifyTest(unittest.TestCase):
    def test_thresholds_are_fixed(self):
        self.assertEqual(stats.classify(1.95, False), "not_significant")
        self.assertEqual(stats.classify(1.96, False), "robust")
        self.assertEqual(stats.classify(-2.83, False), "robust")
        self.assertEqual(stats.classify(2.83, True), "signal_to_monitor")
        self.assertEqual(stats.classify(3.28, True), "signal_to_monitor")
        self.assertEqual(stats.classify(3.29, True), "robust")
        self.assertEqual(stats.classify(-3.5, True), "robust")
        self.assertEqual(stats.classify(1.0, True), "not_significant")

    def test_significance_reads_engine_results(self):
        cur = {"value": 30, "n": 100, "breakdown": {"promoters": 50, "detractors": 20}}
        prev = {"value": 10, "n": 100, "breakdown": {"promoters": 40, "detractors": 30}}
        sig = stats.significance("nps", cur, prev, selected=False)
        self.assertEqual(sig["z"], 1.75)
        self.assertEqual(sig["verdict"], "not_significant")
        self.assertTrue(sig["optimistic_margins"])
        share = stats.significance("choice_share", {"chosen": 60, "n": 100}, {"chosen": 40, "n": 100}, selected=True)
        self.assertEqual((share["z"], share["verdict"]), (2.83, "signal_to_monitor"))
        self.assertIsNone(stats.significance("scale_mean", cur, prev, selected=False))


class CompositionTest(unittest.TestCase):
    def test_new_unit_creates_the_trend(self):
        # A: NPS 40 nos dois períodos; B: -10 nos dois. C entra no 2º período com NPS 90.
        counts = {
            "p1": {"A": (50, 10, 100), "B": (20, 30, 100)},
            "p2": {"A": (50, 10, 100), "B": (20, 30, 100), "C": (90, 0, 100)},
        }
        active = {"p1": {"A", "B"}, "p2": {"A", "B", "C"}}
        out = stats.composition("nps", ["p1", "p2"], counts, active)
        self.assertEqual(out["buckets"][0]["aggregate"]["value"], 15.0)   # (70-40)/200
        self.assertEqual(out["buckets"][1]["aggregate"]["value"], 40.0)   # (160-40)/300
        self.assertEqual(out["buckets"][1]["panel"]["value"], 15.0)       # A+B: (70-40)/200
        self.assertEqual(out["buckets"][1]["outside_panel"]["value"], 90.0)
        self.assertEqual(out["steps"][0]["delta_aggregate"], 25.0)
        self.assertEqual(out["steps"][0]["delta_panel"], 0.0)
        self.assertEqual(out["steps"][0]["composition_share"], 1.0)
        self.assertEqual(out["verdict"], "composition_effect")

    def test_real_improvement_in_fixed_panel(self):
        counts = {"p1": {"A": (50, 10, 100), "B": (20, 30, 100)},
                  "p2": {"A": (80, 5, 100), "B": (50, 20, 100)}}
        active = {"p1": {"A", "B"}, "p2": {"A", "B"}}
        out = stats.composition("nps", ["p1", "p2"], counts, active)
        self.assertEqual(out["steps"][0]["composition_share"], 0.0)
        self.assertGreater(abs(out["steps"][0]["z_panel"]), 1.96)
        self.assertEqual(out["verdict"], "no_composition_effect")
        self.assertFalse(out["contradiction"])

    def test_panel_moves_against_the_aggregate(self):
        # O painel (A) piora de 40 para 10, mas a unidade nova C (90) faz o agregado subir.
        counts = {"p1": {"A": (50, 10, 100)}, "p2": {"A": (30, 20, 100), "C": (95, 0, 100)}}
        active = {"p1": {"A"}, "p2": {"A", "C"}}
        out = stats.composition("nps", ["p1", "p2"], counts, active)
        self.assertTrue(out["contradiction"])
        self.assertEqual(out["verdict"], "composition_effect")

    def test_no_panel_and_too_few_periods(self):
        counts = {"p1": {"A": (5, 1, 10)}, "p2": {"B": (6, 1, 10)}}
        out = stats.composition("nps", ["p1", "p2"], counts, {"p1": {"A"}, "p2": {"B"}})
        self.assertEqual(out["buckets"][0]["panel_units"], 0)
        self.assertIn("Nenhuma unidade tem avaliação em todos os períodos: não há painel fixo.", out["reasons"])
        self.assertEqual(stats.composition("nps", ["p1"], counts, {})["verdict"], "insufficient_data")

    def test_proportions(self):
        counts = {"p1": {"A": (10, 100)}, "p2": {"A": (10, 100), "B": (90, 100)}}
        out = stats.composition("prop", ["p1", "p2"], counts, {"p1": {"A"}, "p2": {"A", "B"}})
        self.assertEqual(out["buckets"][1]["aggregate"]["value"], 50.0)
        self.assertEqual(out["verdict"], "composition_effect")


if __name__ == "__main__":
    unittest.main()
