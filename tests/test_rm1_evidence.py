"""Verify evidence through plan, report and tracking on separate temporary project ledgers."""
import contextlib
import io
import json

from onecrew.v2 import cli, plan, report, tracking, verdict
from pathlib import Path
from tests import v2_fixture as fixtures
from tests.test_ver60_reuse import scoped


class Evidence(fixtures.Fixture):
    def start(self):
        self.checker_input = Path(self.temp.name) / 'checker-policy'
        self.checker_input.write_text('original rules')
        self.approved(value=fixtures.plan_json([scoped('M1', ['a.txt'], env_inputs=[str(self.checker_input)]),
                                                fixtures.milestone('M2')]))
        shown = verdict.run(self.ledger, 'P1', 'M1')
        self.task = shown['anchor_task']
        return shown['milestones'][0]

    def view(self, index=0):
        with contextlib.redirect_stdout(io.StringIO()) as output:
            code = cli.main(['--project', str(self.root), '--state-root', str(self.ledger.state_root),
                             'plan', 'show', 'P1'])
        self.assertEqual(code, 0, output.getvalue())
        return json.loads(output.getvalue())['milestones'][index]

    def alter(self, kind, modify):
        # Model damaged/legacy imported history on this disposable ledger only.
        with self.ledger.transaction(write=True) as conn:
            row = conn.execute('SELECT seq,payload FROM events WHERE task_id=? AND kind=? ORDER BY seq DESC LIMIT 1',
                               (self.task, kind)).fetchone()
            payload = json.loads(row['payload'])
            modify(payload)
            conn.execute('UPDATE events SET payload=? WHERE seq=?', (json.dumps(payload), row['seq']))

    def test_current_and_valid_reuse_have_distinct_reasons(self):
        self.start()
        verdict.run(self.ledger, 'P1', 'M2')
        full = self.view(1)
        self.assertEqual(full['evidence_status'], 'current')
        (self.root / 'notes.md').write_text('outside the intermediate check')
        kept = self.view()
        self.assertEqual(kept['evidence_status'], 'reused')
        self.assertNotEqual(kept['evidence_reason'], full['evidence_reason'])
        self.assertEqual(self.view(1)['evidence_status'], 'stale')

    def test_unrelated_commit_preserves_scoped_reuse(self):
        first = self.start()
        (self.root / 'notes.md').write_text('unrelated')
        self.git('add', 'notes.md')
        self.git('commit', '-qm', 'unrelated fixture change')
        kept = self.view()
        self.assertEqual((kept['evidence_status'], kept['last_verdict']), ('reused', first['last_verdict']))

    def test_wrong_ledger_task_revision_or_criterion_stale(self):
        self.start()
        for key, wrong in [('plan', 'P2'), ('plan_sha', '0' * 64), ('milestone', 'M2')]:
            with self.subTest(key=key):
                original = next(p for k, p in self.events() if k == 'verdict.recorded')
                self.alter('verdict.recorded', lambda p: p.update({key: wrong}))
                self.assertNotEqual(self.view(1 if key == 'milestone' else 0)['state'], 'passed')
                self.alter('verdict.recorded', lambda p: p.update(original))
        # A copied verdict alone has no issuer on the other root.
        self.approved(name='P2', value=fixtures.plan_json([scoped('M1', ['a.txt']), fixtures.milestone('M2')]))
        with self.ledger.transaction(write=True) as conn:
            other = plan.anchor_events(self.ledger, conn, 'P2')
            plan.emit(self.ledger, conn, other['task_id'], 'verdict.recorded', dict(original, plan='P2'))
        self.assertNotEqual(plan.show(self.ledger, 'P2')['milestones'][0]['state'], 'passed')

    def test_changed_input_artifact_attempt_or_checker_rejected(self):
        self.start()
        (self.root / 'a.txt').write_text('changed input')
        self.assertEqual(self.view()['evidence_status'], 'stale')
        (self.root / 'a.txt').write_text('one\n')
        self.checker_input.write_text('changed rules')
        self.assertIn('env_inputs', self.view()['evidence_reason'])
        self.checker_input.write_text('original rules')
        original = self.view()['last_verdict']['artifact_sha']
        self.alter('verdict.recorded', lambda p: p.update(artifact_sha='f' * 40))
        self.assertEqual(self.view()['evidence_status'], 'conflicting')
        self.alter('verdict.recorded', lambda p: p.update(artifact_sha=original))
        self.alter('verdict.receipt_issued', lambda p: p.update(run_id='different-attempt'))
        self.assertEqual(self.view()['evidence_status'], 'missing')

    def test_conflicting_same_id_never_certifies(self):
        first = self.start()
        issued = next(p for k, p in self.events() if k == 'verdict.receipt_issued')
        with self.ledger.transaction(write=True) as conn:
            plan.emit(self.ledger, conn, self.task, 'verdict.receipt_issued', dict(issued, receipt='a' * 64))
        view = self.view()
        self.assertEqual(view['last_verdict'], first['last_verdict'])
        self.assertEqual((view['stale'], view['evidence_status']), (True, 'conflicting'))

    def test_missing_legacy_links_readable_as_unknown(self):
        first = self.start()
        self.alter('verdict.receipt_issued', lambda p: p.pop('run_id'))
        view = self.view()
        self.assertEqual(view['last_verdict'], first['last_verdict'])
        self.assertEqual(view['evidence_status'], 'missing')
        self.assertNotEqual(view['state'], 'passed')
        self.assertIn(view['evidence_reason'], ' '.join(report.render_report(self.ledger.state_root, 'P1').split()))

    def test_cli_ui_report_agree_on_status_and_reason(self):
        self.start()
        for status in ('reused', 'stale'):
            if status == 'stale':
                (self.root / 'a.txt').write_text('input changed')
            cli_view = self.view()
            page = tracking.detail(self.ledger.state_root, 'P1')
            self.assertEqual(page['milestones'][0]['evidence_status'], status)
            self.assertEqual(cli_view['evidence_status'], status)
            reason = cli_view['evidence_reason']
            self.assertEqual(page['milestones'][0]['evidence_reason'], reason)
            self.assertIn(reason, page['milestone_checks']['rows'][0]['note'])
            self.assertIn(reason, ' '.join(report.render_report(self.ledger.state_root, 'P1').split()))
