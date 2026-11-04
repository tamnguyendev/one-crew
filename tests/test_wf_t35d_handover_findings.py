"""T35d (W23d) [E4]: the handover lists exactly the OPEN findings of the register, each with its ID, criterion and artifact; a closed one is absent.

Engine fixture with the finding register (tests/test_wf_t11_integration_finding): N1 and N2 both fail their check -> F1 (N1) and F2 (N2) open;
the prepared repair of N2 re-runs it and its passing receipt closes F2 through the register. The handover then names F1 with `check-N1` and the
artifact of N1, and does not list F2 among the open findings. Counter-rule: a page listing F2 as open, or F1 without its criterion, fails.
"""
from onecrew.v2 import findings, repair_tasks, report
from tests.test_wf_t11_integration_finding import IntegrationFindingTests


class HandoverFindingsTests(IntegrationFindingTests):
    def test_e4_open_findings_only_with_id_criterion_and_artifact(self):
        for nid in ('N1', 'N2'):
            self.assertEqual(self.step()['node'], nid); self.verify(nid, self.red)
        opened = {f['node']: f for f in findings.list_findings(self.ledger, 'P1', open_only=True)}
        self.assertEqual(set(opened), {'N1', 'N2'})
        f1, f2 = opened['N1'], opened['N2']
        receipt = self.engine.state(self.ledger, 'P1')['nodes']['N2']['verification_receipt']
        repair_tasks.prepare(self.ledger, 'P1', 'N2', 'N2', reason='b.txt rows', evidence=[receipt])
        self.assertEqual(self.step()['node'], 'N2')
        self.assertEqual(self.verify('N2')['findings']['closed'], [f2['id']])
        self.assertEqual([f['id'] for f in findings.list_findings(self.ledger, 'P1', open_only=True)], [f1['id']])
        page = report.render_handover(self.ledger.state_root, 'P1', project_id=self.ledger.project_id)
        open_lines = [line for line in page.splitlines() if 'Finding còn mở:' in line]
        self.assertEqual(len(open_lines), 1, page)
        line = open_lines[0]
        self.assertIn(f1['id'], line); self.assertIn('tiêu chí check-N1', line); self.assertIn('artifact ' + f1['artifact_sha'][:7], line)
        self.assertNotIn(f2['id'], line)
        self.assertNotIn(f2['id'] + ' ·', page)                                                        # F2 is not listed as open anywhere
        self.assertIn('Finding còn mở', page)
