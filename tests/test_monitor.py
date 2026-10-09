import io
import json
from contextlib import redirect_stdout
from pathlib import Path
import unittest
import subprocess
import time
from unittest.mock import patch

import tests.test_owned as fixtures
from onecrew.ledger import Ledger
from onecrew.monitor import snapshot, render, safe, main, open_terminal, marker
from onecrew.owned_intake import submit


class MonitorTests(unittest.TestCase):
    def setUp(self):
        self.f=fixtures.OwnedTests();self.f.setUp();self.addCleanup(self.f.doCleanups)
        self.run,self.task,self.worker=self.f.runtime([])

    def test_actual_parallel_units_group_under_task_and_no_ledger_writes(self):
        revision=self.run.control.status(self.task)['revision']
        for unit,provider in (('api','codex'),('ui','claude')):
            self.run.control.reserve(self.task,revision,unit,{'unit':'task:'+unit,'stage':'implement','provider':provider,'model':'fixture'})
        before=self.f.ledger.path.read_bytes()
        value=snapshot(self.f.ledger,verbose=True)
        task=value['projects'][0]['tasks'][0]
        self.assertEqual({w['unit'] for w in task['workers']},{'task:api','task:ui'})
        self.assertEqual({w['provider'] for w in task['workers']},{'codex','claude'})
        self.assertEqual(self.f.ledger.path.read_bytes(),before)
        self.assertEqual(task['used_calls'],0);self.assertEqual(self.worker.calls,[])
        self.assertIn('NOT workers',render(value,True))

    def test_project_filter_and_global_grouping(self):
        other=self.f.root.parent/'other';other.mkdir()
        ledger=Ledger(other,self.f.ledger.state_root);submit(ledger,'Other project goal','other')
        self.assertEqual(len(snapshot(self.f.ledger)['projects']),1)
        self.assertEqual(len(snapshot(self.f.ledger,all_projects=True)['projects']),2)
        self.assertEqual(snapshot(self.f.ledger,task=self.task,all_projects=True)['shown_tasks'],1)

    def test_sensitive_text_controls_and_question_visibility(self):
        self.assertNotIn('abcdefghijk',safe('API_KEY=abcdefghijklmnop'))
        self.assertNotIn('\x1b',safe('\x1b[2Jnormal\x1b]0;title\x07'))
        self.assertNotIn('pass@example',safe('https://user:pass@example.com'))
        self.f.ledger.create_request(self.task,'which',{'schema_version':1,'question':'Choose scope?',
            'reason':'Need boundary','impact':'Wait','options':[{'id':'a','label':'A'},{'id':'b','label':'B'}],'recommendation':'a',
            'action':{'type':'job.clarification','parameters':{}}})
        self.assertIn('Choose scope?',render(snapshot(self.f.ledger)))

    def test_snapshot_cli_once_does_not_dispatch(self):
        output=io.StringIO()
        with redirect_stdout(output):
            code=main(['--project',str(self.f.root),'--state-root',str(self.f.ledger.state_root),
                       'monitor','--once','--json','--verbose'])
        self.assertEqual(code,0);self.assertTrue(json.loads(output.getvalue())['read_only'])
        self.assertEqual(self.worker.calls,[])

    def test_job_terminal_starts_in_background_and_monitor_failure_does_not_restart(self):
        from onecrew.owned_cli import main as job
        with patch('onecrew.runner.start',return_value={'status':'alive'}) as start, patch(
                'onecrew.monitor.open_terminal',side_effect=OSError('console unavailable')), redirect_stdout(io.StringIO()) as out:
            code=job(['--project',str(self.f.root),'--state-root',str(self.f.ledger.state_root),
                      'job','submit','--goal','Another goal','--key','terminal','--terminal'])
        self.assertEqual(code,0);self.assertEqual(start.call_count,1)
        self.assertTrue(json.loads(out.getvalue())['terminal']['runner_unaffected'])
        self.assertEqual(self.worker.calls,[])

    def test_launching_viewer_reused_without_duplicate_process(self):
        path=marker(self.f.ledger,None,True,True,12).with_suffix('.launch.json')
        path.parent.mkdir(parents=True);path.write_text(json.dumps({'identity':{'pid':123},'status':'starting'}))
        with patch('onecrew.monitor.probe',return_value='alive'),patch('onecrew.monitor.subprocess.Popen') as popen:
            self.assertTrue(open_terminal(self.f.ledger)['reused'])
        popen.assert_not_called()

    def test_monitor_interrupt_has_no_control_side_effect(self):
        before=self.run.control.status(self.task)
        with patch('onecrew.monitor.time.sleep',side_effect=KeyboardInterrupt),redirect_stdout(io.StringIO()):
            self.assertEqual(main(['--project',str(self.f.root),'--state-root',str(self.f.ledger.state_root),'monitor']),0)
        after=self.run.control.status(self.task)
        self.assertEqual(after['cancel_requested'],before['cancel_requested'])
        self.assertEqual(after['used_calls'],before['used_calls'])

    def test_native_viewer_reuse_and_close_leave_detached_runner_alive(self):
        from onecrew.runner import start,status
        from onecrew.supervisor import probe
        self.run.control.pause(self.task)
        runner=start(self.f.ledger,self.task);viewer=None
        try:
            self.assertEqual(runner['status'],'alive')
            viewer=open_terminal(self.f.ledger,task=self.task,all_projects=False,verbose=True)
            self.assertEqual(viewer['status'],'alive',viewer)
            self.assertTrue(viewer['console_attached'])
            self.assertEqual(snapshot(self.f.ledger)['projects'][0]['tasks'][0]['runner'],'alive')
            duplicate=open_terminal(self.f.ledger,task=self.task,all_projects=False,verbose=True)
            self.assertTrue(duplicate['reused']);self.assertEqual(viewer['identity'],duplicate['identity'])
            self.assertEqual(probe(viewer['identity']),'alive')
            subprocess.run(['taskkill','/PID',str(viewer['identity']['pid']),'/F'],capture_output=True,timeout=5,check=True)
            self.assertEqual(probe(runner['identity']),'alive')
            state=self.run.control.status(self.task)
            self.assertEqual(state['used_calls'],0);self.assertFalse(state['cancel_requested'])
        finally:
            if viewer and probe(viewer['identity'])=='alive':
                subprocess.run(['taskkill','/PID',str(viewer['identity']['pid']),'/F'],capture_output=True,timeout=5)
            self.run.control.cancel(self.task)
            end=time.monotonic()+8
            while time.monotonic()<end and status(self.f.ledger,self.task)['status']!='stopped': time.sleep(.1)
            self.assertEqual(status(self.f.ledger,self.task)['status'],'stopped')


if __name__=='__main__': unittest.main()
