"""QLMAU: versioned prompt templates, first slice (option mau-prompt). Every template opens with `onecrew-mau: ten=<name> phien-ban=N`; `onecrew mau
list|lint` read the templates only; the delegation `reminded` line and the QSAT row of a hand-over record the template version. Only modules the base
has are imported at the top, and `mau` runs as a subprocess, so a new behaviour is red BY ASSERTION on the base.
"""
import contextlib
import hashlib
import io
import json
import os
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from onecrew.v2 import active_plan, giao_viec, hook_cli, install, where
from tests.test_gsdp_a_standing import StandingFixture
from tests.test_ui33_task_first import Project, milestone
from tests.v2_fixture import PY

REPO = Path(__file__).resolve().parents[1]
HEADER = re.compile(r'onecrew-mau: ten=([a-z0-9-]+) phien-ban=(\d+)')
ROLES = [f'vai-{role}-{lang}' for role in ('dieu-phoi', 'kiem', 'trao-doi') for lang in ('en', 'vi')]


def mau(project, state, command):
    """(exit code, stdout, stderr) of `onecrew --project <p> --state-root <s> mau <command>` run from this tree."""
    env = dict(os.environ, PYTHONUTF8='1', ONECREW_LANG='vi')
    done = subprocess.run([PY, '-X', 'utf8', '-m', 'onecrew', '--project', str(project), '--state-root', str(state), 'mau', command],
                          capture_output=True, cwd=REPO, timeout=120, env=env)
    return done.returncode, done.stdout.decode('utf-8'), done.stderr.decode('utf-8', 'replace')


def snapshot(*folders):
    return {str(p): hashlib.sha256(p.read_bytes()).hexdigest() if p.is_file() else 'dir' for folder in folders for p in sorted(Path(folder).rglob('*'))}


class Templates(unittest.TestCase):
    """A project folder with a copy of the shipped role templates and an empty state root."""

    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        env = patch.dict(os.environ)
        env.start()
        self.addCleanup(env.stop)
        base = Path(temp.name)
        os.environ['LOCALAPPDATA'] = str(base / 'local')
        self.project, self.state = base / 'project', base / 'state'
        self.roles = self.project / 'docs' / 'vai3'
        self.roles.mkdir(parents=True)
        (self.state / 'plans').mkdir(parents=True)
        for path in (REPO / 'docs' / 'vai3').glob('*.md'): (self.roles / path.name).write_bytes(path.read_bytes())


class TestQlMau(StandingFixture):
    def setUp(self):
        super().setUp()
        for name in ('ONECREW_LANG', 'CLAUDE_PROJECT_DIR'): os.environ.pop(name, None)

    def templates(self):
        case = Templates('run')
        case.setUp()
        self.addCleanup(case.doCleanups)
        return case

    def reminded(self):
        code, out, err = self.run_hook('remind', self.tool('Agent', prompt='Làm đi.'))
        self.assertEqual(code, 0, err)
        lines = [v for v in self.violations() if v.get('event') == 'reminded']
        self.assertTrue(lines, err)
        return lines[-1], json.loads(out)['hookSpecificOutput']

    def owner_file(self, name, text):
        path = self.state / 'plans' / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding='utf-8')
        return path

    # ---- kind A -------------------------------------------------------------------------------------------------------------

    def test_default_delegation_template_has_version_header(self):
        first = giao_viec.DEFAULT_TEMPLATE.splitlines()[0]
        found = HEADER.search(first)
        self.assertTrue(found, first)
        self.assertEqual(found.group(1), 'mau-giao-viec')
        self.assertEqual(giao_viec.header(giao_viec.DEFAULT_TEMPLATE), ('mau-giao-viec', int(found.group(2))))
        self.assertEqual(giao_viec.delegation_version(None), int(found.group(2)))
        for language, text in giao_viec.OWNER_TEXT.items():
            self.assertTrue(HEADER.search(text.splitlines()[0]), language)

    def test_every_vai3_template_has_version_header(self):
        names = []
        for path in sorted((REPO / 'docs' / 'vai3').glob('*.md')):
            found = HEADER.search(path.read_text(encoding='utf-8-sig').splitlines()[0])
            self.assertTrue(found, path.name)
            names.append(found.group(1))
        self.assertEqual(sorted(names), sorted(ROLES))

    def test_mau_list_shows_name_version_and_hash(self):
        case = self.templates()
        code, out, err = mau(case.project, case.state, 'list')
        self.assertEqual(code, 0, err)
        lines = {line.split()[0]: line for line in out.splitlines() if line.strip()}
        self.assertEqual(sorted(lines), sorted(['mau-giao-viec', 'mau-loi-chu', *ROLES]), out)
        for name, line in lines.items(): self.assertRegex(line, r'^\S+  phien-ban=1  [0-9a-f]{12}  ', name)
        role = case.roles / 'kiem.vi.md'
        self.assertIn(hashlib.sha256(role.read_bytes()).hexdigest()[:12], lines['vai-kiem-vi'])
        self.assertIn(str(role), lines['vai-kiem-vi'])
        owner = case.state / 'plans' / 'mau-giao-viec.md'                              # the owner's file replaces the built-in one
        owner.write_text('# onecrew-mau: ten=mau-giao-viec phien-ban=7\n- Mục tiêu: mục tiêu\n', encoding='utf-8')
        code, out, err = mau(case.project, case.state, 'list')
        self.assertIn('mau-giao-viec  phien-ban=7  ', out, err)
        self.assertIn(str(owner), out)

    def test_mau_lint_flags_missing_header_overlap_and_gap(self):
        case = self.templates()
        owner = case.state / 'plans' / 'mau-giao-viec.md'
        owner.write_text('- Mục tiêu: mục tiêu, goal\n- Tệp được sửa: files, goal\n- Xong khi: xong khi\n- Không làm:\n- Cách kiểm: verify\n',
                         encoding='utf-8')
        role = case.roles / 'kiem.vi.md'
        text = role.read_text(encoding='utf-8')
        role.write_text(text.replace('## Báo cho', '## Khác'), encoding='utf-8')
        other = case.roles / 'trao-doi.en.md'
        other.write_text(other.read_text(encoding='utf-8').replace('ten=vai-trao-doi-en', 'ten=vai-kiem-en'), encoding='utf-8')
        code, out, err = mau(case.project, case.state, 'lint')
        self.assertEqual(code, 1, out + err)
        lines = out.splitlines()

        def has(*parts):
            self.assertTrue(any(all(part in line for part in parts) for line in lines), (parts, out))

        has('mau-giao-viec', f'{owner}:1:', 'dòng đầu')
        has('mau-giao-viec', f'{owner}:2:', '"goal"', 'Mục tiêu')
        has('mau-giao-viec', f'{owner}:4:', 'Không làm', 'bỏ trống')
        has('mau-giao-viec', 'thiếu mục bắt buộc', 'Không làm', 'Skill')
        has('vai-kiem-vi', 'thiếu phần của vai', 'Báo cho')
        has('vai-kiem-en', 'đã dùng ở')

    def test_mau_lint_passes_the_shipped_templates(self):
        case = self.templates()
        code, out, err = mau(case.project, case.state, 'lint')
        self.assertEqual(code, 0, out + err)
        self.assertIn('ĐẠT: 8 mẫu', out)

    def test_reminded_line_records_template_version(self):
        self.standing(mode='enforce')
        line, reply = self.reminded()
        self.assertIn('mau-giao-viec@1', line['reason'])
        self.assertIn('mau-giao-viec@1', reply['additionalContext'])
        self.assertTrue(line['rule'].startswith('delegation_missing:'))
        self.owner_file('mau-giao-viec.md', '# onecrew-mau: ten=mau-giao-viec phien-ban=4\n- Ngân sách: budget\n')
        line, _ = self.reminded()
        self.assertIn('mau-giao-viec@4', line['reason'])

    def test_qsat_delegation_row_records_template_version(self):
        base = Path(self.temp.name) / 'qsat'
        base.mkdir()
        project = Project(base, 'project-a', base / 'state')
        os.environ.update(HOME=str(base / 'home'), USERPROFILE=str(base / 'home'), CLAUDE_CONFIG_DIR=str(base / 'home' / '.claude'),
                          LOCALAPPDATA=str(base / 'local'), APPDATA=str(base / 'roaming'), CLAUDE_PROJECT_DIR=str(project.root))
        for key in ('CLAUDE_CODE_ENTRYPOINT', 'ONECREW_ACTOR', 'ONECREW_V2_REQUIRE_PLAN', 'CLAUDECODE', 'CLAUDE_CODE_CHILD_SESSION'):
            os.environ.pop(key, None)
        project.plan('PA', [milestone()])
        active_plan.export(project.ledger, 'PA', strict=True)
        where.register_project(project.root, project.ledger.state_root)
        program = base / ('onecrew.cmd' if os.name == 'nt' else 'onecrew')
        program.write_text('@exit /b 0\r\n' if os.name == 'nt' else '#!/bin/sh\nexit 0\n', encoding='ascii')
        program.chmod(0o755)
        settings = base / 'profile' / 'settings.json'
        with contextlib.redirect_stdout(io.StringIO()) as out:
            self.assertEqual(install.user_hook('install', settings, program, observe=True), 0, out.getvalue())
        hooks = json.loads(settings.read_text(encoding='utf-8'))['hooks']
        args, = [h['args'] for entry in hooks['UserPromptSubmit'] for h in entry['hooks'] if h['args'][:2] == ['hook', 'observe']]

        def call(name, **extra):
            event = dict({'hook_event_name': name, 'cwd': str(project.root), 'session_id': 'session-1'}, **extra)
            stdin = type('Input', (), {'buffer': io.BytesIO(json.dumps(event).encode())})()
            with patch.object(Path, 'cwd', return_value=project.root), patch.object(sys, 'stdin', stdin), \
                    contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(hook_cli.main(args), 0)

        call('PreToolUse', tool_name='Agent', tool_use_id='give-1', tool_input={'description': 'giao', 'prompt': 'PRIVATE-PROMPT'})
        call('PreToolUse', tool_name='mcp__ccd_session_mgmt__send_message', tool_use_id='give-2', tool_input={'message': 'PRIVATE-APP'})
        call('PreToolUse', tool_name='Read', tool_use_id='read-1', tool_input={'file_path': str(project.root / 'a.txt')})
        call('Stop')
        task = project.state('PA')['task_id']
        rows = {e['payload'].get('tool_use_id'): e['payload'] for e in project.ledger.events(task) if e['kind'] == 'hook.observed'}
        for key in ('give-1', 'give-2'):
            self.assertEqual((rows[key].get('template'), rows[key].get('template_version')), ('mau-giao-viec', 1), rows[key])
        self.assertNotIn('template', rows['read-1'])
        self.assertNotIn('PRIVATE-', str(rows))

    # ---- kind B -------------------------------------------------------------------------------------------------------------

    def test_owner_template_without_header_still_reminds(self):
        self.standing(mode='enforce')
        self.owner_file('mau-giao-viec.md', '- Ngân sách: ngân sách, budget\n')
        line, reply = self.reminded()
        self.assertIn('Ngân sách', reply['additionalContext'])
        self.assertIn('mau-giao-viec@chua-ghi', line['reason'])
        self.assertIsNone(giao_viec.delegation_version(self.state))
        # the owner-words reminder: the header line is never sent, and a file that holds only its header turns the reminder off
        owner = self.owner_file('mau-loi-chu.md', '# onecrew-mau: ten=mau-loi-chu phien-ban=2\nGhi vào sổ ABC.\n')
        self.assertEqual(giao_viec.owner_reminder('P1', self.state, 'vi'), 'Ghi vào sổ ABC.')
        owner.write_text('# onecrew-mau: ten=mau-loi-chu phien-ban=2\n', encoding='utf-8-sig')
        self.assertEqual(giao_viec.owner_reminder('P1', self.state, 'vi'), '')
        owner.unlink()
        for language in ('vi', 'en'):
            text = giao_viec.owner_reminder('P1', self.state, language)
            self.assertNotIn('onecrew-mau', text)
            self.assertIn('YEU-CAU-CHU.vi.md', text)

    def test_mau_list_and_lint_write_nothing(self):
        case = self.templates()
        before = snapshot(case.project, case.state)
        for command in ('list', 'lint'):
            code, _, err = mau(case.project, case.state, command)
            self.assertEqual(code, 0, err)
        self.assertEqual(snapshot(case.project, case.state), before)

    def test_mau_list_leaves_skill_registry_alone(self):
        case = self.templates()
        code, out, err = mau(case.project, case.state, 'list')
        self.assertEqual(code, 0, err)
        self.assertNotIn('skill', out.replace(str(case.project.parent), '').casefold())
        self.assertEqual(list(case.state.rglob('*.sqlite3')), [])                      # no ledger was opened or made

    # ---- kind C -------------------------------------------------------------------------------------------------------------

    def test_reminder_never_blocks(self):
        self.standing(mode='enforce')
        code, out, err = self.run_hook('remind', self.tool('Agent', prompt='Làm đi.'))
        self.assertEqual(code, 0, err)
        reply = json.loads(out)['hookSpecificOutput']
        self.assertEqual(set(reply), {'hookEventName', 'additionalContext'})
        self.assertNotIn('Blocked', err)

    def test_header_line_does_not_change_parsed_items(self):
        text = '- Mục tiêu: mục tiêu, goal\n- Skill: skill\n'
        self.assertEqual(giao_viec.parse('# onecrew-mau: ten=mau-giao-viec phien-ban=3\n' + text), giao_viec.parse(text))


if __name__ == '__main__':
    unittest.main()
