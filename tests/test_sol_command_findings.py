"""Command failures are evidence of a failed check, never an inferred product bug."""
import sys

from onecrew.v2 import findings, plan, review_dispatch, verdict
from tests.test_v2_l1 import Fixture, milestone, plan_json


class CommandFindingTests(Fixture):
    def contract(self, argv):
        return plan_json(milestones=[milestone(argv=argv, mode='until_pass', max_repairs=3)])

    def start(self, argv):
        plan.propose(self.ledger, 'P1', self.contract(argv), 'codex', workflow=True)
        plan.approve(self.ledger, 'P1', 'owner', 'temporary command fixture')

    def test_failed_command_links_finding_and_only_current_repaired_receipt_closes(self):
        self.start([sys.executable, '-c', 'from pathlib import Path; print("checking a.txt"); assert Path("a.txt").read_text()=="fixed\\n"'])
        red = verdict.run(self.ledger, 'P1', 'M1')['milestones'][0]['last_verdict']['receipt']
        [finding] = findings.list_findings(self.ledger, 'P1', open_only=True)
        self.assertEqual(finding['source']['receipt'], red)
        self.assertEqual(finding['failure_kind'], 'check_failure')
        self.assertEqual(finding['cause'], 'not_established')
        refused = findings.close_from_recheck(self.ledger, 'P1', finding['id'], run_receipt=red,
            request=review_dispatch.recheck_request(self.ledger, 'P1', finding, red))
        self.assertEqual(refused['closed'], [])
        (self.root / 'a.txt').write_text('fixed\n')
        shown = verdict.run(self.ledger, 'P1', 'M1')
        self.assertEqual(shown['finding_rechecks'][0]['closed'], [finding['id']])
        self.assertEqual(findings.list_findings(self.ledger, 'P1', open_only=True), [])
        artifact = shown['milestones'][0]['last_verdict']['artifact_sha']
        self.assertEqual(plan.accept(self.ledger, 'P1', 'owner', 'fixture', artifact)['status'], 'accepted')

    def test_infrastructure_error_is_inconclusive_and_opens_no_product_finding(self):
        # review of dev24c (2.5.0.dev24): a program that is not there is refused before the verifier ("not started", nothing recorded); before,
        # Popen failed and the verdict was inconclusive. Either way no product finding is opened.
        from onecrew.ledger import LedgerError
        self.start([str(self.root / 'missing-executable.exe')])
        with self.assertRaises(LedgerError) as caught:
            verdict.run(self.ledger, 'P1', 'M1')
        self.assertIs(getattr(caught.exception, 'verifier_started', None), False)
        self.assertEqual(plan.show(self.ledger, 'P1')['milestones'][0]['runs'], 0)
        self.assertEqual(findings.list_findings(self.ledger, 'P1'), [])
