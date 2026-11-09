"""2.5.0.dev20 — ninth independent review (Kiro CLI, 10/11; BAO-CAO-REVIEW-dev19.md, verdict FAIL) on 45ccc76.

The coordinator, 10/11: "stop patching path by path": one rule at every place that REUSES or PUBLISHES a verifier result. Every receipt a verifier
writes carries checkout_policy; command.policy_current() is checked by proof_mismatch (candidate _reuse rows, _reused_row, verdict
_reuse_candidate_pass), by _reuse on the node receipt, by publish_issued, and by receipt_assessment. These tests come from the sink side: a
result of another (or no) checkout policy, for each verifier type, is never reused or published.

P2: the Claude CLI and the credential are decided once (reviewer.prepare) and the call runs exactly that; the legacy reviewer (no root budget)
prepares inside before_verifier, so no CLI says the reviewer did not start.
"""
import os
import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))          # test_v2_reviewer imports test_v2_l1 by its plain name

from onecrew import budget_core
from onecrew import common_verification as cv
from onecrew.ledger import LedgerError
from onecrew.snapshots import Snapshots
from onecrew.v2 import engine, namespaces, plan as plans, verdict
from onecrew.v2 import verification_evidence as evidence
from onecrew.v2.metered_verifier import ProviderCall
from onecrew.v2.verifiers import command, reviewer
from tests import test_review_b2_lifecycle as lifecycle
from tests import test_v2_reviewer as reviewer_tests
from tests.test_v2_l1 import Fixture, plan_json, milestone
from tests.test_v2_reviewer import reviewer_milestone, answer, row

OLD = 'tree-attributes-applied/0'
REFUSED = 'proof was made under another checkout policy'


class ProofSink(Fixture):
    """proof_mismatch: the check every candidate reuse path shares, for each verifier type."""
    def test_a_proof_without_or_with_another_policy_is_refused_for_every_type(self):
        for vtype, config in (('command', milestone()['verifier']['config']), ('reviewer', reviewer_milestone()['verifier']['config']),
                              ('data', {})):
            family = cv.PROOF_KIND.get(vtype, 'candidate-adapter-check')
            wrapper = {'kind': family, cv.PROOF_FIELD[family]: 'x', 'milestone': 'M1', 'tree': 't'}
            m = {'id': 'M1', 'verifier': {'type': vtype, 'config': config}}
            for proof in ({}, {'checkout_policy': OLD}):
                with self.subTest(type=vtype, proof=proof):
                    self.assertEqual(cv.proof_mismatch(wrapper, proof, m, 'sha', 1, 't'), REFUSED)
            current = cv.proof_mismatch(wrapper, {'checkout_policy': command.CHECKOUT_POLICY}, m, 'sha', 1, 't')
            self.assertNotEqual(current, REFUSED)                                   # the rule passes; later checks decide the rest


class RecordedReceiptSink(reviewer_tests.ReviewerFixture):
    """receipt_assessment (verdict top level): a bound receipt of another policy is stale, command and reviewer alike."""
    def bound_plan(self, ms):
        value = plan_json(milestones=ms); value['understanding']['target']['paths'] = ['a.txt']
        plans.propose(self.ledger, 'P1', value, 'codex', workflow=True, capabilities=list(namespaces.CAPABILITIES))
        plans.approve(self.ledger, 'P1', 'owner', 'temporary fixture')
        os.environ['ONECREW_ACTOR'] = 'codex'

    def assess(self):
        with self.ledger.transaction() as conn: state = plans.derive(self.ledger, conn, 'P1')
        contract = plans.load(self.ledger, state, 1)[0]
        receipt = plans.show(self.ledger, 'P1')['milestones'][0]['last_verdict']['receipt']
        return evidence.receipt_assessment(self.ledger, contract, contract['milestones'][0], 1, receipt, command.verified_sha(self.root),
                                           task_id=state['task_id'])

    def test_a_command_receipt_of_another_policy_is_stale(self):
        self.bound_plan([milestone()])
        with patch.object(command, 'CHECKOUT_POLICY', OLD):
            verdict.run(self.ledger, 'P1', 'M1')
        result = self.assess()
        self.assertFalse(result['reusable'], result); self.assertIn('checkout policy', '; '.join(result['reasons']))

    def test_a_reviewer_receipt_of_another_policy_is_stale(self):
        self.bound_plan([reviewer_milestone()])
        (self.root / 'a.txt').write_text('one\ntwo\n')
        with patch.object(command, 'CHECKOUT_POLICY', OLD), \
                patch.object(reviewer, 'call', return_value=(answer(row('R1'), row('R2')), {}, None, False, b'fixture')):
            verdict.run(self.ledger, 'P1', 'M1')
        result = self.assess()
        self.assertFalse(result['reusable'], result); self.assertIn('checkout policy', '; '.join(result['reasons']))


class IssuedResultSink(lifecycle.CheckFixture):
    """publish_issued: a node result issued under another policy (the process stopped before publishing, then OneCrew was upgraded) is not
    published; the node is checked again."""
    def test_an_issued_result_of_another_policy_is_not_published(self):
        self.step()
        real = engine._event

        def crash(ledger, conn, view, nid, kind, **payload):
            if kind == 'node.verification': raise RuntimeError('process lost before publication')
            return real(ledger, conn, view, nid, kind, **payload)

        calls = []

        def counting(item, artifact): calls.append(artifact); return self.checker(item, artifact)

        with patch.object(command, 'CHECKOUT_POLICY', OLD), patch.object(engine, '_event', side_effect=crash):
            with self.assertRaises(RuntimeError): self.verify('C', counting)
        again = self.verify('C', counting)
        if again.get('status') == 'stale': again = self.verify('C', counting)
        self.assertEqual(len(calls), 2, 'the old issued result must not stand in for a check under this policy')
        self.assertEqual(again['result'], 'pass')


class CliFoundOnce(Fixture):
    def setUp(self):
        super().setUp()
        plans.propose(self.ledger, 'P1', plan_json(milestones=[reviewer_milestone()], budget={'max_calls': 2, 'time': 1}), 'codex', workflow=True)
        plans.approve(self.ledger, 'P1', 'owner', 'bounded temporary fixture')
        os.environ['ONECREW_ACTOR'] = 'codex'

    def test_the_cli_is_looked_up_once_and_the_call_runs_what_was_found(self):
        looked, ran = [], []

        def cli(env):
            looked.append(1)
            if len(looked) > 1: raise LedgerError('the Claude CLI vanished between two lookups')
            return ['fixture-claude']

        def process(argv, prompt, scratch, env, limit):
            ran.append(argv[0])
            return b'{"result": "{}"}', b'', 0, False, None

        with patch.object(reviewer, 'cli_argv', cli), patch.object(reviewer.providers, 'run_process', process):
            ProviderCall(self.ledger, 'P1', 'M1')('prompt', {'provider': 'claude', 'model': 'claude-haiku-5-5'}, {}, self.root.parent, 1)
        self.assertEqual((len(looked), ran), (1, ['fixture-claude']))


class LegacyReviewerNoCli(reviewer_tests.ReviewerFixture):
    def test_a_legacy_reviewer_without_a_cli_did_not_start_and_is_not_held(self):
        self.start(); self.reply(answer(row('R1'), row('R2')))

        def no_cli(env): raise LedgerError('The Claude CLI was not found on this machine.')

        with patch.object(reviewer, 'cli_argv', no_cli), self.assertRaises(LedgerError) as caught:
            verdict.run(self.ledger, 'P1', 'M1', self.root)
        self.assertIs(getattr(caught.exception, 'verifier_started', None), False)
        shown = verdict.run(self.ledger, 'P1', 'M1', self.root)        # not held: runs again without release-run
        self.assertEqual(shown['milestones'][0]['state'], 'passed', shown['milestones'][0])
