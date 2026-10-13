"""Codex review of the generic execution foundation (13/10/2026), GX-P1-01..03: the core judges effects, not tools.

Each adversarial test reproduces a reviewed probe or a variant through the public runtime and is red by behaviour on
8603e74; each positive control is valid work that must still complete on both sides. Scripted workers (no model call),
real Git, the real Python on PATH and the real Windows write boundary."""
import base64
import hashlib
import json
from pathlib import Path
import subprocess
import unittest
from unittest.mock import patch

from onecrew.ledger import LedgerError
from onecrew.owned import Owned
from onecrew.owned_intake import submit
from onecrew import work_tools as wt
from tests.test_work_contract import ACCEPT, WorkFixture, action, python
from tests.test_workflow import FixtureWorker

PY = python()
FIXED = 'def add(a, b):\n    return a + b\n'


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def program(text):
    """A python -c program whose paths no argument filter can recognise: only the OS boundary can stop it."""
    return f"import base64;exec(base64.b64decode('{base64.b64encode(text.encode()).decode()}').decode())"


class SimulatedCrash(BaseException):
    """The coordinator process dies here (BaseException: nothing in the runtime may catch it)."""


class Hooked(FixtureWorker):
    def __init__(self, ledger, responses, on_review=None):
        super().__init__(ledger, responses); self.on_review = on_review

    def run(self, attempt, prompt, schema, profile):
        if json.loads(attempt['operation'])['stage'] == 'owned_review' and self.on_review: self.on_review()
        return super().run(attempt, prompt, schema, profile)


@unittest.skipIf(PY is None, 'needs a real Python interpreter on PATH')
class Base(WorkFixture):
    def open_job(self, scope=None, **authority):
        contract = self.contract(**authority)
        if scope is not None: contract['scope'] = {'paths': scope}
        runtime, task, worker = self.job(contract, [])
        state = runtime.state(task)[1]
        return runtime, task, state, runtime.control.status(task)['configuration']['profile']['contract']

    def ws(self, state):
        return Path(state['work']['workspace']['path'])

    def py(self, runtime, task, state, contract, text, **extra):
        return wt.run(runtime, task, state, contract, dict({'argv': [PY, '-c', program(text)]}, **extra), lambda: None)

    def unit(self):
        return {'verification': [{'argv': [PY, '-m', 'unittest', '-v']}]}

    def ref(self, name):
        done = subprocess.run(['git', '-C', str(self.root), 'rev-parse', '--verify', '-q', 'refs/heads/' + name], capture_output=True)
        return done.stdout.decode().strip() or None

    def fix(self, state, contract):
        root = self.ws(state)
        return wt.write(state, contract, {'path': 'calc.py', 'expected_sha256': sha(root / 'calc.py'), 'text': FIXED})


class ScopeGateTests(Base):
    """GX-P1-01: authority to run commands is not authority to change source."""

    def test_a_command_cannot_deliver_what_write_may_not(self):
        # Codex probe 1: scope src, write refused, the same change through run was committed, exported and verified.
        runtime, task, state, contract = self.open_job(scope=['src'], edit=True, commands=True, local_branches=['fix/scope'])
        with self.assertRaises(LedgerError): self.fix(state, contract)
        ran = self.py(runtime, task, state, contract, f"open('calc.py','w').write({FIXED!r})")
        self.assertEqual(ran['exit_code'], 0)
        self.assertEqual([c['path'] for c in ran.get('undeliverable_changes', [])], ['calc.py'],
                         'RED-GX-P1-01: the run receipt does not report the out-of-scope change')
        with self.assertRaises(LedgerError): wt.workspace_commit(state, contract, {'message': 'Out of scope through run'})
        with self.assertRaises(LedgerError): wt.export_branch(runtime, task, state, contract, {'name': 'fix/scope'})
        self.assertIsNone(self.ref('fix/scope'))
        findings = wt.verify(runtime, task, state, contract, self.unit(), lambda: None)['findings']
        self.assertTrue(any('calc.py' in f and 'not deliverable' in f for f in findings), findings)

    def test_commands_without_edit_authority_deliver_nothing_until_restored(self):
        runtime, task, state, contract = self.open_job(commands=True)
        ran = self.py(runtime, task, state, contract, "open('out.txt','w').write('generated')")
        self.assertEqual([c['path'] for c in ran.get('undeliverable_changes', [])], ['out.txt'],
                         'RED-GX-P1-01: a commands-only contract changed a file without the core noticing')
        survey = {'verification': [{'argv': [PY, '-c', 'print(1)']}]}
        self.assertTrue(any('out.txt' in f for f in wt.verify(runtime, task, state, contract, survey, lambda: None)['findings']))
        self.assertEqual(wt.restore(runtime, task, state, contract, {'paths': ['out.txt']})['remaining_undeliverable'], [])
        self.assertEqual(wt.verify(runtime, task, state, contract, survey, lambda: None)['findings'], [])

    def test_a_verification_command_cannot_change_the_candidate(self):
        runtime, task, state, contract = self.open_job(edit=True, commands=True)
        self.fix(state, contract)
        tamper = program("open('report.txt','w').write('r'); open('calc.py','w').write('def add(a, b):\\n    return a * b\\n')")
        result = wt.verify(runtime, task, state, contract, {'verification': [
            {'argv': [PY, '-m', 'unittest', '-v']}, {'argv': [PY, '-c', tamper]}]}, lambda: None)
        self.assertTrue(any('changed the candidate file calc.py' in f for f in result['findings']),
                        'RED-GX-P1-01: verification modified the candidate and still passed: ' + str(result['findings']))
        self.assertFalse((self.ws(state) / 'report.txt').exists())
        self.assertIn('a + b', (self.ws(state) / 'calc.py').read_text())

    def test_contained_commands_cannot_write_the_project_the_state_or_elsewhere(self):
        runtime, task, state, contract = self.open_job(commands=True)
        outside = Path(self.temp.name) / 'outside'; outside.mkdir()
        targets = [self.root / 'written-by-command.txt', Path(self.ledger.state_root) / 'written-by-command.txt',
                   outside / 'written-by-command.txt']
        ran = self.py(runtime, task, state, contract, 'import json\nout = {}\n'
                      f'for p in {[str(t) for t in targets]!r}:\n'
                      "    try: open(p, 'w').write('x'); out[p] = 'written'\n"
                      "    except OSError as e: out[p] = 'denied %s' % e.errno\n"
                      "open('inside.txt', 'w').write('ok')\nprint(json.dumps(out))")
        for target in targets:
            self.assertFalse(target.exists(), 'RED-GX-BOUNDARY: a command wrote outside the workspace: ' + str(target))
        self.assertEqual((self.ws(state) / 'inside.txt').read_text(), 'ok')
        self.assertEqual(ran.get('boundary'), 'contained')

    def test_a_command_cannot_redirect_core_git_into_the_user_repository(self):
        runtime, task, state, contract = self.open_job(edit=True, commands=True)
        before = self.snapshot()
        user = (self.root / '.git').as_posix()
        self.py(runtime, task, state, contract, "import os, shutil\n"
                "if os.path.isdir('.git'): shutil.rmtree('.git')\n"
                f"open('.git', 'w').write('gitdir: {user}\\n')\n"
                f"open('calc.py', 'w').write({FIXED!r})")
        try: wt.workspace_commit(state, contract, {'message': 'Fix add'})
        except LedgerError: pass
        self.assertEqual(self.snapshot(), before, 'RED-GX-GITFILE: a command turned a core Git operation onto the user repository')

    def test_unconfined_commands_are_a_user_grant(self):
        from onecrew.work_contract import validate
        with self.assertRaises(LedgerError): validate(self.contract(unconfined_commands=True), self.root)
        runtime, task, state, contract = self.open_job(commands=True, unconfined_commands=True)
        outside = Path(self.temp.name) / 'granted'; outside.mkdir()
        ran = self.py(runtime, task, state, contract, f"open({str(outside / 'x.txt')!r}, 'w').write('x')")
        self.assertEqual((ran['boundary'], (outside / 'x.txt').read_text()), ('unconfined', 'x'))

    def test_positive_control_in_scope_work_through_a_command_is_delivered(self):
        runtime, task, state, contract = self.open_job(scope=['src'], edit=True, commands=True, local_branches=['fix/src'])
        self.py(runtime, task, state, contract, "import os\nos.makedirs('src', exist_ok=True)\n"
                "open('src/util.py', 'w').write('VALUE = 5\\n')")
        sha_commit = wt.workspace_commit(state, contract, {'message': 'Add util'})['commit']
        self.assertEqual(wt.export_branch(runtime, task, state, contract, {'name': 'fix/src'})['status'], 'verified')
        check = {'verification': [{'argv': [PY, '-c', "import runpy; assert runpy.run_path('src/util.py')['VALUE'] == 5"]}]}
        self.assertEqual(wt.verify(runtime, task, state, contract, check, lambda: None)['findings'], [])
        self.assertEqual(self.ref('fix/src'), sha_commit)

    def test_positive_control_output_ignored_by_the_repository_is_not_delivered(self):
        (self.root / '.gitignore').write_text('build/\n'); self.git('add', '.gitignore'); self.git('commit', '-q', '-m', 'ignore build')
        runtime, task, state, contract = self.open_job(edit=True, commands=True)
        self.fix(state, contract)
        self.py(runtime, task, state, contract, "import os\nos.makedirs('build', exist_ok=True)\nopen('build/out.txt','w').write('x')")
        result = wt.verify(runtime, task, state, contract, self.unit(), lambda: None)
        self.assertEqual(result['findings'], [])
        self.assertEqual([c['path'] for c in result['changed_files']], ['calc.py'])

    def test_restore_brings_back_the_pinned_version(self):
        runtime, task, state, contract = self.open_job(scope=['src'], edit=True, commands=True)
        self.py(runtime, task, state, contract, "import os\nos.remove('test_calc.py')\nopen('calc.py','a').write('# fmt\\n')\n"
                "open('new.txt','w').write('n')")
        restored = wt.restore(runtime, task, state, contract, {'paths': ['test_calc.py', 'calc.py', 'new.txt']})
        self.assertEqual((restored['remaining_changes'], restored['remaining_undeliverable']), (0, []))
        self.assertTrue((self.ws(state) / 'test_calc.py').is_file())


class ContainTokenTests(unittest.TestCase):
    """N1-r2/N2-r1 (13/10/2026): under the Task Scheduler host (UAC off) every contained process failed with 0xC0000142,
    because the restricted token's default owner/DACL named BUILTIN\Administrators, which it holds deny-only. This
    property test is green in a chat context too (there the owner already is the user); the red/green evidence is the
    Task Scheduler probe kept in the acceptance folder."""

    def test_the_contained_token_owns_its_objects_as_the_user(self):
        import ctypes
        from ctypes import wintypes as w
        from onecrew import contain
        k, a = contain._apis(); token = contain._token(k, a)
        try:
            a.GetTokenInformation.argtypes = [w.HANDLE, ctypes.c_int, ctypes.c_void_p, w.DWORD, ctypes.POINTER(w.DWORD)]
            a.ConvertSidToStringSidW.argtypes = [ctypes.c_void_p, ctypes.POINTER(w.LPWSTR)]
            a.EqualSid.argtypes = [ctypes.c_void_p, ctypes.c_void_p]

            def info(kind):
                size = w.DWORD(); a.GetTokenInformation(token, kind, None, 0, ctypes.byref(size))
                buffer = ctypes.create_string_buffer(size.value)
                self.assertTrue(a.GetTokenInformation(token, kind, buffer, size, ctypes.byref(size)))
                return buffer
            user = ctypes.cast(info(1), ctypes.POINTER(ctypes.c_void_p))[0]
            owner = ctypes.cast(info(4), ctypes.POINTER(ctypes.c_void_p))[0]
            self.assertTrue(a.EqualSid(ctypes.c_void_p(user), ctypes.c_void_p(owner)), 'RED-GX-HOSTTOKEN: default owner is not the user')
            self.assertTrue(len(info(6).raw) > 8)  # a default DACL is set (user + SYSTEM)
        finally:
            k.CloseHandle(token)

    def test_a_windows_status_exit_is_named_not_left_as_a_decimal(self):
        hint = wt.diagnose({'stderr': '', 'stdout': '', 'stopped': None, 'exit_code': 3221225794, 'tests': {}, 'boundary': 'contained'})
        self.assertIn('0xc0000142', hint); self.assertIn('could not start', hint)


class IntentTests(Base):
    """GX-P1-02: a restart between a side effect and its receipt reconciles from evidence and never re-runs a command."""
    COUNTER = "from pathlib import Path; p=Path('counter.txt'); p.write_text(str(int(p.read_text())+1) if p.exists() else '1')"

    def crash_after(self, runtime, name):
        real = runtime._tool

        def crash(*args, **kwargs):
            result = real(*args, **kwargs)
            if args[2] == name: raise SimulatedCrash()
            return result
        return patch.object(runtime, '_tool', side_effect=crash)

    def last_receipt(self, runtime, state):
        return json.loads(runtime.store.read_blob(state['receipts'][-1]['blob']))['result']

    def test_a_command_that_ran_before_the_crash_is_not_run_again(self):
        # Codex probe 4: counter went 0 -> 1 -> 2 with a single worker call.
        runtime, task, worker = self.job(self.contract(edit=True, commands=True), [action('run', argv=[PY, '-c', self.COUNTER])])
        root = self.ws(runtime.state(task)[1])
        with self.crash_after(runtime, 'run'), self.assertRaises(SimulatedCrash): runtime.run(task, steps=1)
        self.assertEqual((root / 'counter.txt').read_text(), '1')
        restarted = Owned(self.ledger, worker); state = restarted.run(task, steps=1)
        self.assertEqual((root / 'counter.txt').read_text(), '1', 'RED-GX-P1-02: the command ran again after a coordinator restart')
        receipt = self.last_receipt(restarted, state)
        self.assertEqual((receipt.get('outcome'), receipt.get('exit_code')), ('unknown', None))
        self.assertIn('counter.txt', receipt.get('changed_paths', []))
        self.assertEqual(worker.calls, ['owned'])

    def test_a_command_interrupted_before_it_started_is_reported_not_replayed(self):
        runtime, task, worker = self.job(self.contract(edit=True, commands=True), [action('run', argv=[PY, '-c', self.COUNTER])])
        root = self.ws(runtime.state(task)[1])
        with patch('onecrew.work_tools._spawn', side_effect=SimulatedCrash()), self.assertRaises(SimulatedCrash):
            runtime.run(task, steps=1)
        state = Owned(self.ledger, worker).run(task, steps=1)
        self.assertFalse((root / 'counter.txt').exists(), 'RED-GX-P1-02: an action of unknown outcome was replayed')
        self.assertEqual(self.last_receipt(runtime, state).get('outcome'), 'unknown')

    def test_a_write_applied_before_the_crash_is_reconciled_not_failed(self):
        runtime, task, worker = self.job(self.contract(edit=True, commands=True), [])
        root = self.ws(runtime.state(task)[1])
        worker.responses = [action('write', path='calc.py', expected_sha256=sha(root / 'calc.py'), text=FIXED)]
        with self.crash_after(runtime, 'write'), self.assertRaises(SimulatedCrash): runtime.run(task, steps=1)
        state = Owned(self.ledger, worker).run(task, steps=1)
        receipt = self.last_receipt(runtime, state)
        self.assertNotIn('error', receipt, 'RED-GX-P1-02: the replayed write failed as stale instead of being reconciled')
        self.assertTrue(receipt.get('reconciled'))
        self.assertEqual((root / 'calc.py').read_text(), FIXED)

    def test_an_interrupted_verification_is_a_finding_and_is_not_run_again(self):
        marker = program("print('VERIFY-RAN')")
        runtime, task, worker = self.job(self.contract(edit=True, commands=True), [
            action('finish', report='Survey only; the core verification command prints a marker.',
                   verification=[{'argv': [PY, '-c', marker]}])])
        logs = self.ws(runtime.state(task)[1]).parent / 'logs'

        def ran():
            return sum('VERIFY-RAN' in p.read_text(errors='replace') for p in logs.glob('*.out'))
        with patch('onecrew.work_tools.test_integrity', side_effect=SimulatedCrash()), self.assertRaises(SimulatedCrash):
            runtime.run(task, steps=1)
        self.assertEqual(ran(), 1)
        state = Owned(self.ledger, worker).run(task, steps=1)
        self.assertEqual(ran(), 1, 'RED-GX-P1-02: verification commands ran again after a restart')
        self.assertTrue(any('interrupted' in f for f in state['work']['verification']['findings']))
        self.assertEqual(worker.calls, ['owned'])


class OutputBindingTests(Base):
    """GX-P1-03: evidence is bound to the candidate and to the outputs actually delivered, until completion."""

    def test_a_branch_moved_after_export_is_a_finding(self):
        # Codex probe 2: verify compared the workspace with the receipt commit, not with the ref's real value.
        runtime, task, state, contract = self.open_job(edit=True, commands=True, local_branches=['fix/ref'])
        self.fix(state, contract)
        wt.workspace_commit(state, contract, {'message': 'Fix add'})
        wt.export_branch(runtime, task, state, contract, {'name': 'fix/ref'})
        self.git('update-ref', 'refs/heads/fix/ref', self.head.strip())
        findings = wt.verify(runtime, task, state, contract, self.unit(), lambda: None)['findings']
        self.assertTrue(any('fix/ref' in f for f in findings), 'RED-GX-P1-03: a moved delivered branch verified clean')

    def test_a_stale_apply_is_a_finding_until_the_candidate_is_applied_again(self):
        # Codex probe 3: apply a wrong state, fix only the workspace, verification passed.
        (self.root / 'calc.py').write_text('def add(a, b):\n    return a - b\n')  # the user reverted their own edit
        runtime, task, state, contract = self.open_job(edit=True, commands=True, apply_to_project=True)
        root = self.ws(state)
        wt.write(state, contract, {'path': 'calc.py', 'expected_sha256': sha(root / 'calc.py'), 'text': 'def add(a, b):\n    return a * b\n'})
        self.assertEqual(wt.apply(runtime, task, state, contract, {})['status'], 'verified')
        self.fix(state, contract)
        findings = wt.verify(runtime, task, state, contract, self.unit(), lambda: None)['findings']
        self.assertTrue(any('calc.py' in f and 'differs from the verified candidate' in f for f in findings),
                        'RED-GX-P1-03: the project keeps a stale apply and verification passed: ' + str(findings))
        self.assertEqual(wt.apply(runtime, task, state, contract, {})['status'], 'verified')  # its own apply may be updated
        self.assertEqual(wt.verify(runtime, task, state, contract, self.unit(), lambda: None)['findings'], [])
        self.assertIn('a + b', (self.root / 'calc.py').read_text())

    def test_a_project_change_outside_the_applied_files_is_still_a_finding(self):
        (self.root / 'calc.py').write_text('def add(a, b):\n    return a - b\n')
        runtime, task, state, contract = self.open_job(edit=True, commands=True, apply_to_project=True)
        self.fix(state, contract)
        wt.apply(runtime, task, state, contract, {})
        (self.root / 'scratch.txt').write_text('someone else edited this during the job')
        findings = wt.verify(runtime, task, state, contract, self.unit(), lambda: None)['findings']
        self.assertTrue(any('scratch.txt' in f for f in findings), 'RED-GX-P1-03: apply exempted the whole checkout: ' + str(findings))

    def test_an_output_changed_during_the_review_is_not_completed(self):
        contract = self.contract(edit=True, commands=True, local_branches=['fix/r'])
        task = submit(self.ledger, None, 'review-race', mode='work', provider='kiro', model='claude-sonnet-5', contract=contract)['id']
        worker = Hooked(self.ledger, [], on_review=lambda: self.git('update-ref', 'refs/heads/fix/r', self.head.strip()))
        runtime = Owned(self.ledger, worker); runtime.enable(task)
        root = self.ws(runtime.state(task)[1])
        worker.responses = [action('write', path='calc.py', expected_sha256=sha(root / 'calc.py'), text=FIXED),
                            action('workspace_commit', message='Fix add'), action('export_branch', name='fix/r'),
                            action('finish', report='Fixed add, exported fix/r (receipts 0-2); unittest passes.',
                                   verification=[{'argv': [PY, '-m', 'unittest', '-v']}]), ACCEPT]
        state = runtime.run(task, steps=4)
        self.assertNotEqual(state['phase'], 'completed', 'RED-GX-P1-03: completed although the delivered branch changed during review')
        self.assertIn('changed before completion', json.loads(runtime.store.read_blob(state['receipts'][-1]['blob']))['result'].get('error', ''))

    def test_positive_control_valid_work_completes_with_a_patch_of_the_verified_candidate(self):
        contract = dict(self.contract(edit=True, commands=True, local_branches=['fix/ok']))
        runtime, task, worker = self.job(contract, [])
        root = self.ws(runtime.state(task)[1])
        worker.responses = [action('write', path='calc.py', expected_sha256=sha(root / 'calc.py'), text=FIXED),
                            action('workspace_commit', message='Fix add'), action('export_branch', name='fix/ok'),
                            action('finish', report='Fixed add, exported fix/ok (receipts 0-2); unittest passes.',
                                   verification=[{'argv': [PY, '-m', 'unittest', '-v']}]), ACCEPT]
        state = runtime.run(task)
        self.assertEqual(state['phase'], 'completed', state['message'])
        self.assertIn('+    return a + b', Path(state['work']['handover']['patch']).read_text())
        self.assertEqual(self.git('rev-parse', 'refs/heads/fix/ok').strip(), state['work']['workspace_commit'])


if __name__ == '__main__':
    unittest.main()
