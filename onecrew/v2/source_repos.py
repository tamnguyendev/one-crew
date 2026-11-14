"""MR-R — one node reads and searches several Git repositories that its root declares and grants, from a coordination folder that need not be
a Git repository (docs/mrr/DOI-CHIEU-MR-R.vi.md, BAN-GIAO-MR-R.vi.md). The 2.4-A protocol of source_tools (list/search/read/page, cursors,
paging, the limits, the round cap, repeats, the v1 progress counters) runs per repository; nothing changes for a node without repositories.

  * Declaration. The root contract grants reading per repository: authority.repos [{alias, path, read}] (authority.repo_grants): alias 2-24
    lowercase letters, digits, - or _ (never a drive letter); path a folder under the coordination folder or an absolute folder; read the
    folders/files/globs of that repository its workers may read. Approving the contract approves the list. A node names repositories in
    `sources.read` as alias:pattern (all its patterns, never mixed with project patterns); revise refuses an undeclared alias, a pattern
    outside its repository's grant, a node read/write inside a declared repository and a node read outside authority.read + scope.owned, so
    no repository (declared or not) is reached around its grant.
  * Pin, read-only. At the first attempt of a chain each repository the node names is pinned on its own: the declared folder must exist, be
    reached without a link or junction, be the top of its Git working tree, have a commit, no merge/rebase/cherry-pick/revert in progress and
    no unmerged entry, and hold neither the state root nor the coordination folder. A clean working tree is pinned as HEAD^{tree}: nothing is
    written. A dirty one is captured by verifiers.command.artifact_sha (hard links and junctions refused) in its private-store mode: staged
    with --info-only, only blobs no store holds written, trees written where only the private store is seen (GIT_OBJECT_DIRECTORY under the
    state root; the repository's objects are alternates for reading), so not one object of the source is written or freshened (git touches
    an existing object, an alternate's included, when asked to write it again), nor an index entry or a ref. Index operations see a copied Git
    directory/index/sharedindex with only builtin conversion settings, never filters/remotes/hooks. A filtered file that requires external
    conversion, a sparse index or missing source object is an explicit gap. Capture refuses changed ungranted/secret files and never hashes
    their content. GIT_NO_LAZY_FETCH and read-only switches also guard object reads. The others are read normally.
  * Identity. node.started `source_tree` = {kind: git-repos, version, repos: {alias: pin}}; a continuation keeps the pins of its chain, a
    recheck after a changed source pins again. Results carry source {repo, tree, head, dirty}; read results and search matches carry `cite`
    (alias@tree12:path:line). Cursors (m1.) carry the repository key (alias + a hash of its folder) and are refused for another repository,
    another snapshot, another scope or another operation; repeats and the v1 progress counters are judged per repository.
  * Coverage. Every round the prompt lists each repository of the node: pinned (with `current` true, false when its HEAD or working tree
    moved since the pin - the results come from the pinned, older snapshot - or null for a pinned dirty tree, judged at publication),
    unavailable (state, reason), unreadable now, or revoked (pinned for an earlier attempt of the node, no longer granted by the approved
    contract); every row that is not pinned is a `coverage_gap`, in the prompt and the receipt. Nothing more is read from a gap, and what
    came from it earlier is the gap, not current evidence. A node with no readable repository runs as 2.3 and says why.
  * Staleness (2.4-B). The delivery record keeps sources_read.repos {alias: {root, tree, blobs}}; working_context compares each blob with
    the file in its repository now (critical path `alias:file`), so a changed source re-pins and rechecks the reader as in 2.4-B.
Source text is data, never authority: requests are decided by code only.
"""
import base64
import copy
import json
import os
import re
import subprocess
import shutil
import tempfile
import time
from contextlib import contextmanager
from pathlib import Path

from .. import progress_core
from ..artifact_core import CONTINUATION_SCHEMA
from ..ledger import LedgerError, canonical, content_hash
from . import authority, source_tools as st
from .verifiers import command

KIND = 'git-repos'
VERSION = 1
QUALIFIED = re.compile(r'([a-z][a-z0-9_-]{1,23}):(.*)', re.S)
CONFIG = (('core.fsmonitor', 'false'), ('core.splitIndex', 'false'), ('core.untrackedCache', 'false'), ('gc.auto', '0'),
          ('maintenance.auto', 'false'), ('core.hooksPath', os.devnull), ('core.sparseCheckout', 'false'))
READ_ONLY = {'GIT_OPTIONAL_LOCKS': '0', 'GIT_CONFIG_COUNT': str(len(CONFIG)),
             'GIT_NO_LAZY_FETCH': '1', 'GIT_NO_REPLACE_OBJECTS': '1', 'GIT_TERMINAL_PROMPT': '0',
             **{f'GIT_CONFIG_KEY_{n}': key for n, (key, _) in enumerate(CONFIG)},
             **{f'GIT_CONFIG_VALUE_{n}': value for n, (_, value) in enumerate(CONFIG)}}
STATUS = ('--no-optional-locks', 'status', '--porcelain=v1', '-z', '--untracked-files=all', '--ignore-submodules=all', '--no-renames')
IN_PROGRESS = (('MERGE_HEAD', 'a merge'), ('rebase-merge', 'a rebase'), ('rebase-apply', 'a rebase or am'), ('CHERRY_PICK_HEAD', 'a cherry-pick'),
               ('REVERT_HEAD', 'a revert'), ('sequencer', 'a cherry-pick or revert sequence'))
NOT_MINE = "not a repository of this node's read scope (its repositories are listed in source_tools.repos)"
REVOKED = ('pinned for an earlier attempt of this node, no longer granted by the approved contract: nothing more is read from it, and what came '
           'from it earlier is not current')
GIT_ERRORS = (LedgerError, OSError, ValueError, subprocess.SubprocessError)
FIELDS = {'list': {'repo', 'path', 'cursor'}, 'read': {'repo', 'path', 'cursor'}, 'search': {'repo', 'query', 'path', 'cursor'}}
SCHEMA = copy.deepcopy(st.SCHEMA)
SCHEMA['properties']['requests']['items']['properties']['repo'] = {'type': 'string', 'minLength': 2, 'maxLength': 24}
GUIDE = ('Several repositories are pinned for you (source_tools.repos). To read more, answer with a `continuation` AND `source.requests` '
         '(at most 8). list, search and read each name ONE repository: {op:"list", repo, path?} lists its files under a folder ("" = its '
         'whole read scope); {op:"search", repo, query, path?} finds literal text, case-insensitive, line by line, in that repository only; '
         '{op:"read", repo, path} reads a file from its start. A result with next_cursor continues with {op, cursor} (a cursor belongs to its '
         'repository and snapshot); a result cut in this prompt continues with its page.next ({op:"page", index, field, offset}). Requests '
         'run in the next round on the same pinned snapshots, inside each repository\'s read scope. Cite evidence with the `cite` of a read '
         'or a match (repository@snapshot:path:line). A repository in coverage_gaps was not read (or not fully): name it in your conclusion '
         'and never claim a full review; `current: false` means the results come from the pinned, older snapshot. An empty search covers '
         'only its repository and what its coverage says; withheld files were not read. Without requests, answer as usual.')
GAPS = ('No repository of this node could be read: every one is listed in coverage_gaps with the reason. Name them in your conclusion and '
        'never claim a review of them.')


class Unavailable(Exception):
    """A declared repository that cannot be pinned: `state` (a short name) and `reason`."""

    def __init__(self, state, reason):
        super().__init__(reason)
        self.state, self.reason = state, reason


# ---- the declaration and the node spec -----------------------------------------------------------------------------------

def declared(contract):
    """{alias: {alias, path, read}} of the root contract (authority.repos); {} for a root without repositories."""
    return {r['alias']: r for r in (((contract or {}).get('authority') or {}).get('repos') or [])}


def qualified(pattern):
    """(alias, rest) of an alias:pattern, else None. A plain read pattern never holds ':' and an alias is never one letter (a drive)."""
    found = QUALIFIED.fullmatch(pattern) if isinstance(pattern, str) else None
    return (found.group(1), found.group(2)) if found else None


def is_multi(spec):
    return isinstance(spec, dict) and any(qualified(p) for p in spec.get('read') or [])


def normalize_patterns(patterns):
    """The node's sources.read when it names repositories: every entry alias:pattern, the pattern by the read-grant rules."""
    out = set()
    for pattern in patterns:
        found = qualified(pattern)
        if found is None:
            raise LedgerError('Node sources.read: a node reads either the project (plain paths) or declared repositories (alias:path), '
                              f'not both; {str(pattern)[:120]!r} names no repository.')
        alias, rest = found
        out.add(alias + ':' + authority.read_pattern(rest, f'sources.read ({alias})'))
    return sorted(out)


def node_patterns(spec):
    """{alias: [patterns]} of a node spec that names repositories."""
    out = {}
    for pattern in spec.get('read') or []:
        alias, rest = qualified(pattern)
        out.setdefault(alias, []).append(rest)
    return {alias: sorted(rows) for alias, rows in sorted(out.items())}


def _within(path, top):
    a, b = os.path.normcase(os.path.abspath(str(path))), os.path.normcase(os.path.abspath(str(top)))
    return a == b or a.startswith(b.rstrip('\\/') + os.sep)


def _in_repo(path, repos, project):
    """The alias of the declared repository `path` (a node read/write path of the coordination folder) lies in, or None."""
    rel = str(path).replace('\\', '/').casefold().rstrip('/')
    for alias, repo in sorted(repos.items()):
        if not authority.is_absolute(repo['path']):
            top = repo['path'].casefold()
            if rel == top or rel.startswith(top + '/'): return alias
        elif project is not None and _within(Path(project) / path, repo['path']):
            return alias
    return None


def check_plan(contract, nodes, project=None):
    """internal_plan.revise for a root that declares repositories (or a node that names some): every repository a node names is declared and
    every pattern inside that repository's grant; a node's whole-file read stays inside authority.read + scope.owned and no node read or
    write lies inside a declared repository (sources are reached only through their grant). Widening any of it is the owner's decision."""
    repos = declared(contract)
    named = [n for n in nodes if is_multi(n.get('sources'))]
    if named and not repos:
        raise LedgerError(f'Node {named[0]["id"]} sources.read names repositories, but the root declares none (authority.repos in the root '
                          'contract is the owner\'s decision).')
    if not repos: return
    if project is not None:
        holder = next((a for a, r in sorted(repos.items()) if authority.is_absolute(r['path']) and _within(project, r['path'])), None)
        if holder:
            raise LedgerError(f'The coordination folder is inside the declared repository {holder}: its writes would land in a read-only source.')
    allowed = list((contract.get('authority') or {}).get('read') or []) + list(contract['scope']['owned'])
    for node in nodes:
        shown = [p for p in node.get('read') or [] if not st.covered(p, allowed)]
        if shown:
            raise LedgerError(f'Node {node["id"]} read is outside the root read grant (authority.read + scope.owned): ' + ', '.join(shown[:5])
                              + '. A declared repository is read through sources.read (alias:path); widening the grant is the owner\'s decision.')
        for path in list(node.get('read') or []) + list(node.get('write') or []):
            alias = _in_repo(path, repos, project)
            if alias:
                raise LedgerError(f'Node {node["id"]} reads or writes {path} inside the source repository {alias}: a declared repository is '
                                  'read only, and only through sources.read (alias:path).')
        spec = node.get('sources')
        if not is_multi(spec): continue
        for alias, patterns in node_patterns(spec).items():
            if alias not in repos:
                raise LedgerError(f'Node {node["id"]} sources.read names the repository {alias}, which the root does not declare '
                                  f'(authority.repos: {", ".join(sorted(repos))}). Declaring a repository is the owner\'s decision.')
            outside = [p for p in patterns if not st.covered(p, repos[alias]['read'])]
            if outside:
                raise LedgerError(f'Node {node["id"]} sources.read is outside the read grant of repository {alias} '
                                  f'({", ".join(repos[alias]["read"][:8])}): ' + ', '.join(f'{alias}:{p}' for p in outside[:5])
                                  + '. Widening it is the owner\'s decision.')


# ---- git on a source, read-only ---------------------------------------------------------------------------------------------

def _git(root, *args, raw=False, input=None, env=None):
    return command._git(root, *args, env=dict(READ_ONLY, **(env or {})), raw=raw, input=input)


def _optional(root, *args):
    try:
        return _git(root, *args) or None
    except LedgerError:
        return None


def git_locations(root):
    """Discover metadata without opening an index. A redirected .git directory is never followed as a folder grant."""
    dot = Path(root) / '.git'
    if dot.is_symlink() or (hasattr(os.path, 'isjunction') and os.path.isjunction(dot)):
        raise Unavailable('link', 'the repository .git is a link or junction: declare the real repository')
    gitdir, common = map(Path, _git(root, 'rev-parse', '--absolute-git-dir', '--path-format=absolute', '--git-common-dir').split('\n'))
    if dot.is_file():
        # A genuine linked worktree has a backlink. A free-form gitfile can relabel another repository's objects.
        backlink = gitdir / 'gitdir'
        if not backlink.is_file() or os.path.normcase(os.path.realpath(backlink.read_text().strip())) != os.path.normcase(os.path.realpath(dot)):
            raise Unavailable('link', 'the .git file redirects to an unbound Git directory; only a bound linked worktree is supported')
    return gitdir, common


def check_locations(ledger, contract):
    """Reject write locations before propose/amend opens the ledger, including linked-worktree metadata."""
    repos = declared(contract)
    if not repos: return
    check_plan(contract, [], ledger.project)
    for alias, repo in repos.items():
        root = Path(repo['path']) if authority.is_absolute(repo['path']) else Path(ledger.project) / repo['path']
        areas = [root]
        if root.exists():
            try:
                areas.extend(git_locations(root))
            except (Unavailable, *GIT_ERRORS):
                pass                         # an unavailable source is a coverage gap, not admission failure
        for area in areas:
            if _within(Path(ledger.state_root).resolve(), area.resolve()):
                raise LedgerError(f'The state root is inside source repository {alias} (or its Git directory): source repositories are read only.')
        if _within(root.resolve(), Path(ledger.project).resolve()):
            rel = root.resolve().relative_to(Path(ledger.project).resolve()).as_posix()
            authority.check_owned([dict(repo, path=rel)], contract['scope']['owned'])


@contextmanager
def isolated_index(root):
    """A throw-away Git directory, not just an index. Reading a split index touches sharedindex in GIT_DIR; expanding a sparse index can
    write objects. Both locations therefore belong to us. No filter/remote/hook configuration is imported, so conversions cannot launch
    programs or fetch missing objects. Only Git's builtin text conversion and file-mode settings are retained."""
    gitdir, common = git_locations(root)
    with tempfile.TemporaryDirectory(prefix='onecrew-source-') as folder:
        shadow = Path(folder)
        for part in ('objects', 'refs', 'info', 'hooks'): (shadow / part).mkdir()
        (shadow / 'HEAD').write_text(_git(root, 'rev-parse', '--verify', 'HEAD^{commit}') + '\n', encoding='ascii')
        config = '[core]\n\trepositoryformatversion = 0\n\tbare = false\n'
        (shadow / 'config').write_text(config, encoding='ascii')
        env = dict(READ_ONLY, GIT_DIR=str(shadow), GIT_WORK_TREE=str(root), GIT_INDEX_FILE=str(shadow / 'index'),
                   GIT_CONFIG_NOSYSTEM='1', GIT_CONFIG_GLOBAL=os.devnull, GIT_OBJECT_DIRECTORY=str(shadow / 'objects'),
                   GIT_ALTERNATE_OBJECT_DIRECTORIES=str(common / 'objects'))
        allowed = {'core.autocrlf', 'core.eol', 'core.filemode', 'core.symlinks', 'core.ignorecase', 'core.attributesfile', 'core.excludesfile',
                   'extensions.objectformat'}
        effective = {}
        for row in _git(root, 'config', '--null', '--list', raw=True).decode('utf-8', 'surrogateescape').split('\0'):
            key, _, value = row.partition('\n')
            if key.lower() in allowed: effective[key.lower()] = value
        # JSON-style quoting is also Git's config string syntax; write once instead of spawning git for every setting.
        with (shadow / 'config').open('a', encoding='utf-8') as handle:
            for key, value in effective.items():
                section, name = key.split('.', 1)
                handle.write(f'[{section}]\n\t{name} = {json.dumps(value, ensure_ascii=False)}\n')
        for name in ('index', *[p.name for p in gitdir.glob('sharedindex.*')]):
            if (gitdir / name).is_file(): shutil.copyfile(gitdir / name, shadow / name)
        for name in ('attributes', 'exclude'):
            if (common / 'info' / name).is_file(): shutil.copyfile(common / 'info' / name, shadow / 'info' / name)
        yield env


def index_entries(root, env):
    """Index ids/skip-worktree/stat cache, read only from the copied metadata. --debug's stat fields have a fixed Git format."""
    raw = _git(root, 'ls-files', '-s', '-t', '--debug', '-z', raw=True, env=env)
    out, pos = {}, 0
    while pos < len(raw):
        end = raw.index(b'\0', pos)
        header = raw[pos:end].decode('utf-8', 'surrogateescape')
        meta, name = header.split('\t', 1)
        tag, mode, oid, stage = meta.split()
        match = re.match(rb'  ctime: (\d+):(\d+)\n  mtime: (\d+):(\d+)\n  dev:.*\n  uid:.*\n  size: (\d+)\s+flags: [0-9a-f]+\n', raw[end + 1:])
        if not match: raise LedgerError('The source index stat format cannot be read safely.')
        out[name] = {'blob': oid, 'skip': tag == 'S', 'mtime': int(match[3]) * 10**9 + int(match[4]), 'size': int(match[5])}
        pos = end + 1 + match.end()
    return out


def filter_paths(root, names, env):
    names = sorted(names)
    if not names: return {}
    raw = _git(root, 'check-attr', '-z', '--stdin', 'filter', env=env, raw=True,
               input=b''.join(n.encode('utf-8', 'surrogateescape') + b'\0' for n in names)).split(b'\0')
    return {raw[n].decode('utf-8', 'surrogateescape'): raw[n+2].decode('utf-8', 'replace') for n in range(0, len(raw)-2, 3)
            if raw[n+2] not in (b'unspecified', b'unset', b'')}


def unchanged_stat(root, name, entry):
    try:
        facts = os.lstat(Path(root) / name)
        return not os.path.islink(Path(root) / name) and facts.st_size == entry['size'] and facts.st_mtime_ns == entry['mtime']
    except OSError:
        return False


def safe_status(root, env):
    entries = index_entries(root, env)
    others = _git(root, 'ls-files', '--others', '--exclude-standard', '-z', raw=True, env=env).decode('utf-8', 'surrogateescape').split('\0')
    filters = filter_paths(root, set(entries) | {n for n in others if n}, env)
    for name, driver in filters.items():
        if name not in entries or (not entries[name]['skip'] and not unchanged_stat(root, name, entries[name])):
            if (name in entries and not os.path.islink(Path(root) / name) and (Path(root) / name).is_file() and
                    _git(root, 'hash-object', '--no-filters', '--', name, env=env) == entries[name]['blob']):
                continue                    # unchanged Git blob; no external conversion is necessary even when stat data changed
            raise Unavailable('filter_driver', f'{name} needs filter {driver}: external conversion is not run on a read-only source')
    status = _git(root, *STATUS, raw=True, env=env)
    if status and filters:
        name, driver = next(iter(filters.items()))
        raise Unavailable('filter_driver', f'dirty snapshot includes {name} with filter {driver}: external conversion is not run')
    return status


def private_dir(ledger, root):
    """The private object store of a dirty pin of the repository at `root` (under the state root, never in the repository)."""
    return Path(ledger.state_root) / 'source-objects' / content_hash(os.path.normcase(os.path.abspath(str(root))))[:16]


def git_env(ledger, pin):
    """The environment of every git call on a pinned repository: read-only switches; a dirty pin reads its private objects, the
    repository's own objects as alternates."""
    env = dict(READ_ONLY)
    if pin.get('objects') == 'private':
        objects = _git(pin['root'], 'rev-parse', '--path-format=absolute', '--git-path', 'objects')
        env.update(GIT_OBJECT_DIRECTORY=str(private_dir(ledger, pin['root'])), GIT_ALTERNATE_OBJECT_DIRECTORIES=objects)
    return env


def locate(project, path):
    """The absolute folder of a declared repository path (relative to the coordination folder, or absolute); Unavailable when it cannot be
    the folder declared: missing, a link or junction on the way, not spelled as its real name."""
    if re.match(r'[A-Za-z]:/', path):
        if os.name != 'nt': raise Unavailable('unsupported_path', 'a drive path on a system without drives')
        where = Path(path)
    elif path.startswith('/'):
        if os.name == 'nt': raise Unavailable('unsupported_path', 'a path without a drive on Windows: declare a drive path or a folder under the coordination folder')
        where = Path(path)
    else:
        where = Path(project).joinpath(*path.split('/'))
    absolute = os.path.abspath(where)
    if not os.path.lexists(absolute): raise Unavailable('missing', 'the declared folder does not exist')
    links = [p for p in [Path(absolute), *Path(absolute).parents] if os.path.islink(p) or (hasattr(os.path, 'isjunction') and os.path.isjunction(p))]
    if links: raise Unavailable('link', 'the declared path is a link or junction, or passes through one: a link never widens a grant (declare the real folder)')
    try:
        real = os.path.realpath(absolute)
    except OSError as error:
        raise Unavailable('unreadable', f'the declared folder cannot be examined ({type(error).__name__})')
    if os.path.normcase(real) != os.path.normcase(absolute):
        raise Unavailable('link', 'the declared path does not reach the folder it names (a link, a junction or a short name on the way): declare the real folder')
    if not os.path.isdir(absolute): raise Unavailable('missing', 'the declared path is not a folder')
    return Path(absolute)


def pin_repo(ledger, alias, path, read=None):
    """The pin of one declared repository now: {kind: git-tree, declared, root, tree, head, branch, dirty, objects, seconds} or
    {kind: unavailable, declared, root?, state, reason, seconds}. Nothing is written into the repository."""
    started = time.monotonic()
    out = {'declared': path}
    try:
        root = locate(ledger.project, path)
        out['root'] = root.as_posix()
        if _within(Path(ledger.state_root).resolve(), root):
            raise Unavailable('state_inside', 'the OneCrew state root is inside this repository: OneCrew would write into a read-only source')
        if _within(Path(ledger.project).resolve(), root):
            raise Unavailable('project_inside', 'the coordination folder is inside this repository: the root\'s writes would land in a read-only source')
        try:
            top = _git(root, 'rev-parse', '--show-toplevel')
        except LedgerError as error:
            if 'dubious ownership' in str(error): raise Unavailable('dubious_ownership', str(error)) from None
            if _optional(root, 'rev-parse', '--is-bare-repository') == 'true':
                raise Unavailable('bare_repository', 'a bare repository has no working tree') from None
            raise Unavailable('not_a_repository', 'the Git working tree cannot be examined: ' + str(error)) from None
        if os.path.normcase(os.path.abspath(top)) != os.path.normcase(str(root)):
            raise Unavailable('not_top', 'not the top folder of its Git working tree (it lies inside another repository)')
        markers = _git(root, 'rev-parse', '--path-format=absolute', *[a for name, _ in IN_PROGRESS for a in ('--git-path', name)]).splitlines()
        for (name, what), marker in zip(IN_PROGRESS, markers):
            if os.path.lexists(marker):
                raise Unavailable('merge_in_progress', f'{what} is in progress ({name}): an unresolved state is never pinned')
        gitdir, common = git_locations(root)
        for area in (gitdir, common):
            if _within(Path(ledger.state_root).resolve(), area.resolve()):
                raise Unavailable('state_inside', 'the state root is inside the source Git directory')
        if _optional(root, 'config', '--bool', 'index.sparse') == 'true':
            raise Unavailable('sparse_index', 'a sparse index requires expansion; use a full index to read this source without changing it')
        head = _optional(root, 'rev-parse', '--verify', '-q', 'HEAD^{commit}')
        if not head: raise Unavailable('no_commit', 'the repository has no commit to pin')
        base = _git(root, 'rev-parse', '--verify', 'HEAD^{tree}')
        branch = _optional(root, 'symbolic-ref', '-q', 'HEAD')
        with isolated_index(root) as env:
            if _git(root, 'ls-files', '-u', '-z', raw=True, env=env):
                raise Unavailable('unmerged', 'the index holds unmerged entries (a conflict): an unresolved state is never pinned')
            missing = _git(root, 'rev-list', '--objects', '--missing=print', base, env=env)
            if any(line.startswith('?') for line in missing.split('\n')):
                raise Unavailable('partial_clone', 'the pinned commit has missing objects: lazy fetch is disabled for read-only sources')
            status = safe_status(root, env)
            scope = st.Scope(read, read) if read is not None else None
            include = lambda name: (scope is None or scope.allows(name.rstrip('/'))) and not st._withheld(name.rstrip('/'), '100644', 0)
            outside = [row[3:].decode('utf-8', 'surrogateescape') for row in status.split(b'\0') if row and not include(row[3:].decode('utf-8', 'surrogateescape'))]
            if outside:
                raise Unavailable('outside_scope_changes', 'dirty changes outside the readable source scope are not captured: '
                                  + ', '.join(st._row(name, 'outside scope')['path'] for name in outside[:3]))
            if not status:
                tree, objects = base, 'repository'
            else:
                store = private_dir(ledger, root)
                store.mkdir(parents=True, exist_ok=True)
                env = dict(env, GIT_OBJECT_DIRECTORY=str(store))
                tree, objects = command.artifact_sha(str(root), verified=True, git_env=env, store=store, include=include), 'private'
        label = ('bisect probe' if (gitdir / 'BISECT_LOG').exists() else 'detached HEAD' if branch is None else None)
        out.update(kind='git-tree', tree=tree, head=head, branch=branch, dirty=tree != base, objects=objects,
                   **({'label': label} if label else {}))
    except Unavailable as error:
        out.update(kind='unavailable', state=error.state, reason=error.reason[:400])
    except command.HardLinked as error:
        out.update(kind='unavailable', state='unpinnable', reason=('the working tree cannot be pinned: ' + str(error))[:400])
    except GIT_ERRORS as error:
        out.update(kind='unavailable', state='unpinnable', reason=('the repository cannot be pinned: ' + str(error))[:400])
    out['seconds'] = round(time.monotonic() - started, 3)
    return out


def pin_now(ledger, contract, spec):
    """{kind: git-repos, version, repos: {alias: pin}} of the repositories the node names, each pinned on its own now."""
    repos, out, roots = declared(contract), {}, {}
    for alias in node_patterns(spec):
        if alias not in repos:
            out[alias] = {'kind': 'unavailable', 'declared': None, 'state': 'not_granted', 'reason': 'not declared by the approved contract',
                          'seconds': 0.0}
            continue
        row = pin_repo(ledger, alias, repos[alias]['path'], repos[alias]['read'])
        if row['kind'] == 'git-tree':
            same = roots.get(os.path.normcase(row['root']))
            if same:
                row = {'kind': 'unavailable', 'declared': row['declared'], 'root': row['root'], 'state': 'same_repository',
                       'reason': f'the same folder as the repository {same}: one folder is read under one alias', 'seconds': row['seconds']}
            else:
                roots[os.path.normcase(row['root'])] = alias
        out[alias] = row
    return {'kind': KIND, 'version': VERSION, 'repos': out}


def pin(ledger, selector, item):
    """engine.step (through source_tools.pin): the pins of a node that names repositories. A continuation keeps the pins of its chain."""
    if item.get('continues') and not st._repin(ledger, selector, item['continues']):
        kept = st._started_tree(ledger, selector, item['continues'])
        if kept and kept.get('kind') == KIND: return kept
    return pin_now(ledger, st._contract(ledger, selector), item['sources'])


def identity(tree):
    """The pins as the node definition carries them: without the time each took."""
    return {'kind': tree['kind'], 'version': tree.get('version'),
            'repos': {a: {k: v for k, v in p.items() if k != 'seconds'} for a, p in sorted((tree.get('repos') or {}).items())}}


def freshness(pin):
    """(current, note) of a pinned repository now: False when its HEAD or its working tree moved since the pin (the results come from the
    pinned, older snapshot), None for a dirty pin (judged when the result is published), True otherwise."""
    try:
        head = _optional(pin['root'], 'rev-parse', '--verify', '-q', 'HEAD^{commit}')
        if head != pin.get('head'):
            return False, (f'HEAD moved since the pin ({(pin.get("head") or "none")[:12]} -> {(head or "none")[:12]}): these results come from '
                           'the pinned, older snapshot')
        if pin.get('dirty'):
            return None, 'pinned with uncommitted changes: whether the working tree still matches is judged when the result is published'
        with isolated_index(pin['root']) as env:
            status = safe_status(pin['root'], env)
        if status:
            return False, 'the working tree changed since the pin: these results come from the pinned, older snapshot'
        return True, None
    except (Unavailable, *GIT_ERRORS):
        return False, 'the repository cannot be examined now: these results come from the pinned snapshot'


def current_blobs(root, paths):
    """Current file ids, using a copied index and builtin Git conversions only; no external filter can run. Hash files in batches. A filtered
    path uses its index id only when its stat cache or identical raw blob establishes it; absent skip-worktree paths retain the index id.
    An unsafe/missing path or failed batch is None: changed, never silently current. Raw ids preserve deliberately committed CRLF blobs."""
    out = {path: None for path in paths}
    if not root or not out: return out
    try:
        top = os.path.realpath(root)
        files = [p for p in sorted(out) if '\n' not in p and os.path.isfile(Path(root).joinpath(*p.split('/')))
                 and not os.path.islink(Path(root).joinpath(*p.split('/'))) and _within(os.path.realpath(Path(root).joinpath(*p.split('/'))), top)]
        with isolated_index(root) as env:
            entries = index_entries(root, env)
            filters = filter_paths(root, out, env)
            for name in out:
                entry = entries.get(name)
                if entry and ((entry['skip'] and not (Path(root) / name).exists()) or
                              (name in filters and unchanged_stat(root, name, entry))):
                    out[name] = entry['blob']
                elif entry and name in filters and name in files:
                    oid = _git(root, 'hash-object', '--no-filters', '--', name, env=env)
                    if oid == entry['blob']: out[name] = oid
            files = [p for p in files if p not in filters]
            if files:
                data = ''.join(p + '\n' for p in files).encode('utf-8', 'surrogateescape')
                ids = _git(root, 'hash-object', '--stdin-paths', input=data, env=env).split()
                raw = _git(root, 'hash-object', '--no-filters', '--stdin-paths', input=data, env=env).split()
                if len(ids) == len(files) == len(raw):
                    out.update((p, unconverted if entries.get(p, {}).get('blob') == unconverted else oid)
                               for p, oid, unconverted in zip(files, ids, raw))
    except (Unavailable, *GIT_ERRORS):
        pass
    return out


def current_blob(root, path):
    """current_blobs for one file."""
    return current_blobs(root, [path])[path]


# ---- reading ------------------------------------------------------------------------------------------------------------------

def repo_key(alias, root):
    return {'alias': alias, 'root': content_hash(os.path.normcase(os.path.abspath(str(root))))[:16]}


class RepoReader(st.Reader):
    """source_tools.Reader on the pinned snapshot of one declared repository; its results name the repository."""

    def __init__(self, ledger, alias, pin):
        super().__init__(pin['root'], pin['tree'], pin.get('head'), env=git_env(ledger, pin))
        self.alias, self.dirty, self.key = alias, bool(pin.get('dirty')), repo_key(alias, pin['root'])

    @property
    def identity(self):
        return {'repo': self.alias, 'tree': self.tree, 'head': self.head, 'dirty': self.dirty}


def reader(ledger, alias, pin):
    return RepoReader(ledger, alias, pin)


def wrap(cursor, key):
    """The 2.4-A cursor of a result (s1.) as the cursor of its repository (m1.): the same position, bound to the repository too."""
    data = dict(st.uncursor(cursor), r=key)
    return 'm1.' + base64.urlsafe_b64encode(canonical(data).encode('utf-8')).decode('ascii').rstrip('=')


def unwrap(value):
    try:
        if not isinstance(value, str) or not value.startswith('m1.') or len(value) > 2000: raise ValueError
        raw = value[3:] + '=' * (-len(value[3:]) % 4)
        data = json.loads(base64.urlsafe_b64decode(raw.encode('ascii')).decode('utf-8'))
        if (not isinstance(data, dict) or set(data) != {'r', 't', 's', 'o', 'a', 'n'} or not isinstance(data['r'], dict) or set(data['r']) != {'alias', 'root'}
                or data['o'] not in ('list', 'search', 'read') or not isinstance(data['a'], dict) or type(data['n']) is not int or data['n'] < 0):
            raise ValueError
        if (not isinstance(data['r']['alias'], str) or not authority.REPO_ALIAS.fullmatch(data['r']['alias']) or
                not isinstance(data['r']['root'], str) or not re.fullmatch('[0-9a-f]{16}', data['r']['root']) or
                not isinstance(data['t'], str) or not command.TREE_ID.fullmatch(data['t']) or not isinstance(data['s'], str)):
            raise ValueError
        args = data['a']
        if set(args) - {'path', 'query', 'm'} or ('m' in args and (type(args['m']) is not int or args['m'] < 0)):
            raise ValueError
        st.normalize(dict(op=data['o'], **{k: v for k, v in args.items() if k != 'm'}))
        return data
    except (ValueError, TypeError, UnicodeError, st.Refused):
        raise st.Refused('not a source cursor of this node: copy next_cursor exactly') from None


def normalize(request):
    """A request as code accepts it in a node that reads repositories (Refused otherwise): list, search and read name their repository
    (`repo`), except a cursor, which carries it; page is as in 2.4-A."""
    if not isinstance(request, dict) or request.get('op') not in st.OPS: raise st.Refused('op: list, search, read or page')
    op = request['op']
    if op == 'page': return st.normalize(request)
    extra = set(request) - {'op'} - FIELDS[op]
    if extra: raise st.Refused(f'{op} takes ' + ', '.join(sorted(FIELDS[op])) + '; not ' + ', '.join(sorted(map(str, extra)))[:200])
    repo = request.get('repo')
    if repo is not None and (not isinstance(repo, str) or not authority.REPO_ALIAS.fullmatch(repo)):
        raise st.Refused('repo: the alias of one of this node\'s repositories (source_tools.repos)')
    if repo is None and 'cursor' not in request:
        raise st.Refused('list, search and read name their repository: {"repo": alias, ...} (the aliases are in source_tools.repos)')
    clean = st.normalize({k: v for k, v in request.items() if k != 'repo'})
    return dict(clean, **({'repo': repo} if repo is not None else {}))


def _named(clean):
    """(alias, cursor data or None) a normalized list/search/read request names, without judging it."""
    if 'cursor' in clean:
        data = unwrap(clean['cursor'])
        return data['r']['alias'], data
    return clean['repo'], None


def resolve(state, clean):
    """(alias, cursor data or None) of a list/search/read request, or Refused: one of the node's repositories, readable now; a cursor of that
    repository, its pinned snapshot, the same scope and the same operation."""
    alias, data = _named(clean)
    if data and clean.get('repo') not in (None, alias):
        raise st.Refused(f'this cursor belongs to repository {alias}, not {clean["repo"]}')
    row = state['repos'].get(alias)
    if row is None or row['status'] == 'revoked': raise st.Refused(NOT_MINE)
    if row['status'] == 'unavailable': raise st.Refused(f'repository {alias} is unavailable: {row.get("reason")}')
    if row['status'] == 'unreadable': raise st.Refused(f'repository {alias} cannot be read now: {row.get("reason")}')
    if data:
        if data['r'] != state['keys'][alias] or data['t'] != row['tree']: raise st.Refused('source changed; list again')
        if data['s'] != state['scopes'][alias].hash: raise st.Refused('read scope changed; list again')
        if data['o'] != clean['op']: raise st.Refused(f'this cursor continues a {data["o"]}, not a {clean["op"]}')
    return alias, data


def fingerprint(state, request):
    """The effective request (op, repository and its snapshot, path, case-folded query, position) for repeat detection."""
    try:
        clean = normalize(request)
    except st.Refused:
        return content_hash({'repos': state['pins_key'], 'raw': request})[:32]
    if clean['op'] == 'page': return st.fingerprint(state['pins_key'], clean)
    try:
        alias, data = _named(clean)
    except st.Refused:
        return content_hash({'repos': state['pins_key'], 'raw': clean})[:32]
    args, offset = (data['a'], data['n']) if data else (clean, 0)
    path = args.get('path') or ''
    form = {'op': clean['op'], 'path': path.rstrip('/') if clean['op'] != 'read' else path, 'query': (args.get('query') or '').casefold(),
            'skip': args.get('m', 0), 'offset': offset}
    return content_hash({'repo': state['keys'].get(alias) or {'alias': alias}, 'tree': (state['repos'].get(alias) or {}).get('tree'),
                         'request': form})[:32]


def qualify(result, alias, reader):
    """A result of one repository: its cursor bound to the repository, a `cite` on a read and on every match."""
    short = reader.tree[:12]
    if result.get('next_cursor'): result['next_cursor'] = wrap(result['next_cursor'], reader.key)
    if isinstance(result.get('text'), str) and result.get('lines'):
        lines = result['lines']
        result['cite'] = f'{alias}@{short}:{result["path"]}:{lines["start"]}' + (f'-{lines["end"]}' if lines['end'] != lines['start'] else '')
    for match in result.get('matches') or []:
        match['cite'] = f'{alias}@{short}:{match["path"]}:{match["line"]}'
    return result


def run(state, request, *, index=0, lookup=None):
    """The record of one request on the pinned snapshot of its repository: {index, action, arguments, result, fingerprint}."""
    record = {'index': index, 'action': request.get('op') if isinstance(request, dict) else None, 'arguments': request,
              'fingerprint': fingerprint(state, request) if isinstance(request, dict) else None}
    try:
        clean = normalize(request)
        record['arguments'] = clean
        if clean['op'] == 'page':
            target = lookup(clean['index']) if lookup else None
            if target is None: raise st.Refused('no result with this index in this chain')
            alias = ((target.get('result') or {}).get('source') or {}).get('repo')
            if alias and (state['repos'].get(alias) or {}).get('status') != 'pinned':
                raise st.Refused(f'repository {alias} is a coverage gap now: its earlier result is not current evidence')
            field = clean.get('field')
            if field is not None and field not in (target.get('result') or {}):
                raise st.Refused(f'result {clean["index"]} has no field {field!r}; its fields: ' + ', '.join(sorted(target.get('result') or {})))
            record.update(page_of=target['index'], result={'page_of': target['index']})
            return record
        alias, data = resolve(state, clean)
        args, offset = (data['a'], data['n']) if data else ({k: v for k, v in clean.items() if k != 'repo'}, 0)
        reader, scope = state['readers'][alias], state['scopes'][alias]
        try:
            result = {'list': st._list, 'read': st._read, 'search': st._search}[clean['op']](reader, scope, args, offset)
        except st.Refused:
            raise
        except GIT_ERRORS as error:
            raise st.Refused(f'repository {alias} cannot be read now ({type(error).__name__})') from None
        record['result'] = qualify(result, alias, reader)
    except st.Refused as error:
        record['result'] = {'refused': str(error)}
    return record


# ---- a round of a node chain ----------------------------------------------------------------------------------------------------

def _qualified_record(record):
    """The record with every path named by its repository (alias:path): equal files of two repositories are two observations."""
    result = (record or {}).get('result') or {}
    alias = (result.get('source') or {}).get('repo') if isinstance(result.get('source'), dict) else None
    if not alias: return record
    named = lambda p: f'{alias}:{p}' if isinstance(p, str) else p
    result = dict(result)
    if 'path' in result: result['path'] = named(result['path'])
    if 'matches' in result: result['matches'] = [dict(m, path=named(m.get('path'))) for m in result['matches']]
    if 'entries' in result: result['entries'] = [dict(e, path=named(e.get('path'))) for e in result['entries']]
    return dict(record, result=result)


def _progress(records, pins_key):
    """progress_core's repeat/exploration counters replayed over the chain's records, per repository (as source_tools._progress)."""
    state, stopped = {}, None
    for record in records:
        action, args, result = st._observation(_qualified_record(record))
        evidence, intent, page, advanced, empty = progress_core.prepare_evidence(action, args, result)
        key = content_hash({'action': action, 'snapshot': pins_key, 'result': evidence, 'search_intent': intent})
        stopped = progress_core.observe_counters(state, action, args, result, key, page=page, search_advanced=advanced,
                                                 search_empty=empty) or stopped
    counters = state.get('progress') or {}
    return {'observations': counters.get('observations', 0), 'repeated_results': len(counters.get('repeats') or {}), 'stopped': stopped}


def _seen_blobs(records):
    """{alias: {path: blob}} of every file whose content reached a prompt of the chain (reads, search hits, listings; the latest wins)."""
    out = {}
    for r in records:
        result = (r or {}).get('result') or {}
        alias = (result.get('source') or {}).get('repo') if isinstance(result.get('source'), dict) else None
        if not alias: continue
        mine = out.setdefault(alias, {})
        if r.get('action') == 'read' and isinstance(result.get('text'), str) and result.get('blob'): mine[result['path']] = result['blob']
        elif r.get('action') == 'search': mine.update(result.get('blobs') or {})
        elif r.get('action') == 'list': mine.update({e['path']: e['blob'] for e in result.get('entries') or [] if e.get('blob')})
    return out


def _earlier(ledger, selector, nid):
    """The aliases pinned by any attempt of node `nid` in this root (node.started), oldest generations included."""
    from . import namespaces
    with ledger.transaction() as conn:
        root = namespaces.resolve(ledger, conn, selector) if conn else None
        rows = conn.execute("SELECT payload FROM events WHERE task_id=? AND kind='node.started' AND json_extract(payload,'$.node')=?",
                            (root['id'], nid)).fetchall() if root else []
    out = set()
    for row in rows:
        tree = json.loads(row['payload']).get('source_tree') or {}
        if isinstance(tree, dict) and tree.get('kind') == KIND:
            out |= {a for a, p in (tree.get('repos') or {}).items() if isinstance(p, dict) and p.get('kind') == 'git-tree'}
    return sorted(out)


def _pinned(source):
    """{alias: tree} of the pinned repositories of a pin set or a receipt's source block."""
    return {a: p.get('tree') for a, p in sorted(((source or {}).get('repos') or {}).items())
            if p.get('kind') == 'git-tree' and p.get('status', 'pinned') in ('pinned', 'unreadable')}


def _state(ledger, store, selector, node, pins):
    spec = node['sources']
    contract = st._contract(ledger, selector)
    repos, wanted = declared(contract), node_patterns(spec)
    every, receipt_keys, unread = st.node_receipts(ledger, store, selector, node['id'])
    keys, scopes, rows, readers, found = {}, {}, {}, {}, dict((pins or {}).get('repos') or {})
    for alias in wanted:
        pin = found.get(alias) or {'kind': 'unavailable', 'state': 'not_pinned', 'reason': 'not pinned for this chain'}
        if alias not in repos:
            rows[alias] = {'repo': alias, 'status': 'revoked', 'reason': REVOKED}
            continue
        scopes[alias] = st.Scope(repos[alias]['read'], wanted[alias])
        if pin.get('kind') != 'git-tree':
            rows[alias] = {'repo': alias, 'status': 'unavailable', 'state': pin.get('state'), 'reason': pin.get('reason')}
            continue
        keys[alias] = repo_key(alias, pin['root'])
        row = {'repo': alias, 'status': 'pinned', 'tree': pin['tree'], 'head': pin.get('head'), 'branch': pin.get('branch'), 'dirty': bool(pin.get('dirty')),
               **({'label': pin['label']} if pin.get('label') else {})}
        try:
            readers[alias] = RepoReader(ledger, alias, pin)
            entries = readers[alias].entries()
            ids = [e['blob'] for e in entries.values() if e['type'] == 'blob']
            checked = command._git(pin['root'], 'cat-file', '--batch-check', env=readers[alias].env, raw=True,
                                   input=''.join(oid + '\n' for oid in ids).encode('ascii')) if ids else b''
            if len(checked.splitlines()) != len(ids) or any(line.endswith(b' missing') for line in checked.splitlines()):
                raise LedgerError('The pinned snapshot has missing blobs.')
        except GIT_ERRORS as error:
            readers.pop(alias, None)
            rows[alias] = dict(row, status='unreadable', reason=f'its pinned snapshot cannot be read now ({type(error).__name__}): the '
                                                                'repository may have been moved, removed or cleaned')
            continue
        current, note = freshness(pin)
        rows[alias] = dict(row, current=current, **({'note': note} if note else {}))
    for alias in _earlier(ledger, selector, node['id']):
        if alias not in rows and alias not in repos:
            rows[alias] = {'repo': alias, 'status': 'revoked', 'reason': REVOKED}
    rows = dict(sorted(rows.items()))
    gaps = [{k: row[k] for k in ('repo', 'status', 'state', 'reason') if k in row} for row in rows.values() if row['status'] != 'pinned']
    pinned = _pinned(pins)
    base = {'mode': 'repos', 'spec': spec, 'repos': rows, 'gaps': gaps, 'pins': found, 'patterns': wanted, 'scopes': scopes, 'keys': keys,
            'readers': readers, 'pins_key': canonical(pinned)}
    if not readers:
        return dict(base, capability='unavailable', reason='no repository of this node can be read: ' + '; '.join(
            f'{g["repo"]}: {g.get("reason") or g["status"]}' for g in gaps)[:600])
    receipts, broken = st.chain(ledger, store, selector, node.get('continues'))
    history, lost = st._records(store, list(reversed(receipts)))
    node_history, unread_blob = st._records(store, every)
    problem = broken or lost or unread or unread_blob
    previous = receipts[0] if receipts else None
    previous_block = (previous or {}).get('source') or {}
    if previous is None or previous_block.get('capability') != KIND or _pinned(previous_block) != pinned:
        requests = [{'op': 'list', 'repo': alias, 'path': ''} for alias in sorted(readers)]   # newly pinned snapshots start with their catalogue
    else:
        requests = list(previous.get('source_requests') or [])
    known = {r['index']: r for r in history if isinstance(r, dict) and 'index' in r}
    first = max(known, default=-1) + 1
    def lookup(index):
        record = known.get(index)
        return known.get(record.get('page_of')) if record and record.get('action') == 'page' else record
    state = dict(base, capability=KIND, lookup=lookup)
    records = []
    for n, request in enumerate([] if problem else requests):
        record = run(state, request, index=first + n, lookup=lookup)
        records.append(record); known[record['index']] = record
    results = store.blob(canonical({'kind': 'source-results', 'version': st.VERSION, 'mode': 'repos', 'repos': pinned, 'first_index': first,
                                    'records': records}).encode('utf-8'))
    seen = history + [r for r in node_history if r not in history] + records
    before = [_pinned(r.get('source')) for r in every if (r.get('source') or {}).get('capability') == KIND]
    state.update(records=records, results=results, first_index=first, problem=problem,
                 fingerprints={r.get('fingerprint') for r in seen if isinstance(r, dict)} - {None},
                 rounds_used=st._rounds_since_repin(ledger, selector, node['id'], every), node_receipts=receipt_keys,
                 previous_repos=before[-1] if before and before[-1] != pinned else None,
                 chain_changed=any(r.get('changed_paths') for r in receipts),
                 previous_note=((previous or {}).get('continuation') or {}).get('remaining'),
                 refused_last=list(previous_block.get('refused') or [])[:st.REQUESTS_PER_ROUND],
                 progress=_progress(seen, state['pins_key']), read_blobs=_seen_blobs(history + records),
                 rounds_total=sum(1 for r in every if r.get('partial') is True))
    return state


def prepare(ledger, store, selector, node, schema):
    """source_tools.prepare for a node that names repositories: (schema, state). The requests its chain sealed run now on the chain's pins,
    before any prompt exists. With no readable repository the schema is unchanged (the node runs as 2.3) and the state says why."""
    pins = node.get('source_tree') or pin(ledger, selector, node)
    state = _state(ledger, store, selector, node, pins)
    if state['capability'] != KIND: return schema, state
    properties = dict(schema['properties'], source=SCHEMA)
    if not node['write']: properties['continuation'] = CONTINUATION_SCHEMA
    return dict(schema, properties=properties), state


def read_blobs(state):
    """2.4-B: {repos: {alias: {root, tree, blobs}}} of the files of READABLE repositories whose content reached the chain's prompts (None when
    none). A repository that is not readable now is a coverage gap, not current evidence, so it is not judged here."""
    if not state or state.get('capability') != KIND: return None
    out = {}
    for alias, blobs in sorted(state['read_blobs'].items()):
        row = state['repos'].get(alias) or {}
        if blobs and row.get('status') == 'pinned':
            out[alias] = {'root': state['pins'][alias]['root'], 'tree': row['tree'], 'blobs': dict(sorted(blobs.items()))}
    return {'repos': out} if out else None


def _scope_view(state, with_hash=False):
    return {alias: {'read': state['patterns'][alias], 'grant': scope.grants, **({'hash': scope.hash} if with_hash else {}),
                    **({'refused_grant': scope.refused_grant} if scope.refused_grant else {})}
            for alias, scope in sorted(state['scopes'].items())}


def frame(state):
    """The `source_tools` key of the prompt without results."""
    view = {'kind': 'source-tools', 'version': st.VERSION, 'data_not_authority': True, 'notice': st.NOTICE,
            'repos': list(state['repos'].values()), 'coverage_gaps': state['gaps']}
    if state.get('capability') != KIND:
        return dict(view, capability='unavailable', reason=state['reason'], guide=GAPS)
    spec, used = state['spec'], state['rounds_used']
    return dict(view, guide=GUIDE, scope=_scope_view(state),
                rounds={'used': used, 'max': spec['max_rounds'], 'left': max(0, spec['max_rounds'] - used)},
                limits={'requests_per_round': st.REQUESTS_PER_ROUND, 'chars_per_round': spec['max_chars_per_round'], 'list_entries': st.LIST_ENTRIES,
                        'read_chars': st.READ_CHARS, 'search_files': st.SEARCH_FILES, 'match_rows': st.MATCH_ROWS},
                previous_note=state['previous_note'], refused_last_round=state['refused_last'], progress=state['progress'],
                results_blob=state['results'], results=[])


def seal(state, asked, continuation):
    """(accepted, refused): the requests the next round executes, decided by code only (source_tools.seal, per repository)."""
    if state is None or not asked: return [], []
    if state.get('capability') != KIND:
        return [], [{'request': st._brief(r), 'reason': 'source tools are unavailable for this node: ' + state['reason']} for r in asked[:st.MAX_ASKED]]
    accepted, refused = [], []
    seen, used, cap = set(state['fingerprints']), state['rounds_used'], state['spec']['max_rounds']
    total = state['first_index'] + len(state['records'])
    for n, request in enumerate(asked[:st.MAX_ASKED]):
        why, clean = None, request
        try:
            clean = normalize(request)
        except st.Refused as error:
            why = str(error)
        if why is None and n >= st.REQUESTS_PER_ROUND: why = f'more than {st.REQUESTS_PER_ROUND} requests in one round'
        if why is None and continuation is None: why = 'requests run in the next round: answer with a continuation'
        if why is None and state.get('problem'): why = 'the chain evidence cannot be read, no further round: ' + state['problem']
        if why is None and used >= cap: why = f'round cap reached ({used} of {cap})'
        if why is None and state['progress']['stopped']: why = 'progress: ' + state['progress']['stopped']
        if why is None and clean['op'] != 'page':
            try:
                resolve(state, clean)
            except st.Refused as error:
                why = str(error)
        if why is None and clean['op'] == 'page' and not 0 <= clean['index'] < total:
            why = 'no result with this index in this chain'
        if why is None:
            mark = fingerprint(state, clean)
            if mark in seen: why = ('repeat: this request already ran on this snapshot of this repository for this node; use page.next or '
                                    'next_cursor for new content')
            else: seen.add(mark)
        if why: refused.append({'request': st._brief(clean), 'reason': why})
        else: accepted.append(clean)
    if len(asked) > st.MAX_ASKED:
        refused.append({'request': None, 'reason': f'more than {st.MAX_ASKED} entries in the declaration: not looked at', 'count': len(asked) - st.MAX_ASKED})
    return accepted, refused


def _receipt_rows(state):
    out = {}
    for alias, row in state['repos'].items():
        pin = state['pins'].get(alias) or {}
        if row['status'] in ('pinned', 'unreadable'):
            out[alias] = dict({k: v for k, v in pin.items() if k != 'seconds'}, **{k: v for k, v in row.items() if k != 'repo'})
        elif row['status'] == 'unavailable':
            out[alias] = dict({k: v for k, v in pin.items() if k != 'seconds'}, kind='unavailable', status='unavailable',
                              state=row.get('state'), reason=row.get('reason'))
        else:
            out[alias] = {'status': row['status'], 'reason': row.get('reason')}
    return out


def receipt_fields(state, accepted, refused, problem=None, continuation=None):
    """The receipt fields of a node that names repositories (source_tools.receipt_fields, with the repositories and the coverage gaps)."""
    if state is None: return {}
    repos = _receipt_rows(state)
    if state.get('capability') != KIND:
        return {'source': dict({'capability': 'unavailable', 'reason': state['reason'], 'repos': repos, 'coverage_gaps': state['gaps']},
                               **({'refused': refused} if refused else {}), **({'problem': problem} if problem else {}))}
    cap, used = state['spec']['max_rounds'], state['rounds_used']
    exhausted = continuation is not None and (used >= cap or bool(state.get('problem')))
    records = state['records']
    block = {'capability': KIND, 'repos': repos, 'coverage_gaps': state['gaps'], 'scope': _scope_view(state, with_hash=True),
             'results': state['results'], 'first_index': state['first_index'], 'count': len(records),
             'delivered_chars': state.get('delivered_chars'), 'round_chars': state.get('round_chars'), 'pages': state.get('pages', []),
             'not_delivered': state.get('not_delivered', []),
             'execution_refused': [{'index': r['index'], 'reason': r['result']['refused']} for r in records if 'refused' in (r.get('result') or {})],
             'withheld_total': sum((r.get('result') or {}).get('withheld_total', len((r.get('result') or {}).get('withheld') or [])) for r in records),
             'requests': list(accepted), 'refused': list(refused),
             'rounds_used': used + (1 if continuation is not None and not exhausted else 0), 'max_rounds': cap, 'progress': state['progress'],
             'rounds_total': state.get('rounds_total', used) + (1 if continuation is not None and not exhausted else 0),
             **({'previous_repos': state['previous_repos']} if state.get('previous_repos') else {}),
             **({'chain_problem': state['problem']} if state.get('problem') else {}),
             **({'rounds_exhausted': True, 'chain_receipts': list(state.get('node_receipts') or [])} if exhausted else {}),
             **({'problem': problem} if problem else {}), **({'rebuilt': True} if state.get('rebuilt') else {})}
    return {'source': block, **({'source_requests': list(accepted)} if accepted and not exhausted else {})}
