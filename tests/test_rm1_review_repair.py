"""Public external-review intake, authentic milestone rechecks and scoped repair assignments."""
import contextlib
import io
import json
import sqlite3
from unittest.mock import patch

from onecrew.common_verification import CandidateChecker
from onecrew.ledger import LedgerError
from onecrew.v2 import cli, engine, findings, plan, report, tracking, verdict
from tests import test_sol6_recovery as workflow
from tests import v2_fixture as fixtures


class ReviewCaller:
    def call(self, *args, code=0):
        with contextlib.redirect_stdout(io.StringIO()) as output:
            result = cli.main(['--project', str(self.root), '--state-root', str(self.ledger.state_root),
                               'findings', *args])
        self.assertEqual(result, code, output.getvalue())
        return json.loads(output.getvalue())

    def document(self, shown, rows=None):
        last = shown['milestones'][0]['last_verdict']
        return {'id': 'review-7', 'reference': 'independent inspection, report 7', 'task_id': shown['anchor_task'],
                'revision': shown['revision'], 'result': 'changes_requested', 'milestone': 'M1',
                'receipt': last['receipt'], 'artifact_sha': last['artifact_sha'],
                'findings': rows or [{'criterion': 'M1', 'claim': 'Observed wrong output', 'paths': ['a.txt']}]}

    def ingest(self, doc, code=0):
        path = self.root.parent / 'review.json'
        path.write_text(json.dumps(doc), encoding='utf-8')
        return self.call('import-review', 'P1', '--file', str(path), code=code)


class Review(ReviewCaller, fixtures.Fixture):
    def setUp(self):
        super().setUp()
        contract = fixtures.plan_json(scope={'owned': ['a.txt', 'b.txt']},
                                      milestones=[fixtures.milestone('M1'), fixtures.milestone('M2')])
        plan.propose(self.ledger, 'P1', contract, 'codex', workflow=True)
        plan.approve(self.ledger, 'P1', 'owner', 'isolated test fixture')
        self.shown = verdict.run(self.ledger, 'P1', 'M1')
        self.doc = self.document(self.shown)

    def check(self):
        return verdict.run(self.ledger, 'P1', 'M1')['milestones'][0]['last_verdict']['receipt']

    def test_external_changes_requested_via_public_caller(self):
        imported = self.ingest(self.doc)
        self.assertEqual(imported['findings'], ['RF1'])
        [row] = self.call('list', 'P1', '--open-only')
        self.assertEqual(row['external_review']['verification'], self.doc['receipt'])
        self.assertEqual(row['scope']['write'], ['a.txt'])
        self.assertEqual(plan.show(self.ledger, 'P1')['milestones'][0]['state'], 'passed')

    def test_duplicate_import_preserves_source_and_open_findings(self):
        first = self.ingest(self.doc)
        self.assertTrue(self.ingest(self.doc)['duplicate'])
        self.assertIn('Conflicting', self.ingest(dict(self.doc, reference='a different report'), code=2)['error'])
        [row] = self.call('list', 'P1', '--open-only')
        self.assertEqual(row['source']['receipt'], first['receipt'])
        self.assertEqual(row['external_review']['reference'], self.doc['reference'])

    def test_open_findings_block_acceptance_on_report_and_page(self):
        self.ingest(self.doc)
        last = verdict.run(self.ledger, 'P1', 'M2')['milestones'][-1]['last_verdict']
        with self.assertRaisesRegex(LedgerError, 'unresolved findings'):
            plan.accept(self.ledger, 'P1', 'owner', 'isolated acceptance check', last['artifact_sha'])
        self.assertIn('RF1', report.render_report(self.ledger.state_root, 'P1'))
        page = tracking.detail(self.ledger.state_root, 'P1')
        self.assertFalse(page['acceptance']['ready'])
        self.assertIn('RF1', page['situation']['reason'])

    def test_unrelated_pass_cannot_close_finding(self):
        self.ingest(self.doc)
        other = verdict.run(self.ledger, 'P1', 'M2')['milestones'][-1]['last_verdict']['receipt']
        self.assertTrue(self.call('recheck', 'P1', 'RF1', '--receipt', other, code=2)['refused'])
        self.assertEqual(plan.show(self.ledger, 'P1')['open_findings'], ['RF1'])

    def test_wrong_scope_or_stale_recheck_leaves_finding_open(self):
        self.ingest(self.doc)
        (self.root / 'b.txt').write_text('other change')
        wrong = self.check()
        self.assertTrue(self.call('recheck', 'P1', 'RF1', '--receipt', wrong, code=2)['refused'])
        (self.root / 'a.txt').write_text('repair')
        repaired = self.check()
        (self.root / 'a.txt').write_text('changed after the recheck')
        self.assertTrue(self.call('recheck', 'P1', 'RF1', '--receipt', repaired, code=2)['refused'])
        self.assertEqual(len(self.call('list', 'P1', '--open-only')), 1)

    def test_project_comparison_for_recheck_releases_the_ledger_reader(self):
        from onecrew.v2.verifiers import artifact
        self.ingest(self.doc)
        (self.root / 'a.txt').write_text('repair')
        receipt = self.check()
        original = artifact.identity
        def compare(project):
            connection = sqlite3.connect(self.ledger.path, timeout=0.1)
            try:
                connection.execute('BEGIN EXCLUSIVE')
                connection.rollback()
            finally:
                connection.close()
            return original(project)
        with patch.object(artifact, 'identity', side_effect=compare) as observed:
            self.assertEqual(self.call('recheck', 'P1', 'RF1', '--receipt', receipt)['closed'], ['RF1'])
        self.assertTrue(observed.called)

    def test_matching_recheck_closes_only_repaired_finding(self):
        self.doc['findings'].append(dict(self.doc['findings'][0], paths=['b.txt']))
        self.ingest(self.doc)
        (self.root / 'a.txt').write_text('repair')
        receipt = self.check()
        self.assertEqual(self.call('recheck', 'P1', 'RF1', '--receipt', receipt)['closed'], ['RF1'])
        self.assertTrue(self.call('recheck', 'P1', 'RF2', '--receipt', receipt, code=2)['refused'])
        self.assertEqual(plan.show(self.ledger, 'P1')['open_findings'], ['RF2'])


class Assigned(ReviewCaller, workflow.Chain):
    def external(self):
        self.deliver()
        shown = self.final(red=False)
        doc = self.document(shown)
        outside = dict(doc, findings=[dict(doc['findings'][0], paths=['outside.txt'])])
        self.assertIn('outside the approved scope', self.ingest(outside, code=2)['error'])
        return self.ingest(doc)['receipt']

    def test_assigned_repair_can_edit_only_granted_scope(self):
        source = self.external()
        original = self.gens()
        with self.assertRaises(LedgerError):
            self.repair(target='I', failed='C', receipt=source)
        self.assertEqual(self.gens(), original)
        repair = self.repair(receipt=source)
        self.assertEqual(repair['source_receipt'], source)
        self.assertEqual(repair['node_scopes']['C']['write'], ['a.txt'])
        self.overlays.update(self.good)
        self.deliver()
        receipt = self.receipt_of(self.final(red=False))
        self.assertEqual(self.call('recheck', 'P1', 'RF1', '--receipt', receipt)['closed'], ['RF1'])
        [row] = findings.list_findings(self.ledger, 'P1')
        self.assertEqual(row['resolution']['repair']['repair'], repair['receipt'])

    def test_failed_recheck_keeps_history_and_respects_repair_budget(self):
        source = self.external()
        repair = self.repair(receipt=source)
        self.assertGreater(repair['cost']['calls'], 0)
        self.overlays = {'a.txt': workflow.BROKEN}
        self.step()
        observed = self.verify('C', CandidateChecker(self.ledger, 'P1'))
        self.assertEqual(observed['result'], 'fail')
        opened = findings.list_findings(self.ledger, 'P1', open_only=True)
        self.assertEqual(opened[0]['source']['receipt'], source)
        self.assertGreater(len(opened), 1)
        with patch.object(workflow.internal_plan, 'ceilings', return_value={'remaining_calls': 0, 'remaining_seconds': 0}):
            with self.assertRaisesRegex(LedgerError, 'remaining|root has'):
                self.repair()
        self.assertEqual(self.kinds().count('workflow.repair_prepared'), 1)
