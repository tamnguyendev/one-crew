"""Round 7 / T49d [E5] — the rollback SCRIPT (python -m wfkit.rollback_cli) on the S2 fixture of tests.test_wf_namespace_compat.

Per N-table case (05 T49): N1 -> B1, N2 -> B3, N3 -> B2+B3, N4 -> B1+B3, N7 -> B2 are refused with exit 3 and a message naming exactly that
block set; N5 is allowed (exit 0). The script is driven as a subprocess. The decision is the existing gate (tests.wf_rollback.rollback_drill;
with --venv, wfkit.upgrade_drill.guard_swap with the installed build's own scan).

InstalledVenv builds ONE wheel of this checkout and ONE venv per class (setUpClass) and checks, with the test's own `pip list` and the
installed RECORD hash taken before/after each script run, that a refusal does not (partially) uninstall the new build.
No owner verb runs; every state is a disposable copy of S2.
"""
import json
import os
import subprocess
import sys
import unittest
import uuid
from pathlib import Path

import tests.test_wf_namespace_compat as base
from tests import wf_oldversion as ov
from wfkit import rollback_cli

ROOT = Path(__file__).resolve().parents[1]
# The N-table (05 T49, T49d rows), exactly as tests.test_wf_namespace_compat.test_n1_to_n7_gate_branches builds it.
CASES = {'N1': (('R4', 'DUPk'), None, ('B1',)), 'N2': (('R2', 'R4'), 'accepted', ('B3',)),
         'N3': (('R2',), 'accepted', ('B2', 'B3')), 'N4': (('R4',), 'stopped_with_report', ('B1', 'B3')),
         'N5': (('R2', 'R4', 'DUPk'), 'accepted', ()), 'N7': (('R2', 'DUPk'), 'accepted', ('B2',))}
REFUSED = ('N1', 'N2', 'N3', 'N4', 'N7')


def script(state, out, python=None):
    env = {k: v for k, v in os.environ.items() if k not in ('ONECREW_ACTOR', 'CLAUDECODE', 'CLAUDE_CODE_CHILD_SESSION', 'PYTHONPATH')}
    env['PYTHONPATH'] = str(ROOT)
    command = [sys.executable, '-X', 'utf8', '-m', 'wfkit.rollback_cli', '--state-root', str(state), '--out', str(out)]
    if python: command += ['--venv', str(python)]
    result = subprocess.run(command, cwd=str(ROOT), env=env, capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=600)
    return result.returncode, (result.stdout + result.stderr).strip()


def expected_message(blocks):
    return 'refused: ' + ', '.join(blocks) + ' (remaining block conditions; the new build stays installed)'


class _S2Cases(base.NamespaceCompatTests):
    for _name in [n for n in dir(base.NamespaceCompatTests) if n.startswith('test_')]:
        locals()[_name] = None
    del _name

    def prepared(self, case):
        accepted, active, _ = CASES[case]
        state = self.copy()
        for label in accepted:
            self.accept(state, label)
        if case == 'N4':                                    # R2 stopped_with_report, DUPk paused (stopped) by the new code's events
            ov.make_stopped(state, self.ids['R2'], 'r2')
            ov.make_stopped(state, self.ids['DUPk'], 'dup')
        if active:
            self.write_active(state, active)
        return state

    def out(self):
        return self.runs / ('rb-' + uuid.uuid4().hex[:8])


class RollbackScript(_S2Cases):
    def test_e5_refused_cases_exit_3_and_name_the_exact_remaining_block_set(self):
        for case in REFUSED:
            with self.subTest(case=case):
                out = self.out()
                code, text = script(self.prepared(case), out)
                self.assertEqual(code, rollback_cli.EXIT_REFUSED, text)
                self.assertEqual(text, expected_message(CASES[case][2]))
                receipt = json.loads((out / 'receipt.json').read_text(encoding='utf-8'))
                self.assertEqual(receipt['decision']['conditions'], list(CASES[case][2]))
                self.assertFalse(receipt['swapped'])

    def test_e5_n5_allowed_exit_0(self):
        out = self.out()
        state = self.prepared('N5')
        code, text = script(state, out)
        self.assertEqual(code, rollback_cli.EXIT_ALLOWED, text)
        self.assertTrue(text.startswith('allowed: 0 block conditions on ledger '), text)
        self.assertIn(base.compat_scan.scan(state)['ledger_sha'], text)

    def test_e5_n4_pause_and_stopped_with_report_release_neither_b1_nor_b3(self):
        """N4 differs from N5 only by R2/DUPk being paused (stopped_with_report) instead of accepted: B1 and B3 both remain."""
        code, text = script(self.prepared('N4'), self.out())
        self.assertEqual(code, rollback_cli.EXIT_REFUSED, text)
        self.assertIn('B1', text.split('(')[0]); self.assertIn('B3', text.split('(')[0])
        scan = base.compat_scan.scan(self.prepared('N4'))
        self.assertEqual(self.root(scan, 'DUPk')['status'], 'paused')
        self.assertEqual([b['id'] for b in self.root(scan, 'R2')['blocks']], ['B1'])
        self.assertEqual([b['id'] for b in self.root(scan, 'DUPk')['blocks']], ['B3'])

    def test_e5_counter_a_script_whose_gate_skips_b2_goes_red_at_n3_and_n7(self):
        """Mutant gate (ignores B2, the E17 counter): the script then allows N7 and names only B3 at N3, so the per-case check above fails."""
        from unittest.mock import patch
        from tests import wf_rollback
        real = wf_rollback.rollback_drill

        def skips_b2(state_root):
            gate = real(state_root)
            left = [c for c in gate.get('conditions', []) if c != 'B2']
            if gate['ran'] or left: return dict(gate, conditions=left) if not gate['ran'] else gate
            return {'ran': True, 'scan': gate['scan'], 'ledger_sha': gate['scan']['ledger_sha']}
        with patch.object(wf_rollback, 'rollback_drill', skips_b2):
            n7 = rollback_cli.run(self.prepared('N7'), self.out())
            n3 = rollback_cli.run(self.prepared('N3'), self.out())
        self.assertEqual(n7[0], rollback_cli.EXIT_ALLOWED)                         # red: the N-table says refused B2
        self.assertNotEqual(n7[1], expected_message(CASES['N7'][2]))
        self.assertEqual(n3[1], expected_message(('B3',)))                          # red: B2 dropped from the remaining set
        self.assertNotEqual(n3[1], expected_message(CASES['N3'][2]))

    def test_e5_unreadable_state_is_an_error_never_a_permission(self):
        state = self.prepared('N5')
        (state / 'ledger.sqlite3').write_bytes(b'not a database')
        code, text = script(state, self.out())
        self.assertEqual(code, rollback_cli.EXIT_ERROR, text)
        self.assertTrue(text.startswith('error: '), text)


class InstalledVenv(_S2Cases):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        from tests import wf_wheel
        from wfkit.upgrade_drill import build_source
        folder = cls.runs / 'wheel'; folder.mkdir()
        with build_source(ROOT, use_gate_wheel=True):        # under a release gate: the gate's wheel is the build under test
            cls.wheel, _, _ = wf_wheel.build_wheel(folder)
        cls.python = wf_wheel.make_venv(cls.runs / 'venv-home')
        wf_wheel.install(cls.python, cls.wheel)

    def packages(self):
        return rollback_cli.venv_packages(self.python)

    def test_e5_installed_refusals_leave_the_new_venv_package_list_unchanged(self):
        first = self.packages()
        self.assertTrue(any(p['name'] == 'onecrew' for p in first['pip_list']), first)
        self.assertTrue(first['onecrew']['record_sha256'])
        for case in REFUSED:
            with self.subTest(case=case):
                before = self.packages()
                out = self.out()
                code, text = script(self.prepared(case), out, self.python)
                after = self.packages()
                self.assertEqual(code, rollback_cli.EXIT_REFUSED, text)
                self.assertEqual(text, expected_message(CASES[case][2]))
                self.assertEqual(before, after)
                receipt = json.loads((out / 'receipt.json').read_text(encoding='utf-8'))
                self.assertEqual(receipt['decision']['gate'], 'upgrade_drill.guard_swap')
                self.assertEqual((receipt['packages_before'], receipt['packages_after']), (before, before))
        self.assertEqual(self.packages(), first)

    def test_e5_installed_n5_allowed(self):
        code, text = script(self.prepared('N5'), self.out(), self.python)
        self.assertEqual(code, rollback_cli.EXIT_ALLOWED, text)


if __name__ == '__main__':
    unittest.main()
