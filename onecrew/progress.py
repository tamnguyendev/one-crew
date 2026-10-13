"""Deterministic recovery classification and bounded exploration, never model polling."""
from .ledger import content_hash

POLICY = {'version': 1, 'same_result_limit': 3, 'observation_limit': 16,
          'write_limit': 8, 'failed_test_limit': 3, 'review_rejection_limit': 3}


def classify(error):
    from .sandbox_gate import GateUnavailable
    from .owned_git import EffectUnknown
    from .review_evidence import ReviewRejected
    if isinstance(error, ReviewRejected): return 'review'
    text = str(error).lower()
    if isinstance(error, EffectUnknown): return 'effect_unknown'
    if isinstance(error, GateUnavailable): return 'environment'
    if any(x in text for x in ('not logged in', 'authentication', 'oauth', 'unauthorized', 'login required')): return 'auth'
    if any(x in text for x in ('rate limit', 'quota', 'usage limit', '429')): return 'quota'
    if any(x in text for x in ('not authorized', 'is refused', 'are refused', 'not available in the workspace', 'not available in work contracts')): return 'permission'
    if any(x in text for x in ('sdk unavailable', 'tool snapshot', 'docker daemon', 'executable not found', 'storage failure')): return 'environment'
    if any(x in text for x in ('connection reset', 'connection refused', 'timed out', 'timeout', '503', '502')): return 'transient'
    return 'unknown'


def classify_text(text):
    return classify(Exception(text))


def observe(state, action, args, result):
    """Counters survive resume/model changes. Cosmetic plans/arguments aren't progress."""
    p = state.setdefault('progress', {'policy': dict(POLICY), 'observations': 0,
        'writes': 0, 'failed_tests': 0, 'review_rejections': 0, 'results': {}})
    limits = p['policy']
    # Results, rather than query text, catch differently worded searches yielding the same data.
    evidence = result
    intent = None
    if action == 'run' and 'error' not in result:
        # Timing and log names differ on every run; an identical command with identical output is no progress. Durations
        # printed by the tool are masked too (N2-r2: node's per-test milliseconds hid five identical failures).
        import re
        mask = lambda text: re.sub(r'\d+(?:\.\d+)?\s?(?:ms|s|sec|seconds)\b|\d{4}-\d\d-\d\dT[\d:.]+Z?', '<t>', text or '')
        evidence = {k: result.get(k) for k in ('argv', 'cwd', 'exit_code', 'stopped')}
        evidence.update(stdout=mask(result.get('stdout')), stderr=mask(result.get('stderr')))
    if 'error' in result and classify_text(result.get('error', '')) == 'permission':
        p['permission_refusals'] = p.get('permission_refusals', 0) + 1
        if p['permission_refusals'] >= 2 and state['phase'] == 'running':
            state.update(phase='blocked', message='Repeated actions outside the granted authority: ' + str(result['error'])[:300],
                         recovery={'kind': 'permission', 'automatic_retry': False})
            return
    if action == 'search' and 'error' not in result:
        # The new receipt includes query/scope/counters. Positive duplicate evidence
        # still counts across cosmetic queries; empty results are scoped observations.
        evidence = {k: result.get(k) for k in ('matches','directories','next_cursor')}
        if not result.get('matches'):
            intent = {'directory':args.get('directory',''), 'query':args.get('query','').casefold(),
                      'cursor':args.get('cursor',0)}
    key = content_hash({'action': action, 'snapshot': state.get('snapshot'), 'result': evidence,
                        'search_intent':intent})
    p['results'][key] = p['results'].get(key, 0) + 1
    reason = None
    if p['results'][key] >= limits['same_result_limit']:
        reason = 'Repeated equivalent tool result; stopped without progress.'
    if action in ('list', 'search', 'read', 'receipt', 'git_status', 'git_diff', 'git_log', 'git_show'):
        if action == 'read' and 'error' not in result and p['results'][key] == 1:
            p['observations'] = 0  # New source/page is evidence, not blind exploration.
        else: p['observations'] += 1
        if p['observations'] >= limits['observation_limit']:
            reason = 'Exploration limit reached: act on existing evidence or clarify scope before continuing.'
    if action in ('write', 'edit', 'run', 'deliver', 'branch_before', 'android_build', 'create_branch', 'export_branch', 'apply',
                  'restore', 'workspace_commit') and 'error' not in result:
        p['observations'] = 0
    if action in ('write', 'edit') and 'error' not in result:
        p['writes'] += 1
        if p['writes'] >= limits['write_limit']: reason = 'Candidate write limit reached.'
    if action == 'test' and result.get('passed') is False:
        p['failed_tests'] += 1
        if p['failed_tests'] >= limits['failed_test_limit']: reason = 'Test repair limit reached.'
    if action in ('finish', 'branch_before') and str(result.get('error', '')).startswith('Final evidence review:'):
        p['review_rejections'] += 1
        # Count the repaired evidence protocol separately; keep legacy totals for audit.
        counter='review_rejections_v2' if result.get('review_protocol')==2 else 'review_rejections'
        if counter!='review_rejections': p[counter]=p.get(counter,0)+1
        if p[counter] >= limits['review_rejection_limit']: reason = 'Evidence review rejection limit reached.'
    if reason and state['phase'] == 'running':
        state.update(phase='blocked', message=reason, recovery={'kind': 'no_progress', 'automatic_retry': False})
