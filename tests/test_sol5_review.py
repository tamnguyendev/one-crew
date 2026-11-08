"""Sol5: asserted Claude deadline/owner-environment/final-verdict probes.

Only temporary fixture ledgers; no provider or production acceptance.
"""
import json
import os
import sys
import datetime as dt
import unittest
from unittest.mock import patch

from onecrew.ledger import LedgerError, canonical, content_hash
from onecrew.common_handoff import handoff
from onecrew.common_verification import CandidateChecker
from onecrew.v2 import engine, findings, internal_plan, plan, repair_tasks, tracking, verdict, verification_evidence
from onecrew.v2.verifiers import command
from tests.test_review_b2_e2e import LoopFixture, GRANT
from tests.test_v2_l1 import milestone
from tests import test_sol_command_findings as command_cases
from tests.test_v2_l1 import Fixture, plan_json


class FinalWorkflow(LoopFixture):
    paths = ('a.txt',)
    bad = {'a.txt': b'candidate\n'}
    good = {'a.txt': b'good2\n'}
    milestones = (milestone('M1', argv=[sys.executable, '-c',
        'import os,pathlib; t=pathlib.Path("a.txt").read_text();print(t);'
        'raise SystemExit(3 if os.environ.get("CI")=="red" and t!="good2\\n" else 0)']),)

    def prepare(self): pass

    def delivered(self):
        checker = CandidateChecker(self.ledger, 'P1')
        self.step(); self.assertEqual(self.verify('C', checker)['result'], 'pass')
        self.step(); self.assertEqual(self.verify('I', checker)['result'], 'pass')
        return handoff(self.ledger, 'P1')

    def owner_accept(self, tree):
        with patch.dict(os.environ):
            os.environ.pop('ONECREW_ACTOR', None)
            return plan.accept(self.ledger, 'P1', 'owner', 'isolated Sol5 acceptance fixture', tree)

    def test_l10_empty_internal_plan_has_a_concrete_tracking_step(self):
        shown = plan.show(self.ledger, 'P1')
        value = plan_json(scope={'owned': ['a.txt']}, milestones=list(self.milestones), authority=GRANT)
        plan.propose(self.ledger, 'NoNodes', value, 'codex', workflow=True, capabilities=shown['capabilities'])
        with patch.dict(os.environ):
            os.environ.pop('ONECREW_ACTOR', None)
            plan.approve(self.ledger, 'NoNodes', 'owner', 'fixture')
        page = tracking.detail(self.ledger.state_root, 'NoNodes')
        self.assertEqual(page['status']['kind'], 'waiting')
        self.assertIn('engine revise', page['status']['reason'])

    def test_l1_acceptance_after_deadline_does_not_admit_work_or_accept_changed_tree(self):
        delivered = self.delivered()
        verdict.run(self.ledger, 'P1', 'M1')
        with self.ledger.transaction() as conn:
            room = internal_plan.ceilings(self.ledger, conn, plan.anchor_events(self.ledger, conn, 'P1'))
        expired = dict(room, remaining_seconds=0, deadline=(dt.datetime.now(dt.timezone.utc)-dt.timedelta(minutes=1)).isoformat())
        before = len([x for x in self.events() if x[0] == 'verdict.run_started'])
        with patch.object(internal_plan, 'ceilings', return_value=expired):
            self.assertEqual(engine.next_action(self.ledger, 'P1')['kind'], 'owner_accept')
            (self.root/'a.txt').write_text('user edit')
            self.assertEqual(engine.next_action(self.ledger, 'P1')['state'], 'blocked')
            with self.assertRaises(LedgerError): self.owner_accept(delivered['artifact'])
            (self.root/'a.txt').write_bytes(self.bad['a.txt'])
            self.assertEqual(self.owner_accept(delivered['artifact'])['status'], 'accepted')
        self.assertEqual(before, len([x for x in self.events() if x[0]=='verdict.run_started']))

    def test_l2_owner_shell_is_not_execution_environment_but_new_execution_stays_strict(self):
        delivered = self.delivered()
        shown = verdict.run(self.ledger, 'P1', 'M1')
        receipt = shown['milestones'][0]['last_verdict']['receipt']
        contract = shown['contract']; m = contract['milestones'][0]
        before = len([x for x in self.events() if x[0] == 'verdict.run_started'])
        with patch.dict(os.environ, {'TERM': 'different-owner-shell', 'CI': 'red'}):
            strict = verification_evidence.receipt_assessment(self.ledger, contract, m, 1, receipt, delivered['artifact'])
            self.assertFalse(strict['reusable'])
            self.assertEqual(engine.next_action(self.ledger, 'P1')['kind'], 'owner_accept')
            page = tracking.detail(self.ledger.state_root, 'P1')
            self.assertEqual(page['status']['kind'], 'done')
            self.assertTrue(any(n['kind'] == 'accept' for n in page['needs_user']))
            self.assertEqual(self.owner_accept(delivered['artifact'])['status'], 'accepted')
        self.assertEqual(before, len([x for x in self.events() if x[0]=='verdict.run_started']))

    def test_l3_final_failure_repair_uses_existing_generation_and_cas_then_accepts(self):
        self.delivered()
        with patch.dict(os.environ, {'CI': 'red'}):
            failed = verdict.run(self.ledger, 'P1', 'M1')
            self.assertEqual(failed['milestones'][0]['state'], 'failed')
            self.assertEqual(engine.next_action(self.ledger, 'P1')['kind'], 'diagnose')
            receipt = failed['milestones'][0]['last_verdict']['receipt']
            repair_tasks.prepare(self.ledger, 'P1', 'C', 'C', reason='repair final failure', evidence=[receipt])
            self.assertTrue(findings.list_findings(self.ledger, 'P1', open_only=True))
            self.assertFalse(engine.state(self.ledger, 'P1')['finding_blockers'])
            self.overlays = self.good
            delivered = self.delivered()
            shown = verdict.run(self.ledger, 'P1', 'M1')
            self.assertEqual(shown['milestones'][0]['state'], 'passed')
            self.assertEqual(findings.list_findings(self.ledger, 'P1', open_only=True), [])
            self.assertEqual(self.owner_accept(delivered['artifact'])['status'], 'accepted')
            self.assertEqual((self.root/'a.txt').read_text(), self.good['a.txt'].decode())

    def test_l3_repair_handoff_preserves_unrelated_user_edits(self):
        self.delivered()
        with patch.dict(os.environ, {'CI': 'red'}):
            failed = verdict.run(self.ledger, 'P1', 'M1')
            repair_tasks.prepare(self.ledger, 'P1', 'C', 'C', reason='repair', evidence=[failed['milestones'][0]['last_verdict']['receipt']])
            self.overlays = self.good
            checker = CandidateChecker(self.ledger, 'P1')
            self.step(); self.verify('C', checker); self.step(); self.verify('I', checker)
            (self.root/'a.txt').write_text('user edits')
            with self.assertRaises(LedgerError): handoff(self.ledger, 'P1')
            self.assertEqual((self.root/'a.txt').read_text(), 'user edits')

    def test_l3_forged_marker_cannot_release_final_finding(self):
        self.delivered()
        with patch.dict(os.environ, {'CI': 'red'}):
            failed = verdict.run(self.ledger, 'P1', 'M1')
            view = engine.state(self.ledger, 'P1')
            marker = {'kind': repair_tasks.KIND, 'root': view['root'], 'contract_sha': view['contract_sha'],
                      'source_receipt': failed['milestones'][0]['last_verdict']['receipt'], 'affected_nodes': ['C','I'],
                      'checks_sha': {n['id']: content_hash(n['checks']) for n in view['definition']['nodes']}}
            ref = self.store.blob(canonical(marker).encode())
            rows = view['definition']['nodes']
            for n in rows: n['input'].append(repair_tasks.PREFIX + ref)
            self.revise(rows)
            self.assertTrue(engine.state(self.ledger, 'P1')['finding_blockers'])
            self.assertEqual(self.step()['state'], 'waiting')

    def test_l3_final_repair_requires_existing_q5_authority(self):
        self.delivered()
        with patch.dict(os.environ, {'CI': 'red'}):
            failed = verdict.run(self.ledger, 'P1', 'M1')
            from onecrew.v2 import authority
            real = authority.effective
            def without_q5(contract):
                value = dict(real(contract))
                value['self_decide'] = [q for q in value.get('self_decide', []) if q != 'Q5']
                return value
            with patch.object(authority, 'effective', side_effect=without_q5):
                with self.assertRaises(LedgerError):
                    repair_tasks.prepare(self.ledger, 'P1', 'C', 'C', reason='repair without Q5', evidence=[failed['milestones'][0]['last_verdict']['receipt']])
            self.assertTrue(engine.state(self.ledger, 'P1')['finding_blockers'])
            self.assertFalse(any(k == 'workflow.repair_prepared' for k, p in self.events()))

    def test_l3_second_handoff_can_restore_base_without_ignoring_cas(self):
        base = (self.root/'a.txt').read_bytes()
        self.delivered()
        rows = engine.state(self.ledger, 'P1')['definition']['nodes']
        rows[0]['goal'] += ' Restore the original verified content.'
        self.revise(rows)
        self.overlays = {'a.txt': base}
        delivered = self.delivered()
        self.assertEqual((self.root/'a.txt').read_text(), base.decode().replace('\r\n', '\n'))
        self.assertEqual(delivered['state'], 'delivered')


class ClosureRecovery(command_cases.CommandFindingTests):
    # Inherit the established negative finding cases as well as the new crash case.
    def test_l12_crash_after_verdict_reconciles_closure_without_verifier_replay(self):
        self.start([sys.executable, '-c', 'from pathlib import Path; print("checked"); assert Path("a.txt").read_text()=="fixed\\n"'])
        verdict.run(self.ledger, 'P1', 'M1')
        (self.root/'a.txt').write_text('fixed\n')
        with patch.object(verdict, '_finish_findings', side_effect=RuntimeError('crash after verdict commit')):
            with self.assertRaisesRegex(RuntimeError, 'crash after'): verdict.run(self.ledger, 'P1', 'M1')
        self.assertTrue(findings.list_findings(self.ledger, 'P1', open_only=True))
        with patch.object(command, 'run', side_effect=AssertionError('must not execute again')):
            shown = verdict.run(self.ledger, 'P1', 'M1')
        self.assertFalse(shown['verifier_executed'])
        self.assertEqual(findings.list_findings(self.ledger, 'P1', open_only=True), [])


class AdapterClosure(Fixture):
    def test_l6_document_verdict_closes_all_repaired_criteria(self):
        (self.root/'guide.md').write_text('# Wrong\n[ref](missing.txt)\n')
        m = {'id':'Doc','title':'Doc','covers':['O1'],'mode':'until_pass','max_repairs':3,
             'verifier':{'type':'doc','config':{'docs':[{'path':'guide.md','headings':['Summary']}]}}}
        value = plan_json(milestones=[m], items=[{'id':'I1','title':'Doc','tier':'must','milestone':'Doc'}], scope={'owned':['guide.md']})
        plan.propose(self.ledger, 'P1', value, 'codex', workflow=True)
        plan.approve(self.ledger, 'P1', 'owner', 'temporary adapter fixture')
        verdict.run(self.ledger, 'P1', 'Doc')
        self.assertTrue(findings.list_findings(self.ledger, 'P1', open_only=True))
        (self.root/'guide.md').write_text('# Summary\n[ref](a.txt)\n')
        shown = verdict.run(self.ledger, 'P1', 'Doc')
        self.assertEqual(findings.list_findings(self.ledger, 'P1', open_only=True), [])
        self.assertTrue(shown['finding_rechecks'])
        self.assertEqual(plan.accept(self.ledger, 'P1', 'owner', 'fixture', shown['milestones'][0]['last_verdict']['artifact_sha'])['status'], 'accepted')


class SnapshotDiagnostic(unittest.TestCase):
    def test_l13_short_root_window_names_deadline_instead_of_snapshot_setting(self):
        deadline = (dt.datetime.now(dt.timezone.utc) + dt.timedelta(seconds=10)).isoformat()
        with command.snapshot_limits(deadline):
            with command._snapshot('test root cap'):
                budget = command._active.get()
                self.assertEqual(budget.reason, 'deadline')
                budget.begin -= 11
                with self.assertRaises(command.SnapshotFailed) as caught:
                    budget.check('update-index')
        self.assertEqual(caught.exception.reason, 'deadline')
        self.assertIn('increasing the snapshot limit cannot extend it', str(caught.exception))
