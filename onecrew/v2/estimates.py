"""W32a: sourced forecast ranges, separate from execution grants and budgets."""
import datetime as dt
import json
import math
import argparse
from pathlib import Path

from ..ledger import LedgerError, content_hash, key_field, text_field, utcnow
from . import namespaces, plan

KINDS = ('estimate.baseline', 'estimate.eta', 'work.additional')


def interval(value, optional=False):
    if value is None and optional: return None
    if (not isinstance(value, (list, tuple)) or len(value) != 2 or
            any(type(v) not in (int, float) or not math.isfinite(v) or v < 0 for v in value) or value[0] > value[1]):
        raise LedgerError('Estimate must be a finite non-negative [low, high] range in seconds.')
    return list(value)


def normalize_evidence(value):
    if not isinstance(value, list) or not 1 <= len(value) <= 20:
        raise LedgerError('An estimate change requires 1..20 evidence references.')
    for ref in value:
        text_field(ref, 'evidence', 500)
        if not ref.strip(): raise LedgerError('An evidence reference cannot be empty.')
    return list(value)


evidence = normalize_evidence  # Existing callers use this shared validation API.


def normalize(value):
    if value is None:
        return {'execution_seconds': None, 'deadline': None, 'evidence': [], 'policy': {'relative_change': 0.25}}
    if not isinstance(value, dict) or set(value) - {'execution_seconds', 'deadline', 'evidence', 'policy'}:
        raise LedgerError('Estimate takes execution_seconds, deadline, evidence and policy.')
    span = interval(value.get('execution_seconds'), optional=True)
    refs = evidence(value.get('evidence')) if span is not None else []
    deadline = value.get('deadline')
    if deadline is not None:
        try:
            parsed = dt.datetime.fromisoformat(deadline)
            if parsed.tzinfo is None: raise ValueError('timezone required')
        except (TypeError, ValueError) as error:
            raise LedgerError('Deadline must be an ISO time with timezone.') from error
        deadline = parsed.isoformat()
    policy = value.get('policy', {'relative_change': 0.25})
    if (not isinstance(policy, dict) or set(policy) != {'relative_change'} or
            type(policy['relative_change']) not in (int, float) or not 0 < policy['relative_change'] <= 1):
        raise LedgerError('Estimate policy relative_change must be in (0,1].')
    return {'execution_seconds': span, 'deadline': deadline, 'evidence': refs, 'policy': dict(policy)}


def _events(conn, task):
    return [dict(json.loads(r['payload']), event=r['seq']) for r in conn.execute(
        "SELECT seq,payload FROM events WHERE task_id=? AND kind IN ('estimate.baseline','estimate.eta','work.additional') ORDER BY seq", (task,))]


def ensure_baseline(ledger, conn, selector, value=None):
    """Immediately after approval, once per root. Reapproval never resets it."""
    state = plan.anchor_events(ledger, conn, selector)
    old = _events(conn, state['task_id'])
    if any(p.get('estimate_type') == 'baseline' for p in old): return
    approved = state['approved']
    if not approved: raise LedgerError('An estimate baseline requires approval.')
    plan.emit(ledger, conn, state['task_id'], 'estimate.baseline', dict(
        normalize(value), plan=state['name'], revision=approved['revision'], estimate_type='baseline',
        approval_sha=approved['sha'], source='declared_estimate' if value else 'not_supplied', calibrated=False))


def _state(ledger, conn, selector):
    state = plan.anchor_events(ledger, conn, selector)
    if not state['approved'] or state['status'] in ('accepted', 'closed'): raise LedgerError('Forecast changes require an open approved plan.')
    return state


def _append(ledger, conn, state, kind, value):
    for old in _events(conn, state['task_id']):
        if old.get('key') != value['key']: continue
        if any(old.get(k) != v for k, v in value.items()): raise LedgerError('Estimate key already binds a different change.')
        return old
    plan.emit(ledger, conn, state['task_id'], kind, value)
    return value


def reforecast(ledger, selector, key, remaining_seconds, reason, refs):
    key_field(key); text_field(reason, 'reason', 1000)
    if not reason.strip(): raise LedgerError('A forecast change requires a reason.')
    span, refs = interval(remaining_seconds), evidence(refs)
    with ledger.transaction(write=True) as conn:
        state = _state(ledger, conn, selector)
        result = _append(ledger, conn, state, 'estimate.eta', dict(
            key=key, estimate_type='eta', remaining_seconds=span, reason=reason, evidence=refs,
            revision=state['approved']['revision'], plan=state['name'], calibrated=False))
    from .exceptions import observe
    observe(ledger, selector)
    return result


def additional(ledger, selector, key, category, reason, acceptance, seconds, refs, *, nodes=None, still_running=None):
    """One piece of work found on the way (T36b [E11]). mandatory -> the forecast; optional -> the backlog, never the ETA;
    outside_authority -> the work is NOT taken: one U2 request names it, and the internal nodes that depend on it (`nodes`) are held
    through the unknown mechanism (W31a) until the owner's answer resolves it; everything else keeps running."""
    key_field(key); text_field(reason, 'reason', 1000)
    if not reason.strip(): raise LedgerError('Additional work requires a reason.')
    if category not in ('mandatory', 'optional', 'outside_authority'): raise LedgerError('Unknown additional work category.')
    nodes, still_running = _node_lists(ledger, selector, nodes, still_running)        # refused BEFORE any write
    if nodes and category != 'outside_authority':
        raise LedgerError('Only outside-authority work holds nodes; mandatory work goes to the forecast, optional work to the backlog.')
    span, refs = interval(seconds), evidence(refs)
    with ledger.transaction(write=True) as conn:
        state = _state(ledger, conn, selector)
        contract = plan.load(ledger, state, state['approved']['revision'])[0]
        allowed = {'O' + str(i + 1) for i in range(len(contract['output']))}
        if not isinstance(acceptance, list) or not acceptance or not set(acceptance) <= allowed:
            raise LedgerError('Additional work must name approved acceptance IDs.')
        result = _append(ledger, conn, state, 'work.additional', dict(
            key=key, estimate_type='additional', category=category, reason=reason, acceptance=acceptance,
            execution_seconds=span, evidence=refs, plan=state['name'], revision=state['approved']['revision'],
            disposition={'mandatory': 'forecast', 'optional': 'backlog', 'outside_authority': 'U2'}[category],
            grants_execution=False))
    if category == 'outside_authority':
        result['u2'] = _outside_authority(ledger, selector, key, reason, acceptance, refs, nodes, still_running)   # raises when the hold cannot be written
    internal = observe_internal(ledger, selector, reason=reason, evidence=refs)
    if internal is None:
        from .exceptions import observe
        observe(ledger, selector)
    return result


def _node_lists(ledger, selector, nodes, still_running):
    """The dependent nodes (to hold) and the nodes named as still running: lists of ids of the current internal plan, disjoint. Checked
    before anything is written, so a typo never leaves a U2 without its hold."""
    def checked(value, field):
        if value is None: return []
        if not isinstance(value, list) or not all(isinstance(n, str) and n for n in value) or len(set(value)) != len(value):
            raise LedgerError(f'{field}: a list of distinct internal node ids.')
        return list(value)
    nodes, still_running = checked(nodes, 'nodes'), checked(still_running, 'still_running')
    if not nodes and not still_running: return nodes, still_running
    from . import internal_plan as ip
    with ledger.transaction() as conn:
        root = plan.anchor_events(ledger, conn, selector)
        current = ip.current(ledger, root['selector'], conn) if namespaces.has_capability(root, 'sequential-engine') else None
    known = {n['id'] for n in (current or {}).get('definition', {}).get('nodes', [])} if current and current.get('definition') else set()
    unknown = [n for n in nodes + still_running if n not in known]
    if unknown: raise LedgerError(f'nodes/still_running name nodes that are not in the current internal plan: {", ".join(unknown)}.')
    if set(nodes) & set(still_running): raise LedgerError('a node cannot be both held and still running.')
    return nodes, still_running


def _outside_authority(ledger, selector, key, reason, acceptance, refs, nodes, still_running):
    """T36b [E11]: the U2 request for work outside the grant (one per key, idempotent) and the hold of exactly the dependent nodes.
    The hold is opened FIRST (runtime_unknowns, idempotent by key): if it cannot be written the error propagates — the caller never
    hears "held" when nothing holds. A retry re-enters every step idempotently (work.additional by key, request by key, unknown by key)."""
    with ledger.transaction() as conn:
        state = _state(ledger, conn, selector)
    task_id = state['task_id']
    request_key = 'additional:' + key
    question = {'schema_version': 1,
                'question': f'Việc phát sinh «{key}» nằm ngoài quyền đã cấp: {reason.strip()}',
                'reason': 'Phát sinh vượt quyền (U2): OneCrew không tự làm; cần chủ sở hữu cấp quyền hoặc bỏ.',
                'impact': ('Giữ ' + ', '.join(nodes) if nodes else 'Không giữ node nào') + ('; vẫn chạy ' + ', '.join(still_running) if still_running else '') + f'; acceptance liên quan: {", ".join(acceptance)}.',
                'options': [{'id': 'grant', 'label': 'Cấp quyền cho việc phát sinh này (amend hợp đồng)'}, {'id': 'skip', 'label': 'Không làm; giữ phạm vi đã duyệt'}],
                'recommendation': 'skip',
                'action': {'type': 'authorize', 'parameters': {'class': 'U2', 'additional': key, 'acceptance': acceptance, 'nodes': nodes,
                                                               'still_running': still_running, 'evidence': refs}}}
    held = None
    if nodes:
        from . import runtime_unknowns
        held = runtime_unknowns.open_unknown(ledger, selector, 'additional-' + key, question=question['question'], affected=nodes, required_by=nodes,
                                             resolver='owner', evidence=refs)
        if not held or held.get('state') != 'open' and held.get('state') != 'resolved':
            raise LedgerError('The hold of the dependent nodes was not written; the outside-authority work is not recorded as held.')
    existing = next((r for r in ledger.requests(task_id) if r['question'].get('action', {}).get('parameters', {}).get('additional') == key), None)
    request = existing or ledger.create_request(task_id, request_key, question)
    return {'request': request['id'], 'request_revision': request['revision'], 'class': 'U2', 'held_nodes': nodes, 'unknown': held}


def _internal_projection(ledger, conn, selector, rows):
    """Use the engine's actual completion/generation rules, never a second DAG."""
    from . import namespaces
    root = plan.anchor_events(ledger, conn, selector)
    if not namespaces.has_capability(root, 'sequential-engine'): return None
    from . import engine, internal_plan, runtime_unknowns
    view = engine.state(ledger, selector, conn)
    if view['definition'] is None: return None
    revision = internal_plan.current(ledger, selector, conn)
    unknowns = [row for row in runtime_unknowns.read(ledger, selector, conn)
                if row['state'] == 'open' and row['blocks_estimate']]
    unknown_nodes = []
    remaining = [0, 0]
    basis_nodes = []
    for node in view['definition']['nodes']:
        record = view['nodes'][node['id']]
        unfinished = engine._rank(record) < engine.STATES['verified']
        span = interval(node.get('estimate_seconds'), optional=True)
        basis_nodes.append({'node':node['id'], 'generation':record['generation'], 'state':record['state'],
                            'phase':record['phase'], 'verification_result':record.get('verification_result'),
                            'artifact':record.get('artifact'), 'estimate_seconds':span, 'unfinished':unfinished})
        if unfinished:
            if span is None: unknown_nodes.append(node['id'])
            else: remaining = [a+b for a,b in zip(remaining,span)]
    # An explicit source reference means the mandatory work now lives in the
    # internal decomposition. It is counted there once, including after replan.
    additions = [row for row in rows if row.get('estimate_type') == 'additional' and row['category'] == 'mandatory']
    incorporated = {key for row in rows if row.get('source') == 'internal_plan'
                    for key in row.get('incorporated_additions', [])}
    refs = revision.get('evidence', [])
    incorporated.update(row['key'] for row in additions if 'work.additional:'+row['key'] in refs)
    unincorporated = [row for row in additions if row['key'] not in incorporated]
    extra = [sum(row['execution_seconds'][index] for row in unincorporated) for index in (0,1)]
    stale = view['definition_contract_sha'] != view['contract_sha'] or view['definition_contract_revision'] != view['contract_revision']
    missing = bool(unknowns or unknown_nodes or stale)
    total = None if missing else [a+b for a,b in zip(remaining,extra)]
    basis = {'contract_sha':view['contract_sha'], 'contract_revision':view['contract_revision'],
             'definition_sha':revision.get('definition_sha'), 'internal_revision':view['internal_revision'],
             'nodes':basis_nodes, 'unknowns':[{'id':row['unknown'],'event':row['event']} for row in unknowns],
             'unknown_nodes':unknown_nodes, 'stale_definition':stale,
             'mandatory_additions':[{'key':row['key'],'event':row['event']} for row in additions],
             'incorporated_additions':sorted(incorporated)}
    return {'basis':basis, 'basis_sha':content_hash(basis), 'remaining_seconds':total,
            'node_work_seconds':None if missing else remaining, 'unincorporated_additional_seconds':extra,
            'incorporated_additions':sorted(incorporated), 'revision_event':revision['event'],
            'remaining_kind':'execution_work', 'wall_clock_remaining_seconds':None,
            'wall_clock_reason':'Task effort is not an elapsed-time forecast; waits and parallel scheduling are not estimated.',
            'unknown_reason':'Unresolved estimate input or stale approved definition.' if missing else None}


def observe_internal(ledger, selector, *, reason, evidence):
    """Snapshot the current remaining execution work under the ledger write lock.

    The approved baseline is never changed. Duplicate observations reuse their
    basis. Read-only views never invent a new ETA when state has changed without
    a matching observation. Call after publishing a revision or node transition.
    """
    reason = text_field(reason, 'reason', 1000)
    if not reason.strip(): raise LedgerError('An internal forecast requires a reason.')
    refs = normalize_evidence(evidence)
    with ledger.transaction(write=True) as conn:
        state = plan.anchor_events(ledger, conn, selector)
        if state['status'] != 'approved': return None
        rows = _events(conn, state['task_id'])
        projection = _internal_projection(ledger, conn, selector, rows)
        if projection is None: return None
        previous = next((row for row in reversed(rows) if row.get('estimate_type') == 'eta'), None)
        if previous and previous.get('source') == 'internal_plan' and previous.get('basis_sha') == projection['basis_sha']:
            return previous
        key = 'internal-' + content_hash({'basis':projection['basis_sha'], 'after':previous['event'] if previous else None})
        value = dict(projection, key=key, estimate_type='eta', source='internal_plan',
                     plan=state['name'], revision=state['approved']['revision'], reason=reason,
                     evidence=[f'event:{projection["revision_event"]}',*refs], calibrated=False)
        _append(ledger, conn, state, 'estimate.eta', value)
    from .exceptions import observe
    observe(ledger, selector)
    return value


def _clock(now):
    """The injected clock (tests pass an ISO string); default: this machine's UTC time."""
    value = now or utcnow()
    try:
        parsed = value if isinstance(value, dt.datetime) else dt.datetime.fromisoformat(value)
        if parsed.tzinfo is None: raise ValueError('timezone required')
        return parsed
    except (TypeError, ValueError) as error:
        raise LedgerError('now: an ISO time with timezone.') from error


def _wall_clock(deadline, now):
    """Time to the deadline (T36b [E4]): deadline - now, in calendar seconds. Waiting has already consumed this time, so it counts toward the
    deadline; it is NOT remaining execution work and NOT a completion ETA (nothing here is calibrated). After the deadline the figure is
    negative and `deadline_passed` is True: it is never clamped. The deadline itself is only read, never moved."""
    if not deadline:
        return {'wall_clock_remaining_seconds': None, 'deadline_passed': None, 'wall_clock_kind': 'time_to_deadline',
                'wall_clock_reason': 'No deadline was approved; there is no time-to-deadline figure.'}
    remaining = (dt.datetime.fromisoformat(deadline) - _clock(now)).total_seconds()
    return {'wall_clock_remaining_seconds': remaining, 'deadline_passed': remaining < 0, 'wall_clock_kind': 'time_to_deadline',
            'wall_clock_reason': 'Calendar time from now to the approved deadline (waiting included); not remaining execution work, not an ETA.'}


def _measured(attempts):
    """Execution = sum of each attempt's execution (waits inside it already excluded); waiting = union of all observed waits.
    Either is 'unknown' as soon as one input is unknown or not measured: never a partial sum shown as the total, never 0."""
    from .executors import UNKNOWN, waits_seconds
    values = [a.get('execution_seconds', UNKNOWN) for a in attempts]
    execution = sum(values) if values and all(type(v) in (int, float) and math.isfinite(v) and v >= 0 for v in values) else UNKNOWN
    waits = [w for a in attempts for w in a.get('waits', [])]
    return execution, waits_seconds(waits)


def _warnings(conn, task):
    rows = [dict(json.loads(r['payload']), event=r['seq']) for r in conn.execute(
        "SELECT seq,payload FROM events WHERE task_id=? AND kind='notice.exception' ORDER BY seq", (task,))]
    return [p for p in rows if p.get('category') == WARNING]


def read(ledger, selector, now=None):
    with ledger.transaction() as conn:
        state = plan.anchor_events(ledger, conn, selector)
        rows = _events(conn, state['task_id'])
        internal = _internal_projection(ledger, conn, selector, rows)
        warnings = _warnings(conn, state['task_id'])
    baseline = next((p for p in rows if p.get('estimate_type') == 'baseline'), None)
    forecasts = [p for p in rows if p.get('estimate_type') == 'eta']
    additions = [p for p in rows if p.get('estimate_type') == 'additional']
    last = forecasts[-1] if forecasts else baseline
    remaining = (last.get('remaining_seconds') if forecasts else last.get('execution_seconds')) if last else None
    if remaining is not None:
        remaining = list(remaining)
        for p in additions:
            if p['category'] == 'mandatory' and p['event'] > last['event']:
                remaining = [a + b for a, b in zip(remaining, p['execution_seconds'])]
    basis_current = True
    if internal is not None:
        basis_current = bool(last and last.get('source') == 'internal_plan' and last.get('basis_sha') == internal['basis_sha'])
        if not basis_current: remaining = None
    from .executors import summary
    attempts = summary(ledger, selector)['attempts']
    execution, waiting = _measured(attempts)
    deadline = baseline.get('deadline') if baseline else None
    return dict({'plan': state['name'], 'baseline': baseline, 'history': forecasts, 'additional': additions,
                 'remaining_seconds': remaining, 'execution_seconds': execution,
                 'waiting_seconds': waiting, 'deadline': deadline,
                 'calibrated': False, 'measurement_sources': attempts,
                 'remaining_kind': 'execution_work', 'internal_basis_current': basis_current,
                 'remaining_reason': None if basis_current else 'Internal state changed; a sourced forecast observation is required.',
                 'budget_warnings': warnings,
                 'outside_authority': [p['key'] for p in additions if p['category'] == 'outside_authority']}, **_wall_clock(deadline, now))


# ---- T36b [E17]: the 70% budget warning of a v2 root ------------------------------------------------------------------------------

WARNING = 'budget_warning'


def warn_budget(ledger, selector):
    """One in-authority notice when the measured use of the root's approved budget crosses the agreed warning fraction.

    The policy is v1's (task_intake.POLICY warning_fraction, thresholds from budget_policy.watch_policy). v1's effort_watch itself is not
    reused: it runs on v1 job checkpoints/Control and turns the warning into a `job.effort_warning` REQUEST, which T36b [E17] forbids while
    the work is within authority. Here the warning is a `notice.exception` event (category budget_warning, grants_authority False,
    user_action None, request None) with reason, evidence and what changed - no request, no approval, no budget or deadline change.
    Axes: execution seconds (waits excluded, [E4]) against budget.time, and executor-measured calls against budget.max_calls. Unknown or
    not-measured attempts add nothing (the known sum is a lower bound, flagged; nothing is guessed). One notice per axis/revision/threshold:
    a later observation above the same threshold writes nothing, and nothing is written periodically."""
    from ..budget_policy import watch_policy
    from ..task_intake import POLICY
    from .executors import summary
    written = []
    with ledger.transaction(write=True) as conn:
        state = plan.anchor_events(ledger, conn, selector)
        if not state['approved'] or state['status'] in ('accepted', 'closed'): return written
        revision = state['approved']['revision']
        budget = (plan.load(ledger, state, revision)[0] or {}).get('budget') or {}
        limits = {'execution_seconds': budget['time'] * 60 if budget.get('time') else None, 'calls': budget.get('max_calls')}
        policy = watch_policy(POLICY, limits['calls'] or 1, limits['execution_seconds'] or 1)
        thresholds = {'execution_seconds': policy['seconds'], 'calls': policy['calls']}
        attempts = summary(ledger, selector)['attempts']
        old = {p.get('cause') for p in _warnings(conn, state['task_id'])}
        for axis in ('execution_seconds', 'calls'):
            if not limits[axis]: continue
            known = [a for a in attempts if type(a.get(axis)) in (int, float)]
            used = sum(a[axis] for a in known)
            cause = f'{axis}:r{revision}:{thresholds[axis]}'
            if used < thresholds[axis] or cause in old: continue
            if axis == 'execution_seconds':
                what, figure = 'thời gian thực thi (không tính thời gian chờ)', f'{used / 3600:g}/{limits[axis] / 3600:g} giờ'
            else:
                what, figure = 'lần gọi', f'{used:g}/{limits[axis]} lần gọi'
            value = {'version': 1, 'category': WARNING, 'cause': cause, 'axis': axis, 'plan': state['name'], 'revision': revision,
                     'reason': f'Đã dùng {policy["fraction"]:.0%} ngân sách {what}: {figure}. Vẫn trong quyền đã duyệt; OneCrew tiếp tục.',
                     'evidence': ([f'contract:{state["name"]}@r{revision}:budget', f'approval:{state["approved"]["sha"]}']
                                  + [f'executor.observed:{a["executor"]}:{a["attempt"]}' for a in known if a[axis]])[:20],
                     'what_changed': {'used': used, 'limit': limits[axis], 'threshold': thresholds[axis],
                                      'used_is_lower_bound': len(known) != len(attempts)},
                     'policy': {'source': 'onecrew.task_intake.POLICY', 'version': POLICY['version'], 'fraction': policy['fraction']},
                     'occurred_at': utcnow(), 'grants_authority': False, 'user_action': None, 'request': None}
            plan.emit(ledger, conn, state['task_id'], 'notice.exception', value)
            old.add(cause)
            written.append(value)
    return written


def main(argv):
    parser = argparse.ArgumentParser(prog='onecrew estimate', allow_abbrev=False)
    parser.add_argument('--project', type=Path, default=Path.cwd()); parser.add_argument('--state-root', type=Path)
    sub = parser.add_subparsers(dest='group', required=True).add_parser('estimate').add_subparsers(dest='command', required=True)
    p = sub.add_parser('show'); p.add_argument('plan')
    p = sub.add_parser('update'); p.add_argument('plan'); p.add_argument('--file', type=Path, required=True)
    p = sub.add_parser('additional'); p.add_argument('plan'); p.add_argument('--file', type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        from .lint import ReadOnlyLedger
        from ..ledger import Ledger
        from .where import state_root_for
        if args.command == 'show':
            result = read(ReadOnlyLedger(args.project, args.state_root), args.plan)
        else:
            body = json.loads(args.file.read_text(encoding='utf-8-sig'))
            ledger = Ledger(args.project, state_root_for(args.project, args.state_root))
            if args.command == 'update':
                result = reforecast(ledger, args.plan, body['key'], body['remaining_seconds'], body['reason'], body['evidence'])
            else:
                extra = set(body) - {'key', 'category', 'reason', 'acceptance', 'execution_seconds', 'evidence', 'nodes', 'still_running'}
                if extra: raise LedgerError('additional: unknown fields ' + ', '.join(sorted(extra)))
                result = additional(ledger, args.plan, body['key'], body['category'], body['reason'], body['acceptance'], body['execution_seconds'], body['evidence'],
                                    nodes=body.get('nodes'), still_running=body.get('still_running'))
        print(json.dumps(result, ensure_ascii=False, indent=2)); return 0
    except (LedgerError, OSError, ValueError, KeyError, TypeError) as error:
        print(json.dumps({'error': str(error), 'type': type(error).__name__}, ensure_ascii=False)); return 2
