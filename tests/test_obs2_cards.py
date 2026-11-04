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

    def test_sourced_stages_do_not_confuse_verified_closed_and_accepted(self):
        tasks = [dict(root_status='proposed'),dict(root_status='approved',status={'kind':'running'}),
                 dict(root_status='approved',nodes_summary={'produced':1}),dict(root_status='approved',level={'kind':'verified'}),
                 dict(root_status='accepted'),dict(root_status='closed'),dict(status={'kind':'unknown'})]
        self.assertEqual(self.run_js(json.dumps(tasks)+'.map(workStage)'), ['todo','doing','check','accept','done','closed','unknown'])

    def test_owner_attention_is_not_an_execution_stage(self):
        task={'root_status':'approved','status':{'kind':'running'},'active':[{'status':'running'}],
              'needs_user':[{'kind':'request'}]}
        self.assertEqual(self.run_js('workStage('+json.dumps(task)+')'),'doing')
        self.assertEqual(self.run_js('workStatus('+json.dumps(task)+')'),'Đang thực hiện')
        task['status']['kind']='blocked'
        self.assertIn('phần khác vẫn thực hiện',self.run_js('workStatus('+json.dumps(task)+')'))

    def test_pending_amendment_does_not_move_running_work_to_not_started(self):
        task={'root_status':'proposed','status':{'kind':'waiting'},'active':[{'status':'running'}],
              'needs_user':[{'kind':'approve'}]}
        self.assertEqual(self.run_js('workStage('+json.dumps(task)+')'),'doing')
        self.assertEqual(self.run_js('workStatus('+json.dumps(task)+')'),'Đang thực hiện · chờ duyệt thay đổi')

    def test_resumed_pending_task_is_not_claimed_never_started(self):
        task={'root_status':'approved','has_started':True,'status':{'kind':'waiting'},'nodes_summary':{'pending':2}}
        self.assertEqual(self.run_js('workStage('+json.dumps(task)+')'),'doing')
        self.assertEqual(self.run_js('workStatus('+json.dumps(task)+')'),'Chờ bước tiếp theo')

    def test_waiting_on_check_is_not_waiting_on_owner(self):
        task={'root_status':'approved','nodes_summary':{'produced':1},'needs_user':[]}
        self.assertEqual(self.run_js('workStatus('+json.dumps(task)+')'),'Đã có đầu ra · chờ kiểm')

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
        out=self.run_js('workOverview(d,d.work)','\nvar d='+json.dumps(data)+';')
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
