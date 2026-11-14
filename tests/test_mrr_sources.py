"""MR-R (docs/mrr/DOI-CHIEU-MR-R.vi.md; ROADMAP-DESIGN §2.11): one task reads and searches several Git repositories that the root contract
declares and grants (`authority.repos`), from a coordination folder that is NOT a Git repository; evidence names repository + snapshot +
file:line; the source repositories are only read (their .git included); a missing, dirty, conflicted or unreachable source is handled and
reported for its own scope; restarts keep identities, grants and budget; a revoked grant stops the reads and shows as a coverage gap.

Checkout tests on real Git repositories and ledgers with the fixture worker of 2.4-A (no model call). Every engine step is wrapped: the
whole folder of every source repository (working tree and .git: names, sizes, modification times of files and folders, bytes) must be the
same before and after. Repositories that use Git features which run programs or touch files (LFS and other filters, hooks, split and sparse
indexes, partial clones...) are in tests/test_mrr_isolation.py. The installed-wheel run is outside the unit suite (D:/OneCrewRuns/wf-dev-tools/mrr).
"""
import copy
import hashlib
import json
import os
import shutil
import stat
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from onecrew.common_executor import NativeExecutor
from onecrew.control import Control, migrate
from onecrew.ledger import Ledger, LedgerError, content_hash
from onecrew.snapshots import Snapshots
from onecrew.v2 import plan as plans
from tests.test_v2_l1 import plan_json
from tests.test_wf_engine import node
from tests.test_v24_a_sources import WorkerMixin, Crash, ask, body_of, done

PIN = {'role': 'worker', 'provider': 'claude', 'model': 'claude-haiku-5-5'}
CAPS = ['namespaced-storage', 'root-budget', 'internal-plan', 'sequential-engine']
SELF = ['Q1', 'Q2', 'Q3', 'Q4', 'Q5', 'Q9', 'Q12']
DATE = '2026-11-01T10:00:00+07:00'
REPORT = 'reports/analysis.md'
SHARED = b'def shared():\n    return "the same bytes in both repositories"\n'
REPO_A = {'src/shared.py': SHARED,
          'src/alpha.py': b'ALPHA = 1\n# NEEDLE-ALPHA marks the core repository\n',
          'src/.env.local': b'TOKEN=never-shown-core\n',
          'docs/guide.md': b'# Core guide\nThe core VALUE: blue\n',
          'README.md': b'core readme\n'}
REPO_B = {'src/shared.py': SHARED,
          'src/beta.py': b'BETA = 2\n# NEEDLE-BETA marks the app repository\n',
          'docs/guide.md': b'# App guide\nThe app VALUE: green\n',
          'README.md': b'app readme\n'}
REPO_C = {'src/hidden.py': b'HIDDEN = "NEEDLE-HIDDEN outside every grant"\n'}


def st():
    from onecrew.v2 import source_tools
    return source_tools


def sr():
    from onecrew.v2 import source_repos
    return source_repos


def dated():
    return dict(os.environ, GIT_AUTHOR_DATE=DATE, GIT_COMMITTER_DATE=DATE)


def git(root, *args, env=None, input=None, check=True):
    done_ = subprocess.run(['git', '-C', str(root), *args], capture_output=True, input=input, env=env or dated())
    if check and done_.returncode: raise AssertionError(f'git {args} failed: {done_.stderr.decode("utf-8", "replace")}')
    return done_.stdout.decode('utf-8', 'replace').strip()


def write(root, files):
    for name, data in files.items():
        path = Path(root) / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)


def make_repo(root, files, message='base'):
    Path(root).mkdir(parents=True)
    git(root, 'init', '-q', '-b', 'main'); git(root, 'config', 'user.name', 'T'); git(root, 'config', 'user.email', 't@localhost')
    write(root, files)
    git(root, 'add', '-A'); git(root, 'commit', '-q', '-m', message)


def commit(root, files, message='change'):
    write(root, files)
    git(root, 'add', '-A'); git(root, 'commit', '-q', '-m', message)


def remove_tree(path):
    def retry(function, name, _):
        os.chmod(name, stat.S_IWRITE); function(name)
    shutil.rmtree(path, onerror=retry)


def fingerprint(root):
    """Every name under `root` (.git included; links and junctions are not followed): a file with its size, modification time and bytes, a
    folder with the names in it AND its own modification time (a file made and removed again, such as a lock or a temporary file of a filter,
    changes the time of its folder), a link with its target."""
    out = {}
    for folder, dirs, files in os.walk(root):
        dirs.sort()
        rel = os.path.relpath(folder, root).replace('\\', '/')
        out['dir:' + rel] = (sorted(dirs + files), os.lstat(folder).st_mtime_ns)
        for name in sorted(files):
            path = os.path.join(folder, name)
            facts = os.lstat(path)
            if stat.S_ISLNK(facts.st_mode):
                out[rel + '/' + name] = ('link', os.readlink(path), facts.st_mtime_ns)
                continue
            with open(path, 'rb') as handle:
                digest = hashlib.sha256(handle.read()).hexdigest()
            out[rel + '/' + name] = (facts.st_size, facts.st_mtime_ns, digest)
    return out


def changed(before, after):
    """The names whose fingerprint entry differs (made, removed, or another size, time or content)."""
    return sorted(k for k in set(before) | set(after) if before.get(k) != after.get(k))


def lf_lines(data):
    """The lines of a blob as git counts them (git grep -n, blame, sed): split at LF only; a CR before the LF is not part of the line; no
    strip, so a file that starts with blank lines keeps its numbering. An independent oracle for `cite` (never the product's own splitter)."""
    text = data.decode('utf-8-sig', 'replace')
    rows = text.split('\n')
    if rows and rows[-1] == '': rows.pop()
    return [r[:-1] if r.endswith('\r') else r for r in rows]


def blob_bytes(root, spec, env=None):
    """The raw bytes of `git cat-file blob <spec>` (no decoding, no strip)."""
    done_ = subprocess.run(['git', '-C', str(root), 'cat-file', 'blob', spec], capture_output=True, env=env or dated())
    if done_.returncode: raise AssertionError(f'git cat-file blob {spec} failed: {done_.stderr.decode("utf-8", "replace")}')
    return done_.stdout


def objects(root):
    """The loose and packed object files of a repository."""
    base = Path(root) / '.git' / 'objects'
    return sorted(str(p.relative_to(base)) for p in base.rglob('*') if p.is_file())


class MrrFixture(WorkerMixin, unittest.TestCase):
    """A coordination folder (not Git) holding the declared repositories and one undeclared repository (repo-c)."""
    repos = {'core': ('repo-a', REPO_A), 'app': ('repo-b', REPO_B)}
    grants = {'core': ['src/**', 'docs/'], 'app': ['src/**', 'docs/'], 'mirror': ['src/**', 'docs/'], 'gone': ['src/**'], 'plain': ['src/**'],
              'linked': ['src/**']}
    extra = {'other': ('repo-c', REPO_C)}
    target = ('repo-a', ('src/alpha.py',))                              # understanding.target of the root (step 0 checks the file exists)

    def setUp(self):
        env = patch.dict(os.environ); env.start(); self.addCleanup(env.stop)
        for name in ('ONECREW_ACTOR', 'ONECREW_V2_REQUIRE_PLAN', 'CLAUDECODE', 'CLAUDE_CODE_CHILD_SESSION'): os.environ.pop(name, None)
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.work = self.base / 'work'; self.work.mkdir()             # the coordination folder: never a Git repository
        if subprocess.run(['git', '-C', str(self.work), 'rev-parse', '--git-dir'], capture_output=True).returncode == 0:
            # an environment error, never a skip: a skipped MR-R test is not a passed one (review R1 tests-evidence-1)
            self.fail('TEMP lies inside a Git repository: the coordination folder of these tests must not be in one; run with TEMP elsewhere')
        write(self.work, {'a.txt': b'coordination\n', 'brief.md': b'# Brief\nCompare core and app.\n'})
        self.paths = {}
        for alias, (folder, files) in {**self.repos, **self.extra}.items():
            if files is None: continue                                  # declared, never made
            make_repo(self.work / folder, files)
            self.paths[alias] = self.work / folder
        self.prepare_repos()
        self.ledger = Ledger(self.work, self.base / 'state')
        from onecrew.v2 import internal_plan, engine
        self.ip, self.engine = internal_plan, engine
        plans.propose(self.ledger, 'P1', self.contract(), 'codex', workflow=True, capabilities=CAPS)
        plans.approve(self.ledger, 'P1', 'owner', 'fixture approval of a multi-repository reading root')
        os.environ['ONECREW_ACTOR'] = 'codex'
        self.store = Snapshots(self.ledger.state_root)
        migrate(self.ledger)
        self.control = Control(self.ledger)
        self.start_worker()

    def prepare_repos(self):
        """Subclasses change the repositories here, before the root exists."""

    def declared(self, only=None):
        return [{'alias': alias, 'path': folder, 'read': list(self.grants[alias])}
                for alias, (folder, _) in self.repos.items() if only is None or alias in only]

    def contract(self, repos=None, owned=None):
        authority = {'edit': True, 'commands': True, 'edit_tests': True, 'self_decide': SELF, 'read': ['brief.md'],
                     'repos': self.declared() if repos is None else repos}
        understanding = {'restated_goal': 'Compare the core and app repositories and cite every finding.',
                         'target': {'repo': self.target[0], 'ref': 'HEAD', 'paths': list(self.target[1])},
                         'assumptions': [], 'confidence': 'high', 'unknowns': []}
        return plan_json(scope={'owned': owned or ['a.txt', REPORT, 'reports/other.md']}, authority=authority, understanding=understanding)

    # The shared node() helper gives a node a 60 s execution cap: scaffolding for tests that run no git. A node of these tests pins two repositories,
    # reads them under the Sol6 read isolation (a throw-away object store per read) and hashes dirty trees, so one engine step measured 10-14 s on a
    # quiet machine and 30-100 s on a loaded one (Defender, other agents): the cap then ended the step with "Root deadline exhausted" / held, a
    # flake that proved nothing about reading. The cap is widened here; DeadlineTests keeps one test that proves a cap still stops work.
    NODE_CAP = 1800

    def item(self, nid='R', patterns=('core:src/', 'app:src/'), read=('brief.md',), write=(REPORT,), rounds=4, chars=40000, cap=None):
        value = node(nid, write=write)
        value['execution_cap_seconds'] = cap or self.NODE_CAP
        value['read'] = list(read); value['executor'] = dict(PIN)
        value['sources'] = {'read': list(patterns), 'max_rounds': rounds, 'max_chars_per_round': chars}
        return value

    def plan(self, *items):
        integration = node('I', [i['id'] for i in items], integration=True, write=())
        integration['executor'] = dict(PIN)
        integration['execution_cap_seconds'] = self.NODE_CAP
        return self.ip.revise(self.ledger, 'P1', [*items, integration], reason='Multi-repository reading fixture', evidence=['a.txt:1'])

    def step(self, adapter=None):
        """One engine step; no source repository may change while it runs (its whole folder, .git included)."""
        watched = dict(self.paths, **self.also_watched())
        before = {alias: fingerprint(path) for alias, path in watched.items() if path.exists()}
        result = self.engine.step(self.ledger, 'P1', adapter or self.adapter)
        after = {alias: fingerprint(path) for alias, path in watched.items() if path.exists()}
        self.assertEqual(before.keys(), after.keys())
        for alias in before:
            self.assertEqual(changed(before[alias], after[alias]), [], f'an engine step wrote into the source repository {alias}')
        return result

    def also_watched(self):
        """Folders a subclass watches next to the declared repositories (the main repository of a linked worktree, an origin)."""
        return {}

    def run_until(self, done_states=('produced', 'held'), limit=12):
        states = []
        for _ in range(limit):
            result = self.step()
            states.append(result)
            if result.get('state') in done_states and result.get('node') != 'I' or result.get('state') == 'waiting': break
        return states

    def events(self, name='P1'):
        with self.ledger.transaction() as conn:
            task = plans.derive(self.ledger, conn, name)['task_id']
            return [(r['kind'], json.loads(r['payload'])) for r in conn.execute('SELECT kind,payload FROM events WHERE task_id=? ORDER BY seq', (task,))]

    def tools(self, call=-1):
        return body_of(self.calls[call]['prompt'])['source_tools']

    def results(self, call=-1):
        return self.tools(call)['results']

    def receipt(self, result):
        if result.get('receipt'): return json.loads(self.store.read_blob(result['receipt']))
        if result.get('candidate'): return json.loads(self.store.read_blob(result['candidate']['receipt']))
        retained = [p for k, p in self.events() if k == 'node.result_retained' and p.get('attempt') == result['continues_attempt']]
        return json.loads(self.store.read_blob(retained[-1]['candidate']['receipt']))

    def receipts(self, nid='R'):
        out = []
        for kind, payload in self.events():
            if payload.get('node') != nid: continue
            if kind == 'node.result_retained': out.append(json.loads(self.store.read_blob(payload['candidate']['receipt'])))
            if kind == 'node.produced': out.append(json.loads(self.store.read_blob(payload['receipt'])))
        return out

    def prompts(self):
        return '\n'.join(call['prompt'] for call in self.calls)

    def remaining_calls(self):
        with self.ledger.transaction() as conn:
            root = plans.anchor_events(self.ledger, conn, 'P1')
            return self.ip.ceilings(self.ledger, conn, root)['remaining_calls']

    def by_repo(self, results, action):
        return {r['result']['source']['repo']: r['result'] for r in results if r['action'] == action and 'source' in (r.get('result') or {})}

    def cite_lines(self, cite, receipt):
        """The lines a `cite` (alias@tree12:path:line or alias@tree12:path:start-end) names, read from the pinned tree of ITS repository and
        counted as git counts them (LF only, no strip: lf_lines), never with the product's own splitter."""
        alias, rest = cite.split('@', 1)
        tree12, rest = rest.split(':', 1)
        path, lines = rest.rsplit(':', 1)
        pin = receipt['source']['repos'][alias]
        self.assertTrue(pin['tree'].startswith(tree12), (cite, pin['tree']))
        env = dict(dated(), **sr().git_env(self.ledger, pin))
        rows = lf_lines(blob_bytes(pin['root'], f'{pin["tree"]}:{path}', env=env))
        start, _, end = lines.partition('-')
        self.assertLessEqual(int(end or start), len(rows), f'{cite} names a line after the end of the file ({len(rows)} lines)')
        return rows[int(start) - 1:int(end or start)]


class ContractTests(MrrFixture):
    def test_mr01_the_contract_declares_repositories_and_their_grants(self):
        from onecrew.v2 import authority, contract as contracts
        normalized = contracts.validate(self.contract())['authority']['repos']
        self.assertEqual([(r['alias'], r['path'], r['read']) for r in normalized],
                         [('app', 'repo-b', ['docs/', 'src/**']), ('core', 'repo-a', ['docs/', 'src/**'])])
        entry = lambda **kw: dict({'alias': 'core', 'path': 'repo-a', 'read': ['src/**']}, **kw)
        bad = [[entry(alias='Core')], [entry(alias='c')], [entry(alias='core:x')], [entry(), entry(path='repo-b')],
               [entry(), entry(alias='app', path='REPO-A')], [entry(path='../repo-a')], [entry(path='repo-a/.git')], [entry(path='//server/share/repo')],
               [entry(path='')], [entry(read=['.env'])], [entry(read=[])], [entry(read=['../x'])], [dict(entry(), ref='main')], [], 'repo-a']
        for repos in bad:
            with self.assertRaises(LedgerError, msg=repos):
                contracts.validate(self.contract(repos=repos))
        with self.assertRaises(LedgerError, msg='a write location inside a read-only source'):
            contracts.validate(self.contract(owned=['a.txt', 'repo-a/out.txt']))
        self.assertNotIn('repos', authority.normalize({'edit': True}))                 # a grant without repositories is the one there was
        absolute = contracts.validate(self.contract(repos=[entry(path=str(self.paths['core']).replace('\\', '/'))]))['authority']['repos']
        self.assertEqual(absolute[0]['path'], str(self.paths['core']).replace('\\', '/'))

    def test_mr01b_a_node_names_declared_repositories_inside_their_grant_only(self):
        self.plan(self.item(patterns=('core:src/', 'app:docs/guide.md')))
        refused = [self.item(patterns=('other:src/',)),                 # repo-c is in the folder but not declared
                   self.item(patterns=('core:**',)),                    # wider than the core grant (src/**, docs/)
                   self.item(patterns=('core:src/', 'src/')),           # a project pattern and a repository pattern in one node
                   self.item(patterns=('core:../repo-c/',)),
                   self.item(read=('repo-c/src/hidden.py',)),           # an undeclared repository through the node's whole-file read
                   self.item(read=('repo-a/src/alpha.py',)),            # a declared repository outside its grant path
                   self.item(write=('repo-a/out.txt',))]                # a write into a read-only source
        for item in refused:
            with self.assertRaises(LedgerError, msg=item['sources']['read'] + item['read'] + item['write']):
                self.plan(item)


class ReadTests(MrrFixture):
    def test_mr02_one_node_reads_and_searches_two_repositories_from_a_folder_without_git(self):
        self.assertFalse((self.work / '.git').exists())
        self.plan(self.item())
        seen = {}
        def first(prompt, schema):
            seen['first'] = body_of(prompt)['source_tools']
            seen['schema'] = schema['properties']['source']
            return ask({'op': 'search', 'repo': 'core', 'query': 'needle'}, {'op': 'search', 'repo': 'app', 'query': 'needle'},
                       {'op': 'read', 'repo': 'core', 'path': 'src/shared.py'}, {'op': 'read', 'repo': 'app', 'path': 'src/shared.py'})
        def second(prompt, schema):
            tools = body_of(prompt)['source_tools']
            seen['second'] = tools
            cites = [m['cite'] for r in tools['results'] if r['action'] == 'search' for m in r['result']['matches']]
            cites += [r['result']['cite'] for r in tools['results'] if r['action'] == 'read']
            seen['cites'] = cites
            return done('\n'.join(cites) + '\n', path=REPORT)
        self.values += [first, second]
        self.assertEqual(self.step()['state'], 'continuing')
        produced = self.step()
        self.assertEqual(produced['state'], 'produced', produced)
        first = seen['first']
        self.assertEqual([(r['repo'], r['status']) for r in first['repos']], [('app', 'pinned'), ('core', 'pinned')])
        self.assertEqual(first['coverage_gaps'], [])
        self.assertIn('repo', seen['schema']['properties']['requests']['items']['properties'])
        listed = {repo: [e['path'] for e in result['entries']] for repo, result in self.by_repo(first['results'], 'list').items()}
        self.assertEqual(set(listed), {'core', 'app'})
        self.assertIn('src/alpha.py', listed['core']); self.assertNotIn('src/beta.py', listed['core'])
        self.assertIn('src/beta.py', listed['app']); self.assertNotIn('src/alpha.py', listed['app'])
        searched = self.by_repo(seen['second']['results'], 'search')
        self.assertEqual([m['path'] for m in searched['core']['matches']], ['src/alpha.py'])
        self.assertEqual([m['path'] for m in searched['app']['matches']], ['src/beta.py'])
        read = self.by_repo(seen['second']['results'], 'read')
        self.assertEqual(read['core']['text'], read['app']['text'])                    # same name, same bytes ...
        self.assertEqual(read['core']['blob'], read['app']['blob'])
        self.assertNotEqual(read['core']['cite'], read['app']['cite'])                 # ... two repositories, two citations
        self.assertTrue(read['core']['cite'].startswith('core@') and read['app']['cite'].startswith('app@'))
        receipt = self.receipt(produced)
        self.assertEqual(receipt['source']['capability'], 'git-repos')
        self.assertEqual(sorted(receipt['source']['repos']), ['app', 'core'])
        for cite in seen['cites']:
            lines = self.cite_lines(cite, receipt)
            self.assertTrue(lines, cite)
            if '@' in cite and ('alpha' in cite or 'beta' in cite): self.assertIn('NEEDLE', ''.join(lines), cite)
        self.assertNotIn('NEEDLE-HIDDEN', self.prompts())                               # repo-c sits in the same folder, never declared
        self.assertNotIn('never-shown-core', self.prompts())
        started = [p for k, p in self.events() if k == 'node.started' and p['node'] == 'R']
        self.assertEqual(started[0]['source_tree']['kind'], 'git-repos')
        self.assertEqual(sorted(started[0]['source_tree']['repos']), ['app', 'core'])
        self.assertEqual(started[0]['source_tree']['repos'], started[1]['source_tree']['repos'])   # the continuation keeps the pins
        delivered = [p for k, p in self.events() if k == 'knowledge.delivered' and p['node'] == 'R']
        self.assertEqual(sorted(delivered[-1]['sources_read']['repos']), ['app', 'core'])
        self.assertIn('src/beta.py', delivered[-1]['sources_read']['repos']['app']['blobs'])
        self.assertNotIn('src/beta.py', delivered[-1]['sources_read']['repos']['core']['blobs'])
        self.assertEqual(self.ledger.project, self.work.resolve())
        self.assertFalse((self.work / '.git').exists())                                # nobody made the folder a repository

    def test_mr02b_a_request_must_name_its_repository_and_unknown_names_are_refused_alike(self):
        self.plan(self.item())
        asked = [{'op': 'read', 'repo': 'other', 'path': 'src/hidden.py'},     # repo-c: on disk in the same folder, not declared
                 {'op': 'read', 'repo': 'nothere', 'path': 'src/hidden.py'},   # on disk nowhere
                 {'op': 'search', 'repo': 'other', 'query': 'needle'},
                 {'op': 'read', 'path': 'src/alpha.py'},                       # no repository named
                 {'op': 'read', 'repo': 'core', 'path': '../repo-c/src/hidden.py'},
                 {'op': 'read', 'repo': 'core', 'path': 'docs/guide.md'},      # a declared repository, outside this node's read scope
                 {'op': 'read', 'repo': 'core', 'path': 'src/.env.local'},
                 {'op': 'read', 'repo': 'core', 'path': 'D:/x/src/alpha.py'}]
        self.values += [lambda p, s: ask(*asked), lambda p, s: done(path=REPORT)]
        partial = self.step()
        self.assertEqual(self.step()['state'], 'produced')
        sealed = {json.dumps(r['request'], sort_keys=True): r['reason'] for r in self.receipt(partial)['source']['refused']}
        run = {json.dumps(r['arguments'], sort_keys=True): r['result'].get('refused') for r in self.results(1)}
        reasons = dict(sealed, **run)
        key = lambda request: json.dumps(request, sort_keys=True)
        self.assertEqual(reasons[key(asked[0])], reasons[key(asked[1])])            # no oracle of what exists outside the grant
        self.assertEqual(reasons[key(asked[0])], reasons[key(asked[2])])
        self.assertIn('not a repository of this node', reasons[key(asked[0])])
        self.assertIn('repo', reasons[key(asked[3])])
        for request in asked[4:]:
            self.assertTrue(reasons.get(key(request)), request)
        for row in self.results(1):
            self.assertNotIn('text', row['result'])
        self.assertNotIn('NEEDLE-HIDDEN', self.prompts())
        self.assertNotIn('core VALUE', self.prompts())
        self.assertNotIn('never-shown-core', self.prompts())


class SameTreeTests(MrrFixture):
    """Two declared repositories with the same files, the same commit and the same tree."""
    repos = {'core': ('repo-a', REPO_A), 'mirror': ('repo-m', REPO_A)}

    def item(self, nid='R', patterns=('core:src/', 'mirror:src/'), **kw):
        return super().item(nid, patterns=patterns, **kw)

    def test_mr03_identical_trees_never_share_cursors_repeats_or_citations(self):
        self.assertEqual(git(self.paths['core'], 'rev-parse', 'HEAD'), git(self.paths['mirror'], 'rev-parse', 'HEAD'))
        kept = {}
        with patch.object(st(), 'LIST_ENTRIES', 1):
            self.plan(self.item())
            def first(prompt, schema):
                tools = body_of(prompt)['source_tools']
                kept['trees'] = {r['repo']: r['tree'] for r in tools['repos']}
                kept['cursors'] = {repo: result['next_cursor'] for repo, result in self.by_repo(tools['results'], 'list').items()}
                return ask({'op': 'list', 'repo': 'mirror', 'cursor': kept['cursors']['core']},     # core's cursor named for mirror
                           {'op': 'list', 'cursor': kept['cursors']['core']},                       # core's cursor: continues core
                           {'op': 'read', 'repo': 'core', 'path': 'src/shared.py'},
                           {'op': 'read', 'repo': 'mirror', 'path': 'src/shared.py'})               # not a repeat of core's read
            self.values += [first, lambda p, s: ask({'op': 'read', 'repo': 'mirror', 'path': 'src/shared.py'}),   # this one is a repeat
                            lambda p, s: done(path=REPORT)]
            partial = self.step()
            second = self.step()
            self.assertEqual(self.step()['state'], 'produced')
        self.assertEqual(kept['trees']['core'], kept['trees']['mirror'])
        self.assertNotEqual(kept['cursors']['core'], kept['cursors']['mirror'])
        refused = self.receipt(partial)['source']['refused']
        self.assertEqual(len(refused), 1, refused)
        self.assertIn('belongs to repository core, not mirror', refused[0]['reason'])
        results = self.results(1)
        listed = results[0]['result']
        self.assertEqual((listed['source']['repo'], listed['coverage']['scanned_from']), ('core', 1))
        reads = [r['result'] for r in results if r['action'] == 'read']
        self.assertEqual(sorted(r['source']['repo'] for r in reads), ['core', 'mirror'])
        self.assertEqual(len({r['cite'] for r in reads}), 2)
        records = json.loads(self.store.read_blob(self.receipt(second)['source']['results']))['records']   # the prompt shows paged views
        self.assertEqual(len({r['fingerprint'] for r in records}), len(records))
        self.assertEqual(self.tools(1)['progress']['repeated_results'], 0)            # the same bytes in two repositories is no repeat
        again = self.receipt(second)['source']['refused']
        self.assertEqual(len(again), 1)
        self.assertTrue(again[0]['reason'].startswith('repeat'), again)


class LinkTests(MrrFixture):
    repos = {'core': ('repo-a', REPO_A), 'linked': ('repo-j', None)}

    def junction(self, link, target):
        made = subprocess.run(['cmd', '/c', 'mklink', '/J', str(link), str(target)], capture_output=True)
        if made.returncode: self.skipTest('mklink /J is not available here: ' + made.stderr.decode('utf-8', 'replace')[:200])
        self.addCleanup(lambda: os.rmdir(link) if os.path.lexists(link) else None)

    def prepare_repos(self):
        if os.name != 'nt': self.skipTest('a junction is a Windows link')
        elsewhere = self.base / 'elsewhere'
        make_repo(elsewhere / 'repo-b', REPO_B)
        self.junction(self.work / 'repo-j', elsewhere / 'repo-b')                     # the declared path IS a junction
        (elsewhere / 'outside').mkdir()
        (elsewhere / 'outside' / 'loot.txt').write_bytes(b'JUNCTION-LOOT behind a junction\n')
        self.junction(self.work / 'repo-a' / 'src' / 'j', elsewhere / 'outside')     # a junction inside a declared repository

    def test_mr05_links_and_junctions_never_widen_the_grant(self):
        self.plan(self.item(patterns=('core:src/', 'linked:src/')))
        def only(prompt, schema):
            self.assertNotIn('source', schema['properties'])                      # nothing could be pinned: the node runs as 2.3
            return done(path=REPORT)
        self.values.append(only)
        produced = self.step()
        self.assertEqual(produced['state'], 'produced', produced)
        tools = self.tools(0)
        self.assertEqual(tools['capability'], 'unavailable')
        states = {g['repo']: g.get('state') for g in tools['coverage_gaps']}
        self.assertEqual(states['linked'], 'link')
        self.assertEqual(states['core'], 'unpinnable')
        self.assertIn('junction', next(g['reason'] for g in tools['coverage_gaps'] if g['repo'] == 'core'))
        self.assertNotIn('NEEDLE-BETA', self.prompts())
        self.assertNotIn('JUNCTION-LOOT', self.prompts())
        receipt = self.receipt(produced)
        self.assertEqual(receipt['source']['capability'], 'unavailable')
        self.assertEqual(sorted(g['repo'] for g in receipt['source']['coverage_gaps']), ['core', 'linked'])

    def test_mr05b_a_link_entry_in_a_pinned_tree_is_withheld(self):
        core = self.paths['core']
        temp_index = self.base / 'link.index'
        env = dict(dated(), GIT_INDEX_FILE=str(temp_index))
        target = git(core, 'hash-object', '-w', '--stdin', input=b'../../repo-c/src/hidden.py')
        git(core, 'read-tree', 'HEAD', env=env)
        git(core, 'update-index', '--add', '--cacheinfo', f'120000,{target},src/link', env=env)
        tree = git(core, 'write-tree', env=env)
        pin = {'kind': 'git-tree', 'root': str(core.resolve()).replace('\\', '/'), 'declared': 'repo-a', 'tree': tree,
               'head': git(core, 'rev-parse', 'HEAD'), 'branch': 'refs/heads/main', 'dirty': False, 'objects': 'repository'}
        reader = sr().reader(self.ledger, 'core', pin)
        scope = st().Scope(['src/**'], ['src/'])
        listed = st().run(reader, scope, {'op': 'list', 'path': 'src'})['result']
        self.assertIn({'path': 'src/link', 'reason': 'link'}, listed['withheld'])
        read = st().run(reader, scope, {'op': 'read', 'path': 'src/link'})['result']
        self.assertEqual(read['withheld'], [{'path': 'src/link', 'reason': 'link'}])
        self.assertNotIn('text', read)
        self.assertEqual(read['source']['repo'], 'core')


class NestedTests(MrrFixture):
    """core is granted whole; it holds an untracked nested repository and a committed submodule entry. Neither is read through core."""
    grants = dict(MrrFixture.grants, core=['**'])

    def prepare_repos(self):
        core = self.paths['core']
        inner = core / 'nested' / 'inner'                                   # an untracked repository inside core
        make_repo(inner, {'x.py': b'INNER = "NEEDLE-INNER of a nested repository"\n'})
        sub = git(inner, 'rev-parse', 'HEAD')
        git(core, 'update-index', '--add', '--cacheinfo', f'160000,{sub},vendor/sub')     # a committed submodule entry
        git(core, 'commit', '-q', '-m', 'a submodule entry')
        (core / 'vendor' / 'sub').mkdir(parents=True)                            # not initialized: an empty folder

    def test_mr06_nested_repositories_and_submodules_are_never_read_through_the_outer_grant(self):
        self.plan(self.item(patterns=('core:**', 'app:src/')))
        self.values += [lambda p, s: ask({'op': 'list', 'repo': 'core', 'path': ''}, {'op': 'search', 'repo': 'core', 'query': 'needle-inner'},
                                         {'op': 'read', 'repo': 'core', 'path': 'nested/inner/x.py'}, {'op': 'list', 'repo': 'core', 'path': 'vendor'}),
                        lambda p, s: done(path=REPORT)]
        partial = self.step(); self.assertEqual(self.step()['state'], 'produced')
        self.assertNotIn('NEEDLE-INNER', self.prompts())
        core = next(r for r in self.tools(0)['repos'] if r['repo'] == 'core')
        self.assertTrue(core['dirty'])                                           # the untracked nested repository makes it dirty
        refused = self.receipt(partial)['source']['refused']                    # the whole-scope listing IS the catalogue of round 1
        self.assertEqual([(r['request'], r['reason'][:6]) for r in refused], [({'op': 'list', 'repo': 'core', 'path': ''}, 'repeat')])
        listed = self.by_repo(self.results(0), 'list')['core']
        searched, read, vendor = (r['result'] for r in self.results(1))
        withheld = {w['path']: w['reason'] for w in listed['withheld']}
        self.assertEqual(withheld.get('nested/inner'), 'excluded')
        self.assertEqual(withheld.get('vendor/sub'), 'excluded')
        self.assertEqual(searched['matches'], [])
        self.assertNotIn('text', read)
        self.assertIn('not found', read['refused'])
        self.assertEqual(vendor['entries'], [])


class ChangeTests(MrrFixture):
    def test_mr07_a_moved_head_is_labelled_old_then_rechecked_on_new_pins_and_old_cursors_are_refused(self):
        kept, rounds = {}, {'n': 0}
        def script(prompt, schema):
            rounds['n'] += 1
            tools = body_of(prompt)['source_tools']
            kept[rounds['n']] = tools
            if rounds['n'] == 1:
                kept['cursor'] = self.by_repo(tools['results'], 'list')['core']['next_cursor']
                return ask({'op': 'read', 'repo': 'core', 'path': 'src/alpha.py'})
            if rounds['n'] == 2: return done('saw alpha\n', path=REPORT)
            if rounds['n'] == 3: return ask({'op': 'list', 'cursor': kept['cursor']}, {'op': 'read', 'repo': 'core', 'path': 'src/alpha.py'})
            return done('saw alpha again\n', path=REPORT)
        with patch.object(st(), 'LIST_ENTRIES', 1):
            self.plan(self.item(rounds=6))
            self.values += [script] * 6
            calls = [self.remaining_calls()]
            self.assertEqual(self.step()['state'], 'continuing')
            calls.append(self.remaining_calls())
            commit(self.paths['core'], {'src/alpha.py': b'ALPHA = 2\n# NEEDLE-ALPHA moved on\n'}, 'core moves on after the pin')
            second = self.step()
            self.assertEqual(second['state'], 'continuing', second)                 # read a file that changed: rechecked, not published
            calls.append(self.remaining_calls())
            third = self.step()
            fourth = self.step()
            calls.append(self.remaining_calls())
        self.assertEqual(fourth['state'], 'produced', fourth)
        labelled = {r['repo']: r for r in kept[2]['repos']}
        self.assertIs(labelled['core']['current'], False)
        self.assertIn('HEAD moved', labelled['core']['note'])
        self.assertIs(labelled['app']['current'], True)
        self.assertIn('ALPHA = 1', self.by_repo(kept[2]['results'], 'read')['core']['text'])   # round 2 still reads the pinned snapshot
        resumed = [p for k, p in self.events() if k == 'node.resumed' and p.get('knowledge_changed')]
        self.assertEqual(len(resumed), 1)
        self.assertTrue(resumed[0]['repin'])
        critical = resumed[0]['knowledge_changed']['critical']
        self.assertEqual([(c['path'], c['repo'], c['reason']) for c in critical], [('core:src/alpha.py', 'core', 'source changed since it was read')])
        trees = [{a: r['tree'] for a, r in p['source_tree']['repos'].items()} for k, p in self.events() if k == 'node.started' and p['node'] == 'R']
        self.assertNotEqual(trees[1]['core'], trees[2]['core'])                     # the recheck reads newly pinned snapshots
        self.assertEqual(trees[1]['app'], trees[2]['app'])
        refused = self.receipt(third)['source']['refused']
        self.assertEqual([r['reason'] for r in refused], ['source changed; list again'])
        self.assertIn('ALPHA = 2', self.by_repo(kept[4]['results'], 'read')['core']['text'])
        self.assertEqual(self.receipt(fourth)['source']['rounds_total'], 2)        # every reading round of the node, before and after the repin
        self.assertEqual(calls, sorted(calls, reverse=True))                         # the shared root budget only goes down
        self.assertLess(calls[-1], calls[0])

    def test_mr07b_a_stable_source_is_published_with_no_recheck(self):
        self.plan(self.item())
        self.values += [lambda p, s: ask({'op': 'read', 'repo': 'core', 'path': 'src/alpha.py'}, {'op': 'read', 'repo': 'app', 'path': 'src/beta.py'}),
                        lambda p, s: done(path=REPORT)]
        self.step(); produced = self.step()
        self.assertEqual(produced['state'], 'produced')
        self.assertFalse([p for k, p in self.events() if k == 'node.resumed' and p.get('knowledge_changed')])
        self.assertTrue(all(r['current'] is True for r in self.tools(1)['repos']))
        trees = [p['source_tree'] for k, p in self.events() if k == 'node.started' and p['node'] == 'R']
        self.assertEqual({a: r['tree'] for a, r in trees[0]['repos'].items()}, {a: r['tree'] for a, r in trees[1]['repos'].items()})


class DirtyTests(MrrFixture):
    def prepare_repos(self):
        write(self.paths['app'], {'src/beta.py': b'BETA = 3\n# NEEDLE-BETA uncommitted edit\n', 'src/draft.py': b'DRAFT = "NEEDLE-DRAFT untracked"\n'})

    def test_mr08_a_dirty_repository_is_captured_without_writing_into_it(self):
        before = objects(self.paths['app'])
        self.plan(self.item())
        self.values += [lambda p, s: ask({'op': 'search', 'repo': 'app', 'query': 'needle'}), lambda p, s: done(path=REPORT)]
        self.step(); produced = self.step()
        self.assertEqual(produced['state'], 'produced', produced)
        repos = {r['repo']: r for r in self.tools(0)['repos']}
        self.assertEqual((repos['app']['dirty'], repos['core']['dirty']), (True, False))
        texts = [m['text'] for m in self.results(1)[0]['result']['matches']]
        self.assertTrue(any('uncommitted edit' in t for t in texts), texts)
        self.assertTrue(any('NEEDLE-DRAFT' in t for t in texts), texts)
        pin = next(p for k, p in self.events() if k == 'node.started' and p['node'] == 'R')['source_tree']['repos']['app']
        self.assertEqual(pin['objects'], 'private')
        self.assertEqual(pin['head'], git(self.paths['app'], 'rev-parse', 'HEAD'))
        self.assertNotEqual(pin['tree'], git(self.paths['app'], 'rev-parse', 'HEAD^{tree}'))
        self.assertEqual(objects(self.paths['app']), before)                        # not one object written into the source repository
        private = Path(sr().git_env(self.ledger, pin)['GIT_OBJECT_DIRECTORY'])
        self.assertTrue(private.resolve().is_relative_to(Path(self.ledger.state_root).resolve()))
        self.assertTrue(any(private.rglob('*')))
        receipt = self.receipt(produced)
        for match in self.results(1)[0]['result']['matches']:
            self.assertEqual(self.cite_lines(match['cite'], receipt), [match['text']])

    def test_mr08b_mrr_pins_a_dirty_tree_without_a_trace_where_the_2_4a_pin_writes(self):
        """MR-R's pin of a dirty tree runs FIRST, on a repository nothing has hashed yet, and the whole folder (.git included: names, sizes,
        times of files and folders, bytes) is compared; only then the 2.4-A pin of the same tree runs as the witness that a writing pin is
        seen by this very comparison (review R1 tests-evidence-4: the old order compared names after the 2.4-A pin had written them all)."""
        app = self.paths['app']
        before = fingerprint(app)
        pin = sr().pin_repo(self.ledger, 'app', 'repo-b')
        self.assertEqual((pin['kind'], pin.get('dirty')), ('git-tree', True), pin)
        self.assertEqual(changed(before, fingerprint(app)), [], 'the MR-R pin of a dirty tree wrote into the repository')
        again = sr().pin_repo(self.ledger, 'app', 'repo-b')                          # a second pin (a restart): the same identity, still no trace
        self.assertEqual(again['tree'], pin['tree'])
        self.assertEqual(changed(before, fingerprint(app)), [], 'a second MR-R pin wrote into the repository')
        tree = st().pin_now(app)                                                    # the witness (trap 1): the 2.4-A project pin writes
        self.assertEqual(tree['tree'], pin['tree'])                                 # ... the same snapshot identity
        self.assertNotEqual(changed(before, fingerprint(app)), [], 'the comparison did not see the 2.4-A pin write into the repository')


class ConflictTests(MrrFixture):
    def prepare_repos(self):
        app = self.paths['app']
        git(app, 'checkout', '-q', '-b', 'other'); commit(app, {'src/beta.py': b'BETA = "other"\n'}, 'other side')
        git(app, 'checkout', '-q', 'main'); commit(app, {'src/beta.py': b'BETA = "main"\n'}, 'main side')
        git(app, 'merge', 'other', check=False)                                  # a conflict: MERGE_HEAD and unmerged entries
        self.assertTrue((app / '.git' / 'MERGE_HEAD').exists())

    def test_mr09_a_merge_in_progress_is_unavailable_and_reported_while_the_other_repository_is_read(self):
        self.plan(self.item())
        self.values += [lambda p, s: ask({'op': 'read', 'repo': 'app', 'path': 'src/beta.py'}, {'op': 'read', 'repo': 'core', 'path': 'src/alpha.py'}),
                        lambda p, s: done(path=REPORT)]
        partial = self.step(); produced = self.step()
        self.assertEqual(produced['state'], 'produced', produced)
        tools = self.tools(0)
        app = next(r for r in tools['repos'] if r['repo'] == 'app')
        self.assertEqual((app['status'], app['state']), ('unavailable', 'merge_in_progress'))
        self.assertEqual([(g['repo'], g['status']) for g in tools['coverage_gaps']], [('app', 'unavailable')])
        refused = self.receipt(partial)['source']['refused']
        self.assertEqual(len(refused), 1)
        self.assertTrue(refused[0]['reason'].startswith('repository app is unavailable'), refused)
        self.assertEqual([r['result']['source']['repo'] for r in self.results(1)], ['core'])
        self.assertNotIn('<<<<<<<', self.prompts())
        self.assertEqual([g['repo'] for g in self.receipt(produced)['source']['coverage_gaps']], ['app'])

    def test_mr09b_unmerged_entries_without_a_merge_head_are_unavailable_too(self):
        app = self.paths['app']
        for name in ('MERGE_HEAD', 'MERGE_MSG', 'MERGE_MODE'):
            if (app / '.git' / name).exists(): (app / '.git' / name).unlink()
        self.assertTrue(git(app, 'ls-files', '-u'))
        pin = sr().pin_repo(self.ledger, 'app', 'repo-b')
        self.assertEqual((pin['kind'], pin['state']), ('unavailable', 'unmerged'))


class MissingTests(MrrFixture):
    repos = {'core': ('repo-a', REPO_A), 'app': ('repo-b', REPO_B), 'gone': ('repo-gone', None), 'plain': ('not-a-repo', None)}

    def prepare_repos(self):
        write(self.work / 'not-a-repo', {'src/p.py': b'PLAIN = "NEEDLE-PLAIN in a folder without Git"\n'})

    def test_mr10_a_missing_repository_blocks_only_what_depends_on_it(self):
        reader = self.item('R', patterns=('core:src/', 'gone:src/', 'plain:src/'))
        independent = self.item('X', patterns=('app:src/',), write=('reports/other.md',))
        self.plan(reader, independent)
        rounds = {'R': 0, 'X': 0}
        def script(prompt, schema):
            nid = body_of(prompt)['node']['id']
            rounds[nid] += 1
            if rounds[nid] == 1 and nid == 'R':
                return ask({'op': 'read', 'repo': 'gone', 'path': 'src/x.py'}, {'op': 'read', 'repo': 'plain', 'path': 'src/p.py'},
                           {'op': 'read', 'repo': 'core', 'path': 'src/alpha.py'})
            if rounds[nid] == 1: return ask({'op': 'read', 'repo': 'app', 'path': 'src/beta.py'})
            return done(nid + '\n', path=body_of(prompt)['node']['write'][0])
        self.values += [script] * 8
        states = [self.step() for _ in range(4)]
        produced = {r['node']: r for r in states if r.get('state') == 'produced'}
        self.assertEqual(sorted(produced), ['R', 'X'], states)
        first_r = next(body_of(c['prompt'])['source_tools'] for c in self.calls if body_of(c['prompt'])['node']['id'] == 'R')
        gaps = {g['repo']: g['state'] for g in first_r['coverage_gaps']}
        self.assertEqual(gaps, {'gone': 'missing', 'plain': 'not_a_repository'})
        receipt_r, receipt_x = self.receipt(produced['R']), self.receipt(produced['X'])
        self.assertEqual(sorted(g['repo'] for g in receipt_r['source']['coverage_gaps']), ['gone', 'plain'])
        self.assertEqual(receipt_x['source']['coverage_gaps'], [])                  # the independent branch is not touched
        from onecrew.v2 import report
        owner_report = report.render_report(self.ledger.state_root, 'P1')
        self.assertIn('Nguồn đa repo', owner_report)
        self.assertIn('PHỦ THIẾU', owner_report)
        self.assertIn('gone: unavailable', owner_report)
        self.assertIn('plain: unavailable', owner_report)
        self.assertIn(receipt_r['source']['repos']['core']['tree'], owner_report)
        self.assertIn('Candidate node R, reports/analysis.md', owner_report)
        self.assertIn('verify, tích hợp, handoff', owner_report)
        self.assertIn('xem bản phân tích MR-R', owner_report)
        refused = [r['reason'] for rec in self.receipts('R') for r in rec['source']['refused']]
        self.assertTrue(any(r.startswith('repository gone is unavailable') for r in refused), refused)
        self.assertTrue(any(r.startswith('repository plain is unavailable') for r in refused), refused)
        self.assertNotIn('NEEDLE-PLAIN', self.prompts())

    def test_mr10b_a_repository_removed_after_its_pin_is_never_silently_skipped(self):
        """The pin of app stays in the chain, but app cannot be read any more: its requests are refused, it is a coverage gap of the round,
        and what came from it earlier is not judged current (it is the gap), so the candidate is published with the gap and no recheck."""
        self.plan(self.item())
        rounds = {'n': 0}
        def script(prompt, schema):
            rounds['n'] += 1
            if rounds['n'] == 1:
                return ask({'op': 'read', 'repo': 'app', 'path': 'src/beta.py'}, {'op': 'read', 'repo': 'core', 'path': 'src/alpha.py'})
            return done(path=REPORT)
        self.values += [script] * 5
        self.assertEqual(self.step()['state'], 'continuing')
        shutil.move(str(self.paths.pop('app')), str(self.base / 'moved-away'))
        produced = self.step()
        self.assertEqual(produced['state'], 'produced', produced)
        second = self.tools(1)
        self.assertEqual({r['repo']: r['status'] for r in second['repos']}['app'], 'unreadable')
        self.assertEqual([g['repo'] for g in second['coverage_gaps']], ['app'])
        app_read = next(r for r in second['results'] if r['arguments'].get('repo') == 'app')
        self.assertIn('cannot be read now', app_read['result']['refused'])
        core_read = next(r for r in second['results'] if r['arguments'].get('repo') == 'core')
        self.assertIn('ALPHA = 1', core_read['result']['text'])
        final = self.receipt(produced)['source']
        self.assertEqual([(g['repo'], g['status']) for g in final['coverage_gaps']], [('app', 'unreadable')])
        delivered = [p for k, p in self.events() if k == 'knowledge.delivered' and p['node'] == 'R'][-1]
        self.assertEqual(sorted(delivered['sources_read']['repos']), ['core'])         # app's earlier listing is the gap, not current evidence
        self.assertFalse([p for k, p in self.events() if k == 'node.resumed' and p.get('knowledge_changed')])

    def test_mr10c_a_node_whose_repositories_are_all_unavailable_runs_without_source_tools_and_says_so(self):
        self.plan(self.item(patterns=('gone:src/', 'plain:src/')))
        def only(prompt, schema):
            self.assertNotIn('source', schema['properties'])
            return done(path=REPORT)
        self.values.append(only)
        produced = self.step()
        self.assertEqual(produced['state'], 'produced', produced)
        source = self.receipt(produced)['source']
        self.assertEqual(source['capability'], 'unavailable')
        self.assertEqual(sorted(g['repo'] for g in source['coverage_gaps']), ['gone', 'plain'])


class RestartTests(MrrFixture):
    def test_mr11_a_crash_between_request_and_result_reruns_the_same_requests_on_the_same_pins(self):
        self.plan(self.item(rounds=3))
        self.values.append(lambda p, s: ask({'op': 'read', 'repo': 'core', 'path': 'src/alpha.py'}, {'op': 'read', 'repo': 'app', 'path': 'src/beta.py'}))
        first = self.step()
        self.assertEqual(first['state'], 'continuing')
        budget = self.remaining_calls()
        seen, real = {}, self.adapter.prepare
        def dying(ledger, control, task, item, attempt):
            seen.update(task=task, item=copy.deepcopy(item), attempt=attempt)
            from onecrew.v2 import knowledge
            with patch.object(knowledge, 'for_native', side_effect=Crash()):
                return real(ledger, control, task, item, attempt)
        with patch.object(self.adapter, 'prepare', side_effect=dying):
            with self.assertRaises(Crash):
                self.engine.step(self.ledger, 'P1', self.adapter)
        self.assertEqual(len(self.calls), 1)
        restarted = NativeExecutor(self.ledger)                                    # another controller, nothing in memory
        self.values.append(lambda p, s: done(path=REPORT))
        candidate = restarted.start(self.ledger, restarted.control, seen['task'], seen['item'], seen['attempt'])
        self.assertEqual(len(self.calls), 2)
        receipt = json.loads(self.store.read_blob(candidate['receipt']))
        records = json.loads(self.store.read_blob(receipt['source']['results']))['records']
        self.assertEqual([r['arguments'] for r in records], [{'op': 'read', 'repo': 'core', 'path': 'src/alpha.py'},
                                                              {'op': 'read', 'repo': 'app', 'path': 'src/beta.py'}])
        started = [p for k, p in self.events() if k == 'node.started' and p['node'] == 'R']
        pins = [sr().identity(p['source_tree']) for p in started]
        self.assertEqual(pins[0], pins[1])                                          # the same repository identities and snapshots
        self.assertEqual(sr().identity(seen['item']['source_tree']), pins[0])
        first_receipt = self.receipt(first)
        self.assertEqual({a: s['hash'] for a, s in first_receipt['source']['scope'].items()},
                         {a: s['hash'] for a, s in receipt['source']['scope'].items()})   # the same grants
        self.assertEqual(receipt['source']['rounds_total'], 1)
        self.assertLessEqual(self.remaining_calls(), budget)                       # a restart never gives calls back

    def test_mr11b_the_round_cap_and_repeats_hold_across_controllers(self):
        self.plan(self.item(rounds=2))
        self.values += [lambda p, s: ask({'op': 'read', 'repo': 'core', 'path': 'src/shared.py'}),
                        lambda p, s: ask({'op': 'read', 'repo': 'core', 'path': 'src/shared.py'}, {'op': 'read', 'repo': 'app', 'path': 'src/shared.py'}),
                        lambda p, s: ask({'op': 'list', 'repo': 'app', 'path': 'src'})]
        first = self.step(); second = self.step(NativeExecutor(self.ledger)); third = self.step(NativeExecutor(self.ledger))
        self.assertEqual([first['state'], second['state']], ['continuing', 'continuing'])
        self.assertEqual((third['state'], third['classification']), ('held', 'rounds_exhausted'), third)
        r2 = self.receipt(second)['source']
        self.assertEqual([r['request'] for r in r2['refused']], [{'op': 'read', 'repo': 'core', 'path': 'src/shared.py'}])
        self.assertTrue(r2['refused'][0]['reason'].startswith('repeat'))
        self.assertEqual(r2['requests'], [{'op': 'read', 'repo': 'app', 'path': 'src/shared.py'}])   # the same path elsewhere is new
        r3 = self.receipt(third)['source']
        self.assertEqual(r3['refused'][0]['reason'], 'round cap reached (2 of 2)')
        self.assertTrue(r3['rounds_exhausted'])


class RevokeTests(MrrFixture):
    def test_mr12_a_revoked_repository_stops_being_read_and_shows_as_a_coverage_gap(self):
        self.plan(self.item())
        self.values += [lambda p, s: ask({'op': 'read', 'repo': 'core', 'path': 'src/alpha.py'}, {'op': 'read', 'repo': 'app', 'path': 'src/beta.py'}),
                        lambda p, s: done('both\n', path=REPORT)]
        self.step()
        self.assertEqual(self.step()['state'], 'produced')
        budget = self.remaining_calls()
        plans.amend(self.ledger, 'P1', self.contract(repos=self.declared(only=('core',))), 'the owner revokes the app repository', 'codex')
        with patch.dict(os.environ):                                                # the owner's own terminal approves the amendment
            os.environ.pop('ONECREW_ACTOR', None)
            plans.approve(self.ledger, 'P1', 'owner', 'fixture: app is no longer granted')
        with self.assertRaises(LedgerError):
            self.plan(self.item())                                                  # a node cannot keep reading app
        self.plan(self.item(patterns=('core:src/',)))
        calls_before = len(self.calls)
        self.values += [lambda p, s: ask({'op': 'read', 'repo': 'app', 'path': 'src/beta.py'}, {'op': 'read', 'repo': 'core', 'path': 'src/alpha.py'}),
                        lambda p, s: done('core only\n', path=REPORT)]
        partial = self.step(); produced = self.step()
        self.assertEqual(produced['state'], 'produced', produced)
        tools = self.tools(calls_before)
        self.assertEqual([(g['repo'], g['status']) for g in tools['coverage_gaps']], [('app', 'revoked')])
        self.assertEqual([r['repo'] for r in tools['repos'] if r['status'] == 'pinned'], ['core'])
        refused = self.receipt(partial)['source']['refused']
        self.assertEqual(len(refused), 1)
        self.assertIn('not a repository of this node', refused[0]['reason'])
        later = '\n'.join(c['prompt'] for c in self.calls[calls_before:])
        self.assertNotIn('NEEDLE-BETA', later)
        self.assertEqual([(g['repo'], g['status']) for g in self.receipt(produced)['source']['coverage_gaps']], [('app', 'revoked')])
        self.assertLess(self.remaining_calls(), budget)                             # the amendment gave no budget back


class DeadlineTests(MrrFixture):
    def test_mr14_a_node_cap_still_stops_reading_work_that_outlives_it(self):
        """NODE_CAP above is scaffolding width, not an exemption: a cap of 2 s that a slow worker outlives still ends the work."""
        import time
        self.plan(self.item(cap=2))
        def slow(prompt, schema):
            time.sleep(4)
            return ask({'op': 'read', 'repo': 'core', 'path': 'src/alpha.py'})
        self.values += [slow, lambda p, s: done('late\n', path=REPORT)]
        outcomes = []
        for _ in range(2):
            try:
                outcomes.append(self.step()['state'])
            except LedgerError as error:
                outcomes.append(str(error))
        self.assertNotIn('produced', outcomes, outcomes)
        self.assertTrue(any(o == 'held' or 'deadline' in o.lower() for o in outcomes), outcomes)


class SingleRepoUnchangedTests(unittest.TestCase):
    def test_mr13_a_single_repository_spec_validates_as_before(self):
        spec = {'read': ['src/', 'docs/*.md'], 'max_rounds': 2, 'max_chars_per_round': 4000}
        self.assertEqual(st().validate_spec(spec), {'read': ['docs/*.md', 'src/'], 'max_rounds': 2, 'max_chars_per_round': 4000})
        for bad in (['C:/x'], ['c:x'], ['../x'], ['.git/x']):                     # a drive letter is never a repository alias
            with self.assertRaises(LedgerError):
                st().validate_spec(dict(spec, read=bad))
        self.assertEqual(st().validate_spec(dict(spec, read=['core:src/', 'app:docs/']))['read'], ['app:docs/', 'core:src/'])


if __name__ == '__main__':
    unittest.main()
