"""Deterministic repeat/exploration counters extracted from v1 progress.observe.

Mutates only the supplied in-memory state; no I/O, imports of v1 workers, or
execution/authority changes. Both generations call this same implementation.
"""
from .ledger import content_hash

POLICY = {'version': 1, 'same_result_limit': 3, 'observation_limit': 16,
          'write_limit': 8, 'failed_test_limit': 3, 'review_rejection_limit': 3,
          # A1/A2: re-selecting an already-DELIVERED page this many times without reaching new content is a stopped loop.
          'reconsider_limit': 2,
          # B2: repeating the SAME unresolved technical ask this many times without verifying its premise is a stopped loop.
          'self_verify_limit': 2,
          # A3: sustained no-result searches before a (non-blocking) strategy-switch hint is surfaced.
          'empty_search_hint_limit': 6}


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


def observe_counters(state, action, args, result, key, *, unproven=False,
                     uncertain=False, input_reruns=0, page=None,
                     search_advanced=False, search_empty=False):
    p = state.setdefault('progress', {'policy': dict(POLICY), 'observations': 0,
        'writes': 0, 'failed_tests': 0, 'review_rejections': 0, 'results': {}})
    limits = p['policy']
    INPUT_RERUNS = input_reruns
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
        # git_show MODE hint (Git-Show recovery, Codex GXP6): git_show with NO path returns the changed-file LIST; when that list is
        # exhausted (next_cursor None) re-calling it is the same result (still caught by the same-result guard, which still blocks finitely).
        # Surface a STRUCTURED signal naming the mode + valid next action (pick a path yourself); the core never picks the file or rewrites the command.
        # No keyword/path/SHA is named; the hint is fixed text (no counter in it to dodge the guard). Cleared on any non-git_show action.
        if action == 'git_show' and 'error' not in result and result.get('mode') == 'changed_file_list' and result.get('next_cursor') is None and count > 1:
            p['git_show_mode'] = {'kind': 'file_list_exhausted', 'commit': result.get('commit'), 'total_files': result.get('total_paths'),
                'hint': ('You reached the end of the changed-file LIST for this commit (git_show with no path). Re-calling the list returns the same result. '
                        'To read a file diff, call git_show with the same commit and path=one of the filenames already listed (cursor=0) -- pick the file yourself. '
                        'The LIST total and a single file diff are different things; do not re-request the exhausted list.')}
        # V2 BUG2: the warning is resolved by RESULT + WORK SCOPE, not just by leaving git_show. A SUCCESSFUL file_diff read
        # (mode=file_diff, no error) satisfies the 'pick a path' instruction, so clear the matching commit's warning. A tool
        # ERROR is not a successful recovery (handled by the 'error' not in result guard). Do not carry a stale warning to an
        # UNRELATED commit: a changed_file_list for a DIFFERENT commit drops the prior commit's warning (the new set-branch
        # above re-raises only on its own exhaustion). The guard/history are never reset to go green.
        elif action == 'git_show' and 'error' not in result and result.get('mode') == 'file_diff':
            g = p.get('git_show_mode')
            if g and g.get('commit') == result.get('commit'): p.pop('git_show_mode', None)
        elif action == 'git_show' and 'error' not in result and result.get('mode') == 'changed_file_list':
            g = p.get('git_show_mode')
            if g and g.get('commit') not in (None, result.get('commit')): p.pop('git_show_mode', None)
        elif action != 'git_show': p.pop('git_show_mode', None)
        if p['observations'] >= limits['observation_limit']:
            reason = 'Exploration limit reached: act on existing evidence or clarify scope before continuing.'
    return reason


def prepare_evidence(action, args, result):
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
    return evidence, intent, page, search_advanced, search_empty
