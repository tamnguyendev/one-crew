"""T12/T43 local outbox evidence; no real desktop or host message is sent."""
import json
import os
import subprocess
import sys
import sqlite3
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from onecrew import desktop_notifications as desktop, desktop_window, notifications
from onecrew.ledger import Ledger, LedgerError
from onecrew.v2 import estimates, exceptions, plan, report, verdict
from tests.test_v2_l1 import Fixture, plan_json, milestone, BAD
from tests import wf_oldversion as ov


def question(u2=False):
    return {'schema_version': 1, 'question': 'Allow the scoped write?', 'reason': 'The required output needs write permission.',
            'impact': 'Only M2 waits; M1 can continue.', 'options': [{'id': 'yes', 'label': 'Allow'}, {'id': 'no', 'label': 'Keep blocked'}],
            'recommendation': 'no', 'action': {'type': 'authorize', 'parameters': {'class': 'U2', 'still_running': ['M1']} if u2 else {}}}


class ExceptionTests(Fixture):
    def setUp(self):
        super().setUp()
        self.env = patch.dict(os.environ, ONECREW_DESKTOP_HOME=str(Path(self.temp.name) / 'desktop'))
        self.env.start(); self.addCleanup(self.env.stop)
        self.launch = patch.object(desktop, 'launch').start()
        self.addCleanup(patch.stopall)

    def start(self, deadline=None, value=None, span=(21600, 28800)):
        return self.approved(value=value, estimate={'execution_seconds': list(span) if span else None,
            'evidence': ['fixture:approved decomposition'], 'deadline': deadline, 'policy': {'relative_change': .25}})

    def notices(self):
        return [i['notice'] for i in exceptions.desktop_snapshots(self.ledger)]

    def ask(self, u2=False):
        return self.ledger.create_request(plan.show(self.ledger, 'P1')['anchor_task'], 'write', question(u2))

    def test_four_actionable_states_and_no_intermediate_progress(self):
        self.propose()
        first = self.notices()
        self.assertEqual([n['status'] for n in first], ['approval'])
        self.assertEqual(first[0]['open_content'], report.render_present(self.ledger.state_root, first[0]['plan']))
        plan.approve(self.ledger, 'P1', 'owner', 'fixture')
        self.assertEqual(self.notices(), [])
        req = self.ask()
        pending = self.notices()
        self.assertEqual([n['status'] for n in pending], ['question'])
        self.assertEqual(pending[0]['target'], {'type': 'request', 'request': req['id'], 'revision': req['revision']})
        self.ledger.reply(req['id'], req['revision'], 'no')
        self.assertEqual(self.notices(), [])
        verdict.run(self.ledger, 'P1', 'M1')
        done = self.notices()
        self.assertEqual([n['status'] for n in done], ['verified'])
        self.assertEqual(done[0]['current_status'], 'approved')
        self.assertTrue(done[0]['delivery_is_not_acceptance'])
        self.assertFalse(done[0]['user_attention_verified'])
        self.approved('STOP', plan_json(milestones=[milestone(argv=BAD, max_repairs=0)]))
        verdict.run(self.ledger, 'STOP', 'M1')
        self.assertEqual({n['status'] for n in self.notices()}, {'verified', 'stopped'})

    def test_only_final_verified_notice_and_artifact_mutation_suppresses_it(self):
        self.start(value=plan_json(milestones=[milestone(), milestone('M2')]))
        verdict.run(self.ledger, 'P1', 'M1')
        self.assertEqual(self.notices(), [])
        verdict.run(self.ledger, 'P1', 'M2')
        self.assertEqual([n['status'] for n in self.notices()], ['verified'])
        (self.root / 'a.txt').write_text('changed')
        self.assertEqual(self.notices(), [])

    def test_approved_upper_bound_same_cause_dedup_and_six_hours_quiet(self):
        self.start()
        estimates.reforecast(self.ledger, 'P1', 'eta1', [21600, 28800], 'at upper bound', ['evidence:same-cause'])
        self.assertEqual(exceptions.observe(self.ledger, 'P1'), [])
        estimates.reforecast(self.ledger, 'P1', 'eta2', [25000, 32400], 'required migration', ['evidence:same-cause'])
        exceptions.observe(self.ledger, 'P1', '2026-10-24T10:00:00+07:00')
        estimates.reforecast(self.ledger, 'P1', 'eta3', [33000, 43200], 'migration now clearer', ['evidence:same-cause'])
        self.assertEqual(exceptions.observe(self.ledger, 'P1', '2026-10-24T16:00:00+07:00'), [])
        notices = self.notices()
        self.assertEqual(len(notices), 1)
        self.assertEqual(notices[0]['status'], 'baseline')
        self.assertEqual(notices[0]['eta']['remaining_seconds'], [33000, 43200])
        self.assertEqual(notices[0]['eta']['waiting_seconds'], 'unknown')
        self.assertEqual(self.kinds().count('notice.exception'), 1)
        self.assertEqual(self.ledger.requests(), [])
        self.assertEqual(estimates.read(self.ledger, 'P1')['baseline']['execution_seconds'], [21600, 28800])

    def test_relative_remaining_change_alerts_below_baseline_upper(self):
        self.start()
        estimates.reforecast(self.ledger, 'P1', 'eta1', [3600, 7200], 'first stage complete', ['receipt:stage1'])
        self.assertEqual(exceptions.observe(self.ledger, 'P1'), [])
        estimates.reforecast(self.ledger, 'P1', 'eta2', [5400, 9000], 'at exact relative threshold', ['receipt:stage2'])
        self.assertEqual(exceptions.observe(self.ledger, 'P1'), [])
        estimates.reforecast(self.ledger, 'P1', 'eta3', [7200, 12000], 'new required step', ['receipt:stage3'])
        exceptions.observe(self.ledger, 'P1')
        self.assertEqual(len(self.notices()), 1)
        payload = next(p for k, p in self.events() if k == 'notice.exception')
        self.assertEqual(payload['triggers'], ['remaining_relative_change'])
        self.assertEqual(payload['execution_observation'], 'unknown')

    def test_forecast_projection_holds_write_fence_before_reading_sources(self):
        self.start()
        original = estimates.read
        def fenced(ledger, selector):
            competing = sqlite3.connect(ledger.path, timeout=0)
            try:
                with self.assertRaisesRegex(sqlite3.OperationalError, 'locked'):
                    competing.execute('BEGIN IMMEDIATE')
            finally:
                competing.close()
            return original(ledger, selector)
        with patch.object(estimates, 'read', side_effect=fenced):
            self.assertEqual(exceptions.observe(self.ledger, 'P1'), [])

    def test_pending_amendment_cannot_change_committed_deadline_milestone(self):
        self.start(deadline='2026-10-24T15:00:00+07:00')
        verdict.run(self.ledger, 'P1', 'M1')
        plan.amend(self.ledger, 'P1', plan_json(milestones=[milestone(), milestone('M2')]), 'new unapproved milestone', 'fixture')
        exceptions.observe(self.ledger, 'P1', '2026-10-24T16:00:00+07:00')
        self.assertNotIn('deadline', [n['status'] for n in self.notices()])

    def test_mandatory_addition_is_one_cause_optional_does_not_alert_or_grant(self):
        self.start()
        estimates.additional(self.ledger, 'P1', 'polish', 'optional', 'presentation only', ['O1'], [20000, 20000], ['evidence:polish'])
        self.assertEqual(exceptions.observe(self.ledger, 'P1'), [])
        estimates.additional(self.ledger, 'P1', 'migration', 'mandatory', 'required by O1', ['O1'], [10000, 11000], ['evidence:migration'])
        exceptions.observe(self.ledger, 'P1')
        estimates.reforecast(self.ledger, 'P1', 'eta', [33000, 45000], 'migration estimate', ['evidence:migration'])
        self.assertEqual(exceptions.observe(self.ledger, 'P1'), [])
        self.assertEqual([n['cause'] for n in self.notices()], ['additional:migration'])
        self.assertEqual(self.kinds().count('notice.exception'), 1)
        self.assertEqual(self.ledger.requests(), [])

    def test_deadline_and_blocker_delay_show_current_resolution_once(self):
        self.start(deadline='2026-10-24T15:00:00+07:00')
        req = self.ask(True)
        exceptions.observe(self.ledger, 'P1', '2026-10-24T15:01:00+07:00')
        self.assertEqual({n['status'] for n in self.notices()}, {'deadline', 'blocker'})
        blocked = next(n for n in self.notices() if n['status'] == 'blocker')
        self.assertEqual(blocked['still_running'], ['M1'])
        self.assertEqual(blocked['target']['request'], req['id'])
        self.ledger.reply(req['id'], req['revision'], 'no')
        self.assertEqual(exceptions.observe(self.ledger, 'P1', '2026-10-24T15:41:00+07:00'), [])
        resolved = next(n for n in self.notices() if n['status'] == 'blocker')
        self.assertEqual(resolved['id'], blocked['id'])
        self.assertEqual(resolved['event_at'], blocked['event_at'])
        self.assertTrue(resolved['resolved'])
        self.assertIsNone(resolved['user_action'])
        self.assertIn('đã giải', resolved['open_content'])
        self.assertEqual(resolved['target']['type'], 'plan-present')
        self.assertEqual(len(self.ledger.requests()), 1)

    def test_unknown_estimate_never_invents_eta_and_projection_does_not_write(self):
        self.start(span=None)
        self.ask(True)
        exceptions.observe(self.ledger, 'P1')
        before = self.events()
        n = self.notices()[0]
        self.assertIsNone(n['eta']['remaining_seconds'])
        self.assertFalse(n['eta']['calibrated'])
        self.assertEqual(self.events(), before)
        with self.assertRaises(LedgerError): exceptions.observe(self.ledger, 'P1', 'not-a-date')

    def test_revised_u2_gets_new_card_and_old_card_is_superseded(self):
        self.start()
        req = self.ask(True)
        exceptions.observe(self.ledger, 'P1')
        old = self.notices()[0]
        value = question(True)
        value['options'][0]['label'] = 'Allow only the narrower write'
        current = self.ledger.revise_request(req['id'], req['revision'], value)
        exceptions.observe(self.ledger, 'P1')
        cards = self.notices()
        self.assertEqual(len(cards), 1)
        self.assertNotEqual(cards[0]['id'], old['id'])
        self.assertEqual(cards[0]['target']['revision'], current['revision'])
        self.assertEqual(exceptions.observe(self.ledger, 'P1'), [])

    def test_actual_v1_pull_ack_and_desktop_failure_retry_never_approve(self):
        desktop.configure(self.ledger, True)
        self.propose()
        batch = notifications.pull(self.ledger, 'test')
        self.assertEqual([n['status'] for n in batch['notifications']], ['approval'])
        self.assertEqual(notifications.pull(self.ledger, 'test')['id'], batch['id'])
        notifications.ack(self.ledger, 'test', batch['id'])
        self.assertEqual(notifications.pull(self.ledger, 'test')['notifications'], [])
        self.launch.side_effect = OSError('fixture transport unavailable')
        before = self.events()
        desktop.publish(self.ledger)
        records = desktop.status(self.ledger)['records']
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]['status'], 'pending')
        self.launch.side_effect = None
        desktop.publish(self.ledger)
        self.assertEqual(len(desktop.status(self.ledger)['records']), 1)
        self.assertEqual(self.launch.call_count, 2)
        self.assertEqual(Path(records[0]['report']).read_text(encoding='utf-8'), report.render_present(self.ledger.state_root, 'P1'))
        self.assertEqual(self.events(), before)
        self.assertEqual(plan.show(self.ledger, 'P1')['status'], 'proposed')

        test = self
        class Widget:
            def __init__(self, *args, **kwargs): pass
            def pack(self, **kwargs): pass
            def insert(self, *args): pass
            def configure(self, **kwargs): pass
        class Window(Widget):
            def title(self, *args): pass
            def geometry(self, *args): pass
            def attributes(self, *args): pass
            def after(self, *args): pass
            def destroy(self): pass
            def winfo_ismapped(self): return True
            def protocol(self, name, callback): self.close = callback
            def bind(self, name, callback): self.map = callback
            def mainloop(self):
                self.map(SimpleNamespace(widget=self))
                shown = desktop.status(test.ledger)['records'][0]
                test.assertFalse(shown['user_attention_verified'])
                test.assertEqual(shown['receipt'], 'tk-window-mapped')
                self.close()
        with patch.dict('sys.modules', {'tkinter': SimpleNamespace(Tk=Window, Label=Widget, Frame=Widget, Button=Widget),
                                       'tkinter.scrolledtext': SimpleNamespace(ScrolledText=Widget)}):
            desktop_window.show(desktop.directory(self.ledger), records[0]['id'])
        self.assertEqual(desktop.status(self.ledger)['records'][0]['status'], 'closed')
        self.assertFalse(desktop.status(self.ledger)['records'][0]['answers_recorded'])
        self.assertEqual(self.events(), before)
        desktop.publish(self.ledger)
        self.assertEqual(self.launch.call_count, 2)

    def test_actual_archived_cli_preserves_status_gate_continue_and_pull_readability(self):
        old = ov.OldVersion(ov.archive('d3120c6', Path(__file__).resolve().parents[1], self.temp.name))
        contract_file = Path(self.temp.name) / 'old-contract.json'
        contract_file.write_text(json.dumps(ov.contract('old')), encoding='utf-8')
        code, out = old.run(self.root, self.ledger.state_root, 'plan', 'propose', 'OLD', '--file', str(contract_file), '--author', 'fixture')
        self.assertEqual(code, 0, out)
        plan.approve(self.ledger, 'plan:OLD', 'owner', 'local fixture', estimate={
            'execution_seconds': [21600, 28800], 'evidence': ['fixture:baseline']})
        before = ov.read(old, self.root, self.ledger.state_root, 'OLD')
        estimates.reforecast(self.ledger, 'plan:OLD', 'migration', [28800, 32400], 'required migration', ['fixture:migration'])
        exceptions.observe(self.ledger, 'plan:OLD')
        after = ov.read(old, self.root, self.ledger.state_root, 'OLD')
        same = ov.compare(before, after)
        self.assertTrue(same['S'] and same['G'] and same['C'], (before, after))
        self.assertFalse(after['read_blocked'])
        child = subprocess.run([sys.executable, '-X', 'utf8', '-m', 'onecrew', '--project', str(self.root),
            '--state-root', str(self.ledger.state_root), 'notifications', 'pull', '--consumer', 'old-fixture'],
            cwd=old.tree, env=old.env, capture_output=True, text=True, encoding='utf-8')
        self.assertEqual(child.returncode, 0, child.stderr + child.stdout)
        self.assertIn('notifications', json.loads(child.stdout))

    def test_mutating_poll_honors_project_scope_and_all_projects(self):
        self.start()
        other = Ledger(ov.git_project(self.temp.name, 'other-project'), self.ledger.state_root)
        plan.propose(other, 'P1', plan_json(), 'fixture')
        plan.approve(other, 'P1', 'owner', 'fixture', estimate={'execution_seconds': [21600, 28800], 'evidence': ['fixture:baseline']})
        with patch.object(exceptions, 'observe'):
            for ledger in (self.ledger, other):
                estimates.reforecast(ledger, 'P1', 'change', [28800, 32400], 'new required work', ['fixture:change'])
        self.assertEqual(len(exceptions.observe_project(self.ledger)), 1)
        self.assertEqual(len(exceptions.desktop_snapshots(other)), 0)
        self.assertEqual(len(exceptions.observe_project(self.ledger, all_projects=True)), 1)
        self.assertEqual(len(exceptions.desktop_snapshots(other)), 1)
        self.assertEqual(exceptions.observe_project(self.ledger, all_projects=True), [])

    def test_delayed_desktop_launch_refreshes_resolved_blocker_without_answering(self):
        self.start()
        desktop.configure(self.ledger, True)
        req = self.ask(True)
        exceptions.observe(self.ledger, 'P1', '2026-10-24T15:01:00+07:00')
        desktop.publish(self.ledger)
        record = desktop.status(self.ledger)['records'][0]
        self.assertIn(req['id'], Path(record['report']).read_text(encoding='utf-8'))
        self.ledger.reply(req['id'], req['revision'], 'no')
        before = self.events()
        received = []
        class Widget:
            def __init__(self, *args, **kwargs): pass
            def pack(self, **kwargs): pass
            def insert(self, position, text): received.append(text)
            def configure(self, **kwargs): pass
        class Window(Widget):
            def title(self, *args): pass
            def geometry(self, *args): pass
            def attributes(self, *args): pass
            def after(self, *args): pass
            def destroy(self): pass
            def winfo_ismapped(self): return True
            def protocol(self, name, callback): self.close = callback
            def bind(self, name, callback): self.map = callback
            def mainloop(self):
                self.map(SimpleNamespace(widget=self))
                self.close()
        with patch.dict('sys.modules', {'tkinter': SimpleNamespace(Tk=Window, Label=Widget, Frame=Widget, Button=Widget),
                                       'tkinter.scrolledtext': SimpleNamespace(ScrolledText=Widget)}):
            desktop_window.show(desktop.directory(self.ledger), record['id'])
        self.assertIn('đã giải', received[0])
        self.assertIn('2026-10-24T15:01:00+07:00', received[0])
        self.assertIn('Không cần bạn làm gì.', received[0])
        self.assertEqual(self.events(), before)
        self.assertEqual(self.ledger.request(req['id'])['state'], 'answered')

    def test_cached_pull_refreshes_answer_and_revision_but_keeps_ack_envelope(self):
        self.start()
        req = self.ask(True)
        first = notifications.pull(self.ledger, 'late')
        self.assertEqual([n['status'] for n in first['notifications']], ['blocker'])
        newer = question(True)
        newer['options'][0]['label'] = 'Only allow narrowed output'
        current = self.ledger.revise_request(req['id'], req['revision'], newer)
        refreshed = notifications.pull(self.ledger, 'late')
        self.assertEqual(refreshed['id'], first['id'])
        self.assertEqual(refreshed['through'], first['through'])
        self.assertEqual(refreshed['notifications'], [])  # old revision superseded, new event beyond old cursor
        notifications.ack(self.ledger, 'late', first['id'])
        second = notifications.pull(self.ledger, 'late')
        self.assertEqual(len(second['notifications']), 1)
        self.assertEqual(second['notifications'][0]['target']['revision'], current['revision'])
        self.ledger.reply(req['id'], current['revision'], 'no')
        before = self.events()
        answered = notifications.pull(self.ledger, 'late')
        self.assertEqual(answered['id'], second['id'])
        self.assertEqual(answered['through'], second['through'])
        self.assertTrue(answered['notifications'][0]['resolved'])
        self.assertIsNone(answered['notifications'][0]['user_action'])
        notifications.ack(self.ledger, 'late', second['id'])
        self.assertEqual(self.events(), before)
        self.assertEqual(notifications.pull(self.ledger, 'late')['notifications'], [])

    def test_shared_store_binds_projection_and_refuses_cross_projection_cursor_loss(self):
        from onecrew import desktop_core, notification_core
        from onecrew.v2 import notification_cli
        self.propose()
        first = notifications.pull(self.ledger, 'shared-plan-consumer')
        with self.assertRaisesRegex(LedgerError, 'dedicated consumer'):
            notification_cli.pull(self.ledger, 'shared-plan-consumer')
        with self.assertRaisesRegex(LedgerError, 'dedicated consumer'):
            notification_cli.ack(self.ledger, 'shared-plan-consumer', first['id'])
        self.assertEqual(notifications.location(self.ledger, 'shared-plan-consumer', False),
                         notification_core.location(self.ledger, 'shared-plan-consumer', False))
        path = notifications.location(self.ledger, 'shared-plan-consumer', False)
        saved = notification_core.read_state(path)
        saved.pop('projection')  # genuine historical v1 format, with a pending envelope
        path.write_text(json.dumps(saved), encoding='utf-8')
        with self.assertRaisesRegex(LedgerError, 'dedicated consumer'):
            notification_cli.pull(self.ledger, 'shared-plan-consumer')
        self.assertEqual(notifications.pull(self.ledger, 'shared-plan-consumer'), first)
        notifications.ack(self.ledger, 'shared-plan-consumer', first['id'])
        second = notification_cli.pull(self.ledger, 'dedicated-plan-consumer')
        with self.assertRaisesRegex(LedgerError, 'dedicated consumer'):
            notifications.pull(self.ledger, 'dedicated-plan-consumer')
        notification_cli.ack(self.ledger, 'dedicated-plan-consumer', second['id'])
        self.assertEqual(notification_cli.pull(self.ledger, 'dedicated-plan-consumer')['notifications'], [])
        self.assertEqual(desktop.directory(self.ledger), desktop_core.directory(self.ledger))
