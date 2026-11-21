"""Scoped intermediate checks are judged inside the final check's full delivery tree (VER60 D2)."""
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_v2_l2 import HookFixture, owned_plan                                          # noqa: E402
from test_v2_l1 import milestone                                                         # noqa: E402
from onecrew.ledger import LedgerError                                                   # noqa: E402
from onecrew.v2 import plan as plans, verdict                                            # noqa: E402
from onecrew.v2.verifiers import command                                                 # noqa: E402

PY = sys.executable
OK = "import pathlib; print(sorted(str(p) for p in pathlib.Path('.').rglob('*.txt')))"     # reads and says what it saw: silent and fast is inconclusive


class AcceptUnion(HookFixture):
    def setUp(self):
        super().setUp()
        for rel in ('mot/a.txt', 'hai/b.txt', 'ngoai/c.txt'):
            p = self.root / rel; p.parent.mkdir(exist_ok=True); p.write_text(rel + '\n', encoding='utf-8')
        self.git('add', '-A'); self.git('commit', '-qm', 'nguon')
        self.scratch = Path(self.temp.name) / 'tam'; self.scratch.mkdir()
        old = tempfile.tempdir; tempfile.tempdir = str(self.scratch)
        self.addCleanup(setattr, tempfile, 'tempdir', old)

    def git(self, *a):
        return subprocess.run(['git', '-C', str(self.root), '-c', 'user.name=t', '-c', 'user.email=t@t', *a], check=True, capture_output=True, text=True).stdout

    def plan(self, second_inputs=('hai',)):
        m1 = milestone('M1', argv=[PY, '-c', OK]); m1['verifier']['config']['inputs'] = ['mot']
        m2 = milestone('M2', argv=[PY, '-c', OK])
        if second_inputs: m2['verifier']['config']['inputs'] = list(second_inputs)
        self.enforce(value=owned_plan(milestones=[m1, m2]))
        verdict.run(self.ledger, 'P1', 'M1'); verdict.run(self.ledger, 'P1', 'M2')

    def receipt_artifacts(self):
        with self.ledger.transaction() as conn:
            state = plans.anchor_events(self.ledger, conn, 'P1')
        return {v['milestone']: v['artifact_sha'] for v in state['verdicts']}

    def accept(self, sha):
        with patch.dict(os.environ):
            os.environ.pop('ONECREW_ACTOR', None)
            return plans.accept(self.ledger, 'P1', 'owner', 'fixture', sha)

    def status(self):
        return plans.show(self.ledger, 'P1')['status']

    def test_one_receipts_sha_refuses_and_says_where_to_get_the_right_one(self):
        self.plan()
        shas = self.receipt_artifacts()
        self.assertNotEqual(shas['M1'], shas['M2'])
        with self.assertRaisesRegex(LedgerError, r'M2: artifact changed.*verdict artifact --plan P1'): self.accept(shas['M1'])
        self.assertNotEqual(self.status(), 'accepted')

    def test_verdict_artifact_gives_the_full_delivery_tree_and_accept_takes_it(self):
        self.plan()
        got = verdict.artifact(self.ledger, 'P1')
        self.assertEqual(got['artifact_sha'], command.artifact_sha(self.root))
        self.assertEqual(got['artifact_sha'], self.receipt_artifacts()['M2'])
        self.accept(got['artifact_sha'])
        self.assertEqual(self.status(), 'accepted')

    def test_a_changed_input_still_refuses_on_the_delivery_tree(self):
        self.plan()
        (self.root / 'mot' / 'a.txt').write_text('doi\n', encoding='utf-8')
        with self.assertRaisesRegex(LedgerError, 'M1: a declared input changed'): self.accept(verdict.artifact(self.ledger, 'P1')['artifact_sha'])
        self.assertNotEqual(self.status(), 'accepted')

    def test_a_change_outside_every_input_changes_the_delivery_tree(self):
        self.plan()
        before = verdict.artifact(self.ledger, 'P1')['artifact_sha']
        (self.root / 'ngoai' / 'c.txt').write_text('doi\n', encoding='utf-8')
        self.assertNotEqual(verdict.artifact(self.ledger, 'P1')['artifact_sha'], before)

    def test_a_milestone_without_inputs_keeps_the_whole_tree(self):
        self.plan(second_inputs=None)
        got = verdict.artifact(self.ledger, 'P1')
        self.assertNotIn('scope', got)
        self.assertEqual(got['artifact_sha'], command.artifact_sha(self.root))

    def test_a_folder_without_git_never_takes_the_union(self):
        from onecrew.ledger import Ledger
        from onecrew.v2.verifiers import artifact
        plain = Path(self.temp.name) / 'khong_git'; plain.mkdir()
        (plain / 'a.txt').write_text('sample')
        ledger = Ledger(plain, self.ledger.state_root)
        plans.propose(ledger, 'Plain', owned_plan(), 'claude')
        self.assertEqual(verdict.artifact(ledger, 'Plain')['artifact_sha'], artifact.identity(plain))


if __name__ == '__main__':
    unittest.main()
