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
from .ledger import LedgerError, canonical
from .locking_core import task_lock
from .project_apply_core import apply as apply_project
from .snapshots import Snapshots
from .v2 import authority, engine, internal_plan as ip, plan as plans, retention
from .v2.verifiers import command


def handoff(ledger, selector, *, control=None):
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
    action = {'kind': 'apply', 'paths': changed or sorted(declared), 'nodes': [nid]}
    ip.decide(ledger, root, contract, sha, action, ctx, 'onecrew.common_handoff')

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
        checked = CandidateChecker(ledger, root['selector'])(item, record['artifact'])
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
            raise LedgerError('No file changes require a project apply; no synthetic apply receipt is issued.')
        fence()
        delivered = command.artifact_sha(ledger.project)
        if delivered != tree: raise LedgerError('Applied project differs from the verified candidate; no handoff was published.')
        ref = store.blob(canonical(receipt).encode())
        proof = {'kind': 'workflow-handoff-receipt', 'root': root['task_id'], 'contract_sha': sha,
                 'contract_revision': view['contract_revision'], 'internal_revision': view['internal_revision'],
                 'node': nid, 'generation': record['generation'], 'integration_artifact': record['artifact'],
                 'delivered_artifact': delivered, 'method': 'v1-cas-apply', 'apply_receipt': ref,
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
