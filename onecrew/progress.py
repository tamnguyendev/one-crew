"""Deterministic recovery classification and bounded exploration, never model polling."""
from .ledger import content_hash

from .progress_core import POLICY, recency, _brief, observe_counters, prepare_evidence


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
    work = state.get('work') or {}
    if work.get('workspace'):
        # Work mode: refresh the workspace state key after anything that can change files (and when missing, e.g. after a
        # runtime upgrade). It lives in the checkpoint, so it survives restart and resume (R1, Codex review 07d7ad6).
        from .work_tools import MUTATING, progress_state
        current = work.get('progress_state') or {}
        if current.pop('fresh', False): pass  # computed by this very action (a command), after it ran
        elif (action in MUTATING and 'error' not in result) or not current:
            try: work['progress_state'] = progress_state(state)
            except (ValueError, OSError): work.pop('progress_state', None)
    p = state.setdefault('progress', {'policy': dict(POLICY), 'observations': 0,
        'writes': 0, 'failed_tests': 0, 'review_rejections': 0, 'results': {}})
    limits = p['policy']
    evidence, intent, page, search_advanced, search_empty = prepare_evidence(action, args, result)
    if 'error' in result and classify_text(result.get('error', '')) == 'permission':
        p['permission_refusals'] = p.get('permission_refusals', 0) + 1
        if p['permission_refusals'] >= 2 and state['phase'] == 'running':
            state.update(phase='blocked', message='Repeated actions outside the granted authority: ' + str(result['error'])[:300],
                         recovery={'kind': 'permission', 'automatic_retry': False})
            return
    # Work mode: the workspace state key (work_tools.progress_state), refreshed after every action that can change files;
    # the same result after a real change is new evidence, the same result with nothing changed is a repeat.
    workspace = (state.get('work') or {}).get('progress_state') or {}
    observed = workspace.get('key')
    key = content_hash({'action': action, 'snapshot': observed or state.get('snapshot'), 'result': evidence,
                        'search_intent':intent})
    uncertain = unproven = False
    if observed:
        # P4b-R4 (Codex review of P4b): an incomplete key (a Git-ignored dependency tree, an unhashed or unread file) does not
        # show every change. The rule of the failed-command check and the failed-read replay (work_tools.key_unproven): the same
        # result after an action that could change files is allowed INPUT_RERUNS times, then counted; with nothing run in
        # between it is a repeat as before. `observed_at`: the receipt of the latest observation of each result under an
        # incomplete key; a result last seen before this runtime has none, so every earlier receipt counts (counters are kept).
        from .work_tools import INPUT_RERUNS, key_unproven
        at = len(state.get('receipts') or [])  # the receipt this observation is stored as
        marks = p.setdefault('observed_at', {}); allowed = p.setdefault('unproven', {})
        uncertain = key in p['results'] and key_unproven(state, workspace, marks.get(key, -1))
        if uncertain and allowed.get(key, 0) < INPUT_RERUNS:
            unproven = True; allowed[key] = allowed.get(key, 0) + 1
        if workspace.get('truncated'): marks[key] = at
    reason = observe_counters(state, action, args, result, key, unproven=unproven,
        uncertain=uncertain, input_reruns=INPUT_RERUNS if observed else 0,
        page=page, search_advanced=search_advanced, search_empty=search_empty)
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
