"""2.3-A1/A2 — what one consumer may use from the project's knowledge, chosen and delivered by code, never by a model; and (A2) how
knowledge is written with its evidence so that later work — new roots included — can use it again.

Two sources, one entry model (docs/v23/HOP-DONG-2.3.vi.md §3):
  * the project's wiki pages (wiki.pages / wiki.parse: Markdown sections, typed by an optional `onecrew` block);
  * the ledger's context entries (context.retrieve with limit=None; lessons refined: withdrawn ones are gone). A2 records are
    context.entry too (class A), with their fields under payload `knowledge`; there is no second store.

For a consumer — a root, and usually one node of it with its read/write files and the exact file contents its worker will see — every
candidate goes through, in order:
  1. permission: project boundary (general entries follow the old rule); an entry another root keeps as working memory
     (`visibility: root`) stays with that root; every file a source cites, every concrete `applies_to` file pinned with the record and
     every file of the scope the knowledge was learned in (`scope_paths`: the producing node's read ∪ write) must be readable by the
     consumer — otherwise the entry is not delivered and not named;
  2. lifecycle: withdrawn / archived / superseded entries, summaries derived from them and wiki copies of them are history. Only records
     the consumer may see act on it (another root's private note supersedes nothing for it; another project's record never acts), and a
     withdrawal reaches the versions written before it, not a correction written after it;
  3. applicability at the state the worker sees (MEM-01): a cited or pinned file whose blob differs from the one recorded makes the
     entry `recheck`; a checkable condition that is false makes it `not_applicable`; a condition, a symbolic revision, an event or a
     receipt that cannot be checked here makes it `unknown`. Nothing ages by a timer; an unchanged entry is used again as it is;
  4. use: verified + applies = `fact`; refuted + applies = `rejected`; everything else is a `lead`. A summary is never stronger than its
     weakest delivered source, contested and contradicted entries are leads, and a fact carries the property its evidence proved;
  5. relevance (files and words of the node and the plan) and the character cap, which bounds the WHOLE package: mandatory entries
     are never cut (do not fit -> KnowledgeOverflow, the caller stops before the model), optional ones fill the room, the rest is
     listed with a cursor. A mandatory constraint is never lost to a reading limit (Codex P2-02): a wiki section that declares itself
     mandatory and cannot be delivered (wiki.parse/pages `undelivered`), or a wiki too large to look through, stops the consumer it
     may concern before the model (KnowledgeIncomplete); optional pages that cannot be read are reported, never a reason to stop. The native adapter gives the package only the room the prompt cap leaves, so optional knowledge never blocks
     a node that ran before 2.3.

The package is DATA, not authority. `check_use` compares the worker's declaration with the delivery (structural); the node's checks
judge the result. Reading never writes (A1); writing (A2) happens only on an open root, at the strength of the evidence given.
"""
import base64
import fnmatch
import hashlib
import json
import math
import re
import sys
import time
from pathlib import Path

from ..ledger import LedgerError, canonical, content_hash, text_field
from . import context, namespaces, plan as plans, wiki
from .verifiers import command

VERSION = 2
NATIVE_CAP_CHARS = 16000          # the whole knowledge package of a native prompt; the prompt keeps its own cap (common_executor)
ENTRY_TEXT_CHARS = 1600           # text of one optional entry in a page; longer text is marked truncated and can be requested whole
INDEX_ROWS = 15
PROBLEM_ROWS = 10
MIN_CAP = 200
NOTICE = context.NOTICE
POLICY = ('facts: still applicable at this state; rely on them for what their evidence.property states (a cause is established only '
          'when evidence.cause says so); rejected: approaches already shown not to work here, do not retry them unless their conditions '
          'changed; leads: unverified, contested, historical or not checkable now, check the cited source before relying on them. '
          'Answer knowledge.used with the ids you relied on, knowledge.rejected with [{id, why}] for any entry you found wrong, '
          'knowledge.requests with omitted or truncated ids you need (only together with a continuation), and knowledge.new with what '
          'you found that is worth keeping ({kind, text, applies_to, sources: files you read, check: the id of the node check that proves '
          'it}); a claim stays an observation until that check passes.')
STOP = frozenset('the and for with that this from into are was were has have had not but you your our its their them then than there '
                 'what when which who will would should could can may might must also only just some any all each per via use used using '
                 'của và các những một cho với không được trong khi này đó là có thì đã sẽ để từ theo'.split())
KIND_WEIGHT = {'constraint': 3.0, 'decision': 2.0, 'rejected': 2.0, 'lesson': 2.0, 'finding': 1.5, 'summary': 1.0, 'note': 0.5}
USE_RANK = {'fact': 3, 'rejected': 2, 'lead': 1}
LIMITS = {'text': 600, 'claims': 20, 'id': 160, 'why': 1000, 'used': 200, 'requests': 20, 'rejected': 50, 'path': 300, 'paths': 20, 'sources': 10}
_STR = lambda n: {'type': 'string', 'minLength': 1, 'maxLength': n}
SCHEMA = {'type': 'object', 'additionalProperties': False, 'properties': {
    'new': {'type': 'array', 'maxItems': LIMITS['claims'], 'items': {'type': 'object', 'additionalProperties': False, 'required': ['kind', 'text'], 'properties': {
        'kind': {'type': 'string', 'enum': list(wiki.KINDS)}, 'text': _STR(LIMITS['text']),
        'applies_to': {'type': 'array', 'maxItems': LIMITS['paths'], 'items': _STR(LIMITS['path'])},
        'sources': {'type': 'array', 'maxItems': LIMITS['sources'], 'items': _STR(LIMITS['path'])},
        'check': _STR(LIMITS['id'])}}},
    'used': {'type': 'array', 'maxItems': LIMITS['used'], 'items': _STR(LIMITS['id'])},
    'rejected': {'type': 'array', 'maxItems': LIMITS['rejected'], 'items': {'type': 'object', 'additionalProperties': False, 'required': ['id', 'why'],
                                                                         'properties': {'id': _STR(LIMITS['id']), 'why': {'type': 'string', 'maxLength': LIMITS['why']}}}},
    'requests': {'type': 'array', 'maxItems': LIMITS['requests'], 'items': _STR(LIMITS['id'])}}}
FULL_COMMIT = wiki.FULL_COMMIT


class KnowledgeOverflow(LedgerError):
    """Mandatory knowledge does not fit the room: run nothing with partial constraints."""


class KnowledgeIncomplete(KnowledgeOverflow):
    """A mandatory constraint that may concern the consumer cannot be established (undeliverable or not looked through): run nothing."""


class KnowledgeNoRoom(LedgerError):
    """The cap leaves no room for any entry beside the package frame (and nothing is mandatory): deliver no knowledge, run on the inputs."""


# ---- the consumer ------------------------------------------------------------------------------------------------------------

def consumer(ledger, plan, *, node=None, pin=None):
    """Who reads: the project, the root, the node (its read ∪ write files) or, without a node, the files of the plan contract."""
    with ledger.transaction() as conn:
        if conn is None: raise LedgerError('No ledger in this state root.')
        root = namespaces.resolve(ledger, conn, plan)
        if root is None: raise LedgerError(f'No plan named {plan}.')
        state = plans.anchor_events(ledger, conn, root['request_key'])
    contract = plans.load(ledger, state)[0]
    outputs = contract.get('output') or []
    words = [contract.get('title') or '', (contract.get('understanding') or {}).get('restated_goal') or '', *outputs]
    if node:
        paths = sorted(set(node.get('read') or []) | set(node.get('write') or []))
        words += [node.get('goal') or '', *(node.get('output') or []), *[c.get('spec', '') for c in node.get('checks') or []]]
        pin = pin or node.get('executor')
    else:
        target = (contract.get('understanding') or {}).get('target') or {}
        paths = sorted(set(target.get('paths') or []) | set((contract.get('scope') or {}).get('owned') or []))
    return {'project': ledger.project_id, 'plan': root['request_key'], 'root': root['id'], 'node': node['id'] if node else None,
            'paths': [p.replace('\\', '/') for p in paths], 'terms': ' '.join(w for w in words if w), 'environment': _environment(pin)}


def _environment(pin=None):
    """What an `env` condition is checked against: this process, and the provider/model of a node's pin when there is one."""
    environment = {'platform': sys.platform, 'python': '%d.%d' % sys.version_info[:2]}
    if pin: environment.update(provider=pin.get('provider'), model=pin.get('model'))
    return environment


def _covers(pattern, path):
    pattern = pattern.replace('\\', '/')
    if pattern.endswith('/'): return path.startswith(pattern)
    if any(c in pattern for c in '*?['): return fnmatch.fnmatchcase(path, pattern)
    return path == pattern or path.startswith(pattern + '/')


def _readable(paths, path):
    return any(_covers(p, path) for p in paths)


def _concrete(paths):
    return [p for p in paths if p and not p.endswith('/') and not any(c in p for c in '*?[')]


# ---- the state the worker sees, read once per package ---------------------------------------------------------------------------

def blob_of(ledger, path, data):
    """The git blob id `data` would have as `path` (git applies the path's filters, as on commit)."""
    return command._git(ledger.project, 'hash-object', '--stdin', f'--path={path}', input=data) or None


class RevisionView:
    """The files of one commit as a worker view (review r2 R2-01: `context retrieve --revision`): every path is read from that commit,
    a path the commit does not hold is absent."""
    def __init__(self, project, commit):
        self.project, self.commit, self.cache = str(project), commit, {}

    def __contains__(self, path):
        return True

    def __getitem__(self, path):
        if path not in self.cache:
            import os
            import subprocess
            clean = {k: v for k, v in os.environ.items() if not k.upper().startswith('GIT_')}   # review r3 R3-03: the F8 rule of command._git
            done = subprocess.run(['git', '-C', self.project, 'cat-file', 'blob', f'{self.commit}:{path}'], capture_output=True, timeout=120,
                                  env=clean, creationflags=0x08000000 if os.name == 'nt' else 0)
            self.cache[path] = done.stdout if done.returncode == 0 else None
        return self.cache[path]


class _State:
    """File contents and blobs as the consumer's worker will see them: `view` (path -> text, the native prompt's source, or a
    RevisionView) first, the project working tree for any other file; ledger events and receipts of this state root for event/receipt
    sources. Cached."""
    def __init__(self, ledger, view=None):
        self.ledger, self.project = ledger, Path(ledger.project)
        self.view = view if isinstance(view, RevisionView) else dict(view or {})
        self.texts, self.revisions, self.blobs, self.events, self.receipts = {}, {}, {}, {}, {}

    def current(self, path):
        if path not in self.texts:
            if path in self.view:
                value = self.view[path]
                self.texts[path] = value.encode('utf-8') if isinstance(value, str) else value if isinstance(value, bytes) else None
            else:
                try:
                    self.texts[path] = (self.project / path).read_bytes()
                except OSError:
                    self.texts[path] = None
        return self.texts[path]

    def blob(self, path):
        key = ('now', path)
        if key not in self.blobs:
            data = self.current(path)
            try:
                self.blobs[key] = None if data is None else blob_of(self.ledger, path, data)
            except LedgerError:
                self.blobs[key] = None
        return self.blobs[key]

    def blob_at(self, revision, path):
        if revision not in self.revisions:
            try:
                self.revisions[revision] = context.resolve_revision(self.ledger.project, revision)
            except LedgerError:
                self.revisions[revision] = None
        commit = self.revisions[revision]
        if commit is None: raise LedgerError(f'revision {revision[:40]} does not resolve')
        key = ('at', commit, path)
        if key not in self.blobs:
            try:
                self.blobs[key] = command._git(self.ledger.project, 'rev-parse', '--verify', '-q', f'{commit}:{path}') or None
            except LedgerError:
                self.blobs[key] = None
        return self.blobs[key]

    def event_exists(self, ident, project=None):
        project = project or self.ledger.project_id         # (d) a general record's event is checked in the project that wrote it
        if (ident, project) not in self.events:
            with self.ledger.transaction() as conn:
                self.events[(ident, project)] = bool(conn and conn.execute('SELECT 1 FROM events e JOIN tasks t ON t.id=e.task_id WHERE e.seq=? AND t.project_id=?',
                                                                           (ident, project)).fetchone())
        return self.events[(ident, project)]

    def receipt_exists(self, key):
        if key not in self.receipts:                   # once per package (a cleanup may remove a receipt between packages)
            from ..snapshots import Snapshots
            try:
                Snapshots(self.ledger.state_root).read_blob(key); self.receipts[key] = True
            except (LedgerError, OSError, ValueError, TypeError):
                self.receipts[key] = False
        return self.receipts[key]


def _source_state(state, source, recorded_revision=None, project=None):
    """('unchanged'|'changed'|'unknown'|'ignored', reason) of one source against the state the worker sees."""
    kind = source.get('type')
    if kind == 'url': return 'ignored', None
    if kind == 'event':
        return ('unchanged', None) if state.event_exists(source.get('id'), project) else ('unknown', f'event {source.get("id")} is not in the ledger of its project')
    if kind == 'receipt':
        return ('unchanged', None) if state.receipt_exists(source.get('key')) else ('unknown', f'receipt {str(source.get("key"))[:16]} is not in this state root')
    path = source.get('path')
    if not path: return 'unknown', 'source without a path'
    now = state.blob(path)
    if source.get('blob'):
        if now is None: return 'changed', f'{path} no longer exists'
        return ('unchanged', None) if now == source['blob'] else ('changed', f'{path} changed since blob {source["blob"][:12]}')
    revision = source.get('revision') or recorded_revision
    if not revision: return 'unknown', f'{path}: no revision or blob recorded, the source cannot be checked'
    if not FULL_COMMIT.match(revision): return 'unknown', f'{path}: revision {revision[:40]} is symbolic (it always means "now"); pin a commit'
    try:
        then = state.blob_at(revision, path)
    except LedgerError as error:
        return 'unknown', f'{path}: {error}'
    if then is None and now is None: return 'unknown', f'{path} exists neither at {revision[:12]} nor now'
    if now is None: return 'changed', f'{path} no longer exists'
    if then is None: return 'unknown', f'{path} is not in {revision[:12]}'
    return ('unchanged', None) if then == now else ('changed', f'{path} changed since {revision[:12]}')


def _normalized_sha(data):
    return hashlib.sha256(data.replace(b'\r\n', b'\n')).hexdigest()


def _condition_state(state, condition, environment):
    kind = condition.get('type')
    if kind == 'file_contains':
        data = state.current(condition['path'])
        if data is None: return False, f'{condition["path"]} is absent'
        found = condition['text'] in data.decode('utf-8', 'replace')
        return found, None if found else f'{condition["path"]} no longer contains {condition["text"][:60]!r}'
    if kind == 'file_unchanged':
        data = state.current(condition['path'])                 # sha256 of the content with CRLF read as LF (a checkout's line ends never count)
        same = data is not None and condition['sha256'] in (_normalized_sha(data), hashlib.sha256(data).hexdigest())
        return same, None if same else f'{condition["path"]} differs from the recorded content'
    if kind == 'env':
        actual = environment.get(condition['key'])
        if actual is None: return None, f'{condition["key"]} is not known for this consumer'
        same = actual == condition['value'] or str(actual).startswith(condition['value'] + '.')
        return same, None if same else f'{condition["key"]} is {actual}, the entry holds for {condition["value"]}'
    return None, 'condition not checkable here: ' + str(condition.get('text', condition))[:120]


def _applicability(state, entry, environment):
    reasons, changed, unknown = [], False, False
    for condition in entry['conditions']:
        holds, why = _condition_state(state, condition, environment)
        if holds is False: return {'state': 'not_applicable', 'reasons': [why]}
        if holds is None: unknown = True; reasons.append(why)
    checkable = False
    for source in entry['sources']:
        verdict, why = _source_state(state, source, entry.get('recorded_revision'), entry.get('project'))
        if verdict == 'ignored': continue
        if verdict in ('unchanged', 'changed'): checkable = True
        if verdict == 'changed': changed = True; reasons.append(why)
        elif verdict == 'unknown': unknown = True; reasons.append(why)
    if entry.get('ledger_stale'): changed = True; reasons.append(entry['ledger_stale'])
    pinned = {s['path'] for s in entry['sources'] if s.get('path')}
    loose = [p for p in _concrete(entry['applies_to']) if p not in pinned]
    if loose:                                          # an entry about files whose content was never pinned cannot be told current
        unknown = True; reasons.append('applies to ' + ', '.join(loose[:3]) + ' with no pinned content')
    if not checkable and not entry['conditions'] and not changed:
        return {'state': 'unknown', 'reasons': [r for r in reasons if r] or ['no checkable source']}
    return {'state': 'recheck' if changed else 'unknown' if unknown else 'applies', 'reasons': [r for r in reasons if r]}


# ---- candidates ----------------------------------------------------------------------------------------------------------------

def _section_signature(entry):
    return canonical({k: entry.get(k) for k in ('kind', 'label', 'must', 'status', 'sources', 'conditions', 'applies_to', 'supersedes',
                                               'derived_from', 'ledger_id')} | {'text': ' '.join(str(entry.get('text', '')).split()),
                                                                                 'title': ' '.join(str(entry.get('title') or '').split())})


def _undelivered(entry, path, reason):
    return {'path': path, 'line': entry.get('line'), 'id': entry['id'], 'applies_to': list(entry.get('applies_to') or []),
            'source_paths': [s['path'] for s in entry.get('sources') or [] if s.get('path')], 'reason': reason}


def _concerns(item, cons):
    """Whether an undeliverable mandatory section may concern `cons`: the rule of `mandatory` (must, and it applies to the consumer's
    files or to no file in particular) with what is known of it; a section citing files the consumer may not read would not reach it."""
    sources = item.get('source_paths') or []
    if any(not _readable(cons['paths'], f) for f in sources): return False
    if not item.get('applies_to'): return True
    paths = list(item['applies_to']) + list(sources)
    return any(_covers(a, p) or _covers(p, a) for a in paths for p in cons['paths'])

UNKNOWN_TAG = '0' * 12
RESERVED_KEY_PREFIXES = ('lesson-',)   # a 2.3 record never takes a lesson's id (review dev6 R3)


def project_tags(ledger):
    """project id -> the mark of that project in knowledge ids: 12 hex characters of a hash of the project's FIRST task id in this ledger.
    Task ids are random, so the mark is stable but tells nothing about the project: a guessed path cannot be confirmed from it (review dev6
    R12; the project id itself is a hash of the path)."""
    with ledger.transaction() as conn:
        rows = conn.execute('SELECT project_id, id FROM tasks ORDER BY rowid').fetchall() if conn else []
    out = {}
    for row in rows:
        if row['project_id'] not in out:
            out[row['project_id']] = hashlib.sha256(('onecrew-knowledge-subject:' + str(row['id'])).encode('utf-8')).hexdigest()[:12]
    return out


def ledger_id(key, visibility=None, root=None, project=None, reader=None, tag=None, lesson=None):
    """The id a ledger subject is known by. A project-visible subject is one per project (`ctx-<key>`); a root's working memory is
    one per root (`ctx-<key>.r<root>`), so the two never stand for each other. A lesson keeps its logical id (`lesson-<id>`).
    Codex dev5 P2-B: a subject belongs to the project that wrote it. The reader's own subjects keep these ids; a general subject of
    ANOTHER project (`project` != `reader`) is `<id>@<tag>` (`tag`: project_tags): keys cannot hold '@', so it never stands for one of the
    reader's, and two projects that reuse a --key keep two subjects. `lesson`: the entry is a lesson of the lessons store (no 2.3
    knowledge fields); a 2.3 record whose key happens to start with `lesson-` follows the project rule too (review dev6 R3)."""
    if lesson is None: lesson = key.startswith('lesson-')
    other = bool(project and reader and project != reader)
    if key.startswith('lesson-') and (lesson or not other): return key
    if visibility == 'root' and root: return f'ctx-{key}.r{str(root)[-8:]}'
    base = key if key.startswith('lesson-') else 'ctx-' + key
    return f'{base}@{tag or UNKNOWN_TAG}' if other else base


def _in_reader_terms(ref, writer, reader, tag, lessons=False):
    """A ctx- id that project `writer` stored (a withdrawal or archive target, supersedes, derived_from, conflict_with, contradicts), as
    `reader` knows that subject: the writer named its own subject, so for another reader it is the writer's (P2-B). `lesson-` ids are left
    as written (a lesson of the lessons store keeps its id for every project, see _lesson_targets) unless `lessons`: conflict_with, which
    only knowledge.record writes, always names the writer's own 2.3 record (review dev6 D7)."""
    if not isinstance(ref, str) or '@' in ref or not writer or not reader or writer == reader: return ref
    if not (ref.startswith('ctx-') or (lessons and ref.startswith('lesson-'))): return ref    # D7: conflict_with names the writer's own record
    return f'{ref}@{tag or UNKNOWN_TAG}'


def _format_of(value):
    """The knowledge format of a stored record; anything that is not a whole number is read as an old record (review dev6 R11)."""
    return value if isinstance(value, int) and not isinstance(value, bool) else 0


FORMAT = 3          # knowledge payload format: 3 = references name subjects exactly (P2-B); <= 2 = written before, one namespace per key


LEGACY_FIELDS = ('derived_from', 'supersedes', 'contradicts')   # conflict_with always named the writer's own subject (review dev6 R5)


def _legacy_aliases(newest, versions, reader):
    """References in the reader's own records written before P2-B (format <= 2: a supersedes, derived_from or contradicts): `ctx-<key>`
    then stood for the newest record with that key the reader could see, its own or another project's general record. A reference to a key
    that another project also uses keeps that meaning: the subject among them whose newest version written before the referencing record
    is the newest, so a subject written after the reference cannot take it over. A reference to a key that no subject had before it is left
    as written: it names the reader's own subject of that key, as it did before P2-B (review dev6 R15)."""
    others = {}
    for ident, c in newest.items():
        if '@' in ident and c['scope'] == 'general': others.setdefault(ident.rsplit('@', 1)[0], []).append(ident)
    if not others: return
    for c in newest.values():
        if c.get('project') != reader or _format_of(c.get('format')) >= FORMAT: continue
        for field in LEGACY_FIELDS:
            resolved = []
            for ref in c[field]:
                pool = [i for i in [ref] + others.get(ref, []) if any(s < c['seq'] for s in versions.get(i, ()))]
                resolved.append(max(pool, key=lambda i: max(s for s in versions[i] if s < c['seq'])) if pool and ref in others else ref)
            c[field] = resolved


def _replaced_elsewhere(ledger, newest, reader):
    """Data written before the key rule (review dev6 D6): a project could keep a general and a project record under one key, one subject
    whose newest version wins. Another project's shared version that its project replaced with a newer version it did not share is not
    current for this reader: it is marked replaced, so every reader judges it superseded and `wiki history` keeps it (only its writer can
    see the newer version)."""
    shared = {(c['project'], c['origin'].get('key')): ident for ident, c in newest.items()
              if c['scope'] == 'general' and c.get('project') and c['project'] != reader and c['origin'].get('key')}
    if not shared: return
    with ledger.transaction() as conn:
        rows = conn.execute("SELECT t.project_id AS project, json_extract(e.payload,'$.key') AS key, MAX(e.seq) AS seq FROM tasks t JOIN events e "
                            "ON e.task_id=t.id WHERE t.project_id<>? AND e.kind='context.entry' AND json_extract(e.payload,'$.scope')='project' "
                            "AND json_extract(e.payload,'$.knowledge.visibility')='project' AND json_extract(e.payload,'$.knowledge.withdraws') IS NULL "
                            "AND json_extract(e.payload,'$.knowledge.archives') IS NULL GROUP BY t.project_id, key", (reader,)).fetchall() if conn else []
    for row in rows:
        ident = shared.get((row['project'], row['key']))
        if ident is not None and row['seq'] > newest[ident]['seq']: newest[ident]['replaced_by_owner'] = True


def _lesson_targets(newest, lifecycle, reader, tags):
    """A withdrawal or archive that another project wrote for one of ITS subjects with a `lesson-` key: a lesson of the lessons store keeps
    its id for everyone; a 2.3 record with such a key is `<key>@<tag>` for this reader (review dev6 R3)."""
    for record in lifecycle:
        writer = record.get('project')
        if not writer or writer == reader: continue
        for verb in ('withdraws', 'archives'):
            target = record.get(verb)
            if isinstance(target, str) and target.startswith('lesson-') and '@' not in target:
                qualified = f'{target}@{tags.get(writer) or UNKNOWN_TAG}'
                if qualified in newest and newest[qualified].get('project') == writer: record[verb] = qualified


def legacy_wiki_references(candidates, problems):
    """Wiki pages carry no format or time, so a plain `ctx-<key>` (or `lesson-<key>`) in a section is read in this project's namespace:
    it names this project's subject of that key; when the project has none and exactly one other project's general subject has that key,
    it names that one, as before P2-B; with several such subjects it names none. Every plain reference that another project's general
    record also matches is reported (`wiki pages` and packages) with what it names now and the id to write to keep it (review dev6 R6, D1,
    D2): a later write under the key can change what a plain reference names, never silently."""
    ledger_ids = {c['id'] for c in candidates if c['origin']['type'] == 'ledger'}
    others = {}
    for ident in ledger_ids:
        if '@' in ident: others.setdefault(ident.rsplit('@', 1)[0], []).append(ident)
    if not others: return
    for c in candidates:
        if c['origin']['type'] != 'wiki': continue
        for field in ('supersedes', 'derived_from', 'ledger_id'):
            refs = c[field] if field != 'ledger_id' else ([c['ledger_id']] if c['ledger_id'] else [])
            resolved = []
            for ref in refs:
                found = sorted(others.get(ref) or [])
                if not found: resolved.append(ref); continue
                if ref in ledger_ids: now, target = 'names the record of this project', ref
                elif len(found) == 1: now, target = f'names {found[0]} while this project has no record under that key', found[0]
                else: now, target = 'names nothing', ref
                problems.append({'path': c['origin'].get('path'), 'reference': True,
                                 'problem': f'{c["id"]}: {ref} is a plain id that general records of other projects also match ({", ".join(found[:3])}); '
                                            f'it {now}; write the id you mean ({ref} for this project, or one of those) to keep it'})
                resolved.append(target)
            if field == 'ledger_id': c['ledger_id'] = resolved[0] if resolved else c['ledger_id']
            else: c[field] = resolved


def _wiki_candidates(ledger, problems, coverage=None):
    coverage = coverage if coverage is not None else {}
    found, page_problems = wiki.pages(ledger.project, coverage=coverage)
    problems += page_problems
    out, seen = [], {}
    for page in found:
        try:
            parsed = wiki.parse(page['text'], page['path'], mandatory_only=bool(page.get('mandatory_only')))
        except Exception as error:                              # one page never takes the others down (review r1 #4)
            problems.append({'path': page['path'], 'problem': f'page not read ({type(error).__name__})'})
            if wiki.MUST_TEXT.search(page['text']):                # P2-02: ... but its mandatory sections are not lost silently
                coverage['undelivered'].append({'path': page['path'], 'line': None, 'id': None, 'applies_to': None, 'source_paths': None,
                                                'reason': f'the page declares a mandatory section but could not be read ({type(error).__name__})'})
            continue
        problems += [{'path': page['path'], 'problem': p} for p in parsed['problems']]
        coverage['undelivered'] += [dict(u, path=page['path']) for u in parsed['undelivered']]
        if parsed.get('skipped'): coverage['partly_read'] = coverage.get('partly_read', 0) + 1          # review r1 F14
        for entry in parsed['entries']:
            if entry['id'] in seen:
                problems.append({'path': page['path'], 'problem': f'id {entry["id"]} is already used by {seen[entry["id"]][0]}; skipped'})
                first = seen[entry['id']][1]           # review r1 F6: a copy of the same section, or of a live ledger subject, loses nothing
                if entry['must'] and _section_signature(entry) != _section_signature(first):
                    clash = _undelivered(entry, page['path'], f'its id {entry["id"]} is already used by a different section in {seen[entry["id"]][0]}')
                    if entry.get('ledger_id'): coverage.setdefault('copies', []).append(dict(clash, ledger_id=entry['ledger_id']))   # R2-03
                    else: coverage['undelivered'].append(clash)
                continue
            seen[entry['id']] = (page['path'], entry)
            out.append({'id': entry['id'], 'origin': {'type': 'wiki', 'path': page['path'], 'sha256': page['sha256'], 'line': entry['line'],
                                                      'external': page['origin'] == 'external'},
                        'kind': entry['kind'], 'label': entry['label'], 'must': entry['must'], 'status': entry['status'], 'title': entry['title'],
                        'text': entry['text'], 'sources': entry['sources'], 'conditions': entry['conditions'], 'applies_to': entry['applies_to'],
                        'supersedes': entry['supersedes'], 'derived_from': entry['derived_from'], 'ledger_id': entry['ledger_id'],
                        'visibility': 'project', 'scope': 'project', 'root': None, 'seq': 0, 'project': ledger.project_id,
                        'scope_paths': [], 'conflict_with': [], 'contradicts': [], 'evidence': None})
    return out


def _ledger_candidates(ledger, problems, lifecycle=None):
    """Context entries as candidates (the newest version of each subject); lifecycle records go to `lifecycle`, never to the candidates."""
    try:
        entries = context.retrieve(ledger, scope='both', limit=None, raw=True)['entries']
    except (LedgerError, OSError) as error:
        problems.append({'path': 'ledger', 'problem': 'context entries unreadable: ' + str(error)[:160], 'ledger_unreadable': True}); return []
    newest, versions, locations, tags = {}, {}, _lesson_locations(ledger), project_tags(ledger)
    reader = ledger.project_id
    for e in entries:
        try:
            p = e.get('payload') or {}
            if e['kind'] == 'task_done': continue                   # engine progress bookkeeping; the node's inputs carry provenance
            k = p.get('knowledge') if isinstance(p.get('knowledge'), dict) else {}
            key, root, writer = e['key'], p.get('task'), p.get('project')
            visibility = k.get('visibility') or ('project' if key.startswith('lesson-') else 'root')
            tag = tags.get(writer)
            ident = ledger_id(key, visibility, root, writer, reader, tag, lesson=key.startswith('lesson-') and not k)
            if k.get('withdraws') or k.get('archives'):
                if lifecycle is not None:              # P2-B: the target is the writer's own subject
                    lifecycle.append({'id': ident, 'withdraws': _in_reader_terms(k.get('withdraws'), writer, reader, tag),
                                      'archives': _in_reader_terms(k.get('archives'), writer, reader, tag), 'reason': k.get('reason'),
                                      'root': root, 'event': e['event'], 'project': p.get('project'), 'scope': e['scope'], 'visibility': visibility,
                                      'text_sha': k.get('text_sha'), 'version': e['id']})
                continue
            source = dict(e['source'])
            if source.get('type') in ('file_line', 'symbol') and p.get('revision_ref'): source.setdefault('revision', p['revision_ref'])
            sources = [source] + [s for s in (k.get('sources') or []) if isinstance(s, dict) and s != e['source']]
            sources += [dict(s, role='applies') for s in (k.get('applies_pins') or []) if isinstance(s, dict)]
            location = locations.get(key) if key.startswith('lesson-') else None
            if location:                                         # r2 N5: a lesson is about its file: a permission source and a pin
                sources.append({'type': 'file', 'path': location['path'], **({'blob': location['blob']} if location.get('blob') else {'revision': location.get('revision')})})
            conditions = k.get('conditions') if k.get('conditions') is not None else [c if isinstance(c, dict) else {'type': 'text', 'text': c} for c in (e.get('conditions') or [])]
            candidate = {'id': ident, 'origin': {'type': 'ledger', 'event': e['event'], 'key': key, 'scope': e['scope']},
                         'kind': k.get('kind') or ('lesson' if key.startswith('lesson-') else e['kind'] if e['kind'] in wiki.KINDS else 'note'),
                         'label': e['stored_label'] if e['stored_label'] != 'stale' else 'observed', 'must': bool(k.get('must')),
                         'status': 'active', 'title': (k.get('title') or e['text'])[:80], 'text': e['text'], 'sources': sources, 'conditions': conditions,
                         'applies_to': k.get('applies_to') or [],
                         'supersedes': [_in_reader_terms(s, writer, reader, tag) for s in k.get('supersedes') or []],
                         'derived_from': [_in_reader_terms(s, writer, reader, tag) for s in k.get('derived_from') or []],
                         'ledger_id': None, 'visibility': visibility, 'scope': e['scope'], 'root': root, 'project': p.get('project'),
                         'recorded_revision': p.get('revision_ref'), 'seq': e['event'], 'scope_paths': k.get('scope_paths') or [],
                         'conflict_with': [_in_reader_terms(s, writer, reader, tag, lessons=True) for s in k.get('conflict_with') or []],
                         'contradicts': [_in_reader_terms(s, writer, reader, tag) for s in k.get('contradicts') or []], 'evidence': k.get('evidence'),
                         'version': e['id'], 'ledger_stale': e['stale_reason'] if e['label'] == 'stale' else None, 'format': k.get('version')}
        except (KeyError, TypeError, ValueError, AttributeError):
            problems.append({'path': 'ledger', 'problem': 'a context entry could not be read'}); continue
        versions.setdefault(ident, []).append(candidate['seq'])
        if ident not in newest or newest[ident]['seq'] < candidate['seq']:
            newest[ident] = candidate                               # an older version of the same subject (any root) is history
    _legacy_aliases(newest, versions, reader)
    _replaced_elsewhere(ledger, newest, reader)
    if lifecycle is not None: _lesson_targets(newest, lifecycle, reader, tags)
    return sorted(newest.values(), key=lambda c: c['seq'])


def _lesson_locations(ledger):
    """lesson-<logical> -> {path, blob, revision} of the project's lessons (their newest record)."""
    with ledger.transaction() as conn:
        rows = conn.execute("SELECT e.payload FROM tasks t JOIN events e ON e.task_id=t.id WHERE t.project_id=? AND e.kind='learning.lesson' ORDER BY e.seq",
                            (ledger.project_id,)).fetchall() if conn else []
    out = {}
    for row in rows:
        value = json.loads(row['payload'])
        location = value.get('location') if isinstance(value.get('location'), dict) else None
        if value.get('lesson') and location and location.get('path'):
            out['lesson-' + value['lesson']] = {'path': location['path'], 'blob': value.get('file_blob'), 'revision': location.get('revision')}
    return out


def withdrawn_targets(ledger):
    """id -> seq of the newest withdrawal record of the project (for readers outside this module: lessons.refine_context)."""
    with ledger.transaction() as conn:
        rows = conn.execute("SELECT e.seq, t.project_id AS project, json_extract(e.payload,'$.scope') AS scope, "
                            "json_extract(e.payload,'$.knowledge.withdraws') AS target FROM tasks t JOIN events e ON e.task_id=t.id "
                            "WHERE (t.project_id=? OR json_extract(e.payload,'$.scope')='general') AND e.kind='context.entry' "
                            "AND json_extract(e.payload,'$.knowledge.withdraws') IS NOT NULL", (ledger.project_id,)).fetchall() if conn else []
        out = {}
        for row in rows:
            if row['project'] != ledger.project_id:    # another project's general withdrawal counts only for its own general entries
                key = row['target'][len('lesson-'):] if row['target'].startswith('lesson-') else None
                owner = conn.execute("SELECT t.project_id FROM tasks t JOIN events e ON e.task_id=t.id WHERE e.kind='learning.lesson' "
                                     "AND json_extract(e.payload,'$.lesson')=? LIMIT 1", (key,)).fetchone() if key else None
                if owner is None or owner['project_id'] != row['project']: continue
            out[row['target']] = max(out.get(row['target'], 0), row['seq'])
    return out


def _withdrawn_lessons(ledger):
    """Lesson subjects whose newest learning.lesson record is withdrawn: refine_context already drops them, their copies must go too."""
    with ledger.transaction() as conn:
        rows = conn.execute("SELECT e.payload FROM tasks t JOIN events e ON e.task_id=t.id WHERE t.project_id=? AND e.kind='learning.lesson' ORDER BY e.seq",
                            (ledger.project_id,)).fetchall() if conn else []
    latest = {}
    for row in rows:
        value = json.loads(row['payload'])
        if value.get('lesson'): latest[value['lesson']] = value.get('status')
    return {'lesson-' + lesson: 'withdrawn lesson' for lesson, status in latest.items() if status == 'withdrawn'}


def _acts_for(record, cons, project_id):
    """Whether a record's lifecycle/supersession effects act for this consumer: same project, and visible to it."""
    if record.get('project') != project_id: return False
    return record.get('visibility') == 'project' or (cons is not None and record.get('root') == cons['root'])


def _lifecycle(candidates, lifecycle, withdrawn_lessons, cons, project_id, usable=None):
    """id -> (state, reason, before_seq, text_sha): state applies to versions written before `before_seq` (None = every version) and,
    for a wiki entry, to the text it had then (`text_sha`). Only records the consumer may see act; only a superseder in `usable` (the
    consumer may read it and it applies) supersedes for it (review r2 N19)."""
    status = {ident: ('withdrawn', why, None, None) for ident, why in withdrawn_lessons.items()}
    general = {c['id']: c for c in candidates if c['scope'] == 'general'}
    for record in sorted(lifecycle, key=lambda r: r['event']):
        target = record.get('withdraws') or record.get('archives')
        owner = general.get(target)
        effective = (_acts_for(record, cons, project_id) if owner is None
                     else record.get('scope') == 'general' and record.get('project') == owner.get('project'))
        if not effective: continue
        if record.get('withdraws'):
            status[target] = ('withdrawn', record.get('reason') or '', record['event'], record.get('text_sha'))
        elif status.get(target, ('active',))[0] == 'active':
            status[target] = ('archived', record.get('reason') or '', record['event'], record.get('text_sha'))
    for c in candidates:
        if c['status'] != 'active': status.setdefault(c['id'], (c['status'], 'marked ' + c['status'] + ' in the wiki page', None, None))
        if c.get('replaced_by_owner'):                 # review dev6 D6: its project replaced it with a version it did not share
            status.setdefault(c['id'], ('superseded', 'replaced by a newer version of its project that is not shared', None, None))
    hidden = {}
    for c in candidates:                               # supersession: by any usable record of the project, whatever its own state (order-free)
        if c['origin']['type'] == 'ledger' and not _acts_for(c, cons, project_id): continue
        if usable is not None and c['id'] not in usable:
            for old in c['supersedes']:                # r3 R3-2: the reader cannot use the newer entry: the old one is a lead, not current
                if old != c['id']: hidden[old] = 'superseded by an entry outside your read scope or not applicable to you'
            continue
        for old in c['supersedes']:
            if old != c['id']: status.setdefault(old, ('superseded', 'superseded by ' + c['id'], None, None))
    status['__hidden_superseders__'] = hidden
    return status


def _text_sha(text):
    return hashlib.sha256(' '.join(str(text).split()).encode('utf-8')).hexdigest()[:24]


def _state_of(status, c, ident=None):
    entry = status.get(ident or c['id'])
    if entry is None: return 'active', None
    state, reason, before, text_sha = entry
    if before is not None and (ident is None or ident == c['id']):
        if c['origin']['type'] == 'wiki':
            if text_sha and _text_sha(c['text']) != text_sha: return 'active', None     # (a) the section was corrected since
        elif c.get('seq', 0) > before:
            return 'active', None                      # written after the withdrawal: a correction, live again
    return state, reason


def _summarized_withdrawn(status, source_id, summary):
    """r2 N1: the summary was written before its source was withdrawn (or archived): it summarizes a withdrawn version, even if a
    correction of the subject is live now."""
    entry = status.get(source_id)
    return bool(entry and entry[0] in ('withdrawn', 'archived') and entry[2] is not None and summary.get('seq', 0) < entry[2])


def _tokens(text):
    words = set()
    for token in re.findall(r'[\w]+(?:[./-][\w]+)*', str(text).casefold()):
        parts = [token] + re.split(r'[./-]', token)
        words.update(w for w in parts if len(w) >= 3 and w not in STOP and not w.isdigit())
        if '.' in token or '/' in token: words.add(token)
    return words


def _decide(ledger, cons, candidates, lifecycle=(), withdrawn_lessons=None, view=None):
    """Attach to every candidate: excluded (reason) or use/applicability/relevance. Pure code."""
    state = _State(ledger, view)
    usable = set()
    for c in candidates:                               # permission and applicability first: a superseder must be usable by this consumer
        c['_base'] = None
        if c['visibility'] == 'root' and c['root'] != cons['root']: c['_base'] = 'root_private'; continue
        files = [s['path'] for s in c['sources'] if s.get('path')] + list(c['scope_paths'])
        own = cons.get('own_root') and c['origin']['type'] == 'ledger' and c['root'] == cons['root']   # for_root: the root wrote it
        if not own and any(not _readable(cons['paths'], f) for f in files): c['_base'] = 'source_outside_read_scope'; continue
        c['applicability'] = _applicability(state, c, cons['environment'])
        if c['applicability']['state'] == 'not_applicable': c['_base'] = 'not_applicable'; continue
        usable.add(c['id'])
    status = _lifecycle(candidates, list(lifecycle), withdrawn_lessons or {}, cons, ledger.project_id, usable)
    hidden_superseders = status.pop('__hidden_superseders__', {})
    live_ledger = {c['id'] for c in candidates if c['origin']['type'] == 'ledger'}
    contested, contradicted = {}, {}
    for c in candidates:
        if c['origin']['type'] != 'ledger' or _state_of(status, c)[0] != 'active': continue
        mine = _acts_for(c, cons, ledger.project_id)
        if not mine and c['scope'] != 'general': continue
        if c['conflict_with']:                         # review dev6 R8: the writer's contest of its own general subject, for every reader
            contested[c['id']] = 'contested: written from an older version of the same subject'
            for other in c['conflict_with']: contested.setdefault(other, 'contested: a concurrent update of this subject was kept separately')
        if not mine: continue
        for target in c['contradicts']:             # r3 R3-1: the text only for a reader who may use the contradiction record itself
            contradicted.setdefault(target, ('contradicted by a later observation: ' + c['text'][:120]) if c['id'] in usable
                                    else 'contradicted by a later observation outside your read scope')
    by_id = {c['id']: c for c in candidates}
    for c in candidates:
        c['excluded'] = None
        if c['_base'] in ('root_private', 'source_outside_read_scope'): c['excluded'] = c['_base']; continue
        if c['origin']['type'] == 'wiki' and c['ledger_id'] and c['ledger_id'] in live_ledger and _state_of(status, by_id[c['ledger_id']])[0] == 'active':
            c['excluded'] = 'copy_of_ledger_entry'; continue                     # delivered once, from the ledger that holds its lifecycle
        own = _state_of(status, c)[0]
        copied = status.get(c['ledger_id'], ('active',))[0] if c['ledger_id'] else 'active'
        if own != 'active' or copied != 'active':
            c['excluded'] = own if own != 'active' else copied; continue          # a copy never outlives its source
        if c['_base'] == 'not_applicable': c['excluded'] = 'not_applicable'; continue
        for reason in (contested.get(c['id']), contradicted.get(c['id']), hidden_superseders.get(c['id'])):
            if reason:
                applicability = c['applicability']
                c['applicability'] = {'state': 'recheck' if applicability['state'] != 'not_applicable' else 'not_applicable',
                                      'reasons': applicability['reasons'] + [reason]}
        if c['applicability']['state'] == 'not_applicable': c['excluded'] = 'not_applicable'; continue
        applies = c['applicability']['state'] == 'applies'
        c['use'] = 'fact' if applies and c['label'] == 'verified' else 'rejected' if applies and c['label'] == 'refuted' else 'lead'
    changed = True
    while changed:                                     # a summary is never stronger than its weakest source, nor alive without it
        changed = False
        for c in candidates:
            if c['excluded'] or not c['derived_from']: continue
            sources = [by_id.get(d) for d in c['derived_from']]
            gone = [d for d, s in zip(c['derived_from'], sources) if s is None or s['excluded']
                    or _summarized_withdrawn(status, d, c)]
            if gone:
                reasons = {(by_id[d]['excluded'] if d in by_id else 'unknown') for d in gone}
                c['excluded'] = 'source_' + ('withdrawn' if reasons & {'withdrawn', 'superseded', 'archived', 'source_withdrawn'} else
                                             'not_applicable' if 'not_applicable' in reasons else 'not_visible'); changed = True; continue
            weakest = min((s['use'] for s in sources), key=lambda u: USE_RANK[u])
            if any(s['seq'] > c['seq'] for s in sources if s['origin']['type'] == 'ledger') and c['use'] != 'lead':
                weakest = 'lead'                       # a source has a newer version than the one summarized: the summary is a lead
            if USE_RANK[weakest] < USE_RANK[c['use']]:
                c['use'] = weakest
                c['applicability'] = {'state': c['applicability']['state'], 'reasons': c['applicability']['reasons'] + ['a source of this summary is a ' + weakest]}
                changed = True
    eligible = [c for c in candidates if not c['excluded']]
    groups = {}
    for c in eligible:                                 # copies: the same claim, sources, scope and qualifiers; keep the strongest one (a mandatory one is also its heading: r2 R2-04b)
        signature = (' '.join(c['text'].casefold().split()), ' '.join(c['title'].casefold().split()) if c['must'] else '', c['kind'], c['label'], c['must'], canonical(sorted(c['applies_to'])),
                     canonical(sorted(canonical(s) for s in c['sources'])), canonical(c['conditions']))
        groups.setdefault(signature, []).append(c)
    for twins in groups.values():
        if len(twins) < 2: continue
        twins.sort(key=lambda c: (-USE_RANK[c['use']], -int(c['must']), c['seq'], c['id']))
        twins[0]['copies'] = len(twins)
        for twin in twins[1:]: twin['excluded'] = 'copy'
    eligible = [c for c in candidates if not c['excluded']]
    mine = _tokens(cons['terms']) | {t for p in cons['paths'] for t in _tokens(p)}
    vocab = [_tokens(' '.join([c['title'], c['text'], *c['applies_to'], *[s.get('path', '') for s in c['sources']]])) for c in eligible]
    df = {}
    for words in vocab:
        for w in words: df[w] = df.get(w, 0) + 1
    total = len(eligible)
    for c, words in zip(eligible, vocab):
        shared = words & mine
        paths = list(c['applies_to']) + [s['path'] for s in c['sources'] if s.get('path')]
        c['path_hit'] = any(_covers(a, p) or _covers(p, a) for a in paths for p in cons['paths'])
        c['score'] = round((10.0 if c['path_hit'] else 0.0) + sum(math.log((total + 1) / (df[w] + 1)) + 1 for w in shared)
                           + KIND_WEIGHT.get(c['kind'], 0.5) * (1 if shared or c['path_hit'] else 0), 4)
        c['relevant'] = c['path_hit'] or len(shared) >= 2 or any('.' in w or '/' in w for w in shared)
        c['mandatory'] = c['must'] and (c['path_hit'] or not c['applies_to'])
    return eligible


def _render(c, text_chars, whole=False):
    text = c['text']
    if c['mandatory'] or whole: text_chars = len(text)               # a mandatory (or requested) entry is delivered whole, never cut
    out = {'id': c['id'], 'use': c['use'], 'must': c['mandatory'], 'kind': c['kind'], 'label': c['label'], 'title': c['title'][:160],
           'text': text[:max(0, text_chars)], 'applicability': c['applicability'],
           'source': [_source_text(s) for s in c['sources'] if s.get('role') != 'applies'] or ['wiki page ' + c['origin'].get('path', '')],
           'origin': {k: v for k, v in c['origin'].items() if k in ('type', 'path', 'line', 'sha256', 'event')}}
    evidence = c.get('evidence') or {}
    qualifiers = {k: evidence[k] for k in ('status', 'property', 'cause', 'basis', 'semantic_verification') if evidence.get(k)}
    if qualifiers: out['evidence'] = qualifiers
    if c['applies_to']: out['applies_to'] = c['applies_to']
    if c['conditions']: out['conditions'] = c['conditions']
    if len(text) > len(out['text']): out['text_truncated'] = {'delivered': len(out['text']), 'total': len(text)}
    if c.get('copies'): out['copies'] = c['copies']
    if c.get('derived_from'): out['derived_from'] = c['derived_from']
    return out


def _source_text(s):
    if s['type'] == 'file_line': return f'{s["path"]}:{s["line"]}' + (f'@{s["revision"][:12]}' if s.get('revision') else '')
    if s['type'] == 'symbol': return f'{s["name"]} in {s["path"]}' + (f'@{s["revision"][:12]}' if s.get('revision') else '')
    if s['type'] == 'file': return s['path'] + (f'@{s["revision"][:12]}' if s.get('revision') else f' blob {s["blob"][:12]}' if s.get('blob') else '')
    if s['type'] == 'receipt': return 'receipt ' + str(s.get('key'))[:16]
    if s['type'] == 'event': return f'event {s.get("id")}'
    return str(s.get('url', ''))[:200]


def _order(eligible):
    rank = lambda c: (-c['score'], -c['seq'], c['id'])
    must = sorted((c for c in eligible if c['mandatory']), key=rank)
    optional = sorted((c for c in eligible if not c['mandatory'] and c['relevant']), key=rank)
    rest = sorted((c for c in eligible if not c['mandatory'] and not c['relevant']), key=rank)
    return must, optional, rest


def _state_hash(cons, candidates):
    return content_hash({'consumer': {k: cons[k] for k in ('project', 'root', 'node', 'paths', 'terms', 'environment')}, 'version': VERSION,
                         'entries': [[c['id'], c['origin'].get('sha256') or c['origin'].get('event'), c.get('excluded'), c.get('use'),
                                      (c.get('applicability') or {}).get('state')] for c in candidates]})[:32]


def _cursor(revision, offset):
    return 'k1.' + base64.urlsafe_b64encode(canonical({'r': revision, 'o': offset}).encode()).decode().rstrip('=')


def _uncursor(cursor):
    try:
        if not isinstance(cursor, str) or not cursor.startswith('k1.'): raise ValueError
        raw = cursor[3:] + '=' * (-len(cursor[3:]) % 4)
        value = json.loads(base64.urlsafe_b64decode(raw.encode()).decode())
        if set(value) != {'r', 'o'} or type(value['o']) is not int or value['o'] < 0: raise ValueError
        return value['r'], value['o']
    except (ValueError, TypeError, UnicodeDecodeError):
        raise LedgerError('Not a knowledge cursor.') from None


# ---- the package ---------------------------------------------------------------------------------------------------------------

def _read_all(ledger):
    """Everything a decision reads, once: wiki candidates, ledger candidates, lifecycle records, problems, coverage."""
    problems, lifecycle, coverage = [], [], {}
    candidates = _wiki_candidates(ledger, problems, coverage)
    taken = {c['id'] for c in candidates}
    for c in _ledger_candidates(ledger, problems, lifecycle):
        if c['id'] in taken:
            problems.append({'path': 'ledger', 'problem': 'a ledger subject has the id of a wiki entry; the ledger entry is skipped'})
            if c['must']: coverage['undelivered'].append(_undelivered(c, 'ledger', 'a wiki entry has the id of this ledger subject'))
            continue
        taken.add(c['id']); candidates.append(c)
    legacy_wiki_references(candidates, problems)
    if any(p.get('ledger_unreadable') for p in problems): coverage['ledger_unreadable'] = True
    ledger_ids = {c['id'] for c in candidates if c['origin']['type'] == 'ledger'}
    for clash in coverage.pop('copies', []):          # review r2 R2-03: copies of a subject this ledger lacks are the only source
        if clash['ledger_id'] not in ledger_ids: coverage['undelivered'].append(clash)
    return candidates, lifecycle, problems, coverage, _withdrawn_lessons(ledger)


def _collect(ledger, cons, view, memo=None):
    """(candidates, eligible, problems, coverage) for `cons`. `memo` (a dict) shares one reading between several decisions of one
    command (review r1 F17): every decision gets its own copies, _decide writes on them."""
    if memo is not None and 'read' in memo: raw = memo['read']
    else:
        raw = _read_all(ledger)
        if memo is not None: memo['read'] = raw
    candidates, lifecycle, problems, coverage, withdrawn = raw
    candidates = [dict(c) for c in candidates]
    problems = list(problems)
    coverage = dict(coverage, undelivered=list(coverage.get('undelivered') or []))
    eligible = _decide(ledger, cons, candidates, lifecycle, withdrawn, view)
    by_id, known = {c['id']: c for c in candidates}, {}
    def unread(ident):                                 # review r1 F4 / r2 R2-02: not read, here or further down the derivation;
        if ident in known: return known[ident]         # r3 R3-01: one answer per id (linear; a cycle counts as read)
        if ident not in by_id: return True
        known[ident] = False
        c = by_id[ident]
        if c.get('excluded') == 'source_not_visible': known[ident] = any(unread(d) for d in c['derived_from'])
        return known[ident]
    for c in candidates:
        missing = [d for d in c['derived_from'] if unread(d)] if c['must'] and c.get('excluded') == 'source_not_visible' else []
        if missing:
            coverage['undelivered'].append(_undelivered(c, c['origin'].get('path', 'ledger'), f'it derives from {", ".join(missing[:3])}, '
                                                        'which was not read (malformed, or on a page past the reading budget)'))
    return candidates, eligible, problems, coverage


def _ledger_has_must(ledger):
    """Whether the ledger holds a mandatory knowledge record of this project (True when that cannot be told)."""
    try:
        with ledger.transaction() as conn:
            return bool(conn and conn.execute("SELECT 1 FROM events e JOIN tasks t ON t.id=e.task_id WHERE t.project_id=? AND e.kind='context.entry' "
                                              "AND json_extract(e.payload,'$.knowledge.must') IN (1, 'true') LIMIT 1", (ledger.project_id,)).fetchone())
    except Exception:
        return True


def declares_mandatory(ledger):
    """Review r1 F5: whether the project declares any mandatory knowledge at all, by a reading that shares nothing with the selection
    (bytes of the wiki pages, one SQL query); True when that cannot be told."""
    try:
        scanned = 0
        for folder in wiki.configured_paths(ledger.project):
            base = Path(folder) if Path(folder).is_absolute() else Path(ledger.project) / folder
            if not base.is_dir(): continue
            for file in base.rglob('*.md'):
                try:
                    if not file.is_file(): continue    # review r2 R2-08: a folder named like a page declares nothing
                    scanned += file.stat().st_size
                    if scanned > wiki.MAX_SCAN_BYTES: return True
                    if wiki._scan_for_must(file): return True
                except OSError:
                    continue                           # content unknown: reported by the selection, never read as mandatory here
    except Exception:
        return True
    return _ledger_has_must(ledger)


def _established(cons, coverage, ledger=None):
    """P2-02: raise KnowledgeIncomplete when a mandatory constraint that may concern `cons` cannot be established."""
    if coverage.get('ledger_unreadable') and (ledger is None or _ledger_has_must(ledger)):
        raise KnowledgeIncomplete('Mandatory knowledge cannot be established: the context entries of the ledger could not be read and it may '
                                  'hold mandatory records; nothing runs with partial constraints.')
    if coverage.get('unscanned'):
        raise KnowledgeIncomplete(f'Mandatory knowledge cannot be established: {coverage["unscanned"]} wiki page(s) were not looked through '
                                  f'(more than {wiki.MAX_SCAN_BYTES} bytes of wiki); narrow the wiki folders (.onecrew/config.json "wiki") '
                                  'and run again; nothing runs with partial constraints.')
    blocking = [u for u in coverage.get('undelivered') or [] if _concerns(u, cons)]
    if blocking:
        named = '; '.join(f'{u["path"]}' + (f':{u["line"]}' if u.get('line') else '') + (f' {u["id"]}' if u.get('id') else '') + f' ({u["reason"]})'
                          for u in blocking[:5])
        raise KnowledgeIncomplete(f'Mandatory knowledge cannot be established: {len(blocking)} mandatory section(s) cannot be delivered: '
                                  f'{named[:900]}; fix the page and run again; nothing runs with partial constraints.')


def _coverage_view(coverage):
    """What the package says about the wiki it could not read whole (nothing when it read every page)."""
    if not (coverage.get('not_read') or coverage.get('unreadable') or coverage.get('undelivered') or coverage.get('partly_read')
            or coverage.get('missing_folders') or coverage.get('config_problem')): return None
    view = {'complete': False, 'pages': coverage.get('pages', 0), 'not_read': coverage.get('not_read', 0),
            'unreadable': len(coverage.get('unreadable') or []), 'mandatory_not_delivered': len(coverage.get('undelivered') or [])}
    if coverage.get('partly_read'): view['partly_read'] = coverage['partly_read']             # review r1 F14
    if coverage.get('missing_folders'): view['missing_folders'] = coverage['missing_folders'][:5]   # review r1 F2
    if coverage.get('config_problem'): view['config_problem'] = True
    return view


def _build(ledger, cons, cap_chars, offset=0, requested=(), expect_revision=None, view=None):
    if type(cap_chars) is not int or cap_chars < 0: raise LedgerError('cap_chars: an integer of at least 0.')
    started = time.perf_counter()
    candidates, eligible, problems, coverage = _collect(ledger, cons, view)
    _established(cons, coverage, ledger)
    revision = _state_hash(cons, candidates)
    wiki_view = _coverage_view(coverage)
    if expect_revision is not None and expect_revision != revision:
        raise LedgerError('This cursor belongs to an older knowledge state (a page, an entry or the task changed); retrieve the package again.')
    must, optional, rest = _order(eligible)
    ordered = must + optional + rest                    # the cursor runs through every permitted entry: relevance orders, it never hides
    relevant = {id(c) for c in must + optional}
    permitted = {c['id']: c for c in eligible}
    by_reason_excluded = {}
    for c in candidates:
        if c['excluded']: by_reason_excluded[c['excluded']] = by_reason_excluded.get(c['excluded'], 0) + 1
    shown_problems = problems[:PROBLEM_ROWS]
    trimmed_problems, index_rows = None, INDEX_ROWS

    def make(delivered, requested_out, refused, position):
        left = ordered[position:]
        by_reason = dict(by_reason_excluded)
        capped = [c for c in left if id(c) in relevant and c['id'] not in {d['id'] for d in delivered}]
        unrelated = [c for c in left if id(c) not in relevant]
        if capped: by_reason['cap'] = len(capped)
        if unrelated: by_reason['not_relevant'] = len(unrelated)
        index = [{'id': c['id'], 'title': c['title'][:60], 'use': c['use'], 'reason': 'cap'} for c in capped]
        index += [{'id': c['id'], 'title': c['title'][:60], 'use': c['use'], 'reason': 'not_relevant'} for c in unrelated]
        eof = not left
        return {'kind': 'knowledge-package', 'version': VERSION, 'data_not_authority': True, 'notice': NOTICE, 'policy': POLICY,
                'consumer': {k: cons[k] for k in ('project', 'plan', 'node', 'paths')}, 'revision': revision,
                'entries': delivered, 'requested': requested_out, 'requests_refused': refused,
                'omitted': {'total': sum(by_reason.values()), 'by_reason': by_reason, 'index': index[:index_rows],
                            'cursor': None if eof else _cursor(revision, position), 'eof': eof},
                'problems': shown_problems, **({'wiki': wiki_view} if wiki_view else {})}

    skeleton = len(canonical(make([], [], [], max(offset, len(must)) if offset else 0)))
    budget = cap_chars - skeleton - 64                 # the whole package stays under cap_chars (index and problems included)
    text_chars = min(ENTRY_TEXT_CHARS, max(MIN_CAP, cap_chars // 2))
    delivered, room = [], budget
    if budget < 150 and (offset or not must) and (ordered[max(offset, len(must)):] or requested):
        raise KnowledgeNoRoom(f'a cap of {cap_chars} characters leaves no room for an entry beside the package frame ({skeleton} characters).')
    if offset == 0:
        rendered = [_render(c, text_chars) for c in must]
        need = sum(len(canonical(r)) + 1 for r in rendered)
        if must and need > budget and (shown_problems or index_rows):   # review r1 F16 / r2 R2-07: page problems go to the receipt and
            all_problems, shown_problems, index_rows = shown_problems, [], 0   # the omitted list to the cursor; mandatory knowledge stays
            skeleton = len(canonical(make([], [], [], 0)))
            budget = cap_chars - skeleton - 64
            if need <= budget: trimmed_problems = all_problems
        if must and need > budget:
            raise KnowledgeOverflow(f'Mandatory knowledge needs {need} characters, over the room of {max(budget, 0)} left for knowledge '
                                    f'({", ".join(c["id"] for c in must)}); do not run with partial constraints.')
        delivered, room = rendered, budget - need
    requested_out, refused = [], []
    shown = {d['id']: d for d in delivered}
    for ident in requested:                            # what the worker asked for comes before more optional entries, inside the cap
        c = permitted.get(ident)
        if c is None: refused.append({'id': ident, 'reason': 'not_available'}); continue
        if ident in shown and 'text_truncated' not in shown[ident]: continue
        item = _render(c, 0, whole=True)              # the whole text
        size = len(canonical(item)) + 1
        if size > room: refused.append({'id': ident, 'reason': 'too_large_for_the_room', 'chars': size}); continue
        requested_out.append(item); room -= size
    stop = len(must) + len(optional) if offset == 0 else len(ordered)          # the first page carries only mandatory and relevant ones
    position = max(offset, len(must))
    taken_at = []                                      # the position of every optional entry delivered (the pop below gives it back)
    while position < stop:
        candidate = ordered[position]
        if candidate['id'] in {r['id'] for r in requested_out}: position += 1; continue
        item = _render(candidate, text_chars)
        size = len(canonical(item)) + 1
        if size > room:
            if delivered or requested_out or offset == 0: break
            item = _render(candidate, max(80, room - (size - len(item['text'])) - 8))   # a later page always delivers its first entry, cut to the room
            size = len(canonical(item)) + 1
            if size > room: break
        delivered.append(item); taken_at.append(position); room -= size; position += 1
    package = make(delivered, requested_out, refused, position)
    while len(canonical(package)) > cap_chars and taken_at:
        delivered.pop(); position = taken_at.pop()    # the estimate missed: give the last optional entry back to the cursor
        package = make(delivered, requested_out, refused, position)
    package['cost'] = {'candidates': len(candidates), 'eligible': len(eligible), 'seconds': round(time.perf_counter() - started, 4)}
    if trimmed_problems is not None: package['cost']['problems_not_in_the_package'] = trimmed_problems
    return package


def package(ledger, cons, *, cap_chars=NATIVE_CAP_CHARS, requested=(), view=None):
    """The first page for `cons` (judged on `view`, the files its worker sees). KnowledgeOverflow when mandatory knowledge does not fit."""
    return _build(ledger, cons, cap_chars, requested=tuple(requested), view=view)


def read(ledger, cons, cursor, *, cap_chars=NATIVE_CAP_CHARS, view=None):
    """The page after `cursor` (same consumer and task, same knowledge state; otherwise refused)."""
    revision, offset = _uncursor(cursor)
    return _build(ledger, cons, cap_chars, offset=offset, expect_revision=revision, view=view)


def prompt_view(pkg):
    """The part of a package a worker receives (the cost measurement stays out: it is not knowledge)."""
    return {k: v for k, v in pkg.items() if k != 'cost'}


def delivered_ids(view):
    return [e['id'] for e in view.get('entries', [])] + [e['id'] for e in view.get('requested', [])]


# ---- the worker's declaration ----------------------------------------------------------------------------------------------------

def _ok_str(value, limit):
    return isinstance(value, str) and 0 < len(value) <= limit


def split_declaration(value):
    """(declaration or None, value without it, problem or None). The declaration is optional and never costs the attempt: a malformed
    one is dropped and the problem goes in the receipt (review r1 #5); the limits are the ones the worker's SCHEMA states."""
    if not isinstance(value, dict) or 'knowledge' not in value: return None, value, None
    rest = {k: v for k, v in value.items() if k != 'knowledge'}
    declared = value['knowledge']
    try:
        if not isinstance(declared, dict) or set(declared) - {'used', 'rejected', 'requests', 'new'}:
            raise ValueError('an object with used, rejected, requests and new only')
        used, rejected, requests, new = (declared.get(k, []) for k in ('used', 'rejected', 'requests', 'new'))
        if not isinstance(used, list) or len(used) > LIMITS['used'] or not all(_ok_str(i, LIMITS['id']) for i in used): raise ValueError('used')
        if not isinstance(requests, list) or len(requests) > LIMITS['requests'] or not all(_ok_str(i, LIMITS['id']) for i in requests): raise ValueError('requests')
        if (not isinstance(rejected, list) or len(rejected) > LIMITS['rejected']
                or not all(isinstance(r, dict) and set(r) == {'id', 'why'} and _ok_str(r['id'], LIMITS['id']) and isinstance(r['why'], str)
                           and len(r['why']) <= LIMITS['why'] for r in rejected)): raise ValueError('rejected')
        if not isinstance(new, list) or len(new) > LIMITS['claims']: raise ValueError('new')
        claims = []
        for claim in new:
            if (not isinstance(claim, dict) or set(claim) - {'kind', 'text', 'applies_to', 'sources', 'check'} or claim.get('kind') not in wiki.KINDS
                    or not _ok_str(claim.get('text'), LIMITS['text'])
                    or not isinstance(claim.get('applies_to', []), list) or len(claim.get('applies_to', [])) > LIMITS['paths']
                    or not isinstance(claim.get('sources', []), list) or len(claim.get('sources', [])) > LIMITS['sources']
                    or not all(_ok_str(v, LIMITS['path']) for v in claim.get('applies_to', []) + claim.get('sources', []))
                    or ('check' in claim and not _ok_str(claim['check'], LIMITS['id']))):
                raise ValueError('new: claims of {kind, text, applies_to?, sources?, check?} within the schema limits')
            claims.append({'kind': claim['kind'], 'text': claim['text'], 'applies_to': list(claim.get('applies_to', [])),
                           'sources': list(claim.get('sources', [])), **({'check': claim['check']} if 'check' in claim else {})})
    except ValueError as error:
        return None, rest, f'knowledge declaration dropped: {error}'
    return {'used': used, 'rejected': rejected, 'requests': requests, 'new': claims}, rest, None


def check_use(view, declared):
    """What the declaration says against what was delivered. Structural only: it never proves the worker understood an entry."""
    delivered = set(delivered_ids(view)) if view else set()
    entries = (view.get('entries', []) + view.get('requested', [])) if view else []
    leads = {e['id'] for e in entries if e['use'] == 'lead'}
    must = [e['id'] for e in entries if e.get('must')]
    declared = declared or {'used': [], 'rejected': [], 'requests': []}
    violations = [{'id': i, 'problem': 'not_delivered'} for i in declared['used'] if i not in delivered]
    violations += [{'id': r['id'], 'problem': 'not_delivered'} for r in declared['rejected'] if r['id'] not in delivered]
    acknowledged = set(declared['used']) | {r['id'] for r in declared['rejected']}
    return {'declared': bool(declared['used'] or declared['rejected'] or declared['requests']), 'used': list(declared['used']),
            'rejected_by_worker': list(declared['rejected']), 'violations': violations,
            'leads_used': sorted(set(declared['used']) & leads), 'must_unacknowledged': [i for i in must if i not in acknowledged],
            'proves_semantics': False}


# ---- the native adapter ------------------------------------------------------------------------------------------------------

def _id_of_event(ledger, seq):
    """The knowledge id, for this reader, of the subject whose version is context.entry `seq` (None if it is not one)."""
    with ledger.transaction() as conn:
        row = conn.execute("SELECT e.payload, e.task_id FROM events e WHERE e.seq=? AND e.kind='context.entry'", (seq,)).fetchone() if conn else None
    if row is None: return None
    try:
        p = json.loads(row['payload'])
        k = p.get('knowledge') if isinstance(p.get('knowledge'), dict) else {}
        visibility = k.get('visibility') or ('project' if p['key'].startswith('lesson-') else 'root')
        return ledger_id(p['key'], visibility, row['task_id'], p.get('project'), ledger.project_id, project_tags(ledger).get(p.get('project')),
                         lesson=p['key'].startswith('lesson-') and not k)
    except (KeyError, TypeError, ValueError, AttributeError):
        return None


def _current_id(ledger, store, record, ident):
    """The id a delivered entry has NOW: a package sealed before an upgrade (2.3.0.dev5) named another project's general record without
    its project; the delivered entry's origin event says which subject the worker judged (review dev6 R4)."""
    try:
        view = json.loads(store.read_blob(record['package'])) if record.get('package') else {}
    except (KeyError, LedgerError, OSError, ValueError, TypeError):
        return ident
    for e in (view.get('entries') or []) + (view.get('requested') or []):
        origin = e.get('origin') or {}
        if e.get('id') == ident and origin.get('type') == 'ledger' and origin.get('event'):
            return _id_of_event(ledger, origin['event']) or ident
    return ident


def previous_requests(ledger, store, selector, attempt_id):
    """knowledge.requests of the partial result of `attempt_id` (the attempt a continuation continues), from its retained receipt."""
    if not attempt_id: return []
    with ledger.transaction() as conn:
        root = namespaces.resolve(ledger, conn, selector) if conn else None
        if root is None: return []
        rows = conn.execute("SELECT payload FROM events WHERE task_id=? AND kind='node.result_retained' "
                            "AND json_extract(payload,'$.attempt')=? ORDER BY seq DESC", (root['id'], attempt_id)).fetchall()
    for row in rows:
        candidate = json.loads(row['payload']).get('candidate') or {}
        try:
            receipt = json.loads(store.read_blob(candidate['receipt']))
        except (KeyError, LedgerError, OSError, ValueError, TypeError):
            continue
        return list(receipt.get('knowledge_requests') or [])
    return []


def for_native(ledger, store, selector, node, pin, *, view=None, room=None):
    """(view, record) for one native attempt: `view` goes in the prompt (None when nothing is delivered), `record` in the receipt.
    `view` (argument) is the files the worker sees; `room` the characters the prompt cap leaves for the knowledge key. KnowledgeOverflow
    propagates (the caller stops before the model call); any other failure of this layer is recorded and the node runs on its own inputs."""
    cap = NATIVE_CAP_CHARS if room is None else max(0, min(NATIVE_CAP_CHARS, room))
    record = {'package': None, 'delivered': [], 'chars': 0, 'omitted_total': 0, 'problems': [], 'revision': None, 'cap': cap}
    try:
        cons = consumer(ledger, selector, node=node, pin=pin)
        requested = previous_requests(ledger, store, selector, node.get('continues'))
        pkg = package(ledger, cons, cap_chars=cap, requested=requested, view=view)
    except KnowledgeOverflow:
        raise
    except KnowledgeNoRoom as error:               # the prompt is full without knowledge: run on the inputs, say so in the receipt
        record['no_room'] = str(error)[:300]
        return None, record
    except Exception as error:                     # the knowledge layer never takes an independent node down with it ...
        record['error'] = f'{type(error).__name__}: {str(error)[:300]}'
        if declares_mandatory(ledger):             # ... unless the project declares mandatory knowledge (review r1 F5)
            raise KnowledgeIncomplete(f'Mandatory knowledge cannot be established: the knowledge selection failed ({record["error"][:200]}) '
                                      'and the project declares mandatory knowledge; nothing runs with partial constraints.') from error
        return None, record
    prompt = prompt_view(pkg)
    record.update(delivered=delivered_ids(prompt), omitted_total=pkg['omitted']['total'], omitted_by_reason=pkg['omitted']['by_reason'],
                  problems=pkg['problems'], revision=pkg['revision'], requested=[e['id'] for e in pkg['requested']],
                  requests_refused=pkg['requests_refused'], cost=pkg['cost'], **({'wiki': pkg['wiki']} if pkg.get('wiki') else {}))
    if pkg['cost'].get('problems_not_in_the_package'): record['problems'] = pkg['cost']['problems_not_in_the_package']
    if not record['delivered']:
        return None, record
    text = canonical(prompt)
    record.update(package=store.blob(text.encode('utf-8')), chars=len(text))
    return prompt, record


# ---- 2.3-A2: writing knowledge with its evidence ------------------------------------------------------------------------------
#
# One store: context.entry (class A) with the A2 fields under payload `knowledge`. A record is written on an OPEN root (checked in the
# write transaction); its label is the strength of the evidence given, never more:
#   evidence = {'status': observed|hypothesis|verified|refuted, 'sources': [...], 'property': what exactly was shown (verified),
#               'cause': 'established' only with a cause_source, otherwise 'not_established'}
# `visibility` 'project' publishes it for the other roots of the project (still filtered by their read scope); 'root' keeps it as the
# root's working memory. Withdrawal, archiving and supersession are records too: nothing is deleted, the reader applies them.

EVIDENCE_STATUS = ('observed', 'hypothesis', 'verified', 'refuted')
RANK = {'verified': 3, 'refuted': 3, 'observed': 2, 'hypothesis': 1, 'unverified': 0}


def _open_root(ledger, plan):
    from . import incidents, lessons
    with ledger.transaction() as conn:
        if conn is None: raise LedgerError('No ledger in this state root.')
        state, selector = incidents._root(ledger, conn, plan)
    lessons._still_open(state)                    # T52b [E14]: knowledge is written while the root is open (re-checked in the write txn)
    return state, selector


def _evidence_sources(ledger, sources):
    """Validated sources, pinned at write time: a file source keeps its commit AND its blob (the reader compares blobs, no history walk)."""
    out = []
    for source in sources or []:
        problems = []
        checked = wiki._source(source, problems, 'evidence')
        if checked is None: raise LedgerError('evidence source: ' + '; '.join(problems))
        if checked['type'] == 'event':
            with ledger.transaction() as conn:
                row = conn.execute('SELECT 1 FROM events e JOIN tasks t ON t.id=e.task_id WHERE e.seq=? AND t.project_id=?',
                                   (checked['id'], ledger.project_id)).fetchone()
            if row is None: raise LedgerError(f'evidence event {checked["id"]} is not an event of this project.')
        elif checked['type'] == 'receipt':
            from ..snapshots import Snapshots
            Snapshots(ledger.state_root).read_blob(checked['key'])
        elif checked['type'] in ('file', 'file_line', 'symbol') and not checked.get('blob'):
            checked['revision'] = context.resolve_revision(ledger.project, checked.get('revision') or 'HEAD')
            if checked['type'] == 'file':
                blob = command._git(ledger.project, 'rev-parse', '--verify', '-q', f'{checked["revision"]}:{checked["path"]}')
                if not blob: raise LedgerError(f'{checked["path"]} is not in {checked["revision"][:12]}.')
                checked['blob'] = blob
        out.append(checked)
    return out


def _pins(ledger, paths, files=None):
    """Blob pins of the concrete files a record applies to: from `files` (path -> text of the artifact the evidence is about) when given,
    else from HEAD. A file found in neither is not pinned (the entry is then `unknown` for it, never silently current)."""
    pins = []
    for path in _concrete(paths):
        blob = None
        try:
            if files is not None and path in files and isinstance(files[path], str):
                blob = blob_of(ledger, path, files[path].encode('utf-8'))
            else:
                blob = command._git(ledger.project, 'rev-parse', '--verify', '-q', f'HEAD:{path}') or None
        except LedgerError:
            blob = None
        if blob: pins.append({'type': 'file', 'path': path, 'blob': blob})
    return pins


def _primary(sources):
    """The context.entry source: the first event/receipt/file_line/symbol (context.add resolves it again)."""
    for s in sources:
        if s['type'] in ('event', 'receipt', 'file_line', 'symbol'):
            return {k: v for k, v in s.items() if k in ('type', 'id', 'key', 'path', 'line', 'revision', 'name')}
    raise LedgerError('knowledge needs at least one event, receipt, file_line or symbol source (a file blob alone cannot anchor it).')


def record(ledger, plan, *, kind, text, evidence, applies_to=(), conditions=(), must=False, visibility='project', scope='project',
           supersedes=(), derived_from=(), key=None, base=None, title=None, contradicts=(), scope_paths=(), files=None, basis=None, _lifecycle=None):
    """Write one knowledge record on the open root `plan`. Returns {'recorded', 'id', 'version', 'key', 'event', 'conflict'?}.
    `key` + `base`: an update of subject `key` written from version `base` (what `version` returned or `wiki history` shows; '' for
    none). When the subject moved on meanwhile, the update is kept as a separate contested version, never written over the newer one.
    `scope_paths`: the files the knowledge was learned from (a consumer must be able to read them all); `files`: the artifact contents
    the evidence is about (the applies_to pins come from there)."""
    if kind not in wiki.KINDS and _lifecycle is None: raise LedgerError(f'kind: one of {", ".join(wiki.KINDS)}.')
    if visibility not in ('project', 'root'): raise LedgerError('visibility: project or root.')
    if scope not in ('project', 'general'): raise LedgerError('scope: project or general.')
    if base is not None and not key: raise LedgerError('base names the version of a subject: give --key with it.')
    if key and _lifecycle is None and key.startswith(RESERVED_KEY_PREFIXES):
        raise LedgerError('--key: names that start with lesson- are the ids of lessons; choose another key (review dev6 R3).')
    if not isinstance(evidence, dict): raise LedgerError('evidence: an object with status and sources.')
    status = evidence.get('status', 'observed' if _lifecycle else None)
    if status not in EVIDENCE_STATUS: raise LedgerError(f'evidence.status: one of {", ".join(EVIDENCE_STATUS)}.')
    sources = _evidence_sources(ledger, evidence.get('sources'))
    if status == 'verified' and not (isinstance(evidence.get('property'), str) and evidence['property'].strip()):
        raise LedgerError('verified knowledge states the property that was actually shown (evidence.property).')
    cause = 'not_established'
    if evidence.get('cause') == 'established':
        if status != 'verified' or not evidence.get('cause_source'): raise LedgerError('a cause is established only by a verified record with its cause_source.')
        cause = 'established'
    problems = []
    typed_conditions = [c for c in (wiki._condition(c, problems, 'condition') for c in conditions) if c is not None]
    if problems: raise LedgerError('; '.join(problems))
    applies = [p for p in (wiki._relpath_or_glob(a) for a in applies_to) if p]
    if scope == 'general':
        if visibility != 'project': raise LedgerError('a general record is shared: visibility project.')
        extras = [name for name, value in (('applies_to', applies), ('must', must), ('supersedes', supersedes), ('contradicts', contradicts),
                                           ('derived_from', derived_from), ('title', title), ('scope_paths', scope_paths)) if value]
        if extras: raise LedgerError('a general record carries no project detail: drop ' + ', '.join(extras) + ' (review r1 #2).')
        if any(s['type'] not in ('event', 'receipt') for s in sources): raise LedgerError('a general record cites events or receipts only.')
    state, selector = _open_root(ledger, plan)
    if key and _lifecycle is None and _key_in_other_scope(ledger, key, scope):
        raise LedgerError(f'--key {key} already names a {"project" if scope == "general" else "general"} record of this project; a key names one '
                          'subject of a project, so a general and a project record never share one: choose another key (review dev6 R7).')
    key = key or content_hash(['k2', visibility, ledger.project_id if visibility == 'project' else state['task_id'], scope, kind,
                               ' '.join(text.casefold().split())])[:24]
    extra = {'version': FORMAT, 'kind': kind if _lifecycle is None else 'note', 'visibility': visibility, 'applies_to': applies,
             'conditions': typed_conditions, 'must': bool(must), 'supersedes': list(supersedes), 'derived_from': list(derived_from),
             'contradicts': list(contradicts), 'sources': sources, 'title': title, 'scope_paths': sorted(set(scope_paths)),
             'applies_pins': _pins(ledger, applies, files) if scope == 'project' else [],
             'evidence': {'status': status, 'property': evidence.get('property'), 'cause': cause,
                          **({'basis': basis} if basis else {}),
                          **({'cause_source': evidence['cause_source']} if cause == 'established' else {}),
                          **({'semantic_verification': evidence['semantic_verification']} if evidence.get('semantic_verification') else {})}}
    if _lifecycle: extra.update(_lifecycle)
    entry_kind = 'decision' if kind == 'decision' and _lifecycle is None else 'note'
    common = dict(kind=entry_kind, label=status, text=text, source=_primary(sources), scope=scope, require_open=True,
                  conditions=[c['text'] if c['type'] == 'text' else canonical(c) for c in typed_conditions] if scope == 'general' else None)
    subject = 'project' if visibility == 'project' else 'root'
    try:
        written = context.add(ledger, selector, key=key, extra=extra, expect_latest=base, subject_scope=subject,
                              lifecycle_target=ledger_id(key, visibility, state['task_id']) if base is not None and _lifecycle is None else None, **common)
    except context.ContextConflict as conflict:
        extra = dict(extra, conflict_with=[ledger_id(key, visibility, state['task_id'])], base=base)
        conflict_key = f'{key}.c{content_hash([text, base, conflict.current])[:8]}'
        written = context.add(ledger, selector, key=conflict_key, extra=extra, subject_scope=subject, **common)
        return dict(written, id=ledger_id(written['key'], visibility, state['task_id']), version=written['id'], conflict=True, current=conflict.current)
    return dict(written, id=ledger_id(written['key'], visibility, state['task_id']), version=written['id'])


def _target(ledger, ident):
    for r in records(ledger, history=True):
        if r['id'] == ident: return r
    return None


def withdraw(ledger, plan, target, *, reason, evidence):
    """Withdraw knowledge `target` (a ctx-/lesson-/wiki id) from the open root `plan`, with the evidence for it. The target's versions
    written before this record, its summaries and its copies are not delivered at the next retrieval; it stays in history. A general
    entry is withdrawn by its own project, with a general record every project reads."""
    text_field(reason, 'withdrawal reason', 1000)
    return _lifecycle_record(ledger, plan, target, 'withdraws', reason, dict(evidence, status=evidence.get('status', 'observed')))


def _subject_scopes(ledger, key):
    """The scopes in which this project holds versions of the project-visible subject `ctx-<key>` (2.3 records of visibility project;
    lifecycle records, root working notes `ctx-<key>.r<root>` and 2.2 entries are other subjects; review dev6 D5)."""
    with ledger.transaction() as conn:
        rows = conn.execute("SELECT DISTINCT json_extract(e.payload,'$.scope') AS scope FROM tasks t JOIN events e ON e.task_id=t.id WHERE t.project_id=? "
                            "AND e.kind='context.entry' AND json_extract(e.payload,'$.key')=? AND json_extract(e.payload,'$.knowledge.visibility')='project' "
                            "AND json_extract(e.payload,'$.knowledge.withdraws') IS NULL AND json_extract(e.payload,'$.knowledge.archives') IS NULL",
                            (ledger.project_id, key)).fetchall() if conn else []
    return {row['scope'] for row in rows}


def _key_in_other_scope(ledger, key, scope):
    """Would a record under `key` in `scope` put a second scope under one subject? (the subject exists in the other scope only)"""
    scopes = _subject_scopes(ledger, key)
    return bool(scopes) and scope not in scopes


def _lifecycle_record(ledger, plan, target, verb, reason, evidence):
    """One withdraw/archive record. A general entry: only its own project, with a general record every project reads (r2 N2). A wiki
    entry: the record keeps the text it had, so a corrected section lives again (r2 P3a). Review dev6 R1: our own subject named as another
    project shows it (`<id>@<our tag>`) is our subject; an id that names no record is refused, never recorded as done. R7 (data written
    before the key rule): a subject of this project that also has a general version is withdrawn for every project."""
    own = project_tags(ledger).get(ledger.project_id)
    if own and isinstance(target, str) and target.endswith('@' + own): target = target[:-(len(own) + 1)]
    found = _target(ledger, target)
    words = {'withdraws': 'Withdraws', 'archives': 'Archives'}[verb]
    done = {'withdraws': 'withdrawn', 'archives': 'archived'}[verb]
    life = {verb: target, 'reason': reason}
    if found is None:
        wiki_entry = next((c for c in _wiki_candidates(ledger, []) if c['id'] == target), None)
        if wiki_entry is not None: life['text_sha'] = _text_sha(wiki_entry['text'])
        elif not (isinstance(target, str) and target.startswith('lesson-') and '@' not in target and _lesson_exists(ledger, target[len('lesson-'):])):
            raise LedgerError(f'{target} names no knowledge record, lesson or wiki section of this project (`onecrew wiki history` and `onecrew '
                              f'wiki pages` list the ids); a general record of another project is {done} in that project, under the id it has '
                              'there (ctx-<key>).')
    if found is not None and found['project'] != ledger.project_id:
        plain = found['id'].rsplit('@', 1)[0] if '@' in found['id'] else found['id']
        raise LedgerError(f'only the project that wrote a general entry can {verb[:-1]} it: run this in that project, where its id is {plain}.')
    if (found is not None and found['scope'] != 'general' and found['id'].startswith('ctx-') and found.get('visibility') == 'project'
            and 'general' in _subject_scopes(ledger, found['id'][4:])):
        # review dev6 R7/D4: data written before the key rule, one subject with a general version too. The owner's record keeps the sources
        # and reason a project record takes; a neutral general record carries the withdrawal to every project.
        own_record = record(ledger, plan, kind='note', text=f'{words} {target}: {reason}', evidence=evidence, visibility='project', _lifecycle=life)
        with ledger.transaction() as conn:
            anchor = conn.execute('SELECT MIN(seq) FROM events WHERE task_id=?', (_open_root(ledger, plan)[0]['task_id'],)).fetchone()[0]
        shared = record(ledger, plan, kind='note', text=f'{words} {target}: {done} by its project', visibility='project', scope='general',
                        evidence={'status': 'observed', 'sources': [{'type': 'event', 'id': anchor}]},
                        conditions=['lifecycle record of a general entry'], _lifecycle={verb: target, 'reason': f'{done} by its project'})
        return dict(own_record, published=shared.get('id'))
    if found is not None and found['scope'] == 'general':
        return record(ledger, plan, kind='note', text=f'{words} {target}: {reason}', evidence=evidence, visibility='project', scope='general',
                      conditions=['lifecycle record of a general entry'], _lifecycle=life)
    return record(ledger, plan, kind='note', text=f'{words} {target}: {reason}', evidence=evidence, visibility='project', _lifecycle=life)


def _lesson_exists(ledger, logical):
    """Does this project hold a lesson with this logical id (the lessons store)?"""
    with ledger.transaction() as conn:
        row = conn.execute("SELECT 1 FROM tasks t JOIN events e ON e.task_id=t.id WHERE t.project_id=? AND e.kind='learning.lesson' "
                           "AND json_extract(e.payload,'$.lesson')=? LIMIT 1", (ledger.project_id, logical)).fetchone() if conn else None
    return row is not None


def archive(ledger, plan, target, *, reason):
    """Archive `target`: not delivered any more, kept with its sources; the record cites the root's own anchor event."""
    text_field(reason, 'archive reason', 1000)
    with ledger.transaction() as conn:
        root = namespaces.resolve(ledger, conn, plan)
        if root is None: raise LedgerError(f'No plan named {plan}.')
        anchor = conn.execute('SELECT MIN(seq) FROM events WHERE task_id=?', (root['id'],)).fetchone()[0]
    return _lifecycle_record(ledger, plan, target, 'archives', reason, {'status': 'observed', 'sources': [{'type': 'event', 'id': anchor}]})


def records(ledger, *, history=False, root=None):
    """Every ledger knowledge record of the project as the project sees it (status after lifecycle records visible to the project, or
    to `root` too), lifecycle records excluded; `history` keeps withdrawn/archived/superseded ones (the ledger always keeps them)."""
    problems, lifecycle = [], []
    candidates = _ledger_candidates(ledger, problems, lifecycle)
    cons = {'root': root} if root else None
    withdrawn = _withdrawn_lessons(ledger)
    status = _lifecycle(candidates, lifecycle, withdrawn, cons, ledger.project_id)
    status.pop('__hidden_superseders__', None)
    newest_life = {}
    for record in sorted(lifecycle, key=lambda r: r['event']):
        target = record.get('withdraws') or record.get('archives')
        if target and _acts_for(record, cons, ledger.project_id): newest_life[target] = record
    by_id = {c['id']: c for c in candidates}
    states = {c['id']: _state_of(status, c) for c in candidates}
    if root is None:                                   # Codex P2-01: a root's working memory as that root sees it (its own supersession,
        for owner in sorted({c['root'] for c in candidates if c['visibility'] == 'root' and c['root']}):      # withdrawal, archiving)
            own = {'root': owner}
            seen = _lifecycle(candidates, lifecycle, withdrawn, own, ledger.project_id)
            seen.pop('__hidden_superseders__', None)
            for c in candidates:
                if c['visibility'] == 'root' and c['root'] == owner: states[c['id']] = _state_of(seen, c)
            for record in sorted(lifecycle, key=lambda r: r['event']):
                target = record.get('withdraws') or record.get('archives')
                if target in by_id and by_id[target]['visibility'] == 'root' and by_id[target]['root'] == owner and _acts_for(record, own, ledger.project_id):
                    newest_life[target] = record
    changed = True
    while changed:
        changed = False
        for c in candidates:
            if states[c['id']][0] == 'active' and any(states.get(d, ('active',))[0] != 'active' or _summarized_withdrawn(status, d, c)
                                                      for d in c['derived_from'] if d in by_id):
                states[c['id']] = ('source_withdrawn', 'derived from knowledge that is not live'); changed = True
    out = []
    for c in candidates:
        state = states[c['id']]
        if state[0] != 'active' and not history: continue
        out.append({'id': c['id'], 'text': c['text'], 'kind': c['kind'], 'label': c['label'], 'visibility': c['visibility'], 'scope': c['scope'],
                    'status': state[0], 'status_reason': state[1], 'evidence': c.get('evidence') or {'status': c['label']},
                    'sources': c['sources'], 'derived_from': c['derived_from'], 'supersedes': c['supersedes'], 'applies_to': c['applies_to'],
                    'conditions': c['conditions'], 'must': c['must'], 'conflict_with': c.get('conflict_with') or [], 'root': c['root'],
                    'project': c['project'], 'event': c['seq'], 'version': c.get('version'), 'scope_paths': c['scope_paths'],
                    # r3 R3-3: what an update names as --base: the withdrawal/archive record when it is the subject's newest state
                    'state_version': (newest_life[c['id']]['version'] if c['id'] in newest_life and newest_life[c['id']]['event'] > c['seq']
                                      else c.get('version'))})
    return out


GONE = ('withdrawn', 'archived', 'superseded', 'source_withdrawn')


LIFECYCLE_REASONS = ('contested', 'contradicted', 'superseded by')


def for_root(ledger, plan, *, memo=None, revision=None):
    """Codex P2-01: the root's OWN ledger knowledge judged by the same code as a package (`_collect` on the plan consumer), for the
    readers that show it to an agent continuing that root (the resume pack, `context retrieve`). `plan`: a selector or the root's task
    id. The root wrote these entries, so the files they cite do not hide them from it; other roots and projects stay out exactly as in a
    package (of another root only the fact that it replaced a subject is told, never its text). A 2.2 entry keeps the 2.2 rule for its
    source (context._stale_reason: the cited line or symbol, review r1 F11); only lifecycle, contest and contradiction act on it.
    `revision` (a commit-ish, `context retrieve --revision`): applicability is judged on that commit's files (review r1 F12, r2 R2-01;
    the wiki pages themselves are read from the working tree). `memo`: one reading shared by several roots of one command (and the
    verdicts of a root already judged in it).
    Codex dev3 review P2: the shared (general) records are judged here too, for this reader, by the same decision (applicability,
    certainty), so that `context retrieve` never shows one whose condition is false or cannot be checked as current. `plan` None: the
    reader is the project without a root (no paths, no node; its environment is this process): only the general records are judged.
    id -> {'gone': lifecycle state or None, 'stale': reason or None, 'use', 'event', 'root', 'version' and 'scope' of the record judged}."""
    if plan is None:
        return _for_reader(ledger, {'project': ledger.project_id, 'plan': None, 'root': None, 'node': None, 'paths': [], 'terms': '',
                                    'environment': _environment(), 'own_root': True}, memo, revision)
    if str(plan).startswith('TASK-'):                  # a root named by its task id: its exact selector, never an ambiguous bare name
        with ledger.transaction() as conn:
            row = conn.execute('SELECT request_key FROM tasks WHERE id=? AND project_id=?', (plan, ledger.project_id)).fetchone() if conn else None
        if row is None: raise LedgerError(f'No root {plan} in this project.')
        plan = row['request_key']
    return _for_reader(ledger, dict(consumer(ledger, plan), own_root=True), memo, revision)


def _for_reader(ledger, cons, memo, revision):
    key = ('verdicts', cons['root'], revision)
    if memo is not None and key in memo: return memo[key]
    view = RevisionView(ledger.project, context.resolve_revision(ledger.project, revision)) if revision else None
    candidates = _collect(ledger, cons, view, memo)[0]
    out = {}
    for c in candidates:
        if c['origin']['type'] != 'ledger' or (c['visibility'] == 'root' and c['root'] != cons['root']): continue
        shared = c['scope'] == 'general'
        if cons['root'] is None and not shared: continue
        excluded, applicability = c.get('excluded'), c.get('applicability') or {'state': None, 'reasons': []}
        base = {'event': c['seq'], 'root': c['root'], 'use': c.get('use'), 'version': c.get('version'), 'scope': c['scope']}
        if excluded in GONE: out[c['id']] = dict(base, gone=excluded, stale=None); continue
        if not shared and c['root'] != cons['root']:   # review r1 F7: the newest version of this subject is another root's
            out[c['id']] = dict(base, gone=None, use=None, stale='a newer version of this subject was recorded by another root '
                                                                  f'(event {c["seq"]}); `onecrew wiki show` gives what applies now')
            continue
        reasons = applicability['reasons']
        if c.get('evidence') is None:
            reasons = [r for r in reasons if str(r).startswith(LIFECYCLE_REASONS)]
            stale = '; '.join(reasons)[:300] or None
        elif excluded == 'not_applicable': stale = 'not applicable now: ' + '; '.join(reasons)[:300]
        elif applicability['state'] == 'recheck': stale = '; '.join(reasons)[:300] or 'to recheck'
        elif c.get('use') == 'lead' and c['label'] in ('verified', 'refuted'):
            stale = 'cannot be checked now: ' + ('; '.join(reasons)[:300] or str(applicability['state']))
        else: stale = None
        out[c['id']] = dict(base, gone=None, stale=stale)
    if memo is not None: memo[key] = out
    return out


def status_by_id(ledger):
    """knowledge id -> lifecycle status of every ledger record of the project (active, withdrawn, archived, superseded, source_withdrawn)."""
    return {r['id']: r['status'] for r in records(ledger, history=True)}


def summarize(ledger, plan, sources, *, text, visibility=None):
    """A summary of knowledge `sources` (ids): its label is the weakest of theirs, it inherits their conditions, scope and pins, its
    meaning is unverified (nobody checked it against the sources), and it keeps `derived_from` so withdrawal and inapplicability reach it."""
    known = {r['id']: r for r in records(ledger, root=_open_root(ledger, plan)[0]['task_id'])}
    missing = [s for s in sources if s not in known]
    if missing or not sources: raise LedgerError('summarize: live knowledge ids are required (' + ', '.join(missing) + ').')
    labels = [known[s]['label'] for s in sources]
    weakest = min(labels, key=lambda label: RANK.get(label, 0))
    if any(label == 'refuted' for label in labels) and any(label != 'refuted' for label in labels): weakest = 'hypothesis'
    visibility = visibility or ('root' if any(known[s]['visibility'] == 'root' for s in sources) else 'project')
    applies = sorted({a for s in sources for a in known[s]['applies_to']})
    files = [src for s in sources for src in known[s]['sources'] if src.get('path') and src.get('role') != 'applies']
    anchors = [src for s in sources for src in known[s]['sources'] if src['type'] in ('event', 'receipt')]
    conditions, seen = [], set()
    for s in sources:
        for c in known[s]['conditions']:
            if canonical(c) not in seen: seen.add(canonical(c)); conditions.append(c)
    evidence = {'status': weakest if weakest in EVIDENCE_STATUS else 'hypothesis', 'sources': (anchors[:1] + files)[:10],
                'property': 'summary of ' + ', '.join(sources) if weakest == 'verified' else None, 'semantic_verification': 'unverified'}
    return record(ledger, plan, kind='summary', text=text, evidence=evidence, applies_to=applies, derived_from=list(sources), visibility=visibility,
                  conditions=conditions, scope_paths=sorted({p for s in sources for p in known[s]['scope_paths']}))


def export(ledger, folder):
    """Write the live PROJECT knowledge of the ledger as one Markdown page (a derived view, never a second source): every section keeps
    the ledger id it copies (and its conditions and `must`), so a copy committed into the wiki is matched to its ledger lifecycle."""
    folder = Path(folder); folder.mkdir(parents=True, exist_ok=True)
    rows = [r for r in records(ledger) if r['visibility'] == 'project' and r['scope'] == 'project']
    lines = ['# Tri thức project (xuất từ sổ OneCrew — bản dẫn xuất, không phải nguồn riêng)', '']
    for r in rows:
        meta = {'id': 'copy-' + re.sub(r'[^A-Za-z0-9_.-]', '-', r['id'])[:70], 'kind': r['kind'],
                'label': r['label'] if r['label'] in wiki.LABELS else 'unverified', 'must': r['must'], 'applies_to': r['applies_to'],
                'sources': [{k: v for k, v in s.items() if k != 'role'} for s in r['sources'] if s['type'] in wiki.SOURCE_TYPES],
                'conditions': r['conditions'], 'derived_from': r['derived_from'], 'ledger_id': r['id']}
        lines += [f'## {r["text"][:80]}', '```onecrew', json.dumps(meta, ensure_ascii=False), '```', r['text'], '']
    page = folder / 'onecrew-export.md'
    page.write_text('\n'.join(lines), encoding='utf-8')
    return {'pages': [str(page)], 'entries': len(rows), 'derived_view': True}


# ---- 2.3-A2: the engine path: claims at finish, promotion at a passing verification --------------------------------------------

def validate_claims(node, claims, files):
    """(accepted, refused) claims of one attempt: a claim's sources must be files of the node's scope and present in the candidate it was
    made on; the rest is refused with a reason that goes in the receipt (review r1 #15)."""
    scope = sorted(set(node.get('read') or []) | set(node.get('write') or []))
    accepted, refused = [], []
    for claim in claims or []:
        outside = [p for p in claim.get('sources', []) + _concrete(claim.get('applies_to', [])) if not _readable(scope, p)]
        absent = [p for p in claim.get('sources', []) if p not in (files or {})]
        if outside: refused.append({'text': claim['text'][:120], 'reason': 'outside the node scope: ' + ', '.join(outside[:3])})
        elif absent: refused.append({'text': claim['text'][:120], 'reason': 'not in the candidate: ' + ', '.join(absent[:3])})
        else: accepted.append(claim)
    return accepted, refused


def _claim_sources(ledger, claim, files):
    pins = []
    for path in claim.get('sources', []):
        if isinstance(files.get(path), str):
            pins.append({'type': 'file', 'path': path, 'blob': blob_of(ledger, path, files[path].encode('utf-8'))})
    return pins


def record_claims(ledger, selector, node, receipt, claims, files):
    """A worker's accepted claims (knowledge.new) as observations of its root, citing the attempt receipt, pinned to the candidate the
    worker saw (`files`), bounded by the node's read ∪ write scope. Nothing is verified by being claimed."""
    written = []
    scope = sorted(set(node.get('read') or []) | set(node.get('write') or []))
    for claim in claims or []:
        try:
            out = record(ledger, selector, kind=claim['kind'], text=claim['text'], applies_to=claim.get('applies_to', []), visibility='root',
                         scope_paths=scope, files=files, basis='worker claim (observation)',
                         evidence={'status': 'observed', 'sources': [{'type': 'receipt', 'key': receipt}] + _claim_sources(ledger, claim, files)})
            written.append(out['id'])
        except LedgerError:
            continue
    return written


def _chain_receipts(ledger, selector, nid, produced_receipt, verification_receipt=None):
    """The native receipts of the verified attempt and of the partial attempts it continued, following `continues_attempt` back (r2 N3):
    a retained candidate that was discarded and never continued is not part of it."""
    from ..snapshots import Snapshots
    store = Snapshots(ledger.state_root)
    with ledger.transaction() as conn:
        root = namespaces.resolve(ledger, conn, selector) if conn else None
        rows = conn.execute("SELECT payload FROM events WHERE task_id=? AND kind='node.result_retained' AND json_extract(payload,'$.node')=? ORDER BY seq",
                            (root['id'], nid)).fetchall() if root is not None else []
    retained = {}
    for row in rows:
        payload = json.loads(row['payload'])
        if payload.get('attempt') and isinstance(payload.get('candidate'), dict) and payload['candidate'].get('receipt'):
            retained[payload['attempt']] = payload['candidate']['receipt']
    out, receipt = [produced_receipt], produced_receipt
    for _ in range(50):
        try:
            previous = json.loads(store.read_blob(receipt)).get('continues_attempt')
        except (LedgerError, OSError, ValueError, TypeError):
            break
        if not previous or previous not in retained or retained[previous] in out: break
        receipt = retained[previous]; out.append(receipt)
    return out


def after_verification(ledger, selector, nid, produced_receipt, verification_receipt, body, item):
    """The node passed its checks: each claim whose `check` passed in THIS verification becomes PROJECT knowledge — verified for the
    property that check states on that artifact (delivered with it), cause not established, pinned to the verified artifact, bounded by the
    node's scope — superseding the observation; each delivered entry the worker rejected gets a project-visible contradiction (an
    observation, not a proof that the entry is wrong). Claims of the partial attempts of a continuation count too. Returns the ids written."""
    from ..snapshots import Snapshots
    store = Snapshots(ledger.state_root)
    passed = {row.get('id') for row in (body.get('observed') or {}).get('checks', []) if isinstance(row, dict) and row.get('result') == 'pass'}
    specs = {c['id']: c.get('spec', '') for c in item.get('checks') or []}
    scope = sorted(set(item.get('read') or []) | set(item.get('write') or []))
    try:
        files = store.context(body['artifact'])
    except (LedgerError, OSError, ValueError, TypeError, KeyError):
        files = {}
    with ledger.transaction() as conn:
        root = namespaces.resolve(ledger, conn, selector)
    observations = {(r['text'], r['root']): r['id'] for r in records(ledger, root=root['id']) if r['visibility'] == 'root'}
    written, seen = [], set()
    for receipt in _chain_receipts(ledger, selector, nid, produced_receipt, verification_receipt):
        try:
            native = json.loads(store.read_blob(receipt))
        except (LedgerError, OSError, ValueError, TypeError):
            continue
        if native.get('kind') != 'native-node-receipt': continue
        for claim in native.get('knowledge_claims') or []:
            check = claim.get('check')
            if not check or check not in passed or claim['text'] in seen: continue
            seen.add(claim['text'])
            evidence = {'status': 'verified', 'property': f'check {check} ("{specs.get(check, "")[:200]}") passed on artifact {body["artifact"][:12]}',
                        'sources': [{'type': 'receipt', 'key': verification_receipt}, {'type': 'receipt', 'key': receipt}] + _claim_sources(ledger, claim, files)}
            obs = observations.get((claim['text'], root['id']))
            try:
                out = record(ledger, selector, kind=claim['kind'], text=claim['text'], applies_to=claim.get('applies_to', []), visibility='project',
                             evidence=evidence, scope_paths=scope, files=files, supersedes=[obs] if obs else [],
                             basis='worker claim supported by a passing check; the check proves its property, not every word of the claim')
                written.append(out['id'])
            except LedgerError:
                continue
        for rejected in (native.get('knowledge_use') or {}).get('rejected_by_worker') or []:
            if rejected['id'] not in (native.get('knowledge') or {}).get('delivered', []): continue
            judged = _current_id(ledger, store, native.get('knowledge') or {}, rejected['id'])
            try:
                out = record(ledger, selector, kind='finding', text=f'The worker of node {nid} rejected {rejected["id"]}: {rejected["why"][:400]}',
                             visibility='project', contradicts=[judged], scope_paths=scope,
                             evidence={'status': 'observed', 'sources': [{'type': 'receipt', 'key': receipt}, {'type': 'receipt', 'key': verification_receipt}]})
                written.append(out['id'])
            except LedgerError:
                continue
    return written


# ---- the read-only CLI (onecrew wiki ...) ------------------------------------------------------------------------------------

def node_of(ledger, plan, node_id):
    """The node `node_id` of the plan's current internal definition (engine roots)."""
    from . import engine, internal_plan
    with ledger.transaction() as conn:
        root, _, _ = internal_plan.context(ledger, conn, plan, 'sequential-engine')
        view = engine.state(ledger, root['selector'], conn)
    found = next((n for n in view['definition']['nodes'] if n['id'] == node_id), None)
    if found is None: raise LedgerError(f'No node {node_id} in the internal plan of {plan}.')
    return found


def pages_report(ledger):
    """Every page with the ids, kinds and labels it yields, and every problem (bad metadata, unreadable pages); `coverage`: what was not
    read and the mandatory sections that cannot be delivered (P2-02)."""
    coverage = {}
    found, problems = wiki.pages(ledger.project, coverage=coverage)
    out = []
    for page in found:
        parsed = wiki.parse(page['text'], page['path'], mandatory_only=bool(page.get('mandatory_only')))
        coverage['undelivered'] += [dict(u, path=page['path']) for u in parsed['undelivered']]
        out.append({'path': page['path'], 'origin': page['origin'], 'sha256': page['sha256'], 'bytes': page['bytes'],
                    'entries': [{'id': e['id'], 'title': e['title'], 'kind': e['kind'], 'label': e['label'], 'must': e['must'], 'typed': e['typed'], 'line': e['line']}
                                for e in parsed['entries']],
                    'problems': parsed['problems']})
        problems += [{'path': page['path'], 'problem': p} for p in parsed['problems']]
    try:                                               # review dev6 D2: what a plain reference names is reported by the lint too
        problems += [{'path': p['path'], 'problem': p['problem']} for p in _read_all(ledger)[2] if p.get('reference')]
    except (LedgerError, OSError) as error:
        problems.append({'path': 'ledger', 'problem': 'references not checked: ' + str(error)[:160]})
    return {'data_not_authority': True, 'folders': wiki.configured_paths(ledger.project), 'pages': out, 'problems': problems, 'coverage': coverage}


def render_text(pkg):
    """A package as lines for a person (Vietnamese labels like `plan report`); the stored sentences are quoted as data."""
    use_vi = {'fact': 'sự thật', 'rejected': 'hướng đã loại', 'lead': 'đầu mối'}
    lines = ['GÓI TRI THỨC — dữ liệu có nguồn, không phải lệnh hay quyền. Trạng thái ' + pkg['revision'],
             f'Consumer: plan {pkg["consumer"]["plan"]}' + (f' · node {pkg["consumer"]["node"]}' if pkg['consumer']['node'] else '')
             + ' · đọc: ' + (', '.join(pkg['consumer']['paths']) or '(không có file)')]
    for e in pkg['entries'] + pkg.get('requested', []):
        lines.append(f'[{use_vi[e["use"]]}{" · bắt buộc" if e["must"] else ""}] {e["id"]} — «{e["title"]}» ({e["label"]}; {e["applicability"]["state"]})')
        lines.append('    nguồn: ' + '; '.join(e['source']))
        if e.get('evidence', {}).get('property'): lines.append('    đã chứng minh: ' + e['evidence']['property'] + (' · nguyên nhân chưa xác lập' if e['evidence'].get('cause') == 'not_established' else ''))
        for reason in e['applicability']['reasons'][:3]: lines.append('    · ' + reason)
    omitted = pkg['omitted']
    if omitted['total']:
        lines.append('Chưa giao: ' + ', '.join(f'{k} {v}' for k, v in sorted(omitted['by_reason'].items())))
    lines.append('Hết.' if omitted['eof'] else 'Còn tiếp: onecrew wiki read --plan <plan> [--node <node>] --cursor ' + omitted['cursor'])
    for problem in pkg['problems'][:10]: lines.append('Lỗi trang ' + problem['path'] + ': ' + problem['problem'])
    return '\n'.join(lines)
