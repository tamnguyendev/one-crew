"""F1/F3/F4/F6/F7/F9/F10: Claude C1,C2,C3,C7,C8,C11,C13 as asserted regressions."""
import json
import os
import sys
import time
from unittest.mock import patch
from onecrew.ledger import LedgerError
from onecrew.common_handoff import handoff
from onecrew.common_verification import CandidateChecker
from onecrew.v2 import engine, findings, plan, internal_plan, review_dispatch, verdict
from onecrew.v2.verifiers import artifact, command
from tests.test_v2_l1 import Fixture, milestone, plan_json
from tests.test_review_b2_e2e import LoopFixture
from tests import test_review_b2_e2e as e2e
from tests import test_wf_candidate_reviewer as reviewer_fixture

class ProjectionCases(Fixture):
    def test_f7_report_hashes_once_and_next_operation_observes_changes(self):
        plan.propose(self.ledger, 'P1', plan_json(), 'codex', workflow=True)
        plan.approve(self.ledger, 'P1', 'owner', 'fixture')
        real = command._git
        walks = []
        def counted(directory, *args, **kwargs):
            if 'update-index' in args: walks.append(args)
            return real(directory, *args, **kwargs)
        with patch.object(command, '_git', side_effect=counted):
            shown = verdict.run(self.ledger, 'P1', 'M1')
        self.assertEqual(shown['milestones'][0]['state'], 'passed')
        self.assertLessEqual(len(walks), 3, walks)  # verifier before/after + one fresh publication observation
        (self.root / 'dependency.txt').write_text('changed outside owned')
        self.assertTrue(plan.show(self.ledger, 'P1')['milestones'][0]['stale'])

    def test_f9_stopped_plan_is_not_successful_reentry(self):
        value = plan_json(milestones=[milestone(argv=[sys.executable, '-c', 'print("fail");exit(1)'], max_repairs=1)])
        plan.propose(self.ledger, 'P1', value, 'codex', workflow=True)
        plan.approve(self.ledger, 'P1', 'owner', 'fixture')
        verdict.run(self.ledger, 'P1', 'M1')
        verdict.run(self.ledger, 'P1', 'M1')
        self.assertEqual(plan.show(self.ledger, 'P1')['status'], 'stopped_with_report')
        before = self.events()
        with self.assertRaisesRegex(LedgerError, 'stopped'):
            plan.propose(self.ledger, 'P1', value, 'codex', workflow=True, reuse_existing=True)
        self.assertEqual(self.events(), before)

    def test_f6_snapshot_entrypoints_obey_configured_budget_without_outer_scope(self):
        with patch.dict(os.environ, {'ONECREW_SNAPSHOT_MINUTES': '0.02'}):
            with command._snapshot('acceptance'):
                self.assertEqual(command._active.get().limit, 1.2)
                with command._snapshot('nested'):
                    self.assertEqual(command._active.get().limit, 1.2)
        with patch.dict(os.environ, {'ONECREW_SNAPSHOT_MINUTES': 'bad'}):
            with self.assertRaises(LedgerError): command.artifact_sha(self.root)

class CandidateCases(LoopFixture):
    paths = ('a.txt',)
    bad = {'a.txt': b'candidate\n'}
    milestones = (milestone('M1', argv=[sys.executable, '-c', 'print("checked")']),)
    def prepare(self): pass

    def delivered(self):
        checker = CandidateChecker(self.ledger, 'P1')
        self.step(); self.assertEqual(self.verify('C', checker)['result'], 'pass')
        self.step(); self.assertEqual(self.verify('I', checker)['result'], 'pass')
        return handoff(self.ledger, 'P1')

    def test_f3_handoff_to_verdict_reuses_authentic_proof_then_accepts(self):
        with patch.object(command, 'run', wraps=command.run) as called:
            delivered = self.delivered()
            count = called.call_count
            shown = verdict.run(self.ledger, 'P1', 'M1')
            self.assertEqual(called.call_count, count)
        last = shown['milestones'][0]['last_verdict']
        proof = json.loads(self.store.read_blob(last['receipt']))
        self.assertEqual(proof['reused_from']['door'], 'candidate')
        self.assertEqual((proof['calls'], proof['seconds'], proof['execution_seconds']), (0, 0, 0))
        # An already published derived receipt must still authenticate during
        # reconciliation/recheck; it cannot invalidate itself as a newer result.
        with self.ledger.transaction() as conn:
            state = plan.anchor_events(self.ledger, conn, 'P1')
            contract, sha = plan.load(self.ledger, state, 1)
        checked = verdict._check_receipt(self.ledger, 'P1', 1, sha, contract['milestones'][0], 'pass',
            'command', delivered['artifact'], last['receipt'], {(1, 'M1', last['receipt'])})
        self.assertEqual(checked['reused_from'], proof['reused_from'])
        with self.assertRaisesRegex(LedgerError, 'AI cannot approve or accept'):
            plan.accept(self.ledger, 'P1', 'owner', 'fixture', delivered['artifact'])
        with patch.dict(os.environ, {'ONECREW_ACTOR': 'owner'}):
            self.assertEqual(plan.accept(self.ledger, 'P1', 'owner', 'temporary fixture only', delivered['artifact'])['status'], 'accepted')

    def test_f3_changed_environment_never_reuses_candidate(self):
        self.delivered()
        with patch.dict(os.environ, {'CI': 'changed'}), patch.object(command, 'run', wraps=command.run) as called:
            shown = verdict.run(self.ledger, 'P1', 'M1')
            self.assertEqual(called.call_count, 1)
        self.assertEqual(shown['milestones'][0]['state'], 'passed')

    def test_f4_before_verifier_timeout_is_retryable_without_release(self):
        self.step()
        checker = CandidateChecker(self.ledger, 'P1')
        failure = command.SnapshotFailed('before', 'update-index', 1, 1, verifier_started=False)
        with patch.object(command, 'run', side_effect=failure) as called:
            with self.assertRaises(command.SnapshotFailed): self.verify('C', checker)
            self.assertEqual(called.call_count, 1)
        self.assertFalse([r for r in review_dispatch.check_runs(self.ledger, 'P1') if r['state'] == 'held'])
        self.assertEqual(self.verify('C', checker)['result'], 'pass')

    def test_f4_unknown_effect_is_still_held(self):
        self.step()
        with patch.object(command, 'run', side_effect=RuntimeError('unknown after dispatch')):
            with self.assertRaises(RuntimeError): self.verify('C', CandidateChecker(self.ledger, 'P1'))
        self.assertTrue([r for r in review_dispatch.check_runs(self.ledger, 'P1') if r['state'] == 'held'])

    def test_f10_preflight_failure_stops_before_any_dispatch(self):
        failure = command.SnapshotFailed('identity', 'update-index', 1, 1)
        with patch.object(artifact, 'identity', side_effect=failure) as capture, patch.object(command, 'run') as call:
            with self.assertRaises(command.SnapshotFailed): verdict.run(self.ledger, 'P1', 'M1')
            self.assertEqual(capture.call_count, 1)
            call.assert_not_called()
        self.assertNotIn('verdict.run_started', self.kinds())

    def test_f6_snapshot_time_does_not_consume_command_cap(self):
        nodes = self.nodes()
        for item in nodes:
            item['execution_cap_seconds'] = 10
            item['estimate_seconds'] = [1, 2]
        self.revise(nodes)
        self.step()
        real = command.verified_sha
        first = [True]
        def slow(*args, **kwargs):
            if first[0]: first[0] = False; time.sleep(10.1)
            return real(*args, **kwargs)
        with patch.object(command, 'verified_sha', side_effect=slow):
            self.assertEqual(self.verify('C', CandidateChecker(self.ledger, 'P1'))['result'], 'pass')


class AdapterReuse(LoopFixture):
    paths = e2e.DocumentDataCase.paths
    bad = e2e.DocumentDataCase.good
    milestones = e2e.DocumentDataCase.milestones
    prepare = e2e.DocumentDataCase.prepare

    def test_document_and_data_use_the_same_authentic_handoff_reuse(self):
        from onecrew.v2.verifiers import port
        checker = CandidateChecker(self.ledger, 'P1')
        self.step(); self.assertEqual(self.verify('C', checker)['result'], 'pass')
        self.step(); self.assertEqual(self.verify('I', checker)['result'], 'pass')
        delivered = handoff(self.ledger, 'P1')
        with patch.object(port, 'run', wraps=port.run) as calls:
            for mid in ('Doc', 'Data'):
                result = verdict.run(self.ledger, 'P1', mid)
                observed = next(m for m in result['milestones'] if m['id']==mid)
                self.assertEqual(observed['state'], 'passed', observed)
            calls.assert_not_called()
        with patch.dict(os.environ, {'ONECREW_ACTOR': 'owner'}):
            self.assertEqual(plan.accept(self.ledger, 'P1', 'owner', 'temporary adapter fixture', delivered['artifact'])['status'], 'accepted')


class ReviewerReuse(reviewer_fixture.CandidateReviewerFixture):
    def test_reviewer_reuse_preserves_real_call_proof_without_new_charge(self):
        from onecrew.v2.verifiers import reviewer
        self.produce()
        calls = []
        with patch.object(reviewer, 'call', side_effect=self.fake_call(calls)):
            self.assertEqual(self.verify('C', self.production_checker)['result'], 'pass')
            self.step(); self.assertEqual(self.verify('I', self.production_checker)['result'], 'pass')
            handoff(self.ledger, 'P1')
            spent = self.counters()['used_calls']
            verdict.run(self.ledger, 'P1', 'M1')
            shown = verdict.run(self.ledger, 'P1', 'M2')
        self.assertEqual(len(calls), 1)
        self.assertEqual(self.counters()['used_calls'], spent)
        observed = next(m for m in shown['milestones'] if m['id'] == 'M2')
        self.assertEqual(observed['state'], 'passed', observed)
        proof = json.loads(self.store.read_blob(observed['last_verdict']['receipt']))
        self.assertEqual((proof['calls'], proof['new_calls']), (1, 0))
        recorded = [p for k, p in self.events() if k == 'verdict.recorded' and p['milestone'] == 'M2'][-1]
        self.assertEqual(recorded['calls'], 0)
