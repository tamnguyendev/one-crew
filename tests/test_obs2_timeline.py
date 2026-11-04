"""Timeline UX requirements: execute the shipped JS against sourced model shapes."""
import json
import shutil
import subprocess
import unittest
from onecrew.v2.tracking_web import PAGE

START='2026-11-04T00:00:00.000Z'
END='2026-11-04T00:00:00.021Z'

class TimelineUX(unittest.TestCase):
    def js(self,expr,setup=''):
        if not shutil.which('node'):self.skipTest('Node unavailable')
        code=PAGE[PAGE.index('function tms(t)'):PAGE.index('function repaintGantt()')]
        pre=r"""var gRange='current',gPinnedWindow=null,gFold={},selStep=null,lostSince=null,detailError=null,lastOk=null,detailOkAt=null;
function esc(x){return String(x==null?'':x).replace(/[&<>\"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]))}
function when(x){return x||'chưa xác định'}function hms(x){return String(x)}function nodeName(d,n){return (d.work.node_titles||{})[n]||n}function workStatus(d){return d.current_step}function prov(d){return {bySeq:{}}}function occDiv(x){return esc(x.key)}
"""
        r=subprocess.run(['node','-'],input=pre+code+'\n'+setup+'\nconsole.log(JSON.stringify('+expr+'));',text=True,encoding='utf-8',capture_output=True,timeout=10)
        self.assertEqual(r.returncode,0,r.stderr);return json.loads(r.stdout)
    def detail(self):
        r={'node':'C','attempt':'att:one','generation':1,'status':'settled','current':True,'active':False,'launched_at':START,'settled_at':END,'execution_seconds':.021,'segments':[{'kind':'execution','from':START,'to':END,'confirmed':True}],'waits':[],'verification':[],'marks':[]}
        return {'plan':'DOC','current_step':'Đã tạo nội dung, chờ kiểm','nodes':{'C':{'phase':'complete','state':'produced'},'I':{'phase':'pending','state':'none'}},'work':{'node_titles':{'C':'Chuẩn bị nội dung hướng dẫn cho người sử dụng','I':'Kiểm tra kết quả tích hợp'}},'gantt':{'axis':{'start':START,'end':END,'seconds':.021},'rows':[r],'plan_marks':[]},'evidence_index':[]}
    def test_short_window_not_fabricated_one_second(self):
        d=self.detail();w=self.js('gWindow(d.gantt)','var d='+json.dumps(d)+';');self.assertEqual(w['w1']-w['w0'],21)
    def test_ticks_unique_for_ms_seconds_hours_and_days(self):
        for ms in (1,21,999,2911,3600000,86400000):
            ts=self.js('gTicks({w0:0,w1:'+str(ms)+'})');labels=[t['label'] for t in ts];self.assertEqual(len(labels),len(set(labels)));self.assertGreaterEqual(len(ts),3);self.assertLessEqual(len(ts),6)
    def test_hour_axis_uses_readable_quarter_hours(self):
        self.assertEqual([x['label'] for x in self.js('gTicks({w0:0,w1:3600000})')],['0s','15 phút','30 phút','45 phút','1 giờ'])
    def test_missing_time_is_not_epoch(self):
        self.assertIsNone(self.js('gWindow({axis:{start:null,end:null},rows:[]})'))
    def test_zero_window_has_minimal_geometry_but_real_duration_zero(self):
        self.assertEqual(self.js('gWindow({axis:{start:1,end:1},rows:[]})')['w1'],2)
        self.assertEqual(self.js('gDuration(0)'),'0s')
    def test_current_window_excludes_old_attempt(self):
        d=self.detail();old=dict(d['gantt']['rows'][0],attempt='att:old',current=False,segments=[{'kind':'execution','from':'2026-11-03T00:00:00Z','to':'2026-11-03T01:00:00Z'}]);d['gantt']['rows'].append(old)
        self.assertEqual(self.js('gWindow(d.gantt).w1-gWindow(d.gantt).w0','var d='+json.dumps(d)+';'),21)
    def test_history_window_is_pinned_while_model_advances(self):
        self.assertEqual(self.js('gWindow({axis:{start:10,end:900},rows:[]})',"gRange='all';gPinnedWindow={range:'all',w0:10,w1:100};")['w1'],100)
    def test_node_summary_default_and_no_empty_detail_panel(self):
        out=self.js('gantt(d)','var d='+json.dumps(self.detail())+';')
        self.assertIn('data-node-select="C"',out);self.assertIn('Đã tạo đầu ra · chờ kiểm',out);self.assertIn('Thực thi: 21 ms',out);self.assertNotIn('class="grow att"',out);self.assertIn('id="gside" hidden',out)
    def test_pending_step_no_fake_bar_or_zero_execution(self):
        out=self.js('gantt(d)','var d='+json.dumps(self.detail())+';');self.assertIn('Chưa đến lượt',out);self.assertIn('Chưa khởi chạy',out)
    def test_verification_interval_explicitly_may_include_wait(self):
        d=self.detail();d['gantt']['rows'][0]['verification']=[{'from':START,'to':'2026-11-04T00:10:00Z','result':'pass'}]
        out=self.js('gantt(d)','var d='+json.dumps(d)+';');self.assertIn('có thể gồm chờ',out);self.assertIn('Chưa có mốc riêng',out);self.assertIn('Từ đầu ra đến kết quả kiểm',out)
    def test_node_selection_uses_current_evidence_not_old_pass(self):
        d=self.detail();d['evidence_index']=[{'attempt':'att:one','output':True,'key':'current-output'},{'attempt':'att:old','output':True,'key':'old-pass'}]
        out=self.js('gantt(d)',"var d="+json.dumps(d)+";selStep={id:'node:C'};")
        self.assertIn('current-output',out);self.assertNotIn('old-pass',out);self.assertIn('Đã tạo đầu ra · chờ kiểm',out)
    def test_node_source_details_preserve_millisecond_timestamps(self):
        out=self.js('gantt(d)',"var d="+json.dumps(self.detail())+";selStep={id:'node:C'};")
        self.assertIn(END,out);self.assertIn(START,out)
    def test_long_hostile_name_is_text(self):
        d=self.detail();d['work']['node_titles']['C']='<img onerror=evil>'
        out=self.js('gantt(d)','var d='+json.dumps(d)+';');self.assertNotIn('<img',out);self.assertIn('&lt;img',out)
    def test_parallel_duration_is_union_not_sum(self):
        rows=[{'launched_at':START,'settled_at':'2026-11-04T00:00:10Z'},{'launched_at':'2026-11-04T00:00:05Z','settled_at':'2026-11-04T00:00:15Z'}]
        self.assertEqual(self.js('gNodeTime('+json.dumps(rows)+')'),'Thực thi: 15s')
    def test_submillisecond_duration_preserves_source_precision(self):
        self.assertEqual(self.js('gNodeTime([{execution_seconds:0.0004}])'),'Thực thi: <1 ms')
    def test_running_unknown_is_not_zero(self):
        self.assertEqual(self.js('gNodeTime([{launched_at:null,settled_at:null}])'),'Thực thi: chưa đủ mốc đo')
    def test_history_unfolds_without_replacing_current_identity(self):
        d=self.detail();d['gantt']['rows'].append(dict(d['gantt']['rows'][0],attempt='att:old',current=False,generation=0))
        out=self.js('gantt(d)',"var d="+json.dumps(d)+";gFold={'n:C':false,'h:C':false};")
        self.assertIn('Lượt hiện hành',out);self.assertIn('Lượt cũ',out);self.assertIn('data-attempt="att:old"',out);self.assertIn('data-attempt="att:one"',out)

if __name__=='__main__':unittest.main()
