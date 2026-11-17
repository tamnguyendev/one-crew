"""DEV31 slice B (issue #36): one review request -> one reviewer call and one budget charge, whichever door reaches it.

Doors: engine.verify (also `engine step/batch --checks`), the candidate port inside it, `verdict run` and the optional review door.
Real temporary ledgers from the existing fixtures; reviewers are local fakes counted at their provider seam. No model is called.
"""
import copy
import os
import subprocess
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))   # the checkout fixtures import test_v2_l1 by its plain name

from onecrew.ledger import Ledger, LedgerError
from onecrew.snapshots import Snapshots
from onecrew.v2 import engine, internal_plan, plan, plan as plans, review_dispatch, review_request
from onecrew.v2.verifiers import command

try:                                  # checkout-only fixtures (Control, the candidate port, the reviewer seam): absent from the wheel
    from onecrew.common_verification import CandidateChecker
    from onecrew.v2.verifiers import reviewer
    from tests.test_v2_reviewer import answer, row
    from tests.test_wf_candidate_reviewer import CandidateReviewerFixture
    CHECKOUT = True
except ImportError:
    CHECKOUT, CandidateReviewerFixture = False, unittest.TestCase

OK = [sys.executable, '-c', 'print("ok")']
QUESTIONS = ['Q1', 'Q2', 'Q3', 'Q4', 'Q5', 'Q9', 'Q12']
CAPS = ['namespaced-storage', 'root-budget', 'internal-plan', 'sequential-engine']


def contract(**extra):
    """The smallest contract that passes step 0 (same shape the checkout fixtures use), self-contained so the wheel can run this module."""
    value = {'schema_version': 2, 'title': 'Sample', 'size': 'S',
             'understanding': {'restated_goal': 'Do the sample and prove it.', 'target': {'repo': '.', 'ref': 'HEAD', 'paths': ['a.txt']},
                               'assumptions': [], 'confidence': 'high', 'unknowns': []},
             'preconditions': [{'id': 'P1', 'check': 'path_exists', 'args': {'path': 'a.txt'}, 'why': 'the file to work on is there'}],
             'output': ['The sample exists'], 'scope': {'owned': ['a.txt']}, 'non_goals': ['Nothing else'],
             'items': [{'id': 'I1', 'title': 'Do it', 'tier': 'must', 'milestone': 'M1'},
                       {'id': 'S1', 'title': 'Nice to have', 'tier': 'should'}, {'id': 'W1', 'title': 'Never', 'tier': 'wont'}],
             'milestones': [{'id': 'M1', 'title': 'Milestone M1', 'verifier': {'type': 'command', 'config': {'argv': OK}}, 'covers': ['O1']}],
             'budget': {'max_calls': 100, 'time': 120}, 'attention': {'questions': 1}, 'profile_version': None}
    return dict(value, **extra)


def node(nid, dependencies=(), integration=False, write=('a.txt',)):
    return {'id': nid, 'goal': 'Produce evidence for O1', 'input': [], 'output': ['Evidence for O1'],
            'acceptance': ['O1'], 'depends': [{'node': upstream, 'requires': 'verified'} for upstream in dependencies],
            'read': ['a.txt'], 'write': list(write), 'resources': [], 'estimate_seconds': [1, 2],
            'execution_cap_seconds': 60, 'budget_calls': 1,
            'checks': [{'id': 'check-' + nid, 'spec': 'Check the declared O1 output of ' + nid}], 'integration': integration}


class CoreFixture(unittest.TestCase):
    """A real temporary Git project and ledger; only installed (wheel) modules are used."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        base = Path(self.temp.name)
        self.root = base / 'project'; self.root.mkdir()
        self.git('init', '-q'); self.git('config', 'user.name', 'T'); self.git('config', 'user.email', 't@localhost')
        (self.root / 'a.txt').write_text('one\n'); self.git('add', '.'); self.git('commit', '-q', '-m', 'base')
        self.ledger = Ledger(self.root, base / 'state')
        self.store = Snapshots(self.ledger.state_root)
        env = patch.dict(os.environ); env.start(); self.addCleanup(env.stop)
        for name in ('ONECREW_ACTOR', 'ONECREW_V2_REQUIRE_PLAN', 'CLAUDECODE', 'CLAUDE_CODE_CHILD_SESSION'): os.environ.pop(name, None)

    def git(self, *args):
        return subprocess.run(['git', '-C', str(self.root), *args], check=True, capture_output=True).stdout.decode().strip()

    def approved(self):
        plans.propose(self.ledger, 'P1', contract(), 'claude')
        return plans.approve(self.ledger, 'P1', 'owner', 'said yes in chat')

    def events(self):
        with self.ledger.transaction() as conn:
            task = plans.derive(self.ledger, conn, 'P1')['task_id']
        return [(e['kind'], e['payload']) for e in self.ledger.events(task)]

    def kinds(self):
        return [k for k, _ in self.events()]

    def payloads(self, kind):
        return [p for k, p in self.events() if k == kind]

    def tree(self):
        return command.artifact_sha(self.root)


class CoreEngine(CoreFixture):
    """The node door (engine.verify) on a synthetic produced node: no Control, no provider; the checker is a local callable."""

    def setUp(self):
        super().setUp()
        value = contract(scope={'owned': ['a.txt', 'b.txt']}, review_policy={'depth': 'deep', 'optional_reviews': ['extra']},
                         authority={'edit': True, 'commands': True, 'edit_tests': True, 'self_decide': QUESTIONS})
        plans.propose(self.ledger, 'P1', value, 'codex', workflow=True, capabilities=CAPS)
        plans.approve(self.ledger, 'P1', 'owner', 'fixture engine approval')
        os.environ['ONECREW_ACTOR'] = 'codex'
        internal_plan.revise(self.ledger, 'P1', [node('C'), node('I', ['C'], integration=True, write=())],
                             reason='Split work inside the approved scope', evidence=['a.txt:1'])

    def step(self):
        artifact, receipt = self.store.blob(b'artifact-C'), self.store.blob(b'executor-C')
        with self.ledger.transaction(write=True) as conn:
            current = engine.state(self.ledger, 'P1', conn)
            engine._event(self.ledger, conn, current, 'C', 'node.produced', artifact=artifact, receipt=receipt, inputs={})
        return {'node': 'C'}

    def checker(self, item, artifact):
        return {'artifact': artifact, 'checks': [{'id': check['id'], 'result': 'pass', 'evidence': self.store.blob(b'fixture check passed')}
                                                 for check in item['checks']]}

    def verify(self, nid, checker=None):
        return engine.verify(self.ledger, 'P1', nid, checker or self.checker)


class Counting:
    def __init__(self, test):
        self.test, self.calls = test, []

    def __call__(self, item, artifact):
        self.calls.append(artifact)
        return self.test.checker(item, artifact)


class EngineDoor(CoreEngine):
    def runs(self):
        return self.payloads('review.run_started')

    def test_duplicate_verify_calls_checker_once_and_second_door_names_the_run(self):
        self.step()
        one, two = Counting(self), Counting(self)
        done = self.verify('C', one)
        with self.assertRaises(LedgerError) as raised:
            self.verify('C', two)
        self.assertEqual((len(one.calls), len(two.calls)), (1, 0))
        self.assertIn(done['check_run']['run_id'], str(raised.exception))
        self.assertEqual(self.kinds().count('node.verification'), 1)
        self.assertEqual(len(self.runs()), 1)

    def test_duplicate_in_flight_checker_without_identity_still_observes_the_running_check(self):
        self.step()
        entered, release, calls = threading.Event(), threading.Event(), []
        def slow(item, artifact):
            calls.append('slow'); entered.set()
            if not release.wait(20): raise RuntimeError('fixture release missing')
            return self.checker(item, artifact)
        import concurrent.futures
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            first = pool.submit(self.verify, 'C', slow)
            self.assertTrue(entered.wait(20))
            try:
                with patch.object(engine, '_execution_of', return_value={'method': 'adapter', 'implementation': 'other-door', 'configuration': {},
                                                                         'environment': {'shell': 'b'}, 'provenance': {'door': 'b'}}):
                    second = self.verify('C', Counting(self))
            finally:
                release.set()
            done = first.result(timeout=30)
        self.assertEqual(calls, ['slow'])
        self.assertEqual(second['status'], 'pending')
        self.assertEqual(second['check_run']['run_id'], done['check_run']['run_id'])
        self.assertEqual(len(self.runs()), 1)

    def test_independent_reviews_kept_required_check_and_optional_review_both_run_once(self):
        self.step()
        artifact = engine.state(self.ledger, 'P1')['nodes']['C']['artifact']
        optional_calls = []
        def optional_checker(item, art):
            optional_calls.append(art)
            return {'result': 'pass', 'artifact': art}
        execution = {'method': 'adapter', 'implementation': 'fixture-optional', 'configuration': {}, 'environment': {'fixture': 'local'},
                     'provenance': {'adapter': 'test_dev31_review_dedup'}}
        required = Counting(self)
        one = review_dispatch.optional(self.ledger, 'P1', 'C', 'extra', optional_checker, artifact, execution=execution)
        again = review_dispatch.optional(self.ledger, 'P1', 'C', 'extra', None, artifact, execution=execution)
        done = self.verify('C', required)
        self.assertEqual((len(optional_calls), len(required.calls)), (1, 1))
        self.assertNotEqual(one['request_id'], done['check_run']['request_id'])
        self.assertTrue(again['cached_observation'])
        self.assertEqual(len(self.runs()), 2, 'a required check and an optional review of one node are two pieces of work')
        self.assertEqual(self.kinds().count('node.verification'), 1)

    def test_out_of_order_late_result_of_a_released_run_never_becomes_the_pass_of_the_new_run(self):
        self.step()
        calls = []
        def lost(item, art): calls.append('lost'); raise OSError('connection reset')
        with self.assertRaises(OSError): self.verify('C', lost)
        held = self.verify('C', Counting(self))
        old = held['check_run']['run_id']
        review_dispatch.release_check(self.ledger, 'P1', old, 'Checked: the fixture wrote nothing.')
        fresh = Counting(self)
        done = self.verify('C', fresh)
        self.assertNotEqual(done['check_run']['run_id'], old)
        # the first run's result arrives only now, after its release and the second run's publication
        late = review_dispatch.issue_check(self.ledger, 'P1', old, self.store.blob(b'late result of the released run'))
        self.assertEqual(late, 'finished')
        self.assertEqual((calls, len(fresh.calls)), (['lost'], 1))
        self.assertEqual(self.kinds().count('node.verification'), 1)
        with self.assertRaises(LedgerError): self.verify('C', Counting(self))
        finished = [p for k, p in self.events() if k == 'review.run_finished']
        self.assertEqual(sorted(p['outcome'] for p in finished), ['published', 'released'])

    def test_out_of_order_finish_before_result_is_idempotent_and_leaves_one_run(self):
        self.step()
        artifact = engine.state(self.ledger, 'P1')['nodes']['C']['artifact']
        claim, _ = review_dispatch.claim_node_check(self.ledger, 'P1', 'C', execution=None, door='engine.verify',
                                                    expected=(artifact, engine.state(self.ledger, 'P1')['nodes']['C']['generation']))
        with self.ledger.transaction(write=True) as conn:
            root = review_dispatch.plan.anchor_events(self.ledger, conn, 'P1')
            self.assertTrue(review_dispatch.finish_check(self.ledger, conn, root['task_id'], claim['run_id'], outcome='not_dispatched'))
            self.assertFalse(review_dispatch.finish_check(self.ledger, conn, root['task_id'], claim['run_id'], outcome='not_dispatched'))
        self.assertEqual(review_dispatch.issue_check(self.ledger, 'P1', claim['run_id'], self.store.blob(b'x')), 'finished')
        only = Counting(self)
        self.assertEqual(self.verify('C', only)['result'], 'pass')
        self.assertEqual(len(only.calls), 1)
        self.assertEqual(self.kinds().count('review.run_started'), 2)


    def test_unknown_outcome_reconnect_and_retry_no_replay_hold_the_run_and_charge_nothing_more(self):
        self.step()
        before = self.budget_calls()
        lost_calls = []
        def lost(item, artifact): lost_calls.append(artifact); raise OSError('connection reset after dispatch')
        with self.assertRaises(OSError): self.verify('C', lost)
        fresh = Ledger(self.root, self.ledger.state_root)                       # a reconnect: a new connection, no memory of the first
        again = Counting(self)
        for ledger in (self.ledger, fresh, fresh):
            held = engine.verify(ledger, 'P1', 'C', again)
            self.assertEqual(held['status'], 'held')
            self.assertIn('unknown', held['reason'])
            self.assertIn('release-check', held['next'])
        self.assertEqual((len(lost_calls), len(again.calls)), (1, 0))
        self.assertEqual(self.budget_calls(), before)
        self.assertEqual(self.kinds().count('review.run_started'), 1)
        self.assertNotIn('node.verification', self.kinds())
        review_dispatch.release_check(self.ledger, 'P1', held['check_run']['run_id'], 'Checked: the fixture wrote nothing.')
        done = self.verify('C', again)                                          # only the explicit release lets it ask once more
        self.assertEqual((done['result'], len(again.calls)), ('pass', 1))

    def test_crash_reconcile_issued_result_is_published_from_its_receipt_without_a_second_call(self):
        self.step()
        real, calls = engine._event, Counting(self)
        def crash(ledger, conn, view, nid, kind, **payload):
            if kind == 'node.verification': raise RuntimeError('process lost before publication')
            return real(ledger, conn, view, nid, kind, **payload)
        with patch.object(engine, '_event', side_effect=crash):
            with self.assertRaises(RuntimeError): self.verify('C', calls)
        again = engine.verify(Ledger(self.root, self.ledger.state_root), 'P1', 'C', lambda *a: self.fail('an issued result must not run again'))
        self.assertEqual((again['result'], len(calls.calls)), ('pass', 1))
        self.assertTrue(again['check_run']['reconciled'])
        self.assertEqual(self.kinds().count('node.verification'), 1)

    def test_crash_reconcile_dead_process_before_the_result_is_held_and_never_replayed(self):
        self.step()
        calls = Counting(self)
        with patch.object(review_dispatch, '_hold'):                           # a killed process writes nothing after its start
            with self.assertRaises(OSError): self.verify('C', lambda item, artifact: (_ for _ in ()).throw(OSError('killed')))
        with patch('onecrew.v2.verdict.process_alive', return_value=False):
            held = self.verify('C', calls)
        self.assertEqual((held['status'], len(calls.calls)), ('held', 0))
        self.assertEqual(self.kinds().count('review.run_started'), 1)

    def test_retry_no_replay_after_a_published_pass_names_the_run_and_calls_nothing(self):
        self.step()
        first, second = Counting(self), Counting(self)
        done = self.verify('C', first)
        for _ in range(2):
            with self.assertRaises(LedgerError) as raised: self.verify('C', second)
            self.assertIn(done['check_run']['run_id'], str(raised.exception))
        self.assertEqual((len(first.calls), len(second.calls)), (1, 0))

    def budget_calls(self):
        with self.ledger.transaction() as conn:
            root = internal_plan.context(self.ledger, conn, 'P1', 'sequential-engine')[0]
            return internal_plan.ceilings(self.ledger, conn, root)['remaining_calls']


class RequestIdentity(CoreFixture):
    """Which asks are the same request: claims and reuse are decided on the request id (and its in-flight work key)."""

    def setUp(self):
        super().setUp()
        self.approved()
        self.base = review_dispatch.milestone_request(self.ledger, 'P1', 'M1', self.tree())

    def claim(self, request, milestone='M1'):
        return review_dispatch.claim_check(self.ledger, 'P1', request, door='candidate', subject={'milestone': milestone})

    def settle_pass(self, claim):
        proof = Snapshots(self.ledger.state_root).blob(b'proof of ' + claim['run_id'].encode())
        with self.ledger.transaction(write=True) as conn:
            task = plans.anchor_events(self.ledger, conn, 'P1')['task_id']
            review_dispatch.finish_check(self.ledger, conn, task, claim['run_id'], outcome='observed', receipt=proof, proof=proof, result='pass', applicable=True)

    def prior(self, request):
        with self.ledger.transaction() as conn:
            task = plans.anchor_events(self.ledger, conn, 'P1')['task_id']
            return review_dispatch.prior_pass(conn, task, request)

    def contract(self):
        with self.ledger.transaction() as conn:
            state = plans.anchor_events(self.ledger, conn, 'P1')
            target = plans.resolve(self.ledger, state)
            contract, sha = plans.load(self.ledger, state, target['revision'])
        return state, target['revision'], sha, contract

    def test_duplicate_same_request_from_two_doors_is_one_claim_and_a_pass_is_reused(self):
        first = self.claim(self.base)
        again = self.claim(review_dispatch.milestone_request(self.ledger, 'P1', 'M1', self.tree()))
        self.assertEqual((first['status'], again['status'], again['run_id']), ('claimed', 'pending', first['run_id']))
        self.settle_pass(first)
        found = self.prior(self.base)
        self.assertEqual(found['run_id'], first['run_id'])
        self.assertEqual(self.kinds().count('review.run_started'), 1)

    def test_wrong_revision_is_another_request_and_neither_blocks_nor_reuses_the_pass(self):
        state, revision, sha, contract = self.contract()
        milestone = contract['milestones'][0]
        other = review_dispatch._milestone_request(self.ledger, state['task_id'], state['name'], revision + 1, sha, contract, milestone, self.tree())
        self.assertNotEqual(other['id'], self.base['id'])
        self.assertNotEqual(review_request.evidence_status(self.base, other)['status'], 'applies')
        first = self.claim(self.base)
        second = self.claim(other)
        self.assertEqual(second['status'], 'claimed')
        self.assertNotEqual(second['run_id'], first['run_id'])
        self.settle_pass(first)
        self.assertIsNone(self.prior(other), 'a pass of revision 1 is not a pass of the amended revision')

    def test_wrong_artifact_is_another_request_and_neither_blocks_nor_reuses_the_pass(self):
        first = self.claim(self.base)
        (self.root / 'a.txt').write_text('two\n'); self.git('commit', '-qam', 'the artifact moved')
        other = review_dispatch.milestone_request(self.ledger, 'P1', 'M1', self.tree())
        self.assertNotEqual(other['id'], self.base['id'])
        second = self.claim(other)
        self.assertEqual((second['status'] == 'claimed', second['run_id'] != first['run_id']), (True, True))
        self.settle_pass(first)
        self.assertIsNone(self.prior(other))
        self.assertIsNotNone(self.prior(self.base))

    def test_wrong_criterion_is_another_request_and_neither_blocks_nor_reuses_the_pass(self):
        state, revision, sha, contract = self.contract()
        milestone = contract['milestones'][0]
        other = review_dispatch._milestone_request(self.ledger, state['task_id'], state['name'], revision, sha, contract, milestone, self.tree(), criterion='R-other')
        self.assertNotEqual(other['id'], self.base['id'])
        first = self.claim(self.base)
        second = self.claim(other)
        self.assertEqual(second['status'], 'claimed')
        self.settle_pass(first)
        self.assertIsNone(self.prior(other))

    def test_wrong_scope_is_another_request(self):
        state, revision, sha, contract = self.contract()
        wider = copy.deepcopy(contract)
        wider['scope']['owned'] = sorted(wider['scope']['owned']) + ['extra/**']
        other = review_dispatch._milestone_request(self.ledger, state['task_id'], state['name'], revision, sha, wider, wider['milestones'][0], self.tree())
        self.assertNotEqual(other['id'], self.base['id'])
        self.assertEqual(self.claim(self.base)['status'], 'claimed')
        self.assertEqual(self.claim(other)['status'], 'claimed')

    def test_independent_reviews_kept_two_reviewers_on_one_tree_are_two_requests(self):
        state, revision, sha, contract = self.contract()
        first_milestone = contract['milestones'][0]
        second_milestone = copy.deepcopy(first_milestone)
        second_milestone['id'] = 'M2'
        second_milestone['verifier'] = {'type': 'reviewer', 'config': {'provider': 'claude', 'model': 'claude-haiku-5-5', 'max_minutes': 5,
                                        'criteria': [{'id': 'R1', 'question': 'Does a.txt change?'}]}}
        third_milestone = copy.deepcopy(second_milestone)
        third_milestone['id'] = 'M3'
        third_milestone['verifier']['config']['model'] = 'claude-sonnet-5-5'
        ids = []
        for milestone in (second_milestone, third_milestone):
            request = review_dispatch._milestone_request(self.ledger, state['task_id'], state['name'], revision, sha, contract, milestone, self.tree())
            claim = self.claim(request, milestone['id'])
            self.assertEqual(claim['status'], 'claimed', 'independent mandatory reviews are not merged')
            ids.append((request['id'], claim['run_id']))
        self.assertEqual(len({i[0] for i in ids}), 2)
        self.assertEqual(len({i[1] for i in ids}), 2)
        self.assertEqual(self.kinds().count('review.run_started'), 2)

    def test_out_of_order_late_result_after_release_does_not_make_a_pass(self):
        first = self.claim(self.base)
        review_dispatch._hold(self.ledger, 'P1', first['run_id'], 'outcome unknown')
        self.assertEqual(self.claim(self.base)['status'], 'held')
        review_dispatch.release_check(self.ledger, 'P1', first['run_id'], 'Checked: nothing ran.')
        second = self.claim(self.base)
        self.assertEqual((second['status'], second['run_id'] != first['run_id']), ('claimed', True))
        self.assertEqual(review_dispatch.issue_check(self.ledger, 'P1', first['run_id'], Snapshots(self.ledger.state_root).blob(b'late')), 'finished')
        self.assertIsNone(self.prior(self.base))
        self.assertEqual(self.claim(self.base)['run_id'], second['run_id'])


@unittest.skipUnless(CHECKOUT, "needs the checkout-only Control, candidate port and reviewer fixtures (not in the wheel)")
class ReviewerCalls(CandidateReviewerFixture):
    """Real production port (CandidateChecker) and the metered reviewer seam: calls and the shared root budget are counted."""

    def check(self, ledger=None):
        ledger = ledger or self.ledger
        return self.engine.verify(ledger, 'P1', 'C', CandidateChecker(ledger, 'P1'))

    def charged(self):
        return self.counters()['used_calls']

    def test_duplicate_verify_makes_one_reviewer_call_and_one_charge(self):
        self.produce()
        before, calls = self.charged(), []
        with patch.object(reviewer, 'call', side_effect=self.fake_call(calls)):
            done = self.check()
            for door in ('engine.step', 'engine.batch'):
                with self.assertRaises(LedgerError) as raised:
                    self.engine.verify(self.ledger, 'P1', 'C', CandidateChecker(self.ledger, 'P1'), door=door)
                self.assertIn(done['check_run']['run_id'], str(raised.exception))
        self.assertEqual((done['result'], len(calls), self.charged() - before), ('pass', 1, 1))
        self.assertEqual(self.kinds().count('node.verification'), 1)

    def test_reconnect_with_a_fresh_ledger_and_checker_observes_the_running_review(self):
        import concurrent.futures
        self.produce()
        before = self.charged()
        entered, release, calls = threading.Event(), threading.Event(), []
        def slow(prompt, config, env, scratch, limit):
            calls.append(config['model'])
            entered.set()
            if not release.wait(30): raise RuntimeError('fixture release missing')
            return answer(row('R1')), {}, None, False, b'fixture'
        with patch.object(reviewer, 'call', side_effect=slow):
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                first = pool.submit(self.check)
                self.assertTrue(entered.wait(30))
                try:
                    fresh = Ledger(self.root, self.ledger.state_root)               # a new connection, as after a reconnect
                    second = self.check(fresh)
                finally:
                    release.set()
                done = first.result(timeout=60)
        self.assertEqual((second['status'], len(calls)), ('pending', 1))
        self.assertEqual(second['check_run']['run_id'], done['check_run']['run_id'])
        self.assertEqual(self.charged() - before, 1)

    def test_unknown_outcome_is_held_charged_once_and_retry_no_replay_after_reconnect(self):
        self.produce()
        before = self.charged()
        def lost(prompt, config, env, scratch, limit): raise OSError('connection lost after the prompt was sent')
        with patch.object(reviewer, 'call', side_effect=lost):
            with self.assertRaises(OSError): self.check()
        charged = self.charged()
        self.assertEqual(charged - before, 1)
        fresh = Ledger(self.root, self.ledger.state_root)
        with patch.object(reviewer, 'call', side_effect=AssertionError('an unknown outcome is never replayed')):
            for ledger in (self.ledger, fresh, fresh):
                held = self.check(ledger)
                self.assertEqual(held['status'], 'held')
                self.assertIn('unknown', (held['reason'] or '') + str(held.get('check_run')))
                self.assertIn('release-check', held['next'])
        self.assertEqual(self.charged(), charged)
        self.assertNotIn('node.verification', self.kinds())

    def test_retry_no_replay_after_a_failed_review_asks_the_reviewer_nothing_new(self):
        self.produce()
        before, calls = self.charged(), []
        def failing(prompt, config, env, scratch, limit):
            calls.append(1)
            return answer(row('R1', 'fail')), {}, None, False, b'fixture'
        with patch.object(reviewer, 'call', side_effect=failing):
            first = self.check()
            self.assertEqual(first['result'], 'fail')
            for _ in range(2):
                with self.assertRaises(LedgerError): self.check()
        self.assertEqual((len(calls), self.charged() - before), (1, 1))

    def test_crash_reconcile_result_issued_but_not_published_completes_without_a_second_call(self):
        self.produce()
        before, calls = self.charged(), []
        real = engine._event
        def crash(ledger, conn, view, nid, kind, **payload):
            if kind == 'node.verification': raise RuntimeError('process lost before publication')
            return real(ledger, conn, view, nid, kind, **payload)
        with patch.object(reviewer, 'call', side_effect=self.fake_call(calls)):
            with patch.object(engine, '_event', side_effect=crash):
                with self.assertRaises(RuntimeError): self.check()
            again = self.check(Ledger(self.root, self.ledger.state_root))
        self.assertEqual((again['result'], len(calls), self.charged() - before), ('pass', 1, 1))
        self.assertTrue(again['check_run']['reconciled'])
        self.assertEqual(self.kinds().count('node.verification'), 1)

    def test_crash_reconcile_dead_process_after_the_reviewer_answered_never_asks_again_after_release(self):
        """The reviewer answered and its milestone is settled, then the process died before the node result was issued: the run is held
        (unknown), and even after the owner releases it the settled milestone pass is reused, not asked again."""
        self.produce()
        before, calls = self.charged(), []
        def dies(ledger, selector, run_id, receipt): raise KeyboardInterrupt('process killed before the node result was issued')
        with patch.object(reviewer, 'call', side_effect=self.fake_call(calls)):
            with patch.object(review_dispatch, 'issue_check', side_effect=dies):
                with self.assertRaises(KeyboardInterrupt): self.check()
            with patch('onecrew.v2.verdict.process_alive', return_value=False):
                held = self.check()
            self.assertEqual(held['status'], 'held')
            self.assertEqual(len(calls), 1)
            review_dispatch.release_check(self.ledger, 'P1', held['check_run']['run_id'], 'Checked: the node result never reached the ledger.')
            done = self.check()
        self.assertEqual(done['result'], 'pass')
        self.assertEqual((len(calls), self.charged() - before), (1, 1), 'the settled reviewer pass of this very request must be reused')

    def test_wrong_artifact_a_new_candidate_is_reviewed_again_and_the_old_pass_is_not_reused(self):
        self.produce()
        before, calls = self.charged(), []
        with patch.object(reviewer, 'call', side_effect=self.fake_call(calls)):
            first = self.check()
        self.assertEqual(first['result'], 'pass')
        tree_one = first['observed']['candidate_tree']
        with self.ledger.transaction() as conn:
            task = plan.anchor_events(self.ledger, conn, 'P1')['task_id']
            milestone = next(m for m in plan.load(self.ledger, plan.anchor_events(self.ledger, conn, 'P1'), 1)[0]['milestones'] if m['id'] == 'M2')
            self.assertIsNone(review_dispatch.prior_pass(conn, task, review_dispatch.milestone_request(self.ledger, 'P1', 'M2', 'f' * 40)))
            self.assertIsNotNone(review_dispatch.prior_pass(conn, task, review_dispatch.milestone_request(self.ledger, 'P1', 'M2', tree_one)))
        self.assertEqual((len(calls), self.charged() - before), (1, 1))
        self.assertEqual(milestone['verifier']['type'], 'reviewer')
