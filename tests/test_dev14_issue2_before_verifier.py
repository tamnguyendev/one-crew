"""2.5.0.dev14 — issue #2, the part that applies to 2.5 (tamnguyendev/one-crew, from MEP 09/11; review DANH-GIA-ISSUE-2-10.vi.md; owner: "Đưa vào").

A failure before the command verifier is called (a git checkout that fails, an OSError, a LedgerError from the environment, a missing working
directory, no scratch directory) must say so: `verifier_started = False`. Without it verdict.run keeps the run as "unknown outcome" and nothing
runs again until someone types release-run. Only a SnapshotFailed carried the mark before. Red on 698e118.
"""
from pathlib import Path
from unittest.mock import patch

from onecrew.ledger import LedgerError
from onecrew.v2 import contract as contracts, plan as plans, verdict
from onecrew.v2.verifiers import command
from tests.test_v2_l1 import Fixture, plan_json


class BeforeTheVerifier(Fixture):
    def setUp(self):
        super().setUp()
        plans.propose(self.ledger, 'P1', plan_json(), 'claude')
        plans.approve(self.ledger, 'P1', 'owner', 'fixture')

    def milestone(self):
        return contracts.validate(plan_json())['milestones'][0]           # with the defaults validation adds (max_minutes)

    def raised(self, **patches):
        with patch.multiple(command, **patches):
            with self.assertRaises(Exception) as caught:
                command.run(self.ledger, 'P1', 1, 'x' * 64, self.milestone(), self.root)
        return caught.exception

    def test_any_failure_before_the_command_starts_says_it_did_not_start(self):
        for name, error in (('_checkout', OSError(28, 'No space left on device')), ('_checkout', LedgerError('git checkout-index failed')),
                            ('verifier_env', LedgerError('environment refused')), ('verifier_env', ValueError('bad value'))):
            with self.subTest(step=name, error=type(error).__name__):
                failed = self.raised(**{name: lambda *a, **k: (_ for _ in ()).throw(error)})
                self.assertIs(getattr(failed, 'verifier_started', None), False, repr(failed))

    def test_a_missing_working_directory_and_no_scratch_directory_say_it_too(self):
        with self.assertRaises(LedgerError) as caught:
            command.run(self.ledger, 'P1', 1, 'x' * 64, self.milestone(), self.root / 'gone')
        self.assertIs(getattr(caught.exception, 'verifier_started', None), False)
        with patch.object(command.tempfile, 'mkdtemp', side_effect=OSError(13, 'Access is denied')), self.assertRaises(OSError) as caught:
            command.run(self.ledger, 'P1', 1, 'x' * 64, self.milestone(), self.root)
        self.assertIs(getattr(caught.exception, 'verifier_started', None), False)

    def test_a_failure_after_the_command_ran_is_not_marked_as_not_started(self):
        with patch.object(command.Snapshots, 'blob', side_effect=OSError(28, 'disk full after the run')), self.assertRaises(OSError) as caught:
            command.run(self.ledger, 'P1', 1, 'x' * 64, self.milestone(), self.root)
        self.assertIsNot(getattr(caught.exception, 'verifier_started', None), False)

    def test_verdict_run_is_not_held_and_runs_again_without_release_run(self):
        with patch.object(command, '_checkout', side_effect=OSError(28, 'No space left on device')), self.assertRaises(OSError):
            verdict.run(self.ledger, 'P1', 'M1', self.root)
        shown = verdict.run(self.ledger, 'P1', 'M1', self.root)                  # on 698e118: refused, a run of unknown outcome is held
        self.assertEqual(shown['milestones'][0]['state'], 'passed', shown['milestones'][0])
