"""OBS3 MS, using a private Claude profile, registry, target repository and ledger."""
import ast
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
        for key in ('CLAUDE_CODE_ENTRYPOINT', 'ONECREW_ACTOR', 'ONECREW_V2_REQUIRE_PLAN', 'CLAUDECODE', 'CLAUDE_CODE_CHILD_SESSION'):
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
        self.observe_args = self.install_fixture_observer(base)
        self.key = self.observe_args[3]

    @staticmethod
    def install_fixture_observer(base):
        """P2-1: the genuine path. `hook user install --observe` writes the handlers (with their install key) into a fixture settings file, not the
        profile's; call() then runs `hook <args of that handler>` in process. Returns the args of the UserPromptSubmit handler."""
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

    def call(self, name, args=None, **extra):
        event = dict({'hook_event_name': name, 'cwd': str(self.other), 'session_id': 'session-1'}, **extra)
        stdin = type('Input', (), {'buffer': io.BytesIO(json.dumps(event).encode())})()
        with patch.object(Path, 'cwd', return_value=self.other), patch.object(sys, 'stdin', stdin), contextlib.redirect_stdout(io.StringIO()) as out, contextlib.redirect_stderr(io.StringIO()) as err:
            self.assertEqual(hook_cli.main(self.observe_args if args is None else args), 0)
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

    def test_read_only_mention_is_not_a_hook_command(self):
        self.assertIsNone(hook_cli.judge_shell({}, self.root, self.root, 'echo "onecrew hook observe"'))

    def test_hook_policy_checks_executable_positions(self):
        for command, ps in [('onecrew hook --help', False), ('Write-Output "hook sync"', True)]:
            self.assertIsNone(hook_cli.judge_shell({}, self.root, self.root, command, powershell=ps))
        decision = hook_cli.judge_shell({}, self.root, self.root, 'onecrew hook $UNSET_OPERATION')
        self.assertEqual(decision[0], 'bash_deny')
        names = {}
        hook_cli._observation_words(['alias', 'sample=onecrew hook'], names, False)
        self.assertEqual(hook_cli._observation_words(['sample', '--help'], names, False), ['onecrew', 'hook', '--help'])
        hook_cli._observation_words(['$operation=check'], names, True)
        self.assertEqual(hook_cli._observation_words(['onecrew', 'hook', '$operation'], names, True)[-1], 'check')
        for words in (['onecrew', 'hook', '$operation'], ['oc', 'hook', '$operation']):
            verdict = hook_cli._observation_policy(words, '', (), self.root, self.root, False)
            self.assertEqual(verdict[0], 'bash_deny')

    def test_temporary_script_policy_distinguishes_program_and_input(self):
        outside = (self.other / 'fixture.sh').as_posix()
        program = (self.root / 'fixture.sh').as_posix()
        denied = hook_cli.judge_shell({}, self.root, self.root, f'bash "{outside}"')
        self.assertEqual(denied[0], 'bash_deny')
        self.assertIsNone(hook_cli.judge_shell({}, self.root, self.root, f'bash "{program}" "{outside}"'))

    def test_python_policy_recognizes_observation_writers_without_running_code(self):
        # Inspect a syntax tree only. The sample has no executable call or ledger.
        for writer in ('observe', 'flush'):
            syntax = ast.parse('if False: receiver(sample)')
            syntax.body.insert(0, ast.ImportFrom(module='onecrew.v2.session_observe',
                               names=[ast.alias(name=writer, asname='receiver')], level=0))
            with patch.object(ast, 'parse', return_value=syntax):
                self.assertTrue(hook_cli._python_observation('# onecrew policy fixture'))
        self.assertFalse(hook_cli._python_observation("print('onecrew hook observe')"))
        for command in ('python -c "pass"', "python <<'END'\npass\nEND"):
            with patch.object(hook_cli, '_python_observation', side_effect=lambda code: code.strip() == 'pass'):
                decision = hook_cli.judge_shell({}, self.root, self.root, command)
                self.assertEqual(decision[0], 'bash_deny')

    def test_binding_uses_hook_process_directory(self):
        os.environ.pop('CLAUDE_PROJECT_DIR')
        with patch.object(session_observe, '_binding', return_value=None) as binding:
            self.call('SessionStart', cwd=str(self.root))
        self.assertEqual(binding.call_args.args[0]['cwd'], str(self.other))

    def test_print_mode_prompt_is_machine_input(self):
        self.bind()
        with patch.dict(os.environ, CLAUDE_CODE_ENTRYPOINT='sdk-cli'):
            self.call('UserPromptSubmit', prompt='diagnostic')
        self.call('Stop')
        prompt, = [r for r in self.observed() if r['observation'] == 'owner_prompt']
        self.assertEqual(prompt['source'], 'claude_machine')

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
        session_observe.flush(self.ledger, self.key)
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
        legacy = {k: v for k, v in rows[-1].items() if k not in ('kid', 'mac')}
        legacy['source'] = 'owner'  # the spelling of previous releases, in a row sealed by the installed handler (an unsealed line is never imported)
        rows[-1] = session_observe.sealed(legacy, self.key)
        pending.write_text(''.join(json.dumps(row) + '\n' for row in rows), encoding='utf-8')
        session_observe.flush(self.ledger, self.key)
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
        session_observe.flush(self.ledger, self.key)
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
        self.assertEqual(session_observe.flush(self.ledger, self.key), 0)
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
            configured = json.loads(settings.read_text(encoding='utf-8'))
            for tool in ('Bash', 'PowerShell'):
                for verb in ('observe', 'sync'):
                    self.assertIn(f'{tool}(*hook {verb}*)', configured.get('permissions', {}).get('deny', []))
            hooks = configured['hooks']
            keys = set()
            for event in install.OBSERVE_EVENTS:
                handlers = [h for entry in hooks[event] for h in entry['hooks'] if h.get('args', [])[:2] == ['hook', 'observe']]
                self.assertEqual(len(handlers), 1)
                self.assertEqual(handlers[0]['onFailure'], 'continue')
                self.assertEqual(handlers[0]['args'][2], session_observe.KEY_FLAG)      # P2-1: the handler carries the install key
                keys.add(handlers[0]['args'][3])
            key, = keys                                                              # one key per settings file, kept by the second install
            self.assertTrue(session_observe.accepted(key))
            read_rule = 'Read(//' + str(settings.resolve()).replace('\\', '/').lstrip('/') + ')'      # the file now holds the key (S7 review, 5)
            self.assertIn(read_rule, configured['permissions']['deny'])
            self.assertNotIn(key, where.observation_keys_file().read_text(encoding='utf-8'))      # only its hash is kept
            self.assertEqual(install.user_hook('uninstall', settings), 0)
        self.assertEqual(json.loads(settings.read_text(encoding='utf-8')), seed)
        self.assertIsNone(session_observe.accepted(key))                                # uninstall forgets the key

    def test_observation_without_the_install_key_writes_nothing(self):
        # P2-1 / P2-1b / P2-2: only the handler OneCrew installed writes rows; the command text, the folder and the payload give no trust.
        self.bind()
        event = dict(hook_event_name='UserPromptSubmit', cwd=str(self.root), session_id='session-1', prompt='FORGED words')
        for args in (['hook', 'observe'], ['hook', 'observe', session_observe.KEY_FLAG, 'k' * 43], [*self.observe_args[:3], self.key[:-1] + 'x']):
            with self.subTest(args=args[:3]):
                self.assertEqual(self.call('UserPromptSubmit', args=args, prompt='FORGED words'), '')
        with patch.object(Path, 'cwd', return_value=self.root):
            for key in (None, '', 'k' * 43):
                session_observe.observe(event, key)
                session_observe.observe(dict(event, hook_event_name='Stop'), key)
                self.assertEqual(session_observe.flush(self.ledger, key), 0)
        pending = next(self.ledger.state_root.rglob('pending.jsonl'))
        forged = {k: v for k, v in json.loads(pending.read_text(encoding='utf-8').splitlines()[-1]).items() if k not in ('kid', 'mac')}
        with pending.open('a', encoding='utf-8') as stream:            # a line appended by hand: unsealed, sealed with another key, or edited after sealing
            stream.write(json.dumps(dict(forged, text='FORGED words', observation='owner_prompt', spool_id='f1')) + '\n')
            stream.write(json.dumps(session_observe.sealed(dict(forged, text='FORGED words', observation='owner_prompt', spool_id='f2'), 'k' * 43)) + '\n')
            stream.write(json.dumps(dict(session_observe.sealed(dict(forged, spool_id='f3'), self.key), text='FORGED words', observation='owner_prompt')) + '\n')
        self.call('Stop')
        self.assertEqual([r for r in self.observed() if r.get('text') == 'FORGED words'], [])
        self.assertEqual([r['observation'] for r in self.observed()], ['tool_call', 'turn_end'])

    def test_lines_queued_by_an_older_release_are_not_imported_and_doctor_says_reinstall(self):
        # Upgrade case (S7 review, 7): a line an older release queued has no seal, so it cannot be told from a forged one: it is not imported, and
        # doctor says the older handlers record nothing and names the command to run again.
        self.bind()
        pending = next(self.ledger.state_root.rglob('pending.jsonl'))
        sealed = json.loads(pending.read_text(encoding='utf-8').splitlines()[-1])
        old = {k: v for k, v in sealed.items() if k not in ('kid', 'mac')}
        with pending.open('a', encoding='utf-8') as stream:
            stream.write(json.dumps(dict(old, observation='owner_prompt', source='owner', text='queued before the upgrade', spool_id='old-1')) + '\n')
        exe = self.home.parent / 'fixture-bin' / ('onecrew.cmd' if os.name == 'nt' else 'onecrew')
        install.write_text(install.user_settings_file(), json.dumps({'hooks': {e: [{'hooks': [{'type': 'command', 'command': str(exe), 'args': ['hook', 'observe']}]}]
                                                                             for e in install.OBSERVE_EVENTS}}))
        self.call('Stop')
        self.assertNotIn('queued before the upgrade', str(self.observed()))
        self.assertEqual([r['observation'] for r in self.observed()], ['tool_call', 'turn_end'])
        self.assertEqual(len(list(pending.parent.glob('*.rejected'))), 1)
        with patch.dict(os.environ, ONECREW_LANG='en'):
            line, = [(level, detail) for level, name, detail in install.doctor_facts(self.root, self.ledger.state_root, claude=None)
                     if name == install.t('doctor.observation')]
        self.assertEqual(line[0], 'WARN')
        for words in ('0/9', 'hook user install --observe', 'older install', 'record nothing', 'not imported'):
            self.assertIn(words, line[1])

    def test_a_line_of_another_installed_key_is_held_a_bounded_number_of_times(self):
        # S7 review (8): a line naming another installed key waits for that key's flush, but one whose seal never checks out is dropped in the end.
        self.bind()
        other = 'k' + 'o' * 42
        install._remember_key('fixture-other-profile', session_observe.key_id(other))
        pending = next(self.ledger.state_root.rglob('pending.jsonl'))
        base_row = {k: v for k, v in json.loads(pending.read_text(encoding='utf-8').splitlines()[-1]).items() if k not in ('kid', 'mac')}
        good = session_observe.sealed(dict(base_row, spool_id='other-good', hook='SubagentStart', observation='subagent_start'), other)
        bad = dict(session_observe.sealed(dict(base_row, spool_id='other-bad'), other), observation='owner_prompt', text='FORGED held')
        with pending.open('a', encoding='utf-8') as stream:
            stream.write(json.dumps(good) + '\n' + json.dumps(bad) + '\n')
        session_observe.flush(self.ledger, self.key)
        self.assertIn('other-good', pending.read_text(encoding='utf-8'))          # held for its own key
        self.assertEqual(session_observe.flush(self.ledger, other), 1)           # the good line: imported by its own key; the bad one rejected there
        with pending.open('a', encoding='utf-8') as stream:                      # a bad line whose key never flushes again
            stream.write(json.dumps(dict(bad, spool_id='other-bad-2')) + '\n')
        for n in range(session_observe.HELD_FLUSHES + 1):
            session_observe.flush(self.ledger, self.key)
            left = pending.read_text(encoding='utf-8') if pending.exists() else ''
            self.assertEqual('other-bad-2' in left, n < session_observe.HELD_FLUSHES, n)
        self.assertNotIn('FORGED held', str(self.observed()))
        self.assertEqual([r['spool_id'] for r in self.observed() if r.get('observation') == 'subagent_start'], [good['spool_id']])

    def test_only_interactive_entrypoints_are_session_input(self):
        # P2-4: an allowlist. cli, the desktop app and an absent variable are a session; print mode, the SDKs and scheduled runs are machine input.
        for value, source in (('cli', 'claude_session'), ('claude-desktop', 'claude_session'), ('', 'claude_session'),
                              ('sdk-cli', 'claude_machine'), ('sdk-ts', 'claude_machine'), ('sdk-py', 'claude_machine'), ('scheduled-task', 'claude_machine')):
            with self.subTest(entrypoint=value):
                self.assertEqual(session_observe.input_source(value), source)
        os.environ.pop('CLAUDE_CODE_ENTRYPOINT', None)
        self.assertEqual(session_observe.input_source(), 'claude_session')

    def test_older_observer_form_is_recognised_but_not_counted_as_recording(self):
        exe = self.home / ('onecrew.cmd' if os.name == 'nt' else 'onecrew')
        exe.parent.mkdir(parents=True, exist_ok=True)
        exe.write_text('@exit /b 0\n' if os.name == 'nt' else '#!/bin/sh\nexit 0\n', encoding='ascii')
        exe.chmod(0o755)
        settings = install.user_settings_file()
        old = {'hooks': {e: [{'hooks': [{'type': 'command', 'command': str(exe), 'args': ['hook', 'observe'], 'timeout': 10, 'onFailure': 'continue'}]}]
                         for e in install.OBSERVE_EVENTS}}
        install.write_text(settings, json.dumps(old))
        self.assertEqual(install.observed_events(old), list(install.OBSERVE_EVENTS))
        self.assertEqual(install.observed_events(old, keyed=True), [])
        with contextlib.redirect_stdout(io.StringIO()) as out:
            self.assertEqual(install.user_hook('status', settings), 0)
        status = json.loads(out.getvalue())
        self.assertEqual((len(status['observation_events']), status['observation_events_recording']), (len(install.OBSERVE_EVENTS), []))
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(install.user_hook('install', settings, exe), 0)     # a plain install upgrades the older handlers to the keyed form
        upgraded = json.loads(settings.read_text(encoding='utf-8'))
        self.assertEqual(install.observed_events(upgraded, keyed=True), list(install.OBSERVE_EVENTS))
        with contextlib.redirect_stdout(io.StringIO()):
            install.write_text(settings, json.dumps(old))
            self.assertEqual(install.user_hook('uninstall', settings), 0)
        self.assertEqual(install.observed_events(json.loads(settings.read_text(encoding='utf-8'))), [])

    def test_observer_key_is_not_minted_in_an_ai_session(self):
        settings = self.home / 'elsewhere' / 'settings.json'
        with patch.dict(os.environ, CLAUDE_CODE_CHILD_SESSION='1'), contextlib.redirect_stdout(io.StringIO()) as out:
            self.assertEqual(install.user_hook('install', settings, self.home.parent / 'fixture-bin' / ('onecrew.cmd' if os.name == 'nt' else 'onecrew'), observe=True), 2)
        self.assertIn('refused', out.getvalue())
        self.assertFalse(settings.exists())

    def test_ai_session_cannot_read_the_settings_file_that_holds_the_key(self):
        for command in ('cat ~/.claude/settings.json', f'type "{install.user_settings_file()}"', 'Get-Content $env:USERPROFILE/.claude/settings.json'):
            with self.subTest(command=command):
                self.assertEqual(hook_cli.judge_shell({}, self.root, self.root, command)[0], 'protected')
        self.assertEqual(hook_cli.judge_shell({}, self.root, self.root, 'echo $(cat ~/.claude/settings.json)')[0], 'protected')
        self.assertIsNone(hook_cli.judge_shell({}, self.root, self.root, 'cat .claude/settings.json'))
        # a mention that opens nothing is not a read (S7 review, 9): a message, a printed string, a search pattern
        for command, ps in (('git commit -m "docs: ~/.claude/settings.json holds the key"', False), ('echo ~/.claude/settings.json', False),
                            ('grep -n "~/.claude/settings.json" docs/x.md', False), ('rg -e ~/.claude/settings.json docs', False),
                            ("Write-Output '~/.claude/settings.json'", True), ("Select-String -Pattern '~/.claude/settings.json' -Path docs/x.md", True)):
            with self.subTest(command=command):
                self.assertNotIn('Claude Code settings', str(hook_cli.judge_shell({}, self.root, self.root, command, powershell=ps)))
        rules = hook_cli.deny_rules(self.ledger.state_root)
        self.assertIn('Read(//' + str(install.user_settings_file()).replace('\\', '/').lstrip('/') + ')', rules)
        self.assertIn('Edit(//' + str(where.observation_keys_file()).replace('\\', '/').lstrip('/') + ')', rules)
