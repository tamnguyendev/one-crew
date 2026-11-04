"""Round 7 / T46b (KN-R01-R02, W23b + W23a) — E2: the pending change in the resume pack and on the `plan present` page come from ONE function.

The W23a function is `onecrew.contract_diff.diff` (report._diff, used by the present page's "ĐỔI SO VỚI BẢN ĐÃ DUYỆT" block, delegates to it;
resume_pack.changes_vs_approved delegates to contract_diff.changes -> diff). Integration check, on a temp ledger with a real amendment waiting
for the owner (P2 of 05 T46):
  * a call counter on contract_diff.diff is >= 1 WHILE the pack of P2 is generated through the CLI (`continue p2 --json`);
  * the pack's change list equals the diff of the two revision files read from the ledger, entry by entry, and the reason equals plan.amended's;
  * the paths on the present page, in order, equal the pack's paths, in order.
Counter-example ("nối sai"): a pack that computes its own diff — even one that returns the SAME entries, through a private copy of the algorithm
that bypasses the shared function — makes the integration check red (the counter stays at 0); a pack with a hand-rolled top-level diff is red
on the content too.
"""
import json
import re
import unittest
from unittest.mock import patch

from onecrew import contract_diff
from onecrew.v2 import contract as contracts, plan as plans, resume_pack
from wf_r02 import Sandbox, approved, events, milestone, plan_json, run_cli

ORIGINAL_DIFF = contract_diff.diff
HEAD = re.compile(r'^ĐỔI SO VỚI BẢN ĐÃ DUYỆT \(bản (\d+) → bản (\d+)\)$')


class SharedPendingChangeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.sandbox = Sandbox()
        cls.root = cls.sandbox.project('P1')
        cls.state = cls.sandbox.state('S')
        cls.ledger = cls.sandbox.ledger(cls.root, cls.state)
        approved(cls.ledger, 'p2', plan_json(title='Amended plan', milestones=[milestone('M1', covers=['O1'])]))
        new = plan_json(title='Amended plan, bigger', output=['The sample exists', 'A second thing exists'], non_goals=['Nothing else', 'No new dependency'],
                        milestones=[milestone('M1', covers=['O1'], title='Milestone M1, now stricter'), milestone('M2', covers=['O2'])])
        new['budget'] = {'max_calls': 100, 'time': 240}
        plans.amend(cls.ledger, 'p2', new, 'the owner asked for a stricter milestone and a second output', 'claude')

    @classmethod
    def tearDownClass(cls):
        cls.sandbox.close()

    def cli(self, *args):
        return run_cli(['--project', str(self.root), '--state-root', str(self.state), *args])

    def ledger_diff(self, contracts_too=False):
        """(entries, reason) from the ledger alone: the two revision files and the plan.amended payload."""
        amended = [p for _, _, p in events(self.ledger, 'p2', 'plan.amended')][-1]
        proposed = events(self.ledger, 'p2', 'plan.proposed')[0][2]
        old = contracts.read_revision(self.ledger, 'p2', 1, proposed['sha'])[0]
        new = contracts.read_revision(self.ledger, 'p2', 2, amended['sha'])[0]
        if contracts_too: return ORIGINAL_DIFF(old, new), amended['reason'], old, new
        return ORIGINAL_DIFF(old, new), amended['reason']

    def present_paths(self):
        code, text, err = self.cli('plan', 'present', 'p2')
        self.assertEqual(code, 0, text + err)
        lines = text.splitlines()
        start = next(i for i, l in enumerate(lines) if HEAD.match(l))
        self.assertEqual(HEAD.match(lines[start]).groups(), ('1', '2'))
        paths = []
        for line in lines[start + 1:]:
            if re.match(r'\d\. ', line): break
            m = re.match(r'  - (.+?): (thêm|bỏ|đổi)', line)
            if m: paths.append(m.group(1))
        return paths, text

    def integration_problems(self):
        """The T46b E2 integration check. [] when the pack's change comes from the W23a function and equals the ledger diff and the page."""
        problems = []
        expected, reason, old, new = self.ledger_diff(contracts_too=True)
        with patch.object(contract_diff, 'diff', wraps=contract_diff.diff) as counter:
            code, out, err = self.cli('continue', 'p2', '--json')
            # only the calls that compare THE two revisions of p2 at the top (other readers may diff other things)
            during_pack = sum(1 for c in counter.call_args_list if c.args[:2] == (old, new) and (c.args[2:] or ('',))[0] == '')
        if code != 0: return [f'continue exit {code}: {err}']
        change = json.loads(out)['pending_change']
        if during_pack < 1: problems.append('the W23a diff function was not called while the pack was generated')
        got = [(c['path'], c['change'], c['before'], c['after']) for c in change['changes']]
        labels = {'thêm': 'added', 'bỏ': 'removed', 'đổi': 'changed', 'đổi thứ tự': 'reordered'}
        want = [(p, labels[h], None if b is contract_diff.GONE else b, None if a is contract_diff.GONE else a) for p, h, b, a in expected]
        if got != want: problems.append(f'pack changes {got} != ledger diff {want}')
        if change['reason'] != reason: problems.append(f'reason {change["reason"]!r} != plan.amended {reason!r}')
        if (change['from_revision'], change['to_revision']) != (1, 2): problems.append('revisions')
        page, _ = self.present_paths()
        if page != [c['path'] for c in change['changes']]: problems.append(f'present page paths {page} != pack paths {[c["path"] for c in change["changes"]]}')
        return problems

    def test_e2_pack_and_present_use_the_one_shared_function(self):
        self.assertEqual(self.integration_problems(), [])
        expected, _ = self.ledger_diff()
        self.assertGreaterEqual(len(expected), 4)                       # a real, multi-entry amendment (title, output, non_goals, milestones, budget)

    def test_e2_present_page_calls_the_same_function(self):
        _, _, old, new = self.ledger_diff(contracts_too=True)
        with patch.object(contract_diff, 'diff', wraps=contract_diff.diff) as counter:
            paths, text = self.present_paths()
        self.assertGreaterEqual(sum(1 for c in counter.call_args_list if c.args[:2] == (old, new)), 1)
        self.assertIn('Lý do amend: «the owner asked for a stricter milestone and a second output»', text)
        self.assertEqual(paths, [p for p, _, _, _ in self.ledger_diff()[0]])

    def test_e2_counter_a_pack_that_computes_its_own_identical_diff_is_red(self):
        """The 'nối sai' build: same entries, but through a private copy of the algorithm, not the shared function."""
        def own_copy(old, new):
            labels = {'thêm': 'added', 'bỏ': 'removed', 'đổi': 'changed', 'đổi thứ tự': 'reordered'}
            return [{'path': p, 'change': labels[h], 'before': None if b is contract_diff.GONE else b, 'after': None if a is contract_diff.GONE else a}
                    for p, h, b, a in ORIGINAL_DIFF(old, new)]
        with patch.object(resume_pack, 'changes_vs_approved', own_copy):
            problems = self.integration_problems()
        self.assertEqual(problems, ['the W23a diff function was not called while the pack was generated'])

    def test_e2_counter_a_hand_rolled_top_level_diff_is_red_on_content(self):
        def top_level(old, new):
            return [{'path': k, 'change': 'changed', 'before': old.get(k), 'after': new.get(k)} for k in sorted(set(old) | set(new)) if old.get(k) != new.get(k)]
        with patch.object(resume_pack, 'changes_vs_approved', top_level):
            problems = self.integration_problems()
        self.assertTrue(any(p.startswith('pack changes') for p in problems), problems)
        self.assertTrue(any(p.startswith('present page paths') for p in problems), problems)


if __name__ == '__main__':
    unittest.main()
