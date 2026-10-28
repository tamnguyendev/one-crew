"""2.3-A1 — what one consumer may use from the project's knowledge, chosen and delivered by code, never by a model.

Two sources, one entry model (docs/v23/HOP-DONG-2.3.vi.md §3):
  * the project's wiki pages (wiki.pages / wiki.parse: Markdown sections, typed by an optional `onecrew` block);
  * the ledger's context entries (context.retrieve with limit=None, lessons already refined: withdrawn ones are gone).

For a consumer — a root, and usually one node of it with its read/write files — every candidate goes through, in order:
  1. permission: project boundary (the ledger reader already keeps other projects out; general entries follow the old rule); an entry
     of another root is used only when it was published for the project (`visibility: project`, lessons) — a root's working memory stays
     with that root; every file a source cites must be inside the consumer's read scope (otherwise it is not delivered and not named);
  2. status: withdrawn / superseded / archived entries are history, never delivered;
  3. applicability at the current state (MEM-01): a cited file whose content differs from the revision the entry was recorded against
     (committed or not) makes the entry `recheck`; a checkable condition that is false makes it `not_applicable`; a condition that cannot
     be checked here makes it `unknown`. Nothing ages by a timer, and an unchanged entry is used again as it is;
  4. use: verified + applies = `fact`; refuted + applies = `rejected` (an approach already shown not to work here); everything else is a
     `lead` — data to check before relying on it (a refuted conclusion whose source changed is a lead again, its history kept);
  5. relevance to the task: the files (applies_to / sources against read ∪ write) and the words of the node and the plan;
  6. the character cap: mandatory entries (`must`, relevant to the consumer's files or project-wide) go first and are never cut — when they
     do not fit, the package is refused (KnowledgeOverflow) so the caller stops BEFORE a model call; optional ones follow by relevance
     until the cap; the rest is listed (ids and titles of what the consumer may read, counts by reason for everything) with a cursor to
     the next page. A cursor belongs to one knowledge state: any change to a page or an entry makes it stale and it is refused.

The package is DATA, not authority (it says so). It records what was delivered; it does not prove the worker understood or used it
correctly: `check_use` compares the worker's declaration with the delivery (structural), and the node's checks judge the result. A1
writes no knowledge: reading and delivering leave pages and entries as they were.
"""
import base64
import fnmatch
import json
import math
import re
import sys
import time
from pathlib import Path

from ..ledger import LedgerError, canonical, content_hash
from . import context, namespaces, plan as plans, wiki
from .verifiers import command

VERSION = 1
NATIVE_CAP_CHARS = 12000          # the knowledge part of a native prompt; the whole prompt keeps its own 80000 cap
ENTRY_TEXT_CHARS = 1600           # text of one entry in a page; longer text is marked truncated, the whole of it can be requested
INDEX_ROWS = 30
NOTICE = context.NOTICE
POLICY = ('facts: still applicable at this state, rely on them; rejected: approaches already shown not to work here, do not retry them unless '
          'their conditions changed; leads: unverified, historical or not checkable now, check the cited source before relying on them. '
          'Answer knowledge.used with the ids you relied on, knowledge.rejected with [{id, why}] for any entry you found wrong, and '
          'knowledge.requests with omitted ids you need (only together with a continuation).')
STOP = frozenset('the and for with that this from into are was were has have had not but you your our its their them then than there '
                 'what when which who will would should could can may might must also only just some any all each per via use used using '
                 'của và các những một cho với không được trong khi này đó là có thì đã sẽ để từ theo'.split())
KIND_WEIGHT = {'constraint': 3.0, 'decision': 2.0, 'rejected': 2.0, 'lesson': 2.0, 'finding': 1.5, 'summary': 1.0, 'note': 0.5}
SCHEMA = {'type': 'object', 'additionalProperties': False, 'properties': {
    'used': {'type': 'array', 'items': {'type': 'string'}},
    'rejected': {'type': 'array', 'items': {'type': 'object', 'additionalProperties': False, 'required': ['id', 'why'],
                                            'properties': {'id': {'type': 'string'}, 'why': {'type': 'string'}}}},
    'requests': {'type': 'array', 'items': {'type': 'string'}}}}


class KnowledgeOverflow(LedgerError):
    """Mandatory knowledge does not fit the cap: run nothing with partial constraints."""


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
    else:
        target = (contract.get('understanding') or {}).get('target') or {}
        paths = sorted(set(target.get('paths') or []) | set((contract.get('scope') or {}).get('owned') or []))
    environment = {'platform': sys.platform, 'python': '%d.%d' % sys.version_info[:2]}
    if pin: environment.update(provider=pin.get('provider'), model=pin.get('model'))
    return {'project': ledger.project_id, 'plan': root['request_key'], 'root': root['id'], 'node': node['id'] if node else None,
            'paths': [p.replace('\\', '/') for p in paths], 'terms': ' '.join(w for w in words if w), 'environment': environment}


def _covers(pattern, path):
    pattern = pattern.replace('\\', '/')
    if pattern.endswith('/'): return path.startswith(pattern)
    if any(c in pattern for c in '*?['): return fnmatch.fnmatchcase(path, pattern)
    return path == pattern or path.startswith(pattern + '/')


def _readable(paths, path):
    return any(_covers(p, path) for p in paths)


# ---- the current state of the project, read once per package ------------------------------------------------------------------

class _State:
    def __init__(self, ledger):
        self.ledger, self.project = ledger, Path(ledger.project)
        self.texts, self.revisions, self.blobs = {}, {}, {}

    def current(self, path):
        """The working-tree bytes of a repository file (what the next worker sees), None when absent."""
        if path not in self.texts:
            try:
                self.texts[path] = (self.project / path).read_bytes()
            except OSError:
                self.texts[path] = None
        return self.texts[path]

    def blob_at(self, revision, path):
        """The git blob id of `path` at a commit-ish, None when it is not there; LedgerError when the revision does not resolve."""
        if revision not in self.revisions:
            try:
                self.revisions[revision] = context.resolve_revision(self.ledger.project, revision)
            except LedgerError:
                self.revisions[revision] = None
        commit = self.revisions[revision]
        if commit is None: raise LedgerError(f'revision {revision} does not resolve')
        key = ('at', commit, path)
        if key not in self.blobs:
            try:
                self.blobs[key] = command._git(self.ledger.project, 'rev-parse', '--verify', '-q', f'{commit}:{path}') or None
            except LedgerError:
                self.blobs[key] = None
        return self.blobs[key]

    def blob(self, path):
        """The blob id the working-tree file would have (git hash-object applies the same filters as a commit), None when absent."""
        key = ('now', path)
        if key not in self.blobs:
            if self.current(path) is None:
                self.blobs[key] = None
            else:
                try:
                    self.blobs[key] = command._git(self.ledger.project, 'hash-object', '--', path) or None
                except LedgerError:
                    self.blobs[key] = None
        return self.blobs[key]


def _source_state(state, source, recorded_revision=None):
    """('unchanged'|'changed'|'unknown', reason) of one cited file against the revision the entry was recorded at."""
    path = source.get('path')
    if not path: return 'unchanged', None                       # an event or a receipt is immutable; a url is not a source we check
    revision = source.get('revision') or recorded_revision
    now = state.blob(path)
    if source.get('blob'):
        if now is None: return 'changed', f'{path} no longer exists'
        return ('unchanged', None) if now == source['blob'] else ('changed', f'{path} changed since blob {source["blob"][:12]}')
    if not revision: return 'unknown', f'{path}: no revision or blob recorded, the source cannot be checked'
    try:
        then = state.blob_at(revision, path)
    except LedgerError as error:
        return 'unknown', f'{path}: {error}'
    if then is None and now is None: return 'unknown', f'{path} exists neither at {revision[:12]} nor now'
    if now is None: return 'changed', f'{path} no longer exists'
    if then is None: return 'unknown', f'{path} is not in {revision[:12]}'
    return ('unchanged', None) if then == now else ('changed', f'{path} changed since {revision[:12]}')


def _condition_state(state, condition, environment):
    kind = condition.get('type')
    if kind == 'file_contains':
        data = state.current(condition['path'])
        if data is None: return False, f'{condition["path"]} is absent'
        found = condition['text'] in data.decode('utf-8', 'replace')
        return found, None if found else f'{condition["path"]} no longer contains {condition["text"][:60]!r}'
    if kind == 'file_unchanged':
        import hashlib
        data = state.current(condition['path'])
        same = data is not None and hashlib.sha256(data).hexdigest() == condition['sha256']
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
    for source in entry['sources']:
        verdict, why = _source_state(state, source, entry.get('recorded_revision'))
        if verdict == 'changed': changed = True; reasons.append(why)
        elif verdict == 'unknown': unknown = True; reasons.append(why)
    if entry.get('ledger_stale'): changed = True; reasons.append(entry['ledger_stale'])
    checkable = any(s['type'] in wiki.CHECKABLE for s in entry['sources'])
    if not checkable and not entry['conditions']:
        return {'state': 'unknown', 'reasons': ['no checkable source']}
    return {'state': 'recheck' if changed else 'unknown' if unknown else 'applies', 'reasons': [r for r in reasons if r]}


# ---- candidates ----------------------------------------------------------------------------------------------------------------

def _wiki_candidates(ledger, problems):
    found, page_problems = wiki.pages(ledger.project)
    problems += page_problems
    out, seen = [], {}
    for page in found:
        parsed = wiki.parse(page['text'], page['path'])
        problems += [{'path': page['path'], 'problem': p} for p in parsed['problems']]
        for entry in parsed['entries']:
            if entry['id'] in seen:
                problems.append({'path': page['path'], 'problem': f'id {entry["id"]} is already used by {seen[entry["id"]]}; skipped'}); continue
            seen[entry['id']] = page['path']
            out.append({'id': entry['id'], 'origin': {'type': 'wiki', 'path': page['path'], 'sha256': page['sha256'], 'line': entry['line'],
                                                      'external': page['origin'] == 'external'},
                        'kind': entry['kind'], 'label': entry['label'], 'must': entry['must'], 'status': entry['status'], 'title': entry['title'],
                        'text': entry['text'], 'sources': entry['sources'], 'conditions': entry['conditions'], 'applies_to': entry['applies_to'],
                        'supersedes': entry['supersedes'], 'derived_from': entry['derived_from'], 'ledger_id': entry['ledger_id'],
                        'visibility': 'project', 'scope': 'project', 'root': None, 'seq': 0})
    return out


def _ledger_candidates(ledger, problems):
    try:
        entries = context.retrieve(ledger, scope='both', limit=None, raw=True)['entries']
    except (LedgerError, OSError) as error:
        problems.append({'path': 'ledger', 'problem': 'context entries unreadable: ' + str(error)[:160]}); return []
    out = []
    for e in entries:
        p = e.get('payload') or {}
        if e['kind'] == 'task_done': continue                     # engine progress bookkeeping; the node's inputs already carry provenance
        key = e['key']
        ident = key if key.startswith('lesson-') else 'ctx-' + key[:16]
        source = dict(e['source'])
        if source.get('type') in ('file_line', 'symbol') and p.get('revision_ref'): source.setdefault('revision', p['revision_ref'])
        visibility = p.get('visibility') or ('project' if key.startswith('lesson-') else 'root')
        out.append({'id': ident, 'origin': {'type': 'ledger', 'event': e['event'], 'key': key, 'scope': e['scope']},
                    'kind': 'lesson' if key.startswith('lesson-') else e['kind'] if e['kind'] in wiki.KINDS else 'note',
                    'label': e['stored_label'] if e['stored_label'] != 'stale' else 'observed', 'must': bool(p.get('must')),
                    'status': p.get('status') or 'active', 'title': e['text'][:80], 'text': e['text'],
                    'sources': [source], 'conditions': [c if isinstance(c, dict) else {'type': 'text', 'text': c} for c in (e.get('conditions') or [])],
                    'applies_to': p.get('applies_to') or [], 'supersedes': p.get('supersedes') or [], 'derived_from': p.get('derived_from') or [],
                    'ledger_id': e['id'], 'visibility': visibility, 'scope': e['scope'], 'root': p.get('task'),
                    'recorded_revision': p.get('revision_ref'), 'seq': e['event'],
                    'ledger_stale': e['stale_reason'] if e['label'] == 'stale' else None})
    return out


def _tokens(text):
    words = set()
    for token in re.findall(r'[\w]+(?:[./-][\w]+)*', str(text).casefold()):
        parts = [token] + re.split(r'[./-]', token)
        words.update(w for w in parts if len(w) >= 3 and w not in STOP and not w.isdigit())
        if '.' in token or '/' in token: words.add(token)
    return words


def _decide(ledger, cons, candidates):
    """Attach to every candidate: excluded (reason) or use/applicability/relevance. Pure code."""
    state = _State(ledger)
    by_id = {c['id']: c for c in candidates}
    superseded = {old for c in candidates if c['status'] == 'active' for old in c['supersedes'] if old in by_id}
    ledger_status = {c['ledger_id']: c for c in candidates if c['origin']['type'] == 'ledger'}
    for c in candidates:
        c['excluded'] = None
        if c['visibility'] == 'root' and c['root'] != cons['root']: c['excluded'] = 'root_private'; continue
        files = [s['path'] for s in c['sources'] if s.get('path')]
        if any(not _readable(cons['paths'], f) for f in files): c['excluded'] = 'source_outside_read_scope'; continue
        twin = ledger_status.get(c['ledger_id']) if c['origin']['type'] == 'wiki' and c['ledger_id'] else None
        if twin is not None and twin['status'] != 'active': c['status'] = twin['status']            # a copy never outlives its ledger state
        if c['status'] != 'active': c['excluded'] = c['status']; continue
        if c['id'] in superseded: c['excluded'] = 'superseded'; continue
        if c['derived_from'] and any(by_id.get(d, {}).get('status', 'active') != 'active' or d in superseded for d in c['derived_from']):
            c['excluded'] = 'source_withdrawn'; continue
        c['applicability'] = _applicability(state, c, cons['environment'])
        if c['applicability']['state'] == 'not_applicable': c['excluded'] = 'not_applicable'; continue
        applies = c['applicability']['state'] == 'applies'
        c['use'] = 'fact' if applies and c['label'] == 'verified' else 'rejected' if applies and c['label'] == 'refuted' else 'lead'
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


def _render(c, text_chars):
    text = c['text']
    if c['mandatory']: text_chars = len(text)                        # a mandatory entry is delivered whole or the package is refused
    out = {'id': c['id'], 'use': c['use'], 'must': c['mandatory'], 'kind': c['kind'], 'label': c['label'], 'title': c['title'][:160],
           'text': text[:text_chars], 'applicability': c['applicability'],
           'source': [_source_text(s) for s in c['sources']] or ['wiki page ' + c['origin'].get('path', '')],
           'origin': {k: v for k, v in c['origin'].items() if k in ('type', 'path', 'line', 'sha256', 'event')}}
    if c['applies_to']: out['applies_to'] = c['applies_to']
    if c['conditions']: out['conditions'] = c['conditions']
    if len(text) > text_chars: out['text_truncated'] = {'delivered': text_chars, 'total': len(text)}
    return out


def _source_text(s):
    if s['type'] == 'file_line': return f'{s["path"]}:{s["line"]}' + (f'@{s["revision"][:12]}' if s.get('revision') else '')
    if s['type'] == 'symbol': return f'{s["name"]} in {s["path"]}' + (f'@{s["revision"][:12]}' if s.get('revision') else '')
    if s['type'] == 'file': return s['path'] + (f'@{s["revision"][:12]}' if s.get('revision') else f' blob {s["blob"][:12]}' if s.get('blob') else '')
    if s['type'] == 'receipt': return 'receipt ' + s['key'][:16]
    if s['type'] == 'event': return f'event {s["id"]}'
    return s.get('url', '')[:200]


def _order(eligible):
    rank = lambda c: (-c['score'], -c['seq'], c['id'])
    must = sorted((c for c in eligible if c['mandatory']), key=rank)
    optional = sorted((c for c in eligible if not c['mandatory'] and c['relevant']), key=rank)
    rest = sorted((c for c in eligible if not c['mandatory'] and not c['relevant']), key=rank)
    return must, optional, rest


def _state_hash(cons, candidates):
    return content_hash({'consumer': {k: cons[k] for k in ('project', 'root', 'node', 'paths')}, 'version': VERSION,
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

def _build(ledger, cons, cap_chars, offset=0, requested=(), expect_revision=None):
    if type(cap_chars) is not int or cap_chars < 200: raise LedgerError('cap_chars: an integer of at least 200.')
    started = time.perf_counter()
    problems = []
    candidates = _wiki_candidates(ledger, problems)
    taken = {c['id'] for c in candidates}
    for c in _ledger_candidates(ledger, problems):
        if c['id'] in taken: problems.append({'path': 'ledger', 'problem': f'id {c["id"]} also names a wiki entry; the ledger entry is skipped'}); continue
        taken.add(c['id']); candidates.append(c)
    eligible = _decide(ledger, cons, candidates)
    revision = _state_hash(cons, candidates)
    if expect_revision is not None and expect_revision != revision:
        raise LedgerError('This cursor belongs to an older knowledge state (a page or an entry changed); retrieve the package again.')
    must, optional, rest = _order(eligible)
    text_chars = min(ENTRY_TEXT_CHARS, max(200, cap_chars // 2))
    delivered, room = [], cap_chars
    if offset == 0:
        rendered = [_render(c, text_chars) for c in must]
        need = sum(len(canonical(r)) for r in rendered)
        if need > cap_chars:
            raise KnowledgeOverflow(f'Mandatory knowledge needs {need} characters, over the cap of {cap_chars} '
                                    f'({", ".join(c["id"] for c in must)}); do not run with partial constraints.')
        delivered, room = rendered, cap_chars - need
    ordered = must + optional + rest                    # the cursor runs through every permitted entry: relevance orders, it never hides
    stop = len(must) + len(optional) if offset == 0 else len(ordered)          # the first page carries only mandatory and relevant ones
    position = max(offset, len(must))
    while position < stop:
        item = _render(ordered[position], text_chars)
        size = len(canonical(item))
        if size > room and (delivered or offset == 0 and must):
            break
        if size > room:                                 # a page that is not the last always delivers its first entry (cut to the room)
            item = _render(ordered[position], max(80, room - (size - len(item['text']))))
        delivered.append(item); room -= len(canonical(item)); position += 1
    requested_out, refused = [], []
    permitted = {c['id']: c for c in eligible}
    for ident in requested:
        if ident in permitted and ident not in {d['id'] for d in delivered}:
            requested_out.append(_render(permitted[ident], max(text_chars, cap_chars // max(1, len(requested)))))
        elif ident not in permitted:
            refused.append({'id': ident, 'reason': 'not_available'})
    left = ordered[position:]
    relevant = {id(c) for c in must + optional}
    by_reason = {}
    for c in candidates:
        reason = c['excluded']
        if reason: by_reason[reason] = by_reason.get(reason, 0) + 1
    capped = [c for c in left if id(c) in relevant]
    unrelated = [c for c in left if id(c) not in relevant]
    if capped: by_reason['cap'] = len(capped)
    if unrelated: by_reason['not_relevant'] = len(unrelated)
    index = [{'id': c['id'], 'title': c['title'][:80], 'use': c['use'], 'reason': 'cap'} for c in capped]
    index += [{'id': c['id'], 'title': c['title'][:80], 'use': c['use'], 'reason': 'not_relevant'} for c in unrelated]
    eof = not left
    package = {'kind': 'knowledge-package', 'version': VERSION, 'data_not_authority': True, 'notice': NOTICE, 'policy': POLICY,
               'consumer': {k: cons[k] for k in ('project', 'plan', 'node', 'paths')}, 'revision': revision,
               'entries': delivered, 'requested': requested_out, 'requests_refused': refused,
               'omitted': {'total': sum(by_reason.values()), 'by_reason': by_reason, 'index': index[:INDEX_ROWS],
                           'cursor': None if eof else _cursor(revision, position), 'eof': eof},
               'problems': problems[:30],
               'cost': {'candidates': len(candidates), 'eligible': len(eligible), 'seconds': round(time.perf_counter() - started, 4)}}
    return package


def package(ledger, cons, *, cap_chars=NATIVE_CAP_CHARS, requested=()):
    """The first page for `cons`. Raises KnowledgeOverflow when mandatory knowledge does not fit `cap_chars`."""
    return _build(ledger, cons, cap_chars, requested=tuple(requested))


def read(ledger, cons, cursor, *, cap_chars=NATIVE_CAP_CHARS):
    """The page after `cursor` (same consumer, same knowledge state; otherwise refused)."""
    revision, offset = _uncursor(cursor)
    return _build(ledger, cons, cap_chars, offset=offset, expect_revision=revision)


def prompt_view(pkg):
    """The part of a package a worker receives (the cost measurement stays out: it is not knowledge)."""
    return {k: v for k, v in pkg.items() if k != 'cost'}


def delivered_ids(view):
    return [e['id'] for e in view.get('entries', [])] + [e['id'] for e in view.get('requested', [])]


# ---- the worker's declaration ----------------------------------------------------------------------------------------------------

def split_declaration(value):
    """(declaration or None, value without it). The declaration is optional; a malformed one is refused like any malformed result."""
    if not isinstance(value, dict) or 'knowledge' not in value: return None, value
    rest = {k: v for k, v in value.items() if k != 'knowledge'}
    declared = value['knowledge']
    if not isinstance(declared, dict) or set(declared) - {'used', 'rejected', 'requests'}:
        raise LedgerError('knowledge: an object with used, rejected and requests only.')
    used, rejected, requests = declared.get('used', []), declared.get('rejected', []), declared.get('requests', [])
    if (not isinstance(used, list) or len(used) > 200 or not all(isinstance(i, str) and 0 < len(i) <= 120 for i in used)
            or not isinstance(requests, list) or len(requests) > 20 or not all(isinstance(i, str) and 0 < len(i) <= 120 for i in requests)
            or not isinstance(rejected, list) or len(rejected) > 50
            or not all(isinstance(r, dict) and set(r) == {'id', 'why'} and isinstance(r['id'], str) and isinstance(r['why'], str)
                       and 0 < len(r['id']) <= 120 and len(r['why']) <= 1000 for r in rejected)):
        raise LedgerError('knowledge: used/requests are lists of ids, rejected a list of {id, why}.')
    return {'used': used, 'rejected': rejected, 'requests': requests}, rest


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


def for_native(ledger, store, selector, node, pin):
    """(view, record) for one native attempt: `view` goes in the prompt (None when nothing is delivered), `record` in the receipt.
    KnowledgeOverflow propagates (the caller stops before the model call); any other failure of this layer is recorded and the node
    runs on its own inputs (a broken page or entry never blocks independent work)."""
    record = {'package': None, 'delivered': [], 'chars': 0, 'omitted_total': 0, 'problems': [], 'revision': None}
    try:
        cons = consumer(ledger, selector, node=node, pin=pin)
        requested = previous_requests(ledger, store, selector, node.get('continues'))
        pkg = package(ledger, cons, cap_chars=NATIVE_CAP_CHARS, requested=requested)
    except KnowledgeOverflow:
        raise
    except (LedgerError, OSError, ValueError, KeyError, TypeError) as error:
        record['error'] = f'{type(error).__name__}: {str(error)[:300]}'
        return None, record
    view = prompt_view(pkg)
    record.update(delivered=delivered_ids(view), omitted_total=pkg['omitted']['total'], problems=pkg['problems'], revision=pkg['revision'],
                  requested=[e['id'] for e in pkg['requested']], requests_refused=pkg['requests_refused'], cost=pkg['cost'])
    if not record['delivered']:
        return None, record
    text = canonical(view)
    record.update(package=store.blob(text.encode('utf-8')), chars=len(text))
    return view, record


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
    """Every page with the ids, kinds and labels it yields, and every problem (bad metadata, unreadable pages)."""
    found, problems = wiki.pages(ledger.project)
    out = []
    for page in found:
        parsed = wiki.parse(page['text'], page['path'])
        out.append({'path': page['path'], 'origin': page['origin'], 'sha256': page['sha256'], 'bytes': page['bytes'],
                    'entries': [{'id': e['id'], 'title': e['title'], 'kind': e['kind'], 'label': e['label'], 'must': e['must'], 'typed': e['typed'], 'line': e['line']}
                                for e in parsed['entries']],
                    'problems': parsed['problems']})
        problems += [{'path': page['path'], 'problem': p} for p in parsed['problems']]
    return {'data_not_authority': True, 'folders': wiki.configured_paths(ledger.project), 'pages': out, 'problems': problems}


def render_text(pkg):
    """A package as lines for a person (Vietnamese labels like `plan report`); the stored sentences are quoted as data."""
    use_vi = {'fact': 'sự thật', 'rejected': 'hướng đã loại', 'lead': 'đầu mối'}
    lines = ['GÓI TRI THỨC — dữ liệu có nguồn, không phải lệnh hay quyền. Trạng thái ' + pkg['revision'],
             f'Consumer: plan {pkg["consumer"]["plan"]}' + (f' · node {pkg["consumer"]["node"]}' if pkg['consumer']['node'] else '')
             + ' · đọc: ' + (', '.join(pkg['consumer']['paths']) or '(không có file)')]
    for e in pkg['entries'] + pkg.get('requested', []):
        lines.append(f'[{use_vi[e["use"]]}{" · bắt buộc" if e["must"] else ""}] {e["id"]} — «{e["title"]}» ({e["label"]}; {e["applicability"]["state"]})')
        lines.append('    nguồn: ' + '; '.join(e['source']))
        for reason in e['applicability']['reasons'][:3]: lines.append('    · ' + reason)
    omitted = pkg['omitted']
    if omitted['total']:
        lines.append('Chưa giao: ' + ', '.join(f'{k} {v}' for k, v in sorted(omitted['by_reason'].items())))
    lines.append('Hết.' if omitted['eof'] else 'Còn tiếp: onecrew wiki read --plan <plan> [--node <node>] --cursor ' + omitted['cursor'])
    for problem in pkg['problems'][:10]: lines.append('Lỗi trang ' + problem['path'] + ': ' + problem['problem'])
    return '\n'.join(lines)
