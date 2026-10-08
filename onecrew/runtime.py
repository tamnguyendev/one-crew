"""Bounded local controller. Models propose; this process owns authority and gates."""
from __future__ import annotations
import argparse
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import signal
import subprocess
import sys
import time
import uuid
import zipfile

from .profiles import AC, FILES, CONTRACT, POLICY, PLAN_SCHEMA, ARTIFACT_SCHEMA, REVIEW_SCHEMA, canonical, route, validate_plan

TERMINAL = {'ready_for_review','failed','blocked','cancelled','budget_exhausted','interrupted'}
ALLOWED = {p for paths in FILES.values() for p in paths}

class Halt(Exception):
    def __init__(self, status, reason): super().__init__(reason); self.status = status

def digest(data): return hashlib.sha256(data if isinstance(data,bytes) else data.encode('utf-8')).hexdigest()
def now(): return dt.datetime.now(dt.timezone.utc).isoformat()
def validate_schema(value, schema):
    kind=schema['type']
    if kind=='object':
        if not isinstance(value,dict) or set(value)!=set(schema['required']): raise ValueError('Unexpected/missing structured output fields.')
        for key,item in value.items(): validate_schema(item,schema['properties'][key])
    elif kind=='array':
        if not isinstance(value,list): raise ValueError('Expected structured array.')
        for item in value: validate_schema(item,schema['items'])
    elif kind=='string':
        if not isinstance(value,str): raise ValueError('Expected structured string.')
        if 'enum' in schema and value not in schema['enum']: raise ValueError('Structured value outside allowed choices.')

def save(path, value):
    path = Path(path); path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + '.tmp')
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')
    # Windows readers/AV may briefly open the destination without delete sharing.
    # Retry the atomic replace, never truncate the last valid state for readers.
    for attempt in range(10):
        try:
            os.replace(temporary, path)
            break
        except PermissionError:
            if attempt==9: raise
            time.sleep(.02*(attempt+1))

def process_alive(pid):
    if not pid: return False
    if os.name == 'nt':
        import ctypes
        k = ctypes.windll.kernel32
        k.OpenProcess.restype = ctypes.c_void_p
        handle = k.OpenProcess(0x100000, False, pid)
        if not handle: return False
        try: return k.WaitForSingleObject(ctypes.c_void_p(handle), 0) == 258
        finally: k.CloseHandle(ctypes.c_void_p(handle))
    try: os.kill(pid, 0); return True
    except ProcessLookupError: return False
    except PermissionError: return True

def kill_tree(child):
    if child.poll() is not None: return
    if os.name == 'nt':
        result = subprocess.run(['taskkill','/PID',str(child.pid),'/T','/F'], capture_output=True, timeout=12)
        if result.returncode and child.poll() is None: raise Halt('failed','Could not confirm process-tree termination.')
    else: os.killpg(child.pid, signal.SIGKILL)
    child.wait(timeout=12)

def state_path(project, run_id):
    if not re.fullmatch(r'RUN-[0-9]{8}-[0-9]{6}-[a-f0-9]{6}',run_id): raise ValueError('Invalid run ID.')
    return project / '.onecrew' / 'runs' / run_id / 'state.json'

def validate_artifacts(result, ownership):
    files = result.get('files')
    if not isinstance(files,list) or not files or len(files) > 5: raise ValueError('Expected 1–5 owned artifacts.')
    seen = set(); size = 0
    for item in files:
        if not isinstance(item,dict) or set(item) != {'path','content'}: raise ValueError('Invalid file schema.')
        path, content = item['path'], item['content']
        if path not in ownership or path in seen or not isinstance(content,str) or '\x00' in content: raise ValueError('Artifact violates ownership/path/type policy.')
        seen.add(path); size += len(content.encode('utf-8'))
    if size > 400000: raise ValueError('Artifact size exceeds profile budget.')
    if not isinstance(result.get('summary'),str) or not isinstance(result.get('backlog'),list): raise ValueError('Invalid artifact metadata.')
    return files

class Runner:
    def __init__(self, project, output, brief, limits, provider=None):
        self.project, self.output = Path(project).resolve(), Path(output).resolve()
        if self.output.exists(): raise ValueError('Output must be a new directory; existing work is never overwritten.')
        self.id = 'RUN-' + dt.datetime.now().strftime('%Y%m%d-%H%M%S-') + uuid.uuid4().hex[:6]
        self.root = state_path(self.project,self.id).parent
        self.root.mkdir(parents=True)
        self.output.mkdir(parents=True)
        self.provider = provider
        self.started = time.monotonic()
        self.command_count = 0
        self.sealed_files = [Path(__file__),Path(__file__).with_name('profiles.py'),Path(__file__).with_name('cv_gate.py')]
        self.seal = {str(p):digest(p.read_bytes()) for p in self.sealed_files}
        self.grant = {'brief':brief, 'profile':'cv-upload-v1','contract':CONTRACT,'policy':POLICY,
                      'limits':limits,'output':str(self.output),'autonomous':True,
                      'authority':'Explicit --autonomous local execution grant; not customer acceptance or deployment permission.'}
        save(self.root/'grant.json', self.grant)
        self.state = {'id':self.id,'created_at':now(),'status':'running','phase':'preflight','controller_pid':os.getpid(),
            'grant_hash':digest(canonical(self.grant)), 'gate_hashes':self.seal, 'output':str(self.output),
            'calls':0,'repairs':0,'limits':limits,'usage':{'input_tokens':0,'output_tokens':0,'cached_input_tokens':0},
            'cost_usd':None,'verification':'not_run','acceptance':'pending_user_review','checkpoints':[],
            'usage_pending_attempt':None,'usage_missing_attempts':[],
            'completed_tasks':[],'backlog':[], 'last_progress_at':None,'process':None}
        self.persist()

    def persist(self):
        self.state['updated_at']=now(); self.state['elapsed_seconds']=round(time.monotonic()-self.started,2)
        save(self.root/'state.json',self.state)

    def event(self, kind, **data):
        record={'at':now(),'kind':kind,**data}
        with (self.root/'events.jsonl').open('a',encoding='utf-8') as f: f.write(canonical(record)+'\n')
        print(canonical({'run':self.id,**record}), flush=True)
        self.persist()

    def check(self):
        if (self.root/'cancel.request').exists(): raise Halt('cancelled','Cancellation requested by user; active process stopped before terminal state.')
        if time.monotonic()-self.started >= self.state['limits']['seconds']: raise Halt('budget_exhausted','Total wall-clock budget exhausted.')
        if digest(canonical(json.loads((self.root/'grant.json').read_text(encoding='utf-8')))) != self.state['grant_hash']:
            raise Halt('failed','Execution grant changed during run.')
        if any(digest(p.read_bytes()) != self.seal[str(p)] for p in self.sealed_files): raise Halt('failed','Host gate/runtime changed during run; evidence invalidated.')

    def command(self, argv, cwd=None, stdin=None, timeout=30, env=None, cleanup=False):
        if not cleanup: self.check()
        self.command_count += 1
        prefix=self.root/f'command-{self.command_count:03}'
        save(prefix.with_suffix('.json'),{'argv':argv,'cwd':str(cwd or self.root),'timeout':timeout,'started_at':now()})
        with prefix.with_suffix('.stdout').open('wb') as out, prefix.with_suffix('.stderr').open('wb') as err:
            flags={'creationflags':subprocess.CREATE_NEW_PROCESS_GROUP} if os.name=='nt' else {'start_new_session':True}
            child=subprocess.Popen(argv,cwd=cwd or self.root,stdin=subprocess.PIPE if stdin is not None else subprocess.DEVNULL,
                stdout=out,stderr=err,env=env,**flags)
            self.state['process']={'pid':child.pid,'argv':argv,'started_at':now()}
            began=time.monotonic()
            try:
                self.persist()
                if stdin is not None: child.stdin.write(stdin.encode('utf-8')); child.stdin.close()
                while child.poll() is None:
                    if not cleanup: self.check()
                    if time.monotonic()-began>timeout: raise Halt('failed',f'Process timeout after {timeout}s: {Path(argv[0]).name}')
                    if prefix.with_suffix('.stdout').stat().st_size>16000000: raise Halt('failed','Process output exceeded 16MB cap.')
                    self.persist(); time.sleep(.25)
                if not cleanup: self.check()
            except BaseException:
                kill_tree(child); raise
            finally:
                self.state['process']=None; self.persist()
        stdout=prefix.with_suffix('.stdout').read_text(encoding='utf-8',errors='replace')
        stderr=prefix.with_suffix('.stderr').read_text(encoding='utf-8',errors='replace')
        save(prefix.with_suffix('.result.json'),{'exit_code':child.returncode,'seconds':round(time.monotonic()-began,2),'stdout':str(prefix.with_suffix('.stdout')),'stderr':str(prefix.with_suffix('.stderr'))})
        return child.returncode, stdout, stderr

    def invoke(self, stage, prompt, schema, risk='medium'):
        self.check()
        if len(prompt)>80000: raise Halt('failed','Context exceeds 80000-character cap; no model call dispatched.')
        if self.state['calls']>=self.state['limits']['calls']: raise Halt('budget_exhausted','Model call budget exhausted.')
        selection=route(stage,risk)
        self.state['calls']+=1; number=self.state['calls']; self.state['phase']=stage
        self.state['usage_pending_attempt']=number
        self.event('model_dispatched',attempt=number,**selection)
        attempt=self.root/f'attempt-{number:02}'; attempt.mkdir()
        save(attempt/'schema.json',schema)
        (attempt/'prompt.txt').write_text(prompt,encoding='utf-8')
        if self.provider:
            result=self.provider(stage,prompt,schema,selection)
            validate_schema(result,schema)
            self.state['usage_pending_attempt']=None; self.state['usage_missing_attempts'].append(number)
            save(attempt/'result.json',result); return result
        executable=shutil.which('codex')
        if not executable: raise Halt('blocked','Codex CLI unavailable.')
        args=[executable,'--no-daemon','-a','never','exec','--ignore-user-config','--ephemeral','--skip-git-repo-check',
              '--sandbox','read-only','--model',selection['model'],'-c',f'model_reasoning_effort="{selection["effort"]}"',
              '-c','web_search="disabled"','--disable','shell_tool','--disable','apps','--disable','plugins',
              '--disable','hooks','--disable','multi_agent','--json','--color','never',
              '--output-schema',str(attempt/'schema.json'),'-o',str(attempt/'result.json'),'-']
        code,out,err=self.command(args,stdin=prompt,timeout=self.state['limits']['step_seconds'])
        usage=[]; forbidden=[]
        for line in out.splitlines():
            try: event=json.loads(line)
            except ValueError: continue
            if event.get('type')=='turn.completed': usage.append(event.get('usage',{}))
            item=event.get('item',{})
            if item.get('type') not in (None,'agent_message','reasoning'): forbidden.append(item.get('type'))
        for item in usage:
            for key in self.state['usage']: self.state['usage'][key]+=int(item.get(key,0))
        self.state['usage_pending_attempt']=None
        if not usage:self.state['usage_missing_attempts'].append(number)
        save(attempt/'usage.json',usage); self.persist()
        if forbidden: raise Halt('failed',f'Worker attempted tools outside artifact contract: {sorted(set(forbidden))}')
        if code or not (attempt/'result.json').exists(): raise Halt('blocked',f'Provider call {number} failed; see command logs. No automatic provider retries.')
        if (attempt/'result.json').stat().st_size>1000000: raise Halt('failed','Structured response exceeds 1MB cap.')
        try: result=json.loads((attempt/'result.json').read_text(encoding='utf-8'))
        except (ValueError,UnicodeError): raise Halt('failed','Provider output is not valid structured JSON.')
        validate_schema(result,schema)
        self.event('model_completed',attempt=number,usage=usage)
        return result

    def context(self):
        return '\n'.join(f'FILE {p}\n{(self.output/p).read_text(encoding="utf-8")}' for p in sorted(ALLOWED) if (self.output/p).is_file())

    def apply(self, result, ownership, label):
        files=validate_artifacts(result,ownership)
        self.check()
        for item in files:
            target=self.output/item['path']
            if not target.resolve().is_relative_to(self.output) or target.is_symlink(): raise Halt('failed','Output path escaped project.')
            target.parent.mkdir(parents=True,exist_ok=True)
            target.write_text(item['content'],encoding='utf-8')
        self.state['backlog'].extend(str(x)[:1000] for x in result['backlog'][:10])
        self.state['verification']='stale' if self.state['verification']=='passed' else self.state['verification']
        self.checkpoint(label,result['summary'])

    def manifest(self):
        return {p:digest((self.output/p).read_bytes()) for p in sorted(ALLOWED | {'package.json','.gitattributes','.gitignore'}) if (self.output/p).is_file()}

    def checkpoint(self,label,summary):
        manifest=self.manifest(); revision=digest(canonical(manifest)); index=len(self.state['checkpoints'])+1
        path=self.root/f'output-{index:02}.zip'
        with zipfile.ZipFile(path,'x',zipfile.ZIP_DEFLATED) as z:
            for p in manifest: z.write(self.output/p,p)
        record={'id':f'output-{index:02}','label':label,'summary':summary,'revision':revision,'manifest':manifest,'archive':str(path),'at':now()}
        save(self.root/f'output-{index:02}.json',record)
        self.state['checkpoints'].append(record); self.state['last_progress_at']=now(); self.event('checkpoint',label=label,revision=revision)

    def execute(self):
        try:
            from .cv_gate import DockerGate,WindowsGate
            gate=WindowsGate(self) if os.name=='nt' and not self.provider else DockerGate(self)
            gate.preflight()
            self.check()
            plan=self.invoke('plan','You are OneCrew Conductor. No tools. Return only schema JSON. Create exactly two tasks backend/frontend with dependencies and risk, covering every fixed acceptance ID. Brief in Vietnamese <=180 words. Do not expand scope.\nUSER BRIEF\n'+self.grant['brief']+'\nFIXED CONTRACT\n'+CONTRACT,PLAN_SCHEMA)
            tasks=validate_plan(plan); save(self.root/'plan.json',plan)
            if len(plan['brief'].split())>200 or len(plan['title'])>160: raise ValueError('Conductor brief/title exceeds readable limit.')
            spec=f'# {plan["title"]}\n\n## Duyệt nhanh\n{plan["brief"]}\n\n## Không làm\n'+ '\n'.join('- '+x for x in plan['non_goals'])+'\n\n## Chi tiết và nghiệm thu đã khóa\n'+CONTRACT
            (self.root/'spec.md').write_text(spec,encoding='utf-8')
            save(self.output/'package.json',{'name':'onecrew-cv-autonomous','private':True,'version':'0.1.0','type':'module','scripts':{'start':'node server.mjs'},'engines':{'node':'>=24'}})
            (self.output/'.gitattributes').write_text('* text=auto eol=lf\n',encoding='utf-8')
            (self.output/'.gitignore').write_text('.data*/\n.env*\n',encoding='utf-8')
            for task in tasks:
                prompt='You are a OneCrew implementation worker. NO TOOLS. Return complete file contents in schema JSON, no markdown fences. Only files owned below. Implement all requirements for your part, not placeholders. Keep code concise. Use only supplied context.\nCONTRACT\n'+CONTRACT+'\nUSER BRIEF\n'+self.grant['brief']+'\nTASK\n'+canonical(task)+'\nOWNED FILES\n'+canonical(FILES[task['kind']])+'\nCURRENT ARTIFACTS\n'+self.context()
                result=self.invoke(task['kind'],prompt,ARTIFACT_SCHEMA,task['risk'])
                self.apply(result,FILES[task['kind']],task['id']); self.state['completed_tasks'].append(task['id']); self.persist()
            last_failure=None
            while True:
                self.check(); self.state['phase']='verify'; self.state['verification']='running'; self.event('gate_started')
                before=self.manifest()
                missing=ALLOWED-set(before)
                result=({'passed':False,'checks':[],'failures':[{'requirement':'CV-DOC' if p=='README.md' else 'CV-UI','error':'Required artifact missing: '+p} for p in sorted(missing)]} if missing else gate.verify())
                if self.manifest()!=before: raise Halt('failed','Product code changed while gate was running.')
                save(self.root/f'gate-{self.state["repairs"]:02}.json',{'manifest':before,'result':result,'gate_hash':self.seal[str(Path(__file__).with_name('cv_gate.py'))]})
                self.state['verification']='passed' if result['passed'] else 'failed'; self.event('gate_completed',**result)
                failures=result['failures']
                if result['passed']:
                    review=self.invoke('review','Independent review. NO TOOLS. Evaluate only supplied code against fixed AC. Blocking findings must reference an exact acceptance ID and evidence. Suggestions/out-of-scope become backlog, not mandatory work. Do not assume live Turnstile/AV/edge exists: these are explicit external gates. Return empty findings if code meets the local contract.\nCONTRACT\n'+CONTRACT+'\nGATE\n'+canonical(result)+'\nSOURCE\n'+self.context(),REVIEW_SCHEMA,'high')
                    save(self.root/f'review-{self.state["repairs"]:02}.json',review)
                    if self.manifest()!=before: raise Halt('failed','Artifacts changed during semantic review; verification is stale.')
                    if not isinstance(review.get('findings'),list): raise Halt('failed','Invalid review schema.')
                    failures=[]
                    for finding in review['findings']:
                        if finding.get('severity')=='blocking' and finding.get('requirement') in AC and finding.get('evidence'):
                            failures.append(finding)
                        else: self.state['backlog'].append(finding)
                    if not failures: break
                failure_key=digest(canonical({'manifest':self.manifest(),'failures':failures}))
                if failure_key==last_failure: raise Halt('failed','No progress: same artifacts and failures repeated.')
                last_failure=failure_key
                if self.state['repairs']>=self.state['limits']['repairs']: raise Halt('failed','Repair budget exhausted; mandatory findings remain.')
                self.state['repairs']+=1; self.persist()
                repair=self.invoke('repair','Repair only listed acceptance failures. NO TOOLS. Return complete contents ONLY of changed owned files. Never change contract, gates, package, policy or budget. Do not add features.\nCONTRACT\n'+CONTRACT+'\nFAILURES\n'+canonical(failures)+'\nOWNED\n'+canonical(sorted(ALLOWED))+'\nSOURCE\n'+self.context(),ARTIFACT_SCHEMA,'high')
                self.apply(repair,ALLOWED,f'repair-{self.state["repairs"]}')
            self.check(); self.state['phase']='delivery'
            if self.manifest()!=before: raise Halt('failed','Artifacts changed before delivery.')
            for argv in (['git','init','-b','main'],['git','add','--',*sorted(self.manifest())],['git','-c','core.hooksPath='+str(self.root/'no-hooks'),'-c','commit.gpgsign=false','commit','-m','feat: deliver CV form generated autonomously by OneCrew']):
                code,out,err=self.command(argv,cwd=self.output)
                if code: raise Halt('failed','Delivery git command failed: '+err[-600:])
            code,commit,err=self.command(['git','rev-parse','HEAD'],cwd=self.output)
            if code: raise Halt('failed','Cannot record delivery commit.')
            if self.manifest()!=before: raise Halt('failed','Artifacts changed during delivery.')
            self.state.update(status='ready_for_review',phase='delivered',commit=commit.strip(),verification='passed',output_revision=digest(canonical(self.manifest())),
                external_blockers=['Live Turnstile/domain/edge not configured or verified','AV and operational retention not deployed','Human/agent efficacy benchmark not performed'])
            save(self.root/'delivery.json',{'run':self.id,'commit':commit.strip(),'manifest':self.manifest(),'acceptance':'pending_user_review','external_blockers':self.state['external_blockers'],'source_authorship':'Model artifacts applied by OneCrew only; host owns contract, gate and orchestration.'})
            self.event('delivered',commit=commit.strip(),output=str(self.output))
        except Halt as error:
            self.state.update(status=error.status,reason=str(error)); self.event('stopped',status=error.status,reason=str(error))
        except (ValueError,KeyError,TypeError,OSError,subprocess.SubprocessError) as error:
            self.state.update(status='failed',reason=f'{type(error).__name__}: {error}'); self.event('stopped',status='failed',reason=self.state['reason'])
        except KeyboardInterrupt:
            self.state.update(status='cancelled',reason='Controller interrupted'); self.event('stopped',status='cancelled')
        finally:
            if self.state['usage_pending_attempt'] is not None:
                self.state['usage_missing_attempts'].append(self.state['usage_pending_attempt'])
                self.state['usage_pending_attempt']=None
            if self.state['verification']=='running':self.state['verification']='unknown'
            self.state['finished_at']=now(); self.persist()
        return self.state

def main(argv=None):
    if hasattr(sys.stdout,'reconfigure'): sys.stdout.reconfigure(encoding='utf-8')
    parser=argparse.ArgumentParser(prog='onecrew')
    parser.add_argument('--project',type=Path,default=Path.cwd())
    group=parser.add_subparsers(dest='group',required=True).add_parser('task')
    commands=group.add_subparsers(dest='command',required=True)
    run=commands.add_parser('run'); run.add_argument('--brief',type=Path,required=True); run.add_argument('--output',type=Path,required=True)
    run.add_argument('--profile',choices=['cv-upload'],default='cv-upload'); run.add_argument('--autonomous',action='store_true',required=True)
    run.add_argument('--max-seconds',type=int,default=1200); run.add_argument('--max-calls',type=int,default=8); run.add_argument('--max-repairs',type=int,default=2)
    run.add_argument('--step-seconds',type=int,default=240)
    commands.add_parser('list')
    for name in ('status','cancel','outputs'): commands.add_parser(name).add_argument('id')
    args=parser.parse_args(argv)
    try:
        project=args.project.resolve()
        if args.command=='run':
            if not 1<=args.max_calls<=20 or not 1<=args.max_seconds<=3600 or not 0<=args.max_repairs<=4 or not 1<=args.step_seconds<=min(600,args.max_seconds): raise ValueError('Invalid bounded budget.')
            brief=args.brief.read_text(encoding='utf-8')
            if not brief.strip() or len(brief)>12000: raise ValueError('Brief must contain 1–12000 characters.')
            result=Runner(project,args.output,brief,{'seconds':args.max_seconds,'calls':args.max_calls,'repairs':args.max_repairs,'step_seconds':args.step_seconds}).execute()
            print(json.dumps(result,ensure_ascii=False,indent=2)); return 0 if result['status']=='ready_for_review' else 2
        if args.command=='list':
            rows=[json.loads(p.read_text(encoding='utf-8')) for p in sorted((project/'.onecrew'/'runs').glob('RUN-*/state.json'))]
            print(json.dumps([{k:r.get(k) for k in ('id','status','phase','calls','repairs','output')} for r in rows],ensure_ascii=False,indent=2)); return 0
        path=state_path(project,args.id); state=json.loads(path.read_text(encoding='utf-8'))
        if args.command=='cancel':
            if state['status'] not in TERMINAL:
                (path.parent/'cancel.request').write_text(now(),encoding='utf-8')
                print('cancel_requested; use task status to confirm process termination.'); return 0
            print('Run already terminal: '+state['status']); return 0
        if args.command=='outputs': state=state['checkpoints']
        elif state['status'] not in TERMINAL and not process_alive(state.get('controller_pid')):
            state={**state,'observed_status':'interrupted','note':'Controller is absent. No automatic retry/replay or new budget; inspect processes/container labels before recovery.'}
        print(json.dumps(state,ensure_ascii=False,indent=2)); return 0
    except (ValueError,OSError,KeyError) as error:
        print(f'Cannot execute: {error}',file=sys.stderr); return 2
