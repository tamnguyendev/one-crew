"""Relocate a locator of a OneCrew-planned device scenario only when the live UI proves it is the same object.

Principle (Codex reviews of round 2): recalibration may change HOW a step finds its node, never WHICH business
object it acts on or WHAT it checks. A label that matches, or a selector that happens to name one node, is not proof.

A selector splits into identity (text, content-desc, hint, resource-id, class), conditions (checked everywhere;
focused in an assertion) and incidental keys (focused in a locator step). Identity never changes: resource-id and
class stay exactly as written (a node showing another value, or none, is not shown to be the same object - it may
be a sibling with the same label or the object may be off screen), and each expected label stays verbatim; only
the attribute that carries a label may change (text, content-desc or hint, or one whole part of a merged label).
Conditions never change; incidental keys may be dropped. With the sanitized snapshot recorded at the failing
step, exactly one app node must show every identity fact; zero or several is not a proof. If the old identity
already names that node exactly, the failure was its condition (a product or precondition finding), not its
locator. The relocated selector must resolve to exactly that node. Only the failing step can be proven (later
steps and cleanup have no snapshot of their screen), assert_absent is never relocated, a label-less selector has
nothing to relocate, a type target must be an EditText. Everything is decided by code; no model and no screen
data leave the machine. A user-pinned scenario and real-device (exact) stages are never relocated, and
relocations per device node are bounded."""
import json
import re
from pathlib import Path
from xml.sax.saxutils import quoteattr

from .ledger import LedgerError, canonical, content_hash, utcnow

MAX_CALIBRATIONS = 4  # each relocation fixes one proven step; deterministic, so no step loops on itself
ASSERTIONS = ('assert_ui', 'wait_for', 'assert_absent')
LABEL_KEYS = ('text', 'content-desc', 'hint')
IDENTITY_KEYS = LABEL_KEYS + ('resource-id', 'class')
# The snapshot omits a boolean attribute that is 'false'; the live dump always writes it.
BOOLEAN = ('checked', 'focused', 'clickable', 'scrollable')


def _get(node, key):
    return node.get(key) or ('false' if key in BOOLEAN else '')


def rc_key(failure):
    from .delivery_recovery import normalize
    return normalize(failure)


def literals(selector):
    return [v for k, v in selector.items() if k in LABEL_KEYS]


def mentioned(nodes, values):
    labels = [str(n.get(k) or '').casefold() for n in nodes for k in LABEL_KEYS]
    return all(any(v.casefold() in label for label in labels) for v in values)


def as_xml(nodes, package):
    """The recorded snapshot as a hierarchy the live resolver reads, so a selector is checked the same way."""
    parts = []
    for n in nodes:
        attrs = dict({k: 'false' for k in BOOLEAN}, **n, package=package, enabled='true')
        parts.append('<node ' + ' '.join(f'{k}={quoteattr(str(v))}' for k, v in attrs.items()) + '/>')
    return '<hierarchy>' + ''.join(parts) + '</hierarchy>'


def _parts(value):
    return [p.strip() for p in re.split(r'\n|, ', value or '') if p.strip()]


def split(selector, operation):
    """(identity, conditions, incidental) of a selector for the given operation."""
    condition_keys = ('checked', 'focused') if operation in ASSERTIONS else ('checked',)
    identity = {k: v for k, v in selector.items() if k in IDENTITY_KEYS}
    conditions = {k: v for k, v in selector.items() if k in condition_keys}
    incidental = {k: v for k, v in selector.items() if k not in identity and k not in conditions}
    return identity, conditions, incidental


def _holds(node, value):
    """The label attribute of the node that shows the value verbatim (whole or one merged part), else None."""
    for key in LABEL_KEYS:
        text = node.get(key) or ''
        if value == text or value in _parts(text): return key
    return None


def relocate(selector, operation, view):
    """(new_selector, kind, reason). kind: relocated | condition | ambiguous | absent | unprovable."""
    if operation == 'assert_absent':
        return None, 'unprovable', 'an absence check is never relocated'
    nodes = view['nodes']
    identity, conditions, incidental = split(selector, operation)
    labels = {k: v for k, v in identity.items() if k in LABEL_KEYS}
    if not labels:
        return None, 'unprovable', 'the selector names no visible label, so no node can be proven to be its target'
    facts = {k: v for k, v in identity.items() if k not in LABEL_KEYS}
    candidates = [n for n in nodes if all(_holds(n, v) for v in labels.values()) and all(_get(n, k) == v for k, v in facts.items())]
    if not candidates:
        return None, 'absent', 'no node on screen shows ' + canonical(list(labels.values()))[:200] + (' with ' + canonical(facts)[:120] if facts else '')
    if len(candidates) > 1:
        return None, 'ambiguous', str(len(candidates)) + ' nodes on screen fit the identity; no proof which object is meant'
    target = candidates[0]
    if not all(_get(target, k) == v for k, v in conditions.items()):
        return None, 'condition', ('the step found its object on screen (identity proven) but its condition ' +
                                   canonical(conditions)[:120] + ' does not hold (not a locator problem)')
    if operation == 'type' and target.get('class') != 'android.widget.EditText':
        return None, 'unprovable', 'the only consistent node is not an EditText'
    placed = {_holds(target, v) for v in labels.values()}
    if len(placed) < len(labels):
        return None, 'unprovable', 'two expected labels share one attribute on that node; both cannot stay verbatim'
    new = dict(facts)
    for value in labels.values(): new[_holds(target, value)] = value
    new.update(conditions)
    if new == selector:
        return None, 'unprovable', 'the old selector already names this node; the failure is not a locator problem'
    from .delivery_android import resolve
    try: found, _ = resolve(as_xml(nodes, view['package']), new)
    except LedgerError: return None, 'ambiguous', 'the relocated selector does not name exactly one node'
    if any(_get(found.attrib, k) != _get(target, k) for k in set(target) | set(BOOLEAN)):
        return None, 'ambiguous', 'the relocated selector names another node than the proven one'
    moved = sorted(k + '->' + _holds(target, v) for k, v in labels.items() if _holds(target, v) != k)
    return new, 'relocated', ('proven by the live UI: identity kept' + ('; label ' + ','.join(moved) if moved else '') +
                              ('; dropped incidental ' + ','.join(sorted(incidental)) if incidental else ''))


def check(old, new, failure, view):
    """Findings for a revised scenario; empty only when it differs from the old one solely by the proven relocation
    of the failing step. Defence in depth for every path that writes a scenario revision."""
    from .delivery_android import SELECTOR_KEYS
    findings = []
    for part in ('steps', 'cleanup'):
        before, after = old[part], new.get(part)
        if not isinstance(after, list) or len(after) != len(before):
            findings.append(part + ': same number of steps required'); continue
        for i, (a, b) in enumerate(zip(before, after)):
            if not isinstance(b, dict) or b.get('id') != a['id'] or b.get('operation') != a['operation']:
                findings.append(f"{part}[{i}]: id and operation must stay {a['id']}/{a['operation']}"); continue
            args = b.get('arguments') if isinstance(b.get('arguments'), dict) else {}
            if set(args) != set(a['arguments']) or any(args[k] != v for k, v in a['arguments'].items() if k != 'selector'):
                findings.append(f"{a['id']}: only the selector may change"); continue
            if 'selector' not in a['arguments'] or args['selector'] == a['arguments']['selector']: continue
            if part != 'steps' or a['id'] != failure.get('step'):
                findings.append(f"{a['id']}: no live-UI proof for this step (only the failing step's screen was recorded)"); continue
            selector = args['selector']
            if (not isinstance(selector, dict) or not selector or set(selector) - SELECTOR_KEYS or
                    any(not isinstance(x, str) or len(x) > 200 for x in selector.values())):
                findings.append(f"{a['id']}: typed exact selector required"); continue
            if view is None:
                findings.append(f"{a['id']}: no live-UI snapshot, so no proof"); continue
            proven, kind, reason = relocate(a['arguments']['selector'], a['operation'], view)
            if proven is None: findings.append(f"{a['id']}: {reason}")
            elif selector != proven: findings.append(f"{a['id']}: only the proven relocation {canonical(proven)[:200]} is accepted")
    return findings


def _view(job):
    from .delivery_steps import file_hash
    snap = job.get('snapshot')
    if not snap: return None
    path = Path(snap['file'])
    if not path.is_file() or file_hash(path) != snap['sha256']: raise LedgerError('Device UI snapshot changed or missing; calibration refused.')
    return json.loads(path.read_text(encoding='utf-8'))


def _product(runtime, task_id, s, node, row, detail):
    """A device finding about the product: the bounded code-repair path, never a weaker scenario."""
    from . import delivery_recovery as rc
    row.pop('calibrate', None)
    row['receipt'] = dict(row.get('receipt') or {}, failure_kind='product', detail=detail[:500])
    row['phase'] = 'blocked'
    runtime._recover(task_id, s, node, 'product', rc.normalize(detail), detail)


def _blocker(runtime, task_id, s, node, row, detail, failure):
    from . import delivery_recovery as rc
    row.pop('calibrate', None); row['phase'] = 'blocked'
    runtime._recover(task_id, s, node, 'device_assertion', rc.normalize(failure), detail)


def step(runtime, task_id, s, node, row):
    """One relocation transition for a device node marked by the recovery policy. Deterministic; no model call."""
    from .delivery_android import active_scenario, scenario, selector_mode
    from .delivery_steps import file_hash, home
    from .snapshots import durable_write
    d = s['delivery']; job = row['calibrate']; failure = job.get('failure') or {}
    if selector_mode(node['config']) == 'exact':
        # A real-device (exact) stage is never relocated: a mismatch is a blocker with masked evidence.
        row.pop('calibrate', None); row['phase'] = 'blocked'
        runtime._recover(task_id, s, node, 'selector_mismatch', rc_key(failure), 'Exact selector mode: relocation refused.')
        return
    path, digest, revision = active_scenario(node, row)
    old = scenario(path, digest)
    view = _view(job)
    target = next((x for x in old['steps'] if x['id'] == failure.get('step')), None)
    if target is None or view is None or 'selector' not in target['arguments']:
        _blocker(runtime, task_id, s, node, row, 'No live-UI proof for the failing step; the scenario is unchanged.', failure)
        return
    selector, operation = target['arguments']['selector'], target['operation']
    proven, kind, reason = relocate(selector, operation, view)
    history = {'calibrate': node['id'], 'generation': row['generation'], 'from_scenario': digest, 'failure': failure,
               'method': 'relocate-by-observation', 'kind': kind, 'reason': reason, 'at': utcnow()}
    if proven is None:
        d['history'].append(history)
        if operation in ('assert_ui', 'wait_for') and (kind == 'condition' or not mentioned(view['nodes'], literals(selector))):
            # The check itself is false on screen (expected state or text not there): a product finding, assertion unchanged.
            _product(runtime, task_id, s, node, row, 'Device E2E: step ' + target['id'] + ' ' + reason + '. The app must satisfy it; '
                     'the scenario assertion is unchanged.')
        else:
            _blocker(runtime, task_id, s, node, row, 'Locator of step ' + target['id'] + ' not relocated: ' + reason +
                     '. The scenario is unchanged; a person must confirm the target.', failure)
        return
    revised = json.loads(json.dumps(old))
    next(x for x in revised['steps'] if x['id'] == target['id'])['arguments']['selector'] = proven
    findings = check(old, revised, failure, view)
    if findings:  # cannot happen for a proven relocation; refuse rather than write an unproven revision
        history['findings'] = findings; d['history'].append(history)
        _blocker(runtime, task_id, s, node, row, 'Relocation refused by its own check: ' + '; '.join(findings)[:600], failure)
        return
    new_path = home(runtime, task_id) / ('scenario-' + content_hash(revised)[:16] + '.json')
    durable_write(new_path, canonical(revised).encode())
    new_digest = file_hash(new_path)
    scenario(new_path, new_digest)
    row['scenario'] = {'path': str(new_path), 'sha256': new_digest, 'revision': revision + 1, 'from': digest, 'changed_steps': [target['id']]}
    row['calibrations'] = row.get('calibrations', 0) + 1
    row.pop('calibrate', None); row['phase'] = 'pending'
    history.update(to_scenario=new_digest, changed_steps=[target['id']], selector_before=selector, selector_after=proven)
    d['history'].append(history)
    s['message'] = 'Locator of step ' + target['id'] + ' relocated by live-UI proof; device stage reruns.'
