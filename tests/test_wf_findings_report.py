"""W23d uses the same finding register as review and acceptance, read-only."""
import hashlib
import unittest

from onecrew.v2 import findings, report, verdict
from tests.test_v2_l1 import Fixture
from tests import test_wf_findings_integration as runtime_fixtures


class FindingsReportTests(Fixture):
    def setUp(self):
        runtime = runtime_fixtures.FindingRuntimeTests()
        self.addCleanup(runtime.doCleanups)
        runtime.setUp()
        self.root, self.ledger, self.prompts = runtime.root, runtime.ledger, runtime.prompts
        self.events_for = runtime.events_for

    def test_green_verdict_does_not_hide_unresolved_finding_in_handover(self):
        verdict.run(self.ledger, 'P1', 'M1')
        (self.root / 'a.txt').write_text('one\ntwo\nrepaired\n')
        verdict.run(self.ledger, 'P1', 'M1')
        latest = self.events_for('verdict.recorded')[-1]
        before = hashlib.sha256(self.ledger.path.read_bytes()).hexdigest()
        text = report.render_handover(self.ledger.state_root, 'P1', project_id=self.ledger.project_id)
        page = report.render_present(self.ledger.state_root, 'P1', project_id=self.ledger.project_id)
        self.assertIn('RF1', text)
        self.assertIn('cần kiểm lại', text)
        self.assertIn('AI cần xử lý finding', page)
        self.assertEqual(hashlib.sha256(self.ledger.path.read_bytes()).hexdigest(), before)
        self.assertEqual(len(self.prompts), 2, 'presentation never invokes a model')
        findings.resolve(self.ledger, 'P1', 'RF1', latest['receipt'], reason='R1 rechecked', artifact_sha=latest['artifact_sha'])
        clean = report.render_handover(self.ledger.state_root, 'P1', project_id=self.ledger.project_id)
        self.assertIn('Finding còn mở: 0', clean)
        self.assertNotIn('finding RF1', clean)
        self.assertIn('đạt', clean)


if __name__ == '__main__':
    unittest.main()
