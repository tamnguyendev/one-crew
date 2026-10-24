"""R06 verified-repair lessons and explicit general candidates, never policy.

learning.lesson is the durable evidence. Existing context.entry is its index
for the common two-scope reader, not another store or a new authority source.
"""
import hashlib
import ast
import json
import re

from .. import outcome_core
from ..ledger import LedgerError, content_hash, text_field
from . import compat, context, incidents, namespaces, plan as plans
from .verifiers import command

KIND = 'learning.lesson'
KEY_PREFIX = 'lesson-'


def _revision(ledger, revision):
    try:
        return context.resolve_revision(ledger.project, revision), 'commit'
    except LedgerError:
        tree = command._git(ledger.project, 'rev-parse', '--verify', '--end-of-options', str(revision) + '^{tree}')
        if not command.TREE_ID.fullmatch(tree or ''):
            raise LedgerError('The lesson revision is not a commit or retained artifact tree.')
        return tree, 'tree'


def _history(ledger, name):
    with ledger.transaction() as conn:
        state = plans.anchor_events(ledger, conn, name)
        rows = conn.execute('SELECT seq,payload FROM events WHERE task_id=? AND kind=? ORDER BY seq', (state['task_id'], KIND)).fetchall()
    return [dict(json.loads(row['payload']), event=row['seq']) for row in rows]


def _latest(ledger, name):
    latest = {}
    for item in _history(ledger, name):
        if item.get('lesson'):
            latest[item['lesson']] = item
    return latest


def _publish(ledger, name, value):
    with ledger.transaction(write=True) as conn:
        state, selector = incidents._root(ledger, conn, name)
        value = dict(value, task=state['task_id'], plan=state['name'])
        value['id'] = outcome_core.outcome_id(value)
        compat.check_write(KIND, value, selector)
        event = outcome_core.append_learning(conn, ledger, state['task_id'], KIND, value)
        if event is None:
            event = conn.execute("SELECT seq FROM events WHERE task_id=? AND kind=? AND json_extract(payload,'$.id')=?",
                                 (state['task_id'], KIND, value['id'])).fetchone()[0]
    return dict(value, event=event)


def _index(ledger, name, value):
    return context.add(ledger, name, kind='note', label='hypothesis' if value['scope'] == 'general' else 'verified',
        text=value['text'], source={'type': 'event', 'id': value['event']}, scope=value['scope'],
        conditions=value.get('conditions'), key=KEY_PREFIX + value['lesson'])


def record(ledger, name, incident, *, text, path, line, revision, test, symbol=None, candidate=False):
    """Publish after genuine repair verification, while the root is still open."""
    text_field(text, 'lesson text', 600); text_field(test, 'verified test', 200)
    path = context._path(path)
    if type(line) is not int or line < 1:
        raise LedgerError('A lesson location needs a positive line.')
    if type(candidate) is not bool:
        raise LedgerError('candidate must be a boolean.')
    commit, revision_kind = _revision(ledger, revision)
    source_text = context.file_at(ledger.project, commit, path)
    if line > len(source_text.splitlines()):
        raise LedgerError('The lesson location does not exist at the pinned revision.')
    if symbol and not context.symbol_present(ledger.project, commit, symbol, path)[0]:
        raise LedgerError('The lesson symbol does not exist at the pinned revision.')
    with ledger.transaction() as conn:
        state, selector = incidents._root(ledger, conn, name)
        _still_open(state)
        evidence = incidents._event(ledger, conn, state['task_id'], incident, incidents.KIND)
        body = evidence['payload']
        verified, result, _, _ = incidents._receipt(ledger, conn, state, selector, body.get('verified_receipt'), latest=True)
        if result != 'pass':
            raise LedgerError('A lesson requires passing repair verification.')
        checks = ({'check:' + c['id'] for c in verified['supported_checks'] if c['result'] == 'pass'}
                  if verified.get('kind') == 'node-verifier-receipt' else
                  {'reviewer:' + c['id'] for c in verified.get('criteria', []) if c.get('verdict') == 'pass'}
                  if verified.get('kind') == 'reviewer-receipt' else set(verified.get('argv') or []))
        if test not in checks:
            raise LedgerError('The named test/check was not verified by this receipt.')
        tree = command._git(ledger.project, 'rev-parse', commit + '^{tree}')
        if tree != (verified.get('verified_tree') or verified['artifact_sha']):
            raise LedgerError('The lesson revision is not the artifact the repair verified.')
    logical = content_hash([state['task_id'], incident, 'project'])[:32]
    existing = _latest(ledger, selector).get(logical)
    if existing:
        if existing['status'] != 'withdrawn':
            _index(ledger, selector, existing)  # restart repairs an interrupted context-index write
        return dict(existing, recorded=False)
    value = {'version': 1, 'lesson': logical, 'scope': 'project', 'status': 'proposed' if candidate else 'verified', 'text': text,
             'incident': incident, 'evidence_event': incident, 'snapshot': verified['artifact_sha'], 'conditions': None,
             'location': {'path': path, 'line': line, 'revision': commit, 'revision_kind': revision_kind, 'test': test, 'symbol': symbol},
             'verified_repair': True, 'verified_receipt': body['verified_receipt'],
             'file_sha256': hashlib.sha256(source_text.encode('utf-8')).hexdigest(),
             'file_blob': command._git(ledger.project, 'rev-parse', commit + ':' + path),
             'automatic_injection': False, 'automatic_promotion': False, 'origin': 'verified-plan-repair'}
    result = _publish(ledger, selector, value)
    _index(ledger, selector, result)
    return dict(result, recorded=True)


ENDED = ('accepted', 'stopped_with_report', 'closed')


def _still_open(state):
    """T52b [E14]: a lesson (project or general candidate) is written while the root is still open, never after it ended."""
    if state['status'] in ENDED:
        raise LedgerError('Record a repair lesson before the root ends.')


def propose_general(ledger, name, lesson, *, text, conditions):
    """Explicitly generalised, conditional candidate; never automatic promotion."""
    with ledger.transaction() as conn:
        _still_open(incidents._root(ledger, conn, name)[0])
    original = _latest(ledger, name).get(lesson)
    if original is None or original['scope'] != 'project' or original['status'] == 'withdrawn':
        raise LedgerError('A live project lesson is required as the source.')
    text_field(text, 'general lesson text', 600)
    if not isinstance(conditions, list) or not 1 <= len(conditions) <= 20:
        raise LedgerError('General candidates need applicability conditions.')
    checked = [text_field(c, 'condition', 500) for c in conditions]
    joined = '\n'.join([text, *checked])
    private = context._private_reasons(ledger, [text, *checked])
    symbol = original['location'].get('symbol')
    if symbol and symbol.casefold() in joined.casefold():
        private.append('it names the project symbol')
    location = original['location']
    if location['path'].casefold().endswith('.py'):
        try:
            source = context.file_at(ledger.project, location['revision'], location['path'])
            names = {node.name for node in ast.walk(ast.parse(source)) if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))}
            if any(re.search(r'(?<!\w)' + re.escape(name) + r'(?!\w)', joined, re.I) for name in names):
                private.append('it names a definition of the project')
        except (SyntaxError, LedgerError):
            private.append('the project definitions could not be checked for private detail')
    project_name = ledger.project.name
    if project_name and re.search(r'(?<!\w)' + re.escape(project_name) + r'(?!\w)', joined, re.I):
        private.append('it names the project')
    if private:
        raise LedgerError('A general candidate contains private project details: ' + '; '.join(private))
    logical = content_hash([original['lesson'], 'general', text, checked])[:32]
    existing = _latest(ledger, name).get(logical)
    if existing:
        if existing['status'] != 'withdrawn': _index(ledger, name, existing)
        return dict(existing, recorded=False)
    value = {'version': 1, 'lesson': logical, 'scope': 'general', 'status': 'proposed', 'text': text,
             'incident': original['incident'], 'evidence_event': original['incident'], 'source_lesson': original['lesson'],
             'snapshot': None, 'location': None, 'conditions': checked,
             'automatic_injection': False, 'automatic_promotion': False, 'origin': 'explicit-general-candidate'}
    result = _publish(ledger, name, value)
    _index(ledger, name, result)
    return dict(result, recorded=True)


def withdraw(ledger, name, lesson, *, reason):
    text_field(reason, 'withdrawal reason', 1000)
    original = _latest(ledger, name).get(lesson)
    if original is None:
        raise LedgerError('No such lesson on this root.')
    if original['status'] == 'withdrawn':
        return dict(original, recorded=False)
    value = {key: val for key, val in original.items() if key not in ('id', 'event')}
    value.update(status='withdrawn', withdrawal_reason=reason, previous_event=original['event'])
    return dict(_publish(ledger, name, value), recorded=True)


def refine_context(ledger, entries, revision=None):
    """Materialize lesson sources for context.retrieve: withdrawal and file drift.

    Parent wires this one adapter hook after the common context reader builds
    entries. It does not replace that reader or create a second knowledge store.
    """
    keys = {entry['key'][len(KEY_PREFIX):] for entry in entries if entry['key'].startswith(KEY_PREFIX)}
    if not keys:
        return entries
    with ledger.transaction() as conn:
        rows = conn.execute("SELECT e.seq,e.task_id,e.payload FROM events e WHERE e.kind=? ORDER BY e.seq", (KIND,)).fetchall()
    latest, sources = {}, {}
    for row in rows:
        item = json.loads(row['payload'])
        if item.get('lesson'):
            latest[(row['task_id'], item['lesson'])] = item
        if item.get('lesson') in keys:
            sources[row['seq']] = (row['task_id'], item)
    out = []
    for entry in entries:
        logical = entry['key'][len(KEY_PREFIX):] if entry['key'].startswith(KEY_PREFIX) else None
        source = sources.get(entry['source'].get('id')) if entry['source']['type'] == 'event' else None
        typed = source and source[1].get('lesson') == logical and source[1].get('scope') == entry['scope']
        lesson = latest.get((source[0], logical)) if typed else None
        if lesson is None:
            out.append(entry); continue
        if lesson['status'] == 'withdrawn':
            continue
        if lesson.get('source_lesson'):
            origin = latest.get((source[0], lesson['source_lesson']))
            if origin and origin['status'] == 'withdrawn':
                continue
        changed = None
        if lesson['scope'] == 'project':
            try:
                current, _ = _revision(ledger, revision or 'HEAD')
                blob = command._git(ledger.project, 'rev-parse', current + ':' + lesson['location']['path'])
                if blob != lesson['file_blob']:
                    changed = f'file changed since revision {lesson["location"]["revision"][:12]}; recheck at {current[:12]}'
            except (LedgerError, OSError) as error:
                changed = 'cannot verify the lesson revision: ' + str(error)[:200]
        out.append(dict(entry, lesson=logical, lesson_status=lesson['status'],
                        **({'label': 'stale', 'label_vi': 'cần kiểm lại', 'stale_reason': changed} if changed else {})))
    return out


def retrieve(ledger, *, name=None, revision=None, scope='both'):
    result = context.retrieve(ledger, plan=name, revision=revision, scope=scope)
    # Safe even before the parent adds the shared reader's refinement hook.
    result['entries'] = refine_context(ledger, result['entries'], revision)
    result['entries'] = [entry for entry in result['entries'] if entry.get('lesson')]
    return result
