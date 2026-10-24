"""W26: deterministic review depth, using the v1 decision validator and W03 audit.

This component authorizes no execution and creates no human request. Mandatory
contract milestones always remain verifiers; SKIP is only an optional review in
the approved policy. A caller must still use the normal dispatch/verdict gates.
The returned validity binds the decision to the exact revision and artifact.
"""
import json

from .. import routing
from ..ledger import LedgerError, content_hash, key_field, text_field
from . import decisions, plan as plans

ACTIONS = ('SKIP', 'DEFER', 'REVIEW', 'HOLD')
DEFAULT = {'depth': 'standard', 'optional_reviews': []}


def normalize(value):
    if not isinstance(value, dict) or set(value) != {'depth', 'optional_reviews'}:
        raise LedgerError('review_policy: expected depth and optional_reviews.')
    if value['depth'] not in ('light', 'standard', 'deep'):
        raise LedgerError('review_policy.depth: light, standard or deep.')
    rows = value['optional_reviews']
    if not isinstance(rows, list) or len(rows) > 64 or len(set(map(str, rows))) != len(rows):
        raise LedgerError('review_policy.optional_reviews: at most 64 distinct review IDs.')
    for row in rows:
        key_field(row)
    return {'depth': value['depth'], 'optional_reviews': sorted(rows)}


def evaluate(policy, *, node, mandatory, ready=True, unknowns=(), evidence):
    """Common pure rule; inputs are controller facts, never model verdict fields."""
    policy = normalize(policy)
    key_field(node)
    if type(mandatory) is not bool or type(ready) is not bool:
        raise LedgerError('Review readiness and mandatory status must be booleans.')
    if not isinstance(unknowns, (list, tuple)) or any(not isinstance(x, str) or not x for x in unknowns):
        raise LedgerError('Review unknowns must name the unresolved facts.')
    if not mandatory and node not in policy['optional_reviews']:
        raise LedgerError('Review is not a contract milestone or an approved optional review.')
    if unknowns:
        action, reason = 'HOLD', 'Unresolved prerequisite: ' + ', '.join(unknowns)
    elif not ready:
        action, reason = 'DEFER', 'Prerequisite evidence is not ready; keep the review queued.'
    elif mandatory:
        action, reason = 'REVIEW', 'Required contract milestone; depth policy cannot skip it.'
    elif policy['depth'] == 'light':
        action, reason = 'SKIP', 'The approved light policy permits skipping this optional review.'
    else:
        action, reason = 'REVIEW', 'The approved policy requires this optional review at ' + policy['depth'] + ' depth.'
    # One validator for v1 and v2; validation is necessary, never a new grant.
    checked = routing.validate_decision({'action': action, 'confidence': 1.0,
                                        'reason': reason[:1000], 'evidence': list(evidence)}, ACTIONS, evidence)
    # v1's requires_review describes confidence in a proposal, not whether the
    # product task needs review. Do not leak an ambiguous False beside REVIEW.
    return {key: checked[key] for key in ('action', 'confidence', 'reason', 'evidence')}


def decide(ledger, name, node, *, artifact_sha, ready=True, unknowns=(), evidence=(), required=False, input_state=None):
    """Read approved root, evaluate, and idempotently persist a W03 decision.

    Runtime-supplied unknowns add to the root's unknowns; they cannot erase them.
    Cache identity includes policy, input, artifact and contract revision. Cache
    hits still call the shared validator. No result completes a milestone.
    """
    key_field(node)
    if type(required) is not bool: raise LedgerError('Required review status must be a boolean.')
    if input_state is not None and not isinstance(input_state, dict): raise LedgerError('Review input state must be a mapping.')
    text_field(artifact_sha, 'decision artifact', 128)
    if not isinstance(evidence, (tuple, list)) or not all(isinstance(x, str) and x for x in evidence):
        raise LedgerError('Decision evidence must be references.')
    if not isinstance(unknowns, (tuple, list)) or not all(isinstance(x, str) and x for x in unknowns):
        raise LedgerError('Decision unknowns must be named.')
    with ledger.transaction() as conn:
        state = plans.anchor_events(ledger, conn, name)
        if state['status'] != 'approved':
            raise LedgerError('Review policy requires the current contract to be approved.')
        revision = state['approved']['revision']
        contract, sha = plans.load(ledger, state, revision)
        policy = normalize(contract.get('review_policy', DEFAULT))
        mandatory = required or node in {m['id'] for m in contract['milestones']}
        unresolved = {u['id'] for u in contract['understanding'].get('unknowns', []) if u['status'] != 'closed'}
        unresolved.update(unknowns)
        references = sorted(set(evidence) | {f'contract:{sha}', f'artifact:{artifact_sha}'})
        inputs = {'node': node, 'artifact_sha': artifact_sha, 'ready': ready,
                  'unknowns': sorted(unresolved), 'evidence': references, 'mandatory': mandatory}
        if input_state is not None: inputs['engine'] = input_state
        cache_key = 'review-policy-' + content_hash({'revision': revision, 'sha': sha, 'policy': policy, 'input': inputs})
        stored = conn.execute("SELECT payload FROM events WHERE task_id=? AND kind='decision.recorded' AND json_extract(payload,'$.key')=? ORDER BY seq DESC LIMIT 1",
                              (state['task_id'], cache_key)).fetchone()
    verdict = evaluate(policy, node=node, mandatory=mandatory, ready=ready,
                       unknowns=inputs['unknowns'], evidence=references)
    validity = {'revision': revision, 'contract_sha': sha, 'artifact_sha': artifact_sha,
                'input_sha': content_hash(inputs), 'policy_sha': content_hash(policy),
                'action': verdict['action'], 'depth': policy['depth']}
    if stored:
        record = json.loads(stored['payload'])
        if record.get('validity') != validity or record.get('subject') != {'component': 'review_policy', 'model': 'rules'}:
            raise LedgerError('Cached review decision does not match its bound inputs.')
    else:
        record = decisions.record(ledger, state['task_id'], subject={'component': 'review_policy', 'model': 'rules'},
            authority={'grant_id': 'approved-contract:' + sha, 'revision': str(revision)}, evidence=references,
            basis=verdict['reason'], scope=node, validity=validity, key=cache_key)
    # Race check: the record remains an audit fact, but cannot authorize a newer plan.
    with ledger.transaction() as conn:
        current = plans.anchor_events(ledger, conn, name)
        if current['status'] != 'approved' or current['approved']['sha'] != sha or current['approved']['revision'] != revision:
            raise LedgerError('The plan changed while deciding review depth; recompute on the current revision.')
    return dict(verdict, validity=validity, cached=bool(stored), record=record)
