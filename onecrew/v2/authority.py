"""W02 (R04) - the authority grant of a root contract, the "plan is inside the grant" test, and the decision function.

Form (00 §7, O2): the fields and meaning of v1 `authority` (edit, commands, local_branches, branch_at, apply_to_project, edit_tests,
unconfined_commands; `push` is never granted) plus three lists that matter only when OneCrew decides something: `self_decide` (which of
Q1-Q12 the owner delegates), `granted_actions` (named pre-grants such as `activate_rule:suggest`) and `auto_accept` (empty: O4 is the
owner's, nothing here lets anyone but the owner accept a root). The ceilings are the contract `budget` that the gate already reads.

Q1-Q12 and U1-U4 are constants of this module (00 §2.2/§2.3): the contract cannot add a rank, a class or a table of who may do what.

Where it bites:
  * `child_reason` runs at the gate (gate.require_plan): the sealed authority and paths of a job dispatched under the root must be inside
    the grant. A schema-2/legacy root without an `authority` field behaves as before (no check); a workflow root without one is judged
    by effective() (edit inside scope.owned only).
  * `decide` / `enforce` run when OneCrew itself acts: in authority -> go on, with a HD-05 record (decisions.record); otherwise the
    action is classified U1-U4, nothing is performed, and the record says so. Neither creates a request for the user.
Both tests go through `covers`, the one subset test (the v1 delivery planner shares `within`).
"""
import fnmatch
import json
import math
import re

from ..ledger import LedgerError, canonical, content_hash
from .. import work_contract

Q_IDS = tuple('Q%d' % n for n in range(1, 13))
U_IDS = ('U1', 'U2', 'U3', 'U4')
BOOL_FIELDS = ('edit', 'commands', 'apply_to_project', 'edit_tests', 'unconfined_commands')
FIELDS = BOOL_FIELDS + ('local_branches', 'branch_at', 'granted_actions', 'self_decide', 'auto_accept')
GRANTED_ACTION = re.compile(r'[a-z][a-z0-9_]{0,40}(:[a-z0-9_.-]{1,40})?')
MAX_GRANTED = 20


# ---- path helpers ------------------------------------------------------------------------------------------------------

def within(path, prefixes):
    """Is `path` one of the prefixes or under one (a prefix ending in / is a directory). Moved from delivery_planner (v1 imports it back)."""
    for p in prefixes:
        if p.endswith('/') and path.startswith(p): return True
        if path == p.rstrip('/') or path.startswith(p.rstrip('/') + '/'): return True
    return False


def _fold(text):
    return str(text).replace('\\', '/').casefold()


def _scope_path(value, pattern=False):
    """Canonical relative lexical scope; do not resolve traversal into authority.

    Keep within() unchanged for v1. This validation belongs at the new grant
    boundary, before either prefix or glob comparison. A requested write scope
    is concrete; wildcard grants do not authorize wildcard-shaped requests.
    """
    if not isinstance(value, str) or not value or len(value) > 240:
        raise LedgerError('authority.paths: explicit non-empty relative paths are required.')
    value = value.replace('\\', '/')
    if value.startswith('./'): value = value[2:]
    value = value.rstrip('/')
    if value == '.': return value
    parts = value.split('/')
    if (not value or value.startswith('/') or any(p in ('', '.', '..') or p.endswith((' ', '.')) for p in parts)
            or re.search(r'[<>:"|\x00-\x1f]', value) or (not pattern and any(c in value for c in '*?['))
            or any(re.fullmatch(r'(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\..*)?', p, re.I) for p in parts)):
        raise LedgerError('authority.paths: unsafe or non-concrete relative scope path: ' + value)
    return value.casefold()


def owned_match(path, patterns):
    """The rule the write hook applies to scope.owned (hook_cli.under): exact, directory prefix or glob, case-folded."""
    rel = _scope_path(path)
    for pattern in patterns:
        pattern = _scope_path(pattern, pattern=True)
        if pattern == '.': return True
        if rel == '.':
            if pattern in ('*', '**'): return True
            continue
        if any(c in pattern for c in '*?['):
            if fnmatch.fnmatchcase(rel, pattern) or fnmatch.fnmatchcase(rel + '/', pattern): return True
        elif within(rel, [pattern]):
            return True
    return False


# ---- the grant ---------------------------------------------------------------------------------------------------------

def normalize(raw):
    """The `authority` object of a root contract, normalized, or LedgerError ('authority: ...'). Unknown fields are refused: no rank, no class."""
    if not isinstance(raw, dict) or set(raw) - set(FIELDS) - {'push'}:
        extra = sorted(set(raw) - set(FIELDS) - {'push'}) if isinstance(raw, dict) else []
        raise LedgerError('authority: unknown fields ' + ','.join(map(str, extra)) + '; the grant is ' + ', '.join(FIELDS) + '.' if extra
                          else 'authority: expected an object.')
    v1 = work_contract.normalize_authority({k: v for k, v in raw.items() if k in work_contract.AUTHORITY})
    del v1['push']                                        # never granted; not a field of the root grant
    granted = raw.get('granted_actions', [])
    if not isinstance(granted, list) or len(granted) > MAX_GRANTED or any(not isinstance(g, str) or not GRANTED_ACTION.fullmatch(g) for g in granted):
        raise LedgerError(f'authority.granted_actions: at most {MAX_GRANTED} ids like activate_rule:suggest.')
    decide_list = raw.get('self_decide', [])
    if not isinstance(decide_list, list) or any(q not in Q_IDS for q in decide_list):
        raise LedgerError('authority.self_decide: a list of ' + ', '.join(Q_IDS) + ' (the table is fixed in code).')
    if raw.get('auto_accept', []) != []:
        raise LedgerError('authority.auto_accept: root self-acceptance is not enabled (decision O4 is the owner\'s); the list stays empty.')
    return dict(v1, granted_actions=sorted(set(granted)), self_decide=sorted(set(decide_list), key=Q_IDS.index), auto_accept=[])


def seal(contract):
    """Hash of the grant. The grant is part of the contract file, so the approval's sha covers it; this is the id a decision cites."""
    return content_hash(contract.get('authority') or {})[:16]


def grant_ref(name, contract, revision_sha):
    return {'grant_id': f'{name}:{seal(contract)}', 'revision': revision_sha}


def effective(contract):
    """The grant plus the owned scope, for covers(). A root with no `authority` field delegates nothing (everything goes to the owner as before)."""
    grant = contract.get('authority')
    base = dict(grant) if grant else {k: False for k in BOOL_FIELDS} | {'local_branches': [], 'branch_at': 'pinned_head', 'granted_actions': [],
                                                                         'self_decide': [], 'auto_accept': []}
    if not grant: base['edit'] = True                      # the owner approved scope.owned: that is the write grant a legacy root always had
    base['owned'] = list(contract['scope']['owned'])
    base['declared'] = bool(grant)
    return base


def covers(grant, wanted):
    """[(field, text)] where `wanted` exceeds `grant`; empty means covered. wanted: the bool fields, local_branches (names), branch_at, paths."""
    found = []
    for key in BOOL_FIELDS:
        if wanted.get(key) and not grant.get(key): found.append((key, f'{key} is not granted by the root'))
    names = wanted.get('local_branches')
    if names:
        if not isinstance(names, list) or any(not isinstance(n, str) or not n for n in names):
            found.append(('local_branches', 'explicit branch names are required'))
        else:
            out = sorted(set(names) - set(grant.get('local_branches', [])))
            if out: found.append(('local_branches', 'branch not granted: ' + ', '.join(out)))
            if wanted.get('branch_at', 'pinned_head') != grant.get('branch_at', 'pinned_head'):
                found.append(('branch_at', 'branch_at differs from the root grant'))
    if 'paths' in wanted:
        paths = wanted['paths']
        if not isinstance(paths, list) or not paths:
            found.append(('paths', 'an explicit non-empty write scope is required'))
        else:
            try:
                outside = [p for p in paths if not owned_match(p, grant.get('owned', []))]
                if outside: found.append(('paths', 'outside the owned scope: ' + ', '.join(outside[:5])))
            except LedgerError as exc:
                found.append(('paths', str(exc)))
    return found


# ---- the gate: a dispatched job inside the grant -----------------------------------------------------------------------------

PERMISSION_FIELDS = {'workspace.edit': 'edit', 'candidate.write': 'edit', 'workspace.run': 'commands', 'project.apply': 'apply_to_project',
                     'workspace.apply': 'apply_to_project', 'sandbox.test': 'commands', 'native.test': 'commands', 'android.build': 'commands'}


def child_wanted(task):
    """What the job's sealed task row asks for: its work contract when it has one, else the permissions of its grant."""
    payload = json.loads(task['payload'])
    options = payload.get('owned_execution') or {}
    child = options.get('contract')
    perms = set((payload.get('grant') or {}).get('permissions') or [])
    if child:
        a = child['authority']
        wanted = {k: bool(a.get(k)) for k in BOOL_FIELDS}
        wanted.update(local_branches=list(a.get('local_branches') or []), branch_at=a.get('branch_at', 'pinned_head'))
        if wanted['edit']:
            repo = child['scope'].get('repository') or '.'
            repo = _scope_path(repo)
            paths = child['scope'].get('paths') or ['.']
            if not isinstance(paths, list): raise LedgerError('authority.paths: child paths must be an explicit list.')
            wanted['paths'] = []
            for path in paths:
                path = _scope_path(path or '.')
                wanted['paths'].append('/'.join(p for p in (repo, path) if p != '.') or '.')
        return wanted, perms
    wanted = {field: True for perm, field in PERMISSION_FIELDS.items() if perm in perms}
    # Native recipes carry their sealed owned list in owned_execution.native_change;
    # generic sandbox jobs discover a profile later and have no sealed scope at
    # this admission point. Such a writer cannot borrow an entire root's scope.
    native = options.get('native_change') or {}
    if wanted.get('edit') or wanted.get('apply_to_project'):
        wanted['paths'] = native.get('owned', [])
    if native and 'native.test' in perms:
        wanted['unconfined_commands'] = True  # native trusted-project tests are not OS-contained
        if set(native.get('tests') or []) & set(native.get('owned') or []):
            wanted['edit_tests'] = True
    if 'git.branch' in perms:
        wanted['local_branches'] = [options.get('branch')] if options.get('branch') else []
        wanted['branch_at'] = 'pinned_head'
    return wanted, perms


def child_reason(contract, task, workflow=False):
    """Why the job is not inside the root's grant, or None. A schema-2/legacy root with no `authority` field imposes nothing (legacy);
    a workflow root (`workflow` True: its proposal declared workflow_version) without one is judged by effective(), the same grant
    decide() uses: edit inside scope.owned and no other right (audit W02)."""
    if not contract.get('authority') and not workflow: return None
    grant = effective(contract)
    try:
        wanted, perms = child_wanted(task)
    except (LedgerError, ValueError, KeyError, TypeError, AttributeError) as exc:
        return 'the child authority/scope cannot be validated: ' + str(exc)
    found = covers(grant, wanted)
    if 'git.branch' in perms and not wanted.get('local_branches'):
        found.append(('local_branches', 'the child does not pin an explicit branch name'))
    if 'git.push' in perms: found.append(('push', 'git.push is never granted to a job under a root (U2: publication needs its own decision)'))
    if 'git.branch' in perms and not grant['local_branches'] and not any(f[0] == 'local_branches' for f in found):
        found.append(('local_branches', 'git.branch is not granted by the root'))
    if not found: return None
    return 'the job exceeds the authority granted by the approved plan: ' + '; '.join(f'{field}: {text}' for field, text in found)


# ---- decisions -------------------------------------------------------------------------------------------------------------

class OutOfAuthority(LedgerError):
    """An action of OneCrew outside the grant; `.result` is the classification (U1-U4) that decide() returned. Nothing was performed."""

    def __init__(self, result):
        super().__init__(f"outside the authority granted by the approved plan ({result['class'] or 'not applicable'}): {result['reason']}")
        self.result = result


def _res(ok, cls, kind, reason, q=None, **extra):
    return dict({'in_authority': ok, 'class': cls, 'kind': kind, 'q': q, 'reason': reason}, **extra)


def _over(action, ctx):
    """A ceiling text when the action's cost passes what is left of the root budget, or cannot be checked; else None."""
    cost = action.get('cost') or {}
    if not isinstance(cost, dict) or set(cost) - {'calls', 'seconds'}:
        return 'cost must contain only calls and seconds'
    for key, left in (('calls', 'remaining_calls'), ('seconds', 'remaining_seconds')):
        if cost.get(key) is None: continue
        if type(cost[key]) not in (int, float) or not math.isfinite(cost[key]) or cost[key] < 0:
            return f'the cost in {key} must be a finite non-negative number'
        if ctx.get(left) is None: return f'the cost in {key} cannot be checked against the root ceiling (no {left} given)'
        if type(ctx[left]) not in (int, float) or not math.isfinite(ctx[left]) or ctx[left] < 0:
            return f'the root ceiling {left} is invalid'
        if cost[key] > ctx[left]: return f'needs {cost[key]} {key} but the root has {ctx[left]} left (ceiling)'
    return None


def _write(grant, action, ctx, q=None, field='edit'):
    found = covers(grant, {field: True, 'paths': action.get('paths')})
    over = _over(action, ctx)
    if over: found.append(('budget', over))
    if found: return _res(False, 'U2', action.get('kind'), '; '.join(t for _, t in found), q, findings=[f for f, _ in found])
    return _res(True, None, action.get('kind'), 'inside the granted scope', q)


def _simple_grant(field):
    def check(grant, action, ctx):
        wanted = {field: True}
        if field == 'local_branches': wanted = {'local_branches': [action.get('name')], 'branch_at': action.get('at', 'pinned_head')}
        if field == 'unconfined_commands': wanted = {'commands': True, 'unconfined_commands': bool(action.get('unconfined', True))}
        found = covers(grant, wanted)
        if found: return _res(False, 'U2', action.get('kind'), '; '.join(t for _, t in found), findings=[f for f, _ in found])
        return _res(True, None, action.get('kind'), 'granted')
    return check


def _always(cls, why):
    return lambda grant, action, ctx: _res(False, cls, action.get('kind'), why)


def _spend(grant, action, ctx):
    text = _over({'cost': {'calls': action.get('calls'), 'seconds': action.get('seconds')}}, ctx)
    return _res(False, 'U2', 'spend', text) if text else _res(True, None, 'spend', 'inside the root ceiling')


def _deadline(grant, action, ctx):
    granted, wanted = ctx.get('deadline'), action.get('new_deadline')
    if granted is None or wanted is None or wanted > granted:        # ISO UTC strings of one format order like times
        return _res(False, 'U2', 'deadline', f'the deadline {wanted} is later than the granted {granted} (a deadline already granted is not moved back)')
    return _res(True, None, 'deadline', 'not later than the granted deadline')


def _model(grant, action, ctx):
    return _res(True, None, 'model', 'pinned model') if action.get('pinned') else _res(False, 'U2', 'model', 'the model is not pinned by the owner')


def _preference(grant, action, ctx):
    return (_res(True, None, 'preference', 'a technical choice with a default in policy') if action.get('has_policy_default')
            else _res(False, 'U3', 'preference', 'a preference or business choice nobody delegated and policy has no default for'))


def _support_install(grant, action, ctx):
    """2.4-S2: installing a OneCrew hotfix at a declared target. Only a grant that names support_install:<target> allows it (a project edit grant,
    a report or a log line never does), and only with budget left on the root that grants it."""
    wanted = 'support_install:' + str(action.get('target'))
    if wanted not in grant.get('granted_actions', []):
        return _res(False, 'U2', 'support_install', f'the grant does not name {wanted} (an edit or command grant does not allow a OneCrew install)')
    if ctx.get('remaining_calls') is not None and ctx['remaining_calls'] <= 0:
        return _res(False, 'U2', 'support_install', 'the root budget is exhausted (no calls left)')
    over = _over(action, ctx)
    if over: return _res(False, 'U2', 'support_install', 'budget: ' + over)
    return _res(True, None, 'support_install', 'the grant names this install target, inside the root budget')


_HANDLERS = {
    'write': lambda grant, action, ctx: _write(grant, action, ctx),
    'test_edit': lambda grant, action, ctx: (_write(grant, action, ctx, field='edit_tests') if grant.get('edit') else
                                              _res(False, 'U2', 'test_edit', 'edit is not granted')),
    'command': _simple_grant('commands'), 'unconfined_command': _simple_grant('unconfined_commands'),
    'branch': _simple_grant('local_branches'), 'apply': _simple_grant('apply_to_project'),
    'push': _always('U2', 'publication (push/tag/deploy) is never granted to OneCrew'),
    'tag': _always('U2', 'publication (push/tag/deploy) is never granted to OneCrew'),
    'deploy': _always('U2', 'publication (push/tag/deploy) is never granted to OneCrew'),
    'spend': _spend, 'deadline': _deadline, 'model': _model,
    'change_acceptance': _always('U1', 'it changes the goal, the acceptance or a settled constraint (HD-04)'),
    'accept_root': _always('U4', 'accepting the root is the owner\'s (invariant 6)'),
    'approve_root': _always('U4', 'approving the root is the owner\'s'),
    'owner_manual': _always('U4', 'the contract names an action only the owner can do'),
    'device_install': _always('U4', 'installing on a real device is the owner\'s'),
    'preference': _preference,
    'support_install': _support_install,
}


def _q_check(grant, action, ctx, q):
    """The condition of each row of 00 §2.2. Returns (ok, class, reason)."""
    over = _over(action, ctx)
    if q == 'Q1':
        if action.get('acceptance_changed'): return False, 'U1', 'splitting must not change the acceptance (HD-04)'
        return (False, 'U2', over) if over else (True, None, 'a split inside the root ceilings')
    if q == 'Q2':
        return (True, None, 'every dependency is in its declared state') if action.get('eligible') else (False, None, 'the node is not eligible to run')
    if q == 'Q3':
        found = covers(grant, {'edit': True, 'paths': action['paths']}) if 'paths' in action else []
        return (False, 'U2', '; '.join(t for _, t in found)) if found else (True, None, 'inside the read/write scope of the task')
    if q == 'Q4':
        if action.get('weakens'): return False, 'U1', 'a weaker check is a change of acceptance (HD-04)'
        if not action.get('provenance'): return False, 'U1', 'a change to the checks without provenance cannot be told from weakening (HD-39)'
        if not isinstance(action.get('cost'), dict) or not action['cost']:
            return False, 'U2', 'test work needs an explicit cost to check the root ceiling'
        if over: return False, 'U2', over
        operation = action.get('operation', 'edit')
        if operation not in ('edit', 'run'):
            return False, 'U2', 'Q4 must name test edit or test run'
        wanted = {'commands': True} if operation == 'run' else {'edit': True, 'edit_tests': True, 'paths': action.get('paths')}
        if operation == 'run' and action.get('unconfined'):
            wanted['unconfined_commands'] = True
        found = covers(grant, wanted)
        if found: return False, 'U2', '; '.join(t for _, t in found)
        return True, None, 'checks prepared for the existing acceptance, with provenance'
    if q == 'Q5':
        if action.get('repairs_max') is not None and action.get('repairs_used', 0) >= action['repairs_max']:
            return False, 'U2', 'the repair ceiling is reached'
        return (False, 'U2', over) if over else (True, None, 'a repair inside the ceilings')
    if q == 'Q6':
        return (False, 'U4', 'a mandatory gate is never skipped (HD-21)') if action.get('mandatory') else (True, None, 'an optional review level')
    if q == 'Q7':
        if action.get('pinned'): return False, 'U2', 'the role is pinned: no fallback'
        if not (action.get('configured') and action.get('within_limit')): return False, 'U2', 'the fallback is not configured or past its limit'
        return True, None, 'a configured fallback inside its limit'
    if q == 'Q8': return True, None, 'hold limited to the affected scope'
    if q == 'Q9':
        if action.get('evidence') and action.get('artifact_matches'): return True, None, 'receipts bound to the artifact and revision'
        return False, None, 'no evidence bound to this artifact and revision'
    if q == 'Q10': return True, None, 'an outcome or a proposal; a proposal changes nothing'
    if q == 'Q11':
        kind = action.get('rule_kind')
        if kind and 'activate_rule:' + str(kind) in grant.get('granted_actions', []): return True, None, 'the grant names this rule kind'
        return False, 'U2', 'the grant does not name activate_rule:' + str(kind)
    if q == 'Q12':
        return (True, None, 'internal acceptance of a verified child (not the root)') if action.get('node_state') == 'verified' else (False, None, 'the child is not verified')
    return False, 'U3', 'unknown decision ' + str(q)


def decide(contract, action, ctx=None):
    """The authority decision for one action of OneCrew: {in_authority, class (U1-U4 or None), kind, q, reason}. Pure: it reads the contract and
    the context (remaining_calls, remaining_seconds, deadline) it is given and writes nothing; enforce() records it."""
    ctx = ctx or {}
    grant = effective(contract)
    kind = action.get('kind')
    if kind == 'decision':
        q = action.get('q')
        if q not in Q_IDS: return _res(False, 'U3', kind, 'unknown decision ' + str(q), q)
        if q not in grant['self_decide']:
            return _res(False, 'U3', kind, f'{q} is not delegated to OneCrew by this root (self_decide)', q,
                        nodes=list(action.get('nodes') or []))       # the record's scope names the nodes it is about (round 8 G)
        ok, cls, reason = _q_check(grant, action, ctx, q)
        return _res(ok, cls, kind, reason, q, nodes=list(action.get('nodes') or []))
    handler = _HANDLERS.get(kind)
    if handler is None: return _res(False, 'U3', kind, f'action {kind!r} is not in the table; nothing delegates it')
    result = handler(grant, action, ctx)
    result.setdefault('nodes', list(action.get('nodes') or []))
    return result


def record(ledger, task_id, contract, action, result, *, name, revision_sha, component='onecrew.authority', key=None):
    """The HD-05 record of one decision: who (component; a rule, no model), on what grant and revision, with which evidence, for which scope."""
    from . import decisions
    try:
        summary = canonical(action)[:500]
    except (TypeError, ValueError):
        # Keep a refusal record even for non-finite/malformed requested costs.
        # This string is evidence only and is never parsed back into an action.
        summary = ('non-JSON action: ' + repr(action))[:500]
    scope = ','.join(result.get('nodes') or []) or str(result.get('kind'))
    basis = f"{result.get('q') or result.get('kind')}: {result['reason']}"
    decision = decisions.record(ledger, task_id, subject={'component': component, 'model': 'rule'}, authority=grant_ref(name, contract, revision_sha),
                                evidence=[{'action': summary}, {'grant': seal(contract), 'contract_revision': revision_sha}],
                                basis=basis, scope=scope,
                                validity={'outcome': 'in_authority' if result['in_authority'] else 'out_of_authority', 'class': result['class'],
                                          'contract_revision': revision_sha}, key=key)
    _remember(ledger, task_id, name, basis, scope, result)
    return decision


def _remember(ledger, task_id, name, basis, scope, result):
    """W48a: a decision is one of the four significant changes, so the context gets one entry (deduplicated by content), sourced by the
    decision event itself. Written by code, no model. A context failure never undoes the decision record (context is data, not authority)."""
    from . import context
    from ..ledger import LedgerError
    with ledger.transaction() as conn:
        row = conn.execute("SELECT max(seq) AS seq FROM events WHERE task_id=? AND kind='decision.recorded'", (task_id,)).fetchone()
    if not row or row['seq'] is None: return
    outcome = 'in authority' if result['in_authority'] else f"out of authority ({result.get('class') or 'held'})"
    text = f'Decision on {scope}: {basis} — {outcome}.'[:600]
    with ledger.transaction() as conn:
        # the same decision taken again (a new decision event, same subject) is one entry: deduplicated by subject, not by source
        if conn.execute("SELECT 1 FROM events WHERE task_id=? AND kind='context.entry' AND json_extract(payload,'$.kind')='decision' AND json_extract(payload,'$.text')=?",
                        (task_id, text)).fetchone():
            return
    try:
        context.observe(ledger, name, {'type': 'decision', 'text': text, 'source': {'type': 'event', 'id': row['seq']}})
    except LedgerError:
        pass


def enforce(ledger, task_id, contract, action, *, name, revision_sha, ctx=None, perform=None, component='onecrew.authority', key=None):
    """decide, record, and only then perform (when in authority). Out of authority: nothing runs, the grant is untouched, no request is made."""
    result = decide(contract, action, ctx)
    record(ledger, task_id, contract, action, result, name=name, revision_sha=revision_sha, component=component, key=key)
    done = perform() if (result['in_authority'] and perform is not None) else None
    return result, done
