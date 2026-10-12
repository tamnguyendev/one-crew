"""Local git delivery for an approved task: baseline, version edit, commit, reconcile, restore (synthesis §3.5, §3.7).

The commit is ``git commit --only -- <paths>`` on the branch that was checked out at baseline: the repository's own hooks
run, author and committer come from its config, and every other path keeps its index entry and working bytes. A path
that was dirty or staged at baseline is never committed, so a pre-existing hunk cannot be swept in. A retry finds an
earlier commit by its ``OneCrew-Intent`` trailer instead of committing twice. This module never talks to another
repository: the result stays local and the receipt says so.
"""
import base64
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
import subprocess

from .ledger import LedgerError
from .snapshots import bytes_hash, durable_write, scoped_path

GIT_SECONDS = 30
COMMIT_SECONDS = 600
MAX_STATUS = 4_000_000
MAX_HASHED = 2000
MAX_PATHS = 200
MAX_FILE = 1_000_000
MAX_FILES = 8_000_000
TRAILER = 'OneCrew-Intent'
INTENT = re.compile(r'[A-Za-z0-9][A-Za-z0-9._:-]{0,127}')
SHA = re.compile(r'[0-9a-f]{40}|[0-9a-f]{64}')
TRAILER_KEY = re.compile(r'[A-Za-z][A-Za-z0-9-]{0,63}')
TRAILER_LINE = re.compile(r'[A-Za-z][A-Za-z0-9-]*: \S.*')
FIELD = re.compile(r'\{\{|\}\}|\{([A-Za-z_][A-Za-z0-9_]{0,63})\}')
VERSION = re.compile(r'\d+(?:\.\d+){0,3}')
BUMPS = {'major': 0, 'minor': 1, 'patch': 2}
ATTRIBUTES = ('text', 'eol', 'filter', 'working-tree-encoding')
# Attribute and submodule files change how OTHER paths are filtered or resolved, so they are never delivered.
ALWAYS_DENIED = ('.gitattributes', '**/.gitattributes', '.gitmodules')
OPERATIONS = ('MERGE_HEAD', 'CHERRY_PICK_HEAD', 'REVERT_HEAD', 'rebase-merge', 'rebase-apply', 'BISECT_LOG')
PROBLEMS = ('dirty_at_baseline', 'staged_at_baseline', 'ignored', 'denied', 'outside_repo', 'external_filter',
            'not_a_file', 'not_found', 'changed_since_applied', 'not_in_baseline')
BOM = b'\xef\xbb\xbf'


class GitRefusal(LedgerError):
    """A git step refused or could not prove its effect. ``kind`` is the typed reason, ``problems`` the per-path ones."""
    def __init__(self, kind, message, problems=(), **facts):
        super().__init__(message)
        self.kind = kind
        self.problems = list(problems)
        self.facts = facts


def _text(data):
    return data.decode('utf-8', errors='replace')


def _run(project, args, stdin=None, timeout=GIT_SECONDS, plain=False, literal=True):
    environment = {k: v for k, v in os.environ.items() if not k.upper().startswith('GIT_')}
    environment['GIT_TERMINAL_PROMPT'] = '0'
    # The commit runs as the user would run it, so its hooks see normal pathspec and lock behaviour.
    command = ['git', '-C', str(project), *args] if plain else [
        'git', '--no-optional-locks', *(['--literal-pathspecs'] if literal else []), '-C', str(project),
        '-c', 'core.fsmonitor=false', *args]
    options = {'input': stdin} if stdin is not None else {'stdin': subprocess.DEVNULL}
    try:
        return subprocess.run(command, env=environment, capture_output=True, timeout=timeout, **options)
    except subprocess.TimeoutExpired as error:
        raise GitRefusal('git_timeout', f'git {args[0]} did not finish within {timeout} s.') from error
    except OSError as error:
        raise GitRefusal('git_unavailable', 'git could not start: ' + str(error)) from error


def git(project, *args, stdin=None):
    result = _run(project, args, stdin)
    if result.returncode:
        raise GitRefusal('git_failed', f'git {args[0]} failed: ' + _text(result.stderr)[:400])
    return result.stdout


def _repo(project):
    """Work-tree root and the merge/rebase/cherry-pick/revert/bisect in progress, if any (one git call)."""
    root = Path(project).resolve()
    result = _run(root, ['rev-parse', '--show-toplevel', *[a for name in OPERATIONS for a in ('--git-path', name)]])
    lines = _text(result.stdout).splitlines()
    if result.returncode or len(lines) != len(OPERATIONS) + 1 or Path(lines[0]).resolve() != root:
        raise GitRefusal('not_repository_root', f'{root} is not the root of a git work tree.')
    return root, next((name for name, place in zip(OPERATIONS, lines[1:]) if (root/place).exists()), None)


def _root(project):
    return _repo(project)[0]


def _project(project, baseline):
    if not isinstance(baseline, dict) or baseline.get('version') != 1:
        raise LedgerError('Git baseline record is missing or from an unknown version.')
    root, operation = _repo(project)
    if Path(baseline['project']).resolve() != root:
        raise GitRefusal('project_mismatch', 'Git baseline was taken in another repository.')
    return root, operation


def _head(root):
    result = _run(root, ['rev-parse', '--verify', '--quiet', 'HEAD^{commit}'])
    return _text(result.stdout).strip() if result.returncode == 0 else None


def _head_of(status):
    oid = status['branch'].get('oid')
    return None if oid in (None, '(initial)') else oid


def _branch_of(status):
    head = status['branch'].get('head')
    return None if head in (None, '(detached)') else head


def _branch(root):
    result = _run(root, ['symbolic-ref', '--quiet', 'HEAD'])
    ref = _text(result.stdout).strip()
    return ref[len('refs/heads/'):] if result.returncode == 0 and ref.startswith('refs/heads/') else None


def _config(root, key):
    result = _run(root, ['config', '--get', key])
    return _text(result.stdout).strip() if result.returncode == 0 else None


def _sha(value, what):
    if not isinstance(value, str) or not SHA.fullmatch(value):
        raise LedgerError(f'{what} must be a full commit id.')
    return value


def _intent(value):
    if not isinstance(value, str) or not INTENT.fullmatch(value):
        raise LedgerError('Commit intent id must be 1-128 letters, digits, dot, underscore, colon or hyphen.')
    return value


def _path_list(paths, empty=False):
    if not isinstance(paths, (list, tuple)) or len(paths) > MAX_PATHS or (not paths and not empty):
        raise LedgerError(f'Git delivery needs 1-{MAX_PATHS} relative file paths.')
    if any(not isinstance(p, str) for p in paths) or len(set(paths)) != len(paths):
        raise LedgerError('Git delivery paths must be unique strings.')
    return sorted(paths)


def _problem(path, problem, detail=None):
    return {'path': path, 'problem': problem, 'detail': detail}


def _hash_file(target):
    try:
        if target.is_symlink():
            return 'link:' + bytes_hash(os.readlink(target).encode('utf-8'))
        if target.is_dir():
            return 'dir'
        digest = hashlib.sha256()
        with target.open('rb') as stream:
            for chunk in iter(lambda: stream.read(1 << 20), b''):
                digest.update(chunk)
        return digest.hexdigest()
    except (FileNotFoundError, NotADirectoryError):
        return None


def parse_status(data):
    """``git status --porcelain=v2 -z --branch`` output as {'branch': {...}, 'entries': [...]}."""
    found = {'branch': {}, 'entries': []}
    items = data.split(b'\0')
    i = 0
    while i < len(items):
        line = items[i].decode('utf-8')
        i += 1
        if not line:
            continue
        kind = line[0]
        if kind == '#':
            _, key, value = (line.split(' ', 2) + [''])[:3]
            found['branch'][key.removeprefix('branch.')] = value
        elif kind in '12':
            fields = line.split(' ', 8 if kind == '1' else 9)
            entry = {'kind': 'changed' if kind == '1' else 'renamed', 'xy': fields[1], 'sub': fields[2],
                     'mode_head': fields[3], 'mode_index': fields[4], 'mode_worktree': fields[5],
                     'oid_head': fields[6], 'oid_index': fields[7], 'path': fields[-1]}
            if kind == '2':
                entry['score'] = fields[8]
                entry['orig'] = items[i].decode('utf-8')
                i += 1
            found['entries'].append(entry)
        elif kind == 'u':
            fields = line.split(' ', 10)
            found['entries'].append({'kind': 'unmerged', 'xy': fields[1], 'sub': fields[2], 'path': fields[-1]})
        elif kind in '?!':
            found['entries'].append({'kind': 'untracked' if kind == '?' else 'ignored', 'xy': kind * 2, 'path': line[2:]})
        else:
            raise GitRefusal('git_failed', 'Unknown git status line: ' + line[:80])
    return found


def _status(root):
    data = git(root, 'status', '--porcelain=v2', '-z', '--branch', '--untracked-files=all')
    if len(data) > MAX_STATUS:
        raise GitRefusal('status_too_large', 'git status is larger than the delivery bound; clean or ignore build output first.')
    try:
        return parse_status(data)
    except UnicodeDecodeError as error:
        raise GitRefusal('git_failed', 'git status reported a path that is not UTF-8.') from error


def _index(root):
    entries = {}
    for item in git(root, 'ls-files', '-s', '-z').split(b'\0'):
        if item:
            info, path = item.decode('utf-8').split('\t', 1)
            mode, oid, stage = info.split(' ')
            entries[path + ':' + stage] = mode + ' ' + oid
    return entries


def _attributes(root, paths, *names):
    found = {p: {} for p in paths}
    if not paths:
        return found
    items = git(root, 'check-attr', '-z', *names, '--', *paths).decode('utf-8').split('\0')
    for path, name, value in zip(items[0::3], items[1::3], items[2::3]):
        found.setdefault(path, {})[name] = value
    return found


def _ignored(root, paths):
    # check-ignore takes plain path names and rejects the literal-pathspec flag.
    result = _run(root, ['check-ignore', '-z', '--stdin'], stdin=''.join(p + '\0' for p in paths).encode('utf-8'),
                  literal=False)
    if result.returncode not in (0, 1):
        raise GitRefusal('git_failed', 'git check-ignore failed: ' + _text(result.stderr)[:400])
    return sorted(p for p in result.stdout.decode('utf-8').split('\0') if p)


def _eol_of(data):
    if b'\0' in data:
        return '-text'
    crlf = data.count(b'\r\n')
    lf = data.count(b'\n') - crlf
    return 'none' if not crlf + lf else 'crlf' if not lf else 'lf' if not crlf else 'mixed'


def _eol(root, paths):
    index = {}
    for item in git(root, 'ls-files', '--eol', '-z', '--', *paths).split(b'\0') if paths else ():
        if item:
            info, path = item.decode('utf-8').split('\t', 1)
            index[path] = info.split()[0].removeprefix('i/') or None
    found = {}
    for path, attributes in _attributes(root, paths, *ATTRIBUTES).items():
        target = root/path
        found[path] = {**attributes, 'index': index.get(path),
                       'worktree': _eol_of(target.read_bytes()) if target.is_file() else None}
    return found


def _path_problem(root, path):
    if (not isinstance(path, str) or not path or len(path) > 240 or '\\' in path or '\n' in path or
            path.startswith('/') or re.match(r'[A-Za-z]:', path) or any(p in ('', '.', '..') for p in path.split('/'))):
        return 'outside_repo'
    try:
        scoped_path(path)
    except LedgerError:
        return 'denied'
    target = root
    for part in path.split('/'):
        target = target/part
        if target.is_symlink() or (hasattr(target, 'is_junction') and target.is_junction()) or (target/'.git').exists():
            return 'outside_repo'
    return 'not_a_file' if target.is_dir() else None


def _files(root, paths):
    found = {}
    total = 0
    for path in paths:
        target = root/path
        if not target.is_file():
            found[path] = {'sha256': None, 'data': None}
            continue
        data = target.read_bytes()
        total += len(data)
        if len(data) > MAX_FILE or total > MAX_FILES:
            raise GitRefusal('baseline_too_large', f'Baseline copy of {path} exceeds the bound; narrow the owned paths.')
        found[path] = {'sha256': bytes_hash(data), 'data': base64.b64encode(data).decode('ascii')}
    return found


def baseline(project, paths=()):
    """Repository state before OneCrew edits; ``paths`` (the planned owned files) also keep eol facts and exact bytes."""
    root, operation = _repo(project)
    paths = _path_list(paths, empty=True)
    problems = [_problem(p, found) for p in paths if (found := _path_problem(root, p))]
    if problems:
        raise GitRefusal('path_problems', 'Baseline paths refused: ' + _describe(problems), problems)
    status = _status(root)
    dirty = sorted({p for e in status['entries'] if e['kind'] in ('changed', 'renamed', 'unmerged')
                    for p in (e['path'], e.get('orig')) if p})
    untracked = sorted(e['path'] for e in status['entries'] if e['kind'] == 'untracked')
    return {'version': 1, 'project': str(root), 'head': _head_of(status), 'branch': _branch_of(status),
            'detached': status['branch'].get('head') == '(detached)',
            'operation': operation, 'status': status,
            'dirty': {p: _hash_file(root/p) for p in dirty[:MAX_HASHED]},
            'untracked': {p: _hash_file(root/p) for p in untracked[:MAX_HASHED]},
            'truncated': len(dirty) > MAX_HASHED or len(untracked) > MAX_HASHED,
            'autocrlf': _config(root, 'core.autocrlf'), 'eol': _eol(root, paths), 'files': _files(root, paths)}


def _baseline_states(baseline):
    states = {}

    def add(path, state):
        states.setdefault(path, set()).add(state)
    for entry in baseline['status']['entries']:
        if entry['kind'] == 'untracked':
            add(entry['path'], 'dirty_at_baseline')
        elif entry['kind'] == 'ignored':
            add(entry['path'], 'ignored')
        elif entry['kind'] == 'unmerged':
            add(entry['path'], 'staged_at_baseline')
        else:
            if entry['xy'][0] != '.':
                add(entry['path'], 'staged_at_baseline')
                if entry.get('orig'):
                    add(entry['orig'], 'staged_at_baseline')
            if entry['xy'][1] != '.':
                add(entry['path'], 'dirty_at_baseline')
    return states


def check_paths(baseline, paths, deny_globs=()):
    """Typed reasons why ``paths`` may not be committed (empty list = every path may be)."""
    if not isinstance(deny_globs, (list, tuple)) or any(not isinstance(g, str) or not g for g in deny_globs):
        raise LedgerError('Deny globs must be a list of non-empty POSIX glob strings.')
    root = Path(baseline['project'])
    deny = (*deny_globs, *ALWAYS_DENIED)
    states = _baseline_states(baseline)
    problems = []
    usable = []
    for path in paths:
        found = _path_problem(root, path)
        if not found and any(PurePosixPath(path).full_match(glob) for glob in deny):
            found = 'denied'
        if found:
            problems.append(_problem(path, found))
            continue
        problems += [_problem(path, state) for state in sorted(states.get(path, ()))]
        usable.append(path)
    if usable:
        problems += [_problem(p, 'ignored') for p in _ignored(root, usable) if 'ignored' not in states.get(p, ())]
        problems += [_problem(p, 'external_filter', a['filter']) for p, a in _attributes(root, usable, 'filter').items()
                     if a.get('filter') not in ('unspecified', 'unset', None)]
    return sorted(problems, key=lambda p: (p['path'], p['problem']))


def _describe(problems):
    return ', '.join(f"{p['path']}: {p['problem']}" for p in problems[:10])


def _with_intent(message, intent):
    if not isinstance(message, str) or not message.strip() or len(message) > 20000:
        raise LedgerError('Commit message must be non-empty text.')
    if re.search(r'(?im)^' + TRAILER + r'\s*:', message):
        raise LedgerError(TRAILER + ' is added by the commit step, not by the message.')
    text = '\n'.join(line.rstrip() for line in message.replace('\r\n', '\n').strip().split('\n'))
    blocks = text.split('\n\n')
    line = f'{TRAILER}: {intent}'
    if len(blocks) > 1 and all(TRAILER_LINE.fullmatch(item) for item in blocks[-1].split('\n')):
        return text + '\n' + line + '\n'
    return text + '\n\n' + line + '\n'


def _fill(text, fields):
    if not isinstance(text, str):
        raise LedgerError('Commit message template parts must be text.')

    def value(match):
        if match[0] in ('{{', '}}'):
            return match[0][0]
        if match[1] not in fields:
            raise LedgerError('Commit message field missing: ' + match[1])
        item = fields[match[1]]
        if isinstance(item, bool) or not isinstance(item, (str, int)):
            raise LedgerError('Commit message field must be text or an integer: ' + match[1])
        return str(item)
    return FIELD.sub(value, text)


def render_message(template, fields):
    """{'subject', 'body' (text or lines), 'trailers' ([[key, value]] or {key: value})} with ``{name}`` fields filled."""
    if not isinstance(template, dict) or 'subject' not in template or not set(template) <= {'subject', 'body', 'trailers'}:
        raise LedgerError('Commit message template needs subject and may have body and trailers only.')
    fields = dict(fields or {})
    subject = _fill(template['subject'], fields).strip()
    if not subject or '\n' in subject or len(subject) > 120:
        raise LedgerError('Commit subject must be one line of at most 120 characters.')
    body = template.get('body') or ''
    body = '\n'.join(_fill(line, fields) for line in body) if isinstance(body, list) else _fill(body, fields)
    trailers = template.get('trailers') or []
    pairs = list(trailers.items()) if isinstance(trailers, dict) else trailers
    lines = []
    for pair in pairs:
        if not isinstance(pair, (list, tuple)) or len(pair) != 2 or not isinstance(pair[0], str) or not TRAILER_KEY.fullmatch(pair[0]):
            raise LedgerError('Commit trailers must be [key, value] with a token key.')
        if pair[0].lower() == TRAILER.lower():
            raise LedgerError(TRAILER + ' is added by the commit step.')
        value = _fill(pair[1], fields).strip()
        if not value or '\n' in value:
            raise LedgerError('Commit trailer value must be one non-empty line: ' + pair[0])
        lines.append(f'{pair[0]}: {value}')
    return '\n\n'.join(part for part in (subject, body.strip('\n'), '\n'.join(lines)) if part) + '\n'


def _changed(root, parent, commit):
    data = git(root, 'diff-tree', '-r', '-z', '--no-commit-id', '--name-only', '--no-renames', parent, commit)
    return sorted(p for p in data.decode('utf-8').split('\0') if p)


def _facts(root, commit):
    fields = _text(git(root, 'log', '-1', '--format=%P%x00%an <%ae>%x00%(trailers:key=' + TRAILER +
                       ',valueonly,separator=%x1f)', commit)).strip('\n').split('\0')
    return {'parents': fields[0].split(), 'author': fields[1], 'intents': fields[2].strip().split('\x1f')}


def _receipt(root, commit, parent, intent, reconciled, facts=None, changed=None, branch=None):
    return {'commit': commit, 'parent': parent, 'branch': branch or _branch(root),
            'paths': changed if changed is not None else _changed(root, parent, commit), 'intent': intent,
            'author': (facts or _facts(root, commit))['author'], 'pushed': False, 'reconciled': reconciled}


def reconcile(project, intent_id, expected_head):
    """The commit carrying ``intent_id`` made directly on ``expected_head`` and reachable from HEAD, or None."""
    root = _root(project)
    return _reconcile(root, _intent(intent_id), _sha(expected_head, 'Expected head'), _head(root))


def _reconcile(root, intent, expected, head):
    if not head or head == expected:
        return None
    result = _run(root, ['log', '--max-count=200', '--format=%H%x00%P%x00%(trailers:key=' + TRAILER +
                         ',valueonly,separator=%x1f)%x1e', expected + '..' + head])
    if result.returncode:
        return None
    for row in _text(result.stdout).split('\x1e'):
        fields = row.strip('\n').split('\0')
        if len(fields) == 3 and fields[1].split() == [expected] and intent in fields[2].split('\x1f'):
            return _receipt(root, fields[0], expected, intent, True)
    return None


def _expect(status, branch, expected):
    current = _branch_of(status)
    if current != branch:
        raise GitRefusal('branch_changed', f'Checked-out branch is {current or "detached"}, baseline was {branch}.')
    head = _head_of(status)
    if head != expected:
        raise GitRefusal('head_moved', f'HEAD is {head}, expected {expected}; nothing was committed.', head=head)


def _without(index, paths):
    skip = set(paths)
    return {k: v for k, v in index.items() if k.rsplit(':', 1)[0] not in skip}


def _others(status, paths):
    skip = set(paths)
    return {e['path']: e['xy'] for e in status['entries'] if e['path'] not in skip and e.get('orig') not in skip}


def _guard(root, baseline, paths, status, index):
    names = set(baseline['dirty']) | set(baseline['untracked'])
    names |= {p for e in status['entries'] for p in (e['path'], e.get('orig')) if p}
    names = sorted(names - set(paths))[:MAX_HASHED * 2]
    return {'status': _others(status, paths), 'index': _without(index, paths),
            'work': {p: _hash_file(root/p) for p in names}}


def _applied_problems(root, paths, applied):
    if applied is None:
        return []
    return [_problem(p, 'changed_since_applied') for p in paths if p not in applied or _hash_file(root/p) != applied[p]]


def _verify(root, branch, expected, intent, paths, before, reconciled):
    status = _status(root)
    head = _head_of(status)
    facts = _facts(root, head)
    failed = []
    if _branch_of(status) != branch:
        failed.append('branch')
    if facts['parents'] != [expected]:
        failed.append('parent')
    if intent not in facts['intents']:
        failed.append('trailer')
    changed = _changed(root, expected, head) if 'parent' not in failed else []
    if not changed or not set(changed) <= set(paths):
        failed.append('paths')
    # No status entry for the paths: HEAD, index and working bytes agree under git's own eol/ident filters.
    if len(_others(status, paths)) != len(status['entries']):
        failed.append('committed_differs_from_worktree')
    if _others(status, paths) != before['status']:
        failed.append('other_status_changed')
    if _without(_index(root), paths) != before['index']:
        failed.append('other_index_changed')
    if {p: _hash_file(root/p) for p in before['work']} != before['work']:
        failed.append('other_worktree_changed')
    if failed:
        raise GitRefusal('verification_failed', f'Commit {head} failed verification: ' + ', '.join(failed),
                         commit=head, failed=failed)
    return _receipt(root, head, expected, intent, reconciled, facts, changed, branch)


def commit(project, baseline, paths, message, intent_id, expected_head=None, deny_globs=(), applied=None):
    """Commit exactly ``paths`` on the baseline branch; ``applied`` ({path: sha256}) also pins the bytes OneCrew wrote."""
    root, operation = _project(project, baseline)
    intent = _intent(intent_id)
    paths = _path_list(paths)
    text = _with_intent(message, intent)
    branch = baseline['branch']
    if not branch:
        raise GitRefusal('detached', 'A local commit needs the branch that was checked out at baseline.')
    expected = _sha(expected_head or baseline['head'], 'Expected head')
    status = _status(root)
    found = _reconcile(root, intent, expected, _head_of(status))
    if found:
        if not set(found['paths']) <= set(paths):
            raise GitRefusal('intent_conflict', f'Commit {found["commit"]} already carries this intent for other paths.')
        return found
    _expect(status, branch, expected)
    if operation:
        raise GitRefusal('operation_in_progress', f'{operation} is in progress; nothing was committed.')
    problems = check_paths(baseline, paths, deny_globs) + _applied_problems(root, paths, applied)
    if not problems:
        index = _index(root)
        tracked = {k.rsplit(':', 1)[0] for k in index}
        problems = [_problem(p, 'not_found') for p in paths if p not in tracked and _hash_file(root/p) is None]
    if problems:
        raise GitRefusal('path_problems', 'Commit refused: ' + _describe(problems), problems)
    if len(_others(status, paths)) == len(status['entries']):
        raise GitRefusal('nothing_to_commit', 'The selected paths equal HEAD; nothing was committed.')
    before = _guard(root, baseline, paths, status, index)
    added = [p for p in paths if p not in tracked]
    if added:
        git(root, 'add', '--intent-to-add', '--', *added)
    try:
        result = _run(root, ['commit', '--only', '--no-edit', '--cleanup=whitespace', '--quiet', '-F', '-', '--',
                             *[':(literal)' + p for p in paths]], text.encode('utf-8'), COMMIT_SECONDS, plain=True)
        failure = _text(result.stderr) if result.returncode else None
    except GitRefusal as error:
        failure = str(error)
    if failure is not None and not _reconcile(root, intent, expected, _head(root)):
        try:
            if added:
                git(root, 'update-index', '--force-remove', '--', *added)
        except GitRefusal as error:
            failure += '\nCould not drop the intent-to-add entries: ' + str(error)
        raise GitRefusal('commit_failed', 'git commit did not complete: ' + failure[:400], detail=failure[:2000])
    return _verify(root, branch, expected, intent, paths, before, failure is not None)


def _top_level_value(text, field):
    def skip(i):
        while i < len(text) and text[i] in ' \t\r\n':
            i += 1
        return i

    def string_end(i):
        j = i + 1
        while j < len(text):
            if text[j] == '\\':
                j += 2
            elif text[j] == '"':
                return j + 1
            else:
                j += 1
        raise GitRefusal('invalid_json', 'Unterminated JSON string.')

    spans = []
    depth = 0
    key = False
    i = 0
    while i < len(text):
        c = text[i]
        if c == '"':
            end = string_end(i)
            if depth == 1 and key:
                colon = skip(end)
                value = skip(colon + 1)
                if text[colon:colon + 1] != ':':
                    raise GitRefusal('invalid_json', 'JSON key without a colon.')
                if json.loads(text[i:end]) == field:
                    if text[value:value + 1] != '"':
                        raise GitRefusal('unsupported_version', f'Top-level {field} is not a string.')
                    spans.append((value, string_end(value)))
                    end = spans[-1][1]
                else:
                    end = value
                key = False
            i = end
            continue
        if c in '{[':
            depth += 1
            key = depth == 1 and c == '{'
        elif c in '}]':
            depth -= 1
        elif c == ',' and depth == 1:
            key = True
        i += 1
    if len(spans) != 1:
        raise GitRefusal('unsupported_version', f'Top-level {field} must appear exactly once.')
    return spans[0]


def _bumped(old, bump):
    parts = old.split('.')
    index = BUMPS[bump]
    parts += ['0'] * (index + 1 - len(parts))
    parts[index] = str(int(parts[index]) + 1)
    parts[index + 1:] = ['0'] * (len(parts) - index - 1)
    return '.'.join(parts)


def _cas_write(target, data, expected):
    if _hash_file(target) != expected:
        raise GitRefusal('cas_mismatch', f'{target.name} changed since it was read; nothing was written.')
    try:
        if data is None:
            target.unlink()
        else:
            mode = stat.S_IMODE(target.stat().st_mode) if target.exists() else None
            durable_write(target, data)
            if mode is not None:
                os.chmod(target, mode)
    except OSError as error:
        raise GitRefusal('write_failed', f'Could not write {target.name}: {error}') from error
    if _hash_file(target) != (None if data is None else bytes_hash(data)):
        raise GitRefusal('verification_failed', f'{target.name} does not hold the bytes just written.')


def version_bump(project, relpath, field='version', bump='patch', expected_sha=None):
    """Increment a top-level JSON version string in place; every other byte (indent, eol, BOM, order) is kept."""
    root = _root(project)
    if bump not in BUMPS:
        raise LedgerError('Version bump must be major, minor or patch.')
    problem = _path_problem(root, relpath)
    if problem:
        raise GitRefusal('path_problems', f'{relpath}: {problem}', [_problem(relpath, problem)])
    target = root/relpath
    if not target.is_file():
        raise GitRefusal('not_found', f'{relpath} does not exist.')
    data = target.read_bytes()
    before = bytes_hash(data)
    if expected_sha is not None and before != expected_sha:
        raise GitRefusal('cas_mismatch', f'{relpath} is not the expected revision; nothing was written.')
    bom = data.startswith(BOM)
    try:
        text = data[len(BOM) if bom else 0:].decode('utf-8')
        document = json.loads(text)
    except ValueError as error:
        raise GitRefusal('invalid_json', f'{relpath} is not UTF-8 JSON.') from error
    if not isinstance(document, dict):
        raise GitRefusal('invalid_json', f'{relpath} is not a JSON object.')
    start, end = _top_level_value(text, field)
    old = document.get(field)
    if not isinstance(old, str) or not VERSION.fullmatch(old):
        raise GitRefusal('unsupported_version', f'{field} {old!r} is not 1-4 dot-separated numbers.')
    new = _bumped(old, bump)
    edited = text[:start] + json.dumps(new) + text[end:]
    if json.loads(edited) != {**document, field: new}:
        raise GitRefusal('invalid_json', 'Version edit would change other content.')
    output = (BOM if bom else b'') + edited.encode('utf-8')
    _cas_write(target, output, before)
    return {'path': relpath, 'field': field, 'old': old, 'new': new, 'sha_before': before, 'sha_after': bytes_hash(output)}


def _original(root, baseline, path):
    """Baseline bytes of ``path``: bytes, None when it did not exist, False when the baseline cannot tell exactly."""
    item = baseline.get('files', {}).get(path)
    if item is not None:
        if item['sha256'] is None:
            return None
        data = base64.b64decode(item['data'])
        return data if bytes_hash(data) == item['sha256'] else False
    if path in _baseline_states(baseline) or path in baseline['dirty'] or path in baseline['untracked']:
        return False
    if baseline['head'] and git(root, 'ls-tree', '-z', _sha(baseline['head'], 'Baseline head'), '--', path).strip():
        return False
    return False if _ignored(root, [path]) else None


def restore_baseline(project, baseline, applied):
    """Put ``applied`` paths ({path: sha256 OneCrew wrote, or None if it deleted}) back to baseline bytes, all or none."""
    root = _project(project, baseline)[0]
    if not isinstance(applied, dict) or not 1 <= len(applied) <= MAX_PATHS or any(not isinstance(p, str) for p in applied):
        raise LedgerError(f'Restore needs 1-{MAX_PATHS} applied paths.')
    problems = []
    plan = []
    for path in sorted(applied):
        expected = applied[path]
        if expected is not None and (not isinstance(expected, str) or not re.fullmatch(r'[0-9a-f]{64}', expected)):
            raise LedgerError('Applied bytes must be a sha256 hex digest or null.')
        found = _path_problem(root, path)
        original = False if found else _original(root, baseline, path)
        if found or original is False:
            problems.append(_problem(path, found or 'not_in_baseline'))
        elif _hash_file(root/path) != expected:
            problems.append(_problem(path, 'changed_since_applied'))
        else:
            plan.append((path, expected, original))
    if problems:
        raise GitRefusal('restore_refused', 'Restore refused; nothing was written: ' + _describe(problems), problems)
    for path, expected, original in plan:
        if expected != (None if original is None else bytes_hash(original)):
            _cas_write(root/path, original, expected)
    return {'restored': [p for p, _, _ in plan], 'sha256': {p: None if o is None else bytes_hash(o) for p, _, o in plan}}
