"""Delivery autopilot (docs/delivery-autopilot.vi.md): envelope authority, OneCrew planning, bounded recovery,
answer-driven continuation and single notifications. Provider/Flutter/ADB are fixtures."""
import copy
import datetime as dt
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from onecrew import conversations as c
import onecrew.native_change  # noqa: F401  bind the real capture before tests patch native_audit.capture
import onecrew.node_change  # noqa: F401
from onecrew import delivery_recovery as rc
from onecrew.delivery_planner import compile_plan, covers, validate_envelope
from onecrew.ledger import Ledger, LedgerError
from onecrew.solution_delivery import Delivery, submit
from tests.test_solution_delivery import plan as entry_plan

CRITERION = 'Port 1-65535 is validated and shown inline.'


def envelope(**stages):
    value = {'version': 1, 'source_roots': ['app'], 'write': ['app/lib/', 'app/test/'],
             'acceptance': [{'id': 'AC1', 'text': CRITERION, 'evidence': ['regression', 'review']}],
             'stages': {'build': None, 'apk_audit': None, 'device': None},
             'budget': {'max_calls': 40, 'max_seconds': 3600, 'max_repairs': 2},
             'worker': {'provider': 'claude', 'model': 'sonnet'}}
    value['stages'].update(stages)
    return value


def solution(env):
    return dict(brief='Validate the port field.', detail='Settings form validates the port.', acceptance=[CRITERION],
                non_goals=[], assumptions=[], questions=[], envelope=env)


def discovery(root):
    return {'flutter_root': str(root / 'sdk'), 'android_sdk': str(root / 'android'), 'build_tools': str(root / 'bt'),
            'adb': str(root / 'adb.exe'), 'java_home': None, 'problems': [],
            'packages': [{'root': 'app', 'name': 'app', 'flutter': True, 'application_id': 'com.example.app',
                          'application_ids': {'debug': 'com.example.app.dev', 'release': 'com.example.app'},
                          'launch_activity': '.MainActivity', 'launch_activity_class': 'com.example.MainActivity',
                          'tests': ['test/test_test.dart'], 'dependency_ready': True}]}


PROPOSAL = {'package': 'app', 'changes': [{'id': 'c1', 'goal': 'Validate the port field (1-65535) and show an inline error.',
            'owned': ['app/lib/settings.dart', 'app/test/port_test.dart'], 'tests': ['app/test/port_test.dart']}],
            'regression_tests': ['test/test_test.dart'], 'red': [], 'scenario': {'steps': [], 'cleanup': []},
            'out_of_envelope': [], 'notes': 'fixture'}


class Base(unittest.TestCase):
    def setUp(self):
        from tests.test_solution_delivery import DeliveryTests
        DeliveryTests.setUp(self)

    def approve(self, env, key='autopilot'):
        cid = c.create(self.ledger, 'Autopilot contract', key, 'fixture')['id']
        sol = c.propose(self.ledger, cid, 'solution', solution(env), 'fixture')
        c.decide(self.ledger, sol['id'], sol['revision'], 'approve', 'fixture', 'Test operator approval')
        return dict(solution_id=sol['id'], solution_revision=sol['revision'])

    def planned(self, env=None):
        env = env or envelope()
        binding = self.approve(env)
        t = submit(self.ledger, 'Validate the settings port', 'planned', **binding)
        r = Delivery(self.ledger); r.enable(t['id']); return r, t['id']

    def entry(self):
        from tests.test_solution_delivery import DeliveryTests
        return DeliveryTests.create(self)

    def fast_forward(self, r, t):
        seq, s = r.state(t); s['delivery']['retry_after'] = None; r.persist(t, seq, s)


class EnvelopeTests(Base):
    def test_envelope_validated_and_bound_to_approved_text(self):
        env = validate_envelope(envelope(), solution(envelope()))
        self.assertEqual(env['write'], ['app/lib/', 'app/test/'])
        bad = envelope(); bad['acceptance'][0]['text'] = 'Something the user never approved'
        with self.assertRaisesRegex(LedgerError, 'approved solution acceptance'): validate_envelope(bad, solution(envelope()))
        with self.assertRaisesRegex(LedgerError, 'requires build'):
            validate_envelope(envelope(device={'serial': 'X', 'scenario': 'planned', 'scenario_ref': None, 'scenario_sha256': None,
                'private_reference': None, 'private_version': 'none', 'valid_until': '2026-10-13T00:00:00+00:00', 'replay_safe': False, 'required': False}))
        wide = envelope(); wide['write'] = ['other/']
        with self.assertRaisesRegex(LedgerError, 'outside envelope source roots'): validate_envelope(wide)
        with self.assertRaises(LedgerError): c.validate_solution(dict(solution(envelope()), envelope=dict(envelope(), extra=1)))

    def test_entry_plan_and_budget_must_fit_the_approved_envelope(self):
        env = envelope(); env['write'] = ['app/lib/']; env['acceptance'][0]['id'] = 'AC1'
        binding = self.approve(env)
        plan = copy.deepcopy(self.plan); plan['acceptance'][0]['text'] = CRITERION
        plan['acceptance'][0]['nodes'] = ['tests', 'review']
        submit(self.ledger, 'fits', 'fits', plan, **binding, max_calls=40, max_seconds=3600)
        with self.assertRaisesRegex(LedgerError, 'Budget exceeds'):
            submit(self.ledger, 'too big', 'big', plan, **binding, max_calls=41, max_seconds=3600)
        wider = copy.deepcopy(plan); wider['max_repairs'] = 3
        with self.assertRaisesRegex(LedgerError, 'exceeds the approved envelope'):
            submit(self.ledger, 'wider', 'wider', wider, **binding, max_calls=40, max_seconds=3600)

    def test_covers_reports_widening(self):
        env = validate_envelope(envelope(build={'variant': 'release', 'config_reference': None, 'config_version': 'v1', 'signer': 'a' * 64},
                                         apk_audit={'require_16kb': True, 'max_bytes': 1000}))
        plan, _, findings = compile_plan('goal', env, discovery(self.root), PROPOSAL, 'SOL@x', 'a' * 64)
        self.assertEqual(findings, []); self.assertEqual(covers(env, plan), [])
        widened = copy.deepcopy(plan)
        next(n for n in widened['nodes'] if n['kind'] == 'build')['config']['signer_sha256'] = 'b' * 64
        next(n for n in widened['nodes'] if n['kind'] == 'apk_audit')['config']['require_16kb'] = False
        next(n for n in widened['nodes'] if n['kind'] == 'change')['config']['recipe']['owned'].append('app/pubspec.yaml')
        found = ' '.join(covers(env, widened))
        for text in ('signer', '16KB', 'outside envelope'): self.assertIn(text, found)

    def test_planner_output_is_checked_by_code(self):
        env = validate_envelope(envelope())
        bad = copy.deepcopy(PROPOSAL); bad['changes'][0]['owned'].append('app/android/build.gradle')
        bad['regression_tests'] = ['test/port_test.dart']
        bad['red'] = [{'test': 'test/port_test.dart', 'error_pattern': '.*'}]
        _, _, findings = compile_plan('goal', env, discovery(self.root), bad, 'SOL@x')
        text = ' '.join(findings)
        for expected in ('outside the writable prefixes', 'owned by a slice', 'specific regex'): self.assertIn(expected, text)


class PlanningTests(Base):
    def run_planner(self, r, t, proposals):
        values = iter(proposals)
        def invoke(task, seq, state, stage, prompt, schema, profile):
            state['pending'] = None
            return seq, dict(next(values), _native={})
        with patch('onecrew.delivery_env.discover', return_value=discovery(self.root)), \
             patch('onecrew.delivery_env.fingerprint', return_value='env'), \
             patch('onecrew.native_audit.capture', return_value={}), patch.object(r, '_invoke', side_effect=invoke) as call:
            for _ in range(len(proposals) + 1): r.run(t)
        return call

    def test_goal_level_submit_plans_inside_envelope_and_seals(self):
        r, t = self.planned()
        self.assertIsNone(r.state(t)[1]['plan'])
        call = self.run_planner(r, t, [PROPOSAL])
        s = r.state(t)[1]
        self.assertEqual(call.call_count, 1)
        self.assertEqual([n['kind'] for n in s['plan']['nodes']], ['change', 'regression', 'review', 'handover'])
        self.assertEqual(s['delivery']['planning']['mode'], 'onecrew'); self.assertEqual(s['delivery']['planning']['stage'], 'sealed')
        with self.ledger.transaction() as conn:
            sealed = json.loads(conn.execute('SELECT plan FROM delivery_roots WHERE task_id=?', (t,)).fetchone()[0])
        self.assertEqual(sealed, s['plan'])
        self.assertEqual(s['plan']['acceptance'][0]['text'], CRITERION)
        self.assertEqual(r.control.status(t)['budget']['limits']['max_calls'], 40)

    def test_invalid_plan_gets_bounded_same_session_corrections_then_one_question(self):
        r, t = self.planned()
        bad = copy.deepcopy(PROPOSAL); bad['changes'][0]['owned'] = ['app/pubspec.yaml']
        self.run_planner(r, t, [bad, bad, bad])
        s = r.state(t)[1]
        self.assertIsNone(s['plan']); self.assertEqual(s['phase'], 'waiting')
        self.assertEqual(len(self.ledger.requests(t, pending=True)), 1)
        self.assertEqual(s['delivery']['planning']['context']['rounds'], 3)

    def test_out_of_envelope_need_asks_once_and_retry_replans_inside(self):
        r, t = self.planned()
        need = dict(PROPOSAL, out_of_envelope=[{'need': 'edit android/app/build.gradle.kts', 'reason': 'dependency constraint'}])
        self.run_planner(r, t, [need])
        request = self.ledger.requests(t, pending=True)[0]
        self.assertEqual(r.state(t)[1]['delivery']['escalation']['class'], 'permission')
        self.ledger.reply(request['id'], request['revision'], 'retry', 'test', 'user continues within the envelope')
        self.run_planner(r, t, [PROPOSAL])
        self.assertEqual(r.state(t)[1]['delivery']['planning']['stage'], 'sealed')


class RecoveryTests(Base):
    def test_transient_failure_retries_with_backoff_then_asks_once(self):
        r, t = self.entry(); r.run(t)
        with patch('onecrew.delivery_steps.execute', side_effect=LedgerError('ADB operation failed; raw output withheld.')) as op:
            s = r.run(t)
            self.assertEqual(s['phase'], 'waiting_operation'); self.assertEqual(s['waiting_reason'], 'recovery')
            self.assertEqual(r.run(t)['phase'], 'waiting_operation'); self.assertEqual(op.call_count, 1)  # backoff, no work
            for _ in range(3): self.fast_forward(r, t); s = r.run(t)
        self.assertEqual(op.call_count, 4); self.assertEqual(s['phase'], 'waiting')
        record = next(iter(s['delivery']['failures'].values()))
        self.assertEqual(record['class'], 'transient'); self.assertEqual(record['count'], 4)
        self.assertEqual(len(self.ledger.requests(t, pending=True)), 1)
        self.assertEqual(s['delivery']['nodes']['tests']['phase'], 'blocked')

    def test_failure_history_survives_coordinator_restart(self):
        r, t = self.entry(); r.run(t)
        with patch('onecrew.delivery_steps.execute', side_effect=LedgerError('ADB operation failed.')):
            r.run(t); self.fast_forward(r, t)
            fresh = Delivery(Ledger(self.root, self.ledger.state_root)); fresh.run(t)
        record = next(iter(fresh.state(t)[1]['delivery']['failures'].values()))
        self.assertEqual(record['count'], 2)

    def test_answer_retry_continues_without_entry_resume_and_stop_cancels(self):
        r, t = self.entry(); r.run(t)
        with patch('onecrew.delivery_steps.execute', return_value={'passed': False, 'detail': 'Required test skipped'}): r.run(t)
        request = self.ledger.requests(t, pending=True)[0]
        with patch('onecrew.delivery_steps.execute') as op: self.assertEqual(r.run(t)['phase'], 'waiting'); op.assert_not_called()
        self.ledger.reply(request['id'], request['revision'], 'retry', 'test', 'fixed the suite')
        source = r.state(t)[1]['delivery']['source']['hash']
        with patch('onecrew.delivery_steps.execute', return_value={'passed': True, 'source': source, 'counts': {'passed': 1, 'skipped': 0}}):
            s = r.run(t); self.assertEqual(s['phase'], 'running'); s = r.run(t)
        self.assertEqual(s['delivery']['nodes']['tests']['phase'], 'passed')
        self.assertIn(request['id'], [x['request_id'] for x in s['consumed_replies']])
        r2, t2 = self.planned()
        r2.coordinator_lost(t2, 'runner died 3 times')
        req = self.ledger.requests(t2, pending=True)[0]
        self.ledger.reply(req['id'], req['revision'], 'stop', 'test', 'stop')
        self.assertEqual(r2.run(t2)['phase'], 'cancelled')

    def test_repeated_product_failure_without_progress_stops_repairing(self):
        d = {'nodes': {'tests': {'phase': 'blocked'}}, 'generation': 1, 'source': {'hash': 'same'}}
        first, _ = rc.decide(d, 'tests', 'product', {'failing': ['a']}, 'a failed')
        second, _ = rc.decide(d, 'tests', 'product', {'failing': ['a']}, 'a failed')
        self.assertEqual((first, second), ('repair', 'ask'))
        d['source']['hash'] = 'changed'; d['generation'] = 2
        third, record = rc.decide(rc.migrate({'nodes': {}, 'generation': 1, 'source': {'hash': 'x'}}), 'tests', 'product', {'failing': ['b']}, 'b')
        self.assertEqual(third, 'repair')

    def test_device_interruption_reconciles_read_only(self):
        from onecrew import delivery_android as da
        node = {'id': 'device', 'kind': 'device', 'config': {'adb': 'adb', 'serial': 'S', 'package_id': 'com.example.app',
                'build_node': 'build', 'replay_safe': False}}
        row = {'generation': 0}
        runtime = Delivery(self.ledger)
        with patch('onecrew.delivery_android.home', return_value=self.root):
            directory = da.device_directory(runtime, 'task', node, row); directory.mkdir(parents=True)
            self.assertIsNone(da.effects_started(runtime, 'task', node, row))
            (directory / 'intent.json').write_text(json.dumps({'task': 'task', 'operation': 'install', 'apk': 'x'}))
            with patch('onecrew.delivery_android.apk_input', side_effect=LedgerError('no build')):
                self.assertTrue(da.reconcile(runtime, 'task', {}, node, row)['replay'])
                (directory / 'intent.json').write_text(json.dumps({'task': 'task', 'step': 'save', 'state': 'intent'}))
                out = da.reconcile(runtime, 'task', {}, node, row)
                self.assertFalse(out['replay']); self.assertIn('not declared replay-safe', out['detail'])
                node['config']['replay_safe'] = True
                self.assertTrue(da.reconcile(runtime, 'task', {}, node, row)['replay'])

    def test_review_killed_during_model_call_drops_only_a_settled_attempt(self):
        r, t = self.entry(); r.run(t)
        source = r.state(t)[1]['delivery']['source']['hash']
        with patch('onecrew.delivery_steps.execute', return_value={'passed': True, 'source': source, 'counts': {'passed': 1, 'skipped': 0}}): r.run(t)
        c_ = r.control.status(t)
        attempt = r.control.reserve(t, c_['revision'], 'review-call', {'stage': 'delivery_review_review'})
        seq, s = r.state(t)
        s['pending'] = attempt['id']; s['delivery']['nodes']['review'].update(phase='running', review_context={'session': 'old'})
        r.persist(t, seq, s)
        with patch('onecrew.supervisor.Supervisor.reconcile', return_value={'status': 'alive'}), patch('onecrew.delivery_steps.execute') as op:
            s = r.run(t); op.assert_not_called()
        self.assertEqual(s['pending'], attempt['id'])  # unsettled: never duplicated
        r.control.finish(attempt['id'], attempt['generation'], {'reason': 'supervisor_interrupted'})
        self.fast_forward(r, t)
        seq, s = r.state(t); s['delivery']['nodes']['review']['phase'] = 'running'; r.persist(t, seq, s)
        with patch('onecrew.delivery_steps.execute') as op: s = r.run(t); op.assert_not_called()
        self.assertIsNone(s['pending']); self.assertNotIn('review_context', s['delivery']['nodes']['review'])
        self.assertEqual(s['delivery']['nodes']['review']['phase'], 'pending')

    def test_classification_prefers_structured_fields(self):
        self.assertEqual(rc.classify_error(LedgerError('Pinned Android device unavailable at preflight.')), 'environment')
        self.assertEqual(rc.classify_error(LedgerError('Source drift after review/change.')), 'drift')
        self.assertEqual(rc.classify_error(LedgerError('Root deadline exhausted.')), 'budget')
        self.assertEqual(rc.classify_error(LedgerError('Something new')), 'unknown')
        self.assertEqual(rc.classify_receipt({'kind': 'regression'}, {'failure_kind': 'test', 'errors': [{'name': 't1', 'error': 'x'}]})[0], 'product')
        self.assertEqual(rc.classify_receipt({'kind': 'review'}, {'failure_kind': 'review', 'verdict': {'verdict': 'blocked'}})[0], 'decision_needed')
        self.assertEqual(rc.build_class('lib/a.dart:3:5: Error: Undefined name'), 'product')
        self.assertEqual(rc.build_class('The Gradle daemon has terminated unexpectedly'), 'transient')
        self.assertEqual(rc.build_class('SDK location not found'), 'environment')
        self.assertEqual(rc.signature('n', 'c', {'a': 1}), rc.signature('n', 'c', {'a': 1}))
        self.assertEqual(rc.normalize('Failed at D:\\ocd\\abc\\x.dart line 12 TASK-0123456789abcdef'),
                         rc.normalize('Failed at D:\\ocd\\zzz\\y.dart line 99 TASK-fedcba9876543210'))


class NotificationTests(Base):
    def test_automatic_recovery_is_silent_and_escalation_shows_once(self):
        from onecrew.desktop_notifications import snapshots
        r, t = self.entry(); r.run(t)
        with patch('onecrew.delivery_steps.execute', side_effect=LedgerError('ADB operation failed.')):
            r.run(t)
            self.assertEqual(snapshots(self.ledger, task=t), [])
            for _ in range(3): self.fast_forward(r, t); r.run(t)
            first = snapshots(self.ledger, task=t)
            r.run(t); r.run(t)
            self.assertEqual([x['id'] for x in snapshots(self.ledger, task=t)], [x['id'] for x in first])
        self.assertEqual(len(first), 1); self.assertEqual(len(first[0]['questions']), 1)


class OptionalDeviceTests(Base):
    def test_unavailable_optional_device_is_reported_not_run(self):
        r, t = self.entry(); r.run(t)
        seq, s = r.state(t)
        node = {'id': 'device', 'kind': 'device', 'depends': ['review'], 'config': {'optional': True}}
        s['plan']['nodes'].insert(2, node); s['plan']['nodes'][-1]['depends'].append('device')
        s['plan']['acceptance'].append({'id': 'AC2', 'text': 'Device', 'nodes': ['device']})
        s['delivery']['nodes']['device'] = {'phase': 'pending', 'generation': 0, 'receipt': None, 'child': None}
        s['delivery']['criteria']['AC2'] = 'pending'; r.persist(t, seq, s)
        source = s['delivery']['source']['hash']
        from onecrew.delivery_steps import execute as real
        def execute(runtime, task, state, n, row):
            if n['kind'] == 'device': raise LedgerError('Authorized device not ready.')
            if n['kind'] == 'handover': return real(runtime, task, state, n, row)
            return {'passed': True, 'source': source, 'counts': {'passed': 1, 'skipped': 0}, 'red': [{'test': 'x'}]}
        with patch('onecrew.delivery_steps.execute', side_effect=execute):
            for _ in range(12):
                s = r.run(t)
                if s['phase'] == 'waiting_operation': self.fast_forward(r, t)
                if s['phase'] in ('completed', 'waiting'): break
        self.assertEqual(s['phase'], 'completed'); self.assertEqual(s['verification'], 'partial')
        self.assertEqual(s['delivery']['criteria'], {'AC1': 'passed', 'AC2': 'not_run'})
        report = json.loads(Path(s['report_file']).read_text(encoding='utf-8'))
        self.assertTrue(any('device' in g for g in report['gaps']))
        self.assertEqual({e['id']: e['status'] for e in report['acceptance_evidence']}, {'AC1': 'passed', 'AC2': 'not_run'})


if __name__ == '__main__': unittest.main()
