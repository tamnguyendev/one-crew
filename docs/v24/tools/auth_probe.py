"""wheel_auth_probe.py <work dir> - the hotfix auth cases against the INSTALLED onecrew of the interpreter running this (a venv with the wheel;
run with -I from a folder outside any checkout). Self-contained: no test fixtures of the checkout (the wheel does not ship onecrew.cli, which
tests/test_v2_l1 imports). Real: contracts.validate, plans.propose/approve, advisor.advise, verdict.run -> reviewer.run -> reviewer.call ->
providers.run_process (a real child process), the ledger and the snapshot store. Fault injection: the Claude CLI is a Python double found
through reviewer.cli_argv; it records WHETHER ANTHROPIC_API_KEY was in its environment and whether it equalled the fixture value, never the
value. Writes <work>/wheel-auth-probe.json; prints RESULT pass|fail n/5. Expected: dev10 fails (no `auth`), dev11 passes. No real CLI, no key."""
import json
import os
import subprocess
import sys
import traceback
from pathlib import Path
from unittest.mock import patch

from onecrew.ledger import Ledger, LedgerError
from onecrew.snapshots import Snapshots
from onecrew.v2 import contract as contracts, plan as plans, plan_cli, verdict
from onecrew.v2.verifiers import advisor, command, reviewer

KEY = 'sk-ant-fixture-7c1d9e4b2a-not-a-real-key'
WRONG = 'sk-ant-fixture-wrong'
WORK = Path(sys.argv[1]).resolve()
FAKE = '''import json, os, sys
from pathlib import Path
here = Path(__file__).parent
prompt = sys.stdin.read()
(here / 'prompt.txt').write_text(prompt, encoding='utf-8')
calls = here / 'calls.txt'
calls.write_text(str(int(calls.read_text()) + 1 if calls.exists() else 1))
key = os.environ.get('ANTHROPIC_API_KEY')
expected = (here / 'expected-key.txt').read_text()
(here / 'seen.json').write_text(json.dumps({'has_key': key is not None, 'key_is_fixture': key == expected, 'argv': sys.argv[1:]}))
if key == %r:
    print(json.dumps({"type": "result", "is_error": True, "result": "API Error: 401 authentication_error: invalid x-api-key"})); sys.exit(1)
print(json.dumps({"type": "result", "is_error": False, "result": (here / 'answer.txt').read_text(encoding='utf-8'),
                  "usage": {"input_tokens": 10, "output_tokens": 5}, "total_cost_usd": 0, "num_turns": 1}))
''' % WRONG
CRITERIA = [{'id': 'R1', 'question': 'Does the diff of a.txt add the line "two"?'}]
ORIGIN = {'by': 'owner', 'at': '2026-10-19', 'quote': 'Add the sample file and prove it works.'}
DECISION = {'id': 'D1', 'choice': 'Plain text file', 'alternative': 'JSON file', 'cost': 'None'}


def plan_json(milestones, advice=False, **extra):
    """The smallest contract that passes step 0; with advice=True also the origin, decisions and item sources the advisor asks about."""
    value = {'schema_version': 2, 'title': 'Sample', 'size': 'S',
             'understanding': {'restated_goal': 'Do the sample and prove it.', 'target': {'repo': '.', 'ref': 'HEAD', 'paths': ['a.txt']},
                               'assumptions': [], 'confidence': 'high', 'unknowns': []},
             'preconditions': [{'id': 'P1', 'check': 'path_exists', 'args': {'path': 'a.txt'}, 'why': 'the file to work on is there'}],
             'output': ['The sample exists'], 'scope': {'owned': ['a.txt']}, 'non_goals': ['Nothing else'],
             'items': [{'id': 'I1', 'title': 'Do it', 'tier': 'must', 'milestone': 'M1'},
                       {'id': 'S1', 'title': 'Nice to have', 'tier': 'should'}, {'id': 'W1', 'title': 'Never', 'tier': 'wont'}],
             'milestones': milestones, 'budget': {'max_calls': 100, 'time': 120}, 'attention': {'questions': 1}, 'profile_version': None}
    if advice:
        value.update(origin=dict(ORIGIN), decisions=[DECISION])
        value['items'] = [dict(i, source='origin') for i in value['items']]
    return dict(value, **extra)


def reviewer_milestone(**config):
    return {'id': 'M1', 'title': 'Review', 'covers': ['O1'], 'verifier': {'type': 'reviewer', 'config': dict(
        {'provider': 'claude', 'model': 'claude-haiku-5-5', 'criteria': CRITERIA, 'max_minutes': 5}, **config)}}


ANSWER = json.dumps({'criteria': [{'id': 'R1', 'verdict': 'pass', 'evidence': [{'file': 'a.txt', 'line': 2, 'note': 'seen'}]}], 'outside_criteria': []})
ADVICE = json.dumps({'answers': [{'id': f'Q{n}', 'verdict': 'ok', 'note': 'fine'} for n in (1, 2, 3)]})


class Case:
    def __init__(self, name):
        self.dir = WORK / name; self.dir.mkdir(parents=True)
        self.fake = self.dir / 'fake'; self.fake.mkdir()
        (self.fake / 'claude.py').write_text(FAKE, encoding='utf-8')
        (self.fake / 'expected-key.txt').write_text(KEY)
        self.root = self.dir / 'project'; self.root.mkdir()
        for args in (('init', '-q'), ('config', 'user.name', 'T'), ('config', 'user.email', 't@localhost')):
            subprocess.run(['git', '-C', str(self.root), *args], check=True, capture_output=True)
        (self.root / 'a.txt').write_text('one\n')
        subprocess.run(['git', '-C', str(self.root), 'add', '.'], check=True, capture_output=True)
        subprocess.run(['git', '-C', str(self.root), 'commit', '-q', '-m', 'base'], check=True, capture_output=True)
        self.ledger = Ledger(self.root, self.dir / 'state')

    def calls(self):
        p = self.fake / 'calls.txt'; return int(p.read_text()) if p.exists() else 0

    def seen(self):
        p = self.fake / 'seen.json'; return json.loads(p.read_text()) if p.exists() else None

    def review(self, **config):
        (self.fake / 'answer.txt').write_text(ANSWER, encoding='utf-8')
        plans.propose(self.ledger, 'P1', plan_json([reviewer_milestone(**config)]), 'codex')
        plans.approve(self.ledger, 'P1', 'owner', 'said yes in chat')
        (self.root / 'a.txt').write_text('one\ntwo\n')
        verdict.run(self.ledger, 'P1', 'M1', self.root)
        with self.ledger.transaction() as conn: task = plans.derive(self.ledger, conn, 'P1')['task_id']
        recorded = [e['payload'] for e in self.ledger.events(task) if e['kind'] == 'verdict.recorded'][-1]
        return recorded, json.loads(Snapshots(self.ledger.state_root).read_blob(recorded['receipt']))

    def state_bytes(self):
        return b''.join(p.read_bytes() for p in sorted((self.dir / 'state').rglob('*')) if p.is_file())


def check(name, fn):
    try:
        facts = fn(); facts['ok'] = all(v for k, v in facts.items() if k.startswith('ok_'))
    except BaseException as error:          # SystemExit too: argparse of an old wheel refuses --auth
        facts = {'ok': False, 'error': f'{type(error).__name__}: {str(error)[:300]}', 'trace': traceback.format_exc()[-600:]}
    out[name] = facts
    print(name, 'pass' if facts['ok'] else 'FAIL', facts.get('error', ''))


def c1_default_subscription():
    c = Case('c1'); os.environ['ANTHROPIC_API_KEY'] = KEY
    recorded, receipt = c.review()
    return {'calls': c.calls(), 'seen': c.seen(), 'result': recorded['result'], 'auth': receipt.get('auth'),
            'ok_one_call': c.calls() == 1, 'ok_no_key': c.seen() and not c.seen()['has_key'], 'ok_pass': recorded['result'] == 'pass', 'ok_auth': receipt.get('auth') == 'subscription'}


def c2_api_key_to_provider_only():
    c = Case('c2'); os.environ['ANTHROPIC_API_KEY'] = KEY
    recorded, receipt = c.review(auth='api')
    seen = c.seen()
    return {'calls': c.calls(), 'seen': seen, 'result': recorded['result'], 'auth': receipt.get('auth'),
            'ok_key_seen': bool(seen and seen['key_is_fixture']), 'ok_not_in_argv': KEY not in ' '.join(seen['argv']) if seen else False,
            'ok_pass': recorded['result'] == 'pass', 'ok_auth': receipt.get('auth') == 'api',
            'ok_verifier_env_clean': 'ANTHROPIC_API_KEY' not in command.verifier_env(c.root),
            'ok_state_clean': KEY.encode() not in c.state_bytes(), 'ok_prompt_clean': KEY not in (c.fake / 'prompt.txt').read_text(encoding='utf-8')}


def c3_api_missing_key():
    c = Case('c3'); os.environ.pop('ANTHROPIC_API_KEY', None)
    recorded, receipt = c.review(auth='api')
    return {'calls': c.calls(), 'result': recorded['result'], 'provider_error': receipt.get('provider_error'), 'error': (receipt.get('error') or '')[:160],
            'ok_no_process': c.calls() == 0, 'ok_inconclusive': recorded['result'] == 'inconclusive',
            'ok_typed': receipt.get('provider_error') == 'credential_missing', 'ok_names_var': 'ANTHROPIC_API_KEY' in (receipt.get('error') or '')}


def c4_api_wrong_key_no_fallback():
    c = Case('c4'); os.environ['ANTHROPIC_API_KEY'] = WRONG
    recorded, receipt = c.review(auth='api')
    return {'calls': c.calls(), 'result': recorded['result'], 'error': (receipt.get('error') or '')[:160],
            'ok_one_call': c.calls() == 1, 'ok_inconclusive': recorded['result'] == 'inconclusive',
            'ok_cli_error': 'authentication_error' in (receipt.get('error') or ''), 'ok_state_clean': WRONG.encode() not in c.state_bytes()}


def c5_advisor_cli_and_codex():
    c = Case('c5'); os.environ['ANTHROPIC_API_KEY'] = KEY
    (c.fake / 'answer.txt').write_text(ADVICE, encoding='utf-8')
    advisor.init_rules(c.ledger)
    plans.propose(c.ledger, 'P1', plan_json(advice=True, milestones=[{'id': 'M1', 'title': 'Milestone M1', 'covers': ['O1'], 'verifier': {'type': 'command', 'config': {'argv': [sys.executable, '-c', 'print("ok")']}}}]), 'claude-fable-5-1')
    code = plan_cli.main(['--project', str(c.root), '--state-root', str(c.ledger.state_root), 'plan', 'advise', 'P1', '--auth', 'api'])
    with c.ledger.transaction() as conn: event = plans.derive(c.ledger, conn, 'P1')['advice'].get(1)
    try:
        advisor.advise(c.ledger, 'P1', 'gpt-5.1', 'codex', auth='api'); refused = False
    except LedgerError as error:
        refused = 'auth' in str(error)
    seen = c.seen()
    return {'cli_exit': code, 'seen': seen, 'auth': event and event.get('auth'), 'usable': event and event.get('usable'), 'calls': c.calls(),
            'ok_key_seen': bool(seen and seen['key_is_fixture']), 'ok_usable': bool(event and event.get('usable')), 'ok_auth': bool(event and event.get('auth') == 'api'),
            'ok_codex_refused': refused is True, 'ok_one_call': c.calls() == 1, 'ok_state_clean': KEY.encode() not in c.state_bytes()}


WORK.mkdir(parents=True, exist_ok=True)
out = {'onecrew': __import__('onecrew').__file__, 'cases': {}}
for k in list(os.environ):
    if k.upper().startswith(('ANTHROPIC_', 'CLAUDE_CODE_', 'CLAUDECODE', 'ONECREW_')): os.environ.pop(k)
out = out['cases']
with patch.object(reviewer, 'cli_argv', lambda env: [sys.executable, str(Path(os.environ['_FAKE']))]) if False else patch.object(reviewer, 'cli_argv', lambda env: [sys.executable, str(WORK / '_current' / 'claude.py')]):
    for fn in (c1_default_subscription, c2_api_key_to_provider_only, c3_api_missing_key, c4_api_wrong_key_no_fallback, c5_advisor_cli_and_codex):
        name = fn.__name__
        cur = WORK / '_current'
        if cur.exists():
            for p in cur.iterdir(): p.unlink()
        else: cur.mkdir()
        original_case_init = Case.__init__
        def init_with_link(self, n, _orig=original_case_init):
            _orig(self, n)
            # the double is read from WORK/_current: copy this case's double there (per-case answer/expected-key written later into self.fake are
            # read by the double from ITS OWN folder, so point self.fake at _current)
            for p in self.fake.iterdir(): (cur / p.name).write_bytes(p.read_bytes())
            self.fake = cur
        Case.__init__ = init_with_link
        check(name, fn)
        Case.__init__ = original_case_init
passed = sum(1 for v in out.values() if v['ok'])
result = {'onecrew': __import__('onecrew').__file__, 'version': __import__('importlib.metadata').metadata.version('onecrew'), 'cases': out,
          'result': 'pass' if passed == len(out) else 'fail', 'passed': f'{passed}/{len(out)}'}
(WORK / 'wheel-auth-probe.json').write_text(json.dumps(result, indent=1, ensure_ascii=False), encoding='utf-8')
print('RESULT', result['result'], result['passed'], result['version'], result['onecrew'])
sys.exit(0 if result['result'] == 'pass' else 1)
