"""Verdicts at milestones (invariant 4: a milestone without a passing verdict is not passed). Each verdict is bound to the plan
revision, the milestone and the sha of the artifact that was observed; a `command` verdict needs a genuine receipt blob."""
import json
import os
import re
from pathlib import Path

from ..ledger import LedgerError, key_field, text_field
from ..snapshots import Snapshots
from . import contract as contracts, plan as plans
from .verifiers import command, reviewer

KINDS = {'command': 'command-receipt', 'reviewer': 'reviewer-receipt'}
RESULTS = ('pass', 'fail', 'inconclusive')
SHA = re.compile(r'[0-9a-f]{40}|[0-9a-f]{64}')


def _blob(ledger, key):
    try:
        return Snapshots(ledger.state_root).read_blob(key)
    except (OSError, LedgerError) as error:
        raise LedgerError('Receipt is not a blob in this state root: ' + str(error)[:120]) from error


def _check_receipt(ledger, name, revision, plan_sha, milestone, result, by, artifact, receipt, issued):
    verifier = milestone['verifier']['type']
    data = _blob(ledger, receipt)
    if verifier == 'owner-manual':
        if by != 'owner': raise LedgerError('Milestone ' + milestone['id'] + ' is verified by the owner: --by owner.')
        return
    if by != verifier: raise LedgerError(f'Milestone {milestone["id"]} is verified by {verifier}, not {by}.')
    kind = KINDS[verifier]
    try:
        body = json.loads(data.decode('utf-8'))
    except ValueError as error:
        raise LedgerError(f'Receipt is not a {kind}.') from error
    if not isinstance(body, dict) or body.get('kind') != kind: raise LedgerError(f'Receipt is not a {kind}.')
    own = ('argv', milestone['verifier']['config']['argv']) if verifier == 'command' else ('config', milestone['verifier']['config'])
    for field, want in (('plan', name), ('revision', revision), ('plan_sha', plan_sha), ('milestone', milestone['id']), own):
        if body.get(field) != want: raise LedgerError(f'Receipt does not belong to this plan/milestone ({field} differs).')
    if body.get('artifact_sha') != artifact:
        raise LedgerError(f'Artifact sha {artifact} does not match the one the receipt observed ({body.get("artifact_sha")}).')
    expected = (command if verifier == 'command' else reviewer).expected_result(body)
    if result != expected: raise LedgerError(f'Receipt supports a {expected} verdict, not {result}.')
    # A well-formed receipt is not enough: it must be one that verdict.run issued. Anything hand-written is refused (F1).
    if (revision, milestone['id'], receipt) not in issued:
        raise LedgerError(f'This receipt was not issued by verdict run. A {verifier} milestone is verified only by verdict run.')
    return body


def record(ledger, name, milestone_id, result, by, receipt, artifact_sha, receipt_bytes=None, reference=None):
    """receipt_bytes: a file to store as the receipt blob. Only owner-manual milestones take one. reference: where the owner said so
    (`onecrew owner record`); it is kept in the verdict event when given."""
    if result not in RESULTS: raise LedgerError('Result must be pass, fail or inconclusive.')
    if not isinstance(artifact_sha, str) or not SHA.fullmatch(artifact_sha): raise LedgerError('artifact sha must be a 40/64-hex hash.')
    key_field(milestone_id); text_field(by, 'by', 60)
    if reference: text_field(reference, 'reference', 300)               # checked before anything is written
    if by == 'owner':
        plans.require_owner(by, 'An owner verdict')
        from .ownership import refuse_in_ai_session
        refuse_in_ai_session('An owner verdict')
    stopped = None
    with ledger.transaction(write=True) as conn:
        state = plans.anchor_events(ledger, conn, name)
        target = plans.resolve(ledger, state)
        if target is None:
            raise LedgerError(f'No verdict can be recorded: plan {name} is {state["status"]}' + (
                ' (the owner decides the next step; see the question on the plan)' if state['status'] == 'stopped_with_report' else '') + '.')
        revision = target['revision']                    # the latest, or the approved one while an amendment waits (unchanged milestones only)
        contract, sha = plans.load(ledger, state, revision)
        views = plans.milestone_views(contract, state, revision, ledger)     # a pass counts while it still covers the artifact (carried over a wording-only amendment or a neutral-only commit)
        index = next((i for i, m in enumerate(contract['milestones']) if m['id'] == milestone_id), None)
        if index is None: raise LedgerError('Unknown milestone ' + milestone_id + '.')
        _refuse_frozen(name, target, milestone_id)
        milestone, view = contract['milestones'][index], views[index]
        earlier = [v['id'] for v in views[:index] if v['state'] != 'passed' and not v.get('stale')]    # a pass the artifact has since left still counts for the order; acceptance is what refuses it
        if earlier: raise LedgerError('Milestone ' + earlier[0] + ' has not passed yet; milestones go in order.')
        if view['state'] == 'passed' and view['last_verdict']['artifact_sha'] == artifact_sha:
            raise LedgerError(f'Milestone {milestone_id} already passed on revision {revision} for this artifact.')
        if receipt_bytes is not None:
            if milestone['verifier']['type'] != 'owner-manual':
                raise LedgerError('A receipt file is accepted only for an owner-manual milestone; a command or reviewer milestone is verified by verdict run.')
            receipt = Snapshots(ledger.state_root).blob(receipt_bytes)
        body = _check_receipt(ledger, name, revision, sha, milestone, result, by, artifact_sha, receipt, state['issued'])
        base = {'plan': name, 'revision': revision, 'milestone': milestone_id, 'plan_sha': sha}
        extra = ({'independence': body['independence']['level'], 'model': body['config']['model'], 'calls': body['calls']}
                 if body and body.get('kind') == 'reviewer-receipt' else {})
        plans.emit(ledger, conn, state['task_id'], 'verdict.recorded', dict(base, result=result, by=by, receipt=receipt,
                                                                            artifact_sha=artifact_sha, run=view['runs'] + 1,
                                                                            cwd=body.get('cwd') if body else None, **extra,
                                                                            **({'reference': reference} if reference else {})))
        if result == 'pass':
            plans.emit(ledger, conn, state['task_id'], 'milestone.passed', dict(base, artifact_sha=artifact_sha))
        else:
            failures = view['failures'] + 1
            left = max(0, milestone['max_repairs'] - failures)
            plans.emit(ledger, conn, state['task_id'], 'milestone.failed', dict(base, result=result, failures=failures, repairs_left=left))
            reason = stop_reason(contract, state, views, milestone, failures, artifact_sha, revision)
            if reason:
                stopped = dict(base, failures=failures, max_repairs=milestone['max_repairs'], reason=reason, mode=milestone['mode'])
                plans.emit(ledger, conn, state['task_id'], 'milestone.stopped', stopped)
        limit = contract['attention']['questions']
        anchor = state['task_id']
    escalation = _escalate(ledger, name, anchor, stopped, limit) if stopped else None
    from . import active_plan; active_plan.export(ledger, name)  # L2: the hooks see the new milestone state
    out = plans.show(ledger, name, revision)         # the revision the verdict was about (the approved one while an amendment waits)
    if escalation: out['stopped'] = escalation
    return out


def stuck_streak(state, revision, milestone_id, artifact_sha):
    """How many failing verdicts in a row (the one being recorded included) this milestone has had on exactly this artifact."""
    streak = 1
    for v in reversed([v for v in state['verdicts'] if v['revision'] == revision and v['milestone'] == milestone_id]):
        if v['result'] == 'pass' or v['artifact_sha'] != artifact_sha: break
        streak += 1
    return streak


def _refuse_frozen(name, target, milestone_id):
    """While an amendment waits for the owner, a milestone it changed does not run: not on the approved revision (its contract is being
    replaced) and not on the pending one (not approved)."""
    frozen = target['frozen']
    if frozen and milestone_id in frozen['frozen']:
        raise LedgerError(f'Milestone {milestone_id} of plan {name} is frozen: revision {frozen["pending_revision"]} changes it and is not approved yet. '
                          f'Unchanged milestones ({", ".join(frozen["runnable"]) or "none"}) still run on revision {frozen["approved_revision"]}.')


def stop_reason(contract, state, views, milestone, failures, artifact_sha, revision=None):
    """Why the verdict being recorded (a failure, already counted in `failures`) stops the plan, or None. The caps are the approved contract's: the AI cannot widen them."""
    limits = contracts.stop_limits(contract)
    revision = revision or state['latest']
    if failures > milestone['max_repairs']: return 'max_repairs exceeded'
    if sum(v['failures'] for v in views) + 1 > limits['max_repairs_total']:
        return f'max_repairs_total exceeded ({limits["max_repairs_total"]} failed verdicts over all milestones)'
    if stuck_streak(state, revision, milestone['id'], artifact_sha) >= limits['max_stuck']:
        return f'max_stuck reached ({limits["max_stuck"]} failures in a row on an unchanged artifact)'
    return None


def _escalate(ledger, name, anchor, stopped, limit):
    """One question to the owner (counted in attention.questions); past the limit the stop stays and the question is refused."""
    used = [r for r in ledger.requests(anchor) if r['question'].get('action', {}).get('type') in ('v2.plan_stopped', 'v2.item_budget')]
    key = f'v2q-{name}-r{stopped["revision"]}-{stopped["milestone"]}'[:128]
    if len(used) >= limit and not any(r['question']['action']['parameters'].get('key') == key for r in used):
        with ledger.transaction(write=True) as conn:
            plans.emit(ledger, conn, anchor, 'attention.exceeded', {'plan': name, 'limit': limit, 'milestone': stopped['milestone']})
        return {'question': 'refused', 'reason': f'attention.questions={limit} already used; the plan stays stopped_with_report'}
    question = {'schema_version': 1,
                'question': f'Milestone {stopped["milestone"]} of plan {name} failed {stopped["failures"]} times ({stopped["reason"]}; max_repairs={stopped["max_repairs"]}). What now?',
                'reason': 'A stop limit set in the approved plan was reached; the AI cannot extend it.',
                'impact': 'The plan is stopped_with_report: nothing further is dispatched until the owner amends and re-approves it, or ends it.',
                'options': [{'id': 'amend_plan', 'label': 'Amend the plan (new revision, new approval) and continue'},
                            {'id': 'stop', 'label': 'End the task; keep the evidence'}],
                'recommendation': 'amend_plan',
                'action': {'type': 'v2.plan_stopped', 'parameters': {'plan': name, 'revision': stopped['revision'],
                                                                     'milestone': stopped['milestone'], 'key': key}}}
    created = ledger.create_request(anchor, key, question)
    return {'question': 'created', 'request': created['id'], 'revision': created['revision']}


def inside_project(ledger, directory):
    """The resolved directory, which must be the project or inside it (F3): a verdict speaks about the project's tree, not a clone."""
    resolved = Path(directory).resolve()
    if not resolved.is_relative_to(Path(ledger.project).resolve()):
        raise LedgerError(f'Verifier directory {resolved} is outside the plan project {ledger.project}; refused.')
    # C6: a clean clone nested inside the project is inside the path but is another repository, so its tree is not the project's.
    mine, theirs = command.toplevel(resolved), command.toplevel(ledger.project)
    if os.path.normcase(str(mine)) != os.path.normcase(str(theirs)):
        raise LedgerError(f'Verifier directory {resolved} belongs to the Git repository {mine}, not the project repository {theirs}; refused.')
    return resolved


def _receipt_body(ledger, receipt):
    try:
        body = json.loads(Snapshots(ledger.state_root).read_blob(receipt).decode('utf-8'))
    except (OSError, ValueError, LedgerError, AttributeError):
        return {}
    return body if isinstance(body, dict) else {}


def _review_context(ledger, conn, state, milestone_id, config):
    """(base event, (artifact, tracked tree) of this milestone's latest usable pass or None): where the reviewer's diff starts.
    A usable pass is a reviewer verdict of this milestone, on any revision, whose receipt recorded the very same reviewer config (a changed config or
    criteria is a different review) and a tracked_tree. Without one the diff starts from base_tracked of the first approval (reviewer.review_diff)."""
    first = conn.execute("SELECT payload FROM events WHERE task_id=? AND kind='plan.approved' ORDER BY seq LIMIT 1", (state['task_id'],)).fetchone()
    if first is None: raise LedgerError(f'Plan {state["name"]} has no plan.approved event; the reviewer has no base tree.')
    for v in reversed([v for v in state['verdicts'] if v['milestone'] == milestone_id and v['result'] == 'pass' and v.get('by') == 'reviewer']):
        body = _receipt_body(ledger, v.get('receipt'))
        tracked = body.get('tracked_tree')
        if body.get('config') == config and isinstance(tracked, str) and tracked:
            return reviewer.base_event(json.loads(first['payload']), state['accepted']), (v['artifact_sha'], tracked)
    return reviewer.base_event(json.loads(first['payload']), state['accepted']), None


def _directory(ledger, milestone, directory):
    configured = milestone['verifier']['config'].get('cwd')
    return inside_project(ledger, directory or (Path(ledger.project) / configured if configured else ledger.project))


def diff(ledger, name, milestone_id):
    """The diff `verdict run` would send the reviewer of this milestone, as text. No model call, nothing written, no earlier milestone needed."""
    with ledger.transaction() as conn:
        state = plans.anchor_events(ledger, conn, name)
        target = plans.resolve(ledger, state)
        if target is None: raise LedgerError(f'Plan {name} is {state["status"]}; nothing to review.')
        contract = plans.load(ledger, state, target['revision'])[0]
        milestone = next((m for m in contract['milestones'] if m['id'] == milestone_id), None)
        if milestone is None: raise LedgerError('Unknown milestone ' + milestone_id + '.')
        if milestone['verifier']['type'] != 'reviewer': raise LedgerError('Milestone ' + milestone_id + ' is not verified by a reviewer.')
        approved, previous = _review_context(ledger, conn, state, milestone_id, milestone['verifier']['config'])
    return reviewer.review_diff(_directory(ledger, milestone, None), approved, previous)[0]


def artifact(ledger, name):
    """The artifact sha of the project now (what a verdict run now would observe, and what `owner accept --artifact-sha` takes)."""
    with ledger.transaction() as conn:
        plans.anchor_events(ledger, conn, name)
    return {'artifact_sha': command.artifact_sha(ledger.project)}


def run(ledger, name, milestone_id, directory=None):
    """Run the milestone's `command` or `reviewer` verifier. This is the only way to a verdict for such a milestone: the receipt is
    announced in the ledger (verdict.receipt_issued) before it is recorded, and record() accepts no other receipt."""
    with ledger.transaction() as conn:
        state = plans.anchor_events(ledger, conn, name)
        target = plans.resolve(ledger, state)
        if target is None: raise LedgerError(f'Plan {name} is {state["status"]}; nothing to verify.')
        revision = target['revision']                    # the approved revision, which is not the latest while an amendment waits
        contract, sha = plans.load(ledger, state, revision)
        _refuse_frozen(name, target, milestone_id)
        written = state['revisions'][revision]
        index = next((i for i, m in enumerate(contract['milestones']) if m['id'] == milestone_id), None)
        if index is not None:       # refused before the verifier runs (a reviewer call costs money): the same two refusals record() makes afterwards
            views = plans.milestone_views(contract, state, revision, ledger)
            earlier = [v['id'] for v in views[:index] if v['state'] != 'passed' and not v.get('stale')]    # a pass the artifact has since left still counts for the order; acceptance is what refuses it
            if earlier: raise LedgerError('Milestone ' + earlier[0] + ' has not passed yet; milestones go in order.')
            if views[index]['state'] == 'passed' and not views[index].get('neutral_diff'):
                raise LedgerError(f'Milestone {milestone_id} already passed on revision {revision} for this artifact.')
        picked = next((m for m in contract['milestones'] if m['id'] == milestone_id), None)
        approved, previous = _review_context(ledger, conn, state, milestone_id, picked['verifier']['config'] if picked else None)
    milestone = next((m for m in contract['milestones'] if m['id'] == milestone_id), None)
    if milestone is None: raise LedgerError('Unknown milestone ' + milestone_id + '.')
    kind, config = milestone['verifier']['type'], milestone['verifier']['config']
    if kind not in KINDS: raise LedgerError('Milestone ' + milestone_id + ' is not verified by a command or a reviewer.')
    directory = _directory(ledger, milestone, directory)
    if kind == 'command':
        blob, receipt = command.run(ledger, name, revision, sha, milestone, directory)
    else:
        level = reviewer.check_independence(written, config)       # before any call: a reviewer that is the author costs nothing
        blob, receipt = reviewer.run(ledger, name, revision, sha, milestone, directory, level, approved, previous)
    with ledger.transaction(write=True) as conn:
        current = plans.anchor_events(ledger, conn, name)
        again = plans.resolve(ledger, current)
        if again is None or again['revision'] != revision or (again['frozen'] and milestone_id in again['frozen']['frozen']): raise LedgerError(f'The plan changed while the {kind} ran; run it again.')
        plans.emit(ledger, conn, current['task_id'], 'verdict.receipt_issued',
                   {'plan': name, 'revision': revision, 'milestone': milestone_id, 'receipt': blob, 'cwd': str(directory)})
    return record(ledger, name, milestone_id, (command if kind == 'command' else reviewer).expected_result(receipt), kind, blob, receipt['artifact_sha'])
