"""#25: the user-scope hook. `onecrew hook user install|status|uninstall` puts ONE PreToolUse entry in the user's Claude Code settings; `hook check --scope user`
asks the plans of the projects a call writes in, and records who made the call (agent_id, agent_type, tool_use_id, scope). Every file here is in a temp folder:
HOME, USERPROFILE, CLAUDE_CONFIG_DIR, LOCALAPPDATA and APPDATA point into it, so the real profile and the real registry are never read or written."""
import argparse
import contextlib
import io
import json
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

from onecrew.v2 import active_plan, hook_cli, install, where
from tests.test_v2_l1 import Fixture, plan_json
from tests.test_v2_trust_fixes import HookBase

SEED = {'theme': 'dark', 'permissions': {'allow': ['Read(*)']},
        'hooks': {'PreToolUse': [{'matcher': 'Bash', 'hooks': [{'type': 'command', 'command': 'echo other-tool-hook'}]}],
                  'Stop': [{'hooks': [{'type': 'command', 'command': 'echo other-stop'}]}]}}


class UserHookBase(HookBase):
    def setUp(self):
        super().setUp()
        self.home = self.base / 'home'
        self.conf = self.base / 'claude-config'
        (self.home / '.claude').mkdir(parents=True)
        self.conf.mkdir()
        os.environ.update(HOME=str(self.home), USERPROFILE=str(self.home), CLAUDE_CONFIG_DIR=str(self.conf), APPDATA=str(self.base / 'roaming'),
                          LOCALAPPDATA=str(self.base / 'local'))
        self.settings = self.conf / 'settings.json'
        self.exe = self.stub(self.base / 'bin')

    @staticmethod
    def stub(folder, exit_code=0, name='onecrew'):
        """A program that answers like onecrew does for `--version` and `hook check --scope user` (review P2-1/P2-7: install and doctor now run the program)."""
        folder.mkdir(parents=True, exist_ok=True)
        if os.name == 'nt':
            program = folder / (name + '.cmd')
            program.write_text(f'@exit /b {exit_code}\r\n', encoding='ascii')
        else:
            program = folder / name
            program.write_text(f'#!/bin/sh\nexit {exit_code}\n', encoding='ascii')
            program.chmod(0o755)
        return program

    def seed(self, value=None, path=None):
        path = path or self.settings
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(SEED if value is None else value, indent=1), encoding='utf-8')
        return path

    def verb(self, verb, *extra, path=None, program=True):
        out = io.StringIO()
        argv = ['hook', 'user', verb, '--settings-file', str(path or self.settings), *(['--program', str(self.exe)] if verb == 'install' and program else []), *extra]
        with contextlib.redirect_stdout(out):
            code = hook_cli.main(argv)
        return code, out.getvalue()

    def data(self, path=None):
        return json.loads((path or self.settings).read_text(encoding='utf-8'))


class UserHookLifecycle(UserHookBase):
    def test_install_merges_one_pretooluse_entry_and_keeps_everything_else(self):
        self.seed()
        code, out = self.verb('install')
        self.assertEqual(code, 0, out)
        data = self.data()
        ours = [h for e in data['hooks']['PreToolUse'] for h in e['hooks'] if h.get('args')]
        self.assertEqual(ours, [{'type': 'command', 'command': str(self.exe.resolve()), 'args': ['hook', 'check', '--scope', 'user'], 'timeout': 15, 'onFailure': 'block'}])
        entry = next(e for e in data['hooks']['PreToolUse'] if any(h.get('args') for h in e['hooks']))
        self.assertEqual(set(entry['matcher'].split('|')), {'Edit', 'Write', 'MultiEdit', 'NotebookEdit', 'Bash', 'PowerShell'})
        self.assertEqual((data['theme'], data['permissions'], data['hooks']['Stop']), (SEED['theme'], SEED['permissions'], SEED['hooks']['Stop']))
        self.assertIn(SEED['hooks']['PreToolUse'][0], data['hooks']['PreToolUse'])
        self.assertEqual(set(data['hooks']), {'PreToolUse', 'Stop'})                 # no Stop / SessionStart / UserPromptSubmit of ours

    def test_a_copy_of_the_file_is_made_once_before_the_first_change(self):
        self.seed()
        self.verb('install')
        backup = self.settings.with_name('settings.json.bak')
        self.assertEqual(json.loads(backup.read_text(encoding='utf-8')), SEED)
        self.verb('uninstall'); self.verb('install')
        self.assertEqual(json.loads(backup.read_text(encoding='utf-8')), SEED)       # not replaced by a later state

    def test_installing_again_changes_nothing(self):
        self.seed()
        self.verb('install')
        first = self.settings.read_text(encoding='utf-8')
        code, out = self.verb('install')
        self.assertEqual(code, 0)
        self.assertEqual(self.settings.read_text(encoding='utf-8'), first)
        self.assertEqual(sum(1 for e in self.data()['hooks']['PreToolUse'] for h in e['hooks'] if h.get('args')), 1)

    def test_uninstall_returns_the_file_to_its_content_before_install(self):
        for seed in (SEED, {'theme': 'dark'}, {'hooks': {'Stop': SEED['hooks']['Stop']}}, {}):
            with self.subTest(seed=seed):
                self.seed(seed)
                self.verb('install')
                self.assertNotEqual(self.data(), seed)
                code, out = self.verb('uninstall')
                self.assertEqual(code, 0, out)
                self.assertEqual(self.data(), seed)

    def test_uninstall_without_an_entry_changes_nothing(self):
        self.seed()
        before = self.settings.read_text(encoding='utf-8')
        code, out = self.verb('uninstall')
        self.assertEqual(code, 0)
        self.assertEqual(self.settings.read_text(encoding='utf-8'), before)
        self.assertFalse(self.settings.with_name('settings.json.bak').exists())

    def test_install_creates_a_missing_file_and_uninstall_leaves_an_empty_object(self):
        code, out = self.verb('install')
        self.assertEqual(code, 0, out)
        self.assertEqual(len(self.data()['hooks']['PreToolUse']), 1)
        self.verb('uninstall')
        self.assertEqual(self.data(), {})

    def test_status_says_whether_it_is_configured_and_whether_the_program_is_there(self):
        self.seed()
        code, out = self.verb('status')
        self.assertEqual((code, json.loads(out)['configured']), (0, False))
        self.verb('install')
        status = json.loads(self.verb('status')[1])
        self.assertEqual((status['configured'], status['settings_file'], status['program'], status['program_found']), (True, str(self.settings), str(self.exe.resolve()), True))
        self.exe.unlink()
        self.assertFalse(json.loads(self.verb('status')[1])['program_found'])

    def test_a_settings_file_that_is_not_json_is_never_overwritten(self):
        self.settings.write_text('{"theme": ', encoding='utf-8')
        code, out = self.verb('install')
        self.assertEqual(code, 2)
        self.assertEqual(self.settings.read_text(encoding='utf-8'), '{"theme": ')
        self.seed({'hooks': 'x'})
        self.assertEqual(self.verb('install')[0], 2)
        self.assertEqual(self.data(), {'hooks': 'x'})

    def test_the_file_is_claude_config_dir_when_it_is_set_else_the_home_folder(self):
        self.assertEqual(install.user_settings_file(), self.conf / 'settings.json')
        with patch.dict(os.environ, {'CLAUDE_CONFIG_DIR': ''}):
            self.assertEqual(install.user_settings_file(), self.home / '.claude' / 'settings.json')
        with patch.dict(os.environ):
            os.environ.pop('CLAUDE_CONFIG_DIR')
            self.assertEqual(install.user_settings_file(), self.home / '.claude' / 'settings.json')

    def test_an_ai_session_may_not_change_the_users_own_profile(self):
        own = self.home / '.claude' / 'settings.json'
        own.write_text('{"theme": "light"}', encoding='utf-8')
        for marker in ('CLAUDECODE', 'CLAUDE_CODE_CHILD_SESSION'):
            for verb in ('install', 'uninstall'):
                with self.subTest(marker=marker, verb=verb), patch.dict(os.environ, {marker: '1', 'CLAUDE_CONFIG_DIR': ''}):
                    out = io.StringIO()
                    with contextlib.redirect_stdout(out): code = hook_cli.main(['hook', 'user', verb, '--program', str(self.exe)])
                    self.assertEqual(code, 2)
                    self.assertIn('refused', out.getvalue())
                    self.assertEqual(own.read_text(encoding='utf-8'), '{"theme": "light"}')
                    self.assertFalse(own.with_name('settings.json.bak').exists())
        lab = self.base / 'lab-settings.json'
        with patch.dict(os.environ, {'CLAUDECODE': '1'}):                              # another file (a lab file) is allowed, and so is status
            self.assertEqual(self.verb('install', path=lab)[0], 0)                     # (review P2-3: the profile of CLAUDE_CONFIG_DIR is the owner's too, so not self.settings)
            self.assertEqual(self.verb('status', path=own)[0], 0)

    def test_the_owner_may_change_the_default_file_from_a_terminal_of_their_own(self):
        own = self.home / '.claude' / 'settings.json'
        with patch.dict(os.environ, {'CLAUDE_CONFIG_DIR': ''}):
            out = io.StringIO()
            with contextlib.redirect_stdout(out): code = hook_cli.main(['hook', 'user', 'install', '--program', str(self.exe)])
        self.assertEqual(code, 0, out.getvalue())
        self.assertEqual(len(json.loads(own.read_text(encoding='utf-8'))['hooks']['PreToolUse']), 1)

    def test_the_words_come_in_both_languages(self):
        for lang in ('en', 'vi'):
            with self.subTest(lang=lang), patch.dict(os.environ, {'ONECREW_LANG': lang}):
                self.seed()
                self.assertEqual(self.verb('install')[0], 0)
                self.assertIn('user hook' if lang == 'en' else 'hook người dùng', [name for _, name, _ in install.doctor_facts(self.repo, self.state, self.exe, claude=None)])
                self.verb('uninstall')


class RecordsBase(UserHookBase):
    """A is under an enforced plan; B and C have none. `call` runs one hook call; `records` reads A's violations.jsonl."""

    def setUp(self):
        super().setUp()
        self.a = self.base / 'du an A'
        self.b = self.base / 'B'
        self.c = self.base / 'C'
        for repo in (self.a, self.b, self.c):
            (repo / '.git').mkdir(parents=True)
            (repo / 'other.txt').write_text('x\n', encoding='utf-8')
        self.project_copy(self.a, owned=('src/a.txt',))

    def call(self, session, target, scope='user', agent=None, tool_use_id='toolu_1', tool='Write'):
        event = {'hook_event_name': 'PreToolUse', 'session_id': 'S', 'cwd': str(session), 'tool_name': tool, 'tool_input': {'file_path': str(target), 'content': 'x'}}
        if tool_use_id: event['tool_use_id'] = tool_use_id
        if agent: event.update(agent_id=agent[0], agent_type=agent[1])
        stdin = type('In', (), {'buffer': io.BytesIO(json.dumps(event).encode('utf-8'))})()
        err = io.StringIO()
        with patch.dict(os.environ, {'CLAUDE_PROJECT_DIR': str(session)}), patch.object(sys, 'stdin', stdin), contextlib.redirect_stderr(err):
            code = hook_cli.check(argparse.Namespace(project=None, state_root=None, scope=scope))
        return code, err.getvalue()

    def records(self, project=None):
        path = Path(project or self.a) / '.onecrew' / 'violations.jsonl'
        return [json.loads(line) for line in path.read_text(encoding='utf-8').splitlines()] if path.is_file() else []


class UserScopeRecords(RecordsBase):
    """The same check over the same places; a record only when the session's project has no OneCrew hook of its own; who made the call is in the record."""

    def test_a_session_opened_outside_is_judged_by_the_plan_of_the_project_it_writes_in(self):
        self.assertEqual(self.call(self.b, self.a / 'other.txt')[0], 2)
        self.assertEqual(self.call(self.b, self.a / 'src' / 'a.txt')[0], 0)
        self.assertEqual(self.call(self.b, self.b / 'other.txt')[0], 0)
        self.assertEqual(self.call(self.b, self.c / 'other.txt')[0], 0)

    def test_the_user_scope_decides_exactly_as_the_project_scope(self):
        for target in (self.a / 'other.txt', self.a / 'src' / 'a.txt', self.b / 'other.txt'):
            with self.subTest(target=str(target)):
                self.assertEqual(self.call(self.b, target, 'user')[0], self.call(self.b, target, 'project')[0])

    def test_a_record_carries_who_made_the_call(self):
        self.call(self.b, self.a / 'agent-out.txt', agent=('agent-123', 'general-purpose'), tool_use_id='toolu_agent')
        self.call(self.b, self.a / 'main-out.txt', tool_use_id='toolu_main')
        self.call(self.b, self.a / 'bare-out.txt', tool_use_id=None)
        by = {Path(r['subject']).name: r for r in self.records()}
        agent, main, bare = by['agent-out.txt'], by['main-out.txt'], by['bare-out.txt']
        self.assertEqual((agent['agent_id'], agent['agent_type'], agent['tool_use_id'], agent['session'], agent['scope']), ('agent-123', 'general-purpose', 'toolu_agent', 'S', 'user'))
        self.assertEqual((main['agent_id'], main['agent_type'], main['tool_use_id'], main['scope']), (None, None, 'toolu_main', 'user'))
        self.assertIn('agent_id', main)                                              # the field is there, null: never guessed
        self.assertEqual((bare['tool_use_id'], bare['agent_id']), (None, None))

    def test_the_project_hook_records_with_scope_project(self):
        self.call(self.a, self.a / 'other.txt', 'project')
        self.assertEqual([r['scope'] for r in self.records()], ['project'])

    def test_one_call_gives_one_record_when_the_project_has_its_own_hook(self):
        self.put(self.a / '.claude' / 'settings.local.json', {'hooks': {'PreToolUse': [{'matcher': 'Write', 'hooks': [
            {'type': 'command', 'command': 'C:/venv/Scripts/onecrew.exe', 'args': ['hook', 'check']}]}]}})
        target = self.a / 'other.txt'
        self.assertEqual(self.call(self.a, target, 'user', tool_use_id=None)[0], 2)  # the same decision ... (no tool_use_id: only the settings can tell)
        self.assertEqual(self.records(), [])                                         # ... and no record: the project hook writes it
        self.assertEqual(self.call(self.a, target, 'project', tool_use_id=None)[0], 2)
        self.assertEqual([r['scope'] for r in self.records()], ['project'])
        self.assertEqual(self.call(self.b, target, 'user', tool_use_id=None)[0], 2)  # a session in B has no project hook: this one records
        self.assertEqual([r['scope'] for r in self.records()], ['project', 'user'])

    def test_the_user_hook_in_the_settings_is_not_taken_for_a_project_hook(self):
        self.put(self.a / '.claude' / 'settings.local.json', {'hooks': {'PreToolUse': [{'hooks': [
            {'type': 'command', 'command': str(self.exe), 'args': ['hook', 'check', '--scope', 'user']}]}]}})
        self.assertFalse(hook_cli.has_project_hook(self.a))
        self.call(self.a, self.a / 'other.txt', 'user')
        self.assertEqual(len(self.records()), 1)

    def test_a_project_no_plan_governs_runs_normally_and_nothing_is_written_there(self):
        for tool, target in (('Write', self.c / 'x.txt'), ('Edit', self.c / 'other.txt')):
            self.assertEqual(self.call(self.c, target, tool=tool)[0], 0)
        self.assertFalse((self.c / '.onecrew').exists())
        stdin = type('In', (), {'buffer': io.BytesIO(json.dumps({'cwd': str(self.c), 'tool_name': 'Bash', 'tool_input': {'command': 'echo hi > y.txt'}, 'session_id': 'S'}).encode('utf-8'))})()
        with patch.dict(os.environ, {'CLAUDE_PROJECT_DIR': str(self.c)}), patch.object(sys, 'stdin', stdin):
            self.assertEqual(hook_cli.check(argparse.Namespace(project=None, state_root=None, scope='user')), 0)
        self.assertFalse((self.c / '.onecrew').exists())

    def test_a_later_prompt_hook_in_the_same_process_does_not_inherit_the_identity(self):
        self.call(self.b, self.a / 'agent-out.txt', agent=('agent-9', 'general-purpose'))
        hook_cli.note_call({})
        self.assertEqual((hook_cli.CALL['agent_id'], hook_cli.CALL['scope'], hook_cli.CALL['quiet']), (None, 'project', False))


class DoctorSaysWhetherTheUserHookIsThere(UserHookBase):
    def lines(self):
        return {name: (level, detail) for level, name, detail in install.doctor_facts(self.repo, self.state, self.exe, claude=None)}

    def test_not_configured_is_a_warning_that_says_what_is_not_checked(self):
        self.seed()
        level, detail = self.lines()['user hook']
        self.assertEqual(level, 'WARN')
        self.assertIn('not configured', detail)
        self.assertIn('subagents', detail)

    def test_configured_with_its_program_is_a_pass_and_a_missing_program_a_fail(self):
        self.seed()
        self.verb('install')
        level, detail = self.lines()['user hook']
        self.assertEqual(level, 'PASS')
        self.assertEqual(detail, f'configured in {self.settings} (program found)')
        self.exe.unlink()
        level, detail = self.lines()['user hook']
        self.assertEqual(level, 'FAIL')
        self.assertIn('program is missing', detail)

    def test_it_reads_the_file_of_the_home_folder_when_there_is_no_claude_config_dir(self):
        own = self.home / '.claude' / 'settings.json'
        self.verb('install', path=own)
        with patch.dict(os.environ, {'CLAUDE_CONFIG_DIR': ''}):
            self.assertEqual(self.lines()['user hook'][0], 'PASS')
        self.assertEqual(self.lines()['user hook'][0], 'WARN')                       # CLAUDE_CONFIG_DIR points at a folder with no settings

    def test_a_line_says_whether_a_user_scope_call_was_seen_in_this_project(self):
        self.assertIn('no user-scope call', self.lines()['user hook calls'][1])
        spool = self.repo / '.onecrew' / 'violations.jsonl'
        spool.parent.mkdir(parents=True, exist_ok=True)
        spool.write_text(json.dumps({'id': '1', 'at': '2026-11-17T01:02:03+00:00', 'session': 'S-old', 'scope': 'project'}) + '\n', encoding='utf-8')
        self.assertIn('no user-scope call', self.lines()['user hook calls'][1])
        with (self.repo / '.onecrew' / 'violations.jsonl').open('a', encoding='utf-8') as stream:
            stream.write(json.dumps({'id': '2', 'at': '2026-11-17T05:06:07+00:00', 'session': 'S-new', 'scope': 'user'}) + '\n')
        detail = self.lines()['user hook calls'][1]
        self.assertIn('2026-11-17T05:06:07+00:00', detail)
        self.assertIn('S-new', detail)


class InstallSafety(UserHookBase):
    """Review of 058211a: P2-1 (the program), P2-2 (a symlinked settings file), P2-3 (the profile of CLAUDE_CONFIG_DIR), P2-7 (doctor runs the program)."""

    def test_install_refuses_a_program_that_is_missing_misnamed_or_does_not_answer_version(self):
        self.seed()
        before = self.settings.read_bytes()
        odd = self.stub(self.base / 'odd', name='not-onecrew')
        broken = self.stub(self.base / 'broken', exit_code=3)
        for program in (self.base / 'nowhere' / 'onecrew.exe', odd, broken):
            with self.subTest(program=program.name):
                out = io.StringIO()
                with contextlib.redirect_stdout(out): code = hook_cli.main(['hook', 'user', 'install', '--settings-file', str(self.settings), '--program', str(program)])
                self.assertEqual(code, 2, out.getvalue())
                self.assertEqual(self.settings.read_bytes(), before)
                self.assertFalse(self.settings.with_name('settings.json.bak').exists())
        self.assertEqual(self.verb('install')[0], 0)

    def test_a_settings_file_that_is_a_symlink_is_written_through_and_stays_a_link(self):
        target = self.base / 'dotfiles' / 'settings.json'
        self.seed(path=target)
        link = self.base / 'link-settings.json'
        try:
            os.symlink(target, link)
        except (OSError, NotImplementedError):
            self.skipTest('symlinks are not permitted on this machine')
        before = target.read_bytes()
        self.assertEqual(self.verb('install', path=link)[0], 0)
        self.assertTrue(link.is_symlink())
        self.assertEqual(len([h for e in self.data(target)['hooks']['PreToolUse'] for h in e['hooks'] if h.get('args')]), 1)
        self.assertEqual(target.with_name('settings.json.bak').read_bytes(), before)           # the copy sits next to the target
        self.assertFalse(link.with_name(link.name + '.bak').exists())
        self.assertEqual(self.verb('uninstall', path=link)[0], 0)
        self.assertTrue(link.is_symlink())
        self.assertEqual(self.data(target), SEED)

    def test_an_ai_session_may_not_change_the_profile_of_claude_config_dir_either(self):
        self.seed()
        before = self.settings.read_bytes()
        for verb in ('install', 'uninstall'):
            with self.subTest(verb=verb), patch.dict(os.environ, {'CLAUDECODE': '1'}):
                out = io.StringIO()
                with contextlib.redirect_stdout(out): code = hook_cli.main(['hook', 'user', verb, '--program', str(self.exe)])      # the default file is that profile
                self.assertEqual(code, 2)
                self.assertIn('refused', out.getvalue())
                self.assertEqual(self.settings.read_bytes(), before)
        with patch.dict(os.environ, {'CLAUDECODE': '1'}):
            self.assertEqual(self.verb('install', path=self.settings)[0], 2)                  # also when named with --settings-file

    def test_doctor_fails_when_the_program_does_not_understand_the_scope_argument(self):
        self.seed()
        self.verb('install')
        self.assertEqual(self.exe.stat().st_size > 0, True)
        old = self.stub(self.base / 'old', exit_code=2)                                       # what a OneCrew from before #25 does with `--scope user`
        data = self.data()
        for entry in data['hooks']['PreToolUse']:
            for handler in entry['hooks']:
                if handler.get('args') == install.USER_ARGS: handler['command'] = str(old)
        self.settings.write_text(json.dumps(data), encoding='utf-8')
        level, name, detail = next(l for l in install.doctor_facts(self.repo, self.state, self.exe, claude=None) if l[1] == 'user hook')
        self.assertEqual(level, 'FAIL')
        self.assertIn('--scope user', detail)
        self.assertIn('uninstall', detail)


class OneRecordByToolUseId(RecordsBase):
    """P2-4: one call gives one record by tool_use_id, whichever hook comes first and whatever the project's settings say."""

    def test_the_second_hook_of_one_call_adds_no_line(self):
        target = self.a / 'other.txt'
        for first, second in (('project', 'user'), ('user', 'project')):
            with self.subTest(first=first):
                self.call(self.b, target, first, tool_use_id=f'toolu_{first}')
                self.call(self.b, target, second, tool_use_id=f'toolu_{first}')
        self.assertEqual(sorted(r['tool_use_id'] for r in self.records()), ['toolu_project', 'toolu_user'])
        self.assertEqual(sorted(r['scope'] for r in self.records()), ['project', 'user'])     # the first one's scope stays

    def test_an_old_project_hook_does_not_make_the_user_hook_lose_the_record(self):
        self.put(self.b / '.claude' / 'settings.local.json', {'hooks': {'PreToolUse': [{'matcher': 'Write', 'hooks': [
            {'type': 'command', 'command': 'C:/venv/Scripts/onecrew.exe', 'args': ['hook', 'check']}]}]}})
        self.assertEqual(self.call(self.b, self.a / 'other.txt', 'user', tool_use_id='toolu_old')[0], 2)
        self.assertEqual([r['scope'] for r in self.records()], ['user'])                      # the old hook never judged it, so nobody else would record it

    def test_different_calls_and_a_call_without_an_id_are_all_recorded(self):
        target = self.a / 'other.txt'
        self.call(self.b, target, tool_use_id='toolu_x')
        self.call(self.b, target, tool_use_id='toolu_y')
        self.call(self.b, target, tool_use_id=None)
        self.call(self.b, target, tool_use_id=None)
        self.assertEqual(len(self.records()), 4)


class TwoHooksAtOnce(RecordsBase):
    """Review 2 P2-A: Claude Code starts the project hook and the user hook of one call at the same time; a marker created with O_EXCL decides who writes."""

    def test_only_one_of_many_simultaneous_claims_wins(self):
        import threading
        folder = self.a / '.onecrew'
        folder.mkdir(exist_ok=True)
        plan, wins, gate = {'plan': 'P'}, [], threading.Barrier(16)

        def go():
            gate.wait()
            wins.append(hook_cli.claim_call(folder, plan, 'toolu_race'))
        threads = [threading.Thread(target=go) for _ in range(16)]
        for t in threads: t.start()
        for t in threads: t.join()
        self.assertEqual(wins.count(True), 1)
        self.assertTrue((folder / 'calls' / 'toolu_race.P').is_file())

    def test_a_call_without_an_id_always_claims_and_another_plan_or_id_is_its_own_claim(self):
        folder = self.a / '.onecrew'
        folder.mkdir(exist_ok=True)
        self.assertTrue(hook_cli.claim_call(folder, {'plan': 'P'}, None))
        self.assertTrue(hook_cli.claim_call(folder, {'plan': 'P'}, None))
        self.assertTrue(hook_cli.claim_call(folder, {'plan': 'P'}, 'toolu_1'))
        self.assertFalse(hook_cli.claim_call(folder, {'plan': 'P'}, 'toolu_1'))
        self.assertTrue(hook_cli.claim_call(folder, {'plan': 'Q'}, 'toolu_1'))
        self.assertTrue(hook_cli.claim_call(folder, {'plan': 'P'}, 'toolu_2'))

    def test_the_marker_alone_decides_even_when_the_tail_of_the_log_shows_nothing(self):
        self.assertEqual(self.call(self.b, self.a / 'other.txt', 'user', tool_use_id='toolu_z')[0], 2)
        self.assertEqual(len(self.records()), 1)
        (self.a / '.onecrew' / 'violations.jsonl').unlink()                # the winner's line is not there (yet): only the marker says who is first
        code, _ = self.call(self.b, self.a / 'other.txt', 'project', tool_use_id='toolu_z')
        self.assertEqual(code, 2)                                          # still blocked: the claim only decides who records
        self.assertEqual(self.records(), [])

    def test_the_user_hook_stays_quiet_when_the_project_hook_runs_the_same_program(self):
        program = os.path.normcase(os.path.realpath(str(self.exe)))
        self.put(self.b / '.claude' / 'settings.local.json', {'hooks': {'PreToolUse': [{'matcher': 'Write', 'hooks': [
            {'type': 'command', 'command': str(self.exe), 'args': ['hook', 'check']}]}]}})
        self.assertTrue(hook_cli.has_project_hook(self.b, program))
        self.assertFalse(hook_cli.has_project_hook(self.b, os.path.normcase(str(self.base / 'elsewhere' / 'onecrew.exe'))))


class InstallSafetyRound2(UserHookBase):
    """Review 2 P3-2 (a program that answers --version but not `hook check --scope user`) and P3-3 (a symlink that loops or points nowhere)."""

    def test_install_refuses_an_old_program_that_answers_version_only(self):
        self.seed()
        before = self.settings.read_bytes()
        old = self.stub(self.base / 'old')
        with patch.object(install, 'program_runs_scope', return_value=(False, 'exit 2: unrecognized arguments')):
            out = io.StringIO()
            with contextlib.redirect_stdout(out): code = hook_cli.main(['hook', 'user', 'install', '--settings-file', str(self.settings), '--program', str(old)])
        self.assertEqual(code, 2, out.getvalue())
        self.assertIn('--scope user', out.getvalue())
        self.assertEqual(self.settings.read_bytes(), before)
        self.assertFalse(self.settings.with_name('settings.json.bak').exists())

    def test_a_dangling_symlink_is_refused_and_left_as_it_is(self):
        link = self.base / 'dangling.json'
        try:
            os.symlink(self.base / 'nowhere' / 'settings.json', link)
        except (OSError, NotImplementedError):
            self.skipTest('symlinks are not permitted on this machine')
        for verb in ('install', 'uninstall'):
            with self.subTest(verb=verb):
                code, out = self.verb(verb, path=link)
                self.assertEqual(code, 2, out)
                self.assertTrue(link.is_symlink())
                self.assertFalse((self.base / 'nowhere').exists())

    def test_a_looping_symlink_is_refused_and_not_replaced_by_a_file(self):
        one, two = self.base / 'loopA.json', self.base / 'loopB.json'
        try:
            os.symlink(two, one)
            os.symlink(one, two)
        except (OSError, NotImplementedError):
            self.skipTest('symlinks are not permitted on this machine')
        code, out = self.verb('install', path=one)
        self.assertEqual(code, 2, out)
        self.assertTrue(one.is_symlink() and two.is_symlink())
        self.assertFalse(one.with_name('loopA.json.bak').exists())


class SyncCarriesTheIdentity(Fixture):
    def test_hook_sync_writes_the_identity_fields_into_the_ledger_events(self):
        self.approved('P1', plan_json(scope={'owned': ['a.txt']}))
        active_plan.set_mode(self.ledger, 'enforce')
        active_plan.export(self.ledger, 'P1')
        event = {'session_id': 'S', 'cwd': str(self.root), 'tool_name': 'Write', 'tool_input': {'file_path': str(self.root / 'other.txt'), 'content': 'x'},
                 'tool_use_id': 'toolu_sync', 'agent_id': 'agent-sync', 'agent_type': 'general-purpose'}
        stdin = type('In', (), {'buffer': io.BytesIO(json.dumps(event).encode('utf-8'))})()
        with patch.dict(os.environ, {'CLAUDE_PROJECT_DIR': str(self.root)}), patch.object(sys, 'stdin', stdin), contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(hook_cli.check(argparse.Namespace(project=None, state_root=None, scope='user')), 2)
        result = hook_cli.sync(argparse.Namespace(project=self.root, state_root=self.ledger.state_root))
        self.assertEqual(result['imported'], 1)
        payload = next(p for k, p in self.events() if k == 'hook.blocked')
        self.assertEqual((payload['agent_id'], payload['agent_type'], payload['tool_use_id'], payload['scope']), ('agent-sync', 'general-purpose', 'toolu_sync', 'user'))


if __name__ == '__main__':
    unittest.main()
