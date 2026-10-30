r"""2.3 alpha blockers: two readers that sent a file's bytes on although the file has another name on the disk (a hard link) or is reached through
a link or a junction. Such a name may be the other name of a file every reader is kept from (an ignored .env, a home folder, the ledger).

  AL-01 the source snapshot of a node's read+write scope (Snapshots.capture: the engine's capture when it admits an attempt, and the bytes the
        worker gets) read a scope file that is a hard link, so the bytes of a file outside the project, or of a control or credential path the
        snapshot rules keep from every worker, entered the worker's snapshot under an ordinary name. Expected: the capture is refused with the
        reason (LedgerError naming the file and "hard link"), nothing of the file is stored, and an ordinary file is captured as before.
  AL-02 the wiki reader (wiki.pages: the pages knowledge is parsed from and delivered to nodes) read a page that is a hard link or a symbolic
        link, pages below a junction, and a wiki folder that is itself a junction. Expected: such a page is not read (a junction is not walked); it, or the junction, is named in the
        problems with the reason and in coverage['unreadable']; its text is in no page; the other pages are read as before.

No network, no provider, no model: the snapshot store and the wiki reader only, in temporary folders; LOCALAPPDATA and APPDATA are those of the run.
"""
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

from onecrew.ledger import Ledger, LedgerError
from onecrew.snapshots import Snapshots
from onecrew.v2 import engine, wiki

SECRET = 'API_KEY=do-not-read-me\n'
TOKEN = 'do-not-read-me'


def git(root, *args):
    done = subprocess.run(['git', '-C', str(root), '-c', 'core.autocrlf=false', *args], capture_output=True, text=True, encoding='utf-8', errors='replace')
    if done.returncode: raise AssertionError(f'git {args}: {done.stderr}')
    return done.stdout


def link(source, target):
    try:
        os.link(source, target)
    except OSError as error:
        raise unittest.SkipTest(f'no hard link on this volume: {error}')


def junction(target, name):
    if os.name != 'nt': raise unittest.SkipTest('junctions are a Windows feature')
    import _winapi
    _winapi.CreateJunction(str(target), str(name))


def files_holding(folder, token):
    return [p.name for p in Path(folder).rglob('*') if p.is_file() and token.encode() in p.read_bytes()]


class Isolated(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        for name in ('LOCALAPPDATA', 'APPDATA'):
            old = os.environ.get(name); os.environ[name] = str(self.base / name.lower())
            self.addCleanup(lambda n=name, v=old: os.environ.__setitem__(n, v) if v is not None else os.environ.pop(n, None))


# ---- AL-01: the source snapshot of a node's scope ----------------------------------------------------------------------------

class SnapshotHardLink(Isolated):
    def setUp(self):
        super().setUp()
        self.root = self.base / 'repo'; (self.root / 'docs').mkdir(parents=True)
        self.state = self.base / 'state'
        git(self.root, 'init', '-q'); git(self.root, 'config', 'user.email', 't@example.com'); git(self.root, 'config', 'user.name', 't')
        (self.root / '.gitignore').write_text('.env\n', encoding='utf-8')
        (self.root / 'docs' / 'a.md').write_text('# A\n', encoding='utf-8', newline='\n')
        git(self.root, 'add', '-A'); git(self.root, 'commit', '-q', '-m', 'base')

    def test_a01_a_scope_file_linked_to_a_file_outside_the_project_is_refused_and_nothing_of_it_is_stored(self):
        home = self.base / 'home'; home.mkdir()
        (home / '.env').write_text(SECRET, encoding='utf-8', newline='\n')
        link(home / '.env', self.root / 'docs' / 'notes.md')
        with self.assertRaisesRegex(LedgerError, r'hard link.*docs/notes\.md|docs/notes\.md.*hard link'):
            Snapshots(self.state).capture(self.root, ['docs/a.md', 'docs/notes.md'])
        self.assertEqual(files_holding(self.state, TOKEN), [])

    def test_a02_a_scope_file_linked_to_an_ignored_env_of_the_project_is_refused(self):
        (self.root / '.env').write_text(SECRET, encoding='utf-8', newline='\n')
        link(self.root / '.env', self.root / 'docs' / 'notes.md')
        with self.assertRaisesRegex(LedgerError, 'hard link'):
            Snapshots(self.state).capture(self.root, ['docs/notes.md'])
        self.assertEqual(files_holding(self.state, TOKEN), [])

    def test_a03_the_engine_capture_of_such_a_scope_records_the_reason_and_stores_nothing(self):
        (self.root / '.env').write_text(SECRET, encoding='utf-8', newline='\n')
        link(self.root / '.env', self.root / 'docs' / 'notes.md')
        key, reason = engine._source_capture(Ledger(self.root, self.state), {'read': ['docs/notes.md'], 'write': ['docs/a.md']})
        self.assertIsNone(key)
        self.assertIn('hard link', reason)
        self.assertEqual(files_holding(self.state, TOKEN), [])

    def test_a04_an_ordinary_scope_file_is_captured_as_before(self):
        (self.root / 'docs' / 'notes.md').write_text('plain\n', encoding='utf-8', newline='\n')
        store = Snapshots(self.state)
        manifest = store.load(store.capture(self.root, ['docs/a.md', 'docs/notes.md']))
        self.assertEqual(store.read_blob(manifest['files']['docs/notes.md']['working']), b'plain\n')

    def test_a05_a_hard_link_whose_other_name_is_gone_is_an_ordinary_file_again(self):
        (self.root / 'docs' / 'notes.md').write_text('plain\n', encoding='utf-8', newline='\n')
        link(self.root / 'docs' / 'notes.md', self.base / 'other.md')
        with self.assertRaises(LedgerError):
            Snapshots(self.state).capture(self.root, ['docs/notes.md'])
        os.remove(self.base / 'other.md')
        store = Snapshots(self.state)
        self.assertEqual(store.read_blob(store.load(store.capture(self.root, ['docs/notes.md']))['files']['docs/notes.md']['working']), b'plain\n')


# ---- AL-02: the wiki reader ---------------------------------------------------------------------------------------------------

class WikiPageLinks(Isolated):
    def setUp(self):
        super().setUp()
        self.root = self.base / 'repo'; self.wiki = self.root / 'docs' / 'wiki'; self.wiki.mkdir(parents=True)
        (self.wiki / 'rules.md').write_text('# Rules\n\n- Always write tests first.\n', encoding='utf-8', newline='\n')
        self.outside = self.base / 'outside'; self.outside.mkdir()
        (self.outside / 'secret.md').write_text('# Secret\n\n- ' + SECRET, encoding='utf-8', newline='\n')

    def read(self):
        coverage = {}
        found, problems = wiki.pages(self.root, coverage=coverage)
        self.assertFalse(any(TOKEN in page['text'] for page in found), 'the text of a linked page was read')
        return [page['path'] for page in found], problems, coverage

    def assertNotRead(self, name, problems, coverage, why):
        self.assertTrue(any(p['path'] == name and why in p['problem'] for p in problems), problems)
        self.assertIn(name, coverage['unreadable'])

    def test_w01_a_page_with_another_name_on_the_disk_is_not_read(self):
        link(self.outside / 'secret.md', self.wiki / 'linked.md')
        paths, problems, coverage = self.read()
        self.assertEqual(paths, ['docs/wiki/rules.md'])
        self.assertNotRead('docs/wiki/linked.md', problems, coverage, 'hard link')

    def test_w02_pages_below_a_junction_are_not_read(self):
        junction(self.outside, self.wiki / 'j')
        self.addCleanup(lambda: os.rmdir(self.wiki / 'j'))
        paths, problems, coverage = self.read()
        self.assertEqual(paths, ['docs/wiki/rules.md'])
        self.assertNotRead('docs/wiki/j', problems, coverage, 'junction')        # named, not walked: nothing behind it is listed

    def test_w03_a_symbolic_link_page_is_not_read(self):
        try:
            os.symlink(self.outside / 'secret.md', self.wiki / 'sym.md')
        except (OSError, NotImplementedError) as error:
            self.skipTest(f'this account cannot make a symbolic link: {error}')
        paths, problems, coverage = self.read()
        self.assertEqual(paths, ['docs/wiki/rules.md'])
        self.assertNotRead('docs/wiki/sym.md', problems, coverage, 'link')

    def test_w04_a_wiki_folder_that_is_a_junction_is_not_read(self):
        (self.root / 'docs' / 'wiki' / 'rules.md').unlink(); (self.root / 'docs' / 'wiki').rmdir()
        junction(self.outside, self.root / 'docs' / 'wiki')
        self.addCleanup(lambda: os.rmdir(self.root / 'docs' / 'wiki'))
        paths, problems, coverage = self.read()
        self.assertEqual(paths, [])
        self.assertTrue(any(p['path'] == 'docs/wiki' and 'junction' in p['problem'] for p in problems), problems)

    def test_w05_ordinary_pages_are_read_as_before(self):
        (self.wiki / 'sub').mkdir(); (self.wiki / 'sub' / 'more.md').write_text('# More\n\n- Keep it short.\n', encoding='utf-8', newline='\n')
        paths, problems, coverage = self.read()
        self.assertEqual(paths, ['docs/wiki/rules.md', 'docs/wiki/sub/more.md'])
        self.assertEqual(coverage['unreadable'], [])


if __name__ == '__main__':
    unittest.main()
