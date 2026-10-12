"""Behavioural regressions for the two Codex review findings on 356fb82 (2026-10-12).

P1: a target covered by a visible keyboard counted as reached and was then tapped through the IME.
P2: every `path:` line in pubspec files was rewritten, corrupting hosted and git dependencies.
Both are asserted through public entry points that exist on 356fb82, so the old revision fails by
behaviour, not by a missing API."""
import json
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch

from onecrew import delivery_android as da
from onecrew import delivery_steps as ds
from tests import test_delivery_android as fixtures

HEIGHT=2340
KEYBOARD_TOP=1332
# Samsung SM-A546E Android 16 layout with the numeric keyboard shown.
WINDOWS=('Display: mDisplayId=0 (organized)\n  mCurrentFocus=Window{333970 u0 example.app/example.app.MainActivity}\n'
         '  InsetsSource id=3 type=ime frame=[0,1332][1080,2340] visibleFrame=[0,1332][1080,2340] visible=true\n'
         'WINDOW MANAGER WINDOWS\n  mTopFocusedDisplayId=0\n')
HIDDEN=WINDOWS.replace('visible=true','visible=false')


def tree(save_top):
    return ('<?xml version="1.0"?><hierarchy>'
            '<node package="example.app" class="android.widget.ScrollView" scrollable="true" enabled="true" bounds="[0,200][1080,2200]">'
            '<node text="FIELD" package="example.app" class="android.widget.EditText" enabled="true" bounds="[40,400][1040,500]"/>'
            f'<node text="SAVE" package="example.app" class="android.widget.Button" enabled="true" bounds="[100,{save_top}][300,{save_top+50}]"/>'
            '</node></hierarchy>')


class KeyboardCoverTests(unittest.TestCase):
    setUp=fixtures.AndroidDeliveryTests.setUp
    response=fixtures.AndroidDeliveryTests.response

    def steps(self,*steps):
        value=json.loads(self.scenario.read_text());value['steps']=list(steps)
        self.scenario.write_text(json.dumps(value));self.node['config']['scenario_sha256']=ds.file_hash(self.scenario)

    def run_device(self,windows,positions,input_method='mInputShown=true'):
        """positions: SAVE top edge before each swipe; the last value persists."""
        swipes=[0]
        def response(runtime,task,argv,cwd,seconds):
            args=argv[3:]
            if args==['shell','wm','size']:return 0,'Physical size: 1080x2340',''
            if args==['shell','dumpsys','window']:return 0,windows,''
            if args==['shell','dumpsys','input_method']:return 0,input_method,''
            if args[0]=='exec-out':return 0,tree(positions[min(swipes[0],len(positions)-1)]),''
            if args[:3]==['shell','input','swipe']:swipes[0]+=1
            return self.response(runtime,task,argv,cwd,seconds)
        with patch('onecrew.delivery_android.bounded',side_effect=response) as adb,patch('onecrew.delivery_android.time.sleep'):
            result=da.device(self.runtime,'task',self.state,self.node,{'generation':0})
        taps=[tuple(map(int,c.args[2][6:8])) for c in adb.call_args_list if c.args[2][3:6]==['shell','input','tap']]
        return result,taps,swipes[0]

    def test_target_under_keyboard_is_scrolled_clear_before_tap(self):
        self.steps({'id':'reach','operation':'scroll_to','arguments':{'selector':{'text':'SAVE'},'direction':'up','max_swipes':3}},
                   {'id':'save','operation':'tap','arguments':{'selector':{'text':'SAVE'}}})
        result,taps,swipes=self.run_device(WINDOWS,[1450,1000])
        self.assertTrue(all(y<KEYBOARD_TOP for _,y in taps),taps)
        self.assertTrue(result['passed'],result.get('detail'))
        self.assertEqual(swipes,1);self.assertEqual(taps,[(200,1025)])
        self.assertEqual(len([g for g in result['steps'][0]['gestures'] if 'coordinates' in g]),1)

    def test_target_that_stays_under_keyboard_fails_without_any_tap(self):
        self.steps({'id':'reach','operation':'scroll_to','arguments':{'selector':{'text':'SAVE'},'direction':'up','max_swipes':2}},
                   {'id':'save','operation':'tap','arguments':{'selector':{'text':'SAVE'}}})
        result,taps,_=self.run_device(WINDOWS,[1450])
        self.assertFalse(result['passed']);self.assertEqual(taps,[])
        self.assertEqual([s['id'] for s in result['steps']],[])

    def test_direct_tap_on_covered_target_is_refused(self):
        self.steps({'id':'save','operation':'tap','arguments':{'selector':{'text':'SAVE'}}})
        result,taps,_=self.run_device(WINDOWS,[1450])
        self.assertFalse(result['passed']);self.assertEqual(taps,[])

    def test_unknown_keyboard_bounds_refuse_tap(self):
        self.steps({'id':'save','operation':'tap','arguments':{'selector':{'text':'SAVE'}}})
        unknown=HIDDEN  # insets say hidden, but the input method reports the keyboard shown without bounds
        result,taps,_=self.run_device(unknown,[1450])
        self.assertFalse(result['passed']);self.assertEqual(taps,[])

    def test_hidden_keyboard_keeps_full_screen_reachable(self):
        self.steps({'id':'save','operation':'tap','arguments':{'selector':{'text':'SAVE'}}})
        result,taps,_=self.run_device(HIDDEN,[1450],input_method='mInputShown=false')
        self.assertTrue(result['passed'],result.get('detail'));self.assertEqual(taps,[(200,1475)])


PUBSPEC=('name: app\n'
         'dependencies:\n'
         '  flutter:\n'
         '    sdk: flutter\n'
         '  path: ^1.9.0\n'
         '  plugin:\n'
         '    path: ../base/packages/plugin\n'
         '  gitdep:\n'
         '    git:\n'
         '      url: https://example.invalid/repo.git\n'
         '      path: packages/plugin\n'
         'dev_dependencies:\n'
         '  path_provider: ^2.1.0\n'
         'flutter:\n'
         '  uses-material-design: true\n')


class PubspecRebaseTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        root=Path(self.temp.name);self.src=root/'source';self.out=root/'capture';self.red=root/'red'
        (self.src/'app').mkdir(parents=True);(self.src/'base/packages/plugin').mkdir(parents=True)
        (self.src/'base/packages/plugin/lib.dart').write_text('plugin')
        (self.src/'app/pubspec.yaml').write_text(PUBSPEC)
        self.plugin=self.src/'base/packages/plugin'
        (self.src/'app/pubspec_overrides.yaml').write_text('dependency_overrides:\n  plugin:\n    path: '+json.dumps(self.plugin.as_posix())+'\n')

    def lines(self,path):
        return path.read_text(encoding='utf-8').splitlines()

    def test_only_local_path_sources_move_through_capture_and_red(self):
        manifest=ds.fingerprint(self.src,['app','base'])
        ds.capture(self.src,manifest,self.out,['app','base'])
        lines=self.lines(self.out/'app/pubspec.yaml')
        self.assertIn('  path: ^1.9.0',lines)
        self.assertIn('      path: packages/plugin',lines)
        self.assertIn('  path_provider: ^2.1.0',lines)
        self.assertIn('    sdk: flutter',lines)
        local=[l for l in lines if l.startswith('    path: ')]
        self.assertEqual(len(local),1);self.assertIn((self.out/'base/packages/plugin').as_posix(),local[0])
        override=self.lines(self.out/'app/pubspec_overrides.yaml')
        self.assertIn((self.out/'base/packages/plugin').as_posix(),override[2])
        # Source is never rewritten.
        self.assertEqual((self.src/'app/pubspec.yaml').read_text(),PUBSPEC)
        shutil.copytree(self.out,self.red);ds.rebase_packages(self.out,self.red,['app','base'])
        red=self.lines(self.red/'app/pubspec.yaml')
        self.assertIn('  path: ^1.9.0',red);self.assertIn('      path: packages/plugin',red)
        self.assertIn((self.red/'base/packages/plugin').as_posix(),[l for l in red if l.startswith('    path: ')][0])

    def test_text_outside_dependency_sections_is_untouched(self):
        text=PUBSPEC+'flutter_launcher_icons:\n  image:\n    path: assets/icon.png\n'
        (self.src/'app/pubspec.yaml').write_text(text)
        manifest=ds.fingerprint(self.src,['app','base'])
        ds.capture(self.src,manifest,self.out,['app','base'])
        self.assertIn('    path: assets/icon.png',self.lines(self.out/'app/pubspec.yaml'))


if __name__=='__main__':unittest.main()
