"""Typed, deterministic routing from explicit workload/capability/quota evidence."""
import datetime as dt
import math

from .ledger import LedgerError, exact_fields, key_field, text_field


def number(value, name, maximum=100):
    if type(value) not in (int, float) or not math.isfinite(value) or not 0 <= value <= maximum:
        raise LedgerError(name + ': expected finite non-negative number within limit.')
    return value


def instant(value):
    try:
        result = dt.datetime.fromisoformat(value)
        if result.tzinfo is None:
            raise ValueError()
        return result
    except (ValueError, TypeError):
        raise LedgerError('Quota timestamps require ISO-8601 with timezone.') from None


def choose(workload, candidates, now=None, preferred_provider=None):
    """Recommendation only. Core admission still owns atomic call/capacity reservations."""
    now = now or dt.datetime.now(dt.timezone.utc)
    if preferred_provider is not None and preferred_provider not in ('claude','codex','kiro'):
        raise LedgerError('Unknown preferred provider.')
    exact_fields(workload, ('complexity', 'risk', 'allowed_providers'), 'Workload')
    if type(workload['complexity']) is not int or workload['complexity'] not in (1, 2, 3):
        raise LedgerError('complexity must be integer 1-3.')
    if workload['risk'] not in ('low', 'medium', 'high'):
        raise LedgerError('Unknown workload risk.')
    allowed = workload['allowed_providers']
    if not isinstance(allowed, list) or not allowed or not all(isinstance(x, str) for x in allowed) or not set(allowed) <= {'codex', 'claude', 'kiro'}:
        raise LedgerError('Explicit allowed_providers required.')
    required = max(workload['complexity'], {'low': 1, 'medium': 2, 'high': 3}[workload['risk']])
    if not isinstance(candidates, list) or not 1 <= len(candidates) <= 30:
        raise LedgerError('Expected 1-30 candidate configurations.')
    eligible, rejected, ids = [], [], set()
    for candidate in candidates:
        exact_fields(candidate, ('id', 'provider', 'model', 'tier', 'cost_rank',
                                 'capability_verified', 'auth_mode', 'quota'), 'Candidate')
        name = key_field(candidate['id'])
        if name in ids:
            raise LedgerError('Duplicate candidate ID.')
        ids.add(name)
        text_field(candidate['model'], 'model', 100)
        if type(candidate['tier']) is not int or candidate['tier'] not in (1, 2, 3):
            raise LedgerError('Candidate tier must be 1-3.')
        if type(candidate['capability_verified']) is not bool:
            raise LedgerError('capability_verified must be a JSON boolean.')
        number(candidate['cost_rank'], 'cost_rank', 1_000_000)
        reasons = []
        if candidate['provider'] not in allowed:
            reasons.append('provider_not_authorized')
        if candidate['auth_mode'] != 'subscription':
            reasons.append('paid_api_not_authorized')
        if not candidate['capability_verified']:
            reasons.append('capability_unverified')
        if candidate['tier'] < required:
            reasons.append('below_required_tier')
        quota = candidate['quota']
        if quota is None:
            reasons.append('quota_unknown')
        else:
            exact_fields(quota, ('observed_at', 'expires_at', 'source', 'windows'), 'Quota evidence')
            text_field(quota['source'], 'quota source', 500)
            if instant(quota['observed_at']) > now or instant(quota['expires_at']) <= now:
                reasons.append('quota_stale_or_future')
            windows = quota['windows']
            if not isinstance(windows, list) or not 1 <= len(windows) <= 8:
                raise LedgerError('Quota evidence needs every applicable window, 1-8 entries.')
            names = set()
            for window in windows:
                exact_fields(window, ('name', 'remaining', 'reserved', 'keep_for_chat', 'estimated_call', 'resets_at'), 'Quota window')
                key_field(window['name'])
                if window['name'] in names:
                    raise LedgerError('Duplicate quota window.')
                names.add(window['name'])
                for field in ('remaining', 'reserved', 'keep_for_chat', 'estimated_call'):
                    number(window[field], field)
                if instant(window['resets_at']) <= now:
                    reasons.append('quota_reset_requires_refresh:' + window['name'])
                if window['estimated_call'] <= 0:
                    raise LedgerError('estimated_call must be positive; unknown is not zero cost.')
                if window['remaining'] - window['reserved'] - window['keep_for_chat'] < window['estimated_call']:
                    reasons.append('quota_insufficient:' + window['name'])
        if reasons:
            rejected.append({'id': name, 'reasons': reasons})
        else:
            eligible.append(candidate)
    if not eligible:
        return {'status': 'blocked', 'selected': None, 'required_tier': required, 'rejected': rejected,
                'reason': 'No authorized, capable candidate with fresh sufficient quota evidence.'}
    selected = min(eligible, key=lambda c: (bool(preferred_provider and c['provider'] != preferred_provider),c['cost_rank'], c['tier'], c['id']))
    return {'status': 'recommended', 'selected': {k: selected[k] for k in ('id', 'provider', 'model', 'tier')},
            'required_tier': required, 'rejected': rejected,
            'eligible': [c['id'] for c in eligible], 'preferred_provider': preferred_provider,
            'reason': 'Operator provider preference, then supplied cost rank, after all required constraints.',
            'reservation': 'not_reserved', 'quota_limit': 'Estimate only; provider internal usage is not a hard cap.'}


def validate_decision(value, allowed_actions, evidence_ids):
    """Optional AI/JEV suggestions cannot invent actions/evidence or grant authority."""
    exact_fields(value, ('action', 'confidence', 'reason', 'evidence'), 'Decision proposal')
    if value['action'] not in allowed_actions:
        raise LedgerError('Decision action is outside the controller-provided choices.')
    confidence = number(value['confidence'], 'confidence', 1)
    text_field(value['reason'], 'decision reason', 1000)
    if not isinstance(value['evidence'], list) or not value['evidence'] or not all(isinstance(x, str) for x in value['evidence']) or not set(value['evidence']) <= set(evidence_ids):
        raise LedgerError('Decision must reference known evidence.')
    return {'action': value['action'], 'confidence': confidence, 'reason': value['reason'],
            'evidence': value['evidence'], 'authority': 'proposal_only', 'requires_review': confidence < .8}
