"""W48a / W48b (R02) — context written while working, and its retrieval, by ONE mechanism.

Storage: the event `context.entry` (class A of the event-type ledger, 00 §6.1) on the root's anchor. No table, no schema change: the old version never
reads it (S/G/C unchanged). Every entry has a SOURCE that resolves (file:line@revision, a symbol at a revision, a receipt blob, an event id of this
ledger) and exactly one of five labels: observed / hypothesis / verified / stale / refuted.

Writing rule (W48a): the worker (or the entry) reports its operations to `observe`; only four kinds are significant — a decision, a symbol verified,
a hypothesis refuted, a task done — and only those are written. Anything else is dropped. The same content is written once (id = hash of the
content); a change of label on the same subject (same `key`) is a new entry that replaces the earlier one on retrieval. Pure code: no model, ever.

Retrieval (W48b): `retrieve(scope='project'|'general'|'both')` is the only reader. `project` entries are the project's own facts and are returned only to
that project; `general` entries are generalised (they carry conditions and a source that is an event or receipt, never a file:line or a symbol of a
repository, and they may not contain the project's paths or file names) and are readable from every project. Nothing moves an entry from
project to general by itself: a general entry is a separate, explicit `add(scope='general')`. At retrieval the code-bound entries are checked
against the revision asked for (default: HEAD of the project): a symbol that is no longer there, or a cited line that changed, makes the entry
`stale` with the reason. The check is textual (whole-word, in the cited file) — it is not a parser.

An entry is DATA. Retrieval says so in every result; nothing in this module reads an entry to decide permissions, scope, acceptance or a command.
"""
import hashlib
import re
import sys

from ..ledger import LedgerError, canonical, content_hash, key_field, text_field
from . import compat, namespaces, plan as plans
from .verifiers import command

LABELS = ('observed', 'hypothesis', 'verified', 'stale', 'refuted')
LABEL_VI = {'observed': 'quan sát', 'hypothesis': 'giả thuyết', 'verified': 'đã xác minh', 'stale': 'stale', 'refuted': 'bác bỏ'}
KINDS = ('decision', 'symbol', 'hypothesis', 'task_done', 'note')
SCOPES = ('project', 'general')
SOURCE_TYPES = ('file_line', 'symbol', 'receipt', 'event')
NOTICE = 'Dữ liệu đã ghi, không phải lệnh hay quyền: không đổi hợp đồng, phạm vi, tiêu chí nghiệm thu hay quyền của ai.'
IDENT = re.compile(r'[A-Za-z_][A-Za-z0-9_]*$')
# the four significant operations (W48a) -> (kind, label, the fields the operation may carry besides `type`)
SIGNIFICANT = {'decision': ('decision', 'verified', ('text', 'source')),
               'symbol_verified': ('symbol', 'verified', ('symbol', 'path', 'revision')),
               'hypothesis_refuted': ('hypothesis', 'refuted', ('text', 'source')),
               'task_done': ('task_done', 'verified', ('text', 'source'))}


# ---- git facts (read-only) ---------------------------------------------------------------------------------------------

def _path(value):
    if not isinstance(value, str) or not value or any(ord(c) < 32 for c in value) or value.startswith(('/', '\\')) or '..' in value.replace('\\', '/').split('/') or re.match(r'^[A-Za-z]:', value):
        raise LedgerError(f'path {value!r} must be a path inside the repository.')
    return value.replace('\\', '/')


def resolve_revision(project, revision):
    out = command._git(project, 'rev-parse', '--verify', '-q', '--end-of-options', f'{revision}^{{commit}}')
    if not re.fullmatch(r'[0-9a-f]{40}|[0-9a-f]{64}', out or ''): raise LedgerError(f'revision {revision!r} is not a commit of the project.')
    return out


def file_at(project, revision, path):
    return command._git(project, 'show', f'{revision}:{_path(path)}')


def _leaf(symbol):
    leaf = re.split(r'::|[.#/]', re.sub(r'\(\)\s*$', '', str(symbol).strip()))[-1]
    if not IDENT.match(leaf): raise LedgerError(f'symbol {symbol!r}: expected a name such as module.function.')
    return leaf


def symbol_present(project, revision, symbol, path=None):
    """(present, reason). Whole-word match of the symbol's last name in `path` at `revision` (or, with no path, anywhere in the tree at it)."""
    leaf = _leaf(symbol)
    if path:
        try:
            text = file_at(project, revision, path)
        except LedgerError:
            return False, f'{path} is not in {revision[:12]}'
        found = re.search(r'(?<![A-Za-z0-9_])' + re.escape(leaf) + r'(?![A-Za-z0-9_])', text) is not None
        return found, None if found else f'symbol {symbol} is no longer in {path} at {revision[:12]}'
    try:
        command._git(project, 'grep', '-l', '-w', '-F', '-e', leaf, revision)
        return True, None
    except LedgerError:
        return False, f'symbol {symbol} is nowhere in the tree at {revision[:12]}'


def _line_hash(text, line):
    lines = text.splitlines()
    return hashlib.sha256(lines[line - 1].strip().encode('utf-8')).hexdigest() if 1 <= line <= len(lines) else None


# ---- sources -----------------------------------------------------------------------------------------------------------

def _resolve_source(ledger, source, scope):
    """(normalised source, source_text, revision_ref, line_hash). Raises LedgerError when the source does not resolve."""
    if not isinstance(source, dict) or source.get('type') not in SOURCE_TYPES:
        raise LedgerError('an entry needs a source: file_line, symbol, receipt or event.')
    kind = source['type']
    if kind == 'event':
        ident = source.get('id')
        if type(ident) is not int or ident < 1: raise LedgerError('event source: expected the numeric id of an event of this ledger.')
        with ledger.transaction() as conn:
            row = conn.execute('SELECT e.seq FROM events e JOIN tasks t ON t.id=e.task_id WHERE e.seq=? AND t.project_id=?',
                               (ident, ledger.project_id)).fetchone() if conn else None
        if row is None: raise LedgerError(f'event {ident} does not exist in this ledger' + (' (for this project)' if scope == 'project' else '') + '.')
        return {'type': 'event', 'id': ident}, f'event {ident}', None, None
    if kind == 'receipt':
        key = source.get('key')
        from ..snapshots import Snapshots
        try:
            Snapshots(ledger.state_root).read_blob(key)
        except Exception as error:
            raise LedgerError(f'receipt source: no such blob in this state root ({str(error)[:80]}).') from error
        return {'type': 'receipt', 'key': key}, f'receipt {str(key)[:16]}', None, None
    path = _path(source.get('path'))
    commit = resolve_revision(ledger.project, source.get('revision') or '')
    if kind == 'file_line':
        line = source.get('line')
        if type(line) is not int or line < 1: raise LedgerError('file_line source: expected a line number.')
        text = file_at(ledger.project, commit, path)
        digest = _line_hash(text, line)
        if digest is None: raise LedgerError(f'file_line source: {path} has no line {line} at {commit[:12]}.')
        return {'type': 'file_line', 'path': path, 'line': line, 'revision': commit}, f'{path}:{line}@{commit[:12]}', commit, digest
    name = source.get('name')
    present, why = symbol_present(ledger.project, commit, name, path)
    if not present: raise LedgerError(f'symbol source: {why}.')
    return {'type': 'symbol', 'name': name, 'path': path, 'revision': commit}, f'{name} in {path}@{commit[:12]}', commit, None


def _private_reasons(ledger, texts):
    """Why a general entry may not carry these texts: the project's own paths and file names. [] when it is clean."""
    joined = '\n'.join(texts)
    reasons = []
    for token in {str(ledger.project), str(ledger.project).replace('\\', '/'), ledger.project_path, ledger.project_id, str(ledger.state_root)}:
        if token and token.casefold() in joined.casefold(): reasons.append(f'it names the project path or id ({token[:40]})')
    if re.search(r'[A-Za-z]:[\\/]|(?:^|\s)/(?:home|Users|mnt|var|opt|etc|srv)/', joined): reasons.append('it contains an absolute path')
    try:
        files = set(command._git(ledger.project, 'ls-files').splitlines())
        files |= {p.rsplit('/', 1)[-1] for p in files}
    except LedgerError:
        files = set()
    words = set(re.findall(r'[\w./\\-]+', joined.replace('\\', '/')))
    words |= {w.strip('.,;:!?()') for w in words}                      # "service.py." at the end of a sentence is still the file name
    leaked = sorted(w for w in words if w and w in files)
    if leaked: reasons.append('it names files of the project: ' + ', '.join(leaked[:3]))
    return reasons


# ---- write -------------------------------------------------------------------------------------------------------------

class ContextConflict(LedgerError):
    """An update based on an older version of the subject (2.3-A2): `current` is the id of the newer entry it would have hidden."""
    def __init__(self, message, current):
        super().__init__(message)
        self.current = current


def add(ledger, name, *, kind, label, text, source, scope='project', conditions=None, key=None, extra=None, expect_latest=None,
        subject_scope='root', require_open=False, lifecycle_target=None):
    """Write one `context.entry` on the root `name`. Returns {'recorded': bool, 'id', 'key', 'event'}; a repeat of the same content is not written.
    2.3-A2: `extra` (a dict built and validated by knowledge.py) is stored as the payload's `knowledge`; `expect_latest` ('' = no earlier
    entry expected) makes the write refuse with ContextConflict when the subject's newest entry is not that id; `subject_scope='project'`
    looks for that newest entry across the project's roots (a project-visible subject), 'root' on this root only. A write identical to the
    subject's newest version is not written again; a write identical to an OLDER version (a revert) is. `require_open` refuses a root
    that has ended, checked in the same write transaction (2.3 review r1 #24)."""
    if label not in LABELS: raise LedgerError(f'label {label!r}: expected one of {", ".join(LABELS)}.')
    if kind not in KINDS: raise LedgerError(f'kind {kind!r}: expected one of {", ".join(KINDS)}.')
    if scope not in SCOPES: raise LedgerError(f'scope {scope!r}: expected project or general.')
    text_field(text, 'text', 600)
    with ledger.transaction() as conn:
        root = namespaces.resolve(ledger, conn, name)
        if root is None: raise LedgerError(f'No plan named {name}.')
        root_id, selector = root['id'], root['request_key']
    bare = namespaces.parse(selector)[0]
    src, source_text, revision_ref, line_hash = _resolve_source(ledger, source, scope)
    if kind == 'symbol' and src['type'] != 'symbol': raise LedgerError('a symbol entry is sourced by the symbol check itself (source type symbol).')
    if scope == 'general':
        if not isinstance(conditions, list) or not 1 <= len(conditions) <= 20 or not all(isinstance(c, str) and c.strip() and len(c) <= 500 for c in conditions):
            raise LedgerError('a general entry states the conditions it holds under (a non-empty list).')
        if src['type'] not in ('event', 'receipt'):
            raise LedgerError('a general entry cites an event or a receipt, not a file or a symbol of one repository.')
        private = _private_reasons(ledger, [text, *conditions])
        if private: raise LedgerError('a general entry keeps no private detail of the project: ' + '; '.join(private) + '.')
    elif conditions is not None: raise LedgerError('conditions belong to a general entry.')
    symbol = {'name': src['name'], 'path': src['path']} if src['type'] == 'symbol' else None
    subject = ('symbol', src['name']) if symbol else (kind, ' '.join(text.casefold().split()))
    key = key_field(key) if key else content_hash([scope, root_id if scope == 'project' else conditions, *subject])[:24]
    body = {'version': 1, 'key': key, 'scope': scope, 'project': ledger.project_id, 'plan': bare, 'plan_anchor': selector, 'kind': kind, 'label': label, 'text': text,
            'source': src, 'source_text': source_text, 'symbol': symbol, 'revision_ref': revision_ref, 'line_hash': line_hash,
            'conditions': conditions}
    if extra is not None:
        if not isinstance(extra, dict) or len(canonical(extra)) > 12000: raise LedgerError('knowledge fields: an object of at most 12000 characters.')
        body['knowledge'] = extra
    body['id'] = content_hash(body)
    with ledger.transaction(write=True) as conn:
        row = namespaces.resolve(ledger, conn, selector)
        if row is None: raise LedgerError(f'No plan named {name}.')
        if subject_scope == 'project':
            newest = conn.execute("SELECT json_extract(e.payload,'$.id') AS id FROM events e JOIN tasks t ON t.id=e.task_id WHERE t.project_id=? "
                                  "AND e.kind='context.entry' AND json_extract(e.payload,'$.key')=? AND json_extract(e.payload,'$.scope')=? "
                                  "AND json_extract(e.payload,'$.knowledge.visibility')='project' ORDER BY e.seq DESC LIMIT 1",
                                  (ledger.project_id, key, scope)).fetchone()
        else:
            newest = conn.execute("SELECT json_extract(payload,'$.id') AS id FROM events WHERE task_id=? AND kind='context.entry' "
                                  "AND json_extract(payload,'$.key')=? ORDER BY seq DESC LIMIT 1", (row['id'], key)).fetchone()
        current = newest['id'] if newest else ''
        if current == body['id']:
            return {'recorded': False, 'id': body['id'], 'key': key, 'event': None}
        life = None
        if expect_latest is not None and lifecycle_target:
            # 2.3 review r2 N13 / r3 R3-3: a withdrawal or an archive is the newest state of the subject when it is newer than its newest version;
            # an update must be based on that state (its record) — one based on an older version conflicts
            life = conn.execute("SELECT e.seq, json_extract(e.payload,'$.id') AS id FROM tasks t JOIN events e ON e.task_id=t.id WHERE t.project_id=? "
                                "AND e.kind='context.entry' AND (json_extract(e.payload,'$.knowledge.withdraws')=? OR json_extract(e.payload,'$.knowledge.archives')=?) "
                                "ORDER BY e.seq DESC LIMIT 1", (ledger.project_id, lifecycle_target, lifecycle_target)).fetchone()
            newest_seq = conn.execute("SELECT MAX(e.seq) AS seq FROM tasks t JOIN events e ON e.task_id=t.id WHERE t.project_id=? AND e.kind='context.entry' "
                                      "AND json_extract(e.payload,'$.id')=?", (ledger.project_id, current)).fetchone()['seq'] if current else None
            if life is not None and (newest_seq is None or life['seq'] > newest_seq):
                if expect_latest != life['id']:
                    raise ContextConflict(f'subject {key} was withdrawn or archived after version {expect_latest[:12] or "(none)"}; base an update on that record', life['id'])
            else:
                life = None
        if expect_latest is not None and life is None and current != expect_latest:
            raise ContextConflict(f'subject {key} changed since version {expect_latest[:12] or "(none)"}: the newest is {current[:12]}', current)
        state = plans.derive(ledger, conn, selector)
        if require_open and state and state.get('status') in ('accepted', 'stopped_with_report', 'closed'):
            raise LedgerError('Record knowledge before the root ends: this root has ended (' + state['status'] + ').')
        payload = dict(body, plan_revision=state['latest'] if state else None, root=row['id'])
        plans.emit(ledger, conn, row['id'], 'context.entry', payload)                 # the class-A guard of compat.check_write runs here
        event = conn.execute('SELECT last_insert_rowid()').fetchone()[0]
    return {'recorded': True, 'id': body['id'], 'key': key, 'event': event}


def observe(ledger, name, op):
    """One operation of the worker. Writes an entry only for the four significant kinds; any other operation is dropped (not written, no model)."""
    kind = op.get('type') if isinstance(op, dict) else None
    if kind not in SIGNIFICANT: return {'recorded': False, 'reason': 'not_significant'}
    entry_kind, label, allowed = SIGNIFICANT[kind]
    extra = set(op) - {'type', *allowed}
    if extra: raise LedgerError(f'{kind}: unknown field(s) {", ".join(sorted(extra))}; the label and kind come from the operation, never from the operation\'s data.')
    if kind == 'symbol_verified':
        source = {'type': 'symbol', 'name': op.get('symbol'), 'path': op.get('path'), 'revision': op.get('revision')}
        return add(ledger, name, kind='symbol', label=label, text=f'{op.get("symbol")} exists in {op.get("path")}', source=source)
    return add(ledger, name, kind=entry_kind, label=label, text=op.get('text'), source=op.get('source'))


# ---- retrieval ---------------------------------------------------------------------------------------------------------

class FileCache:
    """`file_at` once per (revision, path) within one retrieval: a store of thousands of code-bound entries cites few files, and one git
    process per entry made retrieval cost grow with the store (2.3-A1, KS-01). The cache lives for one call; nothing is kept across calls."""
    def __init__(self, project):
        self.project, self.texts = project, {}

    def file_at(self, revision, path):
        key = (revision, path)
        if key not in self.texts:
            try:
                self.texts[key] = (file_at(self.project, revision, path), None)
            except LedgerError as error:
                self.texts[key] = (None, error)
        text, error = self.texts[key]
        if error is not None: raise error
        return text

    def symbol_present(self, revision, symbol, path=None):
        if not path: return symbol_present(self.project, revision, symbol, path)
        leaf = _leaf(symbol)
        try:
            text = self.file_at(revision, path)
        except LedgerError:
            return False, f'{path} is not in {revision[:12]}'
        found = re.search(r'(?<![A-Za-z0-9_])' + re.escape(leaf) + r'(?![A-Za-z0-9_])', text) is not None
        return found, None if found else f'symbol {symbol} is no longer in {path} at {revision[:12]}'


def _stale_reason(ledger, payload, current, cache=None):
    """Why a code-bound entry no longer holds at commit `current` (None when it still does or is not code-bound)."""
    if payload['scope'] != 'project' or not payload.get('revision_ref') or payload['revision_ref'] == current: return None
    cache = cache or FileCache(ledger.project)
    symbol, source = payload.get('symbol'), payload['source']
    if symbol:
        present, why = cache.symbol_present(current, symbol['name'], symbol.get('path'))
        if not present: return f'{why} (verified at {payload["revision_ref"][:12]})'
    if source['type'] == 'file_line':
        try:
            text = cache.file_at(current, source['path'])
        except LedgerError:
            return f'{source["path"]} is not in {current[:12]} (cited at {payload["revision_ref"][:12]})'
        if _line_hash(text, source['line']) != payload.get('line_hash'):
            return f'line {source["line"]} of {source["path"]} changed since {payload["revision_ref"][:12]}'
    return None


def _rows(ledger, conn, scope, task_id=None):
    """The context.entry rows a retrieval of `scope` can use, filtered in SQL: the project's own (through the tasks of this project and
    the events_task index) and/or the general ones. The same set the former full scan kept after its Python filter, ordered by seq."""
    rows = []
    if scope in ('project', 'both'):
        query = ("SELECT e.seq, e.created_at, e.payload, e.task_id, t.project_id FROM tasks t JOIN events e ON e.task_id=t.id "
                 "WHERE t.project_id=? AND e.kind='context.entry'" + (' AND t.id=?' if task_id else ''))
        rows += conn.execute(query, (ledger.project_id, task_id) if task_id else (ledger.project_id,)).fetchall()
    if scope in ('general', 'both'):
        seen = {row['seq'] for row in rows}
        rows += [row for row in conn.execute("SELECT e.seq, e.created_at, e.payload, e.task_id, t.project_id FROM events e JOIN tasks t ON t.id=e.task_id "
                                             "WHERE e.kind='context.entry' AND json_extract(e.payload,'$.scope')='general'").fetchall()
                 if row['seq'] not in seen]
    return sorted(rows, key=lambda row: row['seq'])


def retrieve(ledger, *, plan=None, scope='both', revision=None, limit=200, raw=False):
    """The entries a task may use, from both scopes by one function. `plan` narrows the project scope to that root. Newest state per subject (`key`).
    `limit=None` (2.3-A1, knowledge.py only) returns every entry, never the newest N: choosing by task, permission and relevance is knowledge.py's
    job, not "the latest 200"; `raw=True` adds the stored payload (with its task) for that choice."""
    if scope not in ('project', 'general', 'both'): raise LedgerError('scope: project, general or both.')
    if limit is not None and (type(limit) is not int or not 1 <= limit <= 1000): raise LedgerError('limit: integer 1-1000.')
    with ledger.transaction() as conn:
        selected = namespaces.resolve(ledger, conn, plan) if plan is not None else None
        if plan is not None and selected is None: raise LedgerError(f'No plan named {plan}.')
        rows = _rows(ledger, conn, scope, selected['id'] if selected is not None and scope == 'project' else None) if conn else []
    import json
    latest = {}
    for row in rows:
        p = json.loads(row['payload'])
        mine = p.get('scope') == 'project' and row['project_id'] == ledger.project_id and p.get('project') == ledger.project_id
        shared = p.get('scope') == 'general' and p.get('conditions') and p.get('source', {}).get('type') in ('event', 'receipt')
        if not (mine and scope in ('project', 'both') or shared and scope in ('general', 'both')): continue
        if mine and selected is not None and row['task_id'] != selected['id']: continue
        latest[(p['scope'], row['project_id'], row['task_id'] if mine else None, p['key'])] = dict(p, event=row['seq'], at=row['created_at'], task=row['task_id'])
    current, problem = None, None
    if any(p['scope'] == 'project' and p.get('revision_ref') for p in latest.values()):
        try:
            current = resolve_revision(ledger.project, revision or 'HEAD')
        except (LedgerError, OSError) as error:
            problem = str(error)[:160]
    entries, cache = [], FileCache(ledger.project)
    ordered = sorted(latest.values(), key=lambda x: x['event'])
    for p in (ordered[-limit:] if limit else ordered):
        label, reason = p['label'], None
        if p['scope'] == 'project' and p.get('revision_ref') and label in ('observed', 'verified'):
            if problem: label, reason = 'stale', f'cannot be checked now: {problem}'
            else:
                reason = _stale_reason(ledger, p, current, cache)
                if reason: label = 'stale'
        entries.append({'event': p['event'], 'id': p['id'], 'key': p['key'], 'scope': p['scope'], 'plan': p.get('plan') if p['scope'] == 'project' else None,
                        'kind': p['kind'], 'label': label, 'label_vi': LABEL_VI[label], 'stored_label': p['label'], 'text': p['text'], 'source': p['source'],
                        'source_text': p['source_text'], 'symbol': p.get('symbol'), 'conditions': p.get('conditions'), 'stale_reason': reason,
                        'plan_revision': p.get('plan_revision'), 'at': p['at'], 'is_instruction': False,
                        **({'payload': p} if raw else {})})
    from . import lessons
    entries = lessons.refine_context(ledger, entries, revision or current)
    return {'data_not_authority': True, 'notice': NOTICE, 'scope': scope, 'plan': plan, 'checked_at': current, 'entries': entries}


def for_pack(ledger, name):
    """The entries of one root for the resume pack (project scope, checked at HEAD), judged like a knowledge package (Codex P2-01).
    2.3-A2: an entry the knowledge lifecycle has withdrawn, archived or superseded (or a summary derived from one) is not shown as live
    context (the ledger keeps it: `wiki history`); lifecycle records themselves are not context."""
    return judged(ledger, retrieve(ledger, plan=name, scope='project', raw=True)['entries'], drop_lifecycle=True)


def judged(ledger, entries, *, drop_lifecycle=False, revision=None, plan=None):
    """`entries` (retrieve(raw=True)) as an agent continuing their roots may read them: knowledge.for_root decides, per root (by task
    id, review r1 F9; one reading of the wiki and the ledger for all roots, F17), what the knowledge package decides — gone (withdrawn,
    archived, superseded, derived from such) is left out; an entry whose pinned file or source changed, that does not apply now, that
    another root replaced (F7) or (a 2.3 record) that cannot be checked is `stale` with the reason, never `verified`. A general record is
    judged the same way for the reader `plan` (the root of --plan; None: the project without a root), its lifecycle by the project that
    wrote it (F8; Codex dev3 review P2: not by the lifecycle alone). `revision`: applicability is judged on that commit's files (F12,
    r2 R2-01). When the judgement fails, gone knowledge is still left out and every other 2.3 record is `stale` (F10); a 2.2 entry keeps
    its label (R2-09). Entries that are not knowledge (engine bookkeeping) are kept as recorded; the payload is dropped."""
    from . import knowledge
    memo, verdicts, failed = {}, {}, {}
    for root in sorted({(e.get('payload') or {}).get('task') or e.get('task') for e in entries if e['scope'] == 'project'} - {None}):
        try:
            verdicts[root] = knowledge.for_root(ledger, root, memo=memo, revision=revision)
        except Exception as error:                     # the reader never fails the pack; an unjudged entry is not shown as current
            failed[root] = f'knowledge state not checked ({type(error).__name__}: {str(error)[:120]})'
    general, general_failed = {}, None
    if any(e['scope'] == 'general' for e in entries):
        try:
            general = knowledge.for_root(ledger, plan, memo=memo, revision=revision)   # the root of `plan` is reused from the memo
        except Exception as error:
            general_failed = f'knowledge state not checked ({type(error).__name__}: {str(error)[:120]})'
    status = {}
    if failed or any(e['scope'] == 'general' for e in entries):
        try:
            status = knowledge.status_by_id(ledger)    # lifecycle only: what is gone whatever the selection can say (F8, F10)
        except Exception:
            status = {}
    out, tags, lessons_by_key = [], knowledge.project_tags(ledger), knowledge.lesson_index(ledger)
    for entry in entries:
        payload = entry.pop('payload', None) or {}
        extra = payload.get('knowledge') if isinstance(payload.get('knowledge'), dict) else {}
        if extra.get('withdraws') or extra.get('archives'):
            if drop_lifecycle: continue
            out.append(entry); continue
        root = payload.get('task') or entry.get('task')
        visibility = extra.get('visibility') or ('project' if entry['key'].startswith('lesson-') else 'root')
        ident = knowledge.ledger_id(entry['key'], visibility, root, payload.get('project'), ledger.project_id, tags.get(payload.get('project')),
                                    lesson=knowledge.is_lesson_entry(entry['key'], extra, entry.get('source') or payload.get('source'), lessons_by_key))   # P2-B, R7-06
        shared = entry['scope'] == 'general'
        verdict = general.get(ident) if shared else verdicts.get(root, {}).get(ident)
        other = None
        if shared:
            if status.get(ident, 'active') != 'active':    # review dev4 F1: what the project's lifecycle says is gone stays gone, also
                continue                                    # for a reader that cannot use the superseder (no --plan: no paths)
            if verdict is not None and verdict.get('version') not in (None, entry['id']):
                other, verdict = verdict, None              # F2/F3: the decision judged another record that has the same knowledge id
        elif verdict is not None and verdict.get('scope') == 'general':
            other, verdict = verdict, None                  # r03 mirrored: a shared record with this id is not this project entry
        reason = None
        if verdict is not None:
            if verdict['gone']: continue
            reason = verdict['stale']
            if not shared and verdict['root'] != root and verdict['event'] <= entry['event']: reason = None   # the newest version itself
        elif status.get(ident, 'active') != 'active':
            continue
        elif (shared or other) and extra and entry['label'] in ('observed', 'verified', 'refuted'):   # a 2.3 record the judgement did not
            reason = (f'not judged: another record (event {other["event"]}) has the same knowledge id {ident}; `onecrew wiki history` '
                      'lists both' if other else general_failed or 'knowledge state not checked (not judged for this reader)')   # never current
        elif root in failed and extra and entry['label'] in ('observed', 'verified', 'refuted'):   # r2 R2-09: a 2.2 entry is judged on
                                                                                                    # lifecycle only, and that is known
            reason = failed[root]
        if reason and entry['label'] != 'stale':
            entry.update(label='stale', label_vi=LABEL_VI['stale'], stale_reason=reason)
        out.append(entry)
    return out


def note_error(error):
    print('Context not recorded: ' + ' '.join(f'{type(error).__name__}: {error}'.split()), file=sys.stderr)
