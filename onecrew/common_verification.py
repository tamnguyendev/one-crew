"""Shared candidate verifier using the owner's sealed milestone verifiers.

The adapter constructs the actual Git candidate with v1 Integration.tree, checks
out that tree, and calls the existing command verifier, the reviewer verifier or a
registered adapter port. It never executes node prose or treats a report as a file
candidate. A reviewer milestone is judged for independence against the proposal
authors AND the actual producing child models before any call, and its provider
call goes through the metered root budget. Owner-manual checks are refused here:
they need the owner.

Declared outputs (R11 finding A, corrected in R12 P1-A; docs/wf/r12-notes.md invariants 1-3). A node's `write` list is a PERMISSION,
not a list of files that must exist: the artifact v1 protocol lets a worker write content, an empty file (`content: ""`) or delete a
file (`content: null`) inside it. The structural output guard (`output_expectations` + `output_check`) compares what the candidate
DECLARED for each write path with the real candidate tree, relative to the authenticated source (below):
  * declared content or empty  -> the path must exist in the candidate tree with exactly that content (an empty file is valid);
  * declared deleted (null)    -> the path must be absent;
  * not declared (unchanged)   -> no obligation; a write path the worker left alone is permission it did not use.
The guard infers NO obligation from prose: a path named in the node `output` or in a contract output criterion is not thereby
required to exist, to be absent or to be non-empty (R11 did, and refused a correct deletion). The state an output must be in is the
approved contract's to judge, through its own milestones (command / reviewer / adapter), which run on the same candidate after the
guard. A worker's declaration never exempts a candidate from them.

Outside the write scope (R12 P1-B, invariant 4; R13 P1-S, docs/wf/r13-notes.md invariants 1-3) nothing may differ from ONE baseline
the ENGINE authenticated for this attempt; the `parent` chain a candidate declares about itself is never that baseline, and the project
HEAD, its working tree and the producers are not alternatives to choose from. The baseline is
  * the source capture the engine took when it admitted the attempt (`node.started` `source`, engine._source_capture): the HEAD it
    observed and the working-tree bytes of the node's read+write scope, uncommitted edits, new files and deletions included; it must be
    a raw capture of this project at the HEAD observed now (R12: a HEAD change during the run is refused);
  * overlaid, on a captured path in a producer's `write`, with that producer's output, when the engine recorded the producer for this
    attempt (`node.started` inputs) and it is still at that artifact and generation and not failed; an integration also takes every
    producer's current artifact (what `snapshot_candidate` already requires it to carry). Producers that disagree on a path outside
    the write scope give no baseline for it: unverifiable.
Every captured or manifest path outside `write` is compared IN THE CANDIDATE GIT TREE (so a path the manifest leaves out, which the tree
takes from the base commit, is judged too); a manifest path outside the captured scope is a change outside the write scope. A missing,
unreadable or foreign capture, or none recorded (a root started before R13), makes the candidate unverifiable: it fails and is kept;
no other baseline is chosen. A parent chain may still exist (inheritance is not banned), but each link must load, verify and come from
this project at the same base commit, or the candidate's provenance is unverifiable and it fails.
`OUT_RULE` versions this rule: a stored receipt of an older rule is never reused as its proof. Text reports present in the write scope
are then scanned for source references (v2/verifiers/output_refs.py).
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


OUT_RULE = 'r13-declared-vs-candidate+engine-source-capture'


def _engine_source(store, record, project, observed, problems):
    """R13 P1-S: the ONE source baseline of this attempt - the capture the engine itself took when it admitted the attempt, recorded in
    node.started (`source`): the HEAD it observed and the working-tree bytes of the node's read+write scope, uncommitted edits, new
    files (a blob) and deletions (None) included. None, with the reason appended to `problems`, when it cannot be authenticated: no
    capture recorded (node.started written before R13, or a scope the engine could not capture), a capture that is missing or fails
    verification, one that is not a raw capture of this project, or one taken at another commit than the HEAD observed now. The
    verifier never falls back to the project HEAD or the current working tree instead."""
    key = record.get('source')
    if not key:
        reason = record.get('source_error')
        problems.append('no engine-recorded source capture for this attempt (' + (reason or 'node.started written before R13') + ')')
        return None
    try:
        capture = store.load(key)
    except (LedgerError, OSError, ValueError, TypeError, KeyError):
        problems.append('the engine source capture ' + str(key)[:16] + ' is missing or fails verification'); return None
    if (capture.get('parent') is not None or not isinstance(capture.get('source'), str)
            or Path(capture['source']).resolve() != project):
        problems.append('the engine source capture ' + key[:16] + ' is not a capture of this project'); return None
    if not observed or capture.get('head') != observed:
        problems.append('the engine source capture ' + key[:16] + ' was taken at another commit than the project HEAD'); return None
    return capture


def _producer_values(store, view, item, problems):
    """({path: blob}, {path}): what the engine-recorded producers of this node put on a path of their own `write` (module docstring),
    and the paths on which two of them disagree (no single inherited value)."""
    definitions = {node['id']: node for node in view['definition']['nodes']}
    record = view['nodes'][item['id']]
    sources = {}
    for source, binding in (record.get('inputs') or {}).items():
        current = view['nodes'].get(source) or {}
        if (isinstance(binding, dict) and current.get('artifact') and binding.get('artifact') == current['artifact']
                and binding.get('generation') == current.get('generation') and current.get('verification_result') != 'fail'):
            sources[source] = current['artifact']
    if item['integration']:
        for nid, node in definitions.items():
            if nid != item['id'] and node['write'] and view['nodes'][nid].get('artifact'):
                sources.setdefault(nid, view['nodes'][nid]['artifact'])
    values, conflicts = {}, set()
    for source, artifact in sorted(sources.items()):
        if source not in definitions: continue
        try:
            produced = store.load(artifact)['files']
        except (LedgerError, OSError, ValueError):
            problems.append('producer ' + source + ' artifact is unreadable'); continue
        for path in definitions[source]['write']:
            if path not in produced: continue
            if path in values and values[path] != produced[path]['working']: conflicts.add(path)
            values.setdefault(path, produced[path]['working'])
    return values, conflicts


def _chain_problems(store, manifest, project):
    """A declared parent chain is never the baseline, but every link must load, verify and come from this project at the same base commit."""
    problems, key, seen = [], manifest.get('parent'), set()
    while key:
        if key in seen or len(seen) >= 64:
            problems.append('snapshot chain is cyclic or deeper than 64 links'); break
        seen.add(key)
        try:
            link = store.load(key)
        except (LedgerError, OSError, ValueError, TypeError):
            problems.append('parent snapshot ' + str(key)[:16] + ' is missing or fails verification'); break
        if (not isinstance(link.get('source'), str) or Path(link['source']).resolve() != project
                or link.get('head') != manifest.get('head')):
            problems.append('parent snapshot ' + key[:16] + ' is not from this project at the candidate base commit'); break
        key = link.get('parent')
    return problems


def output_expectations(store, manifest, item, contract=None, *, ledger=None, view=None):
    """R12: what the candidate artifact declared for each write path, and the manifest paths outside the write scope that differ from
    the engine-authenticated baseline (module docstring). `manifest` is the loaded candidate snapshot; `ledger` and `view`
    (engine.state) supply that baseline - without them nothing is authenticated and the candidate fails. `contract` is accepted for
    callers of the R11 signature; no obligation is read from its prose (nor from the node's)."""
    files, write = manifest['files'], list(item['write'])
    if ledger is None or view is None:
        return {'write': write, 'declared': {path: 'unchanged' for path in write}, 'blobs': {}, 'outside': [], 'baseline': {},
                'provenance': ['no engine view was given to authenticate the candidate baseline']}
    project = Path(ledger.project).resolve()
    head, problems = manifest.get('head'), []
    observed = Snapshots.git(project, 'rev-parse', '--verify', 'HEAD', allow_failure=True)
    observed = observed.decode('ascii', 'replace').strip() if observed is not None else None
    if not isinstance(head, str) or observed is None or observed != head:
        problems.append('the candidate base commit is not the project HEAD')
    problems += _chain_problems(store, manifest, project)
    # R13 P1-S: ONE baseline - the engine's capture for this attempt, overlaid with the engine-recorded producer outputs on its scope
    capture = _engine_source(store, view['nodes'][item['id']], project, observed, problems)
    produced, conflicts = _producer_values(store, view, item, problems)
    baseline = {}
    if capture is not None:
        baseline = {path: row['working'] for path, row in capture['files'].items()}
        baseline.update({path: value for path, value in produced.items() if path in baseline})
        for path in sorted(conflicts):
            if path in baseline and path not in write:
                problems.append('engine-recorded producers disagree on ' + path); del baseline[path]
    declared, blobs = {}, {}
    for path in write:
        want = files[path]['working'] if path in files else None
        if path not in files or (path in baseline and want == baseline[path]):
            declared[path] = 'unchanged'
        elif want is None:
            declared[path] = 'deleted'
        else:
            declared[path] = 'empty' if not store.read_blob(want) else 'content'
        if path in files and want is not None: blobs[path] = want
    # every captured or manifest path outside `write` must be the baseline IN THE CANDIDATE TREE (output_check compares it there, so a
    # path the manifest leaves out - which the tree then takes from the base commit - is judged too); a manifest path with no baseline
    # (outside the captured scope) is a change outside the write scope. A write path the manifest leaves out is declared unchanged:
    # its tree content must be the baseline as well. Without an authenticated capture nothing is compared: the candidate is unverifiable.
    outside, compare = [], {}
    if capture is not None:
        for path in sorted(set(files) | set(baseline)):
            if path in write:
                if path not in files and path in baseline: compare[path] = baseline[path]
            elif path in baseline:
                compare[path] = baseline[path]
            elif path not in conflicts:
                outside.append(path)
    return {'write': write, 'declared': declared, 'blobs': blobs, 'outside': outside, 'baseline': compare, 'provenance': problems}


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
    declared = expected['declared']
    present = {path for path in outputs if path in tree_files and (root / path).is_file()}
    missing = [path for path in outputs if path not in present and declared.get(path) in ('content', 'empty')]
    still = [path for path in outputs if declared.get(path) == 'deleted' and path in present]
    differs = []
    for path, blob in expected['blobs'].items():
        if path in present and declared.get(path) != 'unchanged':
            # the same clean conversion GitCandidate used to seal the tree (filters=True), so CRLF settings cannot change the answer
            if command._git(root, 'hash-object', '--path=' + path, '--stdin', input=store.read_blob(blob)) != oids[path]: differs.append(path)
    # R13 P1-S: the candidate tree against the engine-authenticated baseline (output_expectations), with the same clean conversion
    outside = list(expected['outside'])
    for path, blob in sorted((expected.get('baseline') or {}).items()):
        if blob is None:
            same = path not in oids
        else:
            same = path in oids and command._git(root, 'hash-object', '--path=' + path, '--stdin', input=store.read_blob(blob)) == oids[path]
        if not same: (differs if path in outputs else outside).append(path)
    outside, differs = sorted(set(outside)), sorted(set(differs))
    refs, reports = [], []
    for path in outputs:
        if path not in present or not output_refs.is_text_report(path): continue
        reports.append(path)
        refs.extend(output_refs.scan((root / path).read_bytes().decode('utf-8', 'replace')))
    judged = output_refs.check(tree_files, refs, outputs)
    reasons = []
    provenance = list(expected.get('provenance', ['no authenticated baseline']))
    for label, paths in (('declared output missing', missing), ('declared deletion still present', still),
                         ('output content differs from the artifact', differs), ('changed outside the write scope', outside),
                         ('candidate provenance unverifiable', provenance)):
        if paths: reasons.append(label + ': ' + ', '.join(paths[:5]))
    if judged['result'] == 'fail': reasons.append(f"{judged['offender_count']} unresolved reference(s): " + '; '.join(judged['offenders']))
    return {'id': 'OUT', 'rule': OUT_RULE, 'result': 'fail' if reasons else 'pass', 'outputs': list(outputs), 'reports': reports,
            'missing': missing, 'declared': dict(declared), 'still_present': still, 'content_differs': differs,
            'outside_scope': outside, 'provenance': provenance,
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
        if (not isinstance(observed.get('output_check'), dict) or observed['output_check'].get('result') != 'pass'
                or observed['output_check'].get('rule') != OUT_RULE):
            return None   # R10: no declared-output / reference check, or (R12) one of an older rule, cannot stand in for it
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
            out = output_check(checkout, item['write'], output_expectations(store, manifest, item, contract, ledger=ledger, view=view), store)
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
