"""Deterministic recovery classification and bounded exploration, never model polling."""
from .ledger import content_hash

POLICY = {'version': 1, 'same_result_limit': 3, 'observation_limit': 16,
          'write_limit': 8, 'failed_test_limit': 3, 'review_rejection_limit': 3,
          # A1/A2: re-selecting an already-DELIVERED page this many times without reaching new content is a stopped loop.
          'reconsider_limit': 2,
          # B2: repeating the SAME unresolved technical ask this many times without verifying its premise is a stopped loop.
          'self_verify_limit': 2,
          # A3: sustained no-result searches before a (non-blocking) strategy-switch hint is surfaced.
          'empty_search_hint_limit': 6}


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


def recency(entry):
    """Order of a repeat entry by when it happened: its durable event number, else (checkpoints written before P4b) its step."""
    step = entry.get('step')
    return (entry.get('seq') or 0, step if isinstance(step, int) else -1)


def _brief(args):
    """Arguments of a repeated action, short enough for the worker's context (file contents are never copied)."""
    import json
    if not isinstance(args, dict): return None
    return {k: (v if len(json.dumps(v, ensure_ascii=False, default=str)) <= 200 else '[' + str(len(str(v))) + ' chars]')
            for k, v in args.items() if k not in ('text', 'new', 'old')}


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
    if (action == 'run' and 'error' not in result and (result.get('exit_code') not in (0, None) or result.get('stopped'))
            and (evidence.get('stdout') or '').strip() + (evidence.get('stderr') or '').strip()):
        # P4-C: a failing command whose failure output is identical, in the same workspace, is a repeat whatever cosmetic change
        # was made to its argv (an extra no-op flag used to make it "new"). Silent failures keep their argv: different probes
        # that all fail without output are not the same result.
        evidence = {k: v for k, v in evidence.items() if k not in ('argv', 'cwd')}
    page = None
    if action == 'receipt' and 'error' not in result:
        # P4-B: each page of a receipt is its own evidence; asking for the same page again is a repeat.
        page = {'index': args.get('index'), 'field': args.get('field'), 'offset': args.get('offset') or 0,
                'item_offset': args.get('item_offset') or 0}
        evidence = {'page': page, 'record': result}
    search_advanced = False; search_empty = False
    if action == 'search' and 'error' not in result:
        # The new receipt includes query/scope/counters. Positive duplicate evidence
        # still counts across cosmetic queries; empty results are scoped observations.
        evidence = {k: result.get(k) for k in ('matches','directories','next_cursor')}
        # Did this op cover genuinely NEW files? scanned_through advancing past the cursor over real files is coverage,
        # not blind exploration; re-scanning the same region (intent key below) is still caught as a repeat.
        search_advanced = bool(result.get('files_scanned')) and (result.get('scanned_through') or 0) > (args.get('cursor',0) or 0)
        if not result.get('matches'):
            search_empty = True
            intent = {'directory':args.get('directory',''), 'query':args.get('query','').casefold(),
                      'cursor':args.get('cursor',0)}
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
    # P5 (review of the fix): under a tight cap every prompt shows long contract texts cut, so fetching the same part again is
    # how the worker reads its own contract, never a loop of the same result; it counts as an observation (bounded) only.
    if not unproven and action != 'contract': p['results'][key] = p['results'].get(key, 0) + 1
    reason = None
    count = p['results'].get(key, 1)
    if count >= 2:
        # P4-D: which result repeats, and how close it is to stopping the task, is part of the worker's context (the guard
        # warns at limit-1 instead of only stopping at the limit); bounded, durable in the checkpoint.
        repeats = p.setdefault('repeats', {})
        # P4b-R1 (Codex review of P4): the checkpoint is canonical JSON with sorted keys, so the order of this dict is lost on
        # every persist; recency is a durable event number instead (older checkpoints: their step).
        p['repeat_seq'] = p.get('repeat_seq', 0) + 1
        repeats[key] = {'action': action, 'arguments': _brief(args), 'count': count, 'limit': limits['same_result_limit'],
                        'step': state.get('step'), 'seq': p['repeat_seq'],
                        'error': str(result.get('error'))[:200] if 'error' in result else None}
        for old in sorted(repeats, key=lambda k: recency(repeats[k]))[:-8]: repeats.pop(old)
    if count >= limits['same_result_limit']:
        import json
        reason = ('Repeated equivalent tool result; stopped without progress: ' + action + ' '
                  + json.dumps(_brief(args), ensure_ascii=False)[:200] + f' gave the same result {count} times'
                  + (' with nothing changed in between.' if not uncertain else
                     # P4b-R4: never "nothing changed" when an action in between may have changed files the key cannot see
                     '; the workspace key cannot show whether the actions in between changed it (Git-ignored dependency '
                     f'trees, unhashed or unread files), and the {INPUT_RERUNS} repeats allowed after such actions are used up.'))
        p['stopped_by'] = dict((p.get('repeats') or {}).get(key) or {'action': action, 'arguments': _brief(args), 'count': count,
                                                                    'step': state.get('step')}, key=key)
    if action in ('list', 'search', 'read', 'receipt', 'contract', 'git_status', 'git_diff', 'git_log', 'git_show'):
        # New source, the next page of a cut result, OR a search op that covered genuinely-new files is evidence, not blind
        # exploration (an advancing-cursor scan over unexamined files is coverage). Re-scanning a region already seen is NOT
        # credited: it falls through to the repeat/same-result guard below via its intent key.
        new_coverage = count == 1 and not unproven and (action == 'read'
            or (page and (page['offset'] > 0 or page['item_offset'] > 0))
            or (action == 'search' and search_advanced))
        # Mechanism A (progress-reconciliation, delivery-based). A1/A2 fix: the signal that a receipt is a RE-READ is that the
        # worker RE-SELECTED a page whose content was ALREADY DELIVERED into a prior prompt (state['delivered_pages'], written
        # by owned.run ONLY after the model answered the prompt that carried it - the adapter's send-evidence - never from a
        # request, a trial/measurement build, or an undelivered/does-not-fit page (A1, Codex v2)). We do NOT look
        # at the plan at all: a reworded plan is not progress and cannot re-grant recovery (the A2 reset bug). Re-selecting an
        # already-delivered page raises a bounded 'reconsider' recovery so the worker RE-DECIDES (we never perform the
        # continuation for it); a valid re-read is allowed up to the bound, then the loop is stopped as an honest blocker. The
        # re-selection counter is keyed to the PAGE (stable content), so paging to NEW content or acting re-arms it, and a
        # reworded plan or a changing response counter cannot mask or extend the loop.
        reselect_served = False
        if action == 'receipt' and 'error' not in result and page is not None:
            pagekey = content_hash({'index': page['index'], 'field': page['field'],
                                    'offset': page['offset'], 'item_offset': page['item_offset']})
            delivered = state.get('delivered_pages') or {}
            reselect_served = pagekey in delivered  # this exact page was already rendered into a previous prompt
        if 'error' not in result and new_coverage and not reselect_served:
            p['observations'] = 0
        else: p['observations'] += 1
        if reselect_served:
            # Count re-selections PER PAGE on stable content, so a different already-delivered page is its own (fresh) count
            # and acting on NEW content clears it. Durable in the checkpoint.
            per = p.setdefault('reconsider_by_page', {})
            per[pagekey] = per.get(pagekey, 0) + 1
            if len(per) > 200:
                for k in list(per)[:-200]: per.pop(k, None)
            p['reconsider_count'] = per[pagekey]
            p['reconsider'] = {'kind': 'already_read_region',
                'page': {k: page[k] for k in ('index', 'field', 'offset', 'item_offset')},
                'count': per[pagekey], 'limit': limits.get('reconsider_limit', 2),
                'hint': ('You already received this exact receipt page in an earlier prompt; requesting it again is not '
                         'progress. Use its continuation (latest_result.page.next) to read NEW content, or act on the '
                         'conclusion this evidence already gives - do not request this same page again.')}
            if per[pagekey] >= limits.get('reconsider_limit', 2):
                reason = 'Re-selected already-delivered evidence without advancing to new content (reconsider limit reached); stopped without progress.'
        elif action == 'receipt' and 'error' not in result:
            # reached a NOT-already-delivered page (new content): clear the reconsider state
            p.pop('reconsider', None); p['reconsider_count'] = 0; p['reconsider_by_page'] = {}
        # Separate signal so cursor-advance alone is not treated as infinite progress: count CONSECUTIVE no-result searches
        # (across new regions too). At the threshold, surface a STRUCTURED strategy-switch hint so the worker changes
        # approach (different query, narrow directory, view structure, git history) instead of paging forever. This never
        # names a keyword/path/commit and never blocks by itself; the real loop + exploration guards stay in force.
        if action == 'search' and 'error' not in result and search_empty:
            p['empty_searches'] = p.get('empty_searches', 0) + 1
            if p['empty_searches'] >= limits.get('empty_search_hint_limit', 6):
                p['strategy_switch'] = {'kind': 'search_not_converging', 'empty_searches': p['empty_searches'],
                    'hint': ('Searches keep returning no matches. Switch strategy before more paging: try a different '
                             'keyword or synonym, narrow to a likely directory, view the project structure (list), or '
                             'inspect git history/branches - do not repeat the same query across pages.')}
        elif action == 'search' and not search_empty:
            p.pop('empty_searches', None); p.pop('strategy_switch', None)
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
