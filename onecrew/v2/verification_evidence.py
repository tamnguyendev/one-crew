"""W07/W08: explicit verification bindings and conservative reuse decisions.

Identities come from immutable Git trees or retained v1 snapshots. Environment
values are hashed, never copied into receipts. No behavioral-neutrality inference
is implemented: an assertion that a path is unrelated cannot authorize reuse.
"""
import json
import platform
import re
import sys
from pathlib import Path, PurePosixPath

from ..ledger import LedgerError, canonical, content_hash
from ..snapshots import Snapshots
from . import contract as contracts
from .verifiers import artifact as artifacts, command

HEX = re.compile(r'(?:[0-9a-f]{40}|[0-9a-f]{64})')


def _identity(value):
    if not isinstance(value, str) or not HEX.fullmatch(value) or set(value) == {'0'}:
        raise LedgerError('Evidence requires a nonzero artifact identity.')
    return value


def environment(env=None):
    """Observed interpreter/platform and the effective verifier environment.

    This is a fingerprint of these observations, not a claim to inventory every
    operating-system library or authenticate an external model provider.
    """
    return {'python': sys.version, 'implementation': sys.implementation.name,
            'platform': platform.platform(), 'machine': platform.machine(),
            'variables': {str(k): content_hash(str(v)) for k, v in sorted((env or {}).items())}}


def _path(value):
    if value == '.': return value
    if (not isinstance(value, str) or not value or '\\' in value or ':' in value or
            value.startswith('/') or any(p in ('', '.', '..') for p in value.split('/'))):
        raise LedgerError('Evidence input must be a canonical relative path.')
    return PurePosixPath(value).as_posix()


def input_identities(ledger, source, artifact, paths):
    """Fingerprint named inputs inside the actual immutable artifact, not live files."""
    _identity(artifact)
    if not isinstance(paths, list) or not paths: raise LedgerError('Evidence needs explicit named input paths.')
    paths = [_path(p) for p in paths]
    if len(set(paths)) != len(paths): raise LedgerError('Evidence inputs must be unique.')
    source = Path(source).resolve()
    if artifacts.is_git(source):
        top = command.toplevel(source)
        prefix = source.relative_to(top).as_posix()
        records = command._git(top, 'ls-tree', '-r', '-z', artifact)
        all_files = {}
        for record in records.split('\0'):
            if not record: continue
            head, name = record.split('\t', 1)
            mode, kind, oid = head.split()
            all_files[name] = {'mode': mode, 'kind': kind, 'identity': oid}
    else:
        # Old proof comes from capture(); a read-only freshness query may inspect
        # today's as-yet-unretained snapshot without creating store objects.
        store = Snapshots(ledger.state_root)
        if (store.root / 'manifests' / (artifact + '.json')).exists():
            artifacts.validate_evidence(ledger, artifact)
            manifest = store.load(artifact)
        else:
            manifest = artifacts._manifest(source)
            if content_hash(manifest) != artifact:
                raise LedgerError('The requested input artifact is neither retained nor current.')
        if Path(manifest['source']).resolve() != source: raise LedgerError('Snapshot input source mismatch.')
        prefix = '.'
        all_files = {name: {'identity': row['working']} for name, row in manifest['files'].items()}
    result = {}
    for path in paths:
        full = '/'.join(p for p in (prefix, path) if p != '.') or '.'
        selected = {name: value for name, value in all_files.items()
                    if full == '.' or name == full or name.startswith(full + '/')}
        # Missing is represented, not silently dropped; deletion changes its identity.
        result[path] = {'sha256': content_hash(selected), 'files': len(selected), 'missing': not bool(selected)}
    return result


def bind(*, artifact, revision, acceptance, inputs, configuration, environment, checks):
    _identity(artifact)
    if type(revision) is not int or revision < 1: raise LedgerError('Evidence revision must be a positive integer.')
    for label, value in (('acceptance', acceptance), ('inputs', inputs), ('configuration', configuration), ('environment', environment)):
        if not isinstance(value, dict) or not value: raise LedgerError('Evidence ' + label + ' must be a nonempty mapping.')
    if (not isinstance(checks, list) or not checks or any(not isinstance(c, str) or not c for c in checks)
            or len(set(checks)) != len(checks)):
        raise LedgerError('Evidence needs explicit unique check IDs.')
    return {'version': 1, 'artifact': artifact, 'revision': revision,
            'acceptance': content_hash(acceptance),
            'inputs': {name: content_hash(value) for name, value in sorted(inputs.items())},
            'configuration': content_hash(configuration), 'environment': content_hash(environment),
            'environment_components': {name: content_hash(value) for name, value in sorted(environment.items())},
            'checks': list(checks)}


def for_receipt(ledger, context, milestone, artifact, env=None):
    """Called before checking, with the actual artifact and effective environment."""
    contract = context['contract']
    target = contract['understanding']['target']
    acceptance = dict(zip(contracts.output_ids(contract['output']), contract['output']))
    covered = {key: acceptance[key] for key in milestone['covers']}
    kind = milestone['verifier']['type']
    criteria = milestone['verifier']['config'].get('criteria') if kind == 'reviewer' else None
    checks = [c['id'] for c in criteria] if criteria else [milestone['id']]
    observed = environment(env)
    value = bind(artifact=artifact, revision=context['revision'], acceptance=covered,
                 inputs=input_identities(ledger, Path(ledger.project) / target['repo'], artifact, target['paths']),
                 configuration={'verifier': milestone['verifier'], 'milestone_title': milestone['title']}, environment=observed, checks=checks)
    value['input_paths'] = list(target['paths'])
    value['source'] = target['repo']
    value['environment_observed'] = observed
    return value


def _valid(value):
    try:
        _identity(value['artifact'])
        return (type(value['version']) is int and value['version'] == 1 and type(value['revision']) is int and value['revision'] > 0
                and all(isinstance(value[k], str) and re.fullmatch('[0-9a-f]{64}', value[k])
                        for k in ('acceptance', 'configuration', 'environment'))
                and isinstance(value['inputs'], dict) and bool(value['inputs'])
                and all(isinstance(k, str) and re.fullmatch('[0-9a-f]{64}', v) for k, v in value['inputs'].items())
                and isinstance(value['checks'], list) and bool(value['checks'])
                and all(isinstance(c, str) and c for c in value['checks']))
    except (KeyError, TypeError, ValueError):
        return False


def assess(previous, current, *, neutral=(), changed_paths=None, submodule_changed=False, kind='command', basis=None):
    """Pure decision; a caller persists returned reuse_basis before relying on reuse."""
    checks = list(previous.get('checks', [])) if isinstance(previous, dict) else []
    result = {'status': 'stale', 'reusable': False, 'reasons': [], 'checks_to_rerun': checks,
              'reuse_basis': None, 'requires_record': False}
    if not _valid(previous) or not _valid(current):
        result['reasons'] = ['evidence binding missing or malformed']
        return result
    checks = sorted(set(previous['checks']) | set(current['checks']))
    result['checks_to_rerun'] = checks
    reasons = result['reasons']
    if previous['acceptance'] != current['acceptance']: reasons.append('acceptance changed')
    for name in sorted(set(previous['inputs']) | set(current['inputs'])):
        if previous['inputs'].get(name) != current['inputs'].get(name): reasons.append('input changed: ' + name)
    if previous['configuration'] != current['configuration']: reasons.append('checker configuration changed')
    if previous['environment'] != current['environment']:
        before, after = previous.get('environment_components', {}), current.get('environment_components', {})
        changed = [k for k in sorted(set(before) | set(after)) if before.get(k) != after.get(k)]
        reasons.append('checker environment changed' + (': ' + ', '.join(changed) if changed else ''))
    if previous['checks'] != current['checks']: reasons.append('check set changed')
    if reasons: return result
    if previous['artifact'] == current['artifact']:
        return dict(result, status='current', reusable=True, checks_to_rerun=[])
    if basis and basis.get('kind') == 'path':
        reasons.append('artifact changed; a path-only reuse assertion is insufficient')
        return result
    if basis and basis.get('kind') == 'behavioral':
        reasons.append('behavioral reuse basis lacks evidence' if not basis.get('evidence') else
                       'behavioral-neutrality evaluator is not available; recheck the original check set')
        return result
    if kind != 'command' or submodule_changed:
        reasons.append('artifact changed; this verifier or submodule change requires rechecking')
        return result
    if not changed_paths or not neutral:
        reasons.append('artifact changed without a recorded valid reuse basis; impact unknown')
        return result
    matching = {p: [g for g in neutral if contracts.neutral_match(p, [g])] for p in changed_paths}
    if not all(matching.values()):
        reasons.append('artifact changed outside declared scope.neutral; recheck original checks')
        return result
    reuse = {'kind': 'scope.neutral', 'contract_revision': current['revision'],
             'from_artifact': previous['artifact'], 'to_artifact': current['artifact'],
             'changed_paths': sorted(changed_paths), 'matching_globs': matching}
    return dict(result, status='reuse_eligible', reusable=True, requires_record=True,
                checks_to_rerun=[], reuse_basis=reuse)


def require_binding(body):
    """New opt-in workflow passes cannot downgrade to unbound legacy evidence."""
    binding = body.get('evidence_binding') if isinstance(body, dict) else None
    if (not _valid(binding) or binding['artifact'] != body.get('artifact_sha') or
            binding['revision'] != body.get('revision')):
        raise LedgerError('Required evidence binding is missing, malformed or does not bind this receipt.')
    return binding


def receipt_assessment(ledger, contract, milestone, revision, receipt, current_artifact, *, task_id=None, conn=None, require_bound=False, recorded_environment=False):
    """Read-only view used by plan/verdict; None means an unbound legacy receipt."""
    try:
        body = json.loads(Snapshots(ledger.state_root).read_blob(receipt))
        if not isinstance(body, dict): raise ValueError('receipt body must be an object')
    except (LedgerError, OSError, ValueError, TypeError) as error:
        return {'status': 'stale', 'reusable': False, 'reasons': ['receipt missing or malformed: ' + str(error)],
                'checks_to_rerun': [milestone['id']], 'reuse_basis': None, 'requires_record': False, 'recorded': False}
    old = body.get('evidence_binding')
    if old is None and not require_bound: return None
    try:
        require_binding(body)
    except LedgerError as error:
        return {'status': 'stale', 'reusable': False, 'reasons': [str(error)], 'checks_to_rerun': [milestone['id']],
                'reuse_basis': None, 'requires_record': False, 'recorded': False}
    kind = milestone['verifier']['type']
    directory = Path(body.get('cwd') or ledger.project)
    env = command.verifier_env(directory) if kind in ('command', 'reviewer') else None
    try:
        current = for_receipt(ledger, {'contract': contract, 'revision': revision}, milestone, current_artifact, env)
        if recorded_environment:
            # An owner observes an already authenticated recorded verdict; their
            # shell is not the verifier. New execution/reuse keeps the default
            # strict environment comparison. Only shell variables are inherited:
            # interpreter/platform and every artifact/config/input check remain.
            observed = old.get('environment_observed') or {}
            if (not observed or content_hash(observed) != old.get('environment')
                    or {k: content_hash(v) for k, v in observed.items()} != old.get('environment_components')):
                raise LedgerError('Recorded execution environment is missing or inconsistent.')
            environment_changed = current['environment'] != old.get('environment')
            context = environment(env)
            context['variables'] = observed['variables']
            current['environment'] = content_hash(context)
            current['environment_components'] = {k: content_hash(v) for k, v in context.items()}
            current['environment_observed'] = context
        changed = submodules = []
        if old.get('artifact') != current_artifact and artifacts.is_git(directory):
            changed = command.changed_paths(directory, old['artifact'], current_artifact)
            submodules = command.submodule_paths(directory, old['artifact'], current_artifact)
        result = assess(old, current, neutral=contracts.neutral_globs(contract), changed_paths=changed,
                        submodule_changed=bool(submodules), kind=kind)
    except (LedgerError, OSError, KeyError, TypeError, ValueError) as error:
        return {'status': 'stale', 'reusable': False, 'reasons': ['cannot verify current evidence binding: ' + str(error)],
                'checks_to_rerun': old.get('checks', [milestone['id']]) if isinstance(old, dict) else [milestone['id']],
                'reuse_basis': None, 'requires_record': False, 'recorded': False}
    result['binding'] = current
    result['recorded'] = False
    if recorded_environment: result['environment_changed'] = environment_changed
    if result['requires_record']:
        result['reuse_key'] = content_hash({'receipt': receipt, 'current': current, 'basis': result['reuse_basis']})
        if task_id:
            def exists(opened):
                return bool(opened.execute("SELECT 1 FROM events WHERE task_id=? AND kind='evidence.reuse' AND json_extract(payload,'$.key')=?",
                                           (task_id, result['reuse_key'])).fetchone())
            if conn is not None: result['recorded'] = exists(conn)
            else:
                with ledger.transaction() as opened: result['recorded'] = exists(opened)
    return result


def record_reuse(ledger, selector, milestone_id, receipt, current_artifact, *, conn=None, recorded_environment=False):
    """Persist one exact reuse basis; no verdict, generation, status or grant changes."""
    from . import plan
    if conn is None:
        with ledger.transaction(write=True) as opened:
            return record_reuse(ledger, selector, milestone_id, receipt, current_artifact, conn=opened, recorded_environment=recorded_environment)
    state = plan.anchor_events(ledger, conn, selector)
    target = plan.resolve(ledger, state)
    if target is None: raise LedgerError('Evidence reuse requires an open approved plan.')
    revision = target['revision']
    contract = plan.load(ledger, state, revision)[0]
    milestone = next((m for m in contract['milestones'] if m['id'] == milestone_id), None)
    if milestone is None: raise LedgerError('Unknown evidence milestone.')
    if target.get('frozen') and milestone_id in target['frozen']['frozen']:
        raise LedgerError('A pending amendment freezes this evidence milestone.')
    candidates = [v for v in state['verdicts'] if v['milestone'] == milestone_id and v['revision'] <= revision]
    candidate = candidates[-1] if candidates else None
    if (not candidate or candidate['result'] != 'pass' or candidate['receipt'] != receipt or
            (candidate['revision'], milestone_id, receipt) not in state['issued']):
        raise LedgerError('Reuse requires the latest applicable authentic passing receipt.')
    if artifacts.identity(ledger.project) != current_artifact:
        raise LedgerError('Reuse target is not the current project artifact.')
    result = receipt_assessment(ledger, contract, milestone, revision, receipt, current_artifact, task_id=state['task_id'], conn=conn, recorded_environment=recorded_environment)
    if result is None or not result['reusable'] or not result['requires_record']:
        raise LedgerError('No valid changed-artifact reuse basis: ' + '; '.join(result['reasons'] if result else ['legacy receipt has no binding']))
    payload = {'plan': state['name'], 'revision': revision, 'milestone': milestone_id, 'receipt': receipt,
               'key': result['reuse_key'], 'basis': result['reuse_basis'],
               'binding_sha256': content_hash(result['binding']), 'grants_authority': False}
    if conn.execute("SELECT 1 FROM events WHERE task_id=? AND kind='evidence.reuse' AND json_extract(payload,'$.key')=?",
                    (state['task_id'], payload['key'])).fetchone():
        return payload
    if artifacts.identity(ledger.project) != current_artifact:
        raise LedgerError('The artifact changed while recording its reuse basis.')
    from .retention import pin_trees
    pin_trees(ledger, selector, candidate['artifact_sha'], current_artifact)
    plan.emit(ledger, conn, state['task_id'], 'evidence.reuse', payload)
    return payload
