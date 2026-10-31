r"""Codex review of beta 2.3.0.dev9, P1: a file that becomes a hard link (or is reached through a junction) between the check for such names and the
moment git or OneCrew reads it still had its content stored: `artifact_sha` checks `hard_links`, then runs `git add -A`, which hashes the file into
`.git/objects` and into the tree `verified_sha` hands to the verifiers.

The race is forced here, not waited for: the swap is made at the exact step (just before the `git add`, between the wiki listing and the page read,
between the snapshot's path check and its read). These tests show the window is closed at those steps; they say nothing about how often such a swap
happens in practice (it needs another process writing in the project at that moment).

Expected, whatever the path (verifier, status identity, reviewer tree, worker snapshot, wiki):
  - nothing of the file behind the new name reaches the repository's object store, the ledger's snapshot store, a tree, or a delivered page;
  - a verifier's identity is refused with the reason (verified_sha); the status identity is a tree whose entry for that name is the stat marker of
    B2, never the content; the reviewer's tracked tree is refused;
  - a repository where nothing changes has the identity it always had, and its objects are in the repository afterwards (the tree can be read).
No network, no provider, no model; temporary folders; LOCALAPPDATA and APPDATA are those of the run.
"""
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from onecrew.ledger import LedgerError
from onecrew.snapshots import Snapshots
from onecrew.v2 import wiki
from onecrew.v2.verifiers import artifact, command

SECRET = 'API_KEY=race-do-not-read\n'
TOKEN = 'race-do-not-read'


def git(root, *args, env=None):
    done = subprocess.run(['git', '-C', str(root), '-c', 'core.autocrlf=false', *args], capture_output=True, text=True, encoding='utf-8',
                          errors='replace', env=dict(os.environ, **(env or {})))
    if done.returncode: raise AssertionError(f'git {args}: {done.stderr}')
    return done.stdout.strip()


def objects_holding(root, token):
    done = subprocess.run(['git', '-C', str(root), 'cat-file', '--batch-all-objects', '--batch'], capture_output=True)
    return token.encode() in done.stdout


def files_holding(folder, token):
    return [p.name for p in Path(folder).rglob('*') if p.is_file() and token.encode() in p.read_bytes()]


def link(source, target):
    try:
        os.link(source, target)
    except OSError as error:
        raise unittest.SkipTest(f'no hard link on this volume: {error}')


def junction(target, name):
    if os.name != 'nt': raise unittest.SkipTest('junctions are a Windows feature')
    import _winapi
    _winapi.CreateJunction(str(target), str(name))


class Race(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        for name in ('LOCALAPPDATA', 'APPDATA'):
            old = os.environ.get(name); os.environ[name] = str(self.base / name.lower())
            self.addCleanup(lambda n=name, v=old: os.environ.__setitem__(n, v) if v is not None else os.environ.pop(n, None))
        self.root = self.base / 'repo'; (self.root / 'docs').mkdir(parents=True)
        git(self.root, 'init', '-q'); git(self.root, 'config', 'user.email', 't@example.com'); git(self.root, 'config', 'user.name', 't')
        git(self.root, 'config', 'core.autocrlf', 'false')
        (self.root / 'a.txt').write_text('a\n', encoding='utf-8', newline='\n')
        (self.root / 'docs' / 'd.md').write_text('# D\n', encoding='utf-8', newline='\n')
        git(self.root, 'add', '-A'); git(self.root, 'commit', '-q', '-m', 'base')
        self.home = self.base / 'home'; self.home.mkdir()
        (self.home / '.env').write_text(SECRET, encoding='utf-8', newline='\n')
        self.outside = self.base / 'outside'; self.outside.mkdir()
        (self.outside / 'd.md').write_text(SECRET, encoding='utf-8', newline='\n')
        (self.root / 'a.txt').write_text('a changed\n', encoding='utf-8', newline='\n')       # a working-tree change: git add hashes it

    def before_add(self, swap):
        """command._git with `swap` done once, right before the first `git add` (after every check of names was made)."""
        original, done = command._git, []

        def hooked(directory, *args, **kwargs):
            if not done and 'add' in args:
                done.append(1); swap()
            return original(directory, *args, **kwargs)
        return mock.patch.object(command, '_git', hooked), done

    def to_link(self):
        (self.root / 'a.txt').unlink(); link(self.home / '.env', self.root / 'a.txt')

    def to_junction(self):
        shutil.rmtree(self.root / 'docs'); junction(self.outside, self.root / 'docs')
        self.addCleanup(lambda: os.rmdir(self.root / 'docs') if (self.root / 'docs').is_junction() else None)

    # ---- the verifier's identity
    def test_r01_a_file_made_a_hard_link_before_git_add_is_refused_and_never_stored(self):
        patch, done = self.before_add(self.to_link)
        with patch, self.assertRaisesRegex(LedgerError, 'hard link|another name'):
            command.verified_sha(self.root)
        self.assertTrue(done)
        self.assertFalse(objects_holding(self.root, TOKEN), 'the content behind the new hard link reached .git/objects')

    def test_r02_a_folder_made_a_junction_before_git_add_is_refused_and_never_stored(self):
        patch, done = self.before_add(self.to_junction)
        with patch, self.assertRaises(LedgerError):
            command.verified_sha(self.root)
        self.assertTrue(done)
        self.assertFalse(objects_holding(self.root, TOKEN))

    # ---- the status identity (views, reports, evidence)
    def test_r03_the_status_identity_of_such_a_tree_never_holds_the_content(self):
        patch, done = self.before_add(self.to_link)
        with patch:
            try:
                identity = artifact.identity(self.root)
            except LedgerError:
                identity = None                                              # refused is safe too; what matters is the store
        self.assertTrue(done)
        self.assertFalse(objects_holding(self.root, TOKEN))
        if identity is not None:
            self.assertNotIn(TOKEN, git(self.root, 'cat-file', '-p', identity + ':a.txt'))

    # ---- the reviewer's tracked tree
    def test_r04_the_tracked_tree_refuses_a_file_made_a_hard_link_before_git_add(self):
        patch, done = self.before_add(self.to_link)
        with patch, self.assertRaises(LedgerError):
            command.tracked_tree(self.root)
        self.assertTrue(done)
        self.assertFalse(objects_holding(self.root, TOKEN))

    # ---- controls
    def test_r05_a_tree_where_nothing_changes_has_its_identity_and_its_objects_are_in_the_repository(self):
        with tempfile.TemporaryDirectory() as temp:
            env = {'GIT_INDEX_FILE': str(Path(temp) / 'index')}
            git(self.root, 'read-tree', 'HEAD', env=env); git(self.root, 'add', '-A', env=env)
            plain = git(self.root, 'write-tree', env=env)
        # the plain tree above wrote its objects already; a fresh repository shows the identity also writes what it needs
        fresh = self.base / 'fresh'; shutil.copytree(self.root, fresh)
        identity = command.verified_sha(fresh)
        self.assertEqual(identity, plain)
        self.assertIn('a changed', git(fresh, 'cat-file', '-p', identity + ':a.txt'))
        self.assertEqual(command.verified_sha(self.root), plain)

    def test_r06_the_reviewer_tree_of_an_ordinary_change_is_as_before(self):
        tracked = command.tracked_tree(self.root)
        self.assertIn('a changed', git(self.root, 'cat-file', '-p', tracked + ':a.txt'))


class ReadersRace(unittest.TestCase):
    """The two other readers that judge a name and then read it: the worker snapshot (Snapshots.capture) and the wiki (wiki.pages)."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.root = self.base / 'repo'; (self.root / 'docs' / 'wiki' / 'sub').mkdir(parents=True)
        (self.root / 'docs' / 'wiki' / 'rules.md').write_text('# Rules\n\n- Keep it short.\n', encoding='utf-8', newline='\n')
        (self.root / 'docs' / 'wiki' / 'sub' / 'p.md').write_text('# P\n\n- inside\n', encoding='utf-8', newline='\n')
        self.outside = self.base / 'outside'; self.outside.mkdir()
        (self.outside / 'p.md').write_text('# Secret\n\n- ' + SECRET, encoding='utf-8', newline='\n')
        self.state = self.base / 'state'

    def test_r07_a_wiki_folder_made_a_junction_after_the_listing_is_not_read(self):
        original, done = wiki._listing, []

        def swap(base):
            listed = original(base)
            if not done:
                done.append(1)
                shutil.rmtree(self.root / 'docs' / 'wiki' / 'sub'); junction(self.outside, self.root / 'docs' / 'wiki' / 'sub')
                self.addCleanup(lambda: os.rmdir(self.root / 'docs' / 'wiki' / 'sub'))
            return listed
        with mock.patch.object(wiki, '_listing', swap):
            found, problems = wiki.pages(self.root)
        self.assertTrue(done)
        self.assertFalse(any(TOKEN in page['text'] for page in found), 'a page was read through a junction made after the listing')
        self.assertTrue(any(p['path'] == 'docs/wiki/sub/p.md' for p in problems), problems)

    def test_r08_a_scope_folder_made_a_junction_after_its_path_was_checked_never_reaches_the_store(self):
        from onecrew import snapshots
        (self.root / 'docs' / 'x.md').write_text('inside\n', encoding='utf-8', newline='\n')
        (self.outside / 'x.md').write_text(SECRET, encoding='utf-8', newline='\n')
        original, calls = snapshots.safe_file, []

        def checked_then_swapped(root, name):       # the forced schedule: each path check sees the folder; the read after it meets the junction
            target = original(root, name) if not calls else Path(root) / name
            calls.append(name)
            if len(calls) == 1:
                shutil.rmtree(Path(root) / 'docs'); junction(self.outside, Path(root) / 'docs')
            return target
        self.addCleanup(lambda: os.rmdir(self.root / 'docs') if (self.root / 'docs').is_junction() else None)
        with mock.patch.object(snapshots, 'safe_file', checked_then_swapped):
            try:
                Snapshots(self.state).capture(self.root, ['docs/x.md'])
            except LedgerError:
                pass
        self.assertTrue(calls)
        self.assertEqual(files_holding(self.state, TOKEN), [], 'the bytes behind the junction reached the snapshot store')


if __name__ == '__main__':
    unittest.main()
