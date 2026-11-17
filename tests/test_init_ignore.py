"""INIT29: `onecrew init` makes git ignore .onecrew/ by itself, and its last hint points at the GitHub README.

Plain unittest, temp folders only, isolated LOCALAPPDATA/APPDATA.
"""
import contextlib
import io
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from onecrew.v2 import install

LOGGED_IN = lambda: ('ok', '/usr/bin/claude', '')
URL = 'https://github.com/tamnguyendev/one-crew#readme'


def run(function, *args, **kwargs):
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        code = function(*args, **kwargs)
    return code, out.getvalue()


class InitIgnoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.repo = self.base / 'project'; self.repo.mkdir()
        self.state = self.base / 'state'
        self.exe = self.base / 'venv' / 'bin' / 'onecrew'; self.exe.parent.mkdir(parents=True); self.exe.write_text('#!/bin/sh\n')
        env = patch.dict(os.environ, {'LOCALAPPDATA': str(self.base / 'local'), 'APPDATA': str(self.base / 'roaming')})
        env.start(); self.addCleanup(env.stop)
        for name in ('ONECREW_ACTOR', 'CLAUDECODE', 'CLAUDE_CODE_CHILD_SESSION', 'ONECREW_LANG', 'CLAUDE_PROJECT_DIR'): os.environ.pop(name, None)

    def init(self):
        return run(install.init, project=self.repo, state_root=self.state, yes=True, exe=self.exe, claude=LOGGED_IN)

    def git(self, *args):
        return subprocess.run(['git', *args], cwd=self.repo, capture_output=True, text=True, check=True).stdout

    def make_git_repo(self):
        if not shutil.which('git'): self.skipTest('git is missing')
        self.git('init', '-q')

    def test_init_writes_the_ignore_file_and_git_lists_nothing_under_onecrew(self):
        self.make_git_repo()
        code, out = self.init()
        self.assertEqual(code, 0, out)
        self.assertEqual((self.repo / '.onecrew' / '.gitignore').read_bytes(), b'*\n')
        self.assertTrue((self.repo / '.onecrew' / 'config.json').is_file())
        status = self.git('status', '--porcelain', '--untracked-files=all')
        self.assertNotIn('.onecrew', status)

    def test_the_plan_lists_the_ignore_step_before_the_question(self):
        self.make_git_repo()
        asked = []
        def ask(prompt):
            asked.append(prompt); return 'y'
        code, out = run(install.init, project=self.repo, state_root=self.state, yes=False, exe=self.exe, ask=ask, claude=LOGGED_IN)
        self.assertEqual(code, 0, out)
        self.assertEqual(len(asked), 1)
        self.assertIn(str(self.repo / '.onecrew' / '.gitignore'), out)

    def test_the_users_gitignore_keeps_its_exact_bytes_and_a_second_init_changes_nothing(self):
        self.make_git_repo()
        mine = b'build/\r\n*.log\n'
        (self.repo / '.gitignore').write_bytes(mine)
        self.assertEqual(self.init()[0], 0)
        self.assertEqual((self.repo / '.gitignore').read_bytes(), mine)
        before = (self.repo / '.onecrew' / '.gitignore').read_bytes()
        code, out = self.init()
        self.assertEqual(code, 0, out)
        self.assertIn(install.t('init.nothing'), out)
        self.assertEqual((self.repo / '.gitignore').read_bytes(), mine)
        self.assertEqual((self.repo / '.onecrew' / '.gitignore').read_bytes(), before)

    def test_an_existing_onecrew_gitignore_with_other_content_is_left_alone(self):
        self.make_git_repo()
        path = self.repo / '.onecrew' / '.gitignore'
        path.parent.mkdir(); path.write_bytes(b'keep-me\n')
        self.assertEqual(self.init()[0], 0)
        self.assertEqual(path.read_bytes(), b'keep-me\n')

    def test_the_final_hint_points_at_the_github_readme_in_both_languages(self):
        self.make_git_repo()
        for lang in ('en', 'vi'):
            with self.subTest(lang=lang), patch.dict(os.environ, {'ONECREW_LANG': lang}):
                shutil.rmtree(self.repo / '.onecrew', ignore_errors=True)
                code, out = self.init()
                self.assertEqual(code, 0, out)
                last = [line for line in out.splitlines() if line.strip()][-1]
                self.assertIn(URL, last)
                self.assertNotIn('docs/README.en.md', out)


if __name__ == '__main__':
    unittest.main()
