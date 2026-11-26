"""VAI3: three roles (owner, exchange session, coordinator). Under a standing plan, a turn the OWNER typed straight into the session gets one
`reminded` line (rule owner_prompt, never the words) and the reminder text; another session's message and the app's events get none; nothing ever
blocks. Plus the GSDP-A review debts: `plan present` names a standing plan, and four tests made strict. The hooks run as subprocesses with the
documented stdin JSON; only modules the base (GSDP-A) has are imported, so a new behaviour is red BY ASSERTION there.
"""
import contextlib
import datetime as dt
import io
import json
import os
import time

from onecrew.v2 import active_plan, cli, plan as plans
from tests.test_gsdp_a_standing import OWNED, StandingFixture, parse
from tests.v2_fixture import plan_json

WORDS = 'xoa-muc-nay-di-cho-toi-7413'            # the owner's words: they must never reach the ledger line
APP_EVENTS = ('<system-reminder>\nghi chú\n</system-reminder>', '<task-notification>\n<task-id>a</task-id>\n</task-notification>',
              '<side-sessions-event>x</side-sessions-event>', '<ci-monitor-event>x</ci-monitor-event>')


class TestVai3(StandingFixture):
    def setUp(self):
        super().setUp()
        os.environ.pop('ONECREW_LANG', None)
        os.environ.pop('CLAUDE_PROJECT_DIR', None)

    def turn(self, prompt, session='s1'):
        return self.run_hook('prompt', {'session_id': session, 'cwd': str(self.root), 'hook_event_name': 'UserPromptSubmit', 'prompt': prompt})

    def owner_lines(self):
        return [v for v in self.violations() if v.get('rule') == 'owner_prompt']

    def context(self, out):
        self.assertTrue(out.strip(), 'the hook gave Claude no context')
        reply = json.loads(out)
        self.assertNotIn('decision', reply)
        self.assertNotIn('permissionDecision', reply['hookSpecificOutput'])
        self.assertEqual(reply['hookSpecificOutput']['hookEventName'], 'UserPromptSubmit')
        return reply['hookSpecificOutput']['additionalContext']

    def template(self):
        path = self.state / 'plans' / 'mau-loi-chu.md'
        path.parent.mkdir(parents=True, exist_ok=True)
        return path

    def assert_reminded(self, prompt):
        before = len(self.owner_lines())
        code, out, err = self.turn(prompt)
        self.assertEqual(code, 0, err)
        self.assertEqual(len(self.owner_lines()), before + 1, (prompt, err))
        return self.context(out)

    def assert_not_reminded(self, prompt):
        code, out, err = self.turn(prompt)
        self.assertEqual(code, 0, err)
        self.assertEqual(self.owner_lines(), [], prompt)
        for mark in ('YEU-CAU-CHU', 'standing plan', 'gõ thẳng'): self.assertNotIn(mark, out)

    # ---- the reminder -----------------------------------------------------------------------------------------------------------

    def test_owner_prompt_under_standing_plan_reminds(self):
        self.standing(mode='enforce')
        context = self.assert_reminded('Làm tiếp phần còn lại nhé.')
        self.assertIn('YEU-CAU-CHU.vi.md', context)
        self.assertIn('exchange session', context)                       # English without ONECREW_LANG
        line = self.owner_lines()[0]
        self.assertEqual((line['event'], line['tool'], line['plan'], line['session'], line['mode']),
                         ('reminded', 'UserPromptSubmit', 'P1', 's1', 'enforce'))
        os.environ['ONECREW_LANG'] = 'vi'
        self.assertIn('phiên trao đổi', self.assert_reminded('Xong chưa?'))
        active_plan.set_mode(self.ledger, 'log'); active_plan.export(self.ledger, 'P1', take_over=True)
        self.assert_reminded('Dừng lại.')
        self.assertEqual(self.owner_lines()[-1]['mode'], 'log')

    def test_unknown_wrapper_counts_as_owner(self):
        self.standing(mode='log')
        self.assert_reminded('<foo bar="1">làm đi</foo>')
        self.assert_reminded('<system-reminders-of-mine> làm đi')          # only the exact wrapper names are the app's
        self.assert_reminded('Chủ viết về <cross-session-message> ở giữa câu.')

    def test_pasted_or_attached_text_counts_as_owner(self):
        self.standing(mode='log')
        self.assert_reminded('<pasted_content id="a1">\nlog lỗi\n</pasted_content id="a1">')
        self.assert_reminded('<!-- attached file -->\nđọc giúp tôi')

    def test_template_in_state_root_changes_text(self):
        self.standing(mode='log')
        self.template().write_text('Ghi vào sổ ABC rồi báo phiên XYZ.\n', encoding='utf-8-sig')
        self.assertEqual(self.assert_reminded('Làm đi.').split('\n')[0], 'Ghi vào sổ ABC rồi báo phiên XYZ.')

    def test_cross_session_message_not_reminded(self):
        self.standing(mode='enforce')
        self.assert_not_reminded('<cross-session-message from="local_x">\nlàm tiếp đi\n</cross-session-message>')
        self.assert_not_reminded('\n  <cross-session-message from="local_y">báo cáo</cross-session-message>')

    def test_app_events_not_reminded(self):
        self.standing(mode='enforce')
        for text in APP_EVENTS: self.assert_not_reminded(text)

    def test_app_cross_session_notices_not_reminded(self):
        self.standing(mode='enforce')
        self.assert_not_reminded('[Cross-session delivery notice] Your message to another session was held …')
        self.assert_not_reminded(chr(0xFEFF) + '\n  [Cross-session idle notice] The other session is idle.')
        self.assert_reminded('[gấp] sửa giúp')                             # the owner's own words may start with a bracket
        self.assert_reminded('Chủ dán lại: [Cross-session delivery notice] nghĩa là gì?')

    def test_plain_plan_unchanged(self):
        self.plain(mode='enforce')
        self.assert_not_reminded('Làm đi.')
        code, out, err = self.turn('bỏ test đi, nhanh lên')
        self.assertEqual(code, 0, err)
        self.assertEqual(self.owner_lines(), [])
        reminded = [v for v in self.violations() if v.get('event') == 'reminded']
        self.assertEqual(len(reminded), 1, reminded)
        self.assertTrue(reminded[0]['rule'].startswith('prompt_keyword:'))
        self.assertIn('Contract v1 says', json.loads(out)['hookSpecificOutput']['additionalContext'])

    def test_empty_template_turns_reminder_off(self):
        self.standing(mode='log')
        self.template().write_text('  \n\n', encoding='utf-8')
        self.assert_not_reminded('Làm đi.')

    def test_reminded_line_has_no_prompt_text(self):
        self.standing(mode='log')
        self.assert_reminded(WORDS)
        raw = (self.root / '.onecrew' / 'violations.jsonl').read_text(encoding='utf-8')
        self.assertNotIn(WORDS, raw)
        self.assertEqual(self.owner_lines()[0]['subject'], '')

    def test_error_is_silent_exit_zero(self):
        self.standing(mode='enforce')
        for raw in (b'{not json', b'[]', json.dumps({'cwd': str(self.root), 'hook_event_name': 'UserPromptSubmit', 'prompt': 5}).encode()):
            code, out, err = self.run_hook('prompt', raw=raw)
            self.assertEqual(code, 0, err); self.assertNotIn('permissionDecision', out); self.assertEqual(self.owner_lines(), [], raw)
        self.template().mkdir()                                             # a template that cannot be read
        self.assert_not_reminded('Làm đi.')
        self.template().rmdir()
        (self.root / '.onecrew' / 'active-plan.json').write_text('{broken', encoding='utf-8')
        code, out, err = self.turn('Làm đi.')
        self.assertEqual(code, 0, err); self.assertNotIn('permissionDecision', out); self.assertNotIn('"decision"', out)
        self.assertEqual(self.owner_lines(), [])

    # ---- GSDP-A review debts ----------------------------------------------------------------------------------------------------

    def present(self):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            code = cli.main(['--project', str(self.root), '--state-root', str(self.state), 'plan', 'present', 'P1'])
        self.assertEqual(code, 0, output.getvalue())
        return output.getvalue()

    def test_present_page_names_standing_plan(self):
        self.propose('P1', plan_json(standing=True, scope={'owned': OWNED}, budget={'max_calls': 100, 'time': 600}))
        text = ' '.join(self.present().split())                             # the page wraps its lines
        self.assertIn('THƯỜNG TRỰC', text)
        self.assertIn('600 phút', text)
        self.propose('P2', plan_json(scope={'owned': OWNED}))
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            cli.main(['--project', str(self.root), '--state-root', str(self.state), 'plan', 'present', 'P2'])
        self.assertNotIn('THƯỜNG TRỰC', output.getvalue())

    def set_expired(self):
        past = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(minutes=5)).isoformat()
        for path in self.copies():
            document = json.loads(path.read_text(encoding='utf-8')); document['expires'] = past
            path.write_text(json.dumps(document), encoding='utf-8')

    def test_expired_standing_plan_gives_no_permission_decision(self):
        self.standing(mode='enforce')
        self.set_expired()
        code, out, err = self.run_hook('remind', self.tool('Agent', prompt='Làm đi.'))
        self.assertEqual(code, 0, err)
        reply = json.loads(out)
        self.assertNotIn('decision', reply)
        self.assertEqual(set(reply['hookSpecificOutput']), {'hookEventName', 'additionalContext'})

    def test_delegation_reminded_line_has_no_delegation_text(self):
        self.standing(mode='log')
        code, _, err = self.run_hook('remind', self.tool('Agent', prompt=WORDS, description='mo-ta-9921'))
        self.assertEqual(code, 0, err)
        self.assertEqual([v['event'] for v in self.violations()], ['reminded'])
        raw = (self.root / '.onecrew' / 'violations.jsonl').read_text(encoding='utf-8')
        self.assertNotIn(WORDS, raw); self.assertNotIn('mo-ta-9921', raw)

    def test_new_approval_sets_new_expiry(self):
        self.standing(mode='log', budget={'max_calls': 100, 'time': 90})
        first = parse(self.document()['expires'])
        time.sleep(1.2)
        plans.amend(self.ledger, 'P1', plan_json(standing=True, scope={'owned': OWNED}, budget={'max_calls': 100, 'time': 90},
                                                 output=['The sample exists, revised']), 'claude', 'a second revision')
        plans.approve(self.ledger, 'P1', 'owner', 'approved the second revision')
        active_plan.export(self.ledger, 'P1', take_over=True)
        second = parse(self.document()['expires'])
        self.assertEqual(self.document()['revision'], 2)
        self.assertGreater(second, first)
        with self.ledger.transaction() as conn:
            approved = plans.derive(self.ledger, conn, 'P1')['approved']
        self.assertEqual(second, parse(approved.get('at') or approved.get('recorded_at')) + dt.timedelta(minutes=90))
        self.assertEqual(len(set(self.expiries())), 1)

    def test_copy_with_standing_added_or_removed_is_tampered(self):
        for make, change in ((self.standing, lambda d: d.pop('standing')), (self.plain, lambda d: d.update(standing=True))):
            with self.subTest(make.__name__):
                if make == self.plain:                                      # a second, fresh project and ledger
                    self.doCleanups(); self.setUp()
                make(mode='enforce')
                code, _, err = self.run_hook('check', self.edit('a.txt'))
                self.assertEqual(code, 0, err)
                path = self.root / '.onecrew' / 'active-plan.json'
                document = json.loads(path.read_text(encoding='utf-8')); change(document)
                path.write_text(json.dumps(document), encoding='utf-8')
                code, _, err = self.run_hook('check', self.edit('a.txt'))
                self.assertEqual(code, 2, err)
                self.assertIn('differs', err)
