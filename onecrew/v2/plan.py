"""Plan lifecycle on the v1 ledger. State is never stored in the contract file: it is derived from events on an "anchor" task
(`plan:<name>`, an audit job that is never started), so the only writers of approved/accepted are approve() and accept() below.

OneCrew has no model here. It compares what the owner agreed (the revision) with what was observed (verdicts, receipts).
"""
import json
import os
import subprocess

from ..ledger import LedgerError, canonical, content_hash, key_field, text_field, utcnow
from . import contract as contracts, namespaces
from .ownership import session_info

ANCHOR = 'plan:'
KINDS = ('plan.proposed', 'plan.amended', 'plan.approved', 'plan.accepted', 'verdict.recorded', 'milestone.passed',
         'milestone.failed', 'milestone.stopped', 'attention.exceeded', 'dispatch.refused_no_plan', 'verdict.receipt_issued', 'plan.advised', 'plan.closed')
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
    # W11a: a `plan:` anchor is a root the old version reads. Only class 0/A events, and class-0 payloads that keep every old field,
    # may be written there (00 §6.1). The guard is a no-op on plan-ns: roots and on non-plan tasks.
    row = conn.execute('SELECT request_key FROM tasks WHERE id=?', (task_id,)).fetchone()
    if row is not None:
        from . import compat
        compat.check_write(kind, payload, row['request_key'])
    ledger._event(conn, task_id, kind, dict(payload, at=utcnow()))


# ---- derived state ---------------------------------------------------------------------------------------------------

def derive(ledger, conn, name):
    """State of plan `name` from the anchor task's events, or None when there is no such plan."""
    if conn is None: return None
    row = namespaces.resolve(ledger, conn, name)
    if not row: return None
    state = {'name': namespaces.parse(row['request_key'])[0], 'selector': row['request_key'], 'anchor': row['request_key'],
             'task_id': row['id'], 'revisions': {}, 'latest': 0, 'approved': None, 'accepted': None, 'verdicts': [],
             'stopped': {}, 'issued': set(), 'issued_seq': {}, 'exceeded': 0, 'advice': {}}
    marks = ','.join('?' * len(KINDS))
    declared = False
    for event in conn.execute(f'SELECT seq,kind,payload FROM events WHERE task_id=? AND kind IN ({marks}) ORDER BY seq', (row['id'], *KINDS)):
        kind, p = event['kind'], json.loads(event['payload'])
        if kind in ('plan.proposed', 'plan.amended'):
            if kind == 'plan.proposed' and not declared:
                declared = True
                namespaces.check_workflow(p)
                state.update({key: p[key] for key in ('workflow_version', 'capabilities') if key in p})
            state['revisions'][p['revision']] = p
            state['latest'] = max(state['latest'], p['revision'])
        elif kind == 'plan.approved': state['approved'] = p
        elif kind == 'plan.accepted': state['accepted'] = p
        elif kind == 'plan.closed' and namespaces.has_capability(state, 'sequential-engine'): state['closed'] = p
        elif kind == 'verdict.receipt_issued':
            state['issued'].add((p['revision'], p['milestone'], p['receipt']))
            state['issued_seq'][(p['revision'], p['milestone'])] = event['seq']      # the latest issuance, to tell a receipt that still waits for its verdict
        elif kind == 'verdict.recorded': state['verdicts'].append(dict(p, seq=event['seq']))
        elif kind == 'milestone.stopped': state['stopped'][p['revision']] = p
        elif kind == 'attention.exceeded': state['exceeded'] += 1
        elif kind == 'plan.advised': state['advice'][p['revision']] = p       # the latest advice of a revision; it informs, it never decides
    state['status'] = status(state)
    return state


def status(state):
    if state.get('closed'): return 'closed'
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
    return contracts.read_revision(ledger, state.get('selector', state['name']), revision, state['revisions'][revision]['sha'])


def _signature(milestone, contract):
    """What a verdict was about, apart from the artifact, as canonical JSON: the title, the verifier (type and config), the output ids the milestone
    covers and the full text of each of those outputs in `contract`. Adding, dropping or rewording a covered output changes it, so the milestone runs
    again; an output the milestone does not cover is not in it, so rewording that one costs the milestone nothing."""
    texts = dict(zip(contracts.output_ids(contract['output']), contract['output']))
    covers = sorted(set(milestone.get('covers') or []))
    return canonical({'title': milestone['title'], 'verifier': milestone['verifier'], 'covers': covers, 'outputs': {oid: texts.get(oid) for oid in covers}})


def covers(ledger, verdict_artifact, current, kind, neutral):
    """Does a verdict observed on `verdict_artifact` still speak for `current`? 'same'; 'neutral' when the two trees differ only in paths
    matching scope.neutral (a command milestone only: a reviewer or an owner looked at those very files) and no submodule moved to another
    commit, even one whose path scope.neutral names; else None."""
    if verdict_artifact == current: return 'same'
    if kind != 'command' or not neutral or ledger is None: return None
    from .verifiers import command
    try:
        paths = command.changed_paths(ledger.project, verdict_artifact, current)
        if command.submodule_paths(ledger.project, verdict_artifact, current): return None      # a submodule that moved is never neutral, wherever its path is
    except (LedgerError, OSError, subprocess.SubprocessError):
        return None
    return 'neutral' if paths and all(contracts.neutral_match(p, neutral) for p in paths) else None


def _inherited(ledger, state, revision, milestone, contract):
    """The latest verdict of this milestone on an EARLIER revision when it is a pass, the milestone is the same in that revision (_signature: title,
    verifier, covers and the text of every output it covers) and the independence rule still holds for THIS revision, else None. It is a way of
    reading the ledger: nothing is written."""
    earlier = [v for v in state['verdicts'] if v['milestone'] == milestone['id'] and v['revision'] < revision]
    if not earlier or earlier[-1]['result'] != 'pass': return None
    try:
        old = load(ledger, state, earlier[-1]['revision'])[0]
    except LedgerError:
        return None
    before = next((m for m in old['milestones'] if m['id'] == milestone['id']), None)
    if before is None or _signature(before, old) != _signature(milestone, contract): return None
    if milestone['verifier']['type'] == 'reviewer':       # the authors of the new revision may be the reviewer: a pass is not carried to someone who would be reviewing their own text
        from .verifiers import reviewer
        try:
            reviewer.check_independence(state['revisions'][revision], milestone['verifier']['config'])
        except LedgerError:
            return None
    return earlier[-1]


def milestone_views(contract, state, revision, ledger=None, artifact=None, conn=None):
    """A milestone is passed only while its LATEST verdict on this revision is a pass; a later failure reopens it.

    With a `ledger` (its project is a Git repository) or an explicit `artifact`, the views also say whether that verdict still speaks for the
    artifact being judged (`artifact`, else the project's artifact now): a pass on another artifact is not passed (`stale`), unless the two
    differ only in the paths the contract itself declares in scope.neutral (there is no built-in list) and the verifier is a command (`neutral_diff`). A
    milestone with no verdict on this revision inherits the latest pass of an earlier revision when its title, verifier, covers and the text of every output it
    covers are the same, the independence rule holds for this revision and that verdict covers the artifact (`carried_from`).
    Without either, the views are what they always were."""
    current = [artifact, artifact is not None]
    neutral = contracts.neutral_globs(contract)
    approved = state['approved']
    carries = (ledger is not None and bool(approved) and approved['revision'] == revision          # nothing is inherited by a revision the owner has not approved
               and approved['sha'] == state['revisions'].get(revision, {}).get('sha'))

    def now():
        if not current[1]:
            current[1] = True
            from .verifiers import artifact as identities
            try:
                current[0] = identities.identity(ledger.project) if ledger is not None and getattr(ledger, 'project', None) else None
            except (LedgerError, OSError, subprocess.SubprocessError):
                current[0] = None
        return current[0]
    views = []
    for m in contract['milestones']:
        mine = [v for v in state['verdicts'] if v['revision'] == revision and v['milestone'] == m['id']]
        failures = len([v for v in mine if v['result'] != 'pass'])
        passed = bool(mine) and mine[-1]['result'] == 'pass'
        stopped = revision in state['stopped'] and state['stopped'][revision]['milestone'] == m['id']
        verdict, extra = (mine[-1] if mine else None), {}
        if ledger is not None or artifact is not None:
            candidate = mine[-1] if passed else (_inherited(ledger, state, revision, m, contract) if not mine and carries else None)
            if candidate is not None and now() is not None:
                how = covers(ledger, candidate['artifact_sha'], now(), m['verifier']['type'], neutral)
                if ledger is not None and m['verifier']['type'] != 'owner-manual':
                    from . import verification_evidence
                    binding = verification_evidence.receipt_assessment(ledger, contract, m, revision,
                        candidate['receipt'], now(), task_id=state['task_id'], conn=conn,
                        require_bound=namespaces.has_capability(state, 'sequential-engine'))
                    if binding is not None:
                        if not binding['reusable'] or (binding['requires_record'] and not binding['recorded']):
                            how = None
                            extra.update(stale=True, stale_reasons=binding['reasons'] or ['Evidence reuse basis must be recorded.'],
                                         checks_to_rerun=binding['checks_to_rerun'], reuse_basis=binding.get('reuse_basis'))
                if how is None:
                    if passed: passed = False; extra['stale'] = True
                else:
                    if not passed: passed, verdict = True, candidate
                    if candidate['revision'] != revision or how == 'neutral': extra['carried_from'] = candidate['revision']
                    if how == 'neutral': extra['neutral_diff'] = True
        views.append({'id': m['id'], 'title': m['title'], 'mode': m['mode'], 'verifier': m['verifier']['type'],
                      'max_repairs': m['max_repairs'], 'state': 'passed' if passed else 'stopped' if stopped else 'failed' if failures else 'pending',
                      'runs': len(mine), 'failures': failures, 'repairs_left': max(0, m['max_repairs'] - failures) if not passed else None,
                      'last_verdict': ({k: verdict.get(k) for k in ('result', 'by', 'artifact_sha', 'receipt', 'cwd')} if verdict else None), **extra})
    return views


def _accepted_views(contract, state, revision, accepted):
    """The views of an ACCEPTED revision, from what the `plan.accepted` event recorded and not from today's rules: each milestone is passed on the verdict
    that was recorded last with the receipt the event names (`receipts`; the same evidence file can be judged twice, and the second verdict is the one
    accepted). Nothing says `carried_from`, `neutral_diff` or `stale`: the plan was accepted, those are words for a plan still on its way, and what carried
    a pass is in the event (`carried`). A plan accepted under older rules (2.1, the dev2 default neutral list) therefore reads as it was accepted, and its
    report does not move; the one difference is a milestone accepted on a verdict carried from an earlier revision, which the old report called "no verdict
    yet" and which now reads as the pass it was accepted on. `runs`, `failures` and the rest are what the revision recorded."""
    views = milestone_views(contract, state, revision)
    receipts = accepted.get('receipts') or {}
    for view in views:
        wanted = receipts.get(view['id'])
        matching = [v for v in state['verdicts'] if v['milestone'] == view['id'] and wanted and v.get('receipt') == wanted]
        if not matching: continue             # nothing recorded for it: the view stays what the revision itself recorded
        view.update(state='passed', repairs_left=None, last_verdict={k: matching[-1].get(k) for k in ('result', 'by', 'artifact_sha', 'receipt', 'cwd')})
    return views


def views_for(ledger, contract, state, revision):
    """The milestone views of `revision` as `plan show`, `plan report` and the hooks read them (accept judges with milestone_views at the artifact it is
    given): carried verdicts included, a pass the artifact has left stale. A revision that was accepted is read from the acceptance record
    (_accepted_views), so what was accepted reads the same forever; any other is read at the project's artifact now."""
    accepted = state['accepted'] if state['accepted'] and state['accepted']['revision'] == revision else None
    if accepted and isinstance(accepted.get('receipts'), dict): return _accepted_views(contract, state, revision, accepted)
    return milestone_views(contract, state, revision, ledger, artifact=accepted['artifact_sha'] if accepted else None)


def resolve(ledger, state):
    """The revision a verdict is about, or None when nothing is approved to run.

    Normally that is the latest revision, once it is approved. While a newer revision is only proposed (an amendment waiting for the
    owner), a milestone whose title and verifier are the same in both may still run on the APPROVED revision: `frozen` says which
    milestones changed (blocked until the new revision is approved) and which did not. Invariant 1 holds: the revision a verdict runs on
    always has a plan.approved event whose sha matches its file."""
    if state['status'] == 'approved': return {'revision': state['latest'], 'frozen': None}
    approved, latest = state['approved'], state['latest']
    if (state['status'] != 'proposed' or not approved or approved['revision'] >= latest or state['accepted']
            or approved['revision'] in state['stopped']
            or state['revisions'].get(approved['revision'], {}).get('sha') != approved['sha']):
        return None
    old, _ = load(ledger, state, approved['revision'])
    new, _ = load(ledger, state, latest)
    now = {m['id']: m for m in new['milestones']}
    same = [m['id'] for m in old['milestones'] if m['id'] in now and (m['title'], m['verifier']) == (now[m['id']]['title'], now[m['id']]['verifier'])]
    changed = [m['id'] for m in old['milestones'] if m['id'] not in same]
    return {'revision': approved['revision'], 'frozen': {'approved_revision': approved['revision'], 'pending_revision': latest,
                                                         'frozen': changed, 'runnable': same}}


def anchor_events(ledger, conn, name):
    state = derive(ledger, conn, name)
    if state is None: raise LedgerError(f'No plan named {name}. Create one with: plan propose.')
    return state


# ---- commands --------------------------------------------------------------------------------------------------------

import re as _re

# W12a: a plan name becomes part of a filesystem path (plans/<name>/) and of the anchor key (plan:<name>). A name with a path
# separator, a parent ref, a drive form or a leading separator could write OUTSIDE the state root, and a ':' collides with the
# anchor-key separator. Reject all of those BEFORE any write, on every create path. The stored path does not change (W12b/R04 adds
# per-project namespacing); this is only the name gate.
_PLAN_NAME = _re.compile(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,99}$')
_FORBIDDEN = {':': "a colon (it is the anchor-key separator plan:<name>)", '/': 'a path separator', chr(92): 'a path separator',
              '..': 'a parent-directory reference'}


def valid_plan_name(name):
    """Return `name` if it is a safe plan name; else raise LedgerError naming the forbidden character. Rejects ':', '/', '\\', '..',
    a drive form (C:x), and absolute paths — anything that could put the plan file outside plans/<name>/ or break the anchor key."""
    if not isinstance(name, str) or not name:
        raise LedgerError('plan name: expected a non-empty name of letters, digits, _, . or -.')
    for bad, why in _FORBIDDEN.items():
        if bad in name:
            raise LedgerError(f'plan name {name!r} is refused: it contains {why}. A plan name is letters, digits, _, . or - only, '
                              f'so it cannot escape plans/<name>/ or collide with the anchor key.')
    if _re.match(r'^[A-Za-z]:', name):                       # drive form C:x / C:\x
        raise LedgerError(f'plan name {name!r} is refused: it looks like a drive path. A plan name is letters, digits, _, . or - only.')
    from pathlib import PurePath, PureWindowsPath
    if PurePath(name).is_absolute() or PureWindowsPath(name).is_absolute() or name.startswith(('/', chr(92))):
        raise LedgerError(f'plan name {name!r} is refused: it is an absolute or rooted path.')
    if not _PLAN_NAME.match(name):
        raise LedgerError(f'plan name {name!r} is refused: use 1-100 chars of letters, digits, _, . or - (starting with a letter or digit).')
    return name


def refuse_duplicate_name(ledger, name):
    """W12a: in a shared state root, two projects must not create the same plan name (the R00 storage plans/<name>/ is shared, so the
    second would collide with or branch into the first). If ANOTHER project already owns plan:<name>, refuse and name that project, writing
    nothing. Same-project re-create is left to propose's own 'already exists'. Full same-name support is W12b (R04)."""
    with ledger.transaction() as conn:
        if conn is None:
            return
        row = conn.execute('SELECT project_id FROM tasks WHERE request_key=? AND project_id<>?',
                           (ANCHOR + name, ledger.project_id)).fetchone()
    if row is not None:
        raise LedgerError(f'plan name {name!r} is already used by another project ({row["project_id"][:12]}) in this state root; '
                          f'the R00 store plans/{name}/ is shared, so a second project cannot reuse the name (W12b adds per-project names). '
                          f'Nothing was written.')


def _anchor(ledger, name, title):
    from ..task_intake import submit
    return submit(ledger, f'Plan {name}: {title}'[:2000], namespaces.NAMESPACED + name, mode='audit')['id']


def propose(ledger, name, raw, author, workflow=False, capabilities=None):
    valid_plan_name(name)                       # W12a: reject ':', path chars, drive form, absolute — before any write
    key_field(name); key_field(ANCHOR + name)
    metadata = namespaces.workflow_metadata(workflow, capabilities)
    text_field(author, 'author', 100); refuse_owner_author(author)
    contract = contracts.validate(raw)
    selector = namespaces.NAMESPACED + name
    from . import solution_link
    solution_link.prepare(ledger, selector, contract)
    if contracts.revision_path(ledger, selector, 1).exists(): raise LedgerError(f'Plan {name} already exists; change it with plan amend.')
    task_id = _anchor(ledger, name, contract['title'])
    sha = contracts.write_revision(ledger, selector, 1, contract)
    with ledger.transaction(write=True) as conn:
        if derive(ledger, conn, selector)['latest']: raise LedgerError(f'Plan {name} already exists; change it with plan amend.')
        emit(ledger, conn, task_id, 'plan.proposed', {'plan': name, 'revision': 1, 'sha': sha, 'author': author, 'content_author': author, 'title': contract['title'], **metadata})
        solution_link.record(ledger, conn, task_id, selector, 1, sha, contract)
    return show(ledger, selector)


def amend(ledger, name, raw, reason, author, events=None, keep_content_author=False):
    """A new revision, never an edit. Approval and verdicts belong to a revision, so an amendment needs a new approval.
    `events(revision)` -> [(kind, payload)] are written in the same transaction (step 0: unknown.closed, poc.answered).
    `content_author` is who wrote the text of the revision (step 0 judges evidence by it, C12): the author, except when closing an unknown only
    changes that unknown (keep_content_author), which leaves the text with whoever wrote it before."""
    text_field(reason, 'reason', 200); text_field(author, 'author', 100); refuse_owner_author(author)
    contract = contracts.validate(raw)
    with ledger.transaction(write=True) as conn:
        state = anchor_events(ledger, conn, name)
        if state['status'] in ('accepted', 'closed'): raise LedgerError(f'Plan {name} is {state["status"]}; it cannot be amended.')
        latest, sha_now = state['latest'], content_hash(contract)
        if state['revisions'][latest]['sha'] == sha_now: raise LedgerError('The amendment is identical to the current revision.')
        revision = latest + 1
        from . import solution_link
        solution_link.validate_revision(ledger, conn, state['selector'], contract)
        sha = contracts.write_revision(ledger, state['selector'], revision, contract)
        emit(ledger, conn, state['task_id'], 'plan.amended', {'plan': state['name'], 'revision': revision, 'from_revision': latest, 'sha': sha,
                                                               'parent_sha': state['revisions'][latest]['sha'], 'reason': reason,
                                                               'author': author, 'title': contract['title'],
                                                               'content_author': (state['revisions'][latest].get('content_author') or state['revisions'][latest].get('author')) if keep_content_author else author})
        for kind, payload in (events(revision) if events else ()): emit(ledger, conn, state['task_id'], kind, payload)
        solution_link.record(ledger, conn, state['task_id'], state['selector'], revision, sha, contract)
    from . import active_plan; active_plan.export(ledger, name)  # L2: one line (hooks read the exported file, not the ledger)
    return show(ledger, name)


def _base_tracked(ledger):
    """The tree of the tracked files as the owner approves (HEAD + changes to tracked files, never an untracked file): where a reviewer's diff
    starts, so no untracked content can be on the base side of it. None outside a Git repository."""
    from .verifiers import command
    try:
        return command.tracked_tree(ledger.project)
    except (LedgerError, OSError, subprocess.SubprocessError):
        return None


def _base_artifact(ledger):
    """The tree the project is in as the owner approves: what a reviewer verifier later diffs against. None outside a Git repository."""
    from .verifiers import command
    try:
        return command.artifact_sha(ledger.project)
    except (LedgerError, OSError, subprocess.SubprocessError):
        return None


def approve(ledger, name, by, reference, revision=None, tick=(), choose=None, estimate=None):
    """Owner only, and only when step 0 is done (step0.evaluate): every reason it is not is returned in one refusal. The
    owner's `choose` is recorded here and nowhere else."""
    from . import step0
    require_owner(by, 'Approving a plan'); text_field(reference, 'reference', 500)
    from . import estimates
    if estimate is not None: estimates.normalize(estimate)
    with ledger.transaction() as conn:                       # read first: the preconditions below may run for minutes
        state = anchor_events(ledger, conn, name)
        if state['status'] == 'closed': raise LedgerError('A closed root cannot be reopened by approval; create a new root.')
        revision = revision or state['latest']
        if revision != state['latest']: raise LedgerError(f'Only the latest revision ({state["latest"]}) can be approved.')
        contract, sha = load(ledger, state, revision)
        approved, closed = state['approved'], step0.closed_events(conn, state['task_id'])
        from . import solution_link
        solution_link.validate_root(ledger, conn, state, contract, sha, revision)
        written_by = state['revisions'][revision].get('content_author') or state['revisions'][revision].get('author')
        advice = state['advice'].get(revision)
        proposal_check = step0.latest_proposal_check(conn, state['task_id'], revision)      # W47
    if approved and approved['revision'] == revision and approved['sha'] == sha:   # a repeat is a no-op, but the choice is made once
        if choose is not None and choose != approved.get('chosen'):
            raise LedgerError(f'The choice was made once ({approved.get("chosen")}); changing it needs plan amend (a change request).')
        return show(ledger, name)
    should = {i['id'] for i in contract['items'] if i['tier'] == 'should'}
    ticked = sorted(set(tick))
    if set(ticked) - should: raise LedgerError('Only should items can be ticked: ' + ','.join(sorted(set(ticked) - should)))
    verdict = step0.evaluate(ledger, name, revision, sha, contract, closed, choose, author=written_by, advice=advice, proposal_check=proposal_check)
    base_artifact, base_tracked = _base_artifact(ledger), _base_tracked(ledger)
    with ledger.transaction(write=True) as conn:
        state = anchor_events(ledger, conn, name)
        if state['latest'] != revision or state['revisions'][revision]['sha'] != sha:
            raise LedgerError('The plan changed while step 0 was being checked; run approve again.')
        if state['status'] == 'closed': raise LedgerError('The root was closed while step 0 was being checked.')
        if verdict['results']: step0.record_run(ledger, conn, state['task_id'], name, revision, sha, verdict, 'approve')
        if verdict['ok']:
            solution_link.validate_root(ledger, conn, state, contract, sha, revision)
            from .retention import pin_trees
            bases = [tree for tree in (base_artifact, base_tracked) if tree is not None]
            if bases: pin_trees(ledger, name, *bases)
            emit(ledger, conn, state['task_id'], 'plan.approved', {'plan': name, 'revision': revision, 'sha': sha, 'by': by, 'reference': reference,
                                                                    'ticked': ticked, 'chosen': choose, 'base_artifact': base_artifact,
                                                                    **({'base_tracked': base_tracked} if base_tracked else {}), **session_info()})
            from ..budget_core import ensure_plan_group
            ensure_plan_group(ledger, conn, state['selector'])
            estimates.ensure_baseline(ledger, conn, state['selector'], estimate)
            step0.record_closed(ledger, conn, state['task_id'], name, revision, sha, verdict, choose)
    if not verdict['ok']: raise LedgerError(step0.refusal_text(verdict))   # after the commit, so the precondition run stays recorded
    from . import active_plan; active_plan.export(ledger, name)  # L2: one line (hooks read the exported file, not the ledger)
    return show(ledger, name)


def _as_tree(ledger, value):
    """What `--artifact-sha` names, as a tree hash. Only a 40/64-hex id is ever given to git (anything else, an option such as --relative=docs
    included, is refused here, before git runs); a commit id is read as its tree. A hex id git cannot resolve is returned as it is, so it still
    fails the comparison with the verdicts' artifacts."""
    from .verifiers import command
    if not isinstance(value, str) or not command.TREE_ID.fullmatch(value):
        raise LedgerError('--artifact-sha must be a tree (or commit) id of 40 or 64 lowercase hex characters, not ' + repr(str(value)[:40]) + '.')
    if set(value) == {'0'}:
        raise LedgerError('--artifact-sha is the null id (all zeros): that is what a receipt records when no artifact could be made, never an artifact to accept.')
    try:
        tree = command._git(ledger.project, 'rev-parse', '--verify', '-q', '--end-of-options', value + '^{tree}')
    except (LedgerError, OSError, subprocess.SubprocessError):
        return value
    return tree if command.TREE_ID.fullmatch(tree or '') else value


def accept(ledger, name, by, reference, artifact_sha):
    """The owner's acceptance. Refused unless every milestone of the current revision has a passing verdict and the final one
    was observed on exactly the artifact being accepted (invariants 4 and 6)."""
    require_owner(by, 'Accepting the result'); text_field(reference, 'reference', 500)
    artifact_sha = _as_tree(ledger, artifact_sha)
    with ledger.transaction(write=True) as conn:
        state = anchor_events(ledger, conn, name)
        repeat = state['status'] == 'accepted' and state['accepted']['artifact_sha'] == artifact_sha
        if not repeat:
            if state['status'] != 'approved': raise LedgerError(f'Cannot accept: the plan is {state["status"]}, not approved.')
            revision = state['latest']
            contract, sha = load(ledger, state, revision)
            from .verifiers import artifact as identities
            if not identities.is_git(ledger.project) and any(m['verifier']['type'] != 'owner-manual' for m in contract['milestones']):
                artifact_sha = identities.canonical(ledger, artifact_sha)
            if namespaces.has_capability(state, 'sequential-engine'):
                from . import engine
                if not engine.root_ready(ledger, state['selector'], artifact=artifact_sha):
                    raise LedgerError('Cannot accept: workflow nodes, integration and authorized delivered-artifact handoff are not verified.')
            from . import verification_evidence
            for milestone in contract['milestones']:
                candidates = [v for v in state['verdicts'] if v['milestone'] == milestone['id'] and v['revision'] <= revision]
                candidate = candidates[-1] if candidates else None
                if candidate and candidate['result'] == 'pass' and milestone['verifier']['type'] != 'owner-manual':
                    assessment = verification_evidence.receipt_assessment(ledger, contract, milestone, revision,
                        candidate['receipt'], artifact_sha, task_id=state['task_id'], conn=conn,
                        require_bound=namespaces.has_capability(state, 'sequential-engine'))
                    if assessment and assessment['reusable'] and assessment['requires_record'] and not assessment['recorded']:
                        verification_evidence.record_reuse(ledger, name, milestone['id'], candidate['receipt'], artifact_sha, conn=conn)
            views = milestone_views(contract, state, revision, ledger, artifact=artifact_sha, conn=conn)
            missing = [v['id'] for v in views if v['state'] != 'passed' and not v.get('stale')]
            if missing: raise LedgerError('Cannot accept: no passing verdict for milestone ' + ', '.join(missing) + '.')
            elsewhere = [v for v in views if v.get('stale')]
            if elsewhere:
                raise LedgerError(f'Cannot accept artifact {artifact_sha}: every milestone must have passed on exactly that artifact; '
                                  + '; '.join(f'{v["id"]} passed on {v["last_verdict"]["artifact_sha"]}' for v in views if v['last_verdict']) + '. Re-run the milestones that differ.')
            if namespaces.has_capability(state, 'finding-register'):
                from .findings import list_findings
                open_findings = list_findings(ledger, name, task_id=state['task_id'], open_only=True)
                if open_findings:
                    raise LedgerError('Cannot accept: unresolved findings ' + ', '.join(f['id'] for f in open_findings) + '.')
            carried = {v['id']: v['carried_from'] for v in views if v.get('carried_from')}
            from .retention import pin_evidence
            pin_evidence(ledger, name, artifact_sha,
                         strict=any(m['verifier']['type'] != 'owner-manual' for m in contract['milestones']))
            emit(ledger, conn, state['task_id'], 'plan.accepted', {'plan': name, 'revision': revision, 'sha': sha, 'by': by, 'reference': reference,
                                                                    'artifact_sha': artifact_sha, 'receipts': {v['id']: v['last_verdict']['receipt'] for v in views},
                                                                    **({'carried': carried} if carried else {}), **session_info()})
    from . import outcome
    outcome.note(ledger, name)
    return show(ledger, name)


def _advice_view(event, sha):
    """The advisor's answers for `plan show` (objections included, never filtered), or None before `plan advise`."""
    if not event: return None
    return {k: event.get(k) for k in ('model', 'independence', 'usable', 'answers', 'receipt', 'at')} | {'current': event.get('sha') == sha}


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
        target = resolve(ledger, state)
        frozen = target['frozen'] if target and revision in (state['latest'], target['revision']) else None
        views = views_for(ledger, contract, state, revision)   # an accepted plan is read at the artifact accepted
        if frozen:       # a newer revision waits for the owner: which milestones stay runnable on the approved one, which are blocked
            views = [dict(v, frozen=v['id'] in frozen['frozen']) for v in views]
        out = {'plan': state['name'], 'anchor': state['selector'], 'status': state['status'], 'revision': revision, 'latest_revision': state['latest'], 'sha': sha,
                'approved_revision': state['approved']['revision'] if state['approved'] else None,
                'revisions': [{'revision': r, 'sha': p['sha'], 'reason': p.get('reason')} for r, p in sorted(state['revisions'].items())],
                'contract': dict(contract, items=items), 'milestones': views,
                'step0': step0.step0_status(conn, state['task_id'], revision), 'size': contract['size'],
                'origin': contract.get('origin'), 'decisions': contract.get('decisions'), 'advice': _advice_view(state['advice'].get(revision), sha),
                'stop': dict(contracts.stop_limits(contract), repairs_used=sum(v['failures'] for v in milestone_views(contract, state, revision))),
                'attention': {'questions_limit': contract['attention']['questions'], 'questions_used': len(requests),
                              'exceeded': state['exceeded']},
                'questions': [{'request': r['id'], 'revision': r['revision'], 'state': r['state']} for r in requests],
                'anchor_task': state['task_id'], 'state_root': str(ledger.state_root)}
        if frozen: out['frozen'] = frozen
        out.update({key: state[key] for key in ('workflow_version', 'capabilities') if key in state})
        if state.get('closed'): out['closed'] = state['closed']
        return out
