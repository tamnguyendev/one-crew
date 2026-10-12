"""Autonomy round 2 (2026-10-12): Codex scorecard finding, plus what kept trial 3 from finishing E2E.

1. An entry deciding 'retry' under delegation was scored autonomous_complete. Decisions are now attributed
   to the user, to the user relayed by an entry, or to the entry itself; unattributed stays unknown.
2. The emulator showed a System UI "not responding" dialog and selectors authored from source did not match
   Flutter's accessibility tree. OneCrew now checks/recovers the device inside the grant, resolves selectors
   on the live UI with recorded tiers, keeps a sanitized snapshot of a failing step and recalibrates only a
   scenario it planned itself, never weakening an assertion.

Fixture XML below is the real uiautomator dump of the trial app (Flutter 3, Android 16 emulator, 12/10/2026)."""
import contextlib
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import onecrew.native_change  # noqa: F401  bind the real capture before tests patch native_audit.capture
from onecrew import delivery_android as da
from onecrew import delivery_recovery as rc
from onecrew import eval_scorecard as sc
from onecrew.delivery_steps import file_hash
from onecrew.ledger import Ledger, LedgerError
from tests import test_codex_review_p1 as p1
from tests import test_solution_delivery as base

PKG = 'vn.onetech.trial.settings_trial'


def node(cls, bounds, text='', desc='', hint='', focused='false', clickable='false', package=PKG, rid=''):
    return (f'<node class="{cls}" text="{text}" content-desc="{desc}" hint="{hint}" resource-id="{rid}" package="{package}" '
            f'clickable="{clickable}" focusable="true" focused="{focused}" enabled="true" bounds="{bounds}"/>')


def screen(port='8080', error=False, saved=False, focused=None):
    focused = error if focused is None else focused
    nodes = [node('android.widget.FrameLayout', '[0,0][720,1280]', rid='android:id/content'),
             node('android.view.View', '[28,67][332,116]', desc='Cấu hình máy chủ'),
             node('android.widget.EditText', '[28,168][692,266]', text='10.0.2.2', hint='Địa chỉ máy chủ', clickable='true'),
             node('android.widget.EditText', '[28,287][692,420]' if error else '[28,287][692,385]', text=port,
                  hint='Cổng, Cổng phải từ 1 đến 65535' if error else 'Cổng', clickable='true', focused='true' if focused else 'false')]
    if error: nodes.append(node('android.view.View', '[28,392][286,420]', desc='Cổng phải từ 1 đến 65535'))
    nodes.append(node('android.widget.Button', '[28,462][692,546]' if error else '[28,427][692,511]', desc='LƯU', clickable='true'))
    if saved: nodes.append(node('android.view.View', '[28,560][200,590]', desc='Đã lưu'))
    return '<?xml version="1.0"?><hierarchy rotation="0">' + ''.join(nodes) + '</hierarchy>'


ANR = ('<?xml version="1.0"?><hierarchy rotation="0">'
       + node('android.widget.TextView', '[80,500][640,560]', text="System UI isn't responding", package='android')
       + node('android.widget.Button', '[80,600][640,660]', text='Close app', clickable='true', package='android', rid='android:id/aerr_close')
       + node('android.widget.Button', '[80,680][640,740]', text='Wait', clickable='true', package='android', rid='android:id/aerr_wait')
       + '</hierarchy>')
APP_FOCUS = 'mCurrentFocus=Window{1 u0 ' + PKG + '/' + PKG + '.MainActivity}\n'
ANR_FOCUS = 'mCurrentFocus=Window{2 u0 Application Not Responding: com.android.systemui}\n'


def metrics(**changes):
    m = p1.observed()['metrics']; m.update(changes); return m


def done(**metric_changes):
    """A fully verified delivery; only the decision evidence varies."""
    return p1.observed(verification='passed', gaps=[], gates={'device': 'passed'}, metrics=metrics(**metric_changes),
                       delivery={'technical_verified': True, 'criteria': {'AC1': 'passed', 'AC2': 'passed'},
                                 'nodes': {'tests': {'kind': 'regression', 'phase': 'passed', 'skipped': False},
                                           'device': {'kind': 'device', 'phase': 'passed', 'skipped': False}}})


class DecisionProvenanceTests(unittest.TestCase):
    """Codex review 2026-10-12: Claude deciding retry under delegation was still autonomous_complete."""
    reply = [{'actor': 'claude', 'channel': 'cli', 'command': 'request.reply'}]

    def test_entry_decision_under_delegation_is_assisted(self):
        task = done(decisions_answered=1, interventions=self.reply, decisions_by_source={'user': 0, 'relayed': 0, 'entry': 1, 'unknown': 0})
        self.assertEqual(sc.outcome(task), ('assisted_complete', ['entry_decision']), 'RED-ENTRY-DECISION: entry decision scored autonomous')

    def test_relayed_user_decision_is_assisted_not_autonomous(self):
        task = done(decisions_answered=1, interventions=self.reply, decisions_by_source={'user': 0, 'relayed': 1, 'entry': 0, 'unknown': 0})
        self.assertEqual(sc.outcome(task), ('assisted_complete', ['entry_relayed_decision']))

    def test_unattributed_answer_is_unknown(self):
        # Legacy shape (no per-answer provenance): an answered decision whose decider cannot be shown.
        task = done(decisions_answered=1, interventions=self.reply)
        self.assertEqual(sc.outcome(task), ('unknown', ['decision_provenance_unknown']), 'RED-UNATTRIBUTED-DECISION')

    def test_users_own_answer_keeps_autonomy(self):
        task = done(decisions_answered=1, interventions=[{'actor': 'user', 'channel': 'cli', 'command': 'request.reply'}],
                    decisions_by_source={'user': 1, 'relayed': 0, 'entry': 0, 'unknown': 0})
        self.assertEqual(sc.outcome(task), ('autonomous_complete', []))

    def test_ledger_cli_and_observation_record_who_decided(self):
        from onecrew.cli import main
        from onecrew.eval_observe import observe
        from tests.test_interventions import LedgerFixture
        f = LedgerFixture(self); ledger, root, state = f.ledger, f.project, f.state_root
        task = {'id': f.task()}
        if True:
            ids = []
            for n, decided in enumerate(('entry', 'user', None)):
                q = ledger.create_request(task['id'], 'q' + str(n), {'schema_version': 1, 'question': 'Retry?', 'reason': 'r', 'impact': 'i',
                                          'options': [{'id': 'retry', 'label': 'Retry'}, {'id': 'stop', 'label': 'Stop'}],
                                          'recommendation': 'retry', 'action': {'type': 'none', 'parameters': {}}})
                argv = ['--project', str(root), '--state-root', str(state), 'request', 'reply', q['id'], '--revision', q['revision'],
                        '--choice', 'retry', '--json'] + (['--decided-by', decided] if decided else [])
                with patch.dict(os.environ, {'ONECREW_ACTOR': 'claude'}), contextlib.redirect_stdout(io.StringIO()):
                    self.assertEqual(main(argv), 0)
                ids.append(q['id'])
            receipt = ledger.request(ids[0])['answer']['provenance']
            self.assertEqual((receipt['by'], receipt['decided_by']), ('claude', 'entry'))
            with self.assertRaises(LedgerError): ledger.reply(ids[0], 'x', 'retry', decided_by='boss')
            seen = observe(state, [task['id']])['tasks'][0]['metrics']
            self.assertEqual(seen['decisions_by_source'], {'user': 0, 'relayed': 1, 'entry': 1, 'unknown': 1})


class LiveSelectorTests(unittest.TestCase):
    """Selectors resolve on the real Flutter tree with a recorded tier, never more than one node."""

    def resolve(self, xml, selector):
        evidence = {}
        found, _ = da.find_ui(xml, selector, PKG, evidence=evidence)
        return found, evidence['selector_tier']

    def test_flutter_labels_resolve_with_recorded_tiers(self):
        before, after = screen(), screen(port='70000', error=True)
        self.assertEqual(self.resolve(before, {'text': 'Cấu hình máy chủ'})[1], 'exact')  # Text -> content-desc
        found, tier = self.resolve(before, {'text': 'Cổng'})                              # TextField label -> hint
        self.assertEqual((found.get('text'), tier), ('8080', 'label'))
        found, tier = self.resolve(after, {'hint': 'Cổng'})                               # label + error -> one part
        self.assertEqual((found.get('text'), tier), ('70000', 'label_part'))
        self.assertEqual(self.resolve(after, {'text': 'Cổng phải từ 1 đến 65535'})[0].get('class'), 'android.view.View')
        self.assertEqual(self.resolve(before, {'text': 'Lưu'})[1], 'label_casefold')       # "LƯU" written another way
        with self.assertRaises(da.SelectorUnresolved) as missing: da.find_ui(before, {'resource-id': 'port'}, PKG)
        self.assertEqual(missing.exception.reason, 'not_found')                           # a Flutter Key is not exposed
        with self.assertRaises(da.SelectorUnresolved) as many: da.find_ui(before, {'class': 'android.widget.EditText'}, PKG)
        self.assertEqual(many.exception.reason, 'ambiguous')

    def test_absence_needs_no_mention_at_all(self):
        self.assertFalse(da.present(screen(error=True), {'text': 'Đã lưu'}, PKG))
        self.assertTrue(da.present(screen(saved=True), {'text': 'đã LƯU'}, PKG))
        self.assertTrue(da.present(screen(error=True), {'text': 'phải từ 1'}, PKG))

    def test_snapshot_keeps_labels_and_masks_private_values(self):
        nodes = da.snapshot(screen(port='70000', error=True), PKG, ['70000'])
        port = next(n for n in nodes if n.get('class') == 'android.widget.EditText' and 'Cổng' in n.get('hint', ''))
        self.assertEqual(port['text'], '<private>')
        self.assertNotIn('70000', json.dumps(nodes, ensure_ascii=False))
        self.assertFalse(any(set(n) <= {'class', 'bounds'} for n in nodes))


class DeviceRun(unittest.TestCase):
    """A scripted emulator: answers adb like the real one, changes screens on taps and typing."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name); self.apk = self.root/'app.apk'; self.apk.write_bytes(b'apk')
        self.digest = file_hash(self.apk)
        self.private = self.root/'inputs.json'; self.private.write_text(json.dumps({'bad_port': '70000', 'good_port': '9922'}))
        self.runtime = type('R', (), {'ledger': type('L', (), {'state_root': self.root/'state'})()})()
        self.state = {'delivery': {'source': {'hash': 'src'}, 'nodes': {'build': {'receipt': {
            'passed': True, 'apk': str(self.apk), 'sha256': self.digest, 'source': 'src'}}}}}
        self.port, self.error, self.saved, self.focus, self.dialog, self.typing = '8080', False, False, APP_FOCUS, 0, False
        self.sent = []
        self.home = patch('onecrew.delivery_android.home', return_value=self.root); self.home.start(); self.addCleanup(self.home.stop)
        self.sleep = patch('onecrew.delivery_android.time.sleep'); self.sleep.start(); self.addCleanup(self.sleep.stop)
        self.env_sleep = patch('onecrew.delivery_device_env.time.sleep'); self.env_sleep.start(); self.addCleanup(self.env_sleep.stop)

    def node(self, steps, cleanup=(), **config):
        path = self.root/'scenario.json'
        path.write_text(json.dumps({'version': 1, 'activity': PKG + '.MainActivity', 'steps': steps, 'cleanup': list(cleanup)}))
        c = {'build_node': 'build', 'adb': str(self.root/'adb.exe'), 'serial': 'emulator-5554', 'package_id': PKG,
             'scenario': str(path), 'scenario_sha256': file_hash(path), 'private_reference': str(self.private),
             'private_version': 'v1', 'timeout_seconds': 600, 'replay_safe': True, 'calibration': 'onecrew'}
        c.update(config)
        return {'id': 'device', 'kind': 'device', 'config': c}

    def adb(self, runtime, task, argv, cwd, seconds):
        self.assertEqual(argv[1:3], ['-s', 'emulator-5554'])
        args = argv[3:]; self.sent.append(args)
        if args == ['get-state']: return 0, 'device', ''
        if args == ['shell', 'wm', 'size']: return 0, 'Physical size: 720x1280', ''
        if args[0] == 'install': return 0, 'Success', ''
        if args[:3] == ['shell', 'pm', 'path']: return 0, 'package:/data/app/base.apk', ''
        if args[:2] == ['shell', 'sha256sum']: return 0, self.digest + ' /data/app/base.apk', ''
        if args == ['shell', 'dumpsys', 'window']: return 0, ANR_FOCUS if self.dialog else self.focus, ''
        if args[:2] == ['shell', 'pidof']: return (1, '', '') if getattr(self, 'dead', False) else (0, '4242', '')
        if args[0] == 'exec-out': return 0, ANR if self.dialog else screen(self.port, self.error, self.saved, self.typing), ''
        if args[:3] == ['shell', 'input', 'tap']:
            x, y = int(args[3]), int(args[4])
            if self.dialog and 680 <= y <= 740: self.dialog -= 1
            elif 287 <= y <= (420 if self.error else 385): self.typing = True  # the port field takes focus
            elif 427 <= y <= 546:  # LƯU
                ok = self.port.isdigit() and 1 <= int(self.port) <= 65535
                self.error, self.saved = not ok, ok
        if args[:3] == ['shell', 'input', 'keyevent'] and args[3] == 'KEYCODE_DEL': self.port = self.port[:-1]
        if args[:3] == ['shell', 'input', 'text']: self.port += args[3]
        return 0, '', ''

    def run_device(self, n, row=None):
        with patch('onecrew.delivery_android.bounded', side_effect=self.adb):
            return da.device(self.runtime, 'task', self.state, n, row or {'generation': 0})


AC3 = [{'id': 'title', 'operation': 'wait_for', 'arguments': {'selector': {'text': 'Cấu hình máy chủ'}, 'timeout_seconds': 10}},
       {'id': 'bad', 'operation': 'type', 'arguments': {'selector': {'hint': 'Cổng'}, 'private_key': 'bad_port'}},
       {'id': 'save', 'operation': 'tap', 'arguments': {'selector': {'text': 'LƯU'}}},
       {'id': 'error', 'operation': 'wait_for', 'arguments': {'selector': {'text': 'Cổng phải từ 1 đến 65535'}, 'timeout_seconds': 5}},
       {'id': 'not-saved', 'operation': 'assert_absent', 'arguments': {'selector': {'text': 'Đã lưu'}}}]


class LiveDeviceTests(DeviceRun):
    def test_flutter_scenario_passes_with_tier_evidence(self):
        result = self.run_device(self.node(AC3))
        self.assertTrue(result['passed'], result.get('detail'))
        tiers = {s['id']: s.get('selector_tier') for s in result['steps']}
        self.assertEqual((tiers['title'], tiers['bad'], tiers['save'], tiers['error']), ('exact',)*4)
        self.assertEqual(result['scenario_revision'], 0)

    def test_absent_assertion_fails_as_a_product_finding(self):
        steps = AC3[:3] + [{'id': 'no-save', 'operation': 'assert_absent', 'arguments': {'selector': {'text': 'Cổng phải'}}}]
        result = self.run_device(self.node(steps))
        self.assertFalse(result['passed']); self.assertEqual(result['failure_kind'], 'product')

    def test_unresolved_selector_leaves_a_sanitized_snapshot(self):
        steps = [AC3[0], {'id': 'bad', 'operation': 'type', 'arguments': {'selector': {'resource-id': 'port'}, 'private_key': 'bad_port'}}]
        result = self.run_device(self.node(steps))
        self.assertEqual(result['failure_kind'], 'selector')
        self.assertEqual(result['selector_failure'], {'step': 'bad', 'operation': 'type', 'reason': 'not_found', 'matches': 0})
        view = json.loads(Path(result['ui_snapshot']['file']).read_text(encoding='utf-8'))
        self.assertEqual(view['package'], PKG); self.assertTrue(any(n.get('hint') == 'Cổng' for n in view['nodes']))
        self.assertFalse(any(a[:3] == ['shell', 'input', 'text'] for a in self.sent))

    def test_wait_that_never_matches_is_a_selector_finding_not_a_scenario_timeout(self):
        steps = [{'id': 'wait', 'operation': 'wait_for', 'arguments': {'selector': {'text': 'Không có'}, 'timeout_seconds': 1}}]
        clock = [0.0]
        def tick(seconds=0): clock[0] += max(seconds, .3)
        with patch('onecrew.delivery_android.time.monotonic', side_effect=lambda: clock[0]), \
             patch('onecrew.delivery_android.time.sleep', side_effect=tick):
            result = self.run_device(self.node(steps))
        self.assertEqual(result['failure_kind'], 'selector', 'RED-WAIT-TIMEOUT: a UI wait timeout read as a scenario timeout')
        self.assertEqual(result['selector_failure']['reason'], 'timeout')
        self.assertNotIn('scenario/operation timeout', result['detail'])

    def test_system_ui_not_responding_is_answered_with_wait_inside_the_grant(self):
        self.dialog = 1
        result = self.run_device(self.node(AC3))
        self.assertTrue(result['passed'], result.get('detail'))
        self.assertEqual([a['action'] for a in result['environment']['actions']], ['system_dialog_wait'])
        self.assertFalse(any(a[:2] == ['emu', 'kill'] or a[:1] == ['reboot'] for a in self.sent))
        self.assertNotIn(['shell', 'input', 'tap', '360', '630'], self.sent)  # never "Close app"

    def test_a_just_booted_system_ui_that_hangs_repeatedly_is_waited_out_not_restarted(self):
        # Smoke 12/10 on the real emulator: after a cold boot the dialog came back for 1-2 minutes under boot load;
        # the first version answered Wait for about 15 s (4 reads), then restarted the emulator into the same state.
        states = iter(['absent']); original = self.adb
        def adb(runtime, task, argv, cwd, seconds):
            if argv[3:] == ['get-state'] and next(states, 'device') == 'absent': return 1, '', 'not found'
            if argv[3:] == ['shell', 'dumpsys', 'window'] and not self.dialog and getattr(self, 'relapses', 0) < 6:
                self.relapses = getattr(self, 'relapses', 0) + 1; self.dialog = 1  # System UI hangs again after each Wait
            return original(runtime, task, argv, cwd, seconds)
        self.adb = adb; self.dialog = 1
        with patch('onecrew.delivery_device_env.boot_emulator', return_value={'booted': True}) as boot:
            result = self.run_device(self.node(AC3, emulator={'avd': 'Trial', 'avd_home': str(self.root)}))
        self.assertTrue(result['passed'], result.get('detail')); boot.assert_called_once()
        actions = [a['action'] for a in result['environment']['actions']]
        self.assertNotIn('emulator_stop', actions, 'RED-BOOT-SETTLE: restarted the emulator while System UI was still settling')
        self.assertEqual(actions.count('system_dialog_wait'), 7)

    def test_dialog_that_takes_focus_mid_scenario_is_answered_once_then_input_continues(self):
        original = self.adb
        def adb(runtime, task, argv, cwd, seconds):
            if argv[3:6] == ['shell', 'input', 'text'] and not getattr(self, 'interrupted', False):
                self.interrupted = True; self.dialog = 1
            return original(runtime, task, argv, cwd, seconds)
        self.adb = adb
        result = self.run_device(self.node(AC3))
        self.assertTrue(result['passed'], result.get('detail'))
        self.assertEqual([a['step'] for a in result['environment']['actions']], ['save'])

    def test_physical_device_with_a_stuck_dialog_is_never_rebooted(self):
        from onecrew.delivery_device_env import EnvironmentUnusable
        self.dialog = 99
        with self.assertRaises(EnvironmentUnusable) as stuck: self.run_device(self.node(AC3))
        self.assertEqual(rc.classify_error(stuck.exception), 'environment')
        self.assertFalse(any(a[:1] in (['emu'], ['reboot']) for a in self.sent))
        self.assertFalse(any(a[0] == 'install' for a in self.sent))

    def test_absent_emulator_is_booted_only_when_the_envelope_names_it(self):
        states = iter(['absent'])
        original = self.adb
        def adb(runtime, task, argv, cwd, seconds):
            if argv[3:] == ['get-state'] and next(states, 'device') == 'absent': return 1, '', 'not found'
            return original(runtime, task, argv, cwd, seconds)
        self.adb = adb
        with patch('onecrew.delivery_device_env.boot_emulator', return_value={'booted': True}) as boot:
            result = self.run_device(self.node(AC3, emulator={'avd': 'Trial', 'avd_home': str(self.root)}))
        self.assertTrue(result['passed'], result.get('detail')); boot.assert_called_once()
        self.assertTrue(result['environment']['emulator_started']); self.assertTrue(result['environment']['emulator_stopped'])
        states = iter(['absent'])
        with patch('onecrew.delivery_device_env.boot_emulator') as boot:
            with self.assertRaisesRegex(LedgerError, 'not ready'): self.run_device(self.node(AC3))
        boot.assert_not_called()


# Real crash buffer lines from trial 5 (TASK-dc9d90b9, emulator Android 16, 12/10/2026), shortened.
NATIVE_CRASH = """10-12 16:51:57.381  5711  5711 F DEBUG   : Build fingerprint: 'google/sdk_gphone64_x86_64/emu64xa:16/BE4B.251210.005/14574095:user/release-keys'
10-12 16:51:57.381  5711  5711 F DEBUG   : pid: 5668, tid: 5690, name: 1.raster  >>> vn.onetech.trial.settings_trial <<<
10-12 16:51:57.381  5711  5711 F DEBUG   : signal 11 (SIGSEGV), code 2 (SEGV_ACCERR), fault addr 0x000079bc9108d000 (read)
10-12 16:51:57.381  5711  5711 F DEBUG   : backtrace:
10-12 16:51:57.381  5711  5711 F DEBUG   :       #00 pc 0000000000096b99  /apex/com.android.runtime/lib64/bionic/libc.so (memmove_avx2+1721)
10-12 16:51:57.382  5711  5711 F DEBUG   :       #01 pc 0000000001ae9e76  /data/app/~~yLx==/vn.onetech.trial.settings_trial-3_X==/base.apk!libflutter.so (offset 0x538c000)
"""
JAVA_CRASH = """10-12 17:00:00.000  6000  6000 E AndroidRuntime: FATAL EXCEPTION: main
10-12 17:00:00.000  6000  6000 E AndroidRuntime: Process: vn.onetech.trial.settings_trial, PID: 6000
10-12 17:00:00.000  6000  6000 E AndroidRuntime: java.lang.IllegalStateException: secret account 0912345678 not found
"""


class AppCrashTests(DeviceRun):
    """Trial 5: after a native Flutter raster crash every launch crashed; OneCrew read it as 'another window has focus'."""

    def crash(self, text, launches_dead=99, restart_fixes=False):
        self.crash_text, self.launches = text, 0
        original = self.adb
        def adb(runtime, task, argv, cwd, seconds):
            args = argv[3:]
            if args[:4] == ['shell', 'am', 'start', '-W']:
                self.launches += 1; self.dead = self.launches <= launches_dead
                if self.dead: self.focus = 'mCurrentFocus=Window{9 u0 com.google.android.apps.nexuslauncher/.NexusLauncherActivity}\n'
                else: self.focus = APP_FOCUS
            if args[:2] == ['emu', 'kill'] and restart_fixes: launches_dead_box[0] = 0
            if args[:3] == ['logcat', '-d', '-b']: return 0, self.crash_text if self.dead else '', ''
            return original(runtime, task, argv, cwd, seconds)
        launches_dead_box = [launches_dead]
        self.adb = adb
        return launches_dead_box

    def test_crash_summary_keeps_structure_only(self):
        from onecrew.delivery_device_env import crash_summary
        self.assertEqual(crash_summary(NATIVE_CRASH, PKG), {'kind': 'native', 'signal': 'SIGSEGV', 'thread': '1.raster',
                                                          'libraries': ['libc.so', 'libflutter.so']})
        java = crash_summary(JAVA_CRASH, PKG)
        self.assertEqual(java, {'kind': 'java', 'thread': 'main', 'exception': 'java.lang.IllegalStateException'})
        self.assertNotIn('0912345678', json.dumps(java))
        self.assertIsNone(crash_summary(NATIVE_CRASH, 'other.app'))

    def test_a_dead_app_is_a_crash_finding_not_another_window(self):
        self.crash(NATIVE_CRASH)
        result = self.run_device(self.node(AC3))
        self.assertFalse(result['passed'])
        self.assertNotIn('Another window', result['detail'], 'RED-APP-CRASH: a crashed app read as a focus problem')
        self.assertIn('native SIGSEGV in libc.so,libflutter.so', result['detail'])
        self.assertEqual(result['app_crash']['kind'], 'native')
        # On the approved emulator the same receipt is an environment finding (restart then retry), elsewhere a device finding.
        self.assertEqual(rc.classify_receipt(self.node(AC3), result)[0], 'device_assertion')

    def test_native_crash_at_launch_restarts_the_approved_emulator_once(self):
        box = self.crash(NATIVE_CRASH, launches_dead=1)
        with patch('onecrew.delivery_device_env.boot_emulator', return_value={'booted': True}) as boot:
            result = self.run_device(self.node(AC3, emulator={'avd': 'Trial', 'avd_home': str(self.root)}))
        self.assertTrue(result['passed'], result.get('detail')); boot.assert_called_once()
        self.assertTrue(result['environment']['crash_restart'])
        self.assertEqual([a['action'] for a in result['environment']['actions']][:2], ['emulator_stop', 'emulator_boot'])
        self.assertEqual(sum(a[0] == 'install' for a in self.sent), 1)  # the verified install is reused, not repeated

    def test_java_crash_is_a_product_finding_and_never_restarts(self):
        self.crash(JAVA_CRASH)
        with patch('onecrew.delivery_device_env.boot_emulator') as boot:
            result = self.run_device(self.node(AC3, emulator={'avd': 'Trial', 'avd_home': str(self.root)}))
        boot.assert_not_called()
        self.assertEqual((result['passed'], result['failure_kind']), (False, 'product'))
        self.assertEqual(result['app_crash']['exception'], 'java.lang.IllegalStateException')
        self.assertEqual(rc.classify_receipt(self.node(AC3), result)[0], 'product')

    def test_a_previous_native_crash_restarts_the_emulator_before_install(self):
        n = self.node(AC3, emulator={'avd': 'Trial', 'avd_home': str(self.root)})
        directory = da.device_directory(self.runtime, 'task', n, {'generation': 0}); directory.mkdir(parents=True, exist_ok=True)
        (directory/'receipt.json').write_text(json.dumps({'passed': False, 'app_crash': {'kind': 'native'}}))
        with patch('onecrew.delivery_device_env.boot_emulator', return_value={'booted': True}) as boot:
            result = self.run_device(n)
        self.assertTrue(result['passed'], result.get('detail')); boot.assert_called_once()
        self.assertIn('previous run', result['environment']['actions'][0]['detail'])

    def test_own_crash_dialog_is_not_a_system_hang(self):
        from onecrew.delivery_device_env import health
        calls = {('shell', 'dumpsys', 'window'): 'mCurrentFocus=Window{52 u0 Application Error: ' + PKG + '}\n',
                 ('shell', 'dumpsys', 'power'): 'mWakefulness=Awake'}
        state = health(lambda *a: calls[a], PKG)
        self.assertEqual((state['system_dialog'], state['app_crash_dialog']), (False, True))
        calls[('shell', 'dumpsys', 'window')] = 'mCurrentFocus=Window{53 u0 Application Not Responding: com.android.systemui}\n'
        self.assertEqual(health(lambda *a: calls[a], PKG)['system_dialog'], True)


class RedEvidenceRepairTests(unittest.TestCase):
    """Trial 6 (TASK-71ae1655): production was right and all tests passed, but the red test called a helper added by the
    change, so it could not load on the unchanged code. Two repair generations then hit 'No production fix in patch'
    because the only correct repair touches tests, and OneCrew asked."""
    RED = [{'test': 'test/host_validation_test.dart', 'error_pattern': 'Found 0 widgets with text "Địa chỉ không hợp lệ"'}]
    RECEIPT = {'passed': False, 'failure_kind': 'test', 'errors': [], 'counts': {'failed': 0, 'passed': 6, 'skipped': 0},
               'red': [{'test': 'test/host_validation_test.dart', 'behavioral_failure': False, 'counts': {'failed': 1, 'passed': 0}}]}

    def state(self):
        nodes = [{'id': 'change-1', 'kind': 'change', 'depends': [], 'config': {}},
                 {'id': 'tests', 'kind': 'regression', 'depends': ['change-1'], 'config': {'red': self.RED, 'repair_node': 'change-1'}}]
        return {'plan': {'nodes': nodes, 'max_repairs': 2, 'acceptance': [{'id': 'AC1', 'nodes': ['tests']}]},
                'delivery': {'repairs': 0, 'generation': 0, 'history': [], 'source': {'hash': 'src'}, 'criteria': {'AC1': 'pending'},
                             'nodes': {'change-1': {'phase': 'passed', 'generation': 0, 'receipt': {'passed': True}, 'child': 'TASK-x'},
                                       'tests': {'phase': 'blocked', 'generation': 0, 'receipt': None, 'child': None}}}}

    def test_red_only_failure_is_a_tests_only_repair_with_actionable_feedback(self):
        from onecrew.solution_delivery import Delivery
        s = self.state(); node = s['plan']['nodes'][1]
        self.assertTrue(Delivery._repair(Delivery.__new__(Delivery), s, node, dict(self.RECEIPT)))
        row = s['delivery']['nodes']['change-1']
        self.assertEqual(row.get('scope'), 'tests', 'RED-RED-ONLY-REPAIR: a red-evidence repair still demanded a production change')
        self.assertIn('do NOT change them', row['feedback']); self.assertIn('did not load', row['feedback'])
        self.assertIn('Found 0 widgets', row['feedback'])

    def test_a_real_failing_test_still_needs_a_production_fix(self):
        from onecrew.solution_delivery import Delivery, red_only
        failing = dict(self.RECEIPT, counts={'failed': 2, 'passed': 4, 'skipped': 0}, errors=[{'name': 'rejects http'}])
        s = self.state(); node = s['plan']['nodes'][1]
        self.assertIsNone(red_only(node, failing))
        Delivery._repair(Delivery.__new__(Delivery), s, node, failing)
        self.assertNotIn('scope', s['delivery']['nodes']['change-1'])

    def test_tests_only_scope_cannot_be_claimed_outside_a_delivery(self):
        from onecrew.owned_intake import submit
        from tests.test_interventions import LedgerFixture
        f = LedgerFixture(self)
        with self.assertRaisesRegex(LedgerError, 'delivery coordinator'):
            submit(f.ledger, 'goal text for a child', 'k', mode='change', _delivery_scope='tests')


class TestsOnlyPatchTests(unittest.TestCase):
    def setUp(self):
        from tests.test_native_change import NativeChangeTests
        self.case = NativeChangeTests('test_preparation_progress_is_durable_before_worker_call'); self.case.setUp()
        self.addCleanup(self.case.doCleanups)

    def patch(self, files, scope):
        from onecrew.native_change import install_candidate
        state = self.case.run.state(self.case.task)[1]
        return install_candidate(self.case.run, state, {'report': 'x' * 30, 'question': '', 'files': files}, self.case.recipe, scope)

    def test_scope_tests_accepts_a_test_only_patch_and_refuses_production_edits(self):
        from onecrew.native_change import PatchIncomplete
        test_only = [{'path': 'app/test/main_test.dart', 'text': '// red test rewritten through the existing API\n'}]
        with self.assertRaisesRegex(PatchIncomplete, 'No production fix'): self.patch(test_only, None)
        self.patch(test_only, 'tests')
        same = test_only + [{'path': 'app/lib/main.dart', 'text': 'int add(int a,int b)=>a-b;\n'}]  # production unchanged
        self.patch(same, 'tests')
        changed = test_only + [{'path': 'app/lib/main.dart', 'text': 'int add(int a,int b)=>a+b;\n'}]
        with self.assertRaisesRegex(PatchIncomplete, 'only test files'): self.patch(changed, 'tests')


class EnvelopeEmulatorTests(unittest.TestCase):
    def test_only_an_emulator_serial_may_be_booted(self):
        from onecrew.delivery_device_env import validate_emulator
        self.assertEqual(validate_emulator({'avd': 'Trial', 'avd_home': None}, 'emulator-5554')['avd'], 'Trial')
        for value, serial in (({'avd': 'Trial', 'avd_home': None}, 'R5CW32Y7F9W'), ({'avd': 'x;rm', 'avd_home': None}, 'emulator-5554'),
                              ({'avd': 'Trial', 'avd_home': 'relative'}, 'emulator-5554'), ({'avd': 'Trial'}, 'emulator-5554'),
                              ({'avd': 'Trial', 'avd_home': None}, 'emulator-5555')):
            with self.assertRaises(LedgerError): validate_emulator(value, serial)


class PlannedDeviceTests(unittest.TestCase):
    """The envelope names the emulator OneCrew may boot; a planned scenario is the only one it may recalibrate."""

    def stages(self, **device):
        from tests.test_delivery_autopilot import envelope
        value = {'serial': 'emulator-5554', 'scenario': 'planned', 'scenario_ref': None, 'scenario_sha256': None,
                 'private_reference': None, 'private_version': 'none', 'valid_until': '2026-10-13T00:00:00+07:00',
                 'replay_safe': True, 'required': True}
        value.update(device)
        env = envelope(build={'variant': 'debug', 'config_reference': None, 'config_version': 'none', 'signer': 'debug'},
                       apk_audit={'require_16kb': False, 'max_bytes': 1000}, device=value)
        env['acceptance'].append({'id': 'AC3', 'text': 'On the device the error shows.', 'evidence': ['device']})
        return env

    def test_compiled_device_node_carries_calibration_and_the_approved_emulator(self):
        from tests.test_delivery_autopilot import PROPOSAL, discovery
        from onecrew.delivery_planner import compile_plan, covers, validate_envelope
        root = Path(tempfile.mkdtemp())
        emulator = {'avd': 'OneCrew_Trial', 'avd_home': str(root)}
        env = validate_envelope(self.stages(emulator=emulator))
        proposal = dict(PROPOSAL, scenario={'steps': AC3, 'cleanup': []})
        facts = dict(discovery(root), private_keys=['bad_port'])
        plan, scenario, findings = compile_plan('goal', env, facts, proposal, 'SOL@x', 'a' * 64)
        self.assertEqual(findings, [])
        config = next(n for n in plan['nodes'] if n['kind'] == 'device')['config']
        self.assertEqual((config['calibration'], config['emulator']), ('onecrew', emulator))
        self.assertEqual(covers(env, plan), [])
        config['emulator'] = {'avd': 'Other', 'avd_home': None}
        self.assertIn('device emulator differs from envelope', covers(env, plan))
        pinned = validate_envelope(self.stages(scenario='pinned', scenario_ref=str(root / 's.json'), scenario_sha256='0' * 64))
        config.pop('emulator')
        self.assertIn('scenario calibration is only for a scenario OneCrew planned', covers(pinned, plan))
        with self.assertRaises(LedgerError): validate_envelope(self.stages(serial='R5CW32Y7F9W', emulator=emulator))

    def test_preflight_defers_an_absent_approved_emulator_and_requires_its_avd(self):
        from onecrew.delivery_steps import preflight, fingerprint
        from tests.test_solution_delivery import DeliveryTests
        case = DeliveryTests('test_restart_does_not_repeat_verified_nodes'); case.setUp(); self.addCleanup(case.tmp.cleanup)
        r, t = case.create(); seq, s = r.state(t)
        sdk = Path(case.tmp.name) / 'sdk-android'; (sdk / 'platform-tools').mkdir(parents=True); (sdk / 'emulator').mkdir()
        adb = sdk / 'platform-tools' / 'adb.exe'; adb.write_text('fixture'); (sdk / 'emulator' / 'emulator.exe').write_text('fixture')
        scenario = Path(case.tmp.name) / 'scenario.json'
        scenario.write_text(json.dumps({'version': 1, 'activity': PKG + '.MainActivity', 'steps': AC3, 'cleanup': []}))
        avds = Path(case.tmp.name) / 'avds'; avds.mkdir()
        config = {'build_node': 'build', 'adb': str(adb), 'serial': 'emulator-5554', 'package_id': PKG, 'scenario': str(scenario),
                  'scenario_sha256': file_hash(scenario), 'private_reference': None, 'private_version': 'none', 'timeout_seconds': 600,
                  'optional': False, 'emulator': {'avd': 'Trial', 'avd_home': str(avds)}}
        s['plan']['nodes'].insert(2, {'id': 'device', 'kind': 'device', 'depends': ['review'], 'config': config})
        source = fingerprint(case.root, ['app'])
        with patch('onecrew.delivery_steps.bounded', return_value=(1, '', 'not found')),              patch('onecrew.delivery_device_env.ensure_server', return_value=True):
            with self.assertRaisesRegex(LedgerError, 'AVD unavailable'): preflight(r, t, s, source)
            (avds / 'Trial.ini').write_text('avd.ini.encoding=UTF-8')
            receipt = preflight(r, t, s, source)
        self.assertEqual((receipt['emulator_boot_at_stage'], receipt['optional_device_missing']), (True, False))
        self.assertIn(str((sdk / 'emulator' / 'emulator.exe').resolve()), receipt['tools'])


class CalibrationTests(DeviceRun):
    def failing(self, steps):
        n = self.node(steps); result = self.run_device(n)
        self.assertEqual(result['failure_kind'], 'selector')
        return n, result, json.loads(Path(result['ui_snapshot']['file']).read_text(encoding='utf-8'))

    def test_selector_failure_of_a_planned_replay_safe_scenario_is_calibrated(self):
        n, result, _ = self.failing([AC3[0], {'id': 'bad', 'operation': 'type', 'arguments': {'selector': {'resource-id': 'port'}, 'private_key': 'bad_port'}}])
        self.assertEqual(rc.classify_receipt(n, result)[0], 'scenario_selector')
        pinned = dict(n, config={k: v for k, v in n['config'].items() if k != 'calibration'})
        self.assertEqual(rc.classify_receipt(pinned, result)[0], 'device_assertion')
        self.assertEqual(rc.POLICY['scenario_selector'], ('calibrate', 2))

    def test_validator_keeps_operations_passed_steps_and_assertions(self):
        steps = AC3[:3] + [{'id': 'error', 'operation': 'wait_for', 'arguments': {'selector': {'resource-id': 'portError'}, 'timeout_seconds': 5}}]
        self.port = '70000'; self.error = True
        n, result, view = self.failing(steps)
        old = da.scenario(n['config']['scenario'], n['config']['scenario_sha256'])
        failure = result['selector_failure']
        def revise(**changes):
            new = json.loads(json.dumps(old))
            for step in new['steps']:
                if step['id'] in changes: step['arguments']['selector'] = changes[step['id']]
            return new
        from onecrew import delivery_calibrate as cal
        self.assertEqual(cal.check(old, revise(error={'text': 'Cổng phải từ 1 đến 65535'}), failure, view), [])
        self.assertIn('already passed', ' '.join(cal.check(old, revise(save={'content-desc': 'LƯU'}, error={'text': 'Cổng phải từ 1 đến 65535'}), failure, view)))
        self.assertIn('exactly one node', ' '.join(cal.check(old, revise(error={'class': 'android.view.View'}), failure, view)))
        weaker = json.loads(json.dumps(old)); weaker['steps'][3]['operation'] = 'assert_ui'
        self.assertIn('id and operation', ' '.join(cal.check(old, weaker, failure, view)))
        # An assertion that named a label must keep it (here: shortened to a weaker prefix is refused).
        labelled = json.loads(json.dumps(old)); labelled['steps'][3]['arguments']['selector'] = {'text': 'Cổng phải từ 1 đến 65535'}
        stronger = json.loads(json.dumps(labelled)); stronger['steps'][3]['arguments']['selector'] = {'text': 'Cổng phải từ 1'}
        self.assertIn('expected label', ' '.join(cal.check(labelled, stronger, failure, view)))


class CalibrationDeliveryTests(unittest.TestCase):
    setUp = base.DeliveryTests.setUp
    create = base.DeliveryTests.create

    def delivery(self, receipts, proposals):
        """Root with a planned device stage; device receipts and calibration proposals are scripted."""
        r, t = self.create(); r.run(t)
        seq, s = r.state(t)
        scenario = Path(self.tmp.name)/'scenario.json'
        scenario.write_text(json.dumps({'version': 1, 'activity': PKG + '.MainActivity', 'steps': AC3, 'cleanup': []}))
        s['plan']['nodes'].insert(2, {'id': 'device', 'kind': 'device', 'depends': ['review'], 'config': {
            'optional': False, 'replay_safe': True, 'calibration': 'onecrew', 'scenario': str(scenario), 'scenario_sha256': file_hash(scenario)}})
        s['plan']['nodes'][-1]['depends'].append('device')
        s['plan']['acceptance'].append({'id': 'AC3', 'text': 'Device', 'nodes': ['device']})
        s['delivery']['nodes']['device'] = {'phase': 'pending', 'generation': 0, 'receipt': None, 'child': None}
        s['delivery']['criteria']['AC3'] = 'pending'; r.persist(t, seq, s)
        source = s['delivery']['source']['hash']
        real = __import__('onecrew.delivery_steps', fromlist=['execute']).execute
        runs = iter(receipts); scenarios = []
        def execute(runtime, task, state, n, row):
            if n['kind'] == 'device':
                scenarios.append(da.active_scenario(n, row))
                return dict(next(runs), source=source)
            if n['kind'] == 'handover': return real(runtime, task, state, n, row)
            return {'passed': True, 'source': source, 'counts': {'passed': 1, 'skipped': 0}, 'red': [{'test': 'x'}]}
        answers = iter(proposals)
        def invoke(task, seq, state, stage, prompt, schema, profile):
            state['pending'] = None; self.prompts.append(prompt)
            return seq, dict(next(answers), _native={})
        self.prompts = []
        with patch('onecrew.delivery_steps.execute', side_effect=execute), patch.object(r, '_invoke', side_effect=invoke):
            for _ in range(12):
                s = r.run(t)
                if s['phase'] in ('completed', 'waiting'): break
        return r, t, s, scenarios

    def selector_failure(self, step, reason='not_found', nodes=None):
        view = Path(self.tmp.name)/('ui-' + step + '.json')
        view.write_text(json.dumps({'step': step, 'package': PKG, 'nodes': nodes or da.snapshot(screen(port='70000', error=True), PKG)}))
        return {'passed': False, 'failure_kind': 'selector', 'detail': 'UI wait timeout: selector never matched exactly one visible node.',
                'steps': [{'id': 'title'}, {'id': 'bad'}, {'id': 'save'}], 'scenario_started': True,
                'selector_failure': {'step': step, 'operation': 'wait_for', 'reason': reason, 'matches': 0},
                'ui_snapshot': {'file': str(view), 'sha256': file_hash(view), 'nodes': 5}}

    def test_live_ui_calibration_reruns_the_stage_and_completes(self):
        from onecrew import delivery_calibrate as cal  # noqa: F401  (capability probe: module must exist)
        broken = json.loads(json.dumps(AC3)); broken[3]['arguments']['selector'] = {'resource-id': 'portError'}
        fixed = json.loads(json.dumps(broken)); fixed[3]['arguments']['selector'] = {'content-desc': 'Cổng phải từ 1 đến 65535'}
        receipts = [self.selector_failure('error'), {'passed': True, 'steps': [], 'cleanup': []}]
        r, t, s, used = self.delivery(receipts, [{'verdict': 'revise', 'steps': fixed, 'cleanup': [], 'reason': 'portError is a Flutter Key'}])
        # The first run used the sealed scenario; the rerun used OneCrew's calibrated revision.
        self.assertEqual(s['phase'], 'completed', s['message'])
        self.assertEqual([u[2] for u in used], [0, 1])
        row = s['delivery']['nodes']['device']
        self.assertEqual((row['calibrations'], row['scenario']['changed_steps']), (1, ['error']))
        self.assertIn('calibrate', [x['action'] for x in s['delivery']['recoveries']])
        self.assertIn('Flutter', self.prompts[0])

    def test_expected_text_missing_on_screen_is_a_product_repair_without_a_model_call(self):
        nodes = da.snapshot(screen(port='70000'), PKG)  # no error shown after save: the product did not validate
        r, t, s, used = self.delivery([self.selector_failure('error', 'timeout', nodes)], [])
        self.assertEqual(self.prompts, [])  # decided by code: no model call, no weaker scenario
        row = s['delivery']['nodes']['device']
        self.assertEqual((row['receipt']['failure_kind'], row.get('calibrations', 0)), ('product', 0))
        # This fixture plan has no change slice to repair, so the product finding becomes the one question.
        self.assertEqual((s['phase'], s['delivery']['escalation']['class']), ('waiting', 'product'))

    def test_calibration_is_bounded_then_one_question(self):
        from onecrew import delivery_calibrate as cal
        tries = []
        for selector in ({'content-desc': 'Cổng phải từ 1 đến 65535'}, {'text': 'Cổng phải từ 1 đến 65535'}):
            v = json.loads(json.dumps(AC3)); v[3]['arguments']['selector'] = selector
            tries.append({'verdict': 'revise', 'steps': v, 'cleanup': [], 'reason': 'try'})
        r, t, s, used = self.delivery([self.selector_failure('error') for _ in range(3)], tries)
        self.assertEqual(s['phase'], 'waiting', s['message'])
        self.assertEqual(s['delivery']['nodes']['device']['calibrations'], cal.MAX_CALIBRATIONS)
        self.assertEqual([u[2] for u in used], [0, 1, 2])
        self.assertEqual(s['delivery']['escalation']['class'], 'scenario_selector')
        self.assertEqual(len(self.prompts), 2)

if __name__ == '__main__':
    unittest.main()
