"""W17/T28 and register-only T07a, using real temporary ledger/blobs.

Reviewer answers are injected receipts, never external model calls. W18 branch
holds, W36 executor fencing and automatic verifier wiring are separate slices.
"""
import contextlib
import copy
import io
import json
from unittest.mock import patch

from onecrew import finding_core, review_evidence
from onecrew.ledger import LedgerError, canonical
from onecrew.snapshots import Snapshots
from onecrew.v2 import contract as contracts, findings, plan as plans
from tests.test_v2_l1 import Fixture, plan_json


CRITERIA = [{'id': 'R1', 'question': 'Does a.txt contain the required line?'},
            {'id': 'R2', 'question': 'Does a.txt preserve its first line?'}]


def contract():
    return plan_json(milestones=[{'id': 'M1', 'title': 'Review a.txt', 'covers': ['O1'],
        'verifier': {'type': 'reviewer', 'config': {'provider': 'claude', 'model': 'claude-haiku-5-5',
            'criteria': copy.deepcopy(CRITERIA), 'max_minutes': 5}}}])


class FindingTests(Fixture):
    def setUp(self):
        super().setUp()
        plans.propose(self.ledger, 'P1', contract(), 'claude', workflow=True)
        with self.ledger.transaction() as conn:
            self.task = plans.derive(self.ledger, conn, 'P1')['task_id']
        self.store = Snapshots(self.ledger.state_root)
        self.artifact = self.tree()

    def receipt(self, result='fail', *, revision=1, generation=1, issued=True, recorded=True, artifact=None, **changes):
        value, sha = contracts.read_revision(self.ledger, 'P1', revision)
        body = {'kind': 'reviewer-receipt', 'plan': 'P1', 'revision': revision, 'plan_sha': sha, 'milestone': 'M1',
            'generation': generation, 'config': value['milestones'][0]['verifier']['config'],
            'artifact_sha': artifact or self.artifact, 'artifact_sha_after': artifact or self.artifact,
            'criteria': [{'id': 'R1', 'verdict': result, 'evidence': [{'file': 'a.txt', 'line': 1, 'note': 'required line absent'}]},
                         {'id': 'R2', 'verdict': 'pass', 'evidence': []}],
            'outside_criteria': ['Optional formatting preference; no acceptance criterion.'],
            'problems': [], 'error': None, 'timed_out': False, 'calls': 1}
        body.update(changes)
        blob = self.store.blob(canonical(body).encode('utf-8'))
        with self.ledger.transaction(write=True) as conn:
            base = {'plan': 'P1', 'revision': revision, 'milestone': 'M1', 'receipt': blob, 'generation': generation}
            if issued:
                plans.emit(self.ledger, conn, self.task, 'verdict.receipt_issued', base)
            if recorded:
                plans.emit(self.ledger, conn, self.task, 'verdict.recorded', dict(base, result=result, artifact_sha=body['artifact_sha']))
        return blob

    def open(self, receipt=None, **kwargs):
        return findings.record_review(self.ledger, 'P1', 'M1', receipt or self.receipt(), read=['a.txt'], write=['a.txt'], **kwargs)

    def rows(self, **kwargs):
        return findings.list_findings(self.ledger, 'P1', **kwargs)

    def close(self, receipt=None, **kwargs):
        return findings.resolve(self.ledger, 'P1', 'RF1', receipt or self.receipt('pass'), reason='R1 verified on the repaired artifact',
                                artifact_sha=kwargs.pop('artifact_sha', self.artifact), **kwargs)

    def test_failed_criterion_retains_context_and_notes_stay_in_receipt(self):
        receipt = self.receipt()
        self.assertEqual(self.open(receipt)['opened'], ['RF1'])
        row = self.rows()[0]
        self.assertEqual((row['plan'], row['revision'], row['node'], row['criterion']), ('P1', 1, 'M1', 'R1'))
        self.assertEqual(row['artifact_sha'], self.artifact)
        self.assertEqual(row['severity'], 'major')
        self.assertEqual(row['scope'], {'read': ['a.txt'], 'write': ['a.txt']})
        self.assertEqual(row['source']['receipt'], receipt)
        self.assertEqual(len(self.rows()), 1)
        self.assertTrue(json.loads(self.store.read_blob(receipt))['outside_criteria'])
        self.assertEqual(findings.reviewer_context(self.ledger, 'P1')[0]['id'], 'RF1')

    def test_dedup_stable_claims_and_scope_update(self):
        receipt = self.receipt()
        self.open(receipt)
        result = self.open(receipt)
        self.assertEqual(result, {'opened': [], 'merged': ['RF1'], 'closed': []})
        findings.update(self.ledger, 'P1', 'RF1', reason='triaged severity', severity='critical', read=['b.txt'])
        self.assertEqual(self.rows()[0]['scope']['read'], ['b.txt'])
        self.assertEqual(self.rows()[0]['severity'], 'critical')
        self.assertEqual(len(self.rows()), 1)

    def test_t28_code_change_and_generic_accept_do_not_close_or_call_closure(self):
        self.open()
        (self.root / 'a.txt').write_text('repaired\n')
        self.git('add', 'a.txt'); self.git('commit', '-q', '-m', 'repair')
        self.artifact = self.tree()
        with patch.object(finding_core, 'close_finding', wraps=finding_core.close_finding) as close:
            self.assertEqual(self.rows()[0]['status'], 'open')
            self.open(self.receipt('pass'))
            self.assertEqual(self.rows()[0]['status'], 'open')
            with self.ledger.transaction(write=True) as conn:
                plans.emit(self.ledger, conn, self.task, 'plan.accepted', {'plan': 'P1', 'revision': 1, 'artifact_sha': self.artifact})
            self.assertEqual(self.rows()[0]['status'], 'open')
            self.assertEqual(close.call_count, 0)

    def test_t28_pass_evidence_closes_via_common_register_and_survives_restart(self):
        self.open()
        (self.root / 'a.txt').write_text('repaired\n')
        self.artifact = self.tree()
        receipt = self.receipt('pass')
        with patch.object(finding_core, 'close_finding', wraps=finding_core.close_finding) as close:
            self.assertEqual(self.close(receipt)['closed'], ['RF1'])
            self.assertEqual(close.call_count, 1)
        from onecrew.ledger import Ledger
        fresh = Ledger(self.root, self.ledger.state_root)
        row = findings.list_findings(fresh, 'P1')[0]
        self.assertEqual(row['status'], 'resolved')
        self.assertEqual(row['resolution']['evidence'], [receipt])
        self.assertEqual(row['resolution']['artifact_sha'], self.artifact)

    def test_out_of_order_closure_is_durable_and_does_not_close_later_open(self):
        result = self.close()
        self.assertTrue(result['refused'])
        self.open()
        self.assertEqual(self.rows()[0]['status'], 'open')
        with self.ledger.transaction() as conn:
            events = [json.loads(r[0]) for r in conn.execute('SELECT payload FROM events WHERE kind=? AND task_id=?', (findings.KIND, self.task))]
        self.assertTrue(events[0]['refused'])

    def test_rejection_needs_authentic_passing_evidence(self):
        fail = self.receipt()
        self.open(fail)
        self.assertTrue(self.close(fail, reject=True)['refused'])
        self.assertTrue(self.close('0' * 64, reject=True)['refused'])
        self.assertEqual(self.rows()[0]['status'], 'open')
        receipt = self.receipt('pass')
        self.assertEqual(self.close(receipt, reject=True)['closed'], ['RF1'])
        self.assertEqual(self.rows()[0]['status'], 'rejected')
        self.open(fail)  # replay of the old delivery cannot reopen a settled finding
        self.assertEqual([r['status'] for r in self.rows()], ['rejected'])

    def test_forged_unissued_or_unrecorded_receipts_are_not_evidence(self):
        self.open()
        for kwargs in ({'issued': False, 'nonce': 'no issue'}, {'recorded': False, 'nonce': 'no verdict'}):
            with self.subTest(kwargs=kwargs):
                receipt = self.receipt('pass', **kwargs)
                self.assertTrue(self.close(receipt)['refused'])
                self.assertEqual(self.rows()[0]['status'], 'open')

    def test_wrong_generation_artifact_plan_and_criterion_do_not_close(self):
        self.open()
        for changes, close_args in [({'generation': 2}, {}), ({}, {'artifact_sha': 'a' * 40}),
                                    ({'plan': 'other'}, {}),
                                    ({'criteria': [{'id': 'R2', 'verdict': 'pass', 'evidence': []}]}, {})]:
            with self.subTest(changes=changes):
                self.assertTrue(self.close(self.receipt('pass', **changes), **close_args)['refused'])
                self.assertEqual(self.rows()[0]['status'], 'open')

    def revise(self, *, change=False):
        value, _ = contracts.read_revision(self.ledger, 'P1', 1)
        if change:
            value['milestones'][0]['verifier']['config']['criteria'][0]['question'] += ' And preserve whitespace?'
        value['title'] = 'Revision two'
        sha = contracts.write_revision(self.ledger, 'P1', 2, value)
        with self.ledger.transaction(write=True) as conn:
            plans.emit(self.ledger, conn, self.task, 'plan.amended', {'plan': 'P1', 'revision': 2, 'sha': sha})

    def test_next_revision_receives_open_finding_and_old_receipt_cannot_close(self):
        self.open()
        old = self.receipt('pass')
        self.revise()
        self.assertEqual(findings.reviewer_context(self.ledger, 'P1')[0]['criterion'], 'R1')
        self.assertTrue(self.close(old)['refused'])
        self.assertEqual(self.close(self.receipt('pass', revision=2))['closed'], ['RF1'])

    def test_old_generation_pass_cannot_close_after_new_generation_is_recorded(self):
        self.open()
        old = self.receipt('pass')
        current = self.receipt('pass', generation=2)
        self.assertTrue(self.close(old)['refused'])
        self.assertEqual(self.rows()[0]['status'], 'open')
        self.assertEqual(self.close(current, generation=2)['closed'], ['RF1'])

    def test_green_receipt_from_before_the_finding_cannot_close_it(self):
        old = self.receipt('pass')
        self.open()
        self.assertTrue(self.close(old)['refused'])
        self.assertEqual(self.rows()[0]['status'], 'open')

    def test_changed_criterion_is_stale_and_not_in_next_reviewer_context(self):
        self.open()
        self.revise(change=True)
        self.assertEqual(self.rows()[0]['status'], 'stale')
        self.assertEqual(findings.reviewer_context(self.ledger, 'P1'), [])
        self.open(self.receipt(revision=2))
        self.assertEqual([r['status'] for r in self.rows()], ['stale', 'open'])

    def test_legacy_root_and_other_project_are_refused(self):
        receipt = self.receipt()
        with self.ledger.transaction(write=True) as conn:
            conn.execute('UPDATE tasks SET request_key=? WHERE id=?', ('plan:P1', self.task))
        with self.assertRaisesRegex(LedgerError, 'plan-ns'):
            self.open(receipt)
        with self.assertRaises(LedgerError):
            findings.resolve_root(self.ledger, 'different', self.task)

    def test_list_and_reviewer_context_write_no_events(self):
        self.open()
        before = self.ledger.path.read_bytes()
        self.rows(); findings.reviewer_context(self.ledger, 'P1')
        self.assertEqual(self.ledger.path.read_bytes(), before)
        self.assertEqual(findings.list_findings(self.ledger, 'plan-ns:P1')[0]['id'], 'RF1')

    def test_cli_list_and_resolve_are_reviewable(self):
        self.open()
        argv = ['--project', str(self.root), '--state-root', str(self.ledger.state_root)]
        with contextlib.redirect_stdout(io.StringIO()) as out:
            code = findings.main(argv + ['list', 'P1', '--open-only'])
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out.getvalue())[0]['id'], 'RF1')


class V1SharedRegisterTests(Fixture):
    def test_v1_and_v2_use_same_dedup_and_closure_core(self):
        state = {'receipts': [{'index': 0, 'action': 'run'}], 'work': {'verification': {'candidate': 'a' * 40}}}
        with patch.object(finding_core, 'append_finding', wraps=finding_core.append_finding) as append:
            review_evidence.record_round(state, {'findings': ['r0: bad line']}, shown=[0], round_no=1)
            review_evidence.record_round(state, {'findings': ['r0: bad  line']}, shown=[0], round_no=1)
            self.assertEqual(append.call_count, 1)
        with patch.object(finding_core, 'close_finding', wraps=finding_core.close_finding) as close:
            review_evidence.record_round(state, {'accepted': True}, shown=[0], round_no=2)
            self.assertEqual(close.call_count, 0)
            review_evidence.record_round(state, {'resolved': ['RF1:0: test passed']}, shown=[0], round_no=2)
            self.assertEqual(close.call_count, 1)
        self.assertEqual(state['review_register']['findings'][0]['status'], 'resolved')
