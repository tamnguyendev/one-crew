"""Authentic adapter receipts use the existing register and latest-proof closure."""
import json
from unittest.mock import patch

from onecrew.ledger import LedgerError
from onecrew.snapshots import Snapshots
from onecrew.v2 import findings, plan, verdict
from onecrew.v2.verifiers import doc
from tests.test_v2_l1 import Fixture, plan_json


class AdapterFindings(Fixture):
    def setUp(self):
        super().setUp()
        (self.root / 'guide.md').write_text('# Guide\n[reference](missing.txt)\n', encoding='utf-8')
        value = plan_json(milestones=[{'id': 'M1', 'title': 'Check guide', 'mode': 'until_pass', 'max_repairs': 3,
            'verifier': {'type': 'doc', 'config': {'docs': ['guide.md']}}, 'covers': ['O1']}],
            scope={'owned': ['guide.md']})
        plan.propose(self.ledger, 'P1', value, 'codex-fixture', workflow=True)
        plan.approve(self.ledger, 'P1', 'owner', 'fixture approval on temporary ledger')

    def run_check(self):
        out = verdict.run(self.ledger, 'P1', 'M1')
        last = out['milestones'][0]['last_verdict']
        return last['receipt'], json.loads(Snapshots(self.ledger.state_root).read_blob(last['receipt']))

    def repair(self, suffix=''):
        (self.root / 'guide.md').write_text('# Guide\n[reference](a.txt)\n' + suffix, encoding='utf-8')

    def test_adapter_failure_registers_and_only_explicit_latest_pass_closes(self):
        old, failed = self.run_check()
        rows = findings.list_findings(self.ledger, 'P1')
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['criterion'], 'links')
        self.assertEqual(rows[0]['source']['receipt'], old)
        self.assertEqual(rows[0]['scope']['write'], ['guide.md'])
        self.repair()
        green, passed = self.run_check()
        self.assertEqual(len(findings.list_findings(self.ledger, 'P1', open_only=True)), 1)
        with self.assertRaisesRegex(LedgerError, 'unresolved findings'):
            plan.accept(self.ledger, 'P1', 'owner', 'fixture acceptance', passed['artifact_sha'])
        result = findings.resolve(self.ledger, 'P1', rows[0]['id'], green, reason='link rechecked', artifact_sha=passed['artifact_sha'])
        self.assertEqual(result['closed'], [rows[0]['id']])
        self.assertEqual(plan.accept(self.ledger, 'P1', 'owner', 'fixture acceptance', passed['artifact_sha'])['status'], 'accepted')

    def test_duplicate_failure_preserves_first_source_and_supersedes_intermediate_pass(self):
        first, _ = self.run_check()
        self.repair()
        green, passed = self.run_check()
        (self.root / 'guide.md').write_text('# Guide\n[reference](missing.txt)\nregression\n', encoding='utf-8')
        latest, _ = self.run_check()
        rows = findings.list_findings(self.ledger, 'P1')
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['source']['receipt'], first)
        self.assertEqual(rows[0]['last_observed']['receipt'], latest)
        result = findings.resolve(self.ledger, 'P1', rows[0]['id'], green, reason='stale pass counterexample', artifact_sha=passed['artifact_sha'])
        self.assertEqual(result['closed'], [])
        self.assertIn('superseded', result['refused'][0])

    def test_pass_of_another_check_cannot_close_and_forged_wrong_artifact_generation_refused(self):
        self.run_check()
        ident = findings.list_findings(self.ledger, 'P1')[0]['id']
        self.repair()
        # Fake adapter output exercises only the generic boundary: an authentic
        # receipt with a pass of an unrelated check is insufficient for closure.
        with patch.object(doc, 'run', return_value={'checks': [{'id': 'other', 'ok': True, 'checked': 1, 'problems': []}],
                                                    'findings': [], 'unverified': []}):
            green, body = self.run_check()
        result = findings.resolve(self.ledger, 'P1', ident, green, reason='wrong check', artifact_sha=body['artifact_sha'])
        self.assertIn('does not pass this finding check', result['refused'][0])
        for artifact_sha, generation in (('f' * 40, 1), (body['artifact_sha'], 2)):
            result = findings.resolve(self.ledger, 'P1', ident, green, reason='mismatched proof', artifact_sha=artifact_sha, generation=generation)
            self.assertEqual(result['closed'], [])
        forged = dict(body, checks=[{'id': 'links', 'ok': True, 'checked': 1, 'problems': []}])
        key = Snapshots(self.ledger.state_root).blob(json.dumps(forged).encode())
        result = findings.resolve(self.ledger, 'P1', ident, key, reason='forged report', artifact_sha=body['artifact_sha'])
        self.assertEqual(result['closed'], [])
        self.assertEqual(len(findings.list_findings(self.ledger, 'P1', open_only=True)), 1)

    def test_register_failure_rolls_back_record_and_receipt_reconciles_without_adapter_rerun(self):
        with patch.object(findings, '_save', side_effect=OSError('publication failure')):
            with self.assertRaisesRegex(OSError, 'publication failure'):
                self.run_check()
        events = self.events()
        self.assertFalse(any(k == 'verdict.recorded' for k, _ in events))
        receipt = next(p['receipt'] for k, p in reversed(events) if k == 'verdict.receipt_issued')
        body = json.loads(Snapshots(self.ledger.state_root).read_blob(receipt))
        with patch.object(doc, 'run', side_effect=AssertionError('must reconcile issued evidence')):
            verdict.record(self.ledger, 'P1', 'M1', 'fail', 'doc', receipt, body['artifact_sha'])
        self.assertEqual(len(findings.list_findings(self.ledger, 'P1')), 1)
        duplicate = findings.record_verification(self.ledger, 'P1', 'M1', receipt)
        self.assertEqual(duplicate['opened'], [])
        self.assertEqual(duplicate['merged'], ['RF1'])
