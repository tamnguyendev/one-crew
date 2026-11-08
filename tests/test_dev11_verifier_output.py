"""2.5.0.dev11: a failed command check is visible where the owner looks (dogfood 05/11 gaps).

- the command's stdout/stderr open through `track evidence` and the tracking page, one hop through a receipt the root's own events name;
- a blob of another root is still refused;
- a plain plan (no --workflow) has no finding register: the page says so instead of "no finding recorded";
- a --workflow plan turns the same failed command into an open finding with its receipt (since 4d8311e), shown on the page.
"""
import json
import shutil
import subprocess
import sys

from onecrew.v2 import plan, tracking, verdict
from onecrew.v2.tracking_work_web import SCRIPT
from tests.test_v2_l1 import Fixture, milestone, plan_json

FAILING = [sys.executable, '-c', 'import sys; print("checking a.txt: MARKER-OUT"); print("MARKER-ERR", file=sys.stderr); sys.exit(3)']


class _Base(Fixture):
    def start(self, name='P1', workflow=False):
        plan.propose(self.ledger, name, plan_json(milestones=[milestone(argv=FAILING)]), 'claude', workflow=workflow)
        plan.approve(self.ledger, name, 'owner', 'temporary fixture approval')
        shown = verdict.run(self.ledger, name, 'M1')
        self.assertEqual(shown['milestones'][0]['last_verdict']['result'], 'fail')
        return tracking.detail(self.ledger.state_root, name)


class VerifierOutputTests(_Base):
    def test_stdout_and_stderr_of_a_failed_command_open_through_track_evidence(self):
        d = self.start()
        [run] = d['work']['checks']['runs']
        self.assertEqual(run['status'], 'fail')
        outputs = run['outputs']
        self.assertEqual(outputs['exit_code'], 3)
        for stream, marker in (('stdout', 'MARKER-OUT'), ('stderr', 'MARKER-ERR')):
            key = outputs[stream]
            self.assertIn(key, d['evidence_keys'])                                  # the page's open button is offered
            self.assertIn(marker, tracking.evidence(self.ledger.state_root, 'P1', key)['text'])

    def test_output_of_another_roots_receipt_is_refused(self):
        self.start('P2')
        other = tracking.detail(self.ledger.state_root, 'P2')['work']['checks']['runs'][0]['outputs']['stdout']
        plan.propose(self.ledger, 'P1', plan_json(), 'claude')
        with self.assertRaises(PermissionError):
            tracking.evidence(self.ledger.state_root, 'P1', other)

    def test_plain_plan_says_it_has_no_finding_register(self):
        d = self.start()
        self.assertIs(d['work']['finding_register'], False)
        self.assertEqual(d['work']['findings'], [])

    def test_workflow_plan_records_the_failed_command_as_a_finding(self):
        d = self.start(workflow=True)
        self.assertIs(d['work']['finding_register'], True)
        [finding] = d['work']['findings']
        run = d['work']['checks']['runs'][0]
        self.assertEqual(finding['source']['receipt'], run['receipt'])
        self.assertIn(finding['source']['receipt'], d['evidence_keys'])


class PageTests(_Base):
    def render(self, d):
        node = shutil.which('node')
        if not node: self.skipTest('Node unavailable; not verified')
        prelude = ('function esc(x){return String(x==null?"":x).replace(/[&<>"]/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;","\\"":"&quot;"}[c]))}\n'
                   'function when(x){return x} function hms(x){return String(x)} function openBtn(k){return "<button data-open=\\""+esc(k)+"\\">"+esc(k)+"</button>"}\n'
                   'function nodeName(d,n){return String(n)}\n')
        result = subprocess.run([node, '-'], input=prelude + SCRIPT + '\nconsole.log(JSON.stringify(workResults(' + json.dumps(d) + ',' + json.dumps(d['work']) + ')));',
                                text=True, encoding='utf8', capture_output=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr[-2000:])
        return json.loads(result.stdout)

    def test_page_offers_the_output_and_names_the_missing_register(self):
        d = self.start()
        html = self.render(d)
        outputs = d['work']['checks']['runs'][0]['outputs']
        self.assertIn('data-open="' + outputs['stdout'] + '"', html)
        self.assertIn('data-open="' + outputs['stderr'] + '"', html)
        self.assertIn('mã thoát 3', html)
        self.assertNotIn('Chưa ghi nhận finding', html)
        self.assertIn('không có sổ finding', html)

    def test_page_lists_the_workflow_finding(self):
        d = self.start(workflow=True)
        html = self.render(d)
        self.assertIn(d['work']['findings'][0]['id'], html)
        self.assertNotIn('không có sổ finding', html)

