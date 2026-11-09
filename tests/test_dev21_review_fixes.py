"""2.5.0.dev21 — tenth independent review (Kiro CLI, 10/11; BAO-CAO-REVIEW-dev20.md, verdict FAIL) on c0d62b3: the parts the coordinator asked
for without the owner. Red on c0d62b3: FixedTimes and NoCodexCliIsNoCall; CandidateCallerKeepsThePolicyRule is a guard of the dev20 fix through
its real caller (green on c0d62b3, red if the rule is taken out of proof_mismatch).

P2 (#4)  the times of change of the checkout came from when it ran; now every file and folder has one fixed time (policy exact-blob-bytes/2).
P2 (#2)  no Codex or Kiro CLI was found only after the launch: one call charged, the legacy path counted it too.
P3       the policy rule is tested through a real caller (the candidate checker), not only proof_mismatch.
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
from onecrew.v2 import plan as plans, providers, verdict
from onecrew.v2.metered_verifier import ProviderCall
from onecrew.v2.verifiers import command
from tests import test_wf_candidate_handoff as handoff
from tests.test_v2_l1 import Fixture, plan_json, milestone
from tests.test_v2_reviewer import reviewer_milestone

CHECK_TIMES = ('import os,sys; t={os.path.getmtime(p) for p in ("a.txt","sub","sub/b.txt",".")}; '
               'print(sorted(t)); sys.exit(0 if t=={946684800.0} else 1)')      # prints: a silent fast pass is not believed


class FixedTimes(Fixture):
    def test_every_file_and_folder_of_the_checkout_has_the_fixed_time_through_verdict_run(self):
        (self.root / 'sub').mkdir(); (self.root / 'sub' / 'b.txt').write_text('b\n')
        plans.propose(self.ledger, 'P1', plan_json(milestones=[milestone(argv=[sys.executable, '-c', CHECK_TIMES])]), 'claude')
        plans.approve(self.ledger, 'P1', 'owner', 'fixture')
        shown = verdict.run(self.ledger, 'P1', 'M1', self.root)
        self.assertEqual(shown['milestones'][0]['state'], 'passed', shown['milestones'][0])


def no_cli(provider, env, *a, **k):
    raise LedgerError(f'No {provider} CLI was found on this machine.')


class NoCodexCliIsNoCall(Fixture):
    def test_root_budget_codex_without_a_cli_charges_nothing(self):
        plans.propose(self.ledger, 'P1', plan_json(milestones=[reviewer_milestone('gpt-5-codex', provider='codex')], budget={'max_calls': 2, 'time': 1}),
                      'claude', workflow=True)
        plans.approve(self.ledger, 'P1', 'owner', 'bounded temporary fixture')
        os.environ['ONECREW_ACTOR'] = 'claude'
        with patch.object(providers, 'cli_prefix', no_cli), self.assertRaises(LedgerError) as caught:
            ProviderCall(self.ledger, 'P1', 'M1')('prompt', {'provider': 'codex', 'model': 'gpt-5-codex'}, {}, self.root.parent, 1)
        self.assertIs(getattr(caught.exception, 'verifier_started', None), False)
        with self.ledger.transaction() as conn:
            budget = budget_core.group(conn, plans.anchor_events(self.ledger, conn, 'P1')['task_id'])
        self.assertEqual((budget['used_calls'], budget['unknown_attempts']), (0, 0), budget)

    def test_legacy_kiro_without_a_cli_did_not_start_and_is_not_held(self):
        plans.propose(self.ledger, 'P1', plan_json(milestones=[reviewer_milestone('claude-haiku-4.5', provider='kiro')]), 'codex')
        plans.approve(self.ledger, 'P1', 'owner', 'fixture')
        (self.root / 'a.txt').write_text('one\ntwo\n')
        with patch.object(providers, 'cli_prefix', no_cli):
            for _ in range(2):                     # on c0d62b3 the first records an inconclusive verdict that counted one model call
                with self.assertRaises(LedgerError) as caught:
                    verdict.run(self.ledger, 'P1', 'M1', self.root)
                self.assertIn('No kiro CLI', str(caught.exception))
                self.assertIs(getattr(caught.exception, 'verifier_started', None), False)


class CandidateCallerKeepsThePolicyRule(handoff.CandidateFixture):
    def test_a_pass_of_another_policy_is_run_again_by_the_candidate_checker(self):
        with patch.object(command, 'CHECKOUT_POLICY', 'tree-attributes-applied/0'):
            self.revise(self.definition()); self.step()
            self.engine.verify(self.ledger, 'P1', 'C', self.production_checker)
            self.step()
            self.engine.verify(self.ledger, 'P1', 'I', self.production_checker)
        view = self.engine.state(self.ledger, 'P1')
        item = next(n for n in view['definition']['nodes'] if n['id'] == 'I')
        checked = cv.CandidateChecker(self.ledger, 'P1')(item, view['nodes']['I']['artifact'], previous_receipt=None)   # prior_pass -> _reused_row
        store = Snapshots(self.ledger.state_root)
        import json
        wrappers = [json.loads(store.read_blob(row['evidence'])) for row in checked['checks']]
        self.assertTrue(wrappers)
        self.assertFalse([w for w in wrappers if w.get('reused_from_run')], 'a pass of another checkout policy was wrapped again')
