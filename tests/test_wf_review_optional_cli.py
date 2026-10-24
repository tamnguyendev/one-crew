"""W26 (T29 [E1]-[E3], T16c [E8]): the rule-based optional review is reachable from the public engine CLI (`engine review-optional`).

Same fixture as tests/test_wf_review_dispatch (light policy, sealed optional review `extra`). From the CLI: SKIP under the light policy, with
its HD-05 record (reason, policy depth/revision, scope, validity) and no request; the connected checker is never called on SKIP; a review id
that is a mandatory gate is refused; an unproduced node is refused before any state is touched; the mandatory `verify` still runs its checker.
"""
import contextlib
import io
import json
from unittest.mock import Mock, patch

from onecrew.v2 import engine_cli, plan
from tests import test_wf_engine as fixtures
from tests.test_v2_l1 import plan_json


class ReviewOptionalCliTests(fixtures.EngineFixture):
    def setUp(self):
        with patch.object(fixtures, 'plan_json', side_effect=lambda **kw: plan_json(review_policy={'depth': 'light', 'optional_reviews': ['extra']}, **kw)):
            super().setUp()
        self.revise([fixtures.node('C'), fixtures.node('I', ['C'], integration=True, write=())])

    def call(self, *args, **ports):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = engine_cli.main(['--project', str(self.root), '--state-root', str(self.ledger.state_root), 'engine', *args], **ports)
        return code, json.loads(out.getvalue())

    def test_light_policy_skips_from_the_cli_with_a_record_and_without_a_request_or_checker_call(self):
        code, result = self.call('review-optional', 'P1', 'C', 'extra', checker=lambda ledger, selector: Mock(side_effect=AssertionError('no call')))
        self.assertEqual(code, 2); self.assertIn('produced node', result['error'])                       # nothing produced yet: refused first
        self.step()
        before = len(self.ledger.requests())
        checker = Mock(side_effect=AssertionError('optional reviewer must not run'))
        code, result = self.call('review-optional', 'P1', 'C', 'extra', checker=lambda ledger, selector: checker)
        self.assertEqual(code, 0, result)
        self.assertEqual((result['decision']['action'], result['status'], result['executed']), ('SKIP', 'skipped', False))   # [E1]
        decision = result['decision']
        self.assertIn('light policy', decision['reason'])                                                   # reason
        self.assertEqual((decision['validity']['depth'], decision['validity']['revision']), ('light', 1))    # policy depth + revision
        self.assertTrue(decision['validity']['policy_sha'])
        record = decision['record']
        self.assertEqual((record['scope'], record['validity']['action'], record['subject']), ('extra', 'SKIP', {'component': 'review_policy', 'model': 'rules'}))
        self.assertTrue(record['basis'] and record['authority']['grant_id'].startswith('approved-contract:'))  # HD-05: scope, validity, basis, authority
        rules = [p for k, p in self.events() if k == 'decision.recorded' and p['subject']['component'] == 'review_policy']
        self.assertEqual(rules[-1]['key'], record['key'], 'the record is in the ledger')
        self.assertEqual(checker.call_count, 0)
        self.assertEqual(len(self.ledger.requests()), before)                                               # [E3]
        self.assertFalse(result['changes_node_state'])
        self.assertEqual(self.engine.state(self.ledger, 'P1')['nodes']['C']['state'], 'produced')
        code, result = self.call('review-optional', 'P1', 'C', 'check-C', checker=lambda ledger, selector: checker)
        self.assertEqual(code, 2); self.assertIn('not an optional review', result['error'])                 # [E4]: a mandatory gate is never SKIPped
        code, result = self.call('verify', 'P1', 'C', checker=lambda ledger, selector: self.checker)
        self.assertEqual((code, result['result']), (0, 'pass'))                                             # [E2]: the mandatory gate still runs
        self.assertEqual(plan.show(self.ledger, 'P1')['status'], 'approved')

    def test_disconnected_checker_port_refuses_before_opening_state(self):
        self.step()
        code, result = self.call('review-optional', 'P1', 'C', 'extra', checker=None)
        self.assertEqual(code, 2); self.assertIn('host adapter', result['error'])
