"""Shared candidate verifier using the owner's sealed milestone commands.

The adapter constructs the actual Git candidate with v1 Integration.tree, checks
out that tree, and calls the existing command verifier. It never executes node
prose or treats a report as a file candidate. Reviewer/manual adapters are not
implemented here and are refused explicitly.
"""
import copy
import tempfile
import time
from pathlib import Path

from .git_candidate_core import GitCandidate
from .ledger import LedgerError, canonical, content_hash
from .snapshots import Snapshots
from .v2 import authority, contract as contracts, engine, internal_plan as ip, retention, verification_evidence
from .v2.verifiers import command


def snapshot_candidate(ledger, view, nid, artifact):
    store = Snapshots(ledger.state_root)
    manifest = store.load(artifact)
    if Path(manifest['source']).resolve() != Path(ledger.project).resolve() or not manifest['head']:
        raise LedgerError('Candidate must retain this project and its captured Git base.')
    item = next(node for node in view['definition']['nodes'] if node['id'] == nid)
    if item['integration']:
        producers = [node for node in view['definition']['nodes'] if node['id'] != nid and node['write']]
        required = {path for node in producers for path in node['write']}
        if not required <= set(manifest['files']):
            raise LedgerError('Integration candidate omitted a required producer write path.')
        # A read-only integration combines actual producer bytes. Integration
        # edits are allowed only on its explicitly declared write paths.
        merged = {}
        for producer in producers:
            upstream = store.load(view['nodes'][producer['id']]['artifact'])
            for path in producer['write']:
                wanted = upstream['files'][path]['working']
                if path in merged and merged[path] != wanted and path not in item['write']:
                    raise LedgerError('Producer write conflict requires explicit integration ownership: ' + path)
                merged[path] = wanted
        for path, wanted in merged.items():
            if path not in item['write'] and manifest['files'][path]['working'] != wanted:
                raise LedgerError('Integration candidate lost producer output: ' + path)
    return manifest


def candidate_tree(ledger, manifest):
    store = Snapshots(ledger.state_root)
    adapter = GitCandidate(ledger, store)
    with tempfile.TemporaryDirectory(prefix='oc-candidate-') as temp:
        return adapter.tree(manifest, manifest['head'], Path(temp) / 'index')


class CandidateChecker:
    """Production check port: every node check ID names an approved milestone."""
    def __init__(self, ledger, selector):
        self.ledger, self.selector = ledger, selector

    def __call__(self, item, artifact):
        started = time.monotonic()
        ledger = self.ledger
        with ledger.transaction() as conn:
            root, contract, sha = ip.context(ledger, conn, self.selector, 'sequential-engine')
            view = engine.state(ledger, root['selector'], conn)
            ctx = ip.ceilings(ledger, conn, root)
        nid = item['id']
        current_item = next(node for node in view['definition']['nodes'] if node['id'] == nid)
        if current_item != item or view['nodes'][nid]['artifact'] != artifact:
            raise LedgerError('Checker input differs from the current internal node.')
        manifest = snapshot_candidate(ledger, view, nid, artifact)
        milestones = {row['id']: row for row in contract['milestones']}
        from .v2 import repair_tasks
        order = repair_tasks.verification_order(ledger, root['selector'], nid, item['checks'])
        selected = []
        for check_id in order['ordered']:
            milestone = milestones.get(check_id)
            if not milestone or milestone['verifier']['type'] != 'command':
                raise LedgerError('Candidate checker needs an approved command milestone for every check ID; reviewer/manual support is pending.')
            if not set(milestone['covers']) <= set(item['acceptance']):
                raise LedgerError('Candidate milestone acceptance is outside this node acceptance.')
            selected.append(milestone)
        if item['integration'] and {row['id'] for row in selected} != set(milestones):
            raise LedgerError('Integration must run every approved root milestone before handoff.')
        ip.decide(ledger, root, contract, sha, {'kind': 'decision', 'q': 'Q4', 'operation': 'run', 'nodes': [nid],
                  'weakens': False, 'provenance': ['approved-contract:' + sha], 'unconfined': True,
                  'cost': {'calls': 0, 'seconds': min(item['execution_cap_seconds'], ctx['remaining_seconds'])}},
                  ctx, 'onecrew.common_verification')
        tree = candidate_tree(ledger, manifest)
        retention.pin_evidence(ledger, root['selector'], tree, strict=True)
        store = Snapshots(ledger.state_root)
        effective_environment = command.verifier_env(ledger.project)
        observed_env = verification_evidence.environment(effective_environment)
        inputs = {'source': {'head': manifest['head'], 'files': manifest['files']},
                  **{source: {key: value[key] for key in ('artifact', 'generation')}
                     for source, value in view['nodes'][nid]['inputs'].items()}}
        acceptance = dict(zip(contracts.output_ids(contract['output']), contract['output']))
        binding = verification_evidence.bind(artifact=artifact, revision=view['contract_revision'],
            acceptance={key: acceptance[key] for key in item['acceptance']}, inputs=inputs,
            configuration={'contract_sha': sha, 'milestones': selected, 'internal_revision': view['internal_revision'],
                           'execution_cap_seconds': item['execution_cap_seconds']},
            environment=observed_env, checks=[check['id'] for check in item['checks']])
        rows = []
        with tempfile.TemporaryDirectory(prefix='oc-node-check-') as temp:
            checkout = command._checkout(ledger.project, tree, temp)
            command._git(checkout, 'init', '-q')
            source_git = GitCandidate(ledger, store)
            for key in ('core.autocrlf', 'core.eol'):
                value = source_git.git('config', '--get', key, allow_failure=True)
                if value: command._git(checkout, 'config', key, value.decode().strip())
            command._git(checkout, 'add', '-A')
            actual = command._git(checkout, 'write-tree')
            if actual != tree: raise LedgerError('Materialized candidate differs from the sealed Git tree.')
            commit = command._git(checkout, '-c', 'user.name=OneCrew', '-c', 'user.email=onecrew@localhost',
                                  'commit-tree', tree, input=b'OneCrew candidate verification\n')
            command._git(checkout, 'update-ref', 'HEAD', commit)
            source = checkout / contract['understanding']['target']['repo']
            blocked_by = None
            for milestone in selected:
                if blocked_by:
                    evidence = store.blob(canonical({'kind': 'candidate-command-check-blocked', 'node': nid,
                        'snapshot': artifact, 'milestone': milestone['id'], 'prerequisite': blocked_by,
                        'repair_receipt': order['repair_receipt'], 'executed': False}).encode())
                    rows.append({'id': milestone['id'], 'result': 'blocked', 'evidence': evidence})
                    continue
                remaining = min(item['execution_cap_seconds'], ctx['remaining_seconds']) - (time.monotonic() - started)
                if remaining <= 0: raise LedgerError('Candidate verification exhausted its original node/root time cap.')
                effective = copy.deepcopy(milestone)
                effective['verifier']['config']['max_minutes'] = min(effective['verifier']['config']['max_minutes'], remaining / 60)
                ref, receipt = command.run(ledger, root['selector'], view['contract_revision'], sha, effective, source,
                                           effective_environment=effective_environment)
                proof = {'kind': 'candidate-command-check', 'node': nid, 'snapshot': artifact, 'tree': tree,
                         'milestone': milestone['id'], 'command_receipt': ref, 'evidence_binding': binding,
                         'effective_max_minutes': effective['verifier']['config']['max_minutes']}
                evidence = store.blob(canonical(proof).encode())
                result = command.expected_result(receipt)
                rows.append({'id': milestone['id'], 'result': result, 'evidence': evidence})
                if milestone['id'] in order['failed_first'] and result != 'pass':
                    blocked_by = {'id': milestone['id'], 'result': result, 'evidence': evidence}
        return {'artifact': artifact, 'checks': rows, 'candidate_tree': tree, 'evidence_binding': binding,
                'repair_order': order}
