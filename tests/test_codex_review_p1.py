"""Codex review P1 findings on the autopilot (2026-10-12), reproduced through APIs that exist before the fix:

1. A root whose deadline passed never applied an answered 'stop' (runner exited first).
2. The scorecard called a partial delivery (verification partial, criteria not_run, device skipped) autonomous_complete.
3. Device valid_until was checked once at the start; install/start/cleanup still ran after it expired."""
import datetime as dt
import json
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from onecrew import delivery_android as da
from onecrew import eval_scorecard as sc
from onecrew import runner
from onecrew.delivery_steps import file_hash
from tests import test_delivery_android as android
from tests import test_solution_delivery as base


class DeadlineAnswerTests(unittest.TestCase):
    setUp = base.DeliveryTests.setUp
    create = base.DeliveryTests.create

    def expired(self):
        r, t = self.create(max_seconds=1)
        time.sleep(1.2)
        r.deadline_exhausted(t)
        pending = self.ledger.requests(t, pending=True)
        self.assertEqual(len(pending), 1)
        return r, t, pending[0]

    def test_stop_answered_after_the_deadline_cancels_the_root(self):
        r, t, request = self.expired()
        self.ledger.reply(request['id'], request['revision'], 'stop', 'test', 'user stops at the budget question')
        outcome = runner.loop(self.ledger, t, interval=.01)
        s = r.state(t)[1]
        self.assertEqual(s['phase'], 'cancelled', 'RED-DEADLINE-STOP: the stop answer was not applied')
        self.assertTrue(r.control.status(t)['cancel_requested'])
        self.assertEqual(outcome, 'cancelled')
        self.assertEqual([x['request_id'] for x in s['consumed_replies']], [request['id']])

    def test_retry_answered_without_an_extension_asks_a_new_budget_question(self):
        r, t, request = self.expired()
        self.ledger.reply(request['id'], request['revision'], 'retry', 'test', 'retry without extension')
        runner.loop(self.ledger, t, interval=.01)
        s = r.state(t)[1]
        pending = self.ledger.requests(t, pending=True)
        self.assertEqual(len(pending), 1, 'RED-DEADLINE-RETRY: no new budget question after a consumed retry')
        self.assertNotEqual(pending[0]['id'], request['id'])
        self.assertEqual(s['delivery']['escalation']['class'], 'budget')
        self.assertEqual([x['request_id'] for x in s['consumed_replies']], [request['id']])

    def test_retry_after_a_user_extension_continues_to_completion(self):
        from onecrew.budget import extend
        r, t, request = self.expired()
        c = r.control.status(t)
        end = (dt.datetime.now(dt.timezone.utc) + dt.timedelta(hours=1)).isoformat()
        extend(r.control, t, c['budget']['revision'], 'user-extension', c['budget']['limits']['max_calls'], end, 'user extends the deadline')
        self.ledger.reply(request['id'], request['revision'], 'retry', 'test', 'extended; continue')
        real = __import__('onecrew.delivery_steps', fromlist=['execute']).execute
        def execute(runtime, task, state, node, row):
            if node['kind'] == 'handover': return real(runtime, task, state, node, row)
            return {'passed': True, 'source': state['delivery']['source']['hash'], 'counts': {'passed': 1, 'skipped': 0}, 'red': [{'test': 'x'}]}
        with patch('onecrew.delivery_steps.execute', side_effect=execute):
            outcome = runner.loop(self.ledger, t, interval=.01)
        self.assertEqual(outcome, 'completed', 'RED-DEADLINE-EXTEND: retry after an extension did not continue')
        self.assertEqual(r.state(t)[1]['phase'], 'completed')


def observed(**changes):
    metrics = {'interventions': [], 'coordinator_restarts_by_initiator': {}, 'child_starts_by_initiator': {'onecrew': 1},
               'plan_provenance': 'onecrew', 'runtime_revisions': 1, 'pending_escalations': None, 'failure_classes': {},
               'automatic_recoveries': 1, 'escalations': 0, 'decisions_answered': 0, 'coordinator_restarts': 0}
    task = {'task': 'TASK-fixture', 'phase': 'completed', 'verification': 'partial', 'metrics': metrics, 'assistance': 'unknown',
            'assistance_kinds': [], 'recorded_interventions': [], 'gates': {'device': 'not_run'}, 'gaps': ['device'],
            'pending_requests': [],
            'delivery': {'technical_verified': False, 'criteria': {'AC1': 'passed', 'AC2': 'not_run'},
                         'nodes': {'tests': {'kind': 'regression', 'phase': 'passed', 'skipped': False},
                                   'device': {'kind': 'device', 'phase': 'passed', 'skipped': True}}}}
    task.update(changes)
    return task


class ScorecardLevelTests(unittest.TestCase):
    def test_partial_delivery_is_never_autonomous_complete(self):
        kind, _ = sc.outcome(observed())
        self.assertNotEqual(kind, 'autonomous_complete', 'RED-SCORECARD-PARTIAL: partial delivery scored autonomous_complete')
        row = sc.completion(observed())
        self.assertEqual(row['completion_level'], 'partial')
        self.assertEqual(row['assistance_level'], 'autonomous')  # assistance is judged separately from completion
        self.assertIn('criteria_not_run', row['completion_gaps'])

    def test_full_verified_delivery_without_help_is_autonomous_complete(self):
        full = observed(verification='passed', gaps=[], gates={'device': 'passed'},
                        delivery={'technical_verified': True, 'criteria': {'AC1': 'passed', 'AC2': 'passed'},
                                  'nodes': {'tests': {'kind': 'regression', 'phase': 'passed', 'skipped': False},
                                            'device': {'kind': 'device', 'phase': 'passed', 'skipped': False}}})
        self.assertEqual(sc.outcome(full)[0], 'autonomous_complete')
        helped = dict(full, metrics=dict(full['metrics'], interventions=[{'actor': 'claude', 'channel': 'cli', 'command': 'work.resume'}]))
        self.assertEqual(sc.outcome(helped)[0], 'assisted_complete')
        self.assertEqual(sc.completion(helped)['completion_level'], 'complete')

    def test_partial_and_assisted_are_reported_on_both_levels(self):
        helped = observed(metrics=dict(observed()['metrics'], runtime_revisions=2))
        row = sc.completion(helped)
        self.assertEqual((row['completion_level'], row['assistance_level']), ('partial', 'assisted'))
        self.assertIn('runtime_changed', row['assistance_reasons'])


class DecisionActorTests(unittest.TestCase):
    def test_delegated_replies_are_attributed_to_the_entry_actor(self):
        task = observed(metrics=dict(observed()['metrics'], decisions_answered=2, interventions=[
            {'actor': 'claude', 'channel': 'cli', 'command': 'request.reply'}, {'actor': 'user', 'channel': 'cli', 'command': 'request.reply'}]))
        row = sc.dependencies(task)
        self.assertEqual(row['decision_replies_by_actor'], {'claude': 1, 'user': 1})
        self.assertEqual(row['entry_interventions'], 0)


class Clock(dt.datetime):
    current = None

    @classmethod
    def now(cls, tz=None):
        return cls.current


class DevicePermissionWindowTests(unittest.TestCase):
    setUp = android.AndroidDeliveryTests.setUp
    response = android.AndroidDeliveryTests.response

    def run_with_window(self, steps, expire_after):
        """Permission expires right after the first adb command whose argv starts with expire_after."""
        value = json.loads(self.scenario.read_text()); value['steps'] = steps
        self.scenario.write_text(json.dumps(value)); self.node['config']['scenario_sha256'] = file_hash(self.scenario)
        start = dt.datetime(2026, 10, 12, 8, 0, tzinfo=dt.timezone.utc)
        Clock.current = Clock.fromisoformat(start.isoformat())
        self.node['config']['valid_until'] = (start + dt.timedelta(seconds=30)).isoformat()
        fake = SimpleNamespace(datetime=Clock, timezone=dt.timezone, timedelta=dt.timedelta)
        sent = []
        def response(runtime, task, argv, cwd, seconds):
            args = argv[3:]; sent.append(args)
            if args == ['shell', 'dumpsys', 'window']:
                return 0, 'Display: mDisplayId=0\n  mCurrentFocus=Window{1 u0 example.app/example.app.MainActivity}\n  mTopFocusedDisplayId=0\n', ''
            if args[0] == 'exec-out':
                return 0, '<?xml version="1.0"?><hierarchy><node text="READY" package="example.app" class="android.widget.TextView" enabled="true" bounds="[0,0][100,100]"/></hierarchy>', ''
            result = self.response(runtime, task, argv, cwd, seconds)
            if args[:len(expire_after)] == expire_after: Clock.current = Clock.current + dt.timedelta(seconds=60)
            return result
        with patch('onecrew.delivery_android.bounded', side_effect=response), patch('onecrew.delivery_android.dt', fake):
            receipt = da.device(self.runtime, 'task', self.state, self.node, {'generation': 0})
        return receipt, sent

    def test_no_device_command_after_the_window_expires_during_install(self):
        receipt, sent = self.run_with_window([{'id': 'ready', 'operation': 'assert_ui', 'arguments': {'selector': {'text': 'READY'}}}], ['install'])
        after = sent[[i for i, a in enumerate(sent) if a[0] == 'install'][0] + 1:]
        self.assertEqual(after, [], 'RED-DEVICE-WINDOW: commands ran after the device permission expired: ' + str(after)[:200])
        self.assertFalse(receipt['passed']); self.assertIn('expired', receipt['detail'])
        self.assertFalse(receipt.get('uncertain'))  # only the idempotent install ran; no scenario step

    def test_expiry_after_a_scenario_step_stops_without_cleanup_and_reports_uncertain(self):
        steps = [{'id': 'tap', 'operation': 'tap', 'arguments': {'selector': {'text': 'READY'}}},
                 {'id': 'ready', 'operation': 'assert_ui', 'arguments': {'selector': {'text': 'READY'}}}]
        receipt, sent = self.run_with_window(steps, ['shell', 'input', 'tap'])
        tap = [i for i, a in enumerate(sent) if a[:3] == ['shell', 'input', 'tap']][0]
        self.assertEqual(sent[tap + 1:], [], 'RED-DEVICE-WINDOW: cleanup or steps ran after the permission expired')
        self.assertFalse(receipt['passed']); self.assertTrue(receipt['uncertain'])
        self.assertEqual(receipt['cleanup'][0]['passed'], False)


class PermissionWindowPathTests(unittest.TestCase):
    """Every other device path honours the same window (no probe, no preflight command, no replay)."""
    setUp = android.AndroidDeliveryTests.setUp

    def test_reconcile_after_expiry_sends_nothing_and_never_replays(self):
        from onecrew.delivery_android import reconcile
        node = {'id': 'device', 'kind': 'device', 'config': dict(self.node['config'], valid_until='2020-01-01T00:00:00+00:00', replay_safe=True)}
        with patch('onecrew.delivery_android.bounded') as adb, patch('onecrew.delivery_android.effects_started', return_value={'step': 'tap'}):
            out = reconcile(self.runtime, 'task', self.state, node, {'generation': 0})
        adb.assert_not_called(); self.assertFalse(out['replay']); self.assertTrue(out['permission_expired'])

    def test_preflight_skips_an_expired_optional_device_and_stops_a_required_one(self):
        from onecrew.delivery_steps import preflight, fingerprint
        from onecrew.ledger import LedgerError
        base.DeliveryTests.setUp(self)
        node = {'id': 'device', 'kind': 'device', 'depends': [], 'config': {'adb': str(self.root / 'adb.exe'), 'serial': 'S',
                'scenario': str(self.scenario), 'scenario_sha256': file_hash(self.scenario), 'private_reference': None,
                'valid_until': '2020-01-01T00:00:00+00:00', 'optional': True}}
        (self.root / 'adb.exe').write_text('fixture')
        state = {'plan': {'nodes': [node], 'source_roots': ['app']}}
        runtime = SimpleNamespace(ledger=self.ledger)
        with patch('onecrew.delivery_steps.bounded') as adb, patch('onecrew.delivery_steps.home', return_value=self.root):
            receipt = preflight(runtime, 'task', state, fingerprint(self.root, ['app']))
            adb.assert_not_called(); self.assertTrue(receipt['optional_device_missing'])
            node['config']['optional'] = False
            with self.assertRaisesRegex(LedgerError, 'permission expired'): preflight(runtime, 'task', state, fingerprint(self.root, ['app']))
            adb.assert_not_called()


class PermissionWindowDeliveryTests(unittest.TestCase):
    setUp = base.DeliveryTests.setUp
    create = base.DeliveryTests.create

    def with_device(self, optional, receipt):
        r, t = self.create(); r.run(t)
        seq, s = r.state(t)
        s['plan']['nodes'].insert(2, {'id': 'device', 'kind': 'device', 'depends': ['review'], 'config': {'optional': optional}})
        s['plan']['nodes'][-1]['depends'].append('device')
        s['plan']['acceptance'].append({'id': 'AC2', 'text': 'Device', 'nodes': ['device']})
        s['delivery']['nodes']['device'] = {'phase': 'pending', 'generation': 0, 'receipt': None, 'child': None}
        s['delivery']['criteria']['AC2'] = 'pending'; r.persist(t, seq, s)
        source = s['delivery']['source']['hash']
        real = __import__('onecrew.delivery_steps', fromlist=['execute']).execute
        def execute(runtime, task, state, n, row):
            if n['kind'] == 'device': return dict(receipt, source=source)
            if n['kind'] == 'handover': return real(runtime, task, state, n, row)
            return {'passed': True, 'source': source, 'counts': {'passed': 1, 'skipped': 0}, 'red': [{'test': 'x'}]}
        with patch('onecrew.delivery_steps.execute', side_effect=execute), \
             patch('onecrew.delivery_android.reconcile', return_value={'replay': False, 'permission_expired': True,
                                                                     'detail': 'Device permission expired; device state not probed and nothing replayed.'}):
            for _ in range(10):
                s = r.run(t)
                if s['phase'] in ('completed', 'waiting'): break
        return r, t, s

    expired = {'passed': False, 'failure_kind': 'device', 'permission_expired': True,
               'detail': 'Device permission expired (valid_until); no further device command sent.', 'steps': [], 'cleanup': []}

    def test_optional_device_expired_before_the_scenario_is_not_run(self):
        _, _, s = self.with_device(True, self.expired)
        self.assertEqual(s['phase'], 'completed'); self.assertEqual(s['verification'], 'partial')
        self.assertEqual(s['delivery']['criteria']['AC2'], 'not_run')

    def test_required_device_expired_asks_for_a_new_window(self):
        _, t, s = self.with_device(False, self.expired)
        self.assertEqual(s['phase'], 'waiting'); self.assertEqual(s['delivery']['escalation']['class'], 'permission')

    def test_expiry_after_scenario_steps_asks_and_never_replays(self):
        receipt = dict(self.expired, steps=[{'id': 'tap'}], scenario_started=True, uncertain=True)
        _, t, s = self.with_device(True, receipt)
        self.assertEqual(s['phase'], 'waiting'); self.assertEqual(s['delivery']['escalation']['class'], 'side_effect_unknown')
        self.assertNotEqual(s['delivery']['criteria']['AC2'], 'not_run')
        self.assertFalse(any(x.get('action') == 'reconcile' for x in s['delivery']['recoveries']))


if __name__ == '__main__': unittest.main()
