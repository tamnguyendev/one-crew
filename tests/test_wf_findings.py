"""W17/T28 and register-only T07a, using real temporary ledger/blobs.

Reviewer answers are injected receipts, never external model calls. W18 branch
holds, W36 executor fencing and automatic verifier wiring are separate slices.
"""
import contextlib
import copy
import io
import json
import os
from unittest.mock import patch

from onecrew import finding_core, review_evidence
from onecrew.ledger import LedgerError, canonical
from onecrew.snapshots import Snapshots
from onecrew.v2 import contract as contracts, findings, plan as plans, review_policy
from tests.test_v2_l1 import Fixture, plan_json


CRITERIA = [{'id': 'R1', 'question': 'Does a.txt contain the required line? fail if it does not.'},
            {'id': 'R2', 'question': 'Does a.txt preserve its first line? fail if it does not.'}]


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
        repaired = 'b' * 40       # the closure rule (2.5-A): a recheck speaks about the repaired output, not the candidate that failed
        self.assertEqual(self.close(self.receipt('pass', revision=2, artifact=repaired), artifact_sha=repaired)['closed'], ['RF1'])

    def test_old_generation_pass_cannot_close_after_new_generation_is_recorded(self):
        self.open()
        old = self.receipt('pass')
        repaired = 'b' * 40       # the closure rule (2.5-A): a recheck speaks about the repaired output, not the candidate that failed
        current = self.receipt('pass', generation=2, artifact=repaired)
        self.assertTrue(self.close(old)['refused'])
        self.assertEqual(self.rows()[0]['status'], 'open')
        self.assertEqual(self.close(current, generation=2, artifact_sha=repaired)['closed'], ['RF1'])

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


class SkipLinkTests(Fixture):
    """Round 7 F4 (T35c [E29]): "finding F was missed by SKIP decision S" as a product record, on a temporary ledger.

    The optional review R-opt is SKIPped through the real review_policy.decide (the HD-20 record); the defect is a finding opened through
    record_review; the link is written by findings.link_skip (a decision.recorded through decisions.record) and read back by
    findings.skip_view; the measure is wfkit.pilot_tools.skip_leak_of / aggregate_facts (what the aggregate report uses). Synthetic only.
    """
    REASON = 'R-opt checks the required line of a.txt, which R1 later found missing'

    def setUp(self):
        super().setUp()
        self.store = Snapshots(self.ledger.state_root)
        self.artifact = self.tree()
        self.task = self.root_on('P1')
        self.skip = self.decide('P1')
        self.assertEqual(self.skip['action'], 'SKIP')
        self.key = self.skip['record']['key']
        self.assertEqual(findings.record_review(self.ledger, 'P1', 'M1', self.receipt('P1'), read=['a.txt'])['opened'], ['RF1'])

    def root_on(self, name):
        value = dict(contract(), review_policy={'depth': 'light', 'optional_reviews': ['R-opt']})
        plans.propose(self.ledger, name, value, 'claude', workflow=True)
        plans.approve(self.ledger, name, 'owner', 'synthetic: owner said yes')
        with self.ledger.transaction() as conn:
            return plans.derive(self.ledger, conn, name)['task_id']

    def decide(self, name, note='synthetic: optional review skipped'):
        return review_policy.decide(self.ledger, name, 'R-opt', artifact_sha=self.artifact, evidence=(note,))

    def receipt(self, name, *, revision=1, artifact=None, note='required line absent'):
        value, sha = contracts.read_revision(self.ledger, name, revision)
        artifact = artifact or self.artifact
        body = {'kind': 'reviewer-receipt', 'plan': name, 'revision': revision, 'plan_sha': sha, 'milestone': 'M1', 'generation': 1,
                'config': value['milestones'][0]['verifier']['config'], 'artifact_sha': artifact, 'artifact_sha_after': artifact,
                'criteria': [{'id': 'R1', 'verdict': 'fail', 'evidence': [{'file': 'a.txt', 'line': 1, 'note': note}]},
                             {'id': 'R2', 'verdict': 'pass', 'evidence': []}],
                'outside_criteria': [], 'problems': [], 'error': None, 'timed_out': False, 'calls': 1}
        blob = self.store.blob(canonical(body).encode('utf-8'))
        with self.ledger.transaction(write=True) as conn:
            task = plans.derive(self.ledger, conn, name)['task_id']
            base = {'plan': name, 'revision': revision, 'milestone': 'M1', 'receipt': blob, 'generation': 1}
            plans.emit(self.ledger, conn, task, 'verdict.receipt_issued', base)
            plans.emit(self.ledger, conn, task, 'verdict.recorded', dict(base, result='fail', artifact_sha=artifact))
        return blob

    def link(self, ident='RF1', key=None, name='P1', review='R-opt', **kw):
        return findings.link_skip(self.ledger, name, ident, key or self.key, review=review, reason=self.REASON, **kw)

    def measure(self, name='P1'):
        from wfkit import pilot_tools
        return pilot_tools.skip_leak_of(self.ledger, name)

    def link_events(self, name='P1'):
        return [p for k, p in self.events(name) if k == 'decision.recorded' and p['subject']['component'] == findings.SKIP_LINK]

    def test_measure_reads_the_link_record_and_points_at_the_skip_and_finding_ids(self):
        before = self.measure()
        self.assertEqual((before['skip_records'], before['skip_links'], before['skip_leak']['value']), ([self.key], [], 0))  # never automatic
        out = self.link()
        self.assertFalse(out['duplicate'])
        got = self.measure()
        self.assertEqual(got['skip_leak']['value'], 1)
        self.assertEqual([(x['finding'], x['skip_record']) for x in got['skip_links']], [('RF1', self.key)])
        self.assertEqual((got['skip_links'][0]['root'], got['skip_links'][0]['revision'], got['skip_links'][0]['artifact_sha']),
                         (self.task, 1, self.artifact))
        self.assertEqual(got['skip_records'], [self.key])                                  # the denominator: one SKIP in this root
        stored = self.link_events()
        self.assertEqual(len(stored), 1)
        self.assertEqual((stored[0]['validity']['finding'], stored[0]['validity']['skip_record'], stored[0]['scope']), ('RF1', self.key, 'R-opt'))
        self.assertIn(f'skip-record:{self.key}', stored[0]['evidence'])
        # the same measure inside the aggregate pipeline (aggregate_facts on the measured root)
        from onecrew.v2 import metrics
        from wfkit import pilot_tools
        root = next(r for r in metrics.measure_all(self.ledger)['roots'] if 'P1' in (r['plan'], r['selector']))
        facts = pilot_tools.aggregate_facts(self.ledger, root)
        self.assertEqual((facts['skip_leak']['value'], facts['skip_records']), (1, [self.key]))
        self.assertEqual([(x['finding'], x['skip_record']) for x in facts['skip_links']], [('RF1', self.key)])

    def test_counter_example_a_measure_that_does_not_read_the_hd20_record_goes_red(self):
        self.link()
        with patch.object(findings, '_skip_records', return_value={}):                     # the HD-20 reader patched away
            got = self.measure()
        self.assertNotEqual(got['skip_leak']['value'], 1)
        self.assertEqual(got['skip_links'], [])
        self.assertIn('no review_policy SKIP (HD-20) record', got['skip_links_invalid'][0]['reason'])
        # a link record written past link_skip that names a REVIEW decision (not a SKIP) is never counted
        review = review_policy.decide(self.ledger, 'P1', 'M1', artifact_sha=self.artifact, evidence=('synthetic: mandatory',))
        self.assertEqual(review['action'], 'REVIEW')
        from onecrew.v2 import decisions
        with self.ledger.transaction() as conn:
            sha = plans.derive(self.ledger, conn, 'P1')['approved']['sha']
        forged = {'link': 'missed_by_skip', 'finding': 'RF1', 'skip_record': review['record']['key'], 'review': 'M1', 'root': self.task,
                  'revision': 1, 'contract_sha': sha, 'artifact_sha': self.artifact}
        decisions.record(self.ledger, self.task, subject={'component': findings.SKIP_LINK, 'model': 'rules'},
                         authority={'grant_id': 'approved-contract:' + sha, 'revision': '1'}, evidence=['synthetic: forged link'],
                         basis='forged past link_skip', scope='M1', validity=forged, key='skip-link-forged')
        got = self.measure()
        self.assertEqual([(x['finding'], x['skip_record']) for x in got['skip_links']], [('RF1', self.key)])
        self.assertEqual(got['skip_leak']['value'], 1)
        self.assertEqual([x['record'] for x in got['skip_links_invalid']], ['skip-link-forged'])

    def test_wrong_root_is_not_linked(self):
        self.root_on('P2')
        self.assertEqual(findings.record_review(self.ledger, 'P2', 'M1', self.receipt('P2'), read=['a.txt'])['opened'], ['RF1'])
        with self.assertRaisesRegex(LedgerError, 'no review_policy SKIP \\(HD-20\\) record with this id on this root'):
            self.link(name='P2')                                                       # P1's SKIP, P2's finding RF1
        self.assertEqual(self.measure('P2')['skip_leak']['value'], 0)
        self.assertEqual(self.link_events('P2'), [])

    def test_wrong_revision_is_not_linked(self):
        value, _ = contracts.read_revision(self.ledger, 'P1', 1)
        plans.amend(self.ledger, 'P1', dict(value, title='Sample, again'), 'synthetic: second revision', 'claude')
        plans.approve(self.ledger, 'P1', 'owner', 'synthetic: owner said yes again')
        opened = findings.record_review(self.ledger, 'P1', 'M1', self.receipt('P1', revision=2, note='second line absent'), read=['a.txt'])['opened']
        self.assertEqual(opened, ['RF2'])
        with self.assertRaisesRegex(LedgerError, 'revision 2, the SKIP applied to revision 1'):
            self.link('RF2')
        self.assertEqual(self.link_events(), [])

    def test_wrong_artifact_is_not_linked(self):
        opened = findings.record_review(self.ledger, 'P1', 'M1', self.receipt('P1', artifact='e' * 40, note='other tree'), read=['a.txt'])['opened']
        self.assertEqual(opened, ['RF2'])
        with self.assertRaisesRegex(LedgerError, 'another artifact than the one the SKIP applied to'):
            self.link('RF2')
        self.assertEqual(self.link_events(), [])

    def test_unrelated_finding_is_not_linked(self):
        # RF1 was opened BEFORE this later SKIP; and R-opt is the only review the SKIP covered; and RF9 does not exist
        later = self.decide('P1', note='synthetic: a later SKIP of the same review')
        self.assertNotEqual(later['record']['key'], self.key)
        with self.assertRaisesRegex(LedgerError, 'not opened after the SKIP'):
            self.link(key=later['record']['key'])
        with self.assertRaisesRegex(LedgerError, 'the SKIP covered optional review R-opt, not M1'):
            self.link(review='M1')
        with self.assertRaisesRegex(LedgerError, 'no finding with this id'):
            self.link('RF9')
        self.assertEqual(self.link_events(), [])
        self.assertEqual(self.measure()['skip_leak']['value'], 0)

    def test_duplicate_link_is_recorded_once_and_a_second_skip_is_refused(self):
        self.link()
        self.assertTrue(self.link()['duplicate'])
        self.assertEqual(len(self.link_events()), 1)
        later = self.decide('P1', note='synthetic: a later SKIP of the same review')
        opened = findings.record_review(self.ledger, 'P1', 'M1', self.receipt('P1', note='third line absent'), read=['a.txt'])['opened']
        self.assertEqual(opened, ['RF2'])
        self.link('RF2', key=later['record']['key'])
        with self.assertRaisesRegex(LedgerError, 'already attributed to SKIP'):
            self.link('RF2')                                                           # RF2 came after both SKIPs: counted once
        got = self.measure()
        self.assertEqual(got['skip_leak']['value'], 2)
        self.assertEqual(sorted((x['finding'], x['skip_record']) for x in got['skip_links']),
                         sorted([('RF1', self.key), ('RF2', later['record']['key'])]))
        self.assertEqual(len(got['skip_records']), 2)

    def test_validation_and_write_of_a_link_are_one_transaction(self):
        """Round 7 (integration): link_skip validates and records in ONE write transaction (the round-5 atomicity rule), so a concurrent
        second attribution of the same finding cannot pass validation on a stale read. Structural check + a barrier race."""
        import threading
        from unittest.mock import patch
        from onecrew.v2 import decisions
        seen = []
        real = decisions.record

        def spy(ledger, task_id, **kw):
            seen.append((kw.get('conn') is not None, bool(getattr(kw.get('conn'), 'in_transaction', False))))
            return real(ledger, task_id, **kw)
        with patch.object(decisions, 'record', spy):
            self.link()
        self.assertEqual(seen, [(True, True)], 'the link record must be written on the open validating transaction')
        later = self.decide('P1', note='synthetic: a later SKIP of the same review')
        opened = findings.record_review(self.ledger, 'P1', 'M1', self.receipt('P1', note='third line absent'), read=['a.txt'])['opened']
        self.assertEqual(opened, ['RF2'])
        barrier = threading.Barrier(2)
        results = []

        def attempt(key):
            barrier.wait(30)
            try:
                self.link('RF2', key=key)
                results.append(('ok', key))
            except LedgerError as error:
                results.append(('refused', str(error)))
        threads = [threading.Thread(target=attempt, args=(k,)) for k in (self.key, later['record']['key'])]
        for t in threads:
            t.start()
        for t in threads:
            t.join(60)
        self.assertEqual(sorted(r[0] for r in results), ['ok', 'refused'], results)
        self.assertIn('already attributed to SKIP', [r for r in results if r[0] == 'refused'][0][1])
        rf2 = [e for e in self.link_events() if e['validity']['finding'] == 'RF2']
        self.assertEqual(len(rf2), 1, 'RF2 attributed to two SKIPs: the race got through')
        self.assertEqual(self.measure()['skip_leak']['value'], 2)

    def test_ai_session_cannot_sign_the_link_as_the_owner(self):
        with patch.dict(os.environ, {'CLAUDE_CODE_CHILD_SESSION': '1'}):
            with self.assertRaisesRegex(LedgerError, 'refused: this process runs inside an AI tool session'):
                self.link(by='owner')
            self.assertEqual(self.link_events(), [])
            self.link()
        stored = self.link_events()
        self.assertEqual(len(stored), 1)
        self.assertNotIn(stored[0]['actor'], ('owner', 'user'))
