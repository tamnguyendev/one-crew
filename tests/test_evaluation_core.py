"""The installed evidence classifiers are the same functions used by v1."""
import unittest
from onecrew import evaluation_core, eval_observe, eval_scorecard


class SharedEvaluationTests(unittest.TestCase):
    def test_v1_observer_delegates(self):
        for name in ('label', 'decision_source', 'signals'):
            self.assertIs(getattr(eval_observe, name), getattr(evaluation_core, name))

    def test_v1_scorecard_delegates(self):
        for name in ('role', 'classified', 'decisions', 'assistance_level', 'completion_level', 'outcome'):
            self.assertIs(getattr(eval_scorecard, name), getattr(evaluation_core, name))
