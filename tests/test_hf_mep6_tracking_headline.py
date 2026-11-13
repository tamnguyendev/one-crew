"""MEP hotfix, sixth pass (mep6): the tracking page speaks to the owner.

On a trial project (08/11) the card's title was the AI's restated goal: up to 3000 characters of engineering
text. The status read "chờ verdict của mốc M2, M3 (root không có engine: chỉ theo dõi mốc)". The owner could not tell what was
being done. mep6 changes four things:
- the card and the detail take the contract's own `title` (`headline`) first, and the restated goal stays in the detail;
- a milestone plan in progress with no failed check reads "Đang làm · đạt k/n mốc · chờ kiểm <ids left>";
- the card and the detail name the next milestone that has not passed;
- the full sourced reason stays in status.reason.
Real temporary ledgers, the shipped JS run in Node, no live provider."""
import json
import sys
import unittest

from onecrew.v2 import tracking, tracking_web, verdict
from tests import test_obs2_cards as cards
from tests import test_v2_l1 as fixtures

FAIL = [sys.executable, '-c', 'raise SystemExit(3)']
TITLE = 'S10e: sửa tài liệu cho đúng giới hạn của khoá chống nộp trùng; engine không đổi'
GOAL = 'Trên bản chép <thư mục làm việc>: không đổi luật so khớp; ngưỡng góc tính lại từ dung sai vị trí ' + 'x' * 400


class Headline(fixtures.Fixture):
    run_js = cards.Cards.run_js

    def plan(self, first=None):
        value = fixtures.plan_json([fixtures.milestone('M1', **({'argv': first} if first else {})), fixtures.milestone('M2'), fixtures.milestone('M3')])
        value['title'] = TITLE
        value['understanding']['restated_goal'] = GOAL
        self.approved(value=value)

    def views(self):
        ov = tracking.overview(self.ledger.state_root)
        item = next(t for p in ov['projects'] for t in p['tasks'] if t['plan'] == 'P1')
        return item, tracking.detail(self.ledger.state_root, 'P1')

    def js(self, fn, task):
        return self.run_js(fn + '(' + json.dumps(task) + ')')

    def test_the_card_and_the_detail_take_the_contract_title_and_keep_the_goal(self):
        self.plan()
        item, detail = self.views()
        self.assertEqual(item['headline'], TITLE)
        self.assertTrue(item['goal'].startswith('Trên bản chép'))                      # the restated goal is still served for the detail
        self.assertEqual(self.js('workTitle', item), TITLE)
        self.assertEqual(self.js('workTitle', detail), TITLE)

    def test_without_a_contract_title_the_goal_is_still_the_title(self):
        task = {'plan': 'P9', 'headline': '', 'goal': 'Mục tiêu cũ', 'title': 'Plan P9: x'}
        self.assertEqual(self.js('workTitle', task), 'Mục tiêu cũ')

    def test_a_passed_milestone_reads_as_a_count_and_names_the_next_one(self):
        self.plan()
        verdict.run(self.ledger, 'P1', 'M1')
        item, detail = self.views()
        self.assertEqual([m['state'] for m in item['milestones']], ['passed', 'pending', 'pending'])     # precondition: a real passing verdict
        for t in (item, detail):                                                            # 13/11: a short badge; the count, the reason and the next step apart
            self.assertEqual(self.js('workStatus', t), 'Đang thực hiện')
            self.assertEqual(t['situation']['milestones']['text'], 'Đạt 1/3 mốc')
            self.assertEqual(t['situation']['reason'], 'Chưa kiểm mốc M2, M3')
            self.assertEqual(t['situation']['next'], 'Làm và kiểm mốc M2')
            self.assertEqual(self.js('nextMilestone', t), 'M2 — Milestone M2')
        self.assertIn('chờ verdict của mốc M2, M3', item['status']['reason'])            # the sourced reason is unchanged

    def test_a_failed_milestone_still_says_it_failed(self):
        self.plan(first=FAIL)
        verdict.run(self.ledger, 'P1', 'M1')
        item, _ = self.views()
        card = self.js('workStatus', item)
        self.assertEqual(card, 'Cần sửa')
        self.assertIn('M1', item['situation']['reason']); self.assertIn('không đạt', item['situation']['reason'])

    def test_the_board_card_names_the_next_milestone_only_while_work_is_in_progress(self):
        self.plan()
        before, _ = self.views()
        verdict.run(self.ledger, 'P1', 'M1')
        during, _ = self.views()
        html = self.run_js('row(' + json.dumps(during) + ')', extra=self.row_source())
        self.assertIn('Làm và kiểm mốc M2', html); self.assertIn('Đang thực hiện', html)
        self.assertIn(TITLE, html)
        first = self.run_js('row(' + json.dumps(before) + ')', extra=self.row_source())
        self.assertIn('Chưa bắt đầu', first); self.assertNotIn('Đang thực hiện', first)        # not started: never shown as in progress

    def row_source(self):
        page = tracking_web.PAGE
        body = page[page.index('function row(t){'):page.index('function render(force){')]
        return '\nvar selected=null,lastViewed=null;function sameSel(){return false}function rel(x){return x}function short(x){return x}\n' + body


if __name__ == '__main__':
    unittest.main()
