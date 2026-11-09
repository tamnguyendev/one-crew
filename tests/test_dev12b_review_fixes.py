"""2.5.0.dev12 — second independent review (Kiro CLI, gpt-5.6-sol, 09/11; BAO-CAO-REVIEW-dev12.md, verdict FAIL) on b0d3bdb; owner: "Sửa tiếp hết".
Every test here is red on b0d3bdb.

K1 (P1, was F3)  a reviewer criterion without "fail if" makes plan lint exit 1, yet the propose command wrote the plan and approve approved it.
K2 (P2)          a plan approved before the owner rules existed passed the gate of today on a repeated approve and on propose --reuse-existing.
K3 (P2)          the library propose / amend wrote a revision whose owner part lint refuses.
K4 (P2)          the owner rules created while approve ran its preconditions were not seen by the final write.
K5 (P2)          plain words were refused: "phương án A/B/C", "vitamin B12", "phòng B12", "Q1/Q2".
K6 (P2)          technical tokens slipped through: src/app, HTTPS://..., a mixed-case hash.
"""
import json
from pathlib import Path

from onecrew.ledger import LedgerError
from onecrew.v2 import lint
from tests.test_dev11_owner_view import PLAIN, CommandRefusals, owner_reasons
from tests.test_v2_l1 import Fixture, plan_json

NO_FAIL = [{'id': 'R1', 'question': 'Does the diff update a.txt?'}]
WITH_FAIL = [{'id': 'R1', 'question': 'Does the diff update a.txt? fail if a.txt is unchanged.'}]


def reviewer(criteria):
    return [{'id': 'M1', 'title': 'Review', 'covers': ['O1'], 'verifier': {'type': 'reviewer', 'config': {
        'provider': 'claude', 'model': 'claude-haiku-5-5', 'criteria': criteria, 'max_minutes': 5}}}]


class Base(Fixture):
    contract, cli, file = CommandRefusals.contract, CommandRefusals.cli, CommandRefusals.file

    def rules_file(self):
        return Path(self.ledger.state_root) / 'plans' / 'owner-rules.md'

    def rules(self):
        self.rules_file().parent.mkdir(parents=True, exist_ok=True); self.rules_file().write_text('# rules\n', encoding='utf-8')

    def error(self, argv):
        rc, text = self.cli(*argv)
        self.assertNotEqual(rc, 0, text)
        return json.loads(text)['error']


del CommandRefusals


class NoFailClause(Base):
    """K1: the same rule at lint, at the propose command and at approve, on every path."""
    def test_the_propose_command_refuses_a_criterion_without_fail_if(self):
        value = self.contract(); value['milestones'] = reviewer(NO_FAIL)
        error = self.error(('plan', 'propose', 'P1', '--file', self.file(value), '--author', 'claude-opus-5-5'))
        self.assertIn('[criterion_no_fail_clause]', error); self.assertIn('nothing was written', error)

    def test_approve_refuses_a_criterion_without_fail_if_on_the_library_path(self):
        from onecrew.v2 import plan as plans
        from unittest.mock import patch
        from onecrew.v2 import step0
        value = self.contract(); value['milestones'] = reviewer(NO_FAIL)
        with patch.object(plans, 'refuse_owner_part'):                       # recorded by an older OneCrew (dev14: the library refuses it now)
            plans.propose(self.ledger, 'P1', value, 'claude-opus-5-5')
        with self.assertRaises(LedgerError) as caught:
            plans.approve(self.ledger, 'P1', 'owner', 'fixture')
        self.assertIn('[criterion_no_fail_clause]', str(caught.exception))
        self.assertEqual(plans.show(self.ledger, 'P1')['status'], 'proposed')

    def test_a_criterion_with_fail_if_is_proposed_and_approved(self):
        value = self.contract(); value['milestones'] = reviewer(WITH_FAIL)
        self.assertEqual(self.cli('plan', 'propose', 'P1', '--file', self.file(value), '--author', 'claude-opus-5-5')[0], 0)
        rc, text = self.cli('plan', 'approve', 'P1', '--by', 'owner', '--reference', 'fixture')
        self.assertEqual(rc, 0, text)


class ApprovedBeforeTheRules(Base):
    """K2: a plan approved before the owner rules existed meets the rules of today on a repeated approve and on reuse; the refusal names the way
    out (plan amend with the four sentences), and that way out works."""
    def setUp(self):
        super().setUp()
        from onecrew.v2 import plan as plans
        self.old = self.contract(none=True)
        plans.propose(self.ledger, 'OLD', self.old, 'claude-opus-5-5')
        plans.approve(self.ledger, 'OLD', 'owner', 'fixture')
        self.rules()

    def test_a_repeated_approve_meets_the_owner_part_of_today(self):
        from onecrew.v2 import plan as plans
        for argv in (('plan', 'approve', 'OLD', '--by', 'owner', '--reference', 'again'), ('owner', 'approve', 'OLD', '--reference', 'again')):
            with self.subTest(argv=argv[:2]):
                rc, text = self.cli(*argv)
                self.assertNotEqual(rc, 0, text)
                self.assertIn('owner_view_missing', text); self.assertIn('plan amend', text)
        with self.assertRaises(LedgerError) as caught:
            plans.approve(self.ledger, 'OLD', 'owner', 'again')
        self.assertIn('[owner_view_missing]', str(caught.exception))

    def test_reuse_existing_meets_the_owner_part_of_today(self):
        error = self.error(('plan', 'propose', 'OLD', '--file', self.file(self.old), '--author', 'claude-opus-5-5', '--reuse-existing'))
        self.assertIn('[owner_view_missing]', error); self.assertIn('plan amend', error)

    def test_plan_amend_with_the_four_sentences_unblocks_it(self):
        rc, text = self.cli('plan', 'amend', 'OLD', '--file', self.file(self.contract(), 'a.json'), '--reason', 'owner part', '--author', 'claude-opus-5-5')
        self.assertEqual(rc, 0, text)
        rc, text = self.cli('plan', 'approve', 'OLD', '--by', 'owner', '--reference', 'new revision')
        self.assertEqual(rc, 0, text)


class LibraryProposeAmend(Base):
    """K3: the library propose and amend refuse an owner part lint refuses, before anything is written."""
    def test_library_propose_refuses_a_missing_owner_part_under_the_rules(self):
        from onecrew.v2 import plan as plans
        self.rules()
        with self.assertRaises(LedgerError) as caught:
            plans.propose(self.ledger, 'P1', self.contract(none=True), 'claude-opus-5-5')
        self.assertIn('[owner_view_missing]', str(caught.exception))
        with self.assertRaises(LedgerError): plans.show(self.ledger, 'P1')

    def test_library_propose_refuses_a_technical_owner_part_without_the_rules(self):
        from onecrew.v2 import plan as plans
        with self.assertRaises(LedgerError) as caught:
            plans.propose(self.ledger, 'P1', self.contract(request='Sửa docs/a.md cho người mới.'), 'claude-opus-5-5')
        self.assertIn('[owner_view_technical]', str(caught.exception))

    def test_library_amend_refuses_a_technical_owner_part(self):
        from onecrew.v2 import plan as plans
        plans.propose(self.ledger, 'P1', self.contract(), 'claude-opus-5-5')
        with self.assertRaises(LedgerError) as caught:
            plans.amend(self.ledger, 'P1', self.contract(user_sees=['Mốc M1 đạt.']), 'why', 'claude-opus-5-5')
        self.assertIn('[owner_view_technical]', str(caught.exception))
        self.assertEqual(plans.show(self.ledger, 'P1')['revision'], 1)


class RulesCreatedDuringApprove(Base):
    """K4: the final write of approve judges the owner part again, so rules created while the preconditions ran are not missed."""
    def test_rules_created_while_step0_runs_are_seen_by_the_write(self):
        from onecrew.v2 import plan as plans, step0
        plans.propose(self.ledger, 'P1', self.contract(none=True), 'claude-opus-5-5')     # no rules yet: nothing missing
        evaluate = step0.evaluate

        def rules_meanwhile(*a, **k):
            verdict = evaluate(*a, **k)
            self.rules()
            return verdict
        step0.evaluate = rules_meanwhile
        try:
            with self.assertRaises(LedgerError) as caught:
                plans.approve(self.ledger, 'P1', 'owner', 'fixture')
        finally:
            step0.evaluate = evaluate
        self.assertIn('owner_view_missing', str(caught.exception))
        self.assertEqual(plans.show(self.ledger, 'P1')['status'], 'proposed')


class PlainWordsAgain(Fixture):
    def reasons(self, **shown):
        return owner_reasons(lint.lint(lint.ReadOnlyLedger(self.root, self.ledger.state_root), plan_json(presentation=dict(PLAIN, **shown))))

    def test_plain_vietnamese_the_review_named_and_its_kin_stay_plain(self):
        for text in ('Chọn phương án A/B/C.', 'Bổ sung vitamin B12 vào thực đơn.', 'Bệnh nhân ở phòng B12 tầng 3.', 'Câu Q1/Q2 trên phiếu khảo sát.',
                     'In trên khổ giấy A4.', 'Máy chạy Windows 11.', 'Chỉ số SpO2 hiện đúng.', 'Chọn online/offline ở góc trên.',
                     'Mục X/Y/Z hiện như cũ.', 'Kết quả quý Q3 hiện trên trang.', 'Thuốc nhóm B1, B6 và B12.', 'Giường A12 khoa nội.',
                     'Mẫu đơn C2 của bệnh viện.', 'Đường số 2/3 hiện đúng.', 'Liều 5 mg/kg/ngày.'):
            with self.subTest(text=text):
                self.assertEqual(self.reasons(request=text), [])

    def test_the_tokens_the_review_found_and_onecrew_codes_are_refused(self):
        # dev14 (owner "Đồng ý"): src/app, lib/core and a bare R3, U1, F7, P2 are warnings now (tests/test_dev13_review_fixes.py)
        for text, word in (('Mở HTTPS://x.com/a.', 'HTTPS://x.com/a'), ('Theo bản 0eF1B12a.', '0eF1B12a'),
                           ('Mốc M1 đạt.', 'M1'), ('Bản dev12 chạy được.', 'dev12'),
                           ('Mở Http://x.com.', 'Http://x.com'), ('Theo bản AbC1234dEf.', 'AbC1234dEf')):
            with self.subTest(word=word):
                [(code, said)] = self.reasons(not_doing=text)
                self.assertEqual(code, 'owner_view_technical')
                self.assertIn(word, said)
