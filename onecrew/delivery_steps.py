"""Typed, operator-sealed native delivery operations and artifact provenance."""
import copy
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import time
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
    # Native tools also need short paths; extended Python paths alone are insufficient.
    configured=os.environ.get('ONECREW_DELIVERY_ROOT')
    base=Path(configured) if configured else (
        Path(Path(__file__).resolve().anchor)/'ocd' if os.name=='nt'
        else Path(__file__).resolve().parents[1]/'.onecrew'/'delivery')
    if not base.is_absolute():raise LedgerError('ONECREW_DELIVERY_ROOT must be absolute.')
    root=base/content_hash({'state':str(Path(runtime.ledger.state_root).resolve()),'task':task})[:20]
    try:root.mkdir(parents=True,exist_ok=True)
    except OSError as e:raise LedgerError('Delivery workspace unavailable; configure writable short ONECREW_DELIVERY_ROOT.') from e
    return root


def check_capture_paths(destination, manifest):
    if os.name!='nt':return
    for name in manifest['files']:
        target=Path(destination)/name
        if len(str(target))>259 or len(str(target.parent))>247:
            raise LedgerError('Windows delivery path too long ('+str(len(str(target)))+
                              ' chars): '+name+'; configure a shorter ONECREW_DELIVERY_ROOT. No capture started.')


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
    check_capture_paths(destination,manifest)
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
    from urllib.parse import urlparse
    from urllib.request import url2pathname
    project=Path(project).resolve();destination=Path(destination).resolve()
    captured=sorted((safe_file(project,r).resolve() for r in roots),key=lambda p:len(p.parts),reverse=True)
    def mapped(path):
        path=Path(path).resolve()
        for base in captured:
            if path.is_relative_to(base):
                return safe_file(destination,path.relative_to(project).as_posix())
        return path
    for root in roots:
        src=safe_file(project,root+'/.dart_tool/package_config.json')
        out=safe_file(destination,root+'/.dart_tool/package_config.json')
        if out.exists():
            config=json.loads(out.read_text(encoding='utf-8'))
            for package in config['packages']:
                absolute=urljoin(src.as_uri(),package['rootUri']);parsed=urlparse(absolute)
                if parsed.scheme!='file' or parsed.netloc not in ('','localhost'):
                    raise LedgerError('Only local package dependencies can be captured.')
                package['rootUri']=mapped(Path(url2pathname(parsed.path))).as_uri()+'/'
            durable_write(out,canonical(config).encode())
        # Gradle/CMake uses Flutter's native plugin graph, independently of Dart.
        plugins=safe_file(destination,root+'/.flutter-plugins-dependencies')
        if plugins.exists():
            value=json.loads(plugins.read_text(encoding='utf-8'))
            for entries in value.get('plugins',{}).values():
                for plugin in entries:
                    old=Path(plugin['path'])
                    plugin['path']=str(mapped(old if old.is_absolute() else safe_file(project,root)/old))+os.sep
            durable_write(plugins,canonical(value).encode())
        for leaf in ('pubspec.yaml','pubspec_overrides.yaml'):
            out=safe_file(destination,root+'/'+leaf)
            if not out.exists():continue
            package_root=safe_file(project,root)
            def local(token):
                old=Path(token);return mapped(old if old.is_absolute() else package_root/old).as_posix()
            durable_write(out,rebase_pubspec(out.read_text(encoding='utf-8'),local).encode())


DEPENDENCY_SECTIONS=('dependencies','dev_dependencies','dependency_overrides')
_UNSUPPORTED='Unsupported YAML path dependency; explicit reconciliation required.'


def _scalar(raw):
    token=raw.strip();quote=token[:1] if token[:1] in ('"',"'") else ''
    if quote:
        if len(token)<2 or not token.endswith(quote):raise LedgerError(_UNSUPPORTED)
        return json.loads(token) if quote=='"' else token[1:-1].replace("''","'")
    if any(x in token for x in (' #','{','}','[',']','&','*','|','>')):raise LedgerError(_UNSUPPORTED)
    return token


def rebase_pubspec(text,local):
    """Rewrite only `path:` sources of local dependencies, judged by YAML block structure.

    A package named `path`, git `path:` subdirectories, hosted/sdk entries and keys outside the
    dependency sections keep their text. Flow mappings or odd indentation inside a dependency
    section fail closed rather than being guessed."""
    out=[];section=False;name_indent=None;source_indent=None;in_dependency=False
    for line in text.splitlines(keepends=True):
        body=line.rstrip('\r\n');stripped=body.strip()
        if not stripped or stripped.startswith('#'):out.append(line);continue
        indent=len(body)-len(body.lstrip(' \t'))
        if '\t' in body[:indent]:
            if section:raise LedgerError(_UNSUPPORTED)
            out.append(line);continue
        key=re.match(r'([A-Za-z0-9_.\-]+)[ \t]*:(?:[ \t]+(.*))?$',stripped)
        if indent==0:
            section=bool(key) and key[1] in DEPENDENCY_SECTIONS and not (key[2] or '').split('#')[0].strip()
            name_indent=source_indent=None;in_dependency=False;out.append(line);continue
        if not section:out.append(line);continue
        if not key:raise LedgerError(_UNSUPPORTED)
        value=(key[2] or '').strip()
        if name_indent is None:name_indent=indent
        if indent<name_indent:raise LedgerError(_UNSUPPORTED)
        if indent==name_indent:
            # Dependency name: `name: ^1.0` (hosted constraint, even when name is `path`) or a block.
            if value.startswith('{') and re.search(r'\bpath\b',value):raise LedgerError(_UNSUPPORTED)
            in_dependency=not value or value.startswith('#');source_indent=None
            out.append(line);continue
        if not in_dependency:raise LedgerError(_UNSUPPORTED)
        if source_indent is None:source_indent=indent
        if indent==source_indent and key[1]=='path':
            # Direct source key of a dependency: the local path. Deeper keys (git.path) are untouched.
            ending=line[len(body):]
            out.append(body[:indent]+'path: '+json.dumps(local(_scalar(value)))+ending);continue
        out.append(line)
    return ''.join(out)


def validate_config(kind,c,roots):
    fields={
        'regression':({'package','flutter_root','tests','red'}, {'repair_node'}),
        'review':(set(),{'repair_node'}),
        'build':({'package','flutter_root','android_sdk','variant','config_reference','config_version','signer_sha256','timeout_seconds'},set()),
        'apk_audit':({'build_node','build_tools','package_id','signer_sha256','require_16kb','max_bytes'},{'version_code'}),
        'device':({'build_node','adb','serial','package_id','scenario','scenario_sha256','private_reference','private_version','timeout_seconds'},
                  {'repair_node','replay_safe','valid_until','optional','emulator','calibration','selectors','recovery'})}
    required,optional=fields[kind]
    if set(c)-required-optional or required-set(c): raise LedgerError('Invalid '+kind+' recipe fields.')
    if 'repair_node' in c and not isinstance(c['repair_node'],str): raise LedgerError('Explicit repair node required.')
    for flag in ('replay_safe','optional'):
        if flag in c and type(c[flag]) is not bool: raise LedgerError(flag+' must be a boolean.')
    if 'valid_until' in c:
        try:dt.datetime.fromisoformat(c['valid_until'])
        except (TypeError,ValueError) as e:raise LedgerError('Device permission valid_until must be ISO-8601.') from e
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
        if 'calibration' in c and c['calibration']!='onecrew': raise LedgerError('Only OneCrew calibration of its own scenario is supported.')
        if 'emulator' in c:
            from .delivery_device_env import validate_emulator
            validate_emulator(c['emulator'],c['serial'])
        if 'recovery' in c:
            from .delivery_device_env import validate_recovery
            validate_recovery(c['recovery'],c['serial'])
        if c.get('selectors') not in (None,'exact','tiered'): raise LedgerError('Device selectors must be exact or tiered.')
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
            # A killed tool may still hold its stream for a moment; cleanup must never turn a result into a failure.
            for _ in range(5):
                try:path.unlink(missing_ok=True);break
                except OSError:time.sleep(.2)


def dart_argv(sdk):
    sdk=Path(sdk)
    dart=sdk/'bin/cache/dart-sdk/bin'/('dart.exe' if os.name=='nt' else 'dart')
    return [str(dart),'--packages='+str(sdk/'packages/flutter_tools/.dart_tool/package_config.json'),
            str(sdk/'bin/cache/flutter_tools.snapshot'),'--no-version-check']


def preflight(runtime,task,s,source):
    check_capture_paths(home(runtime,task)/('baseline-'+'0'*10),source)
    tools={};references=[];devices_missing=False;boot_at_stage=False
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
            if c.get('emulator'):
                # The approved emulator is booted at its stage; its executable and AVD must exist now.
                from .delivery_device_env import emulator_executable
                paths.append(emulator_executable(c['adb']))
                avd=Path(c['emulator']['avd_home'] or Path.home()/'.android'/'avd')/(c['emulator']['avd']+'.ini')
                if not avd.is_file():raise LedgerError('Approved emulator AVD unavailable: '+c['emulator']['avd'])
        for path in paths:
            if not path.is_file():raise LedgerError('Pinned tool unavailable: '+str(path))
            tools[str(path.resolve())]=file_hash(path)
        if kind=='device':
            from .delivery_android import PermissionExpired,permission_left
            try:window=permission_left(c)
            except PermissionExpired:
                # No device command outside the approved window; optional E2E is reported not run at its node.
                if not c.get('optional'):raise
                devices_missing=True;continue
            from .delivery_device_env import ensure_server
            ensure_server(c['adb'])
            rc,out,_=bounded(runtime,task,[c['adb'],'-s',c['serial'],'get-state'],home(runtime,task),min(15,window))
            if (rc or out.strip()!='device') and c.get('emulator'):
                boot_at_stage=True  # OneCrew boots the approved emulator when the stage runs
            elif rc or out.strip()!='device':
                # Optional E2E is re-checked at its node and reported as not run; required E2E stops before any call.
                if not c.get('optional'):raise LedgerError('Pinned Android device unavailable at preflight.')
                devices_missing=True
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
    return {'tools':tools,'source':source['hash'],'disk_required_bytes':needed,'private_references_available':len(references),
            'optional_device_missing':devices_missing,'emulator_boot_at_stage':boot_at_stage}


def interrupted(runtime,task,s,node,row):
    """Class of a node that ended without a receipt: replay-safe capture work, or a possible device effect."""
    if node['kind']=='device':
        from .delivery_android import effects_started
        return 'side_effect_unknown' if effects_started(runtime,task,node,row) else 'interrupted'
    return 'interrupted'


def check_tools(preflight_receipt):
    if any(not Path(path).is_file() or file_hash(path)!=digest for path,digest in preflight_receipt['tools'].items()):
        raise LedgerError('Pinned toolchain/scenario changed after preflight.')


def parse_tests(out,code):
    tests={};results={};errors=[];done=None;prints={}
    for line in out.splitlines():
        try: v=json.loads(line)
        except ValueError: continue
        if not isinstance(v,dict): continue
        if v.get('type')=='testStart': tests[v['test']['id']]=v['test']['name']
        elif v.get('type')=='testDone' and not v.get('hidden'): results[v['testID']]=v
        elif v.get('type')=='print':
            # testWidgets reports the real assertion through print events; the error event only says "see logs above".
            text=prints.setdefault(v.get('testID'),'')
            if len(text)<6000:prints[v.get('testID')]=text+str(v.get('message',''))[:3000]+'\n'
        elif v.get('type')=='error' and len(errors)<30:
            detail=str(v.get('error',''))
            logged=prints.get(v.get('testID'),'')
            errors.append({'name':tests.get(v.get('testID'),''),'error':((logged+detail) if logged else detail)[-3000:]})
        elif v.get('type')=='done': done=v.get('success')
    counts={'passed':sum(v.get('result')=='success' and not v.get('skipped') for v in results.values()),
            'failed':sum(v.get('result')!='success' for v in results.values()),'skipped':sum(bool(v.get('skipped')) for v in results.values())}
    return {'passed':code==0 and done is True and counts['passed']>0 and counts['failed']==0 and counts['skipped']==0,
            'counts':counts,'errors':errors,'exit_code':code,'runner_done':done}


def regression(runtime,task,s,node,row):
    c=node['config'];d=s['delivery'];directory=home(runtime,task)/('test-'+uuid.uuid4().hex[:10])
    work=capture(runtime.ledger.project,d['source'],directory,s['plan']['source_roots'])
    package=work/c['package']; tests_hash={t:file_hash(package/t) for t in c['tests']}
    # Test assets are built: Material widgets load shaders (e.g. ink_sparkle) when a test taps a button.
    argv=dart_argv(c['flutter_root'])+['test','--no-pub','--reporter','json']
    code,out,err=bounded(runtime,task,argv+c['tests'],package,600,{'CI':'true'})
    result=parse_tests(out,code)
    if result['runner_done'] is None and not sum(result['counts'].values()):
        # Asset bundling failed before any test ran: fall back to the previous asset-less run, and say so.
        argv=dart_argv(c['flutter_root'])+['test','--no-pub','--no-test-assets','--reporter','json']
        code,out,err=bounded(runtime,task,argv+c['tests'],package,600,{'CI':'true'})
        result=parse_tests(out,code);result['test_assets']=False
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
    owned={p for n in s['plan']['nodes'] if n['kind']=='change' for p in n['config']['recipe']['owned']}
    existing=[t for t in c['tests'] if c['package']+'/'+t not in owned]
    failing={e['name'] for e in result['errors'] if e['name'] and not e['name'].startswith('loading ')}
    if not result['passed'] and existing and failing and d.get('baseline_path'):
        # A read-only suite failing on the final source is only a product failure if it passes on the unchanged baseline.
        basework=home(runtime,task)/('base-'+uuid.uuid4().hex[:10]);baseline=Path(d['baseline_path'])
        shutil.copytree(baseline,basework);rebase_packages(baseline,basework,s['plan']['source_roots'])
        bc,bo,_=bounded(runtime,task,argv+existing,basework/c['package'],600,{'CI':'true'})
        base=parse_tests(bo,bc)
        before={e['name'] for e in base['errors'] if e['name'] and not e['name'].startswith('loading ')}
        result['baseline_check']={'tests':existing,'counts':base['counts'],'failing_on_baseline':sorted(before&failing)}
        if failing<=before:
            result['failure_kind']='environment'
            result['environment_detail']=('Existing tests fail on the unchanged baseline too (test environment, not the change): '+
                                          '; '.join(sorted(failing))[:600])
    result['detail']=canonical({'counts':result['counts'],'errors':result['errors'],'red':result['red'],
                                'baseline_check':result.get('baseline_check')})
    if result.get('environment_detail'):result['detail']=result['environment_detail']+' '+result['detail'][:1500]
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
    prompt=ctx['prompt']+(('\nYour previous answer did not follow the evidence protocol: '+ctx['protocol_feedback']+
                           ' Return the complete review again.') if ctx.get('protocol_feedback') else '')
    try:
        _,value=runtime._invoke(task,runtime.state(task)[0],s,'delivery_review_'+node['id']+'_'+str(ctx.get('protocol_rounds',0)),prompt,schema,profile)
    except NativeTurnLimit as limit:
        from .usage import record
        record(s,limit.attempt_id,[limit.usage],profile['provider'],profile['model'])
        s['pending']=None;s.pop('pending_solution_context',None);ctx['started']=True;ctx['continuations']+=1
        if ctx['continuations']>2:raise LedgerError('Review continuation bound exhausted; evidence retained.')
        return None
    ctx['started']=True
    ids=[a['id'] for a in ctx['criteria']];checks=value.get('checks',[])
    judged=bool(ids) and value.get('verdict')=='accept' and value.get('unresolved_required')==[] and sorted(c.get('id','') for c in checks)==sorted(ids)
    good=judged;protocol=[]
    known=set(ctx['refs'].values())
    for check in checks:
        criterion=next((a for a in ctx['criteria'] if a['id']==check.get('id')),None)
        expected={ctx['refs'][n] for n in criterion['nodes']} if criterion else set()
        cited=set(check.get('evidence_refs',[]))
        good=good and check.get('status')=='passed' and expected<=cited<=known
        if check.get('status')=='passed':
            if not expected<=cited:protocol.append(check.get('id','')+': cite the receipt refs '+','.join(sorted(expected)))
            if not cited<=known:protocol.append(check.get('id','')+': only these receipt refs exist: '+','.join(sorted(known))+'; do not cite snapshots or other hashes')
    if judged and not good and protocol and all(c.get('status')=='passed' for c in checks) and ctx.get('protocol_rounds',0)<2:
        # The reviewer accepted every criterion but cited evidence wrongly: a protocol defect for the reviewer, never a code repair.
        ctx['protocol_rounds']=ctx.get('protocol_rounds',0)+1;ctx['protocol_feedback']='; '.join(protocol)[:1500]
        return None
    return {'passed':bool(good),'source':s['delivery']['source']['hash'],'verdict':value,
            'failure_kind':'review' if not (judged and protocol) else 'review_protocol','detail':value.get('feedback','Invalid review result')}


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
        d=s['delivery'];nodes=d['nodes']
        evidence=[]
        for a in s['plan']['acceptance']:
            rows=[{'node':n,'phase':nodes[n]['phase'],'receipt':content_hash(nodes[n]['receipt']) if nodes[n].get('receipt') else None,
                   'skipped':(nodes[n].get('receipt') or {}).get('skipped')} for n in a['nodes']]
            status='passed' if all(r['phase']=='passed' and not r['skipped'] for r in rows) else 'not_run' if any(r['skipped'] for r in rows) else d['criteria'].get(a['id'],'pending')
            evidence.append({'id':a['id'],'text':a['text'],'status':status,'nodes':rows})
        gaps=[]
        for n in s['plan']['nodes']:
            r=nodes[n['id']].get('receipt') or {}
            if n['kind']=='regression':
                if not r.get('red'):gaps.append('red: not verified (no behavioural red declared)')
                if (r.get('counts') or {}).get('skipped'):gaps.append(n['id']+': '+str(r['counts']['skipped'])+' skipped test(s)')
            if r.get('skipped'):gaps.append(n['id']+': not run ('+str(r.get('detail'))[:200]+')')
            cleanup=(r.get('environment') or {}).get('emulator_cleanup')
            if cleanup in ('stop_failed','replaced_not_stopped','identity_lost_not_stopped'):
                gaps.append(n['id']+': the emulator OneCrew booted was not stopped ('+cleanup+')')
        dropped=(d.get('planning') or {}).get('stay_inside')
        if dropped:gaps.append('out-of-envelope needs dropped by user decision: '+'; '.join(str(n.get('need'))[:150] for n in dropped))
        if not any(n['kind']=='device' for n in s['plan']['nodes']):gaps.append('device E2E: not in plan')
        if not any(n['kind']=='build' for n in s['plan']['nodes']):gaps.append('APK build: not in plan')
        try:
            from .interventions import summary
            interventions=summary(runtime.ledger,[task]+[nodes[k]['child'] for k in nodes if nodes[k].get('child')])
        except (ImportError,ValueError,OSError):interventions='unavailable'
        report={'task':task,'solution':runtime.ledger.task(task,full=True)['handoff']['solution_id'],
            'plan_hash':content_hash(s['plan']),'plan_provenance':d.get('planning',{'mode':'entry'}),'source':d['source']['hash'],
            'acceptance':d['criteria'],'acceptance_evidence':evidence,'gaps':gaps,
            'nodes':{k:{'phase':v['phase'],'child':v['child'],'receipt':v['receipt']} for k,v in nodes.items() if k!=node['id']},
            'repairs':d['repairs'],'history':d['history'],
            'failures':[dict(signature=k,**{x:v.get(x) for x in ('class','node','count','status','detail')}) for k,v in d.get('failures',{}).items()],
            'automatic_recoveries':d.get('recoveries',[]),'escalations':d.get('escalations',[]),'interventions':interventions,
            'technical_verified':all(e['status']=='passed' for e in evidence),'product_acceptance':'not_requested',
            'budget':runtime.control.status(task)['budget'],'assistance':s.get('assistance','unknown'),
            'limits':'Only sealed criteria/scenarios verified. Windows delivery receipt is separate; shown is not user attention.'}
        text=json.dumps(public(report),ensure_ascii=False,indent=2)
        path=home(runtime,task)/('handover-'+str(s['delivery']['generation'])+'.txt')
        durable_write(path,text.encode('utf-8'));s['report']=text;s['report_file']=str(path)
        return {'passed':True,'report':str(path),'sha256':file_hash(path),'source':s['delivery']['source']['hash']}
    raise LedgerError('Unsupported delivery operation.')
