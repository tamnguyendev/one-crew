"""Real-device (A54/HIS) mode: pinned exact selectors, no calibration or UI data to a model, masked evidence on a
mismatch, and every recovery action on a physical device only when the approved stage grants it."""
import json
from pathlib import Path
import unittest
from unittest.mock import patch

from onecrew import delivery_android as da
from onecrew import delivery_recovery as rc
from onecrew.delivery_device_env import EnvironmentUnusable, RECOVERY, recovery_grant, validate_recovery
from onecrew.ledger import LedgerError
from tests.test_autonomy_round2 import AC3, APP_FOCUS, DeviceRun, PKG

SERIAL = 'R5CWTESTONLY'
# The A54 scenario style: labels pinned by attribute (content-desc), values by text, an icon button by class + empty desc.
PINNED = [{'id': 'title', 'operation': 'wait_for', 'arguments': {'selector': {'content-desc': 'Cấu hình máy chủ'}, 'timeout_seconds': 10}},
          {'id': 'bad', 'operation': 'type', 'arguments': {'selector': {'class': 'android.widget.EditText', 'hint': 'Cổng'}, 'private_key': 'bad_port'}},
          {'id': 'save', 'operation': 'tap', 'arguments': {'selector': {'class': 'android.widget.Button', 'content-desc': 'LƯU'}}},
          {'id': 'error', 'operation': 'wait_for', 'arguments': {'selector': {'content-desc': 'Cổng phải từ 1 đến 65535'}, 'timeout_seconds': 5}},
          {'id': 'not-saved', 'operation': 'assert_absent', 'arguments': {'selector': {'text': 'Đã lưu'}}}]


class RealDeviceRun(DeviceRun):
    def setUp(self):
        super().setUp(); self.locked = False

    def adb(self, runtime, task, argv, cwd, seconds):
        self.assertEqual(argv[1:3], ['-s', SERIAL])
        args = argv[3:]
        if args == ['shell', 'dumpsys', 'window'] and self.locked:
            self.sent.append(args); return 0, APP_FOCUS + 'isKeyguardShowing=true\n', ''
        if args == ['shell', 'wm', 'dismiss-keyguard']: self.locked = False
        return DeviceRun.adb(self, runtime, task, argv[:2] + ['emulator-5554'] + argv[3:], cwd, seconds)

    def real(self, steps, **config):
        return self.node(steps, **dict({'serial': SERIAL, 'calibration': 'onecrew'}, **config))


class ExactSelectorTests(RealDeviceRun):
    def test_a_real_device_defaults_to_exact_selectors_and_no_recovery(self):
        self.assertEqual(da.selector_mode({'serial': SERIAL}), 'exact')
        self.assertEqual(da.selector_mode({'serial': 'emulator-5554'}), 'tiered')
        self.assertEqual(recovery_grant({'serial': SERIAL}), set())
        self.assertEqual(recovery_grant({'serial': 'emulator-5554'}), set(RECOVERY))

    def test_pinned_exact_scenario_passes_with_exact_tiers_only(self):
        result = self.run_device(self.real(PINNED))
        self.assertTrue(result['passed'], result.get('detail'))
        self.assertEqual(result['selector_mode'], 'exact')
        self.assertEqual({s.get('selector_tier') for s in result['steps']} - {None}, {'exact'})

    def test_a_relaxed_match_is_a_mismatch_with_masked_evidence_and_no_calibration(self):
        steps = [PINNED[0], {'id': 'save', 'operation': 'tap', 'arguments': {'selector': {'text': 'LƯU'}}}]  # label is content-desc
        n = self.real(steps); result = self.run_device(n)
        self.assertEqual((result['passed'], result['failure_kind'], result['selector_mode']), (False, 'selector', 'exact'))
        self.assertEqual(result['selector_failure']['step'], 'save')
        self.assertFalse(any(a[:3] == ['shell', 'input', 'tap'] for a in self.sent), 'no input after a mismatch')
        text = Path(result['ui_snapshot']['file']).read_text(encoding='utf-8')
        for screen_text in ('Cấu hình máy chủ', '8080', '10.0.2.2', 'Địa chỉ máy chủ'):
            self.assertNotIn(screen_text, text, 'screen text must not reach the evidence file')
        view = json.loads(text)
        self.assertTrue(view['masked']); self.assertEqual(view['selector'], {'text': 'LƯU'})
        button = next(x for x in view['nodes'] if x.get('class') == 'android.widget.Button')
        self.assertEqual(button['content-desc'], {'length': 3})
        self.assertEqual(rc.classify_receipt(n, result)[0], 'selector_mismatch')
        self.assertEqual(rc.POLICY['selector_mismatch'], ('ask', 0))

    def test_empty_content_description_is_a_valid_pinned_value(self):
        steps = [{'id': 'icon', 'operation': 'assert_ui', 'arguments': {'selector': {'class': 'android.widget.Button', 'content-desc': ''}}}]
        n = self.real(steps)
        da.scenario(n['config']['scenario'], n['config']['scenario_sha256'])  # round 2 had rejected '' (A54 icon buttons)

    def test_calibration_step_refuses_exact_mode(self):
        from onecrew import delivery_calibrate as cal
        calls = []
        class Runtime:
            def _recover(self, *args): calls.append(args[3])
        row = {'calibrate': {'failure': {'step': 'save', 'reason': 'not_found'}}, 'generation': 0}
        cal.step(Runtime(), 'task', {'delivery': {'history': []}}, self.real(PINNED), row)
        self.assertEqual(calls, ['selector_mismatch']); self.assertNotIn('calibrate', row)


class RecoveryPermissionTests(RealDeviceRun):
    def test_without_a_grant_nothing_is_sent_and_it_is_a_permission_question(self):
        self.dialog = 1
        with self.assertRaises(EnvironmentUnusable) as stuck: self.run_device(self.real(PINNED))
        self.assertIn('requires permission not granted for this device: system_dialog_wait', str(stuck.exception))
        self.assertEqual(rc.classify_error(stuck.exception), 'permission')
        self.assertFalse(any(a[:3] == ['shell', 'input', 'tap'] for a in self.sent))
        self.assertFalse(any(a[0] == 'install' for a in self.sent))

    def test_locked_screen_needs_its_own_grant(self):
        self.locked = True
        with self.assertRaisesRegex(EnvironmentUnusable, 'dismiss_keyguard'): self.run_device(self.real(PINNED))
        self.assertNotIn(['shell', 'wm', 'dismiss-keyguard'], self.sent)
        self.locked, self.sent = True, []
        result = self.run_device(self.real(PINNED, recovery=['dismiss_keyguard']))
        self.assertTrue(result['passed'], result.get('detail'))
        self.assertIn(['shell', 'wm', 'dismiss-keyguard'], self.sent)

    def test_granted_wait_is_used_and_recorded(self):
        self.dialog = 1
        result = self.run_device(self.real(PINNED, recovery=['system_dialog_wait']))
        self.assertTrue(result['passed'], result.get('detail'))
        self.assertEqual([a['action'] for a in result['environment']['actions']], ['system_dialog_wait'])

    def test_grants_are_validated(self):
        self.assertEqual(validate_recovery(['wake_screen', 'dismiss_keyguard'], SERIAL), ['wake_screen', 'dismiss_keyguard'])
        for bad in (['reboot'], ['wake_screen', 'wake_screen'], 'wake_screen'):
            with self.assertRaises(LedgerError): validate_recovery(bad, SERIAL)
        with self.assertRaisesRegex(LedgerError, 'emulator serial only'): validate_recovery(['restart_emulator'], SERIAL)


class EnvelopeTests(unittest.TestCase):
    def test_envelope_carries_mode_and_grant_and_covers_compares_them(self):
        from tests.test_autonomy_round2 import PlannedDeviceTests
        from tests.test_delivery_autopilot import PROPOSAL, discovery
        from onecrew.delivery_planner import compile_plan, covers, validate_envelope
        import tempfile
        stages = PlannedDeviceTests.stages(self, serial=SERIAL, selectors='exact', recovery=['wake_screen'])
        env = validate_envelope(stages)
        root = Path(tempfile.mkdtemp())
        plan, _, findings = compile_plan('goal', env, dict(discovery(root), private_keys=['bad_port']),
                                         dict(PROPOSAL, scenario={'steps': AC3, 'cleanup': []}), 'SOL@x', 'a' * 64)
        self.assertEqual(findings, [])
        config = next(n for n in plan['nodes'] if n['kind'] == 'device')['config']
        self.assertEqual((config['selectors'], config['recovery']), ('exact', ['wake_screen']))
        self.assertEqual(covers(env, plan), [])
        config['recovery'] = ['wake_screen', 'system_dialog_wait']
        self.assertIn('device recovery grant differs from envelope', covers(env, plan))
        with self.assertRaises(LedgerError): validate_envelope(PlannedDeviceTests.stages(self, selectors='loose'))


if __name__ == '__main__':
    unittest.main()
