"""2.5.0.dev11 — the owner part of a contract (owner 08/11: "UI tracking dành cho người dùng theo dõi, viết kiểu đó sao họ theo dõi và hiểu
task làm gì?").

The contract's `presentation` carries four plain sentences for whoever follows the work: what this does (`request`), what you will see when it
is done (`user_sees`), how you know it passed (`acceptance_steps`), what it does not do (`not_doing`). Once the owner-rules file exists in the
state root (the owner's real setup: `onecrew init` writes it) a new contract must have all four; whenever they are there they must be plain
words: no file name, path, command flag, error code or internal code. A contract without them is still read.
"""
import json
from pathlib import Path

from onecrew.v2 import lint
from tests.test_v2_l1 import Fixture, plan_json

REPO = Path(__file__).resolve().parents[1]
PLAIN = {'request': 'Thêm một trang chào mừng ngắn cho người mới vào dự án.',
         'user_sees': ['Một trang chào có đúng một câu chào.'],
         'acceptance_steps': ['Mở trang chào và đọc câu chào.', 'Bộ kiểm tự động báo đạt.'],
         'not_doing': 'Không sửa trang hay tài liệu nào khác.'}
OWNER_CODES = ('owner_view_missing', 'owner_view_technical')


def owner_reasons(reasons):
    return [r for r in reasons if r[0] in OWNER_CODES]


class OwnerViewRules(Fixture):
    def lint(self, value):
        return owner_reasons(lint.lint(lint.ReadOnlyLedger(self.root, self.ledger.state_root), value))

    def rules(self):
        path = Path(self.ledger.state_root) / 'plans' / 'owner-rules.md'
        path.parent.mkdir(parents=True, exist_ok=True); path.write_text('# rules\n', encoding='utf-8')

    def test_without_the_owner_rules_file_a_contract_without_the_owner_part_is_still_accepted(self):
        self.assertEqual(self.lint(plan_json()), [])

    def test_with_the_owner_rules_file_the_four_parts_are_required_and_named_in_plain_words(self):
        self.rules()
        [(code, text)] = self.lint(plan_json())
        self.assertEqual(code, 'owner_view_missing')
        for words in ('Việc này làm gì', 'Xong bạn thấy gì', 'Làm sao biết đạt', 'Không làm gì'):
            self.assertIn(words, text)
        partial = plan_json(presentation={'request': PLAIN['request'], 'user_sees': []})
        [(code, text)] = self.lint(partial)
        self.assertEqual(code, 'owner_view_missing'); self.assertNotIn('Việc này làm gì', text); self.assertIn('Xong bạn thấy gì', text)
        self.assertEqual(self.lint(plan_json(presentation=dict(PLAIN))), [])

    def test_technical_words_in_the_owner_part_are_refused_with_the_word_and_the_part(self):
        for field, value, word in (('request', 'Tạo file docs/xin-chao.md cho người mới.', 'docs/xin-chao.md'),
                                   ('request', 'Thêm trang chào trong xin-chao.md.', 'xin-chao.md'),
                                   ('acceptance_steps', ['Chạy lệnh với --human rồi đọc.'], '--human'),
                                   ('user_sees', ['Mốc M1 đạt.'], 'M1'),
                                   ('not_doing', 'Không sửa lỗi Errno 13 khi ghi sổ.', 'Errno 13'),
                                   ('user_sees', ['Bản rev 2 hiện trên trang.'], 'rev 2'),
                                   ('request', 'Sửa theo commit 0ef1b12 của nhánh.', '0ef1b12'),
                                   ('not_doing', 'Không đụng C:\\Users\\NUC.', 'C:\\Users\\NUC')):
            with self.subTest(field=field, word=word):
                shown = dict(PLAIN, **{field: value})
                [(code, text)] = self.lint(plan_json(presentation=shown))
                self.assertEqual(code, 'owner_view_technical')
                self.assertIn(word, text)
                self.assertIn('lời thường', text)

    def test_plain_vietnamese_with_numbers_and_hyphenated_words_is_not_technical(self):
        shown = dict(PLAIN, user_sees=['Trang có 3 mục, mỗi mục một dòng.', 'Ngày 08/11 hiện trên trang - dạng ngắn.'],
                     not_doing='Không đổi giao diện e-mail hay số điện thoại.')
        self.assertEqual(self.lint(plan_json(presentation=shown)), [])

    def test_the_sample_contracts_of_the_guides_carry_a_plain_owner_part(self):
        self.rules()
        for sample in ('docs/obs2/su-dung/mau-hop-dong.json', 'docs/sol6/su-dung/mau-hop-dong.json'):
            with self.subTest(sample=sample):
                value = json.loads((REPO / sample).read_text(encoding='utf-8'))
                self.assertEqual(self.lint(value), [])


class CommandRefusals(Fixture):
    """Part 2: the plan propose, plan amend and plan approve commands (owner approve runs plan approve) refuse what lint reports."""
    def setUp(self):
        super().setUp()
        path = Path(self.ledger.state_root) / 'plans' / 'owner-rules.md'
        path.parent.mkdir(parents=True, exist_ok=True); path.write_text('# rules\n', encoding='utf-8')

    def contract(self, **presentation):
        value = plan_json(origin={'by': 'owner', 'at': '2026-11-08', 'quote': 'viết cho người theo dõi đọc được'})
        value['items'] = [dict(i, source='origin') for i in value['items']]
        if presentation.get('none') is None: value['presentation'] = dict(PLAIN, **presentation)
        return value

    def cli(self, *argv):
        import contextlib, io
        from onecrew.v2 import cli
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = cli.main(['--project', str(self.root), '--state-root', str(self.ledger.state_root), *argv])
        return code, out.getvalue()

    def file(self, value, name='c.json'):
        path = self.root.parent / name; path.write_text(json.dumps(value, ensure_ascii=False), encoding='utf-8'); return str(path)

    def test_propose_refuses_a_missing_or_technical_owner_part_and_writes_nothing(self):
        for value, code in ((self.contract(none=True), 'owner_view_missing'), (self.contract(request='Sửa docs/a.md.'), 'owner_view_technical')):
            with self.subTest(code=code):
                rc, text = self.cli('plan', 'propose', 'P1', '--file', self.file(value), '--author', 'claude-opus-5-5')
                self.assertNotEqual(rc, 0, text)
                error = json.loads(text)['error']
                self.assertIn('[' + code + ']', error); self.assertIn('nothing was written', error)
                with self.ledger.transaction() as conn:
                    self.assertEqual(0 if conn is None else conn.execute("SELECT count(*) FROM tasks WHERE request_key LIKE '%P1'").fetchone()[0], 0)
        rc, text = self.cli('plan', 'propose', 'P1', '--file', self.file(self.contract()), '--author', 'claude-opus-5-5')
        self.assertEqual(rc, 0, text)

    def test_amend_refuses_a_technical_owner_part(self):
        self.assertEqual(self.cli('plan', 'propose', 'P1', '--file', self.file(self.contract()), '--author', 'claude-opus-5-5')[0], 0)
        rc, text = self.cli('plan', 'amend', 'P1', '--file', self.file(self.contract(user_sees=['Mốc M1 đạt.']), 'a.json'),
                            '--reason', 'owner asked', '--author', 'claude-opus-5-5')
        self.assertNotEqual(rc, 0, text)
        self.assertIn('[owner_view_technical]', json.loads(text)['error'])
        self.assertEqual(self.cli('plan', 'show', 'P1')[1].count('"revision": 2'), 0)

    def test_approve_command_refuses_a_plan_whose_owner_part_lint_refuses(self):
        from onecrew.v2 import plan as plans
        plans.propose(self.ledger, 'OLD', self.contract(none=True), 'claude-opus-5-5')          # recorded without the part (library, as before)
        rc, text = self.cli('plan', 'approve', 'OLD', '--by', 'owner', '--reference', 'fixture')
        self.assertNotEqual(rc, 0, text)
        error = json.loads(text)['error']
        self.assertIn('[owner_view_missing]', error); self.assertIn('plan amend', error)
        self.assertEqual(plans.show(self.ledger, 'OLD')['status'], 'proposed')
        self.assertEqual(self.cli('plan', 'propose', 'NEW', '--file', self.file(self.contract()), '--author', 'claude-opus-5-5')[0], 0)
        rc, text = self.cli('plan', 'approve', 'NEW', '--by', 'owner', '--reference', 'fixture')
        self.assertEqual(rc, 0, text)

    def test_owner_approve_human_says_in_plain_words_why_it_did_not_approve(self):
        from onecrew.v2 import plan as plans
        plans.propose(self.ledger, 'OLD', self.contract(none=True), 'claude-opus-5-5')
        rc, text = self.cli('owner', 'approve', 'OLD', '--reference', 'fixture', '--human')
        self.assertNotEqual(rc, 0, text)
        self.assertIn('Chưa duyệt: phần viết cho người theo dõi', text)
        self.assertNotIn('Đã ghi nhận', text)
