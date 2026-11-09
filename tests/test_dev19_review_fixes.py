"""2.5.0.dev19 — eighth independent review (Kiro CLI, 10/11; BAO-CAO-REVIEW-dev18.md, verdict FAIL) on ad6b59e. Every test here is red on ad6b59e.

P1 (#4)  the candidate checker built its own evidence binding without the checkout policy: a node receipt of the old checkout was reused.
P2 (#2)  no Claude CLI on the machine was found only after the launch was recorded: one call charged, the attempt left unknown.
P2 (#4)  materialized_tree initialised its repository without the object format: a SHA-256 project could not be checked.
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))          # test_v2_reviewer imports test_v2_l1 by its plain name

from onecrew import budget_core
from onecrew import common_verification as cv
from onecrew.ledger import Ledger, LedgerError
from onecrew.v2 import plan as plans
from onecrew.v2.metered_verifier import ProviderCall
from onecrew.v2.verifiers import command, reviewer
from tests import test_wf_candidate_handoff as handoff          # the module: its classes' tests would run again here
from tests.test_v2_l1 import Fixture, plan_json
from tests.test_v2_reviewer import reviewer_milestone


class OldCandidateReceiptIsNotReused(handoff.CandidateFixture):
    def node_I(self):
        view = self.engine.state(self.ledger, 'P1')
        return next(n for n in view['definition']['nodes'] if n['id'] == 'I'), view['nodes']['I']

    def test_a_node_receipt_of_another_checkout_policy_runs_again(self):
        with patch.object(command, 'CHECKOUT_POLICY', 'tree-attributes-applied/0', create=True):     # receipts of the checkout before dev17
            self.revise(self.definition()); self.step()
            self.engine.verify(self.ledger, 'P1', 'C', self.production_checker)
            self.step()
            self.engine.verify(self.ledger, 'P1', 'I', self.production_checker)
        item, record = self.node_I()
        checked = cv.CandidateChecker(self.ledger, 'P1')(item, record['artifact'], previous_receipt=record['verification_receipt'])
        self.assertNotIn('reuse_basis', checked)                                 # checked again, not reused
        self.assertTrue(all(row['result'] == 'pass' for row in checked['checks']))


class NoCliIsNoCall(Fixture):
    def test_a_missing_claude_cli_is_settled_as_not_started(self):
        plans.propose(self.ledger, 'P1', plan_json(milestones=[reviewer_milestone()], budget={'max_calls': 2, 'time': 1}), 'codex', workflow=True)
        plans.approve(self.ledger, 'P1', 'owner', 'bounded temporary fixture')
        os.environ['ONECREW_ACTOR'] = 'codex'

        def no_cli(env):
            raise LedgerError('The Claude CLI was not found on this machine.')

        with patch.object(reviewer, 'cli_argv', no_cli), self.assertRaises(LedgerError) as caught:
            ProviderCall(self.ledger, 'P1', 'M1')('prompt', {'provider': 'claude', 'model': 'claude-haiku-5-5'}, {}, self.root.parent, 1)
        self.assertIs(getattr(caught.exception, 'verifier_started', None), False)
        with self.ledger.transaction() as conn:
            budget = budget_core.group(conn, plans.anchor_events(self.ledger, conn, 'P1')['task_id'])
        self.assertEqual((budget['used_calls'], budget['unknown_attempts']), (0, 0), budget)


class Sha256Project(Fixture):
    def test_a_sha256_candidate_is_materialized(self):
        project = Path(self.temp.name) / 'sha256'; project.mkdir()
        run = lambda *a: subprocess.run(['git', '-C', str(project), *a], capture_output=True, check=True).stdout.decode().strip()
        run('init', '-q', '--object-format=sha256'); run('config', 'user.name', 'T'); run('config', 'user.email', 't@localhost')
        (project / 'a.txt').write_bytes(b'one\n'); run('add', '.'); run('commit', '-q', '-m', 'base')
        tree = run('rev-parse', 'HEAD^{tree}')
        self.assertEqual(len(tree), 64)
        ledger = Ledger(project, Path(self.temp.name) / 'state256')
        with tempfile.TemporaryDirectory(prefix='oc-dev19-') as temp:
            checkout = cv.materialized_tree(ledger, tree, temp)
            self.assertEqual((checkout / 'a.txt').read_bytes(), b'one\n')
