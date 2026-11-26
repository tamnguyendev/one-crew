"""QSAT (A): a hand-over keeps one short line. The PreToolUse row of Agent/Task, SendMessage and start_session carries `summary` = the tool's own short
field (description, summary, title), masked and cut to 160 characters; the PostToolUse row has none; the prompt or message itself is never stored.

The fixture follows tests/test_obs3_observe.py (a private Claude profile, registry, project and ledger; the observer installed into a fixture settings
file and run in process), copied here so that no test class of that module is imported (and run twice)."""
import contextlib
import io
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from onecrew.v2 import active_plan, hook_cli, install, where
from tests.test_ui33_task_first import Project, milestone


class TestQsatTomTat(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        base = Path(temp.name)
        env = patch.dict(os.environ)
        env.start()
        self.addCleanup(env.stop)
        for key in ('CLAUDE_CODE_ENTRYPOINT', 'ONECREW_ACTOR', 'ONECREW_V2_REQUIRE_PLAN', 'CLAUDECODE', 'CLAUDE_CODE_CHILD_SESSION'):
            os.environ.pop(key, None)
        self.home = base / 'home'
        self.project = Project(base, 'project-a', base / 'state')
        self.root, self.ledger = self.project.root, self.project.ledger
        os.environ.update(HOME=str(self.home), USERPROFILE=str(self.home), CLAUDE_CONFIG_DIR=str(self.home / '.claude'),
                          LOCALAPPDATA=str(base / 'local'), APPDATA=str(base / 'roaming'), CLAUDE_PROJECT_DIR=str(self.root))
        self.project.plan('PA', [milestone()])
        active_plan.export(self.ledger, 'PA', strict=True)
        where.register_project(self.root, self.ledger.state_root)
        self.observe_args = self.install_fixture_observer(base)

    @staticmethod
    def install_fixture_observer(base):
        """`hook user install --observe` writes the handlers (with their install key) into a fixture settings file; returns the observe args."""
        program = base / 'fixture-bin' / ('onecrew.cmd' if os.name == 'nt' else 'onecrew')
        program.parent.mkdir(parents=True, exist_ok=True)
        program.write_text('@exit /b 0\r\n' if os.name == 'nt' else '#!/bin/sh\nexit 0\n', encoding='ascii')
        program.chmod(0o755)
        settings = base / 'fixture-profile' / 'settings.json'
        with contextlib.redirect_stdout(io.StringIO()) as out:
            if install.user_hook('install', settings, program, observe=True) != 0: raise AssertionError(out.getvalue())
        hooks = json.loads(settings.read_text(encoding='utf-8'))['hooks']
        args, = [h['args'] for entry in hooks['UserPromptSubmit'] for h in entry['hooks'] if h['args'][:2] == ['hook', 'observe']]
        return args

    def call(self, name, **extra):
        """One hook event of session-1, whose own folder (the hook process directory) is project A."""
        event = dict({'hook_event_name': name, 'cwd': str(self.root), 'session_id': 'session-1'}, **extra)
        stdin = type('Input', (), {'buffer': io.BytesIO(json.dumps(event).encode())})()
        with patch.object(Path, 'cwd', return_value=self.root), patch.object(sys, 'stdin', stdin), \
                contextlib.redirect_stdout(io.StringIO()) as out, contextlib.redirect_stderr(io.StringIO()) as err:
            self.assertEqual(hook_cli.main(self.observe_args), 0)
        self.assertEqual(out.getvalue(), '')
        return err.getvalue()

    def observed(self):
        task = self.project.state('PA')['task_id']
        return [e['payload'] for e in self.ledger.events(task) if e['kind'] == 'hook.observed']

    def hand_over(self, tool, inputs, hooks=('PreToolUse',), call_id='give-1'):
        """The rows of one hand-over call (tool_use_id call_id) after the turn ends, as {hook: row}."""
        for hook in hooks:
            self.call(hook, tool_name=tool, tool_use_id=call_id, tool_input=inputs)
        self.call('Stop')
        rows = {r['hook']: r for r in self.observed() if r.get('tool_use_id') == call_id}
        self.assertEqual(set(rows), set(hooks), 'every hook of the call is recorded')
        return rows

    def test_agent_description_kept_as_summary(self):
        rows = self.hand_over('Agent', {'description': 'Soát mã bộ quan sát', 'prompt': 'PRIVATE-PROMPT dài', 'subagent_type': 'general-purpose'})
        self.assertEqual(rows['PreToolUse'].get('summary'), 'Soát mã bộ quan sát')

    def test_sendmessage_summary_kept(self):
        rows = self.hand_over('SendMessage', {'to': 'local_0123456789abcdef', 'summary': 'Báo M1 đạt', 'message': 'PRIVATE-MESSAGE dài'})
        self.assertEqual(rows['PreToolUse'].get('summary'), 'Báo M1 đạt')

    def test_start_session_title_kept(self):
        rows = self.hand_over('mcp__ccd_session__start_session', {'title': 'Sửa bộ quan sát', 'prompt': 'PRIVATE-BRIEF dài'})
        self.assertEqual(rows['PreToolUse'].get('summary'), 'Sửa bộ quan sát')

    def test_summary_masked_and_capped(self):
        token = 'ghp_' + 'A1b2C3d4E5' * 4
        rows = self.hand_over('Agent', {'description': 'Dùng ' + token + ' rồi ' + 'x' * 300, 'prompt': 'PRIVATE-PROMPT'})
        summary = rows['PreToolUse'].get('summary')
        self.assertTrue(isinstance(summary, str) and summary.startswith('Dùng ') and 0 < len(summary) <= 160, repr(summary)[:200])
        self.assertNotIn(token, summary)
        self.assertNotIn('A1b2C3d4E5A1b2C3d4E5', summary)
        # a key that straddles the 160th character: masked before the cut, so no part of it is left at the end
        straddle = 'ghp_' + 'Z9y8X7w6V5' * 4
        rows = self.hand_over('Task', {'description': 'y' * 150 + ' ' + straddle + ' cuoi', 'prompt': 'PRIVATE-PROMPT'}, call_id='give-2')
        summary = rows['PreToolUse'].get('summary')
        self.assertTrue(isinstance(summary, str) and len(summary) <= 160, repr(summary)[-80:])
        self.assertNotIn('ghp_Z9', summary)
        self.assertNotIn('Z9y8X7', summary)

    def test_summary_only_on_pretooluse(self):
        rows = self.hand_over('Agent', {'description': 'Chỉ dòng trước', 'prompt': 'PRIVATE-PROMPT'}, hooks=('PreToolUse', 'PostToolUse'))
        self.assertEqual(rows['PreToolUse'].get('summary'), 'Chỉ dòng trước')
        self.assertNotIn('summary', rows['PostToolUse'])
        for tool, inputs in (('Read', {'file_path': str(self.root / 'a.txt'), 'description': 'không phải giao việc'}),
                             ('mcp__ccd_session_mgmt__send_message', {'session_id': 'x', 'message': 'PRIVATE-APP'}),
                             ('Agent', {'description': '   ', 'prompt': 'PRIVATE-PROMPT'})):
            with self.subTest(tool=tool):
                self.call('PreToolUse', tool_name=tool, tool_use_id='other-' + tool, tool_input=inputs)
                self.call('Stop')
                row, = [r for r in self.observed() if r.get('tool_use_id') == 'other-' + tool]
                self.assertNotIn('summary', row)

    def test_message_body_never_stored(self):
        calls = [('Agent', {'description': 'giao', 'prompt': 'PRIVATE-PROMPT-1'}),
                 ('Task', {'description': 'giao', 'prompt': 'PRIVATE-PROMPT-2'}),
                 ('SendMessage', {'to': 'x', 'summary': 'nhắn', 'message': 'PRIVATE-MESSAGE-3'}),
                 ('mcp__ccd_session__start_session', {'title': 'việc', 'prompt': 'PRIVATE-BRIEF-4'}),
                 ('mcp__ccd_session_mgmt__send_message', {'session_id': 'x', 'message': 'PRIVATE-APP-5'})]
        for i, (tool, inputs) in enumerate(calls):
            for hook in ('PreToolUse', 'PostToolUse'):
                self.call(hook, tool_name=tool, tool_use_id=f'body-{i}', tool_input=inputs, tool_response={'text': 'PRIVATE-OUTPUT'})
        spool = ''.join(p.read_text(encoding='utf-8') for p in self.ledger.state_root.rglob('pending.jsonl'))
        self.call('Stop')
        rows = self.observed()
        self.assertEqual(len([r for r in rows if str(r.get('tool_use_id', '')).startswith('body-')]), 10)
        self.assertNotIn('PRIVATE-', spool)
        self.assertNotIn('PRIVATE-', str(rows))


if __name__ == '__main__':
    unittest.main()
