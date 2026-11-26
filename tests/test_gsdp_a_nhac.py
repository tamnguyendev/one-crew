"""GSDP-A (#63, first round), the delegation reminder (decisions D7, D10, D11): `onecrew init --remind on` adds a PreToolUse entry of its own (`hook
remind`, onFailure continue) for Agent, Task, SendMessage, start_session and send_message. When the session's plan is a standing plan and the strings of
the delegation lack an item of the owner's template, it writes one `reminded` line and returns the missing items as additionalContext, exit 0, in log and
enforce mode. Everything else is silence and nothing ever blocks. Kind A cases fail BY ASSERTION on the base (no `hook remind`, no `--remind`, no
standing field): the hook is run as a subprocess and init through its argv, so the base answers with an exit code that the test asserts on.
"""
import contextlib
import io
import json
import os
from pathlib import Path
from unittest.mock import patch

from onecrew.ledger import LedgerError
from onecrew.v2 import active_plan, hook_cli, install
from tests.test_gsdp_a_standing import StandingFixture
from tests.v2_fixture import plan_json

CHECK_MATCHER = 'Edit|Write|MultiEdit|NotebookEdit|Bash|PowerShell'
REMIND_MATCHER = 'Agent|Task|SendMessage|mcp__ccd_session__start_session|mcp__ccd_session_mgmt__send_message'
ITEMS = ('Mục tiêu', 'Tệp được sửa', 'Xong khi', 'Không làm', 'Cách kiểm', 'Skill')
FULL = ('Mục tiêu: tóm tắt a.txt. Tệp được sửa: không tệp nào. Xong khi: có bản tóm tắt. Không làm: không sửa tệp. '
        'Cách kiểm: đọc lại a.txt. Skill: không bắt buộc.')


def context_of(out):
    return json.loads(out)['hookSpecificOutput']['additionalContext']


class TestGsdpNhac(StandingFixture):
    def setUp(self):
        super().setUp()
        # init registers the project and doctor reads the user's Claude settings: never the developer's real ones
        home = Path(self.temp.name) / 'home'; (home / '.claude').mkdir(parents=True)
        for key, value in (('LOCALAPPDATA', Path(self.temp.name) / 'local'), ('APPDATA', Path(self.temp.name) / 'roaming'), ('HOME', home),
                           ('USERPROFILE', home), ('CLAUDE_CONFIG_DIR', home / '.claude')):
            os.environ[key] = str(value)
        for name in ('ONECREW_LANG', 'CLAUDE_PROJECT_DIR'): os.environ.pop(name, None)
        self.exe = Path(self.temp.name) / 'venv' / 'Scripts' / 'onecrew.exe'
        self.exe.parent.mkdir(parents=True); self.exe.write_bytes(b'')
        self.init_state = Path(self.temp.name) / 'init-state'

    def remind(self, tool, **tool_input):
        return self.run_hook('remind', self.tool(tool, **tool_input))

    def reminded(self):
        return [v for v in self.violations() if v.get('event') == 'reminded']

    def settings(self):
        return json.loads((self.root / '.claude' / 'settings.local.json').read_text(encoding='utf-8'))

    def pre_tool_use(self):
        return self.settings()['hooks']['PreToolUse']

    def remind_entries(self):
        return [e for e in self.pre_tool_use() if any((h.get('args') or [])[-2:] == ['hook', 'remind'] for h in e.get('hooks', []))]

    def check_entries(self):
        return [e for e in self.pre_tool_use() if any((h.get('args') or [])[-2:] == ['hook', 'check'] for h in e.get('hooks', []))]

    def init_argv(self, *flags):
        """`onecrew init` through its own argv (install.main), as the owner types it; (exit code, output). A refused option is its exit code."""
        out = io.StringIO()
        with patch.object(install, 'installed_exe', return_value=self.exe), \
                patch.object(install.claude_cli, 'cli_argv', side_effect=LedgerError('no Claude CLI in the test')), \
                contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
            try:
                code = install.main(['init', '--project', str(self.root), '--state-root', str(self.init_state), '--yes', *flags])
            except SystemExit as result:
                code = result.code
        return code, out.getvalue()

    def init(self, remind=None):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = install.init(self.root, self.init_state, yes=True, exe=self.exe, claude=lambda: ('ok', '/x/claude', ''), remind=remind)
        self.assertIn(code, (0, 1), out.getvalue())
        return out.getvalue()

    # ---- kind A: new behaviour --------------------------------------------------------------------------------------------------

    def test_agent_missing_items_reminded(self):
        self.standing(mode='enforce')
        code, out, err = self.remind('Agent', description='Đọc tệp', prompt='Đọc a.txt rồi tóm tắt cho tôi.', subagent_type='general-purpose')
        self.assertEqual(code, 0, err)
        self.assertTrue(out.strip(), 'no additionalContext for a delegation that lacks items')
        reply = json.loads(out)['hookSpecificOutput']
        self.assertEqual(reply['hookEventName'], 'PreToolUse')
        self.assertNotIn('permissionDecision', reply)                                 # a reminder never allows, denies or asks
        for name in ITEMS: self.assertIn(name, reply['additionalContext'])
        self.assertIn('KHÔNG bị chặn', reply['additionalContext'])
        lines = self.reminded()
        self.assertEqual(len(lines), 1, lines)
        self.assertEqual((lines[0]['tool'], lines[0]['mode'], lines[0]['plan']), ('Agent', 'enforce', 'P1'))
        self.assertTrue(lines[0]['rule'].startswith('delegation_missing:'))
        active_plan.set_mode(self.ledger, 'log'); active_plan.export(self.ledger, 'P1', take_over=True)
        code, out, err = self.remind('Task', prompt='Chạy thử bộ test và báo lại. Mục tiêu: biết test có xanh không.')
        self.assertEqual(code, 0, err)
        self.assertTrue(out.strip(), err)
        self.assertNotIn('Mục tiêu', context_of(out).split('thiếu mục:', 1)[1].split('.', 1)[0])     # the item it has is not listed
        self.assertEqual([(v['tool'], v['mode']) for v in self.reminded()], [('Agent', 'enforce'), ('Task', 'log')])

    def test_sendmessage_any_field_reminded(self):
        self.standing(mode='log')
        code, out, err = self.remind('SendMessage', to='worker', message='Làm tiếp phần còn lại nhé.', summary='tiếp việc')
        self.assertEqual(code, 0, err)
        self.assertTrue(out.strip(), err)
        for name in ITEMS: self.assertIn(name, context_of(out))
        self.assertIn('SendMessage', context_of(out))
        # every item is there, in fields no documentation names, nested and in capitals: no field name is relied on, so it is silent
        code, out, err = self.remind('SendMessage', to='worker', envelope={'parts': ['MỤC TIÊU: dọn thư mục', {'x': 'TỆP ĐƯỢC SỬA: chỉ tmp/'}],
                                                                            'tail': 'XONG KHI rỗng. KHÔNG LÀM gì khác. CÁCH KIỂM: ls. SKILL: không.'})
        self.assertEqual((code, out.strip()), (0, ''), err)
        self.assertEqual([v['tool'] for v in self.reminded()], ['SendMessage'])

    def test_start_session_any_field_reminded(self):
        self.standing(mode='enforce')
        code, out, err = self.remind('mcp__ccd_session__start_session', title='Việc mới', prompt='Sửa lỗi đăng nhập.', initiation='user_asked')
        self.assertEqual(code, 0, err)
        self.assertTrue(out.strip(), err)
        self.assertIn('mcp__ccd_session__start_session', context_of(out))
        code, out, err = self.remind('mcp__ccd_session_mgmt__send_message', session_id='local_x', text='Làm tiếp. Mục tiêu: xong phần A.')
        self.assertEqual(code, 0, err)
        self.assertTrue(out.strip(), err)
        self.assertNotIn('Mục tiêu,', context_of(out))
        self.assertEqual([v['tool'] for v in self.reminded()], ['mcp__ccd_session__start_session', 'mcp__ccd_session_mgmt__send_message'])

    def test_remind_entry_only_with_init_flag(self):
        code, out = self.init_argv()
        self.assertIn(code, (0, 1), out)
        self.assertEqual(self.remind_entries(), [])                                  # a plain init has no reminder entry
        self.assertFalse((self.init_state / 'plans' / 'mau-giao-viec.md').exists())
        code, out = self.init_argv('--remind', 'on')
        self.assertIn(code, (0, 1), out)                                             # the base refuses the option (argparse exit 2)
        entries = self.remind_entries()
        self.assertEqual(len(entries), 1, self.pre_tool_use())
        self.assertEqual(entries[0]['matcher'], REMIND_MATCHER)
        handler = entries[0]['hooks'][0]
        self.assertEqual((handler['args'], handler['onFailure']), (['hook', 'remind'], 'continue'))
        self.assertEqual(Path(handler['command']).name, self.exe.name)
        checks = self.check_entries()                                                # its own entry: the check entry is unchanged
        self.assertEqual(len(checks), 1)
        self.assertEqual((checks[0]['matcher'], checks[0]['hooks'][0]['onFailure']), (CHECK_MATCHER, 'block'))
        self.assertTrue((self.init_state / 'plans' / 'mau-giao-viec.md').is_file())

    # ---- kind B: must hold on the candidate ---------------------------------------------------------------------------------------

    def test_all_items_present_silent(self):
        self.standing(mode='enforce')
        code, out, err = self.remind('Agent', description='Tóm tắt', prompt=FULL)
        self.assertEqual((code, out.strip()), (0, ''), err)
        code, out, err = self.remind('Agent', prompt='GOAL: x. FILES: none. DONE WHEN: y. NOT DOING: z. VERIFY: read it. SKILL: none.')
        self.assertEqual((code, out.strip()), (0, ''), err)                         # case-insensitive, English keywords of the template
        template = self.state / 'plans' / 'mau-giao-viec.md'                         # the owner's own template replaces the built-in one
        template.parent.mkdir(parents=True, exist_ok=True)
        template.write_text('# chỉ một mục\n- Ngân sách: ngân sách, budget\n', encoding='utf-8')
        code, out, err = self.remind('Agent', prompt='Ngân sách: 2 giờ. Làm đi.')
        self.assertEqual((code, out.strip()), (0, ''), err)
        code, out, err = self.remind('Agent', prompt=FULL)
        self.assertEqual(code, 0, err)
        self.assertIn('Ngân sách', context_of(out)); self.assertNotIn('Mục tiêu,', context_of(out))
        template.write_text('# chủ tắt nhắc: không còn mục nào\n', encoding='utf-8')
        code, out, err = self.remind('Agent', prompt='Làm đi.')
        self.assertEqual((code, out.strip()), (0, ''), err)
        self.assertEqual(len(self.reminded()), 1)

    def test_no_standing_plan_silent(self):
        self.plain(mode='enforce')
        for tool in ('Agent', 'SendMessage', 'mcp__ccd_session__start_session'):
            code, out, err = self.remind(tool, prompt='Làm đi.')
            self.assertEqual((code, out.strip()), (0, ''), (tool, err))
        self.assertEqual(self.reminded(), [])
        other = Path(self.temp.name) / 'bare'; other.mkdir()                          # no plan anywhere
        import subprocess
        subprocess.check_call(['git', 'init', '-q', str(other)])
        event = dict(self.tool('Agent', prompt='Làm đi.'), cwd=str(other))
        done = subprocess.run([*self.hook_argv(other), 'remind'], input=json.dumps(event).encode('utf-8'), capture_output=True,
                              cwd=str(Path(__file__).resolve().parents[1]), timeout=120, env=self.hook_env())
        self.assertEqual((done.returncode, done.stdout.strip()), (0, b''), done.stderr)

    def hook_argv(self, project):
        from tests.v2_fixture import PY
        return [PY, '-X', 'utf8', '-m', 'onecrew', '--project', str(project), '--state-root', str(Path(self.temp.name) / 'bare-state'), 'hook']

    def hook_env(self):
        return dict({k: v for k, v in os.environ.items() if k not in ('CLAUDE_CODE_CHILD_SESSION', 'CLAUDECODE')}, PYTHONUTF8='1')

    def test_remind_error_never_blocks(self):
        self.standing(mode='enforce')
        code, out, err = self.run_hook('remind', raw=b'{not json')
        self.assertEqual((code, out.strip()), (0, ''), err)
        code, out, err = self.run_hook('remind', dict(self.tool('Agent'), tool_input='a string, not an object'))
        self.assertEqual(code, 0, err)
        template = self.state / 'plans' / 'mau-giao-viec.md'                         # a template that cannot be read: silence
        template.mkdir(parents=True)
        code, out, err = self.remind('Agent', prompt='Làm đi.')
        self.assertEqual((code, out.strip()), (0, ''), err)
        template.rmdir()
        project_copy = self.root / '.onecrew' / 'active-plan.json'                   # an unreadable plan: silence (the check hook is the gate)
        saved = project_copy.read_bytes()
        project_copy.write_text('{broken', encoding='utf-8')
        code, out, err = self.remind('Agent', prompt='Làm đi.')
        self.assertEqual((code, out.strip()), (0, ''), err)
        project_copy.write_bytes(saved)
        import datetime as dt
        past = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(minutes=5)).isoformat()
        for path in self.copies():                                                    # expired in enforce: the reminder still only reminds
            document = json.loads(path.read_text(encoding='utf-8')); document['expires'] = past
            path.write_text(json.dumps(document), encoding='utf-8')
        code, out, err = self.remind('Agent', prompt='Làm đi.')
        self.assertEqual(code, 0, err); self.assertNotIn('Blocked', err)
        self.assertTrue(out.strip(), err)
        handler = hook_cli.portable_settings(self.exe, self.state, remind=True)['hooks']['PreToolUse'][1]['hooks'][0]
        self.assertEqual((handler['args'], handler['onFailure']), (['hook', 'remind'], 'continue'))

    def test_remind_entry_reinit_uninstall_doctor(self):
        self.init(remind='on')
        self.init(remind='on')                                                         # init again: never doubled
        self.assertEqual(len(self.remind_entries()), 1); self.assertEqual(len(self.check_entries()), 1)
        handler = self.remind_entries()[0]['hooks'][0]
        self.assertTrue(install.is_ours(handler)); self.assertTrue(install.has_remind(self.settings()))
        self.assertEqual(install.check_hooks(self.root, self.init_state, self.exe)[0], 'PASS')    # doctor: the entry is OneCrew's, not a stray
        template = self.init_state / 'plans' / 'mau-giao-viec.md'
        template.write_text('- Mục tiêu: mục tiêu\n', encoding='utf-8')              # the owner's edit
        self.init(remind='on')
        self.assertEqual(template.read_text(encoding='utf-8'), '- Mục tiêu: mục tiêu\n')     # never overwritten
        self.init()                                                                    # a plain re-init keeps what is there
        self.assertEqual(len(self.remind_entries()), 1)
        settings = self.settings()
        settings['hooks']['PreToolUse'].append({'matcher': 'Agent', 'hooks': [{'type': 'command', 'command': 'audit-tool', 'args': ['log']}]})
        (self.root / '.claude' / 'settings.local.json').write_text(json.dumps(settings), encoding='utf-8')
        out = self.init(remind='off')                                                 # the way out: the reminder entry is removed
        self.assertEqual(self.remind_entries(), []); self.assertEqual(len(self.check_entries()), 1)
        self.assertIn({'matcher': 'Agent', 'hooks': [{'type': 'command', 'command': 'audit-tool', 'args': ['log']}]}, self.pre_tool_use())   # others stay
        self.assertFalse(install.has_remind(self.settings()))
        self.assertEqual(install.check_hooks(self.root, self.init_state, self.exe)[0], 'PASS')
        self.assertTrue(out)

    # ---- kind C: control (the same on the base) -------------------------------------------------------------------------------

    def test_check_entry_unchanged_and_user_hook_quiet(self):
        pre = hook_cli.portable_settings(self.exe, self.state)['hooks']['PreToolUse']
        self.assertEqual(len(pre), 1)
        self.assertEqual((pre[0]['matcher'], pre[0]['hooks'][0]['args'], pre[0]['hooks'][0]['onFailure']), (CHECK_MATCHER, ['hook', 'check'], 'block'))
        self.assertEqual(install.USER_MATCHER, CHECK_MATCHER)                         # the user hook never sees a delegation tool
        self.plain(mode='enforce')
        for extra in ((), ('--scope', 'user')):
            code, _, err = self.run_hook('check', self.tool('Agent', prompt='Làm đi.'), extra=extra)
            self.assertEqual(code, 0, (extra, err)); self.assertNotIn('Blocked', err)
        self.assertEqual(self.violations(), [])
