"""Dev6 cross-review: presentation must agree with data and permission binding."""
import json
import unittest
from onecrew.v2 import tracking_work, tracking_web
from tests import test_obs2_cards as cards
from tests import test_v2_l1 as fixtures
from onecrew.v2 import tracking, verdict


class ReviewPresentation(unittest.TestCase):
    run_js = cards.Cards.run_js

    def test_unbound_options_are_text_without_copy_or_run_instructions(self):
        helpers = tracking_web.PAGE[tracking_web.PAGE.index('function cmdHtml('):tracking_web.PAGE.index('function needs_open_sync')]
        need = dict(kind='request', id='Q1', question='Choose', reference_placeholder='<reference>',
                    placeholders=['option-id'], binding_reason='Runtime mismatch',
                    options=[dict(id='a', label='A'), dict(id='b', label='B')])
        extra='var detailError=null,copied=null;'+helpers
        html=self.run_js('needCard('+json.dumps(need)+',0)',extra)
        for unwanted in ('data-copy=', 'Mở PowerShell', 'Thay phần', 'Cần điền thêm', 'Chạy lệnh thành công'):
            self.assertNotIn(unwanted,html)
        for wanted in ('Runtime mismatch','<b>A</b>','<b>B</b>'): self.assertIn(wanted,html)
        stale=self.run_js('needCard('+json.dumps(need)+',0)',extra+"copied={k:'need:request:Q1:',ok:false,text:'OLD-WRITE-COMMAND'};")
        self.assertNotIn('OLD-WRITE-COMMAND',stale)
        need['options'][1]['human_command']='valid command'
        html=self.run_js('needCard('+json.dumps(need)+',0)',extra)
        self.assertEqual(html.count('data-copy='),1)
        self.assertIn('data-copy="valid command"',html)
        self.assertIn('Mở PowerShell',html)
        self.assertNotIn('data-copy=""',html)

    def test_milestone_work_is_not_never_started_and_does_not_grant_acceptance(self):
        for milestone in ({'state':'passed'}, {'state':'pending','last_verdict':{'result':'fail'}}):
            task=dict(root_status='approved',status={'kind':'waiting'},nodes_summary={},has_started=False,
                      acceptance={'ready':False},milestones=[milestone],current_step='Cần kiểm lại mốc')
            self.assertEqual(self.run_js('workStage('+json.dumps(task)+')'),'doing')
            self.assertNotEqual(self.run_js('workStatus('+json.dumps(task)+')'),'Chưa khởi chạy')
        task['milestones']=[{'state':'pending'}]
        self.assertEqual(self.run_js('workStage('+json.dumps(task)+')'),'todo')
        task['acceptance']['ready']=True
        self.assertEqual(self.run_js('workStage('+json.dumps(task)+')'),'accept')

    def test_initial_body_is_not_a_change_and_later_change_keeps_its_words(self):
        row=dict(id='first',kind='initial',revision=1,diff=[{'path':'nodes','change':'added','before':None,'after':'Work'}],
                 decision={'validity':{'outcome':'in_authority'}})
        html=self.run_js('workChanges({},'+json.dumps({'changes':[row]})+')')
        self.assertIn('Nội dung kế hoạch',html)
        self.assertNotIn('Nội dung thay đổi:',html)
        self.assertNotIn('Điều chỉnh đã được xử lý',html)
        self.assertNotIn('Xem trước / sau',html)
        row['kind']='internal'
        html=self.run_js('workChanges({},'+json.dumps({'changes':[row]})+')')
        self.assertIn('Nội dung thay đổi:',html)
        self.assertIn('Điều chỉnh đã được xử lý',html)
        self.assertIn('Xem trước / sau',html)

    def test_truncated_structured_finding_is_readable_and_plain_text_retained(self):
        for value in ({'criterion':'C','evidence':['a'*64]*8}, [{'evidence':'a'*600}]):
            claim=json.dumps(value)
            f={'head':claim[:500],'chars':len(claim),'check':{'spec':'Check C'}}
            self.assertEqual(tracking_work._finding_text(f),'Không đạt: Check C')
        plain='The file is invalid. '*40
        self.assertEqual(tracking_work._finding_text({'head':plain[:500],'chars':len(plain)}),plain[:500])
        self.assertEqual(tracking_work._finding_text({'head':'[note] diagnosis'}),'[note] diagnosis')


class MilestoneProgress(fixtures.Fixture):
    run_js=cards.Cards.run_js

    def test_real_verdicts_on_different_artifacts_show_work_without_owner_acceptance(self):
        self.approved(value=fixtures.plan_json([fixtures.milestone('M1'),fixtures.milestone('M2')]))
        verdict.run(self.ledger,'P1','M1')
        (self.root/'a.txt').write_text('changed for second milestone\n')
        verdict.run(self.ledger,'P1','M2')
        before=(self.ledger.state_root/'ledger.sqlite3').read_bytes()
        t=tracking.detail(self.ledger.state_root,'P1')
        self.assertFalse(t['acceptance']['ready'])
        self.assertNotIn('accept',[n['kind'] for n in t['needs_user']])
        self.assertEqual(self.run_js('workStage('+json.dumps(t)+')'),'doing')
        self.assertEqual(before,(self.ledger.state_root/'ledger.sqlite3').read_bytes())
