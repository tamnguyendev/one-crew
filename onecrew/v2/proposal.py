"""W47 - the step-0 proposal check: just enough, not too little, not too much. Pure and mechanical: no model, no process.

The proposal is data the author states (a fixture in tests, a file in `plan proposal check`); this module only checks it against the
owner's request. One preferred option with a before/after and the reason it is the least that is enough. EVERY change must declare what it
is (kind: delete | hide | modify), where it acts (entries: menu | url | api | storage) and which acceptance, constraint or dependency it serves.
Then:

  * too little - an acceptance with no change, or one the proposal states more weakly than the request (`acceptance_dropped`,
    `acceptance_changed`); the destructive-semantics rule, judged ONLY on the declared kind and entries, never guessed from words: an
    acceptance that says "unreachable by menu, URL and API" needs every one of those paths closed (a delete closes the entries it names; a hide
    closes only the menu, because a hidden menu entry leaves the route and the handler usable), and "removed permanently" needs a delete
    over storage - a hide flag is not a deletion;
  * too much - a change tied to no acceptance, constraint or dependency (`change_not_linked`); an optional improvement is moved to the
    backlog instead of the plan;
  * not enough said - a change without kind or entries (`missing_declaration`), a preferred option without before/after/reason.

A request that is clear and inside the authority needs no three options and no mockup (they are counted as `extras`, never demanded) and
produces no request to the owner. An unknown that blocks the choice is written with `affected` and `required_by`, and the choice waits for a
bounded survey (`survey_first`).

`check` returns {ok, result, reasons, table, backlog, ...}; `RULES` is the ordered list of rules, so a test can remove one and show
that the sample it should catch then passes (the counter-proof).

2.4-C, the step-0 card ("enough to act on"): three OPTIONAL fields - `preserve` [{id, text}] (what stays unchanged), `investigation`
{cap {minutes, calls}, paths [explicit], stop_when} (the bound of the step-0 surveys) and `estimate` ({range [lo, hi] seconds,
evidence [...]} or {status: not_enough_data, missing}). A proposal that uses none of them is checked exactly as before. One that uses any of
them opts into the card rules: what a modify/delete change keeps is stated (`preserve_missing`); the estimate is a sourced range or an
explicit "not enough data", never 0 or a bare number (`estimate_*`); the investigation names explicit paths ('.' is the whole project) and
spends no more than its cap (`investigation_*`); an open unknown the approval waits for holds it (`unknown_open`). Estimates never become
caps or budgets.
"""
from pathlib import Path

from ..ledger import LedgerError, key_field, text_field

KINDS = ('delete', 'hide', 'modify')
ENTRIES = ('menu', 'url', 'api', 'storage')
DELETES = ('delete',)                           # the kinds that count as a permanent deletion
MIN_RATIONALE = 20
MAX_CHANGES, MAX_BACKLOG, MAX_LINKS = 30, 30, 10
CLOSES = {'delete': lambda entries: set(entries),             # a deleted route/handler/entry is closed
          'hide': lambda entries: set(entries) & {'menu'},    # a hidden menu entry leaves the URL and the API usable
          'modify': lambda entries: set()}                    # a modification closes nothing by itself
REQUIRED_BY = ('option_choice', 'estimate', 'approval')
CARD_FIELDS = ('preserve', 'investigation', 'estimate')        # 2.4-C: optional; any one present opts the proposal into the card rules
MAX_MINUTES, MAX_CALLS = 120, 50                                # the survey bounds (survey.validate_spec)
WHOLE_PROJECT = ('.', './', '')


def _id_list(value, name, low=0, high=MAX_LINKS):
    if not isinstance(value, list) or not low <= len(value) <= high:
        raise LedgerError(f'{name}: expected a list of {low}-{high} ids.')
    return [key_field(v) for v in value]


def _semantic(value, name):
    if value is None: return None
    if not isinstance(value, dict) or set(value) - {'unreachable_via', 'removal'}:
        raise LedgerError(f'{name}.semantic: unreachable_via (a list of menu|url|api) and/or removal ("permanent").')
    out = {}
    if 'unreachable_via' in value:
        paths = value['unreachable_via']
        if not isinstance(paths, list) or not paths or not set(paths) <= {'menu', 'url', 'api'}:
            raise LedgerError(f'{name}.semantic.unreachable_via: a non-empty list of menu, url, api.')
        out['unreachable_via'] = sorted(set(paths))
    if 'removal' in value:
        if value['removal'] != 'permanent': raise LedgerError(f'{name}.semantic.removal: "permanent".')
        out['removal'] = 'permanent'
    return out or None


def _statements(value, name, low, semantic=False):
    if not isinstance(value, list) or not low <= len(value) <= 12:
        raise LedgerError(f'{name}: expected a list of {low}-12 statements {{id, text}}.')
    out = []
    for item in value:
        keys = {'id', 'text'} | ({'semantic'} if semantic else set())
        if not isinstance(item, dict) or set(item) - keys or not {'id', 'text'} <= set(item):
            raise LedgerError(f'{name}: each is {{"id", "text"' + (', "semantic"' if semantic else '') + '}.')
        entry = {'id': key_field(item['id']), 'text': text_field(item['text'], f'{name} text', 500)}
        if semantic: entry['semantic'] = _semantic(item.get('semantic'), f'{name} {entry["id"]}')
        out.append(entry)
    return out


def validate_requirement(value):
    """The request in a form the check can hold the proposal to: acceptance (with an optional machine-readable semantic), constraints, dependencies."""
    if not isinstance(value, dict) or set(value) - {'acceptance', 'constraints', 'dependencies'} or 'acceptance' not in value:
        raise LedgerError('requirement: expected {"acceptance": [...], "constraints": [...], "dependencies": [...]}.')
    out = {'acceptance': _statements(value['acceptance'], 'requirement.acceptance', 1, semantic=True),
           'constraints': _statements(value.get('constraints', []), 'requirement.constraints', 0),
           'dependencies': _statements(value.get('dependencies', []), 'requirement.dependencies', 0)}
    ids = [s['id'] for group in out.values() for s in group]
    if len(set(ids)) != len(ids): raise LedgerError('requirement: an id is used twice (acceptance, constraints and dependencies share one namespace).')
    return out


def _change(value):
    allowed = {'id', 'title', 'kind', 'entries', 'links', 'target', 'optional'}
    if not isinstance(value, dict) or set(value) - allowed or not {'id', 'title', 'target'} <= set(value):
        raise LedgerError('change: each is {id, title, target, kind, entries, links} (optional: true for an optional improvement).')
    out = {'id': key_field(value['id']), 'title': text_field(value['title'], 'change title', 300), 'target': text_field(value['target'], 'change target', 300),
           'links': _id_list(value.get('links', []), 'change links'), 'optional': bool(value.get('optional', False))}
    kind, entries = value.get('kind'), value.get('entries')
    if kind is not None and kind not in KINDS: raise LedgerError(f'change {out["id"]}.kind: delete, hide or modify.')
    if entries is not None and (not isinstance(entries, list) or not set(entries) <= set(ENTRIES)):
        raise LedgerError(f'change {out["id"]}.entries: a list of menu, url, api, storage.')
    out['kind'], out['entries'] = kind, sorted(set(entries)) if entries else None
    return out


def _unknown(value):
    if not isinstance(value, dict) or set(value) - {'id', 'question', 'affected', 'required_by', 'status'} or not {'id', 'question'} <= set(value):
        raise LedgerError('unknown: each is {id, question, affected, required_by, status}.')
    status = value.get('status', 'open')
    if status not in ('open', 'closed'): raise LedgerError('unknown.status: open or closed.')
    out = {'id': key_field(value['id']), 'question': text_field(value['question'], 'unknown question', 500), 'status': status,
           'affected': value.get('affected'), 'required_by': value.get('required_by')}
    if out['affected'] is not None: out['affected'] = _id_list(out['affected'], f'unknown {out["id"]}.affected', 0)
    return out


def _investigation(value):
    """The shape only; explicit paths and the cap against what was spent are judged by rule_investigation."""
    if not isinstance(value, dict) or set(value) - {'cap', 'paths', 'stop_when'} or not {'cap', 'paths', 'stop_when'} <= set(value):
        raise LedgerError('proposal.investigation: {"cap": {"minutes", "calls"}, "paths": [...], "stop_when": "..."}.')
    cap, paths = value['cap'], value['paths']
    if (not isinstance(cap, dict) or set(cap) != {'minutes', 'calls'} or any(type(cap[k]) is not int for k in cap)):
        raise LedgerError('proposal.investigation.cap: {"minutes": integer, "calls": integer}.')
    if not isinstance(paths, list) or not 1 <= len(paths) <= 20 or any(not isinstance(x, str) for x in paths):
        raise LedgerError('proposal.investigation.paths: 1-20 relative paths.')
    return {'cap': dict(cap), 'paths': list(paths), 'stop_when': text_field(value['stop_when'], 'investigation.stop_when', 500)}


def _estimate(value):
    """The shape only (a dict, or a bare number kept so rule_estimate can refuse it by name)."""
    if type(value) in (int, float): return {'bare': value}
    if not isinstance(value, dict) or set(value) - {'range', 'evidence', 'status', 'missing'}:
        raise LedgerError('proposal.estimate: {"range": [lo, hi], "evidence": [...]} or {"status": "not_enough_data", "missing": "..."}.')
    out = dict(value)
    if 'evidence' in out and (not isinstance(out['evidence'], list) or len(out['evidence']) > 20): raise LedgerError('proposal.estimate.evidence: a list of at most 20 references.')
    return out


def validate_proposal(value):
    """The shape of a proposal. What is MISSING from a change (kind, entries, links) is not a shape error: it is a reason the check reports."""
    allowed = {'preferred', 'covers', 'acceptance', 'backlog', 'alternatives', 'mockups', 'in_authority', 'unknowns', *CARD_FIELDS}
    if not isinstance(value, dict) or set(value) - allowed:
        raise LedgerError('proposal: unknown fields ' + ', '.join(sorted(set(value) - allowed)) if isinstance(value, dict) else 'proposal: expected an object.')
    out = {'in_authority': bool(value.get('in_authority', False)), 'covers': None, 'preferred': None,
           'unknowns': [_unknown(u) for u in value.get('unknowns', [])],
           'backlog': [], 'acceptance': None, 'extras': {'alternatives': len(value.get('alternatives') or []), 'mockups': len(value.get('mockups') or [])}}
    if len(out['unknowns']) > 10 or len({u['id'] for u in out['unknowns']}) != len(out['unknowns']): raise LedgerError('proposal.unknowns: at most 10, distinct ids.')
    if value.get('covers') is not None: out['covers'] = _id_list(value['covers'], 'proposal.covers', 0, 12)
    if value.get('acceptance') is not None: out['acceptance'] = _statements(value['acceptance'], 'proposal.acceptance', 1, semantic=True)
    out['card'] = any(field in value for field in CARD_FIELDS)
    out['preserve'] = _statements(value['preserve'], 'proposal.preserve', 0) if value.get('preserve') is not None else None
    out['investigation'] = _investigation(value['investigation']) if value.get('investigation') is not None else None
    out['estimate'] = _estimate(value['estimate']) if 'estimate' in value else None
    backlog = value.get('backlog', [])
    if not isinstance(backlog, list) or len(backlog) > MAX_BACKLOG: raise LedgerError(f'proposal.backlog: a list of at most {MAX_BACKLOG} items.')
    out['backlog'] = [{'id': key_field(b.get('id')) if isinstance(b, dict) else key_field(None), 'title': text_field(b.get('title'), 'backlog title', 300)}
                      for b in backlog]
    preferred = value.get('preferred')
    if preferred is None: return out
    if not isinstance(preferred, dict):
        raise LedgerError('proposal.preferred: give exactly one preferred option (an object), not a list.')
    keys = {'id', 'summary', 'before', 'after', 'rationale', 'changes'}
    if set(preferred) - keys or not keys <= set(preferred):
        raise LedgerError('proposal.preferred: expected ' + ', '.join(sorted(keys)) + '.')
    changes = preferred['changes']
    if not isinstance(changes, list) or not 1 <= len(changes) <= MAX_CHANGES: raise LedgerError(f'proposal.preferred.changes: 1-{MAX_CHANGES} changes.')
    out['preferred'] = {'id': key_field(preferred['id']), 'summary': text_field(preferred['summary'], 'preferred.summary', 500),
                        'before': text_field(preferred['before'], 'preferred.before', 1000), 'after': text_field(preferred['after'], 'preferred.after', 1000),
                        'rationale': text_field(preferred['rationale'], 'preferred.rationale', 1000), 'changes': [_change(c) for c in changes]}
    if len({c['id'] for c in out['preferred']['changes']}) != len(out['preferred']['changes']): raise LedgerError('proposal.preferred.changes: duplicate id.')
    return out


# ---- the rules ------------------------------------------------------------------------------------------------------------------

def _context(ledger, requirement, proposal, spent=None):
    preferred = proposal['preferred']
    changes = [c for c in (preferred['changes'] if preferred else [])]
    planned = [c for c in changes if not c['optional']]
    known = {s['id'] for group in requirement.values() for s in group}
    return {'ledger': ledger, 'requirement': requirement, 'proposal': proposal, 'preferred': preferred, 'planned': planned,
            'optional': [c for c in changes if c['optional']], 'known': known,
            'declared': all(c['kind'] and c['entries'] for c in planned), 'spent': spent or {'seconds': 0, 'calls': 0}}


def rule_unknowns(ctx):
    out = []
    for unknown in ctx['proposal']['unknowns']:
        missing = [f for f in ('affected', 'required_by') if not unknown[f]]
        if missing:
            out.append(('unknown_unscoped', f'unknown {unknown["id"]} is written without {" and ".join(missing)}: say what it affects and by when '
                                            f'(required_by: {", ".join(REQUIRED_BY)} or milestone:<id>) at the moment it is proposed.'))
        elif not (unknown['required_by'] in REQUIRED_BY or unknown['required_by'].startswith('milestone:')):
            out.append(('unknown_unscoped', f'unknown {unknown["id"]}.required_by {unknown["required_by"]!r} is not one of {", ".join(REQUIRED_BY)} or milestone:<id>.'))
    return out


def blocking_unknowns(proposal):
    """The open unknowns the choice of an option waits for (required_by option_choice)."""
    return [u for u in proposal['unknowns'] if u['status'] == 'open' and u['required_by'] == 'option_choice' and u['affected']]


def rule_declaration(ctx):
    bare = [c['id'] for c in ctx['planned'] if not c['kind'] or not c['entries']]
    if not bare: return []
    return [('missing_declaration', f'change {", ".join(bare)}: missing declaration of change kind and entry path (thiếu khai báo loại thay đổi và đường vào). '
                                    'State kind (delete, hide, modify) and entries (menu, url, api, storage); the destructive-semantics rule is judged on that declaration, never guessed from the text.')]


def rule_linkage(ctx):
    out = []
    for change in ctx['planned']:
        valid = [link for link in change['links'] if link in ctx['known']]
        stray = [link for link in change['links'] if link not in ctx['known']]
        if stray: out.append(('unknown_link', f'change {change["id"]} ({change["title"]}) points at {", ".join(stray)}, which is not an acceptance, constraint or dependency of the request.'))
        elif not valid:
            out.append(('change_not_linked', f'change {change["id"]} ({change["title"]}) is tied to no acceptance, constraint or dependency of the request: '
                                             'tie it to one, or move it to the backlog if it is only an improvement.'))
    return out


def rule_acceptance(ctx):
    out, proposal = [], ctx['proposal']
    if proposal['preferred'] is None: return out
    linked = {link for c in ctx['planned'] for link in c['links']}
    wanted = [a['id'] for a in ctx['requirement']['acceptance']]
    unmet = [a for a in wanted if a not in linked]
    if unmet: out.append(('acceptance_dropped', f'acceptance {", ".join(unmet)} has no change in the proposal: it is dropped, so the proposal is not enough.'))
    if proposal['covers'] is not None and set(wanted) - set(proposal['covers']):
        out.append(('acceptance_dropped', f'the proposal says it covers {", ".join(proposal["covers"]) or "nothing"} but the request has {", ".join(wanted)}: '
                                          f'{", ".join(sorted(set(wanted) - set(proposal["covers"])))} is dropped.'))
    if proposal['acceptance'] is not None:
        mine = {a['id']: a for a in proposal['acceptance']}
        for a in ctx['requirement']['acceptance']:
            if a['id'] in mine and mine[a['id']] != a:
                out.append(('acceptance_changed', f'acceptance {a["id"]} is restated differently from the request (text or semantic): the proposal may not loosen it.'))
    return out


def rule_semantics(ctx):
    """Destructive semantics, on the declared kind and entries only. Skipped while any change is undeclared (rule_declaration reports that)."""
    if not ctx['declared'] or ctx['preferred'] is None: return []
    out = []
    for acceptance in ctx['requirement']['acceptance']:
        semantic = acceptance['semantic']
        if not semantic: continue
        mine = [c for c in ctx['planned'] if acceptance['id'] in c['links']]
        if 'unreachable_via' in semantic:
            closed = set().union(*[CLOSES[c['kind']](c['entries']) for c in mine]) if mine else set()
            still = [p for p in semantic['unreachable_via'] if p not in closed]
            if still:
                out.append(('destructive_semantics', f'acceptance {acceptance["id"]} needs every path closed ({", ".join(semantic["unreachable_via"])}) but '
                                                     f'{", ".join(still)} still work: a hide closes only the menu; a route or handler stays usable until it is deleted.'))
        if semantic.get('removal') == 'permanent':
            if not any(c['kind'] in DELETES and 'storage' in c['entries'] for c in mine):
                flagged = [c for c in mine if 'storage' in c['entries']]
                out.append(('not_permanent', f'acceptance {acceptance["id"]} needs a permanent deletion of the data but ' +
                            (f'change {", ".join(c["id"] for c in flagged)} only {flagged[0]["kind"]}s it: hide is not permanent deletion (the data is still there).'
                             if flagged else 'no change deletes the storage.')))
    return out


def rule_rationale(ctx):
    preferred = ctx['preferred']
    if preferred is None: return []
    if len(preferred['rationale'].strip()) < MIN_RATIONALE:
        return [('missing_rationale', f'preferred option {preferred["id"]} gives no reason it is the least change that is enough ({MIN_RATIONALE}+ characters).')]
    return []


def rule_targets(ctx):
    out, ledger = [], ctx['ledger']
    if ctx['preferred'] is None or ledger is None: return out
    project = Path(ledger.project).resolve()
    for change in ctx['planned']:
        target = (project / change['target']).resolve()
        if project != target and project not in target.parents: out.append(('target_missing', f'change {change["id"]}.target {change["target"]} is outside the project.'))
        elif not target.exists(): out.append(('target_missing', f'change {change["id"]}.target {change["target"]} does not exist under the project.'))
    return out


def rule_preferred(ctx):
    if ctx['preferred'] is None and not blocking_unknowns(ctx['proposal']) and not any(c == 'unknown_unscoped' for c, _ in rule_unknowns(ctx)):
        return [('no_preferred', 'the proposal has no preferred option: give one, or an unknown that blocks the choice.')]
    return []


# ---- 2.4-C: the card rules (only for a proposal that uses preserve / investigation / estimate) ---------------------------------

def rule_preserve(ctx):
    """A change that modifies or deletes something says what it keeps unchanged."""
    proposal = ctx['proposal']
    if not proposal['card']: return []
    touching = [c['id'] for c in ctx['planned'] if c['kind'] in ('modify', 'delete')]
    if touching and not proposal['preserve']:
        return [('preserve_missing', f'change {", ".join(touching)} modifies or deletes: say what stays unchanged (proposal.preserve [{{id, text}}]), '
                                     'so the check and the reviewer can hold the work to it.')]
    return []


def _sourced(ctx, ref):
    if not isinstance(ref, str) or not ref.strip(): return False
    if ctx['ledger'] is None: return True
    from . import step0
    try:
        step0.evidence_kind(ctx['ledger'], ref, 'poc')
    except LedgerError:
        return False
    return True


def rule_estimate(ctx):
    """A sourced range, or an explicit "not enough data" that names what is missing; never 0, never a bare number."""
    proposal = ctx['proposal']
    if not proposal['card']: return []
    value = proposal['estimate']
    if value is None:
        return [('estimate_missing', 'give the estimate as a sourced range {"range": [lo, hi], "evidence": [...]} or say {"status": "not_enough_data", '
                                     '"missing": "..."} - it is never left implicit.')]
    if 'bare' in value:
        return [('estimate_unsourced', f'estimate {value["bare"]!r} is a bare number: give a range [lo, hi] with its evidence, or not_enough_data.')]
    if value.get('status') is not None:
        if value['status'] != 'not_enough_data' or not isinstance(value.get('missing'), str) or not value['missing'].strip() or 'range' in value:
            return [('estimate_unsourced', 'estimate.status is "not_enough_data" with the missing data named (missing), and no range.')]
        return []
    span = value.get('range')
    if (not isinstance(span, list) or len(span) != 2 or any(type(v) not in (int, float) or v != v for v in span) or span[0] > span[1]):
        return [('estimate_unsourced', 'estimate.range is [lo, hi] seconds with lo <= hi.')]
    if span[0] <= 0:
        return [('estimate_zero', f'estimate.range {span} starts at 0: a cost that was not measured is unknown, never 0 (say not_enough_data).')]
    refs = value.get('evidence') or []
    if not refs or not all(_sourced(ctx, ref) for ref in refs):
        return [('estimate_unsourced', 'estimate.range needs evidence that resolves (a blob, a URL or a file:line) for every reference.')]
    open_for_estimate = [u['id'] for u in proposal['unknowns'] if u['status'] == 'open' and u['required_by'] == 'estimate']
    if open_for_estimate:
        return [('estimate_unsourced', f'unknown {", ".join(open_for_estimate)} is open and the estimate waits for it: say not_enough_data until it is closed.')]
    return []


def rule_investigation(ctx):
    """The step-0 investigation is bounded: explicit read paths (never the whole project), a cap inside the survey bounds, an end
    condition, and no more spent than the cap. A card with an unknown that blocks the choice states its investigation."""
    proposal = ctx['proposal']
    value = proposal['investigation']
    if value is None:
        if proposal['card'] and blocking_unknowns(proposal):
            return [('investigation_missing', 'an unknown blocks the choice: state the investigation (cap, explicit paths, stop_when) instead of '
                                              'a survey of the whole project.')]
        return []
    out = []
    whole = [p for p in value['paths'] if p.strip().rstrip('/') in WHOLE_PROJECT or p.strip() in WHOLE_PROJECT]
    if whole:
        out.append(('investigation_unscoped', 'investigation.paths names the whole project (".": a scan of every file): name the paths the unknown is about.'))
    else:
        from ..snapshots import scoped_path
        for path in value['paths']:
            try:
                scoped_path(path)
            except LedgerError as error:
                out.append(('investigation_unscoped', f'investigation path {path!r}: {error}'))
    cap = value['cap']
    if not (1 <= cap['minutes'] <= MAX_MINUTES and 1 <= cap['calls'] <= MAX_CALLS):
        out.append(('investigation_cap', f'investigation.cap: 1-{MAX_MINUTES} minutes and 1-{MAX_CALLS} calls.'))
    spent = ctx['spent']
    if spent.get('seconds', 0) > cap['minutes'] * 60 or spent.get('calls', 0) > cap['calls']:
        out.append(('investigation_over_cap', f'the step-0 surveys spent {spent} - more than the investigation cap {cap}.'))
    return out


def rule_open_for_approval(ctx):
    """An open unknown the approval waits for (required_by approval) holds it; it is never closed by default."""
    if not ctx['proposal']['card']: return []
    waiting = [u['id'] for u in ctx['proposal']['unknowns'] if u['status'] == 'open' and u['required_by'] == 'approval' and u['affected']]
    return [('unknown_open', f'unknown {", ".join(waiting)} is open and the approval waits for it: close it with evidence (survey, PoC or the owner).')] if waiting else []


RULES = (rule_unknowns, rule_preferred, rule_declaration, rule_linkage, rule_acceptance, rule_semantics, rule_rationale, rule_targets,
         rule_preserve, rule_estimate, rule_investigation, rule_open_for_approval)


def check(ledger, requirement, proposal, rules=None, spent=None):
    """Hold `proposal` to `requirement`. Returns {ok, result: ok|refused|survey_first, reasons: [(code, text)], table, backlog, ...}.
    `rules` defaults to RULES (a test passes a shorter tuple for the counter-proof). `spent` = what the step-0 surveys of the plan spent
    ({seconds, calls}), held against the card's investigation cap."""
    requirement, proposal = validate_requirement(requirement), validate_proposal(proposal)
    ctx = _context(ledger, requirement, proposal, spent)
    reasons = []
    for rule in (RULES if rules is None else rules): reasons += rule(ctx)
    waiting = blocking_unknowns(proposal)
    if waiting:
        reasons.append(('survey_first', f'unknown {", ".join(u["id"] for u in waiting)} blocks the choice of an option: a bounded, read-only survey comes first.'))
    preferred = proposal['preferred']
    result = 'survey_first' if waiting else ('ok' if not reasons else 'refused')
    backlog = proposal['backlog'] + [{'id': c['id'], 'title': c['title']} for c in ctx['optional']]
    return {'ok': not reasons, 'result': result, 'reasons': reasons,
            'table': [{'change': c['id'], 'kind': c['kind'], 'entries': c['entries'], 'links': c['links'], 'target': c['target']} for c in ctx['planned']],
            'backlog': backlog, 'preferred': preferred['id'] if preferred else None,
            'before': preferred['before'] if preferred else None, 'after': preferred['after'] if preferred else None,
            'rationale': preferred['rationale'] if preferred else None, 'in_authority': proposal['in_authority'], 'extras': proposal['extras'],
            'unknowns': proposal['unknowns'], 'survey_required': [u['id'] for u in waiting], 'owner_requests': 0,
            **({'card_fields': {'preserve': proposal['preserve'], 'investigation': proposal['investigation'], 'estimate': proposal['estimate'],
                                'summary': preferred['summary'] if preferred else None, 'acceptance': requirement['acceptance']}}
               if proposal['card'] else {})}
