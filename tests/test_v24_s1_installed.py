"""2.4-S1 from the INSTALLED wheel, in a venv and a working folder outside the checkout (ROADMAP-DESIGN §7, S1/S2 packaging row).

The wheel is built from this checkout's pyproject (tests/wf_wheel.build_wheel), installed offline into a fresh venv, and driven only through the
installed `onecrew` executable and `python -I -m onecrew.v2.support_spool`, from a cwd outside the checkout:
report on a healthy ledger; report against a garbage ledger.sqlite3 (spooled, path shown); import-spool after the repair; bundle; show.
Then the same commands in one isolated interpreter of the venv, whose loaded modules must all come from the install (boundary.violations is
empty and no module comes from the checkout, tests/ or wfkit/).
"""
import json
import os
import shutil
import subprocess
import unittest
from pathlib import Path

from onecrew.v2 import boundary
from tests import wf_wheel as wh

REPO = Path(__file__).resolve().parents[1]

BODY = r'''
import contextlib, io, json, sys
from onecrew.v2.cli import main
def run(*args):
    out = io.StringIO()
    with contextlib.redirect_stdout(out): code = main(['--project', PROJECT, '--state-root', STATE, *args])
    assert code == 0, (args, out.getvalue())
    return json.loads(out.getvalue())
made = run('support', 'report', '--text', 'in-process report from the venv', '--json')
run('support', 'classify', made['id'], '--class', 'environment', '--basis', 'doctor:python')
bundle = run('support', 'bundle', made['id'], '--out', EXPORT)
shown = run('support', 'show', made['id'], '--json')
assert shown['classification']['class'] == 'environment', shown
'''


def clean_env(base):
    drop = {'PYTHONPATH', 'PYTHONSTARTUP', 'PYTHONHOME', 'CLAUDECODE', 'CLAUDE_CODE_CHILD_SESSION', 'ONECREW_ACTOR', 'PYTHONUTF8',
            'PYTHONIOENCODING', 'ONECREW_DESKTOP_HOME'}
    env = {k: v for k, v in os.environ.items() if k.upper() not in drop}
    for name in ('localappdata', 'appdata', 'temp'):
        (base / name).mkdir(exist_ok=True)
    env.update(LOCALAPPDATA=str(base / 'localappdata'), APPDATA=str(base / 'appdata'), TEMP=str(base / 'temp'), TMP=str(base / 'temp'))
    return env


class InstalledS1(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.runs = Path(wh._runs())
        cls.wheel, _, (modules, packages) = wh.build_wheel(cls.runs)
        cls.python = wh.make_venv(cls.runs / 'venv home')
        wh.install(cls.python, cls.wheel)
        cls.ctx = wh.build_ctx(cls.python, modules, packages)
        cls.exe = cls.python.parent / ('onecrew.exe' if os.name == 'nt' else 'onecrew')

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.runs, ignore_errors=True)

    def setUp(self):
        self.base = self.runs / self._testMethodName; self.base.mkdir()
        self.cwd = self.base / 'cwd'; self.cwd.mkdir()
        self.project = self.base / 'project'; self.project.mkdir()
        subprocess.run(['git', 'init', '-q', str(self.project)], check=True)
        self.env = clean_env(self.base)

    def onecrew(self, state, *args, module=False):
        argv = ([str(self.python), '-I', '-m', 'onecrew.v2.support_spool'] if module else [str(self.exe)])
        argv += ['--project', str(self.project), '--state-root', str(state), *([] if module else ['support']), *args]
        done = subprocess.run(argv, capture_output=True, text=True, encoding='utf-8', errors='replace', cwd=self.cwd, env=self.env)
        try:
            return done.returncode, json.loads(done.stdout)
        except ValueError:
            return done.returncode, done.stdout + done.stderr

    def test_s1_cli_from_the_installed_wheel_outside_the_checkout(self):
        healthy = self.base / 'state'
        code, made = self.onecrew(healthy, 'report', '--text', 'The installed CLI reports once', '--key', 'w1', '--json')
        self.assertEqual(code, 0, made); self.assertFalse(made['spooled']); self.assertTrue(made['recorded'])
        self.assertTrue(made['runtime']['dist_version'].startswith('2.4.0'), made['runtime'])
        self.assertFalse(made['runtime']['checkout'], made['runtime'])
        broken = self.base / 'broken-state'; broken.mkdir()
        (broken / 'ledger.sqlite3').write_bytes(b'garbage, not sqlite ' * 50)
        code, spooled = self.onecrew(broken, 'report', '--text', 'The ledger is broken', '--json', module=True)
        self.assertEqual(code, 0, spooled); self.assertTrue(spooled['spooled']); self.assertTrue(Path(spooled['path']).is_file())
        self.assertTrue(Path(spooled['path']).is_relative_to(broken / 'support-spool'))
        (broken / 'ledger.sqlite3').rename(broken / 'ledger.garbage')         # the repair
        code, imported = self.onecrew(broken, 'import-spool')
        self.assertEqual((code, imported['imported']), (0, [spooled['id']]), imported)
        code, again = self.onecrew(broken, 'import-spool')
        self.assertEqual(again['imported'], [])
        code, bundle = self.onecrew(broken, 'bundle', spooled['id'], '--out', str(self.base / 'export'))
        self.assertEqual(code, 0, bundle); self.assertTrue((Path(bundle['export']) / 'manifest.json').is_file())
        code, shown = self.onecrew(broken, 'show', spooled['id'], '--json')
        self.assertEqual(code, 0, shown); self.assertEqual(shown['feedback']['spooled']['reason'], spooled['reason'])
        code, status = self.onecrew(broken, 'status', spooled['id'], '--json')
        self.assertEqual((code, status['stage']), (0, 'reported'), status)

    def test_s1_module_origins_inside_the_install(self):
        state = self.base / 'state'
        body = (BODY.replace('PROJECT', repr(str(self.project))).replace('STATE', repr(str(state)))
                .replace('EXPORT', repr(str(self.base / 'export'))))
        dump, tail = wh.run_case(self.python, body, env_extra=self.env, cwd=self.cwd)
        self.assertIsNotNone(dump, tail)
        self.assertEqual(boundary.violations(dump['end'], self.ctx), [], tail)
        loaded = {name: info.get('file') for name, info in dump['end'].items() if name.startswith('onecrew')}
        self.assertIn('onecrew.v2.support', loaded); self.assertIn('onecrew.v2.diagnostics', loaded)
        venv = self.python.parent.parent.resolve()
        for name, file in loaded.items():
            if file is None: continue
            self.assertTrue(Path(file).resolve().is_relative_to(venv), (name, file))
            self.assertFalse(Path(file).resolve().is_relative_to(REPO), (name, file))
        self.assertFalse([n for n in dump['end'] if n.split('.')[0] in ('tests', 'wfkit')])


if __name__ == '__main__':
    unittest.main()
