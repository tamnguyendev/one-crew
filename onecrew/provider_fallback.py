"""Quota-only forward handoff under the job's snapshotted operator policy."""
import datetime as dt
from .provider_limits import QuotaExhausted


def advance(runtime, task_id, seq, state, error):
    if not isinstance(error, QuotaExhausted): return None
    control = runtime.control.status(task_id)
    profile = control['configuration']['profile']
    selected = state['worker']
    pair = {k: selected[k] for k in ('provider', 'model')}
    chain = [{k: profile[k] for k in ('provider', 'model')}] + profile.get('fallbacks', [])
    if error.provider != pair['provider'] or pair not in chain or not state.get('pending'): return None
    attempt = runtime.control.attempt(state['pending'])
    if attempt['status'] != 'settled' or any(a['status'] != 'settled' for a in control['attempts']): return None
    if control['cancel_requested'] or control['status'] == 'paused' or runtime.ledger.requests(task_id, pending=True): return None
    if state.get('quota_binding'):
        state['recovery']['fallback_blocked'] = 'Explicit account reservation requires a new verified binding.'
        return None  # Do not evade an explicitly bound account quota by dropping it.
    if runtime.control.clock() >= dt.datetime.fromisoformat(control['deadline']): return None
    if control['used_calls'] + control['reserved_calls'] >= control['budget']['limits']['max_calls']: return None
    if control['budget'].get('goal', {}).get('remaining_calls', 1) <= 0: return None
    from .providers import make_worker
    skipped = []
    for candidate in chain[chain.index(pair) + 1:]:
        try:
            worker = make_worker(runtime.control, candidate['provider'])
            capability = worker.capability()
        except (ValueError, OSError):
            skipped.append(dict(candidate, reason='CLI capability/subscription unavailable'))
            continue
        state.setdefault('handoffs', []).append({'from': pair, 'to': candidate,
            'reason': 'quota_exhausted', 'attempt': attempt['id'], 'snapshot': state['snapshot'],
            'authority': 'operator fallback policy sealed at submit', 'skipped': skipped,
            'used_calls': control['used_calls'], 'deadline': control['deadline']})
        state.update(worker=dict(candidate, capability=capability), pending=None,
                     message=f"Quota exhausted: {pair['provider']} -> {candidate['provider']}; checkpoint retained.",
                     recovery={'kind': 'quota', 'automatic_retry': False, 'fallback': candidate})
        # Persist before any new native process can launch; a crash resumes this provider.
        return runtime.persist(task_id, seq, state)
    state['recovery']['fallback_blocked'] = 'No remaining authorized available provider.'
    state['recovery']['skipped'] = skipped
    return None
