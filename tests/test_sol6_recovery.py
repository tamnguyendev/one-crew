"""Sol6: every state after a red check leads to a door that works, or to a stop that says why. Temporary fixture ledgers only; no provider, no real acceptance."""
import datetime as dt
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))

from onecrew.common_handoff import handoff                                    # noqa: E402
from onecrew.common_verification import CandidateChecker                      # noqa: E402
from onecrew.ledger import LedgerError, canonical                             # noqa: E402
from onecrew.v2 import (active_plan, engine, findings, internal_plan, plan, questions, recovery_policy,  # noqa: E402
                        repair_tasks, report, tracking, verdict, verification_evidence)
from onecrew.v2.verifiers import command                                      # noqa: E402
from tests import test_review_b2_e2e as loop                                  # noqa: E402
from tests.test_review_b2_e2e import LoopFixture                              # noqa: E402
from tests.test_v2_l1 import Fixture, milestone, plan_json                    # noqa: E402
from tests.test_wf_engine import node                                         # noqa: E402
from tests import wf_oldversion as ov                                         # noqa: E402

GOOD, BAD, BROKEN = b'good2\n', b'candidate\n', b'broken\n'
REPO = str(Path(__file__).resolve().parents[1])


def gate(path='a.txt', good='good2\n'):
    """Fails on `broken` everywhere; with CI=red (standing for the delivered tree) fails on anything but `good`."""
    return [sys.executable, '-c', f'import os,pathlib;t=pathlib.Path({path!r}).read_text();print(repr(t));'
            f'raise SystemExit(3 if (t=="broken\\n" or (os.environ.get("CI")=="red" and t!={good!r})) else 0)']


class Chain(LoopFixture):
    paths = ('a.txt',)
    bad = {'a.txt': BAD}
    good = {'a.txt': GOOD}
    milestones = (milestone('M1', argv=gate(), mode='until_pass', max_repairs=5),)

    def prepare(self): pass

    def through_nodes(self, *order):
        for nid in order or ('C', 'I'):
            self.assertEqual(self.step().get('node'), nid)
            self.assertEqual(self.verify(nid, CandidateChecker(self.ledger, 'P1'))['result'], 'pass', nid)

    def deliver(self, *order):
        self.through_nodes(*order)
        return handoff(self.ledger, 'P1')

    def final(self, mid='M1', red=True):
        with patch.dict(os.environ, {'CI': 'red'} if red else {}):
            return verdict.run(self.ledger, 'P1', mid)

    def receipt_of(self, shown, mid='M1'):
        return next(m for m in shown['milestones'] if m['id'] == mid)['last_verdict']['receipt']

    def need(self, **kw):
        return engine.next_action(self.ledger, 'P1', **kw)

    def open_ids(self):
        return sorted(f['id'] for f in findings.list_findings(self.ledger, 'P1', open_only=True))

    def gens(self):
        return {n: r['generation'] for n, r in engine.state(self.ledger, 'P1')['nodes'].items()}

    def kinds(self):
        return [k for k, _ in self.events()]

    def accept(self, artifact):
        with patch.dict(os.environ):
            os.environ.pop('ONECREW_ACTOR', None)
            return plan.accept(self.ledger, 'P1', 'owner', 'isolated Sol6 acceptance fixture', artifact)

    def repair(self, target='C', failed='C', receipt=None):
        with self.ledger.transaction() as conn:
            view = engine.state(self.ledger, 'P1', conn)
            source = receipt or repair_tasks._source(self.ledger, conn, view, failed)[0]
        return repair_tasks.prepare(self.ledger, 'P1', target, failed, reason='repair the failed check', evidence=[source])

    def owner(self, fn, *args, **kwargs):
        with patch.dict(os.environ):
            os.environ.pop('ONECREW_ACTOR', None)
            return fn(*args, **kwargs)


class RepairChains(Chain):
    def test_s5_1_a_repair_that_fails_its_node_check_can_be_repaired_again(self):
        self.deliver()
        self.assertEqual(self.final()['milestones'][0]['state'], 'failed')
        self.assertEqual(self.need()['kind'], 'diagnose')
        self.repair()
        self.assertEqual(self.open_ids(), ['RF1'])
        self.overlays = {'a.txt': BROKEN}
        self.step()
        self.assertEqual(self.verify('C', CandidateChecker(self.ledger, 'P1'))['result'], 'fail')
        self.assertEqual(self.open_ids(), ['RF1', 'RF2'])
        need = self.need()
        self.assertEqual((need['kind'], need['node']), ('diagnose', 'C'))
        second = self.repair()
        self.assertEqual(second['answered_findings'], ['RF1', 'RF2'])
        self.assertEqual(engine.state(self.ledger, 'P1')['finding_blockers'], {}, 'both findings let the repaired work run; neither is closed')
        self.assertEqual(self.open_ids(), ['RF1', 'RF2'])
        self.overlays = dict(self.good)
        delivered = self.deliver()
        self.assertEqual(self.open_ids(), ['RF1'], 'the node check closes its own finding; the milestone finding waits for its verdict')
        self.assertEqual(self.final()['milestones'][0]['state'], 'passed')
        self.assertEqual(self.open_ids(), [])
        self.assertEqual(self.need()['kind'], 'owner_accept')
        self.assertEqual(self.accept(delivered['artifact'])['status'], 'accepted')

    def test_s5_1_repeating_a_repair_without_a_new_failure_moves_nothing(self):
        self.deliver(); self.final()
        self.repair()
        gens, revisions = self.gens(), self.kinds().count('plan.revised')
        again = self.repair()
        self.assertTrue(again['already_prepared'])
        self.assertFalse(again['generation_moved'])
        self.assertEqual((self.gens(), self.kinds().count('plan.revised')), (gens, revisions))
        self.assertEqual(self.need()['kind'], 'step')
        self.overlays = dict(self.good)
        self.through_nodes()
        self.assertTrue(self.repair()['already_prepared'], 'the verified repair is not repeated either')
        self.assertEqual((self.gens(), self.kinds().count('plan.revised')), (gens, revisions))
        self.assertEqual(self.need()['kind'], 'handoff')

    def test_s5_1_a_new_failure_after_the_marker_needs_a_new_repair(self):
        self.deliver(); self.final()
        first = self.repair()
        self.final()                     # the first delivery is still on disk: a new red while the repair is prepared
        self.assertTrue(engine.state(self.ledger, 'P1')['finding_blockers'], 'the older marker no longer speaks for the current observation')
        self.assertEqual(self.need()['kind'], 'diagnose')
        self.assertNotEqual(self.repair()['receipt'], first['receipt'])
        self.assertEqual(engine.state(self.ledger, 'P1')['finding_blockers'], {})

    def test_s5_2_third_red_replan_runs_and_reaches_acceptance(self):
        self.deliver(); self.final(); self.repair()
        self.overlays = {'a.txt': b'w2\n'}; self.deliver(); self.final(); self.repair()
        self.overlays = {'a.txt': b'w3\n'}; self.deliver(); self.final()
        self.assertEqual(self.need()['kind'], 'diagnose')
        self.assertEqual(recovery_policy.assess(self.ledger, 'P1', 'C')['disposition'], 'diagnose')
        need = self.need()
        self.assertEqual(need['kind'], 'replan')
        rows = json.loads(json.dumps(engine.state(self.ledger, 'P1')['definition']['nodes']))
        rows[0]['goal'] += ' (another approach)'
        out = recovery_policy.replan(self.ledger, 'P1', 'C', rows, reason='a different approach', evidence=need['replan_file']['evidence'])
        self.assertFalse(out['resets_budget'])
        self.assertEqual(engine.state(self.ledger, 'P1')['finding_blockers'], {})
        self.assertEqual(self.need()['kind'], 'step')
        self.assertEqual(self.open_ids(), ['RF1'], 'replan closes nothing')
        self.overlays = dict(self.good)
        delivered = self.deliver()
        self.assertEqual(self.final()['milestones'][0]['state'], 'passed')
        self.assertEqual(self.accept(delivered['artifact'])['status'], 'accepted')

    def test_s5_2_red_after_the_replan_is_a_stop_with_a_reason_not_a_loop(self):
        self.deliver(); self.final(); self.repair()
        self.overlays = {'a.txt': b'w2\n'}; self.deliver(); self.final(); self.repair()
        self.overlays = {'a.txt': b'w3\n'}; self.deliver(); self.final()
        recovery_policy.assess(self.ledger, 'P1', 'C')
        need = self.need()
        rows = json.loads(json.dumps(engine.state(self.ledger, 'P1')['definition']['nodes']))
        rows[0]['goal'] += ' (another approach)'
        recovery_policy.replan(self.ledger, 'P1', 'C', rows, reason='a different approach', evidence=need['replan_file']['evidence'])
        self.overlays = {'a.txt': b'w4\n'}; self.deliver(); self.final()
        with self.assertRaises(LedgerError): recovery_policy.replan(self.ledger, 'P1', 'C', rows, reason='again', evidence=need['replan_file']['evidence'])
        gens = self.gens()
        with self.assertRaisesRegex(LedgerError, 'blocked'): self.repair()
        self.assertEqual(self.gens(), gens)
        need = self.need()                                        # the decision was recorded by the refused door
        self.assertEqual((need['kind'], need['state'], need['owner_only']), ('owner_decision', 'stopped', True))
        self.assertIn('amend', need['reason'])
        page = tracking.detail(self.ledger.state_root, 'P1')
        self.assertEqual(page['status']['kind'], 'blocked')
        self.assertIn('đã dừng', page['status']['reason'])
        self.assertIn('đã dừng', report.render_digest(self.ledger.state_root))

    def test_s5_2_the_digest_does_not_call_an_open_engine_root_closed(self):
        self.deliver()
        for overlay in (b'w2\n', b'w3\n'):
            self.final(); self.repair(); self.overlays = {'a.txt': overlay}; self.deliver()
        self.final()
        text = report.render_digest(self.ledger.state_root)
        self.assertIn('P1', text)
        self.assertIn('bước tiếp theo', text)
        self.assertIn('0 việc đã đóng', text)

    def test_n5_green_on_the_unchanged_tree_names_the_door_that_works(self):
        delivered = self.deliver()
        self.final()
        shown = self.final(red=False)
        self.assertEqual(shown['finding_actions'][0]['command'][:2], ['findings', 'reject'])
        need = self.need()
        self.assertEqual(need['kind'], 'reject_finding')
        self.assertIn('reject', need['command'])
        result = findings.resolve(self.ledger, 'P1', 'RF1', self.receipt_of(shown), reason='the red came from that shell', artifact_sha=delivered['artifact'], reject=True)
        self.assertEqual(result['closed'], ['RF1'])
        self.assertEqual(self.need()['kind'], 'owner_accept')


class EvidenceAndNodeFailures(Chain):
    bad = {'a.txt': BROKEN}

    def test_s5_2_a_node_that_keeps_failing_gets_its_replan_and_it_can_run(self):
        self.step(); self.assertEqual(self.verify('C', CandidateChecker(self.ledger, 'P1'))['result'], 'fail')
        self.repair()
        self.step(); self.assertEqual(self.verify('C', CandidateChecker(self.ledger, 'P1'))['result'], 'fail')
        self.assertEqual(recovery_policy.assess(self.ledger, 'P1', 'C')['disposition'], 'diagnose')
        need = self.need()
        self.assertEqual(need['kind'], 'replan')
        rows = json.loads(json.dumps(engine.state(self.ledger, 'P1')['definition']['nodes']))
        rows[0]['goal'] += ' (another approach)'
        recovery_policy.replan(self.ledger, 'P1', 'C', rows, reason='a different approach', evidence=need['replan_file']['evidence'])
        self.assertEqual(self.need()['kind'], 'step')
        self.overlays = dict(self.good)
        delivered = self.deliver()
        self.assertEqual(self.open_ids(), [])
        self.assertEqual(self.final()['milestones'][0]['state'], 'passed')
        self.assertEqual(self.accept(delivered['artifact'])['status'], 'accepted')


class EvidenceChecks(Chain):
    def test_an_older_final_receipt_cannot_drive_a_repair(self):
        self.deliver()
        old = self.receipt_of(self.final())
        self.final()
        with self.assertRaises(LedgerError):
            repair_tasks.prepare(self.ledger, 'P1', 'C', 'C', reason='stale', evidence=[old], receipt=old)

    def test_a_repair_under_way_does_not_let_acceptance_through(self):
        delivered = self.deliver(); self.final(); self.repair()
        with self.assertRaises(LedgerError): self.accept(delivered['artifact'])
        self.overlays = dict(self.good)
        again = self.deliver()
        with self.assertRaises(LedgerError): self.accept(again['artifact'])
        self.assertEqual(self.open_ids(), ['RF1'])
        self.assertEqual(self.need()['kind'], 'verify_milestone')

    def test_a_repair_with_no_failure_at_all_is_refused(self):
        self.deliver()
        with self.assertRaises(LedgerError): self.repair()
        self.assertNotIn('workflow.repair_prepared', self.kinds())


class TwoMilestones(Chain):
    milestones = (milestone('M1', argv=[sys.executable, '-c', 'import os,pathlib;t=pathlib.Path("a.txt").read_text();print(t);raise SystemExit(3 if os.environ.get("CI")=="red" and t=="regress\\n" else 0)'], mode='until_pass', max_repairs=5),
                  milestone('M2', argv=[sys.executable, '-c', 'import os,pathlib;t=pathlib.Path("a.txt").read_text();print(t);raise SystemExit(3 if os.environ.get("CI")=="red" and t=="candidate\\n" else 0)'], mode='until_pass', max_repairs=5))

    def test_s5_1_a_repair_for_one_milestone_that_breaks_another_can_still_be_repaired(self):
        self.deliver()
        self.final('M1'); self.assertEqual(self.final('M2')['milestones'][1]['state'], 'failed')
        self.assertEqual(self.need()['kind'], 'diagnose')
        self.repair()
        self.overlays = {'a.txt': b'regress\n'}
        self.deliver()
        self.assertEqual(self.final('M1')['milestones'][0]['state'], 'failed')
        self.assertEqual(len(self.open_ids()), 2)
        self.assertEqual(self.need()['kind'], 'diagnose')
        second = self.repair()
        self.assertEqual(len(second['answered_findings']), 2)
        self.assertEqual(engine.state(self.ledger, 'P1')['finding_blockers'], {})
        self.overlays = dict(self.good)
        delivered = self.deliver()
        self.assertEqual(self.open_ids().__len__(), 2, 'no verdict has spoken yet')
        self.final('M1'); self.final('M2')
        self.assertEqual(self.open_ids(), [])
        self.assertEqual(self.accept(delivered['artifact'])['status'], 'accepted')


class IntegrationOnly(Chain):
    milestones = (milestone('M1', mode='until_pass', max_repairs=5), milestone('M2', argv=gate(), mode='until_pass', max_repairs=5))

    def nodes(self):
        rows = super().nodes()
        rows[0]['checks'] = [{'id': 'M1', 'spec': 'Run M1'}]
        return rows

    def test_s5_5_a_milestone_only_the_integration_node_runs_names_its_repair(self):
        self.deliver()
        self.final('M1'); self.final('M2')
        need = self.need()
        self.assertEqual(need['kind'], 'diagnose')
        self.assertEqual((need['node'], need['repair_file']['target'], need['repair_file']['failed_node']), ('I', 'C', 'I'))
        repair_tasks.prepare(self.ledger, 'P1', 'C', 'I', reason='fix what the e2e saw', evidence=[need['source_receipt']])
        self.overlays = dict(self.good)
        delivered = self.deliver()
        self.final('M1') if plan.show(self.ledger, 'P1')['milestones'][0]['state'] != 'passed' else None
        self.final('M2')
        self.assertEqual(self.accept(delivered['artifact'])['status'], 'accepted')

    def test_s5_5_a_node_that_does_not_carry_the_check_is_pointed_at_the_one_that_does(self):
        self.deliver()
        self.final('M1'); self.final('M2')
        with self.assertRaisesRegex(LedgerError, 'M2 failed and is checked by node I'): recovery_policy.assess(self.ledger, 'P1', 'C')


class FolderScope(Chain):
    paths = ('src',)
    bad = {'src/a.txt': BAD}
    good = {'src/a.txt': GOOD}
    milestones = (milestone('M1', argv=gate('src/a.txt'), mode='until_pass', max_repairs=5),)

    def prepare(self):
        (self.root / 'src').mkdir()
        (self.root / 'src' / 'a.txt').write_text('base\n')

    def nodes(self):
        rows = [node('C', write=('src/a.txt',)), node('I', ['C'], integration=True, write=())]
        for item in rows:
            item['read'] = ['src/a.txt']
            item['checks'] = [{'id': 'M1', 'spec': 'Run M1'}]
        return rows

    def execute(self, ledger, control, task, item, attempt):
        paths = ['src/a.txt']
        control.launched(attempt['id'], attempt['generation'], {'fixture': True})
        artifact = self.store.overlay(self.store.capture(self.root, paths), self.overlays, paths)
        receipt = self.store.blob(canonical({'kind': 'fixture-producer', 'artifact': artifact}).encode())
        control.finish(attempt['id'], attempt['generation'], {'artifact': artifact})
        return {'artifact': artifact, 'receipt': receipt}

    def test_s5_5_owned_folder_holds_and_guides_like_owned_file(self):
        self.deliver(); self.final()
        self.assertIn('C', engine.state(self.ledger, 'P1')['finding_blockers'])
        self.assertEqual(self.need()['kind'], 'diagnose')
        self.repair()
        self.overlays = dict(self.good)
        delivered = self.deliver()
        self.assertEqual(self.final()['milestones'][0]['state'], 'passed')
        self.assertEqual(self.accept(delivered['artifact'])['status'], 'accepted')


class ManyWriters(Chain):
    paths = ('a.txt', 'b.txt')
    bad = {'a.txt': BAD, 'b.txt': b'b\n'}
    good = {'a.txt': GOOD, 'b.txt': b'b\n'}
    reader = False

    def prepare(self):
        (self.root / 'b.txt').write_text('base\n')

    def nodes(self):
        a, b = node('A', write=('a.txt',)), node('B', write=('b.txt',))
        a['read'], b['read'] = ['a.txt'], ['b.txt', 'a.txt'] if self.reader else ['b.txt']
        final = node('I', ['A', 'B'], integration=True, write=()); final['read'] = list(self.paths)
        for item in (a, b, final): item['checks'] = [{'id': 'M1', 'spec': 'Run M1'}]
        return [a, b, final]

    def execute(self, ledger, control, task, item, attempt):
        paths = list(item['write']) or list(self.paths)
        control.launched(attempt['id'], attempt['generation'], {'fixture': True})
        artifact = self.store.overlay(self.store.capture(self.root, paths), {p: self.overlays[p] for p in paths}, paths)
        receipt = self.store.blob(canonical({'kind': 'fixture-producer', 'artifact': artifact}).encode())
        control.finish(attempt['id'], attempt['generation'], {'artifact': artifact})
        return {'artifact': artifact, 'receipt': receipt}

    def test_s5_8_a_repair_of_one_writer_leaves_the_other_and_its_evidence(self):
        self.deliver('A', 'B', 'I'); self.final()
        need = self.need()
        self.assertEqual(need['kind'], 'diagnose')
        self.assertEqual([c['target'] for c in need['repair_targets']], ['A', 'B'])
        kept = engine.state(self.ledger, 'P1')['nodes']['B']
        repair = self.repair('A', 'A')
        self.assertEqual(repair['keeps_evidence'], ['B'])
        self.assertEqual([r['node'] for r in repair['rerun']], ['A', 'I'])
        self.assertEqual(repair['cost']['calls'], 2)
        view = engine.state(self.ledger, 'P1')
        self.assertEqual(view['finding_blockers'], {'B': ['RF1']}, 'B takes no new work')
        self.assertEqual(engine.finding_gate(view), {}, 'and does not stop delivery of the repair')
        self.overlays = dict(self.good)
        delivered = self.deliver('A', 'I')
        after = engine.state(self.ledger, 'P1')['nodes']['B']
        self.assertEqual((after['generation'], after['verification_receipt']), (kept['generation'], kept['verification_receipt']))
        self.assertEqual(self.open_ids(), ['RF1'], 'delivery closes nothing')
        self.assertEqual(self.final()['milestones'][0]['state'], 'passed')
        self.assertEqual(self.open_ids(), [])
        self.assertEqual(self.accept(delivered['artifact'])['status'], 'accepted')

    def test_s5_8_the_whole_cost_is_refused_before_anything_changes(self):
        self.deliver('A', 'B', 'I'); self.final()
        gens, kinds = self.gens(), self.kinds()
        real = internal_plan.ceilings
        with patch.object(internal_plan, 'ceilings', side_effect=lambda *a: dict(real(*a), remaining_calls=1)):
            need = self.need()
            self.assertEqual((need['kind'], need['state']), ('owner_decision', 'stopped'))
            with self.assertRaisesRegex(LedgerError, 'U2: this repair needs 2 calls'): self.repair('A', 'A')
        self.assertEqual(self.gens(), gens)
        self.assertNotIn('workflow.repair_prepared', self.kinds())
        self.assertEqual(self.kinds().count('plan.revised'), kinds.count('plan.revised'))


class ManyWritersWithReader(ManyWriters):
    reader = True

    def test_s5_8_a_reader_runs_again_and_is_explained_and_counted(self):
        self.deliver('A', 'B', 'I'); self.final()
        repair = self.repair('A', 'A')
        self.assertEqual(repair['keeps_evidence'], [])
        self.assertEqual(repair['cost']['calls'], 3)
        rows = {r['node']: r['why'] for r in repair['rerun']}
        self.assertIn('A', rows['B'])
        self.assertEqual(engine.state(self.ledger, 'P1')['finding_blockers'], {})

    test_s5_8_a_repair_of_one_writer_leaves_the_other_and_its_evidence = None
    test_s5_8_the_whole_cost_is_refused_before_anything_changes = None


class UnrelatedHold(ManyWriters):
    milestones = (milestone('M1', argv=gate(), mode='until_pass', max_repairs=5),)

    def test_a_finding_of_another_node_keeps_its_hold(self):
        self.overlays = {'a.txt': BROKEN, 'b.txt': b'b\n'}
        checker = CandidateChecker(self.ledger, 'P1')
        self.step(); self.assertEqual(self.verify('A', checker)['result'], 'fail')
        self.step()
        self.assertEqual(self.verify('B', self.red_b)['result'], 'fail')
        ids = {f['node']: f['id'] for f in findings.list_findings(self.ledger, 'P1', open_only=True)}
        self.assertEqual(sorted(ids), ['A', 'B'])
        repair = self.repair('A', 'A')
        self.assertEqual(repair['answered_findings'], [ids['A']], 'not the other node\'s finding')
        view = engine.state(self.ledger, 'P1')
        self.assertIn(ids['B'], view['finding_blockers']['I'])
        self.assertIn(ids['B'], view['finding_blockers']['B'])

    def red_b(self, item, artifact):
        result = CandidateChecker(self.ledger, 'P1')(item, artifact)
        for row in result['checks']: row['result'] = 'fail'
        return result

    test_s5_8_a_repair_of_one_writer_leaves_the_other_and_its_evidence = None
    test_s5_8_the_whole_cost_is_refused_before_anything_changes = None


NOQ5 = dict(loop.GRANT, self_decide=[q for q in loop.GRANT['self_decide'] if q != 'Q5'])


class NoQ5(Chain):
    def setUp(self):
        grant = patch.object(loop, 'GRANT', NOQ5); grant.start(); self.addCleanup(grant.stop)
        super().setUp()

    def held(self):
        self.deliver(); self.final()
        with self.assertRaisesRegex(LedgerError, 'U3'): self.repair()
        [request] = questions.list_for_plan(self.ledger, 'P1', pending=True)
        return request

    def amend(self):
        value = plan.show(self.ledger, 'P1')['contract']
        value = json.loads(json.dumps(value))
        for item in value['items']: item.pop('runs', None)
        value['authority']['self_decide'] = loop.GRANT['self_decide'] + ['Q5'] if 'Q5' not in loop.GRANT['self_decide'] else loop.GRANT['self_decide']
        plan.amend(self.ledger, 'P1', value, 'delegate the repair decision', 'codex')
        self.owner(plan.approve, self.ledger, 'P1', 'owner', 'fixture approval of the amendment')

    def finish_after_amendment(self):
        self.assertEqual(self.need()['kind'], 'revise_plan')
        self.revise(json.loads(json.dumps(engine.state(self.ledger, 'P1')['definition']['nodes'])), reason='bind to the approved revision')
        need = self.need()
        self.assertEqual(need['kind'], 'diagnose')
        self.assertFalse(need['needs_owner_decision'])
        self.repair()
        self.overlays = dict(self.good)
        delivered = self.deliver()
        self.assertEqual(self.final()['milestones'][0]['state'], 'passed')
        self.assertEqual(self.open_ids(), [])
        self.assertEqual(self.accept(delivered['artifact'])['status'], 'accepted')
        self.assertEqual((self.root / 'a.txt').read_bytes().replace(b'\r\n', b'\n'), GOOD)

    def test_s5_3_the_question_offers_only_what_can_be_carried_out(self):
        request = self.held()
        self.assertEqual([o['id'] for o in request['question']['options']], ['amend_plan', 'stop'])
        need = self.need()
        self.assertEqual((need['kind'], need['owner_only']), ('owner_decision', True))
        self.assertEqual(need['choices'], ['amend_plan', 'stop'])
        self.assertEqual(need['command'][need['command'].index('owner') + 1], 'answer')
        with self.assertRaisesRegex(LedgerError, 'Choice does not match'):
            self.owner(questions.answer, self.ledger, request['id'], request['revision'], 'continue', 'fixture')
        self.assertEqual(len(questions.list_for_plan(self.ledger, 'P1', pending=True)), 1)

    def test_s5_3_amend_plan_grants_nothing_until_the_amendment_is_approved(self):
        request = self.held()
        effect = self.owner(questions.answer, self.ledger, request['id'], request['revision'], 'amend_plan', 'fixture')['controller_effect']
        self.assertEqual((effect['effect'], effect['grants_authority']), ('await_new_approved_revision', False))
        self.assertEqual(self.need()['kind'], 'amend_grant')
        with self.assertRaisesRegex(LedgerError, 'U3'): self.repair()
        self.assertEqual(self.open_ids(), ['RF1'])
        self.amend()
        self.finish_after_amendment()

    def test_s5_3_an_approved_amendment_supersedes_the_unanswered_question(self):
        request = self.held()
        self.amend()
        self.assertEqual(questions.list_for_plan(self.ledger, 'P1', pending=True), [])
        row = self.ledger.request(request['id'])
        self.assertEqual(row['answer']['choice'], 'superseded_by_approval')
        self.assertIsNone(row['answer']['provenance']['decided_by'], 'the approval is on record; no answer is put in the owner\'s mouth')
        self.finish_after_amendment()

    def test_s5_3_an_amendment_that_does_not_delegate_q5_asks_again(self):
        self.held()
        value = json.loads(json.dumps(plan.show(self.ledger, 'P1')['contract']))
        for item in value['items']: item.pop('runs', None)
        value['title'] = 'Another title'
        plan.amend(self.ledger, 'P1', value, 'unrelated change', 'codex')
        self.owner(plan.approve, self.ledger, 'P1', 'owner', 'fixture approval of the amendment')
        self.revise(json.loads(json.dumps(engine.state(self.ledger, 'P1')['definition']['nodes'])), reason='bind to the approved revision')
        need = self.need()
        self.assertTrue(need['needs_owner_decision'])
        with self.assertRaisesRegex(LedgerError, 'U3'): self.repair(receipt=need['source_receipt'])
        self.assertEqual(len(questions.list_for_plan(self.ledger, 'P1', pending=True)), 1, 'nothing was delegated by the approval')

    def test_s5_3_stop_closes_the_root_and_keeps_the_evidence(self):
        request = self.held()
        self.owner(questions.answer, self.ledger, request['id'], request['revision'], 'stop', 'fixture')
        self.assertEqual(plan.show(self.ledger, 'P1')['status'], 'closed')
        self.assertEqual(self.need()['state'], 'stopped')
        self.assertEqual(self.open_ids(), ['RF1'])

    def test_s5_3_a_question_still_offering_continue_is_refused_with_the_way_on(self):
        request = self.held()
        question = dict(request['question'], options=[{'id': 'continue', 'label': 'Continue'}, {'id': 'stop', 'label': 'Stop'}], recommendation='continue')
        revised = self.ledger.revise_request(request['id'], request['revision'], question)
        with self.assertRaisesRegex(LedgerError, 'continue grants nothing'):
            self.owner(questions.answer, self.ledger, request['id'], revised['revision'], 'continue', 'fixture')
        self.assertEqual(self.ledger.request(request['id'])['state'], 'pending', 'the refused answer is not recorded')

    def test_s5_3_a_replan_stands_on_the_same_authority(self):
        self.held()
        rows = json.loads(json.dumps(engine.state(self.ledger, 'P1')['definition']['nodes']))
        rows[0]['goal'] += ' (another approach)'
        with self.assertRaises(LedgerError):
            recovery_policy.replan(self.ledger, 'P1', 'C', rows, reason='no authority', evidence=['a.txt:1'])
        self.assertEqual(self.open_ids(), ['RF1'])


class NoQ5AtNode(NoQ5):
    bad = {'a.txt': BROKEN}

    def held(self):
        self.step()
        self.assertEqual(self.verify('C', CandidateChecker(self.ledger, 'P1'))['result'], 'fail')
        with self.assertRaisesRegex(LedgerError, 'U3'): self.repair()
        [request] = questions.list_for_plan(self.ledger, 'P1', pending=True)
        return request

    def finish_after_amendment(self):
        self.assertEqual(self.need()['kind'], 'revise_plan')
        self.revise(json.loads(json.dumps(engine.state(self.ledger, 'P1')['definition']['nodes'])), reason='bind to the approved revision')
        need = self.need()
        self.assertEqual((need['kind'], need['node']), ('diagnose', 'C'))
        self.repair(receipt=need['source_receipt'])
        self.overlays = dict(self.good)
        delivered = self.deliver()
        self.assertEqual(self.open_ids(), [])
        self.assertEqual(self.final(red=False)['milestones'][0]['state'], 'passed')
        self.assertEqual(self.accept(delivered['artifact'])['status'], 'accepted')

    test_s5_3_a_replan_stands_on_the_same_authority = None
    test_s5_3_an_amendment_that_does_not_delegate_q5_asks_again = None


class Stopped(Chain):
    milestones = (milestone('M1', argv=gate(), mode='until_pass', max_repairs=1),)

    def test_s5_5_after_a_stop_and_an_approved_amendment_the_steps_are_named_and_cas_accepts_the_earlier_delivery(self):
        self.deliver(); self.final(); self.repair()
        self.overlays = {'a.txt': b'w2\n'}
        self.deliver()
        shown = self.final()
        self.assertEqual(shown['status'], 'stopped_with_report')
        need = self.need()
        self.assertEqual((need['state'], need['owner_only']), ('stopped', True))
        value = json.loads(json.dumps(plan.show(self.ledger, 'P1')['contract']))
        for item in value['items']: item.pop('runs', None)
        value['milestones'][0]['max_repairs'] = 5
        plan.amend(self.ledger, 'P1', value, 'allow more repairs', 'codex')
        self.assertEqual(self.need()['state'], 'waiting')
        self.owner(plan.approve, self.ledger, 'P1', 'owner', 'fixture approval of the amendment')
        self.assertEqual(self.need()['kind'], 'revise_plan')
        self.revise(json.loads(json.dumps(engine.state(self.ledger, 'P1')['definition']['nodes'])), reason='bind to the approved revision')
        need = self.need()
        self.assertEqual(need['kind'], 'diagnose', need)
        self.repair()
        self.overlays = dict(self.good)
        delivered = self.deliver()
        self.assertEqual((self.root / 'a.txt').read_bytes().replace(b'\r\n', b'\n'), GOOD, 'the earlier delivery of this root is replaced, by hand nothing')
        self.assertEqual(self.final()['milestones'][0]['state'], 'passed')
        self.assertEqual(self.accept(delivered['artifact'])['status'], 'accepted')

    def test_cas_still_refuses_a_hand_edit_after_an_amendment(self):
        self.deliver(); self.final(); self.repair()
        self.overlays = {'a.txt': b'w2\n'}
        self.deliver(); self.final()
        value = json.loads(json.dumps(plan.show(self.ledger, 'P1')['contract']))
        for item in value['items']: item.pop('runs', None)
        value['milestones'][0]['max_repairs'] = 5
        plan.amend(self.ledger, 'P1', value, 'allow more repairs', 'codex')
        self.owner(plan.approve, self.ledger, 'P1', 'owner', 'fixture approval of the amendment')
        self.revise(json.loads(json.dumps(engine.state(self.ledger, 'P1')['definition']['nodes'])), reason='bind to the approved revision')
        self.repair()
        self.overlays = dict(self.good)
        self.through_nodes()
        (self.root / 'a.txt').write_text('user edit\n')
        with self.assertRaises(LedgerError): handoff(self.ledger, 'P1')
        self.assertEqual((self.root / 'a.txt').read_text(), 'user edit\n')


class ReadsAndStates(Chain):
    def spy(self):
        real, rows = command._git, []
        def counted(directory, *args, **kwargs):
            if 'update-index' in args: rows.append(args)
            return real(directory, *args, **kwargs)
        return patch.object(command, '_git', side_effect=counted), rows

    def objects(self):
        return sum(1 for p in (self.root / '.git' / 'objects').rglob('*') if p.is_file())

    def test_s5_4_a_view_of_a_delivered_root_hashes_nothing_and_writes_nothing(self):
        self.deliver(); self.final(red=False)
        (self.root / 'dep.txt').write_text('outside owned\n')       # a read must not store this file in the project's objects either
        before = self.objects()
        spy, rows = self.spy()
        with spy:
            need = self.need(observe_project=False)
            page = tracking.detail(self.ledger.state_root, 'P1')
            tracking.overview(self.ledger.state_root)
            text = report.render_digest(self.ledger.state_root)
        self.assertEqual(rows, [])
        self.assertEqual(self.objects(), before)
        self.assertEqual((need['kind'], need['recorded_only']), ('owner_accept', True))
        self.assertEqual(page['next_action']['kind'], 'owner_accept')
        self.assertIn('nghiệm thu', text)

    def test_s5_4_the_doors_that_act_still_judge_the_tree(self):
        delivered = self.deliver(); self.final(red=False)
        (self.root / 'dep.txt').write_text('outside owned\n')
        need = self.need()
        self.assertEqual((need['kind'], need['state']), ('inspect', 'blocked'))
        self.assertIn('Project changed', need['reason'])
        with self.assertRaisesRegex(LedgerError, 'differs from the verified handoff'): self.accept(delivered['artifact'])
        (self.root / 'dep.txt').unlink()
        self.assertEqual(self.need()['kind'], 'owner_accept')
        self.assertEqual(self.accept(delivered['artifact'])['status'], 'accepted')

    def test_s5_6_an_expired_root_says_stop_and_promises_no_door(self):
        self.step()
        real = internal_plan.ceilings
        with patch.object(internal_plan, 'ceilings', side_effect=lambda *a: dict(real(*a), remaining_seconds=0)):
            need = self.need()
        self.assertEqual((need['kind'], need['state'], need['owner_only']), ('owner_decision', 'stopped', True))
        self.assertIn('niêm phong', need['reason'])
        self.assertNotIn('extend', need['reason'])
        self.assertNotIn('verify', [p for p in need['command']])

    def test_s5_6_an_amendment_does_not_move_the_sealed_ceiling(self):
        with self.ledger.transaction() as conn:
            before = internal_plan.ceilings(self.ledger, conn, plan.anchor_events(self.ledger, conn, 'P1'))
        value = json.loads(json.dumps(plan.show(self.ledger, 'P1')['contract']))
        for item in value['items']: item.pop('runs', None)
        value['budget']['time'] = value['budget']['time'] + 240
        value['budget']['max_calls'] = value['budget']['max_calls'] + 50
        plan.amend(self.ledger, 'P1', value, 'more time and calls', 'codex')
        self.owner(plan.approve, self.ledger, 'P1', 'owner', 'fixture approval of the amendment')
        with self.ledger.transaction() as conn:
            after = internal_plan.ceilings(self.ledger, conn, plan.anchor_events(self.ledger, conn, 'P1'))
        self.assertEqual(after['deadline'], before['deadline'])
        self.assertEqual(after['remaining_calls'], before['remaining_calls'])

    def test_n1_a_held_final_run_names_its_release(self):
        self.deliver()
        with patch.dict(os.environ, {'CI': 'other'}), patch.object(command, 'run', side_effect=RuntimeError('lost')):
            with self.assertRaises(RuntimeError): verdict.run(self.ledger, 'P1', 'M1')
        with self.assertRaisesRegex(LedgerError, 'unknown outcome'):
            with patch.dict(os.environ, {'CI': 'other'}): verdict.run(self.ledger, 'P1', 'M1')
        need = self.need()
        self.assertEqual(need['kind'], 'release_run')
        self.assertIn('release-run', need['command'])
        verdict.release_run(self.ledger, 'P1', need['run'], 'checked: nothing ran')
        self.assertEqual(self.need()['kind'], 'verify_milestone')

    def test_n2_a_held_node_check_names_its_release(self):
        self.step()
        def broken(item, artifact): raise OSError('checker host gone')
        with self.assertRaises(OSError): self.verify('C', broken)
        need = self.need()
        self.assertEqual(need['kind'], 'release_check')
        self.assertIn('release-check', need['command'])

    def test_n3_the_owner_terminal_reads_the_recorded_verdict_as_passed(self):
        delivered = self.deliver(); shown = self.final(red=False)
        contract = shown['contract']
        with patch.dict(os.environ, {'TERM': 'owner-terminal'}):
            row = plan.show(self.ledger, 'P1')['milestones'][0]
            self.assertEqual(row['state'], 'passed')
            self.assertFalse(row.get('stale'))
            self.assertTrue(row['execution_environment_changed'])
            strict = verification_evidence.receipt_assessment(self.ledger, contract, contract['milestones'][0], 1, self.receipt_of(shown), delivered['artifact'])
            self.assertFalse(strict['reusable'], 'a new execution or reuse still judges this environment')

    def test_n6_the_second_milestone_walks_no_extra_time_for_a_closure_it_does_not_have(self):
        self.deliver()
        spy, rows = self.spy()
        with spy, patch.object(verdict.plans, 'milestone_views', wraps=plan.milestone_views) as views:
            self.assertIsNone(verdict._resume_closure(self.ledger, 'P1', 'M1'))
        self.assertEqual(rows, [])
        views.assert_not_called()

    def test_f6_a_door_that_admits_work_keeps_the_root_bound_around_the_ready_check(self):
        self.deliver()
        past = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(minutes=1)).isoformat()
        with command.snapshot_limits(past):
            with self.assertRaises(command.SnapshotFailed):
                engine.root_ready(self.ledger, 'P1')
        self.assertTrue(engine.root_ready(self.ledger, 'P1'), 'acceptance sets no root limit')

    def test_n7_the_snapshot_message_names_only_the_limit_that_applies(self):
        with command._snapshot('accept'):
            budget = command._active.get()
            budget.begin -= budget.limit + 1
            with self.assertRaises(command.SnapshotFailed) as free:
                budget.check('step')
        self.assertNotIn('root deadline', str(free.exception))
        future = (dt.datetime.now(dt.timezone.utc) + dt.timedelta(days=9)).isoformat()
        with command.snapshot_limits(future), command._snapshot('verdict'):
            budget = command._active.get()
            budget.begin -= budget.limit + 1
            with self.assertRaises(command.SnapshotFailed) as bound:
                budget.check('step')
        self.assertIn('the root deadline still applies', str(bound.exception))

    def test_status_words_tell_the_five_states_apart(self):
        self.step()
        working = tracking.detail(self.ledger.state_root, 'P1')['status']
        self.assertEqual(working['kind'], 'waiting')
        self.verify('C', CandidateChecker(self.ledger, 'P1')); self.step(); self.verify('I', CandidateChecker(self.ledger, 'P1'))
        delivered = handoff(self.ledger, 'P1'); self.final()
        blocked = tracking.detail(self.ledger.state_root, 'P1')['status']
        self.assertEqual(blocked['kind'], 'blocked')
        self.assertNotIn('đã dừng', blocked['reason'])
        findings_left = self.final(red=False)
        waiting_owner = None
        findings.resolve(self.ledger, 'P1', 'RF1', self.receipt_of(findings_left), reason='that shell', artifact_sha=delivered['artifact'], reject=True)
        waiting_owner = tracking.detail(self.ledger.state_root, 'P1')['status']
        self.assertEqual(waiting_owner['label'], 'đã kiểm, chờ nghiệm thu')
        self.accept(delivered['artifact'])
        self.assertEqual(tracking.detail(self.ledger.state_root, 'P1')['status']['label'], 'đã nghiệm thu')


class LegacyRoot(Fixture):
    def test_s5_7_a_passing_verdict_on_a_plan_root_reports_success_and_refreshes_the_hooks(self):
        plan.propose(self.ledger, 'P1', plan_json(), 'codex')
        plan.approve(self.ledger, 'P1', 'owner', 'fixture approval on a temporary ledger')
        with self.ledger.transaction(write=True) as conn:
            conn.execute('UPDATE tasks SET request_key=? WHERE request_key=?', ('plan:P1', 'plan-ns:P1'))
        with patch.object(active_plan, 'export', wraps=active_plan.export) as exported:
            shown = verdict.run(self.ledger, 'P1', 'M1')
        self.assertEqual(shown['milestones'][0]['state'], 'passed')
        exported.assert_called()
        self.assertEqual(shown['anchor'], 'plan:P1', 'the namespace is not moved')

    def test_s5_7_a_root_written_by_an_old_build(self):
        temp = tempfile.TemporaryDirectory(prefix='ocs6-old-'); self.addCleanup(temp.cleanup)
        old = ov.OldVersion(ov.archive('d3120c6', REPO, temp.name))
        path = Path(temp.name) / 'contract.json'
        path.write_text(json.dumps(ov.contract('Legacy root')), encoding='utf-8')
        code, output = old.run(self.root, self.ledger.state_root, 'plan', 'propose', 'old', '--file', str(path), '--author', 'codex')
        self.assertEqual(code, 0, output)
        plan.approve(self.ledger, 'plan:old', 'owner', 'fixture legacy approval')
        shown = verdict.run(self.ledger, 'plan:old', plan.show(self.ledger, 'plan:old')['milestones'][0]['id'])
        self.assertEqual(shown['anchor'], 'plan:old')
        self.assertEqual(shown['milestones'][0]['state'], 'passed')


if __name__ == '__main__':
    unittest.main()
