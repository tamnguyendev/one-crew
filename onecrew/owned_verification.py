"""Completion checks from receipts, independent of the worker's success wording."""
import re
from .ledger import LedgerError


def check_tests(state):
    current = state['snapshot']
    latest = {}
    for index, test in enumerate(state['tests']):
        if test['evidence'].get('snapshot') != current: continue
        # Old receipts did not record the test path. Keep their evidence visible,
        # but do not infer coverage of a named mandatory test from an unknown path.
        latest[test.get('test_path', 'legacy:'+str(index))] = test
    if not latest or not any(t['passed'] for t in latest.values()):
        raise LedgerError('Current candidate has no passing sandbox test receipt.')
    if any(not t['passed'] for t in latest.values()):
        raise LedgerError('Current candidate still has a failing test receipt.')
    required = {p for p in state['files'] if re.search(r'(^|/)test[^/]*\.py$', p)
                and state['original'].get(p) is not None}
    if not required <= set(latest):
        raise LedgerError('Captured original tests lack current passing receipts: '+', '.join(sorted(required-set(latest))))
    return {'snapshot':current,'tests':sorted(required),'status':'passed',
            'limitation':'Covers captured original tests; undiscovered behavior and device testing are not verified.'}
