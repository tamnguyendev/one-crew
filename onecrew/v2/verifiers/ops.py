"""W39 operation evidence verifier, with reconcile-before-retry semantics.

Reads bounded pre/post snapshots, an operation receipt, and a separate
reconciliation observation. It never performs or retries the operation. Unknown
or pending outcomes are inconclusive; no provider or external service is inferred.
"""
import hashlib
import sys

from ...ledger import LedgerError, content_hash
from ...snapshots import scoped_path
from . import data, port

NAME = 'ops'


def _conditions(value, label):
    if not isinstance(value, list) or not 1 <= len(value) <= 100:
        raise LedgerError(label + ': requires 1-100 explicit conditions.')
    for condition in value:
        data._object(condition, ('path', 'equals'), label)
        if set(condition) != {'path', 'equals'} or not isinstance(condition['path'], list) or not condition['path']:
            raise LedgerError(label + ': each condition requires a key path and expected value.')
        if any(not isinstance(p, str) or not p for p in condition['path']):
            raise LedgerError(label + ': paths contain nonempty object keys.')
        # Reuse canonical JSON's finite/serializable-value validation.
        content_hash(condition['equals'])
    return value


def validate_config(config, label):
    data._object(config, ('pre', 'post', 'receipt', 'reconcile', 'operation_id', 'request_sha', 'preconditions', 'postconditions'), label)
    paths = {k: scoped_path(config.get(k)) for k in ('pre', 'post', 'receipt', 'reconcile')}
    if len(set(paths.values())) != 4: raise LedgerError(label + ': four distinct evidence files are required.')
    operation = config.get('operation_id')
    if not isinstance(operation, str) or not 1 <= len(operation) <= 100:
        raise LedgerError(label + ': operation_id is required.')
    request = config.get('request_sha')
    if not isinstance(request, str) or not data.re.fullmatch('[0-9a-f]{64}', request) or set(request) == {'0'}:
        raise LedgerError(label + ': request_sha must pin a nonzero SHA256 request.')
    return {**paths, 'operation_id': operation, 'request_sha': request,
            'preconditions': _conditions(config.get('preconditions'), label + '.preconditions'),
            'postconditions': _conditions(config.get('postconditions'), label + '.postconditions')}


def _check(document, conditions, label):
    problems = []
    for condition in conditions:
        current = document
        for key in condition['path']:
            if not isinstance(current, dict) or key not in current:
                problems.append(label + ': missing ' + '.'.join(condition['path']))
                break
            current = current[key]
        else:
            # Canonical equality distinguishes true from 1 and includes structure.
            if content_hash(current) != content_hash(condition['equals']):
                problems.append(label + ': condition differs at ' + '.'.join(condition['path']))
    return problems


def run(config, box):
    documents, hashes = {}, {}
    try:
        for field in ('pre', 'post', 'receipt', 'reconcile'):
            text = box.read_text(config[field])
            hashes[field] = hashlib.sha256(text.encode('utf-8')).hexdigest()
            documents[field] = data.json_value(text)
            if not isinstance(documents[field], dict): raise LedgerError(field + ': expected JSON object.')
    except (LedgerError, FileNotFoundError, UnicodeDecodeError) as error:
        return data.report([{'id': 'evidence', 'ok': False, 'checked': len(documents), 'problems': [str(error)]}])
    receipt, observed = documents['receipt'], documents['reconcile']
    if receipt.get('status') in ('unknown', 'pending') or observed.get('status') in ('unknown', 'pending'):
        raise port.Inconclusive('Operation outcome is unsettled; reconcile before any retry. No operation was executed.')
    checks = []
    for field, conditions in (('pre', config['preconditions']), ('post', config['postconditions'])):
        problems = _check(documents[field], conditions, field)
        checks.append({'id': field + 'conditions', 'ok': not problems, 'checked': len(conditions), 'problems': problems})
    expected = {'operation_id': config['operation_id'], 'request_sha': config['request_sha'],
                'status': 'succeeded', 'pre_sha': hashes['pre'], 'post_sha': hashes['post']}
    problems = [f'Operation receipt {key} differs or is missing.' for key, want in expected.items() if receipt.get(key) != want]
    checks.append({'id': 'receipt', 'ok': not problems, 'checked': len(expected), 'problems': problems})
    expected = {'operation_id': config['operation_id'], 'request_sha': config['request_sha'],
                'status': 'succeeded', 'receipt_sha': hashes['receipt'], 'post_sha': hashes['post']}
    problems = [f'Reconciliation {key} differs or is missing.' for key, want in expected.items() if observed.get(key) != want]
    if not isinstance(observed.get('observation_id'), str) or not observed['observation_id']:
        problems.append('Reconciliation requires an observation_id distinct from the operation receipt.')
    checks.append({'id': 'reconcile', 'ok': not problems, 'checked': len(expected) + 1, 'problems': problems})
    return data.report(checks)


port.register(sys.modules[__name__])
