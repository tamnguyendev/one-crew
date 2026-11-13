"""User-task assertions for card grouping, ordering and action presentation."""
import json
import shutil
import subprocess
import unittest

from onecrew.v2.tracking_work_web import SCRIPT
from onecrew.v2.tracking_web import PAGE


class Cards(unittest.TestCase):
    def run_js(self, expr, extra=''):
        node = shutil.which('node')
        if not node: self.skipTest('Node unavailable; not verified')
        prelude = '''function esc(x){return String(x==null?'':x).replace(/[&<>\"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]))}
function when(x){return x} function hms(x){return String(x)} function openBtn(k){return '<button>'+esc(k)+'</button>'}
'''
        result = subprocess.run([node, '-'], input=prelude+SCRIPT+extra+'\nconsole.log(JSON.stringify('+expr+'));', text=True, encoding='utf8', capture_output=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout)

    # 13/11: the stage is the model's (tracking_situation.situation); the page renders sit(t) and derives none. Same intents as before, on the model.
    def model(self, **kw):
        from tests.test_tracking_situation import call
        return call(**kw)

    def test_sourced_stages_do_not_confuse_verified_closed_and_accepted(self):
        from tests.test_tracking_situation import state, view
        ev = lambda **n: {'nodes': n, 'definition': {'nodes': [{'id': k} for k in n]}}
        got = [self.model(state=state('proposed'))['stage'],
               self.model(engine_view=ev(C={'phase': 'running', 'attempt': 'a'}), active=[{'attempt': 'a', 'status': 'running', 'node': 'C'}], has_started=True)['stage'],
               self.model(engine_view=ev(C={'phase': 'complete', 'state': 'produced'}), has_started=True)['stage'],
               self.model(engine_view=ev(C={'phase': 'complete', 'state': 'verified'}), has_started=True, level='verified', acceptance={'ready': True})['stage'],
               self.model(state=state('accepted'))['stage'], self.model(state=state('closed'))['stage'], self.model()['stage']]
        self.assertEqual(got, ['todo', 'doing', 'check', 'accept', 'done', 'closed', 'unknown'])
        self.assertEqual(self.run_js('[{situation:{stage:"closed",label:"Đã đóng"}}].map(workStage)'), ['closed'])     # the page takes the model's word

    def test_owner_attention_is_not_an_execution_stage(self):
        ev = {'nodes': {'C': {'phase': 'running', 'attempt': 'a'}}, 'definition': {'nodes': [{'id': 'C'}]}}
        s = self.model(engine_view=ev, active=[{'attempt': 'a', 'status': 'running', 'node': 'C'}], has_started=True, needs=[{'kind': 'request', 'question': 'Q?'}])
        self.assertEqual((s['stage'], s['label'], s['next_by_text']), ('doing', 'Đang thực hiện', 'Bạn'))
        self.assertTrue(s['activity']['running'])

    def test_pending_amendment_does_not_move_running_work_to_not_started(self):
        from tests.test_tracking_situation import state
        ev = {'nodes': {'C': {'phase': 'running', 'attempt': 'a'}}, 'definition': {'nodes': [{'id': 'C'}]}}
        s = self.model(state=state('proposed', latest=2), engine_view=ev, active=[{'attempt': 'a', 'status': 'running', 'node': 'C'}], has_started=True,
                       needs=[{'kind': 'approve'}])
        self.assertEqual((s['stage'], s['next']), ('doing', 'Duyệt hoặc yêu cầu sửa kế hoạch'))

    def test_old_verified_output_does_not_put_new_proposal_in_acceptance(self):
        from tests.test_tracking_situation import state
        ev = {'nodes': {'C': {'phase': 'complete', 'state': 'verified'}}, 'definition': {'nodes': [{'id': 'C'}]}}
        s = self.model(state=state('proposed', latest=2), engine_view=ev, has_started=True, level='verified', acceptance={'ready': False}, needs=[{'kind': 'approve', 'revision': 2}])
        self.assertNotEqual(s['stage'], 'accept'); self.assertEqual(s['next_by_text'], 'Bạn')

    def test_resumed_pending_task_is_not_claimed_never_started(self):
        ev = {'nodes': {'C': {'phase': 'complete', 'state': 'verified', 'attempt': 'a'}, 'I': {'phase': 'pending'}}, 'definition': {'nodes': [{'id': 'C'}, {'id': 'I'}]}}
        s = self.model(engine_view=ev, has_started=True)
        self.assertEqual(s['stage'], 'doing'); self.assertFalse(s['activity']['running'])

    def test_waiting_on_check_is_not_waiting_on_owner(self):
        ev = {'nodes': {'C': {'phase': 'complete', 'state': 'produced'}}, 'definition': {'nodes': [{'id': 'C'}]}}
        s = self.model(engine_view=ev, has_started=True)
        self.assertEqual((s['stage'], s['next_by_text']), ('check', 'Bộ kiểm OneCrew')); self.assertTrue(s['no_owner_decision'])

    def test_sort_is_explicit_stable_and_nonmutating(self):
        rows=[{'id':'b','created_at':'2026-01-01','last_update':{'at':'2026-01-03'}},
              {'id':'a','created_at':'2026-01-02','needs_user':[{'kind':'approve'}],'deadline':'2026-01-04'}]
        extra='\nvar original='+json.dumps(rows)+';'
        for mode, expected in [('attention',['a','b']),('updated',['b','a']),('created',['b','a']),('deadline',['a','b'])]:
            value=self.run_js('[workOrder(original,"'+mode+'").map(x=>x.id),original.map(x=>x.id)]',extra)
            self.assertEqual(value,[expected,['b','a']])

    def test_latest_solution_changes_not_hidden_after_old_internal_changes(self):
        rows=[{'id':'1','kind':'internal','revision':1,'internal_revision':2,'reason':'old'},
              {'id':'2','kind':'contract','revision':2,'reason':'new','diff':[{'path':'title','before':'a','after':'b'}]}]
        out=self.run_js('workChanges({},'+json.dumps({'changes':rows})+')')
        self.assertLess(out.index('new'),out.index('old'))
        self.assertIn('lần 2 (phương án 1)',out)
        self.assertIn('Tên công việc',out)
        self.assertIn('<details data-k="work-diff:',out)

    def test_overview_counts_current_outputs_only(self):
        data={'status':{},'needs_user':[],'work':{'outputs':[{'stale':True,'level':'verified'},{'stale':False,'level':'produced'}]}}
        out=self.run_js('workOverview(d,d.work)','\nvar d='+json.dumps(data)+';function short(x){return x}function rel(x){return x}')
        self.assertIn('1 đầu ra hiện hành · 0 đã kiểm',out)

    def test_action_has_separate_powershell_block_and_no_browser_write(self):
        start=PAGE.index('function cmdHtml(');end=PAGE.index('function needs_open_sync',start)
        helpers=PAGE[start:end]
        extra='\nvar detailError=null,copied=null;\n'+helpers
        command="& 'D:/runtime/onecrew.exe' --project 'D:/dự án' owner approve 'plan-ns:CODE' --revision 2 --choose '<option-id>' --human"
        n={'kind':'approve','id':'CODE','revision':2,'question':'Duyệt bản 2','human_command':command,'placeholders':['option-id']}
        out=self.run_js('needCard('+json.dumps(n)+',0)',extra)
        self.assertIn('<pre><code>',out)
        self.assertIn('PowerShell',out)
        self.assertIn('Sao chép lệnh',out)
        self.assertIn('--revision 2',out)
        self.assertIn('Chạy lệnh thành công mới ghi quyết định',out)
        self.assertIn('<mark class="ph">&lt;option-id&gt;</mark>',out)
        self.assertIn('ID phương án anh chọn',out)
        self.assertNotIn('onclick=',out)


if __name__=='__main__': unittest.main()
