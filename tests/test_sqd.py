"""SQD: the owner's decision book per repository. `onecrew decision add|list|show` appends and reads <state-root>/plans/quyet-dinh/<repository>.jsonl;
the session start lists the decisions in force (id, title, scope); a standing plan's delegation that names no decision gets one reminder; nothing
blocks. The command and the hooks run as subprocesses and only modules the base (2.5.0.dev34) has are imported, so every new behaviour is red BY
ASSERTION there (the base answers "unknown group").
"""
import datetime as dt
import json
import os
import shutil
import subprocess
from pathlib import Path

from tests.test_gsdp_a_standing import REPO, StandingFixture
from tests.v2_fixture import PY

FULL = ('Mục tiêu: tóm tắt a.txt. Tệp được sửa: không tệp nào. Xong khi: có bản tóm tắt. Không làm: không sửa tệp. '
        'Cách kiểm: đọc lại a.txt. Skill: không bắt buộc.')
WORDS = 'chỉ áp cho màn hình đăng nhập, "đừng" đổi chỗ khác 7413'          # the owner's words: shown by `show`, never by a hook


class TestSqd(StandingFixture):
    def setUp(self):
        super().setUp()
        for name in ('ONECREW_LANG', 'CLAUDE_PROJECT_DIR'): os.environ.pop(name, None)

    # ---- helpers ------------------------------------------------------------------------------------------------------------------

    def decision(self, *args, project=None):
        argv = [PY, '-X', 'utf8', '-m', 'onecrew.v2.cli', '--project', str(project or self.root), '--state-root', str(self.state), 'decision', *args]
        done = subprocess.run(argv, capture_output=True, cwd=REPO, timeout=120, env=dict(os.environ, PYTHONUTF8='1'))
        return done.returncode, done.stdout.decode('utf-8'), done.stderr.decode('utf-8')

    def add(self, title, scope='*', quote=WORDS, *extra, project=None):
        code, out, err = self.decision('add', '--scope', scope, '--title', title, '--quote', quote, *extra, project=project)
        self.assertEqual(code, 0, out + err)
        return out

    def listed(self, *args, project=None):
        code, out, err = self.decision('list', *args, project=project)
        self.assertEqual(code, 0, out + err)
        return [line for line in out.splitlines() if line.startswith('SQD-')]

    def ids(self, *args, project=None):
        return [line.split()[0] for line in self.listed(*args, project=project)]

    def books(self):
        return sorted((self.state / 'plans' / 'quyet-dinh').glob('*.jsonl'))

    def book(self):
        found = self.books()
        self.assertEqual(len(found), 1, found)
        return found[0]

    def records(self):
        return [json.loads(line) for line in self.book().read_bytes().decode('utf-8').split('\n') if line.strip()]

    def session_context(self):
        code, out, err = self.run_hook('session', {'session_id': 's1', 'cwd': str(self.root), 'hook_event_name': 'SessionStart', 'source': 'startup'})
        self.assertEqual(code, 0, err)
        return json.loads(out)['hookSpecificOutput']['additionalContext']

    def remind(self, tool='Agent', **tool_input):
        code, out, err = self.run_hook('remind', self.tool(tool, **tool_input))
        self.assertEqual(code, 0, err)
        self.assertNotIn('Blocked', err)
        if not out.strip(): return ''
        reply = json.loads(out)
        self.assertNotIn('decision', reply)
        self.assertNotIn('permissionDecision', reply['hookSpecificOutput'])             # a reminder never allows, denies or asks
        self.assertEqual(reply['hookSpecificOutput']['hookEventName'], 'PreToolUse')
        return reply['hookSpecificOutput']['additionalContext']

    def reminded(self):
        return [v for v in self.violations() if v.get('event') == 'reminded']

    # ---- kind A: new behaviour ------------------------------------------------------------------------------------------------------

    def test_decision_add_appends_a_dated_line(self):
        before = dt.datetime.now().astimezone() - dt.timedelta(seconds=2)
        self.assertIn('SQD-1', self.add('Nút đăng nhập màu xanh', 'src/login/', WORDS, '--source', 'chat 26/11 16:00'))
        first = self.book().read_bytes()
        self.assertIn('SQD-2', self.add('Không đổi tên lệnh', '*', 'giữ nguyên tên lệnh'))
        data = self.book().read_bytes()
        self.assertTrue(data.startswith(first) and len(data) > len(first), 'an earlier line changed')
        one, two = self.records()
        self.assertEqual((one['id'], one['scope'], one['title'], one['quote'], one['source'], one['replaces']),
                         ('SQD-1', 'src/login/', 'Nút đăng nhập màu xanh', WORDS, 'chat 26/11 16:00', None))
        self.assertEqual((two['id'], two['scope'], two['quote'], two['source']), ('SQD-2', '*', 'giữ nguyên tên lệnh', None))
        self.assertIn('ai_session', one['recorded_by'])
        at = dt.datetime.fromisoformat(one['at'])                                     # the machine's date, with its offset
        self.assertTrue(before <= at <= dt.datetime.now().astimezone() + dt.timedelta(seconds=2), one['at'])

    def test_decision_list_filters_by_scope(self):
        self.add('Cả repo', '*')
        self.add('Thư mục v2', 'onecrew\\v2\\')                                       # backslashes are the same path
        self.add('Tài liệu', 'docs/*.md')
        self.add('Một tệp', './a.txt')
        self.assertEqual(self.ids(), ['SQD-1', 'SQD-2', 'SQD-3', 'SQD-4'])
        self.assertEqual(self.ids('--path', 'onecrew/v2/cli.py'), ['SQD-1', 'SQD-2'])
        self.assertEqual(self.ids('--path', 'docs/quyet-dinh.md'), ['SQD-1', 'SQD-3'])
        self.assertEqual(self.ids('--path', str(self.root / 'a.txt')), ['SQD-1', 'SQD-4'])
        self.assertEqual(self.ids('--path', 'onecrew/v2x/cli.py'), ['SQD-1'])
        line = self.listed()[1]
        for part in ('Thư mục v2', 'onecrew/v2/', dt.date.today().isoformat()): self.assertIn(part, line)
        self.assertNotIn(WORDS, '\n'.join(self.listed()))

    def test_replaced_decision_leaves_the_list(self):
        self.add('Cũ', '*', 'làm kiểu cũ')
        first = self.book().read_bytes()
        self.add('Mới', '*', WORDS, '--replaces', 'SQD-1')
        self.assertTrue(self.book().read_bytes().startswith(first), 'the replaced line changed')
        self.assertEqual(self.ids(), ['SQD-2'])
        every = self.listed('--all')
        self.assertEqual([line.split()[0] for line in every], ['SQD-1', 'SQD-2'])
        self.assertIn('đã bị thay bởi SQD-2', every[0]); self.assertIn('thay SQD-1', every[1])
        code, out, err = self.decision('show', 'SQD-2')
        self.assertEqual(code, 0, err)
        self.assertIn(WORDS, out); self.assertIn('Mới', out)
        code, out, err = self.decision('show', 'SQD-1')
        self.assertEqual(code, 0, err)
        self.assertIn('làm kiểu cũ', out); self.assertIn('đã bị thay bởi SQD-2', out)
        code, out, err = self.decision('show', 'SQD-9')
        self.assertEqual(code, 2, out)

    def test_session_start_lists_decisions(self):
        self.plain(mode='enforce')
        self.assertNotIn('SQD-', self.session_context())                              # no decision: no line
        self.add('Nút đăng nhập màu xanh', 'src/login/')
        self.add('Bỏ đi', '*', 'sẽ bị thay')
        self.add('Giữ tên lệnh', '*', WORDS, '--replaces', 'SQD-2')
        context = self.session_context()
        lines = [line for line in context.splitlines() if line.startswith('SQD-')]
        self.assertEqual([line.split()[0] for line in lines], ['SQD-1', 'SQD-3'], context)
        for part in ('Nút đăng nhập màu xanh', 'src/login/'): self.assertIn(part, lines[0])
        self.assertNotIn(WORDS, context); self.assertNotIn('sẽ bị thay', context); self.assertNotIn('Bỏ đi', context)
        for n in range(4, 15): self.add(f'Quyết định số {n}')
        context = self.session_context()
        lines = [line for line in context.splitlines() if line.startswith('SQD-')]
        self.assertEqual([line.split()[0] for line in lines], [f'SQD-{n}' for n in range(5, 15)], context)   # the 10 newest
        self.assertIn('13, hiện 10 mới nhất', context)

    def test_delegation_without_decision_reminded(self):
        self.standing(mode='enforce')
        self.add('Nút đăng nhập màu xanh')
        self.add('Giữ tên lệnh')
        note = self.remind(prompt=FULL, description='Tóm tắt')
        self.assertEqual(len(note.splitlines()), 1, note)
        for part in ('SQD-1', 'Nút đăng nhập màu xanh', 'SQD-2', 'Giữ tên lệnh', 'KHÔNG bị chặn'): self.assertIn(part, note)
        self.assertNotIn(WORDS, note); self.assertNotIn('thiếu mục', note)
        self.assertEqual([(v['tool'], v['rule'], v['mode']) for v in self.reminded()], [('Agent', 'delegation_decision', 'enforce')])
        both = self.remind('SendMessage', to='worker', message='Làm tiếp.')               # template items missing too: one call, one record
        self.assertEqual(len(both.splitlines()), 2, both)
        self.assertIn('thiếu mục', both.splitlines()[0]); self.assertIn('SQD-1', both.splitlines()[1])
        self.assertEqual(len(self.reminded()), 2)
        rule = self.reminded()[-1]['rule']
        self.assertTrue(rule.startswith('delegation_missing:') and rule.endswith(';delegation_decision'), rule)

    def test_book_is_a_file_in_the_state_root(self):
        self.add('Một')
        book = self.book()
        self.assertEqual(book.parent, self.state / 'plans' / 'quyet-dinh')
        self.assertEqual(self.git('status', '--porcelain', '--ignored'), '')              # nothing written in the repository
        tree = Path(self.temp.name) / 'second-worktree'
        self.git('worktree', 'add', '-q', str(tree))
        self.assertEqual(self.ids(project=tree), ['SQD-1'])                              # the worktrees of a repository share its book
        self.assertIn('SQD-2', self.add('Hai', project=tree))
        self.assertEqual(self.ids(), ['SQD-1', 'SQD-2'])
        self.assertEqual(self.books(), [book])
        other = Path(self.temp.name) / 'other' / 'project'; other.mkdir(parents=True)     # same folder name, another repository: another book
        subprocess.check_call(['git', 'init', '-q', str(other)])
        self.assertEqual(self.ids(project=other), [])
        self.assertIn('SQD-1', self.add('Riêng', project=other))
        self.assertEqual(len(self.books()), 2)

    # ---- kind B: must hold on the candidate -----------------------------------------------------------------------------------------

    def test_add_refuses_missing_scope_or_quote(self):
        good = {'--scope': '*', '--title': 'Một', '--quote': 'lời chủ'}

        def refused(change, *extra):
            argv = [word for key, value in dict(good, **change).items() if value is not None for word in (key, value)]
            code, out, err = self.decision('add', *argv, *extra)
            self.assertNotEqual(code, 0, (change, extra, out))

        cases = ({'--scope': None}, {'--quote': None}, {'--title': None}, {'--scope': '  '}, {'--quote': ' \n '}, {'--title': ''},
                 {'--quote': 'x' * 501}, {'--title': 'x' * 121}, {'--title': 'hai\ndòng'}, {'--scope': 'C:/ngoai/repo'}, {'--scope': '../ngoai'})
        for change in cases: refused(change)
        refused({}, '--replaces', 'SQD-1')
        self.assertFalse((self.state / 'plans' / 'quyet-dinh').exists(), 'a refusal wrote something')
        self.add('Một', quote='y' * 500)
        self.add('Hai', '*', WORDS, '--replaces', 'SQD-1')
        before = self.book().read_bytes()
        for change in cases: refused(change)
        for wanted in ('SQD-7', 'khong-phai-ma', 'SQD-1'): refused({}, '--replaces', wanted)    # SQD-1 is already replaced
        self.assertEqual(self.book().read_bytes(), before)
        code, out, err = self.decision('add', '--scope', '*', '--title', 'Trong repo', '--quote', 'x', project=self.state.parent)
        self.assertNotEqual(code, 0, out)                                             # a state root inside the project is refused

    def test_delegation_naming_decision_is_silent(self):
        self.standing(mode='enforce')
        self.add('Nút đăng nhập màu xanh')
        for text in (FULL + ' Áp dụng: SQD-1.', FULL + ' (theo sqd-1)', FULL + ' KHÔNG CÓ quyết định\n liên quan.'):
            self.assertEqual(self.remind(prompt=text), '', text)
        self.assertEqual(self.remind('SendMessage', to='w', envelope={'a': [FULL], 'b': 'SQD-1'}), '')
        self.assertEqual(self.reminded(), [])
        self.assertIn('SQD-1', self.remind(prompt=FULL + ' Làm hợp đồng SQD ở nhánh claude/sqd.'))     # the word alone names no decision

    def test_broken_book_never_blocks(self):
        self.standing(mode='enforce')
        self.add('Còn đọc được')
        book = self.book()
        with book.open('ab') as stream: stream.write(b'{"id": "SQD-5", "title": "d\xc3')          # a torn last line
        self.assertEqual(self.ids(), ['SQD-1'])
        self.assertIn('SQD-1', self.remind(prompt=FULL))
        self.assertIn('Còn đọc được', self.session_context())
        self.assertIn('SQD-6', self.add('Sau dòng hỏng'))                             # the torn line keeps its number and stays its own line
        self.assertEqual(self.ids(), ['SQD-1', 'SQD-6'])
        with book.open('ab') as stream: stream.write(b'[1, 2]\nnot json\n{"id": "SQD-9"}\n\xff\xfe\n')
        self.assertEqual(self.ids(), ['SQD-1', 'SQD-6'])
        shutil.move(str(book), str(book) + '.aside'); book.mkdir()                     # a book that cannot be read: silence
        self.assertEqual(self.remind(prompt=FULL), '')
        self.assertIn('thiếu mục', self.remind(prompt='Làm đi.'))                     # the template reminder is not silenced by it
        context = self.session_context()
        self.assertIn('OneCrew contract', context); self.assertNotIn('SQD-', context)
        code, out, err = self.decision('list')
        self.assertEqual(code, 2, out + err)

    # ---- kind C: control (the same on the base) -------------------------------------------------------------------------------------

    def test_no_book_reminder_unchanged(self):
        self.standing(mode='enforce')
        self.assertEqual(self.remind(prompt=FULL), '')
        note = self.remind(prompt='Làm đi.')
        self.assertEqual(len(note.splitlines()), 1, note)
        self.assertTrue(note.startswith('OneCrew (plan thường trực P1): lời giao việc vừa gửi qua Agent thiếu mục:'), note)
        self.assertNotIn('quyết định', note)
        self.assertEqual(len(self.reminded()), 1)
        self.assertTrue(self.reminded()[0]['rule'].startswith('delegation_missing:'))
        self.assertNotIn('delegation_decision', self.reminded()[0]['rule'])
        self.assertNotIn('Quyết định của chủ', self.session_context())

    # ---- I7 (should): the default reminder when the owner types ---------------------------------------------------------------------

    def test_owner_typed_default_mentions_the_book(self):
        self.standing(mode='log')
        event = {'session_id': 's1', 'cwd': str(self.root), 'hook_event_name': 'UserPromptSubmit', 'prompt': 'từ nay nút phải màu xanh'}
        code, out, err = self.run_hook('prompt', event)
        self.assertEqual(code, 0, err)
        self.assertIn('decision add', json.loads(out)['hookSpecificOutput']['additionalContext'])
        own = self.state / 'plans' / 'mau-loi-chu.md'                                 # the owner's own text is not changed
        own.parent.mkdir(parents=True, exist_ok=True)
        own.write_text('Chỉ câu của tôi.', encoding='utf-8')
        code, out, err = self.run_hook('prompt', event)
        self.assertEqual(code, 0, err)
        context = json.loads(out)['hookSpecificOutput']['additionalContext']
        self.assertIn('Chỉ câu của tôi.', context); self.assertNotIn('decision add', context)
