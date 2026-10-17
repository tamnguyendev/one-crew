"""Verdicts at milestones (invariant 4: a milestone without a passing verdict is not passed). Each verdict is bound to the plan
revision, the milestone and the sha of the artifact that was observed; a `command` verdict needs a genuine receipt blob."""
import json
import re

from ..ledger import LedgerError, key_field, text_field
from ..snapshots import Snapshots
from . import plan as plans
from .verifiers import command

RESULTS = ('pass', 'fail', 'inconclusive')
SHA = re.compile(r'[0-9a-f]{40}|[0-9a-f]{64}')


def _blob(ledger, key):
    try:
        return Snapshots(ledger.state_root).read_blob(key)
    except (OSError, LedgerError) as error:
        raise LedgerError('Receipt is not a blob in this state root: ' + str(error)[:120]) from error


def _check_receipt(ledger, name, revision, plan_sha, milestone, result, by, artifact, receipt):
    verifier = milestone['verifier']['type']
    data = _blob(ledger, receipt)
    if verifier == 'owner-manual':
        if by != 'owner': raise LedgerError('Milestone ' + milestone['id'] + ' is verified by the owner: --by owner.')
        return
    if by != verifier: raise LedgerError(f'Milestone {milestone["id"]} is verified by {verifier}, not {by}.')
    try:
        body = json.loads(data.decode('utf-8'))
    except ValueError as error:
        raise LedgerError('Receipt is not a command receipt.') from error
    if body.get('kind') != 'command-receipt': raise LedgerError('Receipt is not a command receipt.')
    for field, want in (('plan', name), ('revision', revision), ('plan_sha', plan_sha), ('milestone', milestone['id']),
                        ('argv', milestone['verifier']['config']['argv'])):
        if body.get(field) != want: raise LedgerError(f'Receipt does not belong to this plan/milestone ({field} differs).')
    if body.get('artifact_sha') != artifact:
        raise LedgerError(f'Artifact sha {artifact} does not match the one the receipt observed ({body.get("artifact_sha")}).')
    expected = command.expected_result(body)
    if result != expected: raise LedgerError(f'Receipt supports a {expected} verdict, not {result}.')


def record(ledger, name, milestone_id, result, by, receipt, artifact_sha):
    if result not in RESULTS: raise LedgerError('Result must be pass, fail or inconclusive.')
    if not isinstance(artifact_sha, str) or not SHA.fullmatch(artifact_sha): raise LedgerError('artifact sha must be a 40/64-hex hash.')
    key_field(milestone_id); text_field(by, 'by', 60)
    if by == 'owner': plans.require_owner(by, 'An owner verdict')
    stopped = None
    with ledger.transaction(write=True) as conn:
        state = plans.anchor_events(ledger, conn, name)
        if state['status'] != 'approved':
            raise LedgerError(f'No verdict can be recorded: plan {name} is {state["status"]}' + (
                ' (the owner decides the next step; see the question on the plan)' if state['status'] == 'stopped_with_report' else '') + '.')
        revision = state['latest']
        contract, sha = plans.load(ledger, state, revision)
        views = plans.milestone_views(contract, state, revision)
        index = next((i for i, m in enumerate(contract['milestones']) if m['id'] == milestone_id), None)
        if index is None: raise LedgerError('Unknown milestone ' + milestone_id + '.')
        milestone, view = contract['milestones'][index], views[index]
        earlier = [v['id'] for v in views[:index] if v['state'] != 'passed']
        if earlier: raise LedgerError('Milestone ' + earlier[0] + ' has not passed yet; milestones go in order.')
        if view['state'] == 'passed': raise LedgerError(f'Milestone {milestone_id} already passed on revision {revision}.')
        _check_receipt(ledger, name, revision, sha, milestone, result, by, artifact_sha, receipt)
        base = {'plan': name, 'revision': revision, 'milestone': milestone_id, 'plan_sha': sha}
        plans.emit(ledger, conn, state['task_id'], 'verdict.recorded', dict(base, result=result, by=by, receipt=receipt,
                                                                            artifact_sha=artifact_sha, run=view['runs'] + 1))
        if result == 'pass':
            plans.emit(ledger, conn, state['task_id'], 'milestone.passed', dict(base, artifact_sha=artifact_sha))
        else:
            failures = view['runs'] + 1  # a pass is final, so every earlier run on this revision was a non-pass
            left = max(0, milestone['max_repairs'] - failures)
            plans.emit(ledger, conn, state['task_id'], 'milestone.failed', dict(base, result=result, failures=failures, repairs_left=left))
            if failures > milestone['max_repairs']:
                stopped = dict(base, failures=failures, max_repairs=milestone['max_repairs'], reason='max_repairs exceeded', mode=milestone['mode'])
                plans.emit(ledger, conn, state['task_id'], 'milestone.stopped', stopped)
        limit = contract['attention']['questions']
        anchor = state['task_id']
    escalation = _escalate(ledger, name, anchor, stopped, limit) if stopped else None
    out = plans.show(ledger, name)
    if escalation: out['stopped'] = escalation
    return out


def _escalate(ledger, name, anchor, stopped, limit):
    """One question to the owner (counted in attention.questions); past the limit the stop stays and the question is refused."""
    used = [r for r in ledger.requests(anchor) if r['question'].get('action', {}).get('type') == 'v2.plan_stopped']
    key = f'v2q-{name}-r{stopped["revision"]}-{stopped["milestone"]}'[:128]
    if len(used) >= limit and not any(r['question']['action']['parameters'].get('key') == key for r in used):
        with ledger.transaction(write=True) as conn:
            plans.emit(ledger, conn, anchor, 'attention.exceeded', {'plan': name, 'limit': limit, 'milestone': stopped['milestone']})
        return {'question': 'refused', 'reason': f'attention.questions={limit} already used; the plan stays stopped_with_report'}
    question = {'schema_version': 1,
                'question': f'Milestone {stopped["milestone"]} of plan {name} failed {stopped["failures"]} times (max_repairs={stopped["max_repairs"]}). What now?',
                'reason': 'The repair limit set in the approved plan was reached; the AI cannot extend it.',
                'impact': 'The plan is stopped_with_report: nothing further is dispatched until the owner amends and re-approves it, or ends it.',
                'options': [{'id': 'amend_plan', 'label': 'Amend the plan (new revision, new approval) and continue'},
                            {'id': 'stop', 'label': 'End the task; keep the evidence'}],
                'recommendation': 'amend_plan',
                'action': {'type': 'v2.plan_stopped', 'parameters': {'plan': name, 'revision': stopped['revision'],
                                                                     'milestone': stopped['milestone'], 'key': key}}}
    created = ledger.create_request(anchor, key, question)
    return {'question': 'created', 'request': created['id'], 'revision': created['revision']}


def run(ledger, name, milestone_id, directory=None):
    """Run the milestone's `command` verifier and record the verdict its receipt supports."""
    with ledger.transaction() as conn:
        state = plans.anchor_events(ledger, conn, name)
        if state['status'] != 'approved': raise LedgerError(f'Plan {name} is {state["status"]}; nothing to verify.')
        contract, sha = plans.load(ledger, state)
        revision = state['latest']
    milestone = next((m for m in contract['milestones'] if m['id'] == milestone_id), None)
    if milestone is None: raise LedgerError('Unknown milestone ' + milestone_id + '.')
    if milestone['verifier']['type'] != 'command': raise LedgerError('Milestone ' + milestone_id + ' is not verified by a command.')
    directory = directory or milestone['verifier']['config']['cwd'] or ledger.project
    blob, receipt = command.run(ledger, name, revision, sha, milestone, directory)
    return record(ledger, name, milestone_id, command.expected_result(receipt), 'command', blob, receipt['artifact_sha'])
