"""QC intake: a candidate branch built outside OneCrew, checked before any call is spent.

`intake` pins what is being judged (the ref, the project HEAD it must sit on, the author's report). `scope_check` compares
the candidate's diff with the recipe's `owned`/`tests` and returns EVERY reason it cannot be accepted, never only the
first. Both return reason lists instead of raising; nothing here writes to the project.
"""
import hashlib
from pathlib import Path

from .ledger import LedgerError
from .work_contract import git


MAX_FILE = 2_000_000          # as native_change.MAX_PATCH_FILE: per file
MAX_DIFF_PATHS = 200          # bound the analysis of an absurd diff; the reason is still recorded
MAX_REPORT_BYTES = 200_000
LINK_MODES = {'120000': 'symlink', '160000': 'submodule'}
STATUS_REASONS = {'D': 'deleted', 'R': 'renamed', 'T': 'type_changed', 'C': 'copied'}


def reason(code, detail, path=None):
    return {'code': code, 'path': path, 'detail': detail}


def _sha(data):
    return hashlib.sha256(data).hexdigest()


def _text(raw):
    return raw.decode('utf-8', errors='replace').strip() if raw else ''


def _commit(project, ref):
    """Commit id a ref names INSIDE the project's repository, or None. Anything not in this repository's object store
    (another repository's path or sha) does not resolve, which is the same-repository rule."""
    if not isinstance(ref, str) or not 0 < len(ref) <= 200 or ref.startswith('-') or any(c in ref for c in '\0\r\n'):
        return None
    done = git(project, 'rev-parse', '--verify', '--quiet', '--end-of-options', ref + '^{commit}', allow_failure=True)
    return _text(done) or None


def intake(project, ref, report=None, author=None):
    """Pin the candidate. `reasons` is empty only if the ref is a commit of this repository, the project HEAD is an ancestor
    of it (the candidate was built on the pinned base) and the report file, when given, is readable UTF-8 text."""
    project = Path(project)
    record = {'branch': ref, 'head': None, 'base': None, 'merge_base': None, 'author': author,
              'report': None, 'report_sha': None, 'reasons': []}
    reasons = record['reasons']
    base = _text(git(project, 'rev-parse', '--verify', 'HEAD', allow_failure=True))
    if not base:
        reasons.append(reason('project_not_a_repository', 'The project has no Git HEAD to compare with.'))
    record['base'] = base or None
    head = _commit(project, ref)
    if not head:
        reasons.append(reason('ref_unresolved', 'Not a commit of the project repository: ' + str(ref)[:120]))
    record['head'] = head
    if head and base:
        merge_base = _text(git(project, 'merge-base', base, head, allow_failure=True))
        record['merge_base'] = merge_base or None
        if merge_base != base:
            reasons.append(reason('base_not_head', 'The candidate is not built on the project HEAD ' + base[:12] +
                                  ' (merge-base ' + (merge_base[:12] or 'none') + ').'))
    if report is not None:
        try:
            data = Path(report).read_bytes()
        except OSError as error:
            reasons.append(reason('report_unreadable', 'Report file cannot be read: ' + type(error).__name__))
        else:
            record['report_sha'] = _sha(data)
            if len(data) > MAX_REPORT_BYTES:
                reasons.append(reason('report_too_large', 'Report exceeds ' + str(MAX_REPORT_BYTES) + ' bytes.'))
            else:
                try:
                    record['report'] = data.decode('utf-8-sig')
                except UnicodeError:
                    reasons.append(reason('report_not_utf8', 'Report is not UTF-8 text.'))
    return record


def _diff(project, base, head):
    """[(status, old_mode, new_mode, new_sha, path)] with repository-relative paths; renames carry the new path."""
    raw = git(project, 'diff', '--raw', '-z', '-M', '--no-abbrev', '--no-ext-diff', base, head, '--')
    parts = raw.split(b'\0')
    entries, index = [], 0
    while index < len(parts) and parts[index].startswith(b':'):
        meta = parts[index][1:].decode().split(' ')
        old_mode, new_mode, new_sha, status = meta[0], meta[1], meta[3], meta[4]
        paths = 2 if status[:1] in ('R', 'C') else 1
        names = [p.decode('utf-8', errors='surrogateescape') for p in parts[index + 1:index + 1 + paths]]
        entries.append((status[:1], old_mode, new_mode, new_sha, names[-1], names[0]))
        index += 1 + paths
    return entries


def scope_check(project, base, ref, recipe):
    """Reasons the candidate `base..ref` cannot be accepted, all of them. `base` is the commit the candidate was built on.
    Paths in `recipe['owned']` are relative to the project directory, which may sit below the repository root."""
    project = Path(project)
    reasons = []
    try:
        prefix = _text(git(project, 'rev-parse', '--show-prefix', allow_failure=True))
        owned = {prefix + p: p for p in recipe['owned']}
        tests = {prefix + p for p in recipe['tests']}
        entries = _diff(project, base, ref)
    except (LedgerError, ValueError, IndexError) as error:
        return [reason('diff_failed', 'The candidate diff cannot be read: ' + str(error)[:200])]
    if len(entries) > MAX_DIFF_PATHS:
        reasons.append(reason('too_many_files', 'The candidate changes ' + str(len(entries)) + ' paths (analysis stops at ' +
                              str(MAX_DIFF_PATHS) + ').'))
        entries = entries[:MAX_DIFF_PATHS]
    changed = set()
    for status, old_mode, new_mode, sha, path, old_path in entries:
        if status in STATUS_REASONS:
            reasons.append(reason(STATUS_REASONS[status], 'Status ' + status + ' is not accepted; only added or modified owned files.',
                                  path if status != 'R' else old_path))
        elif status not in ('A', 'M'):
            reasons.append(reason('unsupported_status', 'Unsupported change status ' + status + '.', path))
        if path not in owned:
            reasons.append(reason('path_outside_owned', 'Not an owned file of the recipe.', path))
        if status in STATUS_REASONS:
            continue
        changed.add(path)
        if new_mode in LINK_MODES:
            reasons.append(reason(LINK_MODES[new_mode], 'Links and submodules are not accepted.', path))
            continue
        if path not in owned:
            continue
        size = _text(git(project, 'cat-file', '-s', sha, allow_failure=True))
        if not size.isdigit():
            reasons.append(reason('blob_unreadable', 'The candidate blob cannot be read.', path))
        elif int(size) > MAX_FILE:
            reasons.append(reason('file_too_large', 'File is ' + size + ' bytes; the limit is ' + str(MAX_FILE) + '.', path))
        else:
            data = git(project, 'cat-file', 'blob', sha, allow_failure=True) or b''
            if b'\0' in data:
                reasons.append(reason('binary', 'Binary content is not accepted.', path))
            else:
                try:
                    data.decode('utf-8')
                except UnicodeError:
                    reasons.append(reason('non_utf8', 'Content is not UTF-8 text.', path))
    if not (changed & tests):
        reasons.append(reason('no_test_change', 'The candidate adds or changes none of the recipe tests: ' +
                              ', '.join(sorted(recipe['tests']))[:300]))
    if not any(p in owned and p not in tests for p in changed):
        reasons.append(reason('no_production_change', 'The candidate changes no production file.'))
    for name in sorted(tests):
        if _text(git(project, 'cat-file', '-t', ref + ':' + name, allow_failure=True)) != 'blob':
            reasons.append(reason('test_missing_at_ref', 'A recipe test does not exist in the candidate.', name))
    return reasons


def candidate_files(project, base, head, recipe):
    """[{'path','text'}] in the shape install_candidate takes: every added/modified file of `base..head` (relative to the
    project directory) plus every recipe test, read from the commit itself (`git cat-file`), never from a checkout."""
    project = Path(project)
    prefix = _text(git(project, 'rev-parse', '--show-prefix', allow_failure=True))
    names = {path[len(prefix):] for status, _, _, _, path, _ in _diff(project, base, head)
             if status in ('A', 'M') and path.startswith(prefix)}
    names |= set(recipe['tests'])
    files = []
    for name in sorted(names):
        data = git(project, 'cat-file', 'blob', head + ':' + prefix + name)
        files.append({'path': name, 'text': data.decode('utf-8')})
    return files


def evaluate(project, ref, recipe, report=None, author=None):
    """intake + scope_check as one record: `reasons` is the union of both lists."""
    record = intake(project, ref, report, author)
    if record['head'] and record['merge_base']:
        record['reasons'].extend(scope_check(project, record['merge_base'], record['head'], recipe))
    return record
