"""W03 — the decision record (R00).

A decision written to the ledger carries a REAL subject (the component and model that made it), the authority it rests on
(a grant id and the revision that granted it), the evidence it is based on (non-empty), its scope and its validity. An AI
session can never sign a decision as the owner: `by=owner` from inside an AI tool session is refused and nothing is written,
exactly as plan.approve/accept are (ownership.refuse_in_ai_session, the CLAUDE_CODE_CHILD_SESSION marker). An AI writes under
its own actor. From an AI session the subject may not be the owner/human either, and on a plan root the authority must be the root's
approved grant (resolve_grant); a task that is not a plan root has no grant model to resolve against.

`decision.recorded` is a class-A (neutral) event in the compatibility ledger (00 §6.1): the old version does not read it, its
S/G/C are unchanged, so it is safe to write on a `plan:` anchor. This module is in the wheel; it imports only shipped modules
(ledger, ownership, interventions), so the core-closure check of test_g1_core stays satisfied.
"""
from ..ledger import LedgerError, canonical, utcnow
from .ownership import in_ai_session, refuse_in_ai_session

OWNER_ACTORS = ('user', 'owner')
KIND = 'decision.recorded'
MAX_EVIDENCE = 64
MAX_JSON = 8000


def _subject(subject):
    if not isinstance(subject, dict):
        raise LedgerError('decision subject: expected an object with a component and a model.')
    component, model = subject.get('component'), subject.get('model')
    if not (isinstance(component, str) and component.strip()):
        raise LedgerError('decision subject.component: who made the decision (a component name), non-empty.')
    if not (isinstance(model, str) and model.strip()):
        raise LedgerError('decision subject.model: the model that made the decision (or "human" for the owner), non-empty.')
    return {'component': component, 'model': model}


def _authority(authority):
    if not isinstance(authority, dict):
        raise LedgerError('decision authority: expected {grant_id, revision} — the grant this decision rests on.')
    grant_id, revision = authority.get('grant_id'), authority.get('revision')
    if not (isinstance(grant_id, str) and grant_id.strip()):
        raise LedgerError('decision authority.grant_id: the id of the authority grant, non-empty.')
    if not (isinstance(revision, str) and revision.strip()):
        raise LedgerError('decision authority.revision: the revision that granted it, non-empty.')
    return {'grant_id': grant_id, 'revision': revision}


def owner_subject(subject):
    """W03: a subject that claims the owner (component owner/user, or model human)."""
    from ..interventions import owner_claim
    return owner_claim(subject.get('component')) or str(subject.get('model', '')).strip().casefold() == 'human'


def resolve_grant(ledger, task_id, authority):
    """W03/W30a: does `authority` {grant_id, revision} name the APPROVED grant of the plan root `task_id`?
    Returns (resolved, reason, contract): resolved None when the task is not a plan root (no grant model to resolve against);
    True when it is the approved revision's grant (authority.grant_ref, or the review-policy form approved-contract:<sha>); else False."""
    from . import authority as grants, namespaces, plan as plans
    with ledger.transaction() as conn:
        row = conn.execute('SELECT request_key FROM tasks WHERE id=?', (task_id,)).fetchone() if conn is not None else None
        key = row['request_key'] if row else ''
        if not key.startswith((namespaces.LEGACY, namespaces.NAMESPACED)): return None, 'not a plan root', None
        state = plans.derive(ledger, conn, key)
    approved = state and state['approved']
    if not approved: return False, f'plan {state["name"] if state else key} has no approved grant yet', None
    contract, _ = plans.load(ledger, state, approved['revision'])
    known = [grants.grant_ref(state['selector'], contract, approved['sha']),
             {'grant_id': 'approved-contract:' + approved['sha'], 'revision': str(approved['revision'])}]
    if {'grant_id': authority.get('grant_id'), 'revision': authority.get('revision')} not in known:
        return False, (f'grant {authority.get("grant_id")}@{authority.get("revision")} is not the approved grant of plan {state["name"]} '
                       f'({known[0]["grant_id"]}@{known[0]["revision"][:12]})'), contract
    return True, 'the approved grant of the root', contract


def _evidence(evidence):
    if not isinstance(evidence, list) or not evidence:
        raise LedgerError('decision evidence: a non-empty list of evidence references.')
    if len(evidence) > MAX_EVIDENCE:
        raise LedgerError(f'decision evidence: at most {MAX_EVIDENCE} references.')
    return evidence


def _actor(by):
    """The actor to record. `by='owner'` is only reached after refuse_in_ai_session has passed, so it means an owner terminal.
    Otherwise the AI session's own declared actor (ONECREW_ACTOR via interventions.actor), never 'owner' from an AI session."""
    if by == 'owner':
        return 'owner'
    from ..interventions import actor as resolve
    who = resolve()
    return 'unknown' if who in OWNER_ACTORS and in_ai_session() else who


def record(ledger, task_id, *, subject, authority, evidence, basis, scope=None, validity=None, by=None, key=None, conn=None):
    """Append one `decision.recorded` event. Refuses `by=owner` from an AI session (writes nothing). Returns the stored payload.
    `conn`: an OPEN write transaction of `ledger` - the caller's validation and this write then commit together (one transaction), the
    rule every entry route follows since the round-5 atomicity fix; without it the record opens its own write transaction."""
    if by not in (None, 'owner'):
        raise LedgerError('decision by: only "owner" (the owner, from their own terminal) or omitted (the AI writes under its own name).')
    if by == 'owner':
        refuse_in_ai_session('recording a decision as the owner')   # C11: refuses inside an AI tool session, before any write
    subject, authority, evidence = _subject(subject), _authority(authority), _evidence(evidence)
    if owner_subject(subject):                                   # W03: the subject is evidence of who decided; an AI cannot name the owner
        refuse_in_ai_session('recording a decision with the owner/human as its subject')
    if not (isinstance(basis, str) and basis.strip()):
        raise LedgerError('decision basis: why the decision was made (the reasoning), non-empty.')
    if in_ai_session():                                          # W03: an AI session cites only the root's real approved grant
        resolved, why, _ = resolve_grant(ledger, task_id, authority)
        if resolved is False: raise LedgerError(f'decision refused: {why}; an AI tool session records a decision only on the approved grant it rests on.')
    payload = {'actor': _actor(by), 'subject': subject, 'authority': authority, 'evidence': evidence,
               'basis': basis.strip()[:2000], 'scope': (scope or None) and str(scope)[:500],
               'validity': validity if isinstance(validity, (dict, str)) else None}
    if key is not None:
        from ..ledger import key_field
        key_field(key)
        payload['key'] = key
    if len(canonical(payload)) > MAX_JSON:
        raise LedgerError('decision record is too large; trim the evidence or basis.')
    def write(conn):
        ledger._task(conn, task_id)
        if key is not None:
            import json
            old = conn.execute("SELECT payload FROM events WHERE task_id=? AND kind=? AND json_extract(payload,'$.key')=?",
                               (task_id, KIND, key)).fetchone()
            if old:
                return json.loads(old['payload'])
        ledger._event(conn, task_id, KIND, dict(payload, at=utcnow()))
        return payload
    if conn is not None:
        if not getattr(conn, 'in_transaction', False):
            raise LedgerError('decision record: conn must be an open write transaction (validate and write together).')
        return write(conn)
    with ledger.transaction(write=True) as conn:
        return write(conn)
