"""2.5.0.dev12 — the findings of the independent review of 2.5.0.dev11 (Kiro CLI, gpt-5.6-sol, 09/11; BAO-CAO-REVIEW.md), each red before its fix.

F2 (P1)  approve --revision 0 skipped the owner-part check and approved the latest revision.
F1 (P1)  the owner-part check lived in the command only: the library approve() and an amendment written between the check and the approval passed.
F4 (P2)  propose --reuse-existing returned an existing plan that lint now refuses.
F5 (P2)  plain words with a slash ("10 km/h") were taken for a path.
F6 (P2)  technical tokens slipped through: /etc/passwd, main.go, src\\main.py, EACCES, an upper-case hash.
F7 (P2)  the search box did not look in the owner part, the card's new title and description.
"""
import json
from pathlib import Path

from onecrew.v2 import lint
from onecrew.ledger import LedgerError
from tests.test_dev11_owner_view import PLAIN, CommandRefusals, owner_reasons
from tests.test_v2_l1 import Fixture, plan_json


class Base(Fixture):
    """The owner-rules state root and helpers of the dev11 command tests, without running those tests again here."""
    contract, cli, file, before_rules = CommandRefusals.contract, CommandRefusals.cli, CommandRefusals.file, CommandRefusals.before_rules

    def setUp(self):
        super().setUp()
        path = Path(self.ledger.state_root) / 'plans' / 'owner-rules.md'
        path.parent.mkdir(parents=True, exist_ok=True); path.write_text('# rules\n', encoding='utf-8')


del CommandRefusals


class RevisionZero(Base):
    def test_plan_approve_revision_zero_is_refused_and_approves_nothing(self):
        from onecrew.v2 import plan as plans
        self.before_rules('OLD', self.contract(none=True))
        for argv in (('plan', 'approve', 'OLD', '--by', 'owner', '--reference', 'fixture', '--revision', '0'),
                     ('owner', 'approve', 'OLD', '--reference', 'fixture', '--revision', '0')):
            with self.subTest(argv=argv[:2]):
                rc, text = self.cli(*argv)
                self.assertNotEqual(rc, 0, text)
                self.assertEqual(plans.show(self.ledger, 'OLD')['status'], 'proposed')

    def test_revision_zero_is_refused_even_for_a_plan_with_a_good_owner_part(self):
        from onecrew.v2 import plan as plans
        self.assertEqual(self.cli('plan', 'propose', 'NEW', '--file', self.file(self.contract()), '--author', 'claude-opus-5-5')[0], 0)
        rc, text = self.cli('plan', 'approve', 'NEW', '--by', 'owner', '--reference', 'fixture', '--revision', '0')
        self.assertNotEqual(rc, 0, text)
        self.assertIn('revision', json.loads(text)['error'])
        self.assertEqual(plans.show(self.ledger, 'NEW')['status'], 'proposed')


class LibraryApprove(Base):
    """F1: the owner part is one of the reasons step 0 gives (step0.evaluate), so approve() refuses it on every path, the library included
    (owner 09/11: "Mở khóa test, bật hết"), in one refusal with the other reasons, on the contract approve read; the write records only that
    revision at that sha, so an amendment written meanwhile is never approved unchecked."""
    def test_library_approve_refuses_a_plan_whose_owner_part_lint_refuses(self):
        from onecrew.v2 import plan as plans
        self.before_rules('OLD', self.contract(none=True))
        with self.assertRaises(LedgerError) as caught:
            plans.approve(self.ledger, 'OLD', 'owner', 'fixture')
        self.assertIn('[owner_view_missing]', str(caught.exception)); self.assertIn('plan amend', str(caught.exception))
        self.assertEqual(plans.show(self.ledger, 'OLD')['status'], 'proposed')

    def test_the_owner_part_is_one_refusal_with_the_other_step0_reasons(self):
        from onecrew.v2 import plan as plans
        value = self.contract(none=True); value['options'] = None
        value['understanding']['confidence'] = 'low'
        self.before_rules('TWO', value)
        with self.assertRaises(LedgerError) as caught:
            plans.approve(self.ledger, 'TWO', 'owner', 'fixture')
        self.assertIn('[confidence_low]', str(caught.exception)); self.assertIn('[owner_view_missing]', str(caught.exception))

    def test_an_amendment_without_the_owner_part_written_during_approval_is_not_approved(self):
        from onecrew.v2 import plan as plans, step0
        plans.propose(self.ledger, 'P', self.contract(), 'claude-opus-5-5')
        evaluate = step0.evaluate

        def amend_meanwhile(*a, **k):          # dev12b: an amendment the library writes (owner part fine) that approve refuses (no "fail if")
            value = self.contract(); value['milestones'] = [{'id': 'M1', 'title': 'Review', 'covers': ['O1'], 'verifier': {'type': 'reviewer', 'config': {
                'provider': 'claude', 'model': 'claude-haiku-5-5', 'criteria': [{'id': 'R1', 'question': 'Does the diff update a.txt?'}], 'max_minutes': 5}}}]
            plans.amend(self.ledger, 'P', value, 'meanwhile', 'claude-opus-5-5')
            return evaluate(*a, **k)
        step0.evaluate = amend_meanwhile
        try:
            with self.assertRaises(LedgerError):
                plans.approve(self.ledger, 'P', 'owner', 'fixture')
        finally:
            step0.evaluate = evaluate
        self.assertEqual(plans.show(self.ledger, 'P')['status'], 'proposed')
        with self.assertRaises(LedgerError) as caught:
            plans.approve(self.ledger, 'P', 'owner', 'fixture')
        self.assertIn('[criterion_no_fail_clause]', str(caught.exception))


class ReuseExisting(Base):
    def test_reuse_existing_refuses_an_identical_plan_lint_now_refuses(self):
        from onecrew.v2 import plan as plans
        old = self.contract(none=True)
        self.before_rules('OLD', old)
        rc, text = self.cli('plan', 'propose', 'OLD', '--file', self.file(old), '--author', 'claude-opus-5-5', '--reuse-existing')
        self.assertNotEqual(rc, 0, text)
        self.assertIn('[owner_view_missing]', json.loads(text)['error'])

    def test_reuse_existing_still_returns_an_identical_plan_lint_accepts(self):
        good = self.contract()
        self.assertEqual(self.cli('plan', 'propose', 'NEW', '--file', self.file(good), '--author', 'claude-opus-5-5')[0], 0)
        rc, text = self.cli('plan', 'propose', 'NEW', '--file', self.file(good), '--author', 'claude-opus-5-5', '--reuse-existing')
        self.assertEqual(rc, 0, text)


class PlainWords(Fixture):
    def reasons(self, **shown):
        return owner_reasons(lint.lint(lint.ReadOnlyLedger(self.root, self.ledger.state_root), plan_json(presentation=dict(PLAIN, **shown))))

    def test_plain_words_with_a_slash_are_not_a_path(self):
        for text in ('Tốc độ tải đạt 10 km/h.', 'Người dùng chọn có/không ở mỗi câu.', 'Trang hiện 3/5 mục đã xong.',
                     'Mỗi ngày/tuần có một bản tóm tắt.', 'Ghi chú cho bác sĩ và/hoặc điều dưỡng.', 'Giá 20 nghìn đồng/tháng.',
                     'Huyết áp 120/80 mmHg hiện đúng.', 'Liều 5 mg/kg/ngày.', 'Điểm 3.5/5 trên trang.', 'Ngày 08/11/2026 hiện trên trang.',
                     'Mục Có/Không/Chưa rõ.', 'Chọn ngày (dd/mm/yyyy).', 'Tổng kết Q4 và báo cáo.', 'TP.HCM và Hà Nội.'):
            with self.subTest(text=text):
                self.assertEqual(self.reasons(request=text), [])

    def test_technical_tokens_the_review_found_are_refused(self):
        for text, word in (('Không đọc /etc/passwd của máy.', '/etc/passwd'), ('Sửa hàm trong main.go cho nhanh.', 'main.go'),
                           ('Sửa src\\main.py cho đúng.', 'src\\main.py'), ('Không còn lỗi EACCES khi ghi.', 'EACCES'),
                           ('Theo bản 0EF1B12A của nhánh.', '0EF1B12A'), ('Không còn lỗi ENOENT.', 'ENOENT'),
                           ('Sửa onecrew/v2/lint.py.', 'onecrew/v2/lint.py'), ('Sửa trong docs/a.md.', 'docs/a.md'),
                           ('Đọc ./scripts trước.', './scripts'), ('Đọc ~/.claude trước.', '~/.claude'),
                           ('Mở https://x.com/a.', 'https://x.com/a'), ('Sửa thư mục docs/ trước.', 'docs/'), ('Đọc .env trước.', '.env'),
                           ('Lỗi ERROR_ACCESS_DENIED.', 'ERROR_ACCESS_DENIED'), ('Sửa wfkit\\manifest.json.', 'wfkit\\manifest.json')):
            with self.subTest(word=word):
                [(code, said)] = self.reasons(not_doing=text)
                self.assertEqual(code, 'owner_view_technical')
                self.assertIn(word, said)

    def test_plain_vietnamese_upper_case_and_abbreviations_stay_plain(self):
        for text in ('Bệnh viện ĐHYD dùng trang này.', 'Trang theo dõi cho chủ dự án.', 'Bản PDF in ra giống trên màn hình.',
                     'Không đổi giao diện e-mail hay số điện thoại.', 'Ngày 08/11 hiện trên trang.', 'HIS lưu phiếu như cũ.',
                     'Dùng được trên Windows và Android.', 'Đạt khi cả ba bước đều xong.'):
            with self.subTest(text=text):
                self.assertEqual(self.reasons(user_sees=[text]), [])


class SearchOwnerPart(Fixture):
    def test_search_finds_a_card_by_the_words_on_it(self):
        from onecrew.v2.tracking_web import PAGE
        body = PAGE[PAGE.index('function visible()'):PAGE.index('function row(t)')]
        self.assertIn('workSearch(t)', body)
        import shutil, subprocess
        from onecrew.v2.tracking_work_web import SCRIPT
        node = shutil.which('node')
        if not node: self.skipTest('Node unavailable; not verified')
        prelude = 'function esc(x){return String(x)} function when(x){return x} function hms(x){return String(x)} function openBtn(k){return k}\n'
        t = {'plan': 'P-tech', 'goal': 'Add docs welcome page', 'title': 't', 'current_step': '',
             'owner_view': dict(PLAIN, present=True)}
        done = subprocess.run([node, '-'], input=prelude + SCRIPT + '\nconsole.log(JSON.stringify(workSearch(' + json.dumps(t) + ')));',
                              text=True, encoding='utf8', capture_output=True, timeout=20)
        self.assertEqual(done.returncode, 0, done.stderr[-1500:])
        text = json.loads(done.stdout)
        for words in ('trang chào mừng', 'câu chào', 'p-tech', 'add docs welcome'):
            self.assertIn(words, text)
