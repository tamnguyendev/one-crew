"""W16 acceptance-bound test preparation, expressed as ordinary engine nodes."""
import copy

from ..ledger import LedgerError, key_field, text_field
from . import authority, decisions, estimates, internal_plan as ip


def prepare(ledger, selector, implementation, node_id, *, write, checks, estimate_seconds,
            execution_cap_seconds, budget_calls, reason, evidence, read=(), executor=None):
    """Add preparation before code, using the existing plan and scheduler.

    Its checks verify that acceptance tests are prepared, not that future code
    already passes them. Test quality remains the responsible checker's work.
    """
    key_field(implementation); key_field(node_id); text_field(reason, 'preparation reason', 1000)
    refs = estimates.evidence(evidence)
    span = estimates.interval(estimate_seconds)
    with ledger.transaction() as conn:
        root, contract, sha = ip.context(ledger, conn, selector, 'sequential-engine')
        current = ip.current(ledger, root['selector'], conn)
        if current['definition'] is None:
            raise LedgerError('Test preparation requires an existing internal decomposition.')
        nodes = copy.deepcopy(current['definition']['nodes'])
        target = next((n for n in nodes if n['id'] == implementation), None)
        if target is None or target['integration']:
            raise LedgerError('Preparation needs an implementation node, not integration.')
        if any(n['id'] == node_id for n in nodes):
            raise LedgerError('The preparation node id already exists.')
        ceilings = ip.ceilings(ledger, conn, root)
    ip.decide(ledger, root, contract, sha, {'kind': 'decision', 'q': 'Q4', 'operation': 'edit',
        'nodes': [node_id], 'paths': list(write), 'weakens': False, 'provenance': ['approved-contract:' + sha, *refs],
        'cost': {'calls': budget_calls, 'seconds': span[1]}}, ceilings, 'onecrew.test_preparation')
    preparation = {'id': node_id, 'goal': 'Prepare tests from approved acceptance before implementation ' + implementation,
        'input': ['acceptance:' + oid for oid in target['acceptance']], 'output': ['Prepared acceptance tests for ' + implementation],
        'acceptance': list(target['acceptance']), 'depends': [], 'read': list(read), 'write': list(write), 'resources': [],
        'estimate_seconds': span, 'execution_cap_seconds': execution_cap_seconds, 'budget_calls': budget_calls,
        'checks': copy.deepcopy(checks), 'integration': False}
    pin = executor if executor is not None else target.get('executor')
    if pin is not None:
        preparation['executor'] = copy.deepcopy(pin)
    # Every source and check obligation is validated by internal_plan.revise;
    # this helper does not implement another node schema or authority gate.
    target['depends'].append({'node': node_id, 'requires': 'verified'})
    nodes.insert(nodes.index(target), preparation)
    for node in nodes:
        if node['integration']:
            node['depends'].append({'node': node_id, 'requires': 'verified'})
    result = ip.revise(ledger, root['selector'], nodes, reason=reason, evidence=evidence,
                       expected_revision=current['internal_revision'])
    decisions.record(ledger, root['task_id'], subject={'component': 'onecrew.test_preparation', 'model': 'deterministic'},
        authority=authority.grant_ref(root['selector'], contract, sha), evidence=[result['event'], *refs],
        basis=reason, scope='acceptance-test-preparation',
        validity={'node': node_id, 'implementation': implementation, 'internal_revision': result['internal_revision'],
                  'contract_revision': root['approved']['revision'], 'checks': [check['id'] for check in checks]},
        key='test-preparation-' + str(result['event']))
    return result
