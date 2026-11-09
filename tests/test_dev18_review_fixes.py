"""2.5.0.dev18 — seventh independent review (Kiro CLI, 10/11; BAO-CAO-REVIEW-dev17.md, verdict FAIL) on b77966e. Every test here is red on b77966e.

P1 (#9)  the approval card compared an amendment with the revision just before it, not with the last approved one.
P1 (#4)  a receipt made under the old checkout (tree attributes applied) stayed current after the exact-bytes checkout of dev17.
P2 (#2)  auth api without a key was charged as one model call under the root budget.
P2 (#4)  the candidate materialization (git add -u) applied the tree's attributes and the machine's filters again.
P3       Ctrl+C after the launch was recorded and before the model call left the attempt of unknown outcome.
"""
import copy
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))          # test_v2_reviewer imports test_v2_l1 by its plain name

from onecrew import budget_core
from onecrew.common_verification import materialized_tree
from onecrew.control_core import Control
from onecrew.ledger import LedgerError
from onecrew.snapshots import Snapshots
from onecrew.v2 import namespaces, plan as plans, verdict
from onecrew.v2 import verification_evidence as evidence
from onecrew.v2.metered_verifier import ProviderCall
from onecrew.v2.verifiers import command, reviewer
from tests.test_v2_l1 import Fixture, plan_json, milestone
from tests.test_v2_reviewer import reviewer_milestone


class CardComparesWithTheLastApproved(Fixture):
    def test_a_retitle_after_an_unapproved_insertion_is_still_a_change_of_acceptance(self):
        first = plan_json(milestones=[milestone()])
        plans.propose(self.ledger, 'P1', first, 'claude'); plans.approve(self.ledger, 'P1', 'owner', 'fixture')
        inserted = copy.deepcopy(first); inserted['milestones'] = [dict(reviewer_milestone(), id='M0'), milestone()]
        plans.amend(self.ledger, 'P1', inserted, 'insert a review first', 'claude')
        retitled = copy.deepcopy(inserted); retitled['title'] = 'Another title'
        plans.amend(self.ledger, 'P1', retitled, 'retitle', 'claude')
        last = [p for k, p in self.events() if k == 'plan.amended'][-1]
        self.assertEqual(last['revision'], 3)
        self.assertEqual(last['acceptance_diff']['classification'], 'U1', last['acceptance_diff'])
        self.assertEqual(last['acceptance_diff'].get('compared_with'), 1)


class OldCheckoutReceiptsAreStale(Fixture):
    def test_a_receipt_made_under_another_checkout_policy_runs_again(self):
        (self.root / 'interface.txt').write_text('interface A'); self.git('add', '.'); self.git('commit', '-qm', 'interface')
        value = plan_json(); value['understanding']['target']['paths'] = ['a.txt', 'interface.txt']
        plans.propose(self.ledger, 'P1', value, 'fixture', workflow=True, capabilities=list(namespaces.CAPABILITIES))
        plans.approve(self.ledger, 'P1', 'owner', 'temporary fixture')
        with patch.object(command, 'CHECKOUT_POLICY', 'tree-attributes-applied/0', create=True):      # a receipt of the checkout before dev17
            out = verdict.run(self.ledger, 'P1', 'M1')
        receipt = out['milestones'][0]['last_verdict']['receipt']
        with self.ledger.transaction() as conn: state = plans.derive(self.ledger, conn, 'P1')
        contract = plans.load(self.ledger, state, 1)[0]
        tree = command.verified_sha(self.root)
        result = evidence.receipt_assessment(self.ledger, contract, contract['milestones'][0], 1, receipt, tree, task_id=state['task_id'])
        self.assertFalse(result['reusable'], result)
        self.assertIn('checker configuration changed', result['reasons'])
        self.assertTrue(plans.show(self.ledger, 'P1')['milestones'][0]['stale'])


class MeteredFixture(Fixture):
    def root_with_budget(self, **config):
        plans.propose(self.ledger, 'P1', plan_json(milestones=[reviewer_milestone(**config)], budget={'max_calls': 2, 'time': 1}), 'codex', workflow=True)
        plans.approve(self.ledger, 'P1', 'owner', 'bounded temporary fixture')
        os.environ['ONECREW_ACTOR'] = 'codex'

    def counters(self):
        with self.ledger.transaction() as conn:
            return budget_core.group(conn, plans.anchor_events(self.ledger, conn, 'P1')['task_id'])


class NoKeyIsNoCall(MeteredFixture):
    def test_auth_api_without_a_key_charges_no_call(self):
        self.root_with_budget(auth='api')
        os.environ.pop('ANTHROPIC_API_KEY', None)
        (self.root / 'a.txt').write_text('two\n')
        verdict.run(self.ledger, 'P1', 'M1')
        budget = self.counters()
        self.assertEqual((budget['used_calls'], budget['unknown_attempts']), (0, 0), budget)


class InterruptAfterTheLaunch(MeteredFixture):
    def test_ctrl_c_after_the_launch_and_before_the_model_is_settled_not_unknown(self):
        self.root_with_budget()
        called = []
        real = Control.launched

        def launched_then_interrupted(control, *a, **k):
            real(control, *a, **k)
            raise KeyboardInterrupt

        with patch.object(Control, 'launched', launched_then_interrupted), self.assertRaises(KeyboardInterrupt) as caught:
            ProviderCall(self.ledger, 'P1', 'M1', call=lambda *a: called.append(1))('prompt', {'provider': 'codex', 'model': 'fixture'}, {},
                                                                                    self.root.parent, 1)
        self.assertEqual(called, [])
        self.assertIs(getattr(caught.exception, 'verifier_started', None), False)
        self.assertEqual(self.counters()['unknown_attempts'], 0)


class CandidateMaterializedWithExactBytes(Fixture):
    def seal(self):
        self.git('add', '-f', '-A'); self.git('commit', '-qm', 'seal')
        return self.git('rev-parse', 'HEAD^{tree}')

    def test_tree_attributes_and_symlinks_do_not_make_the_candidate_differ(self):
        (self.root / '.gitattributes').write_text('*.txt text eol=crlf ident\n*.utf16 text working-tree-encoding=UTF-16\n')
        (self.root / 'b.txt').write_bytes(b'x\n$Id$\n')
        (self.root / 'c.utf16').write_bytes('chữ\n'.encode('utf-16'))          # git keeps it as UTF-8 in the blob
        tree = self.seal()
        link = subprocess.run(['git', '-C', str(self.root), 'hash-object', '-w', '--stdin'], input=b'releases/safe', capture_output=True, check=True).stdout.decode().strip()
        listing = subprocess.check_output(['git', '-C', str(self.root), 'ls-tree', tree]).decode()
        tree = subprocess.run(['git', '-C', str(self.root), 'mktree'], input=(listing + f'120000 blob {link}\tcurrent\n').encode(),
                              capture_output=True, check=True).stdout.decode().strip()
        with tempfile.TemporaryDirectory(prefix='oc-dev18-') as temp:
            checkout = materialized_tree(self.ledger, tree, temp)
            self.assertEqual((checkout / 'b.txt').read_bytes(), b'x\n$Id$\n')
