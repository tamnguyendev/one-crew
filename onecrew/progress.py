"""Deterministic recovery classification and bounded exploration, never model polling."""
from .ledger import content_hash

POLICY = {'version': 1, 'same_result_limit': 3, 'observation_limit': 16,
          'write_limit': 8, 'failed_test_limit': 3, 'review_rejection_limit': 3}


def classify(error):
    from .sandbox_gate import GateUnavailable
    from .owned_git import EffectUnknown
    text = str(error).lower()
    if isinstance(error, EffectUnknown): return 'effect_unknown'
    if isinstance(error, GateUnavailable): return 'environment'
    if any(x in text for x in ('not logged in', 'authentication', 'oauth', 'unauthorized', 'login required')): return 'auth'
    if any(x in text for x in ('rate limit', 'quota', 'usage limit', '429')): return 'quota'
    if any(x in text for x in ('sdk unavailable', 'tool snapshot', 'docker daemon', 'executable not found', 'storage failure')): return 'environment'
    if any(x in text for x in ('connection reset', 'connection refused', 'timed out', 'timeout', '503', '502')): return 'transient'
    return 'unknown'


def observe(state, action, args, result):
    """Counters survive resume/model changes. Cosmetic plans/arguments aren't progress."""
    p = state.setdefault('progress', {'policy': dict(POLICY), 'observations': 0,
        'writes': 0, 'failed_tests': 0, 'review_rejections': 0, 'results': {}})
    limits = p['policy']
    # Results, rather than query text, catch differently worded searches yielding the same data.
    key = content_hash({'action': action, 'snapshot': state.get('snapshot'), 'result': result})
    p['results'][key] = p['results'].get(key, 0) + 1
    reason = None
    if p['results'][key] >= limits['same_result_limit']:
        reason = 'Repeated equivalent tool result; stopped without progress.'
    if action in ('list', 'search', 'read', 'receipt', 'git_status', 'git_diff', 'git_log', 'git_show'):
        p['observations'] += 1
        if p['observations'] >= limits['observation_limit']:
            reason = 'Exploration limit reached: act on existing evidence or clarify scope before continuing.'
    if action in ('write', 'deliver', 'branch_before', 'android_build') and 'error' not in result:
        p['observations'] = 0
    if action == 'write' and 'error' not in result:
        p['writes'] += 1
        if p['writes'] >= limits['write_limit']: reason = 'Candidate write limit reached.'
    if action == 'test' and result.get('passed') is False:
        p['failed_tests'] += 1
        if p['failed_tests'] >= limits['failed_test_limit']: reason = 'Test repair limit reached.'
    if action in ('finish', 'branch_before') and str(result.get('error', '')).startswith('Final evidence review:'):
        p['review_rejections'] += 1
        if p['review_rejections'] >= limits['review_rejection_limit']: reason = 'Evidence review rejection limit reached.'
    if reason and state['phase'] == 'running':
        state.update(phase='blocked', message=reason, recovery={'kind': 'no_progress', 'automatic_retry': False})

