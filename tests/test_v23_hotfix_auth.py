"""2.3 hotfix (02/11/2026): the Claude CLI advisor and reviewer with an EXPLICITLY chosen credential — subscription (the login the CLI holds,
as ever) or api (ANTHROPIC_API_KEY of the OneCrew process, given to the provider process alone).

Issue: `onecrew/v2/verifiers/command.py` verifier_env drops every ANTHROPIC_* variable (right: the project's checks must not see a key), and
advisor.advise (advisor.py:159) and reviewer.run (reviewer.py:294) start the Claude CLI with that same environment, so a key the owner set
for the call never reached it; the CLI then used its subscription login or failed. Nothing let the owner choose.

Expected: `auth` is chosen per call ({"auth": "api"} on the contract advisor / reviewer config, `plan advise --auth api`); default subscription,
unchanged. In api mode the provider process, and only it, gets ANTHROPIC_API_KEY; the project's command checks and the evidence-bound verifier
environment never do. A missing key is a typed, inconclusive result with the reason and NO process started; a rejected key is the CLI's error,
inconclusive, one call, no retry with the subscription (and never the other way round). The key value appears nowhere: not in events,
receipts, blobs, the prompt, argv. codex/kiro: api is not offered (unchanged providers).

Fault injection: the Claude CLI is a Python double (records WHETHER the key was in its environment and whether it equalled the fixture key,
never the value) found through reviewer.cli_argv, as test_v2_reviewer does. Real: contract validation, plan.propose/approve, advisor.advise,
verdict.run -> reviewer.run -> reviewer.call -> providers.run_process (a real child process), the ledger and the snapshot store.
"""
import json
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

from onecrew.ledger import LedgerError
from onecrew.snapshots import Snapshots
from onecrew.v2 import contract as contracts, plan as plans, plan_cli, verdict
from onecrew.v2.verifiers import advisor, command, reviewer
from test_v2_advisor import AUTHOR, DECISION, answers, sourced
from test_v2_l1 import Fixture, plan_json
from test_v2_reviewer import CRITERIA, answer, row

KEY = 'sk-ant-fixture-7c1d9e4b2a-not-a-real-key'           # never a real credential; the double compares, never prints it
WRONG = 'sk-ant-fixture-wrong'
FAKE = '''import json, os, sys
from pathlib import Path
here = Path(__file__).parent
prompt = sys.stdin.read()
(here / 'prompt.txt').write_text(prompt, encoding='utf-8')
calls = here / 'calls.txt'
calls.write_text(str(int(calls.read_text()) + 1 if calls.exists() else 1))
key = os.environ.get('ANTHROPIC_API_KEY')
expected = (here / 'expected-key.txt').read_text() if (here / 'expected-key.txt').exists() else None
seen = {'has_key': key is not None, 'key_is_fixture': key == expected, 'argv': sys.argv[1:],
        'other_anthropic': sorted(k for k in os.environ if k.upper().startswith('ANTHROPIC_') and k != 'ANTHROPIC_API_KEY')}
(here / 'seen.json').write_text(json.dumps(seen))
if key == 'WRONG':
    print(json.dumps({"type": "result", "is_error": True, "result": "API Error: 401 {\\"type\\":\\"authentication_error\\",\\"message\\":\\"invalid x-api-key\\"}"}))
    sys.exit(1)
print(json.dumps({"type": "result", "is_error": False, "result": (here / 'answer.txt').read_text(encoding='utf-8'),
                  "usage": {"input_tokens": 10, "output_tokens": 5}, "total_cost_usd": 0, "num_turns": 1}))
'''.replace("'WRONG'", repr(WRONG))


def reviewer_milestone(**config):
    return {'id': 'M1', 'title': 'Review', 'covers': ['O1'], 'verifier': {'type': 'reviewer', 'config': dict(
        {'provider': 'claude', 'model': 'claude-haiku-5-5', 'criteria': CRITERIA, 'max_minutes': 5}, **config)}}


class AuthFixture(Fixture):
    def setUp(self):
        super().setUp()
        self.fake = Path(self.temp.name) / 'fake'; self.fake.mkdir()
        (self.fake / 'claude.py').write_text(FAKE, encoding='utf-8')
        (self.fake / 'expected-key.txt').write_text(KEY)
        patcher = patch.object(reviewer, 'cli_argv', lambda env: [sys.executable, str(self.fake / 'claude.py')])
        patcher.start(); self.addCleanup(patcher.stop)
        # the OneCrew process environment of the owner's terminal: no key unless a test sets one
        clean = {k: v for k, v in os.environ.items() if not k.upper().startswith(('ANTHROPIC_', 'CLAUDE_CODE_'))}
        self.enterContext(patch.dict(os.environ, clean, clear=True))

    def with_key(self, value=KEY):
        os.environ['ANTHROPIC_API_KEY'] = value

    def calls(self):
        path = self.fake / 'calls.txt'
        return int(path.read_text()) if path.exists() else 0

    def seen(self):
        path = self.fake / 'seen.json'
        return json.loads(path.read_text()) if path.exists() else None

    def reply(self, text):
        (self.fake / 'answer.txt').write_text(text, encoding='utf-8')

    # ---- reviewer through verdict.run ----
    def review(self, **config):
        plans.propose(self.ledger, 'P1', plan_json(milestones=[reviewer_milestone(**config)]), 'codex')
        plans.approve(self.ledger, 'P1', 'owner', 'said yes in chat')
        (self.root / 'a.txt').write_text('one\ntwo\n')
        self.reply(answer(row('R1'), row('R2')))
        return verdict.run(self.ledger, 'P1', 'M1', self.root)

    def last_receipt(self):
        recorded = [p for k, p in self.events() if k == 'verdict.recorded'][-1]
        return recorded, json.loads(Snapshots(self.ledger.state_root).read_blob(recorded['receipt']))

    # ---- advisor through advisor.advise ----
    def propose_for_advice(self, **extra):
        advisor.init_rules(self.ledger)
        plans.propose(self.ledger, 'P1', sourced(plan_json(), decisions=[DECISION], **extra), AUTHOR)
        self.reply(answers())

    def advice(self):
        with self.ledger.transaction() as conn:
            return plans.derive(self.ledger, conn, 'P1')['advice'].get(1)

    def state_bytes(self):
        """Every byte the ledger and the snapshot store hold (the key must appear in none of them)."""
        out = b''
        for path in sorted(Path(self.ledger.state_root).rglob('*')):
            if path.is_file(): out += path.read_bytes()
        return out


class ReviewerAuthTests(AuthFixture):
    def test_control_default_is_the_subscription_and_the_cli_never_sees_a_key_of_the_terminal(self):
        self.with_key()
        self.review()
        self.assertEqual(self.calls(), 1)
        self.assertFalse(self.seen()['has_key'], 'subscription mode must not hand the terminal key to the CLI')
        self.assertEqual(self.seen()['other_anthropic'], [])
        recorded, receipt = self.last_receipt()
        self.assertEqual(recorded['result'], 'pass')
        self.assertEqual(receipt.get('auth'), 'subscription')

    def test_api_mode_gives_the_key_to_the_provider_process_only(self):
        self.with_key()
        self.review(auth='api')
        self.assertEqual(self.calls(), 1)
        self.assertTrue(self.seen()['key_is_fixture'], 'api mode: the CLI must see the key of the OneCrew process')
        self.assertNotIn(KEY, ' '.join(self.seen()['argv']), 'the key never travels on the command line')
        recorded, receipt = self.last_receipt()
        self.assertEqual(recorded['result'], 'pass')
        self.assertEqual(receipt['auth'], 'api')
        # the project's checks and the evidence-bound verifier environment never see it
        self.assertNotIn('ANTHROPIC_API_KEY', command.verifier_env(self.root))
        self.assertNotIn(KEY.encode(), self.state_bytes(), 'the key value is in the ledger or a blob')
        self.assertNotIn(KEY, (self.fake / 'prompt.txt').read_text(encoding='utf-8'))

    def test_api_mode_without_a_key_starts_no_process_and_is_inconclusive_with_the_reason(self):
        self.review(auth='api')
        self.assertEqual(self.calls(), 0, 'nothing may run without the credential the owner chose')
        recorded, receipt = self.last_receipt()
        self.assertEqual(recorded['result'], 'inconclusive')
        self.assertIn('ANTHROPIC_API_KEY', receipt['error'])
        self.assertEqual(receipt['provider_error'], 'credential_missing')
        self.assertEqual(receipt['auth'], 'api')

    def test_api_mode_with_a_rejected_key_is_inconclusive_after_one_call_and_never_retries_with_the_subscription(self):
        self.with_key(WRONG)
        self.review(auth='api')
        self.assertEqual(self.calls(), 1, 'one call: no fallback to the subscription login')
        recorded, receipt = self.last_receipt()
        self.assertEqual(recorded['result'], 'inconclusive')
        self.assertIn('authentication_error', receipt['error'])
        self.assertNotEqual(receipt['provider_error'], 'quota_exhausted')
        self.assertNotIn(WRONG.encode(), self.state_bytes())

    def test_subscription_mode_never_falls_back_to_a_paid_api_call(self):
        """The subscription CLI fails (an error envelope): one call, inconclusive, no second call with the key the terminal holds."""
        self.with_key()
        (self.fake / 'expected-key.txt').unlink()
        self.with_key(WRONG)                     # the double answers with an error when it sees this key; in subscription mode it must not see it
        self.review()
        self.assertEqual(self.calls(), 1)
        self.assertFalse(self.seen()['has_key'])
        self.assertEqual(self.last_receipt()[0]['result'], 'pass')      # the subscription path answered as before: no key reached it

    def test_api_is_offered_for_claude_only_and_the_field_is_checked_at_propose(self):
        with self.assertRaises(LedgerError) as caught:
            contracts.validate(plan_json(milestones=[reviewer_milestone(provider='codex', model='gpt-5.1', auth='api')]))
        self.assertIn('auth', str(caught.exception))
        with self.assertRaises(LedgerError):
            contracts.validate(plan_json(milestones=[reviewer_milestone(auth='token')]))
        kept = contracts.validate(plan_json(milestones=[reviewer_milestone(auth='api')]))['milestones'][0]['verifier']['config']
        self.assertEqual(kept['auth'], 'api')
        plain = contracts.validate(plan_json(milestones=[reviewer_milestone()]))['milestones'][0]['verifier']['config']
        self.assertNotIn('auth', plain, 'a contract without the field is kept as it was (its sha does not move)')


class AdvisorAuthTests(AuthFixture):
    def test_control_default_subscription_and_no_key_reaches_the_cli(self):
        self.with_key()
        self.propose_for_advice()
        advisor.advise(self.ledger, 'P1')
        self.assertEqual(self.calls(), 1)
        self.assertFalse(self.seen()['has_key'])
        event = self.advice()
        self.assertTrue(event['usable'])
        self.assertEqual(event.get('auth'), 'subscription')

    def test_api_mode_from_the_command_line_and_from_the_contract(self):
        self.with_key()
        self.propose_for_advice()
        advisor.advise(self.ledger, 'P1', auth='api')
        self.assertTrue(self.seen()['key_is_fixture'])
        event = self.advice()
        self.assertTrue(event['usable'])
        self.assertEqual(event['auth'], 'api')
        receipt = json.loads(Snapshots(self.ledger.state_root).read_blob(event['receipt']))
        self.assertEqual(receipt['auth'], 'api')
        self.assertNotIn(KEY.encode(), self.state_bytes())
        # pinned in the contract: advise without arguments uses it
        (self.fake / 'seen.json').unlink()
        plans.propose(self.ledger, 'P2', sourced(plan_json(), decisions=[DECISION], advisor={'provider': 'claude', 'model': 'claude-opus-5-5', 'auth': 'api'}), AUTHOR)
        advisor.advise(self.ledger, 'P2')
        self.assertTrue(self.seen()['key_is_fixture'])
        with self.ledger.transaction() as conn:
            self.assertEqual(plans.derive(self.ledger, conn, 'P2')['advice'][1]['auth'], 'api')

    def test_api_mode_without_a_key_is_typed_inconclusive_and_starts_nothing(self):
        self.propose_for_advice()
        advisor.advise(self.ledger, 'P1', auth='api')
        self.assertEqual(self.calls(), 0)
        event = self.advice()
        self.assertFalse(event['usable'])
        self.assertEqual(event['provider_error'], 'credential_missing')
        self.assertTrue(any('ANTHROPIC_API_KEY' in p for p in event['problems']), event['problems'])

    def test_a_rejected_key_is_the_providers_error_once_no_other_login_is_tried(self):
        self.with_key(WRONG)
        self.propose_for_advice()
        advisor.advise(self.ledger, 'P1', auth='api')
        self.assertEqual(self.calls(), 1)
        event = self.advice()
        self.assertFalse(event['usable'])
        self.assertEqual(event['provider_error'], 'provider_unavailable')
        self.assertTrue(any('authentication_error' in p for p in event['problems']), event['problems'])

    def test_the_command_line_takes_auth_and_refuses_other_values(self):
        self.with_key()
        self.propose_for_advice()
        plan_cli.main(['--project', str(self.root), '--state-root', str(self.ledger.state_root), 'plan', 'advise', 'P1', '--auth', 'api'])
        self.assertTrue(self.seen()['key_is_fixture'])
        with self.assertRaises(SystemExit):
            plan_cli.main(['--project', str(self.root), '--state-root', str(self.ledger.state_root), 'plan', 'advise', 'P1', '--auth', 'token'])

    def test_codex_advisor_does_not_take_api(self):
        self.propose_for_advice()
        with self.assertRaises(LedgerError) as caught:
            advisor.advise(self.ledger, 'P1', 'gpt-5.1', 'codex', auth='api')
        self.assertIn('auth', str(caught.exception))
        self.assertEqual(self.calls(), 0)


if __name__ == '__main__':
    unittest.main()
