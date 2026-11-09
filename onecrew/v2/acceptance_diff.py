"""W05 / T21: classify a change of contract or internal plan as a change of acceptance (U1, HD-04) or not.

The classes of the fixture (a)-(g): (a) wording only and (b) an added check are NOT changes of acceptance; (c) a changed threshold,
(d) a dropped required result, (e) a narrowed acceptance, (f) a changed obligation ARE (U1); (g) anything this module cannot classify is
treated as a change (safe side, [E3]). Pure functions: no ledger, no model.
"""
import re

NUMBER = re.compile(r'-?\d+(?:[.,]\d+)?\s*%?')
PUNCT = re.compile(r'[\s\.,;:!?\-–—"\'`()\[\]{}]+')


def _words(text):
    """The wording skeleton: case-folded words without punctuation and whitespace."""
    return [w for w in PUNCT.split(str(text).casefold()) if w]


def _shape(text):
    """The text with every number replaced by a placeholder: equal shapes with different numbers = a changed threshold."""
    return NUMBER.sub('#', ' '.join(_words(text)))


def classify_text(before, after):
    """'same' | 'wording' | 'threshold' | 'changed' for one requirement text."""
    if before == after: return 'same'
    if _words(before) == _words(after): return 'wording'
    if _shape(before) == _shape(after) and NUMBER.search(str(before)) and NUMBER.search(str(after)): return 'threshold'
    return 'changed'


def _finish(changes):
    acceptance = [c for c in changes if c['acceptance']]
    return {'acceptance_changed': bool(acceptance), 'classification': 'U1' if acceptance else 'routine', 'changes': changes,
            'summary': '; '.join(f"{c['kind']}: {c['path']}" for c in acceptance) or 'wording or added checks only'}


def _text_change(path, before, after, *, what):
    kind = classify_text(before, after)
    if kind == 'same': return None
    if kind == 'wording': return {'path': path, 'kind': 'wording', 'acceptance': False, 'why': f'{what}: only the wording changed'}
    if kind == 'threshold': return {'path': path, 'kind': 'threshold', 'acceptance': True, 'why': f'{what}: a number (threshold) changed'}
    return {'path': path, 'kind': 'narrowed_or_changed', 'acceptance': True, 'why': f'{what}: the text changed beyond wording (scope or meaning)'}


def classify_nodes(old_nodes, new_nodes, output_ids):
    """Internal plan (04 W05, HD-04): node acceptance ids and check specs before/after. Dropping an approved output from every node, dropping a
    check or changing a check beyond wording is a change of acceptance; an added check or a reworded spec is routine."""
    changes = []
    old_cov = {oid for n in old_nodes for oid in n.get('acceptance', [])}
    new_cov = {oid for n in new_nodes for oid in n.get('acceptance', [])}
    for oid in sorted(set(output_ids)):
        if oid in old_cov and oid not in new_cov:
            changes.append({'path': f'acceptance:{oid}', 'kind': 'removed_result', 'acceptance': True, 'why': 'an approved output lost every node that proves it'})
    unknown = sorted(new_cov - set(output_ids))
    for oid in unknown:
        changes.append({'path': f'acceptance:{oid}', 'kind': 'unknown', 'acceptance': True, 'why': 'acceptance refers to an output the contract does not have'})
    old_checks = {(n['id'], c['id']): c.get('spec', '') for n in old_nodes for c in n.get('checks', [])}
    new_checks = {(n['id'], c['id']): c.get('spec', '') for n in new_nodes for c in n.get('checks', [])}
    new_ids = {n['id'] for n in new_nodes}
    matched = set()
    # Checks are compared across the whole plan (W05): a check of a removed, renamed or split node must reappear somewhere — under the
    # same check id (moved) with an equal/wording-only spec, or under any id with an equal/wording-only spec — else it was dropped (U1).
    for key, spec in sorted(old_checks.items()):
        node, cid = key
        if key in new_checks:
            matched.add(key)
            item = _text_change(f'{node}.checks.{cid}.spec', spec, new_checks[key], what='check spec')
            if item: changes.append(item)
    for key, spec in sorted(old_checks.items()):
        node, cid = key
        if key in new_checks: continue
        free = [k for k in sorted(new_checks) if k not in matched]
        equal = [k for k in free if classify_text(spec, new_checks[k]) in ('same', 'wording')]
        moved = [k for k in free if k[1] == cid]
        target = next((k for k in equal if k[1] == cid), None) or (equal[0] if equal else None) or (moved[0] if moved else None)
        if target is None:
            why = 'a check of a kept node was dropped' if node in new_ids else 'a check of a removed or renamed node did not reappear in the plan'
            changes.append({'path': f'{node}.checks.{cid}', 'kind': 'removed_check', 'acceptance': True, 'why': why})
            continue
        matched.add(target)
        item = _text_change(f'{node}.checks.{cid}.spec->{target[0]}.checks.{target[1]}.spec', spec, new_checks[target], what='moved check spec')
        changes.append(item or {'path': f'{node}.checks.{cid}->{target[0]}.checks.{target[1]}', 'kind': 'moved_check', 'acceptance': False,
                                'why': 'the check moved to another node with the same spec'})
    for key in sorted(set(new_checks) - matched):
        changes.append({'path': f'{key[0]}.checks.{key[1]}', 'kind': 'added_check', 'acceptance': False, 'why': 'a check was added (more verification, not less)'})
    return _finish(changes)


# Issue #9 (09/11, owner "Đưa vào"): an allow-list, not a deny-list. Every change of a milestone, of its verifier or of the verifier's configuration
# is a change of acceptance (the owner approves it), except what is listed here as harmless: a milestone title (how it is shown), a review
# criterion added (more verification) or changed only in its white space. Reworded, reordered or given twice: acceptance (review of dev14). A verifier key nobody listed, a dropped count or pattern, an added exemption,
# another auth: acceptance. Comparing whole values errs on the safe side (a reordered list is reported too).
MILESTONE_COMPARED = frozenset({'id', 'covers', 'verifier', 'mode', 'max_repairs'})
MILESTONE_HARMLESS = frozenset({'title'})
CONFIG_SPECIAL = frozenset({'criteria'})
CONFIG_DEFAULTS = {'cwd': '.'}


SPACES = re.compile(r'\s+')


def _criterion_change(path, before, after):
    """Issue #9, review of dev14: a reviewer reads every character of its question ("safe-mode" and "safe mode" are two literals to look for), so only
    a change of white space is harmless; any other character changed is a change the owner approves."""
    if before == after: return None
    if SPACES.sub(' ', str(before)).strip() == SPACES.sub(' ', str(after)).strip():
        return {'path': path, 'kind': 'wording', 'acceptance': False, 'why': 'review criterion: only the white space changed'}
    return {'path': path, 'kind': 'narrowed_or_changed', 'acceptance': True,
            'why': 'review criterion: its text changed (the reviewer checks what it says, character by character)'}


def _milestone_changes(mid, m, n):
    changes = []
    if sorted(m.get('covers', [])) != sorted(n.get('covers', [])) or (m.get('verifier') or {}).get('type') != (n.get('verifier') or {}).get('type')             or m.get('mode', 'once') != n.get('mode', 'once') or m.get('max_repairs') != n.get('max_repairs'):
        changes.append({'path': f'milestones.{mid}', 'kind': 'obligation', 'acceptance': True, 'why': 'covers, verifier type, mode or max_repairs changed'})
    for key in sorted((set(m) | set(n)) - MILESTONE_COMPARED):
        if m.get(key) == n.get(key): continue
        if key in MILESTONE_HARMLESS:
            changes.append({'path': f'milestones.{mid}.{key}', 'kind': 'presentation', 'acceptance': False, 'why': f'the milestone {key} changed (how it is shown)'})
        else:
            changes.append({'path': f'milestones.{mid}.{key}', 'kind': 'obligation', 'acceptance': True, 'why': f'the milestone field {key} changed'})
    ov, nv = m.get('verifier') or {}, n.get('verifier') or {}
    for key in sorted((set(ov) | set(nv)) - {'type', 'config'}):
        if ov.get(key) != nv.get(key):
            changes.append({'path': f'milestones.{mid}.verifier.{key}', 'kind': 'obligation', 'acceptance': True, 'why': f'the verifier field {key} changed'})
    oc, nc = ov.get('config') or {}, nv.get('config') or {}
    for key in sorted((set(oc) | set(nc)) - CONFIG_SPECIAL):
        before, after = oc.get(key, CONFIG_DEFAULTS.get(key)), nc.get(key, CONFIG_DEFAULTS.get(key))
        if before == after: continue
        numeric = all(isinstance(x, (int, float)) and not isinstance(x, bool) for x in (before, after))
        changes.append({'path': f'milestones.{mid}.{key}', 'kind': 'threshold' if numeric or key == 'max_minutes' else 'obligation', 'acceptance': True,
                        'why': f'the approved verifier setting {key} changed' + ('' if key in oc and key in nc else ' (added)' if key in nc else ' (removed)')})
    old_list, new_list = list(oc.get('criteria') or []), list(nc.get('criteria') or [])
    old_cr = {c['id']: c for c in old_list}
    new_cr = {c['id']: c for c in new_list}
    old_ids, new_ids = [c['id'] for c in old_list], [c['id'] for c in new_list]
    if len(old_ids) != len(old_cr) or len(new_ids) != len(new_cr):
        if old_list != new_list:          # an id given twice: which question the reviewer answers under it is not settled
            changes.append({'path': f'milestones.{mid}.criteria', 'kind': 'obligation', 'acceptance': True, 'why': 'a review criterion id appears twice'})
    elif [i for i in old_ids if i in new_cr] != [i for i in new_ids if i in old_cr]:
        changes.append({'path': f'milestones.{mid}.criteria', 'kind': 'obligation', 'acceptance': True,
                        'why': 'the review criteria were reordered (the reviewer answers them in this order)'})
    for cid, c in old_cr.items():
        if cid not in new_cr:
            changes.append({'path': f'milestones.{mid}.criteria.{cid}', 'kind': 'removed_check', 'acceptance': True, 'why': 'a review criterion was dropped'})
            continue
        item = _criterion_change(f'milestones.{mid}.criteria.{cid}', c.get('question', ''), new_cr[cid].get('question', ''))
        if item: changes.append(item)
        if {k: v for k, v in c.items() if k != 'question'} != {k: v for k, v in new_cr[cid].items() if k != 'question'}:
            changes.append({'path': f'milestones.{mid}.criteria.{cid}', 'kind': 'obligation', 'acceptance': True, 'why': 'a review criterion setting changed'})
    for cid in sorted(set(new_cr) - set(old_cr)):
        changes.append({'path': f'milestones.{mid}.criteria.{cid}', 'kind': 'added_check', 'acceptance': False, 'why': 'a review criterion was added'})
    return changes


KNOWN_CONTRACT_FIELDS = {'schema_version', 'title', 'size', 'understanding', 'preconditions', 'output', 'scope', 'non_goals', 'items', 'milestones',
                         'budget', 'attention', 'stop', 'profile_version', 'origin', 'decisions', 'presentation', 'authority', 'review_policy',
                         'solution_ref', 'advisor', 'name'}


def classify_contract(before, after):
    """Contract revision before/after (plan amend): outputs (text by position), milestones (every field and every verifier setting: issue #9),
    the scope (owned narrowed or widened, any other key), budget/stop; unknown fields that changed are a change (g)."""
    changes = []
    old_out, new_out = list(before.get('output') or []), list(after.get('output') or [])
    for index, text in enumerate(old_out, start=1):
        if index > len(new_out):
            changes.append({'path': f'output:O{index}', 'kind': 'removed_result', 'acceptance': True, 'why': 'a required result was dropped'})
            continue
        item = _text_change(f'output:O{index}', text, new_out[index - 1], what='required result')
        if item: changes.append(item)
    for index in range(len(old_out) + 1, len(new_out) + 1):
        changes.append({'path': f'output:O{index}', 'kind': 'added_result', 'acceptance': True, 'why': 'a required result was added (the obligation grew)'})
    old_m = {m['id']: m for m in before.get('milestones') or []}
    new_m = {m['id']: m for m in after.get('milestones') or []}
    for mid, m in old_m.items():
        n = new_m.get(mid)
        if n is None:
            changes.append({'path': f'milestones.{mid}', 'kind': 'removed_check', 'acceptance': True, 'why': 'a milestone was dropped'}); continue
        changes += _milestone_changes(mid, m, n)
    # review of dev16 (P1): a new milestone is only an added check after every old one; placed before one, it becomes that milestone's prerequisite
    last_old = max((i for i, m in enumerate(new_m) if m in old_m), default=-1)
    for index, mid in enumerate(new_m):
        if mid in old_m: continue
        if index < last_old:
            changes.append({'path': f'milestones.{mid}', 'kind': 'obligation', 'acceptance': True,
                            'why': 'a milestone was inserted before an approved one (that one now waits for it)'})
        else:
            changes.append({'path': f'milestones.{mid}', 'kind': 'added_check', 'acceptance': False, 'why': 'a milestone was added after the approved ones'})
    # review of dev15 (P1): milestones run in the order of the list (verdict.run refuses one whose earlier ones have not passed), so a new order is
    # a change the owner approves: a reviewer moved before the command that makes its evidence, say.
    if [m for m in old_m if m in new_m] != [m for m in new_m if m in old_m]:
        changes.append({'path': 'milestones', 'kind': 'obligation', 'acceptance': True, 'why': 'the milestones were reordered (they run in this order)'})
    old_scope_all, new_scope_all = before.get('scope') or {}, after.get('scope') or {}
    old_scope, new_scope = set(old_scope_all.get('owned') or []), set(new_scope_all.get('owned') or [])
    if old_scope - new_scope:
        changes.append({'path': 'scope.owned', 'kind': 'narrowed', 'acceptance': True, 'why': 'owned scope narrowed: ' + ', '.join(sorted(old_scope - new_scope))})
    if new_scope - old_scope:          # issue #9: a wider write permission is a change the owner approves, never "added checks"
        changes.append({'path': 'scope.owned', 'kind': 'widened', 'acceptance': True, 'why': 'owned scope widened: ' + ', '.join(sorted(new_scope - old_scope))})
    for key in sorted((set(old_scope_all) | set(new_scope_all)) - {'owned'}):
        if old_scope_all.get(key) != new_scope_all.get(key):
            changes.append({'path': f'scope.{key}', 'kind': 'obligation', 'acceptance': True, 'why': f'scope.{key} changed'})
    for field in ('budget', 'stop', 'attention'):
        if before.get(field) != after.get(field) and (field in before or field in after):
            changes.append({'path': field, 'kind': 'threshold', 'acceptance': True, 'why': f'{field} changed (a settled constraint)'})
    for field in sorted((set(before) | set(after)) - KNOWN_CONTRACT_FIELDS):
        if before.get(field) != after.get(field):
            changes.append({'path': field, 'kind': 'unknown', 'acceptance': True, 'why': 'a field this classifier does not know changed; treated as a change'})
    for field in ('title', 'non_goals', 'understanding', 'preconditions', 'items', 'decisions', 'origin', 'presentation', 'review_policy', 'authority', 'advisor', 'solution_ref', 'profile_version', 'size'):
        if before.get(field) != after.get(field) and not any(c['path'] == field for c in changes):
            kind = classify_text(before.get(field), after.get(field)) if isinstance(before.get(field), str) and isinstance(after.get(field), str) else 'changed'
            if kind == 'wording':
                changes.append({'path': field, 'kind': 'wording', 'acceptance': False, 'why': f'{field}: only the wording changed'})
            elif field in ('title', 'presentation', 'origin', 'decisions', 'size', 'profile_version'):
                changes.append({'path': field, 'kind': 'presentation', 'acceptance': False, 'why': f'{field} changed: how the plan is shown or sourced, not what it must achieve'})
            else:
                changes.append({'path': field, 'kind': 'obligation', 'acceptance': True, 'why': f'{field} changed (settled constraint or scope)'})
    return _finish(changes)
