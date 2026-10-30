r"""2.3 beta B2: the identity that views, reports and evidence checks compare (artifact.identity, command.artifact_sha) hashed the working tree with
`git add -A`, so a name that is a hard link (maybe to an ignored .env or a file in the home folder), or a file reached through a junction, had its
content read and written as a blob into the repository's object store, although no verifier may read it (2.3 rule: a file with another name on the
disk is never read; verifiers refuse it, AL-01 snapshots refuse it).

Expected, for such a name (hard_links names it: names, link counts and reparse tags only):
  - its content is never read: the object store holds nothing of it after the identity is computed;
  - the identity is still a Git tree id, and still changes when the file changes (size, modification time, file id: the stat data, not the
    content), so a view still sees a changed artifact (review D-R01); two identities of an unchanged tree are equal;
  - a tree without such a name has the identity it always had (the tree of `git add -A` without .onecrew).
No network, no provider, no model: git and the identity only, in temporary folders; LOCALAPPDATA and APPDATA are those of the run.
"""
import os
import subprocess
import tempfile
import time
import unittest
from pathlib import Path

from onecrew.v2.verifiers import artifact, command

SECRET = 'API_KEY=beta-do-not-read\n'
TOKEN = 'beta-do-not-read'


def git(root, *args, env=None):
    done = subprocess.run(['git', '-C', str(root), '-c', 'core.autocrlf=false', *args], capture_output=True, text=True, encoding='utf-8',
                          errors='replace', env=dict(os.environ, **(env or {})))
    if done.returncode: raise AssertionError(f'git {args}: {done.stderr}')
    return done.stdout.strip()


def link(source, target):
    try:
        os.link(source, target)
    except OSError as error:
        raise unittest.SkipTest(f'no hard link on this volume: {error}')


def objects_holding(root, token):
    done = subprocess.run(['git', '-C', str(root), 'cat-file', '--batch-all-objects', '--batch'], capture_output=True)
    return token.encode() in done.stdout


class StatusIdentity(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        for name in ('LOCALAPPDATA', 'APPDATA'):
            old = os.environ.get(name); os.environ[name] = str(self.base / name.lower())
            self.addCleanup(lambda n=name, v=old: os.environ.__setitem__(n, v) if v is not None else os.environ.pop(n, None))
        self.root = self.base / 'repo'; (self.root / 'docs').mkdir(parents=True)
        git(self.root, 'init', '-q'); git(self.root, 'config', 'user.email', 't@example.com'); git(self.root, 'config', 'user.name', 't')
        git(self.root, 'config', 'core.autocrlf', 'false')
        (self.root / '.gitignore').write_text('.env\n', encoding='utf-8', newline='\n')
        (self.root / 'docs' / 'a.md').write_text('# A\n', encoding='utf-8', newline='\n')
        git(self.root, 'add', '-A'); git(self.root, 'commit', '-q', '-m', 'base')
        self.home = self.base / 'home'; self.home.mkdir()
        (self.home / '.env').write_text(SECRET, encoding='utf-8', newline='\n')
        self.assertFalse(objects_holding(self.root, TOKEN))

    def plain_tree(self):
        """The identity as it always was, written out here independently of the code under test: the tree of `git add -A` without .onecrew."""
        with tempfile.TemporaryDirectory() as temp:
            env = {'GIT_INDEX_FILE': str(Path(temp) / 'index')}
            git(self.root, 'read-tree', 'HEAD', env=env); git(self.root, 'add', '-A', env=env)
            git(self.root, 'rm', '-r', '--cached', '-f', '-q', '--ignore-unmatch', '--', '.onecrew', env=env)
            return git(self.root, 'write-tree', env=env)

    def test_b01_an_untracked_name_linked_to_a_file_outside_is_never_hashed(self):
        link(self.home / '.env', self.root / 'docs' / 'notes.md')
        identity = artifact.identity(self.root)
        self.assertRegex(identity, '^[0-9a-f]{40}$')
        self.assertFalse(objects_holding(self.root, TOKEN), 'the content behind the hard link was written into the object store')

    def test_b02_a_tracked_name_that_became_a_link_is_never_hashed(self):
        (self.root / 'docs' / 'a.md').unlink()
        link(self.home / '.env', self.root / 'docs' / 'a.md')
        command.artifact_sha(self.root)
        self.assertFalse(objects_holding(self.root, TOKEN))

    def test_b03_a_changed_linked_file_still_changes_the_identity_and_an_unchanged_one_does_not(self):
        link(self.home / '.env', self.root / 'docs' / 'notes.md')
        first = artifact.identity(self.root)
        self.assertEqual(artifact.identity(self.root), first)
        time.sleep(0.05)
        (self.home / '.env').write_text(SECRET + 'MORE=1\n', encoding='utf-8', newline='\n')     # through the other name
        self.assertNotEqual(artifact.identity(self.root), first)
        self.assertFalse(objects_holding(self.root, TOKEN))

    def test_b04_the_identity_names_the_linked_path_as_changed(self):
        link(self.home / '.env', self.root / 'docs' / 'notes.md')
        head = git(self.root, 'rev-parse', 'HEAD^{tree}')
        self.assertIn('docs/notes.md', command.changed_paths(self.root, head, artifact.identity(self.root)))

    def test_b05_a_tree_without_such_a_name_has_the_identity_it_always_had(self):
        (self.root / 'docs' / 'new.md').write_text('new\n', encoding='utf-8', newline='\n')
        (self.root / '.onecrew').mkdir(); (self.root / '.onecrew' / 'x.json').write_text('{}', encoding='utf-8')
        self.assertEqual(artifact.identity(self.root), self.plain_tree())

    # ---- kept from the independent review of the fix (D:/OneCrewRuns/v23/beta/review-b2.md): P2-1, P3-2, P3-5
    def junction(self, target, name):
        if os.name != 'nt': self.skipTest('junctions are a Windows feature')
        import _winapi
        _winapi.CreateJunction(str(target), str(name))
        self.addCleanup(lambda: os.rmdir(name))

    def test_b07_a_tracked_file_under_an_ignored_folder_that_became_a_link_still_has_an_identity(self):
        (self.root / '.gitignore').write_text('.env\nvendor/\n', encoding='utf-8', newline='\n')
        (self.root / 'vendor').mkdir(); (self.root / 'vendor' / 'lib.py').write_text('one\n', encoding='utf-8', newline='\n')
        git(self.root, 'add', '-f', 'vendor/lib.py', '.gitignore'); git(self.root, 'commit', '-q', '-m', 'vendor')
        head = git(self.root, 'rev-parse', 'HEAD^{tree}')
        (self.root / 'vendor' / 'lib.py').unlink()
        link(self.home / '.env', self.root / 'vendor' / 'lib.py')
        identity = artifact.identity(self.root)
        self.assertRegex(identity, '^[0-9a-f]{40}$')
        self.assertEqual(command.changed_paths(self.root, head, identity), ['vendor/lib.py'])
        self.assertFalse(objects_holding(self.root, TOKEN))

    def test_b08_an_ignored_name_only_in_the_real_index_that_is_a_link_changes_nothing(self):
        link(self.home / '.env', self.root / 'local.env')
        (self.root / '.gitignore').write_text('.env\nlocal.env\n', encoding='utf-8', newline='\n')
        git(self.root, 'add', '.gitignore'); git(self.root, 'commit', '-q', '-m', 'ignore local.env')
        before = self.plain_tree()
        self.assertFalse(objects_holding(self.root, TOKEN))
        subprocess.run(['git', '-C', str(self.root), 'update-index', '--add', '--cacheinfo', '100644,' + 'e69de29bb2d1d6434b8b29ae775ad8c2e48c5391' + ',local.env'], check=True)
        self.assertEqual(artifact.identity(self.root), before)                    # the tree never held it: no marker, no error
        self.assertFalse(objects_holding(self.root, TOKEN))

    def test_b09_a_tracked_file_behind_an_ignored_folder_made_a_junction_still_has_an_identity(self):
        (self.root / '.gitignore').write_text('.env\nbuild/\n', encoding='utf-8', newline='\n')
        (self.root / 'build').mkdir(); (self.root / 'build' / 'keep.txt').write_text('keep\n', encoding='utf-8', newline='\n')
        git(self.root, 'add', '-f', 'build/keep.txt', '.gitignore'); git(self.root, 'commit', '-q', '-m', 'build')
        (self.root / 'build' / 'keep.txt').unlink(); (self.root / 'build').rmdir()
        outside = self.base / 'outside'; outside.mkdir(); (outside / 'keep.txt').write_text(SECRET, encoding='utf-8', newline='\n')
        self.junction(outside, self.root / 'build')
        identity = artifact.identity(self.root)
        self.assertRegex(identity, '^[0-9a-f]{40}$')
        self.assertFalse(objects_holding(self.root, TOKEN))

    def test_b10_a_nested_repository_behind_a_junction_shows_in_the_identity(self):
        outside = self.base / 'outside'; (outside / 'nested').mkdir(parents=True)
        git(outside / 'nested', 'init', '-q'); (outside / 'nested' / 'f.txt').write_text(SECRET, encoding='utf-8', newline='\n')
        self.junction(outside, self.root / 'docs' / 'j')
        head = git(self.root, 'rev-parse', 'HEAD^{tree}')
        self.assertNotEqual(command.changed_paths(self.root, head, artifact.identity(self.root)), [])
        self.assertFalse(objects_holding(self.root, TOKEN))

    def test_b11_a_tracked_file_gone_behind_a_junction_is_dropped_as_before(self):
        (self.root / 'lib').mkdir(); (self.root / 'lib' / 'x.py').write_text('x\n', encoding='utf-8', newline='\n')
        git(self.root, 'add', 'lib/x.py'); git(self.root, 'commit', '-q', '-m', 'lib')
        (self.root / 'lib' / 'x.py').unlink(); (self.root / 'lib').rmdir()
        empty = self.base / 'empty'; empty.mkdir()
        self.junction(empty, self.root / 'lib')
        tree = artifact.identity(self.root)
        self.assertNotIn('lib/x.py', git(self.root, 'ls-tree', '-r', '--name-only', tree).splitlines())

    def test_b12_with_sparse_checkout_on_a_tracked_linked_file_is_still_never_hashed(self):
        """Review B2 round 2, P1: with core.sparseCheckout=true git clears skip-worktree on a file that is on disk, and `add` read the linked file."""
        (self.root / 'src').mkdir(); (self.root / 'src' / 'm.py').write_text('m\n', encoding='utf-8', newline='\n')
        git(self.root, 'add', 'src/m.py'); git(self.root, 'commit', '-q', '-m', 'src')
        git(self.root, 'config', 'core.sparseCheckout', 'true')
        info = Path(git(self.root, 'rev-parse', '--git-path', 'info'))
        info = info if info.is_absolute() else self.root / info
        info.mkdir(parents=True, exist_ok=True); (info / 'sparse-checkout').write_text('/*\n', encoding='utf-8', newline='\n')
        (self.root / 'src' / 'm.py').unlink()
        link(self.home / '.env', self.root / 'src' / 'm.py')
        self.assertRegex(artifact.identity(self.root), '^[0-9a-f]{40}$')
        self.assertFalse(objects_holding(self.root, TOKEN))

    def test_b13_in_a_cone_sparse_checkout_a_link_changes_only_its_own_name(self):
        """Review B2 round 3, P2: with sparse checkout turned off for the add, every absent file outside the cone was dropped from the identity.
        Expected: only the linked name differs from what HEAD holds; the files the cone keeps absent stay; nothing of the link is read."""
        (self.root / 'src').mkdir()
        for name in ('x.py', 'y.py'): (self.root / 'src' / name).write_text(name + '\n', encoding='utf-8', newline='\n')
        (self.root / 'docs' / 'm.md').write_text('m\n', encoding='utf-8', newline='\n')
        git(self.root, 'add', '-A'); git(self.root, 'commit', '-q', '-m', 'src')
        head = git(self.root, 'rev-parse', 'HEAD^{tree}')
        git(self.root, 'sparse-checkout', 'set', '--cone', 'docs')
        self.assertFalse((self.root / 'src' / 'x.py').exists())
        self.assertEqual(artifact.identity(self.root), head)                           # no link: as plain `git add -A`
        (self.root / 'docs' / 'm.md').unlink()
        link(self.home / '.env', self.root / 'docs' / 'm.md')
        identity = artifact.identity(self.root)
        self.assertEqual(command.changed_paths(self.root, head, identity), ['docs/m.md'])
        self.assertFalse(objects_holding(self.root, TOKEN))

    def test_b06_a_file_reached_through_a_junction_is_never_hashed(self):
        if os.name != 'nt': self.skipTest('junctions are a Windows feature')
        import _winapi
        outside = self.base / 'outside'; outside.mkdir(); (outside / 'secret.txt').write_text(SECRET, encoding='utf-8', newline='\n')
        _winapi.CreateJunction(str(outside), str(self.root / 'docs' / 'j'))
        self.addCleanup(lambda: os.rmdir(self.root / 'docs' / 'j'))
        identity = artifact.identity(self.root)
        self.assertRegex(identity, '^[0-9a-f]{40}$')
        self.assertFalse(objects_holding(self.root, TOKEN))


if __name__ == '__main__':
    unittest.main()
