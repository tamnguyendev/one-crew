"""Typed, operator-sealed native delivery operations and artifact provenance."""
import copy
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import uuid
from urllib.parse import urljoin

from .ledger import LedgerError, canonical, content_hash, exact_fields
from .snapshots import safe_file, scoped_path, durable_write
from .sandbox_gate import command, task_guard

EXCLUDED={'.git','.onecrew','.gradle','build','node_modules','.dart_tool','.idea','__pycache__','ephemeral'}


def file_hash(path):
    digest=hashlib.sha256()
    with Path(path).open('rb') as f:
        for block in iter(lambda:f.read(1024*1024),b''): digest.update(block)
    return digest.hexdigest()


def fingerprint(project, roots):
    files={};project=Path(project).resolve()
    for root in roots:
        start=safe_file(project,root)
        if not start.is_dir(): raise LedgerError('Source root unavailable: '+root)
        for directory,dirs,names in os.walk(start,followlinks=False):
            base=Path(directory)
            dirs[:]=sorted(d for d in dirs if d.lower() not in EXCLUDED)
            for name in sorted(dirs+names):
                p=base/name
                if p.is_symlink() or (hasattr(p,'is_junction') and p.is_junction()):
                    raise LedgerError('Source links require explicit materialization: '+str(p))
            for name in sorted(names):
                p=base/name
                if name.endswith(('.out','.err')): continue
                if p.stat().st_size>128_000_000: raise LedgerError('Source file exceeds 128 MB capture bound.')
                files[p.relative_to(project).as_posix()]=file_hash(p)
                if len(files)>40000: raise LedgerError('Source manifest exceeds 40000 files.')
        # Resolved dependency graphs are inputs, not disposable build output.
        for leaf in ('package_config.json','package_graph.json'):
            p=start/'.dart_tool'/leaf
            if p.exists(): files[p.relative_to(project).as_posix()]=file_hash(p)
    if not files: raise LedgerError('Empty source capture.')
    return {'hash':content_hash(files),'files':files}


def home(runtime,task):
    root=Path(__file__).resolve().parents[1]/'.onecrew'/'delivery'/content_hash(str(runtime.ledger.state_root))[:12]/task
    root.mkdir(parents=True,exist_ok=True)
    return root


def store_manifest(runtime,task,value):
    path=home(runtime,task)/('source-'+value['hash']+'.json')
    if not path.exists():durable_write(path,canonical(value['files']).encode())
    ref={'hash':value['hash'],'manifest_file':str(path),'file_count':len(value['files'])}
    load_manifest(ref)
    return ref


def load_manifest(ref):
    if 'files' in ref:return ref
    path=Path(ref['manifest_file'])
    if path.stat().st_size>32_000_000:raise LedgerError('Manifest exceeds evidence bound.')
    files=json.loads(path.read_text(encoding='utf-8'))
    if content_hash(files)!=ref['hash']:raise LedgerError('Source manifest evidence changed.')
    return {'hash':ref['hash'],'files':files}


def capture(project, manifest, destination, roots):
    manifest=load_manifest(manifest)
    destination=Path(destination)
    destination.mkdir(parents=True,exist_ok=False)
    for name,digest in manifest['files'].items():
        src=safe_file(project,name)
        if file_hash(src)!=digest: raise LedgerError('Source changed during capture: '+name)
        out=safe_file(destination,name);out.parent.mkdir(parents=True,exist_ok=True)
        shutil.copy2(src,out)
        if file_hash(out)!=digest: raise LedgerError('Capture changed: '+name)
    rebase_packages(project,destination,roots)
    return destination


def rebase_packages(project,destination,roots):
    for root in roots:
        src=safe_file(project,root+'/.dart_tool/package_config.json')
        out=safe_file(destination,root+'/.dart_tool/package_config.json')
        if not out.exists(): continue
        config=json.loads(out.read_text(encoding='utf-8'))
        for package in config['packages']:
            absolute=urljoin(src.as_uri(),package['rootUri'])
            package['rootUri']=absolute
            for r in roots:
                if absolute.rstrip('/')==safe_file(project,r).as_uri().rstrip('/'):
                    package['rootUri']=safe_file(destination,r).as_uri()+'/'
        durable_write(out,canonical(config).encode())


def validate_config(kind,c,roots):
    fields={
        'regression':({'package','flutter_root','tests','red'}, {'repair_node'}),
        'review':(set(),{'repair_node'}),
        'build':({'package','flutter_root','android_sdk','variant','config_reference','config_version','signer_sha256','timeout_seconds'},set()),
        'apk_audit':({'build_node','build_tools','package_id','signer_sha256','require_16kb','max_bytes'},{'version_code'}),
        'device':({'build_node','adb','serial','package_id','scenario','scenario_sha256','private_reference','private_version','timeout_seconds'}, {'repair_node'})}
    required,optional=fields[kind]
    if set(c)-required-optional or required-set(c): raise LedgerError('Invalid '+kind+' recipe fields.')
    if 'repair_node' in c and not isinstance(c['repair_node'],str): raise LedgerError('Explicit repair node required.')
    if kind in ('regression','build'):
        if c['package'] not in roots or not Path(c['flutter_root']).is_absolute(): raise LedgerError('Pin package and Flutter SDK.')
    if kind=='regression':
        if not isinstance(c['tests'],list) or not c['tests'] or len(set(c['tests']))!=len(c['tests']): raise LedgerError('Explicit regression files required.')
        for t in c['tests']:
            scoped_path(t)
            if not t.startswith('test/') or not t.endswith('_test.dart'): raise LedgerError('Invalid regression file.')
        if not isinstance(c['red'],list): raise LedgerError('Red checks must be explicit.')
        for red in c['red']:
            exact_fields(red,('test','error_pattern'),'Behavioral red')
            if red['test'] not in c['tests'] or not isinstance(red['error_pattern'],str) or not 1<=len(red['error_pattern'])<=500:
                raise LedgerError('Red test/pattern invalid.')
            re.compile(red['error_pattern'])
    if kind=='build':
        if c['variant'] not in ('debug','release') or not Path(c['android_sdk']).is_absolute(): raise LedgerError('Invalid build variant/SDK.')
        if c['config_reference'] is not None and not Path(c['config_reference']).is_absolute(): raise LedgerError('Private config requires an absolute local reference.')
    if kind=='apk_audit':
        if not Path(c['build_tools']).is_absolute() or type(c['require_16kb']) is not bool or type(c['max_bytes']) is not int or c['max_bytes']<1:
            raise LedgerError('Explicit APK audit policy required.')
        if 'version_code' in c and (not isinstance(c['version_code'],str) or not re.fullmatch(r'[0-9]{1,12}',c['version_code'])):
            raise LedgerError('Expected version_code must be decimal text.')
    if 'signer_sha256' in c and not re.fullmatch('[0-9a-fA-F]{64}',c['signer_sha256']): raise LedgerError('Expected signer SHA256 required.')
    if kind=='device':
        for k in ('adb','scenario'):
            if not Path(c[k]).is_absolute(): raise LedgerError('Pin absolute device tooling/scenario.')
        if not re.fullmatch('[A-Za-z0-9_.:-]{1,120}',c['serial']): raise LedgerError('Pin device serial.')
        if not re.fullmatch('[0-9a-f]{64}',c['scenario_sha256']): raise LedgerError('Pin scenario hash.')
        if c['private_reference'] is not None and not Path(c['private_reference']).is_absolute(): raise LedgerError('Private device config must be a local reference.')
    if 'package_id' in c and not re.fullmatch(r'[A-Za-z][A-Za-z0-9_]*(\.[A-Za-z0-9_]+)+',c['package_id']): raise LedgerError('Pin Android package ID.')
    if 'timeout_seconds' in c and (type(c['timeout_seconds']) is not int or not 1<=c['timeout_seconds']<=3600): raise LedgerError('Command deadline must be bounded to 3600 seconds.')


def bounded(runtime,task,argv,cwd,seconds,env=None):
    c=runtime.control.status(task)
    remaining=(dt.datetime.fromisoformat(c['deadline'])-runtime.control.clock()).total_seconds()
    if remaining<=0: raise LedgerError('Root deadline exhausted.')
    directory=Path(cwd)
    before=set(directory.glob('*.out'))|set(directory.glob('*.err'))
    try:
        return command(argv,directory,min(seconds,remaining),task_guard(runtime.control,task),env)
    finally:
        # Raw native streams can contain private values. Only sanitized stage logs are retained.
        for path in (set(directory.glob('*.out'))|set(directory.glob('*.err')))-before:
            path.unlink(missing_ok=True)


def dart_argv(sdk):
    sdk=Path(sdk)
    dart=sdk/'bin/cache/dart-sdk/bin'/('dart.exe' if os.name=='nt' else 'dart')
    return [str(dart),'--packages='+str(sdk/'packages/flutter_tools/.dart_tool/package_config.json'),
            str(sdk/'bin/cache/flutter_tools.snapshot'),'--no-version-check']


def preflight(runtime,task,s,source):
    tools={};references=[]
    owned={p for n in s['plan']['nodes'] if n['kind']=='change' for p in n['config']['recipe']['owned']}
    for n in s['plan']['nodes']:
        c=n['config'];kind=n['kind'];paths=[]
        if kind in ('build','regression'):
            args=dart_argv(c['flutter_root']);paths=[Path(args[0]),Path(args[1][11:]),Path(args[2])]
            config=safe_file(runtime.ledger.project,c['package']+'/.dart_tool/package_config.json')
            if not config.is_file():raise LedgerError('Prepared dependency graph missing for '+c['package'])
            from urllib.parse import urlparse
            from urllib.request import url2pathname
            for package in json.loads(config.read_text(encoding='utf-8'))['packages']:
                uri=urljoin(config.as_uri(),package['rootUri']);parsed=urlparse(uri)
                if parsed.scheme!='file' or not Path(url2pathname(parsed.path)).exists():
                    raise LedgerError('Dependency cache unavailable: '+package['name'])
        if kind=='regression':
            trusted=[c['package']+'/'+p for p in c['tests'] if c['package']+'/'+p not in owned]
            if not trusted or any(p not in source['files'] for p in trusted):
                raise LedgerError('An existing read-only regression suite is required alongside worker tests.')
        if kind=='build':
            if not Path(c['android_sdk']).is_dir():raise LedgerError('Android SDK unavailable.')
            if c['config_reference']:references.append(c['config_reference'])
        if kind=='apk_audit':
            suffix='.exe' if os.name=='nt' else ''
            paths=[Path(c['build_tools'])/p for p in ('lib/apksigner.jar','aapt2'+suffix,'zipalign'+suffix)]
            java=shutil.which('java')
            if not java:raise LedgerError('Java unavailable.')
            paths.append(Path(java))
        if kind=='device':
            from .delivery_android import scenario
            scenario(c['scenario'],c['scenario_sha256']);paths=[Path(c['adb']),Path(c['scenario'])]
            if c['private_reference']:references.append(c['private_reference'])
        for path in paths:
            if not path.is_file():raise LedgerError('Pinned tool unavailable: '+str(path))
            tools[str(path.resolve())]=file_hash(path)
        if kind=='device':
            rc,out,_=bounded(runtime,task,[c['adb'],'-s',c['serial'],'get-state'],home(runtime,task),15)
            if rc or out.strip()!='device':raise LedgerError('Pinned Android device unavailable at preflight.')
    for reference in references:
        path=Path(reference).resolve()
        if not path.is_file():raise LedgerError('Private reference unavailable.')
        if any(path.is_relative_to(safe_file(runtime.ledger.project,r)) for r in s['plan']['source_roots']):
            raise LedgerError('Private references must be outside captured source roots.')
        values=json.loads(path.read_text(encoding='utf-8-sig'))
        if not isinstance(values,dict) or any(not isinstance(k,str) or not isinstance(v,str) for k,v in values.items()):
            raise LedgerError('Private JSON must contain only string keys and values.')
    needed=sum(safe_file(runtime.ledger.project,p).stat().st_size for p in source['files'])*3+1_000_000_000
    if shutil.disk_usage(home(runtime,task)).free<needed:raise LedgerError('Insufficient free space for isolated test/build captures.')
    return {'tools':tools,'source':source['hash'],'disk_required_bytes':needed,'private_references_available':len(references)}


def check_tools(preflight_receipt):
    if any(not Path(path).is_file() or file_hash(path)!=digest for path,digest in preflight_receipt['tools'].items()):
        raise LedgerError('Pinned toolchain/scenario changed after preflight.')


def parse_tests(out,code):
    tests={};results={};errors=[];done=None
    for line in out.splitlines():
        try: v=json.loads(line)
        except ValueError: continue
        if not isinstance(v,dict): continue
        if v.get('type')=='testStart': tests[v['test']['id']]=v['test']['name']
        elif v.get('type')=='testDone' and not v.get('hidden'): results[v['testID']]=v
        elif v.get('type')=='error' and len(errors)<30: errors.append({'name':tests.get(v.get('testID'),''),'error':str(v.get('error',''))[:1500]})
        elif v.get('type')=='done': done=v.get('success')
    counts={'passed':sum(v.get('result')=='success' and not v.get('skipped') for v in results.values()),
            'failed':sum(v.get('result')!='success' for v in results.values()),'skipped':sum(bool(v.get('skipped')) for v in results.values())}
    return {'passed':code==0 and done is True and counts['passed']>0 and counts['failed']==0 and counts['skipped']==0,
            'counts':counts,'errors':errors,'exit_code':code,'runner_done':done}


def regression(runtime,task,s,node,row):
    c=node['config'];d=s['delivery'];directory=home(runtime,task)/('test-'+uuid.uuid4().hex[:10])
    work=capture(runtime.ledger.project,d['source'],directory,s['plan']['source_roots'])
    package=work/c['package']; tests_hash={t:file_hash(package/t) for t in c['tests']}
    argv=dart_argv(c['flutter_root'])+['test','--no-pub','--no-test-assets','--reporter','json']
    code,out,err=bounded(runtime,task,argv+c['tests'],package,300,{'CI':'true'})
    result=parse_tests(out,code)
    # Scan before durable evidence enters model context. Raw streams may contain secrets.
    from .monitor import safe
    log=home(runtime,task)/(node['id']+'-'+str(row['generation'])+'.test.txt')
    durable_write(log,safe(out+'\n'+err,100000).encode('utf-8'))
    result.update(source=d['source']['hash'],tests=tests_hash,log=str(log),failure_kind='test',red=[])
    for check in c['red']:
        redwork=home(runtime,task)/('red-'+uuid.uuid4().hex[:10])
        baseline=Path(d['baseline_path'])
        # Copy the immutable baseline snapshot, never restore the user's working source.
        shutil.copytree(baseline,redwork)
        rebase_packages(baseline,redwork,s['plan']['source_roots'])
        source=package/check['test']; target=redwork/c['package']/check['test']
        target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(source,target)
        rc,ro,re_=bounded(runtime,task,argv+[check['test']],redwork/c['package'],300,{'CI':'true'})
        parsed=parse_tests(ro,rc)
        behavioral=rc!=0 and parsed['counts']['failed']>0 and any(not e['name'].startswith('loading ') and re.search(check['error_pattern'],e['error']) for e in parsed['errors'])
        result['red'].append({'test':check['test'],'test_sha256':tests_hash[check['test']],'baseline':d['baseline']['hash'],
                              'behavioral_failure':behavioral,'exit_code':rc,'counts':parsed['counts']})
        result['passed']=result['passed'] and behavioral
    result['detail']=canonical({'counts':result['counts'],'errors':result['errors'],'red':result['red']})
    return result


def review(runtime,task,s,node,row):
    from .native_audit import NativeClaude,capture as audit_capture,NativeTurnLimit
    from .discovery import scan_text
    if not row.get('review_context'):
        work=home(runtime,task)/('review-'+uuid.uuid4().hex[:10])
        audit_capture(runtime,work,s['plan']['source_roots'],flutter_context=True)
        refs={n:content_hash(r['receipt']) for n,r in s['delivery']['nodes'].items() if r['receipt'] and r['phase']=='passed'}
        reports={n:{'ref':refs[n],'receipt':r['receipt']} for n,r in s['delivery']['nodes'].items() if n in refs}
        evidence=scan_text(canonical(reports).encode())
        durable_write(work/'DELIVERY_EVIDENCE.json',evidence.encode())
        criteria=[dict(a,nodes=[n for n in a['nodes'] if n in refs]) for a in s['plan']['acceptance']
                  if any(n in refs for n in a['nodes'])]
        # Review criteria referring to a later build/device need later objective receipts, not guesses here.
        prompt=('Review this source against the approved solution and delivered evidence. Read DELIVERY_EVIDENCE.json and actual source. '
                'Reject mandatory source/test gaps, conditional acceptance, skipped tests and unsupported red claims. '
                'Do not claim a later build/device result. Return verdict accept/revise/blocked, feedback and one check per listed criterion. '
                'List every remaining mandatory source/test gap in unresolved_required, even when overall code looks good. '
                'Each check must cite existing receipt hashes, not invented evidence. Criteria: '+canonical(criteria))
        row['review_context']={'workspace':str(work),'refs':refs,'criteria':criteria,'prompt':prompt,'session':str(uuid.uuid4()),'started':False,'continuations':0}
    ctx=row['review_context']
    schema={'type':'object','properties':{'verdict':{'type':'string','enum':['accept','revise','blocked']},'feedback':{'type':'string'},
        'unresolved_required':{'type':'array','items':{'type':'string'}},
        'checks':{'type':'array','items':{'type':'object','properties':{'id':{'type':'string'},'status':{'type':'string','enum':['passed','failed','blocked']},
        'evidence_refs':{'type':'array','items':{'type':'string'}}},'required':['id','status','evidence_refs'],'additionalProperties':False}}},
        'required':['verdict','feedback','checks','unresolved_required'],'additionalProperties':False}
    if not runtime.custom_worker:runtime.worker=NativeClaude(runtime.control)
    profile=dict(s['worker'],native_workspace=ctx['workspace'],native_session=ctx['session'],native_resume=ctx['started'],step_seconds=600)
    try:
        _,value=runtime._invoke(task,runtime.state(task)[0],s,'delivery_review_'+node['id'],ctx['prompt'],schema,profile)
    except NativeTurnLimit as limit:
        from .usage import record
        record(s,limit.attempt_id,[limit.usage],profile['provider'],profile['model'])
        s['pending']=None;s.pop('pending_solution_context',None);ctx['started']=True;ctx['continuations']+=1
        if ctx['continuations']>2:raise LedgerError('Review continuation bound exhausted; evidence retained.')
        return None
    ctx['started']=True
    ids=[a['id'] for a in ctx['criteria']];checks=value.get('checks',[])
    good=bool(ids) and value.get('verdict')=='accept' and value.get('unresolved_required')==[] and sorted(c.get('id','') for c in checks)==sorted(ids)
    for check in checks:
        criterion=next((a for a in ctx['criteria'] if a['id']==check.get('id')),None)
        expected={ctx['refs'][n] for n in criterion['nodes']} if criterion else set()
        good=good and check.get('status')=='passed' and expected<=set(check.get('evidence_refs',[]))<=set(ctx['refs'].values())
    return {'passed':bool(good),'source':s['delivery']['source']['hash'],'verdict':value,'failure_kind':'review','detail':value.get('feedback','Invalid review result')}


def build(runtime,task,s,node,row):
    c=node['config'];directory=home(runtime,task)/('build-'+uuid.uuid4().hex[:10])
    work=capture(runtime.ledger.project,s['delivery']['source'],directory,s['plan']['source_roots'])
    argv=dart_argv(c['flutter_root'])+['build','apk','--'+c['variant'],'--no-pub']
    private=None
    if c['config_reference']:
        private=Path(c['config_reference'])
        if not private.is_file():raise LedgerError('Private build configuration is unavailable.')
        # Private fingerprint stays in the executor; only operator-provided opaque version is public.
        digest=file_hash(private);argv+=['--dart-define-from-file='+str(private)]
    package=work/c['package']
    rc,out,err=bounded(runtime,task,argv,package,c['timeout_seconds'],{'ANDROID_HOME':c['android_sdk'],'ANDROID_SDK_ROOT':c['android_sdk'],
        'FLUTTER_SUPPRESS_ANALYTICS':'true','DART_SUPPRESS_ANALYTICS':'true'})
    if private and file_hash(private)!=digest:raise LedgerError('Private configuration changed during build.')
    from .monitor import safe
    log=home(runtime,task)/(node['id']+'-'+str(row['generation'])+'.build.txt')
    logs=out+'\n'+err
    if private:
        values=json.loads(private.read_text(encoding='utf-8-sig'))
        if isinstance(values,dict):
            for value in values.values():
                if isinstance(value,str) and value: logs=logs.replace(value,'[private]')
    durable_write(log,safe(logs,100000).encode())
    apk=package/'build/app/outputs/flutter-apk'/('app-'+c['variant']+'.apk')
    if rc or not apk.is_file():return {'passed':False,'failure_kind':'environment','detail':'Build failed; inspect '+str(log),'exit_code':rc,'log':str(log)}
    from .android_build import verify_apk
    verified=verify_apk(apk)
    return {'passed':True,'source':s['delivery']['source']['hash'],'variant':c['variant'],'config_version':c['config_version'],
            'recipe_hash':content_hash(c),'toolchain':s['delivery']['preflight']['tools'],
            'apk':str(apk),'sha256':file_hash(apk),'bytes':apk.stat().st_size,'log':str(log),'zip':verified}


def execute(runtime,task,s,node,row):
    permission={'build':'android.build','apk_audit':'android.build','device':'android.device',
                'regression':'native.test','review':'discover','handover':'report'}[node['kind']]
    if permission not in runtime.ledger.task(task,full=True)['handoff']['grant']['permissions']:
        raise LedgerError('Delivery operation exceeds the dispatch grant.')
    if node['kind']=='regression':return regression(runtime,task,s,node,row)
    if node['kind']=='review':return review(runtime,task,s,node,row)
    if node['kind']=='build':return build(runtime,task,s,node,row)
    if node['kind']=='apk_audit':
        from .delivery_android import audit
        return audit(runtime,task,s,node)
    if node['kind']=='device':
        from .delivery_android import device
        return device(runtime,task,s,node,row)
    if node['kind']=='handover':
        from .monitor import safe
        def public(value):
            if isinstance(value,dict):return {k:public(v) for k,v in value.items()}
            if isinstance(value,list):return [public(v) for v in value]
            return safe(value,10000) if isinstance(value,str) else value
        report={'task':task,'solution':runtime.ledger.task(task,full=True)['handoff']['solution_id'],
            'plan_hash':content_hash(s['plan']),'source':s['delivery']['source']['hash'],
            'acceptance':s['delivery']['criteria'],'nodes':{k:{'phase':v['phase'],'child':v['child'],'receipt':v['receipt']} for k,v in s['delivery']['nodes'].items() if k!=node['id']},
            'repairs':s['delivery']['repairs'],'history':s['delivery']['history'],
            'technical_verified':True,'product_acceptance':'not_requested',
            'budget':runtime.control.status(task)['budget'],'assistance':s.get('assistance','unknown'),
            'limits':'Only sealed criteria/scenarios verified. Windows delivery receipt is separate; shown is not user attention.'}
        text=json.dumps(public(report),ensure_ascii=False,indent=2)
        path=home(runtime,task)/('handover-'+str(s['delivery']['generation'])+'.txt')
        durable_write(path,text.encode('utf-8'));s['report']=text;s['report_file']=str(path)
        return {'passed':True,'report':str(path),'sha256':file_hash(path),'source':s['delivery']['source']['hash']}
    raise LedgerError('Unsupported delivery operation.')
