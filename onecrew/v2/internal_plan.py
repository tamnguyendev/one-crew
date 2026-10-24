"""W04: a workflow's internal decomposition, separate from its owner contract."""
import copy
import datetime as dt
import json

from ..ledger import LedgerError, canonical, content_hash, text_field, utcnow
from ..snapshots import Snapshots, scope_list
from .. import budget_core
from . import authority, contract as contracts, estimates, namespaces, plan as plans

KIND = 'plan.revised'


def context(ledger, conn, selector, capability='internal-plan'):
    state = plans.anchor_events(ledger, conn, selector)
    if not namespaces.has_capability(state, capability) or not namespaces.has_capability(state, 'root-budget'):
        raise LedgerError('This root does not declare the required ' + capability + ' capability.')
    if state['status'] != 'approved':
        raise LedgerError('Internal workflow changes require the current approved root.')
    contract, sha = plans.load(ledger, state)
    return state, contract, sha


def current(ledger, selector, conn=None):
    if conn is None:
        with ledger.transaction() as connection:
            return current(ledger, selector, connection)
    state = plans.anchor_events(ledger, conn, selector)
    row = conn.execute("SELECT seq,payload FROM events WHERE task_id=? AND kind=? ORDER BY seq DESC LIMIT 1", (state['task_id'], KIND)).fetchone()
    if row is None:
        return {'internal_revision': 0, 'contract_revision': state['approved']['revision'] if state['approved'] else None,
                'definition': None, 'event': None}
    body = json.loads(row['payload'])
    definition = json.loads(Snapshots(ledger.state_root).read_blob(body['definition']))
    if content_hash(definition) != body['definition_sha']:
        raise LedgerError('Internal plan definition hash mismatch.')
    return dict(body, definition=definition, event=row['seq'], contract_revision=body['revision'])


def projection(nodes):
    return {'tasks': [{'id': node['id'], 'owned': node['write'],
                       'depends_on': [edge['node'] for edge in node['depends']]} for node in nodes]}


def ceilings(ledger, conn, state):
    shared = budget_core.group(conn, state['task_id'])
    if shared is None:
        raise LedgerError('The workflow root has no sealed shared budget.')
    return {'remaining_calls': shared['remaining_calls'], 'deadline': shared['deadline'],
            'remaining_seconds': max(0, (dt.datetime.fromisoformat(shared['deadline']) - dt.datetime.fromisoformat(utcnow())).total_seconds())}


def decide(ledger, state, contract, sha, action, ctx, component):
    result = authority.decide(contract, action, ctx)
    decision = authority.record(ledger, state['task_id'], contract, action, result, name=state['selector'],
                                revision_sha=sha, component=component)
    if not result['in_authority']:
        raise LedgerError(str(result['class'] or 'held') + ': ' + result['reason'])
    return decision


def _checks(nodes):
    result = {}
    for node in nodes:
        for check in node.get('checks', []):
            if isinstance(check, dict) and isinstance(check.get('id'), str):
                if check['id'] in result and result[check['id']] != check:
                    raise LedgerError('A check id cannot carry different obligations.')
                result[check['id']] = check
    return result


def _validate(nodes, outputs):
    if not isinstance(nodes, list) or not 2 <= len(nodes) <= 200:
        raise LedgerError('An internal plan requires 2..200 explicitly ordered nodes including integration.')
    fields = {'id', 'goal', 'input', 'output', 'acceptance', 'depends', 'read', 'write', 'resources',
              'estimate_seconds', 'execution_cap_seconds', 'budget_calls', 'checks', 'integration'}
    result, known = copy.deepcopy(nodes), set()
    for node in result:
        if not isinstance(node, dict) or not fields <= set(node) or set(node) - fields - {'executor'}:
            raise LedgerError('Internal node fields must explicitly declare goal, inputs/outputs, acceptance, dependencies, scope, resources, estimate, cap, budget and checks.')
        contracts._id(node['id'], 'node id')
        if 'executor' in node:
            pin = node['executor']
            if (not isinstance(pin, dict) or set(pin) != {'role', 'provider', 'model'} or pin['role'] != 'worker'
                    or pin['provider'] not in ('claude', 'codex', 'kiro') or not isinstance(pin['model'], str)
                    or not contracts.MODEL.fullmatch(pin['model'])):
                raise LedgerError('Node executor must pin role=worker, provider and model.')
        if node['id'] in known:
            raise LedgerError('Internal node ids must be unique.')
        text_field(node['goal'], 'node goal', 1000)
        for field in ('input', 'output', 'resources'):
            if not isinstance(node[field], list) or len(node[field]) > 40:
                raise LedgerError('Node ' + field + ' must be a bounded list.')
            for value in node[field]: text_field(value, field, 500)
        if not isinstance(node['acceptance'], list) or not node['acceptance'] or not set(node['acceptance']) <= set(outputs):
            raise LedgerError('U1: node acceptance must refer to approved output ids.')
        for field in ('read', 'write'):
            if not isinstance(node[field], list): raise LedgerError('Node read/write scopes must be explicit file lists.')
            node[field] = scope_list(node[field]) if node[field] else []
        node['estimate_seconds'] = estimates.interval(node['estimate_seconds'])
        if (type(node['execution_cap_seconds']) not in (int, float) or not 0 < node['execution_cap_seconds'] <= 7200
                or node['estimate_seconds'][1] > node['execution_cap_seconds']):
            raise LedgerError('Node estimate exceeds its finite execution cap (at most two hours).')
        if type(node['budget_calls']) is not int or not 1 <= node['budget_calls'] <= 10000:
            raise LedgerError('Node budget_calls must be a finite positive integer.')
        if type(node['integration']) is not bool or not isinstance(node['checks'], list) or not node['checks']:
            raise LedgerError('Every node needs checks and an explicit integration flag.')
        check_ids = set()
        for check in node['checks']:
            if not isinstance(check, dict) or set(check) != {'id', 'spec'}:
                raise LedgerError('Node checks require id and spec.')
            contracts._id(check['id'], 'check id'); text_field(check['spec'], 'check spec', 1000)
            if check['id'] in check_ids: raise LedgerError('Duplicate node check id.')
            check_ids.add(check['id'])
        if not isinstance(node['depends'], list): raise LedgerError('Node depends must be an explicit list.')
        seen = set()
        for edge in node['depends']:
            if (not isinstance(edge, dict) or set(edge) - {'node', 'requires', 'advance'} or
                    edge.get('node') not in known or edge['node'] in seen or edge.get('requires') not in ('produced', 'verified', 'accepted')):
                raise LedgerError('Nodes use ordered, unique dependencies with requires produced, verified or accepted.')
            seen.add(edge['node'])
            if 'advance' in edge:
                advance = edge['advance']
                if (edge['requires'] != 'produced' or not isinstance(advance, dict) or set(advance) != {'limit', 'discard_on_failure'}
                        or type(advance['limit']) is not int or not 1 <= advance['limit'] <= 100 or advance['discard_on_failure'] is not True):
                    raise LedgerError('Advance needs a finite limit and discard_on_failure=true on a produced edge.')
        known.add(node['id'])
    if set().union(*(set(node['acceptance']) for node in result)) != set(outputs):
        raise LedgerError('U1: the internal plan must preserve every approved output.')
    integrations = [node for node in result if node['integration']]
    if not integrations:
        raise LedgerError('A mandatory integration node is required.')
    for node in integrations:
        if ({edge['node'] for edge in node['depends']} != known - {node['id']} or
                any(edge['requires'] == 'produced' for edge in node['depends'])):
            raise LedgerError('Integration must require verified/accepted evidence from every other node.')
    return result


def revise(ledger, selector, nodes, *, reason, evidence, expected_revision=None):
    reason = text_field(reason, 'internal revision reason', 1000)
    refs = estimates.evidence(evidence)
    if (not isinstance(nodes, list) or any(not isinstance(node, dict) or not isinstance(node.get('acceptance'), list)
                                         or not isinstance(node.get('checks'), list) for node in nodes)):
        raise LedgerError('Internal nodes require explicit acceptance and check lists.')
    with ledger.transaction() as conn:
        state, contract, sha = context(ledger, conn, selector)
        before = current(ledger, state['selector'], conn)
        ctx = ceilings(ledger, conn, state)
        # Reuse Control's attempt state: never rewrite a live/ambiguous execution.
        active = conn.execute("SELECT 1 FROM events e JOIN attempts a ON a.id=json_extract(e.payload,'$.attempt') WHERE e.task_id=? AND e.kind='node.started' AND a.status!='settled' LIMIT 1", (state['task_id'],)).fetchone() if conn.execute("SELECT 1 FROM sqlite_master WHERE name='attempts'").fetchone() else None
        if active: raise LedgerError('Reconcile the active workflow attempt before revising the plan.')
    outputs = contracts.output_ids(contract['output'])
    old_nodes = before['definition']['nodes'] if before['definition'] else []
    old_checks, new_checks = _checks(old_nodes), _checks(nodes)
    acceptance = {item for node in nodes for item in node.get('acceptance', [])}
    changed = acceptance != set(outputs) or any(new_checks.get(key) != check for key, check in old_checks.items())
    if changed:
        decide(ledger, state, contract, sha, {'kind': 'change_acceptance', 'nodes': [n.get('id') for n in nodes]}, ctx, 'onecrew.internal_plan')
    normalized = _validate(nodes, outputs)
    paths = sorted({path for node in normalized for path in node['write']})
    if paths:
        # The same scope function used by the root authority gate, not another matcher.
        if authority.covers(authority.effective(contract), {'edit': True, 'paths': paths}):
            decide(ledger, state, contract, sha, {'kind': 'write', 'paths': paths, 'nodes': [n['id'] for n in normalized]}, ctx, 'onecrew.internal_plan')
    definition = {'version': 1, 'nodes': normalized, 'acceptance': {oid: [n['id'] for n in normalized if oid in n['acceptance']] for oid in outputs}}
    definition_sha = content_hash(definition)
    if before.get('definition_sha') == definition_sha and before.get('contract_revision') == state['approved']['revision'] and before.get('contract_sha') == sha:
        return before
    if expected_revision is not None and expected_revision != before['internal_revision']:
        raise LedgerError('Stale internal plan revision.')
    action = {'kind': 'decision', 'q': 'Q1', 'nodes': [n['id'] for n in normalized], 'acceptance_changed': False,
              'cost': {'calls': sum(n['budget_calls'] for n in normalized), 'seconds': sum(n['estimate_seconds'][1] for n in normalized)}}
    decision = decide(ledger, state, contract, sha, action, ctx, 'onecrew.internal_plan')
    blob = Snapshots(ledger.state_root).blob(canonical(definition).encode('utf-8'))
    revision = before['internal_revision'] + 1
    with ledger.transaction(write=True) as conn:
        again, _, current_sha = context(ledger, conn, state['selector'])
        if current_sha != sha or current(ledger, state['selector'], conn)['internal_revision'] != before['internal_revision']:
            raise LedgerError('The root or internal plan changed before revision publication.')
        plans.emit(ledger, conn, again['task_id'], KIND, {'plan': state['name'], 'revision': state['approved']['revision'],
                   'internal_revision': revision, 'contract_sha': sha, 'definition': blob, 'definition_sha': definition_sha,
                   'reason': reason, 'decision': decision, 'evidence': refs})
    estimates.reforecast(ledger, state['selector'], f'internal-r{revision}',
                        [sum(n['estimate_seconds'][i] for n in normalized) for i in (0, 1)], reason, refs)
    return current(ledger, state['selector'])
