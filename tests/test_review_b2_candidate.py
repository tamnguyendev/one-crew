"""2.5-B cycle 2: CandidateChecker in the shared lifecycle. Real Git candidates and real adapter/command verifiers; the reviewer provider
is a fixture standing in for reviewer.call (no real model call is proven here)."""
import concurrent.futures
import json
import sys
import threading
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))          # test_v2_reviewer imports test_v2_l1 by its plain name

from onecrew import common_verification
from onecrew.common_handoff import handoff
from onecrew.common_verification import CandidateChecker, candidate_tree, snapshot_candidate
from onecrew.ledger import LedgerError
from onecrew.snapshots import Snapshots
from onecrew.v2 import engine, plan, review_dispatch, verdict
from onecrew.v2.verifiers import command, port, reviewer
from tests.test_v2_reviewer import reviewer_milestone
from tests import test_wf_candidate_adapters as adapters
from tests.test_v2_reviewer import answer, row
from tests.test_wf_candidate_reviewer import CandidateReviewerFixture


def counting(calls, real):
    def run(*args, **kwargs):
        calls.append(args[4]['id'] if len(args) > 4 else None)
        return real(*args, **kwargs)
    return run


class CandidateClaims(adapters.CandidateAdapterTests):
    test_same_engine_verifies_three_adapters_on_candidate_without_host_command_grant = None
    test_bad_document_fails_and_unsettled_operation_remains_inconclusive = None

    def checker(self):
        return CandidateChecker(self.ledger, 'P1')

    def tree_of(self, nid='C'):
        view = engine.state(self.ledger, 'P1')
        return candidate_tree(self.ledger, snapshot_candidate(self.ledger, view, nid, view['nodes'][nid]['artifact']))

    def test_t1_a_milestone_passed_on_the_same_tree_is_not_executed_again_by_another_node(self):
        self.step()
        calls = []
        with patch.object(port, 'run', side_effect=counting(calls, port.run)):
            first = self.verify('C', self.checker())
            self.step()
            second = self.verify('I', self.checker())
        self.assertEqual((first['result'], second['result']), ('pass', 'pass'))
        self.assertEqual(first['observed']['candidate_tree'], second['observed']['candidate_tree'])
        self.assertEqual(sorted(calls), ['Data', 'Doc', 'Ops'], 'the same milestones on the same tree must execute once')
        for rowed in second['observed']['checks']:
            wrapper = json.loads(self.store.read_blob(rowed['evidence']))
            self.assertEqual(wrapper['node'], 'I')
            self.assertTrue(wrapper['reused_from_run'])
        delivered = handoff(self.ledger, 'P1')                       # the handoff law still authenticates reused rows as the approved checks
        self.assertEqual(delivered['state'], 'delivered')

    def test_t1_a_live_verdict_run_of_the_same_request_makes_the_candidate_door_observe(self):
        self.step()
        tree = self.tree_of()
        request = review_dispatch.milestone_request(self.ledger, 'P1', 'Doc', tree)
        started = verdict._begin_run(self.ledger, 'P1', 1, 'Doc', 'doc', 5, check=(request, tree))
        with patch.object(port, 'run', side_effect=AssertionError('nothing may be dispatched')):
            out = self.verify('C', self.checker())
        self.assertEqual(out['status'], 'pending')
        self.assertIn(started, out['reason'])
        self.assertEqual((out['check_run']['run_id'], out['check_run']['door']), (started, 'verdict.run'))
        self.assertEqual(self.kinds().count('node.verification'), 0)
        finished = [p for k, p in self.events() if k == 'review.run_finished']
        self.assertEqual([p['outcome'] for p in finished], ['not_dispatched'])

    def test_t1_a_request_differing_only_by_environment_still_observes_the_running_check(self):
        self.step()
        tree = self.tree_of()
        first = review_dispatch.milestone_request(self.ledger, 'P1', 'Doc', tree)
        claim = review_dispatch.claim_check(self.ledger, 'P1', first, door='candidate', subject={'milestone': 'Doc'})
        base = command.verifier_env(self.ledger.project)
        with patch.object(command, 'verifier_env', return_value=dict(base, TEMP='another-shell')):
            second = review_dispatch.milestone_request(self.ledger, 'P1', 'Doc', tree)
            again = review_dispatch.claim_check(self.ledger, 'P1', second, door='candidate', subject={'milestone': 'Doc'})
        self.assertNotEqual(first['id'], second['id'])
        self.assertEqual((again['status'], again['run_id']), ('pending', claim['run_id']))

    def test_t1_a_recorded_verdict_pass_on_the_same_tree_is_reused_with_its_door_named(self):
        (self.root / 'guide.md').write_bytes(self.overlays['guide.md'])
        self.git('add', 'guide.md'); self.git('commit', '-qm', 'the document already in its final form')
        self.assertEqual(verdict.run(self.ledger, 'P1', 'Doc')['milestones'][0]['state'], 'passed')
        self.step()
        calls = []
        with patch.object(port, 'run', side_effect=counting(calls, port.run)):
            done = self.verify('C', self.checker())
        self.assertEqual(done['result'], 'pass', done)
        self.assertEqual(sorted(calls), ['Data', 'Ops'], 'Doc passed through the verdict door on this very tree')
        row = next(r for r in done['observed']['checks'] if r['id'] == 'Doc')
        wrapper = json.loads(self.store.read_blob(row['evidence']))
        self.assertEqual(wrapper['reused_from_door'], 'verdict.run')

    def test_t2_another_environment_or_a_corrupt_proof_means_the_check_runs_again(self):
        self.step()
        self.verify('C', self.checker())
        self.step()
        calls, real_read = [], Snapshots.read_blob
        base = command.verifier_env(self.ledger.project)
        with patch.object(port, 'run', side_effect=counting(calls, port.run)), patch.object(command, 'verifier_env', return_value=dict(base, TZ='another-environment')):
            done = self.verify('I', self.checker())
        self.assertEqual(done['result'], 'pass')
        self.assertEqual(sorted(calls), ['Data', 'Doc', 'Ops'], 'another environment is another request: no reuse')
        # a corrupt proof of an otherwise equal request is no permission to believe it
        prior = {}
        with patch.object(command, 'verifier_env', return_value=dict(base, TZ='another-environment')):
            with self.ledger.transaction() as conn:
                task = plan.anchor_events(self.ledger, conn, 'P1')['task_id']
                tree = done['observed']['candidate_tree']
                prior = review_dispatch.prior_pass(conn, task, review_dispatch.milestone_request(self.ledger, 'P1', 'Doc', tree))
        self.assertIsNotNone(prior)
        def corrupt(store, key): return b'{"kind":"forged"}' if key == prior['proof'] else real_read(store, key)
        view = engine.state(self.ledger, 'P1')
        with self.ledger.transaction() as conn:
            state = plan.anchor_events(self.ledger, conn, 'P1')
            contract = plan.load(self.ledger, state, state['approved']['revision'])[0]
        milestone = next(m for m in contract['milestones'] if m['id'] == 'Doc')
        with patch.object(Snapshots, 'read_blob', autospec=True, side_effect=corrupt):
            row = self.checker()._reused_row({'id': 'C'}, 'C', view['nodes']['C']['artifact'], tree, {}, milestone, prior, view['contract_sha'], view['contract_revision'], {})
        self.assertIsNone(row)

    def test_t3_unknown_mid_candidate_holds_only_what_ran_and_finished_milestones_are_not_repeated(self):
        self.step()
        calls, real = [], port.run
        def flaky(*args, **kwargs):
            calls.append(args[4]['id'])
            if len(calls) == 2: raise OSError('adapter process lost')
            return real(*args, **kwargs)
        with patch.object(port, 'run', side_effect=flaky):
            with self.assertRaises(OSError): self.verify('C', self.checker())
            held = self.verify('C', self.checker())
        self.assertEqual(held['status'], 'held')
        self.assertEqual(len(calls), 2)
        run_id = held['check_run']['run_id']
        tree = self.tree_of()
        with self.ledger.transaction() as conn:
            task = plan.anchor_events(self.ledger, conn, 'P1')['task_id']
            unknown = review_dispatch.milestone_request(self.ledger, 'P1', calls[1], tree)
            self.assertEqual(review_dispatch.verdict_conflict(conn, task, unknown)['state'], 'held')
        review_dispatch.release_check(self.ledger, 'P1', run_id, 'Checked: the adapter wrote nothing outside its scratch.')
        before = list(calls)
        calls.clear()
        with patch.object(port, 'run', side_effect=counting(calls, real)):
            done = self.verify('C', self.checker())
        self.assertEqual(done['result'], 'pass')
        self.assertEqual(sorted(calls + [before[0]]), ['Data', 'Doc', 'Ops'], 'the milestone with a known pass is reused, not repeated')

    def test_t3_refusal_before_any_verifier_is_a_known_outcome_not_a_hold(self):
        self.step()
        with patch.object(common_verification, 'candidate_tree', side_effect=LedgerError('git refused the tree')):
            with self.assertRaisesRegex(LedgerError, 'git refused'):
                self.verify('C', self.checker())
        finished = [p for k, p in self.events() if k == 'review.run_finished']
        self.assertEqual([p['outcome'] for p in finished], ['not_dispatched'])
        self.assertEqual(self.verify('C', self.checker())['result'], 'pass')

    def test_t2_execution_identity_comes_from_what_the_runtime_executes(self):
        self.step()
        done = self.verify('C', self.checker())
        started = [p for k, p in self.events() if k == 'review.run_started' and p['check'] == 'node-verification'][0]
        self.assertTrue(started['request']['execution_complete'], started['request']['missing'])
        self.assertTrue(done['check_run']['cache_reusable'])
        self.assertEqual(started['independence'], 'not_established')
        item = next(n for n in engine.state(self.ledger, 'P1')['definition']['nodes'] if n['id'] == 'C')
        identity = self.checker().execution_identity(item)
        self.assertEqual(identity['method'], 'adapter')
        self.assertIn('CandidateChecker', identity['implementation'])
        self.assertEqual(identity['provenance']['source'], 'approved-contract')
        # a look-alike port states nothing about itself
        class Lookalike(CandidateChecker):
            def __call__(self, item, artifact, *, previous_receipt=None): raise AssertionError('not called here')
        self.assertIsNone(engine._execution_of(Lookalike(self.ledger, 'P1'), item))
        class Plain:
            def execution_identity(self, item): return identity
            def __call__(self, item, artifact): raise AssertionError('not called here')
        self.assertIsNone(engine._execution_of(Plain(), item))

    def test_t2_a_changed_reviewer_pin_or_verifier_config_is_another_request(self):
        milestone = dict(reviewer_milestone(), id='R')
        sha = '0' * 64
        first = review_dispatch._milestone_execution(self.ledger, milestone, sha)
        other = json.loads(json.dumps(milestone)); other['verifier']['config']['model'] = 'claude-opus-5-5'
        second = review_dispatch._milestone_execution(self.ledger, other, sha)
        self.assertEqual(first['provider'], 'claude')
        self.assertNotEqual((first['model'], first['configuration']), (second['model'], second['configuration']))


class ReviewerDoors(CandidateReviewerFixture):
    def test_t1_two_engine_doors_make_one_metered_model_call(self):
        self.produce()
        before = self.counters()['used_calls']
        entered, release, calls = threading.Event(), threading.Event(), []
        def fake(prompt, config, env, scratch, limit):
            calls.append(config['model'])
            if len(calls) == 1:
                entered.set()
                if not release.wait(30): raise RuntimeError('fixture release missing')
            return answer(row('R1')), {}, None, False, b'fixture'
        with patch.object(reviewer, 'call', side_effect=fake):
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                first = pool.submit(self.engine.verify, self.ledger, 'P1', 'C', self.production_checker)
                self.assertTrue(entered.wait(30))
                try:
                    second = self.engine.verify(self.ledger, 'P1', 'C', CandidateChecker(self.ledger, 'P1'))
                finally:
                    release.set()
                done = first.result(timeout=60)
        self.assertEqual(len(calls), 1)
        self.assertEqual(second['status'], 'pending')
        self.assertEqual(second['check_run']['run_id'], done['check_run']['run_id'])
        self.assertEqual(self.counters()['used_calls'], before + 1)
        self.assertEqual(done['result'], 'pass')
        with patch.object(reviewer, 'call', side_effect=AssertionError('a valid pass makes no extra model call')):
            with self.assertRaisesRegex(LedgerError, done['check_run']['run_id']):
                self.engine.verify(self.ledger, 'P1', 'C', self.production_checker)
        self.assertEqual(self.counters()['used_calls'], before + 1)

    def test_t4_self_review_is_refused_before_any_call_and_is_a_known_outcome(self):
        self.producer = {'role': 'worker', 'provider': 'claude', 'model': 'claude-haiku-5-5'}
        self.produce()
        before = self.counters()['used_calls']
        with patch.object(reviewer, 'call', side_effect=AssertionError('independence is refused before the call')):
            with self.assertRaisesRegex(LedgerError, 'reviewer would be the author'):
                self.engine.verify(self.ledger, 'P1', 'C', self.production_checker)
        self.assertEqual(self.counters()['used_calls'], before)
        finished = [p for k, p in self.events() if k == 'review.run_finished']
        self.assertEqual([p['outcome'] for p in finished], ['not_dispatched'])
        self.assertNotIn('node.verification', self.kinds())

    def test_t4_missing_producer_provenance_is_never_counted_independent(self):
        self.produce()
        real = self.ledger.task
        def no_pin(task_id, **kwargs):                                         # a handoff that recorded no provider/model for the producer
            row = real(task_id, **kwargs)
            return dict(row, handoff=dict(row['handoff'], owned_execution={})) if kwargs.get('full') else row
        with patch.object(self.ledger, 'task', side_effect=no_pin), patch.object(reviewer, 'call', side_effect=AssertionError('no call without provenance')):
            with self.assertRaisesRegex(LedgerError, 'independence cannot be shown'):
                self.engine.verify(self.ledger, 'P1', 'C', self.production_checker)
        self.assertNotIn('node.verification', self.kinds())
        finished = [p for k, p in self.events() if k == 'review.run_finished']
        self.assertEqual([p['outcome'] for p in finished], ['not_dispatched'])

    def test_t4_model_error_leaves_the_node_unverified_and_keeps_the_receipt(self):
        self.produce()
        def broken(prompt, config, env, scratch, limit):
            return '', {}, 'provider failed', False, b''
        with patch.object(reviewer, 'call', side_effect=broken):
            result = self.engine.verify(self.ledger, 'P1', 'C', self.production_checker)
        self.assertNotEqual(result['result'], 'pass')
        self.assertNotEqual(self.engine.state(self.ledger, 'P1')['nodes']['C']['state'], 'verified')
        self.assertEqual(result['check_run']['executed'], True)

    def test_t3_a_lost_provider_call_is_held_then_released_with_its_charge_kept(self):
        self.produce()
        before = self.counters()['used_calls']
        def lost(prompt, config, env, scratch, limit): raise OSError('connection lost after the prompt was sent')
        with patch.object(reviewer, 'call', side_effect=lost):
            with self.assertRaises(OSError):
                self.engine.verify(self.ledger, 'P1', 'C', self.production_checker)
        charged = self.counters()['used_calls']
        self.assertGreater(charged, before)
        with patch.object(reviewer, 'call', side_effect=AssertionError('an unknown call must not be replayed')):
            held = self.engine.verify(self.ledger, 'P1', 'C', self.production_checker)
        self.assertEqual(held['status'], 'held')
        self.assertEqual(self.counters()['used_calls'], charged)
        released = review_dispatch.release_check(self.ledger, 'P1', held['check_run']['run_id'], 'Checked: the provider log shows no completed answer.')
        self.assertEqual(len(released['settled_attempts']), 1)
        self.assertGreaterEqual(self.counters()['used_calls'], charged)     # the lost call stays charged
        calls = []
        with patch.object(reviewer, 'call', side_effect=self.fake_call(calls)):
            done = self.engine.verify(self.ledger, 'P1', 'C', self.production_checker)
        self.assertEqual((done['result'], len(calls)), ('pass', 1))
        self.assertEqual(self.counters()['used_calls'], charged + 1)
