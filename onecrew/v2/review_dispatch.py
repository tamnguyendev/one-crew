"""W26: engine consumers of the existing rules, never model decision authority.

Every configured node check is mandatory. Optional reviews are separate approved
policy IDs and never publish node.verification, acceptance, or a human request.
Injected checkers own their usual provider/budget boundary; this adapter does not
select models, change pins or implement provider fallback.
"""
import copy
import json

from ..ledger import LedgerError, canonical, content_hash, key_field
from ..snapshots import Snapshots
from . import engine, internal_plan as ip, plan, review_policy


def _context(ledger, selector, node):
    key_field(node)
    with ledger.transaction() as conn:
        root, contract, sha = ip.context(ledger, conn, selector, 'sequential-engine')
        view = engine.state(ledger, root['selector'], conn)
    if not view['definition'] or node not in view['nodes']: raise LedgerError('Unknown review node.')
    if view['definition_contract_sha'] != sha:
        raise LedgerError('Revise the internal plan against the current approved contract before review.')
    item = next(n for n in view['definition']['nodes'] if n['id'] == node)
    record = view['nodes'][node]
    facts = {'node': node, 'contract_sha': sha, 'internal_revision': view['internal_revision'], 'generation': record['generation'],
             'artifact': record['artifact'], 'inputs': record['inputs'], 'checks_sha': content_hash(item['checks']),
             'state': record['state'], 'phase': record['phase'],
             'unknowns': sorted(view.get('unknown_blockers', {}).get(node, []))}
    return root, contract, item, facts


def _decide(ledger, selector, review_id, facts, *, required):
    ready = facts['state'] in ('produced', 'verified', 'accepted') and facts['phase'] != 'held'
    unknowns = facts['unknowns'] + (['node-held:' + facts['node']] if facts['phase'] == 'held' else [])
    decision = review_policy.decide(ledger, selector, review_id, artifact_sha=facts['artifact'] or 'unproduced:' + facts['node'],
        ready=ready, unknowns=unknowns, evidence=['engine-input:' + content_hash(facts)], required=required, input_state=facts)
    action = decision.get('action')
    if action not in review_policy.ACTIONS or (required and action == 'SKIP'):
        raise LedgerError('A mandatory engine check cannot be skipped by a review decision.')
    return decision


def required(ledger, selector, node, check_ids):
    """Gate invoked by engine.verify before its checker; no caller can weaken checks."""
    root, _, item, facts = _context(ledger, selector, node)
    configured = [check['id'] for check in item['checks']]
    if (not isinstance(check_ids, (list, tuple)) or any(not isinstance(c, str) for c in check_ids) or len(check_ids) != len(configured)
            or set(check_ids) != set(configured)):
        raise LedgerError('Required review must include every configured node check.')
    decision = _decide(ledger, root['selector'], node, facts, required=True)
    if _context(ledger, root['selector'], node)[3] != facts:
        raise LedgerError('Engine input changed before required verification; recompute the decision.')
    return decision


def optional(ledger, selector, node, review_id, checker, artifact):
    """Skip/defer/hold before any call, or retain a non-authoritative observation."""
    key_field(review_id)
    root, contract, item, facts = _context(ledger, selector, node)
    nodes = engine.state(ledger, root['selector'])['definition']['nodes']
    mandatory = {m['id'] for m in contract['milestones']} | {n['id'] for n in nodes}
    mandatory.update(check['id'] for n in nodes for check in n['checks'])
    if review_id in mandatory:
        raise LedgerError('A required node, check or contract milestone is not an optional review.')
    policy = review_policy.normalize(contract.get('review_policy', review_policy.DEFAULT))
    if review_id not in policy['optional_reviews']:
        raise LedgerError('Optional review ID is not sealed in the approved root policy.')
    if artifact != facts['artifact']:
        raise LedgerError('Optional review artifact does not match the current node.')
    decision = _decide(ledger, root['selector'], review_id, facts, required=False)
    result = {'decision': decision, 'node': node, 'review_id': review_id, 'artifact': artifact,
              'executed': False, 'receipt': None, 'changes_node_state': False}
    if decision['action'] != 'REVIEW':
        return dict(result, status={'SKIP': 'skipped', 'DEFER': 'deferred', 'HOLD': 'held'}[decision['action']])
    if _context(ledger, root['selector'], node)[3] != facts:
        raise LedgerError('Engine input changed before optional review; recompute the decision.')
    key = decision['record']['key']
    with ledger.transaction() as conn:
        old = conn.execute("SELECT payload FROM events WHERE task_id=? AND kind='review.observed' AND json_extract(payload,'$.decision_key')=? AND json_extract(payload,'$.applicable')=1 ORDER BY seq DESC LIMIT 1",
                           (root['task_id'], key)).fetchone()
    if old:
        old = json.loads(old['payload'])
        Snapshots(ledger.state_root).read_blob(old['receipt'])
        return dict(result, status='observed', receipt=old['receipt'], cached_observation=True)
    if not callable(checker): raise LedgerError('A REVIEW decision requires a checker.')
    observed = checker(copy.deepcopy(item), artifact)
    if not isinstance(observed, dict) or len(canonical(observed).encode('utf-8')) > 65536:
        raise LedgerError('Optional review must return a bounded observation object.')
    # Fields named SKIP/HOLD/action are data. Only the sealed rule result controls
    # dispatch; this receipt cannot substitute for mandatory verification.
    body = {'kind': 'optional-review-observation', 'root': root['task_id'], 'review_id': review_id,
            'node': node, 'inputs': facts, 'decision_key': key, 'observed': observed, 'authority': 'none'}
    receipt = Snapshots(ledger.state_root).blob(canonical(body).encode('utf-8'))
    with ledger.transaction(write=True) as conn:
        current = engine.state(ledger, root['selector'], conn)
        current_record = current['nodes'].get(node, {})
        applicable = (current['root_status'] == 'approved' and current['contract_sha'] == root['approved']['sha']
                      and current['internal_revision'] == facts['internal_revision']
                      and current_record.get('generation') == facts['generation']
                      and current_record.get('artifact') == artifact and current_record.get('phase') != 'held'
                      and not current.get('unknown_blockers', {}).get(node))
        plan.emit(ledger, conn, root['task_id'], 'review.observed', {'plan': root['name'], 'revision': root['approved']['revision'],
            'node': node, 'review_id': review_id, 'decision_key': key, 'receipt': receipt, 'applicable': applicable,
            'internal_revision': facts['internal_revision'], 'generation': facts['generation'], 'artifact': artifact,
            'grants_authority': False})
    return dict(result, status='observed' if applicable else 'stale_observation', executed=True, receipt=receipt,
                cached_observation=False)
