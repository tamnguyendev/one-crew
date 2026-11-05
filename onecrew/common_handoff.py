"""Authorized common handoff through the existing v1 project apply CAS.

No branch, push or root acceptance is implicit. Root milestones must still run
against the delivered working tree and the owner must accept the result.
"""
import json
import tempfile
from pathlib import Path

from .common_verification import CandidateChecker, candidate_tree, snapshot_candidate
from .control_core import Control, migrate
from .git_candidate_core import GitCandidate
from .ledger import LedgerError, canonical, content_hash
from .locking_core import task_lock
from .project_apply_core import apply as apply_project
from .snapshots import Snapshots
from .v2 import authority, engine, internal_plan as ip, plan as plans, retention
from .v2.verifiers import command


def receipt_valid(ledger, proof, record):
    """Validate the durable Control evidence, including a real no-write observation."""
    method = proof.get('method')
    key = 'apply_receipt' if method == 'v1-cas-apply' else 'observation_receipt' if method == 'observed-existing-tree' else None
    if key is None or not proof.get(key): return False
    receipt = json.loads(Snapshots(ledger.state_root).read_blob(proof[key]))
    result = receipt.get('result', {})
    if (receipt.get('status') != 'verified' or not result.get('verified')
            or result.get('candidate') != proof.get('delivered_artifact')):
        return False
    with ledger.transaction() as conn:
        action = conn.execute("SELECT payload FROM actions WHERE task_id=? AND status='verified' AND receipt=?",
                              (record['child'], canonical(receipt))).fetchone()
    if action is None: return False
    if method == 'observed-existing-tree':
        payload = json.loads(action['payload'])
        return (payload.get('kind') == 'observe_verified_tree' and result.get('no_project_write') is True
                and payload.get('candidate') == proof['delivered_artifact']
                and payload.get('verification_receipt') == record['verification_receipt']
                and payload.get('checks_sha') == content_hash(proof['checks'])
                and result.get('checks_sha') == payload.get('checks_sha'))
    return True


def _observe_existing(ledger, control, record, tree, checked, fence):
    payload = {'kind': 'observe_verified_tree', 'candidate': tree,
               'verification_receipt': record['verification_receipt'], 'checks_sha': content_hash(checked)}
    action = control.propose_action(record['child'], 'wf-observe-' + content_hash(payload)[:32], payload)
    def observe(value):
        fence()
        return dict(value, verified=command.artifact_sha(ledger.project) == tree, no_project_write=True)
    if action['status'] == 'proposed':
        control.authorize_action(action['id'], action['revision']); action['status'] = 'authorized'
    if action['status'] in ('unknown', 'executing'):
        receipt = control.reconcile_action(action['id'], action['revision'], observe)
    elif action['status'] == 'verified':
        receipt = json.loads(action['receipt'])
    else:
        receipt = control.execute_action(action['id'], observe)
    if receipt.get('status') != 'verified': raise LedgerError('Existing artifact observation is unconfirmed; reconcile before handoff.')
    return receipt


def handoff(ledger, selector, *, control=None):
    with ledger.transaction() as conn:
        root, _, _ = ip.context(ledger, conn, selector, 'sequential-engine')
        deadline = ip.ceilings(ledger, conn, root)['deadline']
    with command.snapshot_limits(deadline):
        return _handoff(ledger, selector, control=control)


def _handoff(ledger, selector, *, control=None):
    migrate(ledger)
    control = control or Control(ledger)
    store = Snapshots(ledger.state_root)
    with ledger.transaction() as conn:
        root, contract, sha = ip.context(ledger, conn, selector, 'sequential-engine')
        view = engine.state(ledger, root['selector'], conn)
        ctx = ip.ceilings(ledger, conn, root)
    if not engine.verification_ready(ledger, root['selector']):
        raise LedgerError('Handoff requires every current node and mandatory integration verified without unresolved blockers.')
    integrations = [item for item in view['definition']['nodes'] if item['integration']]
    if len(integrations) != 1:
        raise LedgerError('Production handoff currently requires one unambiguous final integration node.')
    item = integrations[0]; nid = item['id']; record = view['nodes'][nid]
    manifest = snapshot_candidate(ledger, view, nid, record['artifact'])
    adapter = GitCandidate(ledger, store)
    tree = candidate_tree(ledger, manifest)
    base_tree = adapter.git('rev-parse', manifest['head'] + '^{tree}').decode().strip()
    changed = command.changed_paths(ledger.project, base_tree, tree)
    declared = {path for node in view['definition']['nodes'] for path in node['write']}
    if not set(changed) <= declared:
        raise LedgerError('Candidate includes changes outside its internal write provenance.')
    if changed:
        action = {'kind': 'apply', 'paths': changed, 'nodes': [nid]}
        ip.decide(ledger, root, contract, sha, action, ctx, 'onecrew.common_handoff')
    else:
        ip.decide(ledger, root, contract, sha, {'kind': 'decision', 'q': 'Q9', 'nodes': [nid],
                  'evidence': [record['verification_receipt']], 'artifact_matches': True}, ctx, 'onecrew.common_handoff')

    def fence():
        with ledger.transaction() as conn:
            current = engine.state(ledger, root['selector'], conn)
        if (not engine._publication_current(current, view, nid) or current['nodes'][nid]['artifact'] != record['artifact']
                or not engine.verification_ready(ledger, root['selector'])):
            raise LedgerError('Root, candidate, dependency evidence or unresolved facts changed before delivery.')
        if adapter.git('rev-parse', 'HEAD').decode().strip() != manifest['head']:
            raise LedgerError('Project HEAD changed after the candidate base was captured.')

    # The root lock serializes handoff attempts. Control still owns action
    # idempotency/reconciliation, and each write rechecks the root fence.
    with task_lock(ledger, root['task_id']):
        fence()
        if engine.root_ready(ledger, root['selector'], tree):
            return {'state': 'delivered', 'artifact': tree, 'idempotent': True}
        checked = CandidateChecker(ledger, root['selector'])(item, record['artifact'],
                                                            previous_receipt=record['verification_receipt'])
        if checked['candidate_tree'] != tree or any(row['result'] != 'pass' for row in checked['checks']):
            raise LedgerError('The actual final candidate failed its approved root checks; project unchanged.')
        fence()
        # Preserve unrelated user edits by refusing the handoff, never copying
        # their contents into a supposedly verified candidate.
        actual = command.artifact_sha(ledger.project)
        if set(command.changed_paths(ledger.project, base_tree, actual)) - set(changed):
            raise LedgerError('Project has changes outside this verified candidate; preserve and rebase before applying.')
        files = []
        for path in changed:
            raw = adapter.git('rev-parse', '--verify', '--quiet', tree + ':' + path, allow_failure=True)
            files.append({'path': path, 'blob': raw.decode().strip() if raw else None})
        if changed:
            with tempfile.TemporaryDirectory(prefix='oc-handoff-') as temp:
                materialized = command._checkout(ledger.project, tree, temp)
                receipt = apply_project(ledger, control, record['child'], Path(ledger.project), materialized,
                    manifest['head'], tree, files, {}, ledger.state_root / 'workflow-rollback' / root['task_id'], guard=fence)
        else:
            receipt = _observe_existing(ledger, control, record, tree, checked, fence)
        fence()
        delivered = command.artifact_sha(ledger.project)
        if delivered != tree: raise LedgerError('Applied project differs from the verified candidate; no handoff was published.')
        ref = store.blob(canonical(receipt).encode())
        proof = {'kind': 'workflow-handoff-receipt', 'root': root['task_id'], 'contract_sha': sha,
                 'contract_revision': view['contract_revision'], 'internal_revision': view['internal_revision'],
                 'node': nid, 'generation': record['generation'], 'integration_artifact': record['artifact'],
                 'delivered_artifact': delivered, 'method': 'v1-cas-apply' if changed else 'observed-existing-tree',
                 'apply_receipt' if changed else 'observation_receipt': ref,
                 'child': record['child'], 'checks': checked, 'grants_root_acceptance': False}
        proof_ref = store.blob(canonical(proof).encode())
        with ledger.transaction(write=True) as conn:
            current = engine.state(ledger, root['selector'], conn)
            if not engine._publication_current(current, view, nid):
                raise LedgerError('Root changed after apply; evidence retained without a delivery claim.')
            retention.pin_evidence(ledger, root['selector'], delivered, strict=True)
            plans.emit(ledger, conn, root['task_id'], 'workflow.handoff',
                       {'plan': root['name'], 'revision': view['contract_revision'], 'receipt': proof_ref})
        return {'state': 'delivered', 'artifact': delivered, 'receipt': proof_ref, 'requires_owner_acceptance': True}
