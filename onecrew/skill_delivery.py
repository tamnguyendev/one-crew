"""#41 v1: hand ONE owner-approved skill to ONE worker attempt, pinned and traceable.

Reuses the v1 skill registry (onecrew.skills: records, signature, similar, validate_evidence, skill_path) and its ledger events.
No catalog, no new ledger, no engine change. A skill is text only: delivery never adds a permission, owned path, tool or budget.

Delivery record = ledger event 'skill.delivery' on the plan's anchor task, one chain per binding
(project, plan, plan revision, node, attempt): selected -> delivered -> evaluated (a separate, later call), or refused with a reason.
The first record of a binding is final for that attempt: a restart returns it and never selects again.
Owner verbs here (rollback, revoke) refuse inside an AI tool session, like skills.decide.
"""
import copy
import hashlib
import json

from .ledger import LedgerError, content_hash, text_field, utcnow
from . import skills as _skills

OUTCOMES = ('success', 'failure', 'unknown')
REFUSALS = ('wrong_project', 'revoked', 'stale', 'tampered', 'not_suitable', 'wrong_permission', 'not_approved')


def body_hash(body):
    return hashlib.sha256(body.encode('utf-8')).hexdigest()


def binding_of(ledger, task_id, plan, plan_revision, node, attempt):
    if not isinstance(attempt, int) or isinstance(attempt, bool) or attempt < 1:
        raise LedgerError('Delivery attempt must be a positive integer.')
    return {'project': ledger.project_id, 'task': text_field(task_id, 'task', 200), 'plan': text_field(plan, 'plan', 200),
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
        by_rev, _, _, _ = history(ledger, conn, record['skill']['id'])
        value = by_rev.get(record['skill']['revision'])
        if not value or body_hash(value['body']) != record['skill']['hash']:
            raise LedgerError('Delivered skill content no longer matches its pinned hash.')
        result['skill'] = dict(record['skill'], body=value['body'])
    return result


def deliver(ledger, task_id, *, plan, plan_revision, node, attempt, goal, profile, files, grant,
            skill_id=None, expected_revision=None, expected_hash=None):
    """Select and deliver one approved skill for one attempt, or refuse with a recorded reason. Idempotent per binding."""
    binding = binding_of(ledger, task_id, plan, plan_revision, node, attempt)
    key = key_of(binding)
    permissions = list(grant.get('permissions', []))
    with ledger.transaction(write=True) as conn:
        ledger._task(conn, task_id)
        existing = chain(conn, ledger, key)
        if existing: return _view(ledger, conn, existing, grant)
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


def record_of(ledger, task_id, *, plan, plan_revision, node, attempt):
    """Read the delivery record of a binding (None if nothing was selected for it)."""
    key = key_of(binding_of(ledger, task_id, plan, plan_revision, node, attempt))
    with ledger.transaction() as conn:
        if not conn: return None
        found = chain(conn, ledger, key)
        return _view(ledger, conn, found) if found else None
