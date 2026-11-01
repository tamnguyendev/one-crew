"""2.4-B — working context per consumer (docs/v24/HUONG-DAN-CONTEXT.vi.md): what was delivered to which attempt, what changed since,
and who must recheck. No new store: the ledger (one class-A kind) and the package blobs of 2.3.

  * Delivery record. NativeExecutor.prepare writes `knowledge.delivered` right after the knowledge selection and the source requests and
    before the launch, once per attempt: root, node, generation, attempt, child task, the base snapshot the worker saw, package blob,
    revision, the delivered entries ({id, use, must, event | sha256, sources: [{path, blob}]}), the consumer paths, and the blobs of the
    files whose content reached the prompt through 2.4-A (`sources_read`: reads, search hits, listings). A rebuild never rewrites it.
  * Delta. `delta` judges a delivered record again by the same code as a package (knowledge._collect on the same consumer) ON THE VIEW IT
    WAS DELIVERED ON (the attempt's base snapshot: engine capture + input-artifact overlays + the carried partial candidate): an entry gone
    (withdrawn, archived, superseded, source withdrawn), changed (another use, not applicable, a newer version) or a new mandatory entry.
    At a safe point the package carries the delta against the previous attempt of the node: ids and reasons only.
  * One decision. `decide` is the only judge, used by the publish/verify gate, the pre-dispatch check of the engine and both consumer
    views (`affected_consumers`, `consumers_report`), so a view never disagrees with a hold:
      - own: a delivered must/fact entry gone or changed, a new mandatory entry, or a file whose content reached the prompt that changed in
        the project since (what the next attempt would pin) -> `recheck` (the engine continues the node in a new generation with the delta,
        within the root budget and MAX_RECHECKS; a changed source re-pins the tree, carries the candidate and opens a new round allowance);
      - upstream only: an input artifact was built, directly or through any chain of inputs, by an attempt whose own record changed so
        -> `input_changed`: the dependent is held at once, without a model call (re-running it on the same input cannot help; re-opening
        the producer is the existing repair path). The walk over the inputs is complete (Codex review F3): every producer attempt
        reachable through node.started inputs is judged once (memo), with an explicit stack (no depth limit), and an input whose check
        cannot be completed (no or unreadable receipt, a producing attempt or start record not in the ledger, a cycle, more than
        MAX_WALK attempts) is also `input_changed`, naming what could not be checked - never a default publish;
      - a lead that changed is only noted.
Nothing here proves that a model understood or forgot knowledge: records and deltas prove delivery only.
"""
import json
from pathlib import Path

from ..ledger import LedgerError
from . import knowledge, namespaces, plan as plans

KIND = 'knowledge.delivered'
MAX_RECHECKS = 2                 # automatic rechecks of one node for changed knowledge; then it is held
MAX_WALK = 10000                 # producer attempts one decision walks at most; beyond that it is incomplete, so never `publish`
UNCHECKED = 'the dependency check could not be completed'
EMPTY = {'withdrawn': [], 'changed': [], 'added_mandatory': []}


# ---- the record ---------------------------------------------------------------------------------------------------------------

def _root(ledger, conn, selector):
    root = namespaces.resolve(ledger, conn, selector) if conn else None
    if root is None: raise LedgerError(f'No plan named {selector}.')
    return root


def _row(conn, root_id, where, args):
    row = conn.execute(f"SELECT seq,payload FROM events WHERE task_id=? AND kind='{KIND}' AND {where} ORDER BY seq DESC LIMIT 1",
                       (root_id, *args)).fetchone()
    return dict(json.loads(row['payload']), event=row['seq']) if row else None


def row_for_attempt(ledger, selector, attempt_id):
    with ledger.transaction() as conn:
        if conn is None: return None
        root = namespaces.resolve(ledger, conn, selector)
        return _row(conn, root['id'], "json_extract(payload,'$.attempt')=?", (attempt_id,)) if root else None


def latest_row(ledger, selector, nid, exclude_attempt=None):
    with ledger.transaction() as conn:
        if conn is None: return None
        root = namespaces.resolve(ledger, conn, selector)
        if root is None: return None
        return _row(conn, root['id'], "json_extract(payload,'$.node')=? AND json_extract(payload,'$.attempt')<>?", (nid, exclude_attempt or ''))


def _started(conn, root_id, attempt_id):
    row = conn.execute("SELECT seq,payload FROM events WHERE task_id=? AND kind='node.started' AND json_extract(payload,'$.attempt')=? "
                       "ORDER BY seq DESC LIMIT 1", (root_id, attempt_id)).fetchone()
    return dict(json.loads(row['payload']), event=row['seq']) if row else None


def delivery_entries(judged, delivered):
    """The dependency form of the delivered entries: {id, use, must, event | sha256, sources: [{path, blob}]}."""
    out = []
    for ident in delivered:
        j = judged.get(ident)
        if not j: continue
        entry = {'id': ident, 'use': j['use'], 'must': j['must'], 'sources': j['sources']}
        if j.get('event') is not None: entry['event'] = j['event']
        if j.get('sha256'): entry['sha256'] = j['sha256']
        out.append(entry)
    return out


def record_delivery(ledger, selector, node, attempt, task, record, delivery, sources_read=None, base=None):
    """Write the delivery record of `attempt` once (an existing one is kept: it is the truth about what was delivered). Returns its event."""
    with ledger.transaction(write=True) as conn:
        root = _root(ledger, conn, selector)
        existing = _row(conn, root['id'], "json_extract(payload,'$.attempt')=?", (attempt['id'],))
        if existing: return existing['event']
        started = _started(conn, root['id'], attempt['id']) or {}
        record = record or {}
        payload = {'plan': namespaces.parse(root['request_key'])[0], 'node': node['id'], 'generation': started.get('generation'),
                   'attempt': attempt['id'], 'task': task['id'], **({'base': base} if base else {}),
                   'package': record.get('package'), 'revision': record.get('revision'),
                   'delivered': list(record.get('delivered') or []), 'entries': list((delivery or {}).get('entries') or []),
                   'consumer_paths': sorted(set(node.get('read') or []) | set(node.get('write') or [])),
                   **({'delta': record['delta']} if record.get('delta') else {}),
                   **({'sources_read': sources_read} if sources_read else {}), 'grants_authority': False}
        plans.emit(ledger, conn, root['id'], KIND, payload)
        return conn.execute('SELECT last_insert_rowid()').fetchone()[0]


# ---- the delta -----------------------------------------------------------------------------------------------------------------

def compare(entries, judged, mandatory_now):
    """{withdrawn, changed, added_mandatory} of delivered `entries` against `judged` (knowledge.judge_map of a selection now)."""
    withdrawn, changed = [], []
    for e in entries:
        j = judged.get(e['id'])
        if j is None: withdrawn.append({'id': e['id'], 'reason': 'gone'}); continue
        if j['excluded'] in knowledge.GONE: withdrawn.append({'id': e['id'], 'reason': j['excluded']}); continue
        if j['excluded']: changed.append({'id': e['id'], 'was': e['use'], 'now': j['excluded']}); continue
        if j['use'] != e['use']: changed.append({'id': e['id'], 'was': e['use'], 'now': j['use']}); continue
        if (e.get('event') is not None and j.get('event') != e['event']) or (e.get('sha256') and j.get('sha256') != e['sha256']):
            changed.append({'id': e['id'], 'was': e['use'], 'now': j['use'], 'reason': 'a newer version'})
    known = {e['id'] for e in entries}
    return {'withdrawn': withdrawn, 'changed': changed, 'added_mandatory': sorted(m for m in mandatory_now if m not in known)}


def _empty(d):
    return not (d['withdrawn'] or d['changed'] or d['added_mandatory'])


def safe_point_delta(ledger, selector, node, attempt_id, judged, delivered):
    """knowledge.for_native: the delta of this attempt's selection against the previous attempt of the node (None when nothing changed)."""
    previous = latest_row(ledger, selector, node['id'], exclude_attempt=attempt_id)
    if previous is None: return None
    d = compare(previous['entries'], judged, [i for i in delivered if (judged.get(i) or {}).get('must')])
    if _empty(d): return None
    d = {'against': {'attempt': previous['attempt'], 'generation': previous.get('generation')}, **d}
    if node.get('resume_artifact') and node.get('continues') == previous['attempt'] and (d['withdrawn'] or d['changed']):
        # the candidate this attempt continues was built with what changed: a partial one, or a final one the gate sent back (review B-R08)
        d['recheck_candidate' if _gate_continued(ledger, selector, previous['attempt']) else 'recheck_partial'] = True
    return d


def _gate_continued(ledger, selector, attempt_id):
    with ledger.transaction() as conn:
        root = namespaces.resolve(ledger, conn, selector) if conn else None
        if root is None: return False
        row = conn.execute("SELECT payload FROM events WHERE task_id=? AND kind='node.resumed' AND json_extract(payload,'$.continues_attempt')=? "
                           "ORDER BY seq DESC LIMIT 1", (root['id'], attempt_id)).fetchone()
    return bool(row and json.loads(row['payload']).get('knowledge_changed'))


def _node_def(ledger, plan, nid):
    from . import internal_plan
    definition = internal_plan.current(ledger, plan)['definition'] or {}
    return next((n for n in definition.get('nodes', []) if n['id'] == nid), None)


def _view(store, base):
    if not base: return None
    try:
        return store.context(base)
    except (LedgerError, OSError, ValueError, TypeError):
        return None


def delta(ledger, store, row, view=None, memo=None):
    """A delivered record judged again now, on `view` (the files as its worker saw them; default: the record's base snapshot)."""
    node = _node_def(ledger, 'plan-ns:' + row['plan'], row['node'])
    if node is None: return dict(EMPTY, status='node_gone')
    view = view if view is not None else _view(store, row.get('base'))
    return _judge(ledger, row['plan'], node, row, view, memo)[0]


def _judge(ledger, plan, node, row, view, memo, started_seq=None):
    """(delta, judged) of the node's delivery `row` (or of no delivery: only mandatory entries recorded after `started_seq`)."""
    cons = knowledge.consumer(ledger, 'plan-ns:' + plan, node=node, pin=node.get('executor'))
    candidates, eligible, _, _ = knowledge._collect(ledger, cons, view, memo)
    if row is not None and row.get('entries') is not None and knowledge._state_hash(cons, candidates) == row.get('revision'):
        return dict(EMPTY), {}
    mandatory = [c['id'] for c in eligible if c.get('mandatory')]
    if row is None:                                # nothing was delivered: only a mandatory entry written after the attempt started is new
        mandatory = [c['id'] for c in eligible if c.get('mandatory') and c['origin'].get('type') == 'ledger'
                     and started_seq is not None and (c.get('seq') or 0) > started_seq]
    return compare((row or {}).get('entries') or [], knowledge.judge_map(candidates), mandatory), {}


def _current_blob(ledger, path):
    try:
        data = (Path(ledger.project) / path).read_bytes()
    except OSError:
        return None
    try:
        return knowledge.blob_of(ledger, path, data)
    except LedgerError:
        return None


def _receipt(store, key):
    try:
        body = json.loads(store.read_blob(key)) if key else None
    except (LedgerError, OSError, ValueError, TypeError):
        return None
    return body if isinstance(body, dict) else None


def _own(ledger, store, conn_data, plan, nid, attempt_id, row, started, receipt, memo):
    """The node's own critical changes and notes for one attempt."""
    critical, notes = [], []
    node = _node_def(ledger, 'plan-ns:' + plan, nid)
    knows = row is not None and bool(row.get('entries'))
    if node is not None and (knows or knowledge.declares_mandatory(ledger)):
        base = (row or {}).get('base') or (receipt or {}).get('base') or (started or {}).get('source')
        d, _ = _judge(ledger, plan, node, row if knows else None, _view(store, base), memo, (started or {}).get('event'))
        entries = {e['id']: e for e in (row or {}).get('entries') or []}
        for w in d['withdrawn']:
            e = entries[w['id']]
            (critical if e['must'] or e['use'] == 'fact' else notes).append({'id': w['id'], 'reason': w['reason'], 'was': e['use'], 'must': e['must']})
        for c in d['changed']:
            # what the candidate relied on as a fact is no longer one (or has a newer version); a lead that became a fact is only noted
            e = entries[c['id']]
            lost = e['use'] == 'fact' and (c['now'] != 'fact' or c.get('reason') == 'a newer version')
            newer = e['must'] and c.get('reason') == 'a newer version'
            (critical if lost or newer else notes).append(dict(c, reason=c.get('reason') or 'changed', must=e['must']))
        for m in d['added_mandatory']: critical.append({'id': m, 'reason': 'a new mandatory entry concerns this node'})
    for path, blob in sorted((((row or {}).get('sources_read') or {}).get('blobs') or {}).items()):
        now = _current_blob(ledger, path)
        if now != blob: critical.append({'path': path, 'reason': 'source changed since it was read', 'was': blob, 'now': now})
    return critical, notes


def _decision(critical, notes, upstream, event):
    return {'action': 'recheck' if critical else 'input_changed' if upstream else 'publish', 'critical': critical, 'upstream': upstream,
            'notes': notes, 'row': event}


def _unchecked(node, attempt, problems):
    """An upstream item for inputs whose dependency check could not be completed (no id is known to have changed)."""
    more = f' (and {len(problems) - 1} more)' if len(problems) > 1 else ''
    return {'node': node, 'attempt': attempt, 'reason': UNCHECKED + ': ' + problems[0] + more, 'ids': [], 'unchecked': problems[:20]}


def _attempt_of(conn, root_id, producer, binding, key):
    """The attempt that produced `producer`'s opaque receipt `key` (another executor's receipt names none): the node.produced event with
    that receipt (in the bound generation when the binding names one), then its adopted attempt or the node.started of that generation
    before it. None when the ledger does not place it."""
    sql = ("SELECT seq,payload FROM events WHERE task_id=? AND kind='node.produced' AND json_extract(payload,'$.node')=? "
           "AND json_extract(payload,'$.receipt')=?")
    args = [root_id, producer, key]
    generation = (binding or {}).get('generation')
    if isinstance(generation, int) and not isinstance(generation, bool):
        sql += " AND json_extract(payload,'$.generation')=?"; args.append(generation)
    row = conn.execute(sql + ' ORDER BY seq DESC LIMIT 1', args).fetchone()
    if row is None: return None
    produced = json.loads(row['payload'])
    if isinstance(produced.get('adopted_attempt'), str): return produced['adopted_attempt']
    start = conn.execute("SELECT payload FROM events WHERE task_id=? AND kind='node.started' AND json_extract(payload,'$.node')=? "
                         "AND json_extract(payload,'$.generation')=? AND seq<? ORDER BY seq DESC LIMIT 1",
                         (root_id, producer, produced.get('generation'), row['seq'])).fetchone()
    attempt = json.loads(start['payload']).get('attempt') if start else None
    return attempt if isinstance(attempt, str) and attempt else None


def _edge(ledger, store, root_id, consumer, producer, binding):
    """(producer, attempt, receipt, problem) of one input of `consumer`: the attempt that built the bound artifact (named by its receipt,
    or by the ledger for an opaque one), or attempt None and a problem naming what cannot be checked."""
    key = binding.get('receipt') if isinstance(binding, dict) else None
    if not isinstance(key, str) or not key:
        return producer, None, None, f'input {producer} of {consumer} names no receipt'
    body = _receipt(store, key)
    if isinstance(body, dict) and isinstance(body.get('attempt'), str) and body['attempt']:
        return producer, body['attempt'], key, None
    try:
        store.read_blob(key)
    except (LedgerError, OSError, ValueError, TypeError) as error:
        return producer, None, key, f'the receipt of input {producer} of {consumer} cannot be read ({str(error)[:160]})'
    with ledger.transaction() as conn:
        attempt = _attempt_of(conn, root_id, producer, binding, key) if conn else None
    if attempt: return producer, attempt, key, None
    return producer, None, key, f'the attempt that produced input {producer} of {consumer} is not in the ledger'


def _facts(ledger, store, root_id, plan, nid, attempt_id, receipt_key, memo):
    """(critical, notes, delivery event, edges) of one attempt, from the ledger: its own changes (_own) and the inputs it consumed."""
    with ledger.transaction() as conn:
        row = _row(conn, root_id, "json_extract(payload,'$.attempt')=?", (attempt_id,)) if conn else None
        started = _started(conn, root_id, attempt_id) if conn else None
    critical, notes = _own(ledger, store, None, plan, nid, attempt_id, row, started, _receipt(store, receipt_key), memo)
    inputs = (started or {}).get('inputs') or {}
    if started is None or not isinstance(inputs, dict):
        what = 'the start record' if started is None else 'the inputs'
        edges = [(nid, attempt_id, None, f'{what} of attempt {attempt_id} of {nid} is not in the ledger')]
    else:
        edges = [_edge(ledger, store, root_id, nid, producer, binding) for producer, binding in sorted(inputs.items())]
    return critical, notes, (row or {}).get('event'), edges


def _upstream(nid, edges, memo):
    """The upstream part of `nid`'s decision from its settled inputs (memo of _walk)."""
    upstream = []
    for producer, attempt, key, problem in edges:
        if problem:
            upstream.append(_unchecked(producer, attempt, [problem])); continue
        sub = memo.get(('decision', producer, attempt, key))
        if sub is None:                                # still open on the walk's own path: the attempt depends on itself
            upstream.append(_unchecked(producer, attempt, [f'input {producer} (attempt {attempt}) of {nid} depends on itself (a cycle)']))
            continue
        # what the producer's artifact was built on changed (a new mandatory entry for the producer does not change its artifact)
        built = [c for c in sub['critical'] if c.get('reason') != 'a new mandatory entry concerns this node']
        if not (built or sub['upstream']): continue
        ids = sorted({c.get('id') or c.get('path') for c in built} | {i for u in sub['upstream'] for i in u['ids']})
        problems = [p for u in sub['upstream'] for p in u.get('unchecked', [])]
        entry = _unchecked(producer, attempt, problems) if problems else {'node': producer, 'attempt': attempt}
        if ids: entry['reason'] = 'an input was built on knowledge or sources that changed'
        entry['ids'] = ids
        upstream.append(entry)
    return upstream


def _walk(ledger, store, root_id, plan, edges, memo):
    """Settle memo[('decision', producer, attempt, receipt)] for every producer attempt reachable from `edges` through the inputs each
    consumed: depth first on an explicit stack (no recursion or depth limit), each attempt judged once, an attempt met again on its own
    path left unsettled (a cycle: its consumer is not published), at most MAX_WALK new attempts (the rest: not checked, not published)."""
    stack = [('enter', e[:3]) for e in reversed(edges) if not e[3]]
    path, pending, walked = set(), {}, 0
    while stack:
        phase, ident = stack.pop()
        key = ('decision',) + ident
        if phase == 'exit':
            path.discard(ident)
            critical, notes, event, inner = pending.pop(ident)
            memo[key] = _decision(critical, notes, _upstream(ident[0], inner, memo), event)
            continue
        if key in memo or ident in path: continue
        if walked >= MAX_WALK:
            memo[key] = _decision([], [], [_unchecked(ident[0], ident[1], [f'the inputs reach more than {MAX_WALK} producer attempts '
                                                                          '(the walk guard)'])], None)
            continue
        walked += 1
        pending[ident] = facts = _facts(ledger, store, root_id, plan, ident[0], ident[1], ident[2], memo)
        path.add(ident)
        stack.append(('exit', ident))
        stack.extend(('enter', e[:3]) for e in reversed(facts[3]) if not e[3] and ('decision',) + e[:3] not in memo)


def decide(ledger, store, selector, nid, attempt_id=None, *, receipt_key=None, inputs=None, memo=None):
    """The one decision (see the module doc): {'action': publish | recheck | input_changed, 'critical', 'upstream', 'notes', 'row'}.
    `attempt_id`: the attempt whose candidate is judged (its record, its base, the inputs it consumed); None with `inputs` (a dependency
    binding {producer: {receipt, ...}}): what a node about to be dispatched would consume (only the upstream part is judged).
    `memo` may be shared between decisions: every entry is a complete decision, so the order of the questions does not change answers."""
    memo = {} if memo is None else memo
    with ledger.transaction() as conn:
        root = namespaces.resolve(ledger, conn, selector) if conn else None
    if root is None: return _decision([], [], [], None)
    plan = namespaces.parse(root['request_key'])[0]
    if attempt_id:
        critical, notes, event, edges = _facts(ledger, store, root['id'], plan, nid, attempt_id, receipt_key, memo)
    else:
        critical, notes, event = [], [], None
        edges = [_edge(ledger, store, root['id'], nid, producer, binding) for producer, binding in sorted((inputs or {}).items())]
    _walk(ledger, store, root['id'], plan, edges, memo)
    return _decision(critical, notes, _upstream(nid, edges, memo), event)


def publish_gate(ledger, store, selector, nid, attempt_id, *, receipt_key=None, memo=None):
    """The gate before a candidate is published or verified: `decide` for that candidate's attempt."""
    return decide(ledger, store, selector, nid, attempt_id, receipt_key=receipt_key, memo=memo)


# ---- consumers ---------------------------------------------------------------------------------------------------------------

def _roots(ledger, scope):
    """The open roots in scope (a selector, or every root of the project that has a delivery record)."""
    with ledger.transaction() as conn:
        if conn is None: return []
        if scope is not None:
            keys = [_root(ledger, conn, scope)['request_key']]
        else:
            keys = [r['request_key'] for r in conn.execute(
                f"SELECT DISTINCT t.request_key FROM events e JOIN tasks t ON t.id=e.task_id WHERE e.kind='{KIND}' AND t.project_id=? "
                "ORDER BY t.request_key", (ledger.project_id,))]
        return [k for k in keys if plans.anchor_events(ledger, conn, k)['status'] == 'approved']


def _decisions(ledger, store, selector, memo):
    """(view, [(item, record, attempt, decision)]) for every open node (not verified/accepted) of the root, by its current attempt (or
    the attempt its pending continuation continues; a node not started yet: the inputs it would consume now)."""
    from . import engine
    view = engine.state(ledger, selector)
    out = []
    for item in (view['definition'] or {}).get('nodes', []):
        record = view['nodes'][item['id']]
        if record.get('state') in ('verified', 'accepted'): continue
        attempt = record.get('attempt') or record.get('continues')
        if attempt:
            decision = decide(ledger, store, selector, item['id'], attempt, receipt_key=record.get('receipt'), memo=memo)
        else:
            # what it would consume now: only producers whose result already satisfies the edge (a producer still to come is not an input yet)
            inputs = {e['node']: {'receipt': view['nodes'][e['node']].get('receipt')} for e in item['depends']
                      if view['nodes'][e['node']].get('receipt') and engine._rank(view['nodes'][e['node']]) >= engine.STATES[e['requires']]}
            decision = decide(ledger, store, selector, item['id'], None, inputs=inputs, memo=memo)
        out.append((item, record, attempt, decision))
    return view, out


def affected_consumers(ledger, scope, changed_ids):
    """The open nodes whose decision names a changed id (own record, or `via` the producer of an input they consumed or would consume).
    `scope`: a root selector, or None for every open root of the project. Same decision as the gate."""
    from ..snapshots import Snapshots
    changed, out, store = set(changed_ids), [], Snapshots(ledger.state_root)
    for selector in _roots(ledger, scope):
        memo = {}
        view, rows = _decisions(ledger, store, selector, memo)
        name = namespaces.parse(selector)[0]
        for item, record, attempt, decision in rows:
            own = sorted({c.get('id') for c in decision['critical'] + decision['notes'] if c.get('id')} & changed)
            base = {'plan': name, 'root': view['root'], 'node': item['id'], 'generation': record['generation'], 'attempt': attempt,
                    'phase': record['phase']}
            if own: out.append(dict(base, ids=own, via=None))
            for up in decision['upstream']:
                hit = sorted(set(up['ids']) & changed)
                if hit and not own: out.append(dict(base, ids=hit, via=up['node']))
    return out


def consumers_report(ledger, plan):
    """`onecrew wiki consumers`: per open node of the root, what it was given and its decision now (the gate's). Read-only."""
    from ..snapshots import Snapshots
    store, memo = Snapshots(ledger.state_root), {}
    selector = _roots(ledger, plan)
    if not selector: return {'data_not_authority': True, 'plan': plan, 'consumers': [], 'note': 'the root is not open'}
    selector = selector[0]
    view, rows = _decisions(ledger, store, selector, memo)
    out = []
    for item, record, attempt, decision in rows:
        row = row_for_attempt(ledger, selector, attempt) if attempt else None
        if row is None and decision['action'] == 'publish': continue
        critical = decision['critical']
        status = ('withdrawn' if any(c.get('reason') in knowledge.GONE + ('gone',) for c in critical) else
                  'changed' if any(c.get('id') and 'now' in c for c in critical) else
                  'added_mandatory' if any(c.get('reason') == 'a new mandatory entry concerns this node' for c in critical) else
                  'source_changed' if any('path' in c for c in critical) else
                  'input_changed' if decision['upstream'] else
                  'withdrawn' if any(n.get('reason') in knowledge.GONE + ('gone',) for n in decision['notes']) else
                  'changed' if decision['notes'] else 'none')
        out.append({'node': item['id'], 'generation': record['generation'], 'phase': record['phase'], 'state': record.get('state'),
                    'attempt': attempt, 'delivered_generation': (row or {}).get('generation'), 'package': (row or {}).get('package'),
                    'revision': (row or {}).get('revision'), 'delivered': (row or {}).get('delivered', []), 'status': status,
                    'decision': decision['action'], 'critical': critical, 'notes': decision['notes'], 'upstream': decision['upstream'],
                    'delta': {'withdrawn': [c for c in critical + decision['notes'] if c.get('reason') in knowledge.GONE + ('gone',)],
                              'changed': [c for c in critical + decision['notes'] if 'now' in c and c.get('id')],
                              'added_mandatory': [c['id'] for c in critical if c.get('reason') == 'a new mandatory entry concerns this node']}})
    return {'data_not_authority': True, 'plan': namespaces.parse(selector)[0], 'consumers': out,
            'note': 'Delivery and its decision only: this never shows what a worker understood, and it grants or refuses nothing.'}
