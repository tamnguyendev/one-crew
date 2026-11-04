"""2.5-B cycle 2: one claim/observe/reconcile lifecycle for the required node check door (engine.verify, which
`engine verify`, `engine step --checks` and `engine batch --checks` all reach) and its link to the verdict door.

Real temporary ledger, Git and Control attempts from the engine fixtures. Checkers are local callables: they prove
the coordination, not any provider behaviour. No model is called.
"""
import concurrent.futures
import copy
import io
import json
import threading
from contextlib import redirect_stdout
from unittest.mock import patch

from onecrew.ledger import LedgerError
from onecrew.v2 import engine, review_dispatch, review_policy
from tests import test_wf_engine as fixtures
from tests.test_v2_l1 import Fixture, plan_json


class CheckFixture(fixtures.EngineFixture):
    def setUp(self):
        with patch.object(fixtures, 'plan_json', side_effect=lambda **kw: plan_json(
                review_policy={'depth': 'deep', 'optional_reviews': ['extra']}, **kw)):
            super().setUp()
        self.nodes = [fixtures.node('C'), fixtures.node('I', ['C'], integration=True, write=())]
        self.revise(self.nodes)

    def payloads(self, kind):
        return [p for k, p in self.events() if k == kind]

    def budget(self):
        with self.ledger.transaction() as conn:
            root = self.ip.context(self.ledger, conn, 'P1', 'sequential-engine')[0]
            return self.ip.ceilings(self.ledger, conn, root)


class RequiredCheckLifecycle(CheckFixture):
    # ---- RV-T1: one effective dispatch per request, every caller sees the same run -------------------------------------------
    def test_t1_concurrent_verify_dispatches_once_and_both_see_the_same_run(self):
        self.step()
        entered, release, calls = threading.Event(), threading.Event(), []
        def checker(item, artifact):
            calls.append(artifact)
            if len(calls) == 1:
                entered.set()
                if not release.wait(20): raise RuntimeError('fixture release missing')
            return self.checker(item, artifact)
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            first = pool.submit(self.verify, 'C', checker)
            self.assertTrue(entered.wait(20))
            try:
                second = self.verify('C', checker)
            finally:
                release.set()
            done = first.result(timeout=30)
        self.assertEqual(len(calls), 1, 'a second door must observe the running check, not dispatch it again')
        self.assertEqual(second.get('status'), 'pending')
        self.assertFalse(second['check_run']['executed'])
        self.assertEqual(second['check_run']['run_id'], done['check_run']['run_id'])
        self.assertEqual(second['check_run']['request_id'], done['check_run']['request_id'])
        self.assertEqual(self.kinds().count('node.verification'), 1)
        self.assertEqual(done['result'], 'pass')

    def test_t1_recall_after_valid_pass_calls_no_checker_and_names_the_run(self):
        self.step()
        done = self.verify('C')
        with self.assertRaisesRegex(LedgerError, 'Only the current produced node can be verified') as raised:
            self.verify('C', lambda *a: self.fail('a valid pass must not dispatch again'))
        self.assertIn(done['check_run']['run_id'], str(raised.exception))
        self.assertEqual(self.kinds().count('node.verification'), 1)

    def test_t1_the_shared_listing_shows_the_running_check_to_other_doors(self):
        self.step()
        entered, release = threading.Event(), threading.Event()
        def checker(item, artifact):
            entered.set()
            if not release.wait(20): raise RuntimeError('fixture release missing')
            return self.checker(item, artifact)
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            first = pool.submit(self.verify, 'C', checker)
            self.assertTrue(entered.wait(20))
            try:
                active = review_dispatch.active_checks(self.ledger, 'P1')
            finally:
                release.set()
            done = first.result(timeout=30)
        self.assertEqual([(a['door'], a['node'], a['run_id']) for a in active],
                         [('engine.verify', 'C', done['check_run']['run_id'])])
        self.assertEqual(review_dispatch.active_checks(self.ledger, 'P1'), [])

    # ---- RV-T2: a change during the check never certifies the new input -------------------------------------------------------
    def test_t2_change_during_check_finishes_stale_and_new_input_is_a_new_request(self):
        self.step()
        def changing(item, artifact):
            changed = copy.deepcopy(self.nodes); changed[0]['goal'] = 'Changed during the check'
            self.revise(changed)
            return self.checker(item, artifact)
        with self.assertRaises(LedgerError): self.verify('C', changing)
        self.assertNotIn('node.verification', self.kinds())
        finished = [p for p in self.payloads('review.run_finished') if p.get('door') == 'engine.verify']
        self.assertEqual([p['applicable'] for p in finished], [False])
        old = finished[0]
        self.step()                                                  # the new generation of C
        calls = []
        def counting(item, artifact): calls.append(artifact); return self.checker(item, artifact)
        done = self.verify('C', counting)
        self.assertEqual(len(calls), 1)
        self.assertNotEqual(done['check_run']['request_id'], old['request_id'])
        self.assertNotEqual(done['check_run']['run_id'], old['run_id'])
        self.assertEqual(done['result'], 'pass')

    # ---- RV-T3: crash / unknown outcome / late response --------------------------------------------------------------------------
    def test_t3_crash_after_checker_result_is_completed_from_the_issued_receipt(self):
        self.step()
        real = engine._event
        def crash(ledger, conn, view, nid, kind, **payload):
            if kind == 'node.verification': raise RuntimeError('process lost before publication')
            return real(ledger, conn, view, nid, kind, **payload)
        calls = []
        def counting(item, artifact): calls.append(artifact); return self.checker(item, artifact)
        with patch.object(engine, '_event', side_effect=crash):
            with self.assertRaises(RuntimeError): self.verify('C', counting)
        again = self.verify('C', lambda *a: self.fail('an issued result must not run again'))
        self.assertEqual(len(calls), 1)
        self.assertEqual(again['result'], 'pass')
        self.assertTrue(again['check_run']['reconciled'])
        self.assertFalse(again['check_run']['executed'])
        self.assertEqual(self.kinds().count('node.verification'), 1)
        self.assertEqual(self.engine.state(self.ledger, 'P1')['nodes']['C']['state'], 'verified')

    def test_t3_unknown_outcome_is_held_explained_and_released_without_budget_reset(self):
        self.step()
        before = self.budget()
        def lost(item, artifact): raise OSError('connection reset after dispatch')
        with self.assertRaises(OSError): self.verify('C', lost)
        held = self.verify('C', lambda *a: self.fail('an unknown outcome must not be replayed'))
        self.assertEqual(held['status'], 'held')
        self.assertIn('unknown', held['reason'])
        self.assertIn('release-check', held['next'])
        run_id = held['check_run']['run_id']
        again = review_dispatch.reconcile_check(self.ledger, 'P1', run_id)
        self.assertEqual(again['status'], 'held')
        with self.assertRaisesRegex(LedgerError, 'reason'):
            review_dispatch.release_check(self.ledger, 'P1', run_id, '  ')
        released = review_dispatch.release_check(self.ledger, 'P1', run_id, 'Checked: the fixture checker wrote nothing.')
        self.assertFalse(released['budget_reset'])
        calls = []
        def counting(item, artifact): calls.append(artifact); return self.checker(item, artifact)
        done = self.verify('C', counting)
        self.assertEqual((len(calls), done['result']), (1, 'pass'))
        self.assertNotEqual(done['check_run']['run_id'], run_id)
        after = self.budget()
        self.assertLessEqual(after['remaining_calls'], before['remaining_calls'])
        self.assertEqual(after['deadline'], before['deadline'])
        self.assertEqual(self.ledger.requests(), [])

    def test_t3_lost_controller_without_receipt_is_held_when_its_process_is_gone(self):
        self.step()
        def lost(item, artifact): raise OSError('killed')
        with patch.object(review_dispatch, '_hold'):               # a killed controller writes nothing after its start
            with self.assertRaises(OSError): self.verify('C', lost)
        with patch('onecrew.v2.verdict.process_alive', return_value=False):
            held = self.verify('C', lambda *a: self.fail('a dead controller does not permit replay'))
        self.assertEqual(held['status'], 'held')
        self.assertEqual(self.kinds().count('node.verification'), 0)

    def test_t3_late_result_of_a_held_run_is_kept_but_never_published_twice(self):
        self.step()
        entered, release = threading.Event(), threading.Event()
        def slow(item, artifact):
            entered.set()
            if not release.wait(20): raise RuntimeError('fixture release missing')
            return self.checker(item, artifact)
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            first = pool.submit(self.verify, 'C', slow)
            self.assertTrue(entered.wait(20))
            run_id = review_dispatch.active_checks(self.ledger, 'P1')[0]['run_id']
            review_dispatch._hold(self.ledger, 'P1', run_id, 'timed out by the caller; outcome unknown')
            release.set()
            late = first.result(timeout=30)
        self.assertEqual(late['status'], 'late')
        self.assertNotIn('node.verification', self.kinds())
        self.assertEqual(len(self.payloads('review.run_result')), 1)       # the late receipt is evidence, kept
        settled = review_dispatch.reconcile_check(self.ledger, 'P1', run_id)
        self.assertEqual(settled['status'], 'published')
        self.assertEqual(self.kinds().count('node.verification'), 1)
        self.assertEqual(review_dispatch.reconcile_check(self.ledger, 'P1', run_id)['status'], 'finished')
        self.assertEqual(self.kinds().count('node.verification'), 1)

    def test_t3_cli_exposes_reconcile_and_release(self):
        from onecrew.v2 import engine_cli
        self.step()
        def lost(item, artifact): raise OSError('ambiguous')
        with self.assertRaises(OSError): self.verify('C', lost)
        run_id = self.payloads('review.run_started')[-1]['run_id']
        def cli(*argv):
            out = io.StringIO()
            with redirect_stdout(out):
                code = engine_cli.main(['--project', str(self.root), '--state-root', str(self.ledger.state_root), 'engine', *argv],
                                       checker=lambda ledger, selector: self.checker)
            return code, json.loads(out.getvalue())
        code, shown = cli('reconcile-check', 'P1', run_id)
        self.assertEqual((code, shown['status']), (0, 'held'))
        code, listed = cli('check-runs', 'P1')
        self.assertEqual([(r['run_id'], r['door'], r['state']) for r in listed], [(run_id, 'engine.verify', 'held')])
        code, shown = cli('release-check', 'P1', run_id, '--reason', 'Checked the checker log: nothing ran.')
        self.assertEqual((code, shown['run_id']), (0, run_id))
        code, shown = cli('verify', 'P1', 'C')
        self.assertEqual((code, shown['result']), (0, 'pass'))

    # ---- RV-T4: no self-declared identity --------------------------------------------------------------------------------------
    def test_t4_unidentified_checker_gets_no_cache_and_no_independence_claim(self):
        self.step()
        done = self.verify('C')
        run = self.payloads('review.run_started')[-1]
        self.assertFalse(run['request']['execution_complete'])
        self.assertIn('execution.implementation', run['request']['missing'])
        self.assertEqual(run['independence'], 'not_established')
        self.assertFalse(done['check_run']['cache_reusable'])


class VerdictDoorLink(Fixture):
    """The verdict door keeps its own run records (W37a/W44); cycle 2 binds them to the same milestone request id."""

    def test_verdict_run_records_the_milestone_request_it_executes(self):
        self.approved()
        verdict_run = __import__('onecrew.v2.verdict', fromlist=['run']).run
        verdict_run(self.ledger, 'P1', 'M1', self.root)
        started = [p for k, p in self.events() if k == 'verdict.run_started'][0]
        self.assertTrue(str(started.get('request_id', '')).startswith('review-'))
        self.assertEqual(started['request']['identity']['kind'], 'milestone')
        self.assertEqual(started['candidate'], self.tree())
        self.assertEqual(started['request_id'], review_dispatch.milestone_request(self.ledger, 'P1', 'M1', self.tree())['id'])

    def test_an_active_candidate_claim_of_the_same_milestone_request_refuses_a_verdict_dispatch(self):
        from onecrew.v2 import verdict
        self.approved()
        request = review_dispatch.milestone_request(self.ledger, 'P1', 'M1', self.tree())
        claim = review_dispatch.claim_check(self.ledger, 'P1', request, door='candidate', subject={'milestone': 'M1'})
        self.assertEqual(claim['status'], 'claimed')
        with patch.object(verdict.command, 'run', side_effect=AssertionError('must not dispatch')):
            with self.assertRaisesRegex(LedgerError, claim['run_id']):
                verdict.run(self.ledger, 'P1', 'M1', self.root)
        again = review_dispatch.claim_check(self.ledger, 'P1', request, door='candidate', subject={'milestone': 'M1'})
        self.assertEqual((again['status'], again['run_id']), ('pending', claim['run_id']))


class IndependentBranch(fixtures.EngineFixture):
    def test_a_held_check_holds_only_its_node_and_what_depends_on_it(self):
        other = fixtures.node('X', write=('b.txt',)); other['read'] = ['b.txt']
        self.revise([fixtures.node('C'), other, fixtures.node('I', ['C', 'X'], integration=True, write=())])
        self.assertEqual(self.step()['node'], 'C')
        def lost(item, artifact): raise OSError('ambiguous')
        with self.assertRaises(OSError): self.verify('C', lost)
        self.assertEqual(self.verify('C', lambda *a: self.fail('no replay'))['status'], 'held')
        self.assertEqual(self.step()['node'], 'X')                   # the independent branch still runs
        self.assertEqual(self.verify('X')['result'], 'pass')
        self.assertEqual(self.engine.ready(self.ledger, 'P1'), [])   # the integration waits for the held dependency
        self.assertEqual(self.engine.state(self.ledger, 'P1')['nodes']['C']['state'], 'produced')


class OverdueClaim(VerdictDoorLink):
    test_verdict_run_records_the_milestone_request_it_executes = None
    test_an_active_candidate_claim_of_the_same_milestone_request_refuses_a_verdict_dispatch = None

    def test_t3_a_run_past_its_deadline_is_held_not_pending_forever_and_not_replayed(self):
        self.approved()
        request = review_dispatch.milestone_request(self.ledger, 'P1', 'M1', self.tree())
        past = '2020-01-01T00:00:00+00:00'
        claim = review_dispatch.claim_check(self.ledger, 'P1', request, door='candidate', subject={'milestone': 'M1'}, deadline=past)
        again = review_dispatch.claim_check(self.ledger, 'P1', request, door='candidate', subject={'milestone': 'M1'}, deadline=past)
        self.assertEqual((again['status'], again['run_id']), ('held', claim['run_id']))
        self.assertIn('deadline', again['reason'])
        self.assertEqual(review_dispatch.reconcile_check(self.ledger, 'P1', claim['run_id'])['status'], 'held')


class RacingProcesses(Fixture):
    SCRIPT = (
        'import json, sys, time\n'
        'from pathlib import Path\n'
        'from onecrew.ledger import Ledger\n'
        'from onecrew.v2 import review_dispatch\n'
        'project, state, request, start = sys.argv[1:5]\n'
        'while not Path(start).exists(): time.sleep(0.01)\n'
        'claim = review_dispatch.claim_check(Ledger(Path(project), Path(state)), "P1", json.loads(Path(request).read_text()), door="candidate", subject={"milestone": "M1"})\n'
        'print(json.dumps({"status": claim["status"], "run_id": claim["run_id"]}))\n')

    def test_t1_separate_processes_racing_for_one_request_get_one_claim(self):
        import subprocess, sys, tempfile
        from pathlib import Path
        self.approved()
        request = review_dispatch.milestone_request(self.ledger, 'P1', 'M1', self.tree())
        with tempfile.TemporaryDirectory() as temp:
            data, start = Path(temp) / 'request.json', Path(temp) / 'start'
            data.write_text(json.dumps(request))
            repo = str(Path(__file__).resolve().parents[1])
            racers = [subprocess.Popen([sys.executable, '-B', '-X', 'utf8', '-c', self.SCRIPT, str(self.root), str(self.ledger.state_root), str(data), str(start)],
                                       stdout=subprocess.PIPE, stderr=subprocess.PIPE, cwd=repo) for _ in range(3)]
            start.write_text('go')
            outs = [racer.communicate(timeout=120) for racer in racers]
        for racer, (_, err) in zip(racers, outs): self.assertEqual(racer.returncode, 0, err.decode())
        answers = [json.loads(out) for out, _ in outs]
        self.assertEqual(sorted(a['status'] for a in answers).count('claimed'), 1, answers)
        self.assertEqual(len({a['run_id'] for a in answers}), 1, answers)
        self.assertEqual(self.kinds().count('review.run_started'), 1)
