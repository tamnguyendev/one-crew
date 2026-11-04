"""2.4 integration of the 2.3 hotfix auth (api credential for the Claude CLI advisor/reviewer): the key must appear NOWHERE in the evidence,
also when the PROVIDER reflects it back (an error envelope or stderr that quotes the x-api-key, a non-JSON stdout that holds it). Before this
fix reviewer.call recorded the CLI's error text and raw stdout as they came, so a reflected key went into the receipt, the raw blob and the
plan.advised problems. Expected: the key value is withheld from error, raw stdout/stderr and every recorded byte; the result stays
inconclusive with its reason; the support bundle's line redaction withholds key shapes and key assignments too.

Fault injection: a Python double of the Claude CLI (found through reviewer.cli_argv) that echoes the key it was given. Real: verdict.run ->
reviewer.run -> reviewer.call -> providers.run_process, advisor.advise, the ledger and the snapshot store, diagnostics.redact_line.
"""
import json
import unittest
from pathlib import Path

from onecrew.snapshots import Snapshots
from onecrew.v2 import diagnostics, plan as plans
from onecrew.v2.verifiers import advisor
from test_v23_hotfix_auth import AuthFixture, KEY

ECHO = '''import json, os, sys
from pathlib import Path
here = Path(__file__).parent
prompt = sys.stdin.read()
calls = here / 'calls.txt'
calls.write_text(str(int(calls.read_text()) + 1 if calls.exists() else 1))
key = os.environ.get('ANTHROPIC_API_KEY') or ''
mode = (here / 'mode.txt').read_text() if (here / 'mode.txt').exists() else 'error'
sys.stderr.write('x-api-key was ' + key + '\\n')
if mode == 'nonjson':
    print('boom: rejected key ' + key); sys.exit(1)
print(json.dumps({"type": "result", "is_error": True, "result": "API Error: 401 authentication_error: invalid x-api-key " + key})); sys.exit(1)
'''
WITHHELD = '[withheld]'


class ReflectedKeyNeverRecorded(AuthFixture):
    def setUp(self):
        super().setUp()
        (self.fake / 'claude.py').write_text(ECHO, encoding='utf-8')

    def mode(self, name):
        (self.fake / 'mode.txt').write_text(name)

    def test_reviewer_error_envelope_quoting_the_key_is_withheld_from_receipt_raw_and_ledger(self):
        self.with_key()
        self.review(auth='api')
        self.assertEqual(self.calls(), 1)
        recorded, receipt = self.last_receipt()
        self.assertEqual(recorded['result'], 'inconclusive')
        self.assertNotIn(KEY, receipt['error'])
        self.assertIn(WITHHELD, receipt['error'])
        self.assertIn('authentication_error', receipt['error'])          # the reason is kept, only the secret is withheld
        raw = Snapshots(self.ledger.state_root).read_blob(receipt['raw'])
        self.assertNotIn(KEY.encode(), raw)
        self.assertNotIn(KEY.encode(), self.state_bytes(), 'the reflected key is in the ledger or a blob')

    def test_reviewer_non_json_output_holding_the_key_is_withheld(self):
        self.with_key(); self.mode('nonjson')
        self.review(auth='api')
        recorded, receipt = self.last_receipt()
        self.assertEqual(recorded['result'], 'inconclusive')
        self.assertIn('not JSON', receipt['error'])
        self.assertNotIn(KEY, receipt['error'])
        self.assertNotIn(KEY.encode(), self.state_bytes())

    def test_advisor_problems_and_raw_never_hold_the_reflected_key(self):
        self.with_key()
        self.propose_for_advice()
        advisor.advise(self.ledger, 'P1', auth='api')
        event = self.advice()
        self.assertFalse(event['usable'])
        self.assertEqual(event['provider_error'], 'provider_unavailable')
        self.assertTrue(all(KEY not in p for p in event['problems']), event['problems'])
        receipt = json.loads(Snapshots(self.ledger.state_root).read_blob(event['receipt']))
        self.assertNotIn(KEY, receipt['error'])
        self.assertNotIn(KEY.encode(), self.state_bytes())

    def test_subscription_mode_records_the_cli_text_unchanged_when_no_key_was_given(self):
        """Control: without a key nothing is withheld (the double echoes an empty key); the error text is the CLI's."""
        self.review()
        recorded, receipt = self.last_receipt()
        self.assertEqual(recorded['result'], 'inconclusive')
        self.assertIn('authentication_error', receipt['error'])
        self.assertNotIn(WITHHELD, receipt['error'])

    def test_bundle_line_redaction_withholds_key_shapes_and_assignments(self):
        """2.4-S1 support bundle: a line that quotes an Anthropic key or assigns ANTHROPIC_API_KEY is redacted, the rest of the line kept."""
        for line in (f'API Error: invalid x-api-key {KEY}', f'ANTHROPIC_API_KEY={KEY}', f'env: ANTHROPIC_API_KEY: {KEY} (set)'):
            out, withheld = diagnostics.redact_line(line)
            self.assertNotIn(KEY, out, line)
            self.assertIn(WITHHELD, out, line)


if __name__ == '__main__':
    unittest.main()
