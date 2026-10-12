import json
import os
from pathlib import Path
import shutil
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from onecrew import delivery_steps as ds
from onecrew import delivery_android as da
from onecrew.eval_observe import project_state
from onecrew.ledger import LedgerError
from tests import test_delivery_android as fixtures


class RecoveryTests(unittest.TestCase):
    def test_blocked_before_source_capture_remains_unverified(self):
        state={'phase':'blocked','plan':{'nodes':[{'id':'test','kind':'regression'}]},
               'delivery':{'source':None,'baseline':None,'preflight':None,'nodes':{'test':{'phase':'pending','receipt':None}}}}
        gates,metrics=project_state(state)
        self.assertEqual(gates['tests'],'unverified');self.assertIsNone(metrics['test_cases_passed'])
        state['delivery']['nodes']=None
        self.assertEqual(project_state(state)[0]['tests'],'unverified')

    def test_nested_dependency_rebased_in_all_build_inputs_and_red(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);src=root/'source';out=root/'capture';red=root/'red'
            for name in ('app/.dart_tool','base/packages/plugin','base-extra'):(src/name).mkdir(parents=True)
            plugin=src/'base/packages/plugin';(plugin/'lib.dart').write_text('source')
            config={'packages':[{'name':'nested','rootUri':plugin.as_uri()},
                                {'name':'prefix','rootUri':(src/'base-extra').as_uri()}]}
            (src/'app/.dart_tool/package_config.json').write_text(json.dumps(config))
            (src/'app/.flutter-plugins-dependencies').write_text(json.dumps({'plugins':{'android':[{'path':str(plugin)}]}}))
            (src/'app/pubspec_overrides.yaml').write_text('dependency_overrides:\n  plugin:\n    path: '+json.dumps(plugin.as_posix())+'\n')
            before=ds.fingerprint(src,['app','base'])
            ds.capture(src,before,out,['app','base'])
            mapped=json.loads((out/'app/.dart_tool/package_config.json').read_text())['packages']
            self.assertEqual(mapped[0]['rootUri'],(out/'base/packages/plugin').as_uri()+'/')
            self.assertEqual(mapped[1]['rootUri'],(src/'base-extra').as_uri()+'/')
            self.assertIn((out/'base/packages/plugin').as_posix(),(out/'app/pubspec_overrides.yaml').read_text())
            native=json.loads((out/'app/.flutter-plugins-dependencies').read_text())['plugins']['android'][0]['path']
            (Path(native)/'generated').write_text('build')
            self.assertFalse((plugin/'generated').exists());self.assertEqual(ds.fingerprint(src,['app','base']),before)
            shutil.copytree(out,red);ds.rebase_packages(out,red,['app','base'])
            self.assertEqual(json.loads((red/'app/.dart_tool/package_config.json').read_text())['packages'][0]['rootUri'],(red/'base/packages/plugin').as_uri()+'/')

    def test_short_home_and_capture_deep_source(self):
        if os.name!='nt':self.skipTest('Windows native path contract')
        with tempfile.TemporaryDirectory() as temp:
            runtime=SimpleNamespace(ledger=SimpleNamespace(state_root=Path(temp)))
            # Default is bounded independently of checkout and state-root depth.
            with patch.dict(os.environ,{},clear=False):
                os.environ.pop('ONECREW_DELIVERY_ROOT',None)
                home=ds.home(runtime,'fixture-'+Path(temp).name)
            try:
                self.assertLessEqual(len(str(home)),28)
                src=Path(temp)/'s';src.mkdir()
                relative='app/'+('p'*30+'/')*5+'f.dart'
                path=src/relative;path.parent.mkdir(parents=True);path.write_text('data')
                manifest=ds.fingerprint(src,['app'])
                ds.capture(src,manifest,home/'baseline-0123456789',['app'])
                self.assertEqual((home/'baseline-0123456789'/relative).read_text(),'data')
            finally:
                self.assertEqual(home.parent,Path(Path(ds.__file__).resolve().anchor)/'ocd')
                shutil.rmtree(home)

    def test_deep_destination_fails_before_creating_partial_capture(self):
        if os.name!='nt':self.skipTest('Windows native path contract')
        with tempfile.TemporaryDirectory() as temp:
            src=Path(temp)/'src';src.mkdir();(src/'x').write_text('x')
            dest=Path(temp)/('a'*120)/('b'*120)
            with self.assertRaisesRegex(LedgerError,'Windows delivery path too long'):
                ds.capture(src,ds.fingerprint(src,['x']) if False else {'files':{'x':ds.file_hash(src/'x')}},dest,[])
            self.assertFalse(dest.exists())

    def test_scroll_avoids_ime_and_rejects_unknown_or_ambiguous_surface(self):
        tree='<hierarchy><node package="example.app" scrollable="true" bounds="[30,300][1050,1800]"/></hierarchy>'
        windows='Window #2 Window{xxx InputMethod}:\n mFrame=[0,1331][1080,2340]'
        coords=da.scroll_gesture(tree,'example.app',(1080,2340),windows,'mInputShown=true','up')
        self.assertLess(coords[1],1331);self.assertGreater(coords[3],300)
        self.assertGreater(coords[1],coords[3])
        with self.assertRaisesRegex(LedgerError,'keyboard bounds'):da.scroll_gesture(tree,'example.app',(1080,2340),'','mInputShown=true','up')
        with self.assertRaisesRegex(LedgerError,'unique'):da.scroll_gesture(tree.replace('</hierarchy>','<node package="example.app" scrollable="true" bounds="[0,0][500,500]"/></hierarchy>'),'example.app',(1080,2340),windows,'mInputShown=true','up')


    # Formats observed on a Samsung SM-A546E, Android 16 (2026-10-12).
    ANDROID16=('WINDOW MANAGER DISPLAY CONTENTS (dumpsys window displays)\nDisplay: mDisplayId=6\n  mCurrentFocus=null\n'
               'Display: mDisplayId=0 (organized)\n  mCurrentFocus=Window{333970 u0 example.app/example.app.MainActivity}\n'
               '  InsetsSource id=3 type=ime frame=[0,0][0,0] visibleFrame=[0,1332][1080,2340] visible=false flags=INVALID\n'
               'WINDOW MANAGER WINDOWS (dumpsys window windows)\n  Window #8 Window{2e0041 u0 InputMethod}:\n'
               '    Frames: parent=[0,95][1080,2340] display=[0,95][1080,2340] frame=[0,95][1080,2340]\n  mTopFocusedDisplayId=0\n')
    def test_android16_focus_is_read_from_top_display(self):
        self.assertTrue(da.app_has_focus(self.ANDROID16,'example.app'))
        self.assertFalse(da.app_has_focus(self.ANDROID16.replace('example.app/','other.app/'),'example.app'))
        self.assertIsNone(da.foreground_focus(self.ANDROID16.replace('mTopFocusedDisplayId=0','mTopFocusedDisplayId=6')))
        self.assertEqual(da.foreground_focus('mCurrentFocus=Window{1 u0 example.app/.Main}'),'Window{1 u0 example.app/.Main}')
        self.assertIsNone(da.foreground_focus('mCurrentFocus=Window{1 u0 a.app/.M}\nmCurrentFocus=Window{2 u0 b.app/.M}'))

    def test_keyboard_edge_ignores_stale_flags_and_full_screen_ime_window(self):
        hidden='mInputShown=false mIsInputViewShown=true'
        self.assertIsNone(da.keyboard_top(self.ANDROID16,hidden,2340))
        shown=self.ANDROID16.replace('frame=[0,0][0,0] visibleFrame=[0,1332][1080,2340] visible=false','frame=[0,1332][1080,2340] visibleFrame=[0,1332][1080,2340] visible=true')
        self.assertEqual(da.keyboard_top(shown,'mInputShown=true',2340),1332)
        with self.assertRaises(da.SwipeRefused):da.keyboard_top(self.ANDROID16,'mInputShown=true',2340)
        tree='<hierarchy><node package="example.app" scrollable="true" bounds="[30,300][1050,1800]"/></hierarchy>'
        coords=da.scroll_gesture(tree,'example.app',(1080,2340),shown,'mInputShown=true','up')
        self.assertLess(coords[1],1332);self.assertGreater(coords[3],300)
        status='<node package="com.android.systemui" bounds="[0,0][1080,95]"/>'
        self.assertEqual(da.scroll_gesture(tree.replace('</hierarchy>',status+'</hierarchy>'),'example.app',(1080,2340),self.ANDROID16,hidden,'up'),
                         da.scroll_gesture(tree,'example.app',(1080,2340),self.ANDROID16,hidden,'up'))


class DeviceRecoveryTests(unittest.TestCase):
    setUp=fixtures.AndroidDeliveryTests.setUp
    response=fixtures.AndroidDeliveryTests.response

    def focused(self,*args):
        if args[2][3:]==['shell','dumpsys','window']:return 0,RecoveryTests.ANDROID16,''
        return self.response(*args)

    def test_tap_allowed_when_android16_focus_is_the_app(self):
        value=json.loads(self.scenario.read_text());value['steps'][0]['operation']='tap'
        self.scenario.write_text(json.dumps(value));self.node['config']['scenario_sha256']=ds.file_hash(self.scenario)
        with patch('onecrew.delivery_android.bounded',side_effect=self.focused) as adb:
            result=da.device(self.runtime,'task',self.state,self.node,{'generation':0})
        self.assertTrue(result['passed'],result.get('detail'))
        self.assertEqual(sum(c.args[2][3:6]==['shell','input','tap'] for c in adb.call_args_list),1)

    def test_scroll_without_safe_surface_rereads_ui_without_input(self):
        value=json.loads(self.scenario.read_text())
        value['steps'][0].update(operation='scroll_to',arguments={'selector':{'text':'READY'},'direction':'up','max_swipes':2})
        self.scenario.write_text(json.dumps(value));self.node['config']['scenario_sha256']=ds.file_hash(self.scenario)
        dumps=0
        def response(*args):
            nonlocal dumps
            if args[2][3]=='exec-out':
                dumps+=1
                if dumps==1:return 0,'<?xml version="1.0"?><hierarchy><node text="BUSY" package="example.app" bounds="[0,0][10,10]"/></hierarchy>',''
            return self.focused(*args)
        with patch('onecrew.delivery_android.bounded',side_effect=response) as adb,patch('onecrew.delivery_android.time.sleep'):
            result=da.device(self.runtime,'task',self.state,self.node,{'generation':0})
        self.assertTrue(result['passed'],result.get('detail'))
        self.assertIn('refused',result['steps'][0]['gestures'][0])
        self.assertFalse(any(c.args[2][3:5]==['shell','input'] for c in adb.call_args_list))

    def test_wait_for_polls_without_input_and_records_receipt(self):
        value=json.loads(self.scenario.read_text());value['steps'][0].update(operation='wait_for',arguments={'selector':{'text':'READY'},'timeout_seconds':2})
        self.scenario.write_text(json.dumps(value));self.node['config']['scenario_sha256']=ds.file_hash(self.scenario)
        count=0
        def response(*args):
            nonlocal count
            if args[2][3]=='exec-out':
                count+=1
                if count==1:return 0,'<?xml version="1.0"?><hierarchy/>',''
            return self.response(*args)
        with patch('onecrew.delivery_android.bounded',side_effect=response) as adb,patch('onecrew.delivery_android.time.sleep'):
            result=da.device(self.runtime,'task',self.state,self.node,{'generation':0})
        self.assertTrue(result['passed']);self.assertEqual(result['steps'][0]['polls'],2)
        self.assertEqual(result['steps'][0]['hierarchy_unavailable'],1)
        self.assertFalse(any('input' in c.args[2] for c in adb.call_args_list))

    def test_wait_for_adb_failure_is_not_retried_as_missing_ui(self):
        value=json.loads(self.scenario.read_text());value['steps'][0].update(operation='wait_for',arguments={'selector':{'text':'READY'},'timeout_seconds':5})
        self.scenario.write_text(json.dumps(value));self.node['config']['scenario_sha256']=ds.file_hash(self.scenario)
        dumps=0
        def response(*args):
            nonlocal dumps
            if args[2][3]=='exec-out':
                dumps+=1
                return 1,'','device offline'
            return self.response(*args)
        with patch('onecrew.delivery_android.bounded',side_effect=response),patch('onecrew.delivery_android.time.sleep'):
            result=da.device(self.runtime,'task',self.state,self.node,{'generation':0})
        self.assertFalse(result['passed']);self.assertIn('ADB operation failed',result['detail'])
        self.assertEqual(dumps,1)

    def test_wait_timeout_does_not_swipe_or_repeat_install(self):
        value=json.loads(self.scenario.read_text());value['steps'][0].update(operation='wait_for',arguments={'selector':{'text':'NEVER'},'timeout_seconds':1})
        self.scenario.write_text(json.dumps(value));self.node['config']['scenario_sha256']=ds.file_hash(self.scenario)
        now=[0]
        def sleep(seconds):now[0]+=seconds
        with patch('onecrew.delivery_android.bounded',side_effect=self.response) as adb,patch('onecrew.delivery_android.time.sleep',side_effect=sleep),patch('onecrew.delivery_android.time.monotonic',side_effect=lambda:now[0]):
            result=da.device(self.runtime,'task',self.state,self.node,{'generation':0})
        self.assertFalse(result['passed']);self.assertIn('timeout',result['detail'])
        self.assertFalse(any('input' in c.args[2] for c in adb.call_args_list))
        self.assertEqual(sum(c.args[2][3]=='install' for c in adb.call_args_list),1)

    def test_wait_validation_rejects_unbounded_duration(self):
        value=json.loads(self.scenario.read_text())
        for seconds in (0,61,True,1.5):
            value['steps'][0].update(operation='wait_for',arguments={'selector':{'text':'READY'},'timeout_seconds':seconds})
            self.scenario.write_text(json.dumps(value))
            with self.assertRaises(LedgerError):da.scenario(self.scenario,ds.file_hash(self.scenario))

if __name__=='__main__':unittest.main()
