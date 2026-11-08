"""Independent review of the integrated build 9933bbf: every reproduced finding, as a regression test that keeps the expected behaviour.
Real temporary ledgers, Git and verifiers; reviewer and Jev providers are local fixtures, so real provider behaviour stays unproven."""
import concurrent.futures
import contextlib
import io
import json
import os
import sys
import tempfile
import threading
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))          # inherited fixtures import test_v2_l1 by its plain name

from onecrew import budget_core, decision_client_core as client   # noqa: E402
from onecrew.common_handoff import handoff                         # noqa: E402
from onecrew.common_verification import CandidateChecker           # noqa: E402
from onecrew.control_core import CapacityWait                      # noqa: E402
from onecrew.ledger import LedgerError                             # noqa: E402
from onecrew.snapshots import Snapshots                            # noqa: E402
from onecrew.v2 import engine, engine_cli, findings, plan, repair_tasks, review_advice, review_dispatch, tracking_work, verdict  # noqa: E402
from onecrew.v2 import plan as plans                               # noqa: E402
from onecrew.v2.verifiers import command, port, reviewer           # noqa: E402
from test_v2_l2 import HookFixture, owned_plan                     # noqa: E402
from tests import test_review_a2_findings as a2                    # noqa: E402
from tests import test_review_b2_candidate as b2c                  # noqa: E402
from tests import test_review_b2_e2e as b2e                        # noqa: E402
from tests import test_review_b2_investigation as b2i              # noqa: E402
from tests import test_review_b2_lifecycle as b2l                  # noqa: E402
from tests import test_review_rda2_dispatch as rda                 # noqa: E402
from tests import test_v24_c_execution_mode as mode                # noqa: E402
from tests import test_v24_c_review as tools                       # noqa: E402
from tests import test_wf_candidate_handoff as handoff_fixture     # noqa: E402
from tests import test_wf_candidate_reviewer as reviewer_fixture   # noqa: E402
from tests.test_review_rda2_lifecycle import KEY, Crash, Provider  # noqa: E402
from tests.test_v2_l1 import milestone, plan_json                  # noqa: E402
from tests.test_v2_reviewer import answer, reviewer_milestone, row  # noqa: E402
from tests.test_wf_engine import node                              # noqa: E402


class RoomyCaps:
    """These tests are about who dispatches, not about time caps: a 60 s node cap can run out on a loaded machine and fail them for another reason."""
    def revise(self, nodes, reason='Split work inside the approved scope'):
        for item in nodes: item['execution_cap_seconds'] = 900
        return super().revise(nodes, reason)


class Claims(RoomyCaps, b2c.CandidateClaims):
    for _inherited in [n for n in dir(b2c.CandidateClaims) if n.startswith('test')]:
        locals()[_inherited] = None
    del _inherited


# ---- P1-1 (R01): the candidate door must not replay a verdict run of unknown outcome ---------------------------------------------------

class R01VerdictUnknown(Claims):
    def lost_verdict_run(self):
        (self.root / 'guide.md').write_bytes(self.overlays['guide.md'])
        self.git('add', 'guide.md'); self.git('commit', '-qm', 'final doc')
        self.step()
        tree = self.tree_of()
        request = review_dispatch.milestone_request(self.ledger, 'P1', 'Doc', tree)
        run_id = verdict._begin_run(self.ledger, 'P1', 1, 'Doc', 'doc', 5, check=(request, tree))
        verdict._mark(self.ledger, run_id, 'dispatched', {'plan': 'P1', 'revision': 1, 'milestone': 'Doc', 'kind': 'doc', 'at': 'x'})
        with self.ledger.transaction(write=True) as conn:              # process lost: what a real crash leaves
            conn.execute("UPDATE events SET payload=json_set(payload,'$.pid',999999) WHERE kind='verdict.run_started'")
        return run_id

    def test_a_held_verdict_run_is_held_at_the_candidate_door_and_released_only_by_its_own_verb(self):
        run_id = self.lost_verdict_run()
        verdict.reap(self.ledger, 'P1')
        with self.assertRaisesRegex(LedgerError, 'unknown'):
            verdict.reconcile(self.ledger, 'P1', 1, 'Doc')
        calls = []
        with patch.object(port, 'run', side_effect=b2c.counting(calls, port.run)):
            out = self.verify('C', self.checker())
            self.assertNotIn('Doc', calls, 'unknown outcome of Doc on this tree was replayed through another door')
            self.assertEqual(out['status'], 'held')
            self.assertEqual(out['check_run']['run_id'], run_id)
            self.assertIn('verdict release-run', out['next'])
            verdict.release_run(self.ledger, 'P1', run_id, 'Checked: the document adapter wrote nothing.')
            done = self.verify('C', self.checker())
        self.assertEqual(done['result'], 'pass')
        self.assertIn('Doc', calls)

    def test_a_lost_verdict_run_is_held_even_before_any_reader_reconciled_it(self):
        self.lost_verdict_run()
        calls = []
        with patch.object(port, 'run', side_effect=b2c.counting(calls, port.run)):
            out = self.verify('C', self.checker())
        self.assertEqual((out['status'], calls), ('held', []))

    def test_a_verdict_receipt_issued_but_not_recorded_is_not_run_again(self):
        (self.root / 'guide.md').write_bytes(self.overlays['guide.md'])
        self.git('add', 'guide.md'); self.git('commit', '-qm', 'final doc')
        with patch.object(verdict, 'record', side_effect=RuntimeError('lost before the verdict was recorded')):
            with self.assertRaises(RuntimeError):
                verdict.run(self.ledger, 'P1', 'Doc')
        self.step()
        calls = []
        with patch.object(port, 'run', side_effect=b2c.counting(calls, port.run)):
            out = self.verify('C', self.checker())
        self.assertEqual((out['status'], calls), ('pending', []))
        self.assertIn('verdict', out['reason'])


class ReviewerRoot(reviewer_fixture.CandidateReviewerFixture):
    def counted_call(self, calls):
        def fake(prompt, config, env, scratch, limit):
            calls.append(config['model'])
            return answer(row('R1')), {}, None, False, b'fixture'
        return fake


class R01ReviewerVariant(RoomyCaps, ReviewerRoot):
    def test_a_lost_verdict_reviewer_call_gets_no_second_model_call_at_the_candidate_door(self):
        (self.root / 'a.txt').write_bytes(b'candidate\n')
        self.git('add', 'a.txt'); self.git('commit', '-qm', 'final')
        self.produce()
        verdict.run(self.ledger, 'P1', 'M1')
        def lost(prompt, config, env, scratch, limit): raise OSError('connection lost after the prompt was sent')
        with patch.object(reviewer, 'call', side_effect=lost):
            with self.assertRaises(OSError):
                verdict.run(self.ledger, 'P1', 'M2')
        with self.assertRaisesRegex(LedgerError, 'unknown'):
            verdict.reconcile(self.ledger, 'P1', 1, 'M2')
        charged = self.counters()['used_calls']
        calls = []
        with patch.object(reviewer, 'call', side_effect=self.counted_call(calls)):
            out = self.engine.verify(self.ledger, 'P1', 'C', self.production_checker)
        self.assertEqual(calls, [], 'the Control signature differs per door, so only the claim can stop a second model call')
        self.assertEqual(out['status'], 'held')
        self.assertEqual(self.counters()['used_calls'], charged)


# ---- P1-2 (R10): a lost advice call never blocks a task; two lost reviewer calls hold capacity until a recorded release -----------------------

class R10AdviceBlocks(rda.DispatchWiring):
    for _inherited in [n for n in dir(rda.DispatchWiring) if n.startswith('test')]:
        locals()[_inherited] = None
    del _inherited

    def crash(self, index):
        with self.assertRaises(Crash):
            review_advice.advise(self.ledger, 'P1', stage='review', node='C', review_id='extra', brief='b', facts={'i': index}, mandatory=False,
                                 key=KEY, opener=Provider('crash'))

    def test_two_lost_advice_calls_leave_the_next_worker_step_free_and_stay_charged(self):
        self.verify('C')
        before = self.used()
        self.crash(0); self.crash(1)
        self.assertGreaterEqual(self.used(), before)
        charged = self.used()
        again = review_advice.advise(self.ledger, 'P1', stage='review', node='C', review_id='extra', brief='b', facts={'i': 0}, mandatory=False,
                                     key=KEY, opener=Provider(), refresh=True)
        self.assertEqual(again['status'], 'unknown', 'an unknown outcome is never replayed, a refresh included')
        out = self.step()
        self.assertEqual(out.get('state'), 'produced', 'lost advice calls hold the real next step')
        self.assertGreaterEqual(self.used(), charged)                  # the charge stays

    def test_an_advice_controller_killed_with_no_handler_blocks_nothing_either(self):
        self.verify('C')
        for index in range(2):
            with patch('onecrew.control_core.Control.unknown'), patch('onecrew.v2.review_advice._record', side_effect=OSError('killed')):
                with self.assertRaises(Crash):
                    review_advice.advise(self.ledger, 'P1', stage='review', node='C', review_id='extra', brief='b', facts={'k': index}, mandatory=False,
                                         key=KEY, opener=Provider('crash'))
        with self.ledger.transaction() as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM attempts WHERE status!='settled'").fetchone()[0], 2)
        self.assertEqual(self.step().get('state'), 'produced')


class R10TwoLostReviewers(RoomyCaps, handoff_fixture.CandidateFixture):
    """What two lost REVIEWER calls do to an independent branch: a required limit. The effect is unknown, so nothing is released by itself; the
    message names the recovery verb, and the recorded release frees the branch with the charge kept."""
    def milestones(self):
        return [dict(reviewer_milestone(criteria=reviewer_fixture.CRITERIA), id='M2')]

    def setUp(self):
        def scoped(**kw):
            return plan_json(scope={'owned': ['a.txt', 'b.txt', 'x.txt']}, items=[{'id': 'I1', 'title': 'Reviewed', 'tier': 'must', 'milestone': 'M2'}], **kw)
        with patch.object(handoff_fixture, 'plan_json', side_effect=scoped):
            super().setUp()
        def worker(nid, path, checks):
            item = node(nid, write=(path,)); item['read'] = [path]
            item['checks'] = [{'id': c, 'spec': 'The approved reviewer'} for c in checks]
            item['executor'] = {'role': 'worker', 'provider': 'codex', 'model': 'gpt-6.1-sol'}
            return item
        final = node('I', ['C', 'D', 'X'], integration=True, write=()); final['read'] = ['a.txt', 'b.txt', 'x.txt']
        final['checks'] = [{'id': 'M2', 'spec': 'The approved reviewer'}]
        (self.root / 'b.txt').write_text('two\n'); (self.root / 'x.txt').write_text('three\n')
        self.git('add', 'b.txt', 'x.txt'); self.git('commit', '-qm', 'files')
        self.revise([worker('C', 'a.txt', ['M2']), worker('D', 'b.txt', ['M2']), worker('X', 'x.txt', ['M2']), final])

    def execute(self, ledger, control, task, item, attempt):
        from onecrew.ledger import canonical
        control.launched(attempt['id'], attempt['generation'], {'fixture': True})
        paths = list(item['write'])
        artifact = self.store.overlay(self.store.capture(self.root, paths), {p: b'candidate\n' for p in paths}, paths)
        receipt = self.store.blob(canonical({'kind': 'fixture-producer', 'artifact': artifact}).encode())
        control.finish(attempt['id'], attempt['generation'], {'artifact': artifact})
        return {'artifact': artifact, 'receipt': receipt}

    def test_two_lost_reviewer_calls_hold_the_independent_branch_and_the_message_names_the_release(self):
        def lost(prompt, config, env, scratch, limit): raise OSError('connection lost after the prompt was sent')
        held = []
        with patch.object(reviewer, 'call', side_effect=lost):
            for nid in ('C', 'D'):
                self.assertEqual(self.step()['node'], nid)
                with self.assertRaises(OSError):
                    self.engine.verify(self.ledger, 'P1', nid, CandidateChecker(self.ledger, 'P1'))
                held.append(self.engine.verify(self.ledger, 'P1', nid, CandidateChecker(self.ledger, 'P1'))['check_run']['run_id'])
        with self.assertRaises(CapacityWait) as raised:
            self.step()
        for words in ('release-check', 'check-runs', 'unknown'):
            self.assertIn(words, str(raised.exception))
        self.assertEqual(self.engine.state(self.ledger, 'P1')['nodes']['X']['state'], None)
        with self.ledger.transaction() as conn:
            used = budget_core.group(conn, plan.anchor_events(self.ledger, conn, 'P1')['task_id'])['used_calls']
        for run_id in held:
            review_dispatch.release_check(self.ledger, 'P1', run_id, 'Checked the provider log: no answer arrived.')
        self.assertEqual(self.step()['node'], 'X')
        with self.ledger.transaction() as conn:
            self.assertGreaterEqual(budget_core.group(conn, plan.anchor_events(self.ledger, conn, 'P1')['task_id'])['used_calls'], used)


# ---- P1-3 (R02): a later fail of the exact request stops reuse --------------------------------------------------------------------------

class R02OldPass(RoomyCaps, handoff_fixture.CandidateFixture):
    def milestones(self):
        self.flag = Path(tempfile.mkdtemp()) / 'break-it'
        check = [sys.executable, '-c', 'import os,sys; from pathlib import Path; assert Path("a.txt").read_text()=="candidate\\n"; print("candidate tested"); '
                                       'sys.exit(1 if os.path.exists(r"%s") else 0)' % self.flag]
        return [milestone(argv=check)]

    def test_an_old_pass_is_not_reused_after_a_later_fail_of_the_same_request(self):
        (self.root / 'a.txt').write_bytes(b'candidate\n')
        self.git('add', 'a.txt'); self.git('commit', '-qm', 'final')
        self.revise(self.definition())
        self.step()
        real, calls = command.run, []
        def counted(*a, **k):
            calls.append('run'); return real(*a, **k)
        with patch.object(command, 'run', side_effect=counted):
            first = self.verify('C', CandidateChecker(self.ledger, 'P1'))
            self.assertEqual(first['result'], 'pass')
            self.flag.write_text('x')
            verdict.run(self.ledger, 'P1', self.check_ids[0])
            self.step()
            before = len(calls)
            second = self.verify('I', CandidateChecker(self.ledger, 'P1'))
        self.assertEqual(second['observed']['candidate_tree'], first['observed']['candidate_tree'])
        self.assertGreater(len(calls) - before, 0, 'a PASS older than a FAIL of the same request was reused with no execution')
        self.assertNotEqual(second['result'], 'pass')


# ---- P2-4 (R08): probes cannot be held to the promise on this path, so they are refused ----------------------------------------------------

class R08Probes(b2i.InvestigationFixture):
    def test_a_probe_reads_and_writes_nothing_outside(self):
        outside = Path(tempfile.mkdtemp())
        scoped_out = self.root / 'b_outside_scope.txt'
        scoped_out.write_text('PROJECT-FILE-OUTSIDE-NODE-SCOPE\n', encoding='utf-8')
        (outside / 'other.txt').write_text('CONTENT-OUTSIDE-THE-PROJECT\n', encoding='utf-8')
        marker, project_marker = outside / 'written-by-probe.txt', self.root / 'written-by-probe.txt'
        code = ('from pathlib import Path\n'
                f'print(Path(r"{scoped_out}").read_text()); print(Path(r"{outside / "other.txt"}").read_text())\n'
                f'Path(r"{marker}").write_text("x"); Path(r"{project_marker}").write_text("x")\n')
        try:
            self.investigate(probes=[[sys.executable, '-c', code]], paths=['a.txt'])
        except LedgerError as error:
            self.assertIn('probes', str(error))
        self.assertFalse(marker.exists() or project_marker.exists(), 'a probe wrote outside the disposable checkout')
        self.assertFalse(any('PROJECT-FILE-OUTSIDE-NODE-SCOPE' in p or 'CONTENT-OUTSIDE-THE-PROJECT' in p for p in self.prompts))

    def test_a_secret_in_argv_or_in_the_question_reaches_neither_the_receipt_nor_the_prompt(self):
        token = 'ghp_' + 'A1b2C3d4' * 5
        for config in ({'probes': [[sys.executable, '-c', 'print(1)', '--token=' + token]]}, {'question': 'Is the token ' + token + ' used?'}):
            try:
                result = self.investigate(paths=['a.txt'], **config)
            except LedgerError:
                result = {}
            self.assertFalse(any(token in p for p in self.prompts))
            if result.get('receipt'):
                self.assertNotIn(token, Snapshots(self.ledger.state_root).read_blob(result['receipt']).decode())

    def test_a_project_changed_during_the_investigation_is_not_reported_observed(self):
        def editing(prompt, config, env, scratch, limit):
            (self.root / 'a.txt').write_text('edited while the investigation ran\n')
            return b2i.ANSWER, {}, None, False, b'fixture'
        with self.assertRaisesRegex(LedgerError, 'changed'):
            self.investigate(call=editing)
        self.assertNotIn('review.observed', self.kinds())
        held = [p for k, p in self.events() if k == 'review.run_held']
        self.assertEqual(len(held), 1)
        self.assertIn('changed', held[0]['reason'])


# ---- P2-5 (R11): the optional door from another shell ------------------------------------------------------------------------------------

class R11OptionalEnv(b2i.InvestigationFixture):
    def test_held_work_is_held_from_another_shell_and_another_question_is_other_work(self):
        calls = []
        def lost(prompt, config, env, scratch, limit):
            calls.append(1); raise OSError('connection lost after the prompt was sent')
        with self.assertRaises(OSError):
            self.investigate(call=lost)
        self.assertEqual(self.investigate(call=lost)['status'], 'held')
        base = command.verifier_env(self.ledger.project)
        with patch.object(command, 'verifier_env', side_effect=lambda *a, **k: dict(base, TEMP='D:/another-shell')):
            other = self.investigate(call=lost)
        self.assertEqual(other['status'], 'held')
        self.assertIn('release-check', other['next'])
        self.assertEqual(len(calls), 1)
        self.assertEqual(self.kinds().count('review.run_started'), 1, 'another shell started the same work again')
        self.assertEqual(self.investigate(question='Another question?')['status'], 'observed')


# ---- P2-6 (R03): a lost or damaged issued receipt ----------------------------------------------------------------------------------------

def damage(ledger, key):
    files = list(Path(ledger.state_root).glob('**/' + key))
    assert files, key
    for found in files: found.write_bytes(b'corrupted by a disk restore')


class R03IssuedLost(b2l.CheckFixture):
    def test_a_recorded_way_out_never_a_pass_and_no_blind_rerun(self):
        self.step()
        real = engine._event
        def crash(ledger, conn, view, nid, kind, **payload):
            if kind == 'node.verification': raise RuntimeError('process lost before publication')
            return real(ledger, conn, view, nid, kind, **payload)
        with patch.object(engine, '_event', side_effect=crash):
            with self.assertRaises(RuntimeError): self.verify('C')
        [run] = [p for k, p in self.events() if k == 'review.run_result']
        damage(self.ledger, run['receipt'])
        held = self.verify('C', lambda *a: self.fail('no blind rerun'))
        self.assertEqual(held['status'], 'held')
        self.assertIn('release-check', held['next'])
        self.assertEqual(review_dispatch.reconcile_check(self.ledger, 'P1', run['run_id'])['status'], 'held')
        self.assertNotIn('node.verification', self.kinds())
        released = review_dispatch.release_check(self.ledger, 'P1', run['run_id'], 'The blob is damaged; check it again.')
        self.assertFalse(released['budget_reset'])
        finished = [p for k, p in self.events() if k == 'review.run_finished'][-1]
        self.assertEqual((finished['outcome'], finished['applicable']), ('receipt_lost', False))
        self.assertEqual(self.engine.state(self.ledger, 'P1')['nodes']['C']['state'], 'produced')
        calls = []
        def counting(item, artifact): calls.append(artifact); return self.checker(item, artifact)
        self.assertEqual(self.verify('C', counting)['result'], 'pass')
        self.assertEqual(len(calls), 1)

    def test_a_readable_issued_receipt_is_settled_not_released(self):
        self.step()
        real = engine._event
        def crash(ledger, conn, view, nid, kind, **payload):
            if kind == 'node.verification': raise RuntimeError('process lost')
            return real(ledger, conn, view, nid, kind, **payload)
        with patch.object(engine, '_event', side_effect=crash):
            with self.assertRaises(RuntimeError): self.verify('C')
        [run] = [p for k, p in self.events() if k == 'review.run_result']
        with self.assertRaisesRegex(LedgerError, 'reconcile-check'):
            review_dispatch.release_check(self.ledger, 'P1', run['run_id'], 'try')

    def execution(self):
        return {'method': 'adapter', 'implementation': 'fixture-v1', 'configuration': {}, 'environment': {'fixture': 'local'}, 'provenance': {'adapter': 'cycle2'}}

    def optional(self, checker):
        artifact = self.engine.state(self.ledger, 'P1')['nodes']['C']['artifact']
        return review_dispatch.optional(self.ledger, 'P1', 'C', 'extra', checker, artifact, execution=self.execution())

    def test_the_optional_door_has_the_same_way_out(self):
        self.step()
        ok = lambda item, artifact: {'result': 'pass', 'artifact': artifact}
        with patch.object(review_dispatch, '_publish_optional', side_effect=RuntimeError('publication interrupted')):
            with self.assertRaises(RuntimeError): self.optional(ok)
        [issued] = [p for k, p in self.events() if k == 'review.run_result']
        damage(self.ledger, issued['receipt'])
        held = self.optional(lambda *a: self.fail('no blind rerun'))
        self.assertEqual(held['status'], 'held')
        self.assertIn('release-check', held['next'])
        review_dispatch.release_check(self.ledger, 'P1', issued['run_id'], 'The blob is damaged; ask again.')
        self.assertEqual(self.optional(ok)['status'], 'observed')

    def test_a_finished_optional_receipt_damaged_later_can_be_retired(self):
        self.step()
        ok = lambda item, artifact: {'result': 'pass', 'artifact': artifact}
        first = self.optional(ok)
        damage(self.ledger, first['receipt'])
        with self.assertRaisesRegex(LedgerError, 'release-check'):
            self.optional(lambda *a: self.fail('no blind rerun'))
        review_dispatch.release_check(self.ledger, 'P1', first['run_id'], 'The blob is damaged; ask again.')
        again = self.optional(ok)
        self.assertEqual(again['status'], 'observed')
        self.assertNotEqual(again['run_id'], first['run_id'])


# ---- P2-7 (R13): one closure rule, and the doors that reach it ---------------------------------------------------------------------------

class R13Closure(a2.NodeRecheck):
    for _inherited in [n for n in dir(a2.NodeRecheck) if n.startswith('test')]:
        locals()[_inherited] = None
    del _inherited

    def moved_on(self):
        receipt = self.repair_and_pass()
        nodes = json.loads(json.dumps(engine.state(self.ledger, 'P1')['definition']['nodes']))
        for item in nodes:
            if item['id'] == 'I': item['goal'] = 'Changed after the pass'
        self.revise(nodes)
        self.step()
        return receipt

    def test_a_pass_of_an_older_generation_does_not_close_through_the_public_door(self):
        receipt = self.moved_on()
        loose = findings.resolve(self.ledger, 'P1', self.finding['id'], receipt, reason='the AI says it is fixed', artifact_sha='f' * 40, generation=99)
        self.assertEqual(loose['closed'], [], 'a pass of an older generation closed the finding through the public door')
        honest = findings.resolve(self.ledger, 'P1', self.finding['id'], receipt, reason='old pass with its own artifact',
                                  artifact_sha=json.loads(self.store.read_blob(receipt))['artifact'])
        self.assertEqual(honest['closed'], [])
        self.assertIn('newer', honest['refused'][0])

    def test_resolve_closes_on_the_current_repaired_output_without_a_caller_generation(self):
        receipt = self.repair_and_pass()
        artifact = json.loads(self.store.read_blob(receipt))['artifact']
        self.assertEqual(findings.resolve(self.ledger, 'P1', self.finding['id'], receipt, reason='rechecked', artifact_sha=artifact)['closed'], [self.finding['id']])

    def test_the_same_candidate_cannot_be_called_repaired_but_a_rejection_stays_legal(self):
        receipt = self.repair_and_pass()
        [row_] = findings.list_findings(self.ledger, 'P1', open_only=True)
        artifact = json.loads(self.store.read_blob(receipt))['artifact']
        register = findings._read
        def failed_on_this_candidate(ledger, conn, task):
            value = register(ledger, conn, task)
            for item in value['findings']:
                if item['id'] == row_['id']: item['artifact_sha'] = item['candidate'] = artifact
            return value
        with patch.object(findings, '_read', side_effect=failed_on_this_candidate):
            same = findings.resolve(self.ledger, 'P1', self.finding['id'], receipt, reason='nothing changed', artifact_sha=artifact)
            self.assertEqual(same['closed'], [])
            self.assertIn('same candidate', same['refused'][0])
            rejected = findings.resolve(self.ledger, 'P1', self.finding['id'], receipt, reason='not a defect: decided by the owner', artifact_sha=artifact, reject=True)
        self.assertEqual(rejected['closed'], [self.finding['id']])
        self.assertEqual(findings.list_findings(self.ledger, 'P1')[0]['status'], 'rejected')

    def cli(self, *argv):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = findings.main(['--project', str(self.root), '--state-root', str(self.ledger.state_root), *argv])
        return code, json.loads(out.getvalue())

    def test_the_recheck_closure_has_a_production_door(self):
        receipt = self.repair_and_pass()
        code, shown = self.cli('recheck', 'P1', self.finding['id'], '--receipt', self.red_receipt)
        self.assertEqual((code, shown['closed']), (2, []))
        code, shown = self.cli('recheck', 'P1', self.finding['id'], '--receipt', receipt)
        self.assertEqual((code, shown['closed']), (0, [self.finding['id']]))


class R13RerunReachable(RoomyCaps, b2e.LoopFixture):
    """`engine rerun-order`: a production caller of the evidence-based rerun, its evidence read from the ledger, with the production port."""
    paths = ('a.txt', 'b.txt')
    bad = {'a.txt': b'wrong\n', 'b.txt': b'b ok\n'}
    good = {'a.txt': b'candidate\n'}
    milestones = (milestone('CheckC', argv=[sys.executable, '-c', 'from pathlib import Path; assert Path("a.txt").exists(); print("a exists")']),
                  milestone('CheckX', argv=[sys.executable, '-c', 'from pathlib import Path; assert Path("b.txt").read_text()=="b ok\\n"; print("b ok")']),
                  milestone('Final', argv=[sys.executable, '-c', 'from pathlib import Path; assert Path("a.txt").read_text()=="candidate\\n"; print("final ok")']))

    def prepare(self):
        (self.root / 'b.txt').write_text('two\n', encoding='utf-8')

    def nodes(self):
        def scoped(nid, path, check):
            item = node(nid, write=(path,)); item['read'] = [path]
            item['checks'] = [{'id': check, 'spec': 'Run the approved ' + check}]
            return item
        final = node('I', ['C', 'X'], integration=True, write=()); final['read'] = list(self.paths)
        final['checks'] = [{'id': m['id'], 'spec': 'Run the approved ' + m['id']} for m in self.milestones]
        return [scoped('C', 'a.txt', 'CheckC'), scoped('X', 'b.txt', 'CheckX'), final]

    execute = b2e.IndependentBranchCase.execute

    def test_the_cli_orders_only_what_the_repair_changed(self):
        checker = CandidateChecker(self.ledger, 'P1')
        for nid in ('C', 'X'):
            self.assertEqual(self.step()['node'], nid)
            self.assertEqual(self.verify(nid, checker)['result'], 'pass')
        self.assertEqual(self.step()['node'], 'I')
        self.assertEqual(self.verify('I', checker)['result'], 'fail')
        [finding] = findings.list_findings(self.ledger, 'P1', open_only=True)
        failed = engine.state(self.ledger, 'P1')['nodes']['I']['verification_receipt']
        repair_tasks.prepare(self.ledger, 'P1', 'C', 'I', reason='a.txt must be the candidate', evidence=[failed])
        self.overlays.update(self.good)
        self.assertEqual(self.step()['node'], 'C')
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = engine_cli.main(['--project', str(self.root), '--state-root', str(self.ledger.state_root), 'engine', 'rerun-order', 'P1', finding['id']])
        self.assertEqual(code, 0, out.getvalue())
        order = json.loads(out.getvalue())
        self.assertEqual(order['evidence_status'].get('X'), 'applies', order)     # X kept its output: its pass still stands
        self.assertEqual(order['ordered'][0], 'Final')
        self.assertIn('CheckC', order['ordered'])                                 # the repaired node has no pass yet
        self.assertEqual([r['node'] for r in order['reusable']], ['X'])


# ---- P3-8 (R04), P3-13 (R14): the tools door --------------------------------------------------------------------------------------------

class ToolsDoor(mode.ModeFixture):
    def test_r04_an_independent_produced_node_is_checked_while_another_is_pending_elsewhere(self):
        self.revise([mode.worker('A', ['a.txt']), mode.worker('B', ['b.txt']), mode.integration(['A', 'B'])])
        engine.run_batch(self.ledger, 'P1', self.isolated(), slots=2)
        view = engine.state(self.ledger, 'P1')
        claim, _ = review_dispatch.claim_node_check(self.ledger, 'P1', 'A', execution=None, door='engine.verify',
                                                    expected=(view['nodes']['A']['artifact'], view['nodes']['A']['generation']))
        self.assertEqual(claim['status'], 'claimed')
        for _ in range(4):
            engine.step(self.ledger, 'P1', self.isolated(), control=self.control, checker=tools.Free(self))
        self.assertEqual(engine.state(self.ledger, 'P1')['nodes']['B']['state'], 'verified', 'independent B was never checked while A is pending elsewhere')

    def test_r14_a_hold_is_explained_at_every_step_and_a_release_lets_the_check_run_again(self):
        class Broken(tools.Free):
            def __call__(self, item, artifact):
                self.calls.append(item['id']); raise OSError('checker host gone')
        self.revise([mode.worker('A', ['a.txt']), mode.integration(['A'])])
        self.step()
        port_ = Broken(self)
        answers = [engine.step(self.ledger, 'P1', self.isolated(), control=self.control, checker=port_) for _ in range(4)]
        self.assertEqual(port_.calls.count('A'), 1)
        for answer_ in answers:
            self.assertEqual(answer_['state'], 'waiting')
            self.assertIn('release-check', answer_.get('next', ''), answer_)
        run_id = answers[-1]['check_run']['run_id']
        self.assertIn(run_id, answers[-1]['next'])
        review_dispatch.release_check(self.ledger, 'P1', run_id, 'Checked: nothing happened.')
        good = tools.Free(self)
        out = engine.step(self.ledger, 'P1', self.isolated(), control=self.control, checker=good)
        self.assertEqual(good.calls, ['A'], out)
        self.assertEqual(engine.state(self.ledger, 'P1')['nodes']['A']['state'], 'verified')


# ---- P3-9 (R05): a dead row from another host ---------------------------------------------------------------------------------------------

class R05HookLetGo(HookFixture):
    def test_a_row_with_no_deadline_from_another_host_does_not_disable_stop(self):
        self.enforce(value=owned_plan(milestones=[milestone('M1')]))
        anchor = plans.show(self.ledger, 'P1')['anchor_task']
        with self.ledger.transaction(write=True) as conn:
            plans.emit(self.ledger, conn, anchor, 'review.run_started', {'run_id': 'dead-optional-run', 'root': anchor, 'revision': 1, 'node': 'N', 'review_id': 'extra',
                       'artifact': 'x', 'request': {'id': 'review-x', 'identity': {}, 'missing': [], 'execution_complete': False}, 'facts': {}, 'decision_key': 'k', 'context_request': {},
                       'pid': 4242, 'host': 'another-machine', 'grants_authority': False})
        self.assertEqual(review_dispatch.active_checks(self.ledger, 'P1'), [])
        _, out, _ = self.run_hook('stop', {'session_id': 's1', 'cwd': str(self.root), 'hook_event_name': 'Stop', 'stop_hook_active': False})
        self.assertTrue(out.strip(), 'the enforce reminder is gone for good: this row has no deadline')


class R05OptionalDeadline(b2l.CheckFixture):
    def test_a_new_optional_row_carries_a_deadline(self):
        self.step()
        artifact = self.engine.state(self.ledger, 'P1')['nodes']['C']['artifact']
        review_dispatch.optional(self.ledger, 'P1', 'C', 'extra', lambda item, value: {'artifact': value}, artifact)
        [started] = [p for k, p in self.events() if k == 'review.run_started']
        self.assertTrue(started['deadline'])


# ---- P3-10 (R06): one status for one held run ------------------------------------------------------------------------------------------------

class R06TraceStatus(Claims):
    def test_a_held_verdict_run_reads_held_everywhere_and_released_after_the_release(self):
        self.step()
        tree = self.tree_of()
        request = review_dispatch.milestone_request(self.ledger, 'P1', 'Doc', tree)
        run_id = verdict._begin_run(self.ledger, 'P1', 1, 'Doc', 'doc', 5, check=(request, tree))
        verdict._mark(self.ledger, run_id, 'dispatched', {'plan': 'P1', 'revision': 1, 'milestone': 'Doc', 'kind': 'doc', 'at': 'x'})
        with self.ledger.transaction(write=True) as conn:
            conn.execute("UPDATE events SET payload=json_set(payload,'$.pid',999999) WHERE kind='verdict.run_started'")
        verdict.reap(self.ledger, 'P1')
        with self.assertRaises(LedgerError): verdict.reconcile(self.ledger, 'P1', 1, 'Doc')
        status = lambda: {r['run_id']: r['status'] for r in tracking_work.review_trace(self.ledger, 'P1')['runs']}[run_id]
        state = lambda: {r['run_id']: r for r in review_dispatch.check_runs(self.ledger, 'P1')}[run_id]['state']
        self.assertEqual(status(), 'held', 'a held run of unknown outcome is projected as started')
        self.assertEqual(state(), 'held')
        verdict.release_run(self.ledger, 'P1', run_id, 'Checked it.')
        self.assertEqual((status(), state()), ('released', 'finished'))


# ---- P3-11 (R07): descriptors bound to the node and its current facts ---------------------------------------------------------------------------

class R07RerunForged(a2.RerunByImpact):
    for _inherited in [n for n in dir(a2.RerunByImpact) if n.startswith('test')]:
        locals()[_inherited] = None
    del _inherited

    def test_an_old_or_foreign_descriptor_cannot_drop_the_repaired_node(self):
        before = self.request('N1')
        self.repair_and_pass()
        honest = repair_tasks.rerun_order(self.ledger, 'P1', self.finding['id'], evidence={'N1': self.evidence('N1', before)})
        self.assertEqual(honest['evidence_status']['N1'], 'recheck')
        forged = repair_tasks.rerun_order(self.ledger, 'P1', self.finding['id'], evidence={'N1': {'previous': before, 'current': before}})
        self.assertIn('check-N1', forged['ordered'], 'an old snapshot descriptor passed as current makes the repaired node reusable')
        self.assertEqual(forged['reusable'], [])
        other = self.request('N2')
        cross = repair_tasks.rerun_order(self.ledger, 'P1', self.finding['id'], evidence={'N1': {'previous': other, 'current': other}})
        self.assertIn('check-N1', cross['ordered'])
        self.assertEqual(cross['reusable'], [])


# ---- P3-12 (R09): the advice record, facts and the last call -----------------------------------------------------------------------------------

class R09Advice(rda.DispatchWiring):
    for _inherited in [n for n in dir(rda.DispatchWiring) if n.startswith('test')]:
        locals()[_inherited] = None
    del _inherited

    def facts(self):
        return review_dispatch._context(self.ledger, 'P1', 'C')[3]

    def test_a_bad_key_charges_nothing_and_the_record_says_so(self):
        provider = Provider()
        with patch.dict(os.environ, {'TYPESAFE_API_KEY': 'x'}):
            before = self.used()
            out = review_advice.advise_optional(self.ledger, 'P1', 'C', 'extra', facts=self.facts(), opener=provider)
        self.assertEqual(out['charged_calls'], self.used() - before, 'the record says what the budget did')
        self.assertEqual((provider.calls, out['reason']), (0, 'not_configured'))

    def test_a_key_refused_only_after_admission_is_recorded_as_charged(self):
        before = self.used()
        with patch.object(client, 'load_key', side_effect=client.JevError('stored key unusable')), patch.object(client, 'configured', return_value=True):
            out = review_advice.advise_optional(self.ledger, 'P1', 'C', 'extra', facts=self.facts(), opener=Provider())
        self.assertEqual(out['charged_calls'], self.used() - before)

    def test_facts_of_no_real_node_or_not_its_current_facts_are_not_charged(self):
        provider, before = Provider(), self.used()
        for index in range(3):
            out = review_advice.advise_optional(self.ledger, 'P1', 'NOT-A-NODE', 'extra', facts={'made_up': index}, key=KEY, opener=provider)
            self.assertNotEqual(out['status'], 'proposal')
            out = review_advice.advise_optional(self.ledger, 'P1', 'C', 'extra', facts={'made_up': index}, key=KEY, opener=provider)
            self.assertNotEqual(out['status'], 'proposal')
        self.assertEqual((provider.calls, self.used() - before), (0, 0), 'facts of no real node, charged to the root budget')
        self.assertEqual(review_advice.advise_optional(self.ledger, 'P1', 'C', 'extra', facts=self.facts(), key=KEY, opener=provider)['status'], 'proposal')

    def test_with_two_calls_left_concurrent_advice_keeps_the_last_call(self):
        entered, release = threading.Event(), threading.Event()
        class HoldsTheFirst(Provider):
            def open(inner, request, timeout):
                if inner.calls == 0:
                    inner.calls += 1
                    inner.bodies.append(json.loads(request.data))
                    entered.set()
                    release.wait(30)
                    inner.calls -= 1; inner.bodies.pop()
                return Provider.open(inner, request, timeout)
        real_budget, provider = review_advice._budget, HoldsTheFirst()
        def two_left(conn, state):
            return real_budget(conn, state)[0], 2
        def ask(index):
            return review_advice.advise(self.ledger, 'P1', stage='review', node='C', review_id='extra', brief='b', facts={'i': index}, mandatory=False, key=KEY, opener=provider)
        with patch.object(review_advice, '_budget', side_effect=two_left), concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            first = pool.submit(ask, 0)
            self.assertTrue(entered.wait(30))
            try:
                second = ask(1)
            finally:
                release.set()
            done = first.result(timeout=60)
        self.assertEqual(done['status'], 'proposal')
        self.assertEqual((second['status'], second['reason']), ('skipped', 'no_call_budget'), 'with 2 left, advice must leave 1: both took one')
        self.assertEqual(provider.calls, 1)
