import json
import os
from pathlib import Path
import struct
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import zipfile

from onecrew.delivery_android import audit,device,elf_alignment,find_ui,scenario
from onecrew.delivery_steps import file_hash
from onecrew.ledger import LedgerError
from onecrew.sandbox_gate import GateUnavailable


class AndroidDeliveryTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.apk=self.root/'app.apk'
        with zipfile.ZipFile(self.apk,'w') as z:z.writestr('AndroidManifest.xml',b'fixture');z.writestr('classes.dex',b'fixture')
        self.digest=file_hash(self.apk)
        self.runtime=SimpleNamespace(ledger=SimpleNamespace(state_root=self.root/'state'))
        self.state={'delivery':{'source':{'hash':'source'},'nodes':{'build':{'receipt':{
            'passed':True,'apk':str(self.apk),'sha256':self.digest,'source':'source'}}}}}
        self.xml='<?xml version="1.0"?><hierarchy><node text="READY" package="example.app" class="android.widget.TextView" enabled="true" focused="true" bounds="[0,0][100,100]"/></hierarchy>'
        self.scenario=self.root/'scenario.json'
        self.scenario.write_text(json.dumps({'version':1,'activity':'.MainActivity',
            'steps':[{'id':'ready','operation':'assert_ui','arguments':{'selector':{'text':'READY'}}}],
            'cleanup':[{'id':'restore','operation':'restart','arguments':{}}]}))
        self.node={'id':'device','config':{'build_node':'build','adb':str(self.root/'adb.exe'),'serial':'PINNED',
            'package_id':'example.app','scenario':str(self.scenario),'scenario_sha256':file_hash(self.scenario),
            'private_reference':None,'private_version':'none','timeout_seconds':60}}
        self.home=patch('onecrew.delivery_android.home',return_value=self.root);self.home.start();self.addCleanup(self.home.stop)

    def response(self,runtime,task,argv,cwd,seconds):
        self.assertEqual(argv[1:3],['-s','PINNED'])
        args=argv[3:]
        if args==['get-state']:return 0,'device',''
        if args==['shell','wm','size']:return 0,'Physical size: 1080x1920',''
        if args[0]=='install':return 0,'Success',''
        if args[:3]==['shell','pm','path']:return 0,'package:/data/app/base.apk',''
        if args[:2]==['shell','sha256sum']:return 0,self.digest+' /data/app/base.apk',''
        if args[0]=='exec-out':return 0,self.xml,''
        return 0,'',''

    def test_pinned_install_assert_and_cleanup_receipt(self):
        with patch('onecrew.delivery_android.bounded',side_effect=self.response) as adb:
            result=device(self.runtime,'task',self.state,self.node,{'generation':0})
        self.assertTrue(result['passed']);self.assertEqual(result['installed_sha256'],self.digest)
        self.assertTrue(result['cleanup'][0]['passed']);self.assertTrue(result['live_device'])
        self.assertEqual(sum(c.args[2][3]=='install' for c in adb.call_args_list),1)

    def test_apk_drift_prevents_install(self):
        self.apk.write_bytes(b'changed')
        with patch('onecrew.delivery_android.bounded') as adb:
            with self.assertRaisesRegex(LedgerError,'APK changed'):device(self.runtime,'task',self.state,self.node,{'generation':0})
            adb.assert_not_called()

    def test_install_timeout_uncertain_no_second_install(self):
        def response(*args):
            if args[2][3]=='install':raise GateUnavailable('Native command deadline exceeded.')
            return self.response(*args)
        with patch('onecrew.delivery_android.bounded',side_effect=response) as adb:
            result=device(self.runtime,'task',self.state,self.node,{'generation':0})
        self.assertFalse(result['passed']);self.assertTrue(result['uncertain'])
        self.assertEqual(sum(c.args[2][3]=='install' for c in adb.call_args_list),1)

    def test_different_installed_hash_blocks_e2e(self):
        def response(*args):
            if args[2][3:5]==['shell','sha256sum']:return 0,'bad /data/app/base.apk',''
            return self.response(*args)
        with patch('onecrew.delivery_android.bounded',side_effect=response):result=device(self.runtime,'task',self.state,self.node,{'generation':0})
        self.assertFalse(result['passed']);self.assertEqual(result['steps'],[])

    def test_selector_cannot_touch_other_app_or_ambiguous_node(self):
        with self.assertRaises(LedgerError):find_ui(self.xml,{'text':'READY'},'other.app')
        with self.assertRaises(LedgerError):find_ui(self.xml,{'text':'READY'},'example.app',(50,50))
        with self.assertRaises(LedgerError):find_ui(self.xml.replace('</hierarchy>','<node text="READY"/></hierarchy>'),{'text':'READY'})

    def test_overlay_window_prevents_tap_even_with_background_app_node(self):
        v=json.loads(self.scenario.read_text());v['steps'][0]['operation']='tap'
        self.scenario.write_text(json.dumps(v));self.node['config']['scenario_sha256']=file_hash(self.scenario)
        def response(*args):
            if args[2][3:]==['shell','dumpsys','window']:
                return 0,('Display: mDisplayId=6\n  mCurrentFocus=null\nDisplay: mDisplayId=0 (organized)\n'
                          '  mCurrentFocus=Window{123 u0 other.app/.Main}\nWINDOW MANAGER WINDOWS\n  mTopFocusedDisplayId=0\n'),''
            return self.response(*args)
        with patch('onecrew.delivery_android.bounded',side_effect=response) as adb:
            result=device(self.runtime,'task',self.state,self.node,{'generation':0})
        self.assertFalse(result['passed']);self.assertFalse(any('input' in c.args[2] for c in adb.call_args_list))

    def test_scenario_shell_and_activity_injection_rejected(self):
        for value in ({'version':1,'activity':'example.other/.Main','steps':[],'cleanup':[]},
                      {'version':1,'activity':'.Main','steps':[{'id':'x','operation':'shell','arguments':{'command':'wipe'}}],'cleanup':[]}):
            self.scenario.write_text(json.dumps(value))
            with self.assertRaises(LedgerError):scenario(self.scenario,file_hash(self.scenario))

    def test_scenario_replacement_rejected(self):
        digest=file_hash(self.scenario);self.scenario.write_text('{}')
        with self.assertRaisesRegex(LedgerError,'changed'):scenario(self.scenario,digest)

    def test_elf_16kb_alignment_gate(self):
        data=bytearray(120);data[:6]=b'\x7fELF\x02\x01'
        struct.pack_into('<Q',data,32,64);struct.pack_into('<HH',data,54,56,1)
        struct.pack_into('<I',data,64,1);struct.pack_into('<Q',data,112,16384)
        self.assertTrue(elf_alignment(data)['aligned_16kb'])
        struct.pack_into('<Q',data,112,4096)
        self.assertFalse(elf_alignment(data)['aligned_16kb'])

    def test_wrong_signer_and_oversized_or_duplicate_zip_fail_audit(self):
        node={'config':{'build_node':'build','build_tools':str(self.root),'package_id':'example.app',
            'signer_sha256':'a'*64,'require_16kb':True,'max_bytes':10000}}
        def response(runtime,task,argv,cwd,seconds):
            if '-jar' in argv:return 0,'Signer #1 certificate SHA-256 digest: '+'a'*64,''
            if 'badging' in argv:return 0,"package: name='example.app'",''
            return 0,'',''
        with patch('onecrew.delivery_android.shutil.which',return_value='java'),patch('onecrew.delivery_android.bounded',side_effect=response):
            self.assertTrue(audit(self.runtime,'task',self.state,node)['passed'])
            node['config']['signer_sha256']='b'*64
            self.assertFalse(audit(self.runtime,'task',self.state,node)['passed'])
            node['config']['signer_sha256']='a'*64;node['config']['max_bytes']=1
            self.assertFalse(audit(self.runtime,'task',self.state,node)['passed'])


if __name__=='__main__':unittest.main()
