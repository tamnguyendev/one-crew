"""MEP hotfix, fourth pass (mep4): inputs the owner exempts from the live-tree text scan.

On the real MEP repository four inputs of the M1 check mention where the repository lives (a ledger of cycles, a limitations register, a review, a replay
script). The check only tests that they exist; mep3 refused the whole run. mep4 lets the contract name such inputs in `inputs_unscanned`: the owner approves
each one, the receipt lists them, and everything else keeps the mep2 refusal. The command line is never exempt.
Owner steps use the suite's own fixture (the suite's process is not an AI session): fixture evidence, not an owner's approval."""
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_v2_l2 import HookFixture, owned_plan                                          # noqa: E402
from test_v2_l1 import milestone                                                         # noqa: E402
from onecrew.ledger import LedgerError                                                   # noqa: E402
from onecrew.v2 import plan as plans, verdict                                            # noqa: E402
from onecrew.v2.verifiers import command                                                 # noqa: E402
import subprocess                                                                        # noqa: E402

PY = sys.executable
CHECK = "import pathlib,sys; print([pathlib.Path(p).exists() for p in ('tool/so.md','tool/doc.md')]); open(sys.argv[1],'a').write('x\\n')"


class Unscanned(HookFixture):
    def setUp(self):
        super().setUp()
        top = str(Path(command.toplevel(self.root)))
        for rel, text in (('tool/cfg.txt', 'tot\n'), ('tool/so.md', f'Repo nam o `{top}` (ghi chep).\n'), ('tool/doc.md', 'khong co duong dan\n'), ('a.txt', 'a\n')):
            p = self.root / rel; p.parent.mkdir(exist_ok=True); p.write_text(text, encoding='utf-8')
        self.git('add', '-A'); self.git('commit', '-qm', 'nguon')
        self.counter = Path(self.temp.name) / 'dem' / 'n.txt'; self.counter.parent.mkdir()
        self.scratch = Path(self.temp.name) / 'tam'; self.scratch.mkdir()
        old = tempfile.tempdir; tempfile.tempdir = str(self.scratch)
        self.addCleanup(setattr, tempfile, 'tempdir', old)

    def git(self, *a):
        return subprocess.run(['git', '-C', str(self.root), '-c', 'user.name=t', '-c', 'user.email=t@t', *a], check=True, capture_output=True, text=True).stdout

    def runs(self):
        return len(self.counter.read_text().splitlines()) if self.counter.exists() else 0

    def plan(self, argv=None, inputs=('tool',), unscanned=None, cwd=None):
        m = milestone('M1', argv=argv or [PY, '-c', CHECK, str(self.counter)])
        m['verifier']['config']['inputs'] = list(inputs) if inputs else None
        if not inputs: m['verifier']['config'].pop('inputs')
        if unscanned is not None: m['verifier']['config']['inputs_unscanned'] = list(unscanned)
        if cwd: m['verifier']['config']['cwd'] = cwd
        self.enforce(value=owned_plan(milestones=[m]))

    def receipt(self):
        with self.ledger.transaction() as conn:
            state = plans.anchor_events(self.ledger, conn, 'P1')
        from onecrew.snapshots import Snapshots
        return json.loads(Snapshots(self.ledger.state_root).read_blob(state['verdicts'][-1]['receipt']))

    def view(self):
        return plans.show(self.ledger, 'P1')['milestones'][0]

    # ---- the run
    def test_without_an_exemption_a_document_naming_the_repository_refuses(self):
        self.plan()
        with self.assertRaisesRegex(LedgerError, "'tool/so.md' spells the live tree"): verdict.run(self.ledger, 'P1', 'M1')
        self.assertEqual(self.runs(), 0)

    def test_an_exempt_document_passes_and_the_receipt_lists_it(self):
        self.plan(unscanned=['tool/so.md'])
        verdict.run(self.ledger, 'P1', 'M1')
        self.assertEqual(self.view()['state'], 'passed')
        self.assertEqual(self.runs(), 1)
        self.assertEqual(self.receipt()['input_scope']['live_tree_scan'], {'files': 2, 'not_text': 0, 'unscanned': 1, 'unscanned_paths': ['tool/so.md']})

    def test_another_input_naming_the_repository_still_refuses(self):
        (self.root / 'tool' / 'doc.md').write_text(f'cung o {command.toplevel(self.root)}\\a.txt\n', encoding='utf-8')
        self.plan(unscanned=['tool/so.md'])
        with self.assertRaisesRegex(LedgerError, "'tool/doc.md' spells the live tree"): verdict.run(self.ledger, 'P1', 'M1')
        self.assertEqual(self.runs(), 0)

    def test_an_exempt_folder_covers_what_is_inside(self):
        self.plan(unscanned=['tool'], argv=[PY, '-c', CHECK, str(self.counter)])
        verdict.run(self.ledger, 'P1', 'M1')
        self.assertEqual(self.receipt()['input_scope']['live_tree_scan']['unscanned'], 3)

    def test_the_command_line_is_never_exempt(self):
        self.plan(unscanned=['tool'], argv=[PY, '-c', CHECK, str(self.counter), '--ra=' + str(self.root / 'tool' / 'chua-co.md')])   # not yet there: the mep2 check
        with self.assertRaisesRegex(LedgerError, 'names the live tree'): verdict.run(self.ledger, 'P1', 'M1')
        self.assertEqual(self.runs(), 0)

    def test_an_exempt_input_still_makes_old_evidence_stale(self):
        self.plan(unscanned=['tool/so.md'])
        verdict.run(self.ledger, 'P1', 'M1')
        (self.root / 'tool' / 'so.md').write_text('doi\n', encoding='utf-8')
        self.assertEqual(self.view()['state'], 'pending')

    def test_without_the_field_the_receipt_keeps_the_mep3_shape(self):
        (self.root / 'tool' / 'so.md').write_text('khong co duong dan\n', encoding='utf-8')
        self.plan()
        verdict.run(self.ledger, 'P1', 'M1')
        self.assertEqual(self.receipt()['input_scope']['live_tree_scan'], {'files': 3, 'not_text': 0})

    # ---- the contract
    def test_contract_refuses_an_exemption_outside_the_inputs(self):
        with self.assertRaisesRegex(LedgerError, 'not one of the inputs'): self.plan(unscanned=['a.txt'])

    def test_contract_refuses_an_exemption_without_inputs(self):
        with self.assertRaisesRegex(LedgerError, 'only with inputs'): self.plan(inputs=None, unscanned=['tool/so.md'])

    def test_contract_refuses_exempting_the_program_the_command_runs(self):
        (self.root / 'tool' / 'kiem.py').write_text('print(1)\n', encoding='utf-8')
        for exempt in ('tool/kiem.py', 'tool'):
            with self.assertRaisesRegex(LedgerError, 'named by the command line', msg=exempt): self.plan(argv=[PY, 'tool/kiem.py'], unscanned=[exempt])
        with self.assertRaisesRegex(LedgerError, 'named by the command line'): self.plan(argv=[PY, 'kiem.py'], cwd='tool', unscanned=['tool/kiem.py'])
        with self.assertRaisesRegex(LedgerError, 'named by the command line'): self.plan(argv=[PY, '.\\tool\\kiem.py'], unscanned=['tool/kiem.py'])

    def test_contract_refuses_duplicates_and_empty_lists(self):
        with self.assertRaisesRegex(LedgerError, 'listed twice'): self.plan(unscanned=['tool/so.md', 'tool/so.md'])
        with self.assertRaisesRegex(LedgerError, '1 to 200'): self.plan(unscanned=[])


if __name__ == '__main__':
    unittest.main()
