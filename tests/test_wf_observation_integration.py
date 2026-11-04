"""Cross-feature regressions: namespaces, actual artifact freshness and v1 metrics."""
import unittest
from unittest.mock import patch

from tests.test_v2_l1 import Fixture, plan_json
from onecrew.v2 import active_plan, hook_cli, metrics, namespaces, plan, verdict


class ObservationIntegrationTests(Fixture):
    def test_refresh_preserves_namespace_and_does_not_create_legacy_copy(self):
        self.propose('alpha', plan_json())
        plan.approve(self.ledger, 'alpha', 'owner', 'fixture authority')
        exported = active_plan.build(self.ledger, 'alpha')
        refreshed = hook_cli.refreshed(self.root, exported)
        self.assertEqual(refreshed['anchor'], 'plan-ns:alpha')
        self.assertTrue(namespaces.active_file(self.ledger, 'plan-ns:alpha').is_file())
        self.assertFalse((self.ledger.state_root / 'plans' / 'alpha' / 'active-plan.json').exists())

    def test_changed_artifact_is_not_reported_as_verified(self):
        self.propose('alpha', plan_json())
        plan.approve(self.ledger, 'alpha', 'owner', 'fixture authority')
        verdict.run(self.ledger, 'alpha', 'M1')
        self.assertIsNotNone(metrics.measure(self.ledger, 'alpha')['time_to_output']['verified_at'])
        (self.root / 'changed.txt').write_text('new unverified result', encoding='utf-8')
        self.assertIsNone(metrics.measure(self.ledger, 'alpha')['time_to_output']['verified_at'])


class WaitUnionTests(unittest.TestCase):
    def test_overlapping_waits_are_not_subtracted_twice(self):
        start, end = '2026-10-24T10:00:00+00:00', '2026-10-24T11:00:00+00:00'
        items = [dict(minutes=40, **{'from': start, 'to': '2026-10-24T10:40:00+00:00'}),
                 dict(minutes=40, **{'from': '2026-10-24T10:20:00+00:00', 'to': end})]
        self.assertEqual(metrics._inside(items, start, end), 60)

    def test_v1_and_wheel_delegate_to_identical_functions(self):
        from onecrew import evaluation_core, eval_observe, eval_scorecard
        self.assertIs(eval_observe.signals, evaluation_core.signals)
        self.assertIs(eval_scorecard.outcome, evaluation_core.outcome)
        self.assertIs(metrics.v1_evaluator().outcome, evaluation_core.outcome)
