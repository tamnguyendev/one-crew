"""W31b: unresolved facts hold only explicitly required internal nodes.

Same ledger, root and evidence resolver as step0. An unknown overlay never
resets attempts or removes independent finding/authority holds.
"""
import json

from ..ledger import LedgerError, canonical, key_field, text_field
from . import internal_plan as ip, plan, step0

KINDS = ('workflow.unknown_opened', 'workflow.unknown_resolved')


def _read(conn, task):
    result = {}
    for row in conn.execute("SELECT seq,kind,payload FROM events WHERE task_id=? AND kind IN (?,?) ORDER BY seq", (task, *KINDS)):
        item = json.loads(row['payload'])
        if row['kind'] == KINDS[0]: result[item['unknown']] = dict(item, event=row['seq'], state='open')
        elif item['unknown'] in result:
            result[item['unknown']].update(state='resolved', resolution=dict(item, event=row['seq']))
    return result


def read(ledger, selector, conn=None):
    if conn is None:
        with ledger.transaction() as connection: return read(ledger, selector, connection)
    root = plan.anchor_events(ledger, conn, selector)
    return list(_read(conn, root['task_id']).values())


def blockers(ledger, selector, conn=None):
    result = {}
    for item in read(ledger, selector, conn):
        if item['state'] == 'open':
            for nid in item['required_by']: result.setdefault(nid, []).append(item['unknown'])
    return result


def _refs(ledger, refs):
    if not isinstance(refs, list) or not 1 <= len(refs) <= 20:
        raise LedgerError('Runtime unknowns require evidence references.')
    for ref in refs: step0.evidence_kind(ledger, ref)
    return refs


def _node_list(value, known, field):
    if (not isinstance(value, list) or not value or len(value) > 200
            or any(not isinstance(nid, str) or nid not in known for nid in value)
            or len(set(value)) != len(value)):
        raise LedgerError(field + ' must name unique nodes in the current internal plan.')
    return list(value)


def open_unknown(ledger, selector, key, *, question, affected, required_by, resolver, evidence,
                 blocks_estimate=False, survey_node=None):
    key_field(key); text_field(question, 'unknown question', 1000)
    if resolver not in ('doc', 'poc', 'owner'):
        raise LedgerError('Unknown resolver must be doc, poc or owner.')
    if type(blocks_estimate) is not bool: raise LedgerError('blocks_estimate must be a boolean.')
    refs = _refs(ledger, evidence)
    with ledger.transaction(write=True) as conn:
        root, contract, sha = ip.context(ledger, conn, selector, 'sequential-engine')
        internal = ip.current(ledger, root['selector'], conn)
        if not internal['definition']: raise LedgerError('An internal plan is required before opening a runtime unknown.')
        nodes = {node['id']: node for node in internal['definition']['nodes']}
        required = _node_list(required_by, nodes, 'required_by')
        affected = 'root' if affected == 'root' else _node_list(affected, nodes, 'affected')
        if affected != 'root' and not set(required) <= set(affected):
            raise LedgerError('required_by must be inside the declared affected scope.')
        if blocks_estimate:
            survey = nodes.get(survey_node)
            if (not survey or survey['write'] or survey_node in required or resolver != 'poc'
                    or not 0 < survey['execution_cap_seconds'] <= 7200
                    or any(not any(edge['node'] == survey_node and edge['requires'] in ('verified','accepted')
                                   for edge in nodes[nid]['depends']) for nid in required)):
                raise LedgerError('An estimate-blocking unknown needs a bounded read-only survey node verified before implementation.')
        value = {'plan':root['name'], 'revision':root['approved']['revision'], 'contract_sha':sha,
                 'unknown':key, 'question':question, 'affected':affected, 'required_by':required,
                 'resolver':resolver, 'evidence':refs, 'blocks_estimate':blocks_estimate,
                 'survey_node':survey_node, 'internal_revision':internal['internal_revision'],
                 'actor':step0._actor() or 'unknown', 'grants_authority':False}
        old = _read(conn, root['task_id']).get(key)
        if old:
            compared = set(value) - {'internal_revision', 'actor'}
            if any(old.get(field) != value[field] for field in compared):
                raise LedgerError('Unknown key already identifies another question; do not overwrite its history.')
            return old
        # A new unknown cannot retroactively certify or interrupt a running node.
        # The scheduler observes it before the next reserve/publication fence.
        plan.emit(ledger, conn, root['task_id'], KINDS[0], value)
        return _read(conn, root['task_id'])[key]


def resolve(ledger, selector, key, *, by, evidence, answer):
    text_field(answer, 'unknown answer', 1000)
    if by == 'owner': plan.require_owner('owner', 'Resolving a workflow unknown')
    with ledger.transaction(write=True) as conn:
        root, contract, sha = ip.context(ledger, conn, selector, 'sequential-engine')
        item = _read(conn, root['task_id']).get(key)
        if item is None: raise LedgerError('Unknown runtime question.')
        if by != item['resolver']: raise LedgerError('This actor role is not the declared unknown resolver.')
        kind = step0.evidence_kind(ledger, evidence, by)
        if item['contract_sha'] != sha:
            raise LedgerError('The root contract changed; explicitly reconcile the original unknown before closing it.')
        if item['state'] == 'resolved':
            prior = item['resolution']
            if any(prior.get(k) != v for k,v in {'by':by,'evidence':evidence,'answer':answer}.items()):
                raise LedgerError('The unknown was already resolved differently.')
            return item
        if item['blocks_estimate']:
            from . import engine
            view = engine.state(ledger, selector, conn)
            record = view['nodes'].get(item['survey_node'])
            if not record or record.get('state') not in ('verified','accepted') or record['phase']=='held':
                raise LedgerError('The bounded survey must be verified before its unknown is closed.')
            if evidence not in (record.get('verification_receipt'), record.get('artifact')):
                raise LedgerError('The estimate answer must reference the current verified survey evidence.')
        plan.emit(ledger, conn, root['task_id'], KINDS[1], {
            'plan':root['name'], 'revision':root['approved']['revision'], 'contract_sha':sha,
            'unknown':key, 'by':by, 'actor':step0._actor(by), 'answer':answer,
            'evidence':evidence, 'evidence_kind':kind, 'required_by':item['required_by'], 'grants_authority':False})
        return _read(conn, root['task_id'])[key]


def validate_revision(ledger, selector, nodes, conn):
    """Internal replanning cannot silently drop unresolved obligations."""
    known = {node['id'] for node in nodes}
    for item in read(ledger, selector, conn):
        if item['state'] != 'open': continue
        required = set(item['required_by']) | ({item['survey_node']} if item['survey_node'] else set())
        if not required <= known:
            raise LedgerError('Resolve or explicitly reconcile unknown ' + item['unknown'] + ' before removing its required nodes.')
