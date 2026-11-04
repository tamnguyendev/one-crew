"""W51: sourced progress observations; a recommendation never stops a worker.

The engine consumes a blocked recommendation within its existing grant and
recovery rules. Missing output is unknown, not proof that computation stalled.
No internal reasoning or number of changed lines is measured here.
"""
import copy
import json
import math

from .. import progress_core
from ..ledger import LedgerError, canonical, content_hash, key_field, text_field, utcnow
from . import executors, plan

TOOL_ACTIONS = ('list', 'search', 'read', 'receipt', 'contract', 'git_status', 'git_diff', 'git_log', 'git_show', 'run')


def number(value, name, positive=False):
    if type(value) not in (int, float) or not math.isfinite(value) or value < 0 or (positive and value == 0):
        raise LedgerError(name + ' must be a finite ' + ('positive' if positive else 'non-negative') + ' number.')
    return value


def advance(previous, observation, *, command_cap_seconds=None, window_seconds=600, hypothesis_limit=3):
    """Pure transition; counters survive attempts and JSON checkpoint roundtrips."""
    if not isinstance(observation, dict): raise LedgerError('Progress observation must be an object.')
    try:
        size = len(canonical(observation).encode('utf-8'))
    except (TypeError, ValueError) as error:
        raise LedgerError('Progress observation must contain finite JSON values.') from error
    if size > 32768: raise LedgerError('Progress observation exceeds 32 KiB.')
    value = copy.deepcopy(previous) if previous else {'counters': {}, 'rejected_hypotheses': [], 'command': {}}
    value.update(status='unknown', reason='No measurable progress observation.')
    kind = observation.get('kind')
    if kind == 'unknown': return value
    if kind == 'wait':
        if observation.get('reason') not in executors.WAIT_REASONS: raise LedgerError('Wait must name owner, resource or external_service.')
        value.update(status='waiting', reason=observation['reason'])
    elif kind == 'tool':
        action, args, result = observation.get('action'), observation.get('args'), observation.get('result')
        if action not in TOOL_ACTIONS or not isinstance(args, dict) or not isinstance(result, dict):
            raise LedgerError('A tool observation requires an observed action, arguments and result.')
        snapshot = text_field(observation.get('snapshot'), 'snapshot', 200)
        evidence, intent, page, advanced, empty = progress_core.prepare_evidence(action, args, result)
        key = content_hash({'action': action, 'snapshot': snapshot, 'result': evidence, 'search_intent': intent})
        reason = progress_core.observe_counters(value['counters'], action, args, result, key,
            page=page, search_advanced=advanced, search_empty=empty)
        value.update(status='blocked' if reason else 'progressing', reason=reason or 'Observed tool evidence within repeat/exploration bounds.')
    elif kind == 'hypothesis':
        hypothesis = text_field(observation.get('hypothesis'), 'hypothesis', 1000)
        refs = observation.get('rejected_by')
        if not isinstance(refs, list) or not 1 <= len(refs) <= 20:
            raise LedgerError('A rejected hypothesis requires bounded evidence references.')
        for ref in refs:
            if not text_field(ref, 'rejected_by', 500).strip(): raise LedgerError('Hypothesis evidence cannot be empty.')
        if type(hypothesis_limit) is not int or not 1 <= hypothesis_limit <= 20: raise LedgerError('Invalid hypothesis cap.')
        record = {'hypothesis': hypothesis, 'rejected_by': refs}
        if record not in value['rejected_hypotheses']:
            value['rejected_hypotheses'].append(record)
        blocked = len(value['rejected_hypotheses']) > hypothesis_limit
        value.update(status='blocked' if blocked else 'progressing',
                     reason='Rejected hypothesis cap exhausted; retain evidence for diagnosis.' if blocked else 'Hypothesis rejected with evidence.')
    elif kind == 'command':
        elapsed = number(observation.get('elapsed_seconds'), 'elapsed_seconds')
        cap = number(command_cap_seconds, 'command execution cap', positive=True)
        window = number(window_seconds, 'observation window', positive=True)
        old = value['command']
        if elapsed < old.get('elapsed_seconds', 0): raise LedgerError('Command elapsed time cannot go backwards.')
        if old.get('cap') is not None and old['cap'] != cap: raise LedgerError('An observation cannot change the execution cap.')
        evidence = {field: observation.get(field) for field in ('output_hash', 'receipt_ref')}
        for field, ref in evidence.items():
            if ref is not None: text_field(ref, field, 200)
        fresh = any(ref and ref != old.get(field) for field, ref in evidence.items())
        last = elapsed if fresh else old.get('last_evidence_seconds')
        old.update(evidence, elapsed_seconds=elapsed, last_evidence_seconds=last, cap=cap)
        if elapsed >= cap:
            value.update(status='blocked', reason='Command execution cap reached; use the existing executor stop protocol.')
        elif last is not None and elapsed - last <= window:
            value.update(status='progressing', reason='New output or receipt in the observation window.')
    else:
        raise LedgerError('Unsupported progress observation; reasoning and changed-line counts are not evidence.')
    return value


def _rows(conn, task, node):
    return [dict(json.loads(row['payload']), event=row['seq']) for row in conn.execute(
        "SELECT seq,payload FROM events WHERE task_id=? AND kind='executor.observed' AND json_extract(payload,'$.what')='progress' AND json_extract(payload,'$.node')=? ORDER BY seq",
        (task, node))]


def read(ledger, selector, node):
    with ledger.transaction() as conn:
        state = plan.anchor_events(ledger, conn, selector)
        rows = _rows(conn, state['task_id'], node)
    return rows[-1] if rows else None


def observe(ledger, selector, node, executor, attempt, key, observation, *, source, ref, at=None,
            command_cap_seconds=None):
    """Record actual adapter evidence; operator tool/hook references stay labeled.

    This records a diagnostic only, never grants execution or marks a worker
    paused. Runtime consumers must bind the node and command cap to their plan.
    """
    key_field(key); text_field(node, 'node', 100); text_field(attempt, 'attempt', 100)
    if not isinstance(observation, dict): raise LedgerError('Progress observation must be an object.')
    declaration = executors.declaration_of(executor)
    if observation.get('kind') == 'command' and not declaration.measures_what('time'):
        raise LedgerError('Command liveness requires an executor that declares measured time; otherwise record unknown.')
    basis = executors._basis(ledger, declaration, source, ref)
    observed_at = executors._stamp(at, 'at')
    data = dict(declaration.view(), node=node, attempt=attempt, key=key, what='progress',
        observation=observation, basis=basis, time_source=source, observed_at=observed_at,
        command_cap_seconds=command_cap_seconds, source_trust='operator_reported; reference not independently verified')
    with ledger.transaction(write=True) as conn:
        state = plan.anchor_events(ledger, conn, selector)
        rows = _rows(conn, state['task_id'], node)
        for old in rows:
            if old['key'] == key:
                if any(old.get(k) != v for k, v in data.items()): raise LedgerError('Progress key already binds a different observation.')
                return old
        prior = rows[-1]['checkpoint'] if rows else None
        # A new attempt has a new command clock, but repeat/hypothesis history
        # remains scoped to the node and cannot be reset by another attempt key.
        if prior and rows[-1]['attempt'] != attempt:
            prior = dict(prior, command={})
        checkpoint = advance(prior, observation, command_cap_seconds=command_cap_seconds)
        payload = dict(data, checkpoint=checkpoint, received_at=utcnow(), grants_execution=False)
        plan.emit(ledger, conn, state['task_id'], executors.KIND, payload)
        return payload
