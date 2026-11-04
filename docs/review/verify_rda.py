"""Run with installed wheel Python -I; no checkout/test imports or real service.

python -I -B -X utf8 <copied verify_rda.py>
"""
import io
import json
from pathlib import Path

from onecrew import decision_client_core
from onecrew.ledger import LedgerError, content_hash
from onecrew.v2 import review_advice

KEY = 'synthetic-test-credential-only'


class Fake:
    def __init__(self, invalid=False, error=False):
        self.invalid, self.error, self.calls = invalid, error, 0

    def open(self, request, timeout):
        self.calls += 1
        if self.error:
            raise TimeoutError(KEY)
        data = {'model': 'jev-wheel-fixture', 'answers': {'workflow': {'type': 'choice', 'choice': 'option1',
                'confidence': .9, 'probabilities': {'option0': .05, 'option1': .9, 'abstain': .05}}}}
        return io.BytesIO(json.dumps({} if self.invalid else data).encode())


def main():
    checks = []
    def check(name, condition):
        checks.append({'name': name, 'pass': bool(condition)})
        if not condition:
            raise AssertionError(name)
    policy = {'depth': 'standard', 'optional_reviews': ['extra']}
    options = [{'id': 'command', 'label': 'Run supplied test', 'action': 'REVIEW', 'method': 'command', 'checkpoint': 'output'},
               {'id': 'inspect', 'label': 'Inspect supplied evidence', 'action': 'REVIEW', 'method': 'bounded_review', 'checkpoint': 'output'}]
    args = {'policy': policy, 'node': 'extra', 'evidence': ['criterion:C1', 'artifact:A'],
            'validity': {'revision': 1, 'contract_sha': 'a' * 64, 'input_sha': 'b' * 64,
                         'policy_sha': content_hash(policy), 'budget_revision': 'grant-1'},
            'configured': True, 'permitted': True, 'remaining_calls': 1, 'key': KEY}
    def suggest(fake, **changes):
        return review_advice.suggest('Check this supplied result.', options, opener=fake, **dict(args, **changes))
    for stage in ('step0', 'review'):
        fake = Fake()
        result = suggest(fake, stage=stage)
        check(stage + '-proposal', result['status'] == 'proposal' and fake.calls == 1 and result['effective_action'] == 'REVIEW'
              and result['proposal']['option']['id'] == 'inspect' and not result['automatic_application'] and not result['dispatch_enabled'])
    for name, change in (('no-permission', {'permitted': False}), ('no-config', {'configured': False}),
                         ('no-budget', {'remaining_calls': 0}), ('unknown', {'unknowns': ['U1']})):
        fake = Fake()
        result = suggest(fake, **change)
        check(name, fake.calls == 0 and result['calls'] == 0 and result['proposal'] is None)
    for name, fake in (('timeout', Fake(error=True)), ('bad-schema', Fake(invalid=True))):
        result = suggest(fake)
        check(name, fake.calls == 1 and result['status'] == 'fallback' and result['effective_action'] == 'REVIEW'
              and KEY not in json.dumps(result))
    options.append({'id': 'skip', 'label': 'Skip', 'action': 'SKIP', 'method': 'command', 'checkpoint': 'output'})
    result = suggest(Fake(), mandatory=True)
    check('mandatory', result['effective_action'] == 'REVIEW' and result['proposal']['option']['action'] == 'REVIEW')
    try:
        suggest(Fake(), validity=dict(args['validity'], policy_sha='c' * 64))
    except LedgerError:
        check('mismatched-policy-refused', True)
    else:
        check('mismatched-policy-refused', False)
    print(json.dumps({'status': 'pass', 'checks': checks, 'count': len(checks), 'provider': 'fake-only',
                      'adapter': str(Path(review_advice.__file__).resolve()),
                      'client': str(Path(decision_client_core.__file__).resolve()),
                      'runtime_wiring': False, 'automatic_application': False}, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
