"""W19 repair generations and failed-first checks on the existing engine.

An immutable repair receipt is referenced by plan.revised node inputs. There is
no repair table, scheduler or duplicate invalidation loop. Affected nodes get a
new child generation through the normal internal-plan projector.
"""
import copy
import json

from .. import dependency_core
from ..ledger import LedgerError, canonical, content_hash, key_field, text_field
from ..snapshots import Snapshots
from . import engine, estimates, internal_plan as ip

PREFIX = 'repair-evidence:'
KIND = 'node-repair-plan'


def _source(ledger, conn, view, failed_node, receipt=None):
    if failed_node not in view['nodes']:
        raise LedgerError('Unknown failed node.')
    record = view['nodes'][failed_node]
    receipt = receipt or record.get('verification_receipt')
    if not receipt or receipt != record.get('verification_receipt'):
        raise LedgerError('Repair requires the latest node verification receipt.')
    event = conn.execute("SELECT seq,payload FROM events WHERE task_id=? AND kind='node.verification' AND json_extract(payload,'$.receipt')=? ORDER BY seq DESC LIMIT 1",
                         (view['root'], receipt)).fetchone()
    if event is None:
        raise LedgerError('Repair evidence has no authentic engine verification event.')
    body = json.loads(Snapshots(ledger.state_root).read_blob(receipt))
    item = next(n for n in view['definition']['nodes'] if n['id'] == failed_node)
    event_body = json.loads(event['payload'])
    expected = {'kind': 'node-verifier-receipt', 'root': view['root'], 'node': failed_node,
                'generation': record['generation'],
                'artifact': record['artifact'], 'checks_sha': content_hash(item['checks'])}
    if (any(body.get(k) != v for k, v in expected.items())
            or event_body.get('node') != failed_node or event_body.get('generation') != record['generation']
            or event_body.get('internal_revision') not in record.get('valid_internal_revisions',[view['internal_revision']])
            or body.get('internal_revision') not in record.get('valid_internal_revisions',[view['internal_revision']])
            or body.get('evidence_errors')):
        raise LedgerError('The failed verification is stale or lacks valid check evidence.')
    observed = body.get('observed') or {}
    if observed.get('artifact') != record['artifact']:
        raise LedgerError('Failure was not observed on the current produced artifact.')
    configured = {c['id'] for c in item['checks']}
    rows = observed.get('checks', [])
    if not isinstance(rows, list) or any(not isinstance(row, dict) or row.get('id') not in configured for row in rows):
        raise LedgerError('Failure does not identify configured checks.')
    failed = [row['id'] for row in rows if row.get('result') == 'fail']
    if not failed:
        raise LedgerError('Repair needs an actual failed check; unknown/environment evidence needs diagnosis.')
    return receipt, event['seq'], list(dict.fromkeys(failed))


def prepare(ledger, selector, target, failed_node, *, reason, evidence, receipt=None):
    """Reissue the explicit existing owner node, preserving every check/spec."""
    key_field(target); key_field(failed_node); text_field(reason, 'repair reason', 1000)
    with ledger.transaction() as conn:
        root, contract, sha = ip.context(ledger, conn, selector, 'sequential-engine')
        view = engine.state(ledger, root['selector'], conn)
        if view['definition_contract_sha'] != sha:
            raise LedgerError('Repair evidence belongs to an older approved contract; revise before repairing.')
        if view['definition'] is None or target not in view['nodes']:
            raise LedgerError('An existing, explicit repair target is required.')
        nodes = copy.deepcopy(view['definition']['nodes'])
        owner = next(n for n in nodes if n['id'] == target)
        if not owner['write'] or owner['integration']:
            raise LedgerError('The repair target must own the implementation writes.')
        source, seq, failed = _source(ledger, conn, view, failed_node, receipt)
        # The shared v1 closure includes declared readers by adapting ownership
        # data. There is deliberately no second transitive traversal here.
        scope=ip.influence_projection(nodes)
        affected = dependency_core.affected_tasks(scope, [target])
        if failed_node not in affected:
            raise LedgerError('The chosen owner is outside the failed node dependency/read/write scope.')
        value = {'kind': KIND, 'version': 1, 'root': view['root'], 'contract_sha': sha,
                 'internal_revision': view['internal_revision'] + 1, 'target': target, 'failed_node': failed_node,
                 'source_receipt': source, 'source_event': seq, 'failed_checks': failed, 'affected_nodes': sorted(affected),
                 'generations': {nid: view['nodes'][nid]['generation'] + 1 for nid in affected},
                 'checks_sha': {n['id']: content_hash(n['checks']) for n in nodes if n['id'] in affected},
                 'reason': reason, 'evidence': estimates.evidence(evidence)}
    blob = Snapshots(ledger.state_root).blob(canonical(value).encode())
    from . import recovery_policy
    recovery_policy.authorize_repair(ledger, root['selector'], failed_node)
    for node in nodes:
        if node['id'] in affected:
            node['input'] = [i for i in node['input'] if not i.startswith(PREFIX)] + [PREFIX + blob]
    revised = ip.revise(ledger, root['selector'], nodes, reason=reason, evidence=[source, *evidence],
                        expected_revision=view['internal_revision'])
    return dict(value, receipt=blob, event=revised['event'])


def verification_order(ledger, selector, nid, configured_checks):
    """Read-only sealed order; every configured obligation stays mandatory."""
    with ledger.transaction() as conn:
        view = engine.state(ledger, selector, conn)
    item = next((n for n in (view['definition'] or {}).get('nodes', []) if n['id'] == nid), None)
    if item is None:
        raise LedgerError('Unknown verification node.')
    configured = [c['id'] for c in item['checks']]
    supplied = [c['id'] if isinstance(c, dict) else c for c in configured_checks]
    if len(supplied) != len(configured) or set(supplied) != set(configured):
        raise LedgerError('Repair verification must retain every configured check.')
    result = {'ordered': configured, 'failed_first': [], 'affected': configured, 'repair_receipt': None,
              'stop_on_failed_prerequisite': False}
    markers = [i[len(PREFIX):] for i in item['input'] if i.startswith(PREFIX)]
    if not markers:
        return result
    value = json.loads(Snapshots(ledger.state_root).read_blob(markers[-1]))
    if (value.get('kind') != KIND or value.get('root') != view['root'] or value.get('contract_sha') != view['contract_sha']
            or value.get('internal_revision') not in view['nodes'][nid].get('valid_internal_revisions',[view['internal_revision']])
            or value.get('generations', {}).get(nid) != view['nodes'][nid]['generation']
            or value.get('checks_sha', {}).get(nid) != content_hash(item['checks'])):
        raise LedgerError('The repair plan no longer binds this node generation/check configuration.')
    first = [cid for cid in value['failed_checks'] if cid in configured]
    rest = [cid for cid in configured if cid not in first]
    return {'ordered': first + rest, 'failed_first': first, 'affected': rest, 'repair_receipt': markers[-1],
            'source_receipt': value['source_receipt'], 'stop_on_failed_prerequisite': bool(first)}


def rebind_order(ledger, selector, nodes, *, expected_revision):
    """Carry authentic failed-first obligations into one authorized diagnostic plan.

    The caller stores this result once with its replan reservation. Replaying a
    reservation must load those bytes, never regenerate against a later state.
    """
    with ledger.transaction() as conn:
        view = engine.state(ledger, selector, conn)
    if view['internal_revision'] != expected_revision:
        raise LedgerError('The internal plan changed before repair-order rebinding.')
    before = {n['id']: n for n in view['definition']['nodes']}
    carried, recipients, checks = {}, set(), set()
    for nid, item in before.items():
        refs = [value[len(PREFIX):] for value in item['input'] if value.startswith(PREFIX)]
        if not refs: continue
        verification_order(ledger, selector, nid, item['checks'])
        ref = refs[-1]
        carried[ref] = json.loads(Snapshots(ledger.state_root).read_blob(ref))
        recipients.add(nid); checks.update(check['id'] for check in item['checks'])
    result = copy.deepcopy(nodes)
    if not carried: return result
    existing_refs = set(carried)
    for node in result:
        refs = {value[len(PREFIX):] for value in node['input'] if value.startswith(PREFIX)}
        if refs - existing_refs: raise LedgerError('Diagnostic plan introduced an unbound repair-order receipt.')
        if any(check['id'] in checks for check in node['checks']): recipients.add(node['id'])
        node['input'] = [value for value in node['input'] if not value.startswith(PREFIX)]
    known = {node['id'] for node in result}
    recipients &= known
    changed = [node['id'] for node in result if node['id'] in recipients or before.get(node['id']) != node]
    affected = dependency_core.affected_tasks(ip.influence_projection(result), changed)
    failed = list(dict.fromkeys(cid for value in carried.values() for cid in value['failed_checks']))
    latest = list(carried.values())[-1]
    value = dict(latest, internal_revision=expected_revision + 1,
                 failed_checks=failed, affected_nodes=sorted(affected), carried_from=sorted(carried),
                 source_receipts=list(dict.fromkeys(value['source_receipt'] for value in carried.values())),
                 generations={nid: view['nodes'][nid]['generation'] + 1 if nid in view['nodes'] else 0 for nid in affected},
                 checks_sha={node['id']: content_hash(node['checks']) for node in result if node['id'] in affected},
                 rebinds_order_only=True, resets_recovery_counters=False)
    blob = Snapshots(ledger.state_root).blob(canonical(value).encode())
    for node in result:
        if node['id'] in affected: node['input'].append(PREFIX + blob)
    return result


def rebind_revised(ledger, selector, old_nodes, nodes, affected, *, expected_revision):
    """W19 (audit, T38c): called by internal_plan.revise for the nodes whose generation the revision moves. A node that still carries the
    repair marker of the current definition would keep a marker bound to its old generation, so it could never be verified or repaired
    again. For each such node: when its checks are unchanged and the marker still binds its current generation, the marker is rebound to
    the new internal revision/generation (same source receipt, failed checks and released findings: the focused order is kept); otherwise
    it is dropped and the node is verified in its full configured order. A marker the proposal itself introduced (prepare, rebind_order)
    is left as it is. Nothing here changes a check, a budget or a recovery counter."""
    before = {n['id']: n for n in old_nodes}
    marked = [n for n in nodes if n['id'] in affected and n['id'] in before
              and any(isinstance(v, str) and v.startswith(PREFIX) for v in n['input'])]
    carried = []
    for node in marked:
        refs = [v[len(PREFIX):] for v in node['input'] if isinstance(v, str) and v.startswith(PREFIX)]
        old_refs = [v[len(PREFIX):] for v in before[node['id']]['input'] if isinstance(v, str) and v.startswith(PREFIX)]
        if old_refs and refs[-1] == old_refs[-1]: carried.append(node)
    if not carried: return nodes
    with ledger.transaction() as conn:
        view = engine.state(ledger, selector, conn)
    if view['internal_revision'] != expected_revision:
        raise LedgerError('The internal plan changed before repair-order rebinding.')
    result = copy.deepcopy(nodes)
    by_id = {n['id']: n for n in result}
    rebound = {}
    for node in carried:
        target, old = by_id[node['id']], before[node['id']]
        ref = [v[len(PREFIX):] for v in target['input'] if v.startswith(PREFIX)][-1]
        target['input'] = [v for v in target['input'] if not (isinstance(v, str) and v.startswith(PREFIX))]
        if content_hash(old['checks']) != content_hash(target['checks']):
            continue                                                        # the check configuration changed: full configured order
        try:
            verification_order(ledger, selector, node['id'], old['checks'])  # the marker binds the current generation and checks
            value = json.loads(Snapshots(ledger.state_root).read_blob(ref))
        except (LedgerError, OSError, ValueError):
            continue                                                        # already stale or unreadable: full configured order
        if value.get('contract_sha') != view['contract_sha']:
            continue
        if ref not in rebound:
            rebound[ref] = Snapshots(ledger.state_root).blob(canonical(dict(
                value, internal_revision=expected_revision + 1,
                generations=dict(value.get('generations', {}), **{nid: (view['nodes'][nid]['generation'] + 1 if nid in view['nodes'] else 0) for nid in sorted(affected)}),
                checks_sha=dict(value.get('checks_sha', {}), **{n['id']: content_hash(n['checks']) for n in result if n['id'] in affected}),
                rebound_from=ref, rebinds_order_only=True, resets_recovery_counters=False)).encode())
        target['input'].append(PREFIX + rebound[ref])
    return result


def rerun_order(ledger, selector, finding_id):
    """W21 (T11 [E3], [E5]): what to run again after a repair for one open node finding: the failed check(s) of the node the finding is attached
    to first, then every check of the nodes in the finding's dependency scope, in definition order — not the whole suite. Read-only."""
    from . import findings
    with ledger.transaction() as conn:
        view = engine.state(ledger, selector, conn)
        root = findings._context(ledger, conn, selector)[0]
        value = findings._read(ledger, conn, root['id'])
    item = next((f for f in value['findings'] if f['id'] == finding_id), None)
    if item is None or not item.get('internal'):
        raise LedgerError('rerun_order needs an internal-node finding of this root.')
    definition = (view['definition'] or {}).get('nodes', [])
    by_id = {n['id']: n for n in definition}
    if item['node'] not in by_id:
        raise LedgerError('The finding node is not in the current internal definition.')
    failed_first = [item['criterion']] if item['criterion'] in {c['id'] for c in by_id[item['node']]['checks']} else []
    scope_nodes = [n['id'] for n in definition if n['id'] in set(item.get('scope_nodes') or [])]
    affected = [c['id'] for nid in scope_nodes for c in by_id[nid]['checks']]
    rest = [c['id'] for c in by_id[item['node']]['checks'] if c['id'] not in failed_first]
    everything = [c['id'] for n in definition for c in n['checks']]
    ordered = failed_first + affected + rest
    return {'finding': finding_id, 'node': item['node'], 'failed_first': failed_first, 'scope_nodes': scope_nodes, 'affected': affected,
            'ordered': ordered, 'whole_suite': everything, 'smaller_than_suite': len(ordered) < len(everything)}
