"""T36b: immutable ranges, sourced changes and unknown measurements."""
from tests.test_v2_l1 import Fixture, plan_json
from onecrew.ledger import LedgerError
from onecrew.v2 import estimates, plan, report


class EstimateTests(Fixture):
    def start(self):
        self.propose()
        plan.approve(self.ledger, 'P1', 'owner', 'fixture', estimate={
            'execution_seconds': [21600, 28800], 'evidence': ['fixture task decomposition'],
            'deadline': '2026-10-25T08:00:00+07:00'})

    def test_first_approval_writes_baseline_once_and_restart_keeps_it(self):
        self.start()
        first = estimates.read(self.ledger, 'P1')['baseline']
        plan.approve(self.ledger, 'P1', 'owner', 'repeat')
        self.assertEqual(first, estimates.read(self.ledger, 'P1')['baseline'])
        self.assertEqual(self.kinds().count('estimate.baseline'), 1)

    def test_optional_work_never_enters_remaining_or_silently_expands_scope(self):
        self.start()
        estimates.additional(self.ledger, 'P1', 'cleanup', 'optional', 'not required', ['O1'], [3600, 7200], ['fixture'])
        self.assertEqual(estimates.read(self.ledger, 'P1')['remaining_seconds'], [21600, 28800])
        estimates.additional(self.ledger, 'P1', 'migration', 'mandatory', 'needed for O1', ['O1'], [3600, 7200], ['fixture'])
        out = estimates.read(self.ledger, 'P1')
        self.assertEqual(out['remaining_seconds'], [25200, 36000])
        self.assertEqual(out['additional'][0]['disposition'], 'backlog')
        self.assertEqual(len(self.ledger.requests(plan.show(self.ledger, 'P1')['anchor_task'])), 0)

    def test_reforecast_needs_reason_and_evidence_and_keeps_history(self):
        self.start()
        with self.assertRaises(LedgerError): estimates.reforecast(self.ledger, 'P1', 'm1', [18000, 25200], '', ['receipt'])
        estimates.reforecast(self.ledger, 'P1', 'm1', [18000, 25200], 'M1 complete', ['receipt:fixture'])
        estimates.reforecast(self.ledger, 'P1', 'm2', [10800, 18000], 'M2 complete', ['receipt:fixture2'])
        out = estimates.read(self.ledger, 'P1')
        self.assertEqual(out['baseline']['execution_seconds'], [21600, 28800])
        self.assertEqual(len(out['history']), 2)
        self.assertEqual(out['execution_seconds'], 'unknown')
        self.assertEqual(out['waiting_seconds'], 'unknown')
        self.assertFalse(out['calibrated'])

    def test_no_estimate_input_means_unknown_not_budget_as_prediction(self):
        self.approved()
        out = estimates.read(self.ledger, 'P1')
        self.assertIsNone(out['baseline']['execution_seconds'])
        self.assertIsNone(out['remaining_seconds'])

    def test_invalid_estimate_refused_before_approval(self):
        self.propose()
        with self.assertRaises(LedgerError): plan.approve(self.ledger, 'P1', 'owner', 'fixture', estimate={'execution_seconds': [9, 2]})
        self.assertNotIn('plan.approved', self.kinds())

    def test_present_and_report_share_range_and_reason_without_mutation(self):
        self.start()
        estimates.reforecast(self.ledger, 'P1', 'done-1', [18000, 25200], 'M1 completed with receipt', ['fixture'])
        before = self.events()
        for render in (report.render_present, report.render_report):
            text = render(self.ledger.state_root, 'P1')
            self.assertIn('6–8', text)
            self.assertIn('5–7', text)
            self.assertIn('M1 completed with receipt', text)
            self.assertIn('chưa đo được', text)
        self.assertEqual(before, self.events())
