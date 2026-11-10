"""MEP hotfix, fifth pass (mep5): accepting a plan whose milestones declare different inputs.

On a trial project (08/11, a plan at rev 4) M1, M2 and M3 passed, each with its own inputs. A receipt's artifact_sha is the tree of
that milestone's inputs only, and `owner accept` judges every milestone inside the one tree it is given: M3's sha refused with "M1: a declared input changed"
although nothing had changed. `verdict artifact --plan` then gave the whole working tree (tens of GB there). mep5: when every milestone declares inputs,
`verdict artifact` answers with the tree of the union of the inputs, and the refusal says where to get it. A change to any input still refuses.
Owner steps use the suite's own fixture (the suite's process is not an AI session): fixture evidence, not an owner's approval."""
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
        with self.assertRaisesRegex(LedgerError, r'M1: a declared input changed.*verdict artifact --plan P1'): self.accept(shas['M2'])
        self.assertNotEqual(self.status(), 'accepted')

    def test_verdict_artifact_gives_the_union_and_accept_takes_it(self):
        self.plan()
        got = verdict.artifact(self.ledger, 'P1')
        self.assertEqual((got['scope'], got['inputs']), ('inputs', ['hai', 'mot']))
        self.assertEqual(got['artifact_sha'], command.scoped_tree(self.root, ['hai', 'mot']))
        self.accept(got['artifact_sha'])
        self.assertEqual(self.status(), 'accepted')

    def test_a_changed_input_still_refuses_with_the_union(self):
        self.plan()
        (self.root / 'mot' / 'a.txt').write_text('doi\n', encoding='utf-8')
        with self.assertRaisesRegex(LedgerError, 'M1: a declared input changed'): self.accept(verdict.artifact(self.ledger, 'P1')['artifact_sha'])
        self.assertNotEqual(self.status(), 'accepted')

    def test_a_change_outside_every_input_leaves_the_union_alone(self):
        self.plan()
        before = verdict.artifact(self.ledger, 'P1')['artifact_sha']
        (self.root / 'ngoai' / 'c.txt').write_text('doi\n', encoding='utf-8')
        self.assertEqual(verdict.artifact(self.ledger, 'P1')['artifact_sha'], before)

    def test_a_milestone_without_inputs_keeps_the_whole_tree(self):
        self.plan(second_inputs=None)
        got = verdict.artifact(self.ledger, 'P1')
        self.assertNotIn('scope', got)
        self.assertEqual(got['artifact_sha'], command.artifact_sha(self.root))

    def test_a_folder_without_git_never_takes_the_union(self):
        from types import SimpleNamespace
        plain = Path(self.temp.name) / 'khong_git'; plain.mkdir()
        self.assertIsNone(verdict.inputs_union(SimpleNamespace(project=str(plain)), {}))     # scoped_tree needs Git; such a folder keeps its manifest identity


if __name__ == '__main__':
    unittest.main()
