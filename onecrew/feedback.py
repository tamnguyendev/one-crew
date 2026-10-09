"""Revision-bound operator feedback becomes one bounded, scoped repair."""
import datetime as dt

from .amendment import affected_tasks, profile_for
from .ledger import LedgerError, content_hash, key_field, text_field


def request_changes(workflow, task_id, revision, output_revision, selected, comment, request_id):
    from .workflow import task_lock
    key_field(request_id)
    text_field(comment, 'Review correction', 2000)
    if not isinstance(selected, list) or not selected or not all(isinstance(x, str) for x in selected):
        raise LedgerError('Select completed task IDs to correct.')
    proposal = {'workflow_revision': revision, 'revision': output_revision,
                'selected': sorted(set(selected)), 'comment': comment}
    proposal_hash = content_hash(proposal)
    with task_lock(workflow.ledger, task_id):
        sequence, state = workflow.state(task_id)
        if not state:
            raise LedgerError('Enable a workflow before requesting changes.')
        previous = next((r for r in state.get('reviews', []) if r.get('request_id') == request_id), None)
        if previous:
            if previous.get('proposal_hash') != proposal_hash:
                raise LedgerError('Request ID already used for a different correction.')
            return previous
        if content_hash(state) != revision:
            raise LedgerError('Stale workflow revision; inspect current work before requesting changes.')
        control = workflow.control.status(task_id)
        if control['cancel_requested'] or state['phase'] not in ('working', 'completed'):
            raise LedgerError('Corrections require a non-cancelled working/completed checkpoint.')
        if state['pending'] or state.get('parallel_pending') or any(a['status'] != 'settled' for a in control['attempts']):
            raise LedgerError('Stop/reconcile pending writers before requesting a correction; feedback comments can be saved while they run.')
        if workflow.ledger.task(task_id)['pending_requests'] or state.get('branch_errors'):
            raise LedgerError('Resolve pending blockers before scheduling a correction.')
        output = next((r for r in state['outputs'] if r['revision'] == output_revision), None)
        if not output or output.get('invalidated_by') or output['verification'] == 'stale':
            raise LedgerError('Unknown or stale output revision.')
        if not set(selected) <= set(state['done']):
            raise LedgerError('Select completed task IDs to correct.')
        profile = profile_for(state, control)
        if state['repairs'] >= profile['max_repairs']:
            raise LedgerError('Repair cap reached; feedback cannot reset or extend it.')
        from .budget import remaining
        if remaining(control['budget'],control['used_calls'],control['reserved_calls']) <= 0:
            raise LedgerError('Root call budget exhausted; no implicit extension.')
        if dt.datetime.fromisoformat(control['deadline']) <= dt.datetime.now(dt.timezone.utc):
            raise LedgerError('Root deadline expired; no implicit extension.')
        # The output is an immutable full snapshot; verify every completed affected
        # path still has the bytes the operator reviewed before granting a repair.
        affected = affected_tasks(state['plan'], selected) & set(state['done'])
        items = [r for r in state['plan']['tasks'] if r['id'] in affected]
        owned = sorted({p for row in items for p in row['owned']})
        viewed, current = (workflow.store.load(ref)['files'] for ref in (output_revision, state['snapshot']))
        if any(viewed[p]['working'] != current[p]['working'] for p in owned):
            raise LedgerError('Affected source changed since this output; review the current snapshot first.')
        record = dict(proposal, request_id=request_id, proposal_hash=proposal_hash,
                      decision='request-changes', provenance='local_operator', applied_to_source=False,
                      affected_tasks=sorted(affected), status='scheduled')
        state.setdefault('reviews', []).append(record)
        state['feedback_repair'] = {'request_id': request_id, 'owned': owned, 'tasks': items, 'comment': comment}
        state['repairs'] += 1
        state.update(phase='repairing', verification='pending', acceptance='not_requested',
                     checks=None, failures=[], message=None)
        state.pop('verification_only', None)
        state.pop('resume_phase', None)
        for row in state['outputs']:
            if row['stage'] in affected or row['stage'] == 'repair':
                row.update(invalidated_by=proposal_hash, verification='stale', acceptance='pending')
        workflow.persist(task_id, sequence, state, unpause=True)
        return record
