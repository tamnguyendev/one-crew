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
        before, made = self.refused_at('repoint', 'after safe point, before repoint', expect='switch_window_violation')
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
        self.refused_at('repoint', 'after safe point, before repoint', 'switch_window_violation')
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


if __name__ == '__main__':
    unittest.main()
