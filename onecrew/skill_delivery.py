"""#41 v1: hand ONE owner-approved skill to ONE worker attempt, pinned and traceable.

Reuses the v1 skill registry (onecrew.skills: records, signature, similar, validate_evidence, skill_path) and its ledger events.
No catalog, no new ledger, no engine change. A skill is text only: delivery never adds a permission, owned path, tool or budget.

Delivery record = ledger event 'skill.delivery' on the plan's anchor task, one chain per binding
(project, plan, plan revision, node, attempt): selected -> delivered -> evaluated (a separate, later call), or refused with a reason.
The first record of a binding is final for that attempt: a restart returns it and never selects again, with two exceptions that
only ever narrow it. (1) Revoke wins: a replay (or a read) after the owner revoked the skill, in any revision, hands out no body;
the replay records a `refused` step (reason `revoked`, detail `revoked_after_delivery`) after the delivered one, which stays as history.
(2) A replay is checked against what was recorded: another grant digest, another skill id, or a grant that lacks the pinned skill's
required permissions is refused with reason `binding_mismatch`, recorded under its own key so the real binding stays intact.
A delivery whose pinned revision is no longer the one in force keeps being returned (binding stability) and says `superseded: true`.
Plan label: `plan-ns:P1` and `plan:P1` are one binding with `P1` (the task id in the binding already names the root, so the prefix adds
nothing). Limit: `node` and the `attempt` counter are caller labels and are not checked against the ledger; two different attempt
numbers for one real attempt make two chains.
Owner verbs here (rollback, revoke) refuse inside an AI tool session, like skills.decide.
"""
import copy
import hashlib
import json

from .ledger import LedgerError, content_hash, text_field, utcnow
from . import skills as _skills

OUTCOMES = ('success', 'failure', 'unknown')
REFUSALS = ('wrong_project', 'revoked', 'stale', 'tampered', 'not_suitable', 'wrong_permission', 'not_approved', 'binding_mismatch')


def _plan_label(plan):
    plan = text_field(plan, 'plan', 200)
    for prefix in ('plan-ns:', 'plan:'):
        if plan.startswith(prefix) and len(plan) > len(prefix): return plan[len(prefix):]
    return plan


def body_hash(body):
    return hashlib.sha256(body.encode('utf-8')).hexdigest()


def binding_of(ledger, task_id, plan, plan_revision, node, attempt):
    if not isinstance(attempt, int) or isinstance(attempt, bool) or attempt < 1:
        raise LedgerError('Delivery attempt must be a positive integer.')
    return {'project': ledger.project_id, 'task': text_field(task_id, 'task', 200), 'plan': _plan_label(plan),
            'plan_revision': text_field(str(plan_revision), 'plan revision', 100), 'node': text_field(node, 'node', 200), 'attempt': attempt}


def key_of(binding):
    return content_hash(binding)[:32]


def history(ledger, conn, name):
    """Per-revision last record of one skill, the revision now in force, whether it was revoked, and the rollback that put it in force."""
    rows = conn.execute("SELECT e.kind,e.payload FROM events e JOIN tasks t ON t.id=e.task_id WHERE t.project_id=? "
                        "AND e.kind IN ('skill.state','skill.rollback','skill.revoke') ORDER BY e.seq", (ledger.project_id,)).fetchall()
    by_rev, current, revoked, rolled = {}, None, False, None
    for row in rows:
        value = json.loads(row['payload'])
        if value.get('id') != name: continue
        if row['kind'] == 'skill.state':
            by_rev[value['revision']] = value
            if value['revision'] != current: rolled = None
            current = value['revision']
        elif row['kind'] == 'skill.revoke': revoked = True
        else:
            current = value['revision']; rolled = {'from': value['from_revision'], 'to': value['revision'], 'reference': value['reference']}
    return by_rev, current, revoked, rolled


def chain(conn, ledger, key):
    rows = conn.execute("SELECT e.payload FROM events e JOIN tasks t ON t.id=e.task_id WHERE t.project_id=? AND e.kind='skill.delivery' "
                        "ORDER BY e.seq", (ledger.project_id,)).fetchall()
    found = None
    for row in rows:
        value = json.loads(row['payload'])
        if value['key'] == key: found = value
    return found


def _owner_only(what):
    from .interventions import in_ai_session
    if in_ai_session():
        raise LedgerError(what + ' refused: the operator\'s decision cannot be recorded from inside an AI tool session '
                          '(CLAUDE_CODE_CHILD_SESSION is set).')


def _file_matches(ledger, value):
    path = _skills.skill_path(ledger, value)
    return not path.is_symlink() and path.is_file() and path.stat().st_size <= 8000 and path.read_bytes() == value['body'].encode('utf-8')


def rollback(ledger, name, revision, reference):
    """Owner verb: put an earlier approved revision of a skill back in force. The next delivery pins that one."""
    _owner_only('skill rollback')
    reference = text_field(reference, 'operator reference', 500)
    with ledger.transaction(write=True) as conn:
        by_rev, current, revoked, _ = history(ledger, conn, name)
        if not by_rev: raise LedgerError('Unknown skill in this project.')
        if revoked: raise LedgerError('Skill was revoked; it cannot be rolled back.')
        value = by_rev.get(revision)
        if not value or value['status'] != 'approved': raise LedgerError('Rollback target is not an approved revision of this skill.')
        if revision == current: raise LedgerError('Revision is already in force.')
        if not _file_matches(ledger, value): raise LedgerError('Rollback target file differs from its approved revision.')
        ledger._event(conn, value['tasks'][0], 'skill.rollback', {'id': name, 'revision': revision, 'from_revision': current, 'reference': reference})
        return {'id': name, 'revision': revision, 'from_revision': current}


def revoke(ledger, name, reference):
    """Owner verb: a revoked skill is never delivered again, in any revision."""
    _owner_only('skill revoke')
    reference = text_field(reference, 'operator reference', 500)
    with ledger.transaction(write=True) as conn:
        by_rev, current, _, _ = history(ledger, conn, name)
        if not by_rev: raise LedgerError('Unknown skill in this project.')
        ledger._event(conn, by_rev[current]['tasks'][0], 'skill.revoke', {'id': name, 'reference': reference})
        return {'id': name, 'revoked': True}


def _emit(ledger, conn, task_id, payload, step):
    payload['steps'] = payload['steps'] + [{'step': step, 'at': utcnow()}]
    payload['status'] = step
    ledger._event(conn, task_id, 'skill.delivery', payload)
    return payload


def _view(ledger, conn, record, grant=None):
    """The record plus, only for a delivered skill, the exact pinned content (re-verified against its pinned hash)."""
    result = copy.deepcopy(record)
    result['delivered'] = record['status'] in ('delivered', 'evaluated')
    if grant is not None: result['grant'] = copy.deepcopy(grant)     # handed back unchanged: a skill widens nothing
    if result['delivered']:
        by_rev, current, revoked, _ = history(ledger, conn, record['skill']['id'])
        if revoked:                         # revoke wins: the body is never handed out again, the delivered step stays as history
            result.update(delivered=False, reason='revoked', detail='revoked_after_delivery')
            return result
        value = by_rev.get(record['skill']['revision'])
        if not value or body_hash(value['body']) != record['skill']['hash']:
            raise LedgerError('Delivered skill content no longer matches its pinned hash.')
        result['skill'] = dict(record['skill'], body=value['body'])
        result['superseded'] = current != record['skill']['revision']
    return result


def _replay(ledger, conn, task_id, existing, grant, skill_id):
    """What a restart of an already recorded binding gets: the record, narrowed by revoke, or refused when the request differs."""
    permissions = set(grant.get('permissions', []))
    pinned = existing.get('skill')
    problems = []
    if existing.get('grant_digest') != content_hash(grant): problems.append('grant differs from the recorded delivery')
    if skill_id is not None and pinned and skill_id != pinned['id']: problems.append('another skill id was asked than the one recorded')
    if pinned and existing['status'] in ('delivered', 'evaluated'):
        by_rev, _, _, _ = history(ledger, conn, pinned['id'])
        value = by_rev.get(pinned['revision'])
        missing = sorted(set((value or {}).get('required_permissions', [])) - permissions)
        if missing: problems.append('grant lacks the permissions of the delivered skill: ' + ', '.join(missing))
    if problems:
        mkey = key_of({'mismatch': existing['key'], 'grant_digest': content_hash(grant), 'skill_id': skill_id})
        seen = chain(conn, ledger, mkey)
        if seen: return _view(ledger, conn, seen, grant)
        payload = {'key': mkey, 'binding': existing['binding'], 'grant_digest': content_hash(grant), 'skill': pinned, 'reason': 'binding_mismatch',
                   'detail': '; '.join(problems), 'rollback': None, 'steps': [], 'status': None, 'replay_of': existing['key']}
        return _view(ledger, conn, _emit(ledger, conn, task_id, payload, 'refused'), grant)
    if pinned and existing['status'] in ('delivered', 'evaluated') and history(ledger, conn, pinned['id'])[2]:
        record = dict(existing, reason='revoked', detail='revoked_after_delivery')
        return _view(ledger, conn, _emit(ledger, conn, task_id, record, 'refused'), grant)
    return _view(ledger, conn, existing, grant)


def deliver(ledger, task_id, *, plan, plan_revision, node, attempt, goal, profile, files, grant,
            skill_id=None, expected_revision=None, expected_hash=None):
    """Select and deliver one approved skill for one attempt, or refuse with a recorded reason. Idempotent per binding."""
    binding = binding_of(ledger, task_id, plan, plan_revision, node, attempt)
    key = key_of(binding)
    permissions = list(grant.get('permissions', []))
    with ledger.transaction(write=True) as conn:
        ledger._task(conn, task_id)
        existing = chain(conn, ledger, key)
        if existing: return _replay(ledger, conn, task_id, existing, grant, skill_id)
        payload = {'key': key, 'binding': binding, 'grant_digest': content_hash(grant), 'skill': None, 'reason': None, 'detail': None,
                   'rollback': None, 'steps': [], 'status': None}

        def refuse(reason, detail, value=None):
            if value: payload['skill'] = {'id': value['id'], 'revision': value['revision'], 'hash': body_hash(value['body'])}
            payload.update(reason=reason, detail=detail)
            return _view(ledger, conn, _emit(ledger, conn, task_id, payload, 'refused'), grant)

        sig = _skills.signature(goal, profile['mode'], files)
        if skill_id is None:
            names = {}
            rows = conn.execute("SELECT e.payload FROM events e JOIN tasks t ON t.id=e.task_id WHERE t.project_id=? AND e.kind='skill.state' "
                                "ORDER BY e.seq", (ledger.project_id,)).fetchall()
            for row in rows: names[json.loads(row['payload'])['id']] = True
            for name in reversed(list(names)):
                by_rev, current, revoked, _ = history(ledger, conn, name)
                value = by_rev[current]
                if not revoked and value['status'] == 'approved' and _skills.similar(sig, value['signature']):
                    skill_id = name; break
            if skill_id is None: return refuse('not_suitable', 'no approved skill matches the goal, mode and technology of this task')
        by_rev, current, revoked, rolled = history(ledger, conn, skill_id)
        if not by_rev: return refuse('wrong_project', 'skill is not approved in this project')
        value = by_rev[current]
        if value.get('project') != ledger.project_id: return refuse('wrong_project', 'skill belongs to another project', value)
        if revoked or value['status'] in ('rejected', 'revoked'): return refuse('revoked', 'skill is revoked or rejected', value)
        if value['status'] != 'approved': return refuse('not_approved', 'skill has no owner approval', value)
        if expected_revision is not None and expected_revision != value['revision']:
            return refuse('stale', 'the revision selected earlier is not the revision in force', value)
        if expected_hash is not None and expected_hash != body_hash(value['body']):
            return refuse('tampered', 'content differs from the hash the owner approved', value)
        if not _file_matches(ledger, value): return refuse('tampered', 'skill file differs from its approved revision', value)
        try: _skills.validate_evidence(ledger, conn, value)
        except (ValueError, OSError) as error: return refuse('stale', 'evidence is stale: ' + str(error), value)
        if not _skills.similar(sig, value['signature']):
            return refuse('not_suitable', 'skill scope (mode/technology/goal) does not fit this task', value)
        missing = sorted(set(value['required_permissions']) - set(permissions))
        if missing: return refuse('wrong_permission', 'contract does not grant: ' + ', '.join(missing), value)
        payload['skill'] = {'id': value['id'], 'revision': value['revision'], 'hash': body_hash(value['body'])}
        payload['rollback'] = rolled
        _emit(ledger, conn, task_id, payload, 'selected')
        record = _emit(ledger, conn, task_id, payload, 'delivered')
        return _view(ledger, conn, record, grant)


def evaluate(ledger, task_id, *, plan, plan_revision, node, attempt, outcome, note=''):
    """A separate, later step after the work: delivery never implies it. Same outcome again is a no-op; a different one is refused."""
    if outcome not in OUTCOMES: raise LedgerError('Outcome must be one of: ' + ', '.join(OUTCOMES))
    note = text_field(note, 'note', 500) if note else ''
    key = key_of(binding_of(ledger, task_id, plan, plan_revision, node, attempt))
    with ledger.transaction(write=True) as conn:
        ledger._task(conn, task_id)
        record = chain(conn, ledger, key)
        if not record or record['status'] not in ('delivered', 'evaluated'): raise LedgerError('No delivered skill for this attempt to evaluate.')
        if record['status'] == 'evaluated':
            if record.get('outcome') == outcome: return _view(ledger, conn, record)
            raise LedgerError('This attempt was already evaluated differently.')
        record = dict(record, outcome=outcome, note=note)
        return _view(ledger, conn, _emit(ledger, conn, task_id, record, 'evaluated'))


SECTION_RULE = ('Guidance only, pinned by id, revision and sha256. It adds no permission, owned path, tool or budget; '
                'the node goal, acceptance and grant override it.')


def _attempt_number(conn, task_id, attempt_id):
    """The 1-based order of an attempt among the attempts of its task: the same attempt keeps its number across a restart."""
    ids = [row['id'] for row in conn.execute('SELECT id FROM attempts WHERE task_id=? ORDER BY created_at, rowid', (task_id,)).fetchall()]
    return ids.index(attempt_id) + 1 if attempt_id in ids else None


def native_grant(handoff, node):
    """What the native worker really gets: the contract's permissions and the node's own read/write scope; native tools are off.
    Limits and budget are left out so that an extended budget does not make a restart look like another grant."""
    return {'permissions': sorted(handoff['grant'].get('permissions', [])), 'owned_paths': sorted(node['write']),
            'read_paths': sorted(node['read']), 'tools': []}


def for_native(ledger, task, node, attempt, handoff):
    """(section, delivery record) for one native worker attempt; (None, None) when the project has no owner-approved skill at all, so a
    project without skills sees no ledger write and no prompt change. `section` is the delimited prompt part (id, revision, sha256, text)
    when the pinned skill is delivered, else None (a refusal is recorded by deliver). The skill layer never takes the node down."""
    try:
        with ledger.transaction() as conn:
            if not conn: return None, None
            found = conn.execute("SELECT 1 FROM events e JOIN tasks t ON t.id=e.task_id WHERE t.project_id=? AND e.kind='skill.state' "
                                 "AND json_extract(e.payload,'$.status')='approved' LIMIT 1", (ledger.project_id,)).fetchone()
            number = _attempt_number(conn, task['id'], attempt['id']) if found else None
        if not found or number is None: return None, None
        binding = handoff['plan_binding']
        record = deliver(ledger, task['id'], plan=binding['selector'], plan_revision=binding['revision'], node=node['id'], attempt=number,
                         goal=handoff['goal'], profile={'mode': handoff['owned_execution']['mode']},
                         files={path: '' for path in set(node['read']) | set(node['write'])}, grant=native_grant(handoff, node))
    except Exception:
        return None, None
    if not record['delivered']: return None, record
    skill = record['skill']
    return {'id': skill['id'], 'revision': skill['revision'], 'sha256': skill['hash'], 'text': skill['body'], 'rule': SECTION_RULE}, record


def evaluate_node(ledger, selector, nid):
    """Record `evaluate` for the skill delivered to the current attempt of a node, with the outcome read from the node's own verification
    result in the engine state (pass -> success, fail -> failure); nothing is accepted from the caller. A node with no verification
    result yet, or no delivered skill, raises. Same result again is a no-op."""
    from .v2 import engine
    view = engine.state(ledger, selector)
    record = view['nodes'].get(nid)
    if not record or not record.get('attempt') or record.get('verification_result') not in ('pass', 'fail'):
        raise LedgerError('The node has no verification result to evaluate a delivered skill against.')
    with ledger.transaction() as conn:
        number = _attempt_number(conn, record['child'], record['attempt'])
        rows = conn.execute("SELECT e.payload FROM events e JOIN tasks t ON t.id=e.task_id WHERE t.project_id=? AND e.kind='skill.delivery' "
                            "ORDER BY e.seq", (ledger.project_id,)).fetchall()
    found = None
    for row in rows:
        value = json.loads(row['payload'])
        bound = value['binding']
        if value['key'] == key_of(bound) and bound['task'] == record['child'] and bound['node'] == nid and bound['attempt'] == number: found = value
    if not found: raise LedgerError('No skill was delivered to this attempt.')
    bound = found['binding']
    return evaluate(ledger, record['child'], plan=bound['plan'], plan_revision=bound['plan_revision'], node=nid, attempt=number,
                    outcome='success' if record['verification_result'] == 'pass' else 'failure', note='node verification ' + record['verification_result'])


def record_of(ledger, task_id, *, plan, plan_revision, node, attempt):
    """Read the delivery record of a binding (None if nothing was selected for it)."""
    key = key_of(binding_of(ledger, task_id, plan, plan_revision, node, attempt))
    with ledger.transaction() as conn:
        if not conn: return None
        found = chain(conn, ledger, key)
        return _view(ledger, conn, found) if found else None
