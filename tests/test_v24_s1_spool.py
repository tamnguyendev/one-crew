"""2.4-S1 / SF-02 (broken runtime): a report is never lost silently.

Counterexamples (ROADMAP-DESIGN §7, S1/SF-02): when the ledger is unreadable (or the CLI cannot import its own modules) the report goes to a
minimal spool and the user is told where; the spool module needs nothing but the standard library; when no location can be written the user is
told "NOT recorded" with every place that was tried; once the ledger is repaired the spool is imported exactly once under the same feedback id.
"""
import ast
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tests.test_v24_s1_intake import S1Fixture

REPO = Path(__file__).resolve().parents[1]
SPOOL = REPO / 'onecrew' / 'v2' / 'support_spool.py'


class SpoolTests(S1Fixture):
    def corrupt(self):
        self.ledger.state_root.mkdir(parents=True, exist_ok=True)
        self.ledger.path.write_bytes(b'this is not a sqlite database at all, just garbage bytes' * 40)

    def test_corrupt_ledger_spools_and_reports_path(self):
        self.corrupt()
        code, made = self.report('--text', 'onecrew plan show crashed', '--expected', 'the plan status', '--key', 'crash-1')
        self.assertEqual(code, 0, made)
        self.assertTrue(made['recorded']); self.assertTrue(made['spooled'])
        self.assertRegex(made['id'], r'^FB-[0-9a-f]{32}$')
        path = Path(made['path'])
        self.assertTrue(path.is_file()); self.assertEqual(path.parent, self.ledger.state_root / 'support-spool')
        self.assertIn('DatabaseError', made['reason'])
        record = json.loads(path.read_text(encoding='utf-8'))
        self.assertEqual((record['id'], record['client_key'], record['text']), (made['id'], 'crash-1', 'onecrew plan show crashed'))
        self.assertEqual(record['ledger']['bytes'], self.ledger.path.stat().st_size)
        self.assertNotIn('Traceback', json.dumps(made))
        code, text = self.cli('support', 'report', '--text', 'second crash')          # the text form says where it went
        self.assertEqual(code, 0, text); self.assertIn('spool', text)

    def test_spool_module_imports_alone_stdlib_only(self):
        tree = ast.parse(SPOOL.read_text(encoding='utf-8'))
        for item in ast.walk(tree):
            if isinstance(item, ast.ImportFrom):
                self.assertEqual(item.level, 0, f'relative import at line {item.lineno}')
                self.assertIn(item.module.split('.')[0], sys.stdlib_module_names, item.module)
            elif isinstance(item, ast.Import):
                for alias in item.names: self.assertIn(alias.name.split('.')[0], sys.stdlib_module_names, alias.name)
        with tempfile.TemporaryDirectory() as tmp:
            package = Path(tmp) / 'onecrew' / 'v2'; package.mkdir(parents=True)
            (Path(tmp) / 'onecrew' / '__init__.py').write_text(''); (package / '__init__.py').write_text('')
            shutil.copy(SPOOL, package / 'support_spool.py')               # the spool alone: no ledger, no support_cli beside it
            self.corrupt()
            code = ('import sys, json\n'
                    f'sys.path.insert(0, {tmp!r})\n'
                    'from onecrew.v2 import support_spool\n'
                    'bad = sorted(n for n in sys.modules if n.startswith("onecrew") and n not in ("onecrew", "onecrew.v2", "onecrew.v2.support_spool"))\n'
                    'assert not bad, bad\n'
                    f'sys.exit(support_spool.main(["--project", {str(self.root)!r}, "--state-root", {str(self.ledger.state_root)!r}, '
                    '"report", "--text", "the CLI cannot even import", "--json"]))\n')
            done = subprocess.run([sys.executable, '-I', '-c', code], capture_output=True, text=True, encoding='utf-8', errors='replace')
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        made = json.loads(done.stdout)
        self.assertTrue(made['spooled']); self.assertIn('ImportError', made['reason'])
        self.assertTrue(Path(made['path']).is_file())

    def test_all_locations_unwritable_reports_not_recorded(self):
        blocker = Path(self.temp.name) / 'a-file'; blocker.write_text('not a directory')
        state = blocker / 'state'                                          # under a file: nothing can be created there
        (self.root / '.onecrew').write_text('a file where the folder would be')
        with patch.object(tempfile, 'tempdir', str(blocker / 'tmp')):
            code, made = self.cli('support', 'report', '--text', 'nothing works', '--json', state=state)
        self.assertNotEqual(code, 0, made)
        self.assertFalse(made['recorded'])
        self.assertIn('NOT recorded', made['message'])
        self.assertEqual(len(made['tried']), 4, made['tried'])            # the ledger, then the three spool places
        self.assertTrue(all(t['error'] for t in made['tried']))

    def test_import_spool_once_after_repair(self):
        self.corrupt()
        code, made = self.report('--text', 'The hook printed a traceback', '--key', 'after-repair')
        self.assertTrue(made['spooled'], made)
        self.ledger.path.unlink()                                          # the owner repairs (here: a fresh ledger)
        code, imported = self.cli('support', 'import-spool')
        self.assertEqual(code, 0, imported)
        self.assertEqual(imported['imported'], [made['id']])
        code, again = self.cli('support', 'import-spool')
        self.assertEqual((code, again['imported']), (0, []))
        events = self.support_events()
        self.assertEqual([(e['id'], e['client_key']) for e in events], [(made['id'], 'after-repair')])
        self.assertEqual(events[0]['spooled']['reason'], made['reason'])
        self.assertFalse(Path(made['path']).exists())
        self.assertTrue((Path(made['path']).parent / 'imported' / Path(made['path']).name).is_file())
        code, view = self.cli('support', 'show', made['id'], '--json')
        self.assertEqual(code, 0, view)

    def test_python_module_form_runs_the_same_report(self):
        self.corrupt()
        code = (f'import sys; sys.path.insert(0, {str(REPO)!r})\n'
                'import runpy; sys.argv = ["support_spool", "--project", sys.argv[1], "--state-root", sys.argv[2], "report", "--text", "module form", "--json"]\n'
                'runpy.run_module("onecrew.v2.support_spool", run_name="__main__")\n')
        done = subprocess.run([sys.executable, '-I', '-c', code, str(self.root), str(self.ledger.state_root)],
                              capture_output=True, text=True, encoding='utf-8', errors='replace')
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertTrue(json.loads(done.stdout)['spooled'])


if __name__ == '__main__':
    unittest.main()
