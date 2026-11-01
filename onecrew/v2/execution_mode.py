"""2.4-C: the recorded, reasoned choice of HOW the next worker node runs (basic policy, ROADMAP-DESIGN 20261026 §2.2).

`choose` is pure: it reads the engine view and the facts the caller measured, writes nothing, launches nothing and calls no model.
The modes:
  continue_worker - the node continues its own attempt chain (node.resumed / resume_artifact / continues_attempt): the root budget is
                    not reset, spent calls stay spent, the partial candidate and its evidence are kept (the next generation has its own child
                    task). It is NOT a model session: no shipped adapter keeps one (session.reuse is False).
  overlap         - the node runs beside another worker node in the second slot (capacity 1-2), independent of it by write, read<->write
                    and `resources` labels.
  run_now         - the default single dispatch; for a second slot it means "not now, in turn" (the slot is not filled).
  tools           - the mandatory checks of a produced node that need no model (command / adapter verifiers): no child task, no model
                    slot, allowed while a worker node is active. A check that needs a reviewer model is never `tools`.
  wait            - blocked; the reasons name what blocks.

Decision order (§2.2): (1) role, dependency, exclusive resources, budget, previous attempt state, capacity; (2) the context package is
present (every input has its artifact) and the restore path is named; (3) overlap gain against the handover cost. A cost that was not
measured is unknown, never 0, so no gain is claimed (run_now, handover_unknown). A clearly independent branch that receives nothing from
another node (only its own source snapshot) may overlap under the stated simple-policy assumption; (4) the caller executes through the
existing admission (Control.reserve) and records mode, reasons and inputs_sha. Estimates are compared, never turned into caps or budgets.

`facts` and `measure` read the ledger (read-only); they never write.
"""
import datetime as dt
import json
import statistics

from ..ledger import LedgerError, content_hash
from ..dependency_core import owned_overlap

CAPABILITY = 'execution-mode'
MODES = ('continue_worker', 'overlap', 'run_now', 'tools', 'wait')
UNKNOWN = 'unknown'
SESSION_CAPABILITY = 'resume_session'
KNOWLEDGE_ADAPTERS = ('common-native-artifact', 'managed-native-artifact')     # adapters whose prepare() adds knowledge.for_native
MODEL_FREE = ('command',)                                                     # milestone verifier types that need no model (adapters: port)


def enabled(view):
    return CAPABILITY in (view or {}).get('capabilities', ())


# ---- exclusive resources ----------------------------------------------------------------------------------------------------

def conflicts(a, b):
    """Why nodes `a` and `b` may not run at the same time (empty when independent): a shared write, one's read against the other's
    write (an unstable API / file another node is changing), a shared `resources` label (an exclusive token such as db:dev)."""
    out = []
    if owned_overlap(a.get('write', []), b.get('write', [])): out.append('write_overlap')
    if owned_overlap(a.get('read', []), b.get('write', [])) or owned_overlap(b.get('read', []), a.get('write', [])): out.append('read_write')
    shared = sorted({str(r).casefold() for r in a.get('resources', [])} & {str(r).casefold() for r in b.get('resources', [])})
    if shared: out.append('shared_resource:' + ','.join(shared))
    return out


def exclusive_blocks(view):
    """Pending nodes that conflict with an ACTIVE node by read<->write or a shared resource (write overlap is already refused by _ready)."""
    nodes = {n['id']: n for n in (view.get('definition') or {}).get('nodes', [])}
    blocked = {}
    for active in view.get('active_nodes', []):
        other = nodes.get(active['node'])
        if other is None: continue
        for nid, node in nodes.items():
            if nid != active['node'] and conflicts(node, other): blocked[nid] = True
    return blocked


# ---- the context restore path and the session --------------------------------------------------------------------------------

def restored_from(node, record, declaration=None):
    """How the attempt's context is rebuilt (no model session is kept): the engine's source snapshot, the upstream input artifacts, the
    partial candidate of a continuation, the project knowledge the native adapters add. Never 'resume_pack' (that is plan level)."""
    out = ['source_snapshot']
    if node.get('depends'): out.append('input_artifacts')
    if record.get('resume_artifact'): out.append('resume_artifact')
    if declaration is not None and getattr(declaration, 'name', None) in KNOWLEDGE_ADAPTERS: out.append('knowledge')
    return out


def session(declaration=None, launched=None, returned=None):
    """reuse True only when the adapter DECLARES resume_session and returned the same session id it launched with (the identity check of
    v1 native_audit). Every shipped adapter declares nothing of the kind, so it is always False today."""
    declared = declaration is not None and declaration.supports(SESSION_CAPABILITY)
    if not declared:
        return {'reuse': False, 'evidence': None, 'basis': 'the adapter declares no resume_session: the context is rebuilt, not a warm start'}
    if not (isinstance(launched, str) and launched and isinstance(returned, str) and returned):
        return {'reuse': False, 'evidence': None, 'basis': 'resume_session declared but no launched/returned session id was reported'}
    if launched != returned:
        return {'reuse': False, 'evidence': {'launched': launched, 'returned': returned}, 'basis': 'the returned session id differs from the launched one'}
    return {'reuse': True, 'evidence': {'launched': launched, 'returned': returned}, 'basis': 'the adapter returned the session id it launched with'}


# ---- the choice ------------------------------------------------------------------------------------------------------------------

def _wait(reasons, inputs, record, node, declaration, **extra):
    return _result('wait', reasons, inputs, record, node, declaration, **extra)


def _result(mode, reasons, inputs, record, node, declaration, **extra):
    body = dict(inputs, mode=mode, reasons=list(reasons))
    out = {'mode': mode, 'reasons': list(reasons), 'inputs': inputs, 'inputs_sha': content_hash(body),
           'session': session(declaration), 'context': {'restored_from': restored_from(node, record or {}, declaration)}}
    out.update(extra)
    return out


def _tools(node, record, inputs, *, checker, check_types, declaration):
    types = check_types or {}
    needs_model = sorted(cid for cid, kind in types.items() if kind == 'reviewer')
    unmapped = sorted(c['id'] for c in node.get('checks', []) if types.get(c['id']) is None)
    if checker is None:
        return _wait(['no_model_free_checker'], inputs, record, node, declaration)
    if needs_model:
        return _wait(['review_needs_model:' + ','.join(needs_model)], inputs, record, node, declaration)
    if unmapped and getattr(checker, 'model_free', False) is not True:
        return _wait(['checker_not_declared_model_free'], inputs, record, node, declaration)
    return _result('tools', ['produced_not_verified', 'checks_need_no_model'], inputs, record, node, declaration)


def choose(node, view, *, slots, declaration=None, ceilings=None, previous=None, handover=None, peer=None, filling=False,
           capacity=None, checker=None, check_types=None):
    """The mode for `node` now. `peer`: the other worker node this one would run beside (the batch partner or an active node);
    `filling`: this node is the one that would take the SECOND slot (the overlap rule applies to it). `handover`: facts()['handover'];
    `capacity`: facts()['capacity']; `previous`: facts()['previous']; `ceilings`: internal_plan.ceilings. Returns
    {mode, reasons, inputs, inputs_sha, session, context}."""
    from . import engine
    nid = node['id']
    record = view['nodes'].get(nid, {})
    role = (node.get('executor') or {}).get('role', 'worker')
    inputs = {'node': nid, 'generation': record.get('generation'), 'internal_revision': view.get('internal_revision'),
              'contract_sha': view.get('contract_sha'), 'slots': slots, 'peer': peer['id'] if peer else None, 'filling': bool(filling),
              'active': sorted(a['node'] for a in view.get('active_nodes', []) if a['node'] != nid),
              'executor': declaration.view() if declaration is not None else None}
    if record.get('state') == 'produced' and record.get('phase') == 'complete':
        stable = {key: inputs[key] for key in ('node', 'generation', 'internal_revision', 'contract_sha')}
        stable.update(artifact=record.get('artifact'), checks=[c['id'] for c in node.get('checks', [])], check_types=check_types or {})
        return _tools(node, record, stable, checker=checker, check_types=check_types, declaration=None)
    # (1) role, dependency, exclusive resources, budget, previous attempt, capacity
    if role != 'worker':
        return _wait(['not_a_worker_node'], inputs, record, node, declaration)
    gate = engine.eligible(view, nid)
    if not gate['ready']:
        return _wait(['not_eligible: ' + gate['reason']], inputs, record, node, declaration)
    definitions = {n['id']: n for n in view['definition']['nodes']}
    for active in view.get('active_nodes', []):
        if active['node'] == nid: continue
        found = conflicts(node, definitions.get(active['node'], {'write': active.get('write', [])}))
        if found:
            return _wait(['exclusive_resource:' + active['node'] + ':' + '+'.join(found)], inputs, record, node, declaration)
    if previous and previous.get('attempt_status') in ('reserved', 'running', 'unknown'):
        return _wait(['previous_attempt_unresolved:' + str(previous['attempt_status'])], inputs, record, node, declaration)
    if ceilings is not None:
        inputs['remaining_calls'] = ceilings.get('remaining_calls')
        if type(ceilings.get('remaining_calls')) is int and ceilings['remaining_calls'] < node['budget_calls']:
            return _wait(['budget_exhausted'], inputs, record, node, declaration)
    if capacity is not None:
        inputs['capacity'] = {'active': capacity.get('active'), 'limit': capacity.get('limit')}
        if capacity.get('active', 0) >= capacity.get('limit', 2):
            return _wait(['capacity_full'], inputs, record, node, declaration)
    others = [a for a in view.get('active_nodes', []) if a['node'] != nid]
    if len(others) >= slots:
        return _wait(['no_free_slot'], inputs, record, node, declaration)
    # (2) the context package
    missing = sorted(edge['node'] for edge in node.get('depends', []) if not view['nodes'].get(edge['node'], {}).get('artifact'))
    if missing:
        return _wait(['context_missing:' + ','.join(missing)], inputs, record, node, declaration)
    reasons = ['context_package_present']
    # (3) the mode
    if record.get('resume_artifact') or record.get('continues'):
        return _result('continue_worker', reasons + ['continues_own_attempt_chain', 'root_budget_not_reset', 'evidence_kept', 'not_a_model_session'],
                       inputs, record, node, declaration)
    concurrent = peer is not None
    if not concurrent:
        return _result('run_now', reasons + (['single_slot'] if slots == 1 else ['no_independent_peer']), inputs, record, node, declaration)
    if slots != 2 or declaration is None or not declaration.supports('isolate'):
        return _result('run_now', reasons + ['no_isolated_second_slot'], inputs, record, node, declaration)
    found = conflicts(node, peer)
    if found:
        return _result('run_now', reasons + ['exclusive_resource:' + peer['id'] + ':' + '+'.join(found)], inputs, record, node, declaration)
    if not filling:
        return _result('overlap', reasons + ['beside:' + peer['id']], inputs, record, node, declaration)
    if capacity is not None and capacity.get('active', 0) + 1 >= capacity.get('limit', 2) and not others:
        return _result('run_now', reasons + ['capacity_one_slot'], inputs, record, node, declaration)
    gain = [node['estimate_seconds'][0]] + ([peer['estimate_seconds'][0]] if peer.get('estimate_seconds') else [])
    gain_seconds = min(gain)
    handover = handover or {'chars': UNKNOWN, 'seconds': UNKNOWN, 'basis': 'not measured'}
    inputs['handover'] = handover
    inputs['gain_seconds'] = gain_seconds
    if not node.get('depends'):
        return _result('overlap', reasons + ['independent_branch', 'no_handover'], inputs, record, node, declaration,
                       assumptions=['startup and integration costs are not measured; a branch that receives nothing from another node may '
                                    'overlap under the simple policy (the mandatory integration node rechecks the whole)'])
    if handover.get('seconds') == UNKNOWN or handover.get('seconds') is None:
        return _result('run_now', reasons + ['handover_unknown'], inputs, record, node, declaration)
    if handover['seconds'] >= gain_seconds:
        upstream = handover.get('largest') or (node['depends'][0]['node'] if node.get('depends') else None)
        return _result('run_now', reasons + ['handover_exceeds_gain'], inputs, record, node, declaration,
                       recommendation=f'merge {nid} into {upstream} at plan time (engine revise, Q1): a worker does not outlive its attempt')
    return _result('overlap', reasons + ['gain_exceeds_handover'], inputs, record, node, declaration)


def idle(view):
    """The wait of a root with nothing ready: one line per node that is not complete, naming what holds it."""
    from . import engine
    reasons = []
    for node in (view.get('definition') or {}).get('nodes', []):
        nid, record = node['id'], view['nodes'][node['id']]
        if record['phase'] == 'pending':
            gate = engine.eligible(view, nid)
            reasons.append(f'{nid}: ' + (gate['reason'] if not gate['ready'] else 'no free slot or an exclusive resource is held'))
        elif record['phase'] == 'running': reasons.append(f'{nid}: running')
        elif record['phase'] == 'held': reasons.append(f'{nid}: held ({str(record.get("classification") or record.get("reason"))[:80]})')
    inputs = {'node': None, 'internal_revision': view.get('internal_revision'), 'contract_sha': view.get('contract_sha'),
              'root_status': view.get('root_status'), 'active': sorted(a['node'] for a in view.get('active_nodes', [])), 'pending': reasons}
    body = dict(inputs, mode='wait', reasons=reasons or ['nothing_pending'])
    return {'mode': 'wait', 'reasons': reasons or ['nothing_pending'], 'inputs': inputs, 'inputs_sha': content_hash(body),
            'session': session(None), 'context': {'restored_from': []}}


def record_fields(decision):
    """What node.started / the Q2 action carry."""
    return {'mode': decision['mode'], 'mode_reasons': decision['reasons'], 'mode_inputs_sha': decision['inputs_sha'],
            'session': decision['session'], 'context': decision['context'],
            **({'recommendation': decision['recommendation']} if decision.get('recommendation') else {})}


# ---- facts (read-only) -------------------------------------------------------------------------------------------------------

def _receipt(store, key):
    if not isinstance(key, str): return None
    try:
        body = json.loads(store.read_blob(key))
    except (ValueError, TypeError, OSError, LedgerError):
        return None
    return body if isinstance(body, dict) else None


def _time(text):
    try:
        value = dt.datetime.fromisoformat(str(text))
    except (TypeError, ValueError):
        return None
    return value if value.tzinfo else value.replace(tzinfo=dt.timezone.utc)


def _attempt_times(conn, attempt_id):
    """(reserved, launched, settled) datetimes of one attempt from its own events; None for an event that was not written."""
    out = {}
    for row in conn.execute("SELECT kind,created_at FROM events WHERE kind IN ('attempt.reserved','attempt.launched','attempt.settled') "
                            "AND json_extract(payload,'$.id')=? ORDER BY seq", (attempt_id,)):
        out.setdefault(row['kind'], _time(row['created_at']))
    return out.get('attempt.reserved'), out.get('attempt.launched'), out.get('attempt.settled')


def _prep_rate(conn, view, store):
    """Seconds of preparation per prompt character, from this root's own settled attempts: (launched - reserved) / prompt_chars of their
    native receipts. None when nothing was observed (then a handover cost is unknown, never 0)."""
    rates = []
    for record in view['nodes'].values():
        if not record.get('attempt') or not record.get('receipt'): continue
        body = _receipt(store, record['receipt'])
        chars = (body or {}).get('prompt_chars')
        if type(chars) is not int or chars <= 0: continue
        reserved, launched, _ = _attempt_times(conn, record['attempt'])
        if reserved and launched and launched >= reserved: rates.append((launched - reserved).total_seconds() / chars)
    return (statistics.median(rates), len(rates)) if rates else (None, 0)


def facts(ledger, conn, view, nid):
    """What `choose` needs that the view does not hold: the previous attempt's status, the global capacity of this state root, and
    the handover cost of the node's inputs (the context each upstream worker was given - its receipt prompt_chars - times the observed
    preparation rate). Read-only."""
    from ..snapshots import Snapshots
    from ..admission_core import active_consultations
    store = Snapshots(ledger.state_root)
    record = view['nodes'].get(nid, {})
    previous = None
    if record.get('attempt'):
        row = conn.execute('SELECT status FROM attempts WHERE id=?', (record['attempt'],)).fetchone()
        previous = {'attempt': record['attempt'], 'attempt_status': row['status'] if row else UNKNOWN}
    has_attempts = conn.execute("SELECT 1 FROM sqlite_master WHERE name='attempts'").fetchone()
    active = conn.execute("SELECT COUNT(*) FROM attempts WHERE status IN ('reserved','running','unknown')").fetchone()[0] if has_attempts else 0
    capacity = {'active': active + active_consultations(conn), 'limit': 2}
    node = next((n for n in (view.get('definition') or {}).get('nodes', []) if n['id'] == nid), None)
    handover = {'chars': 0, 'seconds': 0.0, 'basis': 'no input from another node'}
    if node and node.get('depends'):
        chars, largest, known = 0, None, True
        for edge in node['depends']:
            body = _receipt(store, view['nodes'].get(edge['node'], {}).get('receipt'))
            size = (body or {}).get('prompt_chars')
            if type(size) is not int:
                known = False; continue
            chars += size
            if largest is None or size > largest[1]: largest = (edge['node'], size)
        rate, observed = _prep_rate(conn, view, store)
        if not known:
            handover = {'chars': UNKNOWN, 'seconds': UNKNOWN, 'basis': 'an upstream receipt reports no prompt size'}
        elif rate is None:
            handover = {'chars': chars, 'seconds': UNKNOWN, 'basis': 'no preparation span observed on this root'}
        else:
            handover = {'chars': chars, 'seconds': round(rate * chars, 6), 'largest': largest[0] if largest else None,
                        'basis': f'median preparation rate of {observed} observed attempt(s) x the context the upstream worker(s) were given'}
    return {'previous': previous, 'capacity': capacity, 'handover': handover}


def check_types(contract, node):
    """check id -> the verifier type of the approved milestone it names (None when it names none: a fixture or a direct checker)."""
    milestones = {m['id']: m for m in (contract or {}).get('milestones', [])}
    return {c['id']: (milestones[c['id']]['verifier']['type'] if c['id'] in milestones else None) for c in node.get('checks', [])}


# ---- measurement (read-only) -----------------------------------------------------------------------------------------------

def _span(start, end):
    return round((end - start).total_seconds(), 6) if start and end and end >= start else UNKNOWN


def _union(intervals):
    from .executors import union_seconds
    known = [(a, b) for a, b in intervals if a and b and b >= a]
    return round(union_seconds(known), 6) if known else UNKNOWN


def measure(ledger, selector):
    """Per root, from the ledger only: time to the first useful action, admission/preparation/execution spans per attempt, waits
    (the persisted mode waits included), verification spans, rework. A span whose end or start was not observed is `unknown`, never 0;
    overlapping branches are joined by union, never summed."""
    from . import engine, plan as plans
    from ..snapshots import Snapshots
    with ledger.transaction() as conn:
        root = plans.anchor_events(ledger, conn, selector)
        rows = [(r['seq'], r['kind'], json.loads(r['payload']), _time(r['created_at']))
                for r in conn.execute('SELECT seq,kind,payload,created_at FROM events WHERE task_id=? ORDER BY seq', (root['task_id'],))]
        attempts = {}
        for seq, kind, payload, at in rows:
            if kind == 'node.started':
                reserved, launched, settled = _attempt_times(conn, payload['attempt'])
                attempts[payload['attempt']] = {'node': payload['node'], 'generation': payload['generation'], 'started': at,
                                                'reserved': reserved, 'launched': launched, 'settled': settled, 'mode': payload.get('mode')}
    store = Snapshots(ledger.state_root)
    approved = next((at for _, kind, _, at in rows if kind == 'plan.approved'), None)
    q2 = {}
    for _, kind, payload, at in rows:
        if kind == 'decision.recorded' and str(payload.get('basis', '')).startswith('Q2'):
            scope = payload.get('scope')
            q2.setdefault(scope, []).append(at)
    first_useful = next((at for _, kind, _, at in rows if kind == 'node.produced'), None)
    per_attempt, verify, waits, rework = [], [], [], {'resumed': 0, 'verification_failed': 0, 'retained': 0}
    produced = {}
    for _, kind, payload, at in rows:
        key = (payload.get('node'), payload.get('generation'))
        if kind == 'node.produced': produced[key] = at
        elif kind == 'node.verification':
            verify.append({'node': key[0], 'generation': key[1], 'result': payload.get('result'),
                           'seconds': _span(produced.get(key), at)})
            if payload.get('result') == 'fail': rework['verification_failed'] += 1
        elif kind == 'node.resumed': rework['resumed'] += 1
        elif kind == 'node.result_retained': rework['retained'] += 1
    for attempt_id, item in attempts.items():
        decided = [t for t in q2.get(item['node'], []) if t and item['started'] and t <= item['started']]
        body = None
        for _, kind, payload, _ in rows:
            if kind == 'node.produced' and payload.get('node') == item['node'] and payload.get('generation') == item['generation']:
                body = _receipt(store, payload.get('receipt'))
        per_attempt.append({'attempt': attempt_id, 'node': item['node'], 'generation': item['generation'], 'mode': item['mode'] or UNKNOWN,
                            'admission_seconds': _span(decided[-1] if decided else None, item['started']),
                            'preparation_seconds': _span(item['reserved'], item['launched']),
                            'execution_seconds': _span(item['launched'], item['settled']),
                            'span_seconds': _span(item['reserved'], item['settled']),
                            'prompt_chars': (body or {}).get('prompt_chars', UNKNOWN)})
    # waits: a persisted mode wait lasts until the next record (or node.started) of the same node; still open -> until unknown
    mode_rows = [(at, payload) for _, kind, payload, at in rows if kind in ('workflow.mode', 'node.started')]
    for index, (at, payload) in enumerate(mode_rows):
        if payload.get('mode') != 'wait': continue
        later = next((t for t, p in mode_rows[index + 1:] if p.get('node') == payload.get('node') and p.get('mode') != 'wait'
                      or (payload.get('node') is None and p.get('mode') != 'wait')), None)
        waits.append({'node': payload.get('node'), 'reasons': payload.get('mode_reasons', payload.get('reasons')), 'at': at.isoformat() if at else UNKNOWN,
                      'until': later.isoformat() if later else UNKNOWN, 'seconds': _span(at, later) if later else UNKNOWN})
    from .executors import summary
    observed_waits = [w for a in summary(ledger, root['selector'])['attempts'] for w in a['waits']]
    spans = [(a['reserved'], a['settled']) for a in attempts.values()]
    return {'plan': root['selector'], 'root': root['task_id'],
            'time_to_first_useful_action_seconds': _span(approved, first_useful) if approved and first_useful else UNKNOWN,
            'first_useful_action': 'first node.produced' if first_useful else UNKNOWN,
            'attempts': per_attempt, 'waits': waits, 'executor_waits': observed_waits,
            'wait_seconds': _union([(_time(w['at']), _time(w['until'])) for w in waits]) if waits and all(w['until'] != UNKNOWN for w in waits) else UNKNOWN,
            'verification': verify, 'rework': rework,
            'attempts_wall_seconds': _union(spans) if spans and all(a and b for a, b in spans) else UNKNOWN,
            'method': 'ledger event times (events.created_at); spans with a missing end are unknown; overlapping attempts are joined by union'}
