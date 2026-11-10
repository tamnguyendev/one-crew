"""2.5.0.dev23 — eleventh independent review (Kiro CLI, 10/11; BAO-CAO-REVIEW-dev22.md: P1, FAIL) on b015155. Red on b015155.

P1  an internal node acceptance made before the policy epoch counted as accepted (it overrode needs_recheck) and engine.verify could not
    check that node again.
P1  a handoff made before the policy epoch stayed evidence: root_ready passed and the handoff returned idempotent.
P2  plan.propose and the recovery paths wrote before any epoch; `plan show` through the CLI could write the ledger (sync_refusals);
    the work checkout did not fail closed on its refresh or status; the top-level reconcile recorded a receipt of another checkout policy.
"""
import contextlib
import io
import json
import os
import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))          # test_v2_reviewer imports test_v2_l1 by its plain name

from onecrew.common_handoff import handoff
from onecrew.ledger import LedgerError
from onecrew import work_tools as wt
from onecrew.v2 import engine, plan as plans, plan_cli, verdict
from onecrew.v2.verifiers import command
from tests import test_wf_candidate_handoff as candidate
from tests import test_work_isolation as work
from tests.test_v2_l1 import Fixture, plan_json
from tests.test_work_boundary import PY

OLD = 'tree-attributes-applied/0'


def epochs(ledger):
    with ledger.transaction() as conn:
        try: return [tuple(r) for r in conn.execute('SELECT task_id, policy FROM policy_epochs')]
        except Exception: return []                                       # b015155 before any write: no table


class BeforeTheUpgrade(candidate.CandidateFixture):
    def setUp(self):
        with patch.object(command, 'CHECKOUT_POLICY', OLD):                     # the plan approved by the OneCrew before this one
            super().setUp()


class NodeAcceptedBeforeTheEpoch(BeforeTheUpgrade):
    def test_an_old_internal_acceptance_needs_a_new_check_and_the_node_can_be_verified_again(self):
        with patch.object(command, 'CHECKOUT_POLICY', OLD), patch.object(engine.ip, 'decide', return_value=None):
            self.revise(self.definition()); self.step()
            self.engine.verify(self.ledger, 'P1', 'C', self.production_checker)
            engine.accept_node(self.ledger, 'P1', 'C')
        record = engine.state(self.ledger, 'P1')['nodes']['C']
        self.assertNotEqual(record['state'], 'accepted'); self.assertTrue(record.get('needs_recheck'), record)
        self.assertFalse(engine.eligible(engine.state(self.ledger, 'P1'), 'I')['ready'])
        self.engine.verify(self.ledger, 'P1', 'C', self.production_checker)       # on b015155: "Only the current produced node can be verified"
        self.assertEqual(engine.state(self.ledger, 'P1')['nodes']['C']['state'], 'verified')


class HandoffBeforeTheEpoch(BeforeTheUpgrade):
    def test_an_old_handoff_is_not_ready_and_the_handoff_runs_again(self):
        with patch.object(command, 'CHECKOUT_POLICY', OLD):
            self.revise(self.definition()); self.step()
            self.engine.verify(self.ledger, 'P1', 'C', self.production_checker)
            self.step(); self.engine.verify(self.ledger, 'P1', 'I', self.production_checker)
            first = handoff(self.ledger, 'P1', control=self.control)
            self.assertTrue(self.engine.root_ready(self.ledger, 'P1', first['artifact']))
        self.assertFalse(self.engine.root_ready(self.ledger, 'P1', first['artifact']))
        for nid in ('C', 'I'):
            self.engine.verify(self.ledger, 'P1', nid, self.production_checker)
        again = handoff(self.ledger, 'P1', control=self.control)
        self.assertNotEqual(again.get('idempotent'), True, again)
        self.assertTrue(self.engine.root_ready(self.ledger, 'P1', again['artifact']))


class EveryFirstWriteMarksTheEpoch(Fixture):
    def test_propose_marks_the_epoch(self):
        plans.propose(self.ledger, 'P1', plan_json(), 'claude')
        with self.ledger.transaction() as conn:
            task = plans.derive(self.ledger, conn, 'P1')['task_id']
        self.assertIn((task, command.CHECKOUT_POLICY), epochs(self.ledger))


class ReadOnlyCli(Fixture):
    def test_plan_show_through_the_cli_does_not_sync_refusals(self):
        plans.propose(self.ledger, 'P1', plan_json(), 'claude')
        calls = []
        with patch('onecrew.v2.gate.sync_refusals', side_effect=lambda ledger: calls.append(1)), contextlib.redirect_stdout(io.StringIO()):
            code = plan_cli.main(['--project', str(self.root), '--state-root', str(self.ledger.state_root), 'plan', 'show', 'P1'])
        self.assertEqual((code, calls), (0, []))


class ReconcileKeepsThePolicy(Fixture):
    def test_an_issued_receipt_of_another_policy_is_not_recorded_by_reconcile(self):
        with patch.object(command, 'CHECKOUT_POLICY', OLD):
            plans.propose(self.ledger, 'P1', plan_json(), 'claude'); plans.approve(self.ledger, 'P1', 'owner', 'fixture')
            with patch.object(verdict, 'record', side_effect=RuntimeError('process lost before the verdict was recorded')):
                with self.assertRaises(RuntimeError): verdict.run(self.ledger, 'P1', 'M1', self.root)
        recorded = len([k for k, _ in self.events() if k == 'verdict.recorded'])
        try:
            verdict.reconcile(self.ledger, 'P1', 1, 'M1')
        except LedgerError:
            pass
        self.assertEqual(len([k for k, _ in self.events() if k == 'verdict.recorded']), recorded, 'a receipt of another policy was recorded')


class WorkCheckoutFailsClosed(work.Fixture):
    def test_a_dirty_or_failing_status_stops_the_verification(self):
        job = self.open('closed', edit=True, commands=True)
        runtime, task, state, contract = job
        real = wt.git

        def dirty(repo, *args, **kw):
            if 'status' in args and '--porcelain' in args: return b' M data.txt\n'
            return real(repo, *args, **kw)

        with patch.object(wt, 'git', dirty):
            try:
                result = wt.verify(runtime, task, state, contract, {'verification': [{'argv': [PY, '-c', 'print(1)']}]}, lambda: None)
            except LedgerError as error:
                result = {'findings': [str(error)]}
        self.assertTrue(any('does not read clean' in f for f in result['findings']), result['findings'])
