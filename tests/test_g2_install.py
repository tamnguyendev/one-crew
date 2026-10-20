"""G2 (OneCrew 2.2): `onecrew init`, `onecrew doctor`, `onecrew owner ...`, the portable hook, the two languages, the package data.

Plain unittest and stdlib only. It runs from a checkout (`python -m unittest discover -s tests`) and inside the Linux container (`-m unittest tests.test_g2_install`),
so it imports nothing from the sibling tests and the one test that needs git is skipped where git is missing.
"""
import argparse
import contextlib
import io
import json
import os
import re
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from onecrew.ledger import Ledger
from onecrew.v2 import cli, hook_cli, install, messages, owner_cli, ownership, plan_cli, where
from onecrew.v2.verifiers import advisor

ROOT = Path(__file__).resolve().parents[1]
DIACRITICS = re.compile('[ăâđêôơưĂÂĐÊÔƠƯàáảãạằắẳẵặầấẩẫậèéẻẽẹềếểễệìíỉĩịòóỏõọồốổỗộờớởỡợùúủũụừứửữựỳýỷỹỵ]', re.I)
LOGGED_IN = lambda: ('ok', '/usr/bin/claude', '')
NO_CLAUDE = lambda: ('missing', None, '')
FORBIDDEN_IN_HANDLER = ('sys.path.insert', 'sys.executable', '--project', '--state-root', 'python', '.venv', 'onecrew_cli.py', 'worktrees')
OWNER_FORMS = ('owner approve', 'owner accept', 'owner enforce', 'owner record')


def run(function, *args, **kwargs):
    """(exit code, stdout) of an in-process call."""
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        code = function(*args, **kwargs)
    return code, out.getvalue()


class Base(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.repo = self.base / 'project'; (self.repo / '.git').mkdir(parents=True)      # a directory called .git is all `git_root` looks for
        self.state = self.base / 'state'
        self.exe = self.base / 'venv' / 'bin' / 'onecrew'; self.exe.parent.mkdir(parents=True); self.exe.write_text('#!/bin/sh\n')
        env = patch.dict(os.environ); env.start(); self.addCleanup(env.stop)
        for name in ('ONECREW_ACTOR', 'CLAUDECODE', 'CLAUDE_CODE_CHILD_SESSION', 'ONECREW_LANG', 'CLAUDE_PROJECT_DIR'): os.environ.pop(name, None)

    def init(self, **kwargs):
        options = dict(project=self.repo, state_root=self.state, yes=True, exe=self.exe, claude=LOGGED_IN)
        return run(install.init, **dict(options, **kwargs))

    @property
    def settings_path(self):
        return self.repo / '.claude' / 'settings.local.json'

    def settings(self):
        return json.loads(self.settings_path.read_text(encoding='utf-8'))


class InitTests(Base):
    def test_init_writes_state_rules_config_and_hooks(self):
        code, out = self.init()
        self.assertEqual(code, 0, out)
        self.assertTrue((self.state / 'ledger.sqlite3').is_file())
        self.assertTrue((self.state / 'plans' / 'owner-rules.md').is_file())
        self.assertEqual(Path(where.read_config(self.repo)['state_root']).resolve(), self.state.resolve())
        self.assertTrue(self.settings_path.is_file())
        self.assertFalse((self.repo / '.claude' / 'settings.json').exists())
        self.assertEqual(set(self.settings()['hooks']), {'PreToolUse', 'UserPromptSubmit', 'Stop', 'SessionStart'})

    def test_a_second_init_changes_no_byte(self):
        self.init()
        files = [self.settings_path, where.config_file(self.repo), self.state / 'plans' / 'owner-rules.md']
        before = [p.read_bytes() for p in files]
        code, out = self.init()
        self.assertEqual((code, [p.read_bytes() for p in files]), (0, before))
        self.assertIn('nothing to change', out)
        self.assertFalse(self.settings_path.with_name('settings.local.json.bak').exists())      # nothing existed before the first run

    def test_the_hook_handlers_name_the_installed_command_and_nothing_else(self):
        self.init()
        handlers = [h for entries in self.settings()['hooks'].values() for e in entries for h in e['hooks']]
        self.assertEqual(len(handlers), 4)
        for handler in handlers:
            self.assertEqual(handler['command'], str(self.exe.resolve()))
            self.assertEqual(handler['args'][0], 'hook'); self.assertEqual(len(handler['args']), 2)
            rest = json.dumps(dict(handler, command='')).casefold()
            self.assertEqual([w for w in FORBIDDEN_IN_HANDLER if w.casefold() in rest], [])
        verbs = [h['args'][1] for h in handlers]
        self.assertEqual(sorted(verbs), ['check', 'prompt', 'session', 'stop'])
        gate = self.settings()['hooks']['PreToolUse'][0]
        self.assertEqual((gate['hooks'][0]['onFailure'], gate['hooks'][0]['timeout']), ('block', 15))      # as `hook install --print` has always said

    def test_the_generator_does_not_name_a_repo_an_interpreter_or_a_path(self):
        """The function that makes the handlers contains none of the checkout-only parts."""
        import inspect
        source = inspect.getsource(hook_cli.portable_settings)
        for word in ('sys.path.insert', 'sys.executable', '--project', '--state-root', 'onecrew_cli', '.venv'):
            self.assertNotIn(word, source)

    def test_deny_has_every_owner_verb_in_both_shells(self):
        self.init()
        deny = self.settings()['permissions']['deny']
        for verb in OWNER_FORMS + ('plan approve', 'plan accept', 'plan enforce', 'verdict record', 'hook mode'):
            for shell in ('Bash', 'PowerShell'):
                self.assertIn(f'{shell}(*{verb}*)', deny)
        self.assertIn('Bash(git push:*)', deny)                                  # today's list stays

    def test_init_merges_and_keeps_what_is_there(self):
        seed = {'hooks': {'PreToolUse': [{'matcher': 'Foo', 'hooks': [{'type': 'command', 'command': 'echo other-tool'}]}], 'Notification': [{'hooks': [{'type': 'command', 'command': 'echo n'}]}]},
                'permissions': {'allow': ['Bash(ls:*)'], 'deny': ['Bash(rm -rf:*)'], 'ask': ['Bash(make:*)']}, 'theme': 'keep-me', 'env': {'A': '1'}}
        self.settings_path.parent.mkdir(parents=True)
        original = json.dumps(seed, indent=1)
        self.settings_path.write_text(original, encoding='utf-8')
        self.assertEqual(self.init()[0], 0)
        merged = self.settings()
        self.assertEqual((merged['theme'], merged['env'], merged['permissions']['allow'], merged['permissions']['ask']), ('keep-me', {'A': '1'}, ['Bash(ls:*)'], ['Bash(make:*)']))
        self.assertEqual(merged['permissions']['deny'][0], 'Bash(rm -rf:*)')
        self.assertIn('Bash(*owner approve*)', merged['permissions']['deny'])
        self.assertEqual(merged['hooks']['Notification'], seed['hooks']['Notification'])
        commands = [h['command'] for e in merged['hooks']['PreToolUse'] for h in e['hooks']]
        self.assertEqual(commands, ['echo other-tool', str(self.exe.resolve())])
        self.assertEqual(self.settings_path.with_name('settings.local.json.bak').read_text(encoding='utf-8'), original)

    def test_init_replaces_its_own_entries_and_never_doubles_them(self):
        self.init()
        moved = self.base / 'other' / 'onecrew'; moved.parent.mkdir(); moved.write_text('x')
        self.init(exe=moved)
        merged = self.settings()
        for event, entries in merged['hooks'].items():
            self.assertEqual(len(entries), 1, event)
            self.assertEqual(entries[0]['hooks'][0]['command'], str(moved.resolve()))
        self.assertEqual(len(merged['permissions']['deny']), len(set(merged['permissions']['deny'])))
        self.assertTrue(self.settings_path.with_name('settings.local.json.bak').exists())          # the first run's file was the original of the second

    def test_the_old_checkout_form_is_recognised_and_replaced(self):
        old = hook_cli.settings(self.repo, self.state, ROOT)
        self.settings_path.parent.mkdir(parents=True)
        self.settings_path.write_text(json.dumps(old), encoding='utf-8')
        self.init()
        text = json.dumps(self.settings()['hooks'])
        self.assertNotIn('hook_cli', text); self.assertNotIn('--project', text)

    def test_shared_writes_settings_json(self):
        self.assertEqual(self.init(shared=True)[0], 0)
        self.assertTrue((self.repo / '.claude' / 'settings.json').is_file())
        self.assertFalse(self.settings_path.exists())

    def test_a_settings_file_that_is_not_json_is_left_alone(self):
        self.settings_path.parent.mkdir(parents=True)
        self.settings_path.write_text('{ not json', encoding='utf-8')
        code, out = self.init()
        self.assertEqual(code, 2)
        self.assertEqual(self.settings_path.read_text(encoding='utf-8'), '{ not json')
        self.assertFalse(where.config_file(self.repo).exists())            # nothing was written before the refusal

    def test_a_wrong_shape_is_told_apart_from_bad_json_and_both_follow_the_language(self):
        self.settings_path.parent.mkdir(parents=True)
        self.settings_path.write_text('{"hooks": []}', encoding='utf-8')
        english = self.init()
        self.assertEqual(english[0], 2)
        self.assertIn('wrong shape: "hooks" must be an object', english[1]); self.assertNotIn('not valid JSON', english[1])
        self.settings_path.write_text('[1, 2]', encoding='utf-8')
        self.assertIn('top level is not an object', self.init()[1])
        self.settings_path.write_text('{ not json', encoding='utf-8')
        self.assertIn('not valid JSON (line 1, column 3)', self.init()[1])
        with patch.dict(os.environ, {'ONECREW_LANG': 'vi'}):
            for text in ('{"hooks": []}', '[1]', '{ nope'):
                self.settings_path.write_text(text, encoding='utf-8')
                code, out = self.init()
                self.assertEqual(code, 2)
                self.assertNotRegex(out, r'\b(is not|must be|wrong|valid JSON|Nothing was changed)\b')       # no English sentence inside the Vietnamese one
                self.assertTrue(DIACRITICS.search(out))
            self.settings_path.write_text('{ nope', encoding='utf-8')
            doctor = run(install.doctor, project=self.repo, state_root=self.state, exe=self.exe, claude=LOGGED_IN)[1]
        self.assertTrue(any(l.startswith('FAIL') and 'JSON' in l and 'dòng' in l for l in doctor.splitlines()), doctor)
        self.assertEqual(self.settings_path.read_text(encoding='utf-8'), '{ nope')

    def test_the_claude_status_reason_is_a_code_not_an_english_sentence(self):
        def silent(argv, **kw): return type('Done', (), {'stdout': 'odd', 'stderr': '', 'returncode': 3})()
        with patch('onecrew.v2.claude_cli.cli_argv', return_value=['/x/claude']), patch.dict(os.environ, {'ONECREW_LANG': 'vi'}):
            self.assertEqual(install.claude_status(run=silent), ('unknown', '/x/claude', 'mã thoát 3'))

    def test_without_yes_it_asks_and_a_no_writes_nothing(self):
        code, out = self.init(yes=False, ask=lambda prompt: 'n')
        self.assertEqual(code, 2)
        self.assertFalse(self.settings_path.exists()); self.assertFalse(self.state.exists())
        code, out = self.init(yes=False, ask=lambda prompt: (_ for _ in ()).throw(EOFError()))      # no terminal: counts as no
        self.assertEqual(code, 2)
        code, out = self.init(yes=False, ask=lambda prompt: 'y')
        self.assertEqual(code, 0); self.assertTrue(self.settings_path.is_file())

    def test_exit_1_when_the_claude_cli_is_missing_but_everything_is_written(self):
        code, out = self.init(claude=NO_CLAUDE)
        self.assertEqual(code, 1)
        self.assertTrue(self.settings_path.is_file()); self.assertTrue((self.state / 'ledger.sqlite3').is_file())
        self.assertIn('Claude CLI: not found', out)
        code, out = self.init(claude=lambda: ('logged_out', '/x/claude', ''))
        self.assertEqual(code, 1); self.assertIn('not logged in', out)

    def test_init_outside_a_git_repo_or_without_an_installed_command_writes_nothing(self):
        loose = self.base / 'loose'; loose.mkdir()
        code, out = run(install.init, project=loose, state_root=self.state, yes=True, exe=self.exe, claude=LOGGED_IN)
        self.assertEqual(code, 2); self.assertFalse(self.state.exists())
        with patch.object(install, 'installed_exe', return_value=None):
            code, out = run(install.init, project=self.repo, state_root=self.state, yes=True, claude=LOGGED_IN)
        self.assertEqual(code, 2); self.assertIn('installed', out); self.assertFalse(self.state.exists())

    def test_a_state_root_inside_the_project_is_refused(self):
        code, out = self.init(state_root=self.repo / 'state')
        self.assertEqual(code, 2); self.assertFalse(self.settings_path.exists())

    def test_the_claude_status_reads_the_auth_status_answer(self):
        def fake(stdout, code=0):
            return lambda argv, **kw: type('Done', (), {'stdout': stdout, 'stderr': '', 'returncode': code})()
        with patch('onecrew.v2.claude_cli.cli_argv', return_value=['/x/claude']):
            self.assertEqual(install.claude_status(run=fake('{"loggedIn": true}'))[0], 'ok')
            self.assertEqual(install.claude_status(run=fake('{"loggedIn": false}', 1))[0], 'logged_out')
            self.assertEqual(install.claude_status(run=fake('Not logged in', 1))[0], 'logged_out')
            self.assertEqual(install.claude_status(run=fake('something odd', 3))[0], 'unknown')
            def boom(argv, **kw): raise OSError('no')
            self.assertEqual(install.claude_status(run=boom)[0], 'unknown')
        from onecrew.ledger import LedgerError
        with patch('onecrew.v2.claude_cli.cli_argv', side_effect=LedgerError('nothing')):
            self.assertEqual(install.claude_status()[0], 'missing')


class DoctorTests(Base):
    def doctor(self, git='/usr/bin/git', **kwargs):
        real = shutil.which
        with patch.object(install.shutil, 'which', lambda name, *a, **k: git if name == 'git' else real(name, *a, **k)):
            code, out = run(install.doctor, **dict(dict(project=self.repo, state_root=None, exe=self.exe, claude=LOGGED_IN), **kwargs))
        return code, [l for l in out.splitlines() if l.startswith(('PASS', 'WARN', 'FAIL'))], out

    def test_git_missing_fails(self):
        self.init()
        code, lines, _ = self.doctor(git=None)
        self.assertEqual(code, 1); self.assertTrue(any(l.startswith('FAIL git') for l in lines))

    def test_all_pass_after_init(self):
        self.init()
        code, lines, out = self.doctor()
        self.assertGreaterEqual(len(lines), 6)
        self.assertEqual((code, [l for l in lines if not l.startswith('PASS')]), (0, []), out)
        text = '\n'.join(lines).casefold()
        for word in ('python', 'git', 'claude cli', 'config.json', 'hook', 'active plan'): self.assertIn(word, text)

    def test_a_missing_claude_cli_warns_and_the_exit_stays_0(self):
        self.init()
        code, lines, _ = self.doctor(claude=NO_CLAUDE)
        self.assertEqual(code, 0)
        self.assertEqual(len([l for l in lines if l.startswith('WARN')]), 2)         # found + logged in

    def test_a_missing_hook_and_a_missing_state_root_fail(self):
        code, lines, _ = self.doctor()
        self.assertEqual(code, 1)
        failing = '\n'.join(l for l in lines if l.startswith('FAIL')).casefold()
        self.assertIn('hook', failing); self.assertIn('init', failing)

    def test_a_hook_that_points_nowhere_fails_and_a_changed_one_warns(self):
        self.init()
        data = self.settings()
        data['hooks']['Stop'][0]['timeout'] = 99
        self.settings_path.write_text(json.dumps(data), encoding='utf-8')
        code, lines, _ = self.doctor()
        self.assertEqual(code, 0)
        self.assertTrue(any(l.startswith('WARN') and 'hook' in l.casefold() for l in lines))
        self.exe.unlink()
        code, lines, _ = self.doctor(exe=None)
        self.assertEqual(code, 1); self.assertTrue(any(l.startswith('FAIL') and 'does not exist' in l for l in lines))

    def test_an_unreadable_active_plan_fails_and_a_readable_one_is_named(self):
        self.init()
        plan_file = self.repo / '.onecrew' / hook_cli.FILE
        plan_file.write_text('{ broken', encoding='utf-8')
        code, lines, _ = self.doctor()
        self.assertEqual(code, 1); self.assertTrue(any(l.startswith('FAIL') and 'active plan' in l for l in lines))
        plan_file.write_text(json.dumps({'plan': 'demo', 'revision': 3, 'mode': 'log', 'owned': ['a']}), encoding='utf-8')
        code, lines, _ = self.doctor()
        self.assertTrue(any('demo revision 3, hook mode log' in l for l in lines))

    def test_the_two_languages(self):
        self.init()
        _, english, _ = self.doctor()
        self.assertFalse(DIACRITICS.search('\n'.join(english)))
        with patch.dict(os.environ, {'ONECREW_LANG': 'vi'}):
            _, vietnamese, out = self.doctor()
        self.assertTrue(DIACRITICS.search('\n'.join(vietnamese)))
        self.assertTrue(all(l.split()[0] in ('PASS', 'WARN', 'FAIL') for l in vietnamese))       # the level words stay the same in both languages
        self.assertEqual(len(english), len(vietnamese))


class MessagesTests(unittest.TestCase):
    def fields(self, text):
        return sorted(re.findall(r'\{(\w+)\}', text))

    def test_every_key_has_both_languages_with_the_same_placeholders(self):
        for key, value in messages.TEXT.items():
            self.assertEqual(set(value), {'en', 'vi'}, key)
            self.assertEqual(self.fields(value['en']), self.fields(value['vi']), key)

    def test_english_has_no_vietnamese_letters_and_vietnamese_differs(self):
        for key, value in messages.TEXT.items():
            self.assertFalse(DIACRITICS.search(value['en']), key)
        different = [k for k, v in messages.TEXT.items() if DIACRITICS.search(v['vi'])]
        self.assertGreater(len(different), len(messages.TEXT) * 0.8)

    def test_no_vietnamese_text_is_a_copy_of_the_english_one(self):
        neutral = re.compile(r'\{\w+\}|python|git|PASS|WARN|FAIL|onecrew|enforce|owner|state_root|[^A-Za-z]|\b\w{1,2}\b')      # names, levels, placeholders: the same in both languages
        same = [k for k, v in messages.TEXT.items() if v['en'] == v['vi'] and re.search(r'[A-Za-z]{3,}', neutral.sub(' ', v['en']))]
        self.assertEqual(same, [])

    def test_the_language_switch(self):
        with patch.dict(os.environ, {'ONECREW_LANG': 'vi'}): self.assertEqual((messages.lang(), messages.t('init.nothing')[:2]), ('vi', 'Mọ'))
        with patch.dict(os.environ, {'ONECREW_LANG': ''}): self.assertEqual(messages.lang(), 'en')
        with patch.dict(os.environ, {'ONECREW_LANG': 'fr'}): self.assertEqual(messages.lang(), 'en')

    def test_the_words_are_in_one_module(self):
        for name in ('install.py', 'owner_cli.py', 'where.py'):
            text = (ROOT / 'onecrew' / 'v2' / name).read_text(encoding='utf-8')
            self.assertEqual(DIACRITICS.findall(text), [], name)


class OwnerTests(Base):
    def test_every_owner_form_is_named_and_refused_in_an_ai_session(self):
        for form in (('owner', 'approve'), ('owner', 'accept'), ('owner', 'enforce'), ('owner', 'record')):
            self.assertIn(form, ownership.OWNER_VERBS)
        argvs = [['owner', 'approve', 'p', '--reference', 'r'], ['owner', 'accept', 'p', '--artifact-sha', 'a' * 40, '--reference', 'r'],
                 ['owner', 'enforce', 'p', '--mode', 'log'], ['owner', 'record', '--plan', 'p', '--milestone', 'M1', '--result', 'pass']]
        for argv in argvs:
            self.assertIsNone(ownership.refuse_argv(argv), argv)                         # outside an AI session the router lets it through
            with patch.dict(os.environ, {'CLAUDE_CODE_CHILD_SESSION': '1'}):
                out = io.StringIO()
                with contextlib.redirect_stdout(out): code = cli.main(argv)
                self.assertEqual(code, 2, argv); self.assertIn('refused', out.getvalue())

    def test_a_refused_verb_writes_nothing_to_the_ledger(self):
        with patch.dict(os.environ, {'CLAUDE_CODE_CHILD_SESSION': '1'}):
            code, out = run(cli.main, ['--project', str(self.repo), '--state-root', str(self.state), 'owner', 'approve', 'p', '--reference', 'x'])
        self.assertEqual(code, 2)
        self.assertFalse(self.state.exists())

    def test_the_verbs_stand_for_the_older_commands_with_by_owner(self):
        translate = lambda argv: owner_cli.translate(owner_cli._parser().parse_args(argv))
        self.assertEqual(translate(['approve', 'p', '--reference', 'R', '--choose', 'B', '--tick', 'S1', '--tick', 'S2', '--revision', '2']),
                         ('plan_cli', ['plan', 'approve', 'p', '--by', 'owner', '--reference', 'R', '--revision', '2', '--tick', 'S1', '--tick', 'S2', '--choose', 'B']))
        self.assertEqual(translate(['accept', 'p', '--artifact-sha', 'abc', '--reference', 'R']),
                         ('plan_cli', ['plan', 'accept', 'p', '--by', 'owner', '--reference', 'R', '--artifact-sha', 'abc']))
        self.assertEqual(translate(['enforce', 'p', '--mode', 'log'])[1][:5], ['hook', 'mode', 'log', '--by', 'owner'])
        self.assertEqual(translate(['enforce', 'p'])[1][2], 'enforce')
        record = translate(['record', '--plan', 'p', '--milestone', 'M1', '--result', 'pass', '--artifact-sha', 'abc', '--receipt-file', 'f.txt', '--reference', 'R'])
        self.assertEqual((record[0], record[1][:2], record[1][record[1].index('--by') + 1]), ('plan_cli', ['verdict', 'record'], 'owner'))
        self.assertEqual(record[1][record[1].index('--reference') + 1], 'R')

    def test_the_reference_of_an_owner_record_reaches_the_verdict(self):
        receipt = self.base / 'receipt.txt'; receipt.write_text('seen', encoding='utf-8')
        with patch('onecrew.v2.verdict.record', return_value={'ok': True}) as recorded:
            code, out = run(plan_cli.main, ['--project', str(self.repo), '--state-root', str(self.state), 'verdict', 'record', '--plan', 'p', '--milestone', 'M1',
                                            '--result', 'pass', '--by', 'owner', '--artifact-sha', 'a' * 40, '--receipt-file', str(receipt), '--reference', 'tried it on the phone'])
        self.assertEqual(code, 0, out)
        self.assertEqual(recorded.call_args[0][-1], 'tried it on the phone')
        with patch('onecrew.v2.verdict.record', return_value={'ok': True}) as recorded:           # the older call, without it, is as before
            run(plan_cli.main, ['--project', str(self.repo), '--state-root', str(self.state), 'verdict', 'record', '--plan', 'p', '--milestone', 'M1', '--result', 'pass',
                                '--by', 'owner', '--artifact-sha', 'a' * 40, '--receipt-file', str(receipt)])
        self.assertIsNone(recorded.call_args[0][-1])

    def test_the_output_of_init_and_owner_in_both_languages(self):
        _, english = self.init()
        self.assertFalse(DIACRITICS.search(english), english)
        other = self.base / 'other'; (other / '.git').mkdir(parents=True)
        with patch.dict(os.environ, {'ONECREW_LANG': 'vi'}):
            _, vietnamese = run(install.init, project=other, state_root=self.base / 'state-vi', yes=True, exe=self.exe, claude=NO_CLAUDE)
            _, bad = run(install.init, project=other, state_root=other / 'inside', yes=True, exe=self.exe, claude=NO_CLAUDE)      # a LedgerError, translated around
            _, cancelled = run(install.init, project=self.base / 'loose-vi', state_root=None, yes=True, exe=self.exe, claude=NO_CLAUDE)
            helps = [install._parser().format_help(), owner_cli._parser().format_help(), run(cli.main, ['--help'])[1]]
        for text in (vietnamese, bad, cancelled, *helps): self.assertTrue(DIACRITICS.search(text), text)
        self.assertTrue(bad.startswith('init dừng:'), bad)                         # the sentence of the new command is Vietnamese; the core's own text follows it as it is
        self.assertIn('Tạo sổ', helps[0]); self.assertIn('động từ của chủ sở hữu', helps[2])
        with patch.dict(os.environ, {'ONECREW_LANG': 'vi'}):
            approve = owner_cli._parser()._subparsers._group_actions[0].choices['approve'].format_help()
        self.assertIn('LỰA_CHỌN', approve); self.assertIn('MỤC', approve)
        self.assertNotIn('OPTION', approve)

    def test_a_broken_active_plan_is_reported_by_a_vietnamese_sentence(self):
        self.init()
        (self.repo / '.onecrew' / hook_cli.FILE).write_text('{ broken', encoding='utf-8')
        with patch.dict(os.environ, {'ONECREW_LANG': 'vi'}):
            out = run(install.doctor, project=self.repo, state_root=self.state, exe=self.exe, claude=LOGGED_IN)[1]
        line = next(l for l in out.splitlines() if 'active-plan.json' in l)
        self.assertTrue(line.startswith('FAIL') and 'không đọc được' in line, line)
        self.assertFalse(DIACRITICS.search('\n'.join([install._parser().format_help(), owner_cli._parser().format_help(), run(cli.main, ['--help'])[1]])))

    def verdict_shas(self, node):
        if isinstance(node, dict):
            last = node.get('last_verdict')
            if isinstance(last, dict) and last.get('result') in (None, 'pass') and last.get('artifact_sha'): yield last['artifact_sha']
            for value in node.values(): yield from self.verdict_shas(value)
        elif isinstance(node, list):
            for value in node: yield from self.verdict_shas(value)

    @unittest.skipUnless(shutil.which('git'), 'git is not installed')
    def test_the_whole_flow_with_the_new_commands(self):
        import subprocess
        git = lambda *a: subprocess.run(['git', '-C', str(repo), *a], check=True, capture_output=True)
        repo = self.base / 'real'; repo.mkdir()
        git('init', '-q'); git('config', 'user.name', 'G2'); git('config', 'user.email', 'g2@localhost')
        (repo / 'a.txt').write_text('one\n'); git('add', '.'); git('commit', '-q', '-m', 'base')
        state = self.base / 'real-state'
        self.assertEqual(run(install.init, project=repo, state_root=state, yes=True, exe=self.exe, claude=LOGGED_IN)[0], 0)
        contract = {'schema_version': 2, 'title': 'G2 sample', 'size': 'S',
                    'understanding': {'restated_goal': 'Prove the owner verbs work.', 'target': {'repo': '.', 'ref': 'HEAD', 'paths': ['a.txt']}, 'assumptions': [], 'confidence': 'high', 'unknowns': []},
                    'preconditions': [{'id': 'P1', 'check': 'path_exists', 'args': {'path': 'a.txt'}, 'why': 'the file is there'}],
                    'output': ['The sample exists'], 'scope': {'owned': ['a.txt']}, 'non_goals': ['Nothing else'],
                    'items': [{'id': 'I1', 'title': 'Do it', 'tier': 'must', 'milestone': 'M1', 'source': 'origin'}],
                    'origin': {'by': 'owner', 'at': '2026-10-20', 'quote': 'Prove the owner verbs work.'},       # init writes the owner rules, so approve is strict about where a contract comes from
                    'milestones': [{'id': 'M1', 'title': 'Milestone M1', 'covers': ['O1'], 'verifier': {'type': 'command', 'config': {'argv': [sys.executable, '-c', 'print("ok")']}}}],
                    'budget': {'max_calls': 10, 'time': 30}, 'attention': {'questions': 1}, 'profile_version': None}
        file = self.base / 'contract.json'; file.write_text(json.dumps(contract), encoding='utf-8')
        env = {'CLAUDE_PROJECT_DIR': str(repo)}
        cwd = os.getcwd(); os.chdir(repo); self.addCleanup(os.chdir, cwd)
        with patch.dict(os.environ, env):                                                 # no --project / --state-root anywhere: config.json answers
            self.assertEqual(run(cli.main, ['plan', 'propose', 'flow', '--file', str(file), '--author', 'claude-sonnet-5-5'])[0], 0)
            code, out = run(cli.main, ['owner', 'approve', 'flow', '--reference', 'test'])
            self.assertEqual((code, '"approved"' in out), (0, True), out)
            code, out = run(cli.main, ['owner', 'enforce', 'flow'])
            self.assertEqual((code, 'enforce' in out), (0, True), out)
            blocked = json.dumps({'tool_name': 'Edit', 'tool_input': {'file_path': str(repo / 'b.txt')}, 'cwd': str(repo), 'session_id': 's'})
            allowed = json.dumps({'tool_name': 'Edit', 'tool_input': {'file_path': str(repo / 'a.txt')}, 'cwd': str(repo), 'session_id': 's'})
            for text, want in ((blocked, 2), (allowed, 0)):
                stdin = type('In', (), {'buffer': io.BytesIO(text.encode('utf-8'))})()
                with patch.object(sys, 'stdin', stdin), contextlib.redirect_stderr(io.StringIO()):
                    self.assertEqual(run(cli.main, ['hook', 'check'])[0], want)
            self.assertEqual(run(cli.main, ['verdict', 'run', '--plan', 'flow', '--milestone', 'M1'])[0], 0)
            code, out = run(cli.main, ['plan', 'show', 'flow'])
            sha = next(iter(self.verdict_shas(json.loads(out))), None)
            self.assertTrue(sha, out)
            code, out = run(cli.main, ['owner', 'accept', 'flow', '--artifact-sha', sha, '--reference', 'test'])
            self.assertEqual((code, '"accepted"' in out), (0, True), out)


class HookLocationTests(Base):
    def plan(self, mode):
        return {'plan': 'p', 'revision': 1, 'plan_sha': 'x', 'status': 'approved', 'mode': mode, 'owned': ['a'], 'non_goals': [], 'bash_deny': [], 'protected': [],
                'scratch': [], 'project': str(self.repo), 'state_root': str(self.state), 'exported_at': '2026-10-20T00:00:00+00:00'}

    def test_the_state_root_comes_from_config_json_when_no_argument_names_it(self):
        (self.repo / '.onecrew').mkdir()
        (self.repo / '.onecrew' / hook_cli.FILE).write_text(json.dumps(self.plan('log')), encoding='utf-8')
        copy = self.state / 'plans' / 'p'; copy.mkdir(parents=True)
        (copy / hook_cli.FILE).write_text(json.dumps(self.plan('enforce')), encoding='utf-8')
        args = argparse.Namespace(project=None, state_root=None)
        with patch.dict(os.environ, {'CLAUDE_PROJECT_DIR': str(self.repo), 'LOCALAPPDATA': str(self.base / 'nowhere'), 'HOME': str(self.base / 'nowhere'), 'USERPROFILE': str(self.base / 'nowhere')}):
            plan, root, error, source = hook_cli.governing(args, {})
            self.assertIsNone(error)                                                     # no config.json yet: only the project copy is found
            where.config_file(self.repo).write_text(json.dumps({'state_root': str(self.state)}), encoding='utf-8')
            plan, root, error, source = hook_cli.governing(args, {})
            self.assertIn('differs from the state-root copy', error)                     # the state-root copy was found through config.json
            self.assertEqual(plan['mode'], 'enforce')

    def test_the_project_comes_from_the_environment_then_the_event_then_the_cwd(self):
        with patch.dict(os.environ, {'CLAUDE_PROJECT_DIR': str(self.repo)}):
            self.assertEqual(where.project_from_environment('/elsewhere'), self.repo)
        os.environ.pop('CLAUDE_PROJECT_DIR', None)
        self.assertEqual(where.project_from_environment(str(self.base)), self.base)
        self.assertEqual(where.git_root(self.repo / '.git'), self.repo.resolve())


class ProtectionAndDiscoveryTests(Base):
    def test_config_json_cannot_be_edited_by_the_ai(self):
        self.init()
        deny = self.settings()['permissions']['deny']
        self.assertIn('Edit(.onecrew/config.json)', deny)
        from onecrew.v2 import active_plan
        self.assertIn('.onecrew/', active_plan.DEFAULT_PROTECTED)                  # the whole folder, config.json included, is protected from edits while a plan governs

    def test_the_state_root_is_found_from_a_subdirectory_and_without_a_project(self):
        self.init()
        sub = self.repo / 'src' / 'deep'; sub.mkdir(parents=True)
        self.assertEqual(where.configured_state_root(sub).resolve(), self.state.resolve())
        self.assertEqual(where.state_root_for(None, None), None)                    # no TypeError when there is no project; the cwd here has no config
        self.assertEqual(where.state_root_for(sub, self.base / 'given'), self.base / 'given')
        cwd = os.getcwd(); os.chdir(sub); self.addCleanup(os.chdir, cwd)
        self.assertEqual(where.configured_state_root(None).resolve(), self.state.resolve())

    def test_doctor_reports_a_stale_copy_in_the_other_settings_file(self):
        self.init()
        shared = self.repo / '.claude' / 'settings.json'
        data = self.settings()
        data['hooks']['Stop'][0]['hooks'][0]['command'] = str(self.base / 'gone' / 'onecrew')
        shared.write_text(json.dumps(data), encoding='utf-8')
        out = run(install.doctor, project=self.repo, state_root=None, exe=self.exe, claude=LOGGED_IN)[1]
        self.assertTrue(any(l.startswith('FAIL') and 'settings.json' in l and 'does not exist' in l for l in out.splitlines()), out)


class PackagingTests(unittest.TestCase):
    def test_the_templates_are_package_data_and_the_examples_keep_a_copy(self):
        from importlib.resources import files
        for lang in ('vi', 'en'):
            packaged = files('onecrew.templates').joinpath(f'owner-rules.{lang}.md').read_bytes()
            self.assertEqual(packaged, (ROOT / 'examples' / f'owner-rules.{lang}.md').read_bytes(), lang)
            self.assertGreater(len(packaged), 300)
        text = (ROOT / 'pyproject.toml').read_text(encoding='utf-8')
        self.assertIn('[tool.setuptools.package-data]', text); self.assertIn('"onecrew.templates" = ["*.md"]', text)
        self.assertRegex(text, r'(?m)^version = "2\.2\.0\.dev2"$')
        for module in ('install', 'messages', 'owner_cli', 'where'): self.assertIn(f'"onecrew.v2.{module}"', text)

    def test_the_templates_are_the_six_rules_in_both_languages(self):
        for lang in ('vi', 'en'):
            text = advisor.rules_template(lang).decode('utf-8')
            for rule in ('R1.', 'R2.', 'R3.', 'R4.', 'R5.', 'R6.'): self.assertEqual(len([l for l in text.splitlines() if l.startswith(rule)]), 1, (lang, rule))
        self.assertFalse(DIACRITICS.search(advisor.rules_template('en').decode('utf-8')))

    def test_plan_rules_init_reads_the_package_copy(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp) / 'p'; project.mkdir()
            ledger = Ledger(project, Path(tmp) / 's')
            self.assertTrue(advisor.init_rules(ledger)['created'])
            self.assertEqual((Path(tmp) / 's' / 'plans' / 'owner-rules.md').read_bytes(), advisor.rules_template('vi'))      # `plan rules init` has always written the Vietnamese one
            ledger2 = Ledger(project, Path(tmp) / 's2')
            with patch.dict(os.environ, {'ONECREW_LANG': 'en'}): advisor.init_rules(ledger2)
            self.assertEqual((Path(tmp) / 's2' / 'plans' / 'owner-rules.md').read_bytes(), advisor.rules_template('en'))
            self.assertFalse(advisor.init_rules(ledger2)['created'])

    def test_help_lists_init_doctor_and_owner(self):
        code, out = run(cli.main, ['--help'])
        self.assertEqual(code, 0)
        for group in ('init', 'doctor', 'owner'): self.assertRegex(out, r'(?m)^  ' + group + r'\s')

    def test_the_checkout_print_keeps_its_form_and_shares_the_deny_list(self):
        printed = hook_cli.settings(Path('/p'), Path('/s'), ROOT)
        handler = printed['hooks']['PreToolUse'][0]['hooks'][0]
        self.assertEqual((handler['command'], handler['args'][-4:-1]), (sys.executable, ['--state-root', str(Path('/s')), 'hook']))
        self.assertEqual(printed['permissions']['deny'], hook_cli.deny_rules(Path('/s')))


if __name__ == '__main__':
    unittest.main()
