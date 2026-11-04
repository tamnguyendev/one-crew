"""T49a counter-examples [E9], [E18], [E23], [E24] (W46a/W46b): the scan's rules are what make the fixture expectations hold — a scanner
with one rule removed gives a different, wrong answer that the expectations catch.

Fixture of tests/test_wf_compat_scan (real old binary archive, S1 with R1/R4/X1/X2). Each counter-example replaces ONE rule of
`compat_scan` and checks the scan now contradicts the expectation the original rule guarantees (X1 keeps its B4; a paused/accepted root
releases nothing; predictions are per command).
"""
from unittest.mock import patch

from onecrew.v2 import compat_scan
import tests.test_wf_compat_scan as base


class ScanCounterexampleTests(base.CompatScanTests):
    for _name in [n for n in dir(base.CompatScanTests) if n.startswith('test_')]:
        locals()[_name] = None
    del _name

    def x1(self, rep):
        return self._root(rep, 'x1')

    def test_e9_e23_a_scanner_that_ignores_read_block_events_or_accepted_roots_loses_x1(self):
        original = self.x1(compat_scan.scan(self.s1))
        self.assertEqual([b['id'] for b in original['blocks']], ['B4']); self.assertFalse(original['properties']['old_readable'])
        with patch.object(compat_scan, '_read_block_events', return_value=[]):                       # mutant: no read-block rule
            mutated = self.x1(compat_scan.scan(self.s1))
        self.assertNotEqual([b['id'] for b in mutated['blocks']], ['B4'])                             # the expectation catches it
        self.assertNotEqual(mutated['properties']['old_readable'], original['properties']['old_readable'])

    def test_e18_a_scanner_that_treats_a_pause_as_a_release_is_caught(self):
        rep = compat_scan.scan(self.s1)
        r4 = self._root(rep, 'r4')
        self.assertEqual([b['id'] for b in r4['blocks']], ['B2'])
        original = compat_scan._class_b_events
        with patch.object(compat_scan, '_class_b_events', side_effect=lambda events: []):             # mutant: class-B events ignored
            mutated = self._root(compat_scan.scan(self.s1), 'r4')
        self.assertEqual(mutated['blocks'], [], 'the mutant drops B2')
        self.assertNotEqual(mutated['properties']['old_continuable'], r4['properties']['old_continuable'])
        self.assertEqual([b['id'] for b in self._root(compat_scan.scan(self.s1), 'r4')['blocks']], ['B2'])   # the rule restored, B2 is back
        self.assertIs(compat_scan._class_b_events, original)

    def test_e24_one_prediction_for_every_command_is_caught(self):
        rep = compat_scan.scan(self.s1)
        table = {r['name']: r['commands'] for r in rep['roots']}
        self.assertTrue(any(len(set(str(v) for v in cmds.values())) > 1 for cmds in table.values()), 'predictions differ per command')
        keys = set(compat_scan._predict_commands('open', False, False)) - {'plan digest'}            # the rows only the rule predicts (digest is also set by the B4 root-wide rule)
        with patch.object(compat_scan, '_predict_commands', side_effect=lambda status, rb, cb: {k: 'No plan named' for k in keys}):
            flat = {r['name']: r['commands'] for r in compat_scan.scan(self.s1)['roots']}
        self.assertNotEqual(flat, table)                                                              # a blanket expectation is a different, wrong table
        for name, cmds in flat.items():
            self.assertEqual({cmds[k] for k in keys if k in cmds}, {'No plan named'}, name)
            self.assertNotEqual({table[name][k] for k in keys if k in table[name]}, {'No plan named'}, name)   # the real rule tells commands apart
