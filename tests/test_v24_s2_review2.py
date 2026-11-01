"""2.4-S2, Codex review round 1 on 2.4.0.dev2 (D:/OneCrewRuns/v24/codex-r1/plan.md rows F1, F2).

F1 (P1): the evidence that a venv holds the bound wheel was the venv's own installed RECORD (importlib.metadata), so a site-packages file
changed or deleted with RECORD left intact passed (Codex runtime_probe: diagnostics.py appended, after_problems []). Expected: the content of
every installed file is hashed and compared with the VERIFIED wheel's RECORD rows (art['rows']); the executable is run and the files the
interpreter itself reports loading must be files of that wheel inside that venv (or the standard library).
  * RealVenvIdentity uses the REAL runtime: a venv made by `python -m venv`, the real wheel of this checkout installed by pip. The
    mutations are fixture tampering of that test-owned venv, undone after each test (or made on a test-owned copy).

F2 (P1): `_rollback` copied and drilled each consumer's data, and only then took the fence, so a write between the copy and the fence
became the baseline without being drilled (Codex rollback_probe: data_changed_since_drill true, result rolled_back). Expected: the fence is
taken BEFORE the copy, the copy must hold exactly the fenced data, the fence is compared again at the safe point and again after the hooks
are rewritten; a change at any boundary refuses (or, after the repoint, records a switch window violation), never rolled_back/switched for an
undrilled state.
  * RollbackWindow / InstallWindow: FAULT INJECTION on the fake runtime of test_v24_s2_apply (S2Fixture): a write to the customer root
    is injected at each boundary by wrapping the hotfix step that runs there. The ledger, the engine, the authority check and the hooks are
    real; the venv side is the fake.
  * The same rollback window on REAL venvs (the old runtime drills a copy through its own `onecrew` executable) runs at the end of
    tests/test_v24_s2_installed.py (fault injection of the write timing, real runtime for everything else).
"""
import hashlib
import json
import marshal
import os
import shutil
import sqlite3
import unittest
from pathlib import Path
from unittest.mock import patch

from onecrew.v2 import plan as plans
from tests import wf_wheel as wh
from tests.test_v24_s2_apply import S2Fixture, hotfix, rows_of


class RealVenvIdentity(unittest.TestCase):
    """REAL runtime: one venv for the class, the real wheel of this checkout, pip-installed. Every test undoes its tampering."""

    @classmethod
    def setUpClass(cls):
        cls.runs = Path(wh._runs())
        wheel, cls.version, _ = wh.build_wheel(cls.runs)
        cls.python = wh.make_venv(cls.runs)
        wh.install(cls.python, wheel)
        cls.venv = cls.python.parent.parent
        cls.site = cls.venv / 'Lib' / 'site-packages'
        cls.art = {'version': cls.version, 'rows': rows_of(wheel.read_bytes())}
        cls.record = next(cls.site.glob('onecrew-*.dist-info')) / 'RECORD'
        # round 2 (R2-01): the creation baseline the product records right after it made and checked the venv
        maker = getattr(hotfix(), 'venv_baseline', None)
        cls.baseline = maker(cls.venv, cls.art) if maker else None

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.runs, ignore_errors=True)

    def keep(self, path):
        """Restore `path` (bytes or absence) after the test; RECORD is checked unchanged by every tampering test."""
        path = Path(path)
        saved = path.read_bytes() if path.exists() else None
        record = self.record.read_bytes()

        def restore():
            if saved is None: path.unlink(missing_ok=True)
            else: path.write_bytes(saved)
        self.addCleanup(restore)
        self.addCleanup(lambda: self.assertEqual(self.record.read_bytes(), record, 'the installed RECORD must stay as pip wrote it'))
        return saved

    def problems(self, venv=None):
        return hotfix().verify_installed(venv or self.venv, self.art)[0]

    def test_f1_intact_venv_has_no_problems(self):
        self.assertEqual(self.problems(), [])

    def test_f1_codex_probe_appended_bytes_record_kept(self):
        """Codex runtime_probe exactly: bytes appended to onecrew/v2/diagnostics.py, RECORD intact."""
        target = self.site / 'onecrew' / 'v2' / 'diagnostics.py'
        self.keep(target)
        with target.open('ab') as handle: handle.write(b'\n# isolated corruption probe\n')
        found = self.problems()
        self.assertTrue(found); self.assertIn('onecrew/v2/diagnostics.py', ' '.join(found))

    def test_f1_modified_file_record_kept(self):
        target = self.site / 'onecrew' / 'v2' / 'cli.py'                # a module `onecrew --version` really imports
        self.keep(target)
        target.write_bytes(target.read_bytes().replace(b'def main(argv=None):', b'def main(argv=None):  # changed', 1))
        found = self.problems()
        self.assertIn('onecrew/v2/cli.py', ' '.join(found))

    def test_f1_deleted_file_record_kept(self):
        target = self.site / 'onecrew' / 'v2' / 'support.py'
        self.keep(target)
        target.unlink()
        self.assertIn('onecrew/v2/support.py', ' '.join(self.problems()))

    def test_f1_extra_code_file_in_the_package(self):
        target = self.site / 'onecrew' / 'v2' / 'evil.py'
        self.keep(target)
        target.write_text('import os\n', encoding='utf-8')
        self.assertIn('onecrew/v2/evil.py', ' '.join(self.problems()))

    def test_f1_startup_code_in_a_pth_file(self):
        target = self.site / 'zz-fixture.pth'
        self.keep(target)
        target.write_text('import os\n', encoding='utf-8')
        self.assertIn('zz-fixture.pth', ' '.join(self.problems()))

    def test_f1_tampered_bytecode_cache_that_python_would_load(self):
        """A .pyc keeps the header of the right source (so Python loads it instead of the source) but holds other code."""
        source = self.site / 'onecrew' / 'v2' / 'messages.py'
        cache = source.parent / '__pycache__' / f'messages.{__import__("sys").implementation.cache_tag}.pyc'
        self.assertTrue(cache.is_file(), 'pip compiles the wheel at install')
        saved = self.keep(cache)
        cache.write_bytes(saved[:16] + marshal.dumps(compile('raise SystemExit(7)\n', str(source), 'exec')))
        found = self.problems()
        self.assertIn('messages', ' '.join(found)); self.assertIn('.pyc', ' '.join(found))

    def test_f1_wrong_entrypoint_module_origin(self):
        """A copy of the venv holds byte-identical files, but its onecrew executable runs the ORIGINAL venv's interpreter, so the module
        tree it executes is not inside the copy."""
        copy = self.runs / 'copy-venv'
        shutil.copytree(self.venv, copy)
        self.addCleanup(shutil.rmtree, copy, True)
        found = self.problems(copy)
        self.assertTrue(found)
        self.assertTrue(any('outside' in p or 'did not load' in p for p in found), found)


class RealVenvRound2(unittest.TestCase):
    """Round 2 review (review-s2-r2.md R2-01, R2-03, R2-04, R2-05, R2-11), REAL runtime: one real venv with the real wheel, judged against
    the creation baseline (venv_baseline) the product records; every tampering is undone after its test."""

    setUpClass = classmethod(RealVenvIdentity.setUpClass.__func__)
    tearDownClass = classmethod(RealVenvIdentity.tearDownClass.__func__)
    keep = RealVenvIdentity.keep

    def problems(self, venv=None, spy=None):
        if self.baseline is None: self.fail('no venv_baseline in hotfix (round 2 not implemented)')
        return hotfix().verify_installed(venv or self.venv, self.art, baseline=self.baseline)[0]

    def launched(self, venv):
        """verify_installed under a spy of hotfix.run: the programs it started from inside `venv`."""
        started, real = [], hotfix().run
        def spy(argv, *args, **kwargs):
            started.append(str(argv[0]))
            return real(argv, *args, **kwargs)
        with patch.object(hotfix(), 'run', spy):
            found = self.problems(venv)
        inside = [a for a in started if Path(a).resolve().is_relative_to(Path(venv).resolve())]
        return found, inside

    def test_R2_01_control_intact_venv_matches_its_baseline(self):
        found, inside = self.launched(self.venv)
        self.assertEqual(found, [])
        self.assertTrue(inside)                                                        # the checks that run programs did run

    def test_R2_01a_tampered_launcher_refused_without_running_it(self):
        exe = self.venv / 'Scripts' / 'onecrew.exe'
        saved = self.keep(exe)
        start = saved.rfind(b'PK\x03\x04')
        import io, zipfile
        main = zipfile.ZipFile(io.BytesIO(saved[start:])).read('__main__.py').decode()
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, 'w') as archive: archive.writestr('__main__.py', 'import os\n' + main)
        exe.write_bytes(saved[:start] + buffer.getvalue())
        found, inside = self.launched(self.venv)
        self.assertIn('Scripts/onecrew.exe', ' '.join(found)); self.assertEqual(inside, [])

    def test_R2_01b_bom_pth_and_undecodable_pth_refused(self):
        target = self.site / 'zz-bom.pth'
        self.keep(target)
        target.write_bytes(b'\xef\xbb\xbfimport os\n')
        self.assertIn('zz-bom.pth', ' '.join(self.problems()))
        target.write_bytes(b'\xff\xfe\xfa bad\n')
        self.assertIn('zz-bom.pth', ' '.join(self.problems()))

    def test_R2_01c_pyvenv_home_redirect_or_system_site_refused(self):
        cfg = self.venv / 'pyvenv.cfg'
        saved = self.keep(cfg).decode('utf-8')
        cfg.write_text(saved.replace('include-system-site-packages = false', 'include-system-site-packages = true'), encoding='utf-8')
        found, inside = self.launched(self.venv)
        self.assertIn('pyvenv.cfg', ' '.join(found)); self.assertEqual(inside, [])
        lines = [('home = ' + str(self.runs)) if line.startswith('home') else line for line in saved.splitlines()]
        cfg.write_text('\n'.join(lines) + '\n', encoding='utf-8')
        found, inside = self.launched(self.venv)
        self.assertIn('pyvenv.cfg', ' '.join(found)); self.assertEqual(inside, [])

    def test_R2_01d_replaced_venv_python_refused_without_running_it(self):
        python = self.venv / 'Scripts' / 'python.exe'
        saved = self.keep(python)
        python.write_bytes(saved + b'\0')
        found, inside = self.launched(self.venv)
        self.assertIn('Scripts/python.exe', ' '.join(found)); self.assertEqual(inside, [])

    def test_R2_05_unknown_module_at_the_site_packages_root_refused(self):
        target = self.site / 'pwd.py'
        self.keep(target)
        target.write_text('import os\n', encoding='utf-8')
        found, inside = self.launched(self.venv)
        self.assertIn('pwd.py', ' '.join(found)); self.assertEqual(inside, [])

    def test_R2_03_planted_folder_refused_with_no_program_started_from_it(self):
        planted = self.runs / 'planted-venv'
        (planted / 'Lib' / 'site-packages').mkdir(parents=True)
        shutil.copytree(self.venv / 'Scripts', planted / 'Scripts')
        (planted / 'pyvenv.cfg').write_bytes((self.venv / 'pyvenv.cfg').read_bytes())
        self.addCleanup(shutil.rmtree, planted, True)
        found, inside = self.launched(planted)
        self.assertTrue(found); self.assertEqual(inside, [])

    def test_R2_04_venv_without_a_bytecode_cache_is_accepted(self):
        cache = next((self.site / 'onecrew' / '__pycache__').glob('console.*.pyc'))
        self.keep(cache)
        cache.unlink()
        self.assertEqual(self.problems(), [])

    def test_R2_11_leftover_importlib_temp_file_is_ignored(self):
        cache = next((self.site / 'onecrew' / 'v2' / '__pycache__').glob('messages.*.pyc'))
        leftover = cache.with_name(cache.name + '.123456')
        self.keep(leftover)
        leftover.write_bytes(b'partial')
        self.assertEqual(self.problems(), [])


class Window:
    """Fault injection helpers: a write on the customer root P1 (a row the fence must see) and the guard of what a refusal leaves alone."""

    def write(self, label):
        with self.ledger.transaction(write=True) as conn:
            task = plans.derive(self.ledger, conn, 'P1')['task_id']
            plans.emit(self.ledger, conn, task, 'notice.exception', {'version': 1, 'category': 'deadline', 'cause': label, 'reason': label,
                                                                    'evidence': ['fixture'], 'plan': 'P1'})
        self.injected.append(label)

    def once(self, real, label, after=False):
        """Wrap a hotfix step: the write happens once, before (or right after) the real step."""
        def wrapped(*args, **kwargs):
            if not after and label not in self.injected: self.write(label)
            result = real(*args, **kwargs)
            if after and label not in self.injected: self.write(label)
            return result
        return wrapped

    def guard(self):
        """Every row outside the support anchor, except the audit rows authority.enforce adds on the FIX root at each decision (S2-R14:
        decision.recorded and its context.entry mirror)."""
        with self.fix.transaction() as conn:
            fix_root = plans.derive(self.fix, conn, 'FIX1')['task_id']
        rows = self.others()
        rows['events'] = [r for r in rows['events'] if not (r[1] == fix_root and r[2] in ('decision.recorded', 'context.entry'))]
        return rows

    def assert_untouched(self, before, settings):
        after = self.guard()
        added = [r for r in after['events'] if r not in before['events']]
        self.assertEqual([json.loads(r[3])['cause'] for r in added if r[2] == 'notice.exception'], self.injected)
        self.assertEqual(len(added), len(self.injected), added)                     # only the injected writes: nothing replaced or lost
        for table in after:
            if table != 'events': self.assertEqual(after[table], before[table], table)   # budget, attempts, actions, requests, tasks
        with self.fix.transaction() as conn:
            state = plans.derive(self.fix, conn, 'FIX1')
        self.assertEqual(state['status'], 'approved')
        self.assertEqual(self.settings_exe(), settings)

    def live_has_injected(self):
        conn = sqlite3.connect(self.ledger.path)
        try:
            return [json.loads(r[0])['cause'] for r in conn.execute("SELECT payload FROM events WHERE kind='notice.exception'")]
        finally:
            conn.close()


class RollbackWindow(Window, S2Fixture):
    """FAULT INJECTION on the fake runtime: rollback after a switched install and a passing recheck at the target."""

    def setUp(self):
        super().setUp()
        self.injected = []
        self.ready()
        code, made = self.install()
        self.assertEqual(made['result'], 'switched', made)
        self.assertEqual(self.cli('support', 'recheck', self.fb)[1]['result'], 'pass')
        self.new = self.settings_exe()

    def rollback(self):
        return self.owner('support', 'rollback', self.fb)

    def refused_at(self, step, label, after=False, expect='refused'):
        before = self.guard()
        real = getattr(hotfix(), step)
        with patch.object(hotfix(), step, self.once(real, label, after)):
            code, made = self.rollback()
        self.assertEqual(code, 0, made)
        self.assertNotEqual(made['result'], 'rolled_back', made)
        self.assertEqual(made['result'], expect, made)
        self.assertIn('changed', json.dumps(made['problems']))
        self.assertEqual(self.live_has_injected(), self.injected)                     # the new ledger is kept, never an old copy over it
        return before, made

    def test_f2_unchanged_control_rolls_back(self):
        code, made = self.rollback()
        self.assertEqual(made['result'], 'rolled_back', made)
        self.assertEqual(self.settings_exe(), {str(self.old_exe.resolve())})
        self.assertEqual(made['fences']['drilled'], made['fences']['at_switch'])

    def test_f2_change_before_the_copy(self):
        before, made = self.refused_at('copy_state', 'before copy')
        self.assert_untouched(before, self.new)

    def test_f2_change_after_the_copy_before_the_drill(self):
        before, made = self.refused_at('_read_check', 'after copy, before drill')
        self.assert_untouched(before, self.new)

    def test_f2_change_after_the_drill_before_the_fence_codex_probe(self):
        """Codex rollback_probe: the write lands while the old runtime classifies the kinds, after the copy was drilled."""
        before, made = self.refused_at('event_classes', 'after drill, before fence')
        self.assert_untouched(before, self.new)

    def test_f2_change_after_the_safe_point_before_the_repoint(self):
        # round 2: the fence is compared again right before the first hook file is written: refused, nothing switched
        before, made = self.refused_at('repoint', 'after safe point, before repoint')
        self.assert_untouched(before, self.new)
        code, again = self.rollback()
        self.assertEqual(again['result'], 'rolled_back', again)
        self.assertIn('notice.exception', json.dumps(again['reader_pair']))

    def test_f2_change_during_the_repoint_is_a_rollback_violation_then_recoverable(self):
        before, made = self.refused_at('repoint', 'during the repoint', after=True, expect='switch_window_violation')
        self.assertTrue(self.status()['still_blocked']['value'])
        # the owner runs the rollback again: the second drill holds the write, the decision is bound to it
        code, again = self.rollback()
        self.assertEqual(again['result'], 'rolled_back', again)
        self.assertIn('notice.exception', json.dumps(again['reader_pair']))
        self.assertEqual(again['fences']['drilled'], again['fences']['at_switch'])

    def test_f2_crash_after_the_drill_then_a_write_then_retry(self):
        with patch.dict(os.environ, {'ONECREW_SUPPORT_CRASH': 'rollback_after_drill'}):
            with self.assertRaises(hotfix().Crash):
                self.rollback()
        self.assertEqual(self.settings_exe(), self.new)
        self.write('between the crash and the retry')
        code, made = self.rollback()
        self.assertEqual(made['result'], 'rolled_back', made)                         # drilled again, on data that holds the write
        self.assertIn('notice.exception', json.dumps(made['reader_pair']))
        self.assertEqual(made['fences']['drilled'], made['fences']['at_switch'])
        self.assertEqual(made['fences']['at_switch'][str(self.ledger.state_root.resolve())], hotfix().fence(self.ledger.state_root))


class InstallWindow(Window, S2Fixture):
    """FAULT INJECTION on the fake runtime: the same boundaries on the install side (its fence was already taken before the copy)."""

    def setUp(self):
        super().setUp()
        self.injected = []
        self.ready()
        self.old = {str(self.old_exe.resolve())}

    def refused_at(self, step, label, expect):
        before = self.guard()
        real = getattr(hotfix(), step)
        with patch.object(hotfix(), step, self.once(real, label)):
            code, made = self.install()
        self.assertEqual(code, 0, made)
        self.assertEqual(made['result'], expect, made)
        self.assertIn('changed', json.dumps(made['problems']))
        self.assertEqual(self.live_has_injected(), self.injected)
        return before, made

    def test_f2_install_change_before_the_copy(self):
        before, made = self.refused_at('copy_state', 'before copy', 'refused_unsafe')
        self.assert_untouched(before, self.old)

    def test_f2_install_change_after_the_copy_before_the_drill(self):
        before, made = self.refused_at('_read_check', 'after copy, before drill', 'refused_unsafe')
        self.assert_untouched(before, self.old)

    def test_f2_install_change_after_the_safe_point_before_the_repoint(self):
        # round 2 (R2-02): the fence is compared again right before the first hook file is written, so nothing is switched
        before, made = self.refused_at('repoint', 'after safe point, before repoint', 'refused_unsafe')
        self.assert_untouched(before, self.old)
        self.assertFalse(self.status()['installed']['value'])

    def test_f2_install_two_consumers_of_one_state_root(self):
        """The second consumer's drill must not move the fence of a state root the first consumer was drilled on."""
        second = Path(self.temp.name) / 'second'; second.mkdir()
        __import__('subprocess').run(['git', '-C', str(second), 'init', '-q'], check=True)
        self.hook(second, self.old_exe)                                                # same state root as the customer project
        calls = []
        real = hotfix()._read_check

        def drill(*args, **kwargs):
            done = real(*args, **kwargs)
            calls.append(args[1])
            if len(calls) == 1: self.write('after the first drill')
            return done
        before = self.guard()
        with patch.object(hotfix(), '_read_check', drill):
            code, made = self.install()
        self.assertEqual(len(calls), 2)
        self.assertEqual(made['result'], 'refused_unsafe', made)
        self.assertIn('changed', json.dumps(made['problems']))
        self.assert_untouched(before, self.old)

    def test_f2_install_unchanged_control_switches(self):
        code, made = self.install()
        self.assertEqual(made['result'], 'switched', made)


class Round2(Window, S2Fixture):
    """Round 2 review (review-s2-r2.md R2-02, R2-03, R2-06, R2-08, R2-12, R2-13): FAULT INJECTION on the fake runtime (S2Fixture); the
    ledger, engine, authority check, claim and hook files are real."""

    def setUp(self):
        super().setUp()
        self.injected = []
        self.ready()
        self.old = {str(self.old_exe.resolve())}

    def new_venv(self):
        return Path(self.new_exe()).parent.parent

    def violation(self):
        """An attempt appears while the hooks are rewritten (the old runtime started work in the window)."""
        real = hotfix().repoint
        def racing(*args, **kwargs):
            done = real(*args, **kwargs)
            with self.ledger.transaction(write=True) as conn:
                conn.execute("UPDATE attempts SET status='running', updated_at='in the window'")
            return done
        with patch.object(hotfix(), 'repoint', racing):
            code, made = self.install()
        self.assertEqual(made['result'], 'switch_window_violation', made)
        with self.ledger.transaction(write=True) as conn:
            conn.execute("UPDATE attempts SET status='settled'")
        return made

    def test_R2_02a_install_violation_status_truthful_and_rollback_recovers(self):
        self.violation()
        self.assertEqual(self.settings_exe(), {self.new_exe()})
        state = self.status()
        self.assertTrue(state['installed']['value'], state['installed'])           # the hooks run the new exe: never "not installed"
        self.assertTrue(state['still_blocked']['value'])
        code, back = self.owner('support', 'rollback', self.fb)
        self.assertEqual((code, back['result']), (0, 'rolled_back'), back)
        self.assertEqual(self.settings_exe(), self.old)
        self.assertFalse(self.status()['installed']['value'])
        code, again = self.install()
        self.assertEqual(again['result'], 'switched', again)                         # install is possible again after the rollback

    def test_R2_02b_new_runtime_write_after_the_repoint_is_not_a_violation(self):
        real = hotfix().repoint
        with patch.object(hotfix(), 'repoint', self.once(real, 'written by the new runtime after the repoint', after=True)):
            code, made = self.install()
        self.assertEqual(made['result'], 'switched', made)
        self.assertEqual(made['events_after_repoint'], 1)                             # the one write, counted (support records excluded)

    def test_R2_02c_old_runtime_attempt_in_the_window_is_a_violation(self):
        made = self.violation()
        self.assertIn('during the switch', json.dumps(made['problems']))

    def test_R2_02d_old_runtime_process_still_running_after_the_repoint_is_a_violation(self):
        real = hotfix().repoint
        def racing(*args, **kwargs):
            done = real(*args, **kwargs)
            self.runtime.processes = [{'pid': 777, 'image': str(self.old_venv / 'Scripts' / 'onecrew.exe')}]
            return done
        with patch.object(hotfix(), 'repoint', racing):
            code, made = self.install()
        self.runtime.processes = []
        self.assertEqual(made['result'], 'switch_window_violation', made); self.assertIn('777', json.dumps(made['problems']))

    def test_R2_03_planted_venv_without_a_creation_baseline_is_refused_unrun(self):
        import shutil as sh
        planted = self.new_venv()
        (planted / 'Scripts').mkdir(parents=True)
        for name in ('python.exe', 'onecrew.exe'): (planted / 'Scripts' / name).write_bytes(b'planted')
        (planted / 'pyvenv.cfg').write_text(f'home = {Path(hotfix()._base_python(hotfix().targets(self.ledger)["lab"])).parent}\n'
                                            'include-system-site-packages = false\n', encoding='utf-8')
        from tests.test_v24_s2_apply import place
        place(planted, Path(self.wheel()[0]).read_bytes())                           # exactly the bound wheel's files
        calls = []
        for name in ('entry_run', 'interpreter'):
            real = getattr(hotfix(), name)
            def spy(venv, *a, _real=real, **k):
                calls.append(str(venv)); return _real(venv, *a, **k)
            target = patch.object(hotfix(), name, spy); target.start(); self.addCleanup(target.stop)
        code, refused = self.install()
        self.assertEqual(code, 2, refused); self.assertIn('baseline', refused['error'])
        self.assertEqual(calls, []); self.assertEqual(self.settings_exe(), self.old)
        self.assertTrue((planted / 'Scripts' / 'onecrew.exe').is_file())              # never deleted
        sh.rmtree(planted)
        code, made = self.install()
        self.assertEqual(made['result'], 'switched', made)

    def test_R2_06_lost_claim_refused_before_the_repoint(self):
        real = hotfix()._read_check
        def slow(*args, **kwargs):
            done = real(*args, **kwargs)
            __import__('time').sleep(1.3)                                              # the lease runs out during a long drill
            hotfix().claim(self.ledger, hotfix().targets(self.ledger)['lab']['venv'], 'another', 'install', 'lab')
            return done
        with patch.object(hotfix(), 'CLAIM_SECONDS', 1), patch.object(hotfix(), '_read_check', slow):
            code, refused = self.install()
        self.assertEqual(code, 2, refused); self.assertIn('claim', refused['error'])
        self.assertEqual(self.settings_exe(), self.old)

    def test_R2_06_control_renewed_claim_survives_a_long_drill(self):
        real = hotfix()._read_check
        def slow(*args, **kwargs):
            done = real(*args, **kwargs)
            __import__('time').sleep(1.3)
            return done
        with patch.object(hotfix(), 'CLAIM_SECONDS', 1), patch.object(hotfix(), '_read_check', slow):
            code, made = self.install()
        self.assertEqual(made['result'], 'switched', made)

    def foreign_claim(self, holder, pid):
        """A claim of the target written as another process would write it (expires in an hour)."""
        import datetime as dt, uuid
        venv = hotfix().targets(self.ledger)['lab']['venv']
        expires = (dt.datetime.now(dt.timezone.utc) + dt.timedelta(hours=1)).isoformat()
        hotfix()._emit(self.ledger, 'support.install', {'phase': 'claim', 'token': uuid.uuid4().hex, 'key': 'other', 'venv': str(venv),
                                                        'target': 'lab', 'what': 'install', 'pid': pid, 'holder': holder, 'expires_at': expires})

    def child(self):
        import subprocess, sys
        process = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(120)'], stdin=subprocess.DEVNULL)
        self.addCleanup(lambda: (process.kill(), process.wait()))
        from onecrew import process_core
        return process, process_core.identity(process.pid)

    def test_R2_09_claim_of_a_dead_holder_on_this_host_is_taken_over(self):
        process, holder = self.child()
        process.kill(); process.wait()
        self.foreign_claim(holder, process.pid)
        code, made = self.install()
        self.assertEqual((code, made['result']), (0, 'switched'), made)
        self.assertEqual(made['claim_taken_over_from']['holder']['pid'], process.pid)
        claims = [e for e in self.support_events('support.install') if e.get('phase') == 'claim' and e.get('taken_over_from')]
        self.assertEqual(len(claims), 1)

    def test_R2_09_claim_of_a_live_holder_is_honoured(self):
        process, holder = self.child()
        self.foreign_claim(holder, process.pid)
        code, refused = self.install()
        self.assertEqual(code, 2, refused); self.assertIn('in progress', refused['error'])
        self.assertEqual(self.settings_exe(), self.old)

    def test_R2_09_claim_from_another_host_or_without_holder_is_honoured(self):
        process, holder = self.child()
        process.kill(); process.wait()
        self.foreign_claim(dict(holder, host='another-machine'), process.pid)
        code, refused = self.install()
        self.assertEqual(code, 2, refused); self.assertIn('in progress', refused['error'])
        self.assertEqual(self.settings_exe(), self.old)

    def test_R2_09_claim_without_holder_is_honoured_until_it_expires(self):
        self.foreign_claim(None, 999999)
        code, refused = self.install()
        self.assertEqual(code, 2, refused); self.assertIn('in progress', refused['error'])

    def test_R2_09_rerun_after_a_crashed_rollback_in_another_process(self):
        """The package verifier's case: a rollback process dies at rollback_after_drill; the owner's rerun is not blocked for 15 minutes."""
        code, made = self.install()
        self.assertEqual(made['result'], 'switched', made)
        import subprocess, sys
        env = {k: v for k, v in os.environ.items() if k not in ('CLAUDECODE', 'CLAUDE_CODE_CHILD_SESSION', 'ONECREW_ACTOR')}
        env['ONECREW_SUPPORT_CRASH'] = 'rollback_after_drill'
        body = ('import sys\nfrom unittest.mock import patch\nfrom tests.test_v24_s2_apply import FakeRuntime\n'
                'from onecrew.v2 import hotfix\nfrom onecrew.ledger import Ledger\n'
                'class Case: pass\ncase = Case(); case.old_venv = __import__("pathlib").Path(sys.argv[3])\n'
                'runtime = FakeRuntime(case)\n'
                'for name in ("make_venv", "pip_install", "entry_run", "interpreter", "run_onecrew", "processes_under", "event_classes"):\n'
                '    patch.object(hotfix, name, getattr(runtime, name)).start()\n'
                'hotfix.rollback(Ledger(sys.argv[1], sys.argv[2]), sys.argv[4])\n')
        done = subprocess.run([sys.executable, '-c', body, str(self.root), str(self.ledger.state_root), str(self.old_venv), self.fb],
                              env=env, capture_output=True, text=True, cwd=str(Path(__file__).resolve().parents[1]))
        self.assertIn('fixture crash at rollback_after_drill', done.stderr, done.stderr[-2000:])
        code, back = self.owner('support', 'rollback', self.fb)
        self.assertEqual(back['result'], 'rolled_back', back)
        self.assertTrue(back.get('claim_taken_over_from'), back)

    def test_R2_08_changed_old_venv_refuses_the_rollback(self):
        code, made = self.install()
        self.assertEqual(made['result'], 'switched', made)
        self.old_exe.write_bytes(b'old, replaced after the install')
        code, refused = self.owner('support', 'rollback', self.fb)
        self.assertEqual(refused['result'], 'refused', refused); self.assertIn('old runtime', json.dumps(refused))
        self.assertEqual(self.settings_exe(), {self.new_exe()})
        self.old_exe.write_bytes(b'old')
        code, back = self.owner('support', 'rollback', self.fb)
        self.assertEqual(back['result'], 'rolled_back', back)

    def test_R2_12_settings_moved_to_a_third_exe_in_the_window_is_not_overwritten(self):
        third = Path(self.temp.name) / 'venvs' / 'third' / 'Scripts'; third.mkdir(parents=True)
        (third / 'onecrew.exe').write_bytes(b'third')
        real = hotfix().repoint
        def moved(*args, **kwargs):
            self.hook(self.root, third / 'onecrew.exe')
            return real(*args, **kwargs)
        with patch.object(hotfix(), 'repoint', moved):
            code, refused = self.install()
        self.assertEqual(code, 2, refused); self.assertIn('third', refused['error'])
        self.assertEqual(self.settings_exe(), {str((third / 'onecrew.exe').resolve())})

    def test_R2_13_content_changed_after_the_drill_refused_before_the_repoint(self):
        real = hotfix()._read_check
        def tamper(*args, **kwargs):
            done = real(*args, **kwargs)
            target = self.new_venv() / 'Lib' / 'site-packages' / 'onecrew' / 'v2' / 'fixmod.py'
            target.write_bytes(target.read_bytes() + b'# changed after the drill\n')
            return done
        with patch.object(hotfix(), '_read_check', tamper):
            code, made = self.install()
        self.assertNotEqual(made.get('result') if isinstance(made, dict) else None, 'switched', made)
        self.assertIn('fixmod.py', json.dumps(made))
        self.assertEqual(self.settings_exe(), self.old)


if __name__ == '__main__':
    unittest.main()
