"""MEP hotfix, second pass (mep2): what the inputs path must refuse or contain beyond the first pass.

- A declared input whose text spells the live tree by an absolute path, or a command word that does, refuses before the verifier: the command could read
  or write the real files beside the checkout, which the snapshot of the inputs does not see. The first pass checked only command words naming an existing path.
- An input changed by someone else while the command runs is not a pass on the inputs path (the first pass tested this rule on the old path only).
- Windows: the command and every child it starts end with the run, also when OneCrew itself is killed hard.
Owner steps use the suite's own fixture (the suite's process is not an AI session): fixture evidence, not an owner's approval."""
import json
import os
import subprocess
import sys
import tempfile
import time
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
READ = "import pathlib,sys; print(pathlib.Path('tool/cfg.txt').read_text().strip()); c=pathlib.Path(sys.argv[1]); c.parent.mkdir(exist_ok=True); open(c,'a').write('x\\n')"


def alive(pid):
    return verdict.process_alive(pid)


class LiveTree(HookFixture):
    def setUp(self):
        super().setUp()
        for rel, text in (('tool/cfg.txt', 'tot\n'), ('a.txt', 'a\n')):
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

    def plan(self, argv, inputs=('tool',), max_minutes=None):
        m = milestone('M1', argv=argv)
        if inputs: m['verifier']['config']['inputs'] = list(inputs)
        if max_minutes: m['verifier']['config']['max_minutes'] = max_minutes
        self.enforce(value=owned_plan(milestones=[m]))

    def receipt(self):
        with self.ledger.transaction() as conn:
            state = plans.anchor_events(self.ledger, conn, 'P1')
        from onecrew.snapshots import Snapshots
        return json.loads(Snapshots(self.ledger.state_root).read_blob(state['verdicts'][-1]['receipt']))

    def view(self):
        return plans.show(self.ledger, 'P1')['milestones'][0]

    def spellings(self):
        top = str(Path(command.toplevel(self.root)))
        forward = top.replace('\\', '/')
        out = [top + os.sep + 'a.txt', forward + '/a.txt', top.replace('\\', '\\\\') + '\\\\a.txt', top.upper() + os.sep + 'A.TXT' if os.name == 'nt' else top + '/a.txt']
        if os.name == 'nt' and len(top) > 2 and top[1] == ':':
            out.append('/' + top[0].lower() + forward[2:] + '/a.txt')
        return out

    # ---- a text among the inputs that spells the live tree
    def test_input_text_naming_the_live_tree_refuses_before_the_verifier(self):
        self.plan([PY, 'tool/doc.py', str(self.counter)])
        for spelled in self.spellings():
            (self.root / 'tool' / 'doc.py').write_text(f"import pathlib,sys\nprint(pathlib.Path(r'''{spelled}''').read_text())\nopen(sys.argv[1],'a').write('x\\n')\n", encoding='utf-8')
            with self.assertRaisesRegex(LedgerError, 'spells the live tree', msg=spelled) as caught:
                verdict.run(self.ledger, 'P1', 'M1')
            self.assertIs(getattr(caught.exception, 'verifier_started', None), False)
            self.assertEqual(self.runs(), 0, spelled)
            self.assertEqual(list(self.scratch.glob('ocv-*')), [])

    def test_a_refusal_leaves_a_new_run_possible(self):
        doc = self.root / 'tool' / 'doc.py'
        doc.write_text(f"print(r'{self.root / 'a.txt'}')\n", encoding='utf-8')
        self.plan([PY, 'tool/doc.py', str(self.counter)])
        with self.assertRaisesRegex(LedgerError, 'spells the live tree'): verdict.run(self.ledger, 'P1', 'M1')
        doc.write_text("import sys\nprint('tuong doi')\nopen(sys.argv[1],'a').write('x\\n')\n", encoding='utf-8')
        verdict.run(self.ledger, 'P1', 'M1')
        self.assertEqual(self.view()['state'], 'passed')
        self.assertEqual(self.runs(), 1)
        self.assertEqual(self.receipt()['input_scope']['live_tree_scan'], {'files': 2, 'not_text': 0})

    def test_a_sibling_folder_with_the_same_prefix_is_not_the_live_tree(self):
        top = str(Path(command.toplevel(self.root)))
        (self.root / 'tool' / 'doc.py').write_text(f"import sys\nprint(r'{top}-cu\\a.txt', r'{top}2/x')\nopen(sys.argv[1],'a').write('x\\n')\n", encoding='utf-8')
        self.plan([PY, 'tool/doc.py', str(self.counter)])
        verdict.run(self.ledger, 'P1', 'M1')
        self.assertEqual(self.view()['state'], 'passed')

    def test_a_command_word_naming_the_live_tree_refuses_even_when_the_path_does_not_exist(self):
        self.plan([PY, '-c', READ, str(self.counter), '--ra=' + str(self.root / 'chua-co' / 'ket-qua.txt')])
        with self.assertRaisesRegex(LedgerError, 'names the live tree'): verdict.run(self.ledger, 'P1', 'M1')
        self.assertEqual(self.runs(), 0)

    def test_binary_input_is_counted_not_scanned(self):
        (self.root / 'tool' / 'du-lieu.bin').write_bytes(b'\0\1' + str(self.root).encode() + b'\0')
        self.plan([PY, '-c', READ, str(self.counter)])
        verdict.run(self.ledger, 'P1', 'M1')
        self.assertEqual(self.view()['state'], 'passed')
        self.assertEqual(self.receipt()['input_scope']['live_tree_scan'], {'files': 1, 'not_text': 1})

    def test_without_inputs_the_old_path_is_unchanged(self):
        (self.root / 'tool' / 'doc.py').write_text(f"import sys\nprint(open(r'{self.root / 'a.txt'}').read())\nopen(sys.argv[1],'a').write('x\\n')\n", encoding='utf-8')
        self.git('add', '-A'); self.git('commit', '-qm', 'doc')
        self.plan([PY, 'tool/doc.py', str(self.counter)], inputs=None)
        verdict.run(self.ledger, 'P1', 'M1')
        self.assertEqual(self.view()['state'], 'passed')
        self.assertNotIn('input_scope', self.receipt())
        (self.root / 'a.txt').write_text('khac\n')                       # the old path judges the whole tree: a change anywhere makes it stale
        self.assertEqual(self.view()['state'], 'pending')

    # ---- an input changed by someone else while the command runs (inputs path)
    def test_input_changed_by_another_during_the_run_is_not_a_pass(self):
        self.plan([PY, '-c', READ, str(self.counter)])
        real = subprocess.Popen.communicate

        def meanwhile(process, *a, **k):
            if READ in list(process.args): (self.root / 'tool' / 'cfg.txt').write_text('doi giua luot\n')
            return real(process, *a, **k)
        with patch.object(subprocess.Popen, 'communicate', meanwhile):
            verdict.run(self.ledger, 'P1', 'M1')
        receipt = self.receipt()
        self.assertEqual(receipt['exit_code'], 0)
        self.assertNotEqual(receipt['artifact_sha'], receipt['artifact_sha_after'])
        self.assertEqual(command.expected_result(receipt), 'inconclusive')
        self.assertNotEqual(self.view()['state'], 'passed')

    # ---- Windows: nothing the command starts outlives the run
    @unittest.skipUnless(os.name == 'nt', 'job objects are Windows')
    def test_a_child_left_running_is_ended_and_counted(self):
        script = "import subprocess,sys,pathlib; c=subprocess.Popen([sys.executable,'tool/ngu.py']); print('con',c.pid,flush=True); open(sys.argv[1],'a').write('x\\n')"
        (self.root / 'tool' / 'ngu.py').write_text('import time\ntime.sleep(120)\n')
        self.plan([PY, '-c', script, str(self.counter)])
        verdict.run(self.ledger, 'P1', 'M1')
        receipt = self.receipt()
        from onecrew.snapshots import Snapshots
        out = Snapshots(self.ledger.state_root).read_blob(receipt['stdout']).decode()
        child = int(out.split()[1])
        self.assertTrue(receipt['snapshot']['contained'])
        self.assertGreaterEqual(receipt['snapshot']['left_running'], 1)       # a venv python is a launcher plus the interpreter: two processes
        time.sleep(0.5)
        self.assertFalse(alive(child))

    @unittest.skipUnless(os.name == 'nt', 'job objects are Windows')
    def test_hard_kill_of_the_runner_ends_the_command_and_its_child(self):
        work = Path(self.temp.name) / 'giet'; work.mkdir()
        (work / 'ngu.py').write_text('import time\ntime.sleep(120)\n')
        (work / 'cha.py').write_text("import subprocess,sys,time\nc=subprocess.Popen([sys.executable,'ngu.py'])\nprint('con',c.pid,flush=True)\ntime.sleep(120)\n")
        runner = work / 'chay.py'
        runner.write_text(
            "import subprocess,sys,time\n"
            f"sys.path.insert(0, r'{Path(command.__file__).resolve().parents[3]}')\n"
            "from onecrew.v2.verifiers import command\n"
            "job = command._Job()\n"
            "p = subprocess.Popen([sys.executable,'cha.py'], stdout=subprocess.PIPE, creationflags=0x08000000 | job.flags())\n"
            "job.adopt(p)\n"
            "line = p.stdout.readline().decode()\n"
            "print('cha', p.pid, line.split()[1], job.active, flush=True)\n"
            "time.sleep(120)\n", encoding='utf-8')
        holder = subprocess.Popen([PY, str(runner)], cwd=str(work), stdout=subprocess.PIPE)
        try:
            parts = holder.stdout.readline().decode().split()
            parent, child, contained = int(parts[1]), int(parts[2]), parts[3]
            self.assertEqual(contained, 'True')
            self.assertTrue(alive(parent)); self.assertTrue(alive(child))
            holder.kill(); holder.wait(30)                                # TerminateProcess: no Python cleanup runs in the runner
            for _ in range(50):
                if not alive(parent) and not alive(child): break
                time.sleep(0.1)
            self.assertFalse(alive(parent)); self.assertFalse(alive(child))
        finally:
            if holder.poll() is None: holder.kill()

    def test_host_name_without_computername(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop('COMPUTERNAME', None)
            self.assertTrue(command._host())


if __name__ == '__main__':
    unittest.main()
