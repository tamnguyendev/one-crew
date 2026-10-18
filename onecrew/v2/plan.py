"""Plan lifecycle on the v1 ledger. State is never stored in the contract file: it is derived from events on an "anchor" task
(`plan:<name>`, an audit job that is never started), so the only writers of approved/accepted are approve() and accept() below.

OneCrew has no model here. It compares what the owner agreed (the revision) with what was observed (verdicts, receipts).
"""
import json
import os

from ..ledger import LedgerError, canonical, content_hash, key_field, text_field, utcnow
from . import contract as contracts
from .ownership import session_info

ANCHOR = 'plan:'
KINDS = ('plan.proposed', 'plan.amended', 'plan.approved', 'plan.accepted', 'verdict.recorded', 'milestone.passed',
         'milestone.failed', 'milestone.stopped', 'attention.exceeded', 'dispatch.refused_no_plan', 'verdict.receipt_issued')
OWNER_ACTORS = ('user', 'owner')


def require_owner(by, what):
    """Approval and acceptance are the owner's. `--by owner` is a claim, so an entry shell that declares an AI actor
    (ONECREW_ACTOR=claude|codex|...) is refused too; hooks and permission rules (L2) are what makes this hard to bypass."""
    if by != 'owner': raise LedgerError(f'{what} is the owner\'s decision: pass --by owner. No other actor can do it.')
    actor = os.environ.get('ONECREW_ACTOR')
    if actor and actor not in OWNER_ACTORS:
        raise LedgerError(f'{what} refused: this shell declares ONECREW_ACTOR={actor}, and an AI cannot approve or accept.')
    from .ownership import refuse_in_ai_session
    refuse_in_ai_session(what)                      # C11: also when plan.approve is called as a function or plan_cli is run without the router


def refuse_owner_author(author):
    """An AI session cannot put the owner's name on a revision it writes (the author decides whether step 0 evidence may be a statement)."""
    from .ownership import in_ai_session
    if author in OWNER_ACTORS and in_ai_session():
        raise LedgerError(f'author "{author}" refused: this process runs inside an AI tool session; an AI writes under its own name.')


def emit(ledger, conn, task_id, kind, payload):
    ledger._event(conn, task_id, kind, dict(payload, at=utcnow()))


# ---- derived state ---------------------------------------------------------------------------------------------------

def derive(ledger, conn, name):
    """State of plan `name` from the anchor task's events, or None when there is no such plan."""
    if conn is None: return None
    row = conn.execute('SELECT id FROM tasks WHERE project_id=? AND request_key=?', (ledger.project_id, ANCHOR + name)).fetchone()
    if not row: return None
    state = {'name': name, 'task_id': row['id'], 'revisions': {}, 'latest': 0, 'approved': None, 'accepted': None, 'verdicts': [],
             'stopped': {}, 'issued': set(), 'exceeded': 0}
    marks = ','.join('?' * len(KINDS))
    for event in conn.execute(f'SELECT seq,kind,payload FROM events WHERE task_id=? AND kind IN ({marks}) ORDER BY seq', (row['id'], *KINDS)):
        kind, p = event['kind'], json.loads(event['payload'])
        if kind in ('plan.proposed', 'plan.amended'):
            state['revisions'][p['revision']] = p
            state['latest'] = max(state['latest'], p['revision'])
        elif kind == 'plan.approved': state['approved'] = p
        elif kind == 'plan.accepted': state['accepted'] = p
        elif kind == 'verdict.receipt_issued': state['issued'].add((p['revision'], p['milestone'], p['receipt']))
        elif kind == 'verdict.recorded': state['verdicts'].append(dict(p, seq=event['seq']))
        elif kind == 'milestone.stopped': state['stopped'][p['revision']] = p
        elif kind == 'attention.exceeded': state['exceeded'] += 1
    state['status'] = status(state)
    return state


def status(state):
    latest = state['latest']
    if not latest: return 'proposed'
    if state['accepted'] and state['accepted']['revision'] == latest: return 'accepted'
    if latest in state['stopped']: return 'stopped_with_report'
    approved = state['approved']
    if approved and approved['revision'] == latest and approved['sha'] == state['revisions'][latest]['sha']: return 'approved'
    return 'proposed'


def load(ledger, state, revision=None):
    """(contract, sha) of a revision, re-hashed against the sha the ledger recorded."""
    revision = revision or state['latest']
    if revision not in state['revisions']: raise LedgerError(f'Plan {state["name"]} has no revision {revision}.')
    return contracts.read_revision(ledger, state['name'], revision, state['revisions'][revision]['sha'])


def milestone_views(contract, state, revision):
    """A milestone is passed only while its LATEST verdict on this revision is a pass; a later failure reopens it."""
    views = []
    for m in contract['milestones']:
        mine = [v for v in state['verdicts'] if v['revision'] == revision and v['milestone'] == m['id']]
        failures = len([v for v in mine if v['result'] != 'pass'])
        passed = bool(mine) and mine[-1]['result'] == 'pass'
        stopped = revision in state['stopped'] and state['stopped'][revision]['milestone'] == m['id']
        views.append({'id': m['id'], 'title': m['title'], 'mode': m['mode'], 'verifier': m['verifier']['type'],
                      'max_repairs': m['max_repairs'], 'state': 'passed' if passed else 'stopped' if stopped else 'failed' if failures else 'pending',
                      'runs': len(mine), 'failures': failures, 'repairs_left': max(0, m['max_repairs'] - failures) if not passed else None,
                      'last_verdict': ({k: mine[-1].get(k) for k in ('result', 'by', 'artifact_sha', 'receipt', 'cwd')} if mine else None)})
    return views


def anchor_events(ledger, conn, name):
    state = derive(ledger, conn, name)
    if state is None: raise LedgerError(f'No plan named {name}. Create one with: plan propose.')
    return state


# ---- commands --------------------------------------------------------------------------------------------------------

def _anchor(ledger, name, title):
    from ..owned_intake import submit
    return submit(ledger, f'Plan {name}: {title}'[:2000], ANCHOR + name, mode='audit')['id']


def propose(ledger, name, raw, author):
    key_field(name); key_field(ANCHOR + name)
    text_field(author, 'author', 100); refuse_owner_author(author)
    contract = contracts.validate(raw)
    if contracts.revision_path(ledger, name, 1).exists(): raise LedgerError(f'Plan {name} already exists; change it with plan amend.')
    task_id = _anchor(ledger, name, contract['title'])
    sha = contracts.write_revision(ledger, name, 1, contract)
    with ledger.transaction(write=True) as conn:
        if derive(ledger, conn, name)['latest']: raise LedgerError(f'Plan {name} already exists; change it with plan amend.')
        emit(ledger, conn, task_id, 'plan.proposed', {'plan': name, 'revision': 1, 'sha': sha, 'author': author, 'content_author': author, 'title': contract['title']})
    return show(ledger, name)


def amend(ledger, name, raw, reason, author, events=None, keep_content_author=False):
    """A new revision, never an edit. Approval and verdicts belong to a revision, so an amendment needs a new approval.
    `events(revision)` -> [(kind, payload)] are written in the same transaction (step 0: unknown.closed, poc.answered).
    `content_author` is who wrote the text of the revision (step 0 judges evidence by it, C12): the author, except when closing an unknown only
    changes that unknown (keep_content_author), which leaves the text with whoever wrote it before."""
    text_field(reason, 'reason', 200); text_field(author, 'author', 100); refuse_owner_author(author)
    contract = contracts.validate(raw)
    with ledger.transaction(write=True) as conn:
        state = anchor_events(ledger, conn, name)
        if state['status'] == 'accepted': raise LedgerError(f'Plan {name} is accepted; it cannot be amended.')
        latest, sha_now = state['latest'], content_hash(contract)
        if state['revisions'][latest]['sha'] == sha_now: raise LedgerError('The amendment is identical to the current revision.')
        revision = latest + 1
        sha = contracts.write_revision(ledger, name, revision, contract)
        emit(ledger, conn, state['task_id'], 'plan.amended', {'plan': name, 'revision': revision, 'from_revision': latest, 'sha': sha,
                                                               'parent_sha': state['revisions'][latest]['sha'], 'reason': reason,
                                                               'author': author, 'title': contract['title'],
                                                               'content_author': (state['revisions'][latest].get('content_author') or state['revisions'][latest].get('author')) if keep_content_author else author})
        for kind, payload in (events(revision) if events else ()): emit(ledger, conn, state['task_id'], kind, payload)
    from . import active_plan; active_plan.export(ledger, name)  # L2: one line (hooks read the exported file, not the ledger)
    return show(ledger, name)


def approve(ledger, name, by, reference, revision=None, tick=(), choose=None):
    """Owner only, and only when step 0 is done (step0.evaluate): every reason it is not is returned in one refusal. The
    owner's `choose` is recorded here and nowhere else."""
    from . import step0
    require_owner(by, 'Approving a plan'); text_field(reference, 'reference', 500)
    with ledger.transaction() as conn:                       # read first: the preconditions below may run for minutes
        state = anchor_events(ledger, conn, name)
        revision = revision or state['latest']
        if revision != state['latest']: raise LedgerError(f'Only the latest revision ({state["latest"]}) can be approved.')
        contract, sha = load(ledger, state, revision)
        approved, closed = state['approved'], step0.closed_events(conn, state['task_id'])
        written_by = state['revisions'][revision].get('content_author') or state['revisions'][revision].get('author')
    if approved and approved['revision'] == revision and approved['sha'] == sha:   # a repeat is a no-op, but the choice is made once
        if choose is not None and choose != approved.get('chosen'):
            raise LedgerError(f'The choice was made once ({approved.get("chosen")}); changing it needs plan amend (a change request).')
        return show(ledger, name)
    should = {i['id'] for i in contract['items'] if i['tier'] == 'should'}
    ticked = sorted(set(tick))
    if set(ticked) - should: raise LedgerError('Only should items can be ticked: ' + ','.join(sorted(set(ticked) - should)))
    verdict = step0.evaluate(ledger, name, revision, sha, contract, closed, choose, author=written_by)
    with ledger.transaction(write=True) as conn:
        state = anchor_events(ledger, conn, name)
        if state['latest'] != revision or state['revisions'][revision]['sha'] != sha:
            raise LedgerError('The plan changed while step 0 was being checked; run approve again.')
        if verdict['results']: step0.record_run(ledger, conn, state['task_id'], name, revision, sha, verdict, 'approve')
        if verdict['ok']:
            emit(ledger, conn, state['task_id'], 'plan.approved', {'plan': name, 'revision': revision, 'sha': sha, 'by': by, 'reference': reference,
                                                                    'ticked': ticked, 'chosen': choose, **session_info()})
            step0.record_closed(ledger, conn, state['task_id'], name, revision, sha, verdict, choose)
    if not verdict['ok']: raise LedgerError(step0.refusal_text(verdict))   # after the commit, so the precondition run stays recorded
    from . import active_plan; active_plan.export(ledger, name)  # L2: one line (hooks read the exported file, not the ledger)
    return show(ledger, name)


def accept(ledger, name, by, reference, artifact_sha):
    """The owner's acceptance. Refused unless every milestone of the current revision has a passing verdict and the final one
    was observed on exactly the artifact being accepted (invariants 4 and 6)."""
    require_owner(by, 'Accepting the result'); text_field(reference, 'reference', 500)
    with ledger.transaction(write=True) as conn:
        state = anchor_events(ledger, conn, name)
        repeat = state['status'] == 'accepted' and state['accepted']['artifact_sha'] == artifact_sha
        if not repeat:
            if state['status'] != 'approved': raise LedgerError(f'Cannot accept: the plan is {state["status"]}, not approved.')
            revision = state['latest']
            contract, sha = load(ledger, state, revision)
            views = milestone_views(contract, state, revision)
            missing = [v['id'] for v in views if v['state'] != 'passed']
            if missing: raise LedgerError('Cannot accept: no passing verdict for milestone ' + ', '.join(missing) + '.')
            elsewhere = [v for v in views if v['last_verdict']['artifact_sha'] != artifact_sha]
            if elsewhere:
                raise LedgerError(f'Cannot accept artifact {artifact_sha}: every milestone must have passed on exactly that artifact; '
                                  + '; '.join(f'{v["id"]} passed on {v["last_verdict"]["artifact_sha"]}' for v in views) + '. Re-run the milestones that differ.')
            emit(ledger, conn, state['task_id'], 'plan.accepted', {'plan': name, 'revision': revision, 'sha': sha, 'by': by, 'reference': reference,
                                                                    'artifact_sha': artifact_sha, 'receipts': {v['id']: v['last_verdict']['receipt'] for v in views}, **session_info()})
    return show(ledger, name)


def show(ledger, name, revision=None):
    from . import step0
    with ledger.transaction() as conn:
        state = anchor_events(ledger, conn, name)
        revision = revision or state['latest']
        contract, sha = load(ledger, state, revision)
        approved = state['approved'] if state['approved'] and state['approved']['revision'] == revision else None
        ticked = set(approved['ticked']) if approved else set()
        items = [dict(i, runs=i['tier'] == 'must' or (i['tier'] == 'should' and i['id'] in ticked)) for i in contract['items']]
        requests = [r for r in ledger.requests(state['task_id']) if r['question'].get('action', {}).get('type') == 'v2.plan_stopped']
        return {'plan': name, 'status': state['status'], 'revision': revision, 'latest_revision': state['latest'], 'sha': sha,
                'approved_revision': state['approved']['revision'] if state['approved'] else None,
                'revisions': [{'revision': r, 'sha': p['sha'], 'reason': p.get('reason')} for r, p in sorted(state['revisions'].items())],
                'contract': dict(contract, items=items), 'milestones': milestone_views(contract, state, revision),
                'step0': step0.step0_status(conn, state['task_id'], revision), 'size': contract['size'],
                'stop': dict(contracts.stop_limits(contract), repairs_used=sum(v['failures'] for v in milestone_views(contract, state, revision))),
                'attention': {'questions_limit': contract['attention']['questions'], 'questions_used': len(requests),
                              'exceeded': state['exceeded']},
                'questions': [{'request': r['id'], 'revision': r['revision'], 'state': r['state']} for r in requests],
                'anchor_task': state['task_id'], 'state_root': str(ledger.state_root)}
