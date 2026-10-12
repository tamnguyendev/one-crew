"""Regressions for the adversarial review of the delivery autopilot core (2026-10-12, findings C1-C30)."""
import copy
import json
import unittest
from unittest.mock import patch

import onecrew.native_change  # noqa: F401  bind the real capture before tests patch native_audit.capture
import onecrew.node_change  # noqa: F401
from onecrew import delivery_recovery as rc
from onecrew.control import CapacityWait
from onecrew.delivery_planner import compile_plan, covers, validate_envelope
from onecrew.ledger import LedgerError
from onecrew.owned import Owned
from tests import test_delivery_autopilot as ap
from tests import test_solution_delivery as base

EXECUTE = 'onecrew.delivery_steps.execute'


class EscalationEpisodeTests(unittest.TestCase):
    setUp = base.DeliveryTests.setUp
    create = base.DeliveryTests.create

    def forward(self, r, t):
        seq, s = r.state(t); s['delivery']['retry_after'] = None; r.persist(t, seq, s)

    def test_answered_request_is_never_reused_for_the_next_episode(self):  # C1/C6/C16/C25
        r, t = self.create(); r.run(t)
        with patch(EXECUTE, return_value={'passed': False, 'detail': 'Required test skipped'}) as op:
            r.run(t)
            first = self.ledger.requests(t, pending=True)[0]
            self.ledger.reply(first['id'], first['revision'], 'retry', 'test', 'one retry')
            for _ in range(8): r.run(t)
        self.assertEqual(op.call_count, 2)
        pending = self.ledger.requests(t, pending=True)
        self.assertEqual(len(pending), 1); self.assertNotEqual(pending[0]['id'], first['id'])
        replies = [c['reply_id'] for c in r.state(t)[1]['consumed_replies']]
        self.assertEqual(len(replies), len(set(replies)), 'a reply was applied twice')
        record = next(iter(r.state(t)[1]['delivery']['failures'].values()))
        self.assertEqual(record['allowance'], 1)

    def test_changed_question_text_after_retry_never_crashes_run(self):  # C2/C7/C26
        r, t = self.create(); r.run(t)
        with patch(EXECUTE, side_effect=LedgerError('ADB operation failed.')):
            r.run(t)
            for _ in range(3): self.forward(r, t); r.run(t)
            first = self.ledger.requests(t, pending=True)[0]
            self.ledger.reply(first['id'], first['revision'], 'retry', 'test', 'cable fixed')
            for _ in range(4): self.forward(r, t); s = r.run(t)
        self.assertEqual(s['phase'], 'waiting')
        pending = self.ledger.requests(t, pending=True)
        self.assertEqual(len(pending), 1); self.assertNotEqual(pending[0]['id'], first['id'])
        self.assertEqual(s['delivery']['escalation']['class'], 'transient')

    def test_user_cancel_during_a_node_asks_nothing(self):  # C27
        r, t = self.create(); r.run(t)
        def cancel(*args):
            r.control.cancel(t); raise LedgerError('Container gate stopped by root cancel/pause/deadline.')
        with patch(EXECUTE, side_effect=cancel): s = r.run(t)
        self.assertEqual(s['phase'], 'cancelled'); self.assertEqual(self.ledger.requests(t, pending=True), [])

    def test_pause_during_a_node_is_not_a_failure(self):  # C27
        r, t = self.create(); r.run(t)
        def pause(*args):
            r.control.pause(t); raise LedgerError('Container gate stopped by root cancel/pause/deadline.')
        with patch(EXECUTE, side_effect=pause): s = r.run(t)
        self.assertEqual(self.ledger.requests(t, pending=True), [])
        self.assertEqual(s['delivery']['failures'], {}); self.assertEqual(s['delivery']['nodes']['tests']['phase'], 'pending')

    def test_capacity_wait_is_not_an_interruption(self):  # C12
        r, t = self.create(); r.run(t)
        source = r.state(t)[1]['delivery']['source']['hash']
        with patch(EXECUTE, return_value={'passed': True, 'source': source, 'counts': {'passed': 1, 'skipped': 0}}): r.run(t)
        with patch(EXECUTE, side_effect=CapacityWait('Global worker capacity exhausted.')):
            for _ in range(4): self.forward(r, t); s = r.run(t)
        self.assertEqual(s['waiting_reason'], 'capacity'); self.assertEqual(s['delivery']['recoveries'], [])
        self.assertNotEqual(s['delivery']['nodes']['review']['phase'], 'running')
        self.assertEqual(self.ledger.requests(t, pending=True), [])

    def test_resume_accepts_an_uncertain_row_for_reconcile(self):  # C15
        r, t = self.create(); r.run(t)
        seq, s = r.state(t); s['delivery']['nodes']['tests']['phase'] = 'uncertain'; s['phase'] = 'blocked'; r.persist(t, seq, s)
        self.assertEqual(r.resume(t)['delivery']['nodes']['tests']['phase'], 'uncertain')

    def test_unsettled_attempt_keeps_the_row_running_until_it_settles(self):  # C14
        r, t = self.create(); r.run(t)
        source = r.state(t)[1]['delivery']['source']['hash']
        with patch(EXECUTE, return_value={'passed': True, 'source': source, 'counts': {'passed': 1, 'skipped': 0}}): r.run(t)
        c = r.control.status(t); attempt = r.control.reserve(t, c['revision'], 'review', {'stage': 'delivery_review_review'})
        seq, s = r.state(t); s['pending'] = attempt['id']; s['delivery']['nodes']['review']['phase'] = 'running'; r.persist(t, seq, s)
        with patch('onecrew.supervisor.Supervisor.reconcile', return_value={'status': 'alive'}), patch(EXECUTE) as op:
            for _ in range(3): self.forward(r, t); s = r.run(t)
            op.assert_not_called()
        self.assertEqual(s['delivery']['nodes']['review']['phase'], 'running'); self.assertEqual(self.ledger.requests(t, pending=True), [])
        r.control.finish(attempt['id'], attempt['generation'], {'reason': 'supervisor_interrupted'})
        self.forward(r, t)
        with patch(EXECUTE) as op: s = r.run(t); op.assert_not_called()
        self.assertIsNone(s['pending']); self.assertEqual(s['delivery']['nodes']['review']['phase'], 'pending')


class ChildQuestionTests(unittest.TestCase):
    setUp = base.DeliveryTests.setUp
    create = base.DeliveryTests.create
    change_plan = base.DeliveryTests.change_plan
    child = base.DeliveryTests.child

    def stopped_child(self, **state):
        self.change_plan(); r, t = self.create(max_calls=3); r.run(t)
        cr, child = self.child(r, t)
        seq, cs = cr.state(child); cs.update(state); cr.persist(child, seq, cs)
        seq, s = r.state(t); s['delivery']['nodes']['fix'].update(child=child, phase='running'); r.persist(t, seq, s)
        return r, t, cr, child

    def test_child_waiting_on_an_answered_solution_question_is_continued(self):  # C9/C10/C29
        r, t, cr, child = self.stopped_child(phase='blocked', waiting_reason='solution', message='Required solution decision: CREQ-1')
        with patch('onecrew.runner.status', return_value={'status': 'alive'}), patch('onecrew.runner.start') as start:
            s = r.run(t)
        self.assertEqual(self.ledger.requests(t, pending=True), [])
        self.assertEqual(s['delivery']['failures'], {})
        self.assertNotEqual(cr.state(child)[1]['phase'], 'blocked')

    def test_child_fenced_by_the_root_is_resumed_not_regenerated(self):  # C11
        r, t, cr, child = self.stopped_child(phase='blocked', message='Delivery root has a pending question.',
                                             recovery={'kind': 'native_change', 'automatic_retry': False})
        with patch('onecrew.runner.status', return_value={'status': 'alive'}), patch('onecrew.runner.start'):
            s = r.run(t)
        self.assertEqual(s['delivery']['repairs'], 0); self.assertEqual(s['delivery']['nodes']['fix']['child'], child)
        self.assertFalse(any('regenerate' in h for h in s['delivery']['history']))
        self.assertEqual(self.ledger.requests(t, pending=True), [])


    def test_regeneration_retires_the_superseded_child_so_intake_accepts_the_new_one(self):  # autonomy trial 2026-10-12
        r, t, cr, child = self.stopped_child(phase='blocked', message='Native change repair limit reached; evidence preserved.')
        real_enable = Owned.enable
        def enable(runtime, task):  # the new generation's worker needs no provider CLI in this fixture
            return {'phase': 'running'} if task != child else real_enable(runtime, task)
        with patch('onecrew.runner.status', return_value={'status': 'alive'}), patch('onecrew.runner.start'),              patch.object(Owned, 'enable', enable):
            s = r.run(t)
            self.assertEqual(s['delivery']['recoveries'][-1]['action'], 'regenerate')
            self.forward = lambda *a: None
            seq, x = r.state(t); x['delivery']['retry_after'] = None; r.persist(t, seq, x)
            s = r.run(t)
        self.assertEqual(cr.state(child)[1]['phase'], 'cancelled')
        new = s['delivery']['nodes']['fix']['child']
        self.assertTrue(new and new != child, s['message'])
        self.assertEqual(self.ledger.requests(t, pending=True), [])


class RegressionAttributionTests(unittest.TestCase):  # autonomy trial 2026-10-12: ink_sparkle shader without test assets
    setUp = base.DeliveryTests.setUp
    create = base.DeliveryTests.create

    def reporter(self, failing):
        events = [{'type': 'testStart', 'test': {'id': 1, 'name': 'saving shows confirmation'}}]
        if failing:
            events += [{'type': 'print', 'testID': 1, 'message': "Exception: Asset 'shaders/ink_sparkle.frag' not found"},
                       {'type': 'error', 'testID': 1, 'error': 'Test failed. See exception logs above.'}]
        events += [{'type': 'testDone', 'testID': 1, 'result': 'error' if failing else 'success', 'hidden': False, 'skipped': False},
                   {'type': 'done', 'success': not failing}]
        return '\n'.join(json.dumps(e) for e in events)

    def run_regression(self, final_fails, baseline_fails):
        from onecrew import delivery_steps as ds
        r, t = self.create(); r.run(t)
        s = r.state(t)[1]; node = s['plan']['nodes'][0]; calls = []
        def bounded(runtime, task, argv, cwd, seconds, env=None):
            calls.append((str(cwd), argv))
            on_baseline = '\\base-' in str(cwd) or '/base-' in str(cwd)
            failing = baseline_fails if on_baseline else final_fails
            return (1 if failing else 0), self.reporter(failing), ''
        with patch('onecrew.delivery_steps.bounded', side_effect=bounded):
            receipt = ds.regression(r, t, s, node, {'generation': 0})
        return receipt, calls

    def test_suite_failing_on_baseline_too_is_environment_not_product(self):
        receipt, calls = self.run_regression(True, True)
        self.assertFalse(receipt['passed']); self.assertEqual(receipt['failure_kind'], 'environment')
        self.assertIn('unchanged baseline too', receipt['detail'])
        self.assertNotIn('--no-test-assets', calls[0][1])
        self.assertEqual(rc.classify_receipt({'kind': 'regression'}, receipt)[0], 'environment')

    def test_suite_passing_on_baseline_is_a_product_regression(self):
        receipt, _ = self.run_regression(True, False)
        self.assertEqual(receipt['failure_kind'], 'test')
        self.assertEqual(rc.classify_receipt({'kind': 'regression'}, receipt)[0], 'product')


class ReviewProtocolTests(unittest.TestCase):  # autonomy trial 2 (TASK-03a6a3a9): accepted review cited a snapshot hash
    setUp = base.DeliveryTests.setUp
    create = base.DeliveryTests.create

    def reviewed(self, answers):
        from onecrew import delivery_steps as ds
        r, t = self.create(); r.run(t)
        source = r.state(t)[1]['delivery']['source']['hash']
        with patch(EXECUTE, return_value={'passed': True, 'source': source, 'counts': {'passed': 1, 'skipped': 0}, 'red': [{'test': 'x'}]}): r.run(t)
        s = r.state(t)[1]; node = next(n for n in s['plan']['nodes'] if n['kind'] == 'review'); row = s['delivery']['nodes']['review']
        values = iter(answers); results = []
        def invoke(task, seq, state, stage, prompt, schema, profile):
            refs = row['review_context']['refs']
            return seq, next(values)(sorted(refs.values()), prompt)
        with patch('onecrew.native_audit.capture', return_value={}), patch.object(r, '_invoke', side_effect=invoke):
            for _ in answers: results.append(ds.review(r, t, s, node, row))
        return results, row

    @staticmethod
    def accept(extra):
        return lambda refs, prompt: {'verdict': 'accept', 'feedback': 'ok', 'unresolved_required': [],
                                     'checks': [{'id': 'AC1', 'status': 'passed', 'evidence_refs': refs + extra}]}

    def test_accepted_review_with_a_wrong_ref_goes_back_to_the_reviewer_not_to_code_repair(self):
        results, row = self.reviewed([self.accept(['snapshot-hash']), self.accept([])])
        self.assertIsNone(results[0]); self.assertIn('only these receipt refs exist', row['review_context']['protocol_feedback'])
        self.assertTrue(results[1]['passed'])

    def test_persistent_protocol_defect_asks_instead_of_repairing(self):
        results, _ = self.reviewed([self.accept(['x'])] * 3)
        self.assertEqual(results[:2], [None, None]); self.assertFalse(results[2]['passed'])
        self.assertEqual(results[2]['failure_kind'], 'review_protocol')
        self.assertNotIn(rc.classify_receipt({'kind': 'review'}, results[2])[0], ('product', 'review'))


class Trial3DeviceTests(unittest.TestCase):  # autonomy trial 3 (TASK-e991ebeb): emulator ANR, locked stream, Flutter labels
    def test_text_selector_matches_a_flutter_content_description_label(self):
        from onecrew.delivery_android import find_ui
        xml = ('<hierarchy><node class="android.view.View" text="" content-desc="Cấu hình máy chủ" package="a.b" enabled="true" bounds="[0,0][100,50]"/>'
               '<node class="android.widget.Button" text="" content-desc="LƯU" package="a.b" enabled="true" bounds="[0,60][100,110]"/></hierarchy>')
        self.assertEqual(find_ui(xml, {'text': 'LƯU'}, 'a.b')[0].get('content-desc'), 'LƯU')
        with self.assertRaises(LedgerError): find_ui(xml.replace('text="" content-desc="LƯU"', 'text="X" content-desc="LƯU"'), {'text': 'LƯU'}, 'a.b')

    def test_system_dialog_and_locked_stream_are_environment_or_transient(self):
        self.assertEqual(rc.classify_error(LedgerError('Another window has foreground focus during a UI wait: Window{1 u0 Application Not Responding: com.android.systemui}')), 'environment')
        self.assertEqual(rc.classify_error(OSError("[WinError 32] The process cannot access the file because it is being used by another process: 'x.err'")), 'transient')

    def test_locked_raw_stream_does_not_fail_the_command(self):
        import tempfile
        from pathlib import Path
        from onecrew import delivery_steps as ds
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp)
            def command(argv, cwd, seconds, guard, env):
                (directory / 'x.out').write_text('raw'); return 0, 'ok', ''
            runtime = type('R', (), {})(); runtime.control = type('C', (), {})()
            runtime.control.status = lambda task: {'deadline': '2999-01-01T00:00:00+00:00'}
            import datetime as dt
            runtime.control.clock = lambda: dt.datetime.now(dt.timezone.utc)
            real = Path.unlink; calls = []
            def flaky(self, missing_ok=False):
                calls.append(self)
                if len(calls) == 1: raise PermissionError(32, 'being used by another process')
                return real(self, missing_ok=missing_ok)
            with patch('onecrew.delivery_steps.command', side_effect=command), patch('onecrew.delivery_steps.task_guard', return_value=lambda: None),                  patch.object(Path, 'unlink', flaky), patch('onecrew.delivery_steps.time.sleep'):
                self.assertEqual(ds.bounded(runtime, 'task', ['x'], directory, 5), (0, 'ok', ''))
            self.assertEqual(len(calls), 2)


class DeviceEffectTests(unittest.TestCase):
    def test_failure_after_scenario_steps_is_never_a_free_retry(self):  # C3/C13
        node = {'kind': 'device', 'config': {'replay_safe': False}}
        receipt = {'passed': False, 'failure_kind': 'device', 'detail': 'ADB operation failed; raw output withheld.',
                   'steps': [{'id': 'tap_save', 'passed': True}], 'scenario_started': True}
        self.assertEqual(rc.classify_receipt(node, receipt)[0], 'device_assertion')
        node['config']['replay_safe'] = True
        self.assertEqual(rc.classify_receipt(node, receipt)[0], 'transient')
        before = dict(receipt, steps=[], scenario_started=False)
        node['config']['replay_safe'] = False
        self.assertEqual(rc.classify_receipt(node, before)[0], 'transient')


class OptionalFailureTests(ap.Base):
    def test_optional_device_that_ran_and_failed_is_a_finding_not_not_run(self):  # C4
        r, t = self.entry(); r.run(t)
        seq, s = r.state(t)
        s['plan']['nodes'].insert(2, {'id': 'device', 'kind': 'device', 'depends': ['review'], 'config': {'optional': True, 'replay_safe': True}})
        s['plan']['nodes'][-1]['depends'].append('device')
        s['plan']['acceptance'].append({'id': 'AC2', 'text': 'Device', 'nodes': ['device']})
        s['delivery']['nodes']['device'] = {'phase': 'pending', 'generation': 0, 'receipt': None, 'child': None}
        s['delivery']['criteria']['AC2'] = 'pending'; r.persist(t, seq, s)
        source = s['delivery']['source']['hash']
        def execute(runtime, task, state, n, row):
            if n['kind'] == 'device':
                return {'passed': False, 'failure_kind': 'device', 'detail': 'UI wait timed out.', 'source': source,
                        'steps': [{'id': 'save'}], 'scenario_started': True}
            return {'passed': True, 'source': source, 'counts': {'passed': 1, 'skipped': 0}, 'red': [{'test': 'x'}]}
        with patch(EXECUTE, side_effect=execute):
            for _ in range(10):
                s = r.run(t)
                if s['phase'] == 'waiting_operation': self.fast_forward(r, t)
                if s['phase'] in ('completed', 'waiting'): break
        self.assertEqual(s['phase'], 'waiting'); self.assertNotEqual(s['delivery']['criteria'].get('AC2'), 'not_run')
        self.assertEqual(s['delivery']['escalation']['class'], 'device_assertion')


class PlannerFindingTests(ap.Base):
    run_planner = ap.PlanningTests.run_planner

    def test_private_reference_inside_source_roots_stops_before_capture(self):  # C5
        (self.root / 'app/e2e').mkdir(); (self.root / 'app/e2e/inputs.json').write_text('{"pin": "1234"}')
        env = ap.envelope(build={'variant': 'debug', 'config_reference': None, 'config_version': 'none', 'signer': 'debug'},
                          apk_audit={'require_16kb': False, 'max_bytes': 10 ** 9},
                          device={'serial': 'emulator-5554', 'scenario': 'planned', 'scenario_ref': None, 'scenario_sha256': None,
                                  'private_reference': str(self.root / 'app/e2e/inputs.json'), 'private_version': 'v1',
                                  'valid_until': '2099-01-01T00:00:00+00:00', 'replay_safe': False, 'required': False})
        r, t = self.planned(env)
        with patch('onecrew.delivery_env.discover', return_value=ap.discovery(self.root)), patch('onecrew.delivery_env.fingerprint', return_value='e'), \
             patch('onecrew.delivery_env.debug_signer_sha256', return_value='a' * 64), \
             patch('onecrew.native_audit.capture') as capture, patch.object(r, '_invoke') as invoke:
            for _ in range(3): r.run(t)
            capture.assert_not_called(); invoke.assert_not_called()
        request = self.ledger.requests(t, pending=True)[0]
        self.assertIn('private_reference_inside_source_roots', request['question']['reason'])

    def test_nested_package_is_an_environment_question_before_any_model_call(self):  # C23
        r, t = self.planned()
        nested = ap.discovery(self.root); nested['packages'][0]['root'] = 'app/mobile'
        with patch('onecrew.delivery_env.discover', return_value=nested), patch('onecrew.delivery_env.fingerprint', return_value='e'), \
             patch.object(r, '_invoke') as invoke:
            r.run(t); invoke.assert_not_called()
        self.assertIn('package_not_source_root', self.ledger.requests(t, pending=True)[0]['question']['reason'])

    def test_malformed_scenario_from_the_model_is_feedback_not_a_crash(self):  # C19
        env = ap.envelope(build={'variant': 'debug', 'config_reference': None, 'config_version': 'none', 'signer': 'debug'},
                          apk_audit={'require_16kb': False, 'max_bytes': 10 ** 9},
                          device={'serial': 'emulator-5554', 'scenario': 'planned', 'scenario_ref': None, 'scenario_sha256': None,
                                  'private_reference': None, 'private_version': 'none', 'valid_until': '2099-01-01T00:00:00+00:00',
                                  'replay_safe': False, 'required': False})
        r, t = self.planned(env)
        bad = copy.deepcopy(ap.PROPOSAL)
        bad['scenario'] = {'steps': [{'id': 'x', 'operation': 'type', 'arguments': {'selector': {'text': 'Port'}, 'private_key': 5}}], 'cleanup': []}
        with patch('onecrew.delivery_env.debug_signer_sha256', return_value='a' * 64):
            self.run_planner(r, t, [bad])
        s = r.state(t)[1]
        self.assertIsNone(s['plan']); self.assertTrue(s['delivery']['planning']['context']['feedback'])

    def test_out_of_envelope_question_names_the_need_and_a_new_need_asks_again(self):  # C24
        r, t = self.planned()
        first = dict(ap.PROPOSAL, out_of_envelope=[{'need': 'edit android/app/build.gradle.kts', 'reason': 'constraint'}])
        self.run_planner(r, t, [first])
        request = self.ledger.requests(t, pending=True)[0]
        self.assertIn('build.gradle.kts', request['question']['question'])
        self.assertIn('KHÔNG', [o for o in request['question']['options'] if o['id'] == 'retry'][0]['label'])
        self.assertIsNone(r.state(t)[1]['delivery']['planning'].get('stay_inside'))
        self.ledger.reply(request['id'], request['revision'], 'retry', 'test', 'continue without it')
        second = dict(ap.PROPOSAL, out_of_envelope=first['out_of_envelope'] + [{'need': 'add a dependency', 'reason': 'parser'}])
        self.run_planner(r, t, [second])
        pending = self.ledger.requests(t, pending=True)
        self.assertEqual(len(pending), 1); self.assertIn('add a dependency', pending[0]['question']['question'])

    def test_failed_planning_call_is_dropped_on_retry_and_called_again(self):  # C17
        r, t = self.planned()
        calls = []
        def invoke(task, seq, state, stage, prompt, schema, profile):
            calls.append(stage)
            if len(calls) == 1:
                c = r.control.status(task); a = r.control.reserve(task, c['revision'], 'plan-1', {'stage': stage})
                r.control.finish(a['id'], a['generation'], {'reason': 'malformed'})
                state['pending'] = a['id']
                raise LedgerError('Native audit lacks structured output.')
            state['pending'] = None
            return seq, dict(ap.PROPOSAL, _native={})
        with patch('onecrew.delivery_env.discover', return_value=ap.discovery(self.root)), patch('onecrew.delivery_env.fingerprint', return_value='e'), \
             patch('onecrew.native_audit.capture', return_value={}), patch.object(r, '_invoke', side_effect=invoke):
            for _ in range(3): r.run(t)
            request = self.ledger.requests(t, pending=True)[0]
            self.ledger.reply(request['id'], request['revision'], 'retry', 'test', 'try again')
            for _ in range(3): r.run(t)
        self.assertEqual(len(calls), 2); self.assertEqual(r.state(t)[1]['delivery']['planning']['stage'], 'sealed')


class CoversTests(unittest.TestCase):
    def test_execution_features_and_required_device_are_envelope_bound(self):  # C20/C21
        env = validate_envelope(ap.envelope())
        root = __import__('pathlib').Path('D:/x')
        plan, _, findings = compile_plan('goal', env, ap.discovery(root), ap.PROPOSAL, 'SOL@x')
        self.assertEqual(findings, [])
        wide = copy.deepcopy(plan); recipe = wide['nodes'][0]['config']['recipe']
        recipe.update(execution='workspace', restore_cache=True)
        found = ' '.join(covers(env, wide))
        self.assertIn('workspace', found); self.assertIn('cache', found)
        required = ap.envelope(build={'variant': 'debug', 'config_reference': None, 'config_version': 'none', 'signer': 'debug'},
                               apk_audit={'require_16kb': False, 'max_bytes': 10 ** 9},
                               device={'serial': 'S', 'scenario': 'planned', 'scenario_ref': None, 'scenario_sha256': None,
                                       'private_reference': None, 'private_version': 'none', 'valid_until': '2099-01-01T00:00:00+00:00',
                                       'replay_safe': False, 'required': True})
        self.assertIn('required device stage missing from plan', covers(validate_envelope(required), plan))

    def test_effective_application_id_and_launcher_class(self):  # C22
        env = validate_envelope(ap.envelope(build={'variant': 'debug', 'config_reference': None, 'config_version': 'none', 'signer': 'debug'},
                                            apk_audit={'require_16kb': False, 'max_bytes': 10 ** 9},
                                            device={'serial': 'S', 'scenario': 'planned', 'scenario_ref': None, 'scenario_sha256': None,
                                                    'private_reference': None, 'private_version': 'none',
                                                    'valid_until': '2099-01-01T00:00:00+00:00', 'replay_safe': False, 'required': False}))
        proposal = dict(ap.PROPOSAL, scenario={'steps': [{'id': 'a', 'operation': 'assert_ui', 'arguments': {'selector': {'text': 'LƯU'}}}], 'cleanup': []})
        plan, scenario, findings = compile_plan('goal', env, ap.discovery(__import__('pathlib').Path('D:/x')), proposal, 'SOL@x', 'a' * 64)
        self.assertEqual(findings, [])
        ids = {n['kind']: n['config'].get('package_id') for n in plan['nodes'] if n['kind'] in ('apk_audit', 'device')}
        self.assertEqual(ids, {'apk_audit': 'com.example.app.dev', 'device': 'com.example.app.dev'})
        self.assertEqual(scenario['activity'], 'com.example.MainActivity')


if __name__ == '__main__': unittest.main()
