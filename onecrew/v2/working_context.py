"""2.4-B — working context per consumer (docs/v24/HUONG-DAN-CONTEXT.vi.md): what was delivered to which attempt, what changed since,
and who must recheck. No new store: the ledger (one class-A kind) and the package blobs of 2.3.

  * Delivery record. NativeExecutor.prepare writes `knowledge.delivered` right after the knowledge selection and the source requests and
    before the launch, once per attempt: root, node, generation, attempt, child task, package blob, revision, the delivered entries
    ({id, use, must, event | sha256, sources: [{path, blob}]}), the consumer paths, and the blobs of the files the attempt read through
    2.4-A (`sources_read`). It is the truth about what was delivered; a rebuild after a crash never rewrites it.
  * Delta. `delta` judges a delivered record again, by the same code as a package (knowledge._collect on the same consumer), now: an entry
    gone (withdrawn, archived, superseded, source withdrawn), changed (another use, not applicable, a newer version) or a new mandatory
    entry. At a safe point (a continuation or a resumed generation) the package carries the delta against the previous attempt of the
    node: ids and reasons only, never the history; a withdrawn entry appears only there, never in entries/requested.
  * Gate. Before a candidate is published as the node's result (engine.step, adoption after a crash, release of a retained or paused
    candidate) and before it is verified, `publish_gate` rechecks its record and the records of the producers whose artifacts it
    consumed: a must or fact entry gone or changed, a new mandatory entry, or a file it read that changed -> `recheck`; a lead that changed
    is only noted. The engine then continues the node in a new generation carrying the delta (inside the root's remaining budget and at
    most MAX_RECHECKS times; spent budget stays spent) or holds it (`knowledge_changed`). A changed source restarts the chain (a newly
    pinned tree); anything else continues from the candidate.
  * Consumers. `affected_consumers` maps changed ids to the open nodes whose record names them, and to the dependents that consumed their
    artifacts; independent branches are untouched. `consumers_report` is the read-only `onecrew wiki consumers` view.
Nothing here proves that a model understood or forgot knowledge: records and deltas prove delivery only.
"""
import json
from pathlib import Path

from ..ledger import LedgerError, canonical
from . import knowledge, namespaces, plan as plans

KIND = 'knowledge.delivered'
MAX_RECHECKS = 2                 # automatic rechecks of one node for changed knowledge; then it is held
INPUT_DEPTH = 3


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
    row = conn.execute("SELECT payload FROM events WHERE task_id=? AND kind='node.started' AND json_extract(payload,'$.attempt')=? "
                       "ORDER BY seq DESC LIMIT 1", (root_id, attempt_id)).fetchone()
    return json.loads(row['payload']) if row else None


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


def record_delivery(ledger, selector, node, attempt, task, record, delivery, sources_read=None):
    """Write the delivery record of `attempt` once (an existing one is kept: it is the truth about what was delivered). Returns its event."""
    with ledger.transaction(write=True) as conn:
        root = _root(ledger, conn, selector)
        existing = _row(conn, root['id'], "json_extract(payload,'$.attempt')=?", (attempt['id'],))
        if existing: return existing['event']
        started = _started(conn, root['id'], attempt['id']) or {}
        record = record or {}
        payload = {'plan': namespaces.parse(root['request_key'])[0], 'node': node['id'], 'generation': started.get('generation'),
                   'attempt': attempt['id'], 'task': task['id'], 'package': record.get('package'), 'revision': record.get('revision'),
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
        d['recheck_partial'] = True               # the candidate this attempt continues was built with what changed
    return d


def _node_def(ledger, plan, nid):
    from . import internal_plan
    definition = internal_plan.current(ledger, plan)['definition'] or {}
    return next((n for n in definition.get('nodes', []) if n['id'] == nid), None)


def delta(ledger, store, row, view=None, memo=None):
    """A delivered record judged again now (`view`: files as a worker would see them; None = the project working tree)."""
    node = _node_def(ledger, 'plan-ns:' + row['plan'], row['node'])
    if node is None: return {'status': 'node_gone', 'withdrawn': [], 'changed': [], 'added_mandatory': []}
    cons = knowledge.consumer(ledger, 'plan-ns:' + row['plan'], node=node, pin=node.get('executor'))
    candidates, eligible, _, _ = knowledge._collect(ledger, cons, view, memo)
    if knowledge._state_hash(cons, candidates) == row.get('revision'):
        return {'withdrawn': [], 'changed': [], 'added_mandatory': []}           # nothing the selection reads changed
    return compare(row['entries'], knowledge.judge_map(candidates), [c['id'] for c in eligible if c.get('mandatory')])


def _current_blob(ledger, path):
    try:
        data = (Path(ledger.project) / path).read_bytes()
    except OSError:
        return None
    try:
        return knowledge.blob_of(ledger, path, data)
    except LedgerError:
        return None


def publish_gate(ledger, store, selector, nid, attempt_id, *, memo=None, _depth=0):
    """{'action': publish | recheck, 'critical', 'notes', 'row'} for the candidate of `attempt_id` (see the module doc)."""
    memo = {} if memo is None else memo
    critical, notes = [], []
    with ledger.transaction() as conn:
        root = namespaces.resolve(ledger, conn, selector) if conn else None
        if root is None: return {'action': 'publish', 'critical': [], 'notes': [], 'row': None}
        row = _row(conn, root['id'], "json_extract(payload,'$.attempt')=?", (attempt_id,))
        started = _started(conn, root['id'], attempt_id) or {}
    if row:
        if row.get('entries'):
            d = delta(ledger, store, row, None, memo)
            entries = {e['id']: e for e in row['entries']}
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
        for path, blob in sorted(((row.get('sources_read') or {}).get('blobs') or {}).items()):
            now = _current_blob(ledger, path)
            if now != blob: critical.append({'path': path, 'reason': 'source changed since it was read', 'was': blob, 'now': now})
    if _depth < INPUT_DEPTH:
        for producer, binding in sorted((started.get('inputs') or {}).items()):
            try:
                body = json.loads(store.read_blob(binding.get('receipt')))
            except (LedgerError, OSError, ValueError, TypeError):
                continue
            if not isinstance(body, dict) or not body.get('attempt'): continue
            upstream = publish_gate(ledger, store, selector, producer, body['attempt'], memo=memo, _depth=_depth + 1)
            if upstream['critical']:
                critical.append({'node': producer, 'reason': 'an input was built on knowledge or sources that changed', 'attempt': body['attempt']})
    return {'action': 'recheck' if critical else 'publish', 'critical': critical, 'notes': notes, 'row': (row or {}).get('event')}


# ---- consumers ---------------------------------------------------------------------------------------------------------------

def _roots(ledger, scope):
    with ledger.transaction() as conn:
        if conn is None: return []
        if scope is not None:
            return [_root(ledger, conn, scope)['request_key']]
        rows = conn.execute(f"SELECT DISTINCT t.request_key FROM events e JOIN tasks t ON t.id=e.task_id WHERE e.kind='{KIND}' AND t.project_id=? "
                            "ORDER BY t.request_key", (ledger.project_id,)).fetchall()
        return [r['request_key'] for r in rows]


def affected_consumers(ledger, scope, changed_ids):
    """The open nodes (not verified/accepted) whose delivery record names a changed id, and the open dependents that consumed their
    artifacts (`via`). `scope`: a root selector, or None for every root of the project."""
    from .. import dependency_core
    from . import engine, internal_plan as ip
    changed, out = set(changed_ids), []
    for selector in _roots(ledger, scope):
        view = engine.state(ledger, selector)
        nodes = (view['definition'] or {}).get('nodes', [])
        if not nodes: continue
        name = namespaces.parse(selector)[0]
        direct = {}
        for item in nodes:
            nid, record = item['id'], view['nodes'][item['id']]
            if record.get('state') in ('verified', 'accepted'): continue
            row = latest_row(ledger, selector, nid)
            hit = sorted({e['id'] for e in (row or {}).get('entries', [])} & changed)
            if hit:
                direct[nid] = hit
                out.append({'plan': name, 'root': view['root'], 'node': nid, 'generation': record['generation'], 'attempt': row['attempt'],
                            'phase': record['phase'], 'ids': hit, 'via': None})
        projection = ip.influence_projection(nodes)
        for nid, hit in direct.items():
            for other in sorted(dependency_core.affected_tasks(projection, [nid]) - set(direct)):
                record = view['nodes'][other]
                if record.get('state') in ('verified', 'accepted') or nid not in (record.get('inputs') or {}): continue
                out.append({'plan': name, 'root': view['root'], 'node': other, 'generation': record['generation'], 'attempt': record.get('attempt'),
                            'phase': record['phase'], 'ids': hit, 'via': nid})
    return out


def consumers_report(ledger, plan):
    """`onecrew wiki consumers`: per open node of the root, the package last delivered to it and its delta status now. Read-only."""
    from ..snapshots import Snapshots
    from . import engine
    selector = _roots(ledger, plan)[0]
    view = engine.state(ledger, selector)
    store, memo, rows = Snapshots(ledger.state_root), {}, []
    for item in (view['definition'] or {}).get('nodes', []):
        nid, record = item['id'], view['nodes'][item['id']]
        if record.get('state') in ('verified', 'accepted'): continue
        row = latest_row(ledger, selector, nid)
        if row is None: continue
        d = delta(ledger, store, row, None, memo) if row.get('entries') else {'withdrawn': [], 'changed': [], 'added_mandatory': []}
        gate = publish_gate(ledger, store, selector, nid, row['attempt'], memo=memo)
        sources = [c for c in gate['critical'] if 'path' in c]
        inputs = [c for c in gate['critical'] if 'node' in c]
        status = ('withdrawn' if d['withdrawn'] else 'changed' if d['changed'] else 'added_mandatory' if d['added_mandatory'] else
                  'source_changed' if sources else 'input_changed' if inputs else 'none')
        rows.append({'node': nid, 'generation': record['generation'], 'phase': record['phase'], 'state': record.get('state'),
                     'attempt': row['attempt'], 'delivered_generation': row.get('generation'), 'package': row.get('package'),
                     'revision': row.get('revision'), 'delivered': row.get('delivered', []), 'status': status, 'delta': d,
                     'recheck': gate['action'] == 'recheck', **({'sources_changed': sources} if sources else {}),
                     **({'inputs_changed': inputs} if inputs else {})})
    return {'data_not_authority': True, 'plan': namespaces.parse(selector)[0], 'consumers': rows,
            'note': 'Delivery and its delta only: this never shows what a worker understood, and it grants or refuses nothing.'}
