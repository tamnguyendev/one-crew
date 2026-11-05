"""W19 repair generations and failed-first checks on the existing engine.

An immutable repair receipt is referenced by plan.revised node inputs. There is
no repair table, scheduler or duplicate invalidation loop. Affected nodes get a
new child generation through the normal internal-plan projector.
"""
import copy
import json

from .. import dependency_core
from ..ledger import LedgerError, canonical, content_hash, key_field, text_field
from ..snapshots import Snapshots, bytes_hash
from . import engine, estimates, internal_plan as ip

PREFIX = 'repair-evidence:'
KIND = 'node-repair-plan'


def _carried(ledger, conn, view, failed_node, record):
    """R10 D6: the failed receipt of an OPEN internal finding on `failed_node` whose generation a valid internal revision has moved since.

    `internal_plan.revise` gives a changed node a fresh generation without `verification_receipt`; the finding still holds the node, so
    without this the node could never be repaired nor the finding closed (deadlock). The old failure stays evidence only while its binding
    holds: it is the LATEST node.verification of this node (nothing verified it since), it failed on an older generation of the same
    contract revision, it is the source/last observation of a finding the register still keeps OPEN under the current definition (the
    existing `findings._refresh` change policy: a real check change makes it stale and this returns None) and its failed checks are still
    configured. Returns (receipt, event seq, failed checks) or None. Read-only."""
    row = conn.execute("SELECT seq,payload FROM events WHERE task_id=? AND kind='node.verification' AND json_extract(payload,'$.node')=? "
                       "ORDER BY seq DESC LIMIT 1", (view['root'], failed_node)).fetchone()
    if row is None: return None
    event = json.loads(row['payload'])
    if (event.get('result') != 'fail' or type(event.get('generation')) is not int or event['generation'] >= record['generation']
            or event.get('revision') != view['contract_revision'] or 'finding-register' not in view.get('capabilities', ())):
        return None
    from . import findings
    register_root, _, _, contract = findings._context(ledger, conn, view['selector'])
    value = findings._read(ledger, conn, register_root['id'])
    findings._refresh(value, contract, view['definition']['nodes'])
    if not any(f['status'] == 'open' and f.get('internal') and f['node'] == failed_node
               and event['receipt'] in (f['source']['receipt'], (f.get('last_observed') or {}).get('receipt')) for f in value['findings']):
        return None
    store = Snapshots(ledger.state_root)
    item = next(n for n in view['definition']['nodes'] if n['id'] == failed_node)
    for marker in [i[len(PREFIX):] for i in item['input'] if isinstance(i, str) and i.startswith(PREFIX)]:
        try:
            issued = json.loads(store.read_blob(marker))
        except (LedgerError, OSError, ValueError):
            continue
        if event['receipt'] == issued.get('source_receipt') or event['receipt'] in (issued.get('source_receipts') or []):
            return None                     # a repair for this very failure is already issued: verify its generation, never repair twice
    body = json.loads(store.read_blob(event['receipt']))
    observed = body.get('observed') or {}
    if (body.get('kind') != 'node-verifier-receipt' or body.get('root') != view['root'] or body.get('node') != failed_node
            or body.get('generation') != event['generation'] or body.get('result') != 'fail' or body.get('evidence_errors')
            or observed.get('artifact') != body.get('artifact')):
        raise LedgerError('The failed verification of the finding lacks valid check evidence.')
    configured = {c['id'] for c in item['checks']}
    failed = [r['id'] for r in observed.get('checks', []) if isinstance(r, dict) and r.get('result') == 'fail']
    if not failed or not set(failed) <= configured:
        raise LedgerError('The failed checks of the finding are no longer configured; verify the node again.')
    return event['receipt'], row['seq'], list(dict.fromkeys(failed))


def _source(ledger, conn, view, failed_node, receipt=None):
    if failed_node not in view['nodes']:
        raise LedgerError('Unknown failed node.')
    record = view['nodes'][failed_node]
    if record.get('verification_receipt') is None:
        carried = _carried(ledger, conn, view, failed_node, record)
        if carried is not None:
            if receipt is not None and receipt != carried[0]:
                raise LedgerError('Repair requires the latest node verification receipt.')
            return carried
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
    data = canonical(value).encode()
    blob = bytes_hash(data)                  # the receipt id, known before anything is written
    from . import recovery_policy
    recovery_policy.authorize_repair(ledger, root['selector'], failed_node)
    # T16b [E6] / round 8 G: Q5 (repair inside the ceilings) is an ACTION that changes the plan. Delegated -> its HD-05 record, then the
    # repair. A workflow grant that does not delegate Q5 -> the U3 verdict is recorded, nothing of the repair is written (no receipt blob,
    # no plan.revised), the affected nodes are held and the owner gets the one v2.workflow_hold card (engine.hold_out_of_authority, the
    # path of request_action); recovery continues only through that answered request. A root with no workflow grant: as before.
    verdict = ip.self_decided(ledger, root['selector'], 'Q5', affected, 'onecrew.repair_tasks', key='q5-repair-' + blob[:48],
                              target=target, failed_node=failed_node, failed_checks=failed, evidence=[source, blob])
    if verdict['delegation'] == ip.NOT_DELEGATED:
        result = verdict['result']
        request = engine.hold_out_of_authority(ledger, root, sha, view, verdict['ctx'], failed_node, verdict['action'], result,
                                               verdict['decision'], affected=sorted(affected))
        raise LedgerError(str(result['class']) + ': ' + result['reason'] + '; the repair was not created, '
                          + ', '.join(sorted(affected)) + ' is held for the owner (request ' + request['id'] + ').')
    Snapshots(ledger.state_root).blob(data)
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


def _unbound(ledger, selector, nid, entry):
    """Why a caller's evidence for scope node `nid` does not belong to it (None when it does): both descriptors must be v2 descriptors of this
    node, and `current` must be built from what the node is now. An old descriptor on both sides, or another node's, says nothing about this node."""
    from . import review_dispatch, review_request as rr
    for side in ('previous', 'current'):
        value = entry.get(side)
        if rr.kind_of(value) != 'node' or value['version'] != rr.CHECK_VERSION or value['identity']['target'].get('node') != nid:
            return 'the ' + side + ' descriptor is not a check descriptor of node ' + nid
    identity = entry['current']['identity']
    try:
        facts = review_dispatch._context(ledger, selector, nid)[3]
    except LedgerError as error:
        return 'the current facts of node ' + nid + ' cannot be read: ' + str(error)[:120]
    if (identity['facts'] != rr.evidence_facts(facts) or identity['evidence']['candidate'] != facts['artifact']
            or identity['target'].get('generation') != facts['generation']):
        return 'the current descriptor was not built from the current facts of node ' + nid
    return None


def rerun_recorded(ledger, selector, finding_id):
    """rerun_order with its evidence read from the ledger, for the public verb: for each scope node with a passing published verification, the
    request of that run against the node as it is now under the production check port. Any gap (no pass, no run record, changed checks) gives no
    entry, so the node reruns; an execution identity the run did not state widens. Nothing is taken from a caller."""
    from ..common_verification import CandidateChecker
    from . import findings, review_dispatch, review_request as rr
    port, evidence = CandidateChecker(ledger, selector), {}
    with ledger.transaction() as conn:
        view = engine.state(ledger, selector, conn)
        root = findings._context(ledger, conn, selector)[0]
        item = next((f for f in findings._read(ledger, conn, root['id'])['findings'] if f['id'] == finding_id), None)
        runs = review_dispatch._runs(conn, root['id'])
    def wrapped(execution):
        return dict({k: execution.get(k) for k in ('method', 'implementation', 'provider', 'model')},
                    **{k: ({'fingerprint': execution[k]} if execution.get(k) else None) for k in ('configuration', 'environment', 'provenance')})
    store = Snapshots(ledger.state_root)
    for nid in (item or {}).get('scope_nodes') or []:
        record = view['nodes'].get(nid) or {}
        receipt = record.get('verification_receipt')
        run = next((r for r in runs.values() if r.get('check') == review_dispatch.CHECK_NODE and (r.get('subject') or {}).get('node') == nid
                    and r['finished'] and r['finished'].get('receipt') == receipt), None) if receipt and record.get('verification_result') == 'pass' else None
        if run is None: continue
        try:
            body = json.loads(store.read_blob(receipt))
            state, contract, node, facts = review_dispatch._context(ledger, selector, nid)
            if run['request']['identity']['contract_sha'] != facts['contract_sha']: continue        # the pass belongs to another contract: it reruns
            before = dict(facts, artifact=body['artifact'], generation=body['generation'], internal_revision=body['internal_revision'],
                          inputs=body['inputs'], checks_sha=body['checks_sha'], unknowns=[])
            checks = [check['id'] for check in node['checks']]
            def request(subject, execution):
                return rr.build_check(kind='node', root={'project_id': ledger.project_id, 'task_id': state['task_id']},
                    contract_revision=state['approved']['revision'], contract_sha=state['approved']['sha'], review_id=review_dispatch.CHECK_NODE, required=True, subject=subject,
                    scope={k: node.get(k, []) for k in ('read', 'write', 'acceptance')}, criteria=node['checks'],
                    policy={'recorded': True}, authority={'recorded': True}, budget={'recorded': True},
                    inputs={'artifact': subject['artifact'], 'revision': state['approved']['revision'], 'acceptance': {key: True for key in node.get('acceptance', [])} or {'node': nid},
                            'inputs': dict(subject['inputs']) or {'node': nid}, 'configuration': {'checks_sha': subject['checks_sha']},
                            'environment': {'node': nid}, 'checks': checks},
                    execution=wrapped(execution))
            evidence[nid] = {'previous': request(before, run['request']['identity']['execution']),
                             'current': request(facts, rr._execution(port.execution_identity(node)))}
        except (LedgerError, OSError, ValueError, KeyError, TypeError):
            continue
    return rerun_order(ledger, selector, finding_id, evidence=evidence, _recorded=True)


def rerun_order(ledger, selector, finding_id, *, evidence=None, _recorded=False):
    """W21 (T11 [E3], [E5]) + 2.5-A: what to run again after a repair for one open node finding: the failed check(s) of the node the finding
    is attached to first, then the checks of the nodes in the finding's dependency scope, in definition order. Read-only.

    Impact decides, and a missing basis widens instead of narrowing:
    - a finding with no recorded dependency scope (or a scope node the definition no longer has) cannot say what it affects: the whole
      suite is ordered after the failed check (`widened`);
    - `evidence` = {node_id: kwargs of review_request.evidence_status (previous, current, binding_*, changed_paths, basis)}. This function
      computes the status itself, never trusts a supplied one. A scope node whose evidence `applies` is not rerun (listed in `reusable`
      with its request ids as provenance); `recheck` reruns its checks; `insufficient` (missing/malformed/incomplete evidence) widens to the whole suite, except a node whose only
      change is its own candidate without a neutral basis, which is simply rerun (its candidate is what the repair changed). A scope node without an
      entry is rerun. The failed check and the rest of the finding's own node are always rerun, whatever the evidence says. An old
      snapshot's PASS therefore never covers a new snapshot unless its status is `applies`."""
    from . import findings, review_request
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
    recorded = list(item.get('scope_nodes') or [])
    scope_nodes = [n['id'] for n in definition if n['id'] in set(recorded)]
    widened, reusable, statuses = [], [], {}
    if not recorded or set(recorded) - set(by_id):
        widened.append({'node': None, 'reason': 'the finding records no usable dependency scope; impact cannot be established'})
    for nid in scope_nodes:
        if not isinstance(evidence, dict) or nid not in evidence: continue
        unbound = None
        if not _recorded and isinstance(evidence[nid], dict) and {'previous', 'current'} <= set(evidence[nid]):
            unbound = _unbound(ledger, selector, nid, evidence[nid])
        if unbound:
            statuses[nid] = {'status': 'insufficient', 'reasons': [unbound], 'changed': [], 'reusable': False}
            widened.append({'node': nid, 'reason': unbound})
            continue
        try:
            statuses[nid] = review_request.evidence_status(**evidence[nid])
        except TypeError as error:
            raise LedgerError('Evidence for node ' + nid + ' is not evidence_status arguments: ' + str(error)) from error
        if statuses[nid]['status'] == 'insufficient' and statuses[nid]['changed'] != ['evidence.candidate']:
            widened.append({'node': nid, 'reason': '; '.join(statuses[nid]['reasons']) or 'evidence insufficient'})
    rerun_nodes = [nid for nid in scope_nodes if (statuses.get(nid) or {}).get('status') != 'applies']
    for nid in scope_nodes:
        if nid not in rerun_nodes:
            reusable.append({'node': nid, 'checks': [c['id'] for c in by_id[nid]['checks']],
                             'request': evidence[nid]['current']['id'], 'previous_request': evidence[nid]['previous']['id'],
                             'basis': statuses[nid].get('reuse_basis')})
    everything = [c['id'] for n in definition for c in n['checks']]
    rest = [c['id'] for c in by_id[item['node']]['checks'] if c['id'] not in failed_first]
    if widened:
        ordered = failed_first + rest + [c for c in everything if c not in failed_first and c not in rest]
        affected = [c for c in ordered if c not in failed_first and c not in rest]
    else:
        affected = [c['id'] for nid in rerun_nodes for c in by_id[nid]['checks']]
        ordered = failed_first + affected + rest
    return {'finding': finding_id, 'node': item['node'], 'failed_first': failed_first, 'scope_nodes': scope_nodes, 'affected': affected,
            'ordered': ordered, 'whole_suite': everything, 'smaller_than_suite': len(ordered) < len(everything),
            'widened': widened, 'reusable': reusable, 'evidence_status': {k: v['status'] for k, v in statuses.items()}}
