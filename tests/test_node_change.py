import json
import os
from pathlib import Path
import shutil
import unittest
from unittest.mock import patch

from tests import test_owned as fixtures
from onecrew.native_change import validate
from onecrew.ledger import LedgerError
from onecrew.snapshots import bytes_hash

NODE = shutil.which('node')

# Fake toolchain: real node.exe runs tiny scripts that emulate tsc / vitest --reporter=json / an esbuild build script.
FAKE_TSC = r"""
const fs=require('fs');
if (fs.existsSync('src/app.ts') && fs.readFileSync('src/app.ts','utf8').includes('TYPE_ERROR')) { console.log('src/app.ts(1,1): error TS2322'); process.exit(2); }
console.log('tsc ok');
"""
FAKE_VITEST = r"""
import fs from 'node:fs'; import path from 'node:path';
const args=process.argv.slice(2); let out=null; const files=[];
for (const a of args) { if (a.startsWith('--outputFile=')) out=a.slice(13); else if (!a.startsWith('--') && a!=='run') files.push(a); }
const results=[]; let total=0, passed=0, failed=0;
for (const f of files) {
  const text=fs.existsSync(f)?fs.readFileSync(f,'utf8'):'';
  if (text.includes('HANG')) { const end=Date.now()+60000; while (Date.now()<end) {} }
  if (text.includes('MUTATE')) fs.appendFileSync('node_modules/.package-lock.json',' ');
  if (text.includes('EMPTY')) continue;
  const ok=!text.includes('FAIL'); total++; ok?passed++:failed++;
  results.push({name:path.resolve(f),status:ok?'passed':'failed',assertionResults:[{status:ok?'passed':'failed',title:'t',fullName:'suite adds',
    failureMessages:ok?[]:['AssertionError: expected 1 to be 2\n    at test/app.test.ts:3:1\n    at runner.js:9:9']}]});
}
fs.writeFileSync(out, JSON.stringify({numTotalTests:total,numPassedTests:passed,numFailedTests:failed,numPendingTests:0,numTodoTests:0,success:total>0&&failed===0,testResults:results}));
process.exit(total>0&&failed===0?0:1);
"""
FAKE_E2E = r"""
import fs from 'node:fs';
const src=fs.readFileSync('src/app.ts','utf8');
if (!fs.existsSync('dist/manifest.json')) { console.log('FAIL build output missing'); console.log('0/1 checks passed'); process.exit(1); }
console.log('PASS panel draws shell (mock port ' + (process.env.NA_MOCK_PORT||'none') + ')');
if (src.includes('E2EFAIL')) { console.log('FAIL fill: mach expected 102 got empty'); console.log('2/3 checks passed'); process.exit(1); }
if (src.includes('E2EFEW')) { console.log('1/1 checks passed'); process.exit(0); }
if (src.includes('E2ESILENT')) process.exit(0);
console.log('PASS fill'); console.log('PASS no self save'); console.log('3/3 checks passed');
"""
FAKE_BUILD = r"""
import fs from 'node:fs';
if (fs.readFileSync('src/app.ts','utf8').includes('NOBUILD')) process.exit(0);
fs.mkdirSync('dist',{recursive:true}); fs.writeFileSync('dist/manifest.json', fs.readFileSync('manifest.json'));
"""


@unittest.skipUnless(NODE and os.name == 'nt', 'needs node.exe on Windows')
class NodeChangeTests(unittest.TestCase):
    def setUp(self):
        self.f=fixtures.OwnedTests();self.f.setUp();self.addCleanup(self.f.doCleanups)
        root=self.ext=self.f.root/'ext'
        files={'src/app.ts':'export const add=(a:number,b:number)=>a-b;\n','src/panel.css':'.chat-panel{}\n',
               'test/app.test.ts':'old test\n','test/shell.test.ts':'existing regression\n','manifest.json':'{"version":"0.6.3"}\n',
               'package.json':'{"name":"ext"}\n','tsconfig.json':'{}\n','scripts/build-demo.mjs':FAKE_BUILD,
               'assets/icon.png':'binary-ish local only\n','e2e/run-panel.mjs':FAKE_E2E,
               'node_modules/typescript/bin/tsc':FAKE_TSC,'node_modules/vitest/vitest.mjs':FAKE_VITEST,
               'node_modules/.package-lock.json':'{"lockfileVersion":3}'}
        for name,text in files.items():
            p=root/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_text(text)
        self.lock=bytes_hash((root/'node_modules/.package-lock.json').read_bytes())
        self.recipe=dict(toolchain='node',source_roots=['ext'],owned=['ext/src/app.ts','ext/test/app.test.ts'],extra_sources={},
            package='ext',tests=['ext/test/app.test.ts'],regression_tests=['ext/test/shell.test.ts'],node_exe=NODE,
            build_script='scripts/build-demo.mjs',reference='User approved SOL fixture',trusted_native=True)
        if 'e2e' in self._testMethodName:
            self.recipe['e2e']={'script':'e2e/run-panel.mjs','env':{'NA_MOCK_PORT':'18766'},'timeout_seconds':60,'min_checks':3}
        self.run,self.task,self.worker=self.f.runtime([],mode='change',provider='claude',model='sonnet',native_change=self.recipe)
        self.run.run(self.task,steps=1)

    def candidate(self,source='export const add=(a:number,b:number)=>a+b;\n',test='it adds\n'):
        return {'report':'Fixed add and covered it with a Vitest case. Browser unverified.','question':'','files':[
            {'path':'ext/src/app.ts','text':source},{'path':'ext/test/app.test.ts','text':test}]}

    def work_and_verify(self,candidate):
        self.worker.responses=[candidate,{'accepted':True,'feedback':'Checked'}]
        self.run.run(self.task,steps=1)
        return self.run.run(self.task,steps=1)

    def verification_dir(self,state):
        return Path(state['native_change']['verification_workspace'])/'ext'

    def test_recipe_validation_keeps_tool_configuration_operator_controlled(self):
        self.assertEqual(validate(self.recipe)['tests'],['ext/test/app.test.ts'])
        bad=[dict(owned=['other/app.ts','ext/test/app.test.ts']),dict(owned=['ext/package.json','ext/test/app.test.ts']),
             dict(owned=['ext/tsconfig.json','ext/test/app.test.ts']),dict(owned=['ext/dist/app.js','ext/test/app.test.ts']),
             dict(tests=['ext/test/other.test.ts']),dict(regression_tests=['ext/test/app.test.ts']),
             dict(node_exe='node.exe'),dict(build_script='../x.mjs'),dict(extra_sources={'ext/a.ts':'0'*64}),
             dict(trusted_native=False),dict(toolchain='deno')]
        for change in bad:
            with self.assertRaises(LedgerError,msg=str(change)): validate(dict(self.recipe,**change))
        with self.assertRaises(LedgerError): validate(dict(self.recipe,flutter_root='C:/flutter'))

    def test_full_flow_runs_fixed_steps_detaches_modules_and_applies(self):
        untouched=self.ext/'src/panel.css'
        state=self.work_and_verify(self.candidate())
        check=state['native_change']['checks'][-1]
        self.assertTrue(check['passed'],check['detail'])
        self.assertEqual([s['step'] for s in check['evidence']['steps']],['typecheck','vitest','build'])
        self.assertEqual(check['evidence']['steps'][1]['summary']['totals']['numPassedTests'],2)
        self.assertIn('--no-cache',check['evidence']['steps'][1]['argv'])
        self.assertFalse(os.path.lexists(self.verification_dir(state)/'node_modules'))
        self.assertTrue((self.verification_dir(state)/'assets/icon.png').is_file())  # local-only input staged
        self.assertTrue((self.ext/'node_modules/vitest/vitest.mjs').is_file())
        self.assertIn('a-b',(self.ext/'src/app.ts').read_text())
        self.run.run(self.task,steps=1);state=self.run.run(self.task,steps=1)
        self.assertEqual(state['phase'],'completed');self.assertIn('Node typecheck, Vitest and build passed',state['report'])
        self.assertIn('a+b',(self.ext/'src/app.ts').read_text());self.assertEqual(untouched.read_text(),'.chat-panel{}\n')
        self.assertEqual(bytes_hash((self.ext/'node_modules/.package-lock.json').read_bytes()),self.lock)

    def assert_repair(self,state,needle):
        native=state['native_change']
        self.assertNotEqual(state['phase'],'blocked',state.get('message'))
        self.assertEqual(native['stage'],'work');self.assertEqual(native['repairs'],1)
        self.assertIn(needle,native['feedback']);self.assertFalse(native['checks'][-1]['passed'])
        self.assertFalse(os.path.lexists(self.verification_dir(state)/'node_modules'))
        self.assertIn('a-b',(self.ext/'src/app.ts').read_text())

    def test_failing_owned_test_requests_repair_without_apply(self):
        state=self.work_and_verify(self.candidate(test='FAIL\n'))
        self.assert_repair(state,'vitest')
        feedback=state['native_change']['feedback']
        self.assertIn('test/app.test.ts > suite adds: AssertionError: expected 1 to be 2',feedback)

    def test_e2e_step_runs_after_build_with_pinned_env_and_counts_checks(self):
        state=self.work_and_verify(self.candidate())
        check=state['native_change']['checks'][-1]
        self.assertTrue(check['passed'],check['detail'])
        steps=check['evidence']['steps'];self.assertEqual([s['step'] for s in steps],['typecheck','vitest','build','e2e'])
        self.assertEqual((steps[-1]['summary']['checks_passed'],steps[-1]['summary']['checks_total']),(3,3))
        self.assertIn('mock e2e 3/3 checks',check['detail'])
        self.assertIn(b'mock port 18766',self.run.store.read_blob(steps[-1]['stdout']))
        self.assertTrue(check['evidence']['mock_e2e_ran'])

    def test_e2e_failure_feeds_fail_lines_to_repair(self):
        state=self.work_and_verify(self.candidate(source='export const add=(a:number,b:number)=>a+b; // E2EFAIL\n'))
        self.assert_repair(state,'e2e')
        self.assertIn('FAIL fill: mach expected 102 got empty',state['native_change']['feedback'])
        self.assertIn('2/3 passed',state['native_change']['feedback'])

    def test_e2e_needs_minimum_checks_and_an_explicit_summary(self):
        self.assert_repair(self.work_and_verify(self.candidate(source='export const x=1; // E2EFEW\n')),'minimum 3')

    def test_e2e_silent_success_without_summary_never_passes(self):
        self.assert_repair(self.work_and_verify(self.candidate(source='export const x=1; // E2ESILENT\n')),'no "N/N checks passed"')

    def test_e2e_recipe_validation(self):
        good=dict(self.recipe)
        self.assertEqual(validate(good)['e2e']['script'],'e2e/run-panel.mjs')
        for change in ({'env':{'NA_API_TOKEN':'x'*20}},{'env':{'CHROME_PATH':'API_KEY=abcdefghijkl'}},
                       {'timeout_seconds':5},{'min_checks':0},{'script':'../x.mjs'},{'script':'e2e/run.py'},{'extra':1}):
            with self.assertRaises(LedgerError,msg=str(change)): validate(dict(good,e2e=dict(good['e2e'],**change)))

    def test_crlf_original_keeps_crlf_and_review_diff_is_content_only(self):
        from onecrew.native_change import patch_diff
        (self.ext/'src/app.ts').write_bytes(b''.join(b'export const line%d = %d;\r\n' % (i,i) for i in range(3000)))
        (self.ext/'test/app.test.ts').write_bytes(b'old test\n')  # write_text would emit CRLF on Windows
        from onecrew.native_change import install_candidate
        from onecrew.node_change import prepare
        text=''.join('export const line%d = %d;\n' % (i,i) for i in range(3000)).replace('line7 = 7','line7 = 70')
        state=dict(self.run.state(self.task)[1],original={},files={})
        prepare(self.run,state,validate(self.recipe))
        install_candidate(self.run,state,self.candidate(source=text),validate(self.recipe))
        native=state['native_change'];installed=self.run.store.read_blob(native['changes']['ext/src/app.ts'])
        self.assertEqual(installed.count(b'\r\n'),3000);self.assertIn(b'line7 = 70;\r\n',installed)
        self.assertNotIn(b'\r',self.run.store.read_blob(native['changes']['ext/test/app.test.ts']))  # LF original stays LF
        diff=patch_diff(self.run,state)
        self.assertLess(len(diff),2000);self.assertIn('+export const line7 = 70;',diff)

    def test_partial_repair_patch_is_repaired_not_blocked_and_keeps_previous_feedback(self):
        self.worker.responses=[self.candidate(test='FAIL\n'),
            {'report':'Only touched the test this round.','question':'','files':[{'path':'ext/test/app.test.ts','text':'it adds\n'}]},
            self.candidate(),{'accepted':True,'feedback':'Checked'}]
        for _ in range(3): state=self.run.run(self.task,steps=1)  # work -> verify(fail) -> work(partial)
        native=state['native_change']
        self.assertNotEqual(state['phase'],'blocked',state.get('message'))
        self.assertEqual(native['stage'],'work');self.assertEqual(native['repair_counts'],{'content':1,'product':1})
        self.assertIn('COMPLETE cumulative set',native['feedback']);self.assertIn('expected 1 to be 2',native['feedback'])
        self.assertNotIn('result_pending',native)
        for _ in range(4): state=self.run.run(self.task,steps=1)  # work -> verify -> review -> apply
        self.assertEqual(state['phase'],'completed');self.assertIn('a+b',(self.ext/'src/app.ts').read_text())

    def test_skipped_or_empty_owned_test_never_passes(self):
        self.assert_repair(self.work_and_verify(self.candidate(test='EMPTY\n')),'vitest')

    def test_type_error_stops_before_tests(self):
        state=self.work_and_verify(self.candidate(source='TYPE_ERROR\n'))
        self.assert_repair(state,'typecheck')
        self.assertEqual([s['step'] for s in state['native_change']['checks'][-1]['evidence']['steps']],['typecheck'])

    def test_build_without_dist_manifest_fails(self):
        self.assert_repair(self.work_and_verify(self.candidate(source='export const NOBUILD=1;\n')),'build')

    def test_missing_installed_tools_block_as_environment_without_repair(self):
        shutil.rmtree(self.ext/'node_modules/vitest')
        state=self.work_and_verify(self.candidate())
        self.assertEqual(state['phase'],'blocked');self.assertEqual(state['recovery']['kind'],'environment')
        self.assertEqual(state['native_change']['repairs'],0);self.assertEqual(len(self.worker.calls),1)

    def test_dependency_tree_change_blocks_and_keeps_candidate(self):
        state=self.work_and_verify(self.candidate(test='MUTATE\n'))
        self.assertEqual(state['phase'],'blocked');self.assertIn('node_modules changed',state['message'])
        self.assertIn('a-b',(self.ext/'src/app.ts').read_text())

    def test_deadline_kills_step_and_still_detaches_modules(self):
        from onecrew import node_change
        links=[];original=node_change.detach_modules
        def record(link,target):
            links.append(link);return original(link,target)
        with patch.dict('onecrew.node_change.STEP_SECONDS',{'vitest':2}),patch('onecrew.node_change.detach_modules',side_effect=record):
            state=self.work_and_verify(self.candidate(test='HANG\n'))
        self.assertEqual(state['phase'],'blocked');self.assertIn('deadline',state['message'].lower())
        self.assertEqual(len(links),1);self.assertFalse(os.path.lexists(links[0]))
        self.assertTrue((self.ext/'node_modules/.package-lock.json').is_file())
        self.assertIn('a-b',(self.ext/'src/app.ts').read_text())


if __name__=='__main__': unittest.main()
