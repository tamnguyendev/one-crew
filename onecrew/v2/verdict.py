"""Verdicts at milestones (invariant 4: a milestone without a passing verdict is not passed). Each verdict is bound to the plan
revision, the milestone and the sha of the artifact that was observed; a `command` verdict needs a genuine receipt blob."""
import datetime as dt
import platform
import uuid
import json
import os
import re
from pathlib import Path

from ..ledger import LedgerError, canonical, key_field, text_field, utcnow
from ..snapshots import Snapshots
from . import contract as contracts, namespaces, plan as plans
from .verifiers import command, reviewer, port, artifact as artifacts

KINDS = {'command': 'command-receipt', 'reviewer': 'reviewer-receipt'}
RESULTS = ('pass', 'fail', 'inconclusive')
SHA = re.compile(r'[0-9a-f]{40}|[0-9a-f]{64}')


def _blob(ledger, key):
    try:
        return Snapshots(ledger.state_root).read_blob(key)
    except (OSError, LedgerError) as error:
        raise LedgerError('Receipt is not a blob in this state root: ' + str(error)[:120]) from error


def _check_receipt(ledger, name, revision, plan_sha, milestone, result, by, artifact, receipt, issued, integrity=None):
    verifier = milestone['verifier']['type']
    data = _blob(ledger, receipt)
    if verifier == 'owner-manual':
        if by != 'owner': raise LedgerError('Milestone ' + milestone['id'] + ' is verified by the owner: --by owner.')
        return
    if by != verifier: raise LedgerError(f'Milestone {milestone["id"]} is verified by {verifier}, not {by}.')
    kind = KINDS.get(verifier) or port.receipt_kind(verifier)
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
    expected = integrity_result(_result(verifier, body), integrity)   # W05/T19: a green command on a weakened suite supports a fail (U1), on an unproven one at most inconclusive
    if result != expected: raise LedgerError(f'Receipt supports a {expected} verdict, not {result}.')
    # A well-formed receipt is not enough: it must be one that verdict.run issued. Anything hand-written is refused (F1).
    if (revision, milestone['id'], receipt) not in issued:
        raise LedgerError(f'This receipt was not issued by verdict run. A {verifier} milestone is verified only by verdict run.')
    return body


def _result(kind, receipt):
    return (command if kind == 'command' else reviewer if kind == 'reviewer' else port).expected_result(receipt)


def integrity_result(result, integrity):
    """W05/T19: what a command result supports once the test suite is compared with the approved base. A pass on a weakened suite is a
    fail (U1); a pass on a suite this analysis cannot prove intact (insufficient) is at most inconclusive; a fail stays a fail."""
    if result != 'pass' or not integrity: return result
    if integrity.get('weakened'): return 'fail'
    if integrity.get('insufficient') or integrity.get('error'): return 'inconclusive'
    return result


def record(ledger, name, milestone_id, result, by, receipt, artifact_sha, receipt_bytes=None, reference=None, integrity=None):
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
        body = _check_receipt(ledger, state['name'], revision, sha, milestone, result, by, artifact_sha, receipt, state['issued'], integrity=integrity)
        if body and result == 'pass' and namespaces.has_capability(state, 'sequential-engine'):
            from . import verification_evidence
            verification_evidence.require_binding(body)
        from .retention import pin_evidence
        if result == 'pass' and set(artifact_sha) == {'0'}:
            raise LedgerError('A passing verdict requires an artifact, not the null tree id.')
        pin_evidence(ledger, name, artifact_sha, body, strict=milestone['verifier']['type'] != 'owner-manual')
        base = {'plan': state['name'], 'revision': revision, 'milestone': milestone_id, 'plan_sha': sha}
        if body and 'generation' in body:
            base['generation'] = body['generation']
        extra = ({'independence': body['independence']['level'], 'model': body['config']['model'], 'calls': body['calls'],
                  'provider': body['config']['provider'], **({'provider_error': body['provider_error']} if body.get('provider_error') else {})}     # W43: who answered; a usage limit is named here
                 if body and body.get('kind') == 'reviewer-receipt' else {})
        if body and (body.get('kind') == 'command-receipt' or port.known(milestone['verifier']['type'])):
            extra['calls'] = body.get('calls', 0)
        if integrity and (integrity.get('weakened') or integrity.get('added') or integrity.get('insufficient') or integrity.get('error')):     # W05/T19
            extra['test_integrity'] = {'weakened': integrity.get('weakened', [])[:20], 'added': integrity.get('added', [])[:20],
                                       'insufficient': integrity.get('insufficient', [])[:20],
                                       'receipt': integrity.get('receipt'), 'classification': integrity.get('classification'),
                                       'base': integrity.get('base'), 'error': integrity.get('error')}
        plans.emit(ledger, conn, state['task_id'], 'verdict.recorded', dict(base, result=result, by=by, receipt=receipt,
                                                                            artifact_sha=artifact_sha, run=view['runs'] + 1,
                                                                            cwd=body.get('cwd') if body else None, **extra,
                                                                            **({'reference': reference} if reference else {})))
        # W17: the authentic verdict and its findings commit together. A crash
        # cannot publish a failed criterion without its durable open finding.
        if body and (body.get('kind') == 'reviewer-receipt' or port.known(milestone['verifier']['type'])) and namespaces.has_capability(state, 'finding-register'):
            from . import findings
            findings.record_verification(ledger, name, milestone_id, receipt, conn=conn, task_id=state['task_id'],
                                         revision=revision, generation=body.get('generation', 1), write=contract['scope']['owned'])
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
    # Learning follows authentic committed evidence; failure must not rewrite
    # the verifier result. Replaying the hook can reconcile an interrupted write.
    try:
        from . import incidents
        incidents.after_verdict(ledger, name, milestone_id, receipt)
    except Exception as error:
        import sys
        print('OneCrew learning pending: ' + type(error).__name__ + ': ' + str(error)[:200], file=sys.stderr)
    from . import active_plan; active_plan.export(ledger, name)  # L2: the hooks see the new milestone state
    if body and namespaces.has_capability(state, 'finding-register'):
        from . import findings
        findings.after_change(ledger, name)                        # W36: a running managed attempt of a node a new finding holds is asked to pause
    out = plans.show(ledger, name, revision)         # the revision the verdict was about (the approved one while an amendment waits)
    if escalation: out['stopped'] = escalation
    if result != 'pass':
        from . import outcome
        outcome.note(ledger, name)
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
    criteria is a different review) and a tracked_tree that is a tree id. Without one the diff starts from base_tracked of the first approval (reviewer.review_diff)."""
    first = conn.execute("SELECT payload FROM events WHERE task_id=? AND kind='plan.approved' ORDER BY seq LIMIT 1", (state['task_id'],)).fetchone()
    if first is None: raise LedgerError(f'Plan {state["name"]} has no plan.approved event; the reviewer has no base tree.')
    for v in reversed([v for v in state['verdicts'] if v['milestone'] == milestone_id and v['result'] == 'pass' and v.get('by') == 'reviewer']):
        body = _receipt_body(ledger, v.get('receipt'))
        tracked = body.get('tracked_tree')
        # a tree id read from a receipt is given to git later, so only a 40/64-hex one is a base; anything else is as if the pass had recorded none
        if body.get('config') == config and isinstance(tracked, str) and command.TREE_ID.fullmatch(tracked) and command.TREE_ID.fullmatch(str(v.get('artifact_sha'))):
            return reviewer.base_event(json.loads(first['payload']), state['accepted']), (v['artifact_sha'], tracked)
    return reviewer.base_event(json.loads(first['payload']), state['accepted']), None


def _directory(ledger, milestone, directory):
    configured = milestone['verifier']['config'].get('cwd')
    if port.known(milestone['verifier']['type']) and not artifacts.is_git(ledger.project):
        resolved = Path(directory or ledger.project).resolve()
        if resolved != Path(ledger.project).resolve():
            raise LedgerError('A snapshot verifier must run at the plan project folder.')
        return resolved
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
    return {'artifact_sha': artifacts.identity(ledger.project)}


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
    if kind not in KINDS and not port.known(kind): raise LedgerError('Milestone ' + milestone_id + ' has no executable verifier.')
    directory = _directory(ledger, milestone, directory)
    level = reviewer.check_independence(written, config) if kind == 'reviewer' else None
    minutes = config.get('max_minutes') or config['authority']['max_minutes']
    bounded = {}
    if namespaces.has_capability(state, 'root-budget'):
        from . import internal_plan
        with ledger.transaction() as conn:
            remaining = internal_plan.ceilings(ledger, conn, state)
        if remaining['remaining_seconds'] <= 0:
            raise LedgerError('The original root deadline is exhausted; no verifier starts.')
        minutes = min(minutes, remaining['remaining_seconds'] / 60)
        bounded = {'deadline': remaining['deadline']}
    recovered = reconcile(ledger, name, revision, milestone_id)           # W37a: a run of unknown outcome is settled, or held, before any new dispatch
    if recovered is not None:
        return recovered
    run_id = _begin_run(ledger, name, revision, milestone_id, kind, minutes)
    evidence_context = ({'evidence_context': {'selector': state['selector'], 'revision': revision, 'contract': contract}}
                        if namespaces.has_capability(state, 'sequential-engine') else {})
    integrity = None
    try:
        _mark(ledger, run_id, 'dispatched', {'plan': name, 'revision': revision, 'milestone': milestone_id, 'kind': kind, 'at': utcnow()})
        if kind == 'command':
            blob, receipt = command.run(ledger, state['name'], revision, sha, milestone, directory, **evidence_context, **bounded)
            integrity = _test_integrity(ledger, directory, approved, receipt)          # W05/T19: a weakened test suite cannot make the milestone pass
        elif kind == 'reviewer':
            context = dict(evidence_context)
            if namespaces.has_capability(state, 'root-budget'):
                from .metered_verifier import ProviderCall
                context['call_port'] = ProviderCall(ledger, state['selector'], 'milestone:' + milestone_id)
            if namespaces.has_capability(state, 'finding-register'):
                from . import findings
                context['open_findings'] = findings.reviewer_context(ledger, name, milestone_id, task_id=state['task_id'])
            blob, receipt = reviewer.run(ledger, state['name'], revision, sha, milestone, directory, level, approved, previous, **context)
        else:
            blob, receipt = port.run(ledger, state['name'], revision, sha, milestone, directory, **evidence_context, **bounded)
            port.record_violations(ledger, name, revision, milestone_id, blob, receipt)
        _mark(ledger, run_id, 'receipt', {'blob': blob, 'receipt': receipt, 'integrity': integrity, 'cwd': str(directory)})   # the effect is known from here on
        with ledger.transaction(write=True) as conn:
            current = plans.anchor_events(ledger, conn, name)
            again = plans.resolve(ledger, current)
            if again is None or again['revision'] != revision or (again['frozen'] and milestone_id in again['frozen']['frozen']): raise LedgerError(f'The plan changed while the {kind} ran; run it again.')
            from .retention import pin_evidence
            pin_evidence(ledger, name, receipt['artifact_sha'], receipt, strict=True)
            plans.emit(ledger, conn, current['task_id'], 'verdict.receipt_issued',
                       {'plan': current['name'], 'revision': revision, 'milestone': milestone_id, 'receipt': blob, 'cwd': str(directory), 'run_id': run_id})
    except BaseException as error:
        _abandon_own(ledger, name, run_id, error)
        raise
    result = integrity_result(_result(kind, receipt), integrity)      # T19 [E1]/[E3]: red on a weakened suite, not green on an unproven one
    shown = record(ledger, name, milestone_id, result, kind, blob, receipt['artifact_sha'], integrity=integrity)
    _unmark(ledger, run_id)
    return shown


# ---- W37a: reconcile a run of unknown outcome before any retry (T08a) -------------------------------------------------------------------
#
# The verifier (a command that may write outside the checkout, a reviewer that costs a model call) is X. Around X the run keeps two durable
# markers under <state root>/verdict-runs/<run_id>/: `dispatched` right before X starts, `receipt` right after X returned (before the ledger
# announces the receipt). When a run was abandoned by a lost process (crash at (b) during X, or at (c) after X and before the receipt event),
# the NEXT `verdict run` of the same milestone reconciles first, writes `verdict.run_reconciled`, and only then decides:
#   receipt marker present  -> X finished: the receipt is issued and recorded from the marker, nothing runs again (determination 'completed');
#   dispatched only         -> the outcome is unknown: `verdict.run_held`, the run is reported, and NO new dispatch happens until someone
#                              releases it with `verdict release-run --reason` (verdict.run_released; the decision is recorded, never implied);
#   no marker               -> X never started ('not_dispatched'); a run the process itself closed with reason 'error' is a known outcome too.
# Exactly-once is not promised: a release lets X run a second time, and the record says so.

RUNS_DIR = 'verdict-runs'
RECONCILE_KINDS = ('verdict.run_reconciled', 'verdict.run_held', 'verdict.run_released')


def _run_dir(ledger, run_id):
    return Path(ledger.state_root) / RUNS_DIR / str(run_id)


def _mark(ledger, run_id, marker, body):
    folder = _run_dir(ledger, run_id)
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / (marker + '.json')
    temp = folder / (marker + '.json.tmp')
    temp.write_text(json.dumps(body, ensure_ascii=False), encoding='utf-8')
    os.replace(temp, target)                                        # the marker exists whole or not at all


def _unmark(ledger, run_id):
    import shutil
    shutil.rmtree(_run_dir(ledger, run_id), ignore_errors=True)


def _marker(ledger, run_id, marker):
    try:
        return json.loads((_run_dir(ledger, run_id) / (marker + '.json')).read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return None


def _reconcile_events(conn, task_id):
    rows = {}
    for event in conn.execute(f"SELECT seq,kind,payload FROM events WHERE task_id=? AND kind IN ({','.join('?' * len(RECONCILE_KINDS))}) ORDER BY seq",
                              (task_id, *RECONCILE_KINDS)):
        p = json.loads(event['payload'])
        rows.setdefault(p.get('run_id'), {})[event['kind']] = dict(p, seq=event['seq'])
    return rows


def held_runs(conn, task_id):
    """The runs held with an unknown outcome and not released (run_id -> the hold record). A run is held as soon as its reconcile record
    says `unknown` — the hold is that record, not a second event, so no write boundary can leave an unknown run unheld."""
    return {run_id: _hold_of(rows) for run_id, rows in _reconcile_events(conn, task_id).items() if _hold_of(rows) is not None}


def _hold_of(rows):
    if 'verdict.run_released' in rows: return None
    held = rows.get('verdict.run_held')
    reconciled = rows.get('verdict.run_reconciled')
    if held is not None: return held
    if reconciled is not None and reconciled.get('determination') == 'unknown': return reconciled
    return None


def _held_message(run, hold):
    return (f"Milestone {run.get('milestone')} has a run of unknown outcome (run {run.get('run_id')}, revision {run.get('revision')}, dispatched "
            f"{hold.get('dispatched_at')}, process lost: {hold.get('abandoned_reason')}). It is held and not run again by itself: check what the "
            f"verifier did, then `onecrew verdict release-run --plan {run.get('plan')} --run {run.get('run_id')} --reason ...`.")


def _reconciled_payload(name, run, determination, detail):
    return {'plan': name, 'revision': run.get('revision'), 'milestone': run.get('milestone'), 'run_id': run.get('run_id'), 'kind': run.get('kind'),
            'abandoned_reason': (run.get('abandoned') or {}).get('reason'), 'determination': determination, 'detail': detail,
            'established': determination not in ('unknown',)}          # reconciled != determined: only `established` records settle the outcome


def _emit_reconciled(ledger, name, run, determination, detail, conn=None):
    if conn is None:
        with ledger.transaction(write=True) as connection:
            return _emit_reconciled(ledger, name, run, determination, detail, connection)
    current = plans.anchor_events(ledger, conn, name)
    plans.emit(ledger, conn, current['task_id'], 'verdict.run_reconciled', _reconciled_payload(name, run, determination, detail))


def reconcile(ledger, name, revision, milestone_id):
    """Before any new run of `milestone_id`, settle every earlier run of that milestone (any revision) whose end is not recorded:
      * a held run (unknown outcome, not released)             -> raise: nothing is dispatched;
      * a receipt issued but its verdict not recorded           -> record it from that receipt (no second X); returns the state;
      * an abandoned run with a receipt marker                  -> issue + record the old run's receipt (no second X); returns the state;
      * an abandoned run with only the `dispatched` marker      -> ONE write: `run_reconciled(unknown)` (which IS the hold) + `run_held`; raise;
      * an abandoned run with no marker, or closed by its own error -> `run_reconciled(not_dispatched|raised)`; a new run may start.
    Returns None when a new run may start. Idempotent: a second call writes nothing new."""
    reap(ledger, name)
    with ledger.transaction() as conn:
        state = plans.anchor_events(ledger, conn, name)
        runs = [r for r in run_records(conn, state['task_id']) if r.get('milestone') == milestone_id]
        events = _reconcile_events(conn, state['task_id'])
        recorded = {v.get('receipt') for v in state['verdicts']}
    held = [r for r in runs if r.get('run_id') in held_runs_of(events)]
    if held:
        raise LedgerError(_held_message(held[0], _hold_of(events[held[0]['run_id']])))
    for run in runs:
        rows = events.get(run.get('run_id'), {})
        if run['receipt'] is not None:
            if run['receipt'].get('receipt') not in recorded:
                shown = _record_issued(ledger, name, revision, milestone_id, run)
                if shown is not None: return shown
            _unmark(ledger, run['run_id'])
            continue
        if run['abandoned'] is None or 'verdict.run_reconciled' in rows:
            continue
        reason = run['abandoned'].get('reason')
        receipt_marker, dispatched = _marker(ledger, run['run_id'], 'receipt'), _marker(ledger, run['run_id'], 'dispatched')
        if reason == 'error' or dispatched is None:
            _emit_reconciled(ledger, name, run, 'raised' if reason == 'error' else 'not_dispatched', 'a new run may start')
            _unmark(ledger, run['run_id'])
            continue
        if receipt_marker is not None:
            shown = _complete_from_marker(ledger, name, revision, milestone_id, run, receipt_marker)
            if shown is not None: return shown
            continue
        with ledger.transaction(write=True) as conn:                     # the unknown determination and the hold are one write
            current = plans.anchor_events(ledger, conn, name)
            hold = {'plan': name, 'revision': run.get('revision'), 'milestone': milestone_id, 'run_id': run['run_id'], 'kind': run.get('kind'),
                    'dispatched_at': dispatched.get('at'), 'abandoned_reason': reason,
                    'reason': 'The verifier was dispatched and its process was lost before any receipt: its effect (files it wrote, a model call) is unknown. '
                              'It is not run again by itself; release it with `verdict release-run` after checking.'}
            plans.emit(ledger, conn, current['task_id'], 'verdict.run_reconciled',
                       dict(_reconciled_payload(name, run, 'unknown', 'X was dispatched and no receipt exists; held, not run again'), dispatched_at=dispatched.get('at')))
            plans.emit(ledger, conn, current['task_id'], 'verdict.run_held', hold)
        raise LedgerError(_held_message(run, hold))
    return None


def held_runs_of(events):
    return {run_id for run_id, rows in events.items() if _hold_of(rows) is not None}


def _record_issued(ledger, name, revision, milestone_id, run):
    """A receipt that verdict.run issued for this run exists in the ledger but its verdict was never recorded (crash between the two writes).
    Record it from the ledger's own receipt — the one place the result lives — with the integrity record of its marker when present, else
    recomputed against the approved base. Returns the recorded state, or None when the receipt belongs to another revision (then it is
    evidence of a known outcome only; a new run may start and the run is marked reconciled)."""
    issued = run['receipt']
    if issued.get('revision') != revision:
        with ledger.transaction() as conn:
            events = _reconcile_events(conn, plans.anchor_events(ledger, conn, name)['task_id'])
        if 'verdict.run_reconciled' not in events.get(run.get('run_id'), {}):
            _emit_reconciled(ledger, name, run, 'completed_stale', 'the receipt was issued for an earlier revision; its verdict is not recorded on the current one')
        return None
    blob = issued['receipt']
    try:
        body = json.loads(Snapshots(ledger.state_root).read_blob(blob))
    except Exception as error:                                           # noqa: BLE001
        raise LedgerError(f'The issued receipt {blob[:12]} of run {run.get("run_id")} cannot be read; nothing is run again until it is settled: {error}') from error
    marker = _marker(ledger, run['run_id'], 'receipt') or {}
    integrity = marker.get('integrity')
    if integrity is None and run.get('kind') == 'command':
        with ledger.transaction() as conn:
            state = plans.anchor_events(ledger, conn, name)
        integrity = _test_integrity(ledger, Path(issued.get('cwd') or marker.get('cwd') or ledger.project), state['approved'], body)
    shown = record(ledger, name, milestone_id, integrity_result(_result(run.get('kind'), body), integrity), run.get('kind'), blob, body['artifact_sha'], integrity=integrity)
    _unmark(ledger, run['run_id'])
    return shown


def _complete_from_marker(ledger, name, revision, milestone_id, run, marker):
    """Crash at (c): X finished and its receipt is on disk. Issue and record it for the OLD run (no second X). None when the plan moved on
    (the receipt is then evidence of a known outcome only, and a new run may start). The marker is removed only after the verdict is
    recorded, so a crash in between is completed by `_record_issued` on the next call."""
    blob, receipt = marker['blob'], marker['receipt']
    try:
        Snapshots(ledger.state_root).read_blob(blob)
    except Exception:                                               # noqa: BLE001 — the blob did not survive: the outcome is known (finished), not reusable
        _emit_reconciled(ledger, name, run, 'completed_receipt_lost', 'X finished but its receipt blob is missing; a new run may start')
        _unmark(ledger, run['run_id'])
        return None
    with ledger.transaction(write=True) as conn:
        current = plans.anchor_events(ledger, conn, name)
        again = plans.resolve(ledger, current)
        if again is None or again['revision'] != revision or run.get('revision') != revision or (again['frozen'] and milestone_id in again['frozen']['frozen']):
            _emit_reconciled(ledger, name, run, 'completed_stale', 'X finished; the plan changed since, so its receipt is not issued', conn)
            stale = True
        else:
            from .retention import pin_evidence
            pin_evidence(ledger, name, receipt['artifact_sha'], receipt, strict=True)
            _emit_reconciled(ledger, name, run, 'completed', 'X finished before the crash; its receipt is issued, X is not run again', conn)
            plans.emit(ledger, conn, current['task_id'], 'verdict.receipt_issued',
                       {'plan': current['name'], 'revision': revision, 'milestone': milestone_id, 'receipt': blob, 'cwd': marker.get('cwd'), 'run_id': run['run_id'], 'reconciled': True})
            stale = False
    if stale:
        _unmark(ledger, run['run_id'])
        return None
    integrity = marker.get('integrity')
    shown = record(ledger, name, milestone_id, integrity_result(_result(run.get('kind'), receipt), integrity), run.get('kind'), blob, receipt['artifact_sha'], integrity=integrity)
    _unmark(ledger, run['run_id'])
    return shown


def release_run(ledger, name, run_id, reason):
    """The explicit decision that lets a held milestone run again. Records who (ONECREW_ACTOR, as the AI's own name) and why; never implied by
    silence, a restart or a second `verdict run`. It does not change the grant: the next run is checked by the same rules as any run."""
    text_field(reason, 'reason', 2000)
    if not reason.strip(): raise LedgerError('A release needs a reason (what was checked about the lost run).')
    with ledger.transaction(write=True) as conn:
        state = plans.anchor_events(ledger, conn, name)
        held = held_runs(conn, state['task_id'])
        if run_id not in held:
            raise LedgerError(f'Run {run_id} is not held (held now: {", ".join(sorted(held)) or "none"}).')
        hold = held[run_id]
        payload = {'plan': name, 'revision': hold.get('revision'), 'milestone': hold.get('milestone'), 'run_id': run_id,
                   'actor': os.environ.get('ONECREW_ACTOR') or 'unknown', 'reason': reason.strip(),
                   'note': 'A release lets the verifier run a second time; the first dispatch may have had an effect. Exactly-once is not promised.'}
        plans.emit(ledger, conn, state['task_id'], 'verdict.run_released', payload)
    _unmark(ledger, run_id)
    return payload


def _test_integrity(ledger, directory, approved, receipt):
    """T19: compare the test files of the approved base tree with the tree the command ran on. Returns the integrity record (stored as a
    blob and named in the verdict event) or None outside Git / without a base. Added tests carry provenance; weakened ones are U1."""
    from . import test_integrity
    from .verifiers import artifact as identities
    try:
        if not identities.is_git(directory): return None
        base, source = reviewer.base_tree(directory, approved)
        current = receipt.get('artifact_sha')
        if not (isinstance(base, str) and command.TREE_ID.fullmatch(base) and isinstance(current, str) and command.TREE_ID.fullmatch(current)):
            return None
        report = test_integrity.compare(directory, base, current)
    except (LedgerError, OSError, ValueError) as error:
        return {'error': str(error)[:300], 'weakened': [], 'added': [], 'insufficient': [], 'classification': 'insufficient'}   # not told -> not established
    actor = os.environ.get('ONECREW_ACTOR') or 'unknown'
    record_ = dict(report, base_source=source, provenance={'by': actor, 'receipt': None},
                   classification='U1' if report['weakened'] else 'insufficient' if report['insufficient'] else None)
    if report['weakened'] or report['added'] or report['insufficient']:
        record_['receipt'] = Snapshots(ledger.state_root).blob(canonical(record_).encode('utf-8'))
    return record_


# ---- W44: the run itself (verdict.run_started / verdict.run_abandoned, both class A) ---------------------------------------------
#
# A verdict run writes verdict.run_started, then ends in exactly one of four ways, each a final state in the ledger:
#   completed / failed / timed out -> verdict.receipt_issued (the receipt says which) and verdict.recorded, both unchanged;
#   the process dies (SIGKILL, power, crash) -> verdict.run_abandoned, written by the next reader that finds the run lost (reap).
# A run is LOST when its process is not alive on this machine, or when it is past its own deadline (max_minutes + RUN_GRACE_SECONDS, written in the
# event). The deadline is what keeps a pid that was reused, or a run of another machine, from holding "checking" forever. An abandoned run is
# not a verdict: it is not a failure and costs no repair (views count only verdict.recorded).

RUN_GRACE_SECONDS = 120          # after max_minutes: the artifact sha before and after, the clean checkout and the receipt


def this_host():
    return platform.node() or 'unknown'


def process_alive(pid):
    """Is a process with this id running on this machine? (os.kill(pid, 0) would TERMINATE it on Windows, so Windows asks the kernel instead.)"""
    if not isinstance(pid, int) or isinstance(pid, bool) or pid <= 0: return False
    if os.name == 'nt':
        import ctypes
        kernel = ctypes.windll.kernel32
        kernel.OpenProcess.restype = ctypes.c_void_p
        handle = kernel.OpenProcess(0x1000, False, pid)             # PROCESS_QUERY_LIMITED_INFORMATION
        if not handle: return kernel.GetLastError() == 5            # access denied: it exists; anything else: no such process
        try:
            code = ctypes.c_ulong()
            return bool(kernel.GetExitCodeProcess(ctypes.c_void_p(handle), ctypes.byref(code))) and code.value == 259     # STILL_ACTIVE
        finally:
            kernel.CloseHandle(ctypes.c_void_p(handle))
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True


def _when(text):
    try:
        value = dt.datetime.fromisoformat(str(text))
    except ValueError:
        return None
    return value if value.tzinfo else value.replace(tzinfo=dt.timezone.utc)


def _now():
    return dt.datetime.now(dt.timezone.utc)


RUN_KINDS = ('verdict.run_started', 'verdict.run_abandoned', 'verdict.receipt_issued')


def run_records(conn, task_id):
    """One dict per verdict.run_started of the anchor, in order: its payload plus `receipt` (the verdict.receipt_issued that ended it) and
    `abandoned` (the verdict.run_abandoned that closed it), each None until it happens. A receipt without a run_id (written by a version that has no
    run_started) belongs to the latest open run of the same revision and milestone."""
    runs, by_id = [], {}
    for event in conn.execute(f"SELECT seq,kind,payload FROM events WHERE task_id=? AND kind IN ({','.join('?' * len(RUN_KINDS))}) ORDER BY seq", (task_id, *RUN_KINDS)):
        p = json.loads(event['payload'])
        if event['kind'] == 'verdict.run_started':
            runs.append(dict(p, seq=event['seq'], receipt=None, abandoned=None))
            by_id[p.get('run_id')] = runs[-1]
            continue
        found = by_id.get(p.get('run_id'))
        if found is None and event['kind'] == 'verdict.receipt_issued':
            found = next((r for r in reversed(runs) if r['receipt'] is None and r['abandoned'] is None
                          and (r.get('revision'), r.get('milestone')) == (p.get('revision'), p.get('milestone'))), None)
        if found is None: continue
        found['receipt' if event['kind'] == 'verdict.receipt_issued' else 'abandoned'] = p
    return runs


def _open(run):
    return run['receipt'] is None and run['abandoned'] is None


def lost_reason(run, now, alive):
    """Why an open run is lost ('process_gone' | 'overdue' | 'no_deadline'), or None while it is alive and inside its deadline."""
    if run.get('host') == this_host() and not alive(run.get('pid')): return 'process_gone'
    deadline = _when(run.get('deadline'))
    if deadline is None: return 'no_deadline'                       # an event without a readable deadline must not hold "checking" for ever
    return 'overdue' if now > deadline else None


def live_runs(conn, task_id, revision=None, now=None, alive=None):
    """The open runs that are still alive (a read: nothing is written)."""
    now, alive = now or _now(), alive or process_alive
    return [r for r in run_records(conn, task_id) if _open(r) and (revision is None or r.get('revision') == revision) and lost_reason(r, now, alive) is None]


def _abandon(ledger, conn, task_id, run, reason, detail):
    plans.emit(ledger, conn, task_id, 'verdict.run_abandoned',
               {'plan': run.get('plan'), 'revision': run.get('revision'), 'milestone': run.get('milestone'), 'run_id': run.get('run_id'),
                'pid': run.get('pid'), 'host': run.get('host'), 'kind': run.get('kind'), 'started': run.get('started'),
                'reason': reason, 'detail': detail[:300], 'detected_at': utcnow()})


def reap(ledger, name, now=None, alive=None):
    """Close every lost run of plan `name` with verdict.run_abandoned; returns the runs it closed. Idempotent. Called by whoever reads the milestone state
    (verdict status, verdict run, the Stop hook); a run that is alive and inside its deadline is never touched."""
    now, alive = now or _now(), alive or process_alive
    with ledger.transaction() as conn:                              # a read first: the common case writes nothing and takes no write lock
        state = plans.derive(ledger, conn, name) if conn is not None else None
        if state is None or not any(_open(r) and lost_reason(r, now, alive) for r in run_records(conn, state['task_id'])): return []
    closed = []
    with ledger.transaction(write=True) as conn:
        state = plans.anchor_events(ledger, conn, name)
        for run in run_records(conn, state['task_id']):
            reason = lost_reason(run, now, alive) if _open(run) else None
            if reason:
                _abandon(ledger, conn, state['task_id'], run, reason, f'process {run.get("pid")} on {run.get("host")} is not running' if reason == 'process_gone'
                         else f'no end was written by {run.get("deadline")}')
                closed.append({'run_id': run.get('run_id'), 'milestone': run.get('milestone'), 'reason': reason})
    return closed


def _begin_run(ledger, name, revision, milestone_id, kind, max_minutes):
    reap(ledger, name)                                              # a lost earlier run must not refuse this one
    started = _now()
    run_id = uuid.uuid4().hex[:12]
    with ledger.transaction(write=True) as conn:                    # the check and the write are one transaction: two runs cannot both pass it
        state = plans.anchor_events(ledger, conn, name)
        held = [r for r in held_runs(conn, state['task_id']).values() if r.get('milestone') == milestone_id]
        if held:
            raise LedgerError(f'Milestone {milestone_id} has a held run of unknown outcome ({held[0].get("run_id")}); release it before a new run.')
        for run in run_records(conn, state['task_id']):
            if _open(run) and (run.get('revision'), run.get('milestone')) == (revision, milestone_id) and lost_reason(run, started, process_alive) is None:
                raise LedgerError(f'Milestone {milestone_id} is already being checked (run {run.get("run_id")}, process {run.get("pid")} since {run.get("started")}); '
                                  f'wait for it to end, or until {run.get("deadline")}.')
        plans.emit(ledger, conn, state['task_id'], 'verdict.run_started',
                   {'plan': name, 'revision': revision, 'milestone': milestone_id, 'run_id': run_id, 'kind': kind, 'pid': os.getpid(), 'host': this_host(),
                    'started': started.isoformat(), 'max_minutes': max_minutes,
                    'deadline': (started + dt.timedelta(minutes=max_minutes, seconds=RUN_GRACE_SECONDS)).isoformat()})
    return run_id


def _abandon_own(ledger, name, run_id, error):
    """The run raised before it had a receipt: close it. Never raises (the original error is what the caller needs to see)."""
    try:
        with ledger.transaction(write=True) as conn:
            state = plans.anchor_events(ledger, conn, name)
            run = next((r for r in run_records(conn, state['task_id']) if r.get('run_id') == run_id), None)
            if run is not None and _open(run): _abandon(ledger, conn, state['task_id'], run, 'error', f'{type(error).__name__}: {error}')
    except Exception:                                               # noqa: BLE001
        pass


def status(ledger, name, now=None, alive=None):
    """Which milestones are being checked now, and how every run ended. Reading it closes the lost runs first (reap), so a run whose process died is
    reported as abandoned and `checking` lists only runs that are alive."""
    closed = reap(ledger, name, now, alive)
    now, alive = now or _now(), alive or process_alive
    with ledger.transaction() as conn:
        state = plans.anchor_events(ledger, conn, name)
        records = run_records(conn, state['task_id'])
        by_receipt = {v.get('receipt'): v for v in state['verdicts']}
        reconciled = _reconcile_events(conn, state['task_id'])
    runs, checking = [], set()
    for run in records:
        outcome, reason = 'running', None
        if run['receipt'] is not None:
            recorded = by_receipt.get(run['receipt'].get('receipt'))
            if recorded is None: outcome = 'receipt_waiting'                 # the receipt exists, its verdict is not recorded yet
            elif recorded['result'] == 'pass': outcome = 'completed'
            elif recorded['result'] == 'fail': outcome = 'failed'
            else: outcome = 'timed_out' if _receipt_body(ledger, recorded.get('receipt')).get('timed_out') else 'inconclusive'
        elif run['abandoned'] is not None:
            outcome, reason = 'abandoned', run['abandoned'].get('reason')
            hold = _hold_of(reconciled.get(run.get('run_id'), {}))
            if hold is not None:
                outcome, reason = 'held_unknown_outcome', hold.get('reason') or hold.get('detail')     # W37a: not run again until released
        elif lost_reason(run, now, alive):
            outcome, reason = 'abandoned', 'lost'                           # only when closing it failed to write
        else:
            checking.add(run.get('milestone'))
        runs.append({'run_id': run.get('run_id'), 'revision': run.get('revision'), 'milestone': run.get('milestone'), 'kind': run.get('kind'),
                     'pid': run.get('pid'), 'started': run.get('started'), 'deadline': run.get('deadline'), 'outcome': outcome, 'reason': reason})
    held = sorted(r['run_id'] for r in runs if r['outcome'] == 'held_unknown_outcome')
    return {'plan': name, 'checking': sorted(checking), 'runs': runs, 'closed_now': closed, 'held': held}
