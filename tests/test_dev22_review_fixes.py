"""2.5.0.dev22 — the owner's answer of 10/11 ("Đồng ý cả 3") to the tenth review (Kiro, BAO-CAO-REVIEW-dev20.md). Red on 9d23ed4.

A-lite: the first write of this OneCrew to a plan records a checkout-policy epoch (table policy_epochs, one per policy value); evidence of a plan that is not accepted
counts only when made after it: a top-level verdict by the seq of its receipt_issued, a node verification by its own seq. plan.accept,
accept_node, the handoff, root_ready and eligible all go through it; plan show / tracking say "cần kiểm lại". Read-only commands write nothing.
B: the work-mode verification checkout holds the exact blob bytes (the tree's own .gitattributes included) and `git status` there is clean.
"""
import os
import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))          # test_v2_reviewer imports test_v2_l1 by its plain name

from onecrew.ledger import LedgerError
from onecrew import work_tools as wt
from onecrew.v2 import engine, plan as plans, tracking, verdict
try:
    from onecrew.v2 import policy_epoch
except ImportError:          # 9d23ed4 has no epoch: the tests below then fail on behaviour, which is the red
    policy_epoch = None
EPOCH = 'checkout.policy_epoch'
from onecrew.v2.verifiers import command
from tests import test_wf_candidate_handoff as handoff
from tests.test_v2_l1 import Fixture, plan_json
from tests.test_work_boundary import PY
from tests import test_work_isolation as work

OLD = 'tree-attributes-applied/0'


class TopLevelEvidence(Fixture):
    def start(self):
        with patch.object(command, 'CHECKOUT_POLICY', OLD):                     # a plan and a verdict made by the OneCrew before this one
            plans.propose(self.ledger, 'P1', plan_json(), 'claude'); plans.approve(self.ledger, 'P1', 'owner', 'fixture')
            verdict.run(self.ledger, 'P1', 'M1', self.root)

    def epochs(self):
        with self.ledger.transaction() as conn:
            try: return [tuple(r) for r in conn.execute('SELECT * FROM policy_epochs')]
            except Exception: return []                                   # 9d23ed4: no table

    def test_a_legacy_verdict_needs_a_new_check_and_plan_accept_refuses_it(self):
        self.start()
        before = len(self.epochs())
        view = plans.show(self.ledger, 'P1')['milestones'][0]
        self.assertEqual(len(self.epochs()), before, 'plan show wrote to the ledger')
        self.assertTrue(view.get('needs_recheck'), view); self.assertNotEqual(view['state'], 'passed')
        with self.assertRaises(LedgerError) as caught:
            plans.accept(self.ledger, 'P1', 'owner', 'fixture', command.verified_sha(self.root))
        self.assertIn('policy epoch', str(caught.exception))
        verdict.run(self.ledger, 'P1', 'M1', self.root)                         # checked again under this policy
        self.assertEqual(plans.accept(self.ledger, 'P1', 'owner', 'fixture', command.verified_sha(self.root))['status'], 'accepted')

    def test_a_receipt_issued_before_the_epoch_and_recorded_after_it_is_still_before(self):
        # the epoch here is written by this OneCrew's first write (ensure), after the receipt the older one issued
        self.start()
        recorded = [p for k, p in self.events() if k == 'verdict.recorded'][-1]
        with self.ledger.transaction(write=True) as conn:
            state = plans.anchor_events(self.ledger, conn, 'P1')
            policy_epoch.ensure(self.ledger, state['task_id'], conn)
            self.ledger._event(conn, state['task_id'], 'verdict.recorded', dict(recorded))       # the same receipt, recorded after the epoch
        view = plans.show(self.ledger, 'P1')['milestones'][0]
        self.assertTrue(view.get('needs_recheck'), view)

    def test_tracking_says_needs_a_new_check(self):
        self.start()
        milestones = tracking.detail(self.ledger.state_root, 'P1')['milestones']
        self.assertEqual(milestones[0].get('state_text'), 'cần kiểm lại', milestones[0])


class NodeEvidence(handoff.CandidateFixture):
    def setUp(self):
        with patch.object(command, 'CHECKOUT_POLICY', OLD):                     # the plan approved by the OneCrew before this one
            super().setUp()

    def test_a_node_verified_before_the_epoch_is_not_verified(self):
        with patch.object(command, 'CHECKOUT_POLICY', OLD):                     # everything here by the OneCrew before this one
            self.revise(self.definition()); self.step()
            self.engine.verify(self.ledger, 'P1', 'C', self.production_checker)
        view = engine.state(self.ledger, 'P1')
        self.assertEqual(view['nodes']['C']['state'], 'produced'); self.assertTrue(view['nodes']['C'].get('needs_recheck'))
        self.assertFalse(engine.eligible(view, 'I')['ready'])                    # the dependent node waits
        self.assertFalse(engine.verification_ready(self.ledger, 'P1')); self.assertFalse(engine.root_ready(self.ledger, 'P1'))
        with patch.object(engine.ip, 'decide', return_value=None), self.assertRaises(LedgerError):
            engine.accept_node(self.ledger, 'P1', 'C')
        self.engine.verify(self.ledger, 'P1', 'C', self.production_checker)      # checked again under this policy
        self.assertEqual(engine.state(self.ledger, 'P1')['nodes']['C']['state'], 'verified')


class WorkModeExactBytes(work.Fixture):
    def test_the_work_mode_checkout_has_the_blob_bytes_and_a_clean_status(self):
        (self.root / '.gitattributes').write_text('*.txt text eol=crlf\n')
        (self.root / 'data.txt').write_bytes(b'x\ny\n')
        self.git('add', '.gitattributes', 'data.txt'); self.git('commit', '-q', '-m', 'crlf attribute')
        job = self.open('exact', edit=True, commands=True)
        runtime, task, state, contract = job
        check = ("import subprocess,sys; b=open('data.txt','rb').read(); "
                 "s=subprocess.run(['git','status','--porcelain'],capture_output=True).stdout; print(repr(b), repr(s)); "
                 "sys.exit(0 if b==b'x\\ny\\n' and s==b'' else 1)")
        result = wt.verify(runtime, task, state, contract, {'verification': [{'argv': [PY, '-c', check]}]}, lambda: None)
        self.assertEqual(result['findings'], [], result['findings'])
