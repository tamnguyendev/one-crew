"""Owner UX on temporary real ledgers; human output never bypasses the owner gate."""
import contextlib
import io
import json
import os
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

from onecrew.v2 import cli, owner_cli, plan, tracking
from tests.test_v2_l1 import Fixture, plan_json
from tests.test_obs1_tracking import QUESTION


class HumanOwnerTests(Fixture):
    def call(self, *args):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            code = cli.main(['--project', str(self.root), '--state-root', str(self.ledger.state_root), 'owner', *args])
        return code, output.getvalue()

    def test_human_approval_is_short_json_default_is_unchanged_and_stale_is_refused(self):
        self.propose()
        code, text = self.call('approve', 'P1', '--revision', '1', '--reference', 'temporary fixture approval', '--human')
        self.assertEqual(code, 0, text); self.assertIn('Đã ghi nhận duyệt', text)
        self.assertIn('không xác nhận worker đã bắt đầu', text); self.assertLess(len(text), 700)
        code, text = self.call('approve', 'P1', '--revision', '1', '--reference', 'temporary fixture replay')
        self.assertEqual(code, 0); self.assertEqual(json.loads(text)['approved_revision'], 1)
        plan.amend(self.ledger, 'P1', plan_json(title='New proposal'), 'fixture amendment', 'codex')
        before = self.events()
        code, text = self.call('approve', 'P1', '--revision', '1', '--reference', 'stale fixture choice', '--human')
        self.assertEqual(code, 2); self.assertIn('Only the latest revision (2)', text)
        self.assertNotIn('Đã ghi nhận', text); self.assertEqual(before, self.events())

    def test_human_owner_guard_preserves_ai_marker_and_default_json_denial(self):
        self.propose(); before = self.events()
        with patch.dict(os.environ, {'CLAUDE_CODE_CHILD_SESSION': '1'}):
            code, text = self.call('approve', 'P1', '--reference', 'fixture', '--human')
            self.assertEqual(code, 2); self.assertIn('Chưa ghi nhận', text)
            self.assertIn('CLAUDE_CODE_CHILD_SESSION is set', text)
            code, text = self.call('approve', 'P1', '--reference', 'fixture')
            self.assertEqual(code, 2); self.assertIn('AI tool session', json.loads(text)['error'])
            self.assertEqual(os.environ['CLAUDE_CODE_CHILD_SESSION'], '1')
        self.assertEqual(before, self.events())

    def test_unfilled_reference_and_malformed_revision_cannot_approve(self):
        self.propose(); before = self.events()
        code, text = self.call('approve', 'P1', '--revision', '1', '--reference', tracking.REFERENCE_PLACEHOLDER, '--human')
        self.assertEqual(code, 2); self.assertIn('placeholder', text)
        code, text = self.call('approve', 'P1', '--revision', 'not-a-number', '--reference', 'fixture', '--human')
        self.assertEqual(code, 2); self.assertIn('not-a-number', text)
        self.assertEqual(before, self.events())

    def test_answer_uses_current_request_revision_and_reports_recording_only(self):
        root = self.propose(); request = self.ledger.create_request(root['anchor_task'], 'owner-choice', QUESTION)
        code, text = self.call('answer', request['id'], '--revision', 'stale', '--choice', 'seven', '--reference', 'fixture', '--human')
        self.assertEqual(code, 2); self.assertEqual(self.ledger.request(request['id'])['state'], 'pending')
        code, text = self.call('answer', request['id'], '--revision', request['revision'], '--choice', 'seven', '--reference', 'fixture', '--human')
        self.assertEqual(code, 0, text); self.assertIn('Đã ghi nhận lựa chọn seven', text)
        self.assertIn('không phải là duyệt phương án', text)

    def test_exit_zero_without_receipt_stays_uncertain(self):
        with patch('onecrew.v2.plan_cli.main', side_effect=lambda args: (print('opaque output'), 0)[1]):
            code, text = self.call('approve', 'P1', '--reference', 'fixture', '--human')
        self.assertEqual(code, 1); self.assertIn('Chưa xác nhận được', text); self.assertNotIn('Đã ghi nhận', text)
        self.assertIn('opaque output', text)

    def test_human_terminal_text_is_safe_and_help_is_visible(self):
        with patch('onecrew.v2.plan_cli.main', side_effect=lambda args: (print(json.dumps({'error': '\x1b[31mpassword=never-show-this\x1b[0m'})), 2)[1]):
            code, text = self.call('approve', 'P1', '--reference', 'fixture', '--human')
        self.assertEqual(code, 2); self.assertNotIn('\x1b', text); self.assertNotIn('never-show-this', text)
        code, text = self.call('--human', '--help')
        self.assertEqual(code, 0); self.assertIn('onecrew owner', text); self.assertIn('approve', text)

    def test_accept_revision_guard_is_backward_compatible_and_checked_inside_write(self):
        from onecrew.v2 import verdict
        self.approved(); receipt, body = self.receipt(); self.issue(receipt)
        verdict.record(self.ledger, 'P1', 'M1', 'pass', 'command', receipt, self.tree())
        code, text = self.call('accept', 'P1', '--revision', '2', '--artifact-sha', self.tree(), '--reference', 'fixture', '--human')
        self.assertEqual(code, 2); self.assertIn('expected revision 2, latest is 1', text)
        self.assertNotIn('plan.accepted', self.kinds())
        code, text = self.call('accept', 'P1', '--revision', '1', '--artifact-sha', self.tree(), '--reference', 'fixture', '--human')
        self.assertEqual(code, 0, text); self.assertIn('Đã ghi nhận nghiệm thu', text)
        code, text = self.call('accept', 'P1', '--artifact-sha', self.tree(), '--reference', 'legacy fixture replay')
        self.assertEqual(code, 0); self.assertEqual(json.loads(text)['status'], 'accepted')


class ActionMetadataTests(Fixture):
    def test_proposed_action_pins_selector_revision_runtime_and_never_selects_optional_items(self):
        self.propose()
        value = tracking.detail(self.ledger.state_root, 'P1')
        need = next(n for n in value['needs_user'] if n['kind'] == 'approve')
        self.assertEqual(need['revision'], 1); self.assertEqual(need['title'], 'Sample')
        self.assertIn("owner approve '" + value['selector'] + "' --revision 1", need['reply_command'])
        self.assertIn('--human', need['reply_command']); self.assertIn('--reference', need['reply_command'])
        self.assertNotIn('--tick', need['reply_command'])
        self.assertTrue(all(not i['selected'] for i in need['optional_items']))
        self.assertEqual(need['action']['expected']['task'], value['id'])
        self.assertEqual(need['action']['expected']['revision'], 1)
        self.assertTrue(value['created_at']); self.assertIsNone(value['deadline'])

    def test_hostile_paths_survive_generated_approval_powershell(self):
        state = {'status': 'proposed', 'name': 'P1', 'selector': 'plan:P1', 'task_id': 'root', 'latest': 7, 'revisions': {7: {}}}
        project = "D:/temp $SDK 'quoted' (a)&b`t"; ledger = "D:/state $SDK 'quoted' (c)&d`t"
        need = tracking._needs_user(state, [], [], 'none', None, project=project, state_root=ledger, contract=plan_json())[0]
        # Capture argv, using the generated argument suffix, never execute an owner mutation.
        suffix = need['reply_command'].split(' --project ', 1)[1].replace(tracking.REFERENCE_PLACEHOLDER, 'fixture reference')
        script = Path(self.temp.name) / 'argv.ps1'
        script.write_text("$SDK='wrong'\n& '" + sys.executable.replace("'", "''") + "' -X utf8 -c 'import json,sys;print(json.dumps(sys.argv[1:]))' --project " + suffix, encoding='utf-8-sig')
        result = subprocess.run(['powershell', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', str(script)], capture_output=True, text=True, encoding='utf-8', errors='replace')
        self.assertEqual(result.returncode, 0, result.stderr)
        args = json.loads(result.stdout); self.assertEqual(args[1], project); self.assertEqual(args[3], ledger)
        self.assertIn('plan:P1', args); self.assertIn('7', args)

    def test_plan_options_are_explicit_and_recommendation_is_not_chosen(self):
        from tests.test_v2_l3 import step0_json
        self.propose(value=step0_json())
        need = tracking.detail(self.ledger.state_root, 'P1')['needs_user'][0]
        self.assertEqual([o['id'] for o in need['plan_choices']], ['A', 'B'])
        self.assertIn("--choose '<option-id>'", need['reply_command'])
        self.assertNotIn("--choose 'A'", need['reply_command'])
        self.assertIn('option-id', need['placeholders'])

    def test_accept_copy_is_disabled_without_revision_bound_command(self):
        self.approved()
        with self.ledger.transaction() as conn: state = plan.derive(self.ledger, conn, 'P1')
        need = tracking._needs_user(state, [], [{'state': 'passed'}], 'verified', None,
                                   project=self.ledger.project_path, state_root=str(self.ledger.state_root), contract=plan_json())[0]
        self.assertEqual(need['kind'], 'accept'); self.assertFalse(need['action']['enabled'])
        self.assertIsNone(need['reply_command']); self.assertIn('revision', need['binding_reason'])
        self.assertIn("plan report '" + state['selector'] + "' --revision 1", need['inspect_command'])

    def test_accept_command_pins_real_common_verified_artifact(self):
        from onecrew.v2 import verdict
        self.approved(); receipt, body = self.receipt(); self.issue(receipt)
        verdict.record(self.ledger, 'P1', 'M1', 'pass', 'command', receipt, self.tree())
        need = tracking.detail(self.ledger.state_root, 'P1')['needs_user'][0]
        self.assertEqual(need['kind'], 'accept'); self.assertTrue(need['action']['enabled'])
        self.assertIn('--revision 1', need['reply_command']); self.assertIn("--artifact-sha '" + self.tree() + "'", need['reply_command'])
