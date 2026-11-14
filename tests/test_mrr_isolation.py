"""MR-R round 2 (review R1 of 2.4.0.dev6+mrr.1): a declared source repository is only READ, also when it uses Git features that run
programs or touch files. No git call of MR-R on a source may run a program the repository, the user or the system configured (clean,
smudge or process filters such as Git LFS, hooks, fsmonitor), use the network (a partial clone's promisor) or change a byte, a file or a
modification time inside the repository, .git included (a split index's shared index, the objects a sparse index expands). Where a
repository cannot be read under those rules it is a coverage gap of its own with a precise state (filter_driver, partial_clone,
sparse_index, ...), never a partial or silent read; the other repositories are read as before. Citations count lines as git does (LF).
Nothing OneCrew writes (its ledger, a node's write) may land inside a declared repository, whatever the spelling of the path.

Every test here was written before the fix and fails on 15637a6 for its own property: the MrrFixture.step() guard (the whole folder of
every source repository, file and folder times included) or the test's explicit assertion. Fixture repositories only, no network (a
partial clone's origin is a local file:// repository), the in-process fixture worker (no model).
"""
import base64
import json
import os
import shutil
import subprocess
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from onecrew.ledger import Ledger, LedgerError
from onecrew.v2 import plan as plans
from tests.test_mrr_sources import (CAPS, MrrFixture, REPO_A, REPO_B, REPO_C, REPORT, blob_bytes, changed, commit, dated, fingerprint, git,
                                    lf_lines, make_repo, remove_tree, sr, st, write)
from tests.test_v24_a_sources import ask, body_of, done


def lfs_ready():
    """git-lfs on PATH and the LFS filter configured for this user's git (Git for Windows puts filter.lfs.* in the system gitconfig)."""
    if subprocess.run(['git', 'lfs', 'version'], capture_output=True).returncode: return False
    return bool(subprocess.run(['git', 'config', '--get', 'filter.lfs.process'], capture_output=True).stdout.strip())


def touch_later(path, seconds=5):
    """The same bytes, a newer modification time (a program that rewrote the file unchanged): the index's stat data no longer match."""
    later = time.time() + seconds
    os.utime(path, (later, later))


# ---- filters, hooks ----------------------------------------------------------------------------------------------------------------

LOGO = b'LOGO-ASSET-BYTES ' * 300
SPY = '#!/bin/sh\necho "filter ran" >> "{log}"\necho ran >> "{inside}"\ncat\n'
HOOK = '#!/bin/sh\necho "$0 ran" >> "{log}"\necho ran >> "{inside}"\n'


@unittest.skipUnless(lfs_ready(), 'git-lfs with its filter configured is not installed on this machine')
class LfsTests(MrrFixture):
    """Git LFS as it is on this machine (git-lfs 3.7, filter.lfs.* in the system gitconfig). core: an asset committed through LFS the usual
    way (the pointer is in HEAD), nothing changed since. app: .gitattributes routes *.psd to LFS, LFS never ran in this clone, a new asset is
    on disk (untracked). mirror: like core, but the asset was touched (same bytes, newer time)."""
    repos = {'core': ('repo-a', REPO_A), 'app': ('repo-b', REPO_B), 'mirror': ('repo-m', REPO_B)}
    grants = dict(MrrFixture.grants, core=['src/**', 'docs/', 'assets/**'], mirror=['src/**', 'assets/**'])

    def prepare_repos(self):
        for alias in ('core', 'mirror'):
            root = self.paths[alias]
            write(root, {'.gitattributes': b'*.bin filter=lfs diff=lfs merge=lfs -text\n', 'assets/logo.bin': LOGO})
            git(root, 'add', '-A'); git(root, 'commit', '-q', '-m', 'an LFS asset')     # git-lfs runs here, in the fixture: the pointer is committed
        app = self.paths['app']
        write(app, {'.gitattributes': b'*.psd filter=lfs diff=lfs merge=lfs -text\n'})
        git(app, 'add', '-A'); git(app, 'commit', '-q', '-m', 'LFS attributes')
        time.sleep(1.1)
        for alias in ('core', 'mirror'):
            git(self.paths[alias], 'update-index', '-q', '--really-refresh')            # an index newer than every file: nothing is racily clean
            self.assertEqual(git(self.paths[alias], 'status', '--porcelain'), '')
        write(app, {'art/new.psd': b'PSD-ASSET ' * 400})
        touch_later(self.paths['mirror'] / 'assets' / 'logo.bin')

    def test_mr17_an_lfs_source_is_read_or_a_filter_driver_gap_and_lfs_never_runs(self):
        self.assertFalse((self.paths['app'] / '.git' / 'lfs').exists())
        self.plan(self.item(patterns=('core:assets/', 'core:src/', 'app:src/', 'mirror:src/')))
        self.values += [lambda p, s: ask({'op': 'read', 'repo': 'core', 'path': 'assets/logo.bin'}, {'op': 'search', 'repo': 'core', 'query': 'needle'}),
                        lambda p, s: done(path=REPORT)]
        partial = self.step()                                       # the guard: no LFS object, hook, config line or tmp folder in any source
        produced = self.step()
        self.assertEqual((partial['state'], produced['state']), ('continuing', 'produced'), produced)
        rows = {r['repo']: r for r in self.tools(0)['repos']}
        self.assertEqual((rows['core']['status'], rows['core']['dirty']), ('pinned', False))
        for alias in ('app', 'mirror'):
            self.assertEqual((rows[alias]['status'], rows[alias].get('state')), ('unavailable', 'filter_driver'), rows[alias])
            self.assertIn('lfs', rows[alias]['reason'])
        self.assertIn('art/new.psd', rows['app']['reason'])
        self.assertIn('assets/logo.bin', rows['mirror']['reason'])
        self.assertEqual(sorted(g['repo'] for g in self.tools(0)['coverage_gaps']), ['app', 'mirror'])
        read = next(r['result'] for r in self.results(1) if r['action'] == 'read')
        self.assertTrue(read['text'].startswith('version https://git-lfs.github.com/spec/v1'), read)   # the committed pointer, as HEAD holds it
        self.assertTrue(read['cite'].startswith('core@'))
        self.assertFalse([p for k, p in self.events() if k == 'node.resumed' and p.get('knowledge_changed')])   # its publication check ran no LFS either
        self.assertFalse((self.paths['app'] / '.git' / 'lfs').exists())
        self.assertFalse((self.paths['app'] / '.git' / 'hooks' / 'pre-push').exists())


class FilterTests(MrrFixture):
    """A clean filter of the repository's own .git/config (filter.spy.clean) that would write a marker inside .git and a log beside the
    coordination folder. app: a file under the filter is edited (dirty). core: a file under the filter was only touched (clean)."""

    def prepare_repos(self):
        self.log = self.base / 'spy-ran.log'
        for alias in ('core', 'app'):
            root = self.paths[alias]
            write(root, {'.gitattributes': b'*.py filter=spy\n'}); git(root, 'add', '-A'); git(root, 'commit', '-q', '-m', 'a filter')
            script = self.base / f'spy-{alias}.sh'
            script.write_text(SPY.format(log=self.log.as_posix(), inside=(root / '.git' / 'spy-was-here').as_posix()), encoding='ascii', newline='\n')
            git(root, 'config', 'filter.spy.clean', f'sh "{script.as_posix()}"')
        time.sleep(1.1)
        git(self.paths['core'], 'update-index', '-q', '--really-refresh')       # the filter runs here (fixture), then never again
        if self.log.exists(): self.log.unlink()
        write(self.paths['app'], {'src/beta.py': b'BETA = 3\n# NEEDLE-BETA uncommitted, under a filter\n'})
        touch_later(self.paths['core'] / 'src' / 'alpha.py')

    def test_mr18_a_filter_of_the_repository_never_runs_and_a_change_under_it_is_a_gap(self):
        self.plan(self.item())
        self.values += [lambda p, s: ask({'op': 'read', 'repo': 'core', 'path': 'src/alpha.py'}, {'op': 'read', 'repo': 'app', 'path': 'src/beta.py'}),
                        lambda p, s: done(path=REPORT)]
        partial = self.step(); produced = self.step()
        self.assertFalse(self.log.exists(), 'the filter of a source repository ran: ' + (self.log.read_text() if self.log.exists() else ''))
        self.assertEqual(produced['state'], 'produced', produced)
        rows = {r['repo']: r for r in self.tools(0)['repos']}
        self.assertEqual((rows['core']['status'], rows['core']['dirty']), ('pinned', False))   # a touched file whose bytes did not change
        self.assertEqual((rows['app']['status'], rows['app'].get('state')), ('unavailable', 'filter_driver'), rows['app'])
        self.assertIn('spy', rows['app']['reason'])
        results = {r['arguments'].get('repo'): r['result'] for r in self.results(1)}
        self.assertIn('ALPHA = 1', results['core']['text'])
        refused = self.receipt(partial)['source']['refused']
        self.assertTrue(any(r['request'].get('repo') == 'app' and 'unavailable' in r['reason'] for r in refused), refused)
        self.assertNotIn('app', results)                  # rejected at seal; no request is queued or read in round two


class HookTests(MrrFixture):
    """Hooks of the sources: app has .git/hooks/post-index-change; core points core.hooksPath at a tracked folder with the same hook. Both
    are dirty, so their pins capture the working tree (the old capture wrote throw-away indexes, which runs post-index-change)."""

    def prepare_repos(self):
        self.log = self.base / 'hook-ran.log'
        app, core = self.paths['app'], self.paths['core']
        (app / '.git' / 'hooks' / 'post-index-change').write_text(
            HOOK.format(log=self.log.as_posix(), inside=(app / '.git' / 'hook-was-here').as_posix()), encoding='ascii', newline='\n')
        write(core, {'.githooks/post-index-change': HOOK.format(log=self.log.as_posix(), inside=(core / '.git' / 'hook-was-here').as_posix()).encode()})
        git(core, 'add', '-A'); git(core, 'commit', '-q', '-m', 'tracked hooks')
        git(core, 'config', 'core.hooksPath', '.githooks')
        write(app, {'src/beta.py': b'BETA = 3\n# NEEDLE-BETA uncommitted edit\n', 'src/draft.py': b'DRAFT = "NEEDLE-DRAFT untracked"\n'})
        write(core, {'src/alpha.py': b'ALPHA = 2\n# NEEDLE-ALPHA uncommitted edit\n'})
        if self.log.exists(): self.log.unlink()

    def test_mr19_no_hook_of_a_source_runs_while_it_is_pinned_and_read(self):
        self.plan(self.item())
        self.values += [lambda p, s: ask({'op': 'search', 'repo': 'app', 'query': 'needle'}, {'op': 'search', 'repo': 'core', 'query': 'needle'}),
                        lambda p, s: done(path=REPORT)]
        partial = self.step(); produced = self.step()
        self.assertFalse(self.log.exists(), 'a hook of a source repository ran: ' + (self.log.read_text() if self.log.exists() else ''))
        self.assertEqual(produced['state'], 'produced', produced)
        rows = {r['repo']: r for r in self.tools(0)['repos']}
        self.assertEqual({a: (r['status'], r['dirty']) for a, r in rows.items()}, {'app': ('pinned', True), 'core': ('pinned', True)})
        texts = {r['result']['source']['repo']: ' '.join(m['text'] for m in r['result']['matches']) for r in self.results(1)}
        self.assertIn('uncommitted edit', texts['app']); self.assertIn('NEEDLE-DRAFT', texts['app'])
        self.assertIn('uncommitted edit', texts['core'])


# ---- index shapes, sparse checkout, partial clones ----------------------------------------------------------------------------------

class IndexShapeTests(MrrFixture):
    """app: a split index (core.splitIndex, .git/sharedindex.<id>); core: a sparse index (sparse-checkout --cone --sparse-index). Both clean.
    Git refreshes the shared index's time on every read of a split index, and rewrites (touches) tree objects whenever it expands a sparse one."""

    def prepare_repos(self):
        app, core = self.paths['app'], self.paths['core']
        git(app, 'config', 'core.splitIndex', 'true'); git(app, 'update-index', '--split-index'); git(app, 'status', '--porcelain')
        git(core, 'sparse-checkout', 'init', '--cone', '--sparse-index'); git(core, 'sparse-checkout', 'set', 'src')
        time.sleep(1.1)

    def test_mr20_a_split_index_is_read_untouched_and_a_sparse_index_is_a_gap(self):
        self.assertTrue(list((self.paths['app'] / '.git').glob('sharedindex.*')))
        self.plan(self.item())
        self.values += [lambda p, s: ask({'op': 'read', 'repo': 'app', 'path': 'src/beta.py'}, {'op': 'read', 'repo': 'core', 'path': 'src/alpha.py'}),
                        lambda p, s: done(path=REPORT)]
        partial = self.step(); produced = self.step()
        self.assertEqual(produced['state'], 'produced', produced)
        rows = {r['repo']: r for r in self.tools(0)['repos']}
        self.assertEqual((rows['app']['status'], rows['app']['dirty']), ('pinned', False))
        self.assertEqual((rows['core']['status'], rows['core'].get('state')), ('unavailable', 'sparse_index'), rows['core'])
        results = {r['arguments'].get('repo'): r['result'] for r in self.results(1)}
        self.assertIn('BETA = 2', results['app']['text'])
        refused = self.receipt(partial)['source']['refused']
        self.assertTrue(any(r['request'].get('repo') == 'core' and 'unavailable' in r['reason'] for r in refused), refused)
        self.assertNotIn('core', results)
        self.assertEqual([g['repo'] for g in self.receipt(produced)['source']['coverage_gaps']], ['core'])


class SparseCheckoutTests(MrrFixture):
    """app has a cone sparse checkout of src (a full index): docs/guide.md is in HEAD and in the snapshot, not on disk (skip-worktree)."""

    def prepare_repos(self):
        app = self.paths['app']
        git(app, 'sparse-checkout', 'init', '--cone'); git(app, 'sparse-checkout', 'set', 'src')
        self.assertFalse((app / 'docs' / 'guide.md').exists())

    def test_mr21_a_sparse_checkout_source_is_published_without_a_false_change(self):
        self.plan(self.item(patterns=('core:src/', 'app:src/', 'app:docs/')))
        self.values += [lambda p, s: ask({'op': 'read', 'repo': 'app', 'path': 'docs/guide.md'}, {'op': 'list', 'repo': 'app', 'path': 'docs'}),
                        lambda p, s: done(path=REPORT)]
        partial = self.step(); produced = self.step()
        self.assertEqual((partial['state'], produced['state']), ('continuing', 'produced'), produced)
        self.assertFalse([p for k, p in self.events() if k == 'node.resumed' and p.get('knowledge_changed')],
                         'a file outside the sparse checkout was taken for a changed source')
        read = next(r['result'] for r in self.results(1) if r['action'] == 'read')
        self.assertIn('The app VALUE: green', read['text'])


class PartialCloneTests(MrrFixture):
    """core: a blobless clone (--filter=blob:none) with a sparse checkout of the top folder only: the blobs of src/ and docs/ are not in it and
    would be fetched from its promisor (a local file:// origin; no network here). mirror: a blobless clone with a full checkout: every blob of
    HEAD is local. app: a plain repository."""
    repos = {'core': ('repo-a', None), 'app': ('repo-b', REPO_B), 'mirror': ('repo-m', None)}
    target = ('repo-b', ('src/beta.py',))                                # core's src/ is not checked out

    def prepare_repos(self):
        self.origin = self.base / 'origin-a'
        make_repo(self.origin, REPO_A)
        git(self.origin, 'config', 'uploadpack.allowFilter', 'true'); git(self.origin, 'config', 'uploadpack.allowAnySHA1InWant', 'true')
        for alias, folder, extra in (('core', 'repo-a', ['--sparse']), ('mirror', 'repo-m', [])):
            target = self.work / folder
            cloned = subprocess.run(['git', 'clone', '-q', '--filter=blob:none', *extra, 'file:///' + self.origin.as_posix(), str(target)],
                                    capture_output=True, env=dated())
            self.assertEqual(cloned.returncode, 0, cloned.stderr.decode('utf-8', 'replace'))
            self.paths[alias] = target
        listing = git(self.paths['core'], 'rev-list', '--objects', '--missing=print', 'HEAD', env=dict(dated(), GIT_NO_LAZY_FETCH='1'))
        self.missing = [line for line in listing.splitlines() if line.startswith('?')]
        self.assertTrue(self.missing, 'the fixture clone holds every blob')
        time.sleep(1.1)

    def also_watched(self):
        return {'origin': self.origin}

    def test_mr22_a_partial_clone_is_never_fetched_from_and_missing_blobs_are_a_gap(self):
        packs = sorted(p.name for p in (self.paths['core'] / '.git' / 'objects' / 'pack').iterdir())
        self.plan(self.item(patterns=('core:src/', 'mirror:src/', 'app:src/')))
        self.values += [lambda p, s: ask({'op': 'read', 'repo': 'core', 'path': 'src/alpha.py'}, {'op': 'read', 'repo': 'mirror', 'path': 'src/alpha.py'}),
                        lambda p, s: done(path=REPORT)]
        partial = self.step(); produced = self.step()              # the guard: no pack, no promisor file in any clone, the origin untouched
        self.assertEqual(produced['state'], 'produced', produced)
        self.assertEqual(sorted(p.name for p in (self.paths['core'] / '.git' / 'objects' / 'pack').iterdir()), packs)
        rows = {r['repo']: r for r in self.tools(0)['repos']}
        self.assertEqual((rows['core']['status'], rows['core'].get('state')), ('unavailable', 'partial_clone'), rows['core'])
        self.assertEqual((rows['mirror']['status'], rows['app']['status']), ('pinned', 'pinned'))
        results = {r['arguments'].get('repo'): r['result'] for r in self.results(1)}
        self.assertIn('ALPHA = 1', results['mirror']['text'])
        refused = self.receipt(partial)['source']['refused']
        self.assertTrue(any(r['request'].get('repo') == 'core' and 'unavailable' in r['reason'] for r in refused), refused)
        self.assertNotIn('core', results)
        listing = git(self.paths['core'], 'rev-list', '--objects', '--missing=print', 'HEAD', env=dict(dated(), GIT_NO_LAZY_FETCH='1'))
        self.assertEqual([line for line in listing.splitlines() if line.startswith('?')], self.missing)   # not one missing blob was fetched


# ---- where OneCrew writes ------------------------------------------------------------------------------------------------------------

class RootPlaceTests(MrrFixture):
    def propose_refused(self, ledger, name, contract, watched, why):
        before = {k: fingerprint(v) for k, v in watched.items()}
        with self.assertRaises(LedgerError, msg=why) as caught:
            plans.propose(ledger, name, contract, 'codex', workflow=True, capabilities=CAPS)
        for k, v in watched.items():
            self.assertEqual(changed(before[k], fingerprint(v)), [], f'{why}: the refused proposal wrote into {k}')
        return str(caught.exception)

    def test_mr23_the_state_root_and_the_coordination_folder_never_lie_inside_a_declared_repository(self):
        ext = self.base / 'ext' / 'repo-x'
        make_repo(ext, REPO_C)
        repos = self.declared() + [{'alias': 'ext', 'path': ext.as_posix(), 'read': ['src/**']}]
        message = self.propose_refused(Ledger(self.work, ext / '.onecrew-state'), 'P2', self.contract(repos=repos), {'ext': ext},
                                       'a state root inside a repository declared by an absolute path')
        self.assertIn('state root', message)
        self.assertFalse((ext / '.onecrew-state').exists())
        main = self.base / 'main'
        make_repo(main, REPO_C)
        git(main, 'worktree', 'add', '-q', str(self.work / 'wt'))
        repos = self.declared() + [{'alias': 'wt', 'path': 'wt', 'read': ['src/**']}]
        self.propose_refused(Ledger(self.work, main / '.git' / 'onecrew-state'), 'P3', self.contract(repos=repos), {'main': main},
                             'a state root inside the Git directory of a declared linked worktree')
        outer = self.base / 'outer'
        make_repo(outer, REPO_C)
        write(outer / 'coord', {'a.txt': b'coordination\n', 'brief.md': b'# Brief\n'})
        repos = [{'alias': 'outer', 'path': outer.as_posix(), 'read': ['src/**']}]
        self.propose_refused(Ledger(outer / 'coord', self.base / 'state-outer'), 'P4', self.contract(repos=repos), {'outer': outer},
                             'a coordination folder inside a repository declared by an absolute path')

    def test_mr24_scope_owned_never_names_a_path_inside_a_declared_repository(self):
        from onecrew.v2 import contract as contracts
        for owned in (['a.txt', './repo-a'], ['a.txt', '.\\repo-a'], ['a.txt', './repo-a/'], ['a.txt', 'REPO-A'], ['a.txt', 'repo-a/x.py'],
                      ['repo-*'], ['*'], ['**'], ['.'], ['*.md'], ['a.txt', 'repo-b/../repo-b/x.md']):
            with self.assertRaises(LedgerError, msg=owned):
                contracts.validate(self.contract(owned=owned))
        contracts.validate(self.contract(owned=['a.txt', 'reports/*.md', 'reports/analysis.md', 'repo-a.md']))   # outside every repository
        absolute = [{'alias': 'core', 'path': self.paths['core'].as_posix(), 'read': ['src/**']}]
        self.propose_refused(self.ledger, 'P5', self.contract(repos=absolute, owned=['a.txt', 'repo-a/out.txt']), {'core': self.paths['core']},
                             'scope.owned inside a repository declared by an absolute path under the coordination folder')


# ---- citations, vanished objects --------------------------------------------------------------------------------------------------

LINES = {'src/lines/ff.py': b'header\n# section A\n\x0c\nTARGET = "needle-ff"\ntail\n',
         'src/lines/vt.txt': b'one\x0btwo\nneedle-vt here\n',
         'src/lines/fs.txt': b'a\x1cb\x1dc\x1ed\nneedle-fs\n',
         'src/lines/nel.txt': 'a\x85b\nneedle-nel\n'.encode('utf-8'),
         'src/lines/ls.txt': 'a b c\nneedle-ls\n'.encode('utf-8'),
         'src/lines/cr.txt': b'progress 1\rprogress 2\rdone\nneedle-cr\n',
         'src/lines/crlf.txt': b'first\r\nneedle-crlf\r\n',
         'src/lines/lf.txt': b'first\nneedle-lf\n',
         'src/lines/lead.txt': b'\n\nneedle-lead\n'}


class CiteTests(MrrFixture):
    """Files whose line ends str.splitlines() reads differently from git (FF, VT, FS/GS/RS, NEL, LS/PS, a lone CR), a CRLF and an LF
    control and a file that starts with blank lines; committed byte for byte (core.autocrlf off for that commit)."""

    def prepare_repos(self):
        core = self.paths['core']
        write(core, LINES)
        git(core, '-c', 'core.autocrlf=false', 'add', '-A'); git(core, 'commit', '-q', '-m', 'line ends')

    def test_mr25_every_cite_names_the_line_git_counts(self):
        self.plan(self.item(patterns=('core:src/',)))
        self.values += [lambda p, s: ask({'op': 'search', 'repo': 'core', 'query': 'needle', 'path': 'src/lines'},
                                         *[{'op': 'read', 'repo': 'core', 'path': p} for p in ('src/lines/ff.py', 'src/lines/cr.txt', 'src/lines/lead.txt')]),
                        lambda p, s: done(path=REPORT)]
        self.step(); produced = self.step()
        tree = next(r['tree'] for r in self.tools(1)['repos'] if r['repo'] == 'core')        # the snapshot the results of round 2 come from
        search = next(r['result'] for r in self.results(1) if r['action'] == 'search')
        found = {m['path']: m for m in search['matches']}
        self.assertEqual(set(found), set(LINES))
        grep = git(self.paths['core'], 'grep', '-n', '-i', '-F', 'needle', tree, '--', 'src/lines', env=dict(dated(), GIT_NO_LAZY_FETCH='1'))
        lines_by_git = {row.split(':', 3)[1]: int(row.split(':', 3)[2]) for row in grep.splitlines()}
        wrong = []
        for path, match in sorted(found.items()):
            rows = lf_lines(blob_bytes(self.paths['core'], f'{tree}:{path}'))
            line = int(match['cite'].rsplit(':', 1)[1])
            if line != lines_by_git[path] or match['line'] != line or line > len(rows) or rows[line - 1] != match['text']:
                wrong.append((path, match['cite'], 'git grep -n: %d' % lines_by_git[path]))
        self.assertEqual(wrong, [], 'search cites that name another line than git does')
        for read in (r['result'] for r in self.results(1) if r['action'] == 'read'):
            rows = lf_lines(blob_bytes(self.paths['core'], f'{tree}:{read["path"]}'))
            self.assertEqual(read['cite'].rsplit(':', 1)[1], f'1-{len(rows)}' if len(rows) > 1 else '1', read['cite'])
        # published, with no false change: a blob committed with CRLF under core.autocrlf=true is not "changed" at publication
        self.assertEqual(produced['state'], 'produced', produced)
        self.assertFalse([p for k, p in self.events() if k == 'node.resumed' and p.get('knowledge_changed')])
        receipt = self.receipt(produced)
        for read in (r['result'] for r in self.results(1) if r['action'] == 'read'):
            self.assertEqual(self.cite_lines(read['cite'], receipt), lf_lines(blob_bytes(self.paths['core'], f'{tree}:{read["path"]}')))


class VanishTests(MrrFixture):
    """app is dirty when it is pinned: its snapshot lives in OneCrew's private store and borrows the repository's own objects for every file
    the edit did not touch. Then the owner drops the last commit and prunes (reset + reflog expire + gc --prune=now): a borrowed blob is gone."""

    def prepare_repos(self):
        app = self.paths['app']
        commit(app, {'src/beta2.py': b'BETA2 = "NEEDLE-BETA2 only in the last commit"\nsecond line\n'}, 'a last commit')
        write(app, {'src/beta.py': b'BETA = 3\n# NEEDLE-BETA uncommitted edit\n'})

    def test_mr26_a_dirty_pin_whose_borrowed_objects_vanished_is_a_gap_not_an_empty_file(self):
        self.plan(self.item())
        self.values += [lambda p, s: ask({'op': 'read', 'repo': 'app', 'path': 'src/beta2.py'}, {'op': 'read', 'repo': 'core', 'path': 'src/alpha.py'},
                                         {'op': 'search', 'repo': 'app', 'query': 'second line'}),
                        lambda p, s: done(path=REPORT)]
        self.assertEqual(self.step()['state'], 'continuing')
        app = self.paths['app']
        pin = next(p for k, p in self.events() if k == 'node.started' and p['node'] == 'R')['source_tree']['repos']['app']
        self.assertEqual(pin['objects'], 'private')
        oid = git(app, 'rev-parse', 'HEAD:src/beta2.py')
        git(app, 'reset', '-q', '--soft', 'HEAD~1'); git(app, 'reset', '-q')
        (app / '.git' / 'ORIG_HEAD').unlink(missing_ok=True)
        git(app, 'reflog', 'expire', '--expire=now', '--all'); git(app, 'gc', '-q', '--prune=now')
        self.assertNotEqual(subprocess.run(['git', '-C', str(app), 'cat-file', '-e', oid], capture_output=True).returncode, 0, 'the blob is still there')
        produced = self.step()
        self.assertEqual(produced['state'], 'produced', produced)
        second = self.tools(1)
        row = next(r for r in second['repos'] if r['repo'] == 'app')
        self.assertEqual(row['status'], 'unreadable', row)
        self.assertIn('app', [g['repo'] for g in second['coverage_gaps']])
        for record in second['results']:
            result = record.get('result') or {}
            if (result.get('source') or {}).get('repo') == 'app' or record['arguments'].get('repo') == 'app':
                self.assertNotIn('text', result, record)
                self.assertNotIn('cite', result, record)
                self.assertIn('refused', result, record)
        core = next(r['result'] for r in second['results'] if r['arguments'].get('repo') == 'core')
        self.assertIn('ALPHA = 1', core['text'])


# ---- smaller findings ----------------------------------------------------------------------------------------------------------------

def _cursor(data):
    return 'm1.' + base64.urlsafe_b64encode(json.dumps(data).encode('utf-8')).decode('ascii').rstrip('=')


class CursorTests(MrrFixture):
    def test_mr27_a_cursor_with_values_of_the_wrong_type_is_refused_and_the_round_goes_on(self):
        with patch.object(st(), 'LIST_ENTRIES', 1):
            self.plan(self.item())
            def first(prompt, schema):
                cursor = self.by_repo(body_of(prompt)['source_tools']['results'], 'list')['core']['next_cursor']
                data = json.loads(base64.urlsafe_b64decode(cursor[3:] + '=' * (-len(cursor[3:]) % 4)))
                return ask({'op': 'list', 'cursor': _cursor(dict(data, r=dict(data['r'], alias=['core'])))},      # an unhashable alias
                           {'op': 'list', 'cursor': _cursor(dict(data, a=dict(data['a'], path=5)))},              # a path that is a number
                           {'op': 'read', 'repo': 'core', 'path': 'src/alpha.py'})
            self.values += [first, lambda p, s: done(path=REPORT)]
            partial = self.step()
            self.assertEqual(partial['state'], 'continuing', partial)
            produced = self.step()
        self.assertEqual(produced['state'], 'produced', produced)
        refused = self.receipt(partial)['source']['refused']
        self.assertEqual(len(refused), 2, refused)
        self.assertTrue(all('cursor' in r['reason'] for r in refused), refused)
        self.assertEqual(self.receipt(partial)['source']['requests'], [{'op': 'read', 'repo': 'core', 'path': 'src/alpha.py'}])


class PageGapTests(MrrFixture):
    def test_mr28_a_page_of_a_result_of_a_repository_that_became_a_gap_is_refused(self):
        self.plan(self.item())
        def first(prompt, schema):
            results = body_of(prompt)['source_tools']['results']
            index = next(r['index'] for r in results if r['action'] == 'list' and r['result']['source']['repo'] == 'app')
            return ask({'op': 'page', 'index': index, 'field': 'entries'}, {'op': 'read', 'repo': 'core', 'path': 'src/alpha.py'})
        self.values += [first, lambda p, s: done(path=REPORT)]
        self.assertEqual(self.step()['state'], 'continuing')
        shutil.move(str(self.paths.pop('app')), str(self.base / 'moved-away'))
        produced = self.step()
        self.assertEqual(produced['state'], 'produced', produced)
        second = self.tools(1)
        self.assertEqual([g['repo'] for g in second['coverage_gaps']], ['app'])
        shown = [r for r in second['results'] if ((r.get('result') or {}).get('source') or {}).get('repo') == 'app']
        self.assertEqual(shown, [], 'an earlier result of a repository that is a coverage gap now was delivered again')
        page = next(r for r in second['results'] if r['action'] == 'page')
        self.assertIn('app', page['result']['refused'])


@unittest.skipUnless(os.name == 'nt', 'a junction is a Windows link')
class GitDirLinkTests(MrrFixture):
    """app's .git is a junction to the Git directory of another, undeclared repository (secret)."""

    def prepare_repos(self):
        secret = self.base / 'secret'
        make_repo(secret, {'src/beta.py': b'BETA = "NEEDLE-SECRET of an undeclared repository"\n'})
        app = self.paths['app']
        remove_tree(app / '.git')
        made = subprocess.run(['cmd', '/c', 'mklink', '/J', str(app / '.git'), str(secret / '.git')], capture_output=True)
        if made.returncode: self.skipTest('mklink /J is not available here: ' + made.stderr.decode('utf-8', 'replace')[:200])
        self.addCleanup(lambda: os.rmdir(app / '.git') if os.path.lexists(app / '.git') else None)
        self.secret = secret

    def also_watched(self):
        return {'secret': self.secret}

    def test_mr29_a_declared_folder_whose_git_directory_is_a_junction_is_a_link_gap(self):
        pin = sr().pin_repo(self.ledger, 'app', 'repo-b')
        self.assertEqual((pin['kind'], pin.get('state')), ('unavailable', 'link'), pin)
        self.assertIn('.git', pin['reason'])
        self.plan(self.item())
        self.values += [lambda p, s: ask({'op': 'read', 'repo': 'app', 'path': 'src/beta.py'}), lambda p, s: done(path=REPORT)]
        self.step(); self.step()
        self.assertNotIn('NEEDLE-SECRET', self.prompts())


class LabelTests(MrrFixture):
    """core is in the middle of a bisect (HEAD detached at a probe commit), app's HEAD is detached, mirror is refused by git for dubious
    ownership (simulated with git's GIT_TEST_ASSUME_DIFFERENT_OWNER), bare.git is a bare repository."""
    repos = {'core': ('repo-a', REPO_A), 'app': ('repo-b', REPO_B), 'mirror': ('repo-m', REPO_A)}

    def prepare_repos(self):
        core = self.paths['core']
        commit(core, {'src/alpha.py': b'ALPHA = 2\n# NEEDLE-ALPHA two\n'}, 'two'); commit(core, {'src/alpha.py': b'ALPHA = 3\n# NEEDLE-ALPHA three\n'}, 'three')
        git(core, 'bisect', 'start'); git(core, 'bisect', 'bad'); git(core, 'bisect', 'good', 'HEAD~2')
        git(self.paths['app'], 'checkout', '-q', '--detach')
        subprocess.run(['git', 'init', '-q', '--bare', str(self.work / 'bare.git')], check=True, capture_output=True)

    def test_mr30_bisect_detached_dubious_and_bare_are_named_as_they_are(self):
        pins = {alias: sr().pin_repo(self.ledger, alias, folder) for alias, (folder, _) in self.repos.items()}
        self.assertEqual(pins['core']['kind'], 'git-tree')
        self.assertIn('bisect', pins['core'].get('label', ''), pins['core'])
        self.assertEqual(pins['app']['kind'], 'git-tree')
        self.assertIn('detached', pins['app'].get('label', ''), pins['app'])
        with patch.dict(sr().READ_ONLY, GIT_TEST_ASSUME_DIFFERENT_OWNER='1'):
            dubious = sr().pin_repo(self.ledger, 'mirror', 'repo-m')
        self.assertEqual((dubious['kind'], dubious.get('state')), ('unavailable', 'dubious_ownership'), dubious)
        self.assertIn('safe.directory', dubious['reason'])
        bare = sr().pin_repo(self.ledger, 'bare', 'bare.git')
        self.assertEqual((bare['kind'], bare.get('state')), ('unavailable', 'bare_repository'), bare)
        self.plan(self.item())
        self.values += [lambda p, s: done(path=REPORT)]
        self.step()
        rows = {r['repo']: r for r in self.tools(0)['repos']}
        self.assertIn('bisect', rows['core'].get('label', ''), rows['core'])
        self.assertIn('detached', rows['app'].get('label', ''), rows['app'])


class SymlinkTests(MrrFixture):
    def prepare_repos(self):
        app = self.paths['app']
        try:
            os.symlink('beta.py', app / 'src' / 'link.py')
            os.symlink('../docs', app / 'src' / 'dlink', target_is_directory=True)
            os.symlink(str(app / 'src' / 'beta.py'), app / 'src' / 'abs.py')                  # an absolute target (os.readlink: \\?\D:\...)
        except OSError as error:
            self.skipTest(f'symbolic links cannot be made here ({error})')
        write(app, {'src/beta.py': b'BETA = 3\n# NEEDLE-BETA uncommitted edit\n'})

    def test_mr31_an_untracked_symbolic_link_in_a_dirty_repository_is_pinned_as_a_link(self):
        pin = sr().pin_repo(self.ledger, 'app', 'repo-b')
        self.assertEqual((pin['kind'], pin.get('dirty')), ('git-tree', True), pin)
        reader = sr().reader(self.ledger, 'app', pin)
        modes = {e['path']: e['mode'] for e in reader.entries().values()}
        self.assertEqual((modes.get('src/link.py'), modes.get('src/dlink'), modes.get('src/abs.py')), ('120000', '120000', '120000'))
        listed = st().run(reader, st().Scope(['src/**'], ['src/']), {'op': 'list', 'path': 'src'})['result']
        self.assertIn({'path': 'src/link.py', 'reason': 'link'}, listed['withheld'])


if __name__ == '__main__':
    unittest.main()
