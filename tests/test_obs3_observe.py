"""OBS3 MS, using a private Claude profile, registry, target repository and ledger."""
import contextlib
import io
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from onecrew.v2 import active_plan, hook_cli, install, session_observe, where
from tests.test_ui33_task_first import Project, milestone


class Observe(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        base = Path(temp.name)
        env = patch.dict(os.environ)
        env.start()
        self.addCleanup(env.stop)
        for key in ('ONECREW_ACTOR', 'ONECREW_V2_REQUIRE_PLAN', 'CLAUDECODE', 'CLAUDE_CODE_CHILD_SESSION'):
            os.environ.pop(key, None)
        self.other = base / 'unrelated'
        self.other.mkdir()
        self.home = base / 'home'
        os.environ.update(HOME=str(self.home), USERPROFILE=str(self.home), CLAUDE_CONFIG_DIR=str(self.home / '.claude'),
                          LOCALAPPDATA=str(base / 'local'), APPDATA=str(base / 'roaming'), CLAUDE_PROJECT_DIR=str(self.other))
        self.project = Project(base, 'project', base / 'state')
        self.root, self.ledger = self.project.root, self.project.ledger
        self.project.plan('P1', [milestone()])
        active_plan.export(self.ledger, 'P1', strict=True)
        where.register_project(self.root, self.ledger.state_root)

    def call(self, name, **extra):
        event = dict({'hook_event_name': name, 'cwd': str(self.other), 'session_id': 'session-1'}, **extra)
        stdin = type('Input', (), {'buffer': io.BytesIO(json.dumps(event).encode())})()
        with patch.object(sys, 'stdin', stdin), contextlib.redirect_stdout(io.StringIO()) as out, contextlib.redirect_stderr(io.StringIO()) as err:
            self.assertEqual(hook_cli.main(['hook', 'observe']), 0)
        self.assertEqual(out.getvalue(), '')
        return err.getvalue()

    def bind(self):
        self.assertEqual(self.call('PreToolUse', tool_name='Edit', tool_use_id='target',
                                   tool_input={'file_path': str(self.root / 'a.txt')}), '')

    def observed(self):
        task = self.project.state('P1')['task_id']
        return [e['payload'] for e in self.ledger.events(task) if e['kind'] == 'hook.observed']

    def test_enforced_plan_protects_observation_commands_and_spool(self):
        active_plan.set_mode(self.ledger, 'enforce')
        active_plan.export(self.ledger, 'P1', strict=True)
        target = (self.ledger.state_root / 'claude-observations' / 'pending.jsonl').as_posix()
        cases = [('Bash', {'command': 'printf sample | onecrew hook observe'}, 'bash_deny'),
                 ('Bash', {'command': 'onecrew hook sync'}, 'bash_deny'),
                 ('Bash', {'command': f'fixture-writer "{target}"'}, 'protected'),
                 ('Write', {'file_path': target}, 'protected')]
        for tool, inputs, rule in cases:
            with self.subTest(tool=tool, inputs=inputs):
                event = dict(hook_event_name='PreToolUse', cwd=str(self.root), tool_name=tool, tool_input=inputs)
                stdin = type('Input', (), {'buffer': io.BytesIO(json.dumps(event).encode())})()
                with patch.object(sys, 'stdin', stdin), contextlib.redirect_stderr(io.StringIO()) as err:
                    self.assertEqual(hook_cli.main(['--project', str(self.root), '--state-root', str(self.ledger.state_root),
                                                    'hook', 'check']), 2, err.getvalue())
                self.assertIn(f'({rule})', err.getvalue())

    def test_session_other_folder_reaches_target_plan(self):
        self.bind()
        self.call('UserPromptSubmit', prompt='Mở trang')
        self.assertEqual(self.observed(), [])
        self.assertEqual(self.call('Stop'), '')
        rows = self.observed()
        self.assertEqual([r['observation'] for r in rows], ['tool_call', 'owner_prompt', 'turn_end'])
        self.assertEqual({r['project'] for r in rows}, {self.ledger.project_path})
        self.assertEqual({r['cwd'] for r in rows}, {str(self.other)})

    def test_subagent_start_stop_recorded(self):
        self.bind()
        for event in ('SubagentStart', 'SubagentStop'):
            self.call(event, agent_id='child', agent_type='review')
        self.call('SessionEnd')
        children = [r for r in self.observed() if r['agent_id'] == 'child']
        self.assertEqual([r['observation'] for r in children], ['subagent_start', 'subagent_stop'])
        self.assertTrue(all(r['session'] == 'session-1' and r['agent_type'] == 'review' for r in children))

    def test_background_shell_recorded(self):
        self.bind()
        for _ in range(2):
            self.call('PostToolUse', tool_name='Bash', tool_use_id='bg',
                      tool_input={'run_in_background': True, 'description': 'Kiểm thử', 'command': 'echo PRIVATE-SCRIPT'})
        session_observe.flush(self.ledger)
        self.assertEqual([r['label'] for r in self.observed() if r['observation'] == 'background_shell'], ['Kiểm thử'])
        self.assertNotIn('PRIVATE-SCRIPT', str(self.observed()))

    def test_owner_prompt_recorded_filtered(self):
        self.bind()
        words = 'Giữ tab mở. ' * 180
        self.call('UserPromptSubmit', prompt=words + '\npassword=hunter222')
        self.call('Stop')
        r = self.observed()[1]
        self.assertEqual((r['source'], r['text']), ('claude_session', words + '\npassword=[withheld]'))

    def test_legacy_pending_prompt_keeps_its_words_and_gets_session_provenance(self):
        self.bind()
        self.call('UserPromptSubmit', prompt='Giữ chữ đã gõ.')
        pending = next(self.ledger.state_root.rglob('pending.jsonl'))
        rows = [json.loads(line) for line in pending.read_text(encoding='utf-8').splitlines()]
        rows[-1]['source'] = 'owner'  # format written by previous releases
        pending.write_text(''.join(json.dumps(row) + '\n' for row in rows), encoding='utf-8')
        session_observe.flush(self.ledger)
        prompt = self.observed()[-1]
        self.assertEqual((prompt['source'], prompt['text']), ('claude_session', 'Giữ chữ đã gõ.'))

    def ask(self, name, **extra):
        return self.call(name, tool_name='AskUserQuestion', tool_use_id='ask1',
                         tool_input={'questions': [{'question': 'Cỡ nào?', 'options': [{'label': 'Nhỏ'}, {'label': 'Lớn'}]}],
                                     'answers': {'Cỡ nào?': 'invented by AI'}}, **extra)

    def test_ai_question_recorded_as_claim(self):
        self.bind()
        self.ask('PreToolUse')
        self.ask('PostToolUse')
        self.call('Stop')
        r = self.observed()[1]
        self.assertEqual((r['text'], r['options'], r['source']), ('Cỡ nào?', ['Nhỏ', 'Lớn'], 'ai_claim'))
        self.assertNotIn('owner_choice', str(self.observed()))

    def test_owner_choice_linked(self):
        self.bind()
        self.ask('PreToolUse')
        self.ask('PostToolUse', tool_response={'answers': {'Cỡ nào?': 'Nhỏ'}})
        self.call('Stop')
        question, answer = self.observed()[1:3]
        self.assertTrue(question['question_id'])
        self.assertEqual((answer['question_id'], answer['source'], answer['text']), (question['question_id'], 'claude_session', 'Nhỏ'))

    def test_secret_never_stored(self):
        self.bind()
        self.call('UserPromptSubmit', prompt='-----BEGIN PRIVATE KEY-----\nPRIVATE-BODY\n-----END PRIVATE KEY-----\nAuthorization: Bearer PRIVATE-HEADER')
        self.call('PostToolUse', tool_name='Bash', tool_use_id='bg', tool_input={'run_in_background': True, 'description': 'api_key=PRIVATE-LABEL'})
        self.call('UserPromptSubmit', prompt='api_key:\nPRIVATE-NEXT\npassword="private start\nPRIVATE-CONTINUATION"')
        spool = next(self.ledger.state_root.rglob('pending.jsonl')).read_text(encoding='utf-8')
        self.call('Stop')
        for secret in ('PRIVATE-BODY', 'PRIVATE-HEADER', 'PRIVATE-LABEL', 'PRIVATE-NEXT', 'PRIVATE-CONTINUATION'):
            self.assertNotIn(secret, spool)
            self.assertNotIn(secret, str(self.observed()))

    def test_no_transcript_text_in_ledger(self):
        self.bind()
        transcript = self.other / 'session.jsonl'
        transcript.write_text('PRIVATE-TRANSCRIPT')
        self.call('PostToolUse', tool_name='Read', tool_input={}, tool_response={'text': 'PRIVATE-OUTPUT'})
        self.call('Stop', transcript_path=str(transcript), last_assistant_message='PRIVATE-ASSISTANT', thinking='PRIVATE-THOUGHTS')
        rows = self.observed()
        self.assertEqual(len(rows), 3)
        self.assertNotIn('PRIVATE-', str(rows))
        self.assertNotIn(str(transcript), str(rows))

    def test_unbound_session_said(self):
        self.call('SessionStart')
        self.call('UserPromptSubmit', prompt='unrelated private text')
        item, = session_observe.bindings()
        self.assertEqual((item['status'], item['reason']), ('unbound', 'no active target'))
        self.assertNotIn('private text', str(item))
        self.assertEqual(self.observed(), [])
        self.bind()
        self.project.plan('P2', [milestone()])
        active_plan.export(self.ledger, 'P2', take_over=True, strict=True)
        self.call('UserPromptSubmit', prompt='ambiguous private text')
        self.assertEqual(session_observe.bindings()[0]['reason'], 'multiple plans')
        session_observe.flush(self.ledger)
        self.assertNotIn('private text', str(self.observed()))

    def test_hook_failure_does_not_block_work(self):
        with patch.object(session_observe, '_binding', side_effect=OSError('PRIVATE')):
            error = self.call('UserPromptSubmit', prompt='sensitive')
        self.assertIn('OSError', error)
        self.assertNotIn('PRIVATE', error)
        self.assertEqual(self.observed(), [])

    def test_interrupted_append_and_batch_replay_preserve_later_events(self):
        self.bind()
        pending = next(self.ledger.state_root.rglob('pending.jsonl'))
        old = pending.read_bytes()
        with pending.open('ab') as stream: stream.write(b'{"incomplete"')
        self.call('UserPromptSubmit', prompt='after restart')
        self.call('Stop')
        self.assertEqual(len(self.observed()), 3)
        self.assertEqual(self.observed()[1]['text'], 'after restart')
        self.assertEqual(len(list(pending.parent.glob('*.rejected'))), 1)
        (pending.parent / 'retry.batch').write_bytes(old)
        self.assertEqual(session_observe.flush(self.ledger), 0)
        self.assertEqual(len(self.observed()), 3)

    def test_install_observer_in_private_home_and_remove_only_our_handlers(self):
        exe = self.home / ('onecrew.cmd' if os.name == 'nt' else 'onecrew')
        exe.parent.mkdir(parents=True, exist_ok=True)
        exe.write_text('@exit /b 0\n' if os.name == 'nt' else '#!/bin/sh\nexit 0\n', encoding='ascii')
        exe.chmod(0o755)
        settings = install.user_settings_file()
        seed = {'hooks': {'Stop': [{'hooks': [{'command': 'another-hook'}]}]}}
        install.write_text(settings, json.dumps(seed))
        with contextlib.redirect_stdout(io.StringIO()):
            for _ in range(2):
                self.assertEqual(install.user_hook('install', settings, exe, observe=True), 0)
            hooks = json.loads(settings.read_text(encoding='utf-8'))['hooks']
            for event in install.OBSERVE_EVENTS:
                handlers = [h for entry in hooks[event] for h in entry['hooks'] if h.get('args') == ['hook', 'observe']]
                self.assertEqual(len(handlers), 1)
                self.assertEqual(handlers[0]['onFailure'], 'continue')
            self.assertEqual(install.user_hook('uninstall', settings), 0)
        self.assertEqual(json.loads(settings.read_text(encoding='utf-8')), seed)
