"""Codex review of autonomy round 2 (REVIEW-CODEX-ONECREW-ROUND2-742a139-2026-10-12.txt), reproduced through APIs
that exist on 742a139, so each finding is red there by assertion:

P1-1 calibration could weaken an assertion (drop checked, change an absence label) and turn a fail into a pass;
P1-2 the emulator on the pinned serial was never proven to be the approved AVD before install/input/kill;
P2   ownership of an emulator OneCrew booted was lost across attempts, so it was left running after a pass."""
import copy
import json
from unittest.mock import patch
import unittest

from onecrew import delivery_android as da
from onecrew import delivery_calibrate as cal
from onecrew.ledger import LedgerError
from tests.test_autonomy_round2 import AC3, DeviceRun

PKG = 'example.app'
EMU = {'avd': 'ApprovedTrial', 'avd_home': None}


def scenario(*steps, cleanup=()):
    return {'steps': list(steps), 'cleanup': list(cleanup)}


def step(i, op, selector):
    return {'id': i, 'operation': op, 'arguments': {'selector': selector}}


class CalibrationEquivalenceTests(unittest.TestCase):
    """P1-1: what a step checks may not change; only how its node is located."""

    def view(self, *nodes):
        return {'package': PKG, 'nodes': list(nodes)}

    def test_dropping_an_expected_state_is_refused(self):
        view = self.view({'text': 'Remember', 'checked': 'false', 'class': 'android.widget.CheckBox', 'bounds': '[0,0][100,100]'})
        old = scenario(step('verify', 'assert_ui', {'text': 'Remember', 'checked': 'true'}))
        new = copy.deepcopy(old); new['steps'][0]['arguments']['selector'].pop('checked')
        self.assertTrue(cal.check(old, new, {'step': 'verify'}, view), 'RED-P1-1A: dropping checked=true was accepted (fail -> pass)')

    def test_changing_an_absence_check_is_refused(self):
        view = self.view({'hint': 'Port', 'class': 'android.widget.EditText', 'bounds': '[0,0][100,100]'})
        old = scenario(step('edit', 'tap', {'hint': 'Port', 'class': 'android.widget.TextView'}),
                       step('no-save', 'assert_absent', {'text': 'Saved'}))
        new = copy.deepcopy(old)
        new['steps'][0]['arguments']['selector'] = {'hint': 'Port'}                 # a legitimate locator fix
        new['steps'][1]['arguments']['selector'] = {'text': 'Saved successfully'}   # hides 'Saved' from the absence check
        findings = cal.check(old, new, {'step': 'edit'}, view)
        self.assertTrue(any('no-save' in f for f in findings), 'RED-P1-1B: a weakened absence check was accepted: ' + str(findings))

    def test_future_assertions_and_cleanup_keep_their_conditions(self):
        view = self.view({'content-desc': 'LƯU', 'class': 'android.widget.Button', 'bounds': '[0,0][100,100]'})
        old = scenario(step('save', 'tap', {'text': 'LƯU', 'class': 'android.widget.TextView'}),
                       step('saved', 'assert_ui', {'text': 'Saved'}),
                       cleanup=[step('off', 'tap', {'text': 'Remember', 'checked': 'true'})])
        widened = copy.deepcopy(old)
        widened['steps'][0]['arguments']['selector'] = {'content-desc': 'LƯU'}
        widened['steps'][1]['arguments']['selector'] = {'text': 'Saved successfully'}
        self.assertTrue(any(f.startswith('saved:') for f in cal.check(old, widened, {'step': 'save'}, view)),
                        'RED-P1-1C: a future assertion was re-pointed to another label')
        cleaned = copy.deepcopy(old)
        cleaned['steps'][0]['arguments']['selector'] = {'content-desc': 'LƯU'}
        cleaned['cleanup'][0]['arguments']['selector'] = {'text': 'Remember'}
        self.assertTrue(any(f.startswith('off:') for f in cal.check(old, cleaned, {'step': 'save'}, view)),
                        'RED-P1-1D: a cleanup step lost its checked condition')

    def test_relocating_the_failing_locator_with_its_identity_kept_is_accepted(self):
        # Follow-up review of b19b35e: only the failing step, with resource-id/class unchanged and labels verbatim.
        view = self.view({'content-desc': 'LƯU', 'class': 'android.widget.Button', 'bounds': '[0,0][100,100]'},
                         {'hint': 'Port, Port must be 1-65535', 'class': 'android.widget.EditText', 'focused': 'true', 'bounds': '[0,200][100,300]'})
        old = scenario(step('save', 'tap', {'text': 'LƯU', 'class': 'android.widget.TextView'}),
                       step('field', 'tap', {'hint': 'Port', 'focused': 'false'}),
                       step('error', 'assert_ui', {'text': 'Port must be 1-65535'}))
        new = copy.deepcopy(old)
        new['steps'][1]['arguments']['selector'] = {'hint': 'Port'}  # merged part kept verbatim; incidental focus dropped (trial 5)
        self.assertEqual(cal.check(old, new, {'step': 'field'}, view), [])
        # A class the node contradicts is not relocated (round 3 accepted TextView -> Button; no longer).
        moved = copy.deepcopy(old); moved['steps'][0]['arguments']['selector'] = {'content-desc': 'LƯU', 'class': 'android.widget.Button'}
        self.assertTrue(cal.check(old, moved, {'step': 'save'}, view))

    def test_a_label_less_locator_cannot_be_repointed(self):
        view = self.view({'hint': 'Port', 'class': 'android.widget.EditText', 'bounds': '[0,0][100,100]'})
        old = scenario(step('edit', 'tap', {'resource-id': 'port'}))
        new = copy.deepcopy(old); new['steps'][0]['arguments']['selector'] = {'hint': 'Port'}
        self.assertTrue(cal.check(old, new, {'step': 'edit'}, view))


class EmulatorIdentityTests(DeviceRun):
    """P1-2: the instance on the serial must provably be the approved AVD before anything changes it."""

    def blocked_run(self, **emulator):
        n = self.node(AC3, emulator=dict(EMU, **emulator)); outcome = None
        with patch('onecrew.delivery_device_env.boot_emulator', return_value={'booted': True}) as boot:
            try: outcome = self.run_device(n)
            except LedgerError as error: outcome = error
        return outcome, boot

    def changed(self):
        return [a for a in self.sent if a[0] == 'install' or a[:2] == ['shell', 'input'] or a[:2] == ['emu', 'kill'] or a[:2] == ['shell', 'am']]

    def test_another_avd_on_the_serial_gets_no_install_input_or_kill(self):
        self.avd = 'OtherUserAVD'; self.dialog = 99
        outcome, boot = self.blocked_run()
        self.assertIsInstance(outcome, LedgerError, 'RED-P1-2: ran a scenario on an unapproved AVD')
        self.assertIn('not the approved AVD', str(outcome)); self.assertEqual(self.changed(), [])
        boot.assert_not_called()

    def test_an_unverifiable_identity_blocks(self):
        self.avd = None
        outcome, _ = self.blocked_run()
        self.assertIsInstance(outcome, LedgerError); self.assertIn('unverifiable', str(outcome)); self.assertEqual(self.changed(), [])

    def test_the_approved_avd_opened_by_the_user_is_used_but_never_killed(self):
        self.avd = 'ApprovedTrial'; self.dialog = 99  # stuck: the old runtime restarted (killed) it
        outcome, boot = self.blocked_run()
        self.assertNotIn(['emu', 'kill'], self.sent, 'RED-P1-2: killed an emulator OneCrew did not boot')
        boot.assert_not_called(); self.assertIsInstance(outcome, LedgerError)


class EmulatorOwnershipTests(DeviceRun):
    """P2: ownership of a booted instance survives attempts and coordinator restarts; only it is stopped."""

    def test_boot_then_failure_then_retry_success_stops_the_owned_instance(self):
        self.avd = 'ApprovedTrial'; self.absent = 1
        failing = [AC3[0], {'id': 'bad', 'operation': 'type', 'arguments': {'selector': {'resource-id': 'port'}, 'private_key': 'bad_port'}}]
        with patch('onecrew.delivery_device_env.boot_emulator', return_value={'booted': True}) as boot:
            first = self.run_device(self.node(failing, emulator=EMU))
            self.assertFalse(first['passed'])
            self.sent.clear()
            second = self.run_device(self.node(AC3, emulator=EMU))  # a new attempt: nothing carried in memory
        self.assertTrue(second['passed'], second.get('detail')); boot.assert_called_once()
        self.assertIn(['emu', 'kill'], self.sent, 'RED-P2: the instance OneCrew booted was left running after the retry passed')
        self.assertEqual(second['environment']['emulator_cleanup'], 'stopped')

    def test_a_replaced_instance_is_not_stopped(self):
        self.avd = 'ApprovedTrial'; self.boots = 7
        (self.root/'emulator-emulator-5554.json').write_text(json.dumps(
            {'serial': 'emulator-5554', 'avd': 'ApprovedTrial', 'boot_id': '00000006-0000-4000-8000-000000000000'}))
        result = self.run_device(self.node(AC3, emulator=EMU))
        self.assertTrue(result['passed'], result.get('detail')); self.assertNotIn(['emu', 'kill'], self.sent)
        self.assertEqual(result['environment']['emulator_cleanup'], 'borrowed_left_running')


if __name__ == '__main__':
    unittest.main()
