"""Codex follow-up review of b19b35e (REVIEW-CODEX-ONECREW-b19b35e-FOLLOWUP-2026-10-12.txt): the two P1s as principles,
not as the two probes. Each test uses only APIs that exist on b19b35e where it can, so it is red there by assertion.

Principle 1: relocating a locator never changes the business object or the condition a step checks. A matching
label, or a selector that happens to name one node, is not proof; without proof the assertion stays and the
finding is a blocker (or a product finding when the check itself is false on screen).

Principle 2: every command that changes an emulator is bound to the verified instance and a live permission. If the
instance is lost or replaced between steps, the main operation, recovery and cleanup are all refused on the
replacement."""
import copy
import json
from unittest.mock import patch
import unittest

from onecrew import delivery_android as da
from onecrew import delivery_calibrate as cal
from onecrew import delivery_recovery as rc
from onecrew.ledger import LedgerError
from tests import test_autonomy_round2 as r2
from tests.test_autonomy_round2 import AC3, DeviceRun, NATIVE_CRASH

PKG = 'example.app'
EMU = {'avd': 'ApprovedTrial', 'avd_home': None}
BOOT_ID = ['shell', 'cat', '/proc/sys/kernel/random/boot_id']


def scenario(*steps, cleanup=()):
    return {'steps': list(steps), 'cleanup': list(cleanup)}


def step(i, op, selector):
    return {'id': i, 'operation': op, 'arguments': {'selector': selector}}


def box(text=None, rid=None, checked='false', cls='android.widget.CheckBox', y=0, **more):
    n = {'class': cls, 'checked': checked, 'bounds': f'[0,{y}][100,{y + 100}]', **more}
    if text is not None: n['text'] = text
    if rid is not None: n['resource-id'] = rid
    return n


def view(*nodes):
    return {'package': PKG, 'nodes': list(nodes)}


class RelocationPrincipleTests(unittest.TestCase):
    """Principle 1, through check(): the validator every scenario revision passes (b19b35e had it too)."""

    def refused(self, old, new, failing, screen):
        findings = cal.check(old, new, {'step': failing}, screen)
        self.assertTrue(findings, 'RED-P1-1: an unproven relocation was accepted: ' + json.dumps(new, ensure_ascii=False))
        return findings

    def test_codex_probe_dropping_an_observable_id_moves_the_check_to_another_account(self):
        screen = view(box('Remember', 'accountA', 'false'), box('Remember', 'accountB', 'true', y=200))
        old = scenario(step('verify', 'assert_ui', {'text': 'Remember', 'resource-id': 'accountA', 'checked': 'true'}))
        new = copy.deepcopy(old); new['steps'][0]['arguments']['selector'].pop('resource-id')
        self.refused(old, new, 'verify', screen)

    def test_several_nodes_with_the_same_label_never_prove_one(self):
        # Flutter exposes no resource-id: the expected account cannot be told apart from its siblings on screen.
        screen = view(box('Remember', checked='true'), box('Remember', checked='true', y=200), box('Remember', y=400))
        old = scenario(step('verify', 'assert_ui', {'text': 'Remember', 'resource-id': 'accountA', 'checked': 'true'}))
        for selector in ({'text': 'Remember', 'checked': 'true'}, {'content-desc': 'Remember', 'checked': 'true'}):
            new = copy.deepcopy(old); new['steps'][0]['arguments']['selector'] = selector
            self.refused(old, new, 'verify', screen)
        # Even a tap whose only extra key was incidental focus: two same-label nodes are no proof.
        tap = scenario(step('remember', 'tap', {'text': 'Remember', 'focused': 'false'}))
        new = copy.deepcopy(tap); new['steps'][0]['arguments']['selector'] = {'text': 'Remember'}
        self.refused(tap, new, 'remember', view(box('Remember', focused='true'), box('Remember', focused='true', y=200)))

    def test_one_same_label_node_is_no_proof_for_an_unexposed_id(self):
        # The only Remember on screen may belong to another account (the right one scrolled away): not the same object.
        screen = view(box('Remember', checked='true'))
        old = scenario(step('verify', 'assert_ui', {'text': 'Remember', 'resource-id': 'accountA', 'checked': 'true'}))
        new = copy.deepcopy(old); new['steps'][0]['arguments']['selector'] = {'text': 'Remember', 'checked': 'true'}
        self.refused(old, new, 'verify', screen)

    def test_changing_resource_id_or_class_is_refused(self):
        screen = view(box('Remember', 'accountA', 'false'), box('Remember', 'accountB', 'true', y=200),
                      box('Remember', checked='true', cls='android.widget.Switch', y=400))
        old = scenario(step('verify', 'assert_ui', {'text': 'Remember', 'resource-id': 'accountA', 'class': 'android.widget.CheckBox',
                                                    'checked': 'true'}))
        for selector in ({'text': 'Remember', 'resource-id': 'accountB', 'class': 'android.widget.CheckBox', 'checked': 'true'},
                         {'text': 'Remember', 'class': 'android.widget.Switch', 'checked': 'true'},
                         {'text': 'Remember', 'resource-id': 'accountA', 'checked': 'true'}):
            new = copy.deepcopy(old); new['steps'][0]['arguments']['selector'] = selector
            self.refused(old, new, 'verify', screen)

    def test_a_class_the_screen_does_not_show_is_not_dropped(self):
        # A Switch is not shown to be the CheckBox the step named, even as the only node with the label.
        screen = view(box('Remember', checked='true', cls='android.widget.Switch'))
        old = scenario(step('verify', 'assert_ui', {'text': 'Remember', 'class': 'android.widget.CheckBox', 'checked': 'true'}))
        new = copy.deepcopy(old); new['steps'][0]['arguments']['selector'] = {'text': 'Remember', 'checked': 'true'}
        self.refused(old, new, 'verify', screen)

    def test_moving_a_label_attribute_onto_a_merged_label_shared_by_siblings_is_refused(self):
        screen = view(box(None, checked='true', **{'content-desc': 'Remember\nAccount A'}),
                      box(None, checked='false', y=200, **{'content-desc': 'Remember\nAccount B'}))
        old = scenario(step('verify', 'assert_ui', {'text': 'Remember', 'checked': 'true', 'resource-id': 'accountB'}))
        new = copy.deepcopy(old); new['steps'][0]['arguments']['selector'] = {'content-desc': 'Remember', 'checked': 'true'}
        self.refused(old, new, 'verify', screen)

    def test_a_later_assertion_and_cleanup_are_never_relocated(self):
        screen = view({'content-desc': 'LƯU', 'class': 'android.widget.Button', 'focused': 'true', 'bounds': '[0,0][100,100]'},
                      {'content-desc': 'Saved', 'class': 'android.view.View', 'bounds': '[0,200][100,300]'})
        old = scenario(step('save', 'tap', {'content-desc': 'LƯU', 'focused': 'false'}),
                       step('saved', 'assert_ui', {'text': 'Saved'}),
                       cleanup=[step('off', 'tap', {'text': 'Remember', 'checked': 'true'})])
        later = copy.deepcopy(old)
        later['steps'][0]['arguments']['selector'] = {'content-desc': 'LƯU'}
        later['steps'][1]['arguments']['selector'] = {'content-desc': 'Saved'}  # same label, other attribute: still unproven
        self.assertTrue(any(f.startswith('saved:') for f in self.refused(old, later, 'save', screen)))
        cleaned = copy.deepcopy(old)
        cleaned['steps'][0]['arguments']['selector'] = {'content-desc': 'LƯU'}
        cleaned['cleanup'][0]['arguments']['selector'] = {'content-desc': 'Remember', 'checked': 'true'}
        self.assertTrue(any(f.startswith('off:') for f in self.refused(old, cleaned, 'save', screen)))
        # A failure inside cleanup has no proven relocation either.
        self.assertTrue(any(f.startswith('off:') for f in self.refused(old, cleaned, 'off', screen)))

    def test_an_absence_check_is_never_relocated(self):
        screen = view({'content-desc': 'Saved', 'class': 'android.view.View', 'bounds': '[0,0][100,100]'})
        old = scenario(step('none', 'assert_absent', {'text': 'Saved'}))
        new = copy.deepcopy(old); new['steps'][0]['arguments']['selector'] = {'text': 'Saved successfully'}
        self.refused(old, new, 'none', screen)


class RelocationCapabilityTests(unittest.TestCase):
    """What relocation still does: a locator that only failed on incidental state or on where a label is written."""

    # Trial 5 (TASK-dc9d90b9, 12/10/2026), sanitized snapshot of the failing step s7 (the typed value was masked).
    TRIAL5 = {'package': 'vn.onetech.trial.settings_trial', 'nodes': [
        {'bounds': '[0,0][720,1280]', 'class': 'android.widget.FrameLayout', 'resource-id': 'android:id/content'},
        {'bounds': '[0,0][720,1280]', 'class': 'android.widget.FrameLayout', 'focused': 'true'},
        {'bounds': '[28,67][332,116]', 'class': 'android.view.View', 'content-desc': 'Cấu hình máy chủ'},
        {'bounds': '[28,168][692,301]', 'class': 'android.widget.EditText', 'clickable': 'true', 'focused': 'true',
         'hint': 'Địa chỉ máy chủ, Địa chỉ không hợp lệ', 'text': '<private>'},
        {'bounds': '[28,273][230,301]', 'class': 'android.view.View', 'content-desc': 'Địa chỉ không hợp lệ'},
        {'bounds': '[28,322][692,420]', 'class': 'android.widget.EditText', 'clickable': 'true', 'hint': 'Cổng', 'text': '8080'},
        {'bounds': '[28,462][692,546]', 'class': 'android.widget.Button', 'clickable': 'true', 'content-desc': 'LƯU'}]}

    def test_trial5_locator_that_named_focus_is_relocated_with_identity_kept(self):
        old = {'class': 'android.widget.EditText', 'focused': 'false', 'hint': 'Địa chỉ máy chủ, Địa chỉ không hợp lệ'}
        new, kind, _ = cal.relocate(old, 'type', self.TRIAL5)
        self.assertEqual((new, kind), ({'class': 'android.widget.EditText', 'hint': 'Địa chỉ máy chủ, Địa chỉ không hợp lệ'}, 'relocated'))
        revised = scenario({'id': 's7', 'operation': 'type', 'arguments': {'selector': new, 'private_key': 'k'}})
        self.assertEqual(cal.check(scenario({'id': 's7', 'operation': 'type', 'arguments': {'selector': old, 'private_key': 'k'}}),
                                   revised, {'step': 's7'}, self.TRIAL5), [])

    def test_a_label_written_in_another_attribute_or_as_a_merged_part_is_relocated(self):
        self.assertEqual(cal.relocate({'text': 'Cổng', 'focused': 'false'}, 'type', self.TRIAL5)[:2], ({'hint': 'Cổng'}, 'relocated'))
        self.assertEqual(cal.relocate({'text': 'LƯU', 'class': 'android.widget.Button', 'focused': 'false'}, 'tap', self.TRIAL5)[:2],
                         ({'class': 'android.widget.Button', 'content-desc': 'LƯU'}, 'relocated'))

    def test_codex_probe_is_a_condition_finding_not_a_relocation(self):
        screen = view(box('Remember', 'accountA', 'false'), box('Remember', 'accountB', 'true', y=200))
        self.assertEqual(cal.relocate({'text': 'Remember', 'resource-id': 'accountA', 'checked': 'true'}, 'assert_ui', screen)[1], 'condition')

    def test_relocation_never_calls_a_model(self):
        self.assertFalse(hasattr(cal, 'prompt') or hasattr(cal, 'SCHEMA'))


class CalibrationRoutingTests(unittest.TestCase):
    """Through the delivery coordinator: the Codex probe ends as a product finding with the assertion unchanged."""
    setUp = r2.base.DeliveryTests.setUp
    create = r2.base.DeliveryTests.create
    delivery = r2.CalibrationDeliveryTests.delivery
    selector_failure = r2.CalibrationDeliveryTests.selector_failure

    def test_codex_probe_keeps_the_assertion_and_reports_the_product(self):
        nodes = [box('Remember', 'accountA', 'false'), box('Remember', 'accountB', 'true', y=200)]
        steps = [step('verify', 'assert_ui', {'text': 'Remember', 'resource-id': 'accountA', 'checked': 'true'})]
        r, t, s, used = self.delivery([self.selector_failure('verify', 'not_found', nodes)], steps)
        row = s['delivery']['nodes']['device']
        self.assertIsNone(row.get('scenario'), 'RED-P1-1: the scenario was revised')
        self.assertEqual((row.get('calibrations', 0), row['receipt']['failure_kind']), (0, 'product'))
        self.assertEqual([u[2] for u in used], [0]); self.assertEqual(self.prompts, [])


class InstanceRun(DeviceRun):
    """A scripted emulator whose instance can be replaced at a chosen moment; records what reached which instance."""

    def setUp(self):
        super().setUp(); self.avd = 'ApprovedTrial'; self.reached = []; self.switched_at = None

    def replace(self, avd=None, boots=None):
        self.avd = avd or self.avd; self.boots = boots or self.boots + 1; self.switched_at = len(self.sent)

    def adb(self, runtime, task, argv, cwd, seconds):
        args = argv[3:]
        if args[0] == 'install' or args[:2] in (['shell', 'input'], ['shell', 'am'], ['emu', 'kill'], ['shell', 'wm']) and args[2:3] != ['size']:
            self.reached.append({'command': args[:3], 'avd': self.avd, 'boot': self.boots})
        return DeviceRun.adb(self, runtime, task, argv, cwd, seconds)

    def after_replacement(self):
        """Every command sent once the instance changed (the identity reads that detected it included)."""
        return [] if self.switched_at is None else self.sent[self.switched_at:]

    def changes_after_replacement(self):
        return [r for r in self.reached if (r['avd'], r['boot']) != (self.reached[0]['avd'], self.reached[0]['boot'])]

    def on_receipt(self, steps_done, action):
        """Run action once, right after the receipt records steps_done passed steps (between steps / before cleanup)."""
        real = da.durable_write
        def write(path, data):
            real(path, data)
            if path.name == 'receipt.json' and action and len(json.loads(data.decode())['steps']) == steps_done:
                action(); write.done = True
        return patch('onecrew.delivery_android.durable_write', side_effect=write)


class InstanceBindingTests(InstanceRun):
    def test_codex_probe_replacement_between_prepare_and_install(self):
        def adb(runtime, task, argv, cwd, seconds):
            if argv[3:] == ['shell', 'wm', 'size']: self.replace('OtherUserAVD', 2)
            return InstanceRun.adb(self, runtime, task, argv, cwd, seconds)
        self.adb = adb
        with patch('onecrew.delivery_device_env.ensure_server', return_value={'started': False}):
            n = self.node(AC3, emulator=EMU); result = self.run_device(n)
        wrong = [r for r in self.reached if r['avd'] == 'OtherUserAVD']
        self.assertEqual(wrong, [], 'RED-P1-2: install/input reached the replacement AVD')
        self.assertFalse(result['passed']); self.assertTrue(result.get('identity_lost'))
        self.assertEqual(rc.classify_receipt(n, result)[0], 'permission')  # one question, no recovery on the replacement
        self.assertNotEqual(result['environment'].get('emulator_cleanup'), 'stopped')

    def test_same_avd_new_boot_between_steps_stops_main_steps_and_cleanup(self):
        cleanup = [{'id': 'reset', 'operation': 'tap', 'arguments': {'selector': {'content-desc': 'LƯU'}}}]
        n = self.node(AC3, cleanup, emulator=EMU)
        with self.on_receipt(1, lambda: self.replace()):  # same AVD name, another boot_id, after step 'title'
            result = self.run_device(n)
        self.assertEqual(self.changes_after_replacement(), [], 'RED-P1-2: a step or cleanup reached the replacement')
        self.assertFalse(result['passed']); self.assertEqual([s['id'] for s in result['steps']], ['title'])
        self.assertTrue(result.get('identity_lost'))
        self.assertFalse(result['cleanup'][0]['passed'])
        self.assertEqual(rc.classify_receipt(n, result)[0], 'permission')

    def test_replacement_before_cleanup_gets_no_cleanup(self):
        cleanup = [{'id': 'reset', 'operation': 'tap', 'arguments': {'selector': {'content-desc': 'LƯU'}}}]
        n = self.node(AC3, cleanup, emulator=EMU)
        with self.on_receipt(len(AC3), lambda: self.replace()):
            result = self.run_device(n)
        self.assertEqual([s['id'] for s in result['steps']], [s['id'] for s in AC3])
        self.assertEqual(self.changes_after_replacement(), [], 'RED-P1-2: cleanup was sent to the replacement')
        self.assertFalse(result['passed']); self.assertTrue(result.get('identity_lost')); self.assertTrue(result['uncertain'])

    def test_replacement_before_system_recovery_gets_no_recovery_input(self):
        def adb(runtime, task, argv, cwd, seconds):
            if argv[3] == 'exec-out' and self.dialog and self.switched_at is None: self.replace()
            return InstanceRun.adb(self, runtime, task, argv, cwd, seconds)
        self.adb = adb
        with self.on_receipt(1, lambda: setattr(self, 'dialog', 1)):  # a 'not responding' dialog appears after step 1
            result = self.run_device(self.node(AC3, emulator=EMU))
        self.assertIsNotNone(self.switched_at)
        self.assertEqual(self.changes_after_replacement(), [], 'RED-P1-2: the dialog recovery tapped the replacement')
        self.assertFalse(result['passed']); self.assertTrue(result.get('identity_lost'))

    def test_replacement_before_an_emulator_restart_gets_no_kill(self):
        r2.AppCrashTests.crash(self, NATIVE_CRASH, launches_dead=1); self.absent = 1
        crash_adb = self.adb
        def adb(runtime, task, argv, cwd, seconds):
            if argv[3:6] == ['logcat', '-d', '-b'] and self.switched_at is None: self.replace()
            return crash_adb(runtime, task, argv, cwd, seconds)
        self.adb = adb
        with patch('onecrew.delivery_device_env.boot_emulator', return_value={'booted': True}) as boot:
            result = self.run_device(self.node(AC3, emulator=EMU))
        self.assertNotIn(['emu', 'kill'], self.after_replacement(), 'RED-P1-2: the replacement was killed for a restart')
        self.assertEqual(boot.call_count, 1)
        self.assertFalse(result['passed']); self.assertTrue(result.get('identity_lost'))

    def test_replacement_before_the_stop_after_a_pass_is_not_stopped(self):
        self.absent = 1  # OneCrew boots (and owns) the verified instance
        with patch('onecrew.delivery_device_env.boot_emulator', return_value={'booted': True}), \
                self.on_receipt(len(AC3), lambda: self.replace()):
            result = self.run_device(self.node(AC3, emulator=EMU))
        self.assertTrue(result['passed'], result.get('detail'))  # every step was observed on the pinned instance
        self.assertNotIn(['emu', 'kill'], self.after_replacement(), 'RED-P1-2: the replacement was stopped')
        self.assertEqual(result['environment']['emulator_cleanup'], 'identity_lost_not_stopped')

    def test_an_emulator_serial_without_an_approved_avd_is_bound_to_its_first_instance(self):
        with self.on_receipt(1, lambda: self.replace('OtherUserAVD')):
            result = self.run_device(self.node(AC3))
        self.assertEqual(self.changes_after_replacement(), [], 'RED-P1-2: no-AVD emulator stage followed the replacement')
        self.assertFalse(result['passed']); self.assertTrue(result.get('identity_lost'))

    def test_an_unreadable_identity_is_read_again_but_never_assumed(self):
        reads = {'n': 0, 'fail': 0}
        def adb(runtime, task, argv, cwd, seconds):
            if argv[3:] == BOOT_ID:
                reads['n'] += 1
                if reads['n'] == 3 or reads['fail']: self.sent.append(argv[3:]); return 1, '', 'error: closed'
            return InstanceRun.adb(self, runtime, task, argv, cwd, seconds)
        self.adb = adb
        result = self.run_device(self.node(AC3, emulator=EMU))  # one transport hiccup: the next read shows the same boot
        self.assertTrue(result['passed'], result.get('detail'))
        reads['fail'] = 1; self.sent.clear(); self.reached.clear()
        with patch('onecrew.delivery_device_env.ensure_server', return_value={'started': False}):
            try: outcome = self.run_device(self.node(AC3, emulator=EMU))
            except LedgerError as e: outcome = e
        self.assertIn('unverifiable', str(outcome) if isinstance(outcome, LedgerError) else outcome['detail'])
        self.assertEqual(self.reached, [])


class CoordinatorRestartTests(InstanceRun):
    def run_with_boot(self, n):
        with patch('onecrew.delivery_device_env.boot_emulator', return_value={'booted': True}):
            return self.run_device(n)

    def interrupted(self, boot_id):
        n = self.node(AC3, emulator=EMU); row = {'generation': 0}
        directory = da.device_directory(self.runtime, 'task', n, row); directory.mkdir(parents=True, exist_ok=True)
        (directory/'intent.json').write_text(json.dumps({'task': 'task', 'step': 'save', 'state': 'intent', 'boot_id': boot_id}))
        return n, row

    def test_an_interrupted_attempt_is_not_replayed_on_a_replacement(self):
        n, row = self.interrupted('00000001-0000-4000-8000-000000000000')
        self.boots = 2  # the coordinator restarted and the serial now carries another boot of the same AVD
        with patch('onecrew.delivery_android.bounded', side_effect=self.adb):
            outcome = da.reconcile(self.runtime, 'task', self.state, n, row)
        self.assertFalse(outcome['replay'], 'RED-P1-2: an interrupted attempt would replay on the replacement')
        self.assertEqual(outcome.get('instance'), 'replaced')
        self.assertEqual(self.reached, [])

    def test_an_interrupted_attempt_replays_on_the_same_instance(self):
        n, row = self.interrupted('00000001-0000-4000-8000-000000000000')
        with patch('onecrew.delivery_android.bounded', side_effect=self.adb):
            outcome = da.reconcile(self.runtime, 'task', self.state, n, row)
        self.assertTrue(outcome['replay']); self.assertEqual(outcome.get('instance'), 'same')

    def test_a_new_attempt_after_restart_verifies_again_and_only_stops_its_own_boot(self):
        self.absent = 1
        first = self.run_with_boot(self.node(AC3[:1] + [step('nope', 'tap', {'text': 'Không có'})], emulator=EMU))
        self.assertFalse(first['passed'])
        # Coordinator restart: nothing in memory. The same instance is still there: re-verified, still OneCrew's own.
        self.sent.clear()
        second = self.run_with_boot(self.node(AC3, emulator=EMU))
        self.assertIn(['emu', 'avd', 'name'], self.sent); self.assertTrue(second['passed'], second.get('detail'))
        self.assertEqual(second['environment']['emulator_cleanup'], 'stopped')
        # Restart again, the user started the same AVD: borrowed, used under the AVD approval, never stopped.
        self.boots += 5; self.sent.clear()
        third = self.run_with_boot(self.node(AC3, emulator=EMU))
        self.assertTrue(third['passed']); self.assertNotIn(['emu', 'kill'], self.sent)
        self.assertEqual(third['environment']['emulator_cleanup'], 'borrowed_left_running')
        # And another AVD on the serial after a restart gets nothing at all.
        self.avd = 'OtherUserAVD'; self.reached.clear()
        with self.assertRaisesRegex(LedgerError, 'not the approved AVD'): self.run_with_boot(self.node(AC3, emulator=EMU))
        self.assertEqual(self.reached, [])


class ValidInstanceTests(InstanceRun):
    MUTATING = (['install'], ['shell', 'input'], ['shell', 'am'], ['emu', 'kill'])

    def test_an_unchanged_instance_passes_and_every_change_is_checked_right_before_it(self):
        self.absent = 1
        with patch('onecrew.delivery_device_env.boot_emulator', return_value={'booted': True}):
            result = self.run_device(self.node(AC3, emulator=EMU))
        self.assertTrue(result['passed'], result.get('detail'))
        self.assertEqual(result['environment']['emulator_cleanup'], 'stopped')
        changes = [i for i, a in enumerate(self.sent) if any(a[:len(m)] == m for m in self.MUTATING)]
        self.assertTrue(changes)
        self.assertTrue(all(self.sent[i - 1] == BOOT_ID for i in changes), 'a change was sent without its identity check')

    def test_only_exact_read_shapes_skip_the_gate(self):
        for args in (['install', '-r', 'x.apk'], ['shell', 'input', 'tap', '1', '2'], ['shell', 'am', 'force-stop', 'p'],
                     ['shell', 'wm', 'dismiss-keyguard'], ['emu', 'kill'], ['logcat', '-c'], ['shell', 'dumpsys', 'battery', 'set'],
                     ['shell', 'date', '-s', '0'], ['shell', 'pm', 'clear', 'p'], ['shell', 'settings', 'put'], ['reboot']):
            self.assertTrue(da.mutating(args), args)
        for args in (['get-state'], ['exec-out', 'uiautomator', 'dump', '/dev/tty'], ['shell', 'dumpsys', 'window'], BOOT_ID,
                     ['logcat', '-d', '-b', 'crash'], ['shell', 'pm', 'path', 'p'], ['emu', 'avd', 'name'], ['shell', 'wm', 'size']):
            self.assertFalse(da.mutating(args), args)

    def test_a_physical_device_is_not_gated_by_boot_id(self):
        from tests.test_device_exact_mode import PINNED, RealDeviceRun
        run = RealDeviceRun('run'); run.setUp()
        try:
            result = run.run_device(run.real(PINNED))
            self.assertTrue(result['passed'], result.get('detail'))
            self.assertNotIn(BOOT_ID, run.sent)
        finally:
            run.doCleanups()


if __name__ == '__main__':
    unittest.main()
