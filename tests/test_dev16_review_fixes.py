"""2.5.0.dev16 — fifth independent review (Kiro CLI, 09/11; BAO-CAO-REVIEW-dev15.md, verdict FAIL) on cecd9c5. Red on cecd9c5: 4 of the 5 tests
here; the fifth (a reordered milestone list that keeps the order is routine) is a control.

P1 (#9)  milestones reordered were shown as "wording or added checks only", though verdict.run runs them in the order of the list.
P2 (#2)  the shared root budget refusing a reviewer before the model call did not say the verifier had not started, so the next run was held.
P2 (#2)  Ctrl+C (KeyboardInterrupt) before the verifier passed through before_verifier unmarked.
P2 (#4)  the checkout still ran a filter.<name>.smudge of the global git config (Git LFS works the same way).
"""
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))          # test_v2_reviewer imports test_v2_l1 by its plain name

from onecrew.ledger import LedgerError
from onecrew.v2 import acceptance_diff as ad, contract as contracts, plan as plans, verdict
from onecrew.v2.verifiers import command, reviewer
from tests.test_v2_l1 import Fixture, plan_json, milestone
from tests.test_v2_reviewer import reviewer_milestone, answer, row


class MilestoneOrder(Fixture):
    def contract(self, order):
        ms = {'M1': milestone(), 'M2': dict(reviewer_milestone(), id='M2')}
        return plan_json(milestones=[ms[i] for i in order])

    def test_reordered_milestones_are_acceptance(self):
        result = ad.classify_contract(self.contract(['M1', 'M2']), self.contract(['M2', 'M1']))
        self.assertTrue(result['acceptance_changed'], result)
        self.assertIn('milestones', [c['path'] for c in result['changes'] if c['acceptance']])

    def test_the_same_order_is_routine(self):
        self.assertFalse(ad.classify_contract(self.contract(['M1', 'M2']), self.contract(['M1', 'M2']))['acceptance_changed'])


class RootBudgetRefusalIsNotAStart(Fixture):
    def test_a_refused_admission_says_the_reviewer_did_not_start_and_the_next_run_is_not_held(self):
        plans.propose(self.ledger, 'P1', plan_json(milestones=[reviewer_milestone()], budget={'max_calls': 1, 'time': 1}), 'codex', workflow=True)
        plans.approve(self.ledger, 'P1', 'owner', 'bounded temporary fixture')
        os.environ['ONECREW_ACTOR'] = 'codex'
        (self.root / 'a.txt').write_text('two\n')
        with patch.object(reviewer, 'call', return_value=(answer(row('R1'), row('R2')), {}, None, False, b'fixture')):
            verdict.run(self.ledger, 'P1', 'M1')
            (self.root / 'a.txt').write_text('three\n')
            for _ in range(2):                   # on cecd9c5 the second is "a run of unknown outcome is held"
                with self.assertRaises(LedgerError) as caught:
                    verdict.run(self.ledger, 'P1', 'M1')
                self.assertIn('shared root budget', str(caught.exception))
                self.assertIs(getattr(caught.exception, 'verifier_started', None), False)


class InterruptBeforeTheVerifier(Fixture):
    def test_ctrl_c_before_the_command_says_it_did_not_start_and_stays_an_interrupt(self):
        plans.propose(self.ledger, 'P1', plan_json(), 'claude'); plans.approve(self.ledger, 'P1', 'owner', 'fixture')
        m = contracts.validate(plan_json())['milestones'][0]
        with patch.object(command, '_checkout', side_effect=KeyboardInterrupt), self.assertRaises(KeyboardInterrupt) as caught:
            command.run(self.ledger, 'P1', 1, 'x' * 64, m, self.root)
        self.assertIs(getattr(caught.exception, 'verifier_started', None), False)


class CheckoutIgnoresGlobalFilters(Fixture):
    def test_a_smudge_filter_of_the_global_config_does_not_change_the_bytes(self):
        tool = Path(self.temp.name) / 'upper.py'
        tool.write_text('import sys\nsys.stdout.buffer.write(sys.stdin.buffer.read().upper())\n')
        home = Path(self.temp.name) / 'home'; home.mkdir()
        (home / '.gitconfig').write_text(f'[filter "demo"]\n\tsmudge = \\"{Path(sys.executable).as_posix()}\\" \\"{tool.as_posix()}\\"\n\tclean = cat\n')
        os.environ.update(HOME=str(home), USERPROFILE=str(home), XDG_CONFIG_HOME=str(home / '.config'))
        (self.root / '.gitattributes').write_text('*.txt filter=demo\n')
        (self.root / 'b.txt').write_bytes(b'x\ny\n')
        tree = command.verified_sha(self.root)
        smudged = subprocess.run(['git', '-C', str(self.root), 'cat-file', '--filters', f'{tree}:b.txt'], capture_output=True).stdout
        self.assertEqual(smudged.replace(b'\r', b''), b'X\nY\n')       # the filter is live on this machine (any line ending)
        scratch = tempfile.mkdtemp(prefix='ocv-test-'); self.addCleanup(lambda: shutil.rmtree(scratch, ignore_errors=True))
        self.assertEqual((command._checkout(self.root, tree, scratch) / 'b.txt').read_bytes(), b'x\ny\n')
