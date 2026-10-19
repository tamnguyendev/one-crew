"""v2.1 job 11a, item 2: the command verifier is fail-closed. A run with exit 0 is `inconclusive`, never `pass`, when it is suspicious,
and the receipt names the rule. Real runs here set `command.MIN_SECONDS` through a patch (the stub the 2-second rule allows)."""
import json
import sys
from unittest.mock import patch

from onecrew.snapshots import Snapshots
from onecrew.v2 import verdict
from onecrew.v2.verifiers import command
from tests.test_v2_l1 import BAD, OK, PY, Fixture, milestone, plan_json

SLEEPY = [PY, '-c', 'import time; time.sleep(2.3); print("ok")']


class Rules(Fixture):
    """The pure rule on receipt fields (no process)."""

    def body(self, **fields):
        return dict({'error': None, 'timed_out': False, 'exit_code': 0, 'artifact_sha': 'a', 'artifact_sha_after': 'a', 'argv': OK,
                     'seconds': 5.0, 'stdout_bytes': 3, 'stderr_bytes': 0}, **fields)

    def test_each_rule_makes_an_exit_zero_inconclusive_and_names_itself(self):
        cases = ((dict(stdout_bytes=0, stderr_bytes=0), 'suspicious: empty_output'),
                 (dict(stdout_bytes=0, stderr_bytes=0, seconds=0.8), 'suspicious: fast_and_silent'),
                 (dict(argv=[PY, '-c', 'print(1)', 'x\x07']), 'suspicious: control_char_argv'),
                 (dict(exit_code=None, error='FileNotFoundError: [WinError 2] nope'), 'suspicious: executable_not_found'),
                 (dict(exit_code=127), 'suspicious: executable_not_found'),
                 (dict(exit_code=9009), 'suspicious: executable_not_found'))
        for fields, rule in cases:
            body = self.body(**fields)
            self.assertEqual(command.suspicious_rule(body), rule, fields)
            self.assertEqual(command.expected_result(body), 'inconclusive', fields)

    def test_a_genuine_pass_and_a_genuine_failure_are_unchanged(self):
        self.assertIsNone(command.suspicious_rule(self.body()))
        self.assertEqual(command.expected_result(self.body()), 'pass')
        self.assertEqual(command.expected_result(self.body(stdout_bytes=0, stderr_bytes=40, seconds=2.0)), 'pass')   # output on stderr only is output
        self.assertEqual(command.expected_result(self.body(seconds=0.3)), 'pass')                    # fast alone is not suspicious: a device check prints in 1-2 s
        self.assertEqual(command.expected_result(self.body(stdout_bytes=0, stderr_bytes=0, seconds=2.0)), 'inconclusive')   # silent alone is, at any speed
        self.assertEqual(command.expected_result(self.body(exit_code=3)), 'fail')
        self.assertEqual(command.expected_result(self.body(exit_code=3, stdout_bytes=0, seconds=0.1)), 'fail')   # a failure is not softened

    def test_a_receipt_from_before_the_rules_is_not_judged_on_what_it_never_recorded(self):
        old = {k: v for k, v in self.body().items() if k not in ('seconds', 'stdout_bytes', 'stderr_bytes')}
        self.assertEqual(command.expected_result(old), 'pass')


class RealRuns(Fixture):
    def setUp(self):
        super().setUp()
        clock = patch.object(command, 'MIN_SECONDS', 0.0); clock.start(); self.addCleanup(clock.stop)

    def run_one(self, argv, minimum=None):
        self.approved('P1', plan_json(milestones=[milestone('M1', argv, max_repairs=3)]))
        if minimum is None:
            view = verdict.run(self.ledger, 'P1', 'M1', self.root)
        else:
            with patch.object(command, 'MIN_SECONDS', minimum): view = verdict.run(self.ledger, 'P1', 'M1', self.root)
        last = view['milestones'][0]['last_verdict']
        return last['result'], json.loads(Snapshots(self.ledger.state_root).read_blob(last['receipt']).decode('utf-8'))

    def test_empty_output_is_inconclusive(self):
        result, receipt = self.run_one([PY, '-c', 'pass'])
        self.assertEqual((result, receipt['exit_code'], receipt['suspicious']), ('inconclusive', 0, 'suspicious: empty_output'))

    def test_a_fast_and_silent_run_is_inconclusive_but_a_fast_run_that_prints_passes(self):
        result, receipt = self.run_one([PY, '-c', 'pass'], minimum=3600.0)       # the stub: any real run is "fast" for this threshold
        self.assertEqual((result, receipt['suspicious']), ('inconclusive', 'suspicious: fast_and_silent'))

    def test_a_fast_run_with_output_is_a_genuine_pass(self):
        result, receipt = self.run_one(OK, minimum=3600.0)
        self.assertEqual(result, 'pass'); self.assertNotIn('suspicious', receipt)

    def test_a_control_character_in_argv_is_inconclusive(self):
        result, receipt = self.run_one([PY, '-c', 'print("ok")', 'x\x07'])
        self.assertEqual((result, receipt['suspicious']), ('inconclusive', 'suspicious: control_char_argv'))

    def test_a_missing_executable_is_inconclusive(self):
        result, receipt = self.run_one(['onecrew-no-such-program-11a'])
        self.assertEqual((result, receipt['suspicious']), ('inconclusive', 'suspicious: executable_not_found'))
        self.assertTrue(receipt['error'].startswith('FileNotFoundError'))

    def test_a_genuine_pass_keeps_its_verdict_and_names_no_rule(self):
        result, receipt = self.run_one(OK)
        self.assertEqual(result, 'pass'); self.assertNotIn('suspicious', receipt)
        self.assertGreater(receipt['stdout_bytes'], 0)

    def test_a_genuine_failure_stays_a_failure(self):
        result, receipt = self.run_one(BAD)
        self.assertEqual((result, receipt['exit_code']), ('fail', 3)); self.assertNotIn('suspicious', receipt)


class DefaultThreshold(Fixture):
    def test_with_the_real_threshold_a_fast_run_that_prints_passes_without_any_patch(self):
        self.approved('P1', plan_json(milestones=[milestone('M1', OK)]))
        self.assertEqual(verdict.run(self.ledger, 'P1', 'M1', self.root)['milestones'][0]['last_verdict']['result'], 'pass')

    def test_with_the_real_threshold_a_run_that_takes_longer_than_two_seconds_passes(self):
        self.approved('P1', plan_json(milestones=[milestone('M1', SLEEPY)]))
        with patch.object(command, 'MIN_SECONDS', 2.0):             # the documented threshold, whatever a test run set before
            last = verdict.run(self.ledger, 'P1', 'M1', self.root)['milestones'][0]['last_verdict']
        self.assertEqual(last['result'], 'pass')
