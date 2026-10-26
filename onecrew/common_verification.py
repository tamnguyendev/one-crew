"""Shared candidate verifier using the owner's sealed milestone verifiers.

The adapter constructs the actual Git candidate with v1 Integration.tree, checks
out that tree, and calls the existing command verifier, the reviewer verifier or a
registered adapter port. It never executes node prose or treats a report as a file
candidate. A reviewer milestone is judged for independence against the proposal
authors AND the actual producing child models before any call, and its provider
call goes through the metered root budget. Owner-manual checks are refused here:
they need the owner.

Declared outputs (R11, Codex round 11 finding A). A node's `write` list is a PERMISSION, not a list of files that must exist: the
artifact v1 protocol lets a worker write content, an empty file (`content: ""`) or delete a file (`content: null`) inside it. The
structural output guard (`output_expectations` + `output_check`) therefore judges every write path by what the candidate artifact
DECLARED, relative to the source capture at the root of its snapshot chain (so resumed and inherited content counts as declared):
  * declared content or empty  -> the path must exist in the candidate tree with exactly that content (an empty file is valid);
  * declared deleted (null)    -> the path must be absent;
  * not declared (unchanged)   -> no obligation; a write path the worker left alone is permission it did not use.
A REQUIRED output is a write path that the approved definition names as a deliverable: it appears verbatim, as a whole path token, in
the node's own `output` list or in a contract `output` criterion of the node's `acceptance` ids. A required output must exist, must
not be declared deleted, and must have content unless the artifact itself declared it empty. Nothing else is inferred.
Outside the write scope nothing may change: the artifact API already refuses it (`artifact_core.artifacts`, `Snapshots.overlay`), and
the guard re-checks a non-integration candidate against its immediate parent snapshot so a manifest that bypassed the API fails too
(an integration candidate carries producer outputs; `snapshot_candidate` judges that). Text reports present in the write scope are
then scanned for source references (v2/verifiers/output_refs.py).
"""
import copy
import re
import json
import os
import datetime as dt
import tempfile
import time
from pathlib import Path

from .git_candidate_core import GitCandidate
from .ledger import LedgerError, canonical, content_hash
from .snapshots import Snapshots
from .v2 import authority, contract as contracts, engine, internal_plan as ip, retention, verification_evidence
from .v2.verifiers import command, output_refs, port, reviewer


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
        return adapter.tree(manifest, manifest['head'], Path(temp) / 'index', filters=True)


def materialized_tree(ledger, tree, temp):
    """Check the sealed tree out into `temp`, make it a repository and prove the files are the tree; returns the checkout root."""
    checkout = command._checkout(ledger.project, tree, temp)
    command._git(checkout, 'init', '-q')
    # The original first-approval trees must be real objects in this
    # disposable review repository. Git writes stay in its own object DB.
    objects = Path(command._git(ledger.project, 'rev-parse', '--git-path', 'objects'))
    if not objects.is_absolute(): objects = command.toplevel(ledger.project) / objects
    # bytes, not text mode: on Windows write_text would end the line with CR LF and git would look for "objects\r"
    (checkout / '.git' / 'objects' / 'info' / 'alternates').write_bytes((str(objects.resolve()).replace('\\', '/') + '\n').encode('utf-8'))
    source_git = GitCandidate(ledger, Snapshots(ledger.state_root))
    for key in ('core.autocrlf', 'core.eol'):
        value = source_git.git('config', '--get', key, allow_failure=True)
        if value: command._git(checkout, 'config', key, value.decode().strip())
    # Not `add -A` of a fresh repository: that drops the executable bit on Windows, honours ignore files (the project's and the machine's global
    # one) for files the tree tracks, and records a gitlink that checkout-index cannot materialize as deleted. The index starts as the sealed tree;
    # only the content of the files that really exist in the checkout is refreshed, so a changed file still changes the tree.
    quiet = ('-c', 'core.filemode=false', '-c', 'core.excludesFile=' + os.devnull)
    command._git(checkout, *quiet, 'read-tree', tree)
    present = []
    for row in command._git(checkout, *quiet, 'ls-files', '-s', '-z').split('\0'):
        meta, _, path = row.partition('\t')
        if not path or meta.startswith('160000'): continue
        if not os.path.lexists(checkout / path): raise LedgerError('Materialized candidate differs from the sealed Git tree.')
        present.append(path)
    if present:
        command._git(checkout, *quiet, 'add', '-u', '--force', '--pathspec-from-file=-', '--pathspec-file-nul', input='\0'.join(present).encode('utf-8'))
    # R10: a file the sealed tree does not contain is a difference too. `add -u` never sees untracked files, so list them with no ignore rules at all.
    extra = [row for row in command._git(checkout, *quiet, 'ls-files', '-o', '-z').split('\0') if row]
    if extra: raise LedgerError('Materialized candidate differs from the sealed Git tree.')
    actual = command._git(checkout, *quiet, 'write-tree')
    if actual != tree: raise LedgerError('Materialized candidate differs from the sealed Git tree.')
    return checkout


def _names_path(text, path):
    """`path` appears in `text` as a whole path token (not inside a longer path or name; a sentence-final '.' is allowed)."""
    return re.search(r'(?<![\w./\\-])' + re.escape(path) + r'(?![\w/\\-]|\.\w)', text) is not None


def required_outputs(item, contract=None):
    """R11: the write paths the approved definition names as deliverables (module docstring)."""
    texts = list(item.get('output') or [])
    if contract is not None:
        texts += [text for oid, text in zip(contracts.output_ids(contract['output']), contract['output']) if oid in item['acceptance']]
    return [path for path in item['write'] if any(_names_path(text, path) for text in texts)]


def output_expectations(store, manifest, item, contract=None):
    """R11: what the candidate artifact declared for each write path, the required outputs, and the paths changed outside the write
    scope. `manifest` is the loaded candidate snapshot (its parent chain ends at the project capture)."""
    files, write = manifest['files'], list(item['write'])
    parent = store.load(manifest['parent'])['files'] if manifest.get('parent') else files
    origin, chain, seen = parent, manifest.get('parent'), set()
    while chain:
        if chain in seen or len(seen) >= 64: raise LedgerError('Candidate snapshot chain is cyclic or too deep.')
        seen.add(chain)
        loaded = store.load(chain)
        origin, chain = loaded['files'], loaded.get('parent')
    declared, blobs = {}, {}
    for path in write:
        want = files[path]['working'] if path in files else None
        before = origin[path]['working'] if path in origin else None
        if path not in files or want == before:
            declared[path] = 'unchanged'
        elif want is None:
            declared[path] = 'deleted'
        else:
            declared[path] = 'empty' if not store.read_blob(want) else 'content'
        if path in files and want is not None: blobs[path] = want
    outside = [] if item['integration'] else sorted(
        path for path, row in files.items() if path not in write and (path not in parent or parent[path]['working'] != row['working']))
    return {'write': write, 'required': required_outputs(item, contract), 'declared': declared, 'blobs': blobs, 'outside': outside}


def output_check(checkout, outputs, expected, store):
    """R10/R11: the node's outputs are what its artifact declared (rule: module docstring), and every source reference in a text
    report of the write scope resolves against the candidate tree (grammar and limits: v2/verifiers/output_refs.py). Structural only;
    it never judges whether a finding is true. `checkout` is the materialized candidate; paths are relative to it; `expected` comes
    from `output_expectations` for the same candidate."""
    root = Path(checkout)
    listing = command._git(root, 'ls-files', '-s', '-z').split('\0')
    def counter(path):
        def lines():
            data = (root / path).read_bytes()
            return data.count(b'\n') + (1 if data and not data.endswith(b'\n') else 0)
        return lines
    tree_files, oids = {}, {}
    for row in listing:
        meta, _, path = row.partition('\t')
        if path and not meta.startswith('160000'):
            tree_files[path] = counter(path); oids[path] = meta.split()[1]
    declared, required = expected['declared'], expected['required']
    present = {path for path in outputs if path in tree_files and (root / path).is_file()}
    missing = [path for path in outputs if path not in present and (path in required or declared.get(path) in ('content', 'empty'))]
    deleted = [path for path in required if declared.get(path) == 'deleted']
    empty = [path for path in required if path in present and (root / path).stat().st_size == 0 and declared.get(path) != 'empty']
    still = [path for path in outputs if declared.get(path) == 'deleted' and path in present]
    differs = []
    for path, blob in expected['blobs'].items():
        if path in present and declared.get(path) != 'unchanged':
            # the same clean conversion GitCandidate used to seal the tree (filters=True), so CRLF settings cannot change the answer
            if command._git(root, 'hash-object', '--path=' + path, '--stdin', input=store.read_blob(blob)) != oids[path]: differs.append(path)
    refs, reports = [], []
    for path in outputs:
        if path not in present or not output_refs.is_text_report(path): continue
        reports.append(path)
        refs.extend(output_refs.scan((root / path).read_bytes().decode('utf-8', 'replace')))
    judged = output_refs.check(tree_files, refs, outputs)
    reasons = []
    for label, paths in (('required output missing', [p for p in missing if p in required]),
                         ('declared output missing', [p for p in missing if p not in required]), ('required output deleted', deleted), ('required output empty (the artifact did not declare it empty)', empty),
                         ('declared deletion still present', still), ('output content differs from the artifact', differs),
                         ('changed outside the write scope', expected['outside'])):
        if paths: reasons.append(label + ': ' + ', '.join(paths[:5]))
    if judged['result'] == 'fail': reasons.append(f"{judged['offender_count']} unresolved reference(s): " + '; '.join(judged['offenders']))
    return {'id': 'OUT', 'result': 'fail' if reasons else 'pass', 'outputs': list(outputs), 'reports': reports, 'missing': missing,
            'required': list(required), 'declared': dict(declared), 'deleted_required': deleted, 'empty_required': empty,
            'still_present': still, 'content_differs': differs, 'outside_scope': list(expected['outside']),
            'counts': judged['counts'], 'reasons': judged['reasons'], 'offenders': judged['offenders'], 'offender_count': judged['offender_count'],
            'ignored': judged['ignored'], 'reason': ' | '.join(reasons)}


def producer_pins(ledger, view, item):
    """Actual producing child handoffs, rather than a proposal-author guess."""
    definitions = {n['id']: n for n in view['definition']['nodes']}
    pending = ([n['id'] for n in definitions.values() if n['write']] if item['integration'] else [item['id']])
    seen, pins = set(), []
    while pending:
        nid = pending.pop()
        if nid in seen:
            continue
        seen.add(nid)
        record = view['nodes'][nid]
        pending.extend(record.get('inputs', {}))
        if not definitions[nid]['write']:
            continue
        if not record.get('child'):
            raise LedgerError('A candidate producer has no authentic child handoff.')
        handoff = ledger.task(record['child'], full=True)['handoff'].get('owned_execution') or {}
        if not handoff.get('provider') or not handoff.get('model'):
            raise LedgerError('Actual producer provider/model is unknown; reviewer independence cannot be shown.')
        pins.append({'node': nid, 'task': record['child'], 'generation': record['generation'],
                     'artifact': record['artifact'], 'provider': handoff['provider'], 'model': handoff['model']})
    return sorted(pins, key=lambda p: p['node'])


PROOF_FIELD = {'candidate-command-check': 'command_receipt', 'candidate-adapter-check': 'adapter_receipt',
               'candidate-reviewer-check': 'reviewer_receipt'}
PROOF_KIND = {'command': 'candidate-command-check', 'reviewer': 'candidate-reviewer-check'}   # adapters: candidate-adapter-check


def expected_of(kind, proof):
    """The verdict a retained proof supports, by the verifier family that wrote it."""
    if kind == 'candidate-command-check': return command.expected_result(proof)
    if kind == 'candidate-reviewer-check': return reviewer.expected_result(proof)
    return port.expected_result(proof)


def proof_mismatch(wrapper, proof, milestone, plan_sha, revision, tree):
    """Why a retained (wrapper, proof) pair is NOT the approved milestone's own check on this candidate tree under this
    contract; None when it is. Shared by handoff reuse and native learning so a receipt of another command, a no-op, a
    relabelled family, another contract/revision or a cap above the approved one can never stand in for the real check."""
    kind = wrapper.get('kind')
    field = PROOF_FIELD.get(kind)
    if not field or field not in wrapper: return 'unknown candidate proof kind'
    vtype = milestone['verifier']['type']
    want = PROOF_KIND.get(vtype, 'candidate-adapter-check')
    if kind != want: return 'proof family differs from the approved verifier type'
    if wrapper.get('milestone') != milestone['id'] or proof.get('milestone') != milestone['id']: return 'proof names another milestone'
    if wrapper.get('tree') != tree or proof.get('artifact_sha') != tree or proof.get('artifact_sha_after') != tree: return 'proof is not on this candidate tree'
    if proof.get('plan_sha') != plan_sha or proof.get('revision') != revision: return 'proof belongs to another contract or revision'
    expected_kind = {'candidate-command-check': 'command-receipt', 'candidate-reviewer-check': 'reviewer-receipt'}.get(kind)
    if expected_kind and proof.get('kind') != expected_kind: return 'proof body is not a ' + expected_kind
    config = milestone['verifier']['config']
    approved_cap = config['authority']['max_minutes'] if vtype not in ('command', 'reviewer') else config['max_minutes']
    effective = wrapper.get('effective_max_minutes')
    if not isinstance(effective, (int, float)) or isinstance(effective, bool) or effective <= 0 or effective > approved_cap:
        return 'effective time cap is not within the approved cap'
    if kind == 'candidate-command-check':
        if proof.get('argv') != config['argv']: return 'proof ran another command than the approved argv'
    else:
        recorded = proof.get('config')
        if not isinstance(recorded, dict): return 'proof records no verifier config'
        if vtype == 'reviewer':
            same = {k: v for k, v in recorded.items() if k != 'max_minutes'} == {k: v for k, v in config.items() if k != 'max_minutes'}
            cap_ok = isinstance(recorded.get('max_minutes'), (int, float)) and 0 < recorded['max_minutes'] <= config['max_minutes']
        else:
            own = lambda c: {k: v for k, v in c.items() if k != 'authority'}
            auth = lambda c: {k: v for k, v in (c.get('authority') or {}).items() if k != 'max_minutes'}
            same = own(recorded) == own(config) and auth(recorded) == auth(config)
            got = (recorded.get('authority') or {}).get('max_minutes')
            cap_ok = isinstance(got, (int, float)) and 0 < got <= approved_cap
        if not same: return 'proof config differs from the approved milestone config'
        if not cap_ok: return 'proof time cap is not within the approved cap'
    return None


def _reuse(ledger, view, item, artifact, previous_receipt, tree, binding, plan_sha, milestones):
    """Authenticate current node evidence (every retained proof is the approved check on this tree under this
    contract, with the binding the checker observed), then ask the shared W07 law."""
    if not previous_receipt or view['nodes'][item['id']].get('verification_receipt') != previous_receipt:
        return None
    store = Snapshots(ledger.state_root)
    try:
        previous = json.loads(store.read_blob(previous_receipt))
        record = view['nodes'][item['id']]
        if (previous.get('kind') != 'node-verifier-receipt' or previous.get('root') != view['root']
                or previous.get('node') != item['id'] or previous.get('generation') != record['generation']
                or previous.get('artifact') != artifact or previous.get('result') != 'pass'
                or previous.get('checks_sha') != content_hash(item['checks'])
                or previous.get('internal_revision') not in record.get('valid_internal_revisions', [view['internal_revision']])):
            return None
        observed = previous['observed']
        rows = observed['checks']
        ids = [c['id'] for c in item['checks']]
        if (observed.get('artifact') != artifact or observed.get('candidate_tree') != tree or len(rows) != len(ids)
                or {r['id'] for r in rows} != set(ids) or any(r['result'] != 'pass' for r in rows)):
            return None
        if not isinstance(observed.get('output_check'), dict) or observed['output_check'].get('result') != 'pass':
            return None   # R10: a receipt without the declared-output / reference check cannot stand in for it
        observed_binding = observed.get('evidence_binding')
        if observed_binding is None or observed_binding.get('revision') != view['contract_revision']:
            return None
        for row in rows:
            wrapper = json.loads(store.read_blob(row['evidence']))
            kind = wrapper.get('kind')
            field = PROOF_FIELD.get(kind)
            if not field or wrapper.get('node') != item['id'] or wrapper.get('snapshot') != artifact or wrapper.get('tree') != tree or wrapper.get('milestone') != row['id']:
                return None
            if wrapper.get('evidence_binding') != observed_binding:
                return None
            milestone = milestones.get(row['id'])
            if milestone is None:
                return None
            proof = json.loads(store.read_blob(wrapper[field]))
            if proof_mismatch(wrapper, proof, milestone, plan_sha, view['contract_revision'], tree) is not None:
                return None
            if expected_of(kind, proof) != 'pass':
                return None
        assessment = verification_evidence.assess(observed_binding, binding)
        if not assessment['reusable'] or assessment['requires_record']:
            return None
        return dict(observed, evidence_binding=binding, reuse_basis={'kind': 'current-node-verification', 'source_receipt': previous_receipt,
                    'root': view['root'], 'node': item['id'], 'generation': record['generation'], 'artifact': artifact, 'checks': ids})
    except (OSError, ValueError, KeyError, TypeError):
        return None


class CandidateChecker:
    """Production check port: every node check ID names an approved milestone."""
    def __init__(self, ledger, selector):
        self.ledger, self.selector = ledger, selector

    def __call__(self, item, artifact, *, previous_receipt=None):
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
            if not milestone or (milestone['verifier']['type'] not in ('command', 'reviewer') and not port.known(milestone['verifier']['type'])):
                raise LedgerError('Candidate checker needs an approved command milestone, an approved reviewer milestone or a registered adapter milestone; owner-manual checks require the owner.')
            if milestone['verifier']['type'] not in ('command', 'reviewer'):
                granted = milestone['verifier']['config']['authority']
                if granted['calls'] or granted['commands']:
                    raise LedgerError('Candidate adapters currently use the read-only port; model calls and host commands need separately metered execution.')
            if not set(milestone['covers']) <= set(item['acceptance']):
                raise LedgerError('Candidate milestone acceptance is outside this node acceptance.')
            selected.append(milestone)
        if item['integration'] and {row['id'] for row in selected} != set(milestones):
            raise LedgerError('Integration must run every approved root milestone before handoff.')
        actual_producers = producer_pins(ledger, view, item) if any(m['verifier']['type'] == 'reviewer' for m in selected) else []
        independence = {}
        for milestone in selected:
            if milestone['verifier']['type'] != 'reviewer':
                continue
            config = milestone['verifier']['config']
            levels = [reviewer.check_independence(root['revisions'][root['approved']['revision']], config)]
            levels += [reviewer.check_independence({'author': p['provider'], 'author_model': p['model']}, config) for p in actual_producers]
            rank = {'cross_vendor': 2, 'same_vendor_other_model': 1, 'unknown_author_vendor': 0}
            independence[milestone['id']] = dict(min(levels, key=lambda p: rank[p['level']]), producers=actual_producers, checks=levels)
        if any(m['verifier']['type'] == 'command' for m in selected):
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
                           'execution_cap_seconds': item['execution_cap_seconds'], 'producers': actual_producers},
            environment=observed_env, checks=[check['id'] for check in item['checks']])
        reused = _reuse(ledger, view, item, artifact, previous_receipt, tree, binding, sha, milestones)
        if reused is not None:
            return reused
        rows = []
        with tempfile.TemporaryDirectory(prefix='oc-node-check-') as temp:
            checkout = materialized_tree(ledger, tree, temp)
            commit = command._git(checkout, '-c', 'user.name=OneCrew', '-c', 'user.email=onecrew@localhost',
                                  'commit-tree', tree, input=b'OneCrew candidate verification\n')
            command._git(checkout, 'update-ref', 'HEAD', commit)
            out = output_check(checkout, item['write'], output_expectations(store, manifest, item, contract), store)
            out['evidence'] = store.blob(canonical(dict(out, kind='candidate-output-check', node=nid, snapshot=artifact, tree=tree)).encode())
            if out['result'] != 'pass':
                # A failed structural check fails the node like a failed milestone; the milestones are not run on a candidate that already fails.
                # The first one carries the failure so the engine receipt stays {one row per configured check}; the others are blocked.
                for number, milestone in enumerate(selected):
                    if number == 0:
                        rows.append({'id': milestone['id'], 'result': 'fail', 'evidence': out['evidence']})
                    else:
                        blocked = store.blob(canonical({'kind': 'candidate-command-check-blocked', 'node': nid, 'snapshot': artifact, 'milestone': milestone['id'],
                                                        'prerequisite': {'id': 'OUT', 'result': 'fail', 'evidence': out['evidence']}, 'executed': False}).encode())
                        rows.append({'id': milestone['id'], 'result': 'blocked', 'evidence': blocked})
                return {'artifact': artifact, 'checks': rows, 'candidate_tree': tree, 'evidence_binding': binding,
                        'repair_order': order, 'output_check': out}
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
                deadline = (dt.datetime.now(dt.timezone.utc) + dt.timedelta(seconds=remaining)).isoformat()
                effective = copy.deepcopy(milestone)
                kind = effective['verifier']['type']
                command_check = kind == 'command'
                limits = effective['verifier']['config'] if kind in ('command', 'reviewer') else effective['verifier']['config']['authority']
                limits['max_minutes'] = min(limits['max_minutes'], remaining / 60)
                if command_check:
                    ref, receipt = command.run(ledger, root['selector'], view['contract_revision'], sha, effective, source,
                                               effective_environment=effective_environment, deadline=deadline)
                    result = command.expected_result(receipt)
                elif kind == 'reviewer':
                    from .v2 import verdict, metered_verifier, findings, namespaces
                    with ledger.transaction() as conn:
                        approved, previous = verdict._review_context(ledger, conn, root, milestone['id'], milestone['verifier']['config'])
                    opened = findings.reviewer_context(ledger, root['selector'], milestone['id'], task_id=root['task_id']) if namespaces.has_capability(root, 'finding-register') else None
                    call_port = metered_verifier.ProviderCall(ledger, root['selector'], 'candidate:' + nid + ':' + artifact + ':' + milestone['id'])
                    ref, receipt = reviewer.run(ledger, root['name'], view['contract_revision'], sha, effective, source,
                        independence[milestone['id']], approved, previous, open_findings=opened,
                        evidence_context={'selector': root['selector'], 'revision': view['contract_revision'], 'contract': contract}, call_port=call_port)
                    result = reviewer.expected_result(receipt)
                else:
                    ref, receipt = port.run(ledger, root['selector'], view['contract_revision'], sha, effective, source, deadline=deadline)
                    port.record_violations(ledger, root['selector'], view['contract_revision'], milestone['id'], ref, receipt)
                    result = port.expected_result(receipt)
                proof = {'kind': 'candidate-command-check' if command_check else 'candidate-reviewer-check' if kind == 'reviewer' else 'candidate-adapter-check',
                         'node': nid, 'snapshot': artifact, 'tree': tree, 'milestone': milestone['id'],
                         'command_receipt' if command_check else 'reviewer_receipt' if kind == 'reviewer' else 'adapter_receipt': ref, 'evidence_binding': binding,
                         'effective_max_minutes': limits['max_minutes']}
                evidence = store.blob(canonical(proof).encode())
                rows.append({'id': milestone['id'], 'result': result, 'evidence': evidence})
                if milestone['id'] in order['failed_first'] and result != 'pass':
                    blocked_by = {'id': milestone['id'], 'result': result, 'evidence': evidence}
        return {'artifact': artifact, 'checks': rows, 'candidate_tree': tree, 'evidence_binding': binding,
                'repair_order': order, 'output_check': out}
