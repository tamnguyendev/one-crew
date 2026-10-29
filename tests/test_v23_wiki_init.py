"""2.3-A1 WI-01..05 (docs/v23/HOP-DONG-2.3.vi.md §10.3, KW-01..KW-15): `onecrew init` creates a minimal wiki skeleton or reuses the wiki the
project has, never overwrites, never writes outside the repository, refuses a configuration it cannot read with nothing written, and an
empty skeleton yields no knowledge. Written before the code (red on 4bb41b3, where init knows no wiki)."""
import contextlib
import hashlib
import io
import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from onecrew.ledger import Ledger
from onecrew.v2 import install, knowledge, where, wiki

LOGGED_IN = lambda: ('ok', 'claude', '')
NAMES = ('README.md', 'project.md', 'lessons.md')


def run(fn, **kwargs):
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        code = fn(**kwargs)
    return code, out.getvalue()


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def tree(root):
    """{relative path: sha256} of every file under root (missing root: {})."""
    root = Path(root)
    return {p.relative_to(root).as_posix(): sha(p) for p in sorted(root.rglob('*')) if p.is_file()} if root.exists() else {}


class Base(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='v23 wiki init '); self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.repo = self.base / 'project'; self.repo.mkdir()
        g = lambda *a: subprocess.run(['git', '-C', str(self.repo), *a], check=True, capture_output=True)
        g('init', '-q'); g('config', 'user.email', 'wiki-init@localhost'); g('config', 'user.name', 'wiki init')
        (self.repo / 'a.txt').write_text('base' + chr(10), encoding='utf-8'); g('add', '.'); g('commit', '-qm', 'base')
        self.state = self.base / 'state'
        self.exe = self.base / 'venv' / 'bin' / 'onecrew'; self.exe.parent.mkdir(parents=True); self.exe.write_text('#!/bin/sh\n')
        env = patch.dict(os.environ); env.start(); self.addCleanup(env.stop)
        for name in ('ONECREW_ACTOR', 'CLAUDECODE', 'CLAUDE_CODE_CHILD_SESSION', 'ONECREW_LANG', 'CLAUDE_PROJECT_DIR'): os.environ.pop(name, None)
        os.environ['LOCALAPPDATA'] = str(self.base / 'localappdata'); os.environ['APPDATA'] = str(self.base / 'appdata')

    def init(self, **kwargs):
        options = dict(project=self.repo, state_root=self.state, yes=True, exe=self.exe, claude=LOGGED_IN)
        return run(install.init, **dict(options, **kwargs))

    def config(self, value):
        path = self.repo / '.onecrew' / 'config.json'; path.parent.mkdir(exist_ok=True)
        path.write_text(value if isinstance(value, str) else json.dumps(value), encoding='utf-8')
        return path

    def nothing_written(self, config_bytes=None):
        """No ledger, no settings, no wiki, and config.json as it was (absent, or these bytes)."""
        self.assertFalse((self.state / 'ledger.sqlite3').exists())
        self.assertFalse((self.repo / '.claude').exists())
        self.assertFalse((self.repo / 'docs' / 'wiki').exists())
        config = self.repo / '.onecrew' / 'config.json'
        if config_bytes is None: self.assertFalse(config.exists())
        else: self.assertEqual(config.read_bytes(), config_bytes)

    def pages(self):
        return knowledge.pages_report(Ledger(self.repo, self.state))


class NewWiki(Base):
    def test_kw01_a_new_repository_gets_the_skeleton_and_the_reader_sees_three_pages_and_no_entry(self):
        code, out = self.init()
        self.assertEqual(code, 0, out)
        folder = self.repo / 'docs' / 'wiki'
        self.assertEqual(sorted(p.name for p in folder.iterdir()), sorted(NAMES))
        for name in NAMES:
            self.assertEqual((folder / name).read_text(encoding='utf-8').splitlines()[0], install.SKELETON_MARK)
        self.assertIn('docs/wiki', out.replace('\\', '/'))                                  # the plan names the wiki step
        report = self.pages()
        self.assertEqual(sorted(p['path'] for p in report['pages']), sorted('docs/wiki/' + n for n in NAMES))
        self.assertEqual([e for p in report['pages'] for e in p['entries']], [])
        self.assertEqual(report['problems'], [])

    def test_kw01_declined_writes_nothing(self):
        code, out = self.init(yes=False, ask=lambda _: 'n')
        self.assertEqual(code, 2, out)
        self.nothing_written()

    def test_kw11_the_skeleton_pages_never_yield_an_entry_in_either_language(self):
        for language in ('en', 'vi'):
            for name in NAMES:
                with self.subTest(language=language, name=name):
                    parsed = wiki.parse(install.skeleton_text(name, language), 'docs/wiki/' + name)
                    self.assertEqual((parsed['entries'], parsed['problems'], parsed['undelivered']), ([], [], []))
                    self.assertTrue(install.skeleton_text(name, language).startswith(install.SKELETON_MARK + '\n'))

    def test_kw11_vietnamese_skeleton_follows_the_language(self):
        os.environ['ONECREW_LANG'] = 'vi'
        code, out = self.init()
        self.assertEqual(code, 0, out)
        self.assertIn('Ngữ cảnh project', (self.repo / 'docs' / 'wiki' / 'project.md').read_text(encoding='utf-8'))


class Reuse(Base):
    def test_kw02_a_second_init_writes_nothing_and_keeps_the_edited_page(self):
        self.init()
        page = self.repo / 'docs' / 'wiki' / 'project.md'
        page.write_text(page.read_text(encoding='utf-8') + '\n## Quy uoc\nMot dong.\n', encoding='utf-8')
        before = tree(self.repo / 'docs')
        code, out = self.init()
        self.assertEqual(code, 0, out)
        self.assertIn('nothing to change', out)
        self.assertEqual(tree(self.repo / 'docs'), before)

    def test_kw03_a_wiki_with_pages_of_the_user_is_reused_without_a_skeleton(self):
        notes = self.repo / 'docs' / 'wiki' / 'notes.md'; notes.parent.mkdir(parents=True)
        notes.write_text('# Notes\n\n## A rule\nKeep a.txt short.\n', encoding='utf-8')
        before = tree(self.repo / 'docs')
        code, out = self.init()
        self.assertEqual(code, 0, out)
        self.assertEqual(tree(self.repo / 'docs'), before)

    def test_kw04_one_configured_folder_inside_the_repository_is_created_there_or_reused(self):
        self.config({'wiki': {'paths': ['kb/project']}})
        code, out = self.init()
        self.assertEqual(code, 0, out)
        self.assertEqual(sorted(p.name for p in (self.repo / 'kb' / 'project').iterdir()), sorted(NAMES))
        self.assertFalse((self.repo / 'docs').exists())
        self.assertEqual(where.read_config(self.repo)['wiki'], {'paths': ['kb/project']})          # the configuration is kept
        before = tree(self.repo / 'kb')
        code, out = self.init()
        self.assertEqual((code, tree(self.repo / 'kb')), (0, before), out)

    def test_kw05_several_folders_or_one_outside_are_only_reused(self):
        (self.repo / 'a').mkdir(); (self.repo / 'b').mkdir(); (self.repo / 'b' / 'page.md').write_text('# B\n', encoding='utf-8')
        self.config({'wiki': {'paths': ['a', 'b']}})
        code, out = self.init()
        self.assertEqual(code, 0, out)
        self.assertEqual(sorted(p.name for p in (self.repo / 'a').iterdir()), [])                 # init never picks a folder to write into
        outside = self.base / 'shared wiki'; outside.mkdir(); (outside / 'x.md').write_text('# X\n', encoding='utf-8')
        before = tree(outside)
        self.config({'wiki': {'paths': [str(outside)]}})
        code, out = self.init()
        self.assertEqual((code, tree(outside)), (0, before), out)
        self.assertFalse((self.repo / 'docs').exists())

    def test_kw05_a_missing_folder_among_several_or_outside_is_refused_with_nothing_written(self):
        for paths in (['a', 'missing'], [str(self.base / 'no such folder')]):
            with self.subTest(paths=paths):
                shutil.rmtree(self.repo / '.onecrew', ignore_errors=True); shutil.rmtree(self.repo / 'a', ignore_errors=True)
                (self.repo / 'a').mkdir()
                config = self.config({'wiki': {'paths': paths}}).read_bytes()
                code, out = self.init()
                self.assertEqual(code, 2, out)
                self.nothing_written(config)
                self.assertFalse((self.repo / 'missing').exists()); self.assertFalse((self.base / 'no such folder').exists())


class Refuse(Base):
    def test_kw06_an_unreadable_config_or_a_wrong_wiki_value_is_refused_and_never_overwritten(self):
        for value in ('{ not json', '["a list"]', {'wiki': 'docs/wiki'}, {'wiki': {'paths': []}}, {'wiki': {'paths': ['../outside']}},
                      {'wiki': {'paths': ['.git/wiki']}}):
            with self.subTest(value=value):
                config = self.config(value).read_bytes()
                code, out = self.init()
                self.assertEqual(code, 2, out)
                self.nothing_written(config)
                self.assertFalse((self.base / 'outside').exists())

    def _junction(self, link, target):
        if os.name == 'nt':
            done = subprocess.run(['cmd', '/c', 'mklink', '/J', str(link), str(target)], capture_output=True)
            if done.returncode != 0: self.skipTest('mklink /J failed')
        else:
            os.symlink(target, link)

    def test_kw07_a_wiki_folder_that_is_or_goes_through_a_link_is_refused(self):
        outside = self.base / 'elsewhere'; outside.mkdir()
        for link in (self.repo / 'docs' / 'wiki', self.repo / 'docs'):
            with self.subTest(link=link.name):
                shutil.rmtree(self.repo / 'docs', ignore_errors=True)
                if (self.repo / 'docs').exists(): os.rmdir(self.repo / 'docs')
                link.parent.mkdir(parents=True, exist_ok=True)
                self._junction(link, outside)
                code, out = self.init()
                self.assertEqual(code, 2, out)
                self.assertEqual(list(outside.iterdir()), [])
                self.assertFalse((self.state / 'ledger.sqlite3').exists())
                os.rmdir(link) if os.name == 'nt' else os.unlink(link)

    def test_kw07_a_junction_the_link_test_cannot_see_still_resolves_outside_and_is_refused(self):
        outside = self.base / 'elsewhere'; outside.mkdir()
        self._junction(self.repo / 'docs', outside)
        with patch.object(install, 'is_link', lambda path: False):                         # Python < 3.12: Path.is_junction does not exist
            code, out = self.init()
        self.assertEqual(code, 2, out)
        self.assertEqual(list(outside.iterdir()), [])
        os.rmdir(self.repo / 'docs') if os.name == 'nt' else os.unlink(self.repo / 'docs')

    def test_kw08_a_file_where_the_folder_should_be_is_refused_and_a_folder_named_like_a_page_is_skipped(self):
        (self.repo / 'docs').mkdir(); (self.repo / 'docs' / 'wiki').write_text('not a folder', encoding='utf-8')
        code, out = self.init()
        self.assertEqual(code, 2, out)
        self.assertEqual((self.repo / 'docs' / 'wiki').read_text(encoding='utf-8'), 'not a folder')
        self.assertFalse((self.state / 'ledger.sqlite3').exists())
        (self.repo / 'docs' / 'wiki').unlink(); (self.repo / 'docs' / 'wiki' / 'project.md').mkdir(parents=True)
        code, out = self.init()
        self.assertEqual(code, 0, out)
        self.assertTrue((self.repo / 'docs' / 'wiki' / 'project.md').is_dir())
        self.assertTrue((self.repo / 'docs' / 'wiki' / 'README.md').is_file()); self.assertTrue((self.repo / 'docs' / 'wiki' / 'lessons.md').is_file())


class Partial(Base):
    def test_kw09_an_interrupted_skeleton_is_completed_and_the_written_part_kept(self):
        folder = self.repo / 'docs' / 'wiki'; folder.mkdir(parents=True)
        (folder / 'README.md').write_text(install.SKELETON_MARK + '\n# edited by hand\n', encoding='utf-8')
        before = sha(folder / 'README.md')
        code, out = self.init()
        self.assertEqual(code, 0, out)
        self.assertEqual(sha(folder / 'README.md'), before)
        self.assertEqual(sorted(p.name for p in folder.iterdir()), sorted(NAMES))

    def test_kw10_a_write_error_is_reported_with_exit_3_and_the_next_init_finishes(self):
        real = install._create_new_file
        def failing(path, text):
            if Path(path).name == 'project.md': raise PermissionError(13, 'Access is denied')
            return real(path, text)
        with patch.object(install, '_create_new_file', failing):
            code, out = self.init()
        self.assertEqual(code, 3, out)
        self.assertIn('project.md', out); self.assertIn('README.md', out)
        self.assertTrue((self.state / 'ledger.sqlite3').is_file()); self.assertTrue((self.repo / '.claude' / 'settings.local.json').is_file())
        code, out = self.init()
        self.assertEqual(code, 0, out)
        self.assertEqual(sorted(p.name for p in (self.repo / 'docs' / 'wiki').iterdir()), sorted(NAMES))


class OldProject(Base):
    def test_kw13_a_project_set_up_before_keeps_its_config_ledger_and_other_hooks(self):
        self.init()
        shutil.rmtree(self.repo / 'docs')                                                   # as a 2.2 init left it: no wiki
        config = json.loads((self.repo / '.onecrew' / 'config.json').read_text(encoding='utf-8')); config['custom'] = {'kept': True}
        self.config(config)
        settings = self.repo / '.claude' / 'settings.local.json'
        data = json.loads(settings.read_text(encoding='utf-8'))
        data['hooks'].setdefault('PostToolUse', []).append({'hooks': [{'type': 'command', 'command': 'other-tool --log'}]})
        settings.write_text(json.dumps(data), encoding='utf-8')
        ledger = self.state / 'ledger.sqlite3'
        before = sha(ledger)
        code, out = self.init()
        self.assertEqual(code, 0, out)
        self.assertEqual(sha(ledger), before)
        self.assertEqual(where.read_config(self.repo)['custom'], {'kept': True})
        self.assertIn('other-tool --log', settings.read_text(encoding='utf-8'))
        self.assertEqual(sorted(p.name for p in (self.repo / 'docs' / 'wiki').iterdir()), sorted(NAMES))

    def test_kw15_knowledge_written_after_init_goes_to_the_ledger_and_leaves_the_skeleton_unchanged(self):
        from onecrew.v2 import plan as plans
        from tests.test_v2_l1 import plan_json
        self.init()
        before = tree(self.repo / 'docs')
        ledger = Ledger(self.repo, self.state)
        plans.propose(ledger, 'P1', plan_json(), 'codex')
        with ledger.transaction() as conn:
            event = conn.execute('SELECT MAX(seq) FROM events').fetchone()[0]
        written = knowledge.record(ledger, 'P1', kind='decision', text='Keep a.txt to one line', key='one-line',
                                   evidence={'status': 'observed', 'sources': [{'type': 'event', 'id': event}]})
        self.assertTrue(written['id'])
        self.assertEqual(tree(self.repo / 'docs'), before)
        self.assertIn('Keep a.txt to one line', [r['text'] for r in knowledge.records(ledger)])


class Version(unittest.TestCase):
    def test_onecrew_version_prints_the_installed_version_or_says_unknown(self):
        from onecrew.v2 import cli
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = cli.main(['--version'])
        self.assertEqual(code, 0)
        self.assertRegex(out.getvalue().strip(), r'^onecrew (\d+\.\d+\.\d+\S*|unknown \(.*\))$')


if __name__ == '__main__':
    unittest.main()
