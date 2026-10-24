"""W18 hot hook: holds cache generation. A register change whose re-export failed must not leave the hook working from stale holds.

Reuses the FindingScopeTests fixture (real register, real hook check through a fake tool call). No ledger read on the hot path:
the hook compares the marker the register writer left with the generation recorded in the exported plan.
"""
import json
from unittest.mock import patch

from onecrew.v2 import active_plan
from tests.test_wf_finding_scope import FindingScopeTests


class HookHoldsGenerationTests(FindingScopeTests):
    def test_register_newer_than_exported_plan_fails_closed_until_re_export(self):
        active_plan.set_mode(self.ledger, 'enforce'); active_plan.export(self.ledger, 'P1')
        exported = json.loads(active_plan.project_file(self.root).read_text(encoding='utf-8'))
        self.assertEqual(exported['workflow_holds']['register_seq'], 0)
        code, text = self.hook('Edit', {'file_path': str(self.root / 'b.txt')})
        self.assertEqual(code, 0, text)                                              # nothing held yet
        with patch.object(active_plan, 'export', return_value=None):                # the export after the register change fails
            ident = self.open_finding()
        marker = json.loads(active_plan.holds_marker(self.root).read_text(encoding='utf-8'))
        self.assertGreater(marker['register_seq'], 0)
        stale = json.loads(active_plan.project_file(self.root).read_text(encoding='utf-8'))
        self.assertEqual(stale['workflow_holds']['register_seq'], 0, 'the plan file is still the old export')
        code, text = self.hook('Edit', {'file_path': str(self.root / 'b.txt')})
        self.assertEqual(code, 2); self.assertIn('after the active plan was exported', text)     # fail closed, even for an unheld path
        code, text = self.hook('Edit', {'file_path': str(self.root / 'a.txt')})
        self.assertEqual(code, 2)
        active_plan.export(self.ledger, 'P1')                                        # the real export catches up
        fresh = json.loads(active_plan.project_file(self.root).read_text(encoding='utf-8'))
        self.assertEqual(fresh['workflow_holds']['register_seq'], marker['register_seq'])
        self.assertIn(ident, fresh['workflow_holds']['findings'])
        code, text = self.hook('Edit', {'file_path': str(self.root / 'a.txt')})
        self.assertEqual(code, 2); self.assertIn('finding_scope', text)             # the held path stays blocked, by the real holds
        code, text = self.hook('Edit', {'file_path': str(self.root / 'x.txt')})
        self.assertEqual(code, 0, text)                                              # an unheld owned path is allowed again

    def test_marker_of_another_anchor_or_older_generation_is_ignored(self):
        active_plan.set_mode(self.ledger, 'enforce'); active_plan.export(self.ledger, 'P1')
        active_plan._write(active_plan.holds_marker(self.root), {'anchor': 'plan-ns:other', 'register_seq': 99})
        code, text = self.hook('Edit', {'file_path': str(self.root / 'b.txt')})
        self.assertEqual(code, 0, text)
        plan = json.loads(active_plan.project_file(self.root).read_text(encoding='utf-8'))
        active_plan._write(active_plan.holds_marker(self.root), {'anchor': plan['anchor'], 'register_seq': 0})
        code, text = self.hook('Edit', {'file_path': str(self.root / 'b.txt')})
        self.assertEqual(code, 0, text)
