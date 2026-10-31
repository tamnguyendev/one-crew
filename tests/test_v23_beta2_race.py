r"""Codex review of beta 2.3.0.dev9, P1: a file that becomes a hard link (or is reached through a junction) between the check for such names and the
moment git or OneCrew reads it still had its content stored: `artifact_sha` checked `hard_links`, then ran `git add -A`, which hashed the file into
`.git/objects` and into the tree `verified_sha` hands to the verifiers.

The race is forced here, not waited for: the swap is made at the exact step. For the Git trees there are two steps: (A) after the first look at the
names and before the files are pinned, (B) after they are pinned and before git reads them. For the wiki and the snapshot: after the listing or the
path check and before the read. These tests show the window is closed at those steps; they say nothing about how often such a swap happens in
practice (it needs another process writing in the project at that moment).

Expected, whatever the path (verifier, status identity, reviewer tree, worker snapshot, wiki):
  - nothing of the file behind the new name reaches the repository's object store, a clean filter, the ledger's snapshot store, a tree, or a page;
  - at (A) a verifier's identity and the reviewer's tracked tree are refused with the reason, the status identity holds the B2 marker; at (B) the swap
    itself fails on Windows (the pinned file and the folders above it cannot be renamed, deleted or replaced) and the identity is the ordinary one;
  - ordinary work is as before (kept from the independent review of the first fix): CRLF in the index with core.autocrlf or text=auto, a file above
    core.bigFileThreshold, a path beyond MAX_PATH, a `;` in the repository's path; the tree's objects are in the repository afterwards.
No network, no provider, no model; temporary folders; LOCALAPPDATA and APPDATA are those of the run.
"""
import os
import shutil
import subprocess
import sys
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

    def at_pin(self, swap):
        """(A) `swap` done once, right before the files are pinned (after hard_links looked at every name)."""
        original, done = command._Pins.pin, []

        def hooked(pins, names):
            if not done:
                done.append(1); swap()
            return original(pins, names)
        return mock.patch.object(command._Pins, 'pin', hooked), done

    def at_read(self, swap):
        """(B) `swap` tried once, right before git reads the pinned files (the first `update-index --add`); records whether it succeeded."""
        original, tried = command._git, []

        def hooked(directory, *args, **kwargs):
            if not tried and 'update-index' in args and '--add' in args and '--stdin' in args:
                try:
                    swap(); tried.append('swapped')
                except OSError as error:
                    tried.append(f'blocked: {error.__class__.__name__}')
            return original(directory, *args, **kwargs)
        return mock.patch.object(command, '_git', hooked), tried

    def to_link(self):
        (self.root / 'a.txt').unlink(); link(self.home / '.env', self.root / 'a.txt')

    def to_junction(self):
        shutil.rmtree(self.root / 'docs'); junction(self.outside, self.root / 'docs')
        self.addCleanup(lambda: os.rmdir(self.root / 'docs') if (self.root / 'docs').is_junction() else None)

    def plain(self, root=None, args=('add', '-A')):
        """The identity as it always was, written out independently of the code under test (from HEAD, or from the real index for `add -u`)."""
        root = root or self.root
        with tempfile.TemporaryDirectory() as temp:
            env = {'GIT_INDEX_FILE': str(Path(temp) / 'index')}
            if args == ('add', '-u'):
                shutil.copyfile(Path(git(root, 'rev-parse', '--absolute-git-dir')) / 'index', env['GIT_INDEX_FILE'])
            else:
                git(root, 'read-tree', 'HEAD', env=env)
            git(root, *args, env=env)
            git(root, 'rm', '-r', '--cached', '-f', '-q', '--ignore-unmatch', '--', '.onecrew', env=env)
            return git(root, 'write-tree', env=env)

    # ---- (A) changed after the first look, before the pin
    def test_r01_a_file_made_a_hard_link_after_the_check_is_refused_and_never_stored(self):
        patch, done = self.at_pin(self.to_link)
        with patch, self.assertRaisesRegex(LedgerError, 'hard link|another name'):
            command.verified_sha(self.root)
        self.assertTrue(done)
        self.assertFalse(objects_holding(self.root, TOKEN), 'the content behind the new hard link reached .git/objects')

    def test_r02_a_folder_made_a_junction_after_the_check_is_refused_and_never_stored(self):
        patch, done = self.at_pin(self.to_junction)
        with patch, self.assertRaises(LedgerError):
            command.verified_sha(self.root)
        self.assertTrue(done)
        self.assertFalse(objects_holding(self.root, TOKEN))

    def test_r03_the_status_identity_of_such_a_tree_holds_the_marker_never_the_content(self):
        patch, done = self.at_pin(self.to_link)
        with patch:
            identity = artifact.identity(self.root)
        self.assertTrue(done)
        self.assertFalse(objects_holding(self.root, TOKEN))
        self.assertIn('onecrew: not read', git(self.root, 'cat-file', '-p', identity + ':a.txt'))

    def test_r04_the_tracked_tree_refuses_a_file_made_a_hard_link_after_the_check(self):
        patch, done = self.at_pin(self.to_link)
        with patch, self.assertRaises(LedgerError):
            command.tracked_tree(self.root)
        self.assertTrue(done)
        self.assertFalse(objects_holding(self.root, TOKEN))

    # ---- (B) after the pin, before git reads
    def test_r05_a_pinned_file_cannot_be_swapped_while_git_reads_it(self):
        for name, swap, run in (('file to link, verifier', self.to_link, command.verified_sha), ('folder to junction, verifier', self.to_junction, command.verified_sha),
                                ('file to link, tracked tree', self.to_link, command.tracked_tree)):
            with self.subTest(name):
                patch, tried = self.at_read(swap)
                with patch:
                    try:
                        tree = run(self.root)
                    except LedgerError:
                        tree = None
                self.assertTrue(tried)
                self.assertFalse(objects_holding(self.root, TOKEN))
                if os.name == 'nt':
                    self.assertTrue(tried[0].startswith('blocked'), tried)
                    self.assertIsNotNone(tree)
                elif tried[0] == 'swapped':
                    self.assertIsNone(tree)                        # POSIX cannot keep the name: the recheck refuses it

    def test_r06_a_clean_filter_never_sees_the_linked_file(self):
        spy = self.base / 'spy'; spy.mkdir()
        script = self.base / 'spy.py'
        script.write_text('import sys, uuid, pathlib\ndata = sys.stdin.buffer.read()\n'
                          f'pathlib.Path(r"{spy}", uuid.uuid4().hex).write_bytes(data)\nsys.stdout.buffer.write(data)\n', encoding='utf-8')
        exe = sys.executable.replace('\\', '/')
        git(self.root, 'config', 'filter.spy.clean', f'"{exe}" "{str(script).replace(chr(92), "/")}"')
        (self.root / '.gitattributes').write_text('a.txt filter=spy\n', encoding='utf-8', newline='\n')
        for name, hook in (('after the check', self.at_pin), ('while git reads', self.at_read)):
            with self.subTest(name):
                patch, _ = hook(self.to_link)
                with patch:
                    try:
                        command.verified_sha(self.root)
                    except LedgerError:
                        pass
                self.assertEqual(files_holding(spy, TOKEN), [], 'the clean filter was given the content behind the link')
                if (self.root / 'a.txt').stat().st_nlink > 1:
                    (self.root / 'a.txt').unlink(); (self.root / 'a.txt').write_text('a changed\n', encoding='utf-8', newline='\n')

    # ---- ordinary work, as before
    def test_r07_a_tree_where_nothing_changes_has_its_identity_and_its_objects_are_in_the_repository(self):
        plain = self.plain()
        fresh = self.base / 'fresh'; shutil.copytree(self.root, fresh)
        identity = command.verified_sha(fresh)
        self.assertEqual(identity, plain)
        self.assertIn('a changed', git(fresh, 'cat-file', '-p', identity + ':a.txt'))
        self.assertEqual(command.verified_sha(self.root), plain)
        self.assertEqual(command.tracked_tree(self.root), self.plain(args=('add', '-u')))

    def test_r08_crlf_in_the_index_with_autocrlf_or_text_auto_is_as_before(self):
        for name, setup in (('core.autocrlf=true', lambda r: git(r, 'config', 'core.autocrlf', 'true')),
                            ('text=auto', lambda r: (r / '.gitattributes').write_text('* text=auto\n', encoding='utf-8', newline='\n'))):
            with self.subTest(name):
                r = self.base / ('crlf ' + name.split('=')[0].replace('.', '-'))
                r.mkdir(); git(r, 'init', '-q'); git(r, 'config', 'user.email', 't@example.com'); git(r, 'config', 'user.name', 't')
                git(r, 'config', 'core.autocrlf', 'false')
                (r / 'win.bat').write_bytes(b'@echo off\r\necho one\r\n')
                git(r, 'add', '-A'); git(r, 'commit', '-q', '-m', 'crlf in the index')
                setup(r)
                (r / 'win.bat').write_bytes(b'@echo off\r\necho two\r\n')
                plain = self.plain(r)
                self.assertEqual(command.artifact_sha(r), plain)
                self.assertEqual(command.verified_sha(r), plain)
                self.assertEqual(command.tracked_tree(r), self.plain(r, ('add', '-u')))

    def test_r09_a_file_above_the_big_file_threshold_is_readable_from_the_tree(self):
        git(self.root, 'config', 'core.bigFileThreshold', '1k')
        (self.root / 'asset.bin').write_bytes(bytes(range(256)) * 20)
        identity = command.verified_sha(self.root)
        done = subprocess.run(['git', '-C', str(self.root), 'archive', identity], capture_output=True)
        self.assertEqual(done.returncode, 0, done.stderr[-300:])
        self.assertEqual(identity, self.plain())

    def test_r10_a_semicolon_in_the_repository_path_and_a_path_beyond_max_path(self):
        odd = self.base / 'a;b'; shutil.copytree(self.root, odd)
        self.assertEqual(command.verified_sha(odd), self.plain(odd))
        if os.name != 'nt': return
        git(self.root, 'config', 'core.longpaths', 'true')
        deep = '\\\\?\\' + str(self.root) + '\\' + '\\'.join(['d' * 40] * 7)
        os.makedirs(deep)
        self.addCleanup(shutil.rmtree, '\\\\?\\' + str(self.root / ('d' * 40)), True)      # before the temporary folder: it is beyond MAX_PATH
        with open(deep + '\\long.txt', 'w', encoding='utf-8', newline='\n') as f: f.write('long\n')
        self.assertGreater(len(deep) + 9, 260)
        try:
            plain = self.plain()
        except AssertionError as error:
            self.skipTest(f'git cannot add this long path here: {str(error)[:120]}')
        self.assertEqual(command.verified_sha(self.root), plain)


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
