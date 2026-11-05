"""Run with installed wheel Python -I; no checkout/test imports or real service.

python -I -B -X utf8 <copied verify_rda.py>
"""
import io
import json
import os
import subprocess
import tempfile
from pathlib import Path

from onecrew import decision_client_core
from onecrew.ledger import Ledger, LedgerError, content_hash
from onecrew.v2 import plan as plans, review_advice

KEY = 'synthetic-test-credential-only'


class Fake:
    def __init__(self, invalid=False, error=False):
        self.invalid, self.error, self.calls, self.last_body = invalid, error, 0, None

    def open(self, request, timeout):
        self.calls += 1
        self.last_body = json.loads(request.data)
        if self.error:
            raise TimeoutError(KEY)
        data = {'model': 'jev-wheel-fixture', 'answers': {'workflow': {'type': 'choice', 'choice': 'option1',
                'confidence': .9, 'probabilities': {'option0': .05, 'option1': .9, 'abstain': .05}}}}
        return io.BytesIO(json.dumps({} if self.invalid else data).encode())

def lifecycle(check):
    """RD-A2: the shipped modules put advice on an approved root: one charged call, then the stored record, no grant -> no call."""
    from onecrew import budget_core
    milestone = {'id': 'M1', 'title': 'Milestone M1', 'verifier': {'type': 'command', 'config': {'argv': ['python', '-c', 'print(1)']}}, 'covers': ['O1']}
    def contract(grant):
        return {'schema_version': 2, 'title': 'Sample', 'size': 'S',
                'understanding': {'restated_goal': 'Do the sample and prove it.', 'target': {'repo': '.', 'ref': 'HEAD', 'paths': ['a.txt']},
                                  'assumptions': [], 'confidence': 'high', 'unknowns': []},
                'preconditions': [{'id': 'P1', 'check': 'path_exists', 'args': {'path': 'a.txt'}, 'why': 'the file is there'}],
                'output': ['The sample exists'], 'scope': {'owned': ['a.txt']}, 'non_goals': ['Nothing else'],
                'items': [{'id': 'I1', 'title': 'Do it', 'tier': 'must', 'milestone': 'M1'}, {'id': 'S1', 'title': 'Nice', 'tier': 'should'},
                          {'id': 'W1', 'title': 'Never', 'tier': 'wont'}],
                'milestones': [milestone], 'budget': {'max_calls': 10, 'time': 30}, 'attention': {'questions': 1}, 'profile_version': None,
                'review_policy': {'depth': 'standard', 'optional_reviews': ['extra']}, 'authority': grant}
    with tempfile.TemporaryDirectory() as folder:
        project = Path(folder) / 'project'; project.mkdir()
        def git(*args):
            subprocess.run(['git', '-C', str(project), *args], check=True, capture_output=True)
        git('init', '-q'); git('config', 'user.name', 'T'); git('config', 'user.email', 't@localhost')
        (project / 'a.txt').write_text('one\n'); git('add', '.'); git('commit', '-q', '-m', 'base')
        ledger = Ledger(project, Path(folder) / 'state')
        os.environ.pop('CLAUDE_CODE_CHILD_SESSION', None); os.environ.pop('CLAUDECODE', None)
        os.environ.pop('ONECREW_ACTOR', None)
        plans.propose(ledger, 'P1', contract({'edit': True, 'commands': True, 'granted_actions': ['review_advice:suggest']}), 'codex', workflow=True)
        plans.approve(ledger, 'P1', 'owner', 'wheel check approval')
        plans.propose(ledger, 'P2', contract({'edit': True, 'commands': True}), 'codex', workflow=True)
        plans.approve(ledger, 'P2', 'owner', 'wheel check approval')
        os.environ['ONECREW_ACTOR'] = 'codex'
        def used(name):
            with ledger.transaction() as conn:
                return budget_core.group(conn, plans.anchor_events(ledger, conn, name)['task_id'])['used_calls']
        def ask(name, fake, **changes):
            args = dict(stage='review', node='C', review_id='extra', brief='Pick the check.', facts={'artifact': 'x'}, key=KEY, opener=fake)
            return review_advice.advise(ledger, name, **dict(args, **changes))
        fake = Fake()
        first = ask('P1', fake)
        check('lifecycle-one-charged-call', first['status'] == 'proposal' and fake.calls == 1 and used('P1') == 1 and first['charged_calls'] == 1
              and first['effective_action'] == 'REVIEW' and not first['grants_authority'] and first['receipt'])
        again = ask('P1', fake)
        check('lifecycle-same-input-no-call', again['cache'] == 'hit' and fake.calls == 1 and used('P1') == 1 and again['receipt'] == first['receipt'])
        check('lifecycle-skip-never-offered', 'SKIP' not in json.dumps(fake.last_body) and any(w['id'] == 'skip' for w in first['withheld']))
        changed = ask('P1', fake, facts={'artifact': 'y'})
        stale = [r for r in review_advice.show(ledger, 'P1')['records'] if not r['current']]
        check('lifecycle-changed-input-new-record-old-stale', changed['cache'] == 'miss' and fake.calls == 2 and len(stale) == 1)
        broken = Fake(error=True)
        failed = ask('P1', broken, facts={'artifact': 'z'})
        repeat = ask('P1', broken, facts={'artifact': 'z'})
        check('lifecycle-error-fallback-no-retry', failed['status'] == 'fallback' and repeat['cache'] == 'hit' and broken.calls == 1
              and KEY not in json.dumps([failed, repeat]))
        denied = Fake()
        none = ask('P2', denied)
        check('lifecycle-no-grant-no-call', none['status'] == 'skipped' and none['reason'] == 'not_permitted' and denied.calls == 0 and used('P2') == 0)
        mine = review_advice.advise_optional(ledger, 'NOPE', 'C', 'extra', facts={}, key=KEY, opener=denied)
        check('lifecycle-operational-error-not-raised', mine['status'] == 'fallback' and denied.calls == 0)


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
    lifecycle(check)
    print(json.dumps({'status': 'pass', 'checks': checks, 'count': len(checks), 'provider': 'fake-only',
                      'adapter': str(Path(review_advice.__file__).resolve()),
                      'client': str(Path(decision_client_core.__file__).resolve()),
                      'runtime_wiring': 'advice lifecycle on an approved root only; no dispatcher/step0 caller', 'automatic_application': False}, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
