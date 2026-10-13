"""Work contracts (13/10/2026): what the user controls — goal, scope, invariants, acceptance, authority — sealed into a
generic OneCrew job. How the work is done is the runtime's choice inside this contract; nothing here is a plan."""
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess

from .ledger import LedgerError, canonical, content_hash, text_field
from .snapshots import scoped_path

SCHEMA_VERSION = 1
FIELDS = {'schema_version', 'goal', 'scope', 'preserve', 'acceptance', 'checks', 'authority', 'authorized_by'}
AUTHORITY = {'edit', 'commands', 'local_branches', 'branch_at', 'apply_to_project', 'edit_tests', 'push', 'unconfined_commands'}
SHA = re.compile(r'[0-9a-f]{40}|[0-9a-f]{64}')


def branch_name(value):
    """A plain local branch name (git check-ref-format rules that matter here, without shell or ref tricks)."""
    if (not isinstance(value, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._/-]{0,100}', value) or '..' in value
            or '//' in value or value.endswith(('/', '.', '.lock')) or '/.' in value or value.upper() == 'HEAD'):
        raise LedgerError('Invalid local branch name: ' + str(value)[:80])
    return value


def _texts(value, name, maximum_items, maximum_length, required=False):
    if value is None and not required: return []
    if not isinstance(value, list) or len(value) > maximum_items or (required and not value):
        raise LedgerError(f'{name}: expected a list of at most {maximum_items} items' + (' (at least one)' if required else '') + '.')
    return [text_field(v, name, maximum_length) for v in value]


def argv_value(value, name='argv'):
    if (not isinstance(value, list) or not 1 <= len(value) <= 40 or
            any(not isinstance(a, str) or not a or len(a) > 2000 or '\0' in a or '\n' in a for a in value)):
        raise LedgerError(name + ': expected a list of 1-40 non-empty single-line arguments.')
    return list(value)


def relative_dir(value, name='cwd'):
    if value in (None, '', '.'): return ''
    scoped_path(value)
    return value


def validate(value, project):
    """Normalized contract, or LedgerError. project: the OneCrew project root (Path)."""
    if not isinstance(value, dict) or set(value) - FIELDS:
        raise LedgerError('Work contract: unknown fields ' + ','.join(sorted(set(value) - FIELDS)) if isinstance(value, dict) else
                          'Work contract must be a JSON object.')
    if value.get('schema_version') != SCHEMA_VERSION: raise LedgerError('Work contract schema_version must be 1.')
    scope = value.get('scope') or {}
    if not isinstance(scope, dict) or set(scope) - {'repository', 'paths'}: raise LedgerError('scope: expected repository and paths.')
    repository = relative_dir(scope.get('repository', ''), 'scope.repository')
    root = Path(project).resolve() / repository if repository else Path(project).resolve()
    if not (root / '.git').exists(): raise LedgerError('scope.repository must be a Git repository inside the project.')
    paths = [relative_dir(p, 'scope.paths') for p in (scope.get('paths') or [])]
    if len(paths) > 20: raise LedgerError('scope.paths: at most 20 prefixes.')
    checks = []
    for check in value.get('checks') or []:
        if not isinstance(check, dict) or check.get('kind') not in ('ref', 'command'): raise LedgerError('checks: kind ref or command.')
        if check['kind'] == 'ref':
            if set(check) != {'kind', 'name', 'equals'}: raise LedgerError('ref check: kind, name, equals.')
            if check['equals'] != 'pinned_head' and not SHA.fullmatch(str(check['equals'])): raise LedgerError('ref check equals: pinned_head or a full SHA.')
            checks.append({'kind': 'ref', 'name': branch_name(check['name']), 'equals': check['equals']})
        else:
            if set(check) - {'kind', 'argv', 'cwd'}: raise LedgerError('command check: kind, argv, cwd.')
            checks.append({'kind': 'command', 'argv': argv_value(check.get('argv')), 'cwd': relative_dir(check.get('cwd'))})
    if len(checks) > 10: raise LedgerError('checks: at most 10.')
    if any(c['kind'] == 'command' for c in checks) and not ((value.get('authority') or {}).get('edit') or (value.get('authority') or {}).get('commands')):
        raise LedgerError('Command checks run in the isolated workspace: grant edit or commands.')
    authority = value.get('authority') or {}
    if not isinstance(authority, dict) or set(authority) - AUTHORITY: raise LedgerError('authority: unknown keys.')
    for key in ('edit', 'commands', 'apply_to_project', 'edit_tests', 'push', 'unconfined_commands'):
        if key in authority and type(authority[key]) is not bool: raise LedgerError('authority.' + key + ' must be boolean.')
    if authority.get('push'):
        raise LedgerError('authority.push is not available in work contracts; publication needs its own delivery job.')
    branches = authority.get('local_branches') or []
    if not isinstance(branches, list) or len(branches) > 10: raise LedgerError('authority.local_branches: at most 10 names.')
    at = authority.get('branch_at', 'pinned_head')
    if at != 'pinned_head' and not SHA.fullmatch(str(at)): raise LedgerError('authority.branch_at: pinned_head or a full SHA.')
    if authority.get('apply_to_project') and not authority.get('edit'): raise LedgerError('apply_to_project requires edit.')
    if authority.get('unconfined_commands') and not authority.get('commands'): raise LedgerError('unconfined_commands requires commands.')
    signed = value.get('authorized_by')
    if not isinstance(signed, dict) or set(signed) != {'source', 'reference'}:
        raise LedgerError('authorized_by: source and reference (attribution of the user authorization).')
    return {'schema_version': 1, 'goal': text_field(value.get('goal'), 'goal', 12000),
            'scope': {'repository': repository, 'paths': paths},
            'preserve': _texts(value.get('preserve'), 'preserve', 20, 500),
            'acceptance': _texts(value.get('acceptance'), 'acceptance', 20, 1000, required=True),
            'checks': checks,
            'authority': {'edit': bool(authority.get('edit')), 'commands': bool(authority.get('commands')),
                          'local_branches': sorted({branch_name(b) for b in branches}), 'branch_at': at,
                          'apply_to_project': bool(authority.get('apply_to_project')),
                          'edit_tests': bool(authority.get('edit_tests')), 'push': False,
                          # The user's choice to let commands write outside the workspace (e.g. a Flutter SDK cache).
                          'unconfined_commands': bool(authority.get('unconfined_commands'))},
            'authorized_by': {'source': text_field(signed['source'], 'authorized_by.source', 120),
                              'reference': text_field(signed['reference'], 'authorized_by.reference', 500)}}


def permissions(contract):
    a = contract['authority']
    return (['discover', 'report'] + (['workspace.edit'] if a['edit'] else []) + (['workspace.run'] if a['commands'] else [])
            + (['git.branch'] if a['local_branches'] else []) + (['project.apply'] if a['apply_to_project'] else []))


CONFIG_SELECTION = ('GIT_CONFIG_GLOBAL', 'GIT_CONFIG_SYSTEM', 'GIT_CONFIG_NOSYSTEM')


def git(repo, *args, allow_failure=False, timeout=60, stdin=None, git_dir=None, work_tree=None, env=None):
    """Git against a repository without touching its index stat cache or running its hooks. The user's configuration
    files are the ones the user's own git reads (GIT_CONFIG_GLOBAL/SYSTEM/NOSYSTEM kept, so line-ending rules match);
    every variable that could redirect the repository or inject configuration is dropped. Eval run gx-20261013 found
    the mismatch: dropping GIT_CONFIG_GLOBAL made blobs differ under autocrlf."""
    environment = {k: v for k, v in os.environ.items() if not k.upper().startswith('GIT_') or k.upper() in CONFIG_SELECTION}
    hooks = Path(os.environ.get('TEMP') or os.environ.get('TMP') or '.') / 'onecrew-empty-hooks'
    hooks.mkdir(parents=True, exist_ok=True)
    if env: environment.update(env)
    # git_dir/work_tree: the core names the workspace repository itself, so a gitfile or commondir written by a command
    # can never redirect a core Git operation to another repository (GX-P1-01).
    explicit = (['--git-dir=' + str(git_dir)] if git_dir else []) + (['--work-tree=' + str(work_tree)] if work_tree else [])
    argv = ['git', '--no-optional-locks', '--literal-pathspecs', *explicit, '-C', str(repo), '-c', 'core.fsmonitor=false',
            '-c', 'core.longpaths=true', '-c', 'core.hooksPath=' + str(hooks), *args]
    done = subprocess.run(argv, capture_output=True, timeout=timeout, env=environment, input=stdin,
                          creationflags=0x08000000 if os.name == 'nt' else 0)
    if done.returncode and not allow_failure:
        raise LedgerError('git ' + ' '.join(args[:2]) + ' failed: ' + done.stderr.decode('utf-8', errors='replace')[:300])
    return done.stdout if done.returncode == 0 else None


def _dirty_digest(repo, porcelain):
    """Hash of every dirty/untracked path and its current bytes, so content edits of an already-dirty file count."""
    digest = hashlib.sha256(porcelain)
    entries = [e for e in porcelain.split(b'\0') if e]
    names = []
    skip = False
    for entry in entries:
        if skip: skip = False; continue
        status, name = entry[:2], entry[3:]
        names.append(name)
        if status[:1] in (b'R', b'C'): skip = True  # the next record is the source path of a rename/copy
    total = 0; each = {}
    for name in sorted(names)[:5000]:
        text = name.decode('utf-8', errors='surrogateescape'); path = Path(repo) / text
        digest.update(name + b'\0'); value = 'other'
        if path.is_file() and not path.is_symlink():
            size = path.stat().st_size; total += size
            if total > 256_000_000:
                digest.update(b'size:' + str(size).encode()); each[text.rstrip('/')] = 'size:' + str(size); continue
            value = hashlib.sha256(path.read_bytes()).hexdigest(); digest.update(bytes.fromhex(value))
        elif not path.exists(): value = 'missing'
        each[text.rstrip('/')] = value  # per path, so an apply exempts exactly its own files (GX-P1-03)
    return digest.hexdigest(), len(names), each


def pins(repo):
    """Observed state of the user's repository before any work: what must be preserved, and the base commit."""
    head = git(repo, 'rev-parse', '--verify', 'HEAD').decode().strip()
    branch = git(repo, 'symbolic-ref', '-q', '--short', 'HEAD', allow_failure=True)
    porcelain = git(repo, 'status', '--porcelain=v1', '-z', '--untracked-files=all', timeout=120)
    dirty, count, each = _dirty_digest(repo, porcelain)
    stash = git(repo, 'stash', 'list', '--format=%H', allow_failure=True) or b''
    refs = {}
    for line in (git(repo, 'for-each-ref', '--format=%(refname) %(objectname)', 'refs/heads', 'refs/tags') or b'').decode().splitlines()[:20000]:
        name, _, sha = line.rpartition(' ')
        refs[name] = sha
    return {'head': head, 'branch': branch.decode().strip() if branch else None, 'dirty_digest': dirty, 'dirty_entries': count,
            'dirty_paths': each,
            'stash_digest': hashlib.sha256(stash).hexdigest(), 'stash_entries': len(stash.split()), 'refs_digest': content_hash(refs),
            'refs': refs}


def preserved(repo, before, created_refs=(), applied=()):
    """Findings (empty = preserved): checkout, HEAD, uncommitted source, stash and existing refs versus the pins.
    created_refs: refs OneCrew created with verified receipts. applied: the exact paths a verified apply wrote; only those
    are exempt here (the caller checks their content against the verified candidate), never the whole checkout."""
    after = pins(repo)
    findings = []
    if after['branch'] != before['branch']: findings.append(f"checked-out branch changed: {before['branch']} -> {after['branch']}")
    if after['head'] != before['head']: findings.append(f"HEAD moved: {before['head'][:12]} -> {after['head'][:12]}")
    exempt = set(applied or ())
    if not exempt:
        if after['dirty_digest'] != before['dirty_digest']:
            findings.append(f"uncommitted source changed ({before['dirty_entries']} -> {after['dirty_entries']} dirty paths)")
    elif 'dirty_paths' not in before:  # pinned by an older runtime: nothing can be exempted per path
        findings.append('uncommitted source cannot be compared per path (pinned before per-path pins); review the checkout')
    else:
        old, new = before['dirty_paths'], after['dirty_paths']
        changed = sorted(p for p in set(old) | set(new) if p not in exempt and old.get(p) != new.get(p))
        if changed: findings.append('uncommitted source changed outside the applied files: ' + ', '.join(changed[:10]))
    if after['stash_digest'] != before['stash_digest']: findings.append(f"stash changed ({before['stash_entries']} -> {after['stash_entries']})")
    created = set(created_refs)
    for name, sha in before['refs'].items():
        if after['refs'].get(name) != sha: findings.append('existing ref changed or deleted: ' + name)
    for name in set(after['refs']) - set(before['refs']):
        if name not in created: findings.append('ref created outside OneCrew receipts: ' + name)
    return findings, {k: v for k, v in after.items() if k not in ('refs', 'dirty_paths')}


def summary(contract):
    """What the worker and reviewer see: the user's terms verbatim, plus the invariants the core enforces itself."""
    a = contract['authority']
    enforced = ['The user checkout, index, uncommitted source, stash and existing refs are never changed'
                + ('' if a['apply_to_project'] else ' (apply_to_project not granted: changes stay in the isolated workspace)'),
                'Existing refs are never overwritten; no push, tag, merge, deploy or device/server action is available',
                'Existing test files are immutable' if not a['edit_tests'] else 'Edited tests are compared for removed assertions/skips',
                ("Commands run with the user's normal rights (unconfined_commands granted)" if a.get('unconfined_commands') else
                 'Commands are contained: the OS lets them write only inside the isolated workspace, its temp and cache'),
                'Only workspace changes within edit authority and scope.paths can be committed, exported, applied or handed over, '
                'whichever tool or command made them']
    return {'goal': contract['goal'], 'scope': contract['scope'], 'preserve': contract['preserve'],
            'acceptance': contract['acceptance'], 'checks': contract['checks'], 'authority': a,
            'enforced_by_core': enforced, 'authorized_by': contract['authorized_by']}


def load(path):
    try: return json.loads(Path(path).read_text(encoding='utf-8-sig'))
    except (OSError, ValueError) as error: raise LedgerError('Work contract unreadable: ' + str(error)[:200])


def revision(contract):
    return content_hash(json.loads(canonical(contract)))
