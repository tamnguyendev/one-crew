"""T09a (W27a) — a typed advisor/provider error becomes an inconclusive verdict with a reason, NOT advice_missing that blocks approval
(R00 slice; T09b/T09c local-fallback/cache/init are RD, out of scope). The three error kinds are injected through the advisor's one call
seam. On the pre-fix code approve was refused with advice_missing (step0.py:265-270) -> these tests are red there, green after the fix.

Reuses the advisor fixture (AdvisorFixture) from the existing advisor suite; run with tests/ on the path (the suite's own convention).
"""
import json
import unittest
from unittest.mock import patch

from onecrew.ledger import LedgerError
from onecrew.v2 import plan as plans, step0
from onecrew.v2.verifiers import advisor

from test_v2_advisor import AdvisorFixture, DECISION, AUTHOR, sourced
from test_v2_l1 import plan_json


PINNED = 'claude-opus-5-5'


class AdvisorProviderErrorTests(AdvisorFixture):
    """Each case: the advisor call fails in a typed way; advise records plan.advised; the owner then approves without a second round."""

    def _call_that(self, *, error=None, timed_out=False, answer=''):
        def fake(prompt, model, env, scratch, limit):
            self.prompts.append((prompt, model, scratch))
            return answer, {'num_turns': 1}, error, timed_out, b'RAW'
        patcher = patch.object(advisor, 'call', fake); patcher.start(); self.addCleanup(patcher.stop)

    def _plan_with_decision(self):
        advisor.init_rules(self.ledger)
        plans.propose(self.ledger, 'P1', sourced(plan_json(), decisions=[DECISION]), AUTHOR)

    def _advice(self):
        with self.ledger.transaction() as conn:
            return plans.derive(self.ledger, conn, 'P1')['advice'].get(1)

    # ---- E1: each error kind is recorded as a typed provider_error with an inconclusive verdict ----
    def test_e1_unavailable_is_typed_inconclusive(self):
        self._plan_with_decision()
        self._call_that(error='connection refused')
        advisor.advise(self.ledger, 'P1')
        ev = self._advice()
        self.assertEqual(ev['provider_error'], 'provider_unavailable')
        self.assertFalse(ev['usable'])
        self.assertTrue(all(a['verdict'] == 'inconclusive' for a in ev['answers']))

    def test_e1_timeout_is_typed_inconclusive(self):
        self._plan_with_decision()
        self._call_that(timed_out=True)
        advisor.advise(self.ledger, 'P1')
        self.assertEqual(self._advice()['provider_error'], 'timeout')

    def test_e1_bad_schema_is_typed_inconclusive(self):
        self._plan_with_decision()
        self._call_that(answer='this is not the JSON object asked for')
        advisor.advise(self.ledger, 'P1')
        ev = self._advice()
        self.assertEqual(ev['provider_error'], 'invalid_response')
        self.assertFalse(ev['usable'])

    # ---- E2 / E12: approval is NOT blocked by advice_missing on a provider error (red on pre-fix code) ----
    def test_e2_approval_not_blocked_by_provider_error(self):
        for setup in ('unavailable', 'timeout', 'bad'):
            with self.subTest(setup):
                self.setUp()                       # fresh ledger per case
                self._plan_with_decision()
                if setup == 'unavailable': self._call_that(error='connection refused')
                elif setup == 'timeout':   self._call_that(timed_out=True)
                else:                      self._call_that(answer='garbled')
                advisor.advise(self.ledger, 'P1')
                # the owner approves in one go — no advice_missing, no second round
                result = plans.approve(self.ledger, 'P1', 'owner', 'said yes')
                self.assertEqual(result['status'], 'approved')

    def test_e12_check_provenance_emits_no_advice_missing_on_provider_error(self):
        self._plan_with_decision()
        self._call_that(error='connection refused')
        advisor.advise(self.ledger, 'P1')
        with self.ledger.transaction() as conn:
            state = plans.derive(self.ledger, conn, 'P1')
        contract, sha = plans.load(self.ledger, state, 1)
        advice = state['advice'].get(1)
        reasons = step0.check_provenance(self.ledger, contract, sha, advice)
        self.assertNotIn('advice_missing', [code for code, _ in reasons])

    # counter: a genuinely MISSING advice (no event at all) still blocks — the fix does not open the gate wholesale.
    def test_counter_missing_advice_still_blocks(self):
        advisor.init_rules(self.ledger)
        plans.propose(self.ledger, 'P1', sourced(plan_json(), decisions=[DECISION]), AUTHOR)   # no advise() at all
        with self.ledger.transaction() as conn:
            state = plans.derive(self.ledger, conn, 'P1')
        contract, sha = plans.load(self.ledger, state, 1)
        reasons = step0.check_provenance(self.ledger, contract, sha, None)
        self.assertIn('advice_missing', [code for code, _ in reasons])

    # ---- E3 / E14: the pinned provider/model is not switched ----
    def test_e3_pinned_model_unchanged_no_other_provider(self):
        self._plan_with_decision()
        self._call_that(error='connection refused')
        advisor.advise(self.ledger, 'P1', PINNED)
        ev = self._advice()
        self.assertEqual(ev['model'], PINNED)                       # recorded model is the pinned one
        # exactly one call was made, to the pinned model; no fallback to a second provider
        self.assertEqual(len(self.prompts), 1)
        self.assertEqual(self.prompts[0][1], PINNED)


if __name__ == '__main__':
    unittest.main()
