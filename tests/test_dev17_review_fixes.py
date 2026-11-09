"""2.5.0.dev17 — sixth independent review (Kiro CLI, 09/11; BAO-CAO-REVIEW-dev16.md, verdict FAIL) on 5d7c289. Red on 5d7c289: 3 of the 4 tests
here; the fourth (a milestone added after every approved one stays routine) is a control. ExactBlobBytes (owner 09/11, "Đồng ý"): 3 of 3 red.

P1 (#9)  a new milestone inserted before an approved one ([M1] -> [M0, M1]) was routine, though M1 now waits for M0.
P2 (#2)  the metered reviewer's steps after admission and before the model call (task, reservation, the deadline check) did not say the
         model had not been called; an elapsed deadline left the attempt of unknown outcome instead of settling it as not started.
"""
import datetime as dt
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))          # test_v2_reviewer imports test_v2_l1 by its plain name

from onecrew import budget_core
from onecrew.ledger import LedgerError
from onecrew.v2 import acceptance_diff as ad, contract as contracts, metered_verifier, plan as plans
from onecrew.v2.verifiers import command
from onecrew.v2.metered_verifier import ProviderCall
from tests.test_v2_l1 import Fixture, plan_json, milestone
from tests.test_v2_reviewer import reviewer_milestone


class MilestoneInserted(Fixture):
    def contract(self, *ids):
        made = {'M0': dict(reviewer_milestone(), id='M0'), 'M1': milestone(), 'M2': dict(reviewer_milestone(), id='M2')}
        return plan_json(milestones=[made[i] for i in ids])

    def test_a_milestone_inserted_before_an_approved_one_is_acceptance(self):
        result = ad.classify_contract(self.contract('M1'), self.contract('M0', 'M1'))
        self.assertTrue(result['acceptance_changed'], result)
        self.assertNotEqual(result['summary'], 'wording or added checks only')

    def test_a_milestone_added_after_every_approved_one_stays_routine(self):
        result = ad.classify_contract(self.contract('M1'), self.contract('M1', 'M2'))
        self.assertFalse(result['acceptance_changed'], result); self.assertEqual([c['kind'] for c in result['changes']], ['added_check'])


class MeteredStepsBeforeTheModel(Fixture):
    def setUp(self):
        super().setUp()
        plans.propose(self.ledger, 'P1', plan_json(milestones=[reviewer_milestone()], budget={'max_calls': 3, 'time': 1}), 'codex', workflow=True)
        plans.approve(self.ledger, 'P1', 'owner', 'bounded temporary fixture')
        os.environ['ONECREW_ACTOR'] = 'codex'
        self.called = []

    def call(self):
        return ProviderCall(self.ledger, 'P1', 'M1', call=lambda *a: self.called.append(1))

    def counters(self):
        with self.ledger.transaction() as conn:
            return budget_core.group(conn, plans.anchor_events(self.ledger, conn, 'P1')['task_id'])

    def test_a_deadline_elapsed_before_dispatch_is_not_a_start_and_charges_nothing(self):
        late = (dt.datetime.now(dt.timezone.utc) + dt.timedelta(days=1)).isoformat()
        with patch.object(metered_verifier, 'utcnow', return_value=late), self.assertRaises(LedgerError) as caught:
            self.call()('prompt', {'provider': 'codex', 'model': 'fixture'}, {}, self.root.parent, 1)
        self.assertIn('deadline elapsed', str(caught.exception))
        self.assertIs(getattr(caught.exception, 'verifier_started', None), False)
        self.assertEqual(self.called, [])
        budget = self.counters()
        self.assertEqual((budget['used_calls'], budget['unknown_attempts']), (0, 0))

    def test_a_failure_while_setting_up_the_call_is_not_a_start(self):
        with patch.object(metered_verifier, 'submit', side_effect=OSError(28, 'No space left on device')), self.assertRaises(OSError) as caught:
            self.call()('prompt', {'provider': 'codex', 'model': 'fixture'}, {}, self.root.parent, 1)
        self.assertIs(getattr(caught.exception, 'verifier_started', None), False)
        self.assertEqual(self.called, [])


class ExactBlobBytes(Fixture):
    """Owner 09/11, "Đồng ý": the check runs on exactly the content locked in git, the same on every machine. No attribute of the tree changes a
    byte; a symbolic link is a plain file holding its target on every system; a git without --attr-source is refused, never used the old way."""
    def checkout(self, tree):
        scratch = tempfile.mkdtemp(prefix='ocv-test-'); self.addCleanup(lambda: shutil.rmtree(scratch, ignore_errors=True))
        return command._checkout(self.root, tree, scratch)

    def test_eol_ident_and_encoding_attributes_of_the_tree_change_no_byte(self):
        (self.root / '.gitattributes').write_text('*.txt text eol=crlf ident\n*.utf16 text working-tree-encoding=UTF-16\n')
        (self.root / 'b.txt').write_bytes(b'x\n$Id$\n')
        (self.root / 'c.utf16').write_bytes('chữ\n'.encode('utf-16'))            # git keeps it as UTF-8 in the blob
        tree = command.verified_sha(self.root)
        out = self.checkout(tree)
        for name in ('b.txt', 'c.utf16', '.gitattributes'):
            with self.subTest(name=name):
                blob = subprocess.check_output(['git', '-C', str(self.root), 'cat-file', 'blob', f'{tree}:{name}'])
                self.assertEqual((out / name).read_bytes(), blob)

    def test_a_symbolic_link_is_a_plain_file_holding_its_target(self):
        blob = subprocess.run(['git', '-C', str(self.root), 'hash-object', '-w', '--stdin'], input=b'releases/safe', capture_output=True, check=True).stdout.decode().strip()
        a = subprocess.check_output(['git', '-C', str(self.root), 'rev-parse', 'HEAD:a.txt']).decode().strip()
        tree = subprocess.run(['git', '-C', str(self.root), 'mktree'], input=f'120000 blob {blob}\tcurrent\n100644 blob {a}\ta.txt\n'.encode(),
                              capture_output=True, check=True).stdout.decode().strip()
        out = self.checkout(tree)
        self.assertFalse((out / 'current').is_symlink())
        self.assertEqual((out / 'current').read_bytes(), b'releases/safe')

    def test_a_git_without_attr_source_is_refused_with_what_to_do(self):
        plans.propose(self.ledger, 'P1', plan_json(), 'claude'); plans.approve(self.ledger, 'P1', 'owner', 'fixture')
        m = contracts.validate(plan_json())['milestones'][0]
        with patch.object(command, 'git_version', return_value=(2, 39)), self.assertRaises(LedgerError) as caught:
            command.run(self.ledger, 'P1', 1, 'x' * 64, m, self.root)
        self.assertIn('2.40', str(caught.exception)); self.assertIn('Update git', str(caught.exception))
        self.assertIs(getattr(caught.exception, 'verifier_started', None), False)
