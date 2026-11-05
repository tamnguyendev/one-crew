"""RV-T7: one workflow, two kinds of work: output -> check -> finding -> repair -> recheck -> delivery, through the same engine door, with real Git
candidates, real command verifiers (coding case) and the existing doc/data adapters (non-code case). No provider is used: a reviewer milestone is
exercised separately with a fixture provider. An adapter checks structure and reconciliation; it does not prove business meaning."""
import json
import os
import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))          # the adapter fixtures import test_v2_l1 by its plain name

from onecrew.common_handoff import handoff                          # noqa: E402
from onecrew.common_verification import CandidateChecker            # noqa: E402
from onecrew.control_core import Control, migrate                   # noqa: E402
from onecrew.ledger import LedgerError, canonical, content_hash     # noqa: E402
from onecrew.snapshots import Snapshots                             # noqa: E402
from onecrew.v2 import engine, findings, internal_plan, plan, repair_tasks, review_dispatch, verdict  # noqa: E402
from onecrew.v2.verifiers import command, port                      # noqa: E402
from tests.test_v2_l1 import Fixture, milestone, plan_json          # noqa: E402
from tests.test_v2_reviewer import reviewer_milestone               # noqa: E402
from tests.test_wf_engine import EngineFixture, node                # noqa: E402
from tests.test_wf_rx2_adapters import DATA, TABLE                  # noqa: E402

CAPS = ['namespaced-storage', 'finding-register', 'root-budget', 'internal-plan', 'sequential-engine']
GRANT = {'edit': True, 'commands': True, 'apply_to_project': True, 'unconfined_commands': True,
         'self_decide': ['Q1', 'Q2', 'Q3', 'Q4', 'Q5', 'Q8', 'Q9', 'Q12']}


class LoopFixture(EngineFixture):
    paths, bad, good, milestones = (), {}, {}, ()

    def setUp(self):
        Fixture.setUp(self)
        self.engine, self.ip = engine, internal_plan
        self.prepare()
        self.git('add', '.'); self.git('commit', '-qm', 'work baseline', '--allow-empty')
        value = plan_json(milestones=list(self.milestones), scope={'owned': list(self.paths)}, authority=GRANT,
                          items=[{'id': 'I1', 'title': 'Verified output', 'tier': 'must', 'milestone': self.milestones[0]['id']}])
        self.root_view = plan.propose(self.ledger, 'P1', value, 'codex', workflow=True, capabilities=CAPS)
        plan.approve(self.ledger, 'P1', 'owner', 'fixture approval on a temporary ledger')
        os.environ['ONECREW_ACTOR'] = 'codex'
        self.store = Snapshots(self.ledger.state_root); migrate(self.ledger); self.control = Control(self.ledger)
        self.overlays = dict(self.bad)
        self.revise(self.nodes())

    def nodes(self):
        rows = [node('C', write=self.paths), node('I', ['C'], integration=True, write=())]
        for item in rows:
            item['read'] = list(self.paths)
            item['checks'] = [{'id': m['id'], 'spec': 'Run the approved ' + m['id'] + ' verifier'} for m in self.milestones]
        return rows

    def prepare(self):
        raise NotImplementedError

    def execute(self, ledger, control, task, item, attempt):
        control.launched(attempt['id'], attempt['generation'], {'fixture': True})
        artifact = self.store.overlay(self.store.capture(self.root, list(self.paths)), self.overlays, list(self.paths))
        receipt = self.store.blob(canonical({'kind': 'fixture-producer', 'artifact': artifact}).encode())
        control.finish(attempt['id'], attempt['generation'], {'artifact': artifact})
        return {'artifact': artifact, 'receipt': receipt}

    def node_runs(self):
        return [p for k, p in self.events() if k == 'review.run_started' and p['check'] == 'node-verification']

    def run_the_loop(self, patched, failing):
        """The common workflow; `patched` counts actual verifier executions."""
        checker = CandidateChecker(self.ledger, 'P1')
        self.step()
        first = self.verify('C', checker)
        self.assertEqual(first['result'], 'fail')
        rows = {r['id']: r['result'] for r in first['observed']['checks']}
        self.assertEqual(rows[failing], 'fail')
        failed_receipt = engine.state(self.ledger, 'P1')['nodes']['C']['verification_receipt']
        # a check that ran is not a bug: one failed criterion among several checks is one finding, bound to the failed receipt
        opened = findings.list_findings(self.ledger, 'P1', open_only=True)
        self.assertEqual(len(opened), 1)
        self.assertGreater(len(rows), len(opened))
        self.assertEqual((opened[0]['node'], opened[0]['criterion'], opened[0]['source']['receipt']), ('C', failing, failed_receipt))
        repair = repair_tasks.prepare(self.ledger, 'P1', 'C', 'C', reason='Fix the failed check', evidence=[failed_receipt])
        self.assertEqual((repair['source_receipt'], repair['failed_checks']), (failed_receipt, [failing]))
        self.overlays.update(self.good)
        self.step()
        second = self.verify('C', checker)
        self.assertEqual(second['result'], 'pass')
        self.assertEqual(second['findings']['closed'], [opened[0]['id']])
        closed = next(f for f in findings.list_findings(self.ledger, 'P1') if f['id'] == opened[0]['id'])
        self.assertEqual(closed['status'], 'resolved')
        self.assertEqual(closed['source']['receipt'], failed_receipt)          # the recheck closes the same finding, it does not make a new one
        # the recheck is its own request and run on the repaired output
        self.assertNotEqual(first['check_run']['request_id'], second['check_run']['request_id'])
        self.assertNotEqual(first['check_run']['run_id'], second['check_run']['run_id'])
        self.assertNotEqual(first['observed']['candidate_tree'], second['observed']['candidate_tree'])
        self.assertEqual(engine.state(self.ledger, 'P1')['nodes']['C']['state'], 'verified')
        before = len(patched)
        self.step()
        integrated = self.verify('I', checker)
        self.assertEqual(integrated['result'], 'pass')
        self.assertEqual(integrated['observed']['candidate_tree'], second['observed']['candidate_tree'])
        self.assertEqual(len(patched), before, 'the same milestones on the same tree are not executed again by the integration node')
        delivered = handoff(self.ledger, 'P1')
        self.assertEqual(delivered['state'], 'delivered')
        self.assertTrue(delivered['requires_owner_acceptance'])                # verified and delivered is not accepted
        self.assertEqual(plan.show(self.ledger, 'P1')['status'], 'approved')
        self.assertEqual(len(findings.list_findings(self.ledger, 'P1', open_only=True)), 0)
        self.assertEqual(review_dispatch.active_checks(self.ledger, 'P1'), [])
        with self.ledger.transaction() as conn:
            task = plan.anchor_events(self.ledger, conn, 'P1')['task_id']
            origin = review_dispatch.run_of_receipt(conn, task, failed_receipt)
            self.assertEqual((origin['run_id'], origin['outcome'], origin['door']), (first['check_run']['run_id'], 'published', 'engine.verify'))
            self.assertIsNone(review_dispatch.run_of_receipt(conn, task, self.store.blob(b'a report nobody issued')))
        return first, second


class CodingCase(LoopFixture):
    paths = ('a.txt',)
    bad = {'a.txt': b'wrong\n'}
    good = {'a.txt': b'candidate\n'}
    milestones = (milestone('Unit', argv=[sys.executable, '-c', 'from pathlib import Path; assert Path("a.txt").read_text()=="candidate\\n"; print("unit ok")']),
                  milestone('Smoke', argv=[sys.executable, '-c', 'from pathlib import Path; assert Path("a.txt").exists(); print("smoke ok")']))

    def prepare(self):
        pass

    def test_t7_coding_output_check_finding_repair_recheck_delivery(self):
        calls, real = [], command.run
        def counting(*args, **kwargs):
            calls.append(args[4]['id'])
            return real(*args, **kwargs)
        with patch.object(command, 'run', side_effect=counting):
            first, second = self.run_the_loop(calls, 'Unit')
        self.assertEqual(calls.count('Unit'), 2)                               # failed, then rechecked on the repaired tree
        self.assertEqual((self.root / 'a.txt').read_text(), 'candidate\n')     # delivered through the existing apply path


class DocumentDataCase(LoopFixture):
    paths = ('guide.md', 'input.csv', 'output.csv')
    bad = {'guide.md': b'# Wrong heading\n'}
    good = {'guide.md': b'# Summary\nThe verified deliverable.\n'}
    milestones = ({'id': 'Doc', 'title': 'Doc', 'covers': ['O1'], 'mode': 'until_pass', 'max_repairs': 3,
                   'verifier': {'type': 'doc', 'config': {'docs': [{'path': 'guide.md', 'headings': ['Summary']}]}}},
                  {'id': 'Data', 'title': 'Data', 'covers': ['O1'], 'verifier': {'type': 'data', 'config': json.loads(json.dumps(DATA))}})

    def prepare(self):
        (self.root / 'guide.md').write_text('# Before\n')
        for name in ('input.csv', 'output.csv'): (self.root / name).write_bytes(TABLE.encode())

    def test_t7_document_data_same_workflow_with_existing_adapters(self):
        calls, real = [], port.run
        def counting(*args, **kwargs):
            calls.append(args[4]['id'])
            return real(*args, **kwargs)
        with patch.object(port, 'run', side_effect=counting):
            first, second = self.run_the_loop(calls, 'Doc')
        self.assertEqual(calls.count('Doc'), 2)
        wrapper = json.loads(self.store.read_blob(second['observed']['checks'][0]['evidence']))
        self.assertEqual(wrapper['kind'], 'candidate-adapter-check')
        self.assertEqual((self.root / 'guide.md').read_text(), '# Summary\nThe verified deliverable.\n')


class IndependentBranchCase(LoopFixture):
    """A failed branch holds only what depends on it; the independent branch runs, verifies and keeps its verification through the repair."""
    paths = ('a.txt', 'b.txt')
    bad = {'a.txt': b'wrong\n', 'b.txt': b'b ok\n'}
    good = {'a.txt': b'candidate\n'}
    milestones = (milestone('UnitA', argv=[sys.executable, '-c', 'from pathlib import Path; assert Path("a.txt").read_text()=="candidate\\n"; print("a ok")']),
                  milestone('UnitB', argv=[sys.executable, '-c', 'from pathlib import Path; assert Path("b.txt").read_text()=="b ok\\n"; print("b ok")']))

    def prepare(self):
        (self.root / 'b.txt').write_text('two\n', encoding='utf-8')

    def nodes(self):
        def scoped(nid, path, check):
            row = node(nid, write=(path,)); row['read'] = [path]
            row['checks'] = [{'id': check, 'spec': 'Run the approved ' + check + ' verifier'}]
            return row
        final = node('I', ['C', 'X'], integration=True, write=()); final['read'] = list(self.paths)
        final['checks'] = [{'id': m['id'], 'spec': 'Run the approved ' + m['id'] + ' verifier'} for m in self.milestones]
        return [scoped('C', 'a.txt', 'UnitA'), scoped('X', 'b.txt', 'UnitB'), final]

    def execute(self, ledger, control, task, item, attempt):
        paths = list(item['write']) or list(self.paths)
        control.launched(attempt['id'], attempt['generation'], {'fixture': True})
        artifact = self.store.overlay(self.store.capture(self.root, paths), {p: self.overlays[p] for p in paths}, paths)
        receipt = self.store.blob(canonical({'kind': 'fixture-producer', 'artifact': artifact}).encode())
        control.finish(attempt['id'], attempt['generation'], {'artifact': artifact})
        return {'artifact': artifact, 'receipt': receipt}

    def test_a_failed_branch_holds_only_the_affected_part_and_the_other_branch_continues(self):
        checker = CandidateChecker(self.ledger, 'P1')
        self.assertEqual(self.step()['node'], 'C')
        self.assertEqual(self.verify('C', checker)['result'], 'fail')
        [finding] = findings.list_findings(self.ledger, 'P1', open_only=True)
        view = engine.state(self.ledger, 'P1')
        self.assertIn('C', view['finding_blockers']); self.assertIn('I', view['finding_blockers'])    # the failed node and what depends on it
        self.assertNotIn('X', view['finding_blockers'])                                                # not the independent branch
        self.assertEqual(self.step()['node'], 'X')
        passed = self.verify('X', checker)
        self.assertEqual(passed['result'], 'pass')
        self.assertEqual(engine.ready(self.ledger, 'P1'), [], 'the integration waits for the failed dependency')
        kept = engine.state(self.ledger, 'P1')['nodes']['X']
        self.assertEqual(kept['state'], 'verified')
        failed = engine.state(self.ledger, 'P1')['nodes']['C']['verification_receipt']
        repair_tasks.prepare(self.ledger, 'P1', 'C', 'C', reason='Fix the failed check', evidence=[failed])
        self.overlays.update(self.good)
        self.assertEqual(self.step()['node'], 'C')
        self.assertEqual(self.verify('C', checker)['findings']['closed'], [finding['id']])
        after = engine.state(self.ledger, 'P1')['nodes']['X']
        self.assertEqual((after['generation'], after['verification_receipt'], after['state']), (kept['generation'], kept['verification_receipt'], 'verified'),
                         'the repair of the other branch does not touch this one')
        self.assertEqual(self.step()['node'], 'I')
        self.assertEqual(self.verify('I', checker)['result'], 'pass')
        self.assertEqual(handoff(self.ledger, 'P1')['state'], 'delivered')


class RecheckClosure(Fixture):
    """The receipt a door issued closes a finding through 2.5-A's close_from_recheck; nothing else does."""

    def setUp(self):
        super().setUp()
        (self.root / 'guide.md').write_text('# Guide\n[reference](missing.txt)\n', encoding='utf-8')
        value = plan_json(milestones=[{'id': 'M1', 'title': 'Check guide', 'mode': 'until_pass', 'max_repairs': 3,
            'verifier': {'type': 'doc', 'config': {'docs': ['guide.md']}}, 'covers': ['O1']}], scope={'owned': ['guide.md']})
        plan.propose(self.ledger, 'P1', value, 'codex-fixture', workflow=True)
        plan.approve(self.ledger, 'P1', 'owner', 'fixture approval on a temporary ledger')

    def run_check(self):
        return verdict.run(self.ledger, 'P1', 'M1')['milestones'][0]['last_verdict']['receipt']

    def test_a_door_receipt_of_the_repaired_output_closes_and_nothing_else_does(self):
        red = self.run_check()
        [finding] = findings.list_findings(self.ledger, 'P1', open_only=True)
        same = findings.close_from_recheck(self.ledger, 'P1', finding['id'], run_receipt=red, request=review_dispatch.recheck_request(self.ledger, 'P1', finding, red))
        self.assertEqual(same['closed'], [])                                   # the failed receipt of the same output
        with self.assertRaisesRegex(LedgerError, 'No check run'):
            review_dispatch.recheck_request(self.ledger, 'P1', finding, Snapshots(self.ledger.state_root).blob(b'{"artifact_sha":"self-report"}'))
        (self.root / 'guide.md').write_text('# Guide\n[reference](a.txt)\n', encoding='utf-8')
        green = self.run_check()
        request = review_dispatch.recheck_request(self.ledger, 'P1', finding, green)
        self.assertEqual(findings.close_from_recheck(self.ledger, 'P1', finding['id'], run_receipt=green, request=request), {'closed': [finding['id']], 'refused': []})
        self.assertEqual(findings.list_findings(self.ledger, 'P1')[0]['status'], 'resolved')

    def test_the_door_request_names_the_reviewer_criteria_a_closure_compares(self):
        criteria = [{'id': 'R1', 'question': 'Is it right?'}]
        milestone_row = dict(reviewer_milestone(criteria=criteria), id='R')
        with self.ledger.transaction() as conn:
            state = plan.anchor_events(self.ledger, conn, 'P1')
            contract, sha = plan.load(self.ledger, state, state['approved']['revision'])
        request = review_dispatch._milestone_request(self.ledger, state['task_id'], 'P1', 1, sha, contract, milestone_row, command.artifact_sha(self.root))
        self.assertEqual(request['identity']['criteria'], content_hash(milestone_row['verifier']['config']['criteria']))
        self.assertEqual(request['identity']['target']['criteria_ids'], ['R1'])


class NodeRecheckClosure(CodingCase):
    test_t7_coding_output_check_finding_repair_recheck_delivery = None

    def test_the_engine_door_receipt_closes_a_node_finding_when_the_automatic_closure_did_not(self):
        checker = CandidateChecker(self.ledger, 'P1')
        self.step()
        self.assertEqual(self.verify('C', checker)['result'], 'fail')
        [finding] = findings.list_findings(self.ledger, 'P1', open_only=True)
        failed = engine.state(self.ledger, 'P1')['nodes']['C']['verification_receipt']
        repair_tasks.prepare(self.ledger, 'P1', 'C', 'C', reason='Fix the failed check', evidence=[failed])
        self.overlays.update(self.good)
        self.step()
        with patch.object(findings, 'record_node_verification', side_effect=LedgerError('closure hook unavailable')):
            self.assertEqual(self.verify('C', checker)['result'], 'pass')
        self.assertEqual(len(findings.list_findings(self.ledger, 'P1', open_only=True)), 1)
        green = engine.state(self.ledger, 'P1')['nodes']['C']['verification_receipt']
        request = review_dispatch.recheck_request(self.ledger, 'P1', finding, green)
        self.assertEqual(findings.close_from_recheck(self.ledger, 'P1', finding['id'], run_receipt=green, request=request), {'closed': [finding['id']], 'refused': []})
