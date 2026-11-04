"""Exact W12b/T48b test succession; preserves both executable histories.

This is not a general pin override. The R00 guard's raw verdict is retained.
Only tests/test_wf_plan_names.py may be superseded, with exact source hashes,
the original file at its original pinned commit, and actual passing executions
of that file against the old code and of the successor against the final wheel.
"""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import zipfile

from wfkit import gate, kitguard

FILE = 'tests/test_wf_plan_names.py'
RECORD = 'wfkit/namespace-lineage.json'


def _git_bytes(root, revision, path):
    return subprocess.check_output(['git','-C',str(root),'show',revision+':'+path],stderr=subprocess.PIPE)


def _sha(data): return hashlib.sha256(data.replace(b'\r\n',b'\n')).hexdigest()


def validate(root, record=None):
    root=Path(root).resolve(); record=record or gate._read(root/RECORD)
    if record.get('version')!=1 or record.get('file')!=FILE or record.get('source_tasks')!=['W12b'] or record.get('source_testcases')!=['T48b']:
        raise ValueError('Only the exact W12b/T48b namespace test succession is supported.')
    manifest=kitguard.load_manifest(root)
    pin=manifest['releases']['R00']['pins'][FILE]
    if (record.get('old_commit')!=pin['commit'] or record.get('old_sha256')!=pin['sha256']
            or _sha(_git_bytes(root,record['old_commit'],FILE))!=pin['sha256']):
        raise ValueError('Original pinned testcase/commit does not match historical bytes.')
    new_commit=record.get('new_commit','')
    if len(new_commit)!=40 or any(c not in '0123456789abcdef' for c in new_commit):
        raise ValueError('Successor must name an exact commit, never HEAD.')
    if (kitguard.sha256_file(root/FILE)!=record.get('new_sha256')
            or _sha(_git_bytes(root,new_commit,FILE))!=record['new_sha256']):
        raise ValueError('Current successor differs from its exact committed test bytes.')
    for source in record.get('sources',[]):
        path=(root/source['path']).resolve()
        if not path.is_relative_to(root) or hashlib.sha256(path.read_bytes()).hexdigest()!=source['sha256']:
            raise ValueError('Approved source fixture changed.')
    if {s['path'] for s in record.get('sources',[])} != {'docs/wf/sources/04-TASKS.vi.md','docs/wf/sources/05-TESTCASES.vi.md'}:
        raise ValueError('Both approved task and testcase source fixtures are required.')
    return record


def _execute(python, tests_root, cwd, source_root=None):
    """Load test files without adding the new checkout to module resolution."""
    code='''import hashlib,json,sys,types,unittest
from pathlib import Path
'''
    if source_root is not None: code+='sys.path.insert(0,'+repr(str(source_root))+')\n'
    code+="package=types.ModuleType('tests'); package.__path__=["+repr(str(tests_root))+" ]; sys.modules['tests']=package\n"
    code+="suite=unittest.defaultTestLoader.loadTestsFromName('tests.test_wf_plan_names')\n"
    code+='result=unittest.TextTestRunner(verbosity=2).run(suite)\n'
    code+='''loaded={n:{'path':m.__file__,'sha256':hashlib.sha256(Path(m.__file__).read_bytes()).hexdigest()}
 for n,m in sys.modules.items() if (n=='onecrew' or n.startswith('onecrew.')) and getattr(m,'__file__',None)}
print('@@LINEAGE@@'+json.dumps({'tests_run':result.testsRun,'tests_passed':result.testsRun-len(result.failures)-len(result.errors)-len(result.skipped)
 -len(result.expectedFailures)-len(result.unexpectedSuccesses),
 'tests_errors':len(result.failures)+len(result.errors),'tests_skipped':len(result.skipped),'tests_expected_failures':len(result.expectedFailures),
 'tests_unexpected_successes':len(result.unexpectedSuccesses),'result':'pass' if result.wasSuccessful() and not result.expectedFailures else 'fail','loaded':loaded}))
raise SystemExit(not result.wasSuccessful())
'''
    env={k:v for k,v in os.environ.items() if k not in ('PYTHONPATH','PYTHONHOME','PYTHONSTARTUP','ONECREW_ACTOR','CLAUDECODE','CLAUDE_CODE_CHILD_SESSION')}
    result=subprocess.run([str(python),'-I','-c',code],cwd=cwd,env=env,capture_output=True,text=True,encoding='utf-8',errors='replace',timeout=300)
    line=next((s for s in result.stdout.splitlines() if s.startswith('@@LINEAGE@@')),None)
    if line is None: raise ValueError('Lineage execution emitted no result: '+result.stderr[-800:])
    observed=json.loads(line[len('@@LINEAGE@@'):]); observed['exit_code']=result.returncode
    observed['script_sha256']=hashlib.sha256(code.encode()).hexdigest()
    return observed,code,result.stdout+result.stderr


def execute(root, python, wheel, out):
    """Observe both histories on disposable data; successor uses the final wheel."""
    from tests import wf_oldversion
    root, out, wheel=Path(root).resolve(),Path(out).resolve(),Path(wheel).resolve()
    record=validate(root); out.mkdir(parents=True,exist_ok=False)
    archive=wf_oldversion.archive(record['old_commit'],root,out)
    if kitguard.sha256_file(archive/FILE)!=record['old_sha256']: raise ValueError('Archived original test changed.')
    old,old_code,old_log=_execute(sys.executable,archive/'tests',out,archive)
    for loaded in old['loaded'].values():
        path=Path(loaded['path']).resolve()
        if not path.is_relative_to(archive): raise ValueError('Original test imported a different source tree.')
        blob=_git_bytes(root,record['old_commit'],path.relative_to(archive).as_posix())
        materialized=path.read_bytes()
        if hashlib.sha256(materialized).hexdigest()!=loaded['sha256'] or _sha(blob)!=_sha(materialized):
            raise ValueError('Original loaded bytes differ from pinned commit: '+str(path))
        loaded.update(git_blob_sha256=hashlib.sha256(blob).hexdigest(),normalized_sha256=_sha(blob),
                      normalization='CRLF to LF only; same rule as historical kit pins')
    new,new_code,new_log=_execute(python,root/'tests',out)
    with zipfile.ZipFile(wheel) as package:
        for name,loaded in new['loaded'].items():
            path=Path(loaded['path']).resolve()
            if path.is_relative_to(root) or 'site-packages' not in path.parts:
                raise ValueError('Successor imported checkout code instead of final wheel.')
            member=name.replace('.','/')+('/__init__.py' if path.name=='__init__.py' else '.py')
            if hashlib.sha256(package.read(member)).hexdigest()!=loaded['sha256']:
                raise ValueError('Successor loaded module differs from final wheel: '+name)
    for label,body,code,log in [('old',old,old_code,old_log),('new',new,new_code,new_log)]:
        script=out/(label+'.py'); script.write_text(code,encoding='utf-8',newline='\n')
        logfile=out/(label+'.log'); logfile.write_text(log,encoding='utf-8',newline='\n')
        body.update(script=str(script),log=str(logfile),log_sha256=hashlib.sha256(logfile.read_bytes()).hexdigest())
    validate(root,record) # Fail if the selected test/source changed during execution.
    result={'record':record,'record_sha256':kitguard.canon_sha(record),'wheel_sha256':hashlib.sha256(wheel.read_bytes()).hexdigest(),
            'old':old,'new':new,'kind':'actual dual-history execution','release_acceptance':False}
    gate._write(out/'receipt.json',result)
    return result


def assess(raw_guard, record, receipt, wheel_sha):
    """Retain raw refusal; discharge only its exact, independently proved change."""
    remaining=[]; discharged=[]
    valid=(receipt and receipt.get('record')==record and receipt.get('record_sha256')==kitguard.canon_sha(record)
           and receipt.get('wheel_sha256')==wheel_sha and receipt.get('kind')=='actual dual-history execution')
    for label in ('old','new'):
        observed=(receipt or {}).get(label,{})
        valid=valid and observed.get('exit_code')==0 and bool(observed.get('loaded')) and gate._counts_pass(observed,0)
    for problem in raw_guard.get('problems',[]):
        exact=(problem.get('code')=='changed' and problem.get('pin')==FILE and problem.get('release')=='R00'
               and problem.get('pinned_sha256')==record['old_sha256'] and problem.get('actual_sha256')==record['new_sha256'])
        (discharged if exact and valid else remaining).append(problem)
    return {'ok':not remaining and not raw_guard.get('unchecked'), 'raw':raw_guard,
            'superseded':discharged,'remaining':remaining,'lineage_valid':bool(valid)}
