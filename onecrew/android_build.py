"""Fixed, operator-authorized Flutter debug builds from verified historical branches.

This is a native trusted-project build, not a worker shell or filesystem sandbox.
No source repairs, checkout, push, SDK installs, or license acceptance are performed.
"""
import argparse
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import re
import subprocess
import tarfile
import time
import zipfile
from types import SimpleNamespace

from .ledger import Ledger, LedgerError, canonical, content_hash, key_field, utcnow
from .integration import Integration
from .snapshots import durable_write
from .workflow import task_lock


def dependency_paths(text):
    """Conservative block-YAML path scalar reader; fail closed on unsupported forms."""
    paths=[]
    for line in text.splitlines():
        if line.lstrip().startswith('#'): continue
        if re.search(r'[{,]\s*path\s*:', line):
            raise LedgerError('Inline YAML path dependencies are unsupported; no build executed.')
        match=re.match(r'^\s+path:\s*(.*?)\s*$', line)
        if not match: continue
        value=match[1].split(' #',1)[0].strip()
        if value.startswith(('"', "'")) and value[-1:]==value[0]: value=value[1:-1]
        if not value or not re.fullmatch(r'[A-Za-z0-9_./ -]+',value) or value.startswith('/'):
            raise LedgerError('Unsupported relative dependency path.')
        paths.append(value)
    return paths


def yaml_blocks(text):
    """Read named two-space package blocks without interpreting arbitrary YAML tags."""
    blocks={};name=None
    for line in text.splitlines():
        if not line.strip() or line.lstrip().startswith('#'): continue
        match=re.fullmatch(r'  ([a-zA-Z0-9_]+):\s*',line)
        if match: name=match[1];blocks[name]=[]
        elif line.startswith('    ') and name: blocks[name].append(line)
        else: name=None
    return {k:'\n'.join(v) for k,v in blocks.items()}


def scalar(block, key):
    match=re.search(r'^\s+'+re.escape(key)+r':\s*([^\n]+)',block,re.M)
    return match[1].strip().strip('"\'') if match else None


def repository_identity(url):
    value=re.sub(r'^git@([^:]+):',r'https://\1/',url.strip())
    value=re.sub(r'^ssh://git@', 'https://', value)
    return value.removesuffix('.git').rstrip('/')


def extract_archive(raw, destination):
    """Only regular Git files/directories; reject traversal, links and expansion bombs."""
    if len(raw)>300_000_000: raise LedgerError('Git archive exceeds 300 MB.')
    with tarfile.open(fileobj=io.BytesIO(raw)) as archive:
        entries=archive.getmembers()
        if len(entries)>30000 or sum(m.size for m in entries)>300_000_000:
            raise LedgerError('Git tree exceeds build export limits.')
        for member in entries:
            parts=PurePosixPath(member.name).parts
            if (not parts or '..' in parts or member.name.startswith('/') or '\\' in member.name
                    or ':' in member.name or '.git' in parts or not (member.isfile() or member.isdir())):
                raise LedgerError('Unsupported Git archive member: '+member.name)
            target=destination.joinpath(*parts)
            if not target.resolve().is_relative_to(destination.resolve()): raise LedgerError('Archive escape.')
            if member.isdir(): target.mkdir(parents=True,exist_ok=True)
            else:
                target.parent.mkdir(parents=True,exist_ok=True)
                with archive.extractfile(member) as source: target.write_bytes(source.read())


def verify_apk(path):
    if not path.is_file(): raise LedgerError('Build exited without an APK.')
    with zipfile.ZipFile(path) as archive:
        names=set(archive.namelist())
        if not {'AndroidManifest.xml','classes.dex'} <= names or archive.testzip():
            raise LedgerError('APK failed package integrity verification.')
    digest=hashlib.sha256()
    with path.open('rb') as source:
        for chunk in iter(lambda:source.read(1024*1024),b''): digest.update(chunk)
    return {'path':str(path),'bytes':path.stat().st_size,'sha256':digest.hexdigest()}


class AndroidBuild:
    def __init__(self, ledger, run_command=None):
        from .sandbox_gate import command
        self.ledger=ledger;self.run_command=run_command or command

    def location(self, task, key):
        self.ledger.task(task);key_field(key)
        return self.ledger.state_root/'android-builds'/content_hash({'task':task,'key':key})[:24]

    def save(self, root, task, value):
        value['updated_at']=utcnow()
        durable_write(root/'receipt.json',canonical(value).encode())
        with self.ledger.transaction(write=True) as conn:
            self.ledger._task(conn,task)
            self.ledger._event(conn,task,'android.build',value)

    def status(self, task, key):
        path=self.location(task,key)/'receipt.json'
        if not path.is_file(): raise LedgerError('Unknown Android build request.')
        return json.loads(path.read_text(encoding='utf-8'))

    def git(self, root, *args):
        ledger=SimpleNamespace(project=root,state_root=self.ledger.state_root)
        return Integration(SimpleNamespace(ledger=ledger,store=None)).git('--no-optional-locks',*args)

    def prepare(self, root, source, commit, policy, guard, receipt):
        # The Store-Python ledger path is too long for Gradle/assets on Windows.
        # Keep reproducible build copies short; receipts still live in the ledger.
        boundary=source.parent.resolve(); workspace=Path.home()/'OneCrewBuilds'/root.name/'source'
        workspace.mkdir(parents=True)
        receipt['workspace']=str(workspace)
        timestamp=self.git(source,'show','-s','--format=%cI',commit).decode().strip()
        queue=[(source,commit)];seen=set()
        while queue:
            guard();repo,sha=queue.pop(0);repo=repo.resolve()
            if repo in seen: continue
            if len(seen)>=30: raise LedgerError('Dependency repository limit exceeded.')
            if not repo.is_relative_to(boundary): raise LedgerError('Dependency escapes source parent boundary.')
            if Path(self.git(repo,'rev-parse','--show-toplevel').decode().strip()).resolve()!=repo:
                raise LedgerError('Path dependency must be a repository root: '+str(repo))
            relative=repo.relative_to(boundary);destination=workspace/relative
            # Submodules and symlinks cannot silently disappear from a successful export.
            tree=self.git(repo,'ls-tree','-r',sha).decode()
            if any(line.startswith(('160000 ','120000 ')) for line in tree.splitlines()):
                raise LedgerError('Build export does not support submodules or symlinks: '+str(repo))
            extract_archive(self.git(repo,'archive','--format=tar',sha),destination)
            seen.add(repo)
            receipt['repositories'].append({'source':str(repo),'commit':sha,'export':str(destination)})
            pubspec=destination/'pubspec.yaml'
            if not pubspec.is_file(): raise LedgerError('Missing pubspec.yaml in '+str(repo))
            for value in dependency_paths(pubspec.read_text(encoding='utf-8-sig')):
                dep=(repo/value).resolve()
                if dep==repo or dep in seen: continue
                if not dep.is_relative_to(boundary): raise LedgerError('Dependency escapes source parent boundary.')
                if policy=='as-of':
                    dep_sha=self.git(dep,'log','--first-parent','-1','--format=%H','--before='+timestamp,'HEAD','--').decode().strip()
                else: dep_sha=self.git(dep,'rev-parse','HEAD').decode().strip()
                if not re.fullmatch(r'[a-f0-9]{40}|[a-f0-9]{64}',dep_sha):
                    raise LedgerError('No dependency revision available for '+str(dep))
                queue.append((dep,dep_sha))
        return workspace/source.relative_to(boundary)

    def pin_git_dependencies(self, project, source, commit, boundary, guard, receipt):
        """Recover missing Git lock identities from local repos in explicit operator scope."""
        packages=yaml_blocks((project/'pubspec.yaml').read_text(encoding='utf-8-sig'))
        lock=project/'pubspec.lock';locked=yaml_blocks(lock.read_text(encoding='utf-8-sig')) if lock.exists() else {}
        pins={};missing={};candidates={}
        for name,block in packages.items():
            if not re.search(r'^    git:\s*$',block,re.M): continue
            url=scalar(block,'url');ref=scalar(block,'ref');version=scalar(block,'version')
            if not url or not re.fullmatch(r'https://[^\s@]+',url): raise LedgerError('Unsupported dependency URL.')
            pin=scalar(locked.get(name,''),'resolved-ref') if scalar(locked.get(name,''),'url')==url else None
            explicit=bool(ref and re.fullmatch(r'[a-f0-9]{40}|[a-f0-9]{64}',ref))
            if explicit: pin=ref
            if pin: pins[name]={'url':url,'ref':pin,'reason':'historical lockfile'}
            else: missing[name]={'url':url,'version':version}
            if not explicit: candidates[name]={'url':url,'version':version}
        if not missing and not boundary: return
        if not boundary: raise LedgerError('Unpinned Git dependency needs --dependency-root: '+', '.join(missing))
        boundary=Path(boundary).resolve()
        if not source.resolve().is_relative_to(boundary): raise LedgerError('Dependency root must contain the source repository.')
        timestamp=self.git(source,'show','-s','--format=%cI',commit).decode().strip();count=0
        for directory,dirs,_ in os.walk(boundary,followlinks=False):
            guard();count+=1
            if count>2000: raise LedgerError('Dependency repository discovery exceeds 2000 directories.')
            path=Path(directory)
            dirs[:]=[d for d in dirs if d.lower() not in ('.git','.dart_tool','build','node_modules','.venv')
                     and not (path/d).is_symlink() and not (hasattr(path/d,'is_junction') and (path/d).is_junction())]
            if not (path/'.git').exists(): continue
            receipt.setdefault('dependency_repositories_checked',[]).append(str(path))
            try: urls=self.git(path,'remote','-v').decode()
            except LedgerError: continue
            for name,item in list(candidates.items()):
                if repository_identity(item['url']) not in [repository_identity(line.split()[1]) for line in urls.splitlines() if len(line.split())>=2]: continue
                sha=self.git(path,'log','--first-parent','-1','--format=%H','--before='+timestamp,'HEAD','--').decode().strip()
                if not sha: continue
                pub=self.git(path,'show',sha+':pubspec.yaml').decode('utf-8-sig')
                version=re.search(r'^version:\s*["\']?([^\s"\']+)',pub,re.M)
                if item['version'] and (not version or version[1]!=item['version']):
                    receipt.setdefault('dependency_mismatches',[]).append({'package':name,'repository':str(path),
                        'commit':sha,'required':item['version'],'found':version[1] if version else None})
                    raise LedgerError('Historical local version constraint mismatch for '+name)
                pins[name]={'url':item['url'],'ref':sha,'reason':'local first-parent as-of app commit',
                            'repository':str(path),'version':version[1] if version else None}
                missing.pop(name,None);del candidates[name]
            if not candidates: break
        receipt['git_dependency_pins']=pins
        if missing: raise LedgerError('No matching historical local revision for: '+', '.join(missing))
        override=project/'pubspec_overrides.yaml'
        if override.exists(): raise LedgerError('Existing historical pubspec_overrides.yaml requires explicit reconciliation.')
        original=(project/'pubspec.yaml').read_text(encoding='utf-8-sig')
        overrides=re.search(r'^dependency_overrides:[ \t]*\n(.*?)(?=^\S|\Z)',original,re.M|re.S)
        lines=['# OneCrew build-only pins; application source is unchanged.','dependency_overrides:']
        if overrides:
            if set(pins)&set(yaml_blocks(overrides[1])):
                raise LedgerError('Existing dependency override conflicts with historical Git pins.')
            lines.extend(overrides[1].rstrip().splitlines())
        for name,pin in pins.items():
            lines += ['  '+name+':','    git:','      url: '+json.dumps(pin['url']),'      ref: '+json.dumps(pin['ref'])]
        override.write_text('\n'.join(lines)+'\n',encoding='utf-8')
        receipt['build_only_override']=str(override)

    def build(self, *args, **kwargs):
        # Shared across projects and both foreground/background entry points.
        task=kwargs.get('task',args[0] if args else None)
        key=kwargs.get('key',args[1] if len(args)>1 else None)
        if (self.location(task,key)/'job.json').exists():
            raise LedgerError('Build key belongs to a background job; use android status.')
        with task_lock(self.ledger, 'android.capacity'):
            return self._build(*args, **kwargs)

    def _build(self, task, key, flutter_root, android_sdk, *, max_seconds=1200, dependency_policy='as-of', native_authorized=False, dependency_root=None, external_guard=None):
        if not native_authorized: raise LedgerError('Explicit trusted native build authorization required.')
        if type(max_seconds) is not int or not 10<=max_seconds<=1800: raise LedgerError('Build limit must be 10-1800 seconds.')
        if dependency_policy not in ('as-of','head'): raise LedgerError('Unknown dependency policy.')
        flutter_root=Path(flutter_root).resolve();android_sdk=Path(android_sdk).resolve()
        root=self.location(task,key)
        request={'task':task,'key':key,'flutter_root':str(flutter_root),'android_sdk':str(android_sdk),
                 'max_seconds':max_seconds,'dependency_policy':dependency_policy,'native_authorized':True,
                 'dependency_root':str(Path(dependency_root).resolve()) if dependency_root else None}
        with task_lock(self.ledger,'android.'+root.name):
            if (root/'receipt.json').exists():
                old=self.status(task,key)
                if old['request']!=request: raise LedgerError('Build request key conflicts with prior configuration.')
                if old['status']=='succeeded' and verify_apk(Path(old['apk']['path']))!=old['apk']:
                    raise LedgerError('APK changed after successful build receipt.')
                # Interrupted builds never replay implicitly or become successful from stale artifacts.
                return old
            from .owned import Owned
            from .git_history import History
            runtime=Owned(self.ledger);state=runtime.state(task)[1]
            profile=runtime.control.status(task)['configuration']['profile']
            owned_recipe=profile.get('android_build')
            active_owned=bool(owned_recipe and state and state['phase'] in ('running','waiting_operation'))
            if not state or (state['phase']!='completed' and not active_owned) or len(state.get('branches',[]))!=1:
                raise LedgerError('Build needs one completed or recipe-authorized active historical branch receipt.')
            if owned_recipe:
                if any(request[k]!=owned_recipe[k] for k in owned_recipe if k!='queue_seconds'):
                    raise LedgerError('Build request differs from the owned job recipe grant.')
            branch=state['branches'][0]['result']
            history=History(runtime,task,profile,branch['directory'])
            if not history.observe_branch(branch)['verified']: raise LedgerError('Historical branch moved; build refused.')
            root.mkdir(parents=True,exist_ok=True)
            receipt={'request':request,'status':'preparing','branch':branch,'repositories':[],
                     'isolation':'separate source copy; native process tree; NOT filesystem sandbox',
                     'logs':str(root),'apk':None,'started_at':utcnow()}
            self.save(root,task,receipt);deadline=time.monotonic()+max_seconds
            def guard():
                if external_guard: external_guard()
                if owned_recipe:
                    from .sandbox_gate import task_guard
                    task_guard(runtime.control,task)()
                if self.ledger.requests(task,pending=True): raise LedgerError('Required user input is pending; build stopped without approval.')
                if time.monotonic()>=deadline: raise LedgerError('Android build deadline exceeded.')
                if runtime.control.status(task)['cancel_requested']: raise LedgerError('Android build cancelled.')
            try:
                guard()
                dart=flutter_root/'bin/cache/dart-sdk/bin/dart.exe'
                snapshot=flutter_root/'bin/cache/flutter_tools.snapshot'
                packages=flutter_root/'packages/flutter_tools/.dart_tool/package_config.json'
                if not all(p.is_file() for p in (dart,snapshot,packages)) or not android_sdk.is_dir():
                    raise LedgerError('Installed Flutter tool snapshot / Android SDK unavailable.')
                project=self.prepare(root,history.root,branch['commit'],dependency_policy,guard,receipt)
                if dependency_policy=='as-of':
                    self.pin_git_dependencies(project,history.root,branch['commit'],dependency_root,guard,receipt)
                if not (project/'android').is_dir(): raise LedgerError('Historical project has no Android platform.')
                # Host-local SDK configuration only in disposable export; original source stays untouched.
                local=project/'android/local.properties'
                local.write_text('sdk.dir='+android_sdk.as_posix()+'\nflutter.sdk='+flutter_root.as_posix()+'\n',encoding='utf-8')
                environment={'ANDROID_HOME':str(android_sdk),'ANDROID_SDK_ROOT':str(android_sdk),
                             'FLUTTER_ROOT':str(flutter_root),'CI':'true','FLUTTER_SUPPRESS_ANALYTICS':'true',
                             'DART_SUPPRESS_ANALYTICS':'true'}
                if os.environ.get('JAVA_HOME'): environment['JAVA_HOME']=os.environ['JAVA_HOME']
                receipt.update(status='building',build_directory=str(project));self.save(root,task,receipt)
                argv=[str(dart),'--packages='+str(packages),str(snapshot),'--no-version-check','build','apk','--debug']
                code,out,err=self.run_command(argv,project,max(1,int(deadline-time.monotonic())),guard,environment_extra=environment)
                durable_write(root/'stdout.log',out.encode());durable_write(root/'stderr.log',err.encode())
                receipt.update(exit_code=code,stdout_tail=out[-6000:],stderr_tail=err[-3000:])
                guard()
                if code: raise LedgerError('Flutter build failed; see stdout.log and stderr.log.')
                receipt['apk']=verify_apk(project/'build/app/outputs/flutter-apk/app-debug.apk')
                receipt['status']='succeeded'
            except (ValueError,OSError,tarfile.TarError,zipfile.BadZipFile,subprocess.SubprocessError) as error:
                receipt.update(status='blocked',error=str(error))
            self.save(root,task,receipt)
            return receipt


def main(argv=None):
    parser=argparse.ArgumentParser()
    parser.add_argument('--project',type=Path,default=Path.cwd());parser.add_argument('--state-root',type=Path)
    sub=parser.add_subparsers(dest='group',required=True).add_parser('android').add_subparsers(dest='command',required=True)
    for name in ('build','status','cancel'):
        command=sub.add_parser(name);command.add_argument('--from-task',required=True);command.add_argument('--key',required=True)
        if name=='build':
            command.add_argument('--flutter-root',type=Path,required=True);command.add_argument('--android-sdk',type=Path,required=True)
            command.add_argument('--max-seconds',type=int,default=1200);command.add_argument('--dependency-policy',choices=['as-of','head'],default='as-of')
            command.add_argument('--allow-trusted-native-build',action='store_true')
            command.add_argument('--dependency-root',type=Path)
            command.add_argument('--foreground',action='store_true',help='Wait here instead of dispatching.')
            command.add_argument('--terminal',action='store_true')
            command.add_argument('--queue-seconds',type=int,default=1800)
    args=parser.parse_args(argv)
    try:
        builder=AndroidBuild(Ledger(args.project,args.state_root))
        from .android_jobs import dispatch, status, cancel
        if args.command=='status': result=status(builder.ledger,args.from_task,args.key)
        elif args.command=='cancel': result=cancel(builder.ledger,args.from_task,args.key)
        else:
            options=dict(max_seconds=args.max_seconds,dependency_policy=args.dependency_policy,
                         native_authorized=args.allow_trusted_native_build,dependency_root=args.dependency_root)
            if args.foreground:
                if args.terminal: parser.error('--terminal requires background dispatch.')
                result=builder.build(args.from_task,args.key,args.flutter_root,args.android_sdk,**options)
            else:
                result=dispatch(builder.ledger,args.from_task,args.key,args.flutter_root,args.android_sdk,
                                queue_seconds=args.queue_seconds,**options)
                if args.terminal:
                    from .monitor import open_terminal
                    try: result['terminal']=open_terminal(builder.ledger)
                    except (ValueError,OSError) as error:
                        result['terminal']={'status':'unavailable','error':str(error),'runner_unaffected':True}
        print(json.dumps(result,ensure_ascii=False,indent=2))
        return 2 if result['status'] in ('blocked','interrupted','unknown') else 0
    except (ValueError,OSError) as error:
        print(json.dumps({'error':str(error)},ensure_ascii=False));return 2
