"""MEP hotfix: a command verifier that declares what it reads. Red on 9df359a (the contract refuses `inputs`), green on the fix.
A small repository with a large folder the verifier does not read. The counter is a file outside the project, one line per run of the command. Owner steps use the suite's own fixture (the suite's process is not an AI session), which is fixture evidence, not an owner's approval."""
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_v2_l2 import HookFixture, owned_plan                                          # noqa: E402
from test_v2_l1 import milestone                                                         # noqa: E402
from onecrew.ledger import LedgerError                                                   # noqa: E402
from onecrew.v2 import plan as plans, verdict                                            # noqa: E402
from onecrew.v2.verifiers import command                                                 # noqa: E402

PY = sys.executable
CHECK = "import pathlib,sys; c=pathlib.Path(sys.argv[1]); c.parent.mkdir(exist_ok=True); open(c,'a').write('x\\n'); t=pathlib.Path('tool/cfg.txt').read_text(); s=pathlib.Path('spec/a.txt').read_text(); print('doc',t.strip(),s.strip()); sys.exit(0 if 'tot' in t else 3)"


class Inputs(HookFixture):
    def setUp(self):
        super().setUp()
        for rel, text in (('tool/cfg.txt', 'tot\n'), ('spec/a.txt', 'muc\n'), ('a.txt', 'a\n'), ('README.md', 'r\n')):
            p = self.root / rel; p.parent.mkdir(exist_ok=True); p.write_text(text, encoding='utf-8')
        self.git('add', '-A'); self.git('commit', '-qm', 'nguon')
        (self.root / 'data').mkdir()
        for i in range(30): (self.root / 'data' / f'b{i}.bin').write_bytes(os.urandom(20000))
        self.counter = Path(self.temp.name) / 'dem' / 'n.txt'
        self.inputs = ['tool', 'spec/a.txt']
        self.scratch = Path(self.temp.name) / 'tam'; self.scratch.mkdir()
        old = tempfile.tempdir; tempfile.tempdir = str(self.scratch)
        self.addCleanup(setattr, tempfile, 'tempdir', old)

    def git(self, *a):
        return subprocess.run(['git', '-C', str(self.root), '-c', 'user.name=t', '-c', 'user.email=t@t', *a], check=True, capture_output=True, text=True).stdout

    def runs(self):
        return len(self.counter.read_text().splitlines()) if self.counter.exists() else 0

    def plan(self, inputs='default', argv=None, **config):
        inputs = self.inputs if inputs == 'default' else inputs
        m = milestone('M1', argv=argv or [PY, '-c', CHECK, str(self.counter)])
        if inputs: m['verifier']['config']['inputs'] = inputs
        m['verifier']['config'].update(config)
        self.enforce(value=owned_plan(milestones=[m]))

    def run_m1(self):
        return verdict.run(self.ledger, 'P1', 'M1')

    def view(self):
        return plans.show(self.ledger, 'P1')['milestones'][0]

    def receipt(self):
        with self.ledger.transaction() as conn:
            state = plans.anchor_events(self.ledger, conn, 'P1')
        from onecrew.snapshots import Snapshots
        return json.loads(Snapshots(self.ledger.state_root).read_blob(state['verdicts'][-1]['receipt']))

    def objects(self):
        return sum(p.stat().st_size for p in (self.root / '.git' / 'objects').rglob('*') if p.is_file())

    # ---- the contract
    def test_contract_refuses_bad_inputs(self):
        for bad in (['../x'], ['/abs'], ['a/*.txt'], ['.git/config'], ['.onecrew/x'], [], ['a', 'a'], 'tool', ['c:\\x']):
            m = milestone('M1'); m['verifier']['config']['inputs'] = bad
            with self.assertRaises(LedgerError, msg=str(bad)):
                plans.propose(self.ledger, 'Q' + hashlib.md5(str(bad).encode()).hexdigest()[:6], owned_plan(milestones=[m]), 'claude-opus-5-5')

    def test_no_inputs_means_the_old_contract_and_the_old_path(self):
        self.plan(inputs=None)
        self.assertNotIn('inputs', plans.show(self.ledger, 'P1')['contract']['milestones'][0]['verifier']['config'])
        self.run_m1()
        receipt = self.receipt()
        self.assertNotIn('input_scope', receipt)
        self.assertEqual(self.view()['state'], 'passed')
        self.assertEqual(receipt['artifact_sha'], command.artifact_sha(self.root))
        (self.root / 'data' / 'b0.bin').write_bytes(b'doi')
        self.assertEqual(self.view()['state'], 'pending')       # the old rule: anything in the tree makes it stale

    # ---- the run
    def test_run_holds_only_inputs_and_receipt_says_so(self):
        self.plan()
        before = self.objects()
        self.run_m1()
        receipt = self.receipt()
        self.assertEqual(receipt['exit_code'], 0)
        self.assertEqual(self.view()['state'], 'passed')
        self.assertEqual(receipt['input_scope']['paths'], self.inputs)
        self.assertEqual(receipt['snapshot']['checkout_files'], 2)
        self.assertLess(self.objects() - before, 100000)
        self.assertEqual(self.runs(), 1)
        tree = subprocess.run(['git', '-C', str(self.root), 'ls-tree', '-r', '--name-only', receipt['artifact_sha']], capture_output=True, text=True).stdout.split()
        self.assertEqual(sorted(tree), ['spec/a.txt', 'tool/cfg.txt'])

    def test_whole_tree_not_walked(self):
        self.plan()
        with patch.object(command, 'hard_links', side_effect=AssertionError('walked')), patch.object(command, 'artifact_sha', side_effect=AssertionError('hashed')):
            self.run_m1()
            self.assertEqual(self.view()['state'], 'passed')

    def test_approve_all_declared_does_not_store_the_tree(self):
        before = self.objects()
        with patch.object(command, 'hard_links', side_effect=AssertionError('walked')), patch.object(command, 'artifact_sha', side_effect=AssertionError('hashed')):
            self.plan()
        self.assertLess(self.objects() - before, 100000)

    def test_a_change_inside_makes_it_stale_a_change_outside_does_not(self):
        self.plan()
        self.run_m1()
        (self.root / 'data' / 'b0.bin').write_bytes(b'doi'); (self.root / 'moi.txt').write_text('moi'); (self.root / 'a.txt').write_text('khac')
        self.assertEqual(self.view()['state'], 'passed')
        with self.assertRaisesRegex(LedgerError, 'already passed'): self.run_m1()
        self.assertEqual(self.runs(), 1)
        for rel, text, why in (('tool/cfg.txt', 'tot khac\n', 'input'), ('tool/moi.py', 'x', 'input')):
            (self.root / rel).write_text(text)
            view = self.view()
            self.assertEqual(view['state'], 'pending'); self.assertTrue(view['stale']); self.assertIn(why, ' '.join(view['stale_reasons']))
            self.run_m1()
            self.assertEqual(self.view()['state'], 'passed')
        self.assertEqual(self.runs(), 3)

    def test_gitattributes_above_an_input_counts(self):
        self.plan()
        self.run_m1()
        (self.root / '.gitattributes').write_text('*.txt text\n')
        self.assertEqual(self.view()['state'], 'pending')

    def test_program_change_makes_it_stale(self):
        tool = Path(self.temp.name) / 'cong-cu'; tool.mkdir(); exe = tool / 'kiem.cmd'
        exe.write_text(f'@"{PY}" -c "print(1)"\n')
        self.plan(argv=[str(exe)])
        self.run_m1()
        self.assertEqual(self.view()['state'], 'passed')
        exe.write_text(f'@"{PY}" -c "print(2)"\n')
        view = self.view()
        self.assertEqual(view['state'], 'pending'); self.assertIn('program', ' '.join(view['stale_reasons']))

    def test_input_changed_during_the_run_is_not_a_pass(self):
        script = "import pathlib,sys; pathlib.Path(sys.argv[1]).write_text('doi trong luc chay\\n'); print('xong')"
        self.plan(argv=[PY, '-c', script, str(self.root / 'tool' / 'cfg.txt').replace(str(self.root), str(self.root) + '')], inputs=None)      # the old rule, as a reference
        out = self.run_m1()
        self.assertNotEqual(self.receipt()['artifact_sha'], self.receipt()['artifact_sha_after'])

    def test_absent_input_refuses_before_the_verifier_and_allows_a_new_run(self):
        self.plan(inputs=['tool', 'spec/a.txt', 'chua-co'])
        with self.assertRaisesRegex(LedgerError, 'not found'): self.run_m1()
        self.assertEqual(self.runs(), 0)
        (self.root / 'chua-co').write_text('co roi')
        self.run_m1()
        self.assertEqual(self.runs(), 1)
        self.assertEqual(self.view()['state'], 'passed')

    def test_only_ignored_input_refuses(self):
        (self.root / '.gitignore').write_text('tam/\n'); (self.root / 'tam').mkdir(); (self.root / 'tam' / 'x').write_text('x')
        self.plan(inputs=['tool', 'tam'])
        with self.assertRaisesRegex(LedgerError, 'ignored'): self.run_m1()

    def test_command_naming_a_path_outside_inputs_refuses(self):
        self.plan(argv=[PY, 'a.txt'])
        with self.assertRaisesRegex(LedgerError, 'not among the declared inputs'): self.run_m1()

    def test_command_naming_the_live_tree_by_absolute_path_refuses(self):
        self.plan(argv=[PY, str(self.root / 'tool' / 'cfg.txt')])
        with self.assertRaisesRegex(LedgerError, 'absolute path'): self.run_m1()

    def test_command_naming_the_current_folder_refuses(self):
        self.plan(argv=[PY, '.'])
        with self.assertRaisesRegex(LedgerError, 'not among'): self.run_m1()

    def test_relative_read_outside_inputs_fails_in_the_checkout(self):
        script = "import pathlib; print(pathlib.Path('a'+'.txt').read_text())"
        self.plan(argv=[PY, '-c', script])
        self.run_m1()
        self.assertNotEqual(self.receipt()['exit_code'], 0)
        self.assertNotEqual(self.view()['state'], 'passed')

    def test_hard_link_in_inputs_refuses_and_outside_does_not_matter(self):
        (self.root / 'data' / 'lien').write_text('x'); os.link(self.root / 'data' / 'lien', self.root / 'data' / 'lien2')
        self.plan()
        self.run_m1()
        self.assertEqual(self.view()['state'], 'passed')
        os.link(self.root / 'data' / 'lien', self.root / 'tool' / 'lien3')
        self.assertEqual(self.view()['state'], 'pending')
        with self.assertRaises(command.HardLinked): self.run_m1()

    def test_accept_inside_a_tree_that_holds_the_inputs(self):
        self.plan()
        self.run_m1()
        self.git('add', '-A', '--', 'tool', 'spec'); self.git('commit', '-qm', 'x', '--allow-empty')
        head = self.git('rev-parse', 'HEAD').strip()
        shown = plans.accept(self.ledger, 'P1', 'owner', 'thu', head)
        self.assertEqual(shown['status'], 'accepted')

    def test_accept_refuses_a_tree_with_other_inputs(self):
        self.plan()
        self.run_m1()
        (self.root / 'tool' / 'cfg.txt').write_text('khac\n'); self.git('add', '-A', '--', 'tool'); self.git('commit', '-qm', 'khac')
        with self.assertRaisesRegex(LedgerError, 'Cannot accept'):
            plans.accept(self.ledger, 'P1', 'owner', 'thu', self.git('rev-parse', 'HEAD').strip())

    def test_no_room_refuses_before_anything_is_written(self):
        self.plan(inputs=None)
        real = command.shutil.disk_usage
        def small(path): return real(path)._replace(free=10)
        scratch = []
        with patch.object(command.shutil, 'disk_usage', small):
            with self.assertRaisesRegex(LedgerError, 'needs about'): self.run_m1()
        self.assertEqual(self.runs(), 0)
        self.assertEqual(list(self.scratch.glob('ocv-*/src')), [])
        self.run_m1()                     # no release needed: the verifier was not called
        self.assertEqual(self.runs(), 1)

    def test_timeout_leaves_nothing(self):
        self.plan(argv=[PY, '-c', 'import time; time.sleep(120)'], max_minutes=1)
        real = subprocess.Popen.communicate
        def fake(process, *a, **k):
            if 'time.sleep(120)' in str(process.args) and k.get('timeout'): raise subprocess.TimeoutExpired(process.args, 1)
            return real(process, *a, **k)
        with patch.object(subprocess.Popen, 'communicate', fake):
            self.run_m1()
        self.assertTrue(self.receipt()['timed_out'])
        self.assertNotEqual(self.view()['state'], 'passed')
        self.assertEqual(list(self.scratch.glob('ocv-*')), [])

    def test_interrupt_kills_the_command_and_cleans(self):
        self.plan(argv=[PY, '-c', 'import time; time.sleep(120)'])
        killed = []
        real = subprocess.Popen.communicate
        def fake(process, *a, **k):
            if 'time.sleep(120)' in str(process.args): raise KeyboardInterrupt()
            return real(process, *a, **k)
        with patch.object(subprocess.Popen, 'communicate', fake), patch.object(command, '_kill_tree', side_effect=lambda p: (killed.append(p.pid), p.kill())):
            with self.assertRaises(KeyboardInterrupt): self.run_m1()
        self.assertEqual(len(killed), 1)
        self.assertEqual(list(self.scratch.glob('ocv-*')), [])

    def test_sweep_removes_only_marked_scratch_of_a_dead_process(self):
        temp = self.scratch
        dead, alive, unmarked = temp / 'ocv-chet', temp / 'ocv-song', temp / 'ocv-khong-dau'
        q = subprocess.Popen([PY, '-c', 'pass']); q.wait()
        host = os.environ.get('COMPUTERNAME') or os.uname().nodename
        for d, pid in ((dead, q.pid), (alive, os.getppid()), (unmarked, None)):
            d.mkdir(exist_ok=True)
            if pid: (d / 'owner.json').write_text(json.dumps({'pid': pid, 'host': host}))
        try:
            command._sweep_scratch()
            self.assertFalse(dead.exists()); self.assertTrue(alive.exists()); self.assertTrue(unmarked.exists())
        finally:
            for d in (dead, alive, unmarked):
                if d.exists(): command.shutil.rmtree(d)

    def test_source_not_written(self):
        self.plan()
        before = {p: p.read_bytes() for p in self.root.rglob('*') if p.is_file() and '.git' not in p.parts and '.onecrew' not in p.parts and p.parent.name != 'data'}
        status = self.git('status', '--porcelain')
        self.run_m1()
        self.assertEqual(before, {p: p.read_bytes() for p in before})
        self.assertEqual(self.git('status', '--porcelain'), status)

    def test_workflow_root_refused(self):
        self.plan(inputs=None)
        with patch.object(plans.namespaces, 'has_capability', return_value=True):
            state = {'workflow_version': 1}
            contract = {'milestones': [dict(milestone('M1'), verifier={'type': 'command', 'config': {'argv': ['x'], 'inputs': ['tool']}})]}
            self.assertIn('not supported', plans._inputs_unsupported(state, contract))


if __name__ == '__main__':
    import unittest
    unittest.main()
