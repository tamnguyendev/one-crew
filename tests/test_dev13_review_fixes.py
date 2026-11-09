"""2.5.0.dev14 — third independent review (Kiro CLI, gpt-5.6-sol, 09/11; BAO-CAO-REVIEW-dev13.md, verdict FAIL) on 698e118. Every test here is red on 698e118.

Owner 09/11 ~16:00, asked "Bộ lọc chỉ chặn chữ chắc chắn kỹ thuật, chữ mơ hồ chỉ cảnh báo?": "Đồng ý".
L1 (P2)  plain words are checked at two levels: owner_view_technical refuses only what is certainly technical; owner_view_maybe_technical warns
         (plan lint exit 0, propose/approve go on and say it). Medical Vietnamese (ICD codes, doses, vitamins, rooms) passes clean.
L2 (P1)  the library reuse skipped the "fail if" rule.
L3 (P2)  the library propose / amend wrote a revision without "fail if".
L4 (P2)  plan rules init wrote the owner-rules file without the ledger lock, so it could appear between approve's last check and its record.
"""
import json
import threading
import time
from pathlib import Path
from unittest.mock import patch

from onecrew.ledger import LedgerError
from onecrew.v2 import lint
from tests.test_dev11_owner_view import PLAIN, CommandRefusals
from tests.test_v2_l1 import Fixture, plan_json

NO_FAIL = [{'id': 'R1', 'question': 'Does the diff update a.txt?'}]
MEDICAL = ('Bệnh nhân ở phòng B12 tầng 3.', 'Chọn phương án A/B/C.', 'Hẹn tái khám ngày 09/11/2026.', 'Xe chạy 60 km/h.', 'SpO2 đạt 95%.',
           'Bổ sung vitamin D3/B12.', 'Bổ sung vitamin D3 và B12.', 'Uống paracetamol 500 mg mỗi 8 giờ.', 'Liều 5 mg/kg/ngày.',
           'Tiêm enoxaparin 1 mg/kg/24 giờ.', 'Chẩn đoán ICD-10: F32.1; theo dõi I10.', 'Viêm phổi J18.9 đã ổn.', 'Câu Q1/Q2 trên phiếu.',
           'Huyết áp 120/80 mmHg.', 'Kết quả HbA1c 6,5%.', 'Đường huyết 7 mmol/l.', 'Truyền 20 ml/h trong 24/7.', 'In trên khổ A4.',
           'Mã ICD-10 T39 cho ngộ độc.', 'Bệnh viện ĐHYD dùng bản PDF.', 'Chọn online/offline.', 'Giường A12 khoa nội, nhóm máu O.')
CERTAIN = (('Sửa C:\\Users\\NUC\\a.txt.', 'C:\\Users\\NUC\\a.txt'), ('Mở \\\\server\\share.', '\\\\server\\share'), ('Không đọc /etc/passwd.', '/etc/passwd'),
           ('Đọc ./scripts trước.', './scripts'), ('Đọc ../docs trước.', '../docs'), ('Đọc ~/.claude trước.', '~/.claude'),
           ('Mở HTTPS://x.com/a.', 'HTTPS://x.com/a'), ('Sửa main.go.', 'main.go'), ('Sửa docs/a.md.', 'docs/a.md'), ('Chạy với --human.', '--human'),
           ('Gõ `plan lint` trước.', '`plan lint`'), ('Theo bản 0eF1B12a.', '0eF1B12a'), ('Không còn lỗi Errno 13.', 'Errno 13'),
           ('Không còn Traceback.', 'Traceback'), ('Không còn lỗi EACCES.', 'EACCES'), ('Mốc M1 đạt.', 'M1'), ('Bản rev 2 hiện ra.', 'rev 2'),
           ('Theo v2.5 trở đi.', 'v2.5'), ('Bản dev12 chạy được.', 'dev12'))
MAYBE = (('Gọi api/v2 trước.', 'api/v2'), ('Đọc ui/db trước.', 'ui/db'), ('Sửa src/app trước.', 'src/app'), ('Sửa Dockerfile.', 'Dockerfile'),
         ('Theo yêu cầu REQ-123.', 'REQ-123'), ('Mở www.example.com.', 'www.example.com'), ('Lỗi ERROR_ACCESS_DENIED.', 'ERROR_ACCESS_DENIED'),
         ('Có bản U1 của chủ.', 'U1'), ('Sửa lỗi F7.', 'F7'), ('Theo quy tắc R3.', 'R3'))


def reviewer(criteria):
    return [{'id': 'M1', 'title': 'Review', 'covers': ['O1'], 'verifier': {'type': 'reviewer', 'config': {
        'provider': 'claude', 'model': 'claude-haiku-5-5', 'criteria': criteria, 'max_minutes': 5}}}]


class TwoLevels(Fixture):
    """L1: refuse only the certain; warn on the ambiguous; medical Vietnamese is clean (neither)."""
    def owner(self, text):
        value = plan_json(presentation=dict(PLAIN, not_doing=text))
        led = lint.ReadOnlyLedger(self.root, self.ledger.state_root)
        refused = [r for r in lint.lint(led, value) if r[0] == 'owner_view_technical']
        warned = [w for w in lint.check(led, value)[1] if w[0] == 'owner_view_maybe_technical']
        return refused, warned

    def test_medical_and_everyday_vietnamese_is_clean(self):
        for text in MEDICAL:
            with self.subTest(text=text):
                self.assertEqual(self.owner(text), ([], []))

    def test_what_is_certainly_technical_is_refused(self):
        for text, word in CERTAIN:
            with self.subTest(word=word):
                refused, _ = self.owner(text)
                self.assertEqual(len(refused), 1, refused); self.assertIn(word, refused[0][1])

    def test_what_may_be_technical_is_a_warning_not_a_refusal(self):
        for text, word in MAYBE:
            with self.subTest(word=word):
                refused, warned = self.owner(text)
                self.assertEqual(refused, [])
                self.assertEqual(len(warned), 1, warned); self.assertIn(word, warned[0][1])


class Commands(Fixture):
    contract, cli, file = CommandRefusals.contract, CommandRefusals.cli, CommandRefusals.file

    def test_plan_lint_exits_0_with_the_warning_and_propose_goes_on_and_says_it(self):
        value = self.contract(not_doing='Không gọi api/v2.')
        rc, text = self.cli('plan', 'lint', '--file', self.file(value), '--author', 'claude-opus-5-5')
        self.assertEqual(rc, 0, text); self.assertIn('[owner_view_maybe_technical]', text); self.assertIn('api/v2', text)
        rc, text = self.cli('plan', 'propose', 'P1', '--file', self.file(value), '--author', 'claude-opus-5-5')
        self.assertEqual(rc, 0, text)
        self.assertIn('owner_view_maybe_technical', json.loads(text).get('warnings', [[None]])[0][0] or '')

    def test_owner_approve_human_says_the_warning(self):
        value = self.contract(not_doing='Không gọi api/v2.')
        self.assertEqual(self.cli('plan', 'propose', 'P1', '--file', self.file(value), '--author', 'claude-opus-5-5')[0], 0)
        rc, text = self.cli('owner', 'approve', 'P1', '--reference', 'fixture', '--human')
        self.assertEqual(rc, 0, text)
        self.assertIn('Đã ghi nhận duyệt', text); self.assertIn('Cảnh báo', text); self.assertIn('api/v2', text)


class LibraryContractRules(Fixture):
    """L2, L3: the library propose, amend and reuse judge the same contract rules as the commands and approve (owner part and "fail if")."""
    contract = CommandRefusals.contract

    def test_library_propose_and_amend_refuse_a_criterion_without_fail_if(self):
        from onecrew.v2 import plan as plans
        value = self.contract(); value['milestones'] = reviewer(NO_FAIL)
        with self.assertRaises(LedgerError) as caught:
            plans.propose(self.ledger, 'P1', value, 'claude-opus-5-5')
        self.assertIn('[criterion_no_fail_clause]', str(caught.exception))
        plans.propose(self.ledger, 'P2', self.contract(), 'claude-opus-5-5')
        with self.assertRaises(LedgerError) as caught:
            plans.amend(self.ledger, 'P2', value, 'why', 'claude-opus-5-5')
        self.assertIn('[criterion_no_fail_clause]', str(caught.exception))
        self.assertEqual(plans.show(self.ledger, 'P2')['revision'], 1)

    def test_library_reuse_refuses_an_approved_plan_without_fail_if(self):
        from onecrew.v2 import plan as plans, step0
        value = self.contract(); value['milestones'] = reviewer(NO_FAIL)
        with patch.object(step0, 'contract_rules', return_value=[]):                # what an older OneCrew recorded and approved
            plans.propose(self.ledger, 'OLD', value, 'claude-opus-5-5')
            plans.approve(self.ledger, 'OLD', 'owner', 'fixture')
        with self.assertRaises(LedgerError) as caught:
            plans.propose(self.ledger, 'OLD', value, 'claude-opus-5-5', reuse_existing=True)
        self.assertIn('[criterion_no_fail_clause]', str(caught.exception)); self.assertIn('plan amend', str(caught.exception))


class RulesInitTakesTheLedgerLock(Fixture):
    """L4: plan rules init writes the owner-rules file inside a ledger write transaction, so it cannot appear between approve's last check
    (inside its write transaction) and the approval it records."""
    def test_init_waits_for_a_write_transaction_in_progress(self):
        from onecrew.v2.verifiers import advisor
        with self.ledger.transaction(write=True): pass                              # the ledger exists
        held, release, done = threading.Event(), threading.Event(), {}

        def writer():
            with self.ledger.transaction(write=True):
                held.set(); release.wait(5)
        thread = threading.Thread(target=writer); thread.start(); held.wait(5)
        init = threading.Thread(target=lambda: done.setdefault('result', advisor.init_rules(self.ledger))); init.start()
        time.sleep(1.0)
        appeared_while_held = advisor.rules_path(self.ledger).exists()
        release.set(); thread.join(5); init.join(15)
        self.assertFalse(appeared_while_held, 'the owner-rules file appeared while another write transaction held the ledger')
        self.assertTrue(done.get('result', {}).get('created'))
