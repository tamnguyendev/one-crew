import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from onecrew import delivery_env
from onecrew.delivery_env import EXE,debug_signer_sha256,discover,fingerprint,properties,signer_sha256,tests_for
from onecrew.ledger import LedgerError


GRADLE='''android {
    namespace "com.example.ns"
    // applicationId "com.example.commented"
    defaultConfig {
        applicationIdSuffix ".dev"
        applicationId "com.example.groovy"
    }
    buildTypes {
        debug { applicationIdSuffix ".debug" }
    }
}
'''
FLAVORS_FIRST='''android {
    namespace 'com.base'
    productFlavors {
        free { applicationId "com.flavor.free" }
    }
    defaultConfig {
        applicationId "com.base.prod"
        applicationIdSuffix "dev"
    }
    buildTypes {
        release { minifyEnabled false }
        debug {
            applicationIdSuffix '.debug'
            signingConfig signingConfigs.debug
        }
    }
}
'''
FLAVOR_AFTER='''android {
    namespace = "com.k"
    defaultConfig { minSdk = 21 }
    productFlavors { create("paid") { applicationId = "com.flavor.paid" } }
    buildTypes { getByName("debug") { applicationIdSuffix = ".d" } }
}
'''
KTS='''android {
    namespace = "com.example.kns"
    defaultConfig {
        /* applicationId = "com.example.block" */
        applicationId = "com.example.kts"
    }
}
'''
MANIFEST='''<manifest xmlns:android="http://schemas.android.com/apk/res/android">
  <application>
    <activity android:name=".SettingsActivity"><intent-filter><action android:name="android.intent.action.VIEW"/></intent-filter></activity>
    <activity android:name=".Disabled" android:enabled="false"><intent-filter>
      <action android:name="android.intent.action.MAIN"/><category android:name="android.intent.category.LAUNCHER"/></intent-filter></activity>
    <activity android:name=".MainActivity" android:exported="true"><intent-filter>
      <action android:name="android.intent.action.MAIN"/><category android:name="android.intent.category.LAUNCHER"/></intent-filter></activity>
  </application>
</manifest>
'''
PUBSPEC='''name: app # the app
description: fixture
version: "1.2.3+45"
environment:
  sdk: ">=3.0.0 <4.0.0"
  flutter: ">=3.10.0"
dependencies:
  flutter:
    sdk: flutter
  http: ^1.0.0
'''
KEYTOOL='''Alias name: androiddebugkey
Certificate fingerprints:
	 SHA1: 11:22:33:44:55:66:77:88:99:00:AA:BB:CC:DD:EE:FF:11:22:33:44
	 SHA256: AB:CD:EF:01:23:45:67:89:AB:CD:EF:01:23:45:67:89:AB:CD:EF:01:23:45:67:89:AB:CD:EF:01:23:45:67:89
Signature algorithm name: SHA256withRSA
'''


def launcher(name,package=''):
    return ('<manifest xmlns:android="http://schemas.android.com/apk/res/android"'+(f' package="{package}"' if package else '')+'><application>'
            f'<activity android:name="{name}"><intent-filter><action android:name="android.intent.action.MAIN"/>'
            '<category android:name="android.intent.category.LAUNCHER"/></intent-filter></activity></application></manifest>')


def touch(path,data=b'x'):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(data if isinstance(data,bytes) else data.encode())
    path.chmod(0o755);return path  # PATH lookups need the executable bit on POSIX


def escape(path):
    return str(path).replace('\\','\\\\').replace(':','\\:')


class EnvironmentDiscoveryTests(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup)
        self.root=Path(temp.name).resolve();self.project=self.root/'project';self.home=self.root/'home'
        self.app=self.project/'app';self.home.mkdir()
        touch(self.app/'pubspec.yaml',PUBSPEC);touch(self.app/'.dart_tool/package_config.json','{}')
        touch(self.app/'android/app/build.gradle',GRADLE);touch(self.app/'android/app/src/main/AndroidManifest.xml',MANIFEST)
        for test in ('test/b_test.dart','test/a/a_test.dart','test/helper.dart','test/build/skip_test.dart','test/.dart_tool/skip_test.dart'):
            touch(self.app/test,'void main() {}')

    def env(self,**values):
        base={'PATH':str(self.root/'empty-path'),'PATHEXT':'.EXE;.BAT','USERPROFILE':str(self.home),'HOME':str(self.home),
              'LOCALAPPDATA':str(self.root/'localappdata'),'PROGRAMFILES':str(self.root/'programfiles')}
        base.update({k:str(v) for k,v in values.items()});return base

    def flutter(self,name,snapshot=True):
        root=self.root/name;touch(root/'bin/cache/dart-sdk/bin'/('dart'+EXE));touch(root/'bin/flutter');touch(root/'bin/flutter.bat')
        touch(root/'packages/flutter_tools/.dart_tool/package_config.json','{}')
        if snapshot: touch(root/'bin/cache/flutter_tools.snapshot')
        return root

    def sdk(self,root,versions={'35.0.0':()},adb=True):
        root=Path(root);(root/'platform-tools').mkdir(parents=True,exist_ok=True)
        if adb: touch(root/'platform-tools'/('adb'+EXE))
        for version,missing in versions.items():
            for name in delivery_env.BUILD_TOOLS:
                if name not in missing: touch(root/'build-tools'/version/name)
        return root

    def codes(self,info): return [p['code'] for p in info['problems']]

    def test_flutter_root_precedence_and_rejections(self):
        env_root=self.flutter('env-flutter');local_root=self.flutter('local-flutter');path_root=self.flutter('path-flutter')
        touch(self.app/'android/local.properties','flutter.sdk='+escape(local_root)+'\n')
        info=discover(self.project,['app'],self.env(FLUTTER_ROOT=env_root,PATH=path_root/'bin'))
        self.assertEqual((info['flutter_root'],info['flutter_source']),(str(env_root),'FLUTTER_ROOT'))
        broken=self.flutter('broken-flutter',snapshot=False)
        info=discover(self.project,['app'],self.env(FLUTTER_ROOT=broken,PATH=path_root/'bin'))
        self.assertEqual((info['flutter_root'],info['flutter_source']),(str(local_root),'local.properties:app'))
        (self.app/'android/local.properties').unlink()
        # A complete SDK reachable only through a relative PATH entry (resolved against the cwd) must be ignored.
        self.flutter('cwd/relative');previous=os.getcwd();os.chdir(self.root/'cwd');self.addCleanup(os.chdir,previous)
        info=discover(self.project,['app'],self.env(FLUTTER_ROOT=broken,PATH=os.pathsep.join(['relative/bin',str(path_root/'bin')])))
        self.assertEqual((info['flutter_root'],info['flutter_source']),(str(path_root),'PATH'))
        self.assertNotIn('flutter_root_missing',self.codes(info))
        info=discover(self.project,['app'],self.env(FLUTTER_ROOT=broken))
        problem=next(p for p in info['problems'] if p['code']=='flutter_root_missing')
        self.assertIsNone(info['flutter_root']);self.assertIn('FLUTTER_ROOT=',problem['detail']);self.assertIn('flutter_tools.snapshot',problem['detail'])
        # dart_argv passes packages/flutter_tools/.dart_tool/package_config.json too, so a root without it is rejected.
        unpacked=self.flutter('unpacked-flutter');(unpacked/'packages/flutter_tools/.dart_tool/package_config.json').unlink()
        info=discover(self.project,['app'],self.env(FLUTTER_ROOT=unpacked,PATH=path_root/'bin'))
        self.assertEqual((info['flutter_root'],info['flutter_source']),(str(path_root),'PATH'))
        info=discover(self.project,['app'],self.env(FLUTTER_ROOT=unpacked))
        problem=next(p for p in info['problems'] if p['code']=='flutter_root_missing')
        self.assertIsNone(info['flutter_root']);self.assertIn('packages/flutter_tools/.dart_tool/package_config.json',problem['detail'])

    def test_gradle_properties_unescape_like_java(self):
        path=touch(self.root/'local.properties','# comment \\\n! bang\nsdk.dir=C\\:\\\\Users\\\\me\\\\Sdk\nflutter.sdk = /opt/\\\n    flutter\n'
                   'key\\:with\\=sep:value\\u0041\\t|\nspaced   plain value\ndup=1\ndup=2\nescaped=a\\\\\nlast=x\\')
        self.assertEqual(properties(path),{'sdk.dir':'C:\\Users\\me\\Sdk','flutter.sdk':'/opt/flutter','key:with=sep':'valueA\t|',
                                           'spaced':'plain value','dup':'2','escaped':'a\\','last':'x'})
        self.assertEqual(properties(self.root/'missing.properties'),{})
        sdk=self.sdk(self.root/'local sdk');flutter=self.flutter('spaced flutter')
        touch(self.app/'android/local.properties','sdk.dir='+escape(sdk)+'\nflutter.sdk='+escape(flutter)+'\n')
        info=discover(self.project,['app'],self.env())
        self.assertEqual((info['android_sdk'],info['android_sdk_source']),(str(sdk),'local.properties:app'))
        self.assertEqual(info['flutter_root'],str(flutter))

    def test_android_sdk_precedence(self):
        default=self.root/'localappdata/Android/Sdk' if os.name=='nt' else self.home/'Android/Sdk'
        home=self.sdk(self.root/'home-sdk');root=self.sdk(self.root/'root-sdk');local=self.sdk(self.root/'local-sdk');self.sdk(default)
        empty=self.root/'empty-sdk';empty.mkdir()
        touch(self.app/'android/local.properties','sdk.dir='+escape(local)+'\n')
        info=discover(self.project,['app'],self.env(ANDROID_HOME=home,ANDROID_SDK_ROOT=root))
        self.assertEqual((info['android_sdk'],info['android_sdk_source']),(str(home),'ANDROID_HOME'))
        info=discover(self.project,['app'],self.env(ANDROID_HOME=empty,ANDROID_SDK_ROOT=root))
        self.assertEqual((info['android_sdk'],info['android_sdk_source']),(str(root),'ANDROID_SDK_ROOT'))
        info=discover(self.project,['app'],self.env(ANDROID_HOME=empty))
        self.assertEqual((info['android_sdk'],info['android_sdk_source']),(str(local),'local.properties:app'))
        (self.app/'android/local.properties').unlink()
        info=discover(self.project,['app'],self.env())
        self.assertEqual((info['android_sdk'],info['android_sdk_source']),(str(default),'default'))
        self.assertEqual(info['adb'],str(default/'platform-tools'/('adb'+EXE)))

    def test_build_tools_selection(self):
        sdk=self.sdk(self.root/'sdk',{'34.0.0':(),'36.0.0':('aapt2'+EXE,),'35.0.0':(),'36.1.0-rc1':('lib/apksigner.jar',)})
        info=discover(self.project,['app'],self.env(ANDROID_HOME=sdk))
        self.assertEqual((info['build_tools'],info['build_tools_version'],info['zipalign_16kb']),(str(sdk/'build-tools/35.0.0'),'35.0.0',True))
        self.assertNotIn('build_tools_missing',self.codes(info))
        self.sdk(sdk,{'36.0.0':(),'36.0.0-rc1':()})
        self.assertEqual(discover(self.project,['app'],self.env(ANDROID_HOME=sdk))['build_tools_version'],'36.0.0')
        older=self.sdk(self.root/'older',{'34.0.0':(),'36.0.0':('zipalign'+EXE,)})
        info=discover(self.project,['app'],self.env(ANDROID_HOME=older))
        self.assertEqual((info['build_tools_version'],info['zipalign_16kb']),('34.0.0',False))
        broken=self.sdk(self.root/'broken',{'36.0.0':('aapt2'+EXE,)},adb=False)
        info=discover(self.project,['app'],self.env(ANDROID_HOME=broken))
        problem=next(p for p in info['problems'] if p['code']=='build_tools_missing')
        self.assertIsNone(info['build_tools']);self.assertFalse(info['zipalign_16kb']);self.assertIn('36.0.0 (missing aapt2'+EXE+')',problem['detail'])
        self.assertIn('adb_missing',self.codes(info));self.assertIsNone(info['adb'])
        # zipalign -P first shipped in 35.0.0-rc3.
        for version,ok in (('34.0.0',False),('35.0.0-rc1',False),('35.0.0-rc2',False),('35.0.0-rc3',True),('35.0.0',True),
                           ('35.0.1',True),('36.0.0-rc1',True),(None,False)):
            self.assertEqual(delivery_env.zipalign_16kb(version),ok,version)
        rc=self.sdk(self.root/'rc',{'34.0.0':(),'35.0.0-rc2':()})
        info=discover(self.project,['app'],self.env(ANDROID_HOME=rc))
        self.assertEqual((info['build_tools_version'],info['zipalign_16kb']),('35.0.0-rc2',False))

    def test_package_metadata(self):
        touch(self.project/'packages/core/pubspec.yaml','name: core\nversion: 2.0.0\n')
        touch(self.project/'packages/group/deep/nested/pubspec.yaml','name: too_deep\n')
        touch(self.project/'packages/.hidden/pubspec.yaml','name: hidden\n')
        kts=self.project/'packages/kts';touch(kts/'pubspec.yaml','name: kts\nflutter:\n  uses-material-design: true\n')
        touch(kts/'android/app/build.gradle.kts',KTS);touch(kts/'android/app/src/main/AndroidManifest.xml','<manifest')
        ns=self.project/'packages/ns';touch(ns/'pubspec.yaml','name: ns\ndependencies:\n  flutter: {sdk: flutter}\n')
        touch(ns/'android/app/build.gradle','android {\n  namespace = "com.example.only"\n  defaultConfig { applicationId = flutter.applicationId }\n}\n')
        info=discover(self.project,['app','packages','app'],self.env())
        packages={p['root']:p for p in info['packages']}
        self.assertEqual(list(packages),['app','packages/core','packages/kts','packages/ns'])
        self.assertEqual(packages['app'],{'root':'app','name':'app','flutter':True,'dependency_ready':True,'application_id':'com.example.groovy',
            'namespace':'com.example.ns','application_ids':{'debug':'com.example.groovy.dev.debug','release':'com.example.groovy.dev'},
            'version_name':'1.2.3','version_code':'45','launch_activity':'.MainActivity','launch_activity_class':'com.example.ns.MainActivity',
            'tests':['test/a/a_test.dart','test/b_test.dart']})
        core=packages['packages/core']
        self.assertEqual((core['flutter'],core['version_name'],core['version_code']),(False,'2.0.0',None))
        self.assertEqual((core['application_id'],core['namespace'],core['application_ids'],core['launch_activity_class']),(None,None,{'debug':None,'release':None},None))
        self.assertEqual((packages['packages/kts']['application_id'],packages['packages/kts']['flutter']),('com.example.kts',True))
        self.assertEqual(packages['packages/kts']['application_ids'],{'debug':'com.example.kts','release':'com.example.kts'})
        self.assertIsNone(packages['packages/kts']['launch_activity']);self.assertIsNone(packages['packages/kts']['launch_activity_class'])
        self.assertEqual((packages['packages/ns']['application_id'],packages['packages/ns']['flutter']),('com.example.only',True))
        # applicationId is an expression: the declared fallback stays, but no effective id is claimed.
        self.assertEqual(packages['packages/ns']['application_ids'],{'debug':None,'release':None})
        codes=self.codes(info)
        self.assertIn('manifest_unreadable:packages/kts',codes)
        self.assertEqual([c for c in codes if c.startswith('dependency_graph_missing:')],
                         ['dependency_graph_missing:packages/core','dependency_graph_missing:packages/kts','dependency_graph_missing:packages/ns'])
        whole=discover(self.project,['.'],self.env())
        self.assertEqual([p['root'] for p in whole['packages']],['app','packages/core','packages/kts','packages/ns'])

    def test_effective_application_ids_and_launch_class(self):
        pkg=self.root/'pkg'
        def facts(gradle,manifest=MANIFEST,name='build.gradle'):
            shutil.rmtree(pkg,ignore_errors=True);touch(pkg/'pubspec.yaml','name: pkg\n');touch(pkg/'android/app/src/main/AndroidManifest.xml',manifest)
            if gradle is not None: touch(pkg/'android/app'/name,gradle)
            problems=[];p=delivery_env.package('pkg',pkg,problems);self.assertEqual(problems,[])
            return p['application_id'],p['namespace'],p['application_ids'],p['launch_activity_class']
        # AGP: defaultConfig id + defaultConfig suffix + buildType suffix, '.' added when missing; flavors declared first do not win.
        self.assertEqual(facts(FLAVORS_FIRST),('com.base.prod','com.base',{'debug':'com.base.prod.dev.debug','release':'com.base.prod.dev'},'com.base.MainActivity'))
        # No applicationId in defaultConfig: the namespace, never a flavor's applicationId declared later.
        self.assertEqual(facts(FLAVOR_AFTER,name='build.gradle.kts'),('com.k','com.k',{'debug':'com.k.d','release':'com.k'},'com.k.MainActivity'))
        self.assertEqual(facts('android {\n  namespace = "com.e"\n  defaultConfig { applicationId = "com.e.app" }\n'
                               '  buildTypes { debug { applicationIdSuffix = suffixFromProps } }\n}\n',launcher('com.other.Launch')),
                         ('com.e.app','com.e',{'debug':None,'release':'com.e.app'},'com.other.Launch'))
        # Pre-namespace projects: the manifest package is the namespace; a dotless activity name is relative to it.
        self.assertEqual(facts('android { defaultConfig { minSdkVersion 21 } }',launcher('MainActivity','com.legacy')),
                         ('com.legacy','com.legacy',{'debug':'com.legacy','release':'com.legacy'},'com.legacy.MainActivity'))
        self.assertEqual(facts('android { }',launcher('.Main')),(None,None,{'debug':None,'release':None},None))
        # A computed namespace is unknown; the manifest package is not a substitute for it.
        self.assertEqual(facts('android { namespace = libs.ns\n defaultConfig { applicationId = "com.x" } }',launcher('.Main','com.stale')),
                         ('com.x',None,{'debug':'com.x','release':'com.x'},None))
        self.assertEqual(facts(None,launcher('.Main','com.nobuild')),(None,'com.nobuild',{'debug':None,'release':None},'com.nobuild.Main'))

    def test_missing_tools_are_reported_not_raised(self):
        empty=self.root/'empty';empty.mkdir()
        with patch('onecrew.delivery_env._studio_jbr',return_value=[]): info=discover(empty,['missing'],self.env())
        for key in ('flutter_root','android_sdk','build_tools','adb','java','java_home'): self.assertIsNone(info[key])
        self.assertEqual(self.codes(info),['root_missing:missing','flutter_root_missing','android_sdk_missing','build_tools_missing',
                                           'adb_missing','java_missing','package_missing'])
        self.assertEqual(info['packages'],[])
        for roots in (['/abs'],['../outside'],['C:/x'],[''],'app',[None]):
            with self.assertRaises(LedgerError): discover(self.project,roots,self.env())
        with self.assertRaises(LedgerError): discover(self.root/'nope',['app'],self.env())

    def test_java_precedence(self):
        jdk=self.root/'jdk';touch(jdk/'bin'/('java'+EXE));touch(jdk/'release','JAVA_VERSION="17"')
        path_jdk=self.root/'path-jdk';touch(path_jdk/'bin'/('java'+EXE));touch(path_jdk/'release')
        shim=self.root/'javapath';touch(shim/('java'+EXE))
        info=discover(self.project,['app'],self.env(JAVA_HOME=jdk,PATH=path_jdk/'bin'))
        self.assertEqual((info['java'],info['java_home'],info['java_source']),(str(jdk/'bin'/('java'+EXE)),str(jdk),'JAVA_HOME'))
        # apk_audit/preflight run the java on PATH, so it is reported even when JAVA_HOME wins.
        self.assertEqual(info['java_on_path'],str(path_jdk/'bin'/('java'+EXE)))
        self.assertIsNone(discover(self.project,['app'],self.env(JAVA_HOME=jdk))['java_on_path'])
        info=discover(self.project,['app'],self.env(JAVA_HOME=self.root/'gone',PATH=path_jdk/'bin'))
        self.assertEqual((info['java'],info['java_home'],info['java_source']),(str(path_jdk/'bin'/('java'+EXE)),str(path_jdk),'PATH'))
        info=discover(self.project,['app'],self.env(PATH=shim))
        self.assertEqual((info['java'],info['java_home']),(str(shim/('java'+EXE)),None))
        if os.name=='nt':
            jbr=self.root/'programfiles/Android/Android Studio/jbr';touch(jbr/'bin/java.exe');touch(jbr/'release')
            info=discover(self.project,['app'],self.env())
            self.assertEqual((info['java'],info['java_home'],info['java_source']),(str(jbr/'bin/java.exe'),str(jbr),'android_studio'))

    def test_tests_ranked_by_imports(self):
        touch(self.app/'lib/src/a.dart','class A {}');touch(self.app/'lib/src/b.dart','class B {}')
        touch(self.app/'lib/app.dart',"export 'src/a.dart';\nimport 'package:flutter/widgets.dart';\n")
        touch(self.app/'test/direct_test.dart',"import 'package:app/src/a.dart';\nvoid main() {}")
        touch(self.app/'test/relative_test.dart',"import '../lib/src/a.dart' show A;\nvoid main() {}")
        touch(self.app/'test/barrel_test.dart',"import 'package:app/app.dart';\nvoid main() {}")
        touch(self.app/'test/helper_test.dart',"import 'helper.dart';\nvoid main() {}")
        touch(self.app/'test/helper.dart',"import 'package:app/src/a.dart';\nimport '/abs/escape.dart';\n")
        touch(self.app/'test/other_test.dart',"import 'package:app/src/b.dart';\n// import 'package:app/src/a.dart';\nvoid main() {}")
        touch(self.app/'test/cycle_test.dart',"import 'cycle.dart';\nvoid main() {}");touch(self.app/'test/cycle.dart',"import 'cycle.dart';\n")
        ranked=tests_for(self.app,['lib/src/a.dart'])
        self.assertEqual(ranked,['test/direct_test.dart','test/relative_test.dart','test/barrel_test.dart','test/helper_test.dart',
                                 'test/a/a_test.dart','test/b_test.dart','test/cycle_test.dart','test/other_test.dart'])
        self.assertEqual(tests_for(self.app,[str(self.app/'lib/src/b.dart')])[0],'test/other_test.dart')
        self.assertEqual(tests_for(self.app,['README.md',str(self.root/'elsewhere.dart')]),sorted(ranked))

    def test_fingerprint_tracks_tool_files(self):
        sdk=self.sdk(self.root/'sdk');flutter=self.flutter('flutter');jdk=self.root/'jdk';java=touch(jdk/'bin'/('java'+EXE))
        path_java=touch(self.root/'path-jdk/bin'/('java'+EXE))
        info=discover(self.project,['app'],self.env(ANDROID_HOME=sdk,FLUTTER_ROOT=flutter,JAVA_HOME=jdk,PATH=path_java.parent))
        self.assertEqual(set(delivery_env.tool_paths(info)),{'dart','flutter_tools.snapshot','adb','apksigner.jar','aapt2','zipalign','java','java_on_path'})
        first=fingerprint(info);self.assertRegex(first,r'^[0-9a-f]{64}$');self.assertEqual(fingerprint(info),first)
        touch(sdk/'platform-tools'/('adb'+EXE),b'changed');changed=fingerprint(info);self.assertNotEqual(changed,first)
        touch(flutter/'bin/cache/flutter_tools.snapshot',b'changed');self.assertNotEqual(fingerprint(info),changed);changed=fingerprint(info)
        touch(path_java,b'changed');self.assertNotEqual(fingerprint(info),changed);changed=fingerprint(info)
        java.unlink();self.assertNotEqual(fingerprint(info),changed)
        self.assertEqual(fingerprint({}),fingerprint({'java':None,'adb':str(self.root/'missing')}))

    def test_debug_signer_sha256(self):
        self.assertEqual(signer_sha256(KEYTOOL),'abcdef0123456789'*4)
        self.assertIsNone(signer_sha256('SHA256withRSA'));self.assertIsNone(signer_sha256(None))
        jdk=self.root/'jdk';keytool=touch(jdk/'bin'/('keytool'+EXE));keystore=touch(self.root/'debug.keystore')
        calls=[]
        def run(argv,**kwargs):
            calls.append((argv,kwargs));return subprocess.CompletedProcess(argv,0,KEYTOOL,'')
        with patch('onecrew.delivery_env.subprocess.run',side_effect=run):
            self.assertEqual(debug_signer_sha256(jdk,keystore),'abcdef0123456789'*4)
            self.assertIsNone(debug_signer_sha256(jdk,self.root/'missing.keystore'))
            self.assertIsNone(debug_signer_sha256(self.root/'no-jdk',keystore))
        argv,kwargs=calls[0];self.assertEqual(len(calls),1)
        self.assertEqual(argv[0],str(keytool));self.assertIn('-list',argv);self.assertIn('-v',argv)
        self.assertEqual(argv[argv.index('-alias')+1],'androiddebugkey');self.assertEqual(argv[argv.index('-keystore')+1],str(keystore))
        self.assertEqual(kwargs['timeout'],20);self.assertNotIn('shell',kwargs);self.assertIs(kwargs['stdin'],subprocess.DEVNULL)
        with patch('onecrew.delivery_env.subprocess.run',return_value=subprocess.CompletedProcess([],1,KEYTOOL,'bad password')):
            self.assertIsNone(debug_signer_sha256(jdk,keystore))
        with patch('onecrew.delivery_env.subprocess.run',side_effect=subprocess.TimeoutExpired('keytool',20)):
            self.assertIsNone(debug_signer_sha256(jdk,keystore))
        with patch('onecrew.delivery_env.subprocess.run',side_effect=OSError('denied')):
            self.assertIsNone(debug_signer_sha256(jdk,keystore))

    def test_debug_keystore_follows_agp_location(self):
        user,prefs,sdk_home=self.root/'user-home',self.root/'prefs',self.root/'sdk-home'
        self.assertEqual(delivery_env.debug_keystore(self.env(ANDROID_USER_HOME=user,ANDROID_PREFS_ROOT=prefs,ANDROID_SDK_HOME=sdk_home)),user/'debug.keystore')
        self.assertEqual(delivery_env.debug_keystore(self.env(ANDROID_PREFS_ROOT=prefs,ANDROID_SDK_HOME=sdk_home)),prefs/'.android/debug.keystore')
        self.assertEqual(delivery_env.debug_keystore(self.env(ANDROID_SDK_HOME=sdk_home)),sdk_home/'.android/debug.keystore')
        self.assertEqual(delivery_env.debug_keystore(self.env()),self.home/'.android/debug.keystore')
        jdk=self.root/'jdk';touch(jdk/'bin'/('keytool'+EXE));keystore=touch(user/'debug.keystore')
        with patch.dict(os.environ,{'ANDROID_USER_HOME':str(user)}), \
             patch('onecrew.delivery_env.subprocess.run',return_value=subprocess.CompletedProcess([],0,KEYTOOL,'')) as run:
            self.assertEqual(debug_signer_sha256(jdk),'abcdef0123456789'*4)
        argv=run.call_args[0][0];self.assertEqual(argv[argv.index('-keystore')+1],str(keystore))


if __name__=='__main__':
    unittest.main()
