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


KNOWN_CONTRACT_FIELDS = {'schema_version', 'title', 'size', 'understanding', 'preconditions', 'output', 'scope', 'non_goals', 'items', 'milestones',
                         'budget', 'attention', 'stop', 'profile_version', 'origin', 'decisions', 'presentation', 'authority', 'review_policy',
                         'solution_ref', 'advisor', 'name'}


def classify_contract(before, after):
    """Contract revision before/after (plan amend): outputs (text by position), milestones (covers, verifier, mode, max_repairs, criteria, argv),
    scope.owned narrowing, budget/stop; unknown fields that changed are a change (g)."""
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
        if sorted(m.get('covers', [])) != sorted(n.get('covers', [])) or m.get('verifier', {}).get('type') != n.get('verifier', {}).get('type') \
                or m.get('mode', 'once') != n.get('mode', 'once') or m.get('max_repairs') != n.get('max_repairs'):
            changes.append({'path': f'milestones.{mid}', 'kind': 'obligation', 'acceptance': True, 'why': 'covers, verifier type, mode or max_repairs changed'})
        oc, nc = m.get('verifier', {}).get('config') or {}, n.get('verifier', {}).get('config') or {}
        if oc.get('argv') != nc.get('argv') and 'argv' in oc:
            changes.append({'path': f'milestones.{mid}.argv', 'kind': 'obligation', 'acceptance': True, 'why': 'the approved command changed'})
        if (oc.get('cwd') or '.') != (nc.get('cwd') or '.') and ('argv' in oc or 'argv' in nc):
            changes.append({'path': f'milestones.{mid}.cwd', 'kind': 'obligation', 'acceptance': True, 'why': 'the directory the approved command runs in changed'})
        for key in ('provider', 'model'):
            if oc.get(key) != nc.get(key) and (key in oc or key in nc):
                changes.append({'path': f'milestones.{mid}.{key}', 'kind': 'obligation', 'acceptance': True, 'why': f'the approved reviewer {key} changed'})
        old_cr = {c['id']: c.get('question', '') for c in oc.get('criteria') or []}
        new_cr = {c['id']: c.get('question', '') for c in nc.get('criteria') or []}
        for cid, q in old_cr.items():
            if cid not in new_cr:
                changes.append({'path': f'milestones.{mid}.criteria.{cid}', 'kind': 'removed_check', 'acceptance': True, 'why': 'a review criterion was dropped'})
            else:
                item = _text_change(f'milestones.{mid}.criteria.{cid}', q, new_cr[cid], what='review criterion')
                if item: changes.append(item)
        for cid in sorted(set(new_cr) - set(old_cr)):
            changes.append({'path': f'milestones.{mid}.criteria.{cid}', 'kind': 'added_check', 'acceptance': False, 'why': 'a review criterion was added'})
        for key in ('max_minutes',):
            if key in oc and oc.get(key) != nc.get(key):
                changes.append({'path': f'milestones.{mid}.{key}', 'kind': 'threshold', 'acceptance': True, 'why': 'a verifier limit changed'})
    for mid in sorted(set(new_m) - set(old_m)):
        changes.append({'path': f'milestones.{mid}', 'kind': 'added_check', 'acceptance': False, 'why': 'a milestone was added'})
    old_scope, new_scope = set((before.get('scope') or {}).get('owned') or []), set((after.get('scope') or {}).get('owned') or [])
    if old_scope - new_scope:
        changes.append({'path': 'scope.owned', 'kind': 'narrowed', 'acceptance': True, 'why': 'owned scope narrowed: ' + ', '.join(sorted(old_scope - new_scope))})
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
