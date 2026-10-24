"""T26: a v1 SOL is immutable source material; its linked root grants authority.

Reads existing conversation tables without importing the v1 discussion engine.
The link is part of the root contract hash and a class-B ledger event, never a
second approval/store. A conversation's work has one root; unlink/transfer is not
implicit. Later SOL drafts or decisions cannot replace an approved root revision.
"""
import json
import re

from ..ledger import LedgerError, content_hash
from . import namespaces, plan

KIND = 'solution.linked'


def normalize(value):
    if (not isinstance(value, dict) or set(value) != {'id', 'revision'}
            or not isinstance(value['id'], str) or not re.fullmatch(r'SOL-[0-9a-f]{32}', value['id'])
            or not isinstance(value['revision'], str) or not re.fullmatch(r'[0-9a-f]{64}', value['revision'])
            or set(value['revision']) == {'0'}):
        raise LedgerError('solution_ref requires an exact SOL id and nonzero SHA-256 revision.')
    return dict(value)


def source(ledger, conn, sid, revision=None):
    tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")} if conn else set()
    if not {'solutions', 'conversations'} <= tables:
        raise LedgerError('The referenced SOL is unavailable in this state root.')
    row = conn.execute('SELECT s.* FROM solutions s JOIN conversations c ON c.id=s.conversation '
                       'WHERE s.id=? AND c.project_id=?', (sid, ledger.project_id)).fetchone()
    if row is None: raise LedgerError('The referenced SOL is missing or belongs to another project.')
    try:
        payload = json.loads(row['payload'])
        normalize({'id': row['id'], 'revision': row['revision']})
        if not isinstance(payload, dict) or content_hash(payload) != row['revision']:
            raise LedgerError('The referenced SOL content does not match its immutable revision.')
    except LedgerError:
        raise
    except (TypeError, ValueError) as error:
        raise LedgerError('The referenced SOL content is malformed.') from error
    if revision is not None and revision != row['revision']:
        raise LedgerError('The referenced SOL revision changed or does not match.')
    return dict(row, payload=payload)


def _links(ledger, conn):
    if conn is None: return []
    rows = conn.execute('SELECT t.id AS root_task_id,t.request_key,e.payload FROM events e JOIN tasks t ON t.id=e.task_id '
                        'WHERE t.project_id=? AND e.kind=? ORDER BY e.seq', (ledger.project_id, KIND))
    links = []
    for row in rows:
        try:
            value = json.loads(row['payload'])
            normalize(value['solution_ref'])
            if (not row['request_key'].startswith(namespaces.NAMESPACED)
                    or type(value['revision']) is not int or value['revision'] < 1
                    or not isinstance(value['conversation'], str) or not value['conversation'].startswith('CONV-')
                    or not re.fullmatch(r'[0-9a-f]{64}', value['sha'])):
                raise ValueError('invalid link identity')
        except (ValueError, KeyError, TypeError) as error:
            raise LedgerError('Malformed SOL-root linkage; no authority can be inferred.') from error
        links.append(dict(value, root_task_id=row['root_task_id'], selector=row['request_key']))
    return links


def validate_revision(ledger, conn, selector, contract):
    """Pre-write validation, repeated inside the transaction that records a link."""
    _, explicit = namespaces.parse(selector)
    links = _links(ledger, conn)
    prior = [row for row in links if row['selector'] == explicit]
    ref = contract.get('solution_ref')
    if ref is None:
        if prior: raise LedgerError('A linked root cannot silently remove its SOL reference.')
        return None
    if explicit is None or not explicit.startswith(namespaces.NAMESPACED):
        raise LedgerError('SOL linkage requires an explicit plan-ns: root; legacy roots retain v1 semantics.')
    if not isinstance(contract.get('authority'), dict):
        raise LedgerError('A linked root needs an explicit authority grant; SOL approval cannot supply missing rights.')
    ref = normalize(ref)
    sol = source(ledger, conn, ref['id'], ref['revision'])
    if prior and any(row['conversation'] != sol['conversation'] for row in prior):
        raise LedgerError('A root cannot change the linked work to another SOL conversation.')
    other = next((row for row in links if row['conversation'] == sol['conversation'] and row['selector'] != explicit), None)
    if other:
        raise LedgerError(f"This SOL work already belongs to root {other['selector']} ({other['root_task_id']}); a second approval source is refused.")
    return sol


def prepare(ledger, selector, contract):
    with ledger.transaction() as conn:
        return validate_revision(ledger, conn, selector, contract)


def record(ledger, conn, task_id, selector, revision, sha, contract):
    sol = validate_revision(ledger, conn, selector, contract)
    if sol is None: return
    plan.emit(ledger, conn, task_id, KIND, {'revision': revision, 'sha': sha,
        'conversation': sol['conversation'], 'solution_ref': dict(contract['solution_ref']), 'grants_authority': False})


def validate_root(ledger, conn, state, contract, sha, revision=None):
    sol = validate_revision(ledger, conn, state['selector'], contract)
    if sol is None: return None
    revision = state['latest'] if revision is None else revision
    matching = [row for row in _links(ledger, conn) if row['root_task_id'] == state['task_id'] and row['revision'] == revision]
    if (len(matching) != 1 or matching[0]['sha'] != sha or matching[0]['solution_ref'] != contract['solution_ref']
            or matching[0]['conversation'] != sol['conversation']):
        raise LedgerError('The root revision/hash is not covered by its immutable SOL linkage.')
    _settled_adoption(ledger, conn, state, sol)
    return sol


def _settled_adoption(ledger, conn, state, sol):
    """A v1 writer already in flight must settle before a root takes its work."""
    tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    if 'solution_bindings' not in tables: return
    from . import root_writer
    for task in conn.execute('SELECT t.* FROM tasks t JOIN solution_bindings b ON b.task_id=t.id '
                             'WHERE t.project_id=? AND b.conversation=?', (ledger.project_id, sol['conversation'])):
        binding = json.loads(task['payload']).get('plan_binding') or {}
        if binding.get('root_task_id') == state['task_id']: continue
        attempt = ('attempts' in tables and root_writer.writes(task) and conn.execute(
            "SELECT id FROM attempts WHERE task_id=? AND status IN ('reserved','running','unknown')", (task['id'],)).fetchone())
        action = ('actions' in tables and conn.execute(
            "SELECT id FROM actions WHERE task_id=? AND status IN ('executing','unknown')", (task['id'],)).fetchone())
        if attempt or action:
            raise LedgerError('Root ' + state['selector'] + ' cannot adopt SOL work while v1 writer ' + task['id'] + ' is live; settle or reconcile it first.')


def linked(ledger, conn, sid, revision=None):
    """Return a linked root and source, or None for an ordinary unlinked v1 SOL."""
    sol = source(ledger, conn, sid, revision)
    rows = [row for row in _links(ledger, conn) if row['conversation'] == sol['conversation']]
    if not rows: return None
    if len({row['root_task_id'] for row in rows}) != 1:
        raise LedgerError('Multiple roots claim the same SOL work; approval is ambiguous.')
    state = plan.anchor_events(ledger, conn, rows[-1]['selector'])
    contract, sha = plan.load(ledger, state)
    validate_root(ledger, conn, state, contract, sha)
    if contract['solution_ref'] != {'id': sid, 'revision': sol['revision']}:
        raise LedgerError('The SOL reference differs from the current root revision; use its reviewed handoff.')
    return state, sol


def intake_binding(ledger, conn, sid, revision):
    normalize({'id': sid, 'revision': revision})
    found = linked(ledger, conn, sid, revision)
    if found is None: return None
    state, sol = found
    from . import plan_binding
    binding = plan_binding.capture(ledger, conn, state['selector'])
    return binding, sol


def check_task(ledger, conn, task, solution_binding=None):
    """Core policy-port hook. Return root authority, or None for unlinked v1."""
    from . import plan_binding
    payload = json.loads(task['payload'])
    binding = plan_binding.read(task)
    sid, revision = payload.get('solution_id'), payload.get('solution_revision')
    if solution_binding is None and conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='solution_bindings'").fetchone():
        row = conn.execute('SELECT * FROM solution_bindings WHERE task_id=?', (task['id'],)).fetchone()
        solution_binding = dict(row) if row else None
    if solution_binding:
        # v1's explicit solution-change reply can rebind this row while retaining
        # its original task payload. Unlinked v1 keeps that existing behavior.
        sid, revision = solution_binding['solution'], solution_binding['revision']
    found = linked(ledger, conn, sid, revision) if sid else None
    if found is not None and binding is None:
        raise LedgerError('SOL approval grants no execution after linkage; submit a handoff bound to root ' + found[0]['selector'] + '.')
    if binding is None: return None
    state = plan_binding.state_for_task(ledger, conn, task)
    contract, sha = plan.load(ledger, state)
    source_ref = contract.get('solution_ref')
    if source_ref is None:
        if found is not None: raise LedgerError('The task is bound to a different root from its linked SOL work.')
        return None
    sol = validate_root(ledger, conn, state, contract, sha)
    if sid and (source_ref != {'id': sid, 'revision': revision} or found is None or found[0]['task_id'] != state['task_id']):
        raise LedgerError('The task SOL reference is outside its current approved root.')
    if conn.execute("SELECT 1 FROM events WHERE task_id=? AND kind='solution.stopped'", (task['id'],)).fetchone():
        raise LedgerError('Task stopped by a solution decision; it cannot resume.')
    if conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='conversation_questions'").fetchone():
        for question in conn.execute("SELECT id,payload FROM conversation_questions WHERE conversation=? AND state='pending'", (sol['conversation'],)):
            try:
                affected = json.loads(question['payload'])['affected_tasks']
                if not isinstance(affected, list): raise ValueError('affected tasks must be a list')
            except (ValueError, KeyError, TypeError) as error:
                raise LedgerError('Linked SOL has a malformed pending question.') from error
            if task['id'] in affected:
                raise LedgerError('Solution decision pending: ' + question['id'])
    return {'authority': 'root', 'root': {'task_id': state['task_id'], 'selector': state['selector'],
            'revision': state['approved']['revision'], 'sha': state['approved']['sha']},
            'solution': sol['id'], 'revision': sol['revision'], 'content': contract,
            'solution_ref': dict(source_ref), 'solution_authority': 'none'}
