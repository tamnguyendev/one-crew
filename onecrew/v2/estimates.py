"""W32a: sourced forecast ranges, separate from execution grants and budgets."""
import datetime as dt
import json
import math
import argparse
from pathlib import Path

from ..ledger import LedgerError, key_field, text_field, utcnow
from . import plan

KINDS = ('estimate.baseline', 'estimate.eta', 'work.additional')


def interval(value, optional=False):
    if value is None and optional: return None
    if (not isinstance(value, (list, tuple)) or len(value) != 2 or
            any(type(v) not in (int, float) or not math.isfinite(v) or v < 0 for v in value) or value[0] > value[1]):
        raise LedgerError('Estimate must be a finite non-negative [low, high] range in seconds.')
    return list(value)


def evidence(value):
    if not isinstance(value, list) or not 1 <= len(value) <= 20:
        raise LedgerError('An estimate change requires 1..20 evidence references.')
    for ref in value:
        text_field(ref, 'evidence', 500)
        if not ref.strip(): raise LedgerError('An evidence reference cannot be empty.')
    return list(value)


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
    if not state['approved'] or state['status'] == 'accepted': raise LedgerError('Forecast changes require an open approved plan.')
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
        return _append(ledger, conn, state, 'estimate.eta', dict(
            key=key, estimate_type='eta', remaining_seconds=span, reason=reason, evidence=refs,
            revision=state['approved']['revision'], plan=state['name'], calibrated=False))


def additional(ledger, selector, key, category, reason, acceptance, seconds, refs):
    key_field(key); text_field(reason, 'reason', 1000)
    if not reason.strip(): raise LedgerError('Additional work requires a reason.')
    if category not in ('mandatory', 'optional', 'outside_authority'): raise LedgerError('Unknown additional work category.')
    span, refs = interval(seconds), evidence(refs)
    with ledger.transaction(write=True) as conn:
        state = _state(ledger, conn, selector)
        contract = plan.load(ledger, state, state['approved']['revision'])[0]
        allowed = {'O' + str(i + 1) for i in range(len(contract['output']))}
        if not isinstance(acceptance, list) or not acceptance or not set(acceptance) <= allowed:
            raise LedgerError('Additional work must name approved acceptance IDs.')
        return _append(ledger, conn, state, 'work.additional', dict(
            key=key, estimate_type='additional', category=category, reason=reason, acceptance=acceptance,
            execution_seconds=span, evidence=refs, plan=state['name'], revision=state['approved']['revision'],
            disposition={'mandatory': 'forecast', 'optional': 'backlog', 'outside_authority': 'U2'}[category],
            grants_execution=False))


def read(ledger, selector):
    with ledger.transaction() as conn:
        state = plan.anchor_events(ledger, conn, selector)
        rows = _events(conn, state['task_id'])
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
    from .executors import summary, UNKNOWN, NOT_MEASURED
    attempts = summary(ledger, selector)['attempts']
    def measured(field):
        values = [a.get(field, UNKNOWN) for a in attempts]
        return sum(values) if values and all(type(v) in (int, float) and math.isfinite(v) and v >= 0 for v in values) else UNKNOWN
    return {'plan': state['name'], 'baseline': baseline, 'history': forecasts, 'additional': additions,
            'remaining_seconds': remaining, 'execution_seconds': measured('elapsed_seconds'),
            'waiting_seconds': measured('wait_seconds'), 'deadline': baseline.get('deadline') if baseline else None,
            'calibrated': False, 'measurement_sources': attempts,
            'outside_authority': [p['key'] for p in additions if p['category'] == 'outside_authority']}


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
                result = additional(ledger, args.plan, body['key'], body['category'], body['reason'], body['acceptance'], body['execution_seconds'], body['evidence'])
        print(json.dumps(result, ensure_ascii=False, indent=2)); return 0
    except (LedgerError, OSError, ValueError, KeyError, TypeError) as error:
        print(json.dumps({'error': str(error), 'type': type(error).__name__}, ensure_ascii=False)); return 2
